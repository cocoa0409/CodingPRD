"""Core entity routes: regulatory profiles, borrowers, vehicles, appraisals,
plus the test clock (PRD 3.1, 3.2, 2.10)."""
from flask import Blueprint

import db
import lookups
import calculations as calc
from clock import set_now, get_now
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public
from timeutil import iso_now, parse_iso
from validate import (get_body, require_str, require_int, require_enum,
                      parse_pagination, paginate)

bp = Blueprint("core", __name__)

STATE_CODES = {"CA", "TX", "FL", "VA", "AZ"}
VALUATION_BASES = {"TRADE_IN", "AUCTION"}
CONDITION_GRADES = {"EXCELLENT", "GOOD", "FAIR", "POOR"}


def _sorted_public(entities):
    rows = sorted(entities, key=lambda e: e["_seq"])
    return [public(e) for e in rows]


# ---------------------------------------------------------------------------
# Test-driving clock (PRD 2.10) — NOT under /atl
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"ComplianceAdmin"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    set_now(dt)
    return success({"current_utc": iso_now(get_now())}, status=200)


# ---------------------------------------------------------------------------
# RegulatoryProfile (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/atl/regulatory-profiles", methods=["POST"])
def create_regulatory_profile():
    _, role = authenticate()
    require_role(role, {"ComplianceAdmin"})
    body = get_body()

    state_code = require_enum(body, "state_code", STATE_CODES)
    max_apr_bps = require_int(body, "max_apr_bps")
    max_ltv_bps = require_int(body, "max_ltv_bps")
    max_renewals = require_int(body, "max_renewals")
    min_term_months = require_int(body, "min_term_months")
    max_term_months = require_int(body, "max_term_months")
    redemption_grace_days = require_int(body, "redemption_grace_days")
    valuation_basis = require_enum(body, "valuation_basis", VALUATION_BASES)

    # Range checks (PRD 3.1 constraints) -> ERR_VALIDATION_RANGE
    if max_apr_bps <= 0:
        raise err("ERR_VALIDATION_RANGE", "max_apr_bps must be > 0")
    if not (max_ltv_bps > 0 and max_ltv_bps <= 10000):
        raise err("ERR_VALIDATION_RANGE", "max_ltv_bps must be in (0, 10000]")
    if max_renewals < 0:
        raise err("ERR_VALIDATION_RANGE", "max_renewals must be >= 0")
    if min_term_months < 1:
        raise err("ERR_VALIDATION_RANGE", "min_term_months must be >= 1")
    if max_term_months < min_term_months:
        raise err("ERR_VALIDATION_RANGE", "max_term_months must be >= min_term_months")
    if redemption_grace_days < 0:
        raise err("ERR_VALIDATION_RANGE", "redemption_grace_days must be >= 0")

    # state_code unique across profiles (PRD 3.1). Reported as a state conflict.
    if lookups.regulatory_profile_for_state(state_code) is not None:
        raise err("ERR_INVALID_STATE", "regulatory profile for state already exists")

    # RegulatoryProfile carries only id and created_at (PRD 2.4).
    prof = db.common_fields(with_version=False)
    prof.update({
        "state_code": state_code,
        "max_apr_bps": max_apr_bps,
        "max_ltv_bps": max_ltv_bps,
        "max_renewals": max_renewals,
        "min_term_months": min_term_months,
        "max_term_months": max_term_months,
        "redemption_grace_days": redemption_grace_days,
        "valuation_basis": valuation_basis,
    })
    db.regulatory_profiles[prof["id"]] = prof
    return success(public(prof), status=201)


@bp.route("/atl/regulatory-profiles", methods=["GET"])
def list_regulatory_profiles():
    _, role = authenticate()
    require_role(role, {"ComplianceAdmin", "Underwriter", "Appraiser",
                        "LoanServicer", "RecoveryManager", "TitleClerk"})
    limit, offset = parse_pagination()
    state_code = None
    from flask import request
    state_code = request.args.get("state_code")
    rows = list(db.regulatory_profiles.values())
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


