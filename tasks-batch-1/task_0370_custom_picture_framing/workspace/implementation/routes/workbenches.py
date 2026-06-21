"""Workbench endpoints (PRD §3.6)."""
from flask import Blueprint

import errors
import validate
from db import db
from middleware import get_auth, require_role
from response import ok_array, ok_object
from services import domain

bp = Blueprint("workbenches", __name__)

BENCH_TYPES = {"ASSEMBLY", "GLASS_CUTTING"}


def _find_workbench_or_404(workbench_id):
    w = db.workbenches.get(workbench_id)
    if w is None:
        errors.raise_err(errors.ERR_WORKBENCH_NOT_FOUND, "Workbench not found")
    return w


@bp.route("/workbenches", methods=["POST"])
def create_workbench():
    auth = get_auth()
    require_role(auth, ("FrameProductionTech",))
    body = validate.get_json_body()

    bench_name = validate.as_string(validate.require(body, "bench_name"), "bench_name")
    bench_type = validate.as_enum(validate.require(body, "bench_type"), "bench_type", BENCH_TYPES)
    clean_buffer = validate.opt(body, "clean_buffer_minutes", 0)
    validate.as_nonneg_int(clean_buffer, "clean_buffer_minutes")

    w = {
        "bench_name": bench_name,
        "bench_type": bench_type,
        "clean_buffer_minutes": clean_buffer,
    }
    domain.stamp_create(w)
    db.workbenches[w["id"]] = w
    return ok_object(domain.serialize_workbench(w), status=201)


@bp.route("/workbenches", methods=["GET"])
def list_workbenches():
    auth = get_auth()
    require_role(auth, ("FrameProductionTech", "FrameDesigner", "FrontDeskClerk"))
    limit, offset = validate.parse_pagination()
    items = list(db.workbenches.values())
    items.sort(key=lambda w: (w["created_at"], w["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_workbench(w) for w in page], limit, offset, total)


@bp.route("/workbenches/<workbench_id>", methods=["GET"])
def get_workbench(workbench_id):
    auth = get_auth()
    require_role(auth, ("FrameProductionTech", "FrameDesigner", "FrontDeskClerk"))
    w = _find_workbench_or_404(workbench_id)
    return ok_object(domain.serialize_workbench(w))


@bp.route("/workbenches/<workbench_id>/production-tasks", methods=["GET"])
def list_workbench_tasks(workbench_id):
    auth = get_auth()
    require_role(auth, ("FrameProductionTech", "FrameDesigner", "FrontDeskClerk"))
    _find_workbench_or_404(workbench_id)
    limit, offset = validate.parse_pagination()
    items = [t for t in db.production_tasks.values() if t["workbench_id"] == workbench_id]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_task(t) for t in page], limit, offset, total)
