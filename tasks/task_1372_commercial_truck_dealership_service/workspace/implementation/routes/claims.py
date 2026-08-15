"""WarrantyClaim endpoints (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, stamp_new, touch, now_dt
from errors import err_not_found, err_invalid, err_sod, ApiError
from helpers import (body, req_str, req_enum, req_int, opt_str, paginate,
                     sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import warranty_claim as ser
import services

bp = Blueprint("claims", __name__)

OUTCOMES = {"APPROVE", "SHORT_PAY", "DENY"}


def _get_claim(rid):
    c = store.warranty_claims.get(rid)
    if c is None:
        raise err_not_found("WARRANTY_CLAIM")
    return c


def _approved_total(c):
    return (c["approved_labor_cents"] or 0) + (c["approved_parts_cents"] or 0)


@bp.post("/dealership/warranty-claims")
def create_claim():
    caller(["WarrantyAdministrator"])
    data = body()
    ro_id = req_str(data, "repair_order_id")
    claimed_labor = req_int(data, "claimed_labor_cents", minimum=0)
    claimed_parts = req_int(data, "claimed_parts_cents", minimum=0)
    ro = store.repair_orders.get(ro_id)
    if ro is None:
        raise err_not_found("REPAIR_ORDER")
    # Claimed amounts capped by warranty-eligible line sums per type (14).
    eligible_labor = sum(
        l["line_total_cents"] for l in services.ro_lines(ro["id"])
        if l["line_type"] == "LABOR" and l["warranty_eligible"])
    eligible_parts = sum(
        l["line_total_cents"] for l in services.ro_lines(ro["id"])
        if l["line_type"] == "PART" and l["warranty_eligible"])
    if claimed_labor > eligible_labor:
        raise err_invalid(
            "claimed_labor_cents exceeds warranty-eligible labor line totals")
    if claimed_parts > eligible_parts:
        raise err_invalid(
            "claimed_parts_cents exceeds warranty-eligible part line totals")
    claim = {
        "repair_order_id": ro["id"],
        "claimed_labor_cents": claimed_labor,
        "claimed_parts_cents": claimed_parts,
        "approved_labor_cents": None,
        "approved_parts_cents": None,
        "paid_cents": 0,
        "submitted_by_user_id": None,
        "_submitted_dt": None,
        "_adjudicated_dt": None,
        "denial_reason": None,
        "appeal_notes": None,
        "appeal_count": 0,
        "status": "DRAFT",
    }
    stamp_new(claim)
    store.warranty_claims[claim["id"]] = claim
    return success(ser(claim), status=201)


@bp.get("/dealership/warranty-claims")
def list_claims():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.warranty_claims.values()), [
        ("repair_order_id", request.args.get("repair_order_id")),
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([ser(c) for c in page], meta)


@bp.get("/dealership/warranty-claims/<rid>")
def get_claim(rid):
    caller(ALL_ROLES)
    return success(ser(_get_claim(rid)))


@bp.post("/dealership/warranty-claims/<rid>/submit")
def submit_claim(rid):
    uid, _ = caller(["WarrantyAdministrator"])
    c = _get_claim(rid)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_CLAIM_STATE", 409,
                       "Submit requires claim status DRAFT")
    ro = store.repair_orders.get(c["repair_order_id"])
    if ro is None or ro["work_status"] != "INVOICED":
        raise ApiError("ERR_RO_STATE", 409,
                       "Submit requires the repair order to be INVOICED")
    c["submitted_by_user_id"] = uid
    c["_submitted_dt"] = now_dt()
    c["status"] = "SUBMITTED"
    touch(c)
    return success(ser(c))


@bp.post("/dealership/warranty-claims/<rid>/adjudicate")
def adjudicate_claim(rid):
    uid, _ = caller(["OEMClaimsAdjudicator"])
    c = _get_claim(rid)
    # Segregation of duties (priority 3) before body (4) and state (7).
    if uid == c["submitted_by_user_id"]:
        raise err_sod()
    data = body()
    outcome = req_enum(data, "outcome", OUTCOMES)
    if outcome == "DENY":
        denial_reason = req_str(data, "denial_reason")
    else:
        denial_reason = None
    approved_labor = approved_parts = None
    if outcome == "SHORT_PAY":
        approved_labor = req_int(data, "approved_labor_cents", minimum=0)
        approved_parts = req_int(data, "approved_parts_cents", minimum=0)

    if c["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_CLAIM_STATE", 409,
                       "Adjudication requires status SUBMITTED or APPEALED")

    if outcome == "APPROVE":
        c["approved_labor_cents"] = c["claimed_labor_cents"]
        c["approved_parts_cents"] = c["claimed_parts_cents"]
        c["status"] = "APPROVED"
        cascade = True
    elif outcome == "SHORT_PAY":
        if (approved_labor > c["claimed_labor_cents"]
                or approved_parts > c["claimed_parts_cents"]):
            raise ApiError("ERR_APPROVAL_EXCEEDS_CLAIM", 422,
                           "Approved amounts may not exceed claimed amounts")
        if approved_labor + approved_parts <= 0:
            raise err_invalid("Approved amounts must sum to a positive total")
        c["approved_labor_cents"] = approved_labor
        c["approved_parts_cents"] = approved_parts
        c["status"] = "SHORT_PAID"
        cascade = True
    else:  # DENY
        c["approved_labor_cents"] = 0
        c["approved_parts_cents"] = 0
        c["denial_reason"] = denial_reason
        c["status"] = "DENIED"
        cascade = False

    c["_adjudicated_dt"] = now_dt()
    touch(c)
    if cascade:
        ro = store.repair_orders.get(c["repair_order_id"])
        if ro is not None:
            services.claim_cascade(ro)
    return success(ser(c))


@bp.post("/dealership/warranty-claims/<rid>/appeal")
def appeal_claim(rid):
    caller(["WarrantyAdministrator"])
    data = body()
    notes = req_str(data, "appeal_notes")
    c = _get_claim(rid)
    if c["status"] not in ("DENIED", "SHORT_PAID"):
        raise ApiError("ERR_CLAIM_STATE", 409,
                       "Appeal requires status DENIED or SHORT_PAID")
    was_counted = c["status"] == "SHORT_PAID"
    c["appeal_notes"] = notes
    c["appeal_count"] += 1
    c["status"] = "APPEALED"
    touch(c)
    if was_counted:
        # APPEALED claims no longer count toward warranty_covered_cents.
        ro = store.repair_orders.get(c["repair_order_id"])
        if ro is not None:
            services.claim_cascade(ro)
    return success(ser(c))


@bp.post("/dealership/warranty-claims/<rid>/close")
def close_claim(rid):
    caller(["WarrantyAdministrator"])
    c = _get_claim(rid)
    if c["status"] != "DENIED":
        raise ApiError("ERR_CLAIM_STATE", 409,
                       "Close requires status DENIED")
    c["status"] = "CLOSED"
    touch(c)
    return success(ser(c))


@bp.post("/dealership/warranty-claims/<rid>/post-payment")
def claim_post_payment(rid):
    caller(["Controller"])
    data = body()
    amount = req_int(data, "amount_cents")
    c = _get_claim(rid)
    if c["status"] not in ("APPROVED", "SHORT_PAID"):
        raise ApiError("ERR_CLAIM_STATE", 409,
                       "Payment requires status APPROVED or SHORT_PAID")
    if amount <= 0 or c["paid_cents"] + amount > _approved_total(c):
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "Payment must be positive and within the approved total")
    c["paid_cents"] += amount
    if c["paid_cents"] == _approved_total(c):
        c["status"] = "PAID"
    touch(c)
    return success(ser(c))


@bp.post("/dealership/warranty-claims/<rid>/write-off")
def write_off_claim(rid):
    caller(["Controller"])
    c = _get_claim(rid)
    if c["status"] not in ("APPROVED", "SHORT_PAID"):
        raise ApiError("ERR_CLAIM_STATE", 409,
                       "Write-off requires status APPROVED or SHORT_PAID")
    residual = _approved_total(c) - c["paid_cents"]
    aged = (c["_adjudicated_dt"] is not None and now_dt()
            > c["_adjudicated_dt"] + timedelta(days=services.WRITEOFF_AGE_DAYS))
    if residual <= 0 or not (residual <= services.WRITEOFF_SMALL_BALANCE or aged):
        raise ApiError("ERR_WRITEOFF_RULE_VIOLATION", 409,
                       "Write-off requires a positive residual of at most 2500 "
                       "cents or a claim aged more than 45 days")
    c["status"] = "WRITTEN_OFF"
    touch(c)
    return success(ser(c))