# ---------------------------------------------------------------------------
# Borrower (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/atl/borrowers", methods=["POST"])
def create_borrower():
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin"})
    body = get_body()

    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    state_code = require_enum(body, "state_code", STATE_CODES)
    monthly_income_cents = require_int(body, "monthly_income_cents")

    if monthly_income_cents < 0:
        raise err("ERR_VALIDATION_RANGE", "monthly_income_cents must be >= 0")

    # email unique across borrowers (PRD 3.1).
    for b in db.borrowers.values():
        if b["email"] == email:
            raise err("ERR_INVALID_STATE", "borrower email already registered")

    borrower = db.common_fields(with_version=True)
    borrower.update({
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "monthly_income_cents": monthly_income_cents,
        "status": "ACTIVE",
    })
    db.borrowers[borrower["id"]] = borrower
    return success(public(borrower), status=201)


@bp.route("/atl/borrowers/<borrower_id>", methods=["GET"])
def get_borrower(borrower_id):
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin", "LoanServicer", "Appraiser"})
    borrower = lookups.get_or_404(db.borrowers, borrower_id)
    return success(public(borrower), status=200)


@bp.route("/atl/borrowers/<borrower_id>/vehicles", methods=["GET"])
def list_borrower_vehicles(borrower_id):
    _, role = authenticate()
    require_role(role, {"Underwriter", "ComplianceAdmin", "Appraiser", "LoanServicer"})
    lookups.get_or_404(db.borrowers, borrower_id)
    limit, offset = parse_pagination()
    rows = [v for v in db.vehicles.values() if v["borrower_id"] == borrower_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


# ---------------------------------------------------------------------------
# Vehicle (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/atl/vehicles", methods=["POST"])
def create_vehicle():
    _, role = authenticate()
    require_role(role, {"Appraiser", "Underwriter"})
    body = get_body()

    # Existence of referenced identifiers runs before body field-level validation
    # (PRD 2.5 / 2.6 step 4 precedes step 5). Resolve the FK first.
    borrower_id = require_str(body, "borrower_id")
    lookups.get_or_404(db.borrowers, borrower_id)

    vin = require_str(body, "vin")
    year = require_int(body, "year")
    make = require_str(body, "make")
    model = require_str(body, "model")
    odometer_miles = require_int(body, "odometer_miles")

    if odometer_miles < 0:
        raise err("ERR_VALIDATION_RANGE", "odometer_miles must be >= 0")

    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise err("ERR_INVALID_STATE", "vin already registered")

    vehicle = db.common_fields(with_version=True)
    vehicle.update({
        "borrower_id": borrower_id,
        "vin": vin,
        "year": year,
        "make": make,
        "model": model,
        "odometer_miles": odometer_miles,
        "lien_state": "CLEAR",
    })
    db.vehicles[vehicle["id"]] = vehicle
    return success(public(vehicle), status=201)


@bp.route("/atl/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    _, role = authenticate()
    require_role(role, {"Appraiser", "Underwriter", "LoanServicer", "RecoveryManager", "TitleClerk"})
    vehicle = lookups.get_or_404(db.vehicles, vehicle_id)
    return success(public(vehicle), status=200)


@bp.route("/atl/vehicles/<vehicle_id>/appraisals", methods=["GET"])
def list_vehicle_appraisals(vehicle_id):
    _, role = authenticate()
    require_role(role, {"Appraiser", "Underwriter"})
    lookups.get_or_404(db.vehicles, vehicle_id)
    limit, offset = parse_pagination()
    rows = [a for a in db.appraisals.values() if a["vehicle_id"] == vehicle_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


@bp.route("/atl/vehicles/<vehicle_id>/devices", methods=["GET"])
def list_vehicle_devices(vehicle_id):
    _, role = authenticate()
    require_role(role, {"LoanServicer", "RecoveryManager", "Appraiser"})
    lookups.get_or_404(db.vehicles, vehicle_id)
    limit, offset = parse_pagination()
    rows = [d for d in db.devices.values() if d["vehicle_id"] == vehicle_id]
    items = _sorted_public(rows)
    return list_success(paginate(items, limit, offset), limit, offset, len(items))


# ---------------------------------------------------------------------------
# Appraisal (PRD 3.2)
# ---------------------------------------------------------------------------
@bp.route("/atl/appraisals", methods=["POST"])
def create_appraisal():
    _, role = authenticate()
    require_role(role, {"Appraiser"})
    body = get_body()

    # Resolve referenced identifier before body field-level validation (PRD 2.5).
    vehicle_id = require_str(body, "vehicle_id")
    lookups.get_or_404(db.vehicles, vehicle_id)

    trade_in_value_cents = require_int(body, "trade_in_value_cents")
    auction_value_cents = require_int(body, "auction_value_cents")
    condition_grade = require_enum(body, "condition_grade", CONDITION_GRADES)

    # Range/constraint checks (PRD 3.2): trade_in > 0; 0 < auction <= trade_in.
    if trade_in_value_cents <= 0:
        raise err("ERR_VALIDATION_RANGE", "trade_in_value_cents must be > 0")
    if auction_value_cents <= 0:
        raise err("ERR_VALIDATION_RANGE", "auction_value_cents must be > 0")
    if auction_value_cents > trade_in_value_cents:
        raise err("ERR_VALIDATION_RANGE", "auction_value_cents must be <= trade_in_value_cents")

    appraisal = db.common_fields(with_version=True)
    appraisal.update({
        "vehicle_id": vehicle_id,
        "trade_in_value_cents": trade_in_value_cents,
        "auction_value_cents": auction_value_cents,
        "condition_grade": condition_grade,
        "basis_value_cents": None,
        "max_principal_cents": None,
        "status": "DRAFT",
        "_finalized_by": None,
    })
    db.appraisals[appraisal["id"]] = appraisal
    return success(public(appraisal), status=201)


@bp.route("/atl/appraisals/<appraisal_id>", methods=["GET"])
def get_appraisal(appraisal_id):
    _, role = authenticate()
    require_role(role, {"Appraiser", "Underwriter"})
    appraisal = lookups.get_or_404(db.appraisals, appraisal_id)
    return success(public(appraisal), status=200)


@bp.route("/atl/appraisals/<appraisal_id>/finalize", methods=["POST"])
def finalize_appraisal(appraisal_id):
    user_id, role = authenticate()
    require_role(role, {"Appraiser"})
    appraisal = lookups.get_or_404(db.appraisals, appraisal_id)

    if appraisal["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "appraisal not in DRAFT")

    vehicle = db.vehicles.get(appraisal["vehicle_id"])
    borrower = db.borrowers.get(vehicle["borrower_id"]) if vehicle else None
    prof = lookups.borrower_regulatory_profile(borrower) if borrower else None
    if prof is None:
        # The borrower's state must have a configured regulatory profile to
        # select the valuation basis and LTV. Absence is a state problem.
        raise err("ERR_INVALID_STATE", "no regulatory profile for borrower state")

    if prof["valuation_basis"] == "TRADE_IN":
        raw = appraisal["trade_in_value_cents"]
    else:
        raw = appraisal["auction_value_cents"]

    basis_value = calc.appraisal_basis_value(raw, appraisal["condition_grade"])
    max_principal = calc.max_principal_from_ltv(basis_value, prof["max_ltv_bps"])

    appraisal["basis_value_cents"] = basis_value
    appraisal["max_principal_cents"] = max_principal
    appraisal["status"] = "FINALIZED"
    appraisal["_finalized_by"] = user_id
    db.touch(appraisal)
    return success(public(appraisal), status=200)
