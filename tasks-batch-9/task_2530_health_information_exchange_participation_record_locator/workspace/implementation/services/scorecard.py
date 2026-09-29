"""Participant data quality scorecard (PRD 3.6)."""
from decimal import Decimal

from db import clock, commit, db, fmt_dt, parse_iso, plus_days, snapshot
from services import repo
from services.precision import ZERO, dec, out, rhu2

QUALITY_WINDOW_DAYS = 90
QUALITY_SAMPLE_LIMIT = 6
FEED_DEGRADED_REJECT_RATE = Decimal("0.0500")
PENALTY_BY_PROVISIONAL_GRADE = {"A": 0, "B": 1, "C": 3, "D": 6}
QUALIFYING_FEED_STATUSES = ("MONITORED", "DEGRADED")

WEIGHT_COMPLETENESS = Decimal("0.30")
WEIGHT_REJECTION = Decimal("0.30")
WEIGHT_DUPLICATE = Decimal("0.15")
WEIGHT_TIMELINESS = Decimal("0.25")

HUNDRED = Decimal(100)


def grade_for(score):
    if score >= Decimal("92"):
        return "A"
    if score >= Decimal("84"):
        return "B"
    if score >= Decimal("70"):
        return "C"
    return "D"


def timeliness_component(average_p95):
    if average_p95 <= Decimal("300"):
        return Decimal("100")
    if average_p95 <= Decimal("900"):
        return Decimal("85")
    if average_p95 <= Decimal("3600"):
        return Decimal("60")
    return Decimal("30")


def qualifying_samples(participant_id, exclude_feed_ids=()):
    """Newest six samples inside the ninety day window (PRD 3.6)."""
    moment = clock()
    window_start = plus_days(moment, -QUALITY_WINDOW_DAYS)
    feed_ids = set()
    for feed in repo.participant_feeds(participant_id):
        if feed["id"] in exclude_feed_ids:
            continue
        if feed["status"] in QUALIFYING_FEED_STATUSES:
            feed_ids.add(feed["id"])
    rows = []
    for sample in db.samples.values():
        if sample["data_feed_id"] not in feed_ids:
            continue
        period_end = parse_iso(sample["period_end"])
        if period_end is None:
            continue
        if period_end > window_start and period_end <= moment:
            rows.append((period_end, sample))
    # Descending period_end, ties broken by ascending created_at: sort by the
    # tie-break first, then stable-sort by the primary key.
    rows.sort(key=lambda pair: (pair[1]["created_at"], pair[1]["_seq"]))
    rows.sort(key=lambda pair: pair[0], reverse=True)
    ordered = [pair[1] for pair in rows]
    return ordered[:QUALITY_SAMPLE_LIMIT], window_start, moment


def compute(participant_id, exclude_feed_ids=()):
    samples, window_start, window_end = qualifying_samples(
        participant_id, exclude_feed_ids
    )
    result = {
        "participant_id": participant_id,
        "window_start": fmt_dt(window_start),
        "window_end": fmt_dt(window_end),
        "samples_counted": len(samples),
    }
    if not samples:
        result.update(
            {
                "completeness_component": 0,
                "rejection_component": 0,
                "duplicate_component": 0,
                "timeliness_component": 0,
                "average_p95_seconds": 0,
                "base_quality_score": 0,
                "provisional_grade": "UNGRADED",
                "penalty_points": 0,
                "quality_score": None,
                "grade": "UNGRADED",
            }
        )
        return result

    received = sum(int(s["messages_received"] or 0) for s in samples)
    rejected = sum(int(s["messages_rejected"] or 0) for s in samples)
    missing = sum(int(s["required_fields_missing_count"] or 0) for s in samples)
    duplicates = sum(int(s["duplicate_count"] or 0) for s in samples)
    p95_total = sum(dec(s["timeliness_p95_seconds"]) for s in samples)

    denominator = Decimal(max(1, received))
    completeness = HUNDRED * (Decimal(1) - Decimal(missing) / denominator)
    rejection = HUNDRED * (Decimal(1) - Decimal(rejected) / denominator)
    duplicate = HUNDRED * (Decimal(1) - Decimal(duplicates) / denominator)
    average_p95 = rhu2(p95_total / Decimal(len(samples)))
    timeliness = timeliness_component(average_p95)

    base = rhu2(
        WEIGHT_COMPLETENESS * completeness
        + WEIGHT_REJECTION * rejection
        + WEIGHT_DUPLICATE * duplicate
        + WEIGHT_TIMELINESS * timeliness
    )
    provisional_grade = grade_for(base)
    penalty = PENALTY_BY_PROVISIONAL_GRADE[provisional_grade]
    final = rhu2(base - Decimal(penalty))
    final_grade = grade_for(final)

    result.update(
        {
            "completeness_component": out(completeness),
            "rejection_component": out(rejection),
            "duplicate_component": out(duplicate),
            "timeliness_component": out(timeliness),
            "average_p95_seconds": out(average_p95),
            "base_quality_score": out(base),
            "provisional_grade": provisional_grade,
            "penalty_points": penalty,
            "quality_score": out(final),
            "grade": final_grade,
        }
    )
    return result


def apply_to_participant(participant, exclude_feed_ids=()):
    """Rewrite the participant's stored quality_score / quality_grade."""
    card = compute(participant["id"], exclude_feed_ids)
    participant["quality_score"] = card["quality_score"]
    participant["quality_grade"] = card["grade"]
    return card


def refresh(participant, exclude_feed_ids=()):
    before = snapshot(participant)
    apply_to_participant(participant, exclude_feed_ids)
    commit(participant, before)
