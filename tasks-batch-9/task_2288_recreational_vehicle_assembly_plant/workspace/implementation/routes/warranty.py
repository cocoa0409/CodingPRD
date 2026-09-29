"""Warranty adjudication: the seven-step waterfall, goodwill and chargeback."""
import constants as C
import db
import validation as V
from db import store
from errors import ApiError, bad_request
from flask import Blueprint, g
from middleware import authorize
from routes.common import insert, list_out, must_find, object_out
from services import calc, derive

bp = Blueprint("warranty", __name__)

CLAIM_STATUSES = ["SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "PAID"]


def _scope(dealer_id):
    if g.role == "DealerPrincipal" and g.user_id != dealer_id:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "A dealer principal may only act on its own records.",
        )


def _preview(claim):
    """Steps 1 to 4 of the waterfall — everything a filing or a revision knows."""
    labor, parts, _subtotal, tier = calc.warranty_schedule(claim)
    claim["labor_reimbursement_cents"] = labor
    claim["parts_reimbursement_cents"] = parts
    claim["authority_tier"] = tier


def _lot_supplier(claim):
    lot = store.component_lots.get(claim.get("component_lot_id"))
    if lot is None:
        return None
    return store.suppliers.get(lot["supplier_id"])


@bp.post("/warranty-claims")
@authorize("DealerPrincipal")
def create_claim():
    body = V.body_dict()
    build_id = V.field_string(body, "unit_build_id", required=True, min_len=1)
    claim_type = V.field_enum(body, "claim_type", C.CLAIM_TYPES, required=True)
    labor_hours = V.field_number(body, "labor_hours", required=True, exclusive_minimum=0)
    parts_cost = V.field_int(body, "parts_cost_cents", required=True, minimum=0)
    narrative = V.field_string(body, "narrative", required=True, min_len=1)
    lot_id = V.field_string(body, "component_lot_id", min_len=1)
    goodwill_requested = V.field_int(body, "goodwill_requested_cents", default=0, minimum=0)

    build = must_find("unit_builds", build_id)
    if lot_id is not None:
        must_find("component_lots", lot_id)
    order = store.unit_orders.get(build["unit_order_id"])
    _scope(order["dealer_id"] if order is not None else None)

    shipped_at = order.get("shipped_at") if order is not None else None
    in_warranty = bool(
        shipped_at is not None and db.whole_days_between(shipped_at, db.now()) <= C.WARRANTY_DAYS
    )

    row = db.new_row(
        {
            "dealer_id": g.user_id,
            "unit_build_id": build_id,
            "component_lot_id": lot_id,
            "claim_type": claim_type,
            "labor_hours": calc.rhu2(labor_hours),
            "parts_cost_cents": parts_cost,
            "goodwill_requested_cents": goodwill_requested,
            "narrative": narrative,
            "in_warranty": in_warranty,
            "labor_reimbursement_cents": 0,
            "parts_reimbursement_cents": 0,
            "authority_tier": None,
            "goodwill_authorized_cents": 0,
            "total_reimbursement_cents": 0,
            "supplier_chargeback_cents": 0,
            "info_request_count": 0,
            "resubmission_count": 0,
            "approved_by_user_id": None,
            "paid_by_user_id": None,
            "denial_reason": None,
            "status": "SUBMITTED",
        }
    )
    _preview(row)
    insert("warranty_claims", row)
    return object_out("warranty_claims", row, 201)


@bp.get("/warranty-claims/<row_id>")
@authorize("PlantAdmin", "DealerPrincipal", "WarrantyAdministrator")
def get_claim(row_id):
    row = must_find("warranty_claims", row_id)
    _scope(row["dealer_id"])
    return object_out("warranty_claims", row)


