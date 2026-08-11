"""Claim routes: submit, adjudicate, pay, appeal."""
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_posture_gate,
    err_appeal_window_closed,
)
from middleware import require_roles, check_provider_ownership
from response import success
from services.util import body, req_enum, opt_str, paginate, serialize
from services import core

bp = Blueprint("claims", __name__)


def _claim_or_404(cid):
    c = db.claims.get(cid)
    if c is None:
        raise err_not_found("claim")
    return c


def _maybe_settle_voucher(voucher):
    """REDEEMED -> SETTLED when no non-terminal claim and no non-terminal booking."""
    if voucher["status"] != "REDEEMED":
        return
    for c in db.claims.values():
        if c["voucher_id"] == voucher["id"] and c["status"] in (
            "DRAFT", "SUBMITTED", "APPROVED", "APPEALED",
        ):
            return
    for b in db.bookings.values():
        if b["voucher_id"] == voucher["id"] and b["status"] in (
            "PENDING_CONFIRMATION", "CONFIRMED", "IN_SERVICE",
        ):
            return
    voucher["status"] = "SETTLED"
    db.touch(voucher)


@bp.route("/respite/claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = require_roles("Provider", "Coordinator", "FunderAdmin")
    c = _claim_or_404(cid)
    if role == "Provider":
        check_provider_ownership(user_id, role, c["provider_id"])
    return success(serialize(c, "claim"))


@bp.route("/respite/claims", methods=["GET"])
def list_claims():
    user_id, role = require_roles("Provider", "Coordinator", "FunderAdmin")
    provider_id = request.args.get("provider_id")
    voucher_id = request.args.get("voucher_id")
    visit_record_id = request.args.get("visit_record_id")
    status = request.args.get("status")
    items = list(db.claims.values())
    if role == "Provider":
        items = [c for c in items if c["provider_id"] == user_id]
    if provider_id:
        items = [c for c in items if c["provider_id"] == provider_id]
    if voucher_id:
        items = [c for c in items if c["voucher_id"] == voucher_id]
    if visit_record_id:
        items = [c for c in items if c["visit_record_id"] == visit_record_id]
    if status:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(
        [serialize(c, "claim") for c in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/respite/claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    user_id, role = require_roles("Provider")
    c = _claim_or_404(cid)
    check_provider_ownership(user_id, role, c["provider_id"])
    if c["status"] != "DRAFT":
        raise err_invalid_state("Claim is not DRAFT")
    c["status"] = "SUBMITTED"
    db.touch(c)
    return success(serialize(c, "claim"))


@bp.route("/respite/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    require_roles("FunderAdmin")
    data = body()
    decision = req_enum(data, "decision", {"APPROVE", "DENY"})
    reason = opt_str(data, "reason")
    c = _claim_or_404(cid)
    program = db.programs[c["program_id"]]
    core.gate_operational(program)
    cur = c["status"]
    if decision == "APPROVE":
        if cur not in ("SUBMITTED", "APPEALED"):
            raise err_invalid_state(f"Cannot APPROVE claim from {cur}")
        was_appealed = cur == "APPEALED"
        c["status"] = "APPROVED"
        c["decided_at"] = db.now()
        db.touch(c)
        if was_appealed:
            # re-encumber claim amount (reversing the denial-time release)
            core.encumber(program, c["amount_cents"], "claim", c["id"], "claim approved after appeal")
            db.touch(program)
    else:  # DENY
        if cur not in ("SUBMITTED", "APPEALED"):
            raise err_invalid_state(f"Cannot DENY claim from {cur}")
        c["status"] = "DENIED" if cur == "SUBMITTED" else "DENIED_FINAL"
        c["denial_reason"] = reason
        c["decided_at"] = db.now()
        core.release(program, c["amount_cents"], "claim", c["id"], "claim denied")
        db.touch(c)
        db.touch(program)
    return success(serialize(c, "claim"))


@bp.route("/respite/claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    require_roles("FunderAdmin")
    c = _claim_or_404(cid)
    program = db.programs[c["program_id"]]
    core.gate_operational(program)
    if c["status"] != "APPROVED":
        raise err_invalid_state("Claim is not APPROVED")
    core.settle(program, c["amount_cents"], "claim", c["id"], "claim paid")
    c["paid_at"] = db.now()
    c["status"] = "PAID"
    db.touch(c)
    db.touch(program)
    voucher = db.vouchers.get(c["voucher_id"])
    if voucher is not None:
        _maybe_settle_voucher(voucher)
    return success(serialize(c, "claim"))


@bp.route("/respite/claims/<cid>/appeal", methods=["POST"])
def appeal_claim(cid):
    user_id, role = require_roles("Provider")
    c = _claim_or_404(cid)
    check_provider_ownership(user_id, role, c["provider_id"])
    if c["status"] != "DENIED":
        raise err_invalid_state("Only DENIED claims may be appealed")
    program = db.programs[c["program_id"]]
    if c["decided_at"] is None:
        raise err_invalid_state("Claim has no decision timestamp")
    deadline = c["decided_at"] + timedelta(days=program["appeal_window_days"])
    if db.now() > deadline:
        raise err_appeal_window_closed()
    c["status"] = "APPEALED"
    db.touch(c)
    return success(serialize(c, "claim"))
