"""Water Softener Service API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
"""
import math
import os

from flask import Flask, request

import calculations as calc
import constants as C
from auth import authenticate, authorize
from clock import clock
from db import db, new_primary, new_reference, touch
from errors import ApiError, err
from response import object_response, list_response, error_response, success
from services import (
    get_or_404, fk_or_404, ledger_debit, ledger_credit, _has_other_past_due,
    create_invoice_record, create_service_visit, recompute_regen_health,
)
from validate import (
    get_body, require_present, as_string, opt_string, as_int, as_number,
    as_enum, as_datetime, parse_iso,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % e)


# ---------------------------------------------------------------------------
# Auth/RBAC gate per request
# ---------------------------------------------------------------------------

def guard(allowed_roles):
    """Authenticate then authorize. Returns (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def paginate():
    """Parse limit/offset (PRD §2.3). Bad values -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def list_collection(records, limit, offset):
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response(page, limit, offset, total)


# ===========================================================================
# Customers & FieldTechs (reference entities)
# ===========================================================================

@app.route("/customers", methods=["POST"])
def create_customer():
    guard({"ServiceManager", "BillingClerk"})
    body = get_body()
    full_name = as_string(require_present(body, "full_name"), "full_name")
    email = as_string(require_present(body, "email"), "email")
    if email in db.customer_emails:
        raise err("ERR_INVALID_REQUEST", "email already in use")
    cust = new_reference({"full_name": full_name, "email": email})
    db.customers[cust["id"]] = cust
    db.customer_emails[email] = cust["id"]
    return object_response(cust, status=201)


@app.route("/customers/<rid>", methods=["GET"])
def get_customer(rid):
    guard({"ServiceManager", "BillingClerk", "Customer"})
    return object_response(get_or_404(db.customers, rid), status=200)


@app.route("/field-techs", methods=["POST"])
def create_field_tech():
    guard({"ServiceManager", "Dispatcher"})
    body = get_body()
    full_name = as_string(require_present(body, "full_name"), "full_name")
    home_zone = as_string(require_present(body, "home_zone"), "home_zone")
    tech = new_reference({"full_name": full_name, "home_zone": home_zone})
    db.field_techs[tech["id"]] = tech
    return object_response(tech, status=201)


@app.route("/field-techs/<rid>", methods=["GET"])
def get_field_tech(rid):
    guard({"ServiceManager", "Dispatcher"})
    return object_response(get_or_404(db.field_techs, rid), status=200)


# ===========================================================================
# Service Accounts
# ===========================================================================

@app.route("/accounts", methods=["POST"])
def create_account():
    guard({"ServiceManager", "BillingClerk"})
    body = get_body()
    customer_id = as_string(require_present(body, "customer_id"), "customer_id")
    fk_or_404(db.customers, customer_id)
    property_type = as_enum(require_present(body, "property_type"), "property_type",
                            C.PROPERTY_TYPES)
    service_zone = as_string(require_present(body, "service_zone"), "service_zone")
    acct = new_primary({
        "customer_id": customer_id,
        "property_type": property_type,
        "service_zone": service_zone,
        "credit_balance_cents": 0,
        "hardness_gpg": None,
        "standing": "GOOD",
    })
    db.accounts[acct["id"]] = acct
    return object_response(acct, status=201)


@app.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    guard({"ServiceManager", "BillingClerk", "Customer"})
    return object_response(get_or_404(db.accounts, rid), status=200)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    guard({"ServiceManager", "BillingClerk"})
    limit, offset = paginate()
    customer_id = request.args.get("customer_id")
    recs = list(db.accounts.values())
    if customer_id is not None:
        recs = [r for r in recs if r["customer_id"] == customer_id]
    return list_collection(recs, limit, offset)


@app.route("/accounts/<rid>/credit", methods=["POST"])
def credit_account(rid):
    guard({"BillingClerk", "ServiceManager"})
    acct = get_or_404(db.accounts, rid)
    body = get_body()
    amount = as_int(require_present(body, "amount_cents"), "amount_cents", minimum=0)
    acct["credit_balance_cents"] += amount
    touch(acct)
    return object_response(acct, status=200)


# ===========================================================================
# Water Tests
# ===========================================================================

@app.route("/water-tests", methods=["POST"])
def create_water_test():
    guard({"FieldTech", "ServiceManager"})
    body = get_body()
    account_id = as_string(require_present(body, "account_id"), "account_id")
    fk_or_404(db.accounts, account_id)
    hardness_gpg = as_number(require_present(body, "hardness_gpg"), "hardness_gpg", minimum=0)
    iron_ppm = as_number(require_present(body, "iron_ppm"), "iron_ppm", minimum=0)
    tds_ppm = as_int(require_present(body, "tds_ppm"), "tds_ppm", minimum=0)
    household_size = as_int(require_present(body, "household_size"), "household_size", minimum=1)
    wt = new_primary({
        "account_id": account_id,
        "hardness_gpg": hardness_gpg,
        "iron_ppm": iron_ppm,
        "tds_ppm": tds_ppm,
        "household_size": household_size,
        "status": "DRAFT",
        "recommended_grain_capacity": None,
        "recommended_needs_ro": None,
    })
    db.water_tests[wt["id"]] = wt
    return object_response(wt, status=201)


@app.route("/water-tests/<rid>", methods=["GET"])
def get_water_test(rid):
    guard({"FieldTech", "ServiceManager", "Customer"})
    return object_response(get_or_404(db.water_tests, rid), status=200)


@app.route("/water-tests", methods=["GET"])
def list_water_tests():
    guard({"FieldTech", "ServiceManager", "Customer"})
    limit, offset = paginate()
    account_id = request.args.get("account_id")
    recs = list(db.water_tests.values())
    if account_id is not None:
        recs = [r for r in recs if r["account_id"] == account_id]
    return list_collection(recs, limit, offset)


