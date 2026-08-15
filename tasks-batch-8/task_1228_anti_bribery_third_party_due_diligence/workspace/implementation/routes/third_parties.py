"""ThirdParty lifecycle + ScreeningCheck + Questionnaire + RedFlag + EscalationCase routes."""

from datetime import date, timedelta

from flask import Blueprint, request

import db as dbmod
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER, ERR_POLICY_NOT_ACTIVE, ERR_SPONSOR_TRAINING_OVERDUE,
    ERR_SCREENING_UNRESOLVED, ERR_QUESTIONNAIRE_NOT_ACCEPTED, ERR_RED_FLAGS_OPEN,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, touch, bump, req_str, req_int, req_bool, opt_bool, req_enum,
)
from services import core

bp = Blueprint("third_parties", __name__)


# --- serializers -----------------------------------------------------------------

def serialize_tp(tp):
    return {
        "id": tp["id"],
        "created_at": tp["created_at"],
        "updated_at": tp["updated_at"],
        "version": tp["version"],
        "legal_name": tp["legal_name"],
        "country_code": tp["country_code"],
        "industry": tp["industry"],
        "government_touchpoint": tp["government_touchpoint"],
        "sponsor_user_id": tp["sponsor_user_id"],
        "onboarding_status": tp["onboarding_status"],
        "risk_score_provisional": tp["risk_score_provisional"],
        "risk_score_final": tp["risk_score_final"],
        "risk_tier": tp["risk_tier"],
        "approval_tier_snapshot": tp["approval_tier_snapshot"],
        "approved_policy_id": tp["approved_policy_id"],
        "diligence_expires_at": (tp["diligence_expires_at"].isoformat() if tp["diligence_expires_at"] else None),
        "gov_gift_rolling_12m_cents": tp["gov_gift_rolling_12m_cents"],
    }


def serialize_check(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "third_party_id": c["third_party_id"],
        "check_type": c["check_type"],
        "check_status": c["check_status"],
        "match_detail": c["match_detail"],
    }


def serialize_questionnaire(q):
    return {
        "id": q["id"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
        "third_party_id": q["third_party_id"],
        "questionnaire_status": q["questionnaire_status"],
        "government_ownership_pct": q["government_ownership_pct"],
        "has_facilitation_payments": q["has_facilitation_payments"],
        "uses_sub_agents": q["uses_sub_agents"],
        "red_flag_count": q["red_flag_count"],
        "return_note": q["return_note"],
    }


def serialize_flag(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "third_party_id": f["third_party_id"],
        "source_type": f["source_type"],
        "source_ref_id": f["source_ref_id"],
        "severity": f["severity"],
        "description": f["description"],
        "flag_status": f["flag_status"],
        "escalated_by_user_id": f["escalated_by_user_id"],
    }


def serialize_case(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "third_party_id": c["third_party_id"],
        "case_status": c["case_status"],
        "escalated_by_user_id": c["escalated_by_user_id"],
        "decision_outcome": c["decision_outcome"],
        "conditions_note": c["conditions_note"],
    }


# --- ThirdParty CRUD + lifecycle ---------------------------------------------------

@bp.post("/compliance/third-parties")
def create_third_party():
    user_id, _ = require_roles(["BusinessSponsor"])
    body = get_json_body()
    legal_name = req_str(body, "legal_name")
    country_code = req_str(body, "country_code")
    industry = req_enum(body, "industry", set(core.INDUSTRY_SCORE.keys()))
    touchpoint = req_enum(body, "government_touchpoint", set(core.TOUCHPOINT_SCORE.keys()))
    if country_code not in dbmod.DB["country_code_index"]:
        raise_err(ERR_NOT_FOUND, "country_code has no CountryRiskProfile")
    rec = stamp_new({
        "id": new_id(),
        "legal_name": legal_name,
        "country_code": country_code,
        "industry": industry,
        "government_touchpoint": touchpoint,
        "sponsor_user_id": user_id,
        "onboarding_status": "DRAFT",
        "risk_score_provisional": None,
        "risk_score_final": None,
        "risk_tier": None,
        "approval_tier_snapshot": None,
        "approved_policy_id": None,
        "diligence_expires_at": None,
        "gov_gift_rolling_12m_cents": 0,
    })
    dbmod.DB["third_parties"][rec["id"]] = rec
    return success_object(serialize_tp(rec), 201)


@bp.get("/compliance/third-parties/<third_party_id>")
def get_third_party(third_party_id):
    require_roles(ALL_ROLES)
    tp = core.get_tp(third_party_id)
    return success_object(serialize_tp(tp))


@bp.get("/compliance/third-parties")
def list_third_parties():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    status_f = request.args.get("onboarding_status")
    tier_f = request.args.get("risk_tier")
    country_f = request.args.get("country_code")
    sponsor_f = request.args.get("sponsor_user_id")
    rows = list(dbmod.DB["third_parties"].values())
    if status_f is not None:
        rows = [r for r in rows if r["onboarding_status"] == status_f]
    if tier_f is not None:
        rows = [r for r in rows if r["risk_tier"] == tier_f]
    if country_f is not None:
        rows = [r for r in rows if r["country_code"] == country_f]
    if sponsor_f is not None:
        rows = [r for r in rows if r["sponsor_user_id"] == sponsor_f]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_tp(r) for r in page], total, limit, offset)


