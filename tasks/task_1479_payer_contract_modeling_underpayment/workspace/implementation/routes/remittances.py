"""Remittance endpoints (PRD §3.6)."""

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_remittance_exceeds_charges,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_remittance
from services.validation import body, reject_unknown, as_str, as_int, as_enum, as_date
from services.pricing import (
    reevaluate_claim_after_change,
    compute_paid_amount,
    touch,
)

bp = Blueprint("remittances", __name__)

ADJUSTMENT_REASON_CODES = {"CONTRACTUAL", "DENIAL", "SILENT_PPO_DISCOUNT", "APPEAL_RECOVERY", "OTHER"}


@bp.post("/api/remittances")
def create_remittance():
    require_roles(["RevenueIntegrityAnalyst"])
    data = body()
    reject_unknown(data, {"claim_id", "paid_amount_cents", "remittance_date", "adjustment_reason_code"})
    claim_id = as_str(data, "claim_id")
    paid_amount_cents = as_int(data, "paid_amount_cents", required=True, min_value=0)
    remittance_date = as_date(data, "remittance_date")
    if parse_date(remittance_date) > _db.today():
        raise err_invalid_request("remittance_date may not be after today")
    reason = as_enum(data, "adjustment_reason_code", ADJUSTMENT_REASON_CODES, required=False)
    if reason is None:
        reason = "OTHER"

    claim = _db.store.claims.get(claim_id)
    if claim is None:
        raise err_not_found("Claim not found")

    # State (rung 6): claim must be priced
    if claim["pricing_status"] not in {"PRICED", "REPRICED"}:
        raise err_invalid_state("Claim must be PRICED or REPRICED before a remittance posts")

    # Money guard (rung 11): posted total must not exceed billed charges
    current_posted = compute_paid_amount(claim_id)
    if current_posted + paid_amount_cents > claim["total_billed_charges_cents"]:
        raise err_remittance_exceeds_charges()

    now = _db.now_iso()
    remit = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "claim_id": claim_id,
        "appeal_id": None,
        "paid_amount_cents": paid_amount_cents,
        "remittance_date": remittance_date,
        "adjustment_reason_code": reason,
        "source": "REMITTANCE_835",
        "status": "POSTED",
    }
    _db.store.remittances[remit["id"]] = remit

    reevaluate_claim_after_change(claim, restate_original=True, payment_driven=True)
    return success_object(serialize_remittance(remit), status=201)


@bp.get("/api/remittances/<rid>")
def get_remittance(rid):
    require_roles(ALL_ROLES)
    r = _db.store.remittances.get(rid)
    if r is None:
        raise err_not_found("Remittance not found")
    return success_object(serialize_remittance(r))


@bp.get("/api/remittances")
def list_remittances():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    claim_id = request.args.get("claim_id")
    appeal_id = request.args.get("appeal_id")
    status = request.args.get("status")
    if status is not None and status not in {"POSTED", "REVERSED"}:
        raise err_invalid_request("status filter invalid")
    items = list(_db.store.remittances.values())
    if claim_id is not None:
        items = [r for r in items if r["claim_id"] == claim_id]
    if appeal_id is not None:
        items = [r for r in items if r.get("appeal_id") == appeal_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_remittance(r) for r in page], limit, offset, total)


@bp.post("/api/remittances/<rid>/reverse")
def reverse_remittance(rid):
    require_roles(["FinanceDirector"])
    r = _db.store.remittances.get(rid)
    if r is None:
        raise err_not_found("Remittance not found")
    if r["status"] != "POSTED":
        raise err_invalid_state("Only a POSTED remittance may be reversed")
    # APPEAL_RECOVERY guard: case must be non-terminal
    if r["source"] == "APPEAL_RECOVERY" and r.get("appeal_id"):
        appeal = _db.store.appeals.get(r["appeal_id"])
        case = _db.store.cases.get(appeal["case_id"]) if appeal else None
        if case is not None and case["status"] in {"RECOVERED", "DENIED_FINAL", "WRITTEN_OFF", "WITHDRAWN"}:
            raise err_invalid_state(
                "An APPEAL_RECOVERY remittance may be reversed only while its case is non-terminal"
            )
    r["status"] = "REVERSED"
    touch(r)
    claim = _db.store.claims.get(r["claim_id"])
    if claim is not None:
        # §3.6 reversal cascade: "the queue absorbs the result, restating the
        # active case"; a reversal is not a payment/recovery, so it never
        # triggers the §3.7 auto-RECOVERED transition.
        reevaluate_claim_after_change(claim, restate_original=True)
    return success_object(serialize_remittance(r))