@app.route("/water-tests/<rid>/recommend", methods=["POST"])
def recommend_water_test(rid):
    guard({"FieldTech", "ServiceManager"})
    wt = get_or_404(db.water_tests, rid)
    if wt["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Water test is not DRAFT")
    wt["recommended_grain_capacity"] = calc.size_grain_capacity(
        wt["hardness_gpg"], wt["iron_ppm"], wt["household_size"])
    wt["recommended_needs_ro"] = calc.needs_ro(wt["tds_ppm"])
    wt["status"] = "RECOMMENDED"
    touch(wt)
    return object_response(wt, status=200)


@app.route("/water-tests/<rid>/accept", methods=["POST"])
def accept_water_test(rid):
    guard({"Customer", "ServiceManager"})
    wt = get_or_404(db.water_tests, rid)
    if wt["status"] != "RECOMMENDED":
        raise err("ERR_INVALID_STATE", "Water test is not RECOMMENDED")
    account = db.accounts.get(wt["account_id"])
    # cascade: supersede other ACCEPTED tests for this account
    for other in db.water_tests.values():
        if other["id"] == wt["id"]:
            continue
        if other["account_id"] == wt["account_id"] and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    wt["status"] = "ACCEPTED"
    touch(wt)
    if account is not None:
        account["hardness_gpg"] = wt["hardness_gpg"]
        touch(account)
    return object_response(wt, status=200)


# ===========================================================================
# Softener Systems
# ===========================================================================

@app.route("/systems", methods=["POST"])
def create_system():
    guard({"ServiceManager", "FieldTech"})
    body = get_body()
    account_id = as_string(require_present(body, "account_id"), "account_id")
    fk_or_404(db.accounts, account_id)
    source_test_id = as_string(require_present(body, "source_test_id"), "source_test_id")
    fk_or_404(db.water_tests, source_test_id)
    acquisition_mode = as_enum(require_present(body, "acquisition_mode"),
                               "acquisition_mode", C.ACQUISITION_MODES)
    grain_capacity = as_int(require_present(body, "grain_capacity"),
                            "grain_capacity", minimum=16000)
    sys = new_primary({
        "account_id": account_id,
        "source_test_id": source_test_id,
        "acquisition_mode": acquisition_mode,
        "grain_capacity": grain_capacity,
        "lifecycle_status": "ORDERED",
        "regen_health": "NOMINAL",
        "gallons_since_regen": 0,
        "salt_level_pct": 100,
        "install_date": None,
    })
    db.systems[sys["id"]] = sys
    return object_response(sys, status=201)


@app.route("/systems/<rid>", methods=["GET"])
def get_system(rid):
    guard({"ServiceManager", "FieldTech", "Customer"})
    return object_response(get_or_404(db.systems, rid), status=200)


@app.route("/systems", methods=["GET"])
def list_systems():
    guard({"ServiceManager", "FieldTech", "Customer"})
    limit, offset = paginate()
    account_id = request.args.get("account_id")
    source_test_id = request.args.get("source_test_id")
    recs = list(db.systems.values())
    if account_id is not None:
        recs = [r for r in recs if r["account_id"] == account_id]
    if source_test_id is not None:
        recs = [r for r in recs if r["source_test_id"] == source_test_id]
    return list_collection(recs, limit, offset)


@app.route("/systems/<rid>/install", methods=["POST"])
def install_system(rid):
    guard({"FieldTech", "ServiceManager"})
    sys = get_or_404(db.systems, rid)
    if sys["lifecycle_status"] != "ORDERED":
        raise err("ERR_INVALID_STATE", "System is not ORDERED")
    source = db.water_tests.get(sys["source_test_id"])
    if source is None or source["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Source water test is not ACCEPTED")
    if sys["grain_capacity"] != source["recommended_grain_capacity"]:
        raise err("ERR_CAPACITY_MISMATCH",
                  "grain_capacity does not match source test recommended capacity")
    sys["lifecycle_status"] = "INSTALLED"
    sys["install_date"] = clock.iso()
    sys["regen_health"] = "NOMINAL"
    sys["gallons_since_regen"] = 0
    sys["salt_level_pct"] = 100
    touch(sys)
    return object_response(sys, status=200)


