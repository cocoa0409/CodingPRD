"""AlignmentRecord endpoints."""
from flask import Blueprint, request

import db
from calc import alignment_verdict
from errors import ApiError, ERR_INVALID_STATE
from helpers import alignment_or_404, project_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import alignment_json
from util import new_id, now_iso
from validators import get_body, opt_str, pagination, req_enum, req_num, req_str

bp = Blueprint("alignment_records", __name__)


@bp.post("/v1/alignment-records")
@require_roles("SiteSupervisor")
def create_alignment():
    body = get_body()
    pid = body.get("project_id")
    if isinstance(pid, str):
        project_or_404(pid)
    pid = req_str(body, "project_id")
    measurement_point = req_str(body, "measurement_point")
    tolerance_class = req_enum(body, "tolerance_class", ("STANDARD", "PRECISION"))
    off_raw, off_d = req_num(body, "measured_offset_mils", ge=0)
    ang_raw, ang_d = req_num(body, "measured_angular_mils_per_in", ge=0)
    verdict = alignment_verdict(tolerance_class, off_d, ang_d)
    ts = now_iso()
    a = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": pid,
        "measurement_point": measurement_point,
        "tolerance_class": tolerance_class,
        "measured_offset_mils": off_raw,
        "measured_angular_mils_per_in": ang_raw,
        "offset_passed": verdict["offset_passed"],
        "angular_passed": verdict["angular_passed"],
        "verdict": verdict["verdict"],
        "status": "RECORDED",
        "reviewer_note": None,
        "_seq": db.next_seq(),
    }
    db.alignment_records[a["id"]] = a
    return success(alignment_json(a), 201)


@bp.get("/v1/projects/<pid>/alignment-records")
@require_roles(*ROLES)
def list_alignments(pid):
    project_or_404(pid)
    limit, offset = pagination()
    mp = request.args.get("measurement_point")
    items = [a for a in db.alignment_records.values() if a["project_id"] == pid]
    if mp is not None:
        items = [a for a in items if a["measurement_point"] == mp]
    items = sorted_items(items)
    total = len(items)
    return success_list([alignment_json(a) for a in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/alignment-records/<aid>/review")
@require_roles("ProjectManager")
def review_alignment(aid):
    a = alignment_or_404(aid)
    if a["status"] != "RECORDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RECORDED alignment record can be reviewed")
    body = get_body()
    outcome = req_enum(body, "outcome", ("ACCEPTED", "REJECTED"))
    a["status"] = outcome
    a["reviewer_note"] = opt_str(body, "reviewer_note")
    touch(a)
    return success(alignment_json(a))
