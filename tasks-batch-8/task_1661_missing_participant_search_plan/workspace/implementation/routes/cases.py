"""TerminationCase endpoints (PRD sections 3.1, 3.2, 3.7)."""

import db
import services
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_TERMINATION_DATE_NOT_REACHED,
    ERR_DISTRIBUTION_NOTICE_REQUIRED,
    ERR_BLACKOUT_TRANSITION_PENDING,
    ERR_PARTICIPANTS_NOT_ALL_RESOLVED,
    ERR_NO_REOPENABLE_PARTICIPANT,
    ERR_DLR_PENDING_BLOCKS_CLOSE,
    ERR_DLR_ADVERSE_BLOCKS_CLOSE,
    ERR_FIDUCIARY_DOC_MISSING,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj
from routes import make_blueprint
from services import public_case
from util import body_json, check_shape, check_no_fields, parse_dt, path_entity

bp = make_blueprint("cases")

CASE_STATUSES = [
    "DRAFT",
    "NOTICE_OF_INTENT_ISSUED",
    "TERMINATION_EFFECTIVE",
    "DISTRIBUTION_IN_PROGRESS",
    "FINAL_RECONCILIATION",
    "CLOSED",
]


def _get_case(case_id):
    return path_entity("cases", case_id, "termination case")


@bp.post("/termination-cases")
def create_case():
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "plan_name": {"type": "string", "required": True},
        "sponsor_ein": {"type": "digits", "length": 9, "required": True},
        "plan_number": {"type": "digits", "length": 3, "required": True},
        "proposed_termination_date": {"type": "datetime", "required": True},
        "restoration_policy": {
            "type": "enum", "values": {"NOMINAL", "EARNINGS_ADJUSTED"},
        },
    })
    case = db.new_entity("cases", {
        "plan_name": body["plan_name"],
        "sponsor_ein": body["sponsor_ein"],
        "plan_number": body["plan_number"],
        "proposed_termination_date": parse_dt(
            body["proposed_termination_date"], "proposed_termination_date"
        ),
        "restoration_policy": body.get("restoration_policy") or "NOMINAL",
        "status": "DRAFT",
        "_base_assets_cents": 0,
    })
    return success_obj(public_case(case), 201)


@bp.get("/termination-cases/<case_id>")
def get_case(case_id):
    authenticate(ALL_ROLES)
    return success_obj(public_case(_get_case(case_id)), 200)


@bp.post("/termination-cases/<case_id>/effectuate-termination")
def effectuate_termination(case_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    case = _get_case(case_id)
    if case["status"] != "NOTICE_OF_INTENT_ISSUED":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "effectuate-termination requires NOTICE_OF_INTENT_ISSUED",
        )
    if db.now() < case["proposed_termination_date"]:
        raise ApiError(
            ERR_TERMINATION_DATE_NOT_REACHED, 409,
            "the proposed termination date has not been reached",
        )
    # Fan-out: every participant forced to 100% vesting, version += 1 each.
    for p in services.case_participants(case["id"]):
        p["vested_pct"] = 100
        db.touch(p)
    # Ledger snapshot: sum of account_balance_cents over all participants.
    case["_base_assets_cents"] = sum(
        p["account_balance_cents"] for p in services.case_participants(case["id"])
    )
    case["status"] = "TERMINATION_EFFECTIVE"
    db.touch(case)
    return success_obj(public_case(case), 200)


@bp.post("/termination-cases/<case_id>/begin-distributions")
def begin_distributions(case_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    case = _get_case(case_id)
    if case["status"] != "TERMINATION_EFFECTIVE":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "begin-distributions requires TERMINATION_EFFECTIVE",
        )
    if services.live_notice(case["id"], "DISTRIBUTION") is None:
        raise ApiError(
            ERR_DISTRIBUTION_NOTICE_REQUIRED, 422,
            "a non-superseded DISTRIBUTION notice is required",
        )
    if any(
        b["status"] in ("SCHEDULED", "ACTIVE")
        for b in services.case_blackouts(case["id"])
    ):
        raise ApiError(
            ERR_BLACKOUT_TRANSITION_PENDING, 409,
            "a blackout period is SCHEDULED or ACTIVE",
        )
    case["status"] = "DISTRIBUTION_IN_PROGRESS"
    db.touch(case)
    return success_obj(public_case(case), 200)


@bp.post("/termination-cases/<case_id>/advance-to-reconciliation")
def advance_to_reconciliation(case_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    case = _get_case(case_id)
    if case["status"] != "DISTRIBUTION_IN_PROGRESS":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "advance-to-reconciliation requires DISTRIBUTION_IN_PROGRESS",
        )
    if not public_case(case)["all_participants_resolved"]:
        raise ApiError(
            ERR_PARTICIPANTS_NOT_ALL_RESOLVED, 409,
            "not all participants are resolved",
        )
    case["status"] = "FINAL_RECONCILIATION"
    db.touch(case)
    return success_obj(public_case(case), 200)


@bp.post("/termination-cases/<case_id>/reopen-distributions")
def reopen_distributions(case_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    case = _get_case(case_id)
    if case["status"] != "FINAL_RECONCILIATION":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "reopen-distributions requires FINAL_RECONCILIATION",
        )
    if not any(
        p["distribution_status"] == "RESTORED"
        for p in services.case_participants(case["id"])
    ):
        raise ApiError(
            ERR_NO_REOPENABLE_PARTICIPANT, 409,
            "no participant is in RESTORED",
        )
    case["status"] = "DISTRIBUTION_IN_PROGRESS"
    db.touch(case)
    return success_obj(public_case(case), 200)


@bp.post("/termination-cases/<case_id>/close")
def close_case(case_id):
    authenticate(["IndependentFiduciary"])
    body = body_json()
    check_no_fields(body)
    case = _get_case(case_id)
    # Gates evaluated as a conjunction in the PRD section 3.7 order.
    if case["status"] != "FINAL_RECONCILIATION":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "close requires FINAL_RECONCILIATION",
        )
    if not public_case(case)["all_participants_resolved"]:
        raise ApiError(
            ERR_PARTICIPANTS_NOT_ALL_RESOLVED, 409,
            "not all participants are resolved",
        )
    dlrs = [
        d for d in db.all_of("dlrs") if d["termination_case_id"] == case["id"]
    ]
    if any(d["status"] in ("DRAFT", "FILED") for d in dlrs):
        raise ApiError(
            ERR_DLR_PENDING_BLOCKS_CLOSE, 409,
            "a determination letter request is DRAFT or FILED",
        )
    if any(d["status"] == "ADVERSE" for d in dlrs):
        raise ApiError(
            ERR_DLR_ADVERSE_BLOCKS_CLOSE, 409,
            "an ADVERSE determination letter request must be withdrawn first",
        )
    if any(
        b["status"] in ("SCHEDULED", "ACTIVE")
        for b in services.case_blackouts(case["id"])
    ):
        raise ApiError(
            ERR_BLACKOUT_TRANSITION_PENDING, 409,
            "a blackout period is SCHEDULED or ACTIVE",
        )
    if not any(
        e["termination_case_id"] == case["id"]
        and e["entry_type"] == "CLOSURE_SIGNOFF"
        for e in db.all_of("logs")
    ):
        raise ApiError(
            ERR_FIDUCIARY_DOC_MISSING, 422,
            "a CLOSURE_SIGNOFF fiduciary log entry is required",
        )
    case["status"] = "CLOSED"
    db.touch(case)
    return success_obj(public_case(case), 200)