@bp.get("/warranty-claims")
@authorize("PlantAdmin", "DealerPrincipal", "WarrantyAdministrator")
def list_claims():
    dealer_id = V.query_string("dealer_id")
    build_id = V.query_string("unit_build_id")
    lot_id = V.query_string("component_lot_id")
    status = V.query_enum("status", CLAIM_STATUSES)
    claim_type = V.query_enum("claim_type", C.CLAIM_TYPES)
    rows = list(store.warranty_claims.values())
    if g.role == "DealerPrincipal":
        rows = [r for r in rows if r["dealer_id"] == g.user_id]
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if build_id is not None:
        rows = [r for r in rows if r["unit_build_id"] == build_id]
    if lot_id is not None:
        rows = [r for r in rows if r.get("component_lot_id") == lot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if claim_type is not None:
        rows = [r for r in rows if r["claim_type"] == claim_type]
    return list_out("warranty_claims", rows)


@bp.post("/warranty-claims/<row_id>/request-info")
@authorize("WarrantyAdministrator")
def request_info(row_id):
    body = V.body_dict()
    V.field_string(body, "info_request_note", max_len=1000)
    row = must_find("warranty_claims", row_id)
    if row["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_CLAIM_NOT_DECIDABLE",
            "Claim status is {}; information may only be requested on a SUBMITTED claim.".format(
                row["status"]
            ),
        )
    if int(row["info_request_count"]) >= C.MAX_INFO_REQUESTS:
        raise ApiError(
            "ERR_INFO_REQUEST_LIMIT_REACHED",
            "This claim has already had {} information requests.".format(C.MAX_INFO_REQUESTS),
        )
    row["info_request_count"] = int(row["info_request_count"]) + 1
    row["status"] = "INFO_REQUESTED"
    db.touch(row)
    return object_out("warranty_claims", row)


@bp.post("/warranty-claims/<row_id>/resubmit")
@authorize("DealerPrincipal")
def resubmit_claim(row_id):
    body = V.body_dict()
    labor_hours = V.field_number(body, "labor_hours", exclusive_minimum=0)
    parts_cost = V.field_int(body, "parts_cost_cents", minimum=0)
    narrative = V.field_string(body, "narrative", min_len=1)
    row = must_find("warranty_claims", row_id)
    _scope(row["dealer_id"])
    if row["status"] != "INFO_REQUESTED":
        raise ApiError(
            "ERR_CLAIM_NOT_DECIDABLE",
            "Claim status is {}; only an INFO_REQUESTED claim can be resubmitted.".format(
                row["status"]
            ),
        )
    if labor_hours is not None:
        row["labor_hours"] = calc.rhu2(labor_hours)
    if parts_cost is not None:
        row["parts_cost_cents"] = parts_cost
    if narrative is not None:
        row["narrative"] = narrative
    _preview(row)
    row["resubmission_count"] = int(row["resubmission_count"]) + 1
    row["status"] = "SUBMITTED"
    db.touch(row)
    return object_out("warranty_claims", row)


@bp.post("/warranty-claims/<row_id>/decide")
@authorize("WarrantyAdministrator")
def decide_claim(row_id):
    body = V.body_dict()
    decision = V.field_enum(body, "decision", ["APPROVED", "DENIED"], required=True)
    denial_reason = V.field_string(body, "denial_reason", min_len=1, max_len=1000)
    if decision == "DENIED" and denial_reason is None:
        raise bad_request("Field 'denial_reason' is required when the decision is DENIED.")
    row = must_find("warranty_claims", row_id)
    if row["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_CLAIM_NOT_DECIDABLE",
            "Claim status is {}; only a SUBMITTED claim can be decided.".format(row["status"]),
        )

    if decision == "DENIED":
        row["goodwill_authorized_cents"] = 0
        row["total_reimbursement_cents"] = 0
        row["denial_reason"] = denial_reason
        row["status"] = "DENIED"
        db.touch(row)
        return object_out("warranty_claims", row)

    dealer = store.dealers.get(row["dealer_id"])
    remaining = derive.dealer_goodwill_remaining(dealer) if dealer is not None else 0
    if int(row["goodwill_requested_cents"]) > 0 and remaining <= 0:
        raise ApiError(
            "ERR_GOODWILL_BUDGET_EXHAUSTED",
            "The dealer has no remaining goodwill budget.",
        )

    labor, parts, subtotal, tier = calc.warranty_schedule(row)
    goodwill = calc.warranty_goodwill(row, subtotal, tier, remaining)
    total = calc.warranty_total(row, subtotal, goodwill)
    supplier = _lot_supplier(row)
    chargeback = calc.warranty_chargeback(
        row, total, supplier["supplier_status"] if supplier is not None else None
    )

    row["labor_reimbursement_cents"] = labor
    row["parts_reimbursement_cents"] = parts
    row["authority_tier"] = tier
    row["goodwill_authorized_cents"] = goodwill
    row["total_reimbursement_cents"] = total
    row["supplier_chargeback_cents"] = chargeback
    row["approved_by_user_id"] = g.user_id
    row["status"] = "APPROVED"
    db.touch(row)

    if chargeback > 0 and supplier is not None:
        supplier["penalty_event_count"] = int(supplier["penalty_event_count"]) + 1
        derive.rescore_supplier(supplier)
        db.touch(supplier)
    return object_out("warranty_claims", row)


@bp.post("/warranty-claims/<row_id>/pay")
@authorize("WarrantyAdministrator")
def pay_claim(row_id):
    V.body_dict()
    row = must_find("warranty_claims", row_id)
    if row["status"] != "APPROVED":
        raise ApiError(
            "ERR_CLAIM_NOT_DECIDABLE",
            "Claim status is {}; only an APPROVED claim can be paid.".format(row["status"]),
        )
    if g.user_id == row.get("approved_by_user_id"):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The administrator who approved this claim may not also pay it.",
        )
    row["paid_by_user_id"] = g.user_id
    row["status"] = "PAID"
    db.touch(row)
    return object_out("warranty_claims", row)
