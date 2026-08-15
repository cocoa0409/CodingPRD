"""Recovery cases and communication logs."""
from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import ALL_ROLES, require_roles
from response import ok, paginate
from services import (bump, check_body_fk, create_communication_log, get_claim,
                      is_int, new_entity, need_enum, need_str,
                      require_claim_open, sorted_by_creation, view)

bp = Blueprint("recovery", __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_case(rcid):
    rc = db.recovery_cases.get(rcid)
    if rc is None:
        raise api_error("ERR_RECOVERY_CASE_NOT_FOUND", 404,
                        "recovery case not found: %s" % rcid)
    return rc


@bp.get("/recovery-cases")
def list_recovery_cases():
    require_roles(ALL_ROLES)
    items = list(db.recovery_cases.values())
    reservation_filter = request.args.get("reservation_id")
    if reservation_filter is not None:
        items = [rc for rc in items if rc["reservation_id"] == reservation_filter]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(rc) for rc in page], response_type="array", pagination=meta)


@bp.get("/recovery-cases/<rcid>")
def get_recovery_case(rcid):
    require_roles(ALL_ROLES)
    return ok(view(get_case(rcid)))


@bp.post("/recovery-cases/<rcid>/record-payment")
def record_payment(rcid):
    require_roles(["RecoverySpecialist"])
    rc = get_case(rcid)
    b = body()
    # shape: amount within [1, outstanding]
    amount = b.get("amount_cents")
    if not is_int(amount):
        raise bad_request("amount_cents is required")
    if amount < 1 or amount > rc["outstanding_amount_cents"]:
        raise bad_request("amount_cents must be at least 1 and no more than the outstanding amount")
    claim = get_claim(rc["claim_id"])
    # rung 6
    require_claim_open(claim)
    # rung 8
    if rc["status"] not in ("OPEN", "PARTIAL_RECOVERY"):
        raise api_error("ERR_RECOVERY_INVALID_STATE", 409,
                        "recovery case is CLOSED or WAIVED")
    full = amount == rc["outstanding_amount_cents"]
    rc["recovered_amount_cents"] += amount
    rc["outstanding_amount_cents"] = (rc["assessed_amount_cents"]
                                      - rc["recovered_amount_cents"]
                                      - rc["waived_amount_cents"])
    rc["status"] = "CLOSED" if full else "PARTIAL_RECOVERY"
    bump(rc)
    bump(claim)
    return ok(view(rc))


@bp.post("/recovery-cases/<rcid>/waive")
def waive_case(rcid):
    require_roles(["RecoverySpecialist"])
    rc = get_case(rcid)
    claim = get_claim(rc["claim_id"])
    require_claim_open(claim)
    if rc["status"] not in ("OPEN", "PARTIAL_RECOVERY"):
        raise api_error("ERR_RECOVERY_INVALID_STATE", 409,
                        "recovery case is CLOSED or WAIVED")
    rc["waived_amount_cents"] = rc["outstanding_amount_cents"]
    rc["outstanding_amount_cents"] = 0
    rc["status"] = "WAIVED"
    bump(rc)
    bump(claim)
    return ok(view(rc))


# ---------------------------------------------------------------------------
# Communication logs
# ---------------------------------------------------------------------------


@bp.post("/communication-logs")
def create_comm_log():
    require_roles(["RentalDeskAgent"])
    b = body()
    # rung 4: body FK existence
    check_body_fk(b, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    # shape
    claim_id = b.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id:
        raise bad_request("claim_id is required")
    channel = need_enum(b, "channel", ("EMAIL", "SMS", "PHONE"))
    template = need_enum(b, "template", ("COVERAGE_EXPLAINED", "EXPECTATION_SET",
                                         "EXTENSION_UPDATE", "RETURN_REMINDER",
                                         "RECOVERY_NOTICE"))
    body_summary = need_str(b, "body_summary")
    claim = get_claim(claim_id)
    require_claim_open(claim)
    entry = create_communication_log(claim_id, channel, template, body_summary)
    return ok(view(entry), status=201)
