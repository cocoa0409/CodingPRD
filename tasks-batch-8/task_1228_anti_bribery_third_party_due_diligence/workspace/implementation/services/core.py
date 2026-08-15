"""Core business logic: scoring, cascades, sweeps, gift windows, commission brackets.

Implements SCAFFOLD §1.3 calculations, §1.2 state machine side effects, and the
deterministic clock sweep of PRD §2.5.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db as dbmod
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_STALE_VERSION,
    ERR_NOT_FOUND,
    ERR_POLICY_NOT_ACTIVE,
    ERR_SPONSOR_TRAINING_OVERDUE,
    ERR_COUNTRY_SANCTIONED,
    ERR_EVENT_IN_PAST,
    ERR_SCREENING_UNRESOLVED,
    ERR_QUESTIONNAIRE_NOT_ACCEPTED,
    ERR_RED_FLAGS_OPEN,
    ERR_CLAUSE_SET_INCOMPLETE,
    ERR_CERTIFICATION_REQUIRED,
    ERR_CERTIFICATION_LAPSED,
    ERR_THIRD_PARTY_NOT_APPROVED,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_COMMISSION_CAP_EXCEEDED,
    ERR_ENHANCED_REVIEW_REQUIRED,
    ERR_GIFT_CAP_EXCEEDED,
    ERR_AUDIT_NOTICE_TOO_SHORT,
    ERR_AUDIT_WINDOW_OVERLAP,
    ERR_REDILIGENCE_OVERDUE,
    ERR_DUPLICATE_ACTIVE_CYCLE,
    ERR_FINDINGS_PENDING,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SOD_VIOLATION,
)
from services.common import new_id, stamp_new, touch, bump

# --- enums / constant maps (SCAFFOLD §1.1) -----------------------------------

INDUSTRY_SCORE = {
    "TECHNOLOGY": 20,
    "LOGISTICS": 40,
    "CONSULTING": 60,
    "CONSTRUCTION": 70,
    "GOVERNMENT_RELATIONS": 90,
}
TOUCHPOINT_SCORE = {"NONE": 0, "INDIRECT": 50, "DIRECT": 100}

TP_TERMINAL = {"REJECTED", "TERMINATED"}
TP_NON_TERMINAL = {"DRAFT", "SCREENING", "DD_REVIEW", "ENHANCED_REVIEW", "APPROVED", "SUSPENDED"}

CHECK_TERMINAL = {"CLEAR", "HIT_CONFIRMED", "HIT_DISMISSED"}
QUESTIONNAIRE_TERMINAL = {"ACCEPTED", "SUPERSEDED"}
FLAG_TERMINAL = {"CLEARED", "SUBSTANTIATED"}
CASE_TERMINAL = {"DECIDED"}
CONTRACT_TERMINAL = {"EXPIRED", "TERMINATED"}
CERT_TERMINAL = set()  # certifications have no terminal state
PAYMENT_TERMINAL = {"BLOCKED", "REVERSED"}
GIFT_TERMINAL = {"REJECTED", "VOIDED"}
CYCLE_TERMINAL = {"COMPLETED"}
AUDIT_TERMINAL = {"CLOSED"}
TRAINING_TERMINAL = {"COMPLETED"}
POLICY_TERMINAL = {"SUPERSEDED"}

REDILIGENCE_INTERVAL_DAYS = {"CRITICAL": 90, "HIGH": 180, "MEDIUM": 365, "LOW": 365}
TIER_LADDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

GIFT_ENHANCED_THRESHOLD_CENTS = 25000
GIFT_HARD_CAP_CENTS = 50000
GIFT_WINDOW_DAYS = 365

AUDIT_NOTICE_DAYS = 10
MANUAL_CYCLE_DAYS = 30
AUTO_SUSPEND_GRACE_DAYS = 30

# severity of a screening-sourced red flag by check type
SCREENING_HIT_SEVERITY = {"SANCTIONS": "CRITICAL", "PEP": "HIGH", "ADVERSE_MEDIA": "MEDIUM"}

REQUIRED_CLAUSES = {
    "LOW": {"ABAC"},
    "MEDIUM": {"ABAC"},
    "HIGH": {"ABAC", "AUDIT_RIGHTS", "ANNUAL_CERTIFICATION"},
    "CRITICAL": {"ABAC", "AUDIT_RIGHTS", "ANNUAL_CERTIFICATION", "TERMINATION_FOR_CAUSE", "GOVT_OFFICIAL_DISCLOSURE"},
}


# --- lookups ------------------------------------------------------------------

def get_tp(tp_id):
    tp = dbmod.DB["third_parties"].get(tp_id)
    if tp is None:
        raise_err(ERR_NOT_FOUND, "third party not found")
    return tp


def get_country_profile_for(tp):
    pid = dbmod.DB["country_code_index"].get(tp["country_code"])
    return dbmod.DB["country_risk_profiles"].get(pid) if pid else None


def active_policy():
    """Return the single ACTIVE policy, or None when none exists."""
    actives = [
        p for p in dbmod.DB["risk_scoring_policies"].values()
        if p["policy_status"] == "ACTIVE"
    ]
    if len(actives) == 1:
        return actives[0]
    return None


def require_active_policy():
    pol = active_policy()
    if pol is None:
        raise_err(ERR_POLICY_NOT_ACTIVE, "no RiskScoringPolicy is ACTIVE")
    return pol


def current_questionnaire(tp_id):
    """The current (non-SUPERSEDED) questionnaire for a third party, if any."""
    qs = [
        q for q in dbmod.DB["questionnaires"].values()
        if q["third_party_id"] == tp_id and q["questionnaire_status"] != "SUPERSEDED"
    ]
    if not qs:
        return None
    qs.sort(key=lambda q: q["created_at"])
    return qs[-1]


def checks_of(tp_id):
    rows = [c for c in dbmod.DB["screening_checks"].values() if c["third_party_id"] == tp_id]
    rows.sort(key=lambda c: c["created_at"])
    return rows


def flags_of(tp_id):
    rows = [f for f in dbmod.DB["red_flags"].values() if f["third_party_id"] == tp_id]
    rows.sort(key=lambda f: f["created_at"])
    return rows


def cases_of(tp_id):
    rows = [c for c in dbmod.DB["escalation_cases"].values() if c["third_party_id"] == tp_id]
    rows.sort(key=lambda c: c["created_at"])
    return rows


def contracts_of(tp_id):
    rows = [c for c in dbmod.DB["contracts"].values() if c["third_party_id"] == tp_id]
    rows.sort(key=lambda c: c["created_at"])
    return rows


def certs_of(tp_id):
    rows = [c for c in dbmod.DB["certifications"].values() if c["third_party_id"] == tp_id]
    rows.sort(key=lambda c: c["created_at"])
    return rows


def cycles_of(tp_id):
    rows = [c for c in dbmod.DB["rediligence_cycles"].values() if c["third_party_id"] == tp_id]
    rows.sort(key=lambda c: c["created_at"])
    return rows


def gifts_of(tp_id):
    rows = [g for g in dbmod.DB["gift_entries"].values() if g["third_party_id"] == tp_id]
    rows.sort(key=lambda g: g["created_at"])
    return rows


def payments_of_contract(contract_id):
    rows = [p for p in dbmod.DB["payment_requests"].values() if p["contract_id"] == contract_id]
    rows.sort(key=lambda p: p["created_at"])
    return rows


# --- risk scoring (SCAFFOLD §1.3 third_party_risk_score) -----------------------

def _round_half_up_int(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _tier_for_score(score, policy):
    if score >= policy["tier_critical_min"]:
        return "CRITICAL"
    if score >= policy["tier_high_min"]:
        return "HIGH"
    if score >= policy["tier_medium_min"]:
        return "MEDIUM"
    return "LOW"


def compute_provisional(tp):
    """Provisional variant: base weighted formula only, + sanctions override."""
    policy = require_active_policy()
    profile = get_country_profile_for(tp)
    country_norm = 100 - profile["cpi_score"]
    industry_score = INDUSTRY_SCORE[tp["industry"]]
    touchpoint_score = TOUCHPOINT_SCORE[tp["government_touchpoint"]]
    raw = (
        policy["w_country"] * country_norm
        + policy["w_industry"] * industry_score
        + policy["w_touchpoint"] * touchpoint_score
    )
    score = _round_half_up_int(Decimal(raw) / Decimal(100))
    score = max(0, min(100, score))
    if profile.get("sanctioned"):
        score = 100
    return score, _tier_for_score(score, policy)


def compute_final(tp):
    """Final variant: provisional + questionnaire + screening modifiers, clamped,
    with sanctions overrides evaluated after the arithmetic."""
    policy = require_active_policy()
    profile = get_country_profile_for(tp)
    provisional = tp["risk_score_provisional"]
    if provisional is None:
        provisional, _ = compute_provisional(tp)

    q_mod = 0
    q = current_questionnaire(tp["id"])
    if q is not None and q["questionnaire_status"] == "ACCEPTED":
        if (q.get("government_ownership_pct") or 0) > 0:
            q_mod += 10
        if q.get("has_facilitation_payments"):
            q_mod += 15
        if q.get("uses_sub_agents"):
            q_mod += 5

    s_mod = 0
    sanctions_hit = False
    for c in checks_of(tp["id"]):
        if c["check_status"] == "HIT_CONFIRMED":
            if c["check_type"] == "PEP":
                s_mod += 20
            elif c["check_type"] == "ADVERSE_MEDIA":
                s_mod += 10
            elif c["check_type"] == "SANCTIONS":
                sanctions_hit = True

    score = provisional + q_mod + s_mod
    score = max(0, min(100, score))
    if profile.get("sanctioned") or sanctions_hit:
        score = 100
    return score, _tier_for_score(score, policy)


def apply_provisional(tp):
    score, tier = compute_provisional(tp)
    tp["risk_score_provisional"] = score
    tp["risk_tier"] = tier
    touch(tp)


def apply_final(tp):
    score, tier = compute_final(tp)
    tp["risk_score_final"] = score
    tp["risk_tier"] = tier
    touch(tp)


# --- red flag / escalation cascade (SCAFFOLD §1.2) -----------------------------

def _auto_escalate_flag(flag, escalated_by):
    """Move a flag OPEN -> UNDER_ENHANCED_REVIEW, open an ENHANCED_DD case, and
    shift the owning third party (APPROVED->SUSPENDED, SCREENING/DD_REVIEW->ENHANCED_REVIEW)."""
    flag["flag_status"] = "UNDER_ENHANCED_REVIEW"
    flag["escalated_by_user_id"] = escalated_by
    touch(flag)

    case = stamp_new({
        "id": new_id(),
        "third_party_id": flag["third_party_id"],
        "case_status": "ENHANCED_DD",
        "escalated_by_user_id": escalated_by,
        "decision_outcome": None,
        "conditions_note": None,
    })
    dbmod.DB["escalation_cases"][case["id"]] = case

    tp = get_tp(flag["third_party_id"])
    if tp["onboarding_status"] == "APPROVED":
        tp["onboarding_status"] = "SUSPENDED"
        bump(tp)
    elif tp["onboarding_status"] in ("SCREENING", "DD_REVIEW"):
        tp["onboarding_status"] = "ENHANCED_REVIEW"
        bump(tp)
    return case


def create_red_flag(tp_id, source_type, source_ref_id, severity, description, escalated_by_for_auto=None):
    """Create a red flag; CRITICAL severity auto-escalates at creation."""
    flag = stamp_new({
        "id": new_id(),
        "third_party_id": tp_id,
        "source_type": source_type,
        "source_ref_id": source_ref_id,
        "severity": severity,
        "description": description,
        "flag_status": "OPEN",
        "escalated_by_user_id": None,
    })
    dbmod.DB["red_flags"][flag["id"]] = flag
    if severity == "CRITICAL":
        _auto_escalate_flag(flag, escalated_by_for_auto)
    return flag


def reevaluate_screening_advance(tp):
    """After every screening disposition: if all checks terminal and the party is
    still in SCREENING, advance to DD_REVIEW."""
    if tp["onboarding_status"] != "SCREENING":
        return
    checks = checks_of(tp["id"])
    if checks and all(c["check_status"] in CHECK_TERMINAL for c in checks):
        tp["onboarding_status"] = "DD_REVIEW"
        bump(tp)


# --- termination cascade (SCAFFOLD §1.2 ThirdParty -> TERMINATED) ---------------

def terminate_third_party(tp):
    tp["onboarding_status"] = "TERMINATED"
    bump(tp)
    for contract in contracts_of(tp["id"]):
        if contract["contract_status"] in ("DRAFT", "PENDING_CLAUSES", "ACTIVE"):
            contract["contract_status"] = "TERMINATED"
            touch(contract)
        for pay in payments_of_contract(contract["id"]):
            if pay["payment_status"] == "SUBMITTED":
                pay["payment_status"] = "BLOCKED"
                touch(pay)
    for gift in gifts_of(tp["id"]):
        if gift["entry_status"] == "PENDING_APPROVAL":
            gift["entry_status"] = "REJECTED"
            touch(gift)


# --- gift rolling window (SCAFFOLD §1.3 gift_rolling_window_total) ---------------

def value_usd_cents_of(value_cents, fx_rate_to_usd):
    """Per-entry round-half-up BEFORE summation."""
    if not isinstance(fx_rate_to_usd, Decimal):
        fx = Decimal(str(fx_rate_to_usd))
    else:
        fx = fx_rate_to_usd
    return int((Decimal(value_cents) * fx).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _window_start(event_date):
    return date.fromordinal(event_date.toordinal() - GIFT_WINDOW_DAYS)


def rolling_gov_total(tp_id, event_date):
    """Sum of value_usd_cents over APPROVED gov-official entries with event_date in
    (event_date - 365d, event_date]."""
    lo = _window_start(event_date)
    total = 0
    for g in gifts_of(tp_id):
        if (
            g["recipient_is_government_official"]
            and g["entry_status"] == "APPROVED"
            and lo < g["event_date"] <= event_date
        ):
            total += g["value_usd_cents"]
    return total


def refresh_gift_aggregate(tp):
    """gov_gift_rolling_12m_cents: rolling 365-day sum over the party's APPROVED
    government-official entries. The window is anchored at the latest event_date
    among those entries (or the current date when none exist), so a just-approved
    entry is always included (PRD §3.8: 'now including this entry')."""
    approved_gov = [
        g for g in gifts_of(tp["id"])
        if g["recipient_is_government_official"] and g["entry_status"] == "APPROVED"
    ]
    if not approved_gov:
        tp["gov_gift_rolling_12m_cents"] = 0
        touch(tp)
        return
    anchor = max(g["event_date"] for g in approved_gov)
    lo = _window_start(anchor)
    total = sum(g["value_usd_cents"] for g in approved_gov if lo < g["event_date"] <= anchor)
    tp["gov_gift_rolling_12m_cents"] = total
    touch(tp)


# --- commission reasonableness (SCAFFOLD §1.3 commission_reasonableness) ---------

def compute_ratio_pct(amount_cents, contract_value_cents):
    scaled = (Decimal(amount_cents) * Decimal(10000)) / Decimal(contract_value_cents)
    rounded = scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (rounded / Decimal(100)).quantize(Decimal("0.01"))


def commission_multiplier(country_norm):
    if country_norm >= 70:
        return Decimal("0.60")
    if 40 <= country_norm <= 69:
        return Decimal("0.80")
    return Decimal("1.00")


def evaluate_commission_bracket(payment, contract, tp, policy):
    """Pinned evaluation order: ratio -> country_norm -> multiplier -> effective cap
    -> bracket selection. REIMBURSEMENT skips the brackets entirely."""
    if payment["payment_type"] == "REIMBURSEMENT":
        return "APPROVABLE"
    profile = get_country_profile_for(tp)
    country_norm = 100 - profile["cpi_score"]
    mult = commission_multiplier(country_norm)
    effective_cap = (policy["commission_base_cap_pct"] * mult).quantize(Decimal("0.01"))
    ratio = payment["ratio_pct"]
    hard_cap = policy["commission_hard_cap_pct"]
    if ratio > hard_cap:
        return "BLOCKED_ONLY"
    if ratio > effective_cap:
        return "EVIDENCE_REQUIRED"
    return "APPROVABLE"


# --- re-diligence (SCAFFOLD §1.3 rediligence_schedule) -----------------------------

def create_cycle(tp, trigger_source, due_date, status="SCHEDULED"):
    cycle = stamp_new({
        "id": new_id(),
        "third_party_id": tp["id"],
        "cycle_status": status,
        "trigger_source": trigger_source,
        "due_date": due_date,
        "outcome": None,
    })
    dbmod.DB["rediligence_cycles"][cycle["id"]] = cycle
    return cycle


def tier_interval_days(tier):
    return REDILIGENCE_INTERVAL_DAYS[tier]


# --- deterministic clock sweep (PRD §2.5) ----------------------------------------

def run_clock_sweep():
    today = dbmod.current_date()

    # certification lapse: VERIFIED -> LAPSED when current date > valid_until
    for cert in dbmod.DB["certifications"].values():
        if cert["cert_status"] == "VERIFIED" and cert.get("valid_until") is not None:
            if today > cert["valid_until"]:
                cert["cert_status"] = "LAPSED"
                touch(cert)

    # re-diligence overdue + 30-day auto-suspend
    for cycle in dbmod.DB["rediligence_cycles"].values():
        if cycle["cycle_status"] in ("SCHEDULED", "IN_PROGRESS"):
            if today > cycle["due_date"]:
                cycle["cycle_status"] = "OVERDUE"
                touch(cycle)
        if cycle["cycle_status"] == "OVERDUE":
            grace_end = date.fromordinal(cycle["due_date"].toordinal() + AUTO_SUSPEND_GRACE_DAYS)
            if today > grace_end:
                tp = dbmod.DB["third_parties"].get(cycle["third_party_id"])
                if tp is not None and tp["onboarding_status"] == "APPROVED":
                    tp["onboarding_status"] = "SUSPENDED"
                    bump(tp)

    # training overdue
    for t in dbmod.DB["training_assignments"].values():
        if t["training_status"] == "ASSIGNED" and today > t["due_date"]:
            t["training_status"] = "OVERDUE"
            touch(t)

    # contract expiry
    for c in dbmod.DB["contracts"].values():
        if c["contract_status"] in ("PENDING_CLAUSES", "ACTIVE") and today > c["end_date"]:
            c["contract_status"] = "EXPIRED"
            touch(c)


# --- shared precondition helpers -------------------------------------------------

def ensure_not_terminal(status, terminal_set, entity_label):
    if status in terminal_set:
        raise_err(ERR_ALREADY_TERMINAL, f"{entity_label} is already in a terminal state ({status})")


def ensure_transition(status, allowed_from, entity_label):
    if status not in allowed_from:
        raise_err(ERR_INVALID_STATE, f"{entity_label} cannot perform this action from state {status}")


def check_occ(expected, current):
    if expected != current:
        raise_err(ERR_STALE_VERSION, "expected version does not match the current version")


def sponsor_has_overdue_training(user_id):
    for t in dbmod.DB["training_assignments"].values():
        if t["assignee_user_id"] == user_id and t["training_status"] == "OVERDUE":
            return True
    return False


def has_verified_certification(tp_id):
    for c in certs_of(tp_id):
        if c["cert_status"] == "VERIFIED":
            return True
    return False


def has_open_flags_or_cases(tp_id):
    for f in flags_of(tp_id):
        if f["flag_status"] in ("OPEN", "UNDER_ENHANCED_REVIEW"):
            return True
    for c in cases_of(tp_id):
        if c["case_status"] == "ENHANCED_DD":
            return True
    return False


def has_overdue_cycle(tp_id):
    for c in cycles_of(tp_id):
        if c["cycle_status"] == "OVERDUE":
            return True
    return False


def has_active_cycle(tp_id):
    for c in cycles_of(tp_id):
        if c["cycle_status"] in ("SCHEDULED", "IN_PROGRESS", "OVERDUE"):
            return True
    return False
