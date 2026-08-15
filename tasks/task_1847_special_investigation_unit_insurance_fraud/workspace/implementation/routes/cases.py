"""SIU case endpoints (PRD §3.3, §3.6): open, submit-for-decision, close."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import (
    CASE_NON_TERMINAL,
    CLOSED_REASONS,
    DECISION_WINDOW_DAYS,
    EUO_SCORE_THRESHOLD,
    INVESTIGATION_WINDOW_DAYS,
)
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_case
from services import cascade
from services.scoring import days_from_now, has_admitted_evidence
from util import (
    apply_filters,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_enum,
    sort_created,
)

bp = Blueprint("cases", __name__)


def _case_visible_state_filter(items: list) -> list:
    """The state_code list filter joins through the parent claim."""
    from flask import request

    value = request.args.get("state_code")
    if value is None or value == "":
        return items
    out = []
    for case in items:
        claim = db.claims.get(case.get("claim_id")) or {}
        if claim.get("state_code") == value:
            out.append(case)
    return out


@bp.get("/siu/cases/<caseId>")
@require_roles("All")
def get_case(caseId: str, _user_id: str, _role: str):
    case = path_or_404(db.cases, caseId, "SIUCase")
    return success_object(pub_case(case))


@bp.get("/siu/cases")
@require_roles("All")
def list_cases(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(
        list(db.cases.values()),
        ["status", "assigned_investigator_id", "priority", "claim_id", "opened_by_referral_id"],
    )
    items = _case_visible_state_filter(items)
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_case(c) for c in page], limit, offset, total)


@bp.post("/siu/cases/<caseId>/open")
@require_roles("SIUManager")
def open_case(caseId: str, _user_id: str, _role: str):
    get_json_body()
    case = path_or_404(db.cases, caseId, "SIUCase")
    if case.get("status") != "INTAKE":
        raise_err(ERR_INVALID_STATE, "Case must be INTAKE to be opened")
    referral = db.referrals.get(case.get("opened_by_referral_id"))
    if referral is None or referral.get("status") != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "Originating referral is not ACCEPTED")
    for other in db.cases.values():
        if (
            other["id"] != case["id"]
            and other.get("claim_id") == case.get("claim_id")
            and other.get("status") in CASE_NON_TERMINAL
        ):
            raise_err(ERR_INVALID_STATE, "Another non-terminal case exists for this claim")
    # Snapshot the referral score; compute deadlines and the EUO flag.
    case["suspicion_score"] = referral.get("suspicion_score")
    case["investigation_deadline_at"] = db.render_deadline(days_from_now(INVESTIGATION_WINDOW_DAYS))
    case["euo_required"] = int(referral.get("suspicion_score") or 0) >= EUO_SCORE_THRESHOLD
    case["status"] = "OPEN"
    db.touch(case)
    claim = db.claims.get(case.get("claim_id"))
    if claim is not None:
        cascade.claim_put_under_review(claim)
    return success_object(pub_case(case))


@bp.post("/siu/cases/<caseId>/submit-for-decision")
@require_roles("SIUInvestigator")
def submit_for_decision(caseId: str, _user_id: str, _role: str):
    get_json_body()
    case = path_or_404(db.cases, caseId, "SIUCase")
    if case.get("status") != "UNDER_INVESTIGATION":
        raise_err(ERR_INVALID_STATE, "Case must be UNDER_INVESTIGATION to submit for decision")
    if not has_admitted_evidence(case["id"]):
        raise_err(ERR_INVALID_STATE, "At least one ADMITTED evidence item is required")
    if case.get("euo_required"):
        discharged = any(
            row.get("status") == "CONDUCTED"
            for row in db.euo_sessions.values()
            if row.get("case_id") == case["id"]
        ) or int(case.get("_no_show_total", 0)) >= 2
        if not discharged:
            raise_err(
                ERR_INVALID_STATE,
                "EUO obligation must be discharged (CONDUCTED or two no-shows) first",
            )
    case["status"] = "DECISION_PENDING"
    case["decision_due_at"] = db.render_deadline(days_from_now(DECISION_WINDOW_DAYS))
    db.touch(case)
    return success_object(pub_case(case))


@bp.post("/siu/cases/<caseId>/close")
@require_roles("SIUManager")
def close_case(caseId: str, _user_id: str, _role: str):
    body = get_json_body()
    closed_reason = require_enum(body, "closed_reason", CLOSED_REASONS)
    case = path_or_404(db.cases, caseId, "SIUCase")
    status = case.get("status")

    # Rung 5: the transition must exist for the current status + reason.
    if closed_reason == "SUBSTANTIATED":
        if status != "DECISION_PENDING":
            raise_err(ERR_INVALID_STATE, "Case must be DECISION_PENDING to close SUBSTANTIATED")
        if int(case.get("substantiated_fraud_cents", 0)) <= 0:
            raise_err(ERR_INVALID_STATE, "substantiated_fraud_cents must be > 0")
    elif closed_reason in ("UNSUBSTANTIATED",):
        if status != "DECISION_PENDING":
            raise_err(ERR_INVALID_STATE, "Case must be DECISION_PENDING to close UNSUBSTANTIATED")
    elif closed_reason == "INSUFFICIENT_EVIDENCE":
        if status == "OPEN":
            if has_admitted_evidence(case["id"]):
                raise_err(
                    ERR_INVALID_STATE,
                    "OPEN case with ADMITTED evidence cannot close INSUFFICIENT_EVIDENCE",
                )
        elif status != "DECISION_PENDING":
            raise_err(ERR_INVALID_STATE, "Case cannot close INSUFFICIENT_EVIDENCE from this status")
    else:  # WITHDRAWN_BY_ADJUSTER — no transition is declared for it
        raise_err(ERR_INVALID_STATE, "No closure transition exists for WITHDRAWN_BY_ADJUSTER")

    # Rung 7: segregation of duties — closer != assigned investigator.
    assigned = case.get("assigned_investigator_id")
    if assigned is not None and str(assigned) == str(_user_id):
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "The closing manager must differ from the assigned investigator",
        )

    claim = db.claims.get(case.get("claim_id"))

    if closed_reason == "SUBSTANTIATED":
        case["status"] = "CLOSED_SUBSTANTIATED"
        case["closed_reason"] = "SUBSTANTIATED"
        db.touch(case)
        if claim is not None:
            cascade.claim_deny(claim)
        cascade.auto_create_ledger(case)
        if case.get("bureau_referral_required"):
            cascade.auto_create_bureau_referral(case)
        cascade.link_provider_patterns(case)
    else:
        case["status"] = (
            "CLOSED_UNSUBSTANTIATED" if closed_reason == "UNSUBSTANTIATED" else "CLOSED_INSUFFICIENT"
        )
        case["closed_reason"] = closed_reason
        db.touch(case)
        if claim is not None:
            cascade.claim_release_to_pending(claim)

    cascade.complete_active_assignment(case)
    return success_object(pub_case(case))
