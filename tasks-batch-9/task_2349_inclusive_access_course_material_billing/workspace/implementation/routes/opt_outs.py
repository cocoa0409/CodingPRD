"""OptOutRequest endpoints: file, grant, deny, rescind and re-file (PRD 3.6)."""

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN, ROLE_STUDENT,
                  authenticate)
from calc import MAX_OPT_OUT_CYCLES
from domain import (agreement_of_charge, charge_net, enrollment_of_charge,
                    get_charge, get_opt_out_request, ledger_of_charge,
                    mark_agreement_stale, opt_out_json, opt_outs_of_charge,
                    recompute_section, section_of_charge, term_of_charge,
                    add_ledger)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order, now, touch
from validate import f_enum, f_str, get_body

bp = Blueprint("opt_outs", __name__)

REASON_CODES = ("OWNS_COPY", "COST", "ALTERNATE_SOURCE", "OTHER")

GRANT_EVENT = "POST /opt-out-requests/{request_id}/grant"
RESCIND_EVENT = "POST /opt-out-requests/{request_id}/rescind"


def _open_request_exists(charge_id):
    return any(r["charge_id"] == charge_id and r["status"] in ("SUBMITTED", "GRANTED")
               for r in db.opt_out_requests.values())


@bp.post("/opt-out-requests")
def file_opt_out():
    actor = authenticate(ROLE_STUDENT)
    body = get_body(("charge_id", "reason_code"))
    charge_id = f_str(body, "charge_id")
    reason_code = f_enum(body, "reason_code", REASON_CODES)

    charge = get_charge(charge_id)
    if actor.user_id != charge["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    term = term_of_charge(charge)
    if term["status"] != "OPEN":
        fail("ERR_TERM_BILLING_LOCKED")
    if enrollment_of_charge(charge)["status"] != "ENROLLED":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")
    if charge["opt_out_deadline_at"] is None or now() > charge["opt_out_deadline_at"]:
        fail("ERR_OPT_OUT_WINDOW_CLOSED")
    if _open_request_exists(charge["id"]):
        fail("ERR_DUPLICATE_OPT_OUT_OPEN")

    request = base_record()
    request.update({
        "charge_id": charge["id"],
        "status": "SUBMITTED",
        "reason_code": reason_code,
        "submitted_at": now(),
        "decided_at": None,
        "decided_by_user_id": None,
        "denial_note": None,
        "refund_amount_cents": 0,
        "rescinded_at": None,
        "recharge_amount_cents": 0,
        "cycle_count": 0,
    })
    db.opt_out_requests[request["id"]] = request
    return object_response(opt_out_json(request), 201)


@bp.get("/opt-out-requests/<request_id>")
def read_opt_out(request_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_STUDENT)
    return object_response(opt_out_json(get_opt_out_request(request_id)))


@bp.get("/opt-out-requests")
def list_opt_outs():
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE)
    items = apply_filters(in_order(db.opt_out_requests.values()), [
        ("charge_id", "charge_id"),
        ("status", "status"),
        ("reason_code", "reason_code"),
    ])
    return paginate(items, opt_out_json)


