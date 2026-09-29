"""Field inventory, lineage and administrative closure (PRD 3.1)."""

import calc
import derive
import errors
import middleware
import response
import validate
from db import common_fields, db, new_id, now
from errors import ApiError
from routes.blueprint import bp
from routes.common import listing

FILTERS = {
    "surface_type": "surface_type",
    "play_status": "play_status",
    "certification_status": "certification_status",
    "predecessor_field_id": "predecessor_field_id",
}


@bp.post("/fields")
def register_field():
    middleware.authenticate(["FacilitiesDirector"])
    body = validate.Body(
        required=["name", "surface_type", "installed_on_date",
                  "expected_life_years", "area_sq_ft", "sanctioned_level"],
        optional=["warranty_expires_on", "infill_depth_mm", "predecessor_field_id"])

    name = body.string("name", 1, 120)
    surface_type = body.enum("surface_type", calc.SURFACE_TYPES)
    installed_on_date = body.date("installed_on_date")
    expected_life_years = body.integer("expected_life_years", 1, 30)
    area_sq_ft = body.integer("area_sq_ft", 1, 400000)
    sanctioned_level = body.enum("sanctioned_level", calc.SANCTIONED_LEVELS)
    warranty_expires_on = body.date("warranty_expires_on")
    infill_depth_mm = body.number("infill_depth_mm", calc.rnd("0.0", 1),
                                  calc.rnd("80.0", 1))
    predecessor_field_id = body.string("predecessor_field_id")

    # priority 18 - body-borne foreign key
    predecessor = None
    if predecessor_field_id is not None:
        predecessor = middleware.body_field(predecessor_field_id)

    # priority 22 - name unique across fields whose retired_at IS NULL
    for other in db.fields.values():
        if other["retired_at"] is None and other["name"] == name:
            raise ApiError("ERR_FIELD_NAME_DUPLICATE", 409,
                           "A field still in service already carries that name.")

    # priority 25 - the infill-depth rule
    if surface_type == "SYNTHETIC_TURF" and infill_depth_mm is None:
        raise ApiError("ERR_INFILL_DEPTH_REQUIRED", 422,
                       "infill_depth_mm is required for a SYNTHETIC_TURF field.")
    if surface_type == "NATURAL_GRASS" and infill_depth_mm is not None:
        raise ApiError("ERR_INFILL_DEPTH_REQUIRED", 422,
                       "infill_depth_mm must be absent for a NATURAL_GRASS field.")

    # priority 32 - the predecessor-retirement rule
    if predecessor is not None and predecessor["retired_at"] is None:
        raise ApiError("ERR_PREDECESSOR_FIELD_NOT_RETIRED", 422,
                       "predecessor_field_id must name a field that has been retired.")

    field = {
        "id": new_id(),
        "name": name,
        "surface_type": surface_type,
        "installed_on_date": installed_on_date,
        "expected_life_years": expected_life_years,
        "area_sq_ft": area_sq_ft,
        "sanctioned_level": sanctioned_level,
        "warranty_expires_on": warranty_expires_on,
        "infill_depth_mm": (calc.r1(infill_depth_mm)
                            if infill_depth_mm is not None else None),
        "predecessor_field_id": predecessor_field_id,
        "age_years": None,
        "warranty_status": None,
        "admin_closure_active": False,
        "admin_closure_reason_code": None,
        "retired_at": None,
        "play_status": "OPEN",
        "certification_status": "NOT_CERTIFIED",
        "certified_until_utc": None,
        "latest_gmax_mean_value": None,
        "cumulative_wear_units": calc.r2(0),
        "usage_hours_ytd": calc.r2(0),
        "rest_debt_hours": calc.r2(0),
        "nitrogen_applied_ytd_lb_per_1000_sq_ft": calc.r2(0),
        "condition_index_agronomic": None,
        "open_mandatory_remediation_count": 0,
        "open_advisory_remediation_count": 0,
        "open_certification_packet_count": 0,
        "open_replacement_plan_count": 0,
        "unsafe_cancellation_count": 0,
    }
    field.update(common_fields())
    db.fields[field["id"]] = field
    derive.recompute_field(field)
    return response.created(field)


@bp.get("/fields")
def list_fields():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.fields, FILTERS)


@bp.get("/fields/<field_id>")
def read_field(field_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.field_or_404(field_id))


@bp.post("/fields/<field_id>/closure-order")
def closure_order(field_id):
    middleware.authenticate(["FacilitiesDirector"])
    field = middleware.field_or_404(field_id)
    body = validate.Body(required=["action", "reason_code"])
    action = body.enum("action", ["CLOSE_ADMIN", "REOPEN_ADMIN"])
    reason_code = body.string("reason_code", 1, 200)

    # priority 34 - the retirement guard
    if field["retired_at"] is not None:
        raise ApiError("ERR_FIELD_RETIRED", 409,
                       "A retired field takes no closure orders.")

    # priorities 48 and 49 - state preconditions
    if action == "CLOSE_ADMIN" and field["admin_closure_active"]:
        raise ApiError("ERR_FIELD_ALREADY_CLOSED", 409,
                       "An administrative closure is already in force.")
    if action == "REOPEN_ADMIN" and not field["admin_closure_active"]:
        raise ApiError("ERR_FIELD_NOT_CLOSED", 409,
                       "No administrative closure is in force on this field.")

    # priority 53 - an administrative flag may not obscure an unsafe finding
    if field["open_mandatory_remediation_count"] != 0:
        raise ApiError("ERR_UNSAFE_CLOSURE_IN_FORCE", 409,
                       "An open mandatory remediation order is in force on this field.")

    if action == "CLOSE_ADMIN":
        field["admin_closure_active"] = True
        field["admin_closure_reason_code"] = reason_code
    else:
        field["admin_closure_active"] = False
        field["admin_closure_reason_code"] = None

    derive.touch_field(field)
    return response.ok(field)
