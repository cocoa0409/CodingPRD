"""ISOSnapshot endpoints: create draft, list, get, publish (gated)."""
from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_ISO_SNAPSHOT_NOT_FOUND,
    ERR_NO_HYDRANTS_IN_SCOPE,
    ERR_SNAPSHOT_NOT_DRAFT,
    ERR_UNACKNOWLEDGED_NOTIFICATIONS,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from routes.programs import get_program_or_404
from serializers import iso_snapshot_view
from services import compute_iso_metrics, program_hydrants
from validation import F, paginate, validate_body, validate_empty_body

bp = Blueprint("iso_snapshots", __name__)


def get_snapshot_or_404(snapshot_id):
    s = db.store.iso_snapshots.get(snapshot_id)
    if s is None:
        raise not_found(ERR_ISO_SNAPSHOT_NOT_FOUND, "ISOSnapshot")
    return s


@bp.post("/programs/<program_id>/iso-snapshots")
def create_iso_snapshot(program_id):
    user_id, role = auth()
    body = validate_body([
        F("weighting_profile", "enum", arg={"MUNICIPAL_ONLY", "ALL_HYDRANTS_HALF_PRIVATE"}),
    ])
    require_role(role, {"ProgramAdmin"})
    # Path resources validated left to right: the program must exist first
    program = get_program_or_404(program_id)
    snapshot = new_base()
    snapshot.update({
        "program_id": program["id"],
        "weighting_profile": body["weighting_profile"],
        "status": "DRAFT",
        "total_hydrants_in_scope": None,
        "flow_coverage_pct": None,
        "inspection_compliance_pct": None,
        "iso_points": None,
        "published_at": None,
    })
    db.store.iso_snapshots[snapshot["id"]] = snapshot
    return success_object(iso_snapshot_view(snapshot), code=201)


@bp.get("/iso-snapshots")
def list_iso_snapshots():
    auth_any()
    items = list(db.store.iso_snapshots.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return success_list([iso_snapshot_view(s) for s in page], meta)


@bp.get("/iso-snapshots/<snapshot_id>")
def get_iso_snapshot(snapshot_id):
    auth_any()
    return success_object(iso_snapshot_view(get_snapshot_or_404(snapshot_id)))


@bp.post("/iso-snapshots/<snapshot_id>/publish")
def publish_iso_snapshot(snapshot_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"ProgramAdmin"})
    snapshot = get_snapshot_or_404(snapshot_id)
    if snapshot["status"] != "DRAFT":
        raise ApiError(ERR_SNAPSHOT_NOT_DRAFT, "Snapshot must be DRAFT to publish", 409)
    program = db.store.programs[snapshot["program_id"]]
    in_scope = [h for h in program_hydrants(program["id"]) if h["status"] != "DECOMMISSIONED"]
    if len(in_scope) == 0:
        raise ApiError(
            ERR_NO_HYDRANTS_IN_SCOPE,
            "Program must have at least one hydrant not in DECOMMISSIONED",
            422,
        )
    if program["unacknowledged_notification_count"] != 0:
        raise ApiError(
            ERR_UNACKNOWLEDGED_NOTIFICATIONS,
            "Program has unacknowledged fire-department notifications",
            409,
        )
    metrics = compute_iso_metrics(snapshot)
    snapshot["total_hydrants_in_scope"] = metrics["total_hydrants_in_scope"]
    snapshot["flow_coverage_pct"] = metrics["flow_coverage_pct"]
    snapshot["inspection_compliance_pct"] = metrics["inspection_compliance_pct"]
    snapshot["iso_points"] = metrics["iso_points"]
    snapshot["published_at"] = db.now()
    snapshot["status"] = "PUBLISHED"
    touch(snapshot)
    # Any other PUBLISHED snapshot for the same program -> SUPERSEDED
    for other in db.store.iso_snapshots.values():
        if (
            other["id"] != snapshot["id"]
            and other["program_id"] == program["id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    return success_object(iso_snapshot_view(snapshot))
