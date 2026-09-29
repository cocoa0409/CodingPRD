"""Portability, roaming and in-motion authorisation (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint

import capacity
import licensing
import serialize
from auth import own_roaming, own_subscription, roles
from constants import (
    API_PREFIX,
    ROAMING_COOLDOWN_HOURS,
    ROAMING_DECISIONS,
    ROAMING_MAX_INFO_ROUNDS,
    ROAMING_MODES,
    ROAMING_STATES,
)
from db import db, new_record, ordered, touch
from errors import fail
from response import list_response, object_response
from validators import (
    body_dict,
    filter_enum,
    filter_value,
    opt_str,
    pagination,
    paginate,
    reject_field,
    req_dt,
    req_enum,
    req_jurisdiction,
    req_str,
)

bp = Blueprint("roaming", __name__, url_prefix=API_PREFIX)


def find_roaming(roaming_id):
    record = db.roaming.get(roaming_id)
    if record is None:
        fail("ERR_ROAMING_AUTHORIZATION_NOT_FOUND", "Roaming authorisation not found.")
    return record


def _window(body):
    """`effective_from` / `effective_until`, the latter strictly later."""
    effective_from = req_dt(body, "effective_from")
    effective_until = req_dt(body, "effective_until")
    if effective_until <= effective_from:
        fail(
            "ERR_INVALID_REQUEST",
            "'effective_until' must be strictly later than 'effective_from'.",
        )
    return effective_from, effective_until


def _assert_window_free(subscription_id, effective_from, effective_until, exclude_id=None):
    """Overlap with, or landing inside the cooldown after, an approved window."""
    cooldown = timedelta(hours=ROAMING_COOLDOWN_HOURS)
    for other in ordered(list(db.roaming.values())):
        if other["subscription_id"] != subscription_id:
            continue
        if other["id"] == exclude_id or other["auth_state"] != "APPROVED":
            continue
        # closed intervals overlapping at all
        if effective_from <= other["effective_until"] and effective_until >= other["effective_from"]:
            fail(
                "ERR_ROAMING_WINDOW_CONFLICT",
                "The requested window overlaps an approved window.",
            )
        # the cooldown buffer, exclusive at its far edge
        if effective_from < other["effective_until"] + cooldown:
            fail(
                "ERR_ROAMING_WINDOW_CONFLICT",
                "The requested window starts inside an approved window's cooldown.",
            )


# ------------------------------------------------------------------ requests ---

@bp.post("/roaming-authorizations")
@roles("Subscriber", "ProvisioningAgent")
def request_roaming():
    body = body_dict()

    raw_subscription_id = body.get("subscription_id")
    if isinstance(raw_subscription_id, str):
        own_subscription(raw_subscription_id)

    subscription_id = req_str(body, "subscription_id", 1, 100)
    mode = req_enum(body, "mode", ROAMING_MODES)
    target_jurisdiction_code = req_jurisdiction(body, "target_jurisdiction_code")
    if mode == "PORTABILITY_MOVE":
        target_cell_id = req_str(body, "target_service_cell_id", 1, 100)
    else:
        reject_field(
            body,
            "target_service_cell_id",
            "'target_service_cell_id' is only accepted when mode is PORTABILITY_MOVE.",
        )
        target_cell_id = None
    effective_from, effective_until = _window(body)

    subscription = db.subscriptions.get(subscription_id)
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found.")
    if target_cell_id is not None and target_cell_id not in db.cells:
        fail("ERR_SERVICE_CELL_NOT_FOUND", "Service cell not found.")

    if target_cell_id is not None and target_cell_id == subscription["service_cell_id"]:
        fail(
            "ERR_PORTABILITY_TARGET_INVALID",
            "A portability move must name a different coverage cell.",
        )
    if subscription["service_state"] == "TERMINATED":
        fail(
            "ERR_PORTABILITY_TARGET_INVALID",
            "The named subscription is TERMINATED.",
        )

    plan = capacity.plan_of_subscription(subscription)
    if mode == "IN_MOTION" and not (plan and plan["in_motion_allowed"]):
        fail(
            "ERR_IN_MOTION_NOT_PERMITTED",
            "The subscription's plan does not permit in-motion operation.",
        )
    if mode in ("PORTABILITY_MOVE", "ROAM_TEMPORARY") and not (
        plan and plan["roaming_allowed"]
    ):
        fail(
            "ERR_ROAMING_NOT_PERMITTED",
            "The subscription's plan does not permit roaming.",
        )

    _assert_window_free(subscription["id"], effective_from, effective_until)

    record = new_record()
    record.update(
        {
            "subscription_id": subscription["id"],
            "mode": mode,
            "target_jurisdiction_code": target_jurisdiction_code,
            "target_service_cell_id": target_cell_id,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "auth_state": "REQUESTED",
            "info_round_count": 0,
            "governing_license_id": None,
            "decision_note": None,
            "revoked_reason": None,
        }
    )
    db.roaming[record["id"]] = record
    return object_response(serialize.roaming_authorization(record), 201)


@bp.get("/roaming-authorizations/<roaming_id>")
@roles("Subscriber", "ProvisioningAgent", "ComplianceOfficer")
def read_roaming(roaming_id):
    own_roaming(roaming_id)
    return object_response(serialize.roaming_authorization(find_roaming(roaming_id)))


@bp.get("/roaming-authorizations")
@roles("Subscriber", "ProvisioningAgent", "ComplianceOfficer")
def list_roaming():
    limit, offset = pagination()
    subscription_id = filter_value("subscription_id")
    auth_state = filter_enum("auth_state", ROAMING_STATES)
    mode = filter_enum("mode", ROAMING_MODES)
    target_cell_id = filter_value("target_service_cell_id")
    governing_license_id = filter_value("governing_license_id")

    records = ordered(list(db.roaming.values()))
    if subscription_id is not None:
        records = [r for r in records if r["subscription_id"] == subscription_id]
    if auth_state is not None:
        records = [r for r in records if r["auth_state"] == auth_state]
    if mode is not None:
        records = [r for r in records if r["mode"] == mode]
    if target_cell_id is not None:
        records = [r for r in records if r["target_service_cell_id"] == target_cell_id]
    if governing_license_id is not None:
        records = [
            r for r in records if r["governing_license_id"] == governing_license_id
        ]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.roaming_authorization),
        limit,
        offset,
        len(records),
    )


# -------------------------------------------------------------------- review ---

@bp.post("/roaming-authorizations/<roaming_id>/request-info")
@roles("ComplianceOfficer")
def request_info(roaming_id):
    body = body_dict()
    note = req_str(body, "info_request_note", 1, 1000)

    record = find_roaming(roaming_id)
    if record["auth_state"] != "REQUESTED":
        fail(
            "ERR_ROAMING_STATE_INVALID",
            "A further information round is only legal from REQUESTED.",
        )
    if record["info_round_count"] >= ROAMING_MAX_INFO_ROUNDS:
        fail("ERR_ROAMING_ROUND_LIMIT", "The information-round cap has been reached.")

    record["auth_state"] = "NEEDS_INFO"
    record["info_round_count"] += 1
    record["decision_note"] = note
    touch(record)
    return object_response(serialize.roaming_authorization(record))


@bp.post("/roaming-authorizations/<roaming_id>/resubmit")
@roles("Subscriber", "ProvisioningAgent")
def resubmit_roaming(roaming_id):
    own_roaming(roaming_id)
    body = body_dict()
    effective_from, effective_until = _window(body)

    record = find_roaming(roaming_id)
    if record["auth_state"] != "NEEDS_INFO":
        fail("ERR_ROAMING_STATE_INVALID", "Resubmission is only legal from NEEDS_INFO.")

    _assert_window_free(
        record["subscription_id"], effective_from, effective_until, exclude_id=record["id"]
    )

    record["effective_from"] = effective_from
    record["effective_until"] = effective_until
    record["auth_state"] = "REQUESTED"
    touch(record)
    return object_response(serialize.roaming_authorization(record))


@bp.post("/roaming-authorizations/<roaming_id>/decide")
@roles("ComplianceOfficer")
def decide_roaming(roaming_id):
    body = body_dict()
    decision = req_enum(body, "decision", ROAMING_DECISIONS)
    decision_note = opt_str(body, "decision_note", 1, 1000)

    record = find_roaming(roaming_id)
    if record["auth_state"] != "REQUESTED":
        fail("ERR_ROAMING_STATE_INVALID", "A decision is only legal from REQUESTED.")

    if decision == "DENY":
        record["auth_state"] = "DENIED"
        record["decision_note"] = decision_note
        touch(record)
        return object_response(serialize.roaming_authorization(record))

    subscription = db.subscriptions.get(record["subscription_id"])
    if subscription is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found.")
    if subscription["service_state"] == "TERMINATED":
        fail(
            "ERR_PORTABILITY_TARGET_INVALID",
            "The authorisation's subscription is TERMINATED.",
        )
    if (
        record["mode"] == "PORTABILITY_MOVE"
        and record["target_service_cell_id"] == subscription["service_cell_id"]
    ):
        fail(
            "ERR_PORTABILITY_TARGET_INVALID",
            "A portability move must name a different coverage cell.",
        )

    # The governing licence is searched for, never inferred from a beam.
    license_record = licensing.select_governing_license(
        record["target_jurisdiction_code"]
    )
    if license_record is None:
        fail(
            "ERR_JURISDICTION_NOT_PERMITTED",
            "No live, coordinated licence covers the target jurisdiction.",
        )

    plan = capacity.plan_of_subscription(subscription)
    if record["mode"] == "IN_MOTION" and not (
        license_record["in_motion_permitted"] and plan and plan["in_motion_allowed"]
    ):
        fail(
            "ERR_IN_MOTION_NOT_PERMITTED",
            "In-motion operation is not permitted by the licence or the plan.",
        )

    target_cell = None
    if record["mode"] == "PORTABILITY_MOVE":
        target_cell = db.cells.get(record["target_service_cell_id"])
        if target_cell is None:
            fail("ERR_SERVICE_CELL_NOT_FOUND", "Service cell not found.")
        if capacity.admission_free(target_cell) < 1:
            fail("ERR_CELL_CAPACITY_EXHAUSTED", "The target cell has no free slot.")

    beam = capacity.beam_of_subscription(subscription)
    if beam is None or beam["beam_state"] != "ACTIVE":
        fail("ERR_BEAM_SUSPENDED", "The governing beam is out of service.")

    record["auth_state"] = "APPROVED"
    record["decision_note"] = decision_note
    record["governing_license_id"] = license_record["id"]
    touch(record)

    if record["mode"] == "IN_MOTION":
        if subscription["authorization_state"] == "AUTHORIZED_FIXED":
            subscription["authorization_state"] = "AUTHORIZED_IN_MOTION"
            touch(subscription)
    elif record["mode"] == "PORTABILITY_MOVE":
        vacated_cell = capacity.cell_of_subscription(subscription)
        subscription["service_cell_id"] = target_cell["id"]
        touch(subscription)

        if vacated_cell is not None:
            touch(vacated_cell)
            capacity.run_promotion(vacated_cell)
        touch(target_cell)

        capacity.recompute_beam(capacity.beam_of_cell(vacated_cell) if vacated_cell else None)
        capacity.recompute_beam(capacity.beam_of_cell(target_cell))

    return object_response(serialize.roaming_authorization(record))
