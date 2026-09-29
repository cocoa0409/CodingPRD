"""The classification roster, community-of-interest scoring, rulings and reconsideration."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("classifications", __name__)

BASE = "/labor-relations/classifications"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.DIRECTOR, auth.ANALYST])
def create_classification(user_id, role):
    schema = validate.Schema(validate.body())
    petition_id = schema.reference("petition_id")
    code = schema.string("code")
    title = schema.string("title")
    headcount = schema.integer("headcount", minimum=1)
    avg_hourly_wage_cents = schema.integer("avg_hourly_wage_cents", minimum=1)
    shift_code = schema.string("shift_code")
    work_location = schema.string("work_location")
    supervisory_authority_count = schema.integer(
        "supervisory_authority_count", required=False, default=0, minimum=0)
    employer_position = schema.enum("employer_position", common.POSITIONS)
    union_position = schema.enum("union_position", common.POSITIONS)
    supervision_overlap = schema.integer("supervision_overlap", minimum=0, maximum=100)
    skills_overlap = schema.integer("skills_overlap", minimum=0, maximum=100)
    functional_integration = schema.integer("functional_integration", minimum=0, maximum=100)
    interchange_rate = schema.integer("interchange_rate", minimum=0, maximum=100)
    work_conditions_overlap = schema.integer("work_conditions_overlap", minimum=0, maximum=100)

    petition = gates.must_exist("petitions", petition_id)

    for existing in store.classifications_of(petition_id):
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_CLASSIFICATION_CODE",
                           "That classification code is already used on this case.")

    row = store.insert("classifications", {
        "petition_id": petition_id,
        "code": code,
        "title": title,
        "headcount": headcount,
        "avg_hourly_wage_cents": avg_hourly_wage_cents,
        "shift_code": shift_code,
        "work_location": work_location,
        "supervisory_authority_count": supervisory_authority_count,
        "employer_position": employer_position,
        "union_position": union_position,
        "supervision_overlap": supervision_overlap,
        "skills_overlap": skills_overlap,
        "functional_integration": functional_integration,
        "interchange_rate": interchange_rate,
        "work_conditions_overlap": work_conditions_overlap,
        "wage_proximity": None,
        "coi_score": None,
        "scoring_standard": None,
        "coi_recommendation": None,
        "scope_ruling": "PENDING",
        "ruling_rationale": None,
    })
    petition["total_classified_headcount"] += headcount
    petition["pending_headcount"] += headcount
    gates.check_headcount_conservation(petition)
    store.touch(petition)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_classifications(user_id, role):
    petition_id = validate.query_string("petition_id")
    scope_ruling = validate.query_enum("scope_ruling", common.SCOPE_RULINGS)
    rows = store.ordered("classifications")
    if petition_id is not None:
        rows = [r for r in rows if r["petition_id"] == petition_id]
    if scope_ruling is not None:
        rows = [r for r in rows if r["scope_ruling"] == scope_ruling]
    return common.list_response(rows)


@bp.route(BASE + "/<cid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_classification(user_id, role, cid):
    return common.one(gates.must_exist("classifications", cid))


@bp.route(BASE + "/<cid>/score", methods=["POST"])
@auth.endpoint([auth.DIRECTOR, auth.COUNSEL])
def score_classification(user_id, role, cid):
    schema = validate.Schema(validate.body())
    standard = schema.enum("scoring_standard", common.SCORING_STANDARDS)
    classification = gates.must_exist("classifications", cid)
    petition = store.petition(classification["petition_id"])

    if petition["core_avg_hourly_wage_cents"] is None:
        core = calc.core_avg_hourly_wage_cents(store.classifications_of(petition["id"]))
        if core is None:
            raise ApiError("ERR_NO_UNDISPUTED_CORE",
                           "No classification on the case has both positions set to INCLUDE.")
        petition["core_avg_hourly_wage_cents"] = core
        petition["core_wage_locked_at"] = clockutil.now_dt_str()
        store.touch(petition)

    core_wage = petition["core_avg_hourly_wage_cents"]
    proximity = calc.wage_proximity(classification["avg_hourly_wage_cents"], core_wage)
    score = calc.coi_score(classification, proximity, standard)
    classification["wage_proximity"] = calc.as_number(proximity)
    classification["coi_score"] = calc.as_number(score)
    classification["scoring_standard"] = standard
    classification["coi_recommendation"] = calc.coi_recommendation(
        score, standard, classification["supervisory_authority_count"])
    store.touch(classification)
    return common.one(classification)


@bp.route(BASE + "/<cid>/rule", methods=["POST"])
@auth.endpoint([auth.BOARD])
def rule_classification(user_id, role, cid):
    schema = validate.Schema(validate.body())
    ruling = schema.enum("ruling", ("INCLUDED", "EXCLUDED"))
    ruling_rationale = schema.string("ruling_rationale")
    classification = gates.must_exist("classifications", cid)
    petition = store.petition(classification["petition_id"])

    if classification["scope_ruling"] != "PENDING":
        raise ApiError("ERR_CLASSIFICATION_ALREADY_RULED",
                       "The classification is no longer PENDING.")
    if petition["case_status"] not in ("SCOPE_ANALYSIS", "SOI_VERIFIED"):
        raise ApiError("ERR_PETITION_STATUS_INVALID",
                       "Rulings are only available while the case is in scope analysis.")
    if classification["coi_score"] is None:
        raise ApiError("ERR_CLASSIFICATION_NOT_SCORED",
                       "The classification must be scored before it may be ruled.")

    headcount = classification["headcount"]
    petition["pending_headcount"] -= headcount
    if ruling == "INCLUDED":
        petition["included_headcount"] += headcount
    else:
        petition["excluded_headcount"] += headcount
    gates.check_headcount_conservation(petition)
    classification["scope_ruling"] = ruling
    classification["ruling_rationale"] = ruling_rationale
    store.touch(classification)
    store.touch(petition)
    return common.one(classification)


@bp.route(BASE + "/<cid>/reconsider", methods=["POST"])
@auth.endpoint([auth.BOARD])
def reconsider_classification(user_id, role, cid):
    schema = validate.Schema(validate.body())
    schema.string("reconsideration_note", required=False)
    classification = gates.must_exist("classifications", cid)
    petition = store.petition(classification["petition_id"])

    if classification["scope_ruling"] not in ("INCLUDED", "EXCLUDED"):
        raise ApiError("ERR_CLASSIFICATION_ALREADY_RULED",
                       "Only a ruled classification may be reconsidered.")
    if petition["case_status"] not in ("SCOPE_ANALYSIS", "SOI_VERIFIED"):
        raise ApiError("ERR_PETITION_STATUS_INVALID",
                       "Reconsideration is only available while the case is in scope analysis.")
    gates.check_headcount_conservation(petition)

    headcount = classification["headcount"]
    if classification["scope_ruling"] == "INCLUDED":
        petition["included_headcount"] -= headcount
    else:
        petition["excluded_headcount"] -= headcount
    petition["pending_headcount"] += headcount
    gates.check_headcount_conservation(petition)
    classification["scope_ruling"] = "PENDING"
    classification["ruling_rationale"] = None
    store.touch(classification)
    store.touch(petition)
    return common.one(classification)
