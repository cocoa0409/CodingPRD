"""Material change events and the resample cascade head (PRD 3.10)."""

from flask import Blueprint

import auth
import clock
import db
import paging
import refs
import response
import validation
from errors import ApiError
from routes.products import guard_not_archived
from services import calc, engine

bp = Blueprint("events", __name__)

SUBJECT_TYPES = {"PRODUCT", "COMPONENT_PART"}
CHANGE_KINDS = {
    "SUPPLIER_SWITCH",
    "MATERIAL_SUBSTITUTION",
    "COATING_CHANGE",
    "DESIGN_GEOMETRY_CHANGE",
    "PACKAGING_ONLY",
}
EVENT_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
)


@bp.post("/material-change-events")
def record_event():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    product_id = validation.id_field(body, "product_id")
    subject_type = validation.enum_field(body, "subject_type", SUBJECT_TYPES)
    change_kind = validation.enum_field(body, "change_kind", CHANGE_KINDS)
    description = validation.string_field(body, "description", min_len=1, max_len=400)
    component_part_id = validation.id_field(body, "component_part_id", required=False)

    product = refs.product(product_id)
    part = refs.part(component_part_id) if component_part_id is not None else None
    guard_not_archived(product)

    if subject_type == "COMPONENT_PART":
        if part is None or part["product_id"] != product["id"]:
            raise ApiError("ERR_PART_SUBJECT_MISMATCH")
    else:
        if component_part_id is not None:
            raise ApiError("ERR_PART_SUBJECT_MISMATCH")

    triggers_resample = calc.triggers_resample(change_kind)
    row = db.insert(
        "material_change_events",
        {
            "product_id": product["id"],
            "component_part_id": component_part_id,
            "subject_type": subject_type,
            "change_kind": change_kind,
            "description": description,
            "occurred_at": clock.now(),
            "triggers_resample": triggers_resample,
            "recorded_by_user_id": auth.current_user_id(),
        },
        with_version=False,
    )

    product["material_change_count"] += 1
    if triggers_resample:
        engine.cascade_material_change(product, part, change_kind)
    engine.bump("products", product)
    return response.object_response(db.serialize("material_change_events", row), 201)


@bp.get("/material-change-events/<event_id>")
def get_event(event_id):
    auth.require_roles(*EVENT_READ_ROLES)
    row = refs.event(event_id)
    return response.object_response(db.serialize("material_change_events", row))


@bp.get("/material-change-events")
def list_events():
    auth.require_roles(*EVENT_READ_ROLES)
    product_id = validation.query_string("product_id")
    component_part_id = validation.query_string("component_part_id")
    subject_type = validation.query_enum("subject_type", SUBJECT_TYPES)
    change_kind = validation.query_enum("change_kind", CHANGE_KINDS)
    triggers_resample = validation.query_bool("triggers_resample")
    return paging.build(
        "material_change_events",
        [
            paging.eq_filter("product_id", product_id),
            paging.eq_filter("component_part_id", component_part_id),
            paging.eq_filter("subject_type", subject_type),
            paging.eq_filter("change_kind", change_kind),
            paging.eq_filter("triggers_resample", triggers_resample),
        ],
        sort="material_change_desc",
    )
