"""Calculation rules (PRD 2.6, 3.3, 3.5, 3.7, 3.8, 3.9)."""
from datetime import timedelta
from decimal import Decimal

from common import (DB, ceil_int, clock_now, dec, get, parse_dt, q2, rows,
                    sort_key, sorted_rows)

EXCLUDED = object()

# --- analytics_priority_score constants (PRD 3.3) -------------------------
SILENCE_WEIGHT = Decimal("0.45")
SENTIMENT_WEIGHT = Decimal("0.35")
CATEGORY_POINTS = {
    "PROFANITY": Decimal(25),
    "NO_DISCLOSURE": Decimal(30),
    "ESCALATION_REQUEST": Decimal(15),
    "CONSENT_OBJECTION": Decimal(40),
}
CHANNEL_MULTIPLIER = {
    "VOICE": Decimal("1.20"),
    "CHAT": Decimal("1.00"),
    "EMAIL": Decimal("0.80"),
}
DISCLOSURE_GAP_BONUS = Decimal(15)

# --- other constants -----------------------------------------------------
HIGH_SCORE_FLOOR = Decimal("85.00")
CSAT_IMPUTED_DEFAULT = Decimal(3)
ROLLING_WINDOW_SIZE = 4
VARIANCE_ALIGNED_MAX = Decimal("7.00")
VARIANCE_SEVERE_MAX = Decimal("15.00")
ALIGNED_MAX = Decimal("3.00")
MIN_PARTICIPANTS = 2
DISPUTE_WINDOW_DAYS = 7
MAX_DISPUTE_ROUNDS = 2
ESCALATION_FINDING_THRESHOLD = 2
DEFAULT_MAX_OPEN_ASSIGNMENTS = 3
RECOGNITION_MIN_EVALUATIONS = 2
RECOGNITION_MIN_INDEX = Decimal("92.00")
COACHING_TIERS = {
    "T1": {"multiplier": Decimal("1.00"), "session_gain": Decimal("2.50"), "due_days": 30},
    "T2": {"multiplier": Decimal("1.25"), "session_gain": Decimal("2.00"), "due_days": 45},
    "T3": {"multiplier": Decimal("1.50"), "session_gain": Decimal("1.50"), "due_days": 60},
}
TIER_BUMP = {"T1": "T2", "T2": "T3", "T3": "T3"}
SCORED_REVIEW_STATUSES = ("SUBMITTED", "FINALIZED", "REOPENED")
LIVE_SELECTION_STATUSES = ("SELECTED", "ASSIGNED", "EVALUATED")
SOURCES = ("RANDOM", "TARGETED", "CUSTOMER_FLAGGED")
SOURCE_MIX_KEYS = {
    "RANDOM": "random_pct",
    "TARGETED": "targeted_pct",
    "CUSTOMER_FLAGGED": "customer_flagged_pct",
}


def form_behaviors(form_id):
    """The behaviour rows of one form, iterated in code ASC order."""
    items = [b for b in rows("behaviors") if b["form_id"] == form_id]
    return sorted(items, key=lambda b: b["code"])


# ==========================================================================
# evaluation_weighted_score (PRD 3.5)
# ==========================================================================

def evaluation_weighted_score(form, behaviors, items):
    """Returns dict(weighted_score, raw_weighted_score, auto_fail_triggered,
    compliance_result).  weighted_score is the RENORMALIZED variant,
    raw_weighted_score the FIXED_DENOMINATOR variant."""
    contrib_renorm = {}
    contrib_fixed = {}

    # STEP 1 -- per-behaviour contribution, rounded once per behaviour.
    for b in behaviors:
        value = items.get(b["code"])
        if value == "NA":
            contrib_renorm[b["code"]] = EXCLUDED
            contrib_fixed[b["code"]] = q2(dec(b["weight_pct"]))
        else:
            pct = Decimal(value) / Decimal(b["max_points"])
            contribution = q2(dec(b["weight_pct"]) * pct)
            contrib_renorm[b["code"]] = contribution
            contrib_fixed[b["code"]] = contribution

    # STEP 2 -- automatic-fail reshaping.
    auto_fail = False
    for b in behaviors:
        value = items.get(b["code"])
        if b.get("auto_fail_on_violation") and value != "NA" and value == 0:
            auto_fail = True
            break
    if auto_fail and form["auto_fail_policy"] == "COMPLIANCE_SECTION_ZERO":
        for b in behaviors:
            if b.get("compliance_critical"):
                if contrib_renorm[b["code"]] is not EXCLUDED:
                    contrib_renorm[b["code"]] = Decimal("0.00")
                contrib_fixed[b["code"]] = Decimal("0.00")

    # STEP 3 -- aggregate, renormalise, round again.
    applicable_weight = Decimal(0)
    numerator = Decimal(0)
    for b in behaviors:
        if contrib_renorm[b["code"]] is not EXCLUDED:
            applicable_weight += dec(b["weight_pct"])
            numerator += contrib_renorm[b["code"]]
    fixed_total = Decimal(0)
    for b in behaviors:
        fixed_total += contrib_fixed[b["code"]]

    if applicable_weight == 0:
        weighted = None
        raw = q2(fixed_total)
    else:
        weighted = q2(numerator * Decimal(100) / applicable_weight)
        raw = q2(fixed_total)

    # STEP 4 -- total zeroing.
    if auto_fail and form["auto_fail_policy"] == "ZERO_TOTAL":
        if weighted is not None:
            weighted = Decimal("0.00")
        raw = Decimal("0.00")

    # STEP 5 -- compliance verdict.
    compliance = "PASS"
    if auto_fail:
        compliance = "FAIL"
    else:
        for b in behaviors:
            value = items.get(b["code"])
            if (b.get("compliance_critical") and value != "NA"
                    and Decimal(value) < Decimal(form["min_compliance_item_score"])):
                compliance = "FAIL"
                break

    # EDGE -- every behaviour marked "NA".
    if applicable_weight == 0:
        weighted = None
        raw = Decimal("100.00")
        compliance = "NOT_EVALUATED"

    return {
        "weighted_score": weighted,
        "raw_weighted_score": raw,
        "auto_fail_triggered": auto_fail,
        "compliance_result": compliance,
    }


def renormalized_score(form, behaviors, items):
    return evaluation_weighted_score(form, behaviors, items)["weighted_score"]


# ==========================================================================
# analytics_priority_score (PRD 3.3)
# ==========================================================================

def analytics_priority_score(silence_pct, sentiment_delta, flagged_categories,
                             interaction):
    sentiment_penalty = -dec(sentiment_delta)
    if sentiment_penalty < 0:
        sentiment_penalty = Decimal(0)
    base = (dec(silence_pct) * SILENCE_WEIGHT
            + sentiment_penalty * Decimal(100) * SENTIMENT_WEIGHT)
    for category in flagged_categories:
        base += CATEGORY_POINTS[category]
    if base > Decimal(100):
        base = Decimal(100)

    required = interaction.get("required_disclosures") or []
    captured = interaction.get("captured_disclosures") or []
    gap = Decimal(0)
    if required and any(code not in captured for code in required):
        gap = DISCLOSURE_GAP_BONUS

    value = base * CHANNEL_MULTIPLIER[interaction["channel"]] + gap
    if value > Decimal("100.00"):
        value = Decimal("100.00")
    risk = q2(value)

    if risk >= Decimal("70.00"):
        tier = "P1"
    elif risk >= Decimal("40.00"):
        tier = "P2"
    else:
        tier = "P3"
    return risk, tier


# ==========================================================================
# agent_quality_index (PRD 3.6)
# ==========================================================================

def effective_score(ev):
    if ev.get("adjusted_weighted_score") is not None:
        return dec(ev["adjusted_weighted_score"])
    return dec(ev["weighted_score"])


def scored_evaluations(agent_id):
    out = []
    for ev in rows("evaluations"):
        if ev["agent_id"] != agent_id:
            continue
        if ev["review_status"] not in SCORED_REVIEW_STATUSES:
            continue
        if ev.get("weighted_score") is None:
            continue
        out.append(ev)
    return sorted_rows(out)


def _submitted_key(ev):
    stamp = ev.get("submitted_at") or ""
    return (stamp, ev["created_at"], ev["_seq"])


def quality_index_rolling(agent_id):
    input_set = scored_evaluations(agent_id)
    if not input_set:
        return None
    ordered = sorted(input_set, key=_submitted_key, reverse=True)
    window = ordered[:min(ROLLING_WINDOW_SIZE, len(ordered))]
    total = sum((effective_score(e) for e in window), Decimal(0))
    return q2(total / Decimal(len(window)))


def open_plan_for_clock():
    """The OPEN SamplePlan whose CLOSED period interval covers the clock."""
    now = clock_now()
    candidates = []
    for plan in rows("plans"):
        if plan["status"] != "OPEN":
            continue
        start = parse_dt(plan["period_start"])
        end = parse_dt(plan["period_end"])
        if start <= now <= end:
            candidates.append(plan)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (parse_dt(p["period_start"]), p["created_at"], p["_seq"]))
    return candidates[0]


def evaluation_interaction(ev):
    selection = get("selections", ev["selection_id"])
    if selection is None:
        return None
    return get("interactions", selection["interaction_id"])


def quality_index_period(agent_id):
    plan = open_plan_for_clock()
    if plan is None:
        return None
    start = parse_dt(plan["period_start"])
    end = parse_dt(plan["period_end"])
    numerator = Decimal(0)
    denominator = 0
    empty = True
    for ev in scored_evaluations(agent_id):
        interaction = evaluation_interaction(ev)
        if interaction is None:
            continue
        started = parse_dt(interaction["started_at"])
        if not (start <= started <= end):
            continue
        empty = False
        seconds = int(interaction["duration_seconds"])
        numerator += effective_score(ev) * Decimal(seconds)
        denominator += seconds
    if empty or denominator == 0:
        return None
    return q2(numerator / Decimal(denominator))


def _passing(ev):
    if ev.get("compliance_result") != "PASS":
        return False
    if ev.get("weighted_score") is None and ev.get("adjusted_weighted_score") is None:
        return False
    return effective_score(ev) >= HIGH_SCORE_FLOOR


def consecutive_passing_evaluations(agent_id):
    """Length of the trailing run (submitted_at ASC, created_at ASC) of
    evaluations whose compliance_result is PASS and whose effective score is
    at least 85.00 (PRD 3.5)."""
    scored = [ev for ev in rows("evaluations")
              if ev["agent_id"] == agent_id
              and ev["review_status"] in SCORED_REVIEW_STATUSES]
    ordered = sorted(scored, key=_submitted_key)
    run = 0
    for ev in reversed(ordered):
        if _passing(ev):
            run += 1
        else:
            break
    return run


# ==========================================================================
# agent_quality_correlation (PRD 3.6)
# ==========================================================================

def agent_quality_correlation(agent_id):
    input_set = scored_evaluations(agent_id)
    considered = len(input_set)
    if considered == 0:
        return {
            "evaluations_considered": 0,
            "paired_sample_size": 0,
            "csat_gap_paired": None,
            "csat_gap_all": None,
            "repeat_contact_rate": None,
        }

    high, low = [], []
    paired = 0
    repeats = 0
    for ev in input_set:
        interaction = evaluation_interaction(ev)
        csat = None if interaction is None else interaction.get("csat_score")
        if csat is not None:
            paired += 1
        if interaction is not None and interaction.get("repeat_contact_within_72h"):
            repeats += 1
        bucket = high if effective_score(ev) >= HIGH_SCORE_FLOOR else low
        bucket.append(csat)

    def mean_of(values):
        present = [dec(v) for v in values if v is not None]
        if not present:
            return None
        return q2(sum(present, Decimal(0)) / Decimal(len(present)))

    def mean_imputed(values):
        if not values:
            return None
        filled = [dec(v) if v is not None else CSAT_IMPUTED_DEFAULT for v in values]
        return q2(sum(filled, Decimal(0)) / Decimal(len(filled)))

    h, l = mean_of(high), mean_of(low)
    gap_paired = None if h is None or l is None else q2(h - l)
    hi, li = mean_imputed(high), mean_imputed(low)
    gap_all = None if hi is None or li is None else q2(hi - li)

    return {
        "evaluations_considered": considered,
        "paired_sample_size": paired,
        "csat_gap_paired": gap_paired,
        "csat_gap_all": gap_all,
        "repeat_contact_rate": q2(Decimal(repeats) * Decimal(100) / Decimal(considered)),
    }


# ==========================================================================
# coaching_requirement (PRD 3.7)
# ==========================================================================

def coaching_requirement(target_score, rolling_index, open_findings):
    """Returns (deficit_pct, tier, adjusted_deficit, session_count, due_at,
    escalation_tier) or None when the deficit is not positive."""
    deficit = q2(dec(target_score) - dec(rolling_index))
    if deficit <= Decimal("0.00"):
        return None
    if deficit <= Decimal("5.00"):
        tier = "T1"
    elif deficit <= Decimal("12.00"):
        tier = "T2"
    else:
        tier = "T3"
    spec = COACHING_TIERS[tier]
    adjusted = q2(deficit * spec["multiplier"])
    count = ceil_int(adjusted / spec["session_gain"])
    if count < 1:
        count = 1
    if count > 8:
        count = 8
    due_at = clock_now() + timedelta(days=spec["due_days"])
    escalation_tier = TIER_BUMP[tier] if int(open_findings or 0) >= 1 else tier
    return {
        "deficit_pct": deficit,
        "tier": tier,
        "adjusted_deficit": adjusted,
        "required_session_count": count,
        "due_at": due_at,
        "escalation_tier": escalation_tier,
    }


# ==========================================================================
# calibration_variance (PRD 3.8)
# ==========================================================================

def alignment_band(abs_dev):
    if abs_dev <= ALIGNED_MAX:
        return "ALIGNED"
    if abs_dev <= VARIANCE_ALIGNED_MAX:
        return "MINOR_VARIANCE"
    return "MAJOR_VARIANCE"


def session_submissions(session_id):
    items = [s for s in rows("submissions") if s["session_id"] == session_id]
    return sorted_rows(items)


def calibration_variance(session):
    """Returns (outcome, participant_count, variance_pct, mean_abs_deviation,
    per-submission [(submission, deviation_pct, alignment)])."""
    submissions = session_submissions(session["id"])
    count = len(submissions)
    benchmark = dec(session["benchmark_weighted_score"])
    details = []
    for s in submissions:
        deviation = q2(dec(s["weighted_score"]) - benchmark)
        details.append((s, deviation, alignment_band(abs(deviation))))
    if count < MIN_PARTICIPANTS:
        return {
            "outcome": "VOID",
            "participant_count": count,
            "variance_pct": None,
            "mean_abs_deviation": None,
            "details": [],
        }
    variance = q2(max(abs(d) for (_s, d, _a) in details))
    mean_abs = q2(sum((abs(d) for (_s, d, _a) in details), Decimal(0)) / Decimal(count))
    outcome = "CLOSED_ALIGNED" if variance <= VARIANCE_ALIGNED_MAX else "CLOSED_VARIANT"
    return {
        "outcome": outcome,
        "participant_count": count,
        "variance_pct": variance,
        "mean_abs_deviation": mean_abs,
        "details": details,
    }


