"""Routes: compliance certificates, showroom samples, shipments, logical clock."""
from datetime import timedelta

from flask import Blueprint, g, request

from mill.common import (
    ALL_ROLES,
    ApiError,
    D,
    endpoint,
    fmt_dt,
    get_body,
    list_response,
    new_rec,
    now_dt,
    now_iso,
    ok,
    opt_bool,
    opt_int,
    parse_dt,
    pub,
    req_enum,
    req_field,
    req_int,
    req_pos_num,
    touch,
)
from mill.logic import (
    allocs_of_line,
    classify_freight,
    density_4dp,
    freight_charge,
    lines_of,
    recompute_dealer_outstanding,
)
from mill.store import store

bp = Blueprint("finish", __name__)

WRITE_CO = ["ComplianceOfficer"]
WRITE_SALES = ["SalesRep"]
WRITE_SC = ["ShippingCoordinator"]
WRITE_ADMIN = ["PlantAdmin"]
FLAM_STANDARDS = ["TB117_2013", "UFAC", "TB133"]


# ---------------------------------------------------------------------------
# ComplianceCertificate
# ---------------------------------------------------------------------------


@bp.post("/mill/compliance-certificates")
@endpoint(WRITE_CO)
def create_certificate():
    b = get_body()
    order_id = req_field(b, "order_id")
    standard = req_enum(b, "standard", FLAM_STANDARDS)
    label_lot_number = req_field(b, "label_lot_number")
    label_count = req_int(b, "label_count", minimum=0)
    order = store.orders.get(order_id)
    if not order:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "CustomerOrder not found")
    active_exists = any(
        c["order_id"] == order_id and c["status"] in ("DRAFT", "CERTIFIED")
        for c in store.certificates.values()
    )
    if active_exists:
        raise ApiError(
            "ERR_CERTIFICATE_EXISTS",
            409,
            "An active certificate already exists for this order",
        )
    rec = new_rec()
    rec.update(
        {
            "order_id": order_id,
            "standard": standard,
            "label_lot_number": label_lot_number,
            "label_count": label_count,
            "created_by": g.user_id,
            "certified_by": None,
            "certified_at": None,
            "status": "DRAFT",
        }
    )
    store.certificates[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/compliance-certificates")
@endpoint(ALL_ROLES)
def list_certificates():
    recs = list(store.certificates.values())
    v = request.args.get("order_id")
    if v:
        recs = [c for c in recs if c["order_id"] == v]
    return list_response(recs)


def _find_cert(cid):
    rec = store.certificates.get(cid)
    if not rec:
        raise ApiError("ERR_CERTIFICATE_NOT_FOUND", 404, "ComplianceCertificate not found")
    return rec


@bp.get("/mill/compliance-certificates/<cid>")
@endpoint(ALL_ROLES)
def get_certificate(cid):
    return ok(pub(_find_cert(cid)))


@bp.post("/mill/compliance-certificates/<cid>/certify")
@endpoint(WRITE_CO)
def certify_certificate(cid):
    cert = _find_cert(cid)
    if cert["status"] != "DRAFT":
        raise ApiError("ERR_CERTIFICATE_NOT_DRAFT", 409, "Certificate is not in DRAFT")
    order = store.orders.get(cert["order_id"])
    if not order:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "CustomerOrder not found")
    if order["status"] not in ("IN_PRODUCTION", "QUALITY_REVIEW"):
        raise ApiError(
            "ERR_ORDER_NOT_IN_QUALITY_REVIEW",
            409,
            "Certify requires the order in IN_PRODUCTION or QUALITY_REVIEW",
        )
    # Business safety: flammability standard agreement, then segregation of duties.
    if cert["standard"] != order["common_flammability_standard"]:
        raise ApiError(
            "ERR_FLAMMABILITY_STANDARD_MISMATCH",
            422,
            "Certificate standard differs from the order common flammability standard",
        )
    line_ids = {l["id"] for l in lines_of(order["id"])}
    for alloc in store.allocations.values():
        if alloc["order_line_id"] in line_ids:
            lot = store.material_lots.get(alloc["lot_id"])
            if lot and lot["inspected_by"] and lot["inspected_by"] == g.user_id:
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    409,
                    "The certifier may not be the inspector of a lot allocated to this order",
                )
    # Business constraint: label-count conservation.
    total_qty = sum(l["quantity"] for l in lines_of(order["id"]))
    if cert["label_count"] != total_qty:
        raise ApiError(
            "ERR_LABEL_COUNT_MISMATCH",
            422,
            "label_count must equal the summed quantity of the order's lines",
        )
    cert["certified_by"] = g.user_id
    cert["certified_at"] = now_iso()
    cert["status"] = "CERTIFIED"
    touch(cert)
    return ok(pub(cert))


