"""Routes: warranty claims and service-part shipments."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from common import (ANY_ROLE, ApiError, D, body_json, check_ownership, err400,
                    list_response, need, obj_response, paginate, require_roles, v_dt,
                    v_enum, v_int, v_str)
from services import (CARRIER_FEE, CARRIERS, CLAIM_ACTIVE_STATUSES, COMPONENTS,
                      COVERAGE_VARIANTS, REMEDIES, coverage_pct_for, get_or_404,
                      ser_claim, ser_shipment)
from store import STORE, current_time, new_entity, touch

bp_warranty = Blueprint("warranty", __name__)


def load_claim_owned(claim_id):
    claim = get_or_404(STORE.claims, claim_id)
    order = STORE.orders.get(claim["order_id"])
    if order:
        check_ownership(order["dealer_id"])
    return claim


# ------------------------------------------------------------------ claims

@bp_warranty.post("/fenestration/warranty-claims")
@require_roles("DealerRep", "PlantManager")
def create_claim():
    body = body_json()
    order_id = v_str(need(body, "order_id"), "order_id")
    order = get_or_404(STORE.orders, order_id)
    check_ownership(order["dealer_id"])
    line_id = v_str(need(body, "order_line_id"), "order_line_id")
    line = get_or_404(STORE.lines, line_id)
    if line["order_id"] != order["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Order line does not belong to the order")
    component = v_enum(need(body, "component"), "component", COMPONENTS)
    variant = v_enum(need(body, "coverage_variant"), "coverage_variant", COVERAGE_VARIANTS)
    failure_date = v_dt(need(body, "failure_date"), "failure_date")
    description = v_str(need(body, "description"), "description")
    if failure_date > current_time():
        err400("failure_date must not be later than the current logical time")
    if order["production_status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED", 409, "Order is not DELIVERED")
    if failure_date < order["delivered_at"]:
        err400("failure_date must be on or after the order's delivered_at")
    for c in STORE.claims.values():
        if (c["order_line_id"] == line_id and c["component"] == component
                and c["status"] in CLAIM_ACTIVE_STATUSES):
            raise ApiError("ERR_DUPLICATE_ACTIVE_CLAIM", 409,
                           "An active claim already exists for this line and component")
    claim = new_entity({
        "order_id": order["id"], "order_line_id": line_id, "component": component,
        "coverage_variant": variant, "failure_date": failure_date,
        "description": description, "remedy": None, "remedy_value_cents": None,
        "status": "SUBMITTED", "denial_reason": None,
    })
    claim["coverage_pct"] = coverage_pct_for(claim, order, line)
    STORE.claims[claim["id"]] = claim
    return obj_response(ser_claim(claim), 201)


@bp_warranty.get("/fenestration/warranty-claims/<claimId>")
@require_roles(*ANY_ROLE)
def get_claim(claimId):
    return obj_response(ser_claim(load_claim_owned(claimId)), 200)


@bp_warranty.get("/fenestration/warranty-claims")
@require_roles(*ANY_ROLE)
def list_claims():
    items = list(STORE.claims.values())
    for param in ("order_id", "order_line_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if str(c.get(param)) == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_claim(c) for c in page], limit, offset, total)


@bp_warranty.get("/fenestration/orders/<orderId>/warranty-claims")
@require_roles(*ANY_ROLE)
def list_order_claims(orderId):
    order = get_or_404(STORE.orders, orderId)
    check_ownership(order["dealer_id"])
    items = [c for c in STORE.claims.values() if c["order_id"] == orderId]
    page, limit, offset, total = paginate(items)
    return list_response([ser_claim(c) for c in page], limit, offset, total)


@bp_warranty.post("/fenestration/warranty-claims/<claimId>/take-review")
@require_roles("WarrantyAdjuster", "PlantManager")
def take_review(claimId):
    claim = get_or_404(STORE.claims, claimId)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_REVIEWABLE", 409,
                       "Only a SUBMITTED claim can be taken into review")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return obj_response(ser_claim(claim), 200)


@bp_warranty.post("/fenestration/warranty-claims/<claimId>/request-info")
@require_roles("WarrantyAdjuster", "PlantManager")
def request_info(claimId):
    claim = get_or_404(STORE.claims, claimId)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_NOT_REVIEWABLE", 409,
                       "Only an UNDER_REVIEW claim can move to INFO_REQUESTED")
    claim["status"] = "INFO_REQUESTED"
    touch(claim)
    return obj_response(ser_claim(claim), 200)


@bp_warranty.post("/fenestration/warranty-claims/<claimId>/provide-info")
@require_roles("DealerRep", "PlantManager")
def provide_info(claimId):
    claim = load_claim_owned(claimId)
    if claim["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an INFO_REQUESTED claim can be answered")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return obj_response(ser_claim(claim), 200)


@bp_warranty.post("/fenestration/warranty-claims/<claimId>/approve")
@require_roles("WarrantyAdjuster", "PlantManager")
def approve_claim(claimId):
    claim = get_or_404(STORE.claims, claimId)
    body = body_json()
    remedy = v_enum(need(body, "remedy"), "remedy", REMEDIES)
    part_sku = quantity = carrier = None
    if remedy == "REPAIR_PART":
        part_sku = v_str(need(body, "part_sku"), "part_sku")
        quantity = v_int(need(body, "quantity"), "quantity")
        carrier = v_enum(need(body, "carrier"), "carrier", CARRIERS)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_NOT_REVIEWABLE", 409,
                       "Only an UNDER_REVIEW claim can be approved")
    order = STORE.orders.get(claim["order_id"])
    line = STORE.lines.get(claim["order_line_id"])
    coverage = coverage_pct_for(claim, order, line)
    claim["coverage_pct"] = coverage
    if coverage <= 0:
        raise ApiError("ERR_WARRANTY_EXPIRED", 409,
                       "Claim coverage is zero; warranty expired")
    claim["remedy"] = remedy
    claim["remedy_value_cents"] = int(
        (D(line["line_total_cents"]) * D(coverage) / D(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    if remedy == "REFUND":
        claim["status"] = "FULFILLED"
        touch(claim)
        return obj_response(ser_claim(claim), 200)
    claim["status"] = "APPROVED"
    touch(claim)
    charge = 0 if coverage == 100 else CARRIER_FEE[carrier]
    shipment = new_entity({
        "warranty_claim_id": claim["id"], "part_sku": part_sku, "quantity": quantity,
        "carrier": carrier, "shipping_charge_cents": charge, "status": "PICKING",
    })
    STORE.shipments[shipment["id"]] = shipment
    return obj_response(ser_claim(claim), 200)


@bp_warranty.post("/fenestration/warranty-claims/<claimId>/deny")
@require_roles("WarrantyAdjuster", "PlantManager")
def deny_claim(claimId):
    claim = get_or_404(STORE.claims, claimId)
    body = body_json()
    reason = v_str(need(body, "denial_reason"), "denial_reason")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_NOT_REVIEWABLE", 409,
                       "Only an UNDER_REVIEW claim can be denied")
    claim["status"] = "DENIED"
    claim["denial_reason"] = reason
    touch(claim)
    return obj_response(ser_claim(claim), 200)


@bp_warranty.post("/fenestration/warranty-claims/<claimId>/appeal")
@require_roles("DealerRep", "PlantManager")
def appeal_claim(claimId):
    claim = load_claim_owned(claimId)
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DENIED claim can be appealed")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return obj_response(ser_claim(claim), 200)


@bp_warranty.post("/fenestration/warranty-claims/<claimId>/close")
@require_roles("DealerRep", "WarrantyAdjuster", "PlantManager")
def close_claim(claimId):
    claim = load_claim_owned(claimId)
    if claim["status"] not in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "DENIED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Claim in {claim['status']} cannot be closed")
    claim["status"] = "CLOSED"
    touch(claim)
    return obj_response(ser_claim(claim), 200)


# ------------------------------------------------------------------ service-part shipments

@bp_warranty.get("/fenestration/warranty-claims/<claimId>/service-part-shipments")
@require_roles(*ANY_ROLE)
def list_claim_shipments(claimId):
    load_claim_owned(claimId)
    items = [s for s in STORE.shipments.values() if s["warranty_claim_id"] == claimId]
    page, limit, offset, total = paginate(items)
    return list_response([ser_shipment(s) for s in page], limit, offset, total)


@bp_warranty.get("/fenestration/service-part-shipments/<shipmentId>")
@require_roles(*ANY_ROLE)
def get_shipment(shipmentId):
    return obj_response(ser_shipment(get_or_404(STORE.shipments, shipmentId)), 200)


@bp_warranty.get("/fenestration/service-part-shipments")
@require_roles(*ANY_ROLE)
def list_shipments():
    items = list(STORE.shipments.values())
    val = request.args.get("warranty_claim_id")
    if val is not None:
        items = [s for s in items if s["warranty_claim_id"] == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_shipment(s) for s in page], limit, offset, total)


@bp_warranty.post("/fenestration/service-part-shipments/<shipmentId>/ship")
@require_roles("ShippingCoordinator", "PlantManager")
def ship_shipment(shipmentId):
    s = get_or_404(STORE.shipments, shipmentId)
    if s["status"] != "PICKING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PICKING shipment can ship")
    s["status"] = "SHIPPED"
    touch(s)
    return obj_response(ser_shipment(s), 200)


@bp_warranty.post("/fenestration/service-part-shipments/<shipmentId>/deliver")
@require_roles("ShippingCoordinator", "PlantManager")
def deliver_shipment(shipmentId):
    s = get_or_404(STORE.shipments, shipmentId)
    if s["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SHIPPED shipment can be delivered")
    s["status"] = "DELIVERED"
    touch(s)
    claim = STORE.claims.get(s["warranty_claim_id"])
    if claim and claim["status"] == "APPROVED":
        claim["status"] = "FULFILLED"
        touch(claim)
    return obj_response(ser_shipment(s), 200)