@bp.patch("/compliance/third-parties/<third_party_id>")
def update_third_party(third_party_id):
    user_id, _ = require_roles(["BusinessSponsor"])
    tp = core.get_tp(third_party_id)
    body = get_json_body()
    expected = body.get("expected_third_party_version")
    if expected is None:
        raise_err(ERR_VALIDATION, "expected_third_party_version is required")
    core.check_occ(expected, tp["version"])
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"DRAFT"}, "ThirdParty")
    if tp["sponsor_user_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "sponsor may only update its own third parties")
    if "legal_name" in body:
        tp["legal_name"] = req_str(body, "legal_name")
    if "industry" in body:
        tp["industry"] = req_enum(body, "industry", set(core.INDUSTRY_SCORE.keys()))
    if "government_touchpoint" in body:
        tp["government_touchpoint"] = req_enum(body, "government_touchpoint", set(core.TOUCHPOINT_SCORE.keys()))
    bump(tp)
    return success_object(serialize_tp(tp))


@bp.post("/compliance/third-parties/<third_party_id>/submit")
def submit_third_party(third_party_id):
    user_id, _ = require_roles(["BusinessSponsor"])
    tp = core.get_tp(third_party_id)
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"DRAFT"}, "ThirdParty")
    if tp["sponsor_user_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "sponsor may only submit its own third parties")
    if core.sponsor_has_overdue_training(user_id):
        raise_err(ERR_SPONSOR_TRAINING_OVERDUE, "sponsor has an OVERDUE training assignment")
    core.require_active_policy()

    tp["onboarding_status"] = "SCREENING"
    score, tier = core.compute_provisional(tp)
    tp["risk_score_provisional"] = score
    tp["risk_tier"] = tier
    bump(tp)

    for check_type in ("PEP", "ADVERSE_MEDIA", "SANCTIONS"):
        c = stamp_new({
            "id": new_id(),
            "third_party_id": tp["id"],
            "check_type": check_type,
            "check_status": "QUEUED",
            "match_detail": None,
        })
        dbmod.DB["screening_checks"][c["id"]] = c
    return success_object(serialize_tp(tp))


@bp.post("/compliance/third-parties/<third_party_id>/approve")
def approve_third_party(third_party_id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(third_party_id)
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"DD_REVIEW"}, "ThirdParty")
    # referential gates, priority 9, active-policy first
    policy = core.require_active_policy()
    q = core.current_questionnaire(tp["id"])
    if q is None or q["questionnaire_status"] != "ACCEPTED" or tp["risk_score_final"] is None:
        raise_err(ERR_QUESTIONNAIRE_NOT_ACCEPTED, "current questionnaire is not ACCEPTED")
    if core.has_open_flags_or_cases(tp["id"]):
        raise_err(ERR_RED_FLAGS_OPEN, "open red flags or escalation cases remain")

    tp["onboarding_status"] = "APPROVED"
    tp["approval_tier_snapshot"] = tp["risk_tier"]
    tp["approved_policy_id"] = policy["id"]
    interval = core.tier_interval_days(tp["risk_tier"])
    today = dbmod.current_date()
    expires = date.fromordinal(today.toordinal() + interval)
    tp["diligence_expires_at"] = expires
    bump(tp)
    core.create_cycle(tp, "SCHEDULED", expires)
    return success_object(serialize_tp(tp))


