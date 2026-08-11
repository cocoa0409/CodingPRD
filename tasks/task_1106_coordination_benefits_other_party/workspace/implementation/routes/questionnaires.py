"""MSP questionnaire endpoints."""

from flask import Blueprint, request

from db import stores, now_dt, parse_date
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_MSP_INCOMPLETE,
)
from helpers import (
    base_record, touch, get_or_404, body, req_str, opt_str, opt_int, opt_bool, req_enum, paginate,
)
from middleware import require_roles
from response import success
from services.calculations import msp_determination, active_config

bp = Blueprint("questionnaires", __name__)

RESPONDENT_ROLES = ("SELF", "SPOUSE", "AUTHORIZED_REP")


def _get_nested_q(mid, qid):
    get_or_404(stores["members"], mid, "member")
    q = stores["questionnaires"].get(qid)
    if q is None or q.get("member_id") != mid:
        raise_err(ERR_NOT_FOUND, "questionnaire does not exist or does not belong to member")
    return q


def _compute_age(dob_str, at_date):
    dob = parse_date(dob_str)
    age = at_date.year - dob.year - ((at_date.month, at_date.day) < (dob.month, dob.day))
    return age


@bp.route("/cob/members/<mid>/msp-questionnaires", methods=["POST"])
def submit_questionnaire(mid):
    require_roles("COBAnalyst", "EligibilityAnalyst", "MemberSelf")
    member = get_or_404(stores["members"], mid, "member")
    data = body()
    respondent = req_enum(data, "respondent_role", RESPONDENT_ROLES)
    has_group = opt_bool(data, "has_employer_group_health", False)
    employer_size = opt_int(data, "employer_size", None)
    disability = opt_bool(data, "disability_flag", False)
    esrd = opt_bool(data, "esrd_flag", False)
    esrd_onset = opt_str(data, "esrd_onset_date", None)

    age = _compute_age(member["date_of_birth"], now_dt().date())
    rec = base_record()
    rec.update({
        "member_id": mid,
        "respondent_role": respondent,
        "age_at_submission": age,
        "is_age_65_plus": age >= 65,
        "has_employer_group_health": bool(has_group),
        "employer_size": employer_size,
        "disability_flag": bool(disability),
        "esrd_flag": bool(esrd),
        "esrd_onset_date": esrd_onset,
        "msp_result": None,
        "status": "SUBMITTED",
    })
    stores["questionnaires"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/members/<mid>/msp-questionnaires", methods=["GET"])
def list_questionnaires(mid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "MemberSelf")
    get_or_404(stores["members"], mid, "member")
    items = [q for q in stores["questionnaires"].values() if q.get("member_id") == mid]
    status = request.args.get("status")
    if status:
        items = [q for q in items if q.get("status") == status]
    return paginate(items)


@bp.route("/cob/members/<mid>/msp-questionnaires/<qid>", methods=["GET"])
def get_questionnaire(mid, qid):
    require_roles("PlatformAdmin", "COBAnalyst", "EligibilityAnalyst", "MemberSelf")
    q = _get_nested_q(mid, qid)
    return success(q)


@bp.route("/cob/members/<mid>/msp-questionnaires/<qid>/adjudicate", methods=["POST"])
def adjudicate_questionnaire(mid, qid):
    require_roles("COBAnalyst")
    q = _get_nested_q(mid, qid)
    member = stores["members"][mid]
    if q.get("status") != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Questionnaire is not in SUBMITTED")
    if q.get("has_employer_group_health") and q.get("employer_size") is None:
        raise_err(ERR_MSP_INCOMPLETE, "employer_size missing when has_employer_group_health")
    if q.get("esrd_flag") and not q.get("esrd_onset_date"):
        raise_err(ERR_MSP_INCOMPLETE, "esrd_onset_date missing when esrd_flag")
    config = active_config()
    q["msp_result"] = msp_determination(q, config) if config else "MSP_EXEMPT"
    q["status"] = "ADJUDICATED"
    touch(q)
    touch(member)
    return success(q)


@bp.route("/cob/members/<mid>/msp-questionnaires/<qid>/void", methods=["POST"])
def void_questionnaire(mid, qid):
    require_roles("COBAnalyst")
    q = _get_nested_q(mid, qid)
    if q.get("status") != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Questionnaire is not in SUBMITTED")
    q["status"] = "VOIDED"
    touch(q)
    # Cascade: referencing FINALIZED determinations -> SUPERSEDED
    for det in stores["determinations"].values():
        if det.get("msp_questionnaire_id") == qid and det.get("status") == "FINALIZED":
            det["status"] = "SUPERSEDED"
            touch(det)
    return success(q)
