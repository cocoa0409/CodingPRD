"""Travel Agency Tour Booking API — Flask entry point and routes."""
import os

from flask import Flask, request

import services
from db import db, stamp_create, touch
from errors import ApiError, err
from middleware import get_user_context, require_role
from money import parse_iso
from response import error_response, list_response, success

app = Flask(__name__)

VALID_KINDS = {"FLIGHT", "HOTEL", "ACTIVITY"}
VALID_COVERAGE = {"BASIC", "PREMIUM"}
VALID_METHODS = {"CARD", "WALLET", "BANK_TRANSFER"}
VALID_REFUND_DEST = {"WALLET", "ORIGINAL"}


# =========================================================================
# Error handling
# =========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


# =========================================================================
# Request body / param helpers
# =========================================================================
def body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_string(data, field):
    require_fields(data, [field])
    val = data[field]
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return val


def require_int(data, field):
    require_fields(data, [field])
    val = data[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    return val


def parse_pagination():
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(items):
    """Sort by created_at asc then apply limit/offset; returns list_response."""
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, limit, offset, total)


# =========================================================================
# Lookup helpers (scoped existence, ERR_NOT_FOUND)
# =========================================================================
def get_or_404(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return obj


def booking_agency_id(booking):
    return booking["agency_id"]


# =========================================================================
# Agency
# =========================================================================
@app.route("/agencies", methods=["POST"])
def create_agency():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin"})
    data = body()
    name = require_string(data, "name")
    currency = data.get("currency", "USD")
    if currency is None:
        currency = "USD"
    if not isinstance(currency, str) or currency == "":
        raise err("ERR_INVALID_REQUEST", "currency must be a non-empty string.")
    agency = {
        "name": name,
        "currency": currency,
        "now_utc": "1970-01-01T00:00:00.000Z",
    }
    stamp_create(agency)
    db.agencies[agency["id"]] = agency
    return success(agency, status=201)


@app.route("/agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer", "Supplier"})
    agency = get_or_404(db.agencies, agency_id)
    return success(agency, status=200)


@app.route("/agencies/<agency_id>/_clock/set", methods=["POST"])
def set_clock(agency_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin"})
    agency = get_or_404(db.agencies, agency_id)
    data = body()
    now_utc = require_string(data, "now_utc")
    try:
        parse_iso(now_utc)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "now_utc must be a valid ISO 8601 timestamp.")
    agency["now_utc"] = now_utc
    touch(agency)
    return success(agency, status=200)


