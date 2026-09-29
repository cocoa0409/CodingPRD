"""Project and engineering endpoints."""

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import serializers
import store
import validators as v
from errors import ApiError
from numeric import round_half_up, to_fraction

bp = Blueprint("projects", __name__)


def _region_code(body, name):
    value = v.get_str(body, name, min_len=2, max_len=8)
    if not value.isupper() or not value.isalpha():
        v.fail("Field '%s' must be 2 to 8 uppercase characters." % name)
    return value


@bp.route("/projects", methods=["POST"])
def create_project():
    auth.require("DesignEngineer")
    body = v.body()
    payload = {
        "customer_name": v.get_str(body, "customer_name", min_len=1, max_len=120),
        "install_environment": v.get_enum(body, "install_environment",
                                          calc.INSTALL_ENVIRONMENTS),
        "site_region_code": _region_code(body, "site_region_code"),
        "display_model_id": v.get_id(body, "display_model_id"),
        "cabinet_grid_cols": v.get_int(body, "cabinet_grid_cols", minimum=1, maximum=40),
        "cabinet_grid_rows": v.get_int(body, "cabinet_grid_rows", minimum=1, maximum=40),
        "min_viewing_distance_m": v.get_num(body, "min_viewing_distance_m",
                                            exclusive_min=0, places=1),
        "target_brightness_nits": v.get_int(body, "target_brightness_nits", minimum=100),
        "redundancy_mode": v.get_enum(body, "redundancy_mode", calc.REDUNDANCY_MODES),
        "output_port_count": v.get_int(body, "output_port_count", minimum=1, maximum=64),
        "port_bandwidth_mbps": v.get_int(body, "port_bandwidth_mbps", minimum=1),
        "color_depth_bits": v.get_int(body, "color_depth_bits", choices=(8, 10, 12)),
        "refresh_rate_hz": v.get_int(body, "refresh_rate_hz", minimum=24, maximum=240),
        "player_count": v.get_int(body, "player_count", minimum=1, maximum=16),
    }

    model = store.display_models.get(payload["display_model_id"])
    if model is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    # rung 29
    if to_fraction(payload["min_viewing_distance_m"]) < to_fraction(
            model["recommended_min_viewing_distance_m"]):
        raise ApiError("ERR_VIEWING_DISTANCE_TOO_SHORT")
    # rung 30
    if payload["install_environment"] == "ROADSIDE" and payload["redundancy_mode"] == "NONE":
        raise ApiError("ERR_REDUNDANCY_REQUIRED_FOR_ROADSIDE")

    cabinet_count = payload["cabinet_grid_cols"] * payload["cabinet_grid_rows"]
    required, effective, pct = calc.data_load(model, payload, cabinet_count)
    # rung 53 — a control system with zero effective capacity can never drive the wall
    if pct is None or pct > calc.MAX_DATA_LOAD_PCT:
        raise ApiError("ERR_DATA_LOAD_EXCEEDS_CAPACITY")

    computed = {
        "cabinet_count": cabinet_count,
        "module_count": cabinet_count * model["modules_per_cabinet"],
        "total_area_sqm": round_half_up(
            to_fraction(model["cabinet_area_sqm"]) * cabinet_count, 4),
        "contract_amount_cents": calc.contract_amount_cents(
            model, payload["install_environment"], payload["redundancy_mode"], cabinet_count),
        "required_data_mbps": required,
        "effective_capacity_mbps": effective,
        "data_load_pct": pct,
        "engineering_state": "DRAFT",
        "production_state": "NOT_STARTED",
        "approved_revision_number": None,
    }
    rec = store.new_record(payload)
    rec.update(computed)
    store.display_projects[rec["id"]] = rec
    return envelope.object_response(serializers.display_project(rec), 201)


