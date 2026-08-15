from flask import Blueprint, request

import errors as E
import response
from db import store, new_record, touch, serialize
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response, opt_int
from services.domain import (
    compute_score_and_tier,
    create_auto_grants_for_imminent,
    latest_scoring,
)

bp = Blueprint("scorings", __name__)

DIMENSIONS = ("harm_to_self", "harm_to_others", "academic_disruption", "substance_involvement")


@bp.post("/bit/risk-scorings")
def create_scoring():
    uid, _ = require_auth(["BITChair"])
    b = body()
    case_id = b.get("case_id")
    case = None
    if isinstance(case_id, str):
        case = store.cases.get(case_id)
        if case is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"care case not found: {case_id}")

    # Rank 5: state — scoring requires the case in INTAKE or TRIAGED.
    if case is not None and case["status"] not in ("INTAKE", "TRIAGED"):
        raise ApiError(
            E.ERR_CASE_NOT_TRIAGEABLE, 409, "scoring requires case INTAKE or TRIAGED"
        )

    # Rank 9 (listed order): rubric range, then mode-history consistency,
    # then enum/required-field validity.
    dims = {}
    for name in DIMENSIONS:
        raw = b.get(name)
        if raw is None:
            dims[name] = None
            continue
        value = opt_int(raw)
        if value is None or value < 0 or value > 25:
            raise ApiError(
                E.ERR_RUBRIC_SCORE_OUT_OF_RANGE,
                400,
                f"{name} must be an integer in 0..25",
            )
        dims[name] = value

    mode = b.get("mode")
    if mode in ("INITIAL", "REASSESSMENT") and case is not None:
        prior = latest_scoring(case["id"])
        if mode == "INITIAL" and prior is not None:
            raise ApiError(
                E.ERR_SCORING_MODE_INVALID,
                400,
                "INITIAL is valid only when no prior scoring exists for the case",
            )
        if mode == "REASSESSMENT" and prior is None:
            raise ApiError(
                E.ERR_SCORING_MODE_INVALID,
                400,
                "REASSESSMENT requires a prior scoring for the case",
            )

    if case is None:
        raise ApiError(E.ERR_VALIDATION, 400, "case_id is required")
    if mode not in ("INITIAL", "REASSESSMENT"):
        raise ApiError(E.ERR_VALIDATION, 400, "mode must be INITIAL or REASSESSMENT")
    if any(dims[n] is None for n in DIMENSIONS):
        raise ApiError(E.ERR_VALIDATION, 400, "all four rubric dimensions are required")
    rationale = b.get("rationale")
    if not isinstance(rationale, str) or not rationale:
        raise ApiError(E.ERR_VALIDATION, 400, "rationale is required")

    previous_tier = case["current_risk_tier"]
    score, tier = compute_score_and_tier(
        case, mode, dims["harm_to_self"], dims["harm_to_others"],
        dims["academic_disruption"], dims["substance_involvement"],
    )

    rec = new_record()
    rec.update(
        {
            "case_id": case["id"],
            "scored_by": uid,
            "mode": mode,
            "harm_to_self": dims["harm_to_self"],
            "harm_to_others": dims["harm_to_others"],
            "academic_disruption": dims["academic_disruption"],
            "substance_involvement": dims["substance_involvement"],
            "rationale": rationale,
            "score": score,
            "tier": tier,
        }
    )
    store.scorings[rec["id"]] = rec

    case["current_risk_score"] = score
    case["current_risk_tier"] = tier
    if case["status"] == "INTAKE":
        case["status"] = "TRIAGED"
    touch(case)

    # IMMINENT safety exception fires on the crossing, not on the continuation.
    if tier == "IMMINENT" and previous_tier != "IMMINENT":
        create_auto_grants_for_imminent(case)

    return response.obj(serialize(rec), 201)


@bp.get("/bit/risk-scorings/<sid>")
def get_scoring(sid):
    require_auth(["BITChair", "CaseManager", "DeanOfStudents", "PrivacyOfficer"])
    rec = get_or_404(store.scorings, sid, "risk scoring")
    return response.obj(serialize(rec))


@bp.get("/bit/risk-scorings")
def list_scorings():
    require_auth(["BITChair", "CaseManager", "DeanOfStudents", "PrivacyOfficer"])
    q = request.args
    return list_response(
        store.scorings,
        [("case_id", q.get("case_id")), ("scored_by", q.get("scored_by"))],
    )
