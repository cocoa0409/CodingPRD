from datetime import timedelta

from flask import Blueprint, g

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, is_int, paginate, require_enum, require_fields

bp = Blueprint("cases", __name__)

MEC = "MedicalExecutiveCommitteeChair"
CHIEF = "DepartmentChief"
PRACT = "Practitioner"
OFFICER = "HearingOfficer"

CASE_KINDS = ("SUSPENSION", "REVOCATION", "DENIAL_OF_REAPPOINTMENT",
              "RESTRICTION")
SEATABLE_STATES = ("MEC_ENDORSED", "HEARING_REQUESTED", "REMANDED",
                   "HEARING_HELD")


def _get_case(cid):
    rec = db.cases.get(cid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "AdverseActionCase not found")
    return rec


@bp.route("/mso/adverse-action-cases", methods=["POST"])
@require_roles(CHIEF)
def create_case():
    body = get_body()
    # Rung 3: existence.
    subject_id = body.get("subject_member_id")
    if subject_id is not None and subject_id not in db.members:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    proposer_id = body.get("proposed_by_member_id")
    if proposer_id is not None and proposer_id not in db.members:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    review_id = body.get("linked_review_id")
    if review_id is not None and review_id not in db.reviews:
        errors.raise_err(errors.ERR_NOT_FOUND, "PerformanceReview not found")
    # Rung 11: input shape.
    require_fields(body, ["subject_member_id", "proposed_by_member_id",
                          "case_kind"])
    require_enum(body, "case_kind", CASE_KINDS)
    restriction_days = body.get("restriction_days", 0)
    if not is_int(restriction_days) or restriction_days < 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "restriction_days must be a non-negative integer")
    rec = services.create_case(
        subject_member_id=subject_id,
        proposed_by_member_id=proposer_id,
        case_kind=body["case_kind"],
        restriction_days=restriction_days,
        linked_review_id=review_id,
    )
    return ok_object(serializers.case(rec), 201)


@bp.route("/mso/adverse-action-cases", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cases():
    items, limit, offset, total = paginate(
        db.cases.values(), serializers.case,
        ["subject_member_id", "case_status", "proposed_by_member_id",
         "linked_review_id"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/adverse-action-cases/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_case(cid):
    return ok_object(serializers.case(_get_case(cid)))


@bp.route("/mso/adverse-action-cases/<cid>/endorse", methods=["POST"])
@require_roles(MEC)
def endorse_case(cid):
    get_body()
    case = _get_case(cid)
    if case["case_status"] != "PROPOSED":
        errors.raise_err(errors.ERR_CASE_NOT_PROPOSED,
                         "Case is not in PROPOSED")
    subject = db.members.get(case["subject_member_id"])
    if subject is None or subject["membership_status"] != "ACTIVE":
        errors.raise_err(errors.ERR_MEMBER_NOT_ACTIVE,
                         "Subject member is not ACTIVE")
    case["case_status"] = "MEC_ENDORSED"
    services.touch(case)
    return ok_object(serializers.case(case))


@bp.route("/mso/adverse-action-cases/<cid>/withdraw", methods=["POST"])
@require_roles(CHIEF)
def withdraw_case(cid):
    get_body()
    case = _get_case(cid)
    if case["case_status"] not in ("PROPOSED", "MEC_ENDORSED"):
        errors.raise_err(errors.ERR_CASE_NOT_WITHDRAWABLE,
                         "Case cannot be withdrawn from its state")
    # SoD: only the proposing chief may withdraw (X-User-ID is the acting
    # member id for DepartmentChief).
    if case["proposed_by_member_id"] != g.user_id:
        errors.raise_err(errors.ERR_NOT_CASE_PROPOSER,
                         "Only the proposing DepartmentChief may withdraw")
    case["case_status"] = "WITHDRAWN"
    services.touch(case)
    return ok_object(serializers.case(case))


@bp.route("/mso/adverse-action-cases/<cid>/request-hearing", methods=["POST"])
@require_roles(PRACT)
def request_hearing(cid):
    get_body()
    case = _get_case(cid)
    if case["case_status"] not in ("MEC_ENDORSED", "REMANDED"):
        errors.raise_err(errors.ERR_CASE_NOT_ENDORSED,
                         "Case is not in MEC_ENDORSED or REMANDED")
    # SoD: only the subject may request the hearing.
    if case["subject_member_id"] != g.user_id:
        errors.raise_err(errors.ERR_NOT_CASE_SUBJECT,
                         "Only the case subject may request a hearing")
    from util import parse_dt
    if db.clock_now() > parse_dt(case["hearing_request_deadline"]):
        errors.raise_err(errors.ERR_HEARING_REQUEST_LATE,
                         "The hearing_request_deadline has passed")
    now_iso = services.now_iso()
    case["hearing_requested_at"] = now_iso
    case["case_status"] = "HEARING_REQUESTED"
    services.touch(case)
    # SoD cascade: subject and proposer are excluded from panel duty; any
    # already-seated panelist acquiring the tag is disqualified.
    tagged = []
    for mid in (case["subject_member_id"], case.get("proposed_by_member_id")):
        member = db.members.get(mid) if mid else None
        if member is None:
            continue
        tags = member.setdefault("sod_exclusion_tags", [])
        if case["id"] not in tags:
            tags.append(case["id"])
            services.touch(member)
        tagged.append(mid)
    for p in db.panels.values():
        if (p["case_id"] == case["id"] and p["panel_status"] == "SEATED"
                and p["panel_member_id"] in tagged):
            p["panel_status"] = "DISQUALIFIED"
            services.touch(p)
    return ok_object(serializers.case(case))


@bp.route("/mso/adverse-action-cases/<cid>/hold-hearing", methods=["POST"])
@require_roles(OFFICER)
def hold_hearing(cid):
    get_body()
    case = _get_case(cid)
    if case["case_status"] != "HEARING_REQUESTED":
        errors.raise_err(errors.ERR_CASE_NOT_IN_HEARING,
                         "Case is not in HEARING_REQUESTED")
    required = services.quorum_required_for_case(cid)
    if services.eligible_panel_count(cid) < required:
        errors.raise_err(errors.ERR_HEARING_QUORUM_UNMET,
                         "Seated eligible panel does not meet quorum "
                         f"({required} required)")
    case["case_status"] = "HEARING_HELD"
    services.touch(case)
    return ok_object(serializers.case(case))


@bp.route("/mso/adverse-action-cases/<cid>/decide", methods=["POST"])
@require_roles(OFFICER)
def decide_case(cid):
    body = get_body()
    case = _get_case(cid)
    if case["case_status"] != "HEARING_HELD":
        errors.raise_err(errors.ERR_CASE_NOT_HEARD,
                         "Case is not in HEARING_HELD")
    decision = body.get("decision")
    if decision not in ("UPHELD", "OVERTURNED", "REMAND"):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "decision must be UPHELD, OVERTURNED, or REMAND")
    if decision == "UPHELD":
        services.apply_final_adverse(case)
    elif decision == "OVERTURNED":
        case["case_status"] = "FINAL_NO_ACTION"
        services.touch(case)
    else:  # REMAND
        case["case_status"] = "REMANDED"
        case["hearing_request_deadline"] = services.fmt_dt(
            db.clock_now()
            + timedelta(days=services.HEARING_REQUEST_WINDOW_DAYS))
        services.touch(case)
    return ok_object(serializers.case(case))
