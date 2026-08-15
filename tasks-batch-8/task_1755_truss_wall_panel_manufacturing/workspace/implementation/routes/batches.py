"""ProductionBatch endpoints: scheduling, build lifecycle, QC/rework loop."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_BATCH_INVALID_TRANSITION,
    ERR_CUT_LIST_NOT_RELEASED,
    ERR_DESIGN_NOT_CURRENT,
    ERR_JIG_COMPONENT_MISMATCH,
    ERR_RESERVATION_COVERAGE_SHORT,
)
from middleware import authenticate, require_role, get_or_404, INTERNAL_ROLES
from response import success, success_list
from services import cascade, serializers
from services.derive import design_is_current, resequence_job_batches
from util import as_dt, as_enum, as_fk, body, paginate

bp = Blueprint("batches", __name__)

BATCH_STATES = {"SCHEDULED", "CUTTING", "ASSEMBLY", "BUILT", "QC_PASSED", "QC_FAILED",
                "REWORK", "STAGED", "LOADED", "CANCELLED"}


@bp.route("/plant/jobs/<job_id>/batches", methods=["POST"])
def create_batch(job_id):
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    job = get_or_404(db.jobs, job_id, "job")
    data = body()
    cut_list = as_fk(data.get("cut_list_id"), "cut_list_id", db.cut_lists, "cut list")
    jig = as_fk(data.get("jig_setup_id"), "jig_setup_id", db.jig_setups, "jig setup")
    if cut_list is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: cut_list_id")
    if jig is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: jig_setup_id")
    requested_completion_at = as_dt(data.get("requested_completion_at"),
                                    "requested_completion_at", required=True)
    # Status guard fires before the jig check (section 3.6).
    if cut_list["status"] != "RELEASED":
        raise ApiError(ERR_CUT_LIST_NOT_RELEASED, 409, "cut list is not RELEASED")
    design = db.designs[cut_list["design_id"]]
    if jig["component_type_supported"] != design["component_type"]:
        raise ApiError(ERR_JIG_COMPONENT_MISMATCH, 422,
                       "jig component_type_supported does not equal the cut list design component_type")
    rec = db.new_record({
        "job_id": job["id"],
        "cut_list_id": cut_list["id"],
        "jig_setup_id": jig["id"],
        "requested_completion_at": requested_completion_at,
        "build_sequence_no": None,
        "is_rebuild": False,
        "source_claim_id": None,
        "status": "SCHEDULED",
    })
    db.production_batches[rec["id"]] = rec
    resequence_job_batches(job["id"])
    return success(serializers.production_batch(rec), status=201)


@bp.route("/plant/batches/<bid>", methods=["GET"])
def get_batch(bid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.production_batch(get_or_404(db.production_batches, bid, "production batch")))


@bp.route("/plant/batches", methods=["GET"])
def list_batches():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.production_batches.values())
    for field in ("job_id", "cut_list_id", "jig_setup_id", "source_claim_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [b for b in records if b[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.production_batch(b) for b in page], meta)


def _coverage_check(cut_list):
    """Every PENDING line fully covered by RESERVED lumber; plates covered."""
    lines = [ln for ln in db.cut_list_lines.values() if ln["cut_list_id"] == cut_list["id"]]
    for ln in lines:
        if ln["status"] != "PENDING":
            continue
        reserved = sum(
            (r["reserved_bf"] for r in db.material_reservations.values()
             if r["cut_list_line_id"] == ln["id"] and r["status"] == "RESERVED"),
            start=Decimal("0"),
        )
        if reserved < ln["required_board_feet"]:
            raise ApiError(ERR_RESERVATION_COVERAGE_SHORT, 422,
                           f"line {ln['member_label']} lumber coverage {reserved} < required {ln['required_board_feet']}")
    plates_reserved = sum(
        r["reserved_plates"] for r in db.material_reservations.values()
        if r["cut_list_id"] == cut_list["id"] and r["status"] == "RESERVED"
    )
    if plates_reserved < cut_list["total_plates"]:
        raise ApiError(ERR_RESERVATION_COVERAGE_SHORT, 422,
                       "RESERVED plate reservations do not cover the cut list total_plates")


def _consume_coverage(cut_list):
    """Entering CUTTING consumes every covering reservation."""
    line_ids = {ln["id"] for ln in db.cut_list_lines.values() if ln["cut_list_id"] == cut_list["id"]}
    for r in sorted(db.material_reservations.values(), key=lambda r: r["_seq"]):
        if r["status"] != "RESERVED":
            continue
        if r["cut_list_line_id"] in line_ids or r["cut_list_id"] == cut_list["id"]:
            cascade.reservation_consume_apply(r)


@bp.route("/plant/batches/<bid>/transition", methods=["POST"])
def batch_transition(bid):
    _uid, role = authenticate()
    require_role(role, ["ShopFloorLead"])
    rec = get_or_404(db.production_batches, bid, "production batch")
    data = body()
    to_state = as_enum(data.get("to_state"), "to_state", BATCH_STATES, required=True)
    current = rec["status"]

    # System-only targets are never reachable by direct request.
    if to_state in ("LOADED", "CANCELLED"):
        raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                       f"batch transition to {to_state} is system-only")

    if to_state == "CUTTING":
        if current != "SCHEDULED":
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           f"batch transition {current} -> CUTTING is not declared")
        cut_list = db.cut_lists[rec["cut_list_id"]]
        # Gate order (section 3.6): list RELEASED, design current, job
        # IN_PRODUCTION, then coverage.
        if cut_list["status"] != "RELEASED":
            raise ApiError(ERR_CUT_LIST_NOT_RELEASED, 409, "cut list is not RELEASED")
        if not design_is_current(db.designs[cut_list["design_id"]]):
            raise ApiError(ERR_DESIGN_NOT_CURRENT, 409,
                           "cut list design is not the current SEALED revision")
        job = db.jobs[rec["job_id"]]
        if job["status"] != "IN_PRODUCTION":
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409, "job is not IN_PRODUCTION")
        _coverage_check(cut_list)
        _consume_coverage(cut_list)
    elif to_state == "ASSEMBLY":
        if current != "CUTTING":
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           f"batch transition {current} -> ASSEMBLY is not declared")
        if any(ln["cut_list_id"] == rec["cut_list_id"] and ln["status"] not in ("CUT", "SCRAPPED")
               for ln in db.cut_list_lines.values()):
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           "every line of the cut list must be CUT or SCRAPPED before ASSEMBLY")
    elif to_state == "BUILT":
        if current != "ASSEMBLY":
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           f"batch transition {current} -> BUILT is not declared")
    elif to_state == "QC_PASSED":
        if current not in ("BUILT", "REWORK"):
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           f"batch transition {current} -> QC_PASSED is not declared")
    elif to_state == "QC_FAILED":
        if current != "BUILT":
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           f"batch transition {current} -> QC_FAILED is not declared")
    elif to_state == "REWORK":
        if current != "QC_FAILED":
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           f"batch transition {current} -> REWORK is not declared")
    elif to_state == "STAGED":
        if current != "QC_PASSED":
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           f"batch transition {current} -> STAGED is not declared")
        if not any(s["production_batch_id"] == rec["id"] and s["purpose"] == "BUILD_PICK"
                   and s["status"] == "COMPLETED" for s in db.crane_slots.values()):
            raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                           "no COMPLETED BUILD_PICK crane slot references this batch")
    else:  # SCHEDULED as a target, or anything left
        raise ApiError(ERR_BATCH_INVALID_TRANSITION, 409,
                       f"batch transition {current} -> {to_state} is not declared")

    rec["status"] = to_state
    db.touch(rec)
    return success(serializers.production_batch(rec))
