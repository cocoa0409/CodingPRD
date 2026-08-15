"""AppealCase endpoints: file, list, decision (with full overturn cascade)."""
from flask import Blueprint

import db
from db import now_iso
from errors import (
    ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE, ERR_DENIAL_NOT_FINAL,
    ERR_APPEAL_DEADLINE_PASSED, ERR_APPEAL_ALREADY_FILED,
    ERR_VALIDATION_FAILED, ERR_BED_DAY_BUDGET_EXCEEDED,
)
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.case_service import (
    recompute_certified_counts, case_frontier_end,
    recompute_attribution, recompute_open_counts_and_escalation,
    refresh_escalation_effective,
)
from services.clock import logical_now, parse_iso
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_int, validate_string,
)

bp = Blueprint("appeals", __name__)

FILE_FIELDS = ["appeal_level", "argument_summary"]
DECISION_FIELDS = ["decision", "overturned_day_count"]


def _denied_window_start(denial):
    """The denied window starts at the denial decision's calendar date."""
    return parse_iso(denial["denied_at"]).strftime("%Y-%m-%d")


def _overturn_cascade(denial, granted_days, role, user_id):
    """Shared restoration cascade for appeal OVERTURNED/PARTIAL."""
    case = db.utilization_cases[denial["case_id"]]
    ar = db.authorization_requests[denial["authorization_request_id"]]
    payer = db.payers[case["payer_id"]]

    # Budget check on the restored grant
    if case["certified_day_count"] + granted_days > payer["bed_day_budget_per_case"]:
        raise ApiError(ERR_BED_DAY_BUDGET_EXCEEDED,
                       "Restored certified days would exceed payer bed_day_budget_per_case", 422)

    # Restore linked auth DENIED -> APPROVED with interval appended at case frontier
    frontier = case_frontier_end(case["id"])
    ar["status"] = "APPROVED"
    ar["certified_day_start"] = frontier
    ar["certified_day_end"] = frontier + granted_days
    touch(ar)

    # Overturn avoidable days: OPEN records with day_date on/after the denied
    # window start, ordered day_date ASC then created_at ASC. Full overturn takes
    # them all; partial takes the earliest `granted_days`.
    window_start = _denied_window_start(denial)
    candidates = sorted(
        (a for a in db.avoidable_days.values()
         if a["case_id"] == case["id"] and a["status"] == "OPEN"
         and a["day_date"] >= window_start),
        key=lambda a: (a["day_date"], a["created_at"]),
    )
    # The count selected depends on the caller (all vs granted_days)
    return case, ar, candidates


@bp.post("/api/denial-cases/<did>/appeals")
def file_appeal(did):
    user_id, role = require_roles(["AppealsCoordinator"])
    body = get_json_body()
    reject_unknown_fields(body, FILE_FIELDS)
    validate_int(body, "appeal_level", min_val=1, max_val=2)
    validate_string(body, "argument_summary")

    denial = lookup(db.denial_cases, did, "DenialCase")
    # NOTE: lazy CLOSED_NO_APPEAL materialization is scoped by PRD §3.8 to
    # "list and single-resource reads" — appeal filing is a write, so the
    # denial is NOT materialized here. The deadline gate below must evaluate
    # the still-OPEN denial directly so a late filing surfaces
    # ERR_APPEAL_DEADLINE_PASSED rather than a finality error.
    case = db.utilization_cases[denial["case_id"]]

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)

    # Priority 23: at most one AppealCase per DenialCase — covers APPEAL_FILED
    # and RESOLVED_* postures (any existing appeal blocks a new filing).
    existing = next(
        (a for a in db.appeal_cases.values() if a["denial_id"] == did), None,
    )

    # Priority 11: denial must be OPEN and no linked conference SCHEDULED
    conf_open = any(
        c["authorization_request_id"] == denial["authorization_request_id"]
        and c["status"] == "SCHEDULED"
        for c in db.peer_to_peer_conferences.values()
    )
    if denial["status"] == "P2P_SCHEDULED" or conf_open:
        raise ApiError(ERR_DENIAL_NOT_FINAL,
                       "Denial is not final: a peer-to-peer conference is still scheduled", 409)
    if denial["status"] != "OPEN":
        # If an appeal already exists, the more specific error applies
        if existing is not None:
            raise ApiError(ERR_APPEAL_ALREADY_FILED,
                           "An AppealCase already exists for this DenialCase", 409)
        raise ApiError(ERR_DENIAL_NOT_FINAL,
                       f"Denial is {denial['status']}, not OPEN", 409)
    if existing is not None:
        raise ApiError(ERR_APPEAL_ALREADY_FILED,
                       "An AppealCase already exists for this DenialCase", 409)

    # Priority 17: appeal deadline (equality allowed)
    if logical_now() > parse_iso(denial["appeal_deadline_at"]):
        raise ApiError(ERR_APPEAL_DEADLINE_PASSED,
                       "Appeal filed after appeal_deadline_at", 422)

    appeal = {
        **init_common(),
        "denial_id": did,
        "appeal_level": body["appeal_level"],
        "argument_summary": body["argument_summary"],
        "filed_at": now_iso(),
        "status": "FILED",
        "decided_at": None,
        "overturned_day_count": None,
    }
    db.appeal_cases[appeal["id"]] = appeal

    denial["status"] = "APPEAL_FILED"
    touch(denial)
    append_audit(case["id"], "APPEAL_FILED", role, user_id,
                 f"Appeal {appeal['id']} filed on denial {did} (level {body['appeal_level']})")
    return success_object(appeal, 201)