@app.route("/systems/<rid>/activate", methods=["POST"])
def activate_system(rid):
    guard({"FieldTech", "ServiceManager"})
    sys = get_or_404(db.systems, rid)
    if sys["lifecycle_status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "System is not INSTALLED")
    sys["lifecycle_status"] = "ACTIVE"
    touch(sys)
    return object_response(sys, status=200)


@app.route("/systems/<rid>/decommission", methods=["POST"])
def decommission_system(rid):
    guard({"ServiceManager"})
    sys = get_or_404(db.systems, rid)
    if sys["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "System is not ACTIVE")
    for contract in db.rental_contracts.values():
        if contract["system_id"] == sys["id"] and contract["status"] in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_INVALID_STATE",
                      "System has an ACTIVE/SUSPENDED rental contract")
    sys["lifecycle_status"] = "DECOMMISSIONED"
    # cartridge schedules freeze at current status (no further accrual) — no field change
    touch(sys)
    return object_response(sys, status=200)


@app.route("/systems/<rid>/meter-reading", methods=["POST"])
def meter_reading(rid):
    guard({"FieldTech", "ServiceManager"})
    sys = get_or_404(db.systems, rid)
    body = get_body()
    gallons = as_int(require_present(body, "gallons_since_regen"),
                     "gallons_since_regen", minimum=0)
    if sys["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "System is not ACTIVE")
    sys["gallons_since_regen"] = gallons
    recompute_regen_health(sys)
    touch(sys)
    return object_response(sys, status=200)


@app.route("/systems/<rid>/regenerate", methods=["POST"])
def regenerate_system(rid):
    guard({"FieldTech", "ServiceManager"})
    sys = get_or_404(db.systems, rid)
    if sys["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "System is not ACTIVE")
    if sys["regen_health"] not in ("DUE", "OVERDUE"):
        raise err("ERR_INVALID_STATE", "regen_health is not DUE or OVERDUE")
    if sys["salt_level_pct"] < C.SALT_MIN_REGEN_PCT:
        raise err("ERR_INSUFFICIENT_SALT", "Salt level below regeneration floor")
    sys["regen_health"] = "NOMINAL"
    sys["gallons_since_regen"] = 0
    sys["salt_level_pct"] = max(0, sys["salt_level_pct"] - C.SALT_PER_REGEN_PCT)
    create_service_visit(sys["id"], stop_id=None, visit_type="REGEN",
                         gallons_treated_reading=0, billable_cents=0)
    touch(sys)
    return object_response(sys, status=200)


@app.route("/systems/<rid>/cartridge-schedules", methods=["GET"])
def list_system_cartridge_schedules(rid):
    guard({"ServiceManager", "FieldTech", "Customer"})
    get_or_404(db.systems, rid)
    limit, offset = paginate()
    recs = [r for r in db.cartridge_schedules.values() if r["system_id"] == rid]
    return list_collection(recs, limit, offset)


@app.route("/systems/<rid>/service-visits", methods=["GET"])
def list_system_service_visits(rid):
    guard({"ServiceManager", "FieldTech", "Customer"})
    get_or_404(db.systems, rid)
    limit, offset = paginate()
    recs = [r for r in db.service_visits.values() if r["system_id"] == rid]
    return list_collection(recs, limit, offset)


@app.route("/systems/<rid>/warranty-claims", methods=["GET"])
def list_system_warranty_claims(rid):
    guard({"ServiceManager", "FieldTech", "Customer"})
    get_or_404(db.systems, rid)
    limit, offset = paginate()
    recs = [r for r in db.warranty_claims.values() if r["system_id"] == rid]
    return list_collection(recs, limit, offset)


# ===========================================================================
# Rental Contracts
# ===========================================================================

@app.route("/rental-contracts", methods=["POST"])
def create_rental_contract():
    guard({"BillingClerk", "ServiceManager"})
    body = get_body()
    account_id = as_string(require_present(body, "account_id"), "account_id")
    account = fk_or_404(db.accounts, account_id)
    system_id = as_string(require_present(body, "system_id"), "system_id")
    system = fk_or_404(db.systems, system_id)
    monthly_rate_cents = as_int(require_present(body, "monthly_rate_cents"),
                                "monthly_rate_cents", minimum=0)
    term_months = as_int(require_present(body, "term_months"), "term_months", minimum=1)
    start_date_raw = require_present(body, "start_date")
    start_date = as_datetime(start_date_raw, "start_date")
    # business rule: ERR_RENTAL_NOT_ALLOWED
    if account["standing"] != "GOOD":
        raise err("ERR_RENTAL_NOT_ALLOWED", "Account standing is not GOOD")
    if system["acquisition_mode"] != "RENTAL":
        raise err("ERR_RENTAL_NOT_ALLOWED", "System acquisition_mode is not RENTAL")
    for c in db.rental_contracts.values():
        if c["system_id"] == system_id and c["status"] in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_RENTAL_NOT_ALLOWED",
                      "System already has an ACTIVE/SUSPENDED contract")
    contract = new_primary({
        "account_id": account_id,
        "system_id": system_id,
        "monthly_rate_cents": monthly_rate_cents,
        "term_months": term_months,
        "start_date": start_date_raw,
        "status": "ACTIVE",
        "months_billed": 0,
        "early_termination_fee_cents": 0,
    })
    # internal: track suspended intervals for billable-day proration
    contract["_suspend_intervals"] = []
    contract["_suspend_open"] = None
    db.rental_contracts[contract["id"]] = contract
    return object_response(contract, status=201)


@app.route("/rental-contracts/<rid>", methods=["GET"])
def get_rental_contract(rid):
    guard({"BillingClerk", "ServiceManager", "Customer"})
    return object_response(get_or_404(db.rental_contracts, rid), status=200)


@app.route("/rental-contracts", methods=["GET"])
def list_rental_contracts():
    guard({"BillingClerk", "ServiceManager", "Customer"})
    limit, offset = paginate()
    account_id = request.args.get("account_id")
    system_id = request.args.get("system_id")
    recs = list(db.rental_contracts.values())
    if account_id is not None:
        recs = [r for r in recs if r["account_id"] == account_id]
    if system_id is not None:
        recs = [r for r in recs if r["system_id"] == system_id]
    return list_collection(recs, limit, offset)


@app.route("/rental-contracts/<rid>/suspend", methods=["POST"])
def suspend_contract(rid):
    guard({"BillingClerk", "ServiceManager"})
    contract = get_or_404(db.rental_contracts, rid)
    if contract["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract is not ACTIVE")
    contract["status"] = "SUSPENDED"
    contract["_suspend_open"] = clock.now()
    touch(contract)
    return object_response(contract, status=200)


@app.route("/rental-contracts/<rid>/resume", methods=["POST"])
def resume_contract(rid):
    guard({"BillingClerk", "ServiceManager"})
    contract = get_or_404(db.rental_contracts, rid)
    if contract["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Contract is not SUSPENDED")
    account = db.accounts.get(contract["account_id"])
    if account is None or account["standing"] != "GOOD":
        raise err("ERR_INVALID_STATE", "Account standing is not GOOD")
    if contract.get("_suspend_open") is not None:
        contract["_suspend_intervals"].append((contract["_suspend_open"], clock.now()))
        contract["_suspend_open"] = None
    contract["status"] = "ACTIVE"
    touch(contract)
    return object_response(contract, status=200)


@app.route("/rental-contracts/<rid>/terminate", methods=["POST"])
def terminate_contract(rid):
    guard({"BillingClerk", "ServiceManager"})
    contract = get_or_404(db.rental_contracts, rid)
    body = get_body()
    expected = require_present(body, "expected_rentalcontract_version")
    expected = as_int(expected, "expected_rentalcontract_version", minimum=0)
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Contract is not ACTIVE or SUSPENDED")
    if expected != contract["version"]:
        raise err("ERR_STALE_VERSION", "expected_rentalcontract_version is stale")
    start_date = parse_iso(contract["start_date"], "start_date")
    fee = calc.early_termination_fee(start_date, clock.now(),
                                     contract["term_months"],
                                     contract["monthly_rate_cents"])
    contract["early_termination_fee_cents"] = fee
    if fee > 0:
        account = db.accounts.get(contract["account_id"])
        if account is not None:
            create_invoice_record(
                account,
                contract_id=contract["id"],
                supersedes_invoice_id=None,
                invoice_kind="TERMINATION",
                period_start=contract["start_date"],
                period_end=clock.iso(),
                amount_cents=fee,
                due_offset_days=30,
            )
    contract["status"] = "TERMINATED"
    touch(contract)
    return object_response(contract, status=200)


# ===========================================================================
# Routes & Stops
# ===========================================================================

@app.route("/routes", methods=["POST"])
def create_route():
    guard({"Dispatcher", "ServiceManager"})
    body = get_body()
    service_zone = as_string(require_present(body, "service_zone"), "service_zone")
    route_date_raw = require_present(body, "route_date")
    as_datetime(route_date_raw, "route_date")
    tech_id = as_string(require_present(body, "tech_id"), "tech_id")
    fk_or_404(db.field_techs, tech_id)
    capacity_stops = as_int(require_present(body, "capacity_stops"),
                            "capacity_stops", minimum=1)
    route = new_primary({
        "service_zone": service_zone,
        "route_date": route_date_raw,
        "tech_id": tech_id,
        "status": "PLANNED",
        "capacity_stops": capacity_stops,
        "stop_count": 0,
    })
    db.routes[route["id"]] = route
    return object_response(route, status=201)


@app.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    guard({"Dispatcher", "ServiceManager", "FieldTech"})
    return object_response(get_or_404(db.routes, rid), status=200)


@app.route("/routes", methods=["GET"])
def list_routes():
    guard({"Dispatcher", "ServiceManager", "FieldTech"})
    limit, offset = paginate()
    tech_id = request.args.get("tech_id")
    service_zone = request.args.get("service_zone")
    recs = list(db.routes.values())
    if tech_id is not None:
        recs = [r for r in recs if r["tech_id"] == tech_id]
    if service_zone is not None:
        recs = [r for r in recs if r["service_zone"] == service_zone]
    return list_collection(recs, limit, offset)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    # half-open style overlap: they overlap unless one ends at/before other starts
    return a_start < b_end and b_start < a_end


@app.route("/routes/<rid>/stops", methods=["POST"])
def add_route_stop(rid):
    guard({"Dispatcher", "ServiceManager"})
    route = get_or_404(db.routes, rid)
    body = get_body()
    system_id = as_string(require_present(body, "system_id"), "system_id")
    system = fk_or_404(db.systems, system_id)
    stop_type = as_enum(require_present(body, "stop_type"), "stop_type", C.STOP_TYPES)
    window_start_raw = require_present(body, "window_start")
    window_end_raw = require_present(body, "window_end")
    window_start = as_datetime(window_start_raw, "window_start")
    window_end = as_datetime(window_end_raw, "window_end")
    salt_bags = body.get("salt_bags_delivered", 0)
    if salt_bags is None:
        salt_bags = 0
    salt_bags = as_int(salt_bags, "salt_bags_delivered", minimum=0)

    # state: route must be PLANNED to accept stops
    if route["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Route is not PLANNED")

    # business rules, in priority order (SCAFFOLD §1.4):
    # 9 ERR_ZONE_MISMATCH, 10 (n/a for non-regen), 11 ERR_WINDOW_OVERLAP,
    # 12 ERR_SERVICE_GAP_VIOLATION, 13 ERR_ROUTE_FULL.
    # Window coherence (window_end > window_start) is part of ERR_WINDOW_OVERLAP.

    # zone/active eligibility (priority 9)
    account = db.accounts.get(system["account_id"])
    if system["lifecycle_status"] != "ACTIVE" or account is None or \
            account["service_zone"] != route["service_zone"]:
        raise err("ERR_ZONE_MISMATCH", "System not ACTIVE or zone mismatch")

    # window coherence + overlap with existing SCHEDULED stops on same route (priority 11)
    if window_end <= window_start:
        raise err("ERR_WINDOW_OVERLAP", "window_end must be after window_start")
    for st in db.route_stops.values():
        if st["route_id"] != route["id"] or st["status"] != "SCHEDULED":
            continue
        es = parse_iso(st["window_start"], "window_start")
        ee = parse_iso(st["window_end"], "window_end")
        if _intervals_overlap(window_start, window_end, es, ee):
            raise err("ERR_WINDOW_OVERLAP", "Window overlaps an existing scheduled stop")

    # service-gap across ANY route for same system (priority 12)
    gap = C.MIN_SERVICE_GAP_HOURS * 3600
    for st in db.route_stops.values():
        if st["system_id"] != system_id:
            continue
        if st["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        es = parse_iso(st["window_start"], "window_start")
        ee = parse_iso(st["window_end"], "window_end")
        # within MIN_SERVICE_GAP_HOURS of each other (closest endpoints)
        if window_start < ee and es < window_end:
            raise err("ERR_SERVICE_GAP_VIOLATION", "Stops within service gap window")
        if window_start >= ee:
            delta = (window_start - ee).total_seconds()
        else:
            delta = (es - window_end).total_seconds()
        if delta < gap:
            raise err("ERR_SERVICE_GAP_VIOLATION", "Stops within service gap window")

    # capacity (priority 13)
    if route["stop_count"] + 1 > route["capacity_stops"]:
        raise err("ERR_ROUTE_FULL", "Route is at capacity")

    stop = new_primary({
        "route_id": route["id"],
        "system_id": system_id,
        "stop_type": stop_type,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "status": "SCHEDULED",
        "salt_bags_delivered": salt_bags,
    })
    db.route_stops[stop["id"]] = stop
    route["stop_count"] += 1
    touch(route)
    return object_response(stop, status=201)


@app.route("/routes/<rid>/stops", methods=["GET"])
def list_route_stops(rid):
    guard({"Dispatcher", "ServiceManager", "FieldTech"})
    get_or_404(db.routes, rid)
    limit, offset = paginate()
    recs = [r for r in db.route_stops.values() if r["route_id"] == rid]
    return list_collection(recs, limit, offset)


@app.route("/routes/<rid>/dispatch", methods=["POST"])
def dispatch_route(rid):
    guard({"Dispatcher", "ServiceManager"})
    route = get_or_404(db.routes, rid)
    if route["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Route is not PLANNED")
    if route["stop_count"] < 1:
        raise err("ERR_INVALID_STATE", "Route has no stops")
    route["status"] = "DISPATCHED"
    touch(route)
    return object_response(route, status=200)


@app.route("/routes/<rid>/complete", methods=["POST"])
def complete_route(rid):
    guard({"FieldTech", "ServiceManager"})
    route = get_or_404(db.routes, rid)
    if route["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Route is not DISPATCHED")
    # cascade: force-skip SCHEDULED stops
    for st in db.route_stops.values():
        if st["route_id"] == route["id"] and st["status"] == "SCHEDULED":
            st["status"] = "SKIPPED"
            touch(st)
    route["status"] = "COMPLETED"
    touch(route)
    return object_response(route, status=200)


# ===========================================================================
# Route Stops (peer access)
# ===========================================================================

@app.route("/route-stops/<rid>", methods=["GET"])
def get_route_stop(rid):
    guard({"Dispatcher", "ServiceManager", "FieldTech"})
    return object_response(get_or_404(db.route_stops, rid), status=200)


@app.route("/route-stops", methods=["GET"])
def list_all_route_stops():
    guard({"Dispatcher", "ServiceManager", "FieldTech"})
    limit, offset = paginate()
    system_id = request.args.get("system_id")
    recs = list(db.route_stops.values())
    if system_id is not None:
        recs = [r for r in recs if r["system_id"] == system_id]
    return list_collection(recs, limit, offset)


@app.route("/route-stops/<rid>/complete", methods=["POST"])
def complete_route_stop(rid):
    guard({"FieldTech", "ServiceManager"})
    stop = get_or_404(db.route_stops, rid)
    route = db.routes.get(stop["route_id"])
    system = db.systems.get(stop["system_id"])
    # state preconditions
    if stop["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Stop is not SCHEDULED")
    if route is None or route["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Parent route is not DISPATCHED")
    if system is None or system["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Serviced system is not ACTIVE")

    stop_type = stop["stop_type"]
    if stop_type == "REGEN_SERVICE":
        # subject to salt floor (PRD §3.4, §3.7)
        if system["salt_level_pct"] < C.SALT_MIN_REGEN_PCT:
            raise err("ERR_INSUFFICIENT_SALT", "Salt level below regeneration floor")

    if stop_type == "SALT_DELIVERY":
        bump = stop["salt_bags_delivered"] * C.SALT_PCT_PER_BAG
        system["salt_level_pct"] = min(100, system["salt_level_pct"] + bump)
        touch(system)
    elif stop_type == "REGEN_SERVICE":
        create_service_visit(system["id"], stop_id=stop["id"], visit_type="REGEN",
                             gallons_treated_reading=0, billable_cents=0)
        system["gallons_since_regen"] = 0
        system["regen_health"] = "NOMINAL"
        touch(system)
    elif stop_type == "FILTER_SWAP":
        for sched in db.cartridge_schedules.values():
            if sched["system_id"] == system["id"]:
                sched["replacements_logged"] += 1
                sched["last_replaced_at"] = clock.iso()
                sched["status"] = "ON_TRACK"
                touch(sched)
                break
    # INSPECTION: no side effects

    stop["status"] = "COMPLETED"
    touch(stop)
    return object_response(stop, status=200)


# ===========================================================================
# Cartridge Schedules
# ===========================================================================

@app.route("/cartridge-schedules", methods=["POST"])
def create_cartridge_schedule():
    guard({"ServiceManager", "FieldTech"})
    body = get_body()
    system_id = as_string(require_present(body, "system_id"), "system_id")
    fk_or_404(db.systems, system_id)
    cartridge_type = as_enum(require_present(body, "cartridge_type"),
                             "cartridge_type", C.CARTRIDGE_TYPES)
    interval_days = as_int(require_present(body, "interval_days"),
                           "interval_days", minimum=1)
    last_replaced_at_raw = require_present(body, "last_replaced_at")
    as_datetime(last_replaced_at_raw, "last_replaced_at")
    sched = new_primary({
        "system_id": system_id,
        "cartridge_type": cartridge_type,
        "interval_days": interval_days,
        "last_replaced_at": last_replaced_at_raw,
        "status": "ON_TRACK",
        "replacements_logged": 0,
    })
    db.cartridge_schedules[sched["id"]] = sched
    return object_response(sched, status=201)


@app.route("/cartridge-schedules/<rid>", methods=["GET"])
def get_cartridge_schedule(rid):
    guard({"ServiceManager", "FieldTech", "Customer"})
    return object_response(get_or_404(db.cartridge_schedules, rid), status=200)


def _due_date(sched):
    from datetime import timedelta
    last = parse_iso(sched["last_replaced_at"], "last_replaced_at")
    return last + timedelta(days=sched["interval_days"])


@app.route("/cartridge-schedules/<rid>/evaluate", methods=["POST"])
def evaluate_cartridge_schedule(rid):
    guard({"Dispatcher", "ServiceManager"})
    sched = get_or_404(db.cartridge_schedules, rid)
    from datetime import timedelta
    now = clock.now()
    due = _due_date(sched)
    overdue_at = due + timedelta(days=C.CARTRIDGE_GRACE_DAYS)
    lead_at = due - timedelta(days=C.CARTRIDGE_LEAD_DAYS)
    new_status = sched["status"]
    if now >= overdue_at:
        new_status = "OVERDUE"
    elif lead_at <= now < due:
        new_status = "DUE_SOON"
    if new_status != sched["status"]:
        sched["status"] = new_status
        touch(sched)
    return object_response(sched, status=200)


@app.route("/cartridge-schedules/<rid>/replace", methods=["POST"])
def replace_cartridge_schedule(rid):
    guard({"FieldTech", "ServiceManager"})
    sched = get_or_404(db.cartridge_schedules, rid)
    if sched["status"] not in ("DUE_SOON", "OVERDUE"):
        raise err("ERR_INVALID_STATE", "Schedule is not DUE_SOON or OVERDUE")
    sched["last_replaced_at"] = clock.iso()
    sched["status"] = "ON_TRACK"
    sched["replacements_logged"] += 1
    create_service_visit(sched["system_id"], stop_id=None,
                         visit_type="CARTRIDGE_REPLACE",
                         gallons_treated_reading=0, billable_cents=0)
    touch(sched)
    return object_response(sched, status=200)


# ===========================================================================
# Service Visits
# ===========================================================================

@app.route("/service-visits", methods=["POST"])
def create_service_visit_endpoint():
    guard({"FieldTech", "ServiceManager"})
    body = get_body()
    system_id = as_string(require_present(body, "system_id"), "system_id")
    fk_or_404(db.systems, system_id)
    stop_id = opt_string(body, "stop_id")
    if stop_id is not None:
        fk_or_404(db.route_stops, stop_id)
    visit_type = as_enum(require_present(body, "visit_type"), "visit_type", C.VISIT_TYPES)
    gallons = as_int(require_present(body, "gallons_treated_reading"),
                     "gallons_treated_reading", minimum=0)
    billable = body.get("billable_cents", 0)
    if billable is None:
        billable = 0
    billable = as_int(billable, "billable_cents", minimum=0)
    visit = new_primary({
        "system_id": system_id,
        "stop_id": stop_id,
        "visit_type": visit_type,
        "gallons_treated_reading": gallons,
        "status": "LOGGED",
        "billable_cents": billable,
    })
    db.service_visits[visit["id"]] = visit
    return object_response(visit, status=201)


@app.route("/service-visits/<rid>", methods=["GET"])
def get_service_visit(rid):
    guard({"FieldTech", "ServiceManager", "Customer"})
    return object_response(get_or_404(db.service_visits, rid), status=200)


@app.route("/service-visits", methods=["GET"])
def list_service_visits():
    guard({"FieldTech", "ServiceManager", "Customer"})
    limit, offset = paginate()
    system_id = request.args.get("system_id")
    stop_id = request.args.get("stop_id")
    recs = list(db.service_visits.values())
    if system_id is not None:
        recs = [r for r in recs if r["system_id"] == system_id]
    if stop_id is not None:
        recs = [r for r in recs if r.get("stop_id") == stop_id]
    return list_collection(recs, limit, offset)


@app.route("/service-visits/<rid>/confirm", methods=["POST"])
def confirm_service_visit(rid):
    guard({"FieldTech", "ServiceManager"})
    visit = get_or_404(db.service_visits, rid)
    if visit["status"] != "LOGGED":
        raise err("ERR_INVALID_STATE", "Visit is not LOGGED")
    if visit["billable_cents"] > 0:
        system = db.systems.get(visit["system_id"])
        account = db.accounts.get(system["account_id"]) if system else None
        if account is not None:
            inv = create_invoice_record(
                account,
                contract_id=None,
                supersedes_invoice_id=None,
                invoice_kind="SERVICE_REPAIR",
                period_start=clock.iso(),
                period_end=clock.iso(),
                amount_cents=visit["billable_cents"],
                due_offset_days=30,
            )
            visit["_confirm_invoice_id"] = inv["id"]
    visit["status"] = "CONFIRMED"
    touch(visit)
    return object_response(visit, status=200)


@app.route("/service-visits/<rid>/void", methods=["POST"])
def void_service_visit(rid):
    guard({"ServiceManager"})
    visit = get_or_404(db.service_visits, rid)
    if visit["status"] not in ("LOGGED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Visit is not LOGGED or CONFIRMED")
    inv_id = visit.get("_confirm_invoice_id")
    if inv_id is not None:
        inv = db.invoices.get(inv_id)
        if inv is not None and inv["status"] == "OPEN":
            account = db.accounts.get(inv["account_id"])
            if account is not None:
                ledger_credit(account, inv.get("_applied_amount", 0))
                touch(account)
            inv["status"] = "VOID"
            touch(inv)
    visit["status"] = "VOIDED"
    touch(visit)
    return object_response(visit, status=200)


# ===========================================================================
# Warranty Claims
# ===========================================================================

@app.route("/warranty-claims", methods=["POST"])
def create_warranty_claim():
    guard({"Customer", "FieldTech", "ServiceManager"})
    body = get_body()
    system_id = as_string(require_present(body, "system_id"), "system_id")
    fk_or_404(db.systems, system_id)
    contract_id = opt_string(body, "contract_id")
    if contract_id is not None:
        fk_or_404(db.rental_contracts, contract_id)
    defect_class = as_enum(require_present(body, "defect_class"),
                           "defect_class", C.DEFECT_CLASSES)
    reported_at_raw = require_present(body, "reported_at")
    as_datetime(reported_at_raw, "reported_at")
    claim = new_primary({
        "system_id": system_id,
        "contract_id": contract_id,
        "defect_class": defect_class,
        "reported_at": reported_at_raw,
        "status": "FILED",
        "covered": None,
        "settlement_cents": 0,
    })
    db.warranty_claims[claim["id"]] = claim
    return object_response(claim, status=201)


@app.route("/warranty-claims/<rid>", methods=["GET"])
def get_warranty_claim(rid):
    guard({"Customer", "FieldTech", "ServiceManager"})
    return object_response(get_or_404(db.warranty_claims, rid), status=200)


@app.route("/warranty-claims", methods=["GET"])
def list_warranty_claims():
    guard({"Customer", "FieldTech", "ServiceManager"})
    limit, offset = paginate()
    contract_id = request.args.get("contract_id")
    recs = list(db.warranty_claims.values())
    if contract_id is not None:
        recs = [r for r in recs if r.get("contract_id") == contract_id]
    return list_collection(recs, limit, offset)


@app.route("/warranty-claims/<rid>/triage", methods=["POST"])
def triage_warranty_claim(rid):
    guard({"FieldTech", "ServiceManager"})
    claim = get_or_404(db.warranty_claims, rid)
    if claim["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim is not FILED")
    system = db.systems.get(claim["system_id"])
    install_date = parse_iso(system["install_date"], "install_date") \
        if system and system.get("install_date") else None
    reported_at = parse_iso(claim["reported_at"], "reported_at")
    if install_date is None:
        claim["covered"] = False
    else:
        claim["covered"] = calc.coverage_covered(
            claim["defect_class"], install_date, reported_at)
    claim["status"] = "TRIAGED"
    touch(claim)
    return object_response(claim, status=200)


@app.route("/warranty-claims/<rid>/resolve", methods=["POST"])
def resolve_warranty_claim(rid):
    guard({"ServiceManager"})
    claim = get_or_404(db.warranty_claims, rid)
    body = get_body()
    resolution = as_enum(require_present(body, "resolution"), "resolution",
                         {"REPAIR", "REPLACE"})
    if claim["status"] != "TRIAGED":
        raise err("ERR_INVALID_STATE", "Claim is not TRIAGED")
    if resolution == "REPLACE" and not claim["covered"]:
        raise err("ERR_INVALID_STATE", "Uncovered claim cannot elect free replacement")
    system = db.systems.get(claim["system_id"])
    install_date = parse_iso(system["install_date"], "install_date") \
        if system and system.get("install_date") else clock.now()
    settlement = calc.claim_settlement(
        claim["defect_class"], bool(claim["covered"]), install_date, clock.now())
    claim["settlement_cents"] = settlement
    if resolution == "REPAIR":
        claim["status"] = "REPAIR"
        create_service_visit(claim["system_id"], stop_id=None, visit_type="REPAIR",
                             gallons_treated_reading=0, billable_cents=settlement)
    else:
        claim["status"] = "REPLACE"
    touch(claim)
    return object_response(claim, status=200)


@app.route("/warranty-claims/<rid>/deny", methods=["POST"])
def deny_warranty_claim(rid):
    guard({"ServiceManager"})
    claim = get_or_404(db.warranty_claims, rid)
    if claim["status"] != "TRIAGED":
        raise err("ERR_INVALID_STATE", "Claim is not TRIAGED")
    if claim["covered"]:
        raise err("ERR_INVALID_STATE", "Covered claim cannot be denied")
    claim["status"] = "DENIED"
    touch(claim)
    return object_response(claim, status=200)


@app.route("/warranty-claims/<rid>/close", methods=["POST"])
def close_warranty_claim(rid):
    guard({"ServiceManager"})
    claim = get_or_404(db.warranty_claims, rid)
    if claim["status"] not in ("REPAIR", "REPLACE"):
        raise err("ERR_INVALID_STATE", "Claim is not REPAIR or REPLACE")
    if claim["settlement_cents"] > 0:
        system = db.systems.get(claim["system_id"])
        account = db.accounts.get(system["account_id"]) if system else None
        if account is not None:
            create_invoice_record(
                account,
                contract_id=None,
                supersedes_invoice_id=None,
                invoice_kind="SERVICE_REPAIR",
                period_start=clock.iso(),
                period_end=clock.iso(),
                amount_cents=claim["settlement_cents"],
                due_offset_days=30,
            )
    claim["status"] = "CLOSED"
    touch(claim)
    return object_response(claim, status=200)


# ===========================================================================
# Invoices
# ===========================================================================

def _billable_days(contract, period_start, period_end):
    """Days in [period_start, period_end) the contract was ACTIVE (PRD §3.10).
    SUSPENDED intervals excluded; period_start inclusive, period_end exclusive.
    Computed in whole UTC days."""
    from datetime import timedelta
    suspended = list(contract.get("_suspend_intervals", []))
    if contract.get("_suspend_open") is not None:
        suspended = suspended + [(contract["_suspend_open"], None)]
    total = 0
    day = period_start
    while day < period_end:
        next_day = day + timedelta(days=1)
        is_suspended = False
        for (s_start, s_end) in suspended:
            end = s_end if s_end is not None else period_end
            if s_start <= day < end:
                is_suspended = True
                break
        if not is_suspended:
            total += 1
        day = next_day
    return total


@app.route("/invoices", methods=["POST"])
def create_invoice():
    guard({"BillingClerk", "ServiceManager"})
    body = get_body()
    account_id = as_string(require_present(body, "account_id"), "account_id")
    account = fk_or_404(db.accounts, account_id)
    contract_id = opt_string(body, "contract_id")
    contract = None
    if contract_id is not None:
        contract = fk_or_404(db.rental_contracts, contract_id)
    supersedes_invoice_id = opt_string(body, "supersedes_invoice_id")
    superseded = None
    if supersedes_invoice_id is not None:
        superseded = fk_or_404(db.invoices, supersedes_invoice_id)
    invoice_kind = as_enum(require_present(body, "invoice_kind"), "invoice_kind",
                           C.INVOICE_KINDS)
    period_start_raw = require_present(body, "period_start")
    period_end_raw = require_present(body, "period_end")
    period_start = as_datetime(period_start_raw, "period_start")
    period_end = as_datetime(period_end_raw, "period_end")
    if period_end <= period_start:
        raise err("ERR_INVALID_REQUEST", "period_end must be after period_start")
    due_offset_days = body.get("due_offset_days", 30)
    if due_offset_days is None:
        due_offset_days = 30
    due_offset_days = as_int(due_offset_days, "due_offset_days", minimum=0)

    # business: supersedes must point at a VOID invoice (priority 15)
    if superseded is not None and superseded["status"] != "VOID":
        raise err("ERR_SUPERSEDE_NOT_VOID", "supersedes_invoice_id is not a VOID invoice")

    # compute amount
    if invoice_kind in ("RENTAL_CYCLE", "PRORATION"):
        if contract is None:
            raise err("ERR_INVALID_REQUEST",
                      "contract_id required for %s invoices" % invoice_kind)
        billable_days = _billable_days(contract, period_start, period_end)
        amount = calc.rental_amount(invoice_kind, contract["monthly_rate_cents"],
                                    billable_days)
    else:
        # SERVICE_REPAIR / TERMINATION issued directly take amount from body? PRD
        # ties these to cascades; an explicit issue computes 0 unless provided.
        amount = body.get("amount_cents", 0)
        if amount is None:
            amount = 0
        amount = as_int(amount, "amount_cents", minimum=0)

    inv = new_primary({
        "account_id": account_id,
        "contract_id": contract_id,
        "supersedes_invoice_id": supersedes_invoice_id,
        "invoice_kind": invoice_kind,
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "amount_cents": amount,
        "status": "OPEN",
        "due_offset_days": due_offset_days,
    })
    applied = ledger_debit(account, amount)
    inv["_applied_amount"] = applied
    touch(account)
    if invoice_kind == "RENTAL_CYCLE" and contract is not None:
        contract["months_billed"] += 1
        touch(contract)
    db.invoices[inv["id"]] = inv
    return object_response(inv, status=201)


@app.route("/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    guard({"BillingClerk", "ServiceManager", "Customer"})
    return object_response(get_or_404(db.invoices, rid), status=200)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    guard({"BillingClerk", "ServiceManager", "Customer"})
    limit, offset = paginate()
    account_id = request.args.get("account_id")
    contract_id = request.args.get("contract_id")
    supersedes_invoice_id = request.args.get("supersedes_invoice_id")
    recs = list(db.invoices.values())
    if account_id is not None:
        recs = [r for r in recs if r["account_id"] == account_id]
    if contract_id is not None:
        recs = [r for r in recs if r.get("contract_id") == contract_id]
    if supersedes_invoice_id is not None:
        recs = [r for r in recs if r.get("supersedes_invoice_id") == supersedes_invoice_id]
    return list_collection(recs, limit, offset)


def _is_past_due(inv, now):
    from datetime import timedelta
    period_end = parse_iso(inv["period_end"], "period_end")
    due = period_end + timedelta(days=inv["due_offset_days"])
    return now > due


@app.route("/invoices/<rid>/evaluate", methods=["POST"])
def evaluate_invoice(rid):
    guard({"BillingClerk", "ServiceManager"})
    inv = get_or_404(db.invoices, rid)
    if inv["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Invoice is not OPEN")
    if _is_past_due(inv, clock.now()):
        inv["status"] = "PAST_DUE"
        account = db.accounts.get(inv["account_id"])
        if account is not None and account["standing"] != "DELINQUENT":
            account["standing"] = "DELINQUENT"
            account["_delinquent_invoice_id"] = inv["id"]
            touch(account)
        touch(inv)
    return object_response(inv, status=200)


@app.route("/invoices/<rid>/pay", methods=["POST"])
def pay_invoice(rid):
    guard({"BillingClerk", "ServiceManager"})
    inv = get_or_404(db.invoices, rid)
    if inv["status"] in ("PAID", "VOID"):
        raise err("ERR_INVOICE_CLOSED", "Invoice is already PAID or VOID")
    if inv["status"] not in ("OPEN", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Invoice is not OPEN or PAST_DUE")
    inv["status"] = "PAID"
    account = db.accounts.get(inv["account_id"])
    if account is not None:
        if not _has_other_past_due(inv["account_id"], inv["id"]):
            if account["standing"] != "GOOD":
                account["standing"] = "GOOD"
                account.pop("_delinquent_invoice_id", None)
                touch(account)
    touch(inv)
    return object_response(inv, status=200)


@app.route("/invoices/<rid>/void", methods=["POST"])
def void_invoice(rid):
    guard({"BillingClerk", "ServiceManager"})
    inv = get_or_404(db.invoices, rid)
    if inv["status"] in ("PAID", "VOID"):
        raise err("ERR_INVOICE_CLOSED", "Invoice is already PAID or VOID")
    if inv["status"] not in ("OPEN", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Invoice is not OPEN or PAST_DUE")
    account = db.accounts.get(inv["account_id"])
    # reverse ledger debit by exact applied amount
    if account is not None:
        ledger_credit(account, inv.get("_applied_amount", 0))
        touch_account = True
    else:
        touch_account = False
    # rental-cycle conservation of months_billed
    if inv["invoice_kind"] == "RENTAL_CYCLE" and inv.get("contract_id"):
        contract = db.rental_contracts.get(inv["contract_id"])
        if contract is not None:
            contract["months_billed"] -= 1
            touch(contract)
    was_delinquency_driver = (
        account is not None
        and account.get("_delinquent_invoice_id") == inv["id"]
    )
    inv["status"] = "VOID"
    # restore standing if this invoice drove delinquency and no other past-due
    if account is not None:
        if was_delinquency_driver and not _has_other_past_due(inv["account_id"], inv["id"]):
            account["standing"] = "GOOD"
            account.pop("_delinquent_invoice_id", None)
        touch(account)
    touch(inv)
    return object_response(inv, status=200)


# ===========================================================================
# Logical clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    guard({"ServiceManager", "Dispatcher", "BillingClerk"})
    body = get_body()
    to_iso = require_present(body, "to_iso8601")
    dt = as_datetime(to_iso, "to_iso8601")
    clock.set(dt)
    return success({"current_utc": clock.iso()}, status=200, response_type="object")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
