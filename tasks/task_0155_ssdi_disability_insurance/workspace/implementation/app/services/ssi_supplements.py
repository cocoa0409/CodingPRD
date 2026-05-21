"""SSISupplement: create, activate, patch, recompute on DIB loss."""

from __future__ import annotations

from app import clock, store
from app.calculations import SSI_RESOURCE_LIMIT_CENTS, ssi_calc
from app.errors import (
    bad_request,
    claimant_not_found,
    invalid_state,
    resource_not_found,
    ssi_resources_exceeded,
    version_mismatch,
)
from app.util import new_uuid


_VALID_LIVING = {"OWN_HOUSEHOLD", "ANOTHER_HOUSEHOLD", "INSTITUTION"}


def create_supplement(body: dict) -> dict:
    for f in ("claimant_id", "countable_income_cents", "countable_resources_cents", "living_arrangement"):
        if f not in body or body[f] is None:
            raise bad_request(f"Missing required field: {f}")

    claimant_id = body["claimant_id"]
    if claimant_id not in store.claimants:
        raise claimant_not_found(f"Claimant {claimant_id} not found")

    income = body["countable_income_cents"]
    resources = body["countable_resources_cents"]
    if isinstance(income, bool) or not isinstance(income, int) or income < 0:
        raise bad_request("countable_income_cents must be a non-negative integer")
    if isinstance(resources, bool) or not isinstance(resources, int) or resources < 0:
        raise bad_request("countable_resources_cents must be a non-negative integer")
    arrangement = body["living_arrangement"]
    if arrangement not in _VALID_LIVING:
        raise bad_request(f"living_arrangement must be one of {sorted(_VALID_LIVING)}")

    now = clock.now()
    new_id = new_uuid()
    record = {
        "id": new_id,
        "claimant_id": claimant_id,
        "countable_income_cents": income,
        "countable_resources_cents": resources,
        "living_arrangement": arrangement,
        "ssi_payment_cents": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock():
        store.ssi_supplements[new_id] = record
    return record


def _fetch(supplement_id: str) -> dict:
    s = store.ssi_supplements.get(supplement_id)
    if not s:
        raise resource_not_found(f"SSISupplement {supplement_id} not found")
    return s


def _has_live_dib(claimant_id: str) -> bool:
    """A live DIB benefit is an Application in APPROVED or ALJ_APPROVED for this claimant."""
    for app in store.applications.values():
        if app["claimant_id"] == claimant_id and app["status"] in ("APPROVED", "ALJ_APPROVED"):
            return True
    return False


def activate_supplement(supplement_id: str) -> dict:
    with store.lock():
        s = _fetch(supplement_id)
        if s["status"] != "DRAFT":
            raise invalid_state(f"SSISupplement in status {s['status']} cannot be activated")
        if s["countable_resources_cents"] > SSI_RESOURCE_LIMIT_CENTS:
            raise ssi_resources_exceeded(
                f"countable_resources_cents {s['countable_resources_cents']} exceeds limit {SSI_RESOURCE_LIMIT_CENTS}"
            )

        payment = ssi_calc(s["countable_income_cents"], s["living_arrangement"])
        s["ssi_payment_cents"] = payment
        if payment == 0 and _has_live_dib(s["claimant_id"]):
            s["status"] = "TERMINATED_DIB_OFFSET"
        else:
            s["status"] = "ACTIVE"
        s["updated_at"] = clock.now()
        s["version"] += 1
    return s


def patch_supplement(supplement_id: str, body: dict) -> dict:
    with store.lock():
        s = _fetch(supplement_id)
        if "version" in body and body["version"] is not None:
            if not isinstance(body["version"], int) or isinstance(body["version"], bool):
                raise bad_request("version must be an integer")
            if body["version"] != s["version"]:
                raise version_mismatch(
                    f"Stored version {s['version']} does not match supplied {body['version']}"
                )

        if "countable_income_cents" in body and body["countable_income_cents"] is not None:
            v = body["countable_income_cents"]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise bad_request("countable_income_cents must be a non-negative integer")
            s["countable_income_cents"] = v
        if "countable_resources_cents" in body and body["countable_resources_cents"] is not None:
            v = body["countable_resources_cents"]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise bad_request("countable_resources_cents must be a non-negative integer")
            s["countable_resources_cents"] = v
        if "living_arrangement" in body and body["living_arrangement"] is not None:
            v = body["living_arrangement"]
            if v not in _VALID_LIVING:
                raise bad_request(f"living_arrangement must be one of {sorted(_VALID_LIVING)}")
            s["living_arrangement"] = v

        # If currently ACTIVE, re-run calc and possibly transition.
        if s["status"] == "ACTIVE":
            if s["countable_resources_cents"] > SSI_RESOURCE_LIMIT_CENTS:
                s["status"] = "TERMINATED_RESOURCES"
                s["ssi_payment_cents"] = 0
            else:
                new_payment = ssi_calc(s["countable_income_cents"], s["living_arrangement"])
                if new_payment == 0:
                    s["status"] = "TERMINATED_INCOME"
                s["ssi_payment_cents"] = new_payment

        s["updated_at"] = clock.now()
        s["version"] += 1
    return s


def recompute_after_dib_loss(claimant_id: str) -> None:
    """Called by the cessation cascade — supplements suppressed by DIB may revive."""
    if _has_live_dib(claimant_id):
        return   # DIB still live (shouldn't happen mid-cascade, defensive)
    now = clock.now()
    for s in store.ssi_supplements.values():
        if s["claimant_id"] != claimant_id:
            continue
        if s["status"] != "TERMINATED_DIB_OFFSET":
            continue
        if s["countable_resources_cents"] > SSI_RESOURCE_LIMIT_CENTS:
            s["status"] = "TERMINATED_RESOURCES"
            s["ssi_payment_cents"] = 0
        else:
            new_payment = ssi_calc(s["countable_income_cents"], s["living_arrangement"])
            if new_payment > 0:
                s["status"] = "ACTIVE"
                s["ssi_payment_cents"] = new_payment
            else:
                s["status"] = "TERMINATED_INCOME"
                s["ssi_payment_cents"] = 0
        s["updated_at"] = now
        s["version"] += 1