@bp.post("/mill/compliance-certificates/<cid>/void")
@endpoint(WRITE_CO)
def void_certificate(cid):
    cert = _find_cert(cid)
    if cert["status"] not in ("DRAFT", "CERTIFIED"):
        raise ApiError(
            "ERR_CERTIFICATE_NOT_DRAFT", 409, "Only DRAFT or CERTIFIED certificates can be voided"
        )
    if cert["status"] == "CERTIFIED":
        order = store.orders.get(cert["order_id"])
        if not order or order["status"] not in ("IN_PRODUCTION", "QUALITY_REVIEW"):
            raise ApiError(
                "ERR_ORDER_NOT_IN_QUALITY_REVIEW",
                409,
                "Voiding a CERTIFIED certificate requires the order in IN_PRODUCTION or QUALITY_REVIEW",
            )
    cert["status"] = "VOID"
    touch(cert)
    return ok(pub(cert))


# ---------------------------------------------------------------------------
# ShowroomSample
# ---------------------------------------------------------------------------


@bp.post("/mill/showroom-samples")
@endpoint(WRITE_SALES)
def create_sample():
    b = get_body()
    dealer_id = req_field(b, "dealer_id")
    model_id = req_field(b, "model_id")
    unit_serial = req_field(b, "unit_serial")
    sample_value_cents = req_int(b, "sample_value_cents", minimum=0)
    due_back_days = opt_int(b, "due_back_days", 90, minimum=1)
    dealer = store.dealers.get(dealer_id)
    if not dealer:
        raise ApiError("ERR_DEALER_NOT_FOUND", 404, "DealerAccount not found")
    model = store.product_models.get(model_id)
    if not model:
        raise ApiError("ERR_PRODUCT_MODEL_NOT_FOUND", 404, "ProductModel not found")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED", 409, "Dealer account is suspended")
    # One active loan per serial.
    for s in store.samples.values():
        if s["unit_serial"] == unit_serial and s["disposition"] == "ON_LOAN":
            raise ApiError(
                "ERR_UNIT_SERIAL_UNAVAILABLE",
                409,
                "unit_serial already has an ON_LOAN sample",
            )
    # Refurbishment gap: last RETURNED sample of the serial, returned_at + 5 days.
    returned = [
        s
        for s in store.samples.values()
        if s["unit_serial"] == unit_serial and s["disposition"] == "RETURNED" and s["returned_at"]
    ]
    if returned:
        last = max(returned, key=lambda s: parse_dt(s["returned_at"]))
        if parse_dt(last["returned_at"]) + timedelta(days=5) > now_dt():
            raise ApiError(
                "ERR_SAMPLE_IN_REFURB",
                409,
                "unit_serial is still within its 5-day refurbishment gap",
            )
    # Allowance gate (inclusive boundary).
    outstanding = dealer["outstanding_sample_value_cents"]
    if outstanding + sample_value_cents > dealer["sample_allowance_cents"]:
        raise ApiError(
            "ERR_SAMPLE_ALLOWANCE_EXCEEDED",
            422,
            "Sample would exceed the dealer's sample allowance",
        )
    loaned = now_dt()
    rec = new_rec()
    rec.update(
        {
            "dealer_id": dealer_id,
            "model_id": model_id,
            "unit_serial": unit_serial,
            "sample_value_cents": sample_value_cents,
            "due_back_days": due_back_days,
            "loaned_at": fmt_dt(loaned),
            "due_back_at": fmt_dt(loaned + timedelta(days=due_back_days)),
            "returned_at": None,
            "disposition": "ON_LOAN",
        }
    )
    store.samples[rec["id"]] = rec
    recompute_dealer_outstanding(dealer)
    return ok(pub(rec), 201)


