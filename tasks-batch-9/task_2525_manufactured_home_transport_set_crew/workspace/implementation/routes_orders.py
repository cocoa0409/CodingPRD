"""Installation orders, home sections and destination sites (PRD 3.2, 3.3)."""
from flask import Blueprint

import calc
import domain
from envelope import object_response
from errors import fail
from guards import (
    ANY_ROLE,
    actor_id,
    actor_role,
    apply_filters,
    filters,
    lookup,
    lookup_ref,
    roles,
    validate,
)
from routes_partners import list_response
from store import base_row, db, mark

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# InstallationOrder
# ---------------------------------------------------------------------------
@bp.post("/installations/orders")
@roles("NetworkAdmin", "PlantDispatcher")
def create_order():
    body = validate(
        [
            {"name": "plant_id", "type": "string", "required": True},
            {"name": "dealer_name", "type": "string", "required": True},
            {"name": "home_model", "type": "string", "required": True},
            {
                "name": "section_count",
                "type": "integer",
                "required": True,
                "min": 1,
                "max": 4,
            },
            {"name": "destination_state", "type": "state_code", "required": True},
            {
                "name": "wind_zone",
                "type": "enum",
                "required": True,
                "values": ["I", "II", "III"],
            },
        ]
    )
    lookup_ref("plants", body["plant_id"], "ERR_PLANT_NOT_FOUND")
    row = base_row()
    row.update(
        {
            "plant_id": body["plant_id"],
            "dealer_name": body["dealer_name"],
            "home_model": body["home_model"],
            "section_count": body["section_count"],
            "destination_state": body["destination_state"],
            "wind_zone": body["wind_zone"],
            "posture": "OPEN",
            "warranty_start_date": None,
            "invoice_total_cents": None,
        }
    )
    db.orders[row["id"]] = row
    row["posture"] = domain.derive_posture(row)
    return object_response(domain.pub_order(row), 201)


@bp.get("/installations/orders/<row_id>")
@roles(*ANY_ROLE)
def read_order(row_id):
    row = lookup("orders", row_id, "ERR_ORDER_NOT_FOUND")
    return object_response(domain.pub_order(row))


@bp.get("/installations/orders")
@roles(*ANY_ROLE)
def list_orders():
    active = filters(
        {
            "plant_id": None,
            "posture": [
                "OPEN",
                "TRANSPORT_BLOCKED",
                "SET_IN_PROGRESS",
                "SITE_BLOCKED",
                "CLOSED",
            ],
            "destination_state": None,
        }
    )
    rows = apply_filters(list(db.orders.values()), active)
    return list_response(rows, domain.pub_order)


@bp.get("/installations/orders/<row_id>/summary")
@roles(*ANY_ROLE)
def read_order_summary(row_id):
    row = lookup("orders", row_id, "ERR_ORDER_NOT_FOUND")
    return object_response(domain.order_summary(row))


# ---------------------------------------------------------------------------
# HomeSection
# ---------------------------------------------------------------------------
def _check_mate(section_id, order_id, mate_id):
    """PRD 3.2 / ladder priority 16: self-referential integrity of the pairing."""
    if mate_id is None:
        return
    if section_id is not None and mate_id == section_id:
        fail("ERR_SECTION_MATE_INVALID", "A floor may not mate against itself.")
    mate = db.sections.get(mate_id)
    if mate["order_id"] != order_id:
        fail(
            "ERR_SECTION_MATE_INVALID",
            "The named mate belongs to a different installation order.",
        )
    existing = mate.get("mates_to_section_id")
    if existing is not None and existing != section_id:
        fail(
            "ERR_SECTION_MATE_INVALID",
            "The named mate is already mated to a third floor.",
        )
    for other in db.sections.values():
        if other["id"] in (mate_id, section_id):
            continue
        if other.get("mates_to_section_id") == mate_id:
            fail(
                "ERR_SECTION_MATE_INVALID",
                "The named mate is already mated to a third floor.",
            )


