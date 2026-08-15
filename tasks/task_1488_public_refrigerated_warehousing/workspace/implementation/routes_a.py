"""Routes: logical clock, customers, rate cards, zones, inbound receipts.

Validation tiers (PRD §2.9) are applied in order inside every handler:
1 auth -> 2 body schema -> 3 role -> 4 ownership -> 5 existence -> 6 state ->
7 food-safety -> 8 temporal -> 9 capacity/consistency -> 10 claim refs ->
11 fiscal.
"""

from flask import Blueprint, request

from core import (
    ALL_ROLES, CLOCK, ApiError, DB, as_bool, as_enum, as_int, as_number,
    as_str, authenticate, authorize, check_ownership, clock_now, fmt_ts,
    get_body, get_or_404, list_response, new_record, ok_object, parse_date,
    parse_datetime, req_present, touch,
)
from views import (
    active_rate_card, create_invoice, customer_view, month_bounds, open_invoice,
    rate_card_view, receipt_view, zone_metrics, zone_posture, zone_view,
)

bp = Blueprint("routes_a", __name__)


# ----------------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------------

@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    uid, role = authenticate()
    data = get_body()
    to_iso = req_present(data, "to_iso8601")
    target = parse_datetime(to_iso, "to_iso8601")
    authorize(role, ALL_ROLES)
    CLOCK["now"] = target
    return ok_object({"current_utc": fmt_ts(target)})


# ----------------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------------

@bp.route("/api/customers", methods=["POST"])
def create_customer():
    uid, role = authenticate()
    data = get_body()
    name = as_str(req_present(data, "name"), "name")
    credit = as_int(req_present(data, "credit_limit_cents"), "credit_limit_cents", minimum=0)
    authorize(role, {"BillingAdmin"})
    cust = new_record({"name": name, "credit_limit_cents": credit, "status": "ACTIVE"})
    DB["customers"][cust["id"]] = cust
    start, end = month_bounds(clock_now())
    create_invoice(cust["id"], start, end)
    return ok_object(customer_view(cust), 201)


