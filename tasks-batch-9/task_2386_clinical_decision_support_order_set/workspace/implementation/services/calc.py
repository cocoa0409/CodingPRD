"""Every derived number in the system (PRD §2.5 precision discipline + §3 formulas).

All arithmetic is decimal and rounded half-up.
"""
from decimal import Decimal, ROUND_HALF_UP

import const

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def q(value, exp):
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, TWO)


def q4(value):
    return q(value, FOUR)


# ------------------------------------------------------ content request priority
def intake_provisional_score(evidence_grade, urgency, patient_safety_flag):
    total = (
        Decimal(const.EVIDENCE_GRADE_POINTS[evidence_grade])
        + Decimal(const.URGENCY_POINTS[urgency])
        + (Decimal(const.SAFETY_FLAG_POINTS) if patient_safety_flag else Decimal(0))
    )
    return min(const.SCORE_CAP, q2(total))


def committee_calibrated_score(peer_reviewed_count, urgency, patient_safety_flag, created_at, current):
    citation_component = min(
        Decimal(const.CITATION_COMPONENT_CAP),
        Decimal(const.CITATION_POINTS_PER_PEER_REVIEWED) * Decimal(peer_reviewed_count),
    )
    base = (
        citation_component
        + Decimal(const.URGENCY_POINTS[urgency])
        + (Decimal(const.SAFETY_FLAG_POINTS) if patient_safety_flag else Decimal(0))
    )
    elapsed = (current - created_at).total_seconds()
    backlog_days = int(Decimal(str(elapsed)) // Decimal(86400)) if elapsed > 0 else 0
    if backlog_days < 0:
        backlog_days = 0
    bonus = min(const.BACKLOG_AGE_BONUS_CAP, q4(const.BACKLOG_AGE_BONUS_PER_DAY * Decimal(backlog_days)))
    product = base * (Decimal(1) + bonus)
    return min(const.SCORE_CAP, q2(product))


def peer_reviewed_count(citations):
    return sum(1 for c in citations if c.get("peer_reviewed") is True)


def evidence_clears_acceptance_bar(citations, patient_safety_flag, urgency):
    total = len(citations)
    reviewed = peer_reviewed_count(citations)
    if total < const.MIN_CITATIONS_FOR_ACCEPT:
        return False
    if reviewed < const.MIN_PEER_REVIEWED_FOR_ACCEPT:
        return False
    if patient_safety_flag or urgency == "SAFETY_URGENT":
        if reviewed < const.MIN_PEER_REVIEWED_FOR_SAFETY:
            return False
    return True


# ------------------------------------------------------ burden index
def _index(rate, tier_multiplier, volume_factor):
    product = rate * tier_multiplier * volume_factor * Decimal(100)
    return min(const.BURDEN_INDEX_CAP, q2(product))


def burden_metrics(fire_count, override_count, distinct_fired, distinct_overriding, severity_tier):
    tier_multiplier = const.TIER_MULTIPLIER[severity_tier]

    if fire_count == 0:
        override_rate = Decimal("0.0000")
    else:
        override_rate = q4(Decimal(override_count) / Decimal(fire_count))
    volume_factor = min(
        const.VOLUME_FACTOR_CAP,
        q4(Decimal(fire_count) / Decimal(const.EXPECTED_FIRES_PER_WINDOW)),
    )
    burden_index = _index(override_rate, tier_multiplier, volume_factor)

    if distinct_fired == 0:
        clinician_rate = Decimal("0.0000")
    else:
        clinician_rate = q4(Decimal(distinct_overriding) / Decimal(distinct_fired))
    clinician_volume = min(
        const.VOLUME_FACTOR_CAP,
        q4(Decimal(distinct_fired) / Decimal(const.EXPECTED_CLINICIANS_PER_WINDOW)),
    )
    clinician_index = _index(clinician_rate, tier_multiplier, clinician_volume)

    if fire_count == 0:
        classification = "NO_SIGNAL"
    elif burden_index >= const.LOW_VALUE_INDEX_THRESHOLD:
        classification = "LOW_VALUE"
    elif burden_index <= const.HIGH_VALUE_INDEX_CEILING:
        classification = "HIGH_VALUE"
    else:
        classification = "MONITOR"

    return {
        "override_rate": override_rate,
        "volume_factor": volume_factor,
        "burden_index": burden_index,
        "burden_index_clinician_weighted": clinician_index,
        "burden_classification": classification,
    }


# ------------------------------------------------------ adherence
def per_protocol_pct(rows):
    included = [r for r in rows if r["eligible_orders"] > 0]
    if not included:
        return None
    total = Decimal(0)
    for row in included:
        total += q4(Decimal(row["adherent_orders"]) / Decimal(row["eligible_orders"]))
    mean = total / Decimal(len(included))
    return q2(mean * Decimal(100))


def intention_to_treat_pct(rows):
    included = [r for r in rows if r["eligible_orders"] > 0]
    if not included:
        return None
    adherent = sum(r["adherent_orders"] for r in included)
    eligible = sum(r["eligible_orders"] for r in included)
    if eligible == 0:
        return None
    return q2(Decimal(100) * Decimal(adherent) / Decimal(eligible))


def unintended_rate_per_100(rows):
    included = [r for r in rows if r["eligible_orders"] > 0]
    if not included:
        return None
    events = sum(r["unintended_events"] for r in included)
    eligible = sum(r["eligible_orders"] for r in included)
    if eligible == 0:
        return None
    return q2(Decimal(const.UNINTENDED_RATE_BASIS) * Decimal(events) / Decimal(eligible))


def verdict_supported(verdict, itt, rate):
    if verdict == "REVISE":
        return True
    if itt is None or rate is None:
        return False
    if verdict == "SUSTAIN":
        return itt >= const.ADHERENCE_SUCCESS_FLOOR and rate <= const.UNINTENDED_RATE_CEILING
    if verdict == "RETIRE":
        return itt < const.ADHERENCE_SUCCESS_FLOOR or rate > const.UNINTENDED_RATE_CEILING
    return False


# ------------------------------------------------------ quorum
def approve_ratio(approve_count, cast_count):
    if cast_count == 0:
        return None
    return q4(Decimal(approve_count) / Decimal(cast_count))


def required_votes(risk_class, evidence_concern_count):
    base = const.BASE_REQUIRED_VOTES[risk_class]
    if evidence_concern_count >= 1:
        base += const.EVIDENCE_CONCERN_VOTE_BUMP
    return min(const.MAX_REQUIRED_VOTES, base)


def quorum_met(risk_class, cast_count, approve_count, reject_count, needed):
    if cast_count < needed:
        return False
    ratio = approve_ratio(approve_count, cast_count)
    if ratio is None or ratio < const.REQUIRED_APPROVAL_RATIO[risk_class]:
        return False
    return reject_count == 0


def alert_quorum_met(cast_count, approve_count, reject_count, needed):
    if cast_count < needed:
        return False
    ratio = approve_ratio(approve_count, cast_count)
    if ratio is None or ratio < const.ALERT_REQUIRED_APPROVAL_RATIO:
        return False
    return reject_count == 0


# ------------------------------------------------------ workload
def assignment_minutes(review_kind, risk_class_snapshot, severity_tier=None):
    if severity_tier is not None:
        return const.ALERT_REVIEW_MINUTES[severity_tier]
    return const.REVIEW_MINUTES[review_kind][risk_class_snapshot]


# ------------------------------------------------------ vendor impact
def delta_weight(change_type, new_severity):
    weight = const.DELTA_WEIGHTS[change_type]
    if new_severity == "CONTRAINDICATED":
        weight += const.HIGH_SEVERITY_BONUS
    return weight


def impact_branch(impact_score):
    if impact_score >= const.CLINICAL_REVIEW_THRESHOLD:
        return "IMPACT_ANALYZED_CLINICAL_REVIEW"
    return "IMPACT_ANALYZED_FAST_TRACK"