@bp.post("/installations/sections")
@roles("PlantDispatcher")
def create_section():
    body = validate(
        [
            {"name": "order_id", "type": "string", "required": True},
            {"name": "mates_to_section_id", "type": "string", "required": False},
            {
                "name": "section_index",
                "type": "integer",
                "required": True,
                "min": 1,
                "max": 4,
            },
            {
                "name": "declared_width_in",
                "type": "number",
                "required": True,
                "min": 120,
                "max": 240,
            },
            {
                "name": "declared_height_in",
                "type": "number",
                "required": True,
                "min": 120,
                "max": 200,
            },
            {"name": "declared_length_in", "type": "number", "required": True},
            {"name": "declared_weight_lb", "type": "integer", "required": True},
        ]
    )
    order = lookup_ref("orders", body["order_id"], "ERR_ORDER_NOT_FOUND")
    mate_id = body.get("mates_to_section_id")
    if mate_id is not None:
        lookup_ref("sections", mate_id, "ERR_SECTION_NOT_FOUND")
    _check_mate(None, order["id"], mate_id)
    for existing in db.sections.values():
        if (
            existing["order_id"] == order["id"]
            and existing["section_index"] == body["section_index"]
        ):
            fail("ERR_DUPLICATE_SECTION_INDEX")

    row = base_row()
    row.update(
        {
            "order_id": order["id"],
            "mates_to_section_id": mate_id,
            "section_index": body["section_index"],
            "declared_width_in": body["declared_width_in"],
            "declared_height_in": body["declared_height_in"],
            "declared_length_in": body["declared_length_in"],
            "declared_weight_lb": body["declared_weight_lb"],
            "measured_width_in": None,
            "measured_height_in": None,
            "transit_status": "AT_PLANT",
        }
    )
    db.sections[row["id"]] = row
    mark(order)
    domain.recompute_posture(order)
    return object_response(domain.pub_section(row), 201)


@bp.patch("/installations/sections/<row_id>")
@roles("PlantDispatcher")
def amend_section(row_id):
    body = validate(
        [
            {
                "name": "declared_width_in",
                "type": "number",
                "required": False,
                "min": 120,
                "max": 240,
            },
            {
                "name": "declared_height_in",
                "type": "number",
                "required": False,
                "min": 120,
                "max": 200,
            },
            {"name": "declared_length_in", "type": "number", "required": False},
            {
                "name": "mates_to_section_id",
                "type": "string",
                "required": False,
                "nullable": True,
            },
        ],
        required_body=False,
    )
    section = lookup("sections", row_id, "ERR_SECTION_NOT_FOUND")
    mate_present = "mates_to_section_id" in body
    mate_id = body.get("mates_to_section_id")
    if mate_present and mate_id is not None:
        lookup_ref("sections", mate_id, "ERR_SECTION_NOT_FOUND")
    if section["transit_status"] != "AT_PLANT":
        fail("ERR_INVALID_STATE")
    if mate_present:
        _check_mate(section["id"], section["order_id"], mate_id)

    for field in ("declared_width_in", "declared_height_in", "declared_length_in"):
        if field in body:
            section[field] = body[field]
    if mate_present:
        section["mates_to_section_id"] = mate_id
    mark(section)
    return object_response(domain.pub_section(section))


@bp.get("/installations/sections/<row_id>")
@roles(*ANY_ROLE)
def read_section(row_id):
    row = lookup("sections", row_id, "ERR_SECTION_NOT_FOUND")
    return object_response(domain.pub_section(row))


@bp.get("/installations/sections")
@roles(*ANY_ROLE)
def list_sections():
    active = filters(
        {
            "order_id": None,
            "mates_to_section_id": None,
            "transit_status": [
                "AT_PLANT",
                "MEASURED",
                "PERMIT_PENDING",
                "DISPATCH_READY",
                "IN_TRANSIT",
                "DELIVERED",
                "PERMIT_REVOKED_HOLD",
                "DAMAGED_HOLD",
            ],
        }
    )
    rows = apply_filters(list(db.sections.values()), active)
    return list_response(rows, domain.pub_section)


