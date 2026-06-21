"""Run endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_roles
from services import serialize
from services.common import stamp_create, get_body, require_fields, require_enum
from services.query import paginate_params, sort_by_created, apply_page
from routes.facilities import get_facility_or_404

bp = Blueprint("runs", __name__)

RUN_KINDS = {"OVERNIGHT_SUITE", "DAYCARE_PEN"}
SIZE_CLASSES = {"TOY", "SMALL", "MEDIUM", "LARGE"}
RUN_STATUSES = {"AVAILABLE", "RETIRED"}


def get_run_or_404(rid):
    r = db.runs.get(rid)
    if r is None:
        raise errors.err_not_found()
    return r


@bp.route("/facilities/<fid>/runs", methods=["POST"])
@require_roles("FacilityManager")
def create_run(fid):
    get_facility_or_404(fid)
    body = get_body()
    require_fields(body, ["label", "kind", "size_class"])
    label = body["label"]
    if not isinstance(label, str) or label == "":
        raise errors.err_invalid_request("label must be a non-empty string.")
    kind = body["kind"]
    require_enum(kind, RUN_KINDS, "kind")
    size_class = body["size_class"]
    require_enum(size_class, SIZE_CLASSES, "size_class")

    daycare_capacity = body.get("daycare_capacity", 1)
    if not isinstance(daycare_capacity, int) or isinstance(daycare_capacity, bool) \
            or daycare_capacity < 1:
        raise errors.err_invalid_request("daycare_capacity must be a positive integer.")
    status = body.get("status", "AVAILABLE")
    require_enum(status, RUN_STATUSES, "status")

    # OVERNIGHT_SUITE forced single-occupancy.
    if kind == "OVERNIGHT_SUITE":
        daycare_capacity = 1

    run = {
        "facility_id": fid,
        "label": label,
        "kind": kind,
        "size_class": size_class,
        "daycare_capacity": daycare_capacity,
        "status": status,
    }
    stamp_create(run)
    db.runs[run["id"]] = run
    return response.success(serialize.run(run), status=201)


@bp.route("/facilities/<fid>/runs", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff")
def list_runs(fid):
    get_facility_or_404(fid)
    limit, offset = paginate_params()
    kind_filter = request.args.get("kind")
    status_filter = request.args.get("status")
    items = [r for r in db.runs.values() if r["facility_id"] == fid]
    if kind_filter is not None:
        items = [r for r in items if r["kind"] == kind_filter]
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.run(r) for r in page], limit, offset, total)
