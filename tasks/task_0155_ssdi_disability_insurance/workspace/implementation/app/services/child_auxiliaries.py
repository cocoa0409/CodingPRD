"""ChildAuxiliary: create, entitle, terminate, list."""

from __future__ import annotations

from datetime import date
from typing import Optional

from app import clock, store
from app.calculations import child_aux_waterfall
from app.errors import (
    application_not_found,
    bad_request,
    child_ineligible,
    invalid_state,
    resource_not_found,
)
from app.util import floor_age_years, new_uuid, parse_iso_date


_VALID_RELATIONSHIP = {"BIOLOGICAL", "ADOPTED", "STEPCHILD", "DEPENDENT_GRANDCHILD"}
_VALID_TERMINATION = {"AGE_OUT", "NO_LONGER_DISABLED", "PARENT_BENEFIT_ENDED"}


def create_child(body: dict) -> dict:
    for f in ("application_id", "child_name", "child_date_of_birth", "child_relationship"):
        if f not in body or body[f] is None:
            raise bad_request(f"Missing required field: {f}")

    app_id = body["application_id"]
    application = store.applications.get(app_id)
    if not application:
        raise application_not_found(f"Application {app_id} not found")

    child_name = body["child_name"]
    if not isinstance(child_name, str) or not child_name.strip():
        raise bad_request("child_name must be a non-empty string")

    dob = parse_iso_date(body["child_date_of_birth"], "child_date_of_birth")
    relationship = body["child_relationship"]
    if relationship not in _VALID_RELATIONSHIP:
        raise bad_request(f"child_relationship must be one of {sorted(_VALID_RELATIONSHIP)}")

    is_student = body.get("is_full_time_student")
    if is_student is not None and not isinstance(is_student, bool):
        raise bad_request("is_full_time_student must be a boolean")
    is_dac = body.get("is_disabled_before_22")
    if is_dac is not None and not isinstance(is_dac, bool):
        raise bad_request("is_disabled_before_22 must be a boolean")

    now = clock.now()
    new_id = new_uuid()
    record = {
        "id": new_id,
        "application_id": app_id,
        "child_name": child_name.strip(),
        "child_date_of_birth": dob,
        "child_relationship": relationship,
        "is_full_time_student": bool(is_student) if is_student is not None else False,
        "is_disabled_before_22": bool(is_dac) if is_dac is not None else False,
        "status": "PENDING",
        "termination_reason": None,
        "monthly_benefit_cents": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock():
        store.child_auxiliaries[new_id] = record
    return record


def _fetch_child(child_id: str) -> dict:
    c = store.child_auxiliaries.get(child_id)
    if not c:
        raise resource_not_found(f"ChildAuxiliary {child_id} not found")
    return c


def entitle_child(child_id: str) -> dict:
    with store.lock():
        child = _fetch_child(child_id)
        if child["status"] != "PENDING":
            raise invalid_state(f"ChildAuxiliary in status {child['status']} cannot be entitled")

        app = store.applications.get(child["application_id"])
        if not app:
            raise application_not_found(f"Application {child['application_id']} not found")
        if app["status"] not in ("APPROVED", "ALJ_APPROVED"):
            raise invalid_state(
                f"Parent application must be APPROVED or ALJ_APPROVED; current is {app['status']}"
            )

        # Eligibility: age check, student-aged-18, or disabled-before-22.
        now = clock.now()
        if isinstance(now, type(child["child_date_of_birth"])):
            ref_date = now
        else:
            ref_date = now.date()
        age = floor_age_years(ref_date, child["child_date_of_birth"])
        eligible = False
        if age < 18:
            eligible = True
        elif 18 <= age < 19 and child.get("is_full_time_student"):
            eligible = True
        elif child.get("is_disabled_before_22"):
            eligible = True
        if not eligible:
            raise child_ineligible("Child does not meet age/student/disabled-before-22 rules")

        child["status"] = "ENTITLED"
        child["updated_at"] = clock.now()
        child["version"] += 1

        _recompute_family_waterfall(app)
    return child


def terminate_child(child_id: str, body: dict) -> dict:
    reason = body.get("termination_reason")
    if reason not in _VALID_TERMINATION:
        raise bad_request(f"termination_reason must be one of {sorted(_VALID_TERMINATION)}")

    with store.lock():
        child = _fetch_child(child_id)
        if child["status"] != "ENTITLED":
            raise invalid_state(f"ChildAuxiliary in status {child['status']} cannot be terminated")
        child["status"] = "TERMINATED"
        child["termination_reason"] = reason
        child["monthly_benefit_cents"] = 0
        child["updated_at"] = clock.now()
        child["version"] += 1

        app = store.applications.get(child["application_id"])
        if app:
            _recompute_family_waterfall(app)
    return child


def _recompute_family_waterfall(application: dict) -> None:
    entitled = [
        c for c in store.child_auxiliaries.values()
        if c["application_id"] == application["id"] and c["status"] == "ENTITLED"
    ]
    pia = application.get("pia_cents") or 0
    fmb = application.get("family_max_cents") or 0
    allocations = child_aux_waterfall(pia, fmb, entitled)
    now = clock.now()
    for child in entitled:
        new_amount = allocations.get(child["id"], 0)
        if child.get("monthly_benefit_cents") != new_amount:
            child["monthly_benefit_cents"] = new_amount
            child["updated_at"] = now
            child["version"] += 1


def list_children(application_id: Optional[str], status: Optional[str]) -> list[dict]:
    rows = list(store.child_auxiliaries.values())
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows
