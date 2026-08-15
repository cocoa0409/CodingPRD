"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All scores: Decimal math,
round-half-up at exactly 2 decimal places, no intermediate rounding.
"""
import json
from datetime import timedelta
from decimal import Decimal

import db
import util
from util import dec, round2

# ---- tier_assignment --------------------------------------------------------
SEVERITY_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "REGULATED": 3}
ACCESS_RANK = {"NONE": 0, "READ_ONLY": 1, "OPERATOR": 2, "PRIVILEGED": 3}
CRIT_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "MISSION_CRITICAL": 3}
TIER4_CUTOFF = 7
TIER3_CUTOFF = 5
TIER2_CUTOFF = 3

_MATRIX_SEPS = (",", "|", ":", ";", "/", "+", " ", "-")


def _matrix_lookup(tier_matrix, sens, access, crit):
    if not isinstance(tier_matrix, dict):
        return None
    for sep in _MATRIX_SEPS:
        key = sep.join((sens, access, crit))
        if key in tier_matrix:
            return tier_matrix[key]
    for candidate in (json.dumps([sens, access, crit]),
                      json.dumps([sens, access, crit], separators=(",", ":")),
                      str((sens, access, crit))):
        if candidate in tier_matrix:
            return tier_matrix[candidate]
    return None


def tier_assignment(sens, access, crit, policy):
    """Matrix override wins outright; otherwise rank-sum fallback (§3.1)."""
    if policy is not None:
        hit = _matrix_lookup(policy.get("tier_matrix"), sens, access, crit)
        if hit in ("TIER_1", "TIER_2", "TIER_3", "TIER_4"):
            return hit
    score = SEVERITY_RANK[sens] + ACCESS_RANK[access] + CRIT_RANK[crit]
    if score >= TIER4_CUTOFF:
        return "TIER_4"
    if score >= TIER3_CUTOFF:
        return "TIER_3"
    if score >= TIER2_CUTOFF:
        return "TIER_2"
    return "TIER_1"


# ---- questionnaire_response_score -------------------------------------------
REVISION_PENALTY_PCT = Decimal("0.05")
REVISION_PENALTY_CAP = Decimal("20.0")
ANSWER_SCORE = {"YES": Decimal("1.0"), "PARTIAL": Decimal("0.5"), "NO": Decimal("0.0")}

PASS_THRESHOLD = {"TIER_1": Decimal("60"), "TIER_2": Decimal("70"),
                  "TIER_3": Decimal("80"), "TIER_4": Decimal("90")}


def questionnaire_raw(template, response):
    """Raw ratio (no revision penalty). NA items excluded from both sums.
    Returns Decimal rounded half-up to 2dp; 0.00 when everything is NA."""
    answers = {a.get("item_key"): a for a in response.get("answers", [])
               if isinstance(a, dict)}
    earned = Decimal("0")
    possible = Decimal("0")
    for item in template.get("items", []):
        ans = answers.get(item.get("item_key"))
        if ans is None:
            continue
        value = ans.get("answer_value")
        if value == "NA" or value is None:
            continue
        if value not in ANSWER_SCORE:
            continue
        weight = dec(item.get("weight", 0))
        earned += weight * ANSWER_SCORE[value]
        possible += weight
    if possible == 0:
        return Decimal("0.00")
    return round2(Decimal("100") * earned / possible)


def questionnaire_final(template, response):
    """Final variant: raw minus revision penalty
    min(raw * 5% * revision_count, 20), rounded half-up 2dp."""
    raw = questionnaire_raw(template, response)
    penalty = raw * REVISION_PENALTY_PCT * dec(response.get("revision_count", 0))
    if penalty > REVISION_PENALTY_CAP:
        penalty = REVISION_PENALTY_CAP
    return raw, round2(raw - penalty)


# ---- evidence_review_score ---------------------------------------------------
GAP_PENALTY_MAX = Decimal("30.0")
EVIDENCE_BASE = {"SOC2_TYPE2": Decimal("100"), "ISO27001": Decimal("95"),
                 "SOC2_TYPE1": Decimal("80"), "PENTEST": Decimal("70"),
                 "OTHER": Decimal("50")}
SEVERITY_WEIGHT = {"CRITICAL": Decimal("25"), "HIGH": Decimal("15"),
                   "MEDIUM": Decimal("8"), "LOW": Decimal("3")}


def evidence_review_score(cycle):
    """Average of per-kind base minus coverage-gap penalty (strict 180-day
    normalisation for TIER_3/4, 365-day otherwise), minus severity deductions
    for EVIDENCE-source exceptions still OPEN / IN_REMEDIATION. REJECTED
    artifacts are excluded entirely; never below zero."""
    artifacts = [a for a in db.artifacts.values()
                 if a["cycle_id"] == cycle["id"]
                 and a["status"] in ("REVIEWED_CLEAN", "REVIEWED_WITH_EXCEPTIONS")]
    if not artifacts:
        return Decimal("0.00")
    strict = cycle.get("tier_at_issue") in ("TIER_3", "TIER_4")
    cap = 180 if strict else 365
    adjusted = []
    for a in artifacts:
        gap = a.get("coverage_gap_days") or 0
        penalty = dec(min(gap, cap)) / dec(cap) * GAP_PENALTY_MAX
        adjusted.append(EVIDENCE_BASE[a["kind"]] - penalty)
    avg_adj = sum(adjusted) / dec(len(adjusted))
    deductions = Decimal("0")
    for e in db.exceptions.values():
        if (e["cycle_id"] == cycle["id"] and e["source"] == "EVIDENCE"
                and e["status"] in ("OPEN", "IN_REMEDIATION")):
            deductions += SEVERITY_WEIGHT[e["severity"]]
    result = round2(avg_adj - deductions)
    return result if result > 0 else Decimal("0.00")


# ---- composite_cycle_score ---------------------------------------------------
W_Q = Decimal("0.40")
W_E = Decimal("0.60")


def composite_cycle_score(cycle):
    return round2(W_Q * dec(cycle["questionnaire_score"])
                  + W_E * dec(cycle["evidence_score"]))


def recompute_acceptance_required(cycle):
    """True when composite < tier pass threshold OR any exception in this
    cycle was closed through an approved risk acceptance."""
    if cycle.get("composite_score") is None or cycle.get("tier_at_issue") is None:
        below = False
    else:
        below = dec(cycle["composite_score"]) < PASS_THRESHOLD[cycle["tier_at_issue"]]
    accepted = any(
        e["cycle_id"] == cycle["id"] and e["status"] == "CLOSED_ACCEPTED"
        for e in db.exceptions.values()
    )
    cycle["acceptance_required"] = bool(below or accepted)


# ---- vendor_risk_score --------------------------------------------------------
RISK_BASE = {"ONBOARDING": Decimal("50"), "ASSESSING": Decimal("60"),
             "APPROVED": Decimal("20"), "CONDITIONAL": Decimal("45"),
             "SUSPENDED": Decimal("85"), "OFFBOARDING": Decimal("70"),
             "OFFBOARDED": Decimal("10")}
ALERT_HIGH = Decimal("5")
ALERT_CRITICAL = Decimal("10")
ACCEPTED_PER = Decimal("3")
EXPIRY_IMMINENT = Decimal("8")
EXPIRY_WINDOW_DAYS = 30


def vendor_risk_score(vendor, now):
    risk = RISK_BASE[vendor["posture"]]
    for a in db.alerts.values():
        if a["vendor_id"] != vendor["id"] or a["status"] not in ("OPEN", "ACKNOWLEDGED"):
            continue
        if a["severity"] == "CRITICAL":
            risk += ALERT_CRITICAL
        elif a["severity"] == "HIGH":
            risk += ALERT_HIGH
    approved_cycles = [c for c in db.cycles.values()
                       if c["vendor_id"] == vendor["id"] and c["status"] == "APPROVED"]
    if approved_cycles:
        latest = max(approved_cycles, key=lambda c: c["_seq"])
        for e in db.exceptions.values():
            if e["cycle_id"] == latest["id"] and e["status"] == "CLOSED_ACCEPTED":
                risk += ACCEPTED_PER
    horizon = now + timedelta(days=EXPIRY_WINDOW_DAYS)
    cycle_ids = {c["id"] for c in db.cycles.values() if c["vendor_id"] == vendor["id"]}
    for r in db.acceptances.values():
        if r["cycle_id"] not in cycle_ids or r["status"] != "APPROVED":
            continue
        try:
            expires = util.parse_dt(r["expires_at"])
        except (ValueError, TypeError):
            continue
        if expires < horizon:
            risk += EXPIRY_IMMINENT
    if risk < 0:
        risk = Decimal("0")
    if risk > 100:
        risk = Decimal("100")
    return round2(risk)


# ---- addendum_requirement ------------------------------------------------------
BASE_CLAUSES = {
    "TIER_1": {"C_DPA"},
    "TIER_2": {"C_DPA", "C_BREACH_NOTIFY"},
    "TIER_3": {"C_DPA", "C_BREACH_NOTIFY", "C_AUDIT_RIGHT"},
    "TIER_4": {"C_DPA", "C_BREACH_NOTIFY", "C_AUDIT_RIGHT",
               "C_ENCRYPTION", "C_SUBPROCESSOR_FLOWDOWN"},
}


def addendum_clause_set(cycle):
    """Sorted union of tier base clauses and exception-driven clauses;
    HIGH -> C_REMEDIATION_TIMELINE, CRITICAL -> C_TERMINATION_RIGHT."""
    clauses = set(BASE_CLAUSES.get(cycle.get("tier_at_issue"), {"C_DPA"}))
    for e in db.exceptions.values():
        if e["cycle_id"] != cycle["id"]:
            continue
        if e["severity"] == "HIGH":
            clauses.add("C_REMEDIATION_TIMELINE")
        elif e["severity"] == "CRITICAL":
            clauses.add("C_TERMINATION_RIGHT")
    return sorted(clauses)


# ---- tier_response_window ------------------------------------------------------
RESPONSE_WINDOW_DAYS = {"TIER_1": 45, "TIER_2": 30, "TIER_3": 21, "TIER_4": 14}


def response_due(issued_at, tier):
    return issued_at + timedelta(days=RESPONSE_WINDOW_DAYS[tier])


# ---- escalation_pull_forward ----------------------------------------------------
DELTA_CRITICAL_DAYS = 14
DELTA_HIGH_DAYS = 30
DELTA_ACCEPTANCE_EXPIRY_DAYS = 30


def pull_forward(existing_due, candidate):
    """min semantics: never moves the due date later than its current value."""
    if existing_due is None:
        return candidate
    return candidate if candidate < existing_due else existing_due
