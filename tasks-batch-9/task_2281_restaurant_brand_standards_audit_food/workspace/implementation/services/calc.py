"""Scoring arithmetic: section percents, penalties, composites, grades,
health-component selection, calibration bands and reliability scores.

Every rounding step is round-half-up to two decimals (PRD 2.6).
"""

from decimal import Decimal

import db
from common import clamp, days, dec, q2, set_if_changed, touch

SECTIONS = ("FOOD_SAFETY", "BRAND_STANDARDS", "FACILITY")

WEIGHT_FOOD_SAFETY = Decimal("0.50")
WEIGHT_BRAND_STANDARDS = Decimal("0.30")
WEIGHT_FACILITY = Decimal("0.20")

PROVISIONAL_WEIGHT_BASE = Decimal("0.60")
PROVISIONAL_WEIGHT_FOOD_SAFETY = Decimal("0.40")
FINAL_WEIGHT_BASE = Decimal("0.45")
FINAL_WEIGHT_FOOD_SAFETY = Decimal("0.30")
FINAL_WEIGHT_HEALTH = Decimal("0.25")

PASS_THRESHOLD = Decimal("90.00")
CONDITIONAL_THRESHOLD = Decimal("80.00")
CRITICAL_FAIL_COUNT = 2

HEALTH_LOOKBACK_DAYS = 180
REPEAT_LOOKBACK_DAYS = 365

BASELINE_RELIABILITY = Decimal("70.00")
ROLLING_DECAY = (Decimal("1.00"), Decimal("0.60"), Decimal("0.30"))
SUSPENSION_FLOOR = Decimal("60.00")
CERTIFICATION_FLOOR = Decimal("70.00")


# --------------------------------------------------------------------------
# Rubric / scored item helpers
# --------------------------------------------------------------------------

def rubric_items_of(rubric_version_id):
    return [
        item for item in db.store.rubric_items.values()
        if item["rubric_version_id"] == rubric_version_id
    ]


def scored_items_of(visit_id):
    items = [si for si in db.store.scored_items.values() if si["visit_id"] == visit_id]
    items.sort(key=db.sort_key)
    return items


def effective_points(scored):
    if scored["status"] == "AMENDED" and scored["amended_points_awarded"] is not None:
        return scored["amended_points_awarded"]
    return scored["points_awarded"]


def derive_scored_item(scored):
    """Re-derive effective_points_awarded, is_violation and severity."""
    rubric_item = db.store.rubric_items.get(scored["rubric_item_id"])
    max_points = rubric_item["max_points"] if rubric_item else 0
    effective = effective_points(scored)
    is_violation = effective < max_points
    if is_violation and rubric_item is not None and rubric_item["is_critical"]:
        severity = "CRITICAL"
    elif is_violation:
        severity = "STANDARD"
    else:
        severity = "NONE"
    scored["effective_points_awarded"] = effective
    scored["is_violation"] = is_violation
    scored["severity"] = severity
    return scored


# --------------------------------------------------------------------------
# visit_section_percent / visit_rubric_percent / critical_penalty_points
# --------------------------------------------------------------------------

def section_percents(visit):
    items = rubric_items_of(visit["rubric_version_id"])
    scored_by_item = {}
    for scored in scored_items_of(visit["id"]):
        scored_by_item[scored["rubric_item_id"]] = scored

    result = {}
    for section in SECTIONS:
        section_items = [i for i in items if i["section"] == section]
        section_items.sort(key=lambda i: i["display_order"])
        if not section_items:
            result[section] = q2(0)
            continue
        total = Decimal(0)
        for item in section_items:
            scored = scored_by_item.get(item["id"])
            awarded = effective_points(scored) if scored is not None else 0
            # PINNED ORDER: each item's percent is rounded to 2dp FIRST.
            total += q2(Decimal(awarded) / Decimal(item["max_points"]) * Decimal(100))
        result[section] = q2(total / Decimal(len(section_items)))
    return result


def critical_penalty_for(count):
    if count == 0:
        return Decimal("0.00")
    if count == 1:
        return Decimal("5.00")
    if count == 2:
        return Decimal("12.00")
    return Decimal("25.00")


def grade_for(composite_score, critical_violation_count):
    if critical_violation_count >= CRITICAL_FAIL_COUNT:
        return "FAIL"
    if composite_score is None:
        return None
    if composite_score >= PASS_THRESHOLD:
        return "PASS"
    if composite_score >= CONDITIONAL_THRESHOLD:
        return "CONDITIONAL"
    return "FAIL"


def recompute_visit_scores(visit, variant):
    """Run the visit-level scoring pipeline and store the results."""
    if visit["status"] == "VOIDED":
        return
    percents = section_percents(visit)
    food_safety = percents["FOOD_SAFETY"]
    brand_standards = percents["BRAND_STANDARDS"]
    facility = percents["FACILITY"]

    rubric_percent = q2(
        WEIGHT_FOOD_SAFETY * food_safety
        + WEIGHT_BRAND_STANDARDS * brand_standards
        + WEIGHT_FACILITY * facility
    )

    critical_count = 0
    for scored in scored_items_of(visit["id"]):
        if scored["severity"] == "CRITICAL":
            critical_count += 1

    penalty = critical_penalty_for(critical_count)
    base = q2(rubric_percent - penalty)
    if base < Decimal("0.00"):
        base = Decimal("0.00")

    health = visit.get("health_component_percent")
    if variant == "FINAL" and health is not None:
        composite = q2(
            FINAL_WEIGHT_BASE * base
            + FINAL_WEIGHT_FOOD_SAFETY * food_safety
            + FINAL_WEIGHT_HEALTH * dec(health)
        )
    else:
        composite = q2(
            PROVISIONAL_WEIGHT_BASE * base
            + PROVISIONAL_WEIGHT_FOOD_SAFETY * food_safety
        )

    visit["food_safety_percent"] = food_safety
    visit["brand_standards_percent"] = brand_standards
    visit["facility_percent"] = facility
    visit["critical_violation_count"] = critical_count
    visit["critical_penalty_points"] = penalty
    visit["composite_score"] = composite
    visit["composite_variant"] = variant
    visit["grade"] = grade_for(composite, critical_count)
    touch(visit)


