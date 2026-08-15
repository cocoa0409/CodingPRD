"""Claims / settlement negotiation and inspection certificates
(PRD sections 3.8 and 3.4)."""

from flask import Blueprint, request

from store import TABLES
from helpers import (
    auth, own_or_fail, success, err, get_body, req_str, req_enum,
    req_positive_int, req_int, req_date, paginate, sorted_by_created,
    stamp_new, touch, path_get, require_ref, find, num_out, dec, q2,
    round_half_up_int, recompute_customer_exposure, claim_customer_id,
    shipment_customer_id, recompute_lot_value, compute_unit_value,
    cutout_at_grading,
)

bp = Blueprint("claims", __name__)

GRADER = ["QualityGrader"]
ADJUSTER = ["ClaimsAdjuster"]
CUSTREP = ["CustomerRep"]
ALL = ["DeskAdmin", "Trader", "RiskOfficer", "QualityGrader",
       "WarehouseOperator", "ClaimsAdjuster", "CustomerRep"]

PROV_PCT = {
    "TEMPERATURE_ABUSE": dec("0.60"),
    "SPEC_NONCONFORMANCE": dec("0.50"),
    "WEIGHT_SHORTAGE": dec("1.00"),
    "QUALITY_DEFECT": dec("0.40"),
}
CLAIM_TYPES = set(PROV_PCT.keys())
GRADE_RESULTS = {"PRIME", "CHOICE", "SELECT", "STANDARD", "NO_ROLL"}
CERT_TYPES = {"USDA_GRADE", "USDA_INSPECTION", "COA"}


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def claim_public(c):
    return {
        "id": c["id"],
        "shipment_id": c["shipment_id"],
        "claim_type": c["claim_type"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "provisional_credit_cents": c["provisional_credit_cents"],
        "current_offer_cents": c["current_offer_cents"],
        "offer_round": c["offer_round"],
        "final_settlement_cents": c["final_settlement_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def shipped_value_cents(shipment):
    alloc = find("allocations", shipment["allocation_id"])
    if alloc is None or alloc["unit_price_cents"] is None:
        return dec(0)
    return dec(shipment["shipped_lbs"]) * alloc["unit_price_cents"]


@bp.route("/api/claims", methods=["POST"])
def create_claim():
    uid, _ = auth(CUSTREP)
    body = get_body()
    # Ownership (priority 3): the claim's shipment must belong to the caller.
    raw_sid = body.get("shipment_id")
    if isinstance(raw_sid, str):
        sh = TABLES["shipments"].get(raw_sid)
        if sh is not None:
            own_or_fail(shipment_customer_id(sh), uid)
    # Request shape (priority 4).
    shipment_id = req_str(body, "shipment_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    claimed = req_positive_int(body, "claimed_amount_cents")
    # Body FK existence (priority 6).
    shipment = require_ref("shipments", shipment_id, "shipment_id")
    # Cross-entity state (priority 8).
    if shipment["status"] not in ("DELIVERED", "REJECTED_AT_RECEIVING"):
        err("ERR_SHIPMENT_NOT_CLAIMABLE", 409,
            "Claims require a DELIVERED or REJECTED_AT_RECEIVING shipment")
    # Safety (priority 9): TEMPERATURE_ABUSE requires a BREACHED axis.
    if claim_type == "TEMPERATURE_ABUSE" and shipment["temp_compliance"] != "BREACHED":
        err("ERR_CLAIM_TYPE_NOT_SUPPORTED", 422,
            "TEMPERATURE_ABUSE claims require temp_compliance BREACHED")
    # Provisional credit: min(claimed, round_half_up(shipped_value * pct)).
    pct_value = round_half_up_int(shipped_value_cents(shipment) * PROV_PCT[claim_type])
    provisional = min(claimed, pct_value)
    rec = {
        "shipment_id": shipment_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed,
        "provisional_credit_cents": provisional,
        "current_offer_cents": None,
        "offer_round": 0,
        "final_settlement_cents": None,
        "status": "FILED",
    }
    stamp_new(rec)
    TABLES["claims"][rec["id"]] = rec
    return success(claim_public(rec), code=201)


@bp.route("/api/claims", methods=["GET"])
def list_claims():
    auth(ALL)
    items = sorted_by_created(TABLES["claims"].values())
    shipment_id = request.args.get("shipment_id")
    status = request.args.get("status")
    if shipment_id is not None:
        items = [c for c in items if c["shipment_id"] == shipment_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success([claim_public(c) for c in page], response_type="array",
                   pagination=meta)


@bp.route("/api/claims/<claimId>", methods=["GET"])
def get_claim(claimId):
    auth(ALL)
    c = path_get("claims", claimId, "ERR_CLAIM_NOT_FOUND")
    return success(claim_public(c))


@bp.route("/api/claims/<claimId>/offers", methods=["POST"])
def post_offer(claimId):
    auth(ADJUSTER)
    body = get_body()
    offer = req_positive_int(body, "offer_cents")
    expected = req_int(body, "expected_claim_version")
    c = path_get("claims", claimId, "ERR_CLAIM_NOT_FOUND")
    # Target state (priority 7).
    if c["status"] not in ("FILED", "OFFER_MADE", "COUNTERED"):
        err("ERR_CLAIM_STATE_INVALID", 409,
            "Offers may only be posted from FILED, OFFER_MADE, or COUNTERED")
    # Negotiation cap.
    if c["offer_round"] >= 3:
        err("ERR_CLAIM_OFFER_LIMIT_EXCEEDED", 422,
            "The three-offer negotiation cap has been reached")
    # Optimistic concurrency (priority 15).
    if expected != c["version"]:
        err("ERR_STALE_CLAIM_VERSION", 412,
            "expected_claim_version does not match the claim's current version")
    c["offer_round"] += 1
    c["current_offer_cents"] = offer
    c["status"] = "OFFER_MADE"
    touch(c)
    return success(claim_public(c))


@bp.route("/api/claims/<claimId>/counter", methods=["POST"])
def counter_claim(claimId):
    uid, _ = auth(CUSTREP)
    c = TABLES["claims"].get(claimId)
    if c is not None:
        own_or_fail(claim_customer_id(c), uid)
    body = get_body()
    _counter = req_positive_int(body, "counter_amount_cents")
    if c is None:
        err("ERR_CLAIM_NOT_FOUND", 404, f"Claim {claimId} not found")
    if c["status"] != "OFFER_MADE":
        err("ERR_CLAIM_STATE_INVALID", 409,
            "Counters are only permitted from OFFER_MADE")
    if c["offer_round"] >= 3:
        err("ERR_CLAIM_OFFER_LIMIT_EXCEEDED", 422,
            "The three-offer negotiation cap has been reached")
    c["status"] = "COUNTERED"
    touch(c)
    return success(claim_public(c))


@bp.route("/api/claims/<claimId>/accept", methods=["POST"])
def accept_claim(claimId):
    uid, _ = auth(CUSTREP)
    c = TABLES["claims"].get(claimId)
    if c is not None:
        own_or_fail(claim_customer_id(c), uid)
    if c is None:
        err("ERR_CLAIM_NOT_FOUND", 404, f"Claim {claimId} not found")
    if c["status"] != "OFFER_MADE":
        err("ERR_CLAIM_STATE_INVALID", 409,
            "Acceptance requires the claim to be OFFER_MADE")
    # Final settlement: min(current_offer, round_half_up(shipped_value*0.80))
    # plus a conditional 15000-cent freight allowance.
    shipment = find("shipments", c["shipment_id"])
    cap = round_half_up_int(shipped_value_cents(shipment) * dec("0.80"))
    base = min(c["current_offer_cents"], cap)
    freight = 15000 if (c["claim_type"] == "TEMPERATURE_ABUSE"
                        and shipment is not None
                        and shipment["temp_compliance"] == "BREACHED") else 0
    c["final_settlement_cents"] = base + freight
    c["status"] = "SETTLED_PAID"
    touch(c)
    # Cascade: exposure reduced by the settlement; credit-hold re-evaluated.
    customer = find("customers", claim_customer_id(c))
    if customer is not None:
        recompute_customer_exposure(customer)
    return success(claim_public(c))


@bp.route("/api/claims/<claimId>/deny", methods=["POST"])
def deny_claim(claimId):
    auth(ADJUSTER)
    c = path_get("claims", claimId, "ERR_CLAIM_NOT_FOUND")
    if c["status"] not in ("OFFER_MADE", "COUNTERED"):
        err("ERR_CLAIM_STATE_INVALID", 409,
            "Denial requires the claim to be OFFER_MADE or COUNTERED")
    c["status"] = "SETTLED_DENIED"
    touch(c)
    return success(claim_public(c))


@bp.route("/api/claims/<claimId>/withdraw", methods=["POST"])
def withdraw_claim(claimId):
    uid, _ = auth(CUSTREP)
    c = TABLES["claims"].get(claimId)
    if c is not None:
        own_or_fail(claim_customer_id(c), uid)
    if c is None:
        err("ERR_CLAIM_NOT_FOUND", 404, f"Claim {claimId} not found")
    if c["status"] not in ("FILED", "OFFER_MADE", "COUNTERED"):
        err("ERR_CLAIM_STATE_INVALID", 409,
            "Withdrawal requires the claim to be FILED, OFFER_MADE, or COUNTERED")
    c["status"] = "WITHDRAWN"
    touch(c)
    return success(claim_public(c))


# ---------------------------------------------------------------------------
# Inspection certificates (light resource: id + created_at only)
# ---------------------------------------------------------------------------

def cert_public(c):
    return {
        "id": c["id"],
        "lot_id": c["lot_id"],
        "certificate_type": c["certificate_type"],
        "grade_result": c["grade_result"],
        "certificate_number": c["certificate_number"],
        "issued_by": c["issued_by"],
        "issue_date": c["issue_date"],
        "status": c["status"],
        "created_at": c["created_at"],
    }


@bp.route("/api/inspection-certificates", methods=["POST"])
def create_cert():
    auth(GRADER)
    body = get_body()
    lot_id = req_str(body, "lot_id")
    cert_type = req_enum(body, "certificate_type", CERT_TYPES)
    # grade_result is required iff certificate_type == USDA_GRADE.
    if cert_type == "USDA_GRADE":
        grade = req_enum(body, "grade_result", GRADE_RESULTS)
    else:
        grade = body.get("grade_result")
        if grade is not None and grade not in GRADE_RESULTS:
            err("ERR_INVALID_REQUEST", 400, "grade_result is not a declared grade")
    number = req_str(body, "certificate_number")
    issued_by = req_str(body, "issued_by")
    issue_date = req_date(body, "issue_date")
    # Body FK existence (priority 6).
    lot = require_ref("inventory_lots", lot_id, "lot_id")
    # Uniqueness (priority 10).
    for c in TABLES["inspection_certificates"].values():
        if c["certificate_number"] == number:
            err("ERR_DUPLICATE_CODE", 409,
                f"certificate_number already exists: {number}")
    rec = {
        "lot_id": lot_id,
        "certificate_type": cert_type,
        "grade_result": grade,
        "certificate_number": number,
        "issued_by": issued_by,
        "issue_date": issue_date,
        "status": "VALID",
    }
    stamp_new(rec, common=False)
    TABLES["inspection_certificates"][rec["id"]] = rec
    if cert_type == "USDA_GRADE":
        # Set the lot's grade and recompute its market value.
        lot["usda_grade"] = grade
        lot["unit_value_cents_per_lb"] = compute_unit_value(lot)
        touch(lot)
        # A PO lot in RECEIVED advances to GRADED with the grading-date cutout.
        if lot["po_id"]:
            po = find("purchase_orders", lot["po_id"])
            if po is not None and po["status"] == "RECEIVED":
                product = find("products", po["product_id"])
                po["actual_cutout_value_cents"] = cutout_at_grading(
                    po, product, lot["received_weight_lbs"], issue_date)
                po["status"] = "GRADED"
                touch(po)
    return success(cert_public(rec), code=201)


@bp.route("/api/inspection-certificates", methods=["GET"])
def list_certs():
    auth(ALL)
    items = sorted_by_created(TABLES["inspection_certificates"].values())
    lot_id = request.args.get("lot_id")
    cert_type = request.args.get("certificate_type")
    status = request.args.get("status")
    if lot_id is not None:
        items = [c for c in items if c["lot_id"] == lot_id]
    if cert_type is not None:
        items = [c for c in items if c["certificate_type"] == cert_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success([cert_public(c) for c in page], response_type="array",
                   pagination=meta)


@bp.route("/api/inspection-certificates/<certId>", methods=["GET"])
def get_cert(certId):
    auth(ALL)
    c = path_get("inspection_certificates", certId, "ERR_CERTIFICATE_NOT_FOUND")
    return success(cert_public(c))


@bp.route("/api/inspection-certificates/<certId>/revoke", methods=["POST"])
def revoke_cert(certId):
    auth(GRADER)
    c = path_get("inspection_certificates", certId, "ERR_CERTIFICATE_NOT_FOUND")
    if c["status"] != "VALID":
        err("ERR_CERTIFICATE_ALREADY_REVOKED", 409,
            "Certificate is already REVOKED")
    c["status"] = "REVOKED"
    if c["certificate_type"] == "USDA_GRADE":
        lot = find("inventory_lots", c["lot_id"])
        if lot is not None:
            # Link 1: grade reverts to UNGRADED; value recomputed.
            lot["usda_grade"] = "UNGRADED"
            recompute_lot_value(lot)
            # Link 2: an AVAILABLE lot is quarantined CERT_REVOKED.
            if lot["status"] == "AVAILABLE":
                lot["status"] = "QUARANTINED"
                lot["quarantine_reason"] = "CERT_REVOKED"
            touch(lot)
            # Link 3: a GRADED PO reverts to RECEIVED with null cutout.
            if lot["po_id"]:
                po = find("purchase_orders", lot["po_id"])
                if po is not None and po["status"] == "GRADED":
                    po["status"] = "RECEIVED"
                    po["actual_cutout_value_cents"] = None
                    touch(po)
    return success(cert_public(c))