@bp.get("/api/denial-cases/<did>/appeals")
def list_appeals(did):
    any_authenticated()
    lookup(db.denial_cases, did, "DenialCase")
    items = sorted(
        (a for a in db.appeal_cases.values() if a["denial_id"] == did),
        key=lambda a: a["created_at"],
    )
    return paginate(items)


@bp.post("/api/appeals/<aid>/decision")
def decide_appeal(aid):
    user_id, role = require_roles(["PayerReviewer"])
    body = get_json_body()
    reject_unknown_fields(body, DECISION_FIELDS)
    validate_enum(body, "decision", {"UPHELD", "OVERTURNED", "PARTIAL"})
    decision = body["decision"]

    appeal = lookup(db.appeal_cases, aid, "AppealCase")
    denial = db.denial_cases[appeal["denial_id"]]
    case = db.utilization_cases[denial["case_id"]]

    if decision == "PARTIAL":
        validate_int(body, "overturned_day_count", min_val=1)
        if body["overturned_day_count"] >= denial["denied_day_count"]:
            raise ApiError(ERR_VALIDATION_FAILED,
                           "overturned_day_count must be strictly less than denied_day_count", 400)

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if appeal["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, f"Appeal is {appeal['status']}, not FILED", 409)

    appeal["decided_at"] = now_iso()

    if decision == "UPHELD":
        appeal["status"] = "DECIDED_UPHELD"
        appeal["overturned_day_count"] = 0
        touch(appeal)
        denial["status"] = "RESOLVED_UPHELD"
        touch(denial)
        append_audit(case["id"], "APPEAL_DECIDED", role, user_id,
                     f"Appeal {aid} decided UPHELD; denial {denial['id']} resolved UPHELD")
        return success_object(appeal, 200)

    if decision == "OVERTURNED":
        granted = denial["denied_day_count"]
        case_, ar, candidates = _overturn_cascade(denial, granted, role, user_id)
        selected = candidates  # all OPEN days in the denied window
        appeal["status"] = "DECIDED_OVERTURNED"
        appeal["overturned_day_count"] = granted
        denial["status"] = "RESOLVED_OVERTURNED"
    else:  # PARTIAL
        granted = body["overturned_day_count"]
        case_, ar, candidates = _overturn_cascade(denial, granted, role, user_id)
        selected = candidates[:granted]  # earliest that-many
        appeal["status"] = "DECIDED_PARTIAL"
        appeal["overturned_day_count"] = granted
        denial["status"] = "RESOLVED_PARTIAL"

    touch(appeal)
    touch(denial)

    # Overturn the selected avoidable days
    overturned_dates = set()
    for rec in selected:
        rec["status"] = "OVERTURNED"
        touch(rec)
        overturned_dates.add(rec["day_date"])
        append_audit(case["id"], "AVOIDABLE_DAY_OVERTURNED", role, user_id,
                     f"Avoidable day {rec['id']} overturned via appeal {aid}")
    for d in overturned_dates:
        recompute_attribution(case, d)

    case["auth_status"] = "AUTHORIZED"
    recompute_certified_counts(case)
    recompute_open_counts_and_escalation(case)
    refresh_escalation_effective(case)
    touch(case)
    append_audit(case["id"], "APPEAL_DECIDED", role, user_id,
                 f"Appeal {aid} decided {decision}; {granted} day(s) restored")
    return success_object(appeal, 200)
