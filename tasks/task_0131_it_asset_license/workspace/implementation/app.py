"""IT Asset & License API — Flask entry point (PRD-driven).

Single-module route layer for simplicity; business logic delegates to
calculations.py, derive.py, and the per-entity helpers below. All storage is
in-memory (db.py) and wiped on every fresh process boot.
"""
import os

from flask import Flask, request

import db
import clock
import auth
import derive
import serialize
import calculations
import validate as V
from errors import ApiError, err
from listing import paginate
from response import success, success_list, error as error_response
from timeutil import parse_iso, add_months

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# Error handling                                                              #
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    # Method not allowed on a known path — treat as a not-found-style miss.
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 422, "Unhandled error: %s" % e)


def body():
    """Parse the JSON request body, tolerating an empty body as {}."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# --------------------------------------------------------------------------- #
# Existence lookups (priority 3: ERR_NOT_FOUND, left-to-right)                #
# --------------------------------------------------------------------------- #
def _get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Entity %s not found" % _id)
    return rec


def get_vendor(_id):
    return _get_or_404(db.vendors, _id)


def get_employee(_id):
    return _get_or_404(db.employees, _id)


def get_product(_id):
    return _get_or_404(db.software_products, _id)


def get_asset(_id):
    return _get_or_404(db.hardware_assets, _id)


def get_coverage(_id):
    return _get_or_404(db.warranty_leases, _id)


def get_entitlement(_id):
    return _get_or_404(db.license_entitlements, _id)


def get_install(_id):
    return _get_or_404(db.installation_records, _id)


def get_checkout(_id):
    return _get_or_404(db.assignment_checkouts, _id)


def get_disposal(_id):
    return _get_or_404(db.disposal_requests, _id)


def get_renewal(_id):
    return _get_or_404(db.renewal_orders, _id)


def get_true_up(_id):
    return _get_or_404(db.true_up_reconciliations, _id)


def get_finding(_id):
    return _get_or_404(db.compliance_findings, _id)


# --------------------------------------------------------------------------- #
# Server clock                                                                #
# --------------------------------------------------------------------------- #
@app.route("/assets/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    data = body()
    if "to_iso8601" not in data or data.get("to_iso8601") is None:
        raise err("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required")
    dt = parse_iso(data["to_iso8601"])
    clock.set_now(dt)
    from timeutil import format_iso

    return success({"current_utc": format_iso(dt)}, 200)


# --------------------------------------------------------------------------- #
# Vendor                                                                      #
# --------------------------------------------------------------------------- #
@app.route("/assets/vendors", methods=["POST"])
def create_vendor():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    rec = {
        "name": V.req_str(data, "name"),
        "vendor_type": V.req_enum(data, "vendor_type", {"HARDWARE", "SOFTWARE", "BOTH"}),
        "support_email": V.req_str(data, "support_email"),
        "active": V.opt_bool(data, "active", True),
    }
    db.new_common(rec)
    db.vendors[rec["id"]] = rec
    return success(serialize.vendor(rec), 201)


@app.route("/assets/vendors/<_id>", methods=["GET"])
def read_vendor(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.vendor(get_vendor(_id)), 200)


# --------------------------------------------------------------------------- #
# Employee                                                                    #
# --------------------------------------------------------------------------- #
@app.route("/assets/employees", methods=["POST"])
def create_employee():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    full_name = V.req_str(data, "full_name")
    email = V.req_str(data, "email")
    department = V.req_str(data, "department")
    max_assigned = V.opt_int(data, "max_assigned_assets", 3, min_value=0)
    # Email unique among non-OFFBOARDED employees (priority 15).
    for e in db.employees.values():
        if e["status"] != "OFFBOARDED" and e["email"] == email:
            raise err("ERR_DUPLICATE_KEY", "Employee email already in use")
    rec = {
        "full_name": full_name,
        "email": email,
        "department": department,
        "max_assigned_assets": max_assigned,
        "status": "ACTIVE",
        "open_checkout_count": 0,
    }
    db.new_common(rec)
    db.employees[rec["id"]] = rec
    return success(serialize.employee(rec), 201)


@app.route("/assets/employees/<_id>", methods=["GET"])
def read_employee(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer", "Employee"})
    emp = get_employee(_id)
    return success(serialize.employee(emp), 200)


@app.route("/assets/employees/<_id>/transition", methods=["POST"])
def transition_employee(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    emp = get_employee(_id)
    data = body()
    to_status = V.req_enum(data, "to_status", {"ACTIVE", "SUSPENDED", "OFFBOARDED"})
    emp["status"] = to_status
    db.touch(emp)
    return success(serialize.employee(emp), 200)


# --------------------------------------------------------------------------- #
# SoftwareProduct                                                             #
# --------------------------------------------------------------------------- #
@app.route("/assets/software-products", methods=["POST"])
def create_product():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    vendor_id = V.req_str(data, "vendor_id")
    name = V.req_str(data, "name")
    license_model = V.req_enum(data, "license_model", {"PER_SEAT", "PER_CORE"})
    # Existence (priority 3) before well-formedness completes.
    get_vendor(vendor_id)
    core_factor = V.opt_number(data, "core_factor", 1.0, min_value=0)
    min_core_units = V.opt_int(data, "min_core_units", 1, min_value=1)
    rec = {
        "vendor_id": vendor_id,
        "name": name,
        "license_model": license_model,
        "core_factor": core_factor,
        "min_core_units": min_core_units,
        "compliance_status": "COMPLIANT",
    }
    db.new_common(rec)
    db.software_products[rec["id"]] = rec
    return success(serialize.software_product(rec), 201)


@app.route("/assets/software-products/<_id>", methods=["GET"])
def read_product(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.software_product(get_product(_id)), 200)


@app.route("/assets/software-products", methods=["GET"])
def list_products():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    vendor_id = request.args.get("vendor_id")
    license_model = request.args.get("license_model")
    records = [
        p
        for p in db.software_products.values()
        if (vendor_id is None or p["vendor_id"] == vendor_id)
        and (license_model is None or p["license_model"] == license_model)
    ]
    items, limit, offset, total = paginate(records, serialize.software_product)
    return success_list(items, limit, offset, total)


# --------------------------------------------------------------------------- #
# LicenseEntitlement                                                          #
# --------------------------------------------------------------------------- #
@app.route("/assets/entitlements", methods=["POST"])
def create_entitlement():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    software_product_id = V.req_str(data, "software_product_id")
    vendor_id = V.req_str(data, "vendor_id")
    # Existence left-to-right (priority 3).
    get_product(software_product_id)
    get_vendor(vendor_id)
    entitled_units = V.req_int(data, "entitled_units", min_value=0)
    unit_price_cents = V.req_int(data, "unit_price_cents", min_value=0)
    term_start = parse_iso(data.get("term_start")) if data.get("term_start") is not None else None
    term_end = parse_iso(data.get("term_end")) if data.get("term_end") is not None else None
    if term_start is None or term_end is None:
        raise err("ERR_INVALID_REQUEST", "term_start and term_end are required")
    grace_days = V.opt_int(data, "grace_days", 0, min_value=0)
    rec = {
        "software_product_id": software_product_id,
        "vendor_id": vendor_id,
        "entitled_units": entitled_units,
        "unit_price_cents": unit_price_cents,
        "term_start": term_start,
        "term_end": term_end,
        "grace_days": grace_days,
        "status": "DRAFT",
        "consumed_units": 0,
        "available_units": entitled_units,
    }
    db.new_common(rec)
    db.license_entitlements[rec["id"]] = rec
    return success(serialize.license_entitlement(rec), 201)


@app.route("/assets/entitlements/<_id>", methods=["GET"])
def read_entitlement(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.license_entitlement(get_entitlement(_id)), 200)


@app.route("/assets/entitlements", methods=["GET"])
def list_entitlements():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    spid = request.args.get("software_product_id")
    vid = request.args.get("vendor_id")
    status = request.args.get("status")
    records = [
        e
        for e in db.license_entitlements.values()
        if (spid is None or e["software_product_id"] == spid)
        and (vid is None or e["vendor_id"] == vid)
        and (status is None or e["status"] == status)
    ]
    items, limit, offset, total = paginate(records, serialize.license_entitlement)
    return success_list(items, limit, offset, total)


@app.route("/assets/entitlements/<_id>/activate", methods=["POST"])
def activate_entitlement(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    ent = get_entitlement(_id)
    # State (priority 5).
    if ent["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Entitlement must be DRAFT to activate")
    # Term window well-formed (PRD 3.4).
    if ent["term_start"] > ent["term_end"]:
        raise err("ERR_INVALID_TERM_WINDOW", "term_start must be <= term_end")
    ent["status"] = "ACTIVE"
    db.touch(ent)
    return success(serialize.license_entitlement(ent), 200)


@app.route("/assets/entitlements/<_id>/transition", methods=["POST"])
def transition_entitlement(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    ent = get_entitlement(_id)
    data = body()
    to_status = V.req_enum(data, "to_status", {"SUSPENDED", "ACTIVE", "EXPIRED"})

    if to_status == "SUSPENDED":
        if ent["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Only ACTIVE entitlements can be suspended")
        ent["status"] = "SUSPENDED"
        db.touch(ent)
        # Cascade up to product (PRD 3.4).
        product = db.software_products.get(ent["software_product_id"])
        if product is not None:
            product["compliance_status"] = "UNDER_REVIEW"
            db.touch(product)
    elif to_status == "ACTIVE":
        if ent["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", "Only SUSPENDED entitlements can be resumed")
        ent["status"] = "ACTIVE"
        db.touch(ent)
        product = db.software_products.get(ent["software_product_id"])
        if product is not None:
            product["compliance_status"] = "COMPLIANT"
            db.touch(product)
    else:  # EXPIRED
        if ent["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_INVALID_STATE", "Only ACTIVE/SUSPENDED entitlements can be expired")
        # Temporal: clock must be strictly past term_end (PRD 3.4).
        if not (clock.get_now() > ent["term_end"]):
            raise err("ERR_TERM_NOT_ENDED", "Clock has not passed term_end")
        ent["status"] = "EXPIRED"
        db.touch(ent)
        # Cascade: every ACTIVE install charged to this entitlement -> UNINSTALLED.
        for inst in db.installation_records.values():
            if inst["license_entitlement_id"] == ent["id"] and inst["status"] == "ACTIVE":
                inst["status"] = "UNINSTALLED"
                db.touch(inst)
                ent["consumed_units"] -= inst["required_core_units"]
        derive.recompute_entitlement_units(ent)
        db.touch(ent)
    return success(serialize.license_entitlement(ent), 200)


# --------------------------------------------------------------------------- #
# HardwareAsset                                                               #
# --------------------------------------------------------------------------- #
@app.route("/assets/hardware", methods=["POST"])
def create_hardware():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    vendor_id = V.req_str(data, "vendor_id")
    asset_tag = V.req_str(data, "asset_tag")
    category = V.req_enum(data, "category", {"LAPTOP", "DESKTOP", "SERVER", "MONITOR", "MOBILE"})
    get_vendor(vendor_id)
    physical_cores = V.opt_int(data, "physical_cores", 0, min_value=0)
    purchase_cost_cents = V.req_int(data, "purchase_cost_cents", min_value=0)
    if data.get("in_service_date") is None:
        raise err("ERR_INVALID_REQUEST", "in_service_date is required")
    in_service_date = parse_iso(data["in_service_date"])
    useful_life_months = V.opt_int(data, "useful_life_months", 36, min_value=1)
    salvage_value_cents = V.opt_int(data, "salvage_value_cents", 0, min_value=0)
    if salvage_value_cents > purchase_cost_cents:
        raise err("ERR_INVALID_REQUEST", "salvage_value_cents must be <= purchase_cost_cents")
    rec = {
        "vendor_id": vendor_id,
        "asset_tag": asset_tag,
        "category": category,
        "physical_cores": physical_cores,
        "purchase_cost_cents": purchase_cost_cents,
        "in_service_date": in_service_date,
        "useful_life_months": useful_life_months,
        "salvage_value_cents": salvage_value_cents,
        "status": "IN_STOCK",
        "support_status": "UNCOVERED",
        "accumulated_depreciation_cents": 0,
        "net_book_value_cents": purchase_cost_cents,
        "disposal_proceeds_cents": 0,
        "disposal_gain_loss_cents": 0,
    }
    # asset_tag unique among non-DISPOSED assets (priority 15).
    for a in db.hardware_assets.values():
        if a["status"] != "DISPOSED" and a["asset_tag"] == asset_tag:
            raise err("ERR_DUPLICATE_KEY", "asset_tag already in use")
    db.new_common(rec)
    # Compute provisional depreciation against the clock at creation.
    derive.recompute_asset_depreciation(rec)
    db.hardware_assets[rec["id"]] = rec
    return success(serialize.hardware_asset(rec), 201)


@app.route("/assets/hardware/<_id>", methods=["GET"])
def read_hardware(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer", "Employee"})
    asset = get_asset(_id)
    derive.refresh_asset_on_read(asset)
    return success(serialize.hardware_asset(asset), 200)


@app.route("/assets/hardware", methods=["GET"])
def list_hardware():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    category = request.args.get("category")
    records = [
        a
        for a in db.hardware_assets.values()
        if (vendor_id is None or a["vendor_id"] == vendor_id)
        and (status is None or a["status"] == status)
        and (category is None or a["category"] == category)
    ]
    # Refresh provisional fields for each returned record.
    for a in records:
        derive.refresh_asset_on_read(a)
    items, limit, offset, total = paginate(records, serialize.hardware_asset)
    return success_list(items, limit, offset, total)


@app.route("/assets/hardware/<_id>/transition", methods=["POST"])
def transition_hardware(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    asset = get_asset(_id)
    data = body()
    to_status = V.req_enum(data, "to_status", {"IN_STOCK", "IN_REPAIR"})
    if to_status == "IN_REPAIR":
        if asset["status"] != "IN_STOCK":
            raise err("ERR_INVALID_STATE", "Only IN_STOCK assets can go to IN_REPAIR")
        asset["status"] = "IN_REPAIR"
    else:  # IN_STOCK
        if asset["status"] != "IN_REPAIR":
            raise err("ERR_INVALID_STATE", "Only IN_REPAIR assets can return to IN_STOCK")
        asset["status"] = "IN_STOCK"
    db.touch(asset)
    derive.refresh_asset_on_read(asset)
    return success(serialize.hardware_asset(asset), 200)


@app.route("/assets/hardware/<_id>/checkout", methods=["POST"])
def checkout_hardware(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    asset = get_asset(_id)
    data = body()
    employee_id = V.req_str(data, "employee_id")
    employee = get_employee(employee_id)
    if data.get("checkout_at") is None or data.get("expected_return_at") is None:
        raise err("ERR_INVALID_REQUEST", "checkout_at and expected_return_at are required")
    checkout_at = parse_iso(data["checkout_at"])
    expected_return_at = parse_iso(data["expected_return_at"])

    # State (priority 5 family): asset must be IN_STOCK.
    if asset["status"] != "IN_STOCK":
        raise err("ERR_ASSET_NOT_AVAILABLE", "Asset is not IN_STOCK")
    # Referential (priority 9): employee must be ACTIVE.
    if employee["status"] != "ACTIVE":
        raise err("ERR_EMPLOYEE_NOT_ACTIVE", "Employee is not ACTIVE")
    # Temporal (priority 12): half-open interval overlap with existing OPEN checkouts.
    for c in db.assignment_checkouts.values():
        if c["hardware_asset_id"] != asset["id"] or c["status"] != "OPEN":
            continue
        if checkout_at < c["expected_return_at"] and c["checkout_at"] < expected_return_at:
            raise err("ERR_CHECKOUT_OVERLAP", "Checkout interval overlaps an existing OPEN checkout")
    # Capacity (priority 16): open_checkout_count strictly < max_assigned_assets.
    open_count = derive.employee_open_checkout_count(employee_id)
    if open_count >= employee["max_assigned_assets"]:
        raise err("ERR_ASSIGNMENT_LIMIT_REACHED", "Employee assignment limit reached")

    rec = {
        "hardware_asset_id": asset["id"],
        "employee_id": employee_id,
        "checkout_at": checkout_at,
        "expected_return_at": expected_return_at,
        "returned_at": None,
        "status": "OPEN",
    }
    db.new_common(rec)
    db.assignment_checkouts[rec["id"]] = rec
    asset["status"] = "ASSIGNED"
    db.touch(asset)
    db.touch(employee)  # open_checkout_count derived field changed (PRD 2.6).
    return success(serialize.assignment_checkout(rec), 201)


# --------------------------------------------------------------------------- #
# AssignmentCheckout                                                          #
# --------------------------------------------------------------------------- #
@app.route("/assets/checkouts/<_id>", methods=["GET"])
def read_checkout(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer", "Employee"})
    c = get_checkout(_id)
    return success(serialize.assignment_checkout(c), 200)


@app.route("/assets/checkouts", methods=["GET"])
def list_checkouts():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer", "Employee"})
    asset_id = request.args.get("hardware_asset_id")
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    records = []
    for c in db.assignment_checkouts.values():
        if asset_id is not None and c["hardware_asset_id"] != asset_id:
            continue
        if employee_id is not None and c["employee_id"] != employee_id:
            continue
        if status is not None and c["status"] != status:
            continue
        # Employee role sees only their own checkouts (PRD 3.3).
        if caller.role == "Employee" and c["employee_id"] != caller.user_id:
            continue
        records.append(c)
    items, limit, offset, total = paginate(records, serialize.assignment_checkout)
    return success_list(items, limit, offset, total)


@app.route("/assets/checkouts/<_id>/return", methods=["POST"])
def return_checkout(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    c = get_checkout(_id)
    if c["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only OPEN checkouts can be returned")
    c["status"] = "RETURNED"
    c["returned_at"] = clock.get_now()
    db.touch(c)
    asset = db.hardware_assets.get(c["hardware_asset_id"])
    if asset is not None:
        asset["status"] = "IN_STOCK"
        db.touch(asset)
    employee = db.employees.get(c["employee_id"])
    if employee is not None:
        db.touch(employee)  # open_checkout_count derived field changed.
    return success(serialize.assignment_checkout(c), 200)


@app.route("/assets/checkouts/<_id>/transition", methods=["POST"])
def transition_checkout(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    c = get_checkout(_id)
    data = body()
    to_status = V.req_enum(data, "to_status", {"LOST"})
    if c["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only OPEN checkouts can be marked LOST")
    c["status"] = "LOST"
    c["returned_at"] = clock.get_now()
    db.touch(c)
    asset = db.hardware_assets.get(c["hardware_asset_id"])
    if asset is not None:
        asset["status"] = "IN_STOCK"
        db.touch(asset)
    employee = db.employees.get(c["employee_id"])
    if employee is not None:
        db.touch(employee)
    return success(serialize.assignment_checkout(c), 200)


# --------------------------------------------------------------------------- #
# WarrantyLease (coverage)                                                    #
# --------------------------------------------------------------------------- #
@app.route("/assets/coverage", methods=["POST"])
def create_coverage():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    hardware_asset_id = V.req_str(data, "hardware_asset_id")
    vendor_id = V.req_str(data, "vendor_id")
    coverage_type = V.req_enum(data, "coverage_type", {"WARRANTY", "LEASE"})
    asset = get_asset(hardware_asset_id)
    get_vendor(vendor_id)
    if data.get("coverage_start") is None or data.get("coverage_end") is None:
        raise err("ERR_INVALID_REQUEST", "coverage_start and coverage_end are required")
    coverage_start = parse_iso(data["coverage_start"])
    coverage_end = parse_iso(data["coverage_end"])
    if coverage_start > coverage_end:
        raise err("ERR_INVALID_TERM_WINDOW", "coverage_start must be <= coverage_end")
    monthly_cost_cents = V.opt_int(data, "monthly_cost_cents", 0, min_value=0)
    auto_renew = V.opt_bool(data, "auto_renew", False)

    # Temporal (priority 13): no overlap with ACTIVE/RENEWED coverage on the same
    # asset; closed intervals, zero-gap adjacency allowed (PRD 3.2).
    for cov in db.warranty_leases.values():
        if cov["hardware_asset_id"] != hardware_asset_id:
            continue
        if cov["status"] not in ("ACTIVE", "RENEWED"):
            continue
        if coverage_start < cov["coverage_end"] and cov["coverage_start"] < coverage_end:
            raise err("ERR_COVERAGE_OVERLAP", "Coverage window overlaps existing coverage")

    rec = {
        "hardware_asset_id": hardware_asset_id,
        "vendor_id": vendor_id,
        "coverage_type": coverage_type,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "monthly_cost_cents": monthly_cost_cents,
        "auto_renew": auto_renew,
        "status": "ACTIVE",
    }
    db.new_common(rec)
    db.warranty_leases[rec["id"]] = rec
    # Recompute asset support_status (PRD 3.2).
    if derive.recompute_asset_support_status(asset):
        db.touch(asset)
    return success(serialize.warranty_lease(rec), 201)


@app.route("/assets/coverage/<_id>", methods=["GET"])
def read_coverage(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.warranty_lease(get_coverage(_id)), 200)


@app.route("/assets/coverage", methods=["GET"])
def list_coverage():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    asset_id = request.args.get("hardware_asset_id")
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    records = [
        c
        for c in db.warranty_leases.values()
        if (asset_id is None or c["hardware_asset_id"] == asset_id)
        and (vendor_id is None or c["vendor_id"] == vendor_id)
        and (status is None or c["status"] == status)
    ]
    items, limit, offset, total = paginate(records, serialize.warranty_lease)
    return success_list(items, limit, offset, total)


@app.route("/assets/coverage/<_id>/transition", methods=["POST"])
def transition_coverage(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    cov = get_coverage(_id)
    data = body()
    to_status = V.req_enum(data, "to_status", {"EXPIRED", "CANCELLED"})
    if cov["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only ACTIVE coverage can be transitioned")
    if to_status == "EXPIRED":
        # Force-expiry legal only once clock strictly past coverage_end (PRD 3.2).
        if not (clock.get_now() > cov["coverage_end"]):
            raise err("ERR_COVERAGE_NOT_ENDED", "Clock has not passed coverage_end")
        cov["status"] = "EXPIRED"
    else:
        cov["status"] = "CANCELLED"
    db.touch(cov)
    asset = db.hardware_assets.get(cov["hardware_asset_id"])
    if asset is not None and derive.recompute_asset_support_status(asset):
        db.touch(asset)
    return success(serialize.warranty_lease(cov), 200)


# --------------------------------------------------------------------------- #
# InstallationRecord                                                          #
# --------------------------------------------------------------------------- #
@app.route("/assets/installations", methods=["POST"])
def create_installation():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    software_product_id = V.req_str(data, "software_product_id")
    hardware_asset_id = V.req_str(data, "hardware_asset_id")
    license_entitlement_id = V.req_str(data, "license_entitlement_id")
    # Existence left-to-right (priority 3).
    product = get_product(software_product_id)
    asset = get_asset(hardware_asset_id)
    ent = get_entitlement(license_entitlement_id)
    # Well-formedness (priority 4): OCC field present.
    if "expected_entitlement_version" not in data or data.get("expected_entitlement_version") is None:
        raise err("ERR_INVALID_REQUEST", "expected_entitlement_version is required")
    expected_version = V.req_int(data, "expected_entitlement_version", min_value=0)
    # OCC (priority 6): version must match the entitlement's current version.
    if expected_version != ent["version"]:
        raise err("ERR_STALE_VERSION", "Entitlement version is stale")

    required = calculations.required_core_units(product, asset)
    rec = {
        "software_product_id": software_product_id,
        "hardware_asset_id": hardware_asset_id,
        "license_entitlement_id": license_entitlement_id,
        "required_core_units": required,
        "status": "PENDING",
        "activated_at": None,
    }
    db.new_common(rec)
    db.installation_records[rec["id"]] = rec
    # Successful create increments the entitlement's version by one (PRD 2.7).
    db.touch(ent)
    return success(serialize.installation_record(rec), 201)


@app.route("/assets/installations/<_id>", methods=["GET"])
def read_installation(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.installation_record(get_install(_id)), 200)


@app.route("/assets/installations", methods=["GET"])
def list_installations():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    spid = request.args.get("software_product_id")
    haid = request.args.get("hardware_asset_id")
    leid = request.args.get("license_entitlement_id")
    status = request.args.get("status")
    records = [
        i
        for i in db.installation_records.values()
        if (spid is None or i["software_product_id"] == spid)
        and (haid is None or i["hardware_asset_id"] == haid)
        and (leid is None or i["license_entitlement_id"] == leid)
        and (status is None or i["status"] == status)
    ]
    items, limit, offset, total = paginate(records, serialize.installation_record)
    return success_list(items, limit, offset, total)


@app.route("/assets/installations/<_id>/activate", methods=["POST"])
def activate_installation(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    inst = get_install(_id)
    # State (priority 5).
    if inst["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only PENDING installs can be activated")
    ent = db.license_entitlements.get(inst["license_entitlement_id"])
    asset = db.hardware_assets.get(inst["hardware_asset_id"])
    # Referential (priority 10): entitlement ACTIVE.
    if ent is None or ent["status"] != "ACTIVE":
        raise err("ERR_ENTITLEMENT_NOT_ACTIVE", "Charged entitlement is not ACTIVE")
    # Referential: host asset must be IN_STOCK/ASSIGNED/IN_REPAIR.
    if asset is None or asset["status"] not in ("IN_STOCK", "ASSIGNED", "IN_REPAIR"):
        raise err("ERR_ASSET_NOT_AVAILABLE", "Host asset is not available")
    # Fiscal (priority 17): consumed + required must not exceed entitled.
    if ent["consumed_units"] + inst["required_core_units"] > ent["entitled_units"]:
        raise err("ERR_ENTITLEMENT_EXCEEDED", "Activation would exceed entitled units")

    inst["status"] = "ACTIVE"
    inst["activated_at"] = clock.get_now()
    db.touch(inst)
    ent["consumed_units"] += inst["required_core_units"]
    derive.recompute_entitlement_units(ent)
    db.touch(ent)
    return success(serialize.installation_record(inst), 200)


@app.route("/assets/installations/<_id>/transition", methods=["POST"])
def transition_installation(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    inst = get_install(_id)
    data = body()
    to_status = V.req_enum(data, "to_status", {"REJECTED", "UNINSTALLED"})
    if to_status == "REJECTED":
        if inst["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Only PENDING installs can be rejected")
        inst["status"] = "REJECTED"
        db.touch(inst)
    else:  # UNINSTALLED
        if inst["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Only ACTIVE installs can be uninstalled")
        inst["status"] = "UNINSTALLED"
        db.touch(inst)
        ent = db.license_entitlements.get(inst["license_entitlement_id"])
        if ent is not None:
            ent["consumed_units"] -= inst["required_core_units"]
            derive.recompute_entitlement_units(ent)
            db.touch(ent)
    return success(serialize.installation_record(inst), 200)


# --------------------------------------------------------------------------- #
# DisposalRequest                                                             #
# --------------------------------------------------------------------------- #
@app.route("/assets/disposal-requests", methods=["POST"])
def create_disposal():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager"})
    data = body()
    hardware_asset_id = V.req_str(data, "hardware_asset_id")
    reason = V.req_enum(data, "reason", {"END_OF_LIFE", "DAMAGED", "LOST", "SOLD"})
    get_asset(hardware_asset_id)
    proposed_proceeds_cents = V.opt_int(data, "proposed_proceeds_cents", 0, min_value=0)
    rec = {
        "hardware_asset_id": hardware_asset_id,
        "submitted_by_user_id": caller.user_id,
        "reason": reason,
        "proposed_proceeds_cents": proposed_proceeds_cents,
        "approved_by_user_id": None,
        "status": "SUBMITTED",
    }
    db.new_common(rec)
    db.disposal_requests[rec["id"]] = rec
    return success(serialize.disposal_request(rec), 201)


@app.route("/assets/disposal-requests/<_id>", methods=["GET"])
def read_disposal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.disposal_request(get_disposal(_id)), 200)


@app.route("/assets/disposal-requests", methods=["GET"])
def list_disposals():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    asset_id = request.args.get("hardware_asset_id")
    status = request.args.get("status")
    records = [
        d
        for d in db.disposal_requests.values()
        if (asset_id is None or d["hardware_asset_id"] == asset_id)
        and (status is None or d["status"] == status)
    ]
    items, limit, offset, total = paginate(records, serialize.disposal_request)
    return success_list(items, limit, offset, total)


def _asset_has_open_checkout(asset_id):
    return any(
        c["hardware_asset_id"] == asset_id and c["status"] == "OPEN"
        for c in db.assignment_checkouts.values()
    )


@app.route("/assets/disposal-requests/<_id>/approve", methods=["POST"])
def approve_disposal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    req = get_disposal(_id)
    # State (priority 5).
    if req["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only SUBMITTED requests can be approved")
    # Segregation of duties (priority 7): approver != submitter.
    if caller.user_id == req["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from submitter")
    asset = db.hardware_assets.get(req["hardware_asset_id"])
    # Open-checkout safety (priority 8) before retireability (priority 11), per PRD 3.6.
    if asset is not None and _asset_has_open_checkout(asset["id"]):
        raise err("ERR_ASSET_HAS_OPEN_CHECKOUT", "Asset has an OPEN checkout")
    if asset is None or asset["status"] not in ("IN_STOCK", "IN_REPAIR"):
        raise err("ERR_ASSET_NOT_RETIREABLE", "Asset is not retireable")
    req["approved_by_user_id"] = caller.user_id
    req["status"] = "APPROVED"
    db.touch(req)
    asset["status"] = "RETIRED"
    db.touch(asset)
    return success(serialize.disposal_request(req), 200)


@app.route("/assets/disposal-requests/<_id>/reject", methods=["POST"])
def reject_disposal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    req = get_disposal(_id)
    if req["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only SUBMITTED requests can be rejected")
    if caller.user_id == req["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Rejector must differ from submitter")
    req["status"] = "REJECTED"
    db.touch(req)
    return success(serialize.disposal_request(req), 200)


@app.route("/assets/disposal-requests/<_id>/complete", methods=["POST"])
def complete_disposal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    req = get_disposal(_id)
    if req["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only APPROVED requests can be completed")
    asset = db.hardware_assets.get(req["hardware_asset_id"])
    if asset is None or asset["status"] != "RETIRED":
        raise err("ERR_INVALID_STATE", "Asset must be RETIRED to dispose")

    # Finalize depreciation as of server clock using the disposal (final) variant.
    derive.recompute_asset_depreciation(asset, final=True)
    asset["disposal_proceeds_cents"] = req["proposed_proceeds_cents"]
    asset["disposal_gain_loss_cents"] = (
        asset["disposal_proceeds_cents"] - asset["net_book_value_cents"]
    )
    asset["status"] = "DISPOSED"
    db.touch(asset)

    # Cascade: every ACTIVE install on this asset -> UNINSTALLED, releasing units.
    for inst in db.installation_records.values():
        if inst["hardware_asset_id"] == asset["id"] and inst["status"] == "ACTIVE":
            inst["status"] = "UNINSTALLED"
            db.touch(inst)
            ent = db.license_entitlements.get(inst["license_entitlement_id"])
            if ent is not None:
                ent["consumed_units"] -= inst["required_core_units"]
                derive.recompute_entitlement_units(ent)
                db.touch(ent)

    req["status"] = "COMPLETED"
    db.touch(req)
    return success(serialize.disposal_request(req), 200)


@app.route("/assets/disposal-requests/<_id>/reverse", methods=["POST"])
def reverse_disposal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    req = get_disposal(_id)
    if req["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Only COMPLETED requests can be reversed")
    asset = db.hardware_assets.get(req["hardware_asset_id"])
    if asset is None or asset["status"] != "DISPOSED":
        raise err("ERR_INVALID_STATE", "Asset must be DISPOSED to reverse")
    # Compensation: zero proceeds/gain-loss, restore provisional book value.
    asset["disposal_proceeds_cents"] = 0
    asset["disposal_gain_loss_cents"] = 0
    asset["status"] = "RETIRED"
    derive.recompute_asset_depreciation(asset)  # provisional
    db.touch(asset)
    req["status"] = "REVERSED"
    db.touch(req)
    # NOTE: uninstalled installs are NOT resurrected (PRD 3.6).
    return success(serialize.disposal_request(req), 200)


# --------------------------------------------------------------------------- #
# RenewalOrder                                                                #
# --------------------------------------------------------------------------- #
@app.route("/assets/renewal-orders", methods=["POST"])
def create_renewal():
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    data = body()
    target_type = V.req_enum(data, "target_type", {"ENTITLEMENT", "COVERAGE"})
    license_entitlement_id = V.opt_str(data, "license_entitlement_id", None)
    warranty_lease_id = V.opt_str(data, "warranty_lease_id", None)

    if target_type == "ENTITLEMENT":
        if not license_entitlement_id:
            raise err("ERR_INVALID_REQUEST", "license_entitlement_id required for ENTITLEMENT target")
        get_entitlement(license_entitlement_id)
        warranty_lease_id = None
    else:
        if not warranty_lease_id:
            raise err("ERR_INVALID_REQUEST", "warranty_lease_id required for COVERAGE target")
        get_coverage(warranty_lease_id)
        license_entitlement_id = None

    extend_months = V.req_int(data, "extend_months", min_value=1)
    added_units = V.opt_int(data, "added_units", 0, min_value=0)

    rec = {
        "target_type": target_type,
        "license_entitlement_id": license_entitlement_id,
        "warranty_lease_id": warranty_lease_id,
        "extend_months": extend_months,
        "added_units": added_units,
        "quoted_cost_cents": 0,
        "status": "QUOTED",
    }
    db.new_common(rec)
    db.renewal_orders[rec["id"]] = rec
    return success(serialize.renewal_order(rec), 201)


@app.route("/assets/renewal-orders/<_id>", methods=["GET"])
def read_renewal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.renewal_order(get_renewal(_id)), 200)


@app.route("/assets/renewal-orders", methods=["GET"])
def list_renewals():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    leid = request.args.get("license_entitlement_id")
    wlid = request.args.get("warranty_lease_id")
    status = request.args.get("status")
    records = [
        r
        for r in db.renewal_orders.values()
        if (leid is None or r["license_entitlement_id"] == leid)
        and (wlid is None or r["warranty_lease_id"] == wlid)
        and (status is None or r["status"] == status)
    ]
    items, limit, offset, total = paginate(records, serialize.renewal_order)
    return success_list(items, limit, offset, total)


@app.route("/assets/renewal-orders/<_id>/complete", methods=["POST"])
def complete_renewal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    order = get_renewal(_id)
    data = body()
    # State (priority 5).
    if order["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Only QUOTED orders can be completed")

    if order["target_type"] == "ENTITLEMENT":
        ent = db.license_entitlements.get(order["license_entitlement_id"])
        if ent is None:
            raise err("ERR_NOT_FOUND", "Target entitlement not found")
        # State of the entitlement target (priority 5).
        if ent["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_INVALID_STATE", "Entitlement must be ACTIVE or SUSPENDED")
        # OCC (priority 6): expected_entitlement_version must match.
        if "expected_entitlement_version" not in data or data.get("expected_entitlement_version") is None:
            raise err("ERR_INVALID_REQUEST", "expected_entitlement_version is required")
        expected_version = V.req_int(data, "expected_entitlement_version", min_value=0)
        if expected_version != ent["version"]:
            raise err("ERR_STALE_VERSION", "Entitlement version is stale")

        order["quoted_cost_cents"] = calculations.renewal_cost_entitlement(
            ent, order["extend_months"], order["added_units"]
        )
        ent["term_end"] = add_months(ent["term_end"], order["extend_months"])
        ent["entitled_units"] += order["added_units"]
        derive.recompute_entitlement_units(ent)
        # Cyclic ACTIVE->RENEWED->ACTIVE: lands back on ACTIVE (PRD 3.5).
        ent["status"] = "ACTIVE"
        db.touch(ent)  # successful completion increments entitlement version (PRD 2.7).
    else:  # COVERAGE
        cov = db.warranty_leases.get(order["warranty_lease_id"])
        if cov is None:
            raise err("ERR_NOT_FOUND", "Target coverage not found")
        # Eligibility (priority): must be ACTIVE and auto_renew (PRD 3.5).
        if cov["status"] != "ACTIVE" or not cov["auto_renew"]:
            raise err("ERR_RENEWAL_NOT_ELIGIBLE", "Coverage is not eligible for renewal")
        order["quoted_cost_cents"] = calculations.renewal_cost_coverage(cov, order["extend_months"])
        cov["coverage_end"] = add_months(cov["coverage_end"], order["extend_months"])
        cov["status"] = "ACTIVE"
        db.touch(cov)
        asset = db.hardware_assets.get(cov["hardware_asset_id"])
        if asset is not None and derive.recompute_asset_support_status(asset):
            db.touch(asset)

    order["status"] = "COMPLETED"
    db.touch(order)
    return success(serialize.renewal_order(order), 200)


@app.route("/assets/renewal-orders/<_id>/transition", methods=["POST"])
def transition_renewal(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    order = get_renewal(_id)
    data = body()
    to_status = V.req_enum(data, "to_status", {"CANCELLED"})
    if order["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Only QUOTED orders can be cancelled")
    order["status"] = "CANCELLED"
    db.touch(order)
    return success(serialize.renewal_order(order), 200)


# --------------------------------------------------------------------------- #
# TrueUpReconciliation + ComplianceFinding                                    #
# --------------------------------------------------------------------------- #
@app.route("/assets/true-ups", methods=["POST"])
def create_true_up():
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    data = body()
    software_product_id = V.req_str(data, "software_product_id")
    variant = V.req_enum(data, "variant", {"LIVE", "AUDIT"})
    get_product(software_product_id)
    if data.get("as_of") is not None:
        as_of = parse_iso(data["as_of"])
    else:
        as_of = clock.get_now()
    rec = {
        "software_product_id": software_product_id,
        "variant": variant,
        "as_of": as_of,
        "total_entitled_units": 0,
        "total_consumed_units": 0,
        "position_units": 0,
        "verdict": "COMPLIANT",
        "status": "DRAFT",
    }
    db.new_common(rec)
    db.true_up_reconciliations[rec["id"]] = rec
    return success(serialize.true_up_reconciliation(rec), 201)


@app.route("/assets/true-ups/<_id>", methods=["GET"])
def read_true_up(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.true_up_reconciliation(get_true_up(_id)), 200)


@app.route("/assets/true-ups", methods=["GET"])
def list_true_ups():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    spid = request.args.get("software_product_id")
    status = request.args.get("status")
    records = [
        t
        for t in db.true_up_reconciliations.values()
        if (spid is None or t["software_product_id"] == spid)
        and (status is None or t["status"] == status)
    ]
    items, limit, offset, total = paginate(records, serialize.true_up_reconciliation)
    return success_list(items, limit, offset, total)


def _entitlement_in_scope(ent, variant, as_of, product_id):
    if ent["software_product_id"] != product_id:
        return False
    if variant == "LIVE":
        if ent["status"] != "ACTIVE":
            return False
        return ent["term_start"] <= as_of <= ent["term_end"]
    else:  # AUDIT
        if ent["status"] not in ("ACTIVE", "SUSPENDED", "RENEWED"):
            return False
        end_with_grace = add_days(ent["term_end"], ent["grace_days"])
        return ent["term_start"] <= as_of <= end_with_grace


def add_days(dt, days):
    from datetime import timedelta

    return dt + timedelta(days=days)


def _install_in_scope(inst, variant, in_scope_entitlement_ids):
    if inst["license_entitlement_id"] not in in_scope_entitlement_ids:
        return False
    if variant == "LIVE":
        return inst["status"] == "ACTIVE"
    else:  # AUDIT
        return inst["status"] in ("ACTIVE", "PENDING")


@app.route("/assets/true-ups/<_id>/finalize", methods=["POST"])
def finalize_true_up(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"ComplianceOfficer"})
    recon = get_true_up(_id)
    if recon["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only DRAFT reconciliations can be finalized")

    variant = recon["variant"]
    as_of = recon["as_of"]
    product_id = recon["software_product_id"]

    in_scope_ents = [
        e
        for e in db.license_entitlements.values()
        if _entitlement_in_scope(e, variant, as_of, product_id)
    ]
    in_scope_ent_ids = set(e["id"] for e in in_scope_ents)
    total_entitled = sum(e["entitled_units"] for e in in_scope_ents)

    in_scope_installs = [
        i
        for i in db.installation_records.values()
        if _install_in_scope(i, variant, in_scope_ent_ids)
    ]
    total_consumed = sum(i["required_core_units"] for i in in_scope_installs)

    position = total_entitled - total_consumed
    verdict = "OVER_DEPLOYED" if position < 0 else "COMPLIANT"

    recon["total_entitled_units"] = total_entitled
    recon["total_consumed_units"] = total_consumed
    recon["position_units"] = position
    recon["verdict"] = verdict
    recon["status"] = "FINALIZED"
    db.touch(recon)

    # Mint a ComplianceFinding when over-deployed (PRD 3.7).
    if verdict == "OVER_DEPLOYED":
        finding = {
            "true_up_reconciliation_id": recon["id"],
            "software_product_id": product_id,
            "finding_type": "OVER_DEPLOYED",
            "detail": "Over-deployed by %d units (entitled=%d, consumed=%d)"
            % (-position, total_entitled, total_consumed),
            "shortfall_units": -position,
        }
        db.new_lean(finding)
        db.compliance_findings[finding["id"]] = finding

    # Cascade to product compliance_status (PRD 3.7).
    product = db.software_products.get(product_id)
    if product is not None:
        product["compliance_status"] = "OVER_DEPLOYED" if verdict == "OVER_DEPLOYED" else "COMPLIANT"
        db.touch(product)

    return success(serialize.true_up_reconciliation(recon), 200)


@app.route("/assets/true-ups/<_id>/findings", methods=["GET"])
def list_true_up_findings(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    get_true_up(_id)  # existence
    records = [
        f for f in db.compliance_findings.values() if f["true_up_reconciliation_id"] == _id
    ]
    items, limit, offset, total = paginate(records, serialize.compliance_finding)
    return success_list(items, limit, offset, total)


@app.route("/assets/findings/<_id>", methods=["GET"])
def read_finding(_id):
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    return success(serialize.compliance_finding(get_finding(_id)), 200)


@app.route("/assets/findings", methods=["GET"])
def list_findings():
    caller = auth.authenticate()
    auth.require_roles(caller, {"AssetManager", "ComplianceOfficer"})
    spid = request.args.get("software_product_id")
    trid = request.args.get("true_up_reconciliation_id")
    records = [
        f
        for f in db.compliance_findings.values()
        if (spid is None or f["software_product_id"] == spid)
        and (trid is None or f["true_up_reconciliation_id"] == trid)
    ]
    items, limit, offset, total = paginate(records, serialize.compliance_finding)
    return success_list(items, limit, offset, total)


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def _serve(host: str, port: int) -> None:
    """Start the WSGI server with a bind-retry loop.

    Under the benchmark's per-test-server isolation the runner restarts this
    process before every test; across 8 concurrent sweep rounds the previous
    server on the same port may not have fully released its socket by the time
    this process tries to bind (SIGTERM still in flight under CPU contention).
    A bare app.run() would then crash with "Address already in use" and the
    runner would report "could not be restarted". Retrying the bind for a few
    seconds rides out that brief window instead of dying.
    """
    import time
    from werkzeug.serving import make_server

    deadline = time.time() + 20.0
    last_exc = None
    while time.time() < deadline:
        try:
            srv = make_server(host, port, app, threaded=True)
            break
        except OSError as exc:  # port not yet free
            last_exc = exc
            time.sleep(0.25)
    else:
        raise last_exc
    srv.serve_forever()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _serve("0.0.0.0", port)