def _require_section_owner(section):
    order = domain.order_of_section(section)
    if order is None or actor_id() != order["plant_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    return order


@bp.post("/installations/sections/<row_id>/measure")
@roles("PlantDispatcher")
def measure_section(row_id):
    body = validate(
        [
            {"name": "measured_width_in", "type": "number", "required": True},
            {"name": "measured_height_in", "type": "number", "required": True},
        ]
    )
    section = lookup("sections", row_id, "ERR_SECTION_NOT_FOUND")
    order = _require_section_owner(section)
    if section["transit_status"] != "AT_PLANT":
        fail("ERR_INVALID_STATE")
    section["measured_width_in"] = body["measured_width_in"]
    section["measured_height_in"] = body["measured_height_in"]
    section["transit_status"] = "MEASURED"
    mark(section)
    domain.recompute_posture(order)
    return object_response(domain.pub_section(section))


@bp.post("/installations/sections/<row_id>/release")
@roles("PlantDispatcher")
def release_section(row_id):
    section = lookup("sections", row_id, "ERR_SECTION_NOT_FOUND")
    order = _require_section_owner(section)
    if section["transit_status"] != "MEASURED":
        fail("ERR_INVALID_STATE")
    section["transit_status"] = "PERMIT_PENDING"
    mark(section)
    domain.recompute_posture(order)
    return object_response(domain.pub_section(section))


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------
@bp.post("/installations/sites")
@roles("NetworkAdmin", "InstallationInspector")
def create_site():
    body = validate(
        [
            {"name": "order_id", "type": "string", "required": True},
            {
                "name": "pad_type",
                "type": "enum",
                "required": True,
                "values": ["SLAB", "RUNNER", "CROSSING_BEAM"],
            },
            {"name": "pier_plan_ref", "type": "string", "required": True},
            {"name": "pier_count", "type": "integer", "required": True, "min": 0},
            {"name": "utility_water", "type": "boolean", "required": True},
            {"name": "utility_sewer", "type": "boolean", "required": True},
            {"name": "utility_electric", "type": "boolean", "required": True},
        ]
    )
    order = lookup_ref("orders", body["order_id"], "ERR_ORDER_NOT_FOUND")
    row = base_row()
    row.update(
        {
            "order_id": order["id"],
            "pad_type": body["pad_type"],
            "pier_plan_ref": body["pier_plan_ref"],
            "pier_count": body["pier_count"],
            "utility_water": body["utility_water"],
            "utility_sewer": body["utility_sewer"],
            "utility_electric": body["utility_electric"],
            "readiness_status": "READINESS_PENDING",
            "inspection_round": 0,
            "last_inspector_user_id": None,
            "blocking_defect_count": 0,
        }
    )
    db.sites[row["id"]] = row
    mark(order)
    domain.recompute_posture(order)
    return object_response(domain.pub_site(row), 201)


@bp.get("/installations/sites/<row_id>")
@roles(*ANY_ROLE)
def read_site(row_id):
    row = lookup("sites", row_id, "ERR_SITE_NOT_FOUND")
    return object_response(domain.pub_site(row))


@bp.get("/installations/sites")
@roles(*ANY_ROLE)
def list_sites():
    active = filters(
        {
            "order_id": None,
            "readiness_status": ["READINESS_PENDING", "READINESS_FAILED", "READY"],
        }
    )
    rows = apply_filters(list(db.sites.values()), active)
    return list_response(rows, domain.pub_site)


@bp.post("/installations/sites/<row_id>/readiness-inspection")
@roles("InstallationInspector")
def inspect_site(row_id):
    body = validate(
        [
            {"name": "pad_pass", "type": "boolean", "required": True},
            {"name": "pier_plan_pass", "type": "boolean", "required": True},
            {"name": "utility_pass", "type": "boolean", "required": True},
        ]
    )
    site = lookup("sites", row_id, "ERR_SITE_NOT_FOUND")
    if site["readiness_status"] not in ("READINESS_PENDING", "READINESS_FAILED"):
        fail("ERR_INVALID_STATE")
    order = db.orders.get(site["order_id"])
    previous = site["readiness_status"]
    defects, status = calc.site_readiness_evaluation(
        site,
        order,
        body["pad_pass"],
        body["pier_plan_pass"],
        body["utility_pass"],
    )
    site["blocking_defect_count"] = defects
    site["readiness_status"] = status
    site["inspection_round"] = int(site["inspection_round"]) + 1
    site["last_inspector_user_id"] = actor_id()
    mark(site)
    # PRD 3.3: the READINESS_FAILED self-loop does not re-derive the posture.
    if not (previous == "READINESS_FAILED" and status == "READINESS_FAILED"):
        domain.recompute_posture(order)
    return object_response(domain.pub_site(site))
