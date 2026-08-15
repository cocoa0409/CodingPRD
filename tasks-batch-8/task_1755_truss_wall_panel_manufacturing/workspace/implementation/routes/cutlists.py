"""CutList and CutListLine endpoints: explosion, release, reconcile, cut/scrap."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_DESIGN_NOT_CURRENT,
    ERR_CUT_LIST_NOT_RELEASED,
    ERR_CUT_LIST_NOT_RECONCILING,
    ERR_JIG_COMPONENT_MISMATCH,
)
from middleware import authenticate, require_role, get_or_404, INTERNAL_ROLES
from response import success, success_list
from services import cascade, serializers
from services.derive import design_is_current
from util import as_enum, as_int, as_num, as_str, as_fk, body, paginate

bp = Blueprint("cutlists", __name__)

DIMENSIONS = {"L2X4", "L2X6", "L2X8"}


def _validate_line_spec(spec, index):
    if not isinstance(spec, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"lines[{index}] must be an object")
    return {
        "member_label": as_str(spec.get("member_label"), f"lines[{index}].member_label", required=True),
        "dimension": as_enum(spec.get("dimension"), f"lines[{index}].dimension", DIMENSIONS, required=True),
        "length_ft": as_num(spec.get("length_ft"), f"lines[{index}].length_ft", required=True),
        "qty": as_int(spec.get("qty"), f"lines[{index}].qty", required=True),
    }


@bp.route("/plant/designs/<design_id>/cut-lists", methods=["POST"])
def create_cut_list(design_id):
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    design = get_or_404(db.designs, design_id, "component design")
    data = body()
    jig = as_fk(data.get("jig_setup_id"), "jig_setup_id", db.jig_setups, "jig setup")
    # Schema.
    if jig is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: jig_setup_id")
    lines = data.get("lines")
    if not isinstance(lines, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: lines (array)")
    line_specs = [_validate_line_spec(s, i) for i, s in enumerate(lines)]
    # Seal governance (priority 20): design must be SEALED and current.
    if not design_is_current(design):
        raise ApiError(ERR_DESIGN_NOT_CURRENT, 409,
                       "design is not the current SEALED revision of its component_ref")
    # Jig compatibility (priority 27).
    if jig["component_type_supported"] != design["component_type"]:
        raise ApiError(ERR_JIG_COMPONENT_MISMATCH, 422,
                       "jig component_type_supported does not equal the design component_type")
    rec = db.new_record({
        "design_id": design["id"],
        "job_id": design["job_id"],
        "jig_setup_id": jig["id"],
        "rebuild_for_claim_id": None,
        "status": "EXPLODED",
    })
    db.cut_lists[rec["id"]] = rec
    total_bf, total_pieces, total_plates = cascade.create_cut_list_lines(rec, design, line_specs)
    rec["total_board_feet"] = total_bf
    rec["total_pieces"] = total_pieces
    rec["total_plates"] = total_plates
    return success(serializers.cut_list(rec), status=201)


@bp.route("/plant/cut-lists/<cid>", methods=["GET"])
def get_cut_list(cid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.cut_list(get_or_404(db.cut_lists, cid, "cut list")))


@bp.route("/plant/cut-lists", methods=["GET"])
def list_cut_lists():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.cut_lists.values())
    for field in ("design_id", "job_id", "jig_setup_id", "rebuild_for_claim_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [c for c in records if c[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.cut_list(c) for c in page], meta)


@bp.route("/plant/cut-lists/<cid>/release", methods=["POST"])
def release_cut_list(cid):
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    rec = get_or_404(db.cut_lists, cid, "cut list")
    # Status guard first (priority 9), then currency (20), then jig (27).
    if rec["status"] != "EXPLODED":
        raise ApiError(ERR_CUT_LIST_NOT_RELEASED, 409, "only an EXPLODED cut list can be released")
    design = db.designs[rec["design_id"]]
    if not design_is_current(design):
        raise ApiError(ERR_DESIGN_NOT_CURRENT, 409,
                       "design is not the current SEALED revision of its component_ref")
    jig = db.jig_setups[rec["jig_setup_id"]]
    if jig["component_type_supported"] != design["component_type"]:
        raise ApiError(ERR_JIG_COMPONENT_MISMATCH, 422,
                       "jig component_type_supported does not equal the design component_type")
    rec["status"] = "RELEASED"
    db.touch(rec)
    job = db.jobs[rec["job_id"]]
    if job["status"] == "CONFIRMED":
        # First RELEASED cut list of the job advances it to IN_PRODUCTION.
        job["status"] = "IN_PRODUCTION"
        db.touch(job)
    return success(serializers.cut_list(rec))


@bp.route("/plant/cut-lists/<cid>/reconcile", methods=["POST"])
def reconcile_cut_list(cid):
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    rec = get_or_404(db.cut_lists, cid, "cut list")
    if rec["status"] != "RECONCILING":
        raise ApiError(ERR_CUT_LIST_NOT_RECONCILING, 409, "cut list is not in RECONCILING")
    lines = sorted((ln for ln in db.cut_list_lines.values() if ln["cut_list_id"] == rec["id"]),
                   key=lambda ln: ln["_seq"])
    for ln in lines:
        if ln["status"] in ("PENDING", "CUT"):
            cascade.scrap_line(ln)
    rec["status"] = "CLOSED"
    db.touch(rec)
    return success(serializers.cut_list(rec))


# ---------------------------------------------------------------------------
# Cut list lines
# ---------------------------------------------------------------------------

@bp.route("/plant/cut-list-lines", methods=["GET"])
def list_cut_list_lines():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.cut_list_lines.values())
    for field in ("cut_list_id", "status", "dimension"):
        raw = request.args.get(field)
        if raw is not None:
            records = [ln for ln in records if ln[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.cut_list_line(ln) for ln in page], meta)


@bp.route("/plant/cut-list-lines/<lid>", methods=["GET"])
def get_cut_list_line(lid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.cut_list_line(get_or_404(db.cut_list_lines, lid, "cut list line")))


@bp.route("/plant/cut-list-lines/<lid>/mark-cut", methods=["POST"])
def mark_line_cut(lid):
    _uid, role = authenticate()
    require_role(role, ["ShopFloorLead"])
    rec = get_or_404(db.cut_list_lines, lid, "cut list line")
    if rec["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, f"line in status {rec['status']} cannot be marked cut")
    # Sibling-state guard: some batch referencing this line's cut list must be
    # in CUTTING.
    if not any(b["cut_list_id"] == rec["cut_list_id"] and b["status"] == "CUTTING"
               for b in db.production_batches.values()):
        raise ApiError(ERR_INVALID_STATE, 409, "no production batch of this cut list is in CUTTING")
    rec["status"] = "CUT"
    db.touch(rec)
    return success(serializers.cut_list_line(rec))


@bp.route("/plant/cut-list-lines/<lid>/scrap", methods=["POST"])
def scrap_line_endpoint(lid):
    _uid, role = authenticate()
    require_role(role, ["ShopFloorLead"])
    rec = get_or_404(db.cut_list_lines, lid, "cut list line")
    if rec["status"] not in ("PENDING", "CUT"):
        raise ApiError(ERR_INVALID_STATE, 409, f"line in status {rec['status']} cannot be scrapped")
    cascade.scrap_line(rec)
    return success(serializers.cut_list_line(rec))
