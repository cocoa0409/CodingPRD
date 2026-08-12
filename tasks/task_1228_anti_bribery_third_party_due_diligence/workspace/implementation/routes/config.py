"""Clock, CountryRiskProfile, RiskScoringPolicy routes."""

from flask import Blueprint

import db as dbmod
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
)
from middleware import require_roles, get_json_body, ALL_ROLES
from response import success_object
from services.common import (
    new_id, stamp_new, touch, bump, parse_iso_datetime, req_str, req_int, opt_int,
    opt_bool, number_out,
)
from services import core

bp = Blueprint("config", __name__)


def serialize_policy(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "policy_status": p["policy_status"],
        "w_country": p["w_country"],
        "w_industry": p["w_industry"],
        "w_touchpoint": p["w_touchpoint"],
        "tier_medium_min": p["tier_medium_min"],
        "tier_high_min": p["tier_high_min"],
        "tier_critical_min": p["tier_critical_min"],
        "commission_base_cap_pct": number_out(p["commission_base_cap_pct"]),
        "commission_hard_cap_pct": number_out(p["commission_hard_cap_pct"]),
    }


def serialize_profile(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "country_code": p["country_code"],
        "cpi_score": p["cpi_score"],
        "sanctioned": p["sanctioned"],
    }


# --- logical clock ---------------------------------------------------------------

@bp.post("/compliance/_clock/set_current_utc")
def set_clock():
    require_roles(["ComplianceAdmin"])
    body = get_json_body()
    to = body.get("to_iso8601")
    dt = parse_iso_datetime(to, "to_iso8601")
    dbmod.DB["clock"] = dt
    core.run_clock_sweep()
    return success_object({"current_utc": dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"})


# --- CountryRiskProfile ----------------------------------------------------------

@bp.post("/compliance/country-risk-profiles")
def create_country_profile():
    require_roles(["ComplianceAdmin"])
    body = get_json_body()
    country_code = req_str(body, "country_code")
    cpi_score = req_int(body, "cpi_score")
    if cpi_score < 0 or cpi_score > 100:
        raise_err(ERR_VALIDATION, "cpi_score must be between 0 and 100")
    sanctioned = opt_bool(body, "sanctioned", False)
    if country_code in dbmod.DB["country_code_index"]:
        raise_err(ERR_VALIDATION, "country_code already has a CountryRiskProfile")
    rec = stamp_new({
        "id": new_id(),
        "country_code": country_code,
        "cpi_score": cpi_score,
        "sanctioned": sanctioned,
    })
    dbmod.DB["country_risk_profiles"][rec["id"]] = rec
    dbmod.DB["country_code_index"][country_code] = rec["id"]
    return success_object(serialize_profile(rec), 201)


@bp.patch("/compliance/country-risk-profiles/<profile_id>")
def update_country_profile(profile_id):
    require_roles(["ComplianceAdmin"])
    rec = dbmod.DB["country_risk_profiles"].get(profile_id)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "country risk profile not found")
    body = get_json_body()
    cpi = opt_int(body, "cpi_score")
    if cpi is not None:
        if cpi < 0 or cpi > 100:
            raise_err(ERR_VALIDATION, "cpi_score must be between 0 and 100")
        rec["cpi_score"] = cpi
    san = opt_bool(body, "sanctioned", None)
    if san is not None:
        rec["sanctioned"] = san
    touch(rec)

    # Re-score cascade: recompute both variants for every non-terminal third party
    # in this country, keeping modifiers intact. The scoring functions apply the
    # sanctions override (score 100 / CRITICAL) themselves.
    affected = [
        tp for tp in dbmod.DB["third_parties"].values()
        if tp["country_code"] == rec["country_code"] and tp["onboarding_status"] in core.TP_NON_TERMINAL
    ]
    for tp in affected:
        if tp["risk_score_provisional"] is not None:
            core.apply_provisional(tp)
            if tp["risk_score_final"] is not None:
                core.apply_final(tp)
    # Sanctions flip -> raise a SYSTEM CRITICAL red flag on each non-terminal party
    # (auto-escalation: flag UNDER_ENHANCED_REVIEW, ENHANCED_DD case, suspension).
    if san is True:
        for tp in affected:
            core.create_red_flag(
                tp["id"], "SYSTEM", None, "CRITICAL",
                f"Country {rec['country_code']} sanctioned",
                escalated_by_for_auto=None,
            )
    return success_object(serialize_profile(rec))


# --- RiskScoringPolicy ------------------------------------------------------------

@bp.post("/compliance/risk-scoring-policies")
def create_policy():
    require_roles(["ComplianceAdmin"])
    body = get_json_body()
    w_country = req_int(body, "w_country")
    w_industry = req_int(body, "w_industry")
    w_touchpoint = req_int(body, "w_touchpoint")
    if w_country + w_industry + w_touchpoint != 100:
        raise_err(ERR_VALIDATION, "weights must sum to 100")
    tier_medium_min = req_int(body, "tier_medium_min")
    tier_high_min = req_int(body, "tier_high_min")
    tier_critical_min = req_int(body, "tier_critical_min")
    from services.common import req_number
    base_cap = req_number(body, "commission_base_cap_pct")
    hard_cap = req_number(body, "commission_hard_cap_pct")
    rec = stamp_new({
        "id": new_id(),
        "policy_status": "DRAFT",
        "w_country": w_country,
        "w_industry": w_industry,
        "w_touchpoint": w_touchpoint,
        "tier_medium_min": tier_medium_min,
        "tier_high_min": tier_high_min,
        "tier_critical_min": tier_critical_min,
        "commission_base_cap_pct": base_cap,
        "commission_hard_cap_pct": hard_cap,
    })
    dbmod.DB["risk_scoring_policies"][rec["id"]] = rec
    return success_object(serialize_policy(rec), 201)


@bp.post("/compliance/risk-scoring-policies/<policy_id>/activate")
def activate_policy(policy_id):
    require_roles(["ComplianceAdmin"])
    rec = dbmod.DB["risk_scoring_policies"].get(policy_id)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "risk scoring policy not found")
    body = get_json_body()
    expected = body.get("expected_policy_version")
    if expected is None:
        raise_err(ERR_VALIDATION, "expected_policy_version is required")
    core.check_occ(expected, rec["version"])
    core.ensure_not_terminal(rec["policy_status"], core.POLICY_TERMINAL, "RiskScoringPolicy")
    core.ensure_transition(rec["policy_status"], {"DRAFT"}, "RiskScoringPolicy")
    # supersede the previously ACTIVE policy
    for p in dbmod.DB["risk_scoring_policies"].values():
        if p["policy_status"] == "ACTIVE" and p["id"] != rec["id"]:
            p["policy_status"] = "SUPERSEDED"
            touch(p)
    rec["policy_status"] = "ACTIVE"
    bump(rec)
    return success_object(serialize_policy(rec))


@bp.get("/compliance/risk-scoring-policies/<policy_id>")
def get_policy(policy_id):
    require_roles(ALL_ROLES)
    rec = dbmod.DB["risk_scoring_policies"].get(policy_id)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "risk scoring policy not found")
    return success_object(serialize_policy(rec))
