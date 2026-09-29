"""Air-plus-hotel packages and opaque bundle pricing (PRD 3.7)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("packages", __name__)

STATUSES = ("DRAFT", "PRICED", "PUBLISHED", "WITHDRAWN")
COMPONENT_TYPES = ("AIR", "HOTEL")


def _pairs(package):
    out = []
    for component in cascade.components_of_package(package["id"]):
        offer = db["offers"].get(component["offer_id"])
        if offer is not None:
            out.append((component, offer))
    return out


def _guard_mix(pairs):
    types = [component["component_type"] for component, _offer in pairs]
    if len(pairs) < calc.MIN_COMPONENTS or "AIR" not in types or "HOTEL" not in types:
        raise ApiError("ERR_PACKAGE_COMPONENT_MIX_INVALID")


def _guard_live(package, pairs):
    for _component, offer in pairs:
        if offer["status"] != "LIVE" or offer["travel_date"] != package["travel_date"]:
            raise ApiError("ERR_COMPONENT_NOT_LIVE")


@bp.post("/packages")
def create_package():
    actor = auth.authenticate(("CommercialManager", "BookingAgent"))
    data = validate.body()
    raw_market = data.get("market_id")
    if isinstance(raw_market, str) and raw_market:
        common.find("markets", raw_market)
    market_id = validate.str_req(data, "market_id")
    travel_date = validate.date_req(data, "travel_date")
    name = validate.str_req(data, "name")
    opaque = data.get("opaque")
    if not isinstance(opaque, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'opaque' is required and must be a boolean.")
    today = clock.today()
    if travel_date < today.isoformat() \
            or travel_date > clock.plus_days(today, calc.MAX_HORIZON_DAYS).isoformat():
        raise ApiError("ERR_TRAVEL_DATE_OUT_OF_RANGE")
    package = store.new_row("packages", {
        "market_id": market_id,
        "travel_date": travel_date,
        "name": name,
        "opaque": opaque,
        "components_subtotal_cents": None,
        "discount_pct": None,
        "discount_cents": None,
        "package_total_cents": None,
        "component_count": 0,
        "status": "DRAFT",
        "reveal_supplier_names": False,
        "priced_at": None,
        "created_by_user_id": actor.user_id,
        "withdrawal_reason": None,
    })
    return response.obj(package, 201)


@bp.get("/packages/<package_id>")
def read_package(package_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("packages", package_id), 200)


@bp.get("/packages")
def list_packages():
    auth.authenticate(auth.ALL_ROLES)
    market_id = validate.filter_str("market_id")
    travel_date = validate.filter_date("travel_date")
    status = validate.filter_enum("status", STATUSES)
    opaque = validate.filter_bool("opaque")
    rows = []
    for row in db["packages"].values():
        if market_id is not None and row["market_id"] != market_id:
            continue
        if travel_date is not None and row["travel_date"] != travel_date:
            continue
        if status is not None and row["status"] != status:
            continue
        if opaque is not None and row["opaque"] != opaque:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/packages/<package_id>/components")
def add_component(package_id):
    auth.authenticate(("CommercialManager", "BookingAgent"))
    package = common.find("packages", package_id)
    data = validate.body()
    raw_offer = data.get("offer_id")
    if isinstance(raw_offer, str) and raw_offer:
        common.find("offers", raw_offer)
    offer_id = validate.str_req(data, "offer_id")
    component_type = validate.enum_req(data, "component_type", COMPONENT_TYPES)
    if package["status"] not in ("DRAFT", "PRICED"):
        raise ApiError("ERR_PACKAGE_NOT_DRAFT_OR_PRICED")
    offer = db["offers"][offer_id]
    if offer["status"] != "LIVE":
        raise ApiError("ERR_COMPONENT_NOT_LIVE")
    plan = common.offer_plan(offer)
    if offer["travel_date"] != package["travel_date"] \
            or plan is None or plan["market_id"] != package["market_id"]:
        raise ApiError("ERR_COMPONENT_DATE_MISMATCH")
    component = store.new_row("components", {
        "package_id": package["id"],
        "offer_id": offer["id"],
        "component_type": component_type,
        "display_total_snapshot_cents": offer["display_total_cents"],
        "discount_alloc_cents": None,
        "allocated_cents": None,
    }, versioned=False)
    package["component_count"] = int(package["component_count"]) + 1
    if package["status"] == "PRICED":
        package["status"] = "DRAFT"
        cascade.clear_package_pricing(package)
        component["display_total_snapshot_cents"] = None
    touch(package)
    return response.obj(component, 201)


@bp.post("/packages/<package_id>/price")
def price_package(package_id):
    auth.authenticate(("CommercialManager", "BookingAgent"))
    package = common.find("packages", package_id)
    data = validate.body()
    expected = validate.int_req(data, "expected_package_version")
    if expected != package["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if package["status"] not in ("DRAFT", "PRICED"):
        raise ApiError("ERR_PACKAGE_NOT_PRICED")
    pairs = _pairs(package)
    _guard_mix(pairs)
    _guard_live(package, pairs)
    fields, allocations = calc.price_package(pairs)
    package.update(fields)
    package["status"] = "PRICED"
    package["priced_at"] = clock.now_iso()
    for component, values in allocations:
        component.update(values)
    touch(package)
    return response.obj(package, 200)


@bp.post("/packages/<package_id>/publish")
def publish_package(package_id):
    auth.authenticate(("CommercialManager",))
    package = common.find("packages", package_id)
    data = validate.body()
    reveal = validate.bool_opt(data, "reveal_supplier_names", False)
    validate.str_opt(data, "note")
    if package["status"] != "PRICED":
        raise ApiError("ERR_PACKAGE_NOT_PRICED")
    if package["opaque"] and reveal:
        raise ApiError("ERR_OPAQUE_DISCLOSURE_FORBIDDEN")
    pairs = _pairs(package)
    _guard_mix(pairs)
    _guard_live(package, pairs)
    package["status"] = "PUBLISHED"
    package["reveal_supplier_names"] = reveal
    touch(package)
    return response.obj(package, 200)


@bp.post("/packages/<package_id>/withdraw")
def withdraw_package(package_id):
    auth.authenticate(("CommercialManager", "ComplianceOfficer"))
    package = common.find("packages", package_id)
    data = validate.body()
    reason = validate.str_req(data, "withdrawal_reason")
    if package["status"] != "PUBLISHED":
        raise ApiError("ERR_PACKAGE_NOT_PUBLISHED")
    package["status"] = "WITHDRAWN"
    package["withdrawal_reason"] = reason
    package["reveal_supplier_names"] = False
    touch(package)
    return response.obj(package, 200)


@bp.get("/package-components/<component_id>")
def read_component(component_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("components", component_id), 200)


@bp.get("/package-components")
def list_components():
    auth.authenticate(auth.ALL_ROLES)
    package_id = validate.filter_str("package_id")
    offer_id = validate.filter_str("offer_id")
    component_type = validate.filter_enum("component_type", COMPONENT_TYPES)
    rows = []
    for row in db["components"].values():
        if package_id is not None and row["package_id"] != package_id:
            continue
        if offer_id is not None and row["offer_id"] != offer_id:
            continue
        if component_type is not None and row["component_type"] != component_type:
            continue
        rows.append(row)
    return common.paged(rows)
