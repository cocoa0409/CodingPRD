"""Carrier registration and the two independent status axes (PRD 3.1)."""

from flask import Blueprint

from db import base_record, by_created, db, now, touch
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    ROLE_PORTING,
    body,
    check_action_role,
    opt_bool,
    opt_dt,
    opt_int,
    opt_str,
    req_dt,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import OCN_PATTERN, STATE_PATTERN, field, filter_rows
from services import constants as C
from services import core, serialize, workflows

bp = Blueprint("carriers", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_PORTING)

READINESS_ACTION_ROLES = {
    "ATTEST": (ROLE_CARRIER,),
    "VERIFY": (ROLE_ADMIN,),
    "FAIL": (ROLE_ADMIN,),
}


@bp.route("/numbering/carriers", methods=["POST"])
def create_carrier():
    require_roles(ROLE_ADMIN)
    payload = body()
    ocn = req_str(payload, "ocn", 4, 4, OCN_PATTERN)
    legal_name = req_str(payload, "legal_name", 1, 120)
    carrier_type = req_enum(payload, "carrier_type", C.CARRIER_TYPES)
    home_state_code = req_str(payload, "home_state_code", 2, 2, STATE_PATTERN)
    months = opt_int(payload, "months_in_operation", 0, None, 0)

    for existing in db.carriers.values():
        if existing["ocn"] == ocn:
            fail("ERR_DUPLICATE_OCN", "ocn %s is already registered" % ocn)

    record = base_record(
        ocn=ocn,
        legal_name=legal_name,
        carrier_type=carrier_type,
        home_state_code=home_state_code,
        months_in_operation=months,
        license_status="NONE",
        license_expires_on=None,
        facilities_readiness_status="NOT_SUBMITTED",
        switch_clli=None,
        interconnection_ready=False,
        reclamation_strike_count=0,
        safety_valve_grant_count=0,
        probation_until=None,
    )
    db.carriers[record["id"]] = record
    return object_response(serialize.carrier(record), 201)


@bp.route("/numbering/carriers", methods=["GET"])
def list_carriers():
    require_roles(*READERS)
    rows = by_created(db.carriers.values())
    rows = filter_rows(
        rows,
        [
            ("ocn", field("ocn")),
            ("license_status", field("license_status")),
            ("eligibility_status", core.eligibility_status),
            ("home_state_code", field("home_state_code")),
        ],
    )
    return paginate(rows, serialize.carrier)


@bp.route("/numbering/carriers/<carrier_id>", methods=["GET"])
def get_carrier(carrier_id):
    require_roles(*READERS)
    return object_response(serialize.carrier(core.get_carrier(carrier_id)))


@bp.route("/numbering/carriers/<carrier_id>/license-actions", methods=["POST"])
def license_action(carrier_id):
    require_roles(ROLE_ADMIN)
    payload = body()
    action = req_enum(payload, "action", C.LICENSE_ACTIONS)
    if action in ("GRANT", "RENEW"):
        expires = req_dt(payload, "license_expires_on")
    else:
        expires = opt_dt(payload, "license_expires_on")
    opt_str(payload, "reason", 1, 500)

    carrier = core.get_carrier(carrier_id)
    status = carrier["license_status"]
    instant = now()

    if action == "GRANT":
        if status != "NONE" or expires <= instant:
            fail("ERR_INVALID_STATE_TRANSITION", "GRANT is not available")
        carrier["license_status"] = "GRANTED"
        carrier["license_expires_on"] = expires
    elif action == "RENEW":
        stored = carrier["license_expires_on"]
        if status != "GRANTED" or stored is None or expires <= stored:
            fail("ERR_INVALID_STATE_TRANSITION", "RENEW is not available")
        carrier["license_expires_on"] = expires
    elif action == "SUSPEND":
        if status != "GRANTED":
            fail("ERR_INVALID_STATE_TRANSITION", "SUSPEND is not available")
        carrier["license_status"] = "SUSPENDED"
    elif action == "REINSTATE":
        stored = carrier["license_expires_on"]
        if status != "SUSPENDED" or stored is None or stored <= instant:
            fail("ERR_INVALID_STATE_TRANSITION", "REINSTATE is not available")
        carrier["license_status"] = "GRANTED"
    else:
        if status not in ("GRANTED", "SUSPENDED"):
            fail("ERR_INVALID_STATE_TRANSITION", "REVOKE is not available")
        carrier["license_status"] = "REVOKED"
        _revocation_cascade(carrier)

    touch(carrier)
    return object_response(serialize.carrier(carrier))


def _revocation_cascade(carrier):
    instant = now()
    blocks = [
        b
        for b in core.blocks_of_carrier(carrier["id"])
        if b["allocation_status"] in ("RESERVED", "ASSIGNED")
    ]
    for block in blocks:
        block["allocation_status"] = "RECLAMATION_PENDING"
        touch(block)
        workflows.create_reclamation_order(
            block, carrier["id"], "LICENSE_REVOKED", instant
        )
        rate_center = db.rate_centers.get(block["rate_center_id"])
        if rate_center is not None:
            touch(rate_center)

    requests = [
        r
        for r in db.allocation_requests.values()
        if r["carrier_id"] == carrier["id"]
        and r["status"] in ("PENDING_REVIEW", "INFO_REQUESTED")
    ]
    for request_row in by_created(requests):
        request_row["status"] = "DENIED"
        request_row["denial_reason"] = "CARRIER_PROBATION"
        request_row["decided_at"] = instant
        touch(request_row)
        rate_center = db.rate_centers.get(request_row["rate_center_id"])
        if rate_center is not None:
            rate_center["pending_request_count"] = max(
                0, rate_center["pending_request_count"] - 1
            )
            touch(rate_center)


@bp.route("/numbering/carriers/<carrier_id>/readiness-events", methods=["POST"])
def readiness_event(carrier_id):
    actor = require_roles(ROLE_CARRIER, ROLE_ADMIN)
    payload = body()
    event = req_enum(payload, "event", C.READINESS_EVENTS)
    if event == "ATTEST":
        switch_clli = req_str(payload, "switch_clli", 1, 11)
        ready = payload.get("interconnection_ready")
        if ready is None:
            fail("ERR_INVALID_REQUEST", "interconnection_ready is required")
        ready = opt_bool(payload, "interconnection_ready")
    else:
        switch_clli = opt_str(payload, "switch_clli", 1, 11)
        ready = opt_bool(payload, "interconnection_ready")
    opt_str(payload, "note", 1, 1000)

    carrier = core.get_carrier(carrier_id)

    if actor.role == ROLE_CARRIER and actor.user_id != carrier["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "only the carrier itself may attest readiness")

    check_action_role(actor, event, READINESS_ACTION_ROLES)

    status = carrier["facilities_readiness_status"]
    if event == "ATTEST":
        if status not in ("NOT_SUBMITTED", "FAILED"):
            fail("ERR_INVALID_STATE_TRANSITION", "ATTEST is not available")
        carrier["facilities_readiness_status"] = "ATTESTED"
        carrier["switch_clli"] = switch_clli
        carrier["interconnection_ready"] = ready
    elif event == "VERIFY":
        if status != "ATTESTED" or not carrier["interconnection_ready"]:
            fail("ERR_INVALID_STATE_TRANSITION", "VERIFY is not available")
        carrier["facilities_readiness_status"] = "VERIFIED"
    else:
        if status not in ("ATTESTED", "VERIFIED"):
            fail("ERR_INVALID_STATE_TRANSITION", "FAIL is not available")
        carrier["facilities_readiness_status"] = "FAILED"

    touch(carrier)
    return object_response(serialize.carrier(carrier))
