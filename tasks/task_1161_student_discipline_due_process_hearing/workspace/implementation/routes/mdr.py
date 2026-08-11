"""Manifestation determinations (PRD §3.6)."""
from flask import Blueprint

from db import db, touch, serialize, clock
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MDR_NOT_APPLICABLE,
    ERR_MDR_ALREADY_OPEN,
    ERR_MDR_DEADLINE_PASSED,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, render_list
from services.calc import create_mdr, open_mdr_exists
from util import parse_dt

bp = Blueprint("mdr", __name__)


@bp.post("/cases/<cid>/manifestation-determinations")
@endpoint("StudentServicesDirector")
def create_manual_mdr(ctx, cid):
    case = get_or_404(db.cases, cid, "case")
    student = db.students[case["student_id"]]
    # Applicability before uniqueness (PRD §2.9 rung 11 listing order)
    if student["disability_status"] == "NONE" or case["status"] not in (
        "EXPULSION_REFERRED",
        "EXPULSION_ACTIVE",
    ):
        raise_err(ERR_MDR_NOT_APPLICABLE, "manual MDR requires a disability-status student on the expulsion track")
    if open_mdr_exists(cid):
        raise_err(ERR_MDR_ALREADY_OPEN, "an open manifestation determination already exists for this case")
    mdr = create_mdr(cid, "MANUAL")
    return success(serialize(mdr), 201)


@bp.get("/cases/<cid>/manifestation-determinations")
@endpoint("DistrictAdmin", "SchoolAdministrator", "StudentServicesDirector")
def list_mdrs(ctx, cid):
    get_or_404(db.cases, cid, "case")
    mdrs = {k: v for k, v in db.mdrs.items() if v["case_id"] == cid}
    return render_list(mdrs)


@bp.post("/manifestation-determinations/<mid>/schedule")
@endpoint("StudentServicesDirector")
def schedule_mdr(ctx, mid):
    mdr = get_or_404(db.mdrs, mid, "manifestation determination")
    meeting_at = parse_dt(ctx.body.get("meeting_at"))
    if meeting_at is None:
        raise_err(ERR_INVALID_REQUEST, "meeting_at must be a valid ISO 8601 timestamp")
    if mdr["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "manifestation determination is not PENDING")
    mdr["meeting_at"] = meeting_at
    mdr["status"] = "SCHEDULED"
    touch(mdr)
    return success(serialize(mdr))


@bp.post("/manifestation-determinations/<mid>/complete")
@endpoint("StudentServicesDirector")
def complete_mdr(ctx, mid):
    mdr = get_or_404(db.mdrs, mid, "manifestation determination")
    outcome = ctx.body.get("outcome")
    if outcome not in ("MANIFESTATION_YES", "MANIFESTATION_NO"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be MANIFESTATION_YES or MANIFESTATION_NO")
    if mdr["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "manifestation determination is not SCHEDULED")
    if clock() > mdr["due_at"]:
        raise_err(ERR_MDR_DEADLINE_PASSED, "manifestation determination is past due_at")

    mdr["status"] = "COMPLETED"
    mdr["outcome"] = outcome
    mdr["completed_at"] = clock()
    touch(mdr)

    # IDEA 10-day cap on the live proposal (PRD §3.6)
    if outcome == "MANIFESTATION_YES":
        case = db.cases[mdr["case_id"]]
        if case["status"] == "SANCTION_PROPOSED" and case["proposed_sanction_days"] is not None:
            student = db.students[case["student_id"]]
            cap = max(0, 10 - student["cumulative_suspension_days"])
            capped = min(case["proposed_sanction_days"], cap)
            if capped != case["proposed_sanction_days"]:
                case["proposed_sanction_days"] = capped
                touch(case)
    return success(serialize(mdr))