@bp.route("/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    auth.require(*auth.ALL_ROLES)
    rec = store.display_projects.get(project_id)
    if rec is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    return envelope.object_response(serializers.display_project(rec))


@bp.route("/projects", methods=["GET"])
def list_projects():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    model_id = v.query_str("display_model_id")
    environment = v.query_enum("install_environment", calc.INSTALL_ENVIRONMENTS)
    eng = v.query_enum("engineering_state", calc.ENGINEERING_STATES)
    prod = v.query_enum("production_state", calc.PRODUCTION_STATES)
    rows = aggregates.by_created(store.display_projects.values())
    if model_id is not None:
        rows = [r for r in rows if r["display_model_id"] == model_id]
    if environment is not None:
        rows = [r for r in rows if r["install_environment"] == environment]
    if eng is not None:
        rows = [r for r in rows if r["engineering_state"] == eng]
    if prod is not None:
        rows = [r for r in rows if r["production_state"] == prod]
    return envelope.paginated(rows, limit, offset, serializers.display_project)


# ---------------------------------------------------------------------------
# Drawing revisions
# ---------------------------------------------------------------------------
@bp.route("/drawing-revisions", methods=["POST"])
def submit_revision():
    user_id, _ = auth.require("DesignEngineer")
    body = v.body()
    payload = {
        "project_id": v.get_id(body, "project_id"),
        "structural_load_kg_per_sqm": v.get_num(body, "structural_load_kg_per_sqm",
                                                exclusive_min=0, places=2),
        "wind_load_kph": v.get_int(body, "wind_load_kph", minimum=0),
        "mounting_type": v.get_enum(body, "mounting_type", calc.MOUNTING_TYPES),
        "service_access_side": v.get_enum(body, "service_access_side",
                                          calc.SERVICE_ACCESS_SIDES),
    }
    project = store.display_projects.get(payload["project_id"])
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    # rung 17
    if project["engineering_state"] == "APPROVED":
        raise ApiError("ERR_ENGINEERING_ALREADY_APPROVED")
    model = aggregates.model_of_project(project)
    # rung 27
    if payload["wind_load_kph"] < calc.MIN_WIND_LOAD_KPH[project["install_environment"]]:
        raise ApiError("ERR_WIND_LOAD_INSUFFICIENT")
    # rung 28
    if to_fraction(payload["structural_load_kg_per_sqm"]) < to_fraction(
            model["required_load_kg_per_sqm"]):
        raise ApiError("ERR_STRUCTURAL_CAPACITY_INSUFFICIENT")
    # rung 40
    existing = [r for r in store.drawing_revisions.values()
                if r["project_id"] == project["id"]]
    if any(r["revision_state"] == "SUBMITTED" for r in existing):
        raise ApiError("ERR_OPEN_REVISION_EXISTS")

    rec = store.new_record(payload)
    rec["revision_number"] = len(existing) + 1
    rec["required_load_kg_per_sqm"] = model["required_load_kg_per_sqm"]
    rec["submitted_by_user_id"] = user_id
    rec["reviewed_by_user_id"] = None
    rec["rejection_reason"] = None
    rec["revision_state"] = "SUBMITTED"
    store.drawing_revisions[rec["id"]] = rec

    project["engineering_state"] = "UNDER_REVIEW"
    store.touch(project)
    return envelope.object_response(serializers.drawing_revision(rec), 201)


@bp.route("/drawing-revisions/<drawing_revision_id>/review", methods=["POST"])
def review_revision(drawing_revision_id):
    user_id, _ = auth.require("StructuralReviewer")
    body = v.body()
    decision = v.get_enum(body, "decision", ("APPROVE", "REJECT"))
    rec = store.drawing_revisions.get(drawing_revision_id)
    if rec is None:
        raise ApiError("ERR_REVISION_NOT_FOUND")
    # rung 16
    if rec["revision_state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REVISION_STATE")
    # rung 26
    if user_id == rec["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    project = store.display_projects.get(rec["project_id"])
    if decision == "REJECT":
        reason = v.get_str(body, "reason", min_len=1, max_len=240)
        rec["revision_state"] = "REJECTED"
        rec["reviewed_by_user_id"] = user_id
        rec["rejection_reason"] = reason
        store.touch(rec)
        if project is not None:
            project["engineering_state"] = "REJECTED"
            store.touch(project)
    else:
        rec["revision_state"] = "APPROVED"
        rec["reviewed_by_user_id"] = user_id
        store.touch(rec)
        if project is not None:
            project["engineering_state"] = "APPROVED"
            project["approved_revision_number"] = rec["revision_number"]
            store.touch(project)
    return envelope.object_response(serializers.drawing_revision(rec))


@bp.route("/drawing-revisions/<drawing_revision_id>", methods=["GET"])
def get_revision(drawing_revision_id):
    auth.require(*auth.ALL_ROLES)
    rec = store.drawing_revisions.get(drawing_revision_id)
    if rec is None:
        raise ApiError("ERR_REVISION_NOT_FOUND")
    return envelope.object_response(serializers.drawing_revision(rec))


@bp.route("/drawing-revisions", methods=["GET"])
def list_revisions():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    project_id = v.query_str("project_id")
    state = v.query_enum("revision_state", calc.REVISION_STATES)
    rows = aggregates.by_created(store.drawing_revisions.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if state is not None:
        rows = [r for r in rows if r["revision_state"] == state]
    return envelope.paginated(rows, limit, offset, serializers.drawing_revision)