@bp.route("/api/customers/<cid>", methods=["GET"])
def get_customer(cid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    cust = get_or_404("customers", cid, "customer")
    check_ownership(role, uid, cust["id"])
    return ok_object(customer_view(cust))


@bp.route("/api/customers", methods=["GET"])
def list_customers():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(DB["customers"].values())
    if role == "CustomerAdmin":
        records = [c for c in records if c["id"] == uid]
    return list_response(records, customer_view)


@bp.route("/api/customers/<cid>", methods=["PATCH"])
def patch_customer(cid):
    uid, role = authenticate()
    data = get_body()
    credit = None
    status = None
    if "credit_limit_cents" in data and data["credit_limit_cents"] is not None:
        credit = as_int(data["credit_limit_cents"], "credit_limit_cents", minimum=0)
    if "status" in data and data["status"] is not None:
        status = as_enum(data["status"], "status", ("ACTIVE", "SUSPENDED"))
    authorize(role, {"BillingAdmin"})
    cust = get_or_404("customers", cid, "customer")
    if credit is not None:
        cust["credit_limit_cents"] = credit
    if status is not None:
        cust["status"] = status
    touch(cust)
    return ok_object(customer_view(cust))


# ----------------------------------------------------------------------------
# Rate cards
# ----------------------------------------------------------------------------

@bp.route("/api/rate-cards", methods=["POST"])
def create_rate_card():
    uid, role = authenticate()
    data = get_body()
    customer_id = as_str(req_present(data, "customer_id"), "customer_id")
    storage_method = as_enum(req_present(data, "storage_method"), "storage_method",
                             ("DAILY_PRORATED", "FULL_MONTH"))
    frozen = as_int(req_present(data, "frozen_storage_cents_per_pallet_month"),
                    "frozen_storage_cents_per_pallet_month")
    chilled = as_int(req_present(data, "chilled_storage_cents_per_pallet_month"),
                     "chilled_storage_cents_per_pallet_month")
    h_in = as_int(req_present(data, "handling_in_cents_per_pallet"), "handling_in_cents_per_pallet")
    h_out = as_int(req_present(data, "handling_out_cents_per_pallet"), "handling_out_cents_per_pallet")
    blast_base = as_int(req_present(data, "blast_base_cents"), "blast_base_cents")
    blast_pp = as_int(req_present(data, "blast_per_pallet_cents"), "blast_per_pallet_cents")
    liability_model = as_enum(req_present(data, "liability_model"), "liability_model",
                              ("DECLARED_VALUE", "LIMITED_LIABILITY"))
    liability_pp = as_int(req_present(data, "liability_per_pallet_cents"), "liability_per_pallet_cents")
    dwell_exempt = as_bool(req_present(data, "dwell_exempt"), "dwell_exempt")
    expected_version = as_int(req_present(data, "expected_customer_version"), "expected_customer_version")
    authorize(role, {"BillingAdmin"})
    cust = get_or_404("customers", customer_id, "customer")
    # OCC (state tier): stale expectation -> 412
    if expected_version != cust["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_customer_version does not match the customer's current version")
    prior = active_rate_card(customer_id)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    rc = new_record({
        "customer_id": customer_id,
        "storage_method": storage_method,
        "frozen_storage_cents_per_pallet_month": frozen,
        "chilled_storage_cents_per_pallet_month": chilled,
        "handling_in_cents_per_pallet": h_in,
        "handling_out_cents_per_pallet": h_out,
        "blast_base_cents": blast_base,
        "blast_per_pallet_cents": blast_pp,
        "liability_model": liability_model,
        "liability_per_pallet_cents": liability_pp,
        "dwell_exempt": dwell_exempt,
        "status": "ACTIVE",
    })
    DB["rate_cards"][rc["id"]] = rc
    touch(cust)  # Customer.version incremented by 1
    return ok_object(rate_card_view(rc), 201)


@bp.route("/api/rate-cards/<rid>", methods=["GET"])
def get_rate_card(rid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    rc = get_or_404("rate_cards", rid, "rate card")
    check_ownership(role, uid, rc["customer_id"])
    return ok_object(rate_card_view(rc))


@bp.route("/api/rate-cards", methods=["GET"])
def list_rate_cards():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_status = request.args.get("status")
    records = list(DB["rate_cards"].values())
    if role == "CustomerAdmin":
        records = [r for r in records if r["customer_id"] == uid]
    if f_customer is not None:
        records = [r for r in records if r["customer_id"] == f_customer]
    if f_status is not None:
        records = [r for r in records if r["status"] == f_status]
    return list_response(records, rate_card_view)


# ----------------------------------------------------------------------------
# Temperature zones
# ----------------------------------------------------------------------------

@bp.route("/api/zones", methods=["POST"])
def create_zone():
    uid, role = authenticate()
    data = get_body()
    zone_code = as_str(req_present(data, "zone_code"), "zone_code")
    temp_class = as_enum(req_present(data, "temp_class"), "temp_class", ("FROZEN", "CHILLED"))
    capacity = as_int(req_present(data, "capacity_pallets"), "capacity_pallets", minimum=1)
    dock_doors = as_int(req_present(data, "dock_doors"), "dock_doors", minimum=1)
    authorize(role, {"WarehouseOperator"})
    if any(z["zone_code"] == zone_code for z in DB["zones"].values()):
        raise ApiError("ERR_VALIDATION", 400, "zone_code must be unique across all zones")
    zone = new_record({
        "zone_code": zone_code,
        "temp_class": temp_class,
        "capacity_pallets": capacity,
        "dock_doors": dock_doors,
    })
    DB["zones"][zone["id"]] = zone
    return ok_object(zone_view(zone), 201)


@bp.route("/api/zones/<zid>", methods=["GET"])
def get_zone(zid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    zone = get_or_404("zones", zid, "zone")
    return ok_object(zone_view(zone))


@bp.route("/api/zones", methods=["GET"])
def list_zones():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_class = request.args.get("temp_class")
    records = list(DB["zones"].values())
    if f_class is not None:
        records = [z for z in records if z["temp_class"] == f_class]
    return list_response(records, zone_view)


# ----------------------------------------------------------------------------
# Inbound receipts
# ----------------------------------------------------------------------------

@bp.route("/api/inbound-receipts", methods=["POST"])
def create_receipt():
    uid, role = authenticate()
    data = get_body()
    customer_id = as_str(req_present(data, "customer_id"), "customer_id")
    zone_id = as_str(req_present(data, "zone_id"), "zone_id")
    product_code = as_str(req_present(data, "product_code"), "product_code")
    lot_code = as_str(req_present(data, "lot_code"), "lot_code")
    production_date = parse_date(req_present(data, "production_date"), "production_date")
    temp_class = as_enum(req_present(data, "temp_class"), "temp_class", ("FROZEN", "CHILLED"))
    expected = as_int(req_present(data, "expected_pallets"), "expected_pallets", minimum=1)
    window_start = parse_datetime(req_present(data, "window_start"), "window_start")
    window_end = parse_datetime(req_present(data, "window_end"), "window_end")
    if not window_end > window_start:
        raise ApiError("ERR_VALIDATION", 400, "window_end must be later than window_start")
    authorize(role, {"CustomerAdmin"})
    check_ownership(role, uid, customer_id)
    cust = get_or_404("customers", customer_id, "customer")
    zone = get_or_404("zones", zone_id, "zone")
    # Tier 8 — dock-door aggregate overlap (strict overlap; adjacency allowed)
    overlap = sum(
        1 for r in DB["receipts"].values()
        if r["zone_id"] == zone_id and r["status"] in ("SCHEDULED", "ARRIVED")
        and window_start < r["window_end"] and r["window_start"] < window_end
    )
    if overlap >= zone["dock_doors"]:
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED", 409,
                       "overlapping arrival windows would exceed the zone's dock doors")
    # Tier 9 — temperature-class agreement
    if temp_class != zone["temp_class"]:
        raise ApiError("ERR_TEMP_CLASS_MISMATCH", 409,
                       "receipt temp_class differs from the zone's temp_class")
    # Tier 11 — customer standing
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "customer is SUSPENDED")
    receipt = new_record({
        "customer_id": customer_id,
        "zone_id": zone_id,
        "lot_id": None,
        "product_code": product_code,
        "lot_code": lot_code,
        "production_date": production_date,
        "temp_class": temp_class,
        "expected_pallets": expected,
        "actual_pallets": None,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    })
    DB["receipts"][receipt["id"]] = receipt
    return ok_object(receipt_view(receipt), 201)


@bp.route("/api/inbound-receipts/<rid>", methods=["GET"])
def get_receipt(rid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    receipt = get_or_404("receipts", rid, "receipt")
    check_ownership(role, uid, receipt["customer_id"])
    return ok_object(receipt_view(receipt))


@bp.route("/api/inbound-receipts", methods=["GET"])
def list_receipts():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    f_customer = request.args.get("customer_id")
    f_zone = request.args.get("zone_id")
    f_lot = request.args.get("lot_id")
    f_status = request.args.get("status")
    records = list(DB["receipts"].values())
    if role == "CustomerAdmin":
        records = [r for r in records if r["customer_id"] == uid]
    if f_customer is not None:
        records = [r for r in records if r["customer_id"] == f_customer]
    if f_zone is not None:
        records = [r for r in records if r["zone_id"] == f_zone]
    if f_lot is not None:
        records = [r for r in records if r["lot_id"] == f_lot]
    if f_status is not None:
        records = [r for r in records if r["status"] == f_status]
    return list_response(records, receipt_view)


@bp.route("/api/inbound-receipts/<rid>/arrive", methods=["POST"])
def arrive_receipt(rid):
    uid, role = authenticate()
    authorize(role, {"WarehouseOperator"})
    receipt = get_or_404("receipts", rid, "receipt")
    if receipt["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "receipt is not SCHEDULED")
    zone = DB["zones"][receipt["zone_id"]]
    _, _, free = zone_metrics(zone)
    if zone_posture(zone, free) == "FULL":
        raise ApiError("ERR_ZONE_FULL", 409, "zone posture is FULL")
    receipt["status"] = "ARRIVED"
    touch(receipt)
    return ok_object(receipt_view(receipt))


@bp.route("/api/inbound-receipts/<rid>/complete", methods=["POST"])
def complete_receipt(rid):
    uid, role = authenticate()
    data = get_body()
    actual = as_int(req_present(data, "actual_pallets"), "actual_pallets", minimum=1)
    authorize(role, {"WarehouseOperator"})
    receipt = get_or_404("receipts", rid, "receipt")
    if receipt["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "receipt is not ARRIVED")
    zone = DB["zones"][receipt["zone_id"]]
    # Tier 9 — putaway capacity: reservation released BEFORE the capacity check
    in_use, reserved, _ = zone_metrics(zone)
    reserved_after = reserved - receipt["expected_pallets"]
    free_after = zone["capacity_pallets"] - in_use - reserved_after
    if actual > free_after:
        raise ApiError("ERR_ZONE_CAPACITY_EXCEEDED", 409,
                       "actual_pallets exceeds the zone's free capacity")
    # Tier 9 — lot production-date continuity
    lot = None
    for existing in DB["lots"].values():
        if (existing["customer_id"] == receipt["customer_id"]
                and existing["product_code"] == receipt["product_code"]
                and existing["lot_code"] == receipt["lot_code"]):
            lot = existing
            break
    if lot is not None and lot["production_date"] != receipt["production_date"]:
        raise ApiError("ERR_LOT_PRODUCTION_DATE_MISMATCH", 409,
                       "receipt production_date differs from the existing lot's")
    # Tier 11 — ACTIVE rate card required for the handling-in charge
    card = active_rate_card(receipt["customer_id"])
    if card is None:
        raise ApiError("ERR_NO_ACTIVE_RATE_CARD", 409, "customer has no ACTIVE rate card")
    # --- apply: lot upsert, pallet creation, accrual ---
    if lot is None:
        lot = new_record({
            "customer_id": receipt["customer_id"],
            "product_code": receipt["product_code"],
            "lot_code": receipt["lot_code"],
            "production_date": receipt["production_date"],
        })
        DB["lots"][lot["id"]] = lot
    now = clock_now()
    for _ in range(actual):
        pallet = new_record({
            "lot_id": lot["id"],
            "receipt_id": receipt["id"],
            "zone_id": receipt["zone_id"],
            "customer_id": receipt["customer_id"],
            "status": "STORED",
            "quality": "OK",
            "received_at": now,
            "last_blast_frozen_at": None,
            "out_at": None,
            "out_reason": None,
        })
        DB["pallets"][pallet["id"]] = pallet
    receipt["actual_pallets"] = actual
    receipt["lot_id"] = lot["id"]
    receipt["status"] = "COMPLETED"
    touch(receipt)
    inv = open_invoice(receipt["customer_id"])
    inv["handling_in_cents"] += actual * card["handling_in_cents_per_pallet"]
    touch(inv)
    return ok_object(receipt_view(receipt))


@bp.route("/api/inbound-receipts/<rid>/cancel", methods=["POST"])
def cancel_receipt(rid):
    uid, role = authenticate()
    authorize(role, {"CustomerAdmin", "WarehouseOperator"})
    receipt = get_or_404("receipts", rid, "receipt")
    check_ownership(role, uid, receipt["customer_id"])
    if receipt["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "only a SCHEDULED receipt can be cancelled")
    receipt["status"] = "CANCELLED"
    touch(receipt)
    return ok_object(receipt_view(receipt))
