import os
import re
import secrets

from flask import Flask, request

import errors
from errors import ApiError, err
from response import success, error_response
from clock import clock
from db import db, new_common, touch
from middleware import authenticate, require_role, require_owner
from pagination import parse_pagination, paginate
import util
import serialize
import services

app = Flask(__name__)

ZONE_RE = re.compile(r"^[A-Z0-9]+$")


# ===========================================================================
# Error handling
# ===========================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 422)


def get_json():
    """Parse the request JSON body, defaulting to {} for empty bodies on action
    endpoints. Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body.")
    if body is None:
        return {}
    return body


# ===========================================================================
# Generic list / fetch helpers
# ===========================================================================

def do_list(collection, serializer, filters=None):
    limit, offset = parse_pagination()
    items = list(collection.values())
    if filters:
        for field, value in filters.items():
            if value is not None:
                items = [r for r in items if r.get(field) == value]
    page, meta = paginate(items, limit, offset)
    return success([serializer(r) for r in page], status=200, pagination=meta)


def fetch_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, "Resource not found.")
    return rec


# ===========================================================================
# Clock (test-driving) — FareAdmin only (PRD §2.8)
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    body = util.require_body(get_json())
    dt = util.req_datetime(body, "to_iso8601")
    clock.set(dt)
    from response import iso_ms
    return success({"current_utc": iso_ms(dt)}, status=200)


# ===========================================================================
# FareProduct (PRD §3.1)
# ===========================================================================

@app.route("/fare-products", methods=["POST"])
def create_fare_product():
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    body = util.require_body(get_json())

    zone_code = util.req_str(body, "zone_code", 1, 100)
    if not ZONE_RE.match(zone_code):
        raise err(errors.ERR_INVALID_REQUEST, "zone_code must be uppercase alphanumeric.")
    base_fare = util.req_int(body, "base_fare_cents", 0)
    daily_cap = util.req_int(body, "daily_cap_cents", base_fare)
    weekly_cap = util.req_int(body, "weekly_cap_cents", daily_cap)
    transfer_window = util.opt_int(body, "transfer_window_minutes", 1, default=120)
    transfer_discount = util.opt_number(body, "transfer_discount_pct", 0.0, 1.0,
                                        min_inclusive=True, max_inclusive=True, default=1.0)
    reduced_fare = util.opt_number(body, "reduced_fare_pct", 0.0, 1.0,
                                   min_inclusive=True, max_inclusive=False, default=0.5)

    # zone_code unique among ACTIVE products (PRD §3.1).
    for p in db.fare_products.values():
        if p["zone_code"] == zone_code and p["status"] == "ACTIVE":
            raise err(errors.ERR_INVALID_REQUEST, "zone_code already in use by an ACTIVE product.")

    rec = new_common()
    rec.update({
        "zone_code": zone_code,
        "base_fare_cents": base_fare,
        "daily_cap_cents": daily_cap,
        "weekly_cap_cents": weekly_cap,
        "transfer_window_minutes": transfer_window,
        "transfer_discount_pct": transfer_discount,
        "reduced_fare_pct": reduced_fare,
        "status": "ACTIVE",
    })
    db.fare_products[rec["id"]] = rec
    return success(serialize.fare_product_out(rec), status=201)


@app.route("/fare-products", methods=["GET"])
def list_fare_products():
    authenticate(allow_anonymous=True)
    return do_list(db.fare_products, serialize.fare_product_out, {
        "zone_code": request.args.get("zone_code"),
        "status": request.args.get("status"),
    })


@app.route("/fare-products/<rid>", methods=["GET"])
def get_fare_product(rid):
    authenticate(allow_anonymous=True)
    rec = fetch_or_404(db.fare_products, rid)
    return success(serialize.fare_product_out(rec), status=200)


@app.route("/fare-products/<rid>/retire", methods=["POST"])
def retire_fare_product(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.fare_products, rid)
    rec["status"] = "RETIRED"
    touch(rec)
    return success(serialize.fare_product_out(rec), status=200)


# ===========================================================================
# Rider (PRD §3.2)
# ===========================================================================

@app.route("/riders", methods=["POST"])
def create_rider():
    # Registration is the one creation open to Anonymous.
    _, role = authenticate(allow_anonymous=True)
    require_role(role, {"Anonymous"})
    body = util.require_body(get_json())

    email = util.req_str(body, "email", 1, 320)
    full_name = util.req_str(body, "full_name", 1, 320)
    home_zone = util.req_str(body, "home_zone_code", 1, 100)
    income_tier = util.opt_enum(body, "income_tier", {"STANDARD", "LOW_INCOME"}, "STANDARD")
    low_income_pct = util.opt_number(body, "low_income_discount_pct", 0.0, 1.0,
                                     min_inclusive=True, max_inclusive=False, default=0.5)

    # email unique across all riders (PRD §3.2).
    for r in db.riders.values():
        if r["email"] == email:
            raise err(errors.ERR_INVALID_REQUEST, "email already registered.")

    # home_zone_code must match an ACTIVE FareProduct.zone_code at registration.
    if services._active_product_for_zone(home_zone) is None:
        raise err(errors.ERR_INVALID_REQUEST, "home_zone_code must match an ACTIVE fare product zone.")

    rec = new_common()
    rec.update({
        "email": email,
        "full_name": full_name,
        "home_zone_code": home_zone,
        "income_tier": income_tier,
        "low_income_discount_pct": low_income_pct,
        "status": "ACTIVE",
    })
    db.riders[rec["id"]] = rec
    return success(serialize.rider_out(rec), status=201)


@app.route("/riders/<rid>", methods=["GET"])
def get_rider(rid):
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider", "EmployerAdmin"})
    rec = fetch_or_404(db.riders, rid)
    # Ownership: a Rider may fetch only their own record.
    require_owner(role, user_id, rec["id"])
    return success(serialize.rider_out(rec), status=200)


@app.route("/riders/<rid>/risk", methods=["GET"])
def get_rider_risk(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.riders, rid)
    mode = request.args.get("mode")
    if mode is None:
        mode = "trailing_week"
    if mode not in ("gross", "trailing_week"):
        raise err(errors.ERR_INVALID_REQUEST, "mode must be 'gross' or 'trailing_week'.")
    score = services.rider_risk_score(rec, mode)
    return success({"rider_id": rec["id"], "rider_risk_score": score, "mode": mode}, status=200)


@app.route("/riders/<rid>/suspend", methods=["POST"])
def suspend_rider(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.riders, rid)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(serialize.rider_out(rec), status=200)


# ===========================================================================
# FundingSource (PRD §3.3)
# ===========================================================================

@app.route("/funding-sources", methods=["POST"])
def create_funding_source():
    user_id, role = authenticate()
    require_role(role, {"Rider"})
    body = util.require_body(get_json())

    # Read rider_id for ownership (priority 3) before existence (priority 4).
    rider_id = body.get("rider_id")
    require_owner(role, user_id, rider_id if isinstance(rider_id, str) else None)

    if not isinstance(rider_id, str) or not rider_id:
        raise err(errors.ERR_INVALID_REQUEST, "rider_id must be a string.")
    rider = db.riders.get(rider_id)
    if rider is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced rider does not exist.")

    source_type = util.req_enum(body, "source_type", {"APPLE_PAY", "GOOGLE_PAY", "CONTACTLESS_CARD"})
    is_default = util.opt_bool(body, "is_default", True)

    rec = new_common()
    rec.update({
        "rider_id": rider_id,
        "source_type": source_type,
        "prepaid_balance_cents": 0,
        "is_default": is_default,
        "status": "ACTIVE",
    })
    db.funding_sources[rec["id"]] = rec
    return success(serialize.funding_source_out(rec), status=201)


@app.route("/funding-sources", methods=["GET"])
def list_funding_sources():
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rider_filter = request.args.get("rider_id")
    if role == "Rider":
        rider_filter = user_id
    return do_list(db.funding_sources, serialize.funding_source_out, {
        "rider_id": rider_filter,
        "status": request.args.get("status"),
    })


@app.route("/funding-sources/<rid>", methods=["GET"])
def get_funding_source(rid):
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rec = fetch_or_404(db.funding_sources, rid)
    require_owner(role, user_id, rec["rider_id"])
    return success(serialize.funding_source_out(rec), status=200)


@app.route("/funding-sources/<rid>/load", methods=["POST"])
def load_funding_source(rid):
    user_id, role = authenticate()
    require_role(role, {"Rider", "FareAdmin"})
    rec = fetch_or_404(db.funding_sources, rid)
    require_owner(role, user_id, rec["rider_id"])
    body = util.require_body(get_json())
    amount = util.req_int(body, "amount_cents", 1)
    rec["prepaid_balance_cents"] += amount
    touch(rec)
    return success(serialize.funding_source_out(rec), status=200)


# ===========================================================================
# ReducedFareCard (PRD §3.4)
# ===========================================================================

@app.route("/reduced-fare-cards", methods=["POST"])
def create_reduced_fare_card():
    user_id, role = authenticate()
    require_role(role, {"Rider"})
    body = util.require_body(get_json())

    rider_id = body.get("rider_id")
    require_owner(role, user_id, rider_id if isinstance(rider_id, str) else None)

    if not isinstance(rider_id, str) or not rider_id:
        raise err(errors.ERR_INVALID_REQUEST, "rider_id must be a string.")
    rider = db.riders.get(rider_id)
    if rider is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced rider does not exist.")

    program_code = util.req_enum(body, "program_code", {"SENIOR", "DISABILITY", "STUDENT"})
    expires_on, _ = util.req_date_str(body, "expires_on")

    rec = new_common()
    rec.update({
        "rider_id": rider_id,
        "program_code": program_code,
        "expires_on": expires_on,
        "verification_token": "vtok_" + secrets.token_hex(16),
        "status": "PENDING_VERIFICATION",
    })
    db.reduced_fare_cards[rec["id"]] = rec
    return success(serialize.reduced_fare_card_out(rec), status=201)


@app.route("/reduced-fare-cards", methods=["GET"])
def list_reduced_fare_cards():
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rider_filter = request.args.get("rider_id")
    if role == "Rider":
        rider_filter = user_id
    return do_list(db.reduced_fare_cards, serialize.reduced_fare_card_out, {
        "rider_id": rider_filter,
        "status": request.args.get("status"),
    })


@app.route("/reduced-fare-cards/<rid>", methods=["GET"])
def get_reduced_fare_card(rid):
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rec = fetch_or_404(db.reduced_fare_cards, rid)
    require_owner(role, user_id, rec["rider_id"])
    return success(serialize.reduced_fare_card_out(rec), status=200)


@app.route("/reduced-fare-cards/<rid>", methods=["PATCH"])
def patch_reduced_fare_card(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.reduced_fare_cards, rid)
    body = util.require_body(get_json())
    expires_on, _ = util.req_date_str(body, "expires_on")
    rec["expires_on"] = expires_on
    touch(rec)
    return success(serialize.reduced_fare_card_out(rec), status=200)


@app.route("/reduced-fare-cards/<rid>/verify", methods=["POST"])
def verify_reduced_fare_card(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.reduced_fare_cards, rid)
    body = util.require_body(get_json())
    token = util.req_str(body, "verification_token", 1, 200)

    # State (priority 6): verify is defined only out of PENDING_VERIFICATION or
    # EXPIRED.
    if rec["status"] not in ("PENDING_VERIFICATION", "EXPIRED"):
        raise err(errors.ERR_INVALID_STATE, "Card is not in a verifiable state.")

    # Business: token must match (priority 9).
    if token != rec["verification_token"]:
        raise err(errors.ERR_BAD_VERIFICATION_TOKEN, "Verification token does not match.")

    # Business: expires_on must be on or after the current fare day (priority 10).
    cur_fday = clock.now().date()
    exp = util.parse_iso_date(rec["expires_on"])
    if exp is None or exp < cur_fday:
        raise err(errors.ERR_CARD_EXPIRED, "Card has expired.")

    rec["status"] = "VERIFIED"
    touch(rec)
    return success(serialize.reduced_fare_card_out(rec), status=200)


@app.route("/reduced-fare-cards/<rid>/refresh-expiry", methods=["POST"])
def refresh_expiry_reduced_fare_card(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.reduced_fare_cards, rid)
    # Re-evaluate a VERIFIED card against the current clock; move to EXPIRED only
    # when expires_on is strictly before the current fare day (PRD §3.4).
    if rec["status"] == "VERIFIED":
        cur_fday = clock.now().date()
        exp = util.parse_iso_date(rec["expires_on"])
        if exp is not None and exp < cur_fday:
            rec["status"] = "EXPIRED"
            touch(rec)
    return success(serialize.reduced_fare_card_out(rec), status=200)


@app.route("/reduced-fare-cards/<rid>/revoke", methods=["POST"])
def revoke_reduced_fare_card(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.reduced_fare_cards, rid)
    # Revoke is defined from PENDING_VERIFICATION, VERIFIED, or EXPIRED (PRD §3.4).
    if rec["status"] not in ("PENDING_VERIFICATION", "VERIFIED", "EXPIRED"):
        raise err(errors.ERR_INVALID_STATE, "Card cannot be revoked from its current state.")
    rec["status"] = "REVOKED"
    touch(rec)
    return success(serialize.reduced_fare_card_out(rec), status=200)


# ===========================================================================
# BenefitAllocation (PRD §3.5)
# ===========================================================================

@app.route("/benefit-allocations", methods=["POST"])
def create_benefit_allocation():
    _, role = authenticate()
    require_role(role, {"EmployerAdmin"})
    body = util.require_body(get_json())

    # Existence (priority 4): rider FK.
    rider_id = body.get("rider_id")
    if not isinstance(rider_id, str) or not rider_id:
        raise err(errors.ERR_INVALID_REQUEST, "rider_id must be a string.")
    rider = db.riders.get(rider_id)
    if rider is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced rider does not exist.")

    # Body well-formedness (priority 5).
    employer_ref = util.req_str(body, "employer_ref", 1, 200)
    period_month = util.req_month_str(body, "period_month")
    allocated_cents = util.req_int(body, "allocated_cents", 1)
    expected_rider_version = util.req_int(body, "expected_rider_version")

    # Duplicate / supersede branching (priority 11): is there an existing ACTIVE
    # allocation for (rider_id, period_month)?
    existing_active = None
    for a in db.benefit_allocations.values():
        if (a["rider_id"] == rider_id and a["period_month"] == period_month
                and a["status"] == "ACTIVE"):
            existing_active = a
            break

    # FSA cap (priority 12).
    if allocated_cents > services.MONTHLY_FSA_CAP_CENTS:
        raise err(errors.ERR_FSA_CAP_EXCEEDED, "allocated_cents exceeds the monthly Transit FSA maximum.")

    if existing_active is not None:
        # OCC supersede (priority 13): expected_rider_version must match.
        if expected_rider_version != rider["version"]:
            raise err(errors.ERR_STALE_RIDER_VERSION, "Stale rider version on supersede.")
        existing_active["status"] = "SUPERSEDED"
        touch(existing_active)
        # A successful supersede increments the rider's version by one and
        # refreshes its updated_at (PRD §2.7, §3.5).
        touch(rider)
    # When no active allocation exists, a plain create proceeds (no version bump).

    rec = new_common()
    rec.update({
        "rider_id": rider_id,
        "employer_ref": employer_ref,
        "period_month": period_month,
        "allocated_cents": allocated_cents,
        "consumed_cents": 0,
        "status": "ACTIVE",
    })
    db.benefit_allocations[rec["id"]] = rec
    return success(serialize.benefit_allocation_out(rec), status=201)


@app.route("/benefit-allocations", methods=["GET"])
def list_benefit_allocations():
    _, role = authenticate()
    require_role(role, {"FareAdmin", "EmployerAdmin", "Rider"})
    return do_list(db.benefit_allocations, serialize.benefit_allocation_out, {
        "rider_id": request.args.get("rider_id"),
        "period_month": request.args.get("period_month"),
        "status": request.args.get("status"),
    })


@app.route("/benefit-allocations/<rid>", methods=["GET"])
def get_benefit_allocation(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin", "EmployerAdmin", "Rider"})
    rec = fetch_or_404(db.benefit_allocations, rid)
    return success(serialize.benefit_allocation_out(rec), status=200)


# ===========================================================================
# FareWeek (PRD §3.6, §3.11)
# ===========================================================================

@app.route("/fare-weeks", methods=["POST"])
def create_fare_week():
    user_id, role = authenticate()
    require_role(role, {"Rider", "FareAdmin"})
    body = util.require_body(get_json())

    rider_id = body.get("rider_id")
    require_owner(role, user_id, rider_id if isinstance(rider_id, str) else None)

    if not isinstance(rider_id, str) or not rider_id:
        raise err(errors.ERR_INVALID_REQUEST, "rider_id must be a string.")
    rider = db.riders.get(rider_id)
    if rider is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced rider does not exist.")

    week_start_raw, week_start = util.req_date_str(body, "week_start_date")
    zone_code = util.req_str(body, "zone_code", 1, 100)

    # week_start_date must be a Monday (PRD §3.6). Monday => weekday() == 0.
    if week_start.weekday() != 0:
        raise err(errors.ERR_INVALID_REQUEST, "week_start_date must be a Monday.")

    # Unique per (rider_id, week_start_date) (PRD §3.6).
    for w in db.fare_weeks.values():
        if w["rider_id"] == rider_id and w["week_start_date"] == week_start_raw:
            raise err(errors.ERR_INVALID_REQUEST, "A fare week already exists for this rider and week start.")

    rec = new_common()
    rec.update({
        "rider_id": rider_id,
        "week_start_date": week_start_raw,
        "zone_code": zone_code,
        "charged_total_cents": 0,
        "status": "OPEN",
    })
    db.fare_weeks[rec["id"]] = rec
    return success(serialize.fare_week_out(rec), status=201)


@app.route("/fare-weeks", methods=["GET"])
def list_fare_weeks():
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rider_filter = request.args.get("rider_id")
    if role == "Rider":
        rider_filter = user_id
    return do_list(db.fare_weeks, serialize.fare_week_out, {
        "rider_id": rider_filter,
        "status": request.args.get("status"),
    })


@app.route("/fare-weeks/<rid>", methods=["GET"])
def get_fare_week(rid):
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rec = fetch_or_404(db.fare_weeks, rid)
    require_owner(role, user_id, rec["rider_id"])
    return success(serialize.fare_week_out(rec), status=200)


@app.route("/fare-weeks/<rid>/close", methods=["POST"])
def close_fare_week(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.fare_weeks, rid)
    # State (priority 6): defined only out of OPEN.
    if rec["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Fare week is not OPEN.")
    # No PENDING tap may reference this week (PRD §3.11).
    for t in db.taps.values():
        if t["fare_week_id"] == rec["id"] and t["status"] == "PENDING":
            raise err(errors.ERR_INVALID_STATE, "Fare week has a PENDING tap.")
    rec["status"] = "CLOSED"
    touch(rec)
    return success(serialize.fare_week_out(rec), status=200)


# ===========================================================================
# Tap (PRD §3.6, §3.7, §3.9, §3.10)
# ===========================================================================

@app.route("/taps", methods=["POST"])
def create_tap():
    user_id, role = authenticate()
    require_role(role, {"Rider"})
    body = util.require_body(get_json())

    # Ownership (priority 3) before existence (priority 4).
    rider_id = body.get("rider_id")
    require_owner(role, user_id, rider_id if isinstance(rider_id, str) else None)

    # Existence (priority 4): rider, then fare_week, then funding_source,
    # validated left-to-right (PRD §2.10).
    if not isinstance(rider_id, str) or not rider_id:
        raise err(errors.ERR_INVALID_REQUEST, "rider_id must be a string.")
    rider = db.riders.get(rider_id)
    if rider is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced rider does not exist.")

    fare_week_id = body.get("fare_week_id")
    if not isinstance(fare_week_id, str) or not fare_week_id:
        raise err(errors.ERR_INVALID_REQUEST, "fare_week_id must be a string.")
    fare_week = db.fare_weeks.get(fare_week_id)
    if fare_week is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced fare week does not exist.")

    funding_source_id = body.get("funding_source_id")
    if not isinstance(funding_source_id, str) or not funding_source_id:
        raise err(errors.ERR_INVALID_REQUEST, "funding_source_id must be a string.")
    funding_source = db.funding_sources.get(funding_source_id)
    if funding_source is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced funding source does not exist.")

    # Body well-formedness (priority 5): tapped_at.
    tapped_at = util.req_datetime(body, "tapped_at")

    # State (priority 6/7-ish): a SUSPENDED rider cannot tap (PRD §3.6).
    if rider["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Rider is not ACTIVE.")

    # Week open (priority 7): the cited week must be OPEN.
    if fare_week["status"] != "OPEN":
        raise err(errors.ERR_WEEK_CLOSED, "Fare week is CLOSED.")

    # Business referential (priority 8): tapped_at fare day within the week's
    # 7-day window AND the week's zone matches the rider's product zone.
    fday = util.fare_day(tapped_at)
    week_start = util.parse_iso_date(fare_week["week_start_date"])
    week_end = util.add_days(week_start, 6)
    if not (week_start <= fday <= week_end):
        raise err(errors.ERR_TAP_WEEK_MISMATCH, "Tap fare day falls outside the fare week window.")
    if fare_week["zone_code"] != rider["home_zone_code"]:
        raise err(errors.ERR_TAP_WEEK_MISMATCH, "Fare week zone does not match the rider's product zone.")

    rec = new_common()
    rec.update({
        "rider_id": rider_id,
        "fare_week_id": fare_week_id,
        "funding_source_id": funding_source_id,
        "benefit_allocation_id": None,
        "tapped_at": body["tapped_at"],
        "list_fare_cents": 0,
        "transfer_discount_cents": 0,
        "cap_credit_cents": 0,
        "charge_cents": 0,
        "benefit_applied_cents": 0,
        "status": "PENDING",
    })
    db.taps[rec["id"]] = rec
    return success(serialize.tap_out(rec), status=201)


@app.route("/taps/quote", methods=["GET"])
def quote_tap():
    user_id, role = authenticate()
    require_role(role, {"Rider"})
    # Quote params arrive as query string.
    rider_id = request.args.get("rider_id")
    require_owner(role, user_id, rider_id)

    if not rider_id:
        raise err(errors.ERR_INVALID_REQUEST, "rider_id is required.")
    rider = db.riders.get(rider_id)
    if rider is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced rider does not exist.")

    fare_week_id = request.args.get("fare_week_id")
    if not fare_week_id:
        raise err(errors.ERR_INVALID_REQUEST, "fare_week_id is required.")
    fare_week = db.fare_weeks.get(fare_week_id)
    if fare_week is None:
        raise err(errors.ERR_NOT_FOUND, "Referenced fare week does not exist.")

    tapped_at = util.parse_iso_datetime(request.args.get("tapped_at"))
    if tapped_at is None:
        raise err(errors.ERR_INVALID_REQUEST, "tapped_at must be an ISO 8601 datetime.")

    product = services._active_product_for_zone(fare_week["zone_code"])
    if product is None:
        raise err(errors.ERR_NOT_FOUND, "No ACTIVE fare product for the fare week zone.")

    q = services.compute_quote(rider, product, fare_week, tapped_at)
    return success({
        "rider_id": rider["id"],
        "fare_week_id": fare_week["id"],
        "estimated_charge_cents": q["estimated_charge_cents"],
        "list_fare_cents": q["list_fare_cents"],
        "transfer_discount_cents": q["transfer_discount_cents"],
        "cap_credit_cents": q["cap_credit_cents"],
    }, status=200)


@app.route("/taps", methods=["GET"])
def list_taps():
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rider_filter = request.args.get("rider_id")
    if role == "Rider":
        rider_filter = user_id
    return do_list(db.taps, serialize.tap_out, {
        "rider_id": rider_filter,
        "fare_week_id": request.args.get("fare_week_id"),
        "funding_source_id": request.args.get("funding_source_id"),
        "benefit_allocation_id": request.args.get("benefit_allocation_id"),
        "status": request.args.get("status"),
    })


@app.route("/taps/<rid>", methods=["GET"])
def get_tap(rid):
    user_id, role = authenticate()
    require_role(role, {"FareAdmin", "Rider"})
    rec = fetch_or_404(db.taps, rid)
    require_owner(role, user_id, rec["rider_id"])
    return success(serialize.tap_out(rec), status=200)


@app.route("/taps/<rid>/settle", methods=["POST"])
def settle_tap(rid):
    _, role = authenticate()
    require_role(role, {"PaymentGateway"})
    rec = fetch_or_404(db.taps, rid)

    # State (priority 6): settle defined only out of PENDING.
    if rec["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Tap is not PENDING.")

    rider = db.riders.get(rec["rider_id"])
    funding_source = db.funding_sources.get(rec["funding_source_id"])
    fare_week = db.fare_weeks.get(rec["fare_week_id"])

    # Week open (priority 7): settle against a CLOSED week is ERR_WEEK_CLOSED.
    # (Checked before the funds branch per §1.2.1 / Rule-5 priority pairing.)
    if fare_week is None or fare_week["status"] != "OPEN":
        raise err(errors.ERR_WEEK_CLOSED, "Fare week is CLOSED.")

    # Settle preconditions: rider ACTIVE, funding source ACTIVE (PRD §3.7).
    if rider is None or rider["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Owning rider is not ACTIVE.")
    if funding_source is None or funding_source["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Funding source is not ACTIVE.")

    product = services._active_product_for_zone(fare_week["zone_code"])
    if product is None:
        raise err(errors.ERR_NOT_FOUND, "No ACTIVE fare product for the fare week zone.")

    tapped_at = util.parse_iso_datetime(rec["tapped_at"])
    computed = services.compute_tap_charge(rider, product, fare_week, tapped_at, tap_id=rec["id"])

    # Funds branch (priority 14): capture when balance >= charge, else REJECTED.
    if funding_source["prepaid_balance_cents"] >= computed["charge_cents"]:
        services.apply_capture(rec, funding_source, fare_week, computed)
        return success(serialize.tap_out(rec), status=200)
    else:
        services.apply_reject(rec, computed)
        # The tap is persisted as REJECTED, but the HTTP response is 402.
        raise err(errors.ERR_INSUFFICIENT_FUNDS, "Insufficient funds to settle the tap.")


@app.route("/taps/<rid>/reverse", methods=["POST"])
def reverse_tap(rid):
    _, role = authenticate()
    require_role(role, {"FareAdmin"})
    rec = fetch_or_404(db.taps, rid)

    # State (priority 6): reverse defined only out of CAPTURED.
    if rec["status"] != "CAPTURED":
        raise err(errors.ERR_INVALID_STATE, "Tap is not CAPTURED.")

    fare_week = db.fare_weeks.get(rec["fare_week_id"])
    # Week open (priority 7): reversal against a CLOSED week is ERR_WEEK_CLOSED.
    if fare_week is None or fare_week["status"] != "OPEN":
        raise err(errors.ERR_WEEK_CLOSED, "Fare week is CLOSED.")

    funding_source = db.funding_sources.get(rec["funding_source_id"])
    services.apply_reverse(rec, funding_source, fare_week)
    return success(serialize.tap_out(rec), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
