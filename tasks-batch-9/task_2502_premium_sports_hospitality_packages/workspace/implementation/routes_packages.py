"""Package construction, pricing and publication (PRD 3.4)."""
from flask import Blueprint, g

import calc
from auth import (
    CLIENT_PORTAL_USER,
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_MANAGER,
    FINANCE_CONTROLLER,
    guard,
)
from common import get_component, get_event, get_package, listing
from errors import (
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_EVENT_STATE,
    ERR_INVALID_PACKAGE_STATE,
    ERR_MARGIN_BELOW_FLOOR,
    ERR_PACKAGE_HAS_NO_COMPONENTS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_PACKAGE_VERSION,
    fail,
)
from response import object_response
from store import (
    create_record,
    db,
    logical_now,
    package_component_json,
    package_product_json,
    touch,
    update_record,
)
from validation import (
    bad,
    body,
    opt_bool,
    opt_int,
    opt_number,
    req_enum,
    req_id,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("packages", __name__)

TIERS = ("BRONZE", "SILVER", "GOLD", "PLATINUM")
COMPONENT_TYPES = ("TICKET", "HOTEL", "TRANSPORT", "EXPERIENCE", "CATERING")


# --- PackageProduct ---------------------------------------------------------


@bp.route("/package-products", methods=["POST"])
@guard(COMMERCIAL_MANAGER, COMMERCIAL_DIRECTOR)
def create_package():
    data = body()
    event_id = req_id(data, "event_id")
    name = req_string(data, "name")
    tier = req_enum(data, "tier", TIERS)
    tickets_per_package = req_int(data, "tickets_per_package", minimum=1)
    hotel_nights = opt_int(data, "hotel_nights", default=0, minimum=0)
    transport_included = opt_bool(data, "transport_included", default=False)
    min_margin_pct = opt_number(data, "min_margin_pct", default="0.25")

    event = get_event(event_id)
    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "Packages cannot be built against this fixture.")

    package = create_record(
        db.package_products,
        {
            "event_id": event_id,
            "name": name,
            "tier": tier,
            "tickets_per_package": tickets_per_package,
            "hotel_nights": hotel_nights,
            "transport_included": transport_included,
            "min_margin_pct": min_margin_pct,
            "package_status": "DRAFT",
            "base_cost_cents": 0,
            "component_price_subtotal_cents": 0,
            "list_price_cents": 0,
            "margin_pct": calc.dec(0),
            "priced_by_user_id": None,
            "priced_at": None,
            "published_by_user_id": None,
            "published_at": None,
        },
    )
    return object_response(package_product_json(package), 201)


@bp.route("/package-products/<package_id>", methods=["GET"])
@guard(
    COMMERCIAL_MANAGER,
    COMMERCIAL_DIRECTOR,
    CLIENT_SERVICE_AGENT,
    FINANCE_CONTROLLER,
    CLIENT_PORTAL_USER,
)
def read_package(package_id):
    return object_response(package_product_json(get_package(package_id)))


@bp.route("/package-products", methods=["GET"])
@guard(
    COMMERCIAL_MANAGER,
    COMMERCIAL_DIRECTOR,
    CLIENT_SERVICE_AGENT,
    FINANCE_CONTROLLER,
    CLIENT_PORTAL_USER,
)
def list_packages():
    return listing(
        calc.all_of(db.package_products),
        package_product_json,
        ("event_id", "package_status", "tier"),
    )


@bp.route("/package-products/<package_id>/price", methods=["POST"])
@guard(COMMERCIAL_MANAGER, COMMERCIAL_DIRECTOR)
def price_package(package_id):
    package = get_package(package_id)
    body()
    if package["package_status"] not in ("DRAFT", "PRICED"):
        fail(ERR_INVALID_PACKAGE_STATE, "Only a draft or priced package can be priced.")
    components = calc.components_of_package(package_id)
    if not components:
        fail(ERR_PACKAGE_HAS_NO_COMPONENTS, "A package with no component lines cannot be priced.")

    ordered = sorted(components, key=lambda c: c["sequence_no"])
    for component in ordered:
        update_record(component, calc.component_line_values(component))

    package.update(calc.package_price_values(package, ordered))
    package["package_status"] = "PRICED"
    package["priced_by_user_id"] = g.user_id
    package["priced_at"] = logical_now()
    package["published_by_user_id"] = None
    package["published_at"] = None
    touch(package)
    return object_response(package_product_json(package))