@bp.get("/mill/showroom-samples")
@endpoint(ALL_ROLES)
def list_samples():
    recs = list(store.samples.values())
    for param in ("dealer_id", "model_id", "disposition"):
        v = request.args.get(param)
        if v:
            recs = [s for s in recs if s[param] == v]
    return list_response(recs)


def _find_sample(sid):
    rec = store.samples.get(sid)
    if not rec:
        raise ApiError("ERR_SAMPLE_NOT_FOUND", 404, "ShowroomSample not found")
    return rec


@bp.get("/mill/showroom-samples/<sid>")
@endpoint(ALL_ROLES)
def get_sample(sid):
    return ok(pub(_find_sample(sid)))


def _sample_transition(sid, disposition, recompute=True):
    rec = _find_sample(sid)
    if rec["disposition"] != "ON_LOAN":
        raise ApiError("ERR_SAMPLE_NOT_ON_LOAN", 409, "Sample is not ON_LOAN")
    rec["disposition"] = disposition
    if disposition == "RETURNED":
        rec["returned_at"] = now_iso()
    touch(rec)
    if recompute:
        dealer = store.dealers.get(rec["dealer_id"])
        if dealer:
            recompute_dealer_outstanding(dealer)
    return ok(pub(rec))


@bp.post("/mill/showroom-samples/<sid>/return")
@endpoint(WRITE_SALES)
def return_sample(sid):
    return _sample_transition(sid, "RETURNED")


@bp.post("/mill/showroom-samples/<sid>/sell")
@endpoint(WRITE_SALES)
def sell_sample(sid):
    return _sample_transition(sid, "SOLD")


@bp.post("/mill/showroom-samples/<sid>/write-off")
@endpoint(WRITE_SALES)
def write_off_sample(sid):
    # Written-off value keeps consuming the allowance: outstanding UNCHANGED.
    return _sample_transition(sid, "WRITTEN_OFF", recompute=False)


# ---------------------------------------------------------------------------
# Shipment
# ---------------------------------------------------------------------------

SHIPMENT_ORDER_STATES = (
    "CONFIRMED",
    "MATERIAL_HOLD",
    "IN_PRODUCTION",
    "QUALITY_REVIEW",
    "READY_TO_SHIP",
)