# =========================================================================
# Customer
# =========================================================================
@app.route("/agencies/customers", methods=["POST"])
def create_customer():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent"})
    data = body()
    agency_id = require_string(data, "agency_id")
    email = require_string(data, "email")
    full_name = require_string(data, "full_name")
    if agency_id not in db.agencies:
        raise err("ERR_INVALID_REFERENCE", "agency_id does not resolve.")
    for c in db.customers.values():
        if c["agency_id"] == agency_id and c["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "Email already used in this agency.")
    customer = {
        "agency_id": agency_id,
        "email": email,
        "full_name": full_name,
        "wallet_credit_cents": 0,
    }
    stamp_create(customer)
    db.customers[customer["id"]] = customer
    return success(customer, status=201)


@app.route("/agencies/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    customer = get_or_404(db.customers, customer_id)
    return success(customer, status=200)


@app.route("/agencies/customers", methods=["GET"])
def list_customers():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent"})
    agency_id = request.args.get("agency_id")
    email = request.args.get("email")
    items = list(db.customers.values())
    if agency_id is not None:
        items = [c for c in items if c["agency_id"] == agency_id]
    if email is not None:
        items = [c for c in items if c["email"] == email]
    return paginate(items)


# =========================================================================
# Supplier
# =========================================================================
@app.route("/agencies/suppliers", methods=["POST"])
def create_supplier():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin"})
    data = body()
    agency_id = require_string(data, "agency_id")
    name = require_string(data, "name")
    kind = require_string(data, "kind")
    if kind not in VALID_KINDS:
        raise err("ERR_INVALID_REQUEST", "kind must be FLIGHT, HOTEL, or ACTIVITY.")
    auto_confirm = data.get("auto_confirm", False)
    if auto_confirm is None:
        auto_confirm = False
    if not isinstance(auto_confirm, bool):
        raise err("ERR_INVALID_REQUEST", "auto_confirm must be a boolean.")
    if agency_id not in db.agencies:
        raise err("ERR_INVALID_REFERENCE", "agency_id does not resolve.")
    supplier = {
        "agency_id": agency_id,
        "name": name,
        "kind": kind,
        "auto_confirm": auto_confirm,
    }
    stamp_create(supplier)
    db.suppliers[supplier["id"]] = supplier
    return success(supplier, status=201)


@app.route("/agencies/suppliers/<supplier_id>", methods=["GET"])
def get_supplier(supplier_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Supplier"})
    supplier = get_or_404(db.suppliers, supplier_id)
    return success(supplier, status=200)


@app.route("/agencies/suppliers", methods=["GET"])
def list_suppliers():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent"})
    agency_id = request.args.get("agency_id")
    kind = request.args.get("kind")
    items = list(db.suppliers.values())
    if agency_id is not None:
        items = [s for s in items if s["agency_id"] == agency_id]
    if kind is not None:
        items = [s for s in items if s["kind"] == kind]
    return paginate(items)


# =========================================================================
# Tour Package
# =========================================================================
@app.route("/agencies/tour-packages", methods=["POST"])
def create_tour_package():
    _, role = get_user_context()
    require_role(role, {"TravelAgent"})
    data = body()
    agency_id = require_string(data, "agency_id")
    title = require_string(data, "title")
    base_price = require_int(data, "base_price_per_person_cents")
    if base_price <= 0:
        raise err("ERR_INVALID_REQUEST", "base_price_per_person_cents must be > 0.")

    deposit_pct = data.get("deposit_pct", 20)
    if deposit_pct is None:
        deposit_pct = 20
    if isinstance(deposit_pct, bool) or not isinstance(deposit_pct, int):
        raise err("ERR_INVALID_REQUEST", "deposit_pct must be an integer.")
    if deposit_pct < 1 or deposit_pct > 100:
        raise err("ERR_INVALID_REQUEST", "deposit_pct must be between 1 and 100.")

    balance_days = data.get("balance_due_days_before_departure", 30)
    if balance_days is None:
        balance_days = 30
    if isinstance(balance_days, bool) or not isinstance(balance_days, int):
        raise err("ERR_INVALID_REQUEST", "balance_due_days_before_departure must be an integer.")
    if balance_days < 0:
        raise err("ERR_INVALID_REQUEST", "balance_due_days_before_departure must be >= 0.")

    min_group = data.get("min_group_size_for_discount", 5)
    if min_group is None:
        min_group = 5
    if isinstance(min_group, bool) or not isinstance(min_group, int):
        raise err("ERR_INVALID_REQUEST", "min_group_size_for_discount must be an integer.")

    if agency_id not in db.agencies:
        raise err("ERR_INVALID_REFERENCE", "agency_id does not resolve.")

    pkg = {
        "agency_id": agency_id,
        "title": title,
        "base_price_per_person_cents": base_price,
        "deposit_pct": deposit_pct,
        "balance_due_days_before_departure": balance_days,
        "min_group_size_for_discount": min_group,
        "status": "DRAFT",
    }
    stamp_create(pkg)
    db.tour_packages[pkg["id"]] = pkg
    return success(pkg, status=201)


@app.route("/agencies/tour-packages/<package_id>", methods=["GET"])
def get_tour_package(package_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    pkg = get_or_404(db.tour_packages, package_id)
    return success(pkg, status=200)


@app.route("/agencies/tour-packages", methods=["GET"])
def list_tour_packages():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    agency_id = request.args.get("agency_id")
    status = request.args.get("status")
    items = list(db.tour_packages.values())
    if agency_id is not None:
        items = [p for p in items if p["agency_id"] == agency_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items)


@app.route("/agencies/tour-packages/<package_id>/publish", methods=["POST"])
def publish_tour_package(package_id):
    _, role = get_user_context()
    require_role(role, {"TravelAgent"})
    pkg = get_or_404(db.tour_packages, package_id)
    if pkg["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Package is not DRAFT.")
    if pkg["base_price_per_person_cents"] <= 0:
        raise err("ERR_INVALID_REQUEST", "base_price_per_person_cents must be > 0.")
    pkg["status"] = "PUBLISHED"
    touch(pkg)
    return success(pkg, status=200)


@app.route("/agencies/tour-packages/<package_id>/retire", methods=["POST"])
def retire_tour_package(package_id):
    _, role = get_user_context()
    require_role(role, {"TravelAgent"})
    pkg = get_or_404(db.tour_packages, package_id)
    if pkg["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Package is not PUBLISHED.")
    for b in db.bookings.values():
        if b["tour_package_id"] == package_id and b["status"] in ("DRAFT", "RESERVED"):
            raise err(
                "ERR_PACKAGE_HAS_OPEN_BOOKINGS",
                "Package has DRAFT/RESERVED bookings.",
            )
    pkg["status"] = "RETIRED"
    touch(pkg)
    return success(pkg, status=200)


# =========================================================================
# Booking
# =========================================================================
@app.route("/agencies/bookings", methods=["POST"])
def create_booking():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent"})
    data = body()
    agency_id = require_string(data, "agency_id")
    customer_id = require_string(data, "customer_id")
    tour_package_id = require_string(data, "tour_package_id")
    departure_date = require_string(data, "departure_date")
    try:
        parse_iso(departure_date)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "departure_date must be a valid ISO 8601 timestamp.")

    if agency_id not in db.agencies:
        raise err("ERR_INVALID_REFERENCE", "agency_id does not resolve.")
    customer = db.customers.get(customer_id)
    if customer is None or customer["agency_id"] != agency_id:
        raise err("ERR_INVALID_REFERENCE", "customer_id does not resolve in agency.")
    pkg = db.tour_packages.get(tour_package_id)
    if pkg is None or pkg["agency_id"] != agency_id:
        raise err("ERR_INVALID_REFERENCE", "tour_package_id does not resolve in agency.")
    if pkg["status"] != "PUBLISHED":
        raise err("ERR_PACKAGE_NOT_PUBLISHED", "Package is not PUBLISHED.")

    booking = {
        "agency_id": agency_id,
        "customer_id": customer_id,
        "tour_package_id": tour_package_id,
        "departure_date": departure_date,
        "traveler_count": 0,
        "subtotal_cents": 0,
        "insurance_premium_cents": 0,
        "grand_total_cents": 0,
        "paid_cents": 0,
        "status": "DRAFT",
        "payment_status": "UNPAID",
    }
    stamp_create(booking)
    db.bookings[booking["id"]] = booking
    return success(booking, status=201)


@app.route("/agencies/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    user_id, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    booking = get_or_404(db.bookings, booking_id)
    if role == "Customer" and booking["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Customer does not own this booking.")
    return success(booking, status=200)


@app.route("/agencies/bookings", methods=["GET"])
def list_bookings():
    user_id, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    agency_id = request.args.get("agency_id")
    customer_id = request.args.get("customer_id")
    tour_package_id = request.args.get("tour_package_id")
    status = request.args.get("status")
    items = list(db.bookings.values())
    if role == "Customer":
        items = [b for b in items if b["customer_id"] == user_id]
    if agency_id is not None:
        items = [b for b in items if b["agency_id"] == agency_id]
    if customer_id is not None:
        items = [b for b in items if b["customer_id"] == customer_id]
    if tour_package_id is not None:
        items = [b for b in items if b["tour_package_id"] == tour_package_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate(items)


def check_occ(booking, data):
    """ERR_STALE_VERSION when expected_booking_version mismatches."""
    require_fields(data, ["expected_booking_version"])
    expected = data["expected_booking_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_booking_version must be an integer.")
    if expected != booking["version"]:
        raise err("ERR_STALE_VERSION", "expected_booking_version is stale.")


@app.route("/agencies/bookings/<booking_id>/reserve", methods=["POST"])
def reserve_booking(booking_id):
    _, role = get_user_context()
    require_role(role, {"TravelAgent"})
    booking = get_or_404(db.bookings, booking_id)
    data = body()
    check_occ(booking, data)
    if booking["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Booking is not DRAFT.")
    pkg = db.tour_packages[booking["tour_package_id"]]
    if pkg["status"] != "PUBLISHED":
        raise err("ERR_PACKAGE_NOT_PUBLISHED", "Package is not PUBLISHED.")
    if booking["traveler_count"] < 1:
        raise err("ERR_NO_TRAVELERS", "Booking has no travelers.")
    mandatory = [
        c
        for c in db.components.values()
        if c["booking_id"] == booking_id
        and c["is_mandatory"]
        and c["status"] in ("REQUESTED", "CONFIRMED")
    ]
    if not mandatory:
        raise err("ERR_NO_COMPONENTS", "Booking has no mandatory components.")

    # Finalized quote: freeze totals from current travelers/policies.
    services.recompute_draft_quote(booking)
    booking["status"] = "RESERVED"
    services.generate_milestones(booking, pkg)
    services.recompute_payment_status(booking)
    touch(booking)
    return success(booking, status=200)


@app.route("/agencies/bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    _, role = get_user_context()
    require_role(role, {"TravelAgent"})
    booking = get_or_404(db.bookings, booking_id)
    data = body()
    check_occ(booking, data)
    if booking["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Booking is not RESERVED.")
    mandatory = [
        c
        for c in db.components.values()
        if c["booking_id"] == booking_id and c["is_mandatory"]
    ]
    for c in mandatory:
        if c["status"] != "CONFIRMED":
            raise err(
                "ERR_COMPONENTS_NOT_CONFIRMED",
                "Not all mandatory components are CONFIRMED.",
            )
    deposit = services.milestone_by_kind(booking_id, "DEPOSIT")
    if deposit is None or deposit["status"] != "SETTLED":
        raise err("ERR_DEPOSIT_NOT_SETTLED", "DEPOSIT milestone is not SETTLED.")
    booking["status"] = "CONFIRMED"
    touch(booking)
    return success(booking, status=200)


@app.route("/agencies/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer", "TravelAgent"})
    booking = get_or_404(db.bookings, booking_id)
    if role == "Customer" and booking["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Customer does not own this booking.")
    data = body()
    check_occ(booking, data)
    if booking["status"] not in ("DRAFT", "RESERVED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Booking is in a terminal state.")
    refund_destination = data.get("refund_destination", "ORIGINAL")
    if refund_destination is None:
        refund_destination = "ORIGINAL"
    if refund_destination not in VALID_REFUND_DEST:
        raise err("ERR_INVALID_REQUEST", "refund_destination must be WALLET or ORIGINAL.")
    services.cancel_sweep(booking, refund_destination)
    return success(booking, status=200)


# =========================================================================
# Traveler
# =========================================================================
@app.route("/agencies/bookings/<booking_id>/travelers", methods=["POST"])
def add_traveler(booking_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent"})
    booking = get_or_404(db.bookings, booking_id)
    data = body()
    full_name = require_string(data, "full_name")
    passport_no = data.get("passport_no")
    if passport_no is not None and not isinstance(passport_no, str):
        raise err("ERR_INVALID_REQUEST", "passport_no must be a string.")
    check_occ(booking, data)
    if booking["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Booking is not DRAFT.")

    is_first = booking["traveler_count"] == 0
    traveler = {
        "booking_id": booking_id,
        "full_name": full_name,
        "is_lead": True if is_first else False,
        "passport_no": passport_no,
    }
    stamp_create(traveler)
    db.travelers[traveler["id"]] = traveler

    booking["traveler_count"] += 1
    services.recompute_draft_quote(booking)
    touch(booking)
    return success(traveler, status=201)


@app.route("/agencies/travelers/<traveler_id>", methods=["GET"])
def get_traveler(traveler_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    traveler = get_or_404(db.travelers, traveler_id)
    return success(traveler, status=200)


@app.route("/agencies/travelers", methods=["GET"])
def list_travelers():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    booking_id = request.args.get("booking_id")
    items = list(db.travelers.values())
    if booking_id is not None:
        items = [t for t in items if t["booking_id"] == booking_id]
    return paginate(items)


# =========================================================================
# Booking Component
# =========================================================================
@app.route("/agencies/components", methods=["POST"])
def create_component():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent"})
    data = body()
    booking_id = require_string(data, "booking_id")
    supplier_id = require_string(data, "supplier_id")
    kind = require_string(data, "kind")
    if kind not in VALID_KINDS:
        raise err("ERR_INVALID_REQUEST", "kind must be FLIGHT, HOTEL, or ACTIVITY.")
    starts_at = require_string(data, "starts_at")
    ends_at = require_string(data, "ends_at")
    try:
        starts_dt = parse_iso(starts_at)
        ends_dt = parse_iso(ends_at)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "starts_at/ends_at must be ISO 8601 timestamps.")
    is_mandatory = data.get("is_mandatory", True)
    if is_mandatory is None:
        is_mandatory = True
    if not isinstance(is_mandatory, bool):
        raise err("ERR_INVALID_REQUEST", "is_mandatory must be a boolean.")

    # Referential: booking + supplier resolve in same agency; supplier.kind==kind.
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err("ERR_INVALID_REFERENCE", "booking_id does not resolve.")
    supplier = db.suppliers.get(supplier_id)
    if supplier is None or supplier["agency_id"] != booking["agency_id"]:
        raise err("ERR_INVALID_REFERENCE", "supplier_id does not resolve in agency.")
    if supplier["kind"] != kind:
        raise err("ERR_INVALID_REFERENCE", "supplier.kind must equal component.kind.")

    # State: booking DRAFT or RESERVED.
    if booking["status"] not in ("DRAFT", "RESERVED"):
        raise err("ERR_INVALID_STATE", "Booking is not DRAFT or RESERVED.")

    # Interval.
    if not (ends_dt > starts_dt):
        raise err("ERR_INVALID_INTERVAL", "ends_at must be after starts_at.")

    # Overlap checks.
    if kind == "HOTEL":
        for ex in db.components.values():
            if (
                ex["booking_id"] == booking_id
                and ex["supplier_id"] == supplier_id
                and ex["kind"] == "HOTEL"
                and ex["status"] in ("REQUESTED", "CONFIRMED")
            ):
                ex_start = parse_iso(ex["starts_at"])
                ex_end = parse_iso(ex["ends_at"])
                if starts_dt < ex_end and ex_start < ends_dt:
                    raise err("ERR_COMPONENT_OVERLAP", "HOTEL component overlaps.")
    else:  # FLIGHT or ACTIVITY
        from datetime import timedelta

        buffer = timedelta(seconds=services.BUFFER_SECONDS)
        for ex in db.components.values():
            if (
                ex["supplier_id"] == supplier_id
                and ex["kind"] == kind
                and ex["status"] in ("REQUESTED", "CONFIRMED")
            ):
                ex_start = parse_iso(ex["starts_at"])
                ex_end = parse_iso(ex["ends_at"])
                if starts_dt < (ex_end + buffer) and ex_start < (ends_dt + buffer):
                    raise err(
                        "ERR_SUPPLIER_CAPACITY_CONFLICT",
                        "Supplier capacity conflict within buffer.",
                    )

    component = {
        "booking_id": booking_id,
        "supplier_id": supplier_id,
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "is_mandatory": is_mandatory,
        "status": "CONFIRMED" if supplier["auto_confirm"] else "REQUESTED",
    }
    stamp_create(component)
    db.components[component["id"]] = component
    return success(component, status=201)


@app.route("/agencies/components/<component_id>", methods=["GET"])
def get_component(component_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer", "Supplier"})
    component = get_or_404(db.components, component_id)
    return success(component, status=200)


@app.route("/agencies/components", methods=["GET"])
def list_components():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer", "Supplier"})
    booking_id = request.args.get("booking_id")
    supplier_id = request.args.get("supplier_id")
    status = request.args.get("status")
    kind = request.args.get("kind")
    items = list(db.components.values())
    if booking_id is not None:
        items = [c for c in items if c["booking_id"] == booking_id]
    if supplier_id is not None:
        items = [c for c in items if c["supplier_id"] == supplier_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    return paginate(items)


@app.route("/agencies/components/<component_id>/confirm", methods=["POST"])
def confirm_component(component_id):
    user_id, role = get_user_context()
    require_role(role, {"Supplier"})
    component = get_or_404(db.components, component_id)
    if component["supplier_id"] != user_id:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Supplier does not own this component.")
    booking = db.bookings[component["booking_id"]]
    if booking["status"] not in ("DRAFT", "RESERVED"):
        raise err("ERR_INVALID_STATE", "Parent booking is not DRAFT or RESERVED.")
    if component["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Component is not REQUESTED.")
    component["status"] = "CONFIRMED"
    touch(component)
    return success(component, status=200)


@app.route("/agencies/components/<component_id>/reject", methods=["POST"])
def reject_component(component_id):
    user_id, role = get_user_context()
    require_role(role, {"Supplier"})
    component = get_or_404(db.components, component_id)
    if component["supplier_id"] != user_id:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Supplier does not own this component.")
    booking = db.bookings[component["booking_id"]]
    if booking["status"] not in ("DRAFT", "RESERVED"):
        raise err("ERR_INVALID_STATE", "Parent booking is not DRAFT or RESERVED.")
    if component["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Component is not REQUESTED.")
    component["status"] = "REJECTED"
    touch(component)
    # Bubble-up: mandatory reject while booking RESERVED reopens the booking.
    if component["is_mandatory"] and booking["status"] == "RESERVED":
        services.reopen_booking_on_mandatory_reject(booking)
    return success(component, status=200)


# =========================================================================
# Insurance Policy
# =========================================================================
@app.route("/agencies/insurance-policies", methods=["POST"])
def create_insurance_policy():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent"})
    data = body()
    booking_id = require_string(data, "booking_id")
    coverage_tier = require_string(data, "coverage_tier")
    if coverage_tier not in VALID_COVERAGE:
        raise err("ERR_INVALID_REQUEST", "coverage_tier must be BASIC or PREMIUM.")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err("ERR_INVALID_REFERENCE", "booking_id does not resolve.")
    if booking["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Booking is not DRAFT.")

    premium = services.compute_insurance_premium(
        booking["traveler_count"], coverage_tier
    )
    policy = {
        "booking_id": booking_id,
        "coverage_tier": coverage_tier,
        "premium_cents": premium,
        "refundable": coverage_tier == "PREMIUM",
        "status": "ACTIVE",
    }
    stamp_create(policy)
    db.insurance_policies[policy["id"]] = policy

    services.recompute_draft_quote(booking)
    touch(booking)
    return success(policy, status=201)


@app.route("/agencies/insurance-policies/<policy_id>", methods=["GET"])
def get_insurance_policy(policy_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    policy = get_or_404(db.insurance_policies, policy_id)
    return success(policy, status=200)


@app.route("/agencies/insurance-policies", methods=["GET"])
def list_insurance_policies():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    booking_id = request.args.get("booking_id")
    status = request.args.get("status")
    items = list(db.insurance_policies.values())
    if booking_id is not None:
        items = [p for p in items if p["booking_id"] == booking_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items)


# =========================================================================
# Payment Milestones
# =========================================================================
@app.route("/agencies/milestones/<milestone_id>", methods=["GET"])
def get_milestone(milestone_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    milestone = get_or_404(db.milestones, milestone_id)
    return success(milestone, status=200)


@app.route("/agencies/milestones", methods=["GET"])
def list_milestones():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    booking_id = request.args.get("booking_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = list(db.milestones.values())
    if booking_id is not None:
        items = [m for m in items if m["booking_id"] == booking_id]
    if kind is not None:
        items = [m for m in items if m["kind"] == kind]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return paginate(items)


# =========================================================================
# Payments
# =========================================================================
@app.route("/agencies/payments", methods=["POST"])
def create_payment():
    user_id, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    data = body()
    booking_id = require_string(data, "booking_id")
    milestone_id = require_string(data, "milestone_id")
    amount_cents = require_int(data, "amount_cents")
    if amount_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0.")
    method = data.get("method", "CARD")
    if method is None:
        method = "CARD"
    if method not in VALID_METHODS:
        raise err("ERR_INVALID_REQUEST", "method must be CARD, WALLET, or BANK_TRANSFER.")

    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err("ERR_INVALID_REFERENCE", "booking_id does not resolve.")
    # Customer ownership.
    if role == "Customer" and booking["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Customer does not own this booking.")
    milestone = db.milestones.get(milestone_id)
    if milestone is None or milestone["booking_id"] != booking_id:
        raise err("ERR_INVALID_REFERENCE", "milestone_id does not resolve for booking.")

    # State gate before fiscal checks (priority: state p6 beats fiscal p11/p12).
    if booking["status"] not in ("RESERVED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Booking is not RESERVED or CONFIRMED.")

    # Overpayment check (p11) before deposit ordering (p12)? PRD lists overpayment
    # p11 then deposit-ordering p12; honor that priority order.
    remaining = milestone["amount_due_cents"] - milestone["settled_amount_cents"]
    if amount_cents > remaining:
        raise err("ERR_OVERPAYMENT", "Payment exceeds milestone remaining due.")

    if milestone["kind"] == "BALANCE":
        deposit = services.milestone_by_kind(booking_id, "DEPOSIT")
        if deposit is None or deposit["status"] != "SETTLED":
            raise err("ERR_DEPOSIT_NOT_SETTLED", "DEPOSIT milestone is not SETTLED.")

    payment = {
        "booking_id": booking_id,
        "milestone_id": milestone_id,
        "amount_cents": amount_cents,
        "method": method,
        "status": "APPLIED",
    }
    stamp_create(payment)
    db.payments[payment["id"]] = payment

    milestone["settled_amount_cents"] += amount_cents
    services.refresh_milestone_status(milestone)
    touch(milestone)
    services.recompute_paid_cents(booking)
    services.recompute_payment_status(booking)
    touch(booking)
    return success(payment, status=201)


@app.route("/agencies/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    payment = get_or_404(db.payments, payment_id)
    return success(payment, status=200)


@app.route("/agencies/payments", methods=["GET"])
def list_payments():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    booking_id = request.args.get("booking_id")
    milestone_id = request.args.get("milestone_id")
    status = request.args.get("status")
    items = list(db.payments.values())
    if booking_id is not None:
        items = [p for p in items if p["booking_id"] == booking_id]
    if milestone_id is not None:
        items = [p for p in items if p["milestone_id"] == milestone_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items)


# =========================================================================
# Cancellation Records
# =========================================================================
@app.route("/agencies/cancellation-records/<record_id>", methods=["GET"])
def get_cancellation_record(record_id):
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    record = get_or_404(db.cancellation_records, record_id)
    return success(record, status=200)


@app.route("/agencies/cancellation-records", methods=["GET"])
def list_cancellation_records():
    _, role = get_user_context()
    require_role(role, {"AgencyAdmin", "TravelAgent", "Customer"})
    booking_id = request.args.get("booking_id")
    items = list(db.cancellation_records.values())
    if booking_id is not None:
        items = [r for r in items if r["booking_id"] == booking_id]
    return paginate(items)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
