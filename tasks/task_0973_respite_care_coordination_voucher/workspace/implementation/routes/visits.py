"""VisitRecord routes: check-out, verification, resubmit."""
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_posture_gate, err_invalid_state,
    err_provider_not_active,
)
from middleware import require_roles, check_provider_ownership
from response import success
from services.util import (
    body, req_enum, opt_str, req_ts, paginate, serialize, hours_val,
    round_half_up_int,
)
from services import core

bp = Blueprint("visits", __name__)


def _visit_or_404(vid):
    v = db.visits.get(vid)
    if v is None:
        raise err_not_found("visit")
    return v


def _recompute_minutes(visit, booking, program):
    visit["verified_minutes"] = core.compute_verified_minutes(
        visit["check_in_at"], visit["check_out_at"]
    )
    visit["payable_minutes"] = core.compute_payable_minutes(
        visit["verified_minutes"], booking["committed_minutes"], program["max_overage_pct"]
    )


@bp.route("/respite/visit-records/<vid>", methods=["GET"])
def get_visit(vid):
    user_id, role = require_roles("Caregiver", "Provider", "Coordinator", "FunderAdmin")
    v = _visit_or_404(vid)
    return success(serialize(v, "visit"))


@bp.route("/respite/visit-records/<vid>/check-out", methods=["POST"])
def check_out(vid):
    user_id, role = require_roles("Provider")
    v = _visit_or_404(vid)
    b = db.bookings[v["booking_id"]]
    check_provider_ownership(user_id, role, b["provider_id"])
    if v["status"] != "OPEN":
        raise err_invalid_state("Visit is not OPEN")
    data = body()
    tasks = data.get("tasks_completed")
    if tasks is not None:
        if not isinstance(tasks, list) or not all(isinstance(t, str) for t in tasks):
            raise err_invalid_request("tasks_completed must be an array of strings")
        v["tasks_completed"] = tasks
    program = db.programs[b["program_id"]]
    v["check_out_at"] = db.now()
    v["auto_closed"] = False
    _recompute_minutes(v, b, program)
    v["status"] = "SUBMITTED"
    db.touch(v)
    return success(serialize(v, "visit"))


@bp.route("/respite/visit-records/<vid>/verification-decisions", methods=["POST"])
def verification_decision(vid):
    require_roles("Coordinator")
    data = body()
    decision = req_enum(data, "decision", {"VERIFY", "REJECT"})
    reason = opt_str(data, "reason")
    v = _visit_or_404(vid)
    if v["status"] != "SUBMITTED":
        raise err_invalid_state("Visit is not SUBMITTED")
    b = db.bookings[v["booking_id"]]
    program = db.programs[b["program_id"]]
    if decision == "REJECT":
        v["rejection_reason"] = reason
        v["status"] = "REJECTED"
        db.touch(v)
        return success(serialize(v, "visit"))

    # VERIFY cascade
    v["status"] = "VERIFIED"
    db.touch(v)

    voucher = db.vouchers[b["voucher_id"]]
    provider = db.providers[b["provider_id"]]
    amount_cents = core.compute_claim_amount(program, provider, b, v)

    # Claim created in DRAFT
    base = db.new_common()
    claim = {
        **base,
        "visit_record_id": v["id"],
        "voucher_id": voucher["id"],
        "provider_id": provider["id"],
        "program_id": program["id"],
        "provisional_amount_cents": b.get("provisional_amount_cents"),
        "amount_cents": amount_cents,
        "status": "DRAFT",
        "denial_reason": None,
        "decided_at": None,
        "paid_at": None,
    }
    db.claims[claim["id"]] = claim

    # Voucher COMMITTED -> REDEEMED
    verified_hours = Decimal(v["verified_minutes"]) / Decimal(60)
    voucher["consumed_hours"] = hours_val(
        Decimal(str(voucher["consumed_hours"])) + verified_hours
    )
    voucher["committed_hours"] = 0.0
    voucher["released_hours"] = hours_val(
        Decimal(str(voucher["authorized_hours"]))
        - Decimal(str(voucher["consumed_hours"]))
        - Decimal(str(voucher["forfeited_hours"]))
    )
    voucher["status"] = "REDEEMED"
    db.touch(voucher)

    # Allocation bucket shifts when OPEN
    alloc_id = voucher.get("allocation_id")
    if alloc_id is not None:
        alloc = db.allocations[alloc_id]
        if alloc["status"] == "OPEN":
            alloc["reserved_hours"] = hours_val(
                Decimal(str(alloc["reserved_hours"])) - Decimal(str(voucher["authorized_hours"]))
            )
            alloc["consumed_hours"] = hours_val(
                Decimal(str(alloc["consumed_hours"])) + verified_hours
            )
            alloc["available_hours"] = hours_val(
                Decimal(str(alloc["available_hours"])) + Decimal(str(voucher["released_hours"]))
            )
            db.touch(alloc)

    # Booking IN_SERVICE -> COMPLETED
    b["status"] = "COMPLETED"
    db.touch(b)

    # Budget: RELEASE voucher provisional, ENCUMBER claim amount
    prov = core.voucher_remaining_provisional_cents(voucher, program)
    core.release(program, prov, "voucher", voucher["id"], "voucher redeemed")
    core.encumber(program, amount_cents, "claim", claim["id"], "claim created")
    db.touch(program)

    # EmergencyRequest: DISPATCHED -> FULFILLED when its booking completes
    if b.get("emergency_request_id"):
        er = db.emergencies.get(b["emergency_request_id"])
        if er is not None and er["status"] == "DISPATCHED":
            er["status"] = "FULFILLED"
            db.touch(er)

    return success(serialize(v, "visit"))


@bp.route("/respite/visit-records/<vid>/resubmit", methods=["POST"])
def resubmit_visit(vid):
    user_id, role = require_roles("Provider")
    v = _visit_or_404(vid)
    b = db.bookings[v["booking_id"]]
    check_provider_ownership(user_id, role, b["provider_id"])
    if v["status"] != "REJECTED":
        raise err_invalid_state("Visit is not REJECTED")
    data = body()
    ci = data.get("check_in_at")
    co = data.get("check_out_at")
    if ci is not None:
        if not isinstance(ci, str):
            raise err_invalid_request("check_in_at must be an ISO 8601 timestamp")
        v["check_in_at"] = db.parse_ts(ci)
    if co is not None:
        if not isinstance(co, str):
            raise err_invalid_request("check_out_at must be an ISO 8601 timestamp")
        v["check_out_at"] = db.parse_ts(co)
    program = db.programs[b["program_id"]]
    _recompute_minutes(v, b, program)
    v["rejection_reason"] = None
    v["status"] = "SUBMITTED"
    db.touch(v)
    return success(serialize(v, "visit"))
