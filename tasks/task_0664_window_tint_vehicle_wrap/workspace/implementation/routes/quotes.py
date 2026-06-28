"""Quotes, quote lines, pricing, accept, void."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from models import stamp_create, serialize, touch
from response import success, success_list
from services import common
from services import quote as quote_svc

bp = Blueprint("quotes", __name__)

COVERAGES = {"FULL", "PARTIAL", "ACCENT"}
WINDOW_POSITIONS = {"FRONT_SIDE", "REAR_SIDE", "REAR_WINDOW", "WINDSHIELD", "BODY_PANEL"}


def _customer_owns_quote(role, user_id, quote):
    if role == "Customer":
        vehicle = db.vehicle_profiles.get(quote["vehicle_profile_id"])
        common.check_customer_owns_vehicle(role, user_id, vehicle)


def _check_quote_version(quote, body):
    expected = common.require_field(body, "expected_quote_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "expected_quote_version must be an integer.")
    if expected != quote["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "expected_quote_version does not match the quote.")


# ---- create / read / list ---------------------------------------------------
@bp.route("/quotes", methods=["POST"])
def create_quote():
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    body = get_json_body()
    vehicle_profile_id = common.require_string(body, "vehicle_profile_id")
    shop_location_id = common.require_string(body, "shop_location_id")
    fleet_account_id = body.get("fleet_account_id")
    rushed = common.optional_bool(body, "rushed", False)

    # Existence: path then body FKs left to right.
    vehicle = common.get_or_404(db.vehicle_profiles, vehicle_profile_id)
    common.get_or_404(db.shop_locations, shop_location_id)
    if fleet_account_id is not None:
        common.get_or_404(db.fleet_accounts, fleet_account_id)

    common.check_customer_owns_vehicle(role, user_id, vehicle)

    rec = {
        "vehicle_profile_id": vehicle_profile_id,
        "shop_location_id": shop_location_id,
        "fleet_account_id": fleet_account_id,
        "rushed": rushed,
        "status": "DRAFT",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "net_cents": 0,
        "rush_fee_cents": 0,
        "total_due_cents": 0,
        "deposit_required_cents": 0,
    }
    stamp_create(rec)
    db.quotes[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager", "FleetManager"})
    limit, offset = parse_pagination()
    items = list(db.quotes.values())

    vp = request.args.get("vehicle_profile_id")
    sp = request.args.get("shop_location_id")
    fa = request.args.get("fleet_account_id")
    if vp is not None:
        items = [q for q in items if q["vehicle_profile_id"] == vp]
    if sp is not None:
        items = [q for q in items if q["shop_location_id"] == sp]
    if fa is not None:
        items = [q for q in items if q.get("fleet_account_id") == fa]

    if role == "Customer":
        owned = {v["id"] for v in db.vehicle_profiles.values() if v["customer_user_id"] == user_id}
        items = [q for q in items if q["vehicle_profile_id"] in owned]
    elif role == "FleetManager":
        owned = {f["id"] for f in db.fleet_accounts.values() if f["fleet_manager_user_id"] == user_id}
        items = [q for q in items if q.get("fleet_account_id") in owned]

    items.sort(key=lambda q: (q["created_at"], q["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(q) for q in page], limit, offset, total, 200)


@bp.route("/quotes/<rid>", methods=["GET"])
def get_quote(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager", "FleetManager"})
    quote = common.get_or_404(db.quotes, rid)
    if role == "Customer":
        _customer_owns_quote(role, user_id, quote)
    elif role == "FleetManager":
        fleet = db.fleet_accounts.get(quote.get("fleet_account_id"))
        if fleet is None:
            raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "FleetManager does not own this quote.")
        common.check_fleet_manager_owns(role, user_id, fleet)
    # Observe TTL expiry on read.
    quote_svc.observe_ttl_expiry(quote)
    return success(serialize(quote), 200)


# ---- lines ------------------------------------------------------------------
@bp.route("/quotes/<rid>/lines", methods=["POST"])
def add_line(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    quote = common.get_or_404(db.quotes, rid)
    _customer_owns_quote(role, user_id, quote)
    body = get_json_body()

    service_package_id = common.require_string(body, "service_package_id")
    film_material_id = common.require_string(body, "film_material_id")
    coverage = common.require_enum(body, "coverage", COVERAGES)
    window_position = common.require_enum(body, "window_position", WINDOW_POSITIONS)

    requested_vlt_pct = body.get("requested_vlt_pct", 100)
    if requested_vlt_pct is None:
        requested_vlt_pct = 100
    if isinstance(requested_vlt_pct, bool) or not isinstance(requested_vlt_pct, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "requested_vlt_pct must be an integer.")

    strip_depth_inches = body.get("strip_depth_inches", 0)
    if strip_depth_inches is None:
        strip_depth_inches = 0
    if isinstance(strip_depth_inches, bool) or not isinstance(strip_depth_inches, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "strip_depth_inches must be a number.")
    if strip_depth_inches < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "strip_depth_inches must be >= 0.")

    # Existence of body FKs (left to right).
    pkg = common.get_or_404(db.service_packages, service_package_id)
    mat = common.get_or_404(db.film_materials, film_material_id)

    # OCC version check (state priority 21).
    _check_quote_version(quote, body)

    # VLT range check.
    if requested_vlt_pct < 0 or requested_vlt_pct > 100:
        raise ApiError(errors.ERR_VLT_OUT_OF_RANGE, 422, "requested_vlt_pct must be between 0 and 100.")

    # Material compatibility at add time.
    if not quote_svc.material_compatible(pkg["service_type"], mat["category"]):
        raise ApiError(errors.ERR_MATERIAL_INCOMPATIBLE, 422,
                       "Material category incompatible with package service_type.")

    line = {
        "quote_id": rid,
        "service_package_id": service_package_id,
        "film_material_id": film_material_id,
        "coverage": coverage,
        "window_position": window_position,
        "requested_vlt_pct": requested_vlt_pct,
        "strip_depth_inches": strip_depth_inches,
        "status": "INCLUDED",
        "line_total_cents": 0,
    }
    stamp_create(line)
    db.quote_lines[line["id"]] = line

    # Adding a line reverts a PRICED quote to DRAFT, zeroes money, bumps version.
    if quote["status"] == "PRICED":
        quote["status"] = "DRAFT"
        quote_svc.zero_money_fields(quote)
    touch(quote)

    return success(serialize(line), 201)


@bp.route("/quotes/<rid>/lines", methods=["GET"])
def list_lines(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager", "FleetManager"})
    quote = common.get_or_404(db.quotes, rid)
    if role == "Customer":
        _customer_owns_quote(role, user_id, quote)
    elif role == "FleetManager":
        fleet = db.fleet_accounts.get(quote.get("fleet_account_id"))
        if fleet is None:
            raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "FleetManager does not own this quote.")
        common.check_fleet_manager_owns(role, user_id, fleet)
    limit, offset = parse_pagination()
    items = [l for l in db.quote_lines.values() if l["quote_id"] == rid]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(l) for l in page], limit, offset, total, 200)


@bp.route("/quote-lines/<rid>", methods=["GET"])
def get_line(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    line = common.get_or_404(db.quote_lines, rid)
    if role == "Customer":
        quote = db.quotes.get(line["quote_id"])
        _customer_owns_quote(role, user_id, quote)
    return success(serialize(line), 200)


@bp.route("/quote-lines", methods=["GET"])
def list_quote_lines():
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    limit, offset = parse_pagination()
    items = list(db.quote_lines.values())
    qid = request.args.get("quote_id")
    spid = request.args.get("service_package_id")
    fmid = request.args.get("film_material_id")
    if qid is not None:
        items = [l for l in items if l["quote_id"] == qid]
    if spid is not None:
        items = [l for l in items if l["service_package_id"] == spid]
    if fmid is not None:
        items = [l for l in items if l["film_material_id"] == fmid]
    if role == "Customer":
        owned_quotes = {q["id"] for q in db.quotes.values()
                        if db.vehicle_profiles.get(q["vehicle_profile_id"], {}).get("customer_user_id") == user_id}
        items = [l for l in items if l["quote_id"] in owned_quotes]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(l) for l in page], limit, offset, total, 200)


@bp.route("/quote-lines/<rid>", methods=["DELETE"])
def remove_line(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    line = common.get_or_404(db.quote_lines, rid)
    quote = db.quotes.get(line["quote_id"])
    if role == "Customer":
        _customer_owns_quote(role, user_id, quote)

    line["status"] = "REMOVED"
    touch(line)

    # Removing a line reverts a PRICED quote to DRAFT, zeroes money, bumps version.
    if quote["status"] == "PRICED":
        quote["status"] = "DRAFT"
        quote_svc.zero_money_fields(quote)
    touch(quote)

    return success(serialize(line), 200)


# ---- price / accept / void --------------------------------------------------
@bp.route("/quotes/<rid>/price", methods=["POST"])
def price(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    quote = common.get_or_404(db.quotes, rid)
    _customer_owns_quote(role, user_id, quote)
    body = get_json_body()

    # Observe TTL before state check (price is one of the lazy-expiry triggers).
    quote_svc.observe_ttl_expiry(quote)

    # State: must be DRAFT to price.
    if quote["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Quote is not DRAFT.")

    # OCC version check.
    _check_quote_version(quote, body)

    # At least one INCLUDED line.
    lines = quote_svc.included_lines(rid)
    if not lines:
        raise ApiError(errors.ERR_NO_INCLUDED_LINES, 422, "Quote has no INCLUDED lines.")

    # Compliance + compatibility gates (raise before money computed).
    quote_svc.run_compliance_gates(quote)

    # Recompute line totals + quote totals.
    quote_svc.price_quote(quote)
    quote["status"] = "PRICED"
    touch(quote)
    return success(serialize(quote), 200)


@bp.route("/quotes/<rid>/accept", methods=["POST"])
def accept(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    quote = common.get_or_404(db.quotes, rid)
    _customer_owns_quote(role, user_id, quote)
    body = get_json_body()

    # Observe TTL on read of a priced quote.
    quote_svc.observe_ttl_expiry(quote)

    # State must be PRICED. (EXPIRED is reported by the expiry guard below.)
    if quote["status"] == "EXPIRED":
        raise ApiError(errors.ERR_QUOTE_EXPIRED, 409, "Quote is expired.")
    if quote["status"] != "PRICED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Quote is not PRICED.")

    _check_quote_version(quote, body)

    quote["status"] = "ACCEPTED"
    touch(quote)
    return success(serialize(quote), 200)


@bp.route("/quotes/<rid>/void", methods=["POST"])
def void(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    quote = common.get_or_404(db.quotes, rid)
    _customer_owns_quote(role, user_id, quote)

    if quote["status"] not in ("DRAFT", "PRICED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Quote is not DRAFT or PRICED.")

    quote["status"] = "VOIDED"
    touch(quote)
    return success(serialize(quote), 200)