@bp.post("/compliance/third-parties/<third_party_id>/reject")
def reject_third_party(third_party_id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(third_party_id)
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"SCREENING", "DD_REVIEW"}, "ThirdParty")
    tp["onboarding_status"] = "REJECTED"
    bump(tp)
    return success_object(serialize_tp(tp))


@bp.post("/compliance/third-parties/<third_party_id>/suspend")
def suspend_third_party(third_party_id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(third_party_id)
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"APPROVED"}, "ThirdParty")
    tp["onboarding_status"] = "SUSPENDED"
    bump(tp)
    return success_object(serialize_tp(tp))


@bp.post("/compliance/third-parties/<third_party_id>/reinstate")
def reinstate_third_party(third_party_id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(third_party_id)
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"SUSPENDED"}, "ThirdParty")
    if core.has_open_flags_or_cases(tp["id"]):
        raise_err(ERR_RED_FLAGS_OPEN, "open red flags or escalation cases remain")
    tp["onboarding_status"] = "APPROVED"
    bump(tp)
    return success_object(serialize_tp(tp))


@bp.post("/compliance/third-parties/<third_party_id>/terminate")
def terminate_third_party_route(third_party_id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(third_party_id)
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"APPROVED", "SUSPENDED"}, "ThirdParty")
    core.terminate_third_party(tp)
    return success_object(serialize_tp(tp))


# --- ScreeningCheck ---------------------------------------------------------------

@bp.post("/compliance/screening-checks/<check_id>/disposition")
def disposition_check(check_id):
    require_roles(["ScreeningAnalyst"])
    c = dbmod.DB["screening_checks"].get(check_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, "screening check not found")
    body = get_json_body()
    outcome = req_enum(body, "outcome", {"CLEAR", "POTENTIAL_HIT", "HIT_CONFIRMED", "HIT_DISMISSED"})
    core.ensure_not_terminal(c["check_status"], core.CHECK_TERMINAL, "ScreeningCheck")
    tp = core.get_tp(c["third_party_id"])

    if c["check_status"] == "QUEUED":
        if outcome not in ("CLEAR", "POTENTIAL_HIT"):
            raise_err(ERR_INVALID_STATE, f"cannot disposition QUEUED check with outcome {outcome}")
        if outcome == "POTENTIAL_HIT":
            match_detail = body.get("match_detail")
            if match_detail is None or not isinstance(match_detail, str) or match_detail == "":
                raise_err(ERR_VALIDATION, "match_detail is required for POTENTIAL_HIT")
            c["match_detail"] = match_detail
        c["check_status"] = outcome
        touch(c)
    elif c["check_status"] == "POTENTIAL_HIT":
        if outcome not in ("HIT_CONFIRMED", "HIT_DISMISSED"):
            raise_err(ERR_INVALID_STATE, f"cannot disposition POTENTIAL_HIT check with outcome {outcome}")
        c["check_status"] = outcome
        touch(c)
        if outcome == "HIT_CONFIRMED":
            # Cascade L0: recompute provisional score/tier under the confirmed hit
            profile = core.get_country_profile_for(tp)
            if c["check_type"] == "SANCTIONS" or (profile and profile.get("sanctioned")):
                tp["risk_score_provisional"] = 100
                tp["risk_tier"] = "CRITICAL"
            else:
                score, tier = core.compute_provisional(tp)
                tp["risk_score_provisional"] = score
                tp["risk_tier"] = tier
            touch(tp)
            # Cascade L1: create the screening-sourced red flag
            severity = core.SCREENING_HIT_SEVERITY[c["check_type"]]
            core.create_red_flag(
                tp["id"], "SCREENING", c["id"], severity,
                f"Confirmed {c['check_type']} hit", escalated_by_for_auto=None,
            )
            # (L2/L3 auto-escalation happen inside create_red_flag for CRITICAL)
    core.reevaluate_screening_advance(tp)
    return success_object(serialize_check(c))


