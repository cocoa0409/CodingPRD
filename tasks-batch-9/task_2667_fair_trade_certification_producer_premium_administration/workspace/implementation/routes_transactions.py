"""Trade transactions: pricing, verification, settlement and voiding."""
from flask import Blueprint

import calc
import common as C
import domain as D
import store as S
import validators as V
from common import dec, new_id, now_iso, vol
from errors import ApiError
from response import created, listing, ok
from store import ordered, touch_once

bp = Blueprint("transactions", __name__)

VERIFY_OUTCOMES = ("VERIFIED", "DISPUTED", "REJECTED")


def _seller_holder(tx):
    node = S.nodes[tx["seller_node_id"]]
    return S.holders[node["holder_id"]]


@bp.post("/trade-transactions")
def record_trade():
    from auth import authorize
    user_id, role = authorize("ProducerRepresentative")
    data = V.body()
    seller_node_id = V.req_id(data, "seller_node_id")
    buyer_node_id = V.req_id(data, "buyer_node_id")
    product_code = V.req_enum(data, "product_code", C.PRODUCT_CODES)
    quality_grade = V.req_enum(data, "quality_grade", C.QUALITY_GRADES)
    volume_kg = V.req_number(data, "volume_kg", 3, exclusive_min=0)
    declared_price = V.req_int(data, "declared_unit_price_cents_per_kg", minimum=0)
    contract_date = V.req_date(data, "contract_date")
    expected_version = V.req_int(data, "expected_seller_node_version")
    is_organic = V.req_bool(data, "is_organic", default=False)

    seller = S.node_or_404(seller_node_id)
    buyer = S.node_or_404(buyer_node_id)
    seller_holder = S.holders[seller["holder_id"]]

    if user_id != seller["holder_id"]:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID does not own the seller node's certificate holder")

    if expected_version != seller["version"]:
        raise ApiError("ERR_STALE_NODE_VERSION",
                       "expected_seller_node_version %s does not match %s"
                       % (expected_version, seller["version"]))

    if seller["status"] != "ACTIVE":
        raise ApiError("ERR_NODE_NOT_ACTIVE", "seller node is %s" % seller["status"])
    if buyer["status"] != "ACTIVE":
        raise ApiError("ERR_NODE_NOT_ACTIVE", "buyer node is %s" % buyer["status"])

    for finding in S.findings_of_holder(seller_holder["id"]):
        if finding["status"] == "ESCALATED":
            raise ApiError("ERR_OPEN_CRITICAL_NONCONFORMITY",
                           "the seller holder has an escalated nonconformity")

    if buyer.get("upstream_node_id") != seller["id"]:
        raise ApiError("ERR_SUPPLY_CHAIN_LINK_MISSING",
                       "the buyer node does not name the seller node as upstream")

    if (seller["traceability_mode"] == "MASS_BALANCE"
            and volume_kg > dec(seller["available_credit_kg"])):
        raise ApiError("ERR_MASS_BALANCE_CREDIT_EXCEEDED",
                       "volume_kg exceeds the seller node's available credit")

    priced = calc.minimum_price_floor(product_code, is_organic, quality_grade,
                                      declared_price, volume_kg)
    premium = calc.community_development_premium(
        product_code, is_organic, volume_kg, seller["traceability_mode"])

    tx = {
        "id": new_id(),
        "seller_node_id": seller_node_id,
        "buyer_node_id": buyer_node_id,
        "product_code": product_code,
        "quality_grade": quality_grade,
        "is_organic": is_organic,
        "volume_kg": volume_kg,
        "declared_unit_price_cents_per_kg": declared_price,
        "contract_date": contract_date.isoformat(),
        "verification_status": "UNVERIFIED",
        "settlement_status": "PENDING",
        "verified_at": None,
        "settled_at": None,
        "voided_at": None,
    }
    tx.update(priced)
    tx.update(premium)
    S.stamp_new(tx)
    S.transactions[tx["id"]] = tx

    D.add_reserved(seller, volume_kg)
    touch_once(seller)
    return created(tx)


@bp.post("/trade-transactions/<tx_id>/verify")
def verify_trade(tx_id):
    from auth import authorize
    authorize("Auditor")
    data = V.body()
    outcome = V.req_enum(data, "outcome", VERIFY_OUTCOMES)
    tx = S.transaction_or_404(tx_id)
    seller = S.nodes[tx["seller_node_id"]]
    current = tx["verification_status"]

    if current == "UNVERIFIED" and outcome == "VERIFIED":
        if seller["status"] != "ACTIVE":
            raise ApiError("ERR_NODE_NOT_ACTIVE", "seller node is %s" % seller["status"])
        tx["verification_status"] = "VERIFIED"
        tx["verified_at"] = now_iso()
    elif current == "UNVERIFIED" and outcome == "DISPUTED":
        tx["verification_status"] = "DISPUTED"
        D.add_reserved(seller, -dec(tx["volume_kg"]))
        touch_once(seller)
    elif current == "DISPUTED" and outcome == "VERIFIED":
        if seller["status"] != "ACTIVE":
            raise ApiError("ERR_NODE_NOT_ACTIVE", "seller node is %s" % seller["status"])
        if dec(seller["available_credit_kg"]) < dec(tx["volume_kg"]):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "the released reservation is no longer re-reservable")
        tx["verification_status"] = "VERIFIED"
        tx["verified_at"] = now_iso()
        D.add_reserved(seller, dec(tx["volume_kg"]))
        touch_once(seller)
    elif current == "DISPUTED" and outcome == "REJECTED":
        if tx["settlement_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "settlement_status %s blocks rejection"
                           % tx["settlement_status"])
        tx["verification_status"] = "REJECTED"
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "verification_status %s cannot move to %s" % (current, outcome))

    touch_once(tx)
    return ok(tx)