# --------------------------------------------------------------------------
# health_component_percent
# --------------------------------------------------------------------------

def select_health_component(visit):
    """Return (inspection_id, health_component_percent) for a finalizing visit."""
    window_end = visit["scheduled_start_at"]
    window_start = window_end - days(HEALTH_LOOKBACK_DAYS)
    eligible = [
        h for h in db.store.health_inspections.values()
        if h["location_id"] == visit["location_id"]
        and h["status"] == "RECORDED"
        and h["inspection_date"] <= window_end
        and h["inspection_date"] >= window_start
    ]
    if not eligible:
        return None, None
    eligible.sort(key=lambda h: (h["inspection_date"], h["created_at"], h["_seq"]), reverse=True)
    selected = eligible[0]
    raw = q2(Decimal(selected["points_scored"]) / Decimal(selected["points_possible"]) * Decimal(100))
    letter = selected["letter_grade"]
    if letter in ("A", "B"):
        cap = Decimal("100.00")
    elif letter == "C":
        cap = Decimal("79.00")
    else:
        cap = Decimal("0.00")
    return selected["id"], (raw if raw < cap else cap)


# --------------------------------------------------------------------------
# location_repeat_violation_count / location_standing_score
# --------------------------------------------------------------------------

def critical_item_ids_of_visit(visit_id):
    return set(
        scored["rubric_item_id"]
        for scored in scored_items_of(visit_id)
        if scored["severity"] == "CRITICAL"
    )


def repeat_hits(location_id):
    """Map rubric_item_id -> number of distinct FINALIZED visits with a
    CRITICAL scored item on it inside the trailing 365-day window."""
    window_start = db.store.clock - days(REPEAT_LOOKBACK_DAYS)
    visits = [
        v for v in db.store.audit_visits.values()
        if v["location_id"] == location_id
        and v["status"] == "FINALIZED"
        and v["finalized_at"] is not None
        and v["finalized_at"] >= window_start
    ]
    hits = {}
    for visit in visits:
        for rubric_item_id in critical_item_ids_of_visit(visit["id"]):
            hits[rubric_item_id] = hits.get(rubric_item_id, 0) + 1
    return hits


def recompute_repeat_violation_count(location):
    hits = repeat_hits(location["id"])
    count = sum(1 for value in hits.values() if value >= 2)
    set_if_changed(location, "repeat_violation_count", count)
    return count


def standing_visits(location_id):
    visits = [
        v for v in db.store.audit_visits.values()
        if v["location_id"] == location_id
        and v["status"] == "FINALIZED"
        and v["visit_type"] != "SHADOW"
    ]
    visits.sort(key=lambda v: (v["finalized_at"], v["created_at"], v["_seq"]), reverse=True)
    return visits[:3]


def recompute_standing_score(location):
    visits = standing_visits(location["id"])
    if not visits:
        set_if_changed(location, "standing_score", Decimal("0.00"))
        set_if_changed(location, "latest_grade", None)
        return
    weights = [Decimal("0.50"), Decimal("0.30"), Decimal("0.20")][:len(visits)]
    total_weight = sum(weights)
    accumulated = Decimal(0)
    for index, visit in enumerate(visits):
        composite = visit["composite_score"]
        if composite is None:
            composite = Decimal("0.00")
        # Renormalized weights are carried at full precision.
        accumulated += (weights[index] / total_weight) * dec(composite)
    base = q2(accumulated)

    if base >= Decimal("90.00"):
        per_unit = Decimal("0.50")
    elif base >= Decimal("80.00"):
        per_unit = Decimal("1.00")
    else:
        per_unit = Decimal("2.00")

    standing = q2(base - per_unit * Decimal(location["repeat_violation_count"]))
    if standing < Decimal("0.00"):
        standing = Decimal("0.00")
    set_if_changed(location, "standing_score", standing)
    set_if_changed(location, "latest_grade", visits[0]["grade"])


# --------------------------------------------------------------------------
# calibration_variance_and_delta / auditor_reliability_score
# --------------------------------------------------------------------------

def calibration_band(variance):
    if variance <= Decimal("2.00"):
        return "EXCELLENT", Decimal("4.00")
    if variance <= Decimal("5.00"):
        return "ACCEPTABLE", Decimal("1.00")
    if variance <= Decimal("10.00"):
        return "MARGINAL", Decimal("-3.00")
    return "UNACCEPTABLE", Decimal("-8.00")


def calibration_records_of(auditor_id):
    records = [
        r for r in db.store.calibration_records.values()
        if r["auditor_id"] == auditor_id
    ]
    return records


def rolling_reliability(auditor_id):
    records = calibration_records_of(auditor_id)
    records.sort(key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]), reverse=True)
    records = records[:3]
    total = BASELINE_RELIABILITY
    for index, record in enumerate(records):
        total += ROLLING_DECAY[index] * dec(record["reliability_delta"])
    return clamp(q2(total), Decimal("0.00"), Decimal("100.00"))


def certification_review_reliability(auditor):
    start = auditor["certification_period_start"]
    total = BASELINE_RELIABILITY
    for record in calibration_records_of(auditor["id"]):
        if start is not None and record["recorded_at"] < start:
            continue
        total += dec(record["reliability_delta"])
    return clamp(q2(total), Decimal("0.00"), Decimal("100.00"))