@bp.post("/mill/shipments")
@endpoint(WRITE_SC)
def create_shipment():
    b = get_body()
    order_id = req_field(b, "order_id")
    carrier_name = req_field(b, "carrier_name")
    weight_lb = req_pos_num(b, "weight_lb")
    length_in = req_pos_num(b, "length_in")
    width_in = req_pos_num(b, "width_in")
    height_in = req_pos_num(b, "height_in")
    piece_count = req_int(b, "piece_count", minimum=1)
    declared_value_cents = opt_int(b, "declared_value_cents", 0, minimum=0)
    condition_check_passed = opt_bool(b, "condition_check_passed", None)
    order = store.orders.get(order_id)
    if not order:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "CustomerOrder not found")
    if order["status"] not in SHIPMENT_ORDER_STATES:
        raise ApiError(
            "ERR_ORDER_NOT_READY_TO_SHIP",
            409,
            "Shipment requires the order confirmed-or-later",
        )
    if any(s["order_id"] == order_id for s in store.shipments.values()):
        raise ApiError("ERR_SHIPMENT_EXISTS", 409, "A shipment already exists for this order")
    rec = new_rec()
    rec.update(
        {
            "order_id": order_id,
            "carrier_name": carrier_name,
            "method": "LTL" if order["delivery_method"] == "LTL_FREIGHT" else "WHITE_GLOVE",
            "weight_lb": weight_lb,
            "length_in": length_in,
            "width_in": width_in,
            "height_in": height_in,
            "declared_value_cents": declared_value_cents,
            "piece_count": piece_count,
            "density_lb_per_cuft": None,
            "freight_class": None,
            "freight_charge_cents": None,
            "condition_check_passed": condition_check_passed,
            "status": "DRAFT",
        }
    )
    store.shipments[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/shipments")
@endpoint(ALL_ROLES)
def list_shipments():
    recs = list(store.shipments.values())
    v = request.args.get("order_id")
    if v:
        recs = [s for s in recs if s["order_id"] == v]
    return list_response(recs)


def _find_shipment(sid):
    rec = store.shipments.get(sid)
    if not rec:
        raise ApiError("ERR_SHIPMENT_NOT_FOUND", 404, "Shipment not found")
    return rec


@bp.get("/mill/shipments/<sid>")
@endpoint(ALL_ROLES)
def get_shipment(sid):
    return ok(pub(_find_shipment(sid)))


@bp.post("/mill/shipments/<sid>/rate")
@endpoint(WRITE_SC)
def rate_shipment(sid):
    rec = _find_shipment(sid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE", 409, "Shipment is not in DRAFT")
    density = density_4dp(rec["weight_lb"], rec["length_in"], rec["width_in"], rec["height_in"])
    cls = classify_freight(density, rec["declared_value_cents"], rec["weight_lb"])
    charge = freight_charge(rec["method"], cls, rec["weight_lb"], rec["piece_count"])
    rec["density_lb_per_cuft"] = density
    rec["freight_class"] = cls
    rec["freight_charge_cents"] = charge
    rec["status"] = "RATED"
    touch(rec)
    return ok(pub(rec))


@bp.post("/mill/shipments/<sid>/tender")
@endpoint(WRITE_SC)
def tender_shipment(sid):
    rec = _find_shipment(sid)
    if rec["status"] != "RATED":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE", 409, "Shipment is not RATED")
    order = store.orders.get(rec["order_id"])
    if not order or order["status"] != "READY_TO_SHIP":
        raise ApiError(
            "ERR_ORDER_NOT_READY_TO_SHIP", 409, "Tender requires the order READY_TO_SHIP"
        )
    rec["status"] = "TENDERED"
    touch(rec)
    return ok(pub(rec))


@bp.post("/mill/shipments/<sid>/record-pickup")
@endpoint(WRITE_SC)
def pickup_shipment(sid):
    rec = _find_shipment(sid)
    if rec["status"] != "TENDERED":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE", 409, "Shipment is not TENDERED")
    b = get_body()
    effective = (
        bool(b["condition_check_passed"])
        if b.get("condition_check_passed") is not None
        else rec["condition_check_passed"]
    )
    if rec["method"] == "WHITE_GLOVE" and effective is not True:
        raise ApiError(
            "ERR_WHITE_GLOVE_CHECK_REQUIRED",
            422,
            "White-glove pickup requires condition_check_passed true",
        )
    if b.get("condition_check_passed") is not None:
        rec["condition_check_passed"] = bool(b["condition_check_passed"])
    rec["status"] = "PICKED_UP"
    touch(rec)
    order = store.orders.get(rec["order_id"])
    if order and order["status"] == "READY_TO_SHIP":
        order["status"] = "SHIPPED"
        touch(order)
    return ok(pub(rec))


@bp.post("/mill/shipments/<sid>/record-delivery")
@endpoint(WRITE_SC)
def deliver_shipment(sid):
    rec = _find_shipment(sid)
    if rec["status"] != "PICKED_UP":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE", 409, "Shipment is not PICKED_UP")
    rec["status"] = "DELIVERED"
    touch(rec)
    order = store.orders.get(rec["order_id"])
    if order and order["status"] == "SHIPPED":
        order["status"] = "DELIVERED"
        touch(order)
    return ok(pub(rec))


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------


@bp.post("/mill/_clock/set_current_utc")
@endpoint(WRITE_ADMIN)
def set_clock():
    b = get_body()
    to_iso8601 = req_field(b, "to_iso8601")
    store.clock = parse_dt(to_iso8601)
    return ok({"current_utc": fmt_dt(store.clock)})