@bp.post("/opt-out-requests/<request_id>/grant")
def grant_opt_out(request_id):
    actor = authenticate(ROLE_BURSAR)
    get_body(())
    request = get_opt_out_request(request_id)
    charge = get_charge(request["charge_id"])
    term = term_of_charge(charge)

    if request["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    if term["status"] not in ("OPEN", "BILLING_LOCKED"):
        fail("ERR_INVALID_STATE")
    if enrollment_of_charge(charge)["status"] != "ENROLLED":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")
    if charge["opt_out_deadline_at"] is None or now() > charge["opt_out_deadline_at"]:
        fail("ERR_OPT_OUT_WINDOW_CLOSED")
    if charge["billing_status"] not in ("POSTED", "REBILLED"):
        fail("ERR_INVALID_STATE")

    pre_refund_net = charge_net(charge)
    request["status"] = "GRANTED"
    request["refund_amount_cents"] = pre_refund_net
    request["decided_at"] = now()
    request["decided_by_user_id"] = actor.user_id
    touch(request)

    # Hop one: refund the charge and revoke its access.
    charge["billing_status"] = "REFUNDED"
    charge["refunded_amount_cents"] += pre_refund_net
    add_ledger(charge, "REFUND", "OPT_OUT_REFUND", -pre_refund_net, GRANT_EVENT)
    charge["access_status"] = "REVOKED"
    charge["access_revoked_at"] = now()
    touch(charge)

    # Hop two: the section's counters and participation rate.
    recompute_section(section_of_charge(charge))
    # Hop three: the pricing agreement goes stale.
    mark_agreement_stale(agreement_of_charge(charge))
    return object_response(opt_out_json(request))


@bp.post("/opt-out-requests/<request_id>/deny")
def deny_opt_out(request_id):
    actor = authenticate(ROLE_BURSAR)
    body = get_body(("denial_note",))
    note = f_str(body, "denial_note")
    request = get_opt_out_request(request_id)
    if request["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    request["status"] = "DENIED"
    request["denial_note"] = note
    request["decided_at"] = now()
    request["decided_by_user_id"] = actor.user_id
    touch(request)
    return object_response(opt_out_json(request))


@bp.post("/opt-out-requests/<request_id>/rescind")
def rescind_opt_out(request_id):
    actor = authenticate(ROLE_STUDENT)
    get_body(())
    request = get_opt_out_request(request_id)
    charge = get_charge(request["charge_id"])
    term = term_of_charge(charge)

    if actor.user_id != charge["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if request["status"] != "GRANTED":
        fail("ERR_INVALID_STATE")
    if term["status"] != "OPEN":
        fail("ERR_TERM_BILLING_LOCKED")
    if enrollment_of_charge(charge)["status"] != "ENROLLED":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")
    if charge["opt_out_deadline_at"] is None or now() > charge["opt_out_deadline_at"]:
        fail("ERR_OPT_OUT_WINDOW_CLOSED")

    refunds = [r for r in ledger_of_charge(charge["id"])
               if r["reason_code"] == "OPT_OUT_REFUND"]
    recharge = abs(refunds[-1]["amount_cents"]) if refunds else 0

    request["status"] = "RESCINDED"
    request["recharge_amount_cents"] = recharge
    request["rescinded_at"] = now()
    touch(request)

    # Hop one: re-charge the bursar account and restore the entitlement.
    add_ledger(charge, "CHARGE", "OPT_IN_RECHARGE", recharge, RESCIND_EVENT)
    charge["refunded_amount_cents"] = 0
    charge["billing_status"] = "POSTED"
    charge["access_status"] = "RESTORED"
    charge["access_restored_at"] = now()
    touch(charge)

    # Hop two, then hop three.
    recompute_section(section_of_charge(charge))
    mark_agreement_stale(agreement_of_charge(charge))
    return object_response(opt_out_json(request))


@bp.post("/opt-out-requests/<request_id>/resubmit")
def resubmit_opt_out(request_id):
    actor = authenticate(ROLE_STUDENT)
    body = get_body(("reason_code",))
    reason_code = f_enum(body, "reason_code", REASON_CODES)
    request = get_opt_out_request(request_id)
    charge = get_charge(request["charge_id"])
    term = term_of_charge(charge)

    if actor.user_id != charge["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if request["status"] != "RESCINDED":
        fail("ERR_INVALID_STATE")
    if term["status"] != "OPEN":
        fail("ERR_TERM_BILLING_LOCKED")
    if enrollment_of_charge(charge)["status"] != "ENROLLED":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")
    if charge["opt_out_deadline_at"] is None or now() > charge["opt_out_deadline_at"]:
        fail("ERR_OPT_OUT_WINDOW_CLOSED")
    if request["cycle_count"] >= MAX_OPT_OUT_CYCLES:
        fail("ERR_OPT_OUT_CYCLE_LIMIT")

    request["status"] = "SUBMITTED"
    request["cycle_count"] += 1
    request["reason_code"] = reason_code
    request["submitted_at"] = now()
    request["decided_at"] = None
    request["decided_by_user_id"] = None
    touch(request)
    return object_response(opt_out_json(request))
