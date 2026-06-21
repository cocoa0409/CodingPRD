"""EligibilityDetermination endpoints (PRD 3.9)."""
from flask import Blueprint, request

from common import (as_str, get_body, init_common, parse_pagination, require,
                    sort_by_creation, touch)
from db import db
from errors import (ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD, ERR_INVALID_STATE,
                    raise_error)
from lookups import get_eligibility, get_enrollment, get_member, get_plan, get_program
from middleware import require_roles
from response import paginated, success
from serializers import serialize
import calculations as calc

bp = Blueprint("eligibility", __name__)

ALL_READ = ("ProgramAdmin", "Clinician", "BillingAgent", "Member")


def _approved_intake_for_member(member_id):
    approved = [a for a in db.intake_assessments.values()
                if a["member_id"] == member_id and a["status"] == "APPROVED"]
    approved.sort(key=lambda a: a["_seq"])
    return approved[-1] if approved else None


@bp.route("/wm/eligibility-determinations", methods=["POST"])
@require_roles("ProgramAdmin", "Clinician")
def create_determination():
    body = get_body()
    member_id = as_str(require(body, "member_id"), "member_id")
    enrollment_id = as_str(require(body, "enrollment_id"), "enrollment_id")

    member = get_member(member_id)
    enrollment = get_enrollment(enrollment_id)
    plan = get_plan(enrollment["plan_id"])

    # composite score from member's APPROVED intake (bmi, comorbidity) + plan tier
    intake = _approved_intake_for_member(member_id)
    bmi = intake["bmi"] if intake else 0
    comorbidity = intake["comorbidity_count"] if intake else 0
    composite = calc.compute_eligibility_composite_score(bmi, comorbidity, plan["tier"])

    determination = {
        "member_id": member_id,
        "program_id": member["program_id"],
        "enrollment_id": enrollment_id,
        "composite_score": composite,
        "hsa_fsa_eligible": False,
        "determined_utc": None,
        "status": "PENDING",
    }
    init_common(determination)
    db.eligibility_determinations[determination["id"]] = determination
    return success(serialize(determination), 201)


@bp.route("/wm/eligibility-determinations", methods=["GET"])
@require_roles(*ALL_READ)
def list_determinations():
    limit, offset = parse_pagination()
    items = list(db.eligibility_determinations.values())
    member_id = request.args.get("member_id")
    program_id = request.args.get("program_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [d for d in items if d["member_id"] == member_id]
    if program_id is not None:
        items = [d for d in items if d["program_id"] == program_id]
    if enrollment_id is not None:
        items = [d for d in items if d["enrollment_id"] == enrollment_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(d) for d in page], limit, offset, total)


@bp.route("/wm/eligibility-determinations/<determination_id>", methods=["GET"])
@require_roles(*ALL_READ)
def get_one_determination(determination_id):
    return success(serialize(get_eligibility(determination_id)), 200)


@bp.route("/wm/eligibility-determinations/<determination_id>/approve", methods=["POST"])
@require_roles("Clinician")
def approve_determination(determination_id):
    determination = get_eligibility(determination_id)
    if determination["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "Approve allowed only from PENDING")
    if determination["composite_score"] < float(calc.ELIGIBILITY_THRESHOLD):
        raise_error(ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD,
                    "composite_score below threshold")
    program = get_program(determination["program_id"])
    determination["status"] = "APPROVED"
    determination["hsa_fsa_eligible"] = True
    determination["determined_utc"] = program["current_utc"]
    touch(determination)
    # Invoice hsa_fsa_eligible_cents is derived live at invoice read time
    # (see routes/invoices._view); no retroactive invoice patching needed.
    return success(serialize(determination), 200)


@bp.route("/wm/eligibility-determinations/<determination_id>/deny", methods=["POST"])
@require_roles("Clinician")
def deny_determination(determination_id):
    determination = get_eligibility(determination_id)
    if determination["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "Deny allowed only from PENDING")
    program = get_program(determination["program_id"])
    determination["status"] = "DENIED"
    determination["hsa_fsa_eligible"] = False
    determination["determined_utc"] = program["current_utc"]
    touch(determination)
    return success(serialize(determination), 200)