def next_calibration_status(current, deviation, alignment):
    if abs(deviation) > VARIANCE_SEVERE_MAX:
        return "SUSPENDED"
    if alignment == "MAJOR_VARIANCE" and current == "CALIBRATED":
        return "PROBATION"
    if alignment == "MAJOR_VARIANCE" and current == "PROBATION":
        return "SUSPENDED"
    if alignment == "ALIGNED" and current == "PROBATION":
        return "CALIBRATED"
    return current


# ==========================================================================
# sample_quota_attainment (PRD 3.4)
# ==========================================================================

def plan_source_caps(plan, agent_id):
    volume = int(plan["per_agent_target_volume"])
    mix = plan["source_mix"]
    base = {}
    for source in SOURCES:
        pct = int(mix[SOURCE_MIX_KEYS[source]])
        base[source] = (volume * pct) // 100
    remainder = volume - sum(base.values())
    reserve = int((plan.get("targeted_reserve_by_agent") or {}).get(agent_id, 0))
    caps = {
        "RANDOM": base["RANDOM"] + remainder,
        "TARGETED": base["TARGETED"] + reserve,
        "CUSTOMER_FLAGGED": base["CUSTOMER_FLAGGED"],
    }
    return caps, reserve


def plan_selections(plan_id):
    return sorted_rows([s for s in rows("selections") if s["plan_id"] == plan_id])


def consumed_by_source(plan_id, agent_id):
    counts = {source: 0 for source in SOURCES}
    for sel in rows("selections"):
        if sel["plan_id"] != plan_id or sel["agent_id"] != agent_id:
            continue
        if sel["status"] in LIVE_SELECTION_STATUSES:
            counts[sel["source"]] += 1
    return counts


def sample_quota_attainment(plan):
    volume = int(plan["per_agent_target_volume"])
    reserves = plan.get("targeted_reserve_by_agent") or {}
    agent_ids = []
    for sel in plan_selections(plan["id"]):
        if sel["agent_id"] not in agent_ids:
            agent_ids.append(sel["agent_id"])
    for agent_id in reserves:
        if agent_id not in agent_ids:
            agent_ids.append(agent_id)

    attainment = {}
    for agent_id in agent_ids:
        counts = consumed_by_source(plan["id"], agent_id)
        consumed = sum(counts.values())
        reserve = int(reserves.get(agent_id, 0))
        attainment[agent_id] = {
            "consumed": consumed,
            "remaining": volume + reserve - consumed,
            "by_source": {source: counts[source] for source in SOURCES},
        }

    selections_count = 0
    excluded_count = 0
    for sel in rows("selections"):
        if sel["plan_id"] != plan["id"]:
            continue
        if sel["status"] in LIVE_SELECTION_STATUSES:
            selections_count += 1
        elif sel["status"] == "EXCLUDED":
            excluded_count += 1

    return {
        "agent_volume_attainment": attainment,
        "selections_count": selections_count,
        "excluded_count": excluded_count,
        "targeted_reserved_count": sum(int(v) for v in reserves.values()),
    }


# ==========================================================================
# evaluator_load (PRD 3.9)
# ==========================================================================

def open_assignment_count(evaluator_id):
    return sum(1 for sel in rows("selections")
               if sel.get("assigned_evaluator_id") == evaluator_id
               and sel["status"] == "ASSIGNED")


def last_deviation_pct(evaluator_id):
    items = [s for s in rows("submissions") if s["evaluator_id"] == evaluator_id]
    if not items:
        return None
    latest = max(items, key=sort_key)
    return latest.get("deviation_pct")


def interaction_sampled_count(interaction_id):
    return sum(1 for sel in rows("selections")
               if sel["interaction_id"] == interaction_id
               and sel["status"] in LIVE_SELECTION_STATUSES)


def open_compliance_findings(agent_id):
    """Count of that agent's interactions carrying compliance_hold (PRD 3.5)."""
    return sum(1 for it in rows("interactions")
               if it["agent_id"] == agent_id and it.get("compliance_hold"))