@bp.route("/package-products/<package_id>/publish", methods=["POST"])
@guard(COMMERCIAL_DIRECTOR)
def publish_package(package_id):
    package = get_package(package_id)
    data = body()
    expected_version = req_int(data, "expected_package_product_version")

    if expected_version != package["version"]:
        fail(ERR_STALE_PACKAGE_VERSION, "The package has moved on since its margin was reviewed.")
    if package["package_status"] != "PRICED":
        fail(ERR_INVALID_PACKAGE_STATE, "Only a priced package can be published.")
    if g.user_id == package["priced_by_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES, "The operator who priced a package may not publish it.")
    if calc.dec(package["margin_pct"]) < calc.dec(package["min_margin_pct"]):
        fail(ERR_MARGIN_BELOW_FLOOR, "The computed margin is below the package's floor.")

    supported = False
    for deal in calc.deals_of_event(package["event_id"]):
        if deal["inventory_type"] != "TICKET":
            continue
        if deal["deal_status"] in ("COMMITTED", "PARTIALLY_RELEASED", "FULLY_RELEASED"):
            supported = True
            break
    if not supported:
        fail(ERR_INVALID_DEAL_STATE, "No committed ticket rights deal stands behind this package.")

    package["package_status"] = "PUBLISHED"
    package["published_by_user_id"] = g.user_id
    package["published_at"] = logical_now()
    touch(package)
    return object_response(package_product_json(package))


# --- PackageComponent -------------------------------------------------------


@bp.route("/package-components", methods=["POST"])
@guard(COMMERCIAL_MANAGER)
def create_component():
    data = body()
    package_id = req_id(data, "package_product_id")
    component_type = req_enum(data, "component_type", COMPONENT_TYPES)
    descriptor = req_string(data, "descriptor")
    quantity = req_int(data, "quantity", minimum=1)
    unit_cost_cents = req_int(data, "unit_cost_cents", minimum=0)
    markup_pct = req_number(data, "markup_pct", minimum=0, maximum=5)
    sequence_no = req_int(data, "sequence_no", minimum=1)

    package = get_package(package_id)
    for existing in calc.components_of_package(package_id):
        if existing["sequence_no"] == sequence_no:
            bad("Field `sequence_no` must be unique within the package.")
    if package["package_status"] not in ("DRAFT", "PRICED"):
        fail(ERR_INVALID_PACKAGE_STATE, "Lines may only be added to a draft or priced package.")

    component = create_record(
        db.package_components,
        {
            "package_product_id": package_id,
            "component_type": component_type,
            "descriptor": descriptor,
            "quantity": quantity,
            "unit_cost_cents": unit_cost_cents,
            "markup_pct": markup_pct,
            "sequence_no": sequence_no,
            "line_cost_cents": 0,
            "line_price_cents": 0,
        },
    )
    component.update(calc.component_line_values(component))
    return object_response(package_component_json(component), 201)


@bp.route("/package-components/<component_id>", methods=["GET"])
@guard(COMMERCIAL_MANAGER, COMMERCIAL_DIRECTOR, CLIENT_SERVICE_AGENT)
def read_component(component_id):
    return object_response(package_component_json(get_component(component_id)))


@bp.route("/package-components", methods=["GET"])
@guard(COMMERCIAL_MANAGER, COMMERCIAL_DIRECTOR, CLIENT_SERVICE_AGENT)
def list_components():
    return listing(
        calc.all_of(db.package_components),
        package_component_json,
        ("package_product_id", "component_type"),
    )