@bp.post("/trade-transactions/<tx_id>/settle")
def settle_trade(tx_id):
    from auth import authorize
    authorize("CertificationOfficer")
    V.body()
    tx = S.transaction_or_404(tx_id)
    if tx["settlement_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "settlement_status is %s" % tx["settlement_status"])
    if tx["verification_status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "verification_status is %s" % tx["verification_status"])
    seller = S.nodes[tx["seller_node_id"]]
    buyer = S.nodes[tx["buyer_node_id"]]
    if seller["status"] != "ACTIVE":
        raise ApiError("ERR_NODE_NOT_ACTIVE", "seller node is %s" % seller["status"])
    holder = S.holders[seller["holder_id"]]
    if holder["certificate_status"] not in ("CERTIFIED", "TRANSITIONING"):
        raise ApiError("ERR_HOLDER_NOT_CERTIFIED",
                       "seller holder is %s" % holder["certificate_status"])

    volume = dec(tx["volume_kg"])
    tx["settlement_status"] = "SETTLED"
    tx["settled_at"] = now_iso()

    D.add_reserved(seller, -volume)
    D.add_claimed(seller, volume)
    touch_once(seller)

    D.add_certified_input(buyer, calc.conversion_adjusted(volume, buyer["conversion_ratio"]))
    touch_once(buyer)

    fund = S.fund_of(holder["id"])
    if fund is not None and tx["premium_cents"] > 0:
        D.write_entry(fund, "ACCRUAL", tx["premium_cents"],
                      "premium accrual for settled trade %s" % tx["id"],
                      trade_transaction_id=tx["id"])
        D.committee_on_balance_rise(S.live_committee_of(holder["id"]), fund)

    D.recompute_annual_certified_volume(holder)
    touch_once(holder)
    touch_once(tx)
    return ok(tx)


@bp.post("/trade-transactions/<tx_id>/void")
def void_trade(tx_id):
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    V.opt_str(data, "reason", 1000)
    tx = S.transaction_or_404(tx_id)
    if tx["settlement_status"] != "SETTLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "settlement_status is %s" % tx["settlement_status"])
    seller = S.nodes[tx["seller_node_id"]]
    buyer = S.nodes[tx["buyer_node_id"]]
    holder = S.holders[seller["holder_id"]]
    fund = S.fund_of(holder["id"])
    premium = tx["premium_cents"]
    if fund is not None and premium > 0 and fund["balance_cents"] < premium:
        raise ApiError("ERR_FUND_BALANCE_INSUFFICIENT",
                       "the fund cannot absorb a reversal of %d cents" % premium)

    volume = dec(tx["volume_kg"])
    tx["settlement_status"] = "REVERSED"
    tx["voided_at"] = now_iso()

    D.add_claimed(seller, -volume)
    touch_once(seller)
    D.add_certified_input(buyer, -calc.conversion_adjusted(volume, buyer["conversion_ratio"]))
    touch_once(buyer)

    if fund is not None and premium > 0:
        D.write_entry(fund, "REVERSAL", premium,
                      "premium reversal for voided trade %s" % tx["id"],
                      trade_transaction_id=tx["id"])
        D.committee_on_balance_fall(S.live_committee_of(holder["id"]), fund)

    D.recompute_annual_certified_volume(holder)
    touch_once(holder)
    touch_once(tx)
    return ok(tx)


@bp.get("/trade-transactions")
def list_trades():
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative",
              "BrandLicensee")
    seller_node_id = V.str_filter("seller_node_id")
    buyer_node_id = V.str_filter("buyer_node_id")
    verification_status = V.enum_filter("verification_status", C.VERIFICATION_STATUSES)
    settlement_status = V.enum_filter("settlement_status", C.SETTLEMENT_STATUSES)
    product_code = V.enum_filter("product_code", C.PRODUCT_CODES)

    rows = ordered(list(S.transactions.values()))
    if seller_node_id:
        rows = [r for r in rows if r["seller_node_id"] == seller_node_id]
    if buyer_node_id:
        rows = [r for r in rows if r["buyer_node_id"] == buyer_node_id]
    if verification_status:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    if settlement_status:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]
    if product_code:
        rows = [r for r in rows if r["product_code"] == product_code]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/trade-transactions/<tx_id>")
def read_trade(tx_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "ProducerRepresentative",
              "BrandLicensee")
    return ok(S.transaction_or_404(tx_id))