@bp.get("/compliance/third-parties/<id>/screening-checks")
def list_checks(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    rows = core.checks_of(id)
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_check(r) for r in page], total, limit, offset)


# --- Questionnaire -----------------------------------------------------------------

@bp.post("/compliance/third-parties/<id>/questionnaires")
def issue_questionnaire(id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(id)
    body = get_json_body()
    expected = body.get("expected_third_party_version")
    if expected is None:
        raise_err(ERR_VALIDATION, "expected_third_party_version is required")
    core.check_occ(expected, tp["version"])
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(tp["onboarding_status"], {"SCREENING", "DD_REVIEW", "ENHANCED_REVIEW"}, "ThirdParty")
    # supersede prior non-terminal questionnaires
    for q in dbmod.DB["questionnaires"].values():
        if q["third_party_id"] == tp["id"] and q["questionnaire_status"] in ("ISSUED", "SUBMITTED", "RETURNED"):
            q["questionnaire_status"] = "SUPERSEDED"
            touch(q)
    rec = stamp_new({
        "id": new_id(),
        "third_party_id": tp["id"],
        "questionnaire_status": "ISSUED",
        "government_ownership_pct": None,
        "has_facilitation_payments": None,
        "uses_sub_agents": None,
        "red_flag_count": None,
        "return_note": None,
    })
    dbmod.DB["questionnaires"][rec["id"]] = rec
    bump(tp)
    return success_object(serialize_questionnaire(rec), 201)


def _get_questionnaire(questionnaire_id):
    q = dbmod.DB["questionnaires"].get(questionnaire_id)
    if q is None:
        raise_err(ERR_NOT_FOUND, "questionnaire not found")
    return q


@bp.post("/compliance/questionnaires/<questionnaire_id>/submit")
def submit_questionnaire(questionnaire_id):
    user_id, _ = require_roles(["BusinessSponsor"])
    q = _get_questionnaire(questionnaire_id)
    tp = core.get_tp(q["third_party_id"])
    body = get_json_body()
    core.ensure_not_terminal(q["questionnaire_status"], core.QUESTIONNAIRE_TERMINAL, "Questionnaire")
    core.ensure_transition(q["questionnaire_status"], {"ISSUED", "RETURNED"}, "Questionnaire")
    # current-questionnaire precondition
    cur = core.current_questionnaire(tp["id"])
    if cur is None or cur["id"] != q["id"]:
        raise_err(ERR_INVALID_STATE, "questionnaire is not the current one for its third party")
    if tp["sponsor_user_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "sponsor may only submit its own questionnaires")
    gov_pct = req_int(body, "government_ownership_pct")
    if gov_pct < 0 or gov_pct > 100:
        raise_err(ERR_VALIDATION, "government_ownership_pct must be between 0 and 100")
    fac = req_bool(body, "has_facilitation_payments")
    sub = req_bool(body, "uses_sub_agents")
    q["government_ownership_pct"] = gov_pct
    q["has_facilitation_payments"] = fac
    q["uses_sub_agents"] = sub
    q["red_flag_count"] = int(gov_pct > 0) + int(fac) + int(sub)
    q["questionnaire_status"] = "SUBMITTED"
    touch(q)
    return success_object(serialize_questionnaire(q))


@bp.post("/compliance/questionnaires/<questionnaire_id>/accept")
def accept_questionnaire(questionnaire_id):
    require_roles(["ComplianceOfficer"])
    q = _get_questionnaire(questionnaire_id)
    tp = core.get_tp(q["third_party_id"])
    core.ensure_not_terminal(q["questionnaire_status"], core.QUESTIONNAIRE_TERMINAL, "Questionnaire")
    # third-party must be in DD_REVIEW or ENHANCED_REVIEW
    core.ensure_transition(tp["onboarding_status"], {"DD_REVIEW", "ENHANCED_REVIEW"}, "ThirdParty")
    cur = core.current_questionnaire(tp["id"])
    if cur is None or cur["id"] != q["id"]:
        raise_err(ERR_INVALID_STATE, "questionnaire is not the current one for its third party")
    core.ensure_transition(q["questionnaire_status"], {"SUBMITTED"}, "Questionnaire")
    # all screening checks terminal
    for c in core.checks_of(tp["id"]):
        if c["check_status"] not in core.CHECK_TERMINAL:
            raise_err(ERR_SCREENING_UNRESOLVED, "screening checks are not all terminal")
    q["questionnaire_status"] = "ACCEPTED"
    touch(q)
    core.apply_final(tp)
    return success_object(serialize_questionnaire(q))


@bp.post("/compliance/questionnaires/<questionnaire_id>/return")
def return_questionnaire(questionnaire_id):
    require_roles(["ComplianceOfficer"])
    q = _get_questionnaire(questionnaire_id)
    body = get_json_body()
    core.ensure_not_terminal(q["questionnaire_status"], core.QUESTIONNAIRE_TERMINAL, "Questionnaire")
    core.ensure_transition(q["questionnaire_status"], {"SUBMITTED"}, "Questionnaire")
    note = body.get("return_note")
    if note is not None and not isinstance(note, str):
        raise_err(ERR_VALIDATION, "return_note must be a string")
    q["return_note"] = note
    q["questionnaire_status"] = "RETURNED"
    touch(q)
    return success_object(serialize_questionnaire(q))


@bp.get("/compliance/third-parties/<id>/questionnaires")
def list_questionnaires(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    rows = [q for q in dbmod.DB["questionnaires"].values() if q["third_party_id"] == id]
    rows.sort(key=lambda q: q["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_questionnaire(r) for r in page], total, limit, offset)


# --- RedFlag -----------------------------------------------------------------------

@bp.post("/compliance/third-parties/<id>/red-flags")
def create_manual_flag(id):
    user_id, role = require_roles(["ComplianceOfficer", "ScreeningAnalyst"])
    tp = core.get_tp(id)
    body = get_json_body()
    # requires the third party to be past DRAFT
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    if tp["onboarding_status"] == "DRAFT":
        raise_err(ERR_INVALID_STATE, "third party is still in DRAFT")
    severity = req_enum(body, "severity", {"LOW", "MEDIUM", "HIGH", "CRITICAL"})
    description = req_str(body, "description")
    flag = core.create_red_flag(tp["id"], "MANUAL", None, severity, description, escalated_by_for_auto=None)
    return success_object(serialize_flag(flag), 201)


@bp.post("/compliance/red-flags/<flag_id>/disposition")
def disposition_flag(flag_id):
    user_id, _ = require_roles(["ComplianceOfficer"])
    flag = dbmod.DB["red_flags"].get(flag_id)
    if flag is None:
        raise_err(ERR_NOT_FOUND, "red flag not found")
    body = get_json_body()
    disposition = req_enum(body, "disposition", {"CLEARED", "ESCALATE"})
    core.ensure_not_terminal(flag["flag_status"], core.FLAG_TERMINAL, "RedFlag")
    core.ensure_transition(flag["flag_status"], {"OPEN"}, "RedFlag")
    if disposition == "CLEARED":
        if flag["severity"] == "CRITICAL":
            raise_err(ERR_INVALID_STATE, "CRITICAL flags may only be resolved via escalation decision")
        flag["flag_status"] = "CLEARED"
        touch(flag)
    else:  # ESCALATE
        core._auto_escalate_flag(flag, user_id)
    return success_object(serialize_flag(flag))


@bp.get("/compliance/third-parties/<id>/red-flags")
def list_flags(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    status_f = request.args.get("flag_status")
    sev_f = request.args.get("severity")
    rows = core.flags_of(id)
    if status_f is not None:
        rows = [r for r in rows if r["flag_status"] == status_f]
    if sev_f is not None:
        rows = [r for r in rows if r["severity"] == sev_f]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_flag(r) for r in page], total, limit, offset)


# --- EscalationCase ------------------------------------------------------------------

@bp.post("/compliance/escalation-cases/<case_id>/decide")
def decide_case(case_id):
    user_id, _ = require_roles(["ComplianceOfficer"])
    case = dbmod.DB["escalation_cases"].get(case_id)
    if case is None:
        raise_err(ERR_NOT_FOUND, "escalation case not found")
    body = get_json_body()
    outcome = req_enum(body, "outcome", {"APPROVE_WITH_CONDITIONS", "REJECT", "TERMINATE"})
    core.ensure_not_terminal(case["case_status"], core.CASE_TERMINAL, "EscalationCase")
    core.ensure_transition(case["case_status"], {"ENHANCED_DD"}, "EscalationCase")
    # SoD: decider must differ from escalator when non-null
    if case["escalated_by_user_id"] is not None and case["escalated_by_user_id"] == user_id:
        raise_err(ERR_SOD_VIOLATION, "decider must differ from escalated_by_user_id")
    tp = core.get_tp(case["third_party_id"])
    if outcome == "REJECT" and tp["onboarding_status"] != "ENHANCED_REVIEW":
        raise_err(ERR_INVALID_STATE, "REJECT is valid only while the third party is in ENHANCED_REVIEW")

    case["case_status"] = "DECIDED"
    case["decision_outcome"] = outcome
    cond = body.get("conditions_note")
    if cond is not None and not isinstance(cond, str):
        raise_err(ERR_VALIDATION, "conditions_note must be a string")
    case["conditions_note"] = cond
    touch(case)

    # linked flags: the escalated flags of this third party tied to this case window.
    # A case opens when a flag escalates; resolve every UNDER_ENHANCED_REVIEW flag of
    # the third party.
    linked = [
        f for f in core.flags_of(tp["id"])
        if f["flag_status"] == "UNDER_ENHANCED_REVIEW"
    ]
    if outcome == "APPROVE_WITH_CONDITIONS":
        for f in linked:
            f["flag_status"] = "CLEARED"
            touch(f)
        if tp["onboarding_status"] == "ENHANCED_REVIEW":
            tp["onboarding_status"] = "DD_REVIEW"
            bump(tp)
        elif tp["onboarding_status"] == "SUSPENDED":
            tp["onboarding_status"] = "APPROVED"
            bump(tp)
    elif outcome == "REJECT":
        for f in linked:
            f["flag_status"] = "SUBSTANTIATED"
            touch(f)
        tp["onboarding_status"] = "REJECTED"
        bump(tp)
    else:  # TERMINATE
        for f in linked:
            f["flag_status"] = "SUBSTANTIATED"
            touch(f)
        core.terminate_third_party(tp)
    return success_object(serialize_case(case))


@bp.get("/compliance/third-parties/<id>/escalation-cases")
def list_cases(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    rows = core.cases_of(id)
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_case(r) for r in page], total, limit, offset)
