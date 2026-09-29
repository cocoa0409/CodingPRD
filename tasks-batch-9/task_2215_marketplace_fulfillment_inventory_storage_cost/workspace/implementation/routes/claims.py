"""ReimbursementClaim endpoints: filing, evidence cycle and adjudication."""
from flask import Blueprint

import calc
import clock
import response
import serialize
import validate
from db import db, mark_created, new_row, set_field
from errors import ApiError
from middleware import require_roles, require_seller_scope
from routes.common import finish, get_claim, get_listing, get_lot, get_seller

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("LOST_INBOUND", "DAMAGED_WAREHOUSE", "LOST_REMOVAL")
DECISIONS = ("APPROVED", "DENIED")


def _check_window(claim):
    deadline = claim["filing_deadline_at"]
    if deadline is None:
        return
    if clock.now() > deadline:
        raise ApiError("ERR_CLAIM_FILING_WINDOW_CLOSED", 422)


def _check_evidence(claim_type, evidence_document_count):
    if evidence_document_count < calc.CLAIM_EVIDENCE_MIN[claim_type]:
        raise ApiError("ERR_EVIDENCE_REFERENCE_MISSING", 422)


@bp.post("/fulfillment/reimbursement-claims")
@require_roles("SellerOperator")
def file_claim():
    data = validate.body()
    inventory_lot_id = validate.req_str(data, "inventory_lot_id")
    claim_type = validate.req_enum(data, "claim_type", CLAIM_TYPES)
    claimed_units = validate.req_int(data, "claimed_units", minimum=1)
    evidence_document_count = validate.req_int(data, "evidence_document_count", minimum=0)
    evidence_reference = validate.req_str(data, "evidence_reference")

    lot = get_lot(inventory_lot_id)
    listing = get_listing(lot["sku_listing_id"])
    require_seller_scope(listing["seller_account_id"])

    if claim_type == "LOST_INBOUND" and lot["reconciliation_status"] != "DISCREPANCY_OPEN":
        raise ApiError("ERR_LOT_NO_OPEN_DISCREPANCY", 409)

    anchor = lot[calc.CLAIM_ANCHOR_FIELD[claim_type]]
    deadline = clock.plus_days(anchor, calc.FILING_WINDOW_DAYS) if anchor else None
    if deadline is not None and clock.now() > deadline:
        raise ApiError("ERR_CLAIM_FILING_WINDOW_CLOSED", 422)

    _check_evidence(claim_type, evidence_document_count)

    if claimed_units > calc.claim_pool_units(lot, claim_type):
        raise ApiError("ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS", 422)

    row = new_row()
    row.update({
        "inventory_lot_id": inventory_lot_id,
        "claim_type": claim_type,
        "claimed_units": claimed_units,
        "evidence_document_count": evidence_document_count,
        "evidence_reference": evidence_reference,
        "status": "SUBMITTED",
        "resubmission_count": 0,
        "filing_deadline_at": deadline,
        "eligible_units": 0,
        "approved_units": 0,
        "reimbursement_amount_cents": 0,
        "decided_at": None,
    })
    db.claims[row["id"]] = row
    mark_created(row)

    if claim_type == "LOST_INBOUND":
        set_field(lot, "reconciliation_status", "DISCREPANCY_CLAIMED")

    return finish(lambda: serialize.claim(row), 201)


@bp.get("/fulfillment/reimbursement-claims/<claim_id>")
@require_roles("MarketplaceAdmin", "SellerOperator", "ClaimsAdjudicator")
def read_claim(claim_id):
    claim = get_claim(claim_id)
    return response.object_response(serialize.claim(claim), 200)


@bp.post("/fulfillment/reimbursement-claims/<claim_id>/request-info")
@require_roles("ClaimsAdjudicator")
def request_info(claim_id):
    data = validate.body()
    validate.req_str(data, "information_request_note")

    claim = get_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", 409)

    set_field(claim, "status", "INFO_REQUESTED")
    return finish(lambda: serialize.claim(claim), 200)


@bp.post("/fulfillment/reimbursement-claims/<claim_id>/resubmit")
@require_roles("SellerOperator")
def resubmit_claim(claim_id):
    data = validate.body()
    evidence_document_count = validate.req_int(data, "evidence_document_count", minimum=0)
    evidence_reference = validate.req_str(data, "evidence_reference")

    claim = get_claim(claim_id)
    lot = get_lot(claim["inventory_lot_id"])
    listing = get_listing(lot["sku_listing_id"])
    require_seller_scope(listing["seller_account_id"])

    if claim["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", 409)

    _check_window(claim)

    if claim["resubmission_count"] >= 2:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED", 422)

    _check_evidence(claim["claim_type"], evidence_document_count)

    set_field(claim, "evidence_document_count", evidence_document_count)
    set_field(claim, "evidence_reference", evidence_reference)
    set_field(claim, "status", "SUBMITTED")
    set_field(claim, "resubmission_count", claim["resubmission_count"] + 1)
    return finish(lambda: serialize.claim(claim), 200)


@bp.post("/fulfillment/reimbursement-claims/<claim_id>/decide")
@require_roles("ClaimsAdjudicator")
def decide_claim(claim_id):
    data = validate.body()
    decision = validate.req_enum(data, "decision", DECISIONS)
    validate.opt_str(data, "decision_note")

    claim = get_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", 409)

    lot = get_lot(claim["inventory_lot_id"])
    listing = get_listing(lot["sku_listing_id"])
    seller = get_seller(listing["seller_account_id"])
    now = clock.now()

    if decision == "DENIED":
        set_field(claim, "status", "DENIED")
        set_field(claim, "approved_units", 0)
        set_field(claim, "reimbursement_amount_cents", 0)
        set_field(claim, "decided_at", now)
        if (claim["claim_type"] == "LOST_INBOUND"
                and lot["reconciliation_status"] == "DISCREPANCY_CLAIMED"):
            set_field(lot, "reconciliation_status", "DISCREPANCY_OPEN")
        return finish(lambda: serialize.claim(claim), 200)

    eligible, amount = calc.run_reimbursement_settlement(claim, lot, listing, seller)
    if eligible < 1:
        raise ApiError("ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS", 422)

    set_field(claim, "status", "APPROVED")
    set_field(claim, "eligible_units", eligible)
    set_field(claim, "approved_units", eligible)
    set_field(claim, "reimbursement_amount_cents", amount)
    set_field(claim, "decided_at", now)

    pool_field = calc.CLAIM_POOL_FIELD[claim["claim_type"]]
    set_field(lot, pool_field, max(0, lot[pool_field] - eligible))
    if (lot["missing_units"] == 0
            and lot["reconciliation_status"] == "DISCREPANCY_CLAIMED"):
        set_field(lot, "reconciliation_status", "DISCREPANCY_RESOLVED")

    return finish(lambda: serialize.claim(claim), 200)
