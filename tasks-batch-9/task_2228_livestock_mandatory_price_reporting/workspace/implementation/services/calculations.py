"""Calculation rules (SCAFFOLD §1.3, PRD §3).

Every rounding order here is pinned by PRD §2.7:
  * submission booked totals   -> round per record, THEN sum
  * market report aggregation  -> accumulate at full precision, round ONCE
"""

import math

import clock
import constants
import db
from errors import (
    ApiError,
    ERR_FORWARD_COMMITMENT_CAP_EXCEEDED,
    ERR_INCOMPLETE_SLAUGHTER_HISTORY,
    ERR_NO_ELIGIBLE_PLANTS,
)
from numeric import dec, money, pct, round_half_up


# ---------------------------------------------------------------------------
# reporter_threshold_determination
# ---------------------------------------------------------------------------
def eligible_plants(reporting_entity_id):
    return [
        p
        for p in db.plants.values()
        if p["reporting_entity_id"] == reporting_entity_id and p["status"] in ("ACTIVE", "IDLE")
    ]


def run_threshold_determination(registration, entity):
    """Returns (measured_head, threshold_head, determination_outcome).

    PRD §2.9: the slaughter-history completeness check ranks AHEAD of the
    eligible-plant check, so a firm with no eligible plant passes the history
    check vacuously and then fails with ERR_NO_ELIGIBLE_PLANTS.
    """
    year = registration["determination_year"]
    basis = registration["basis_variant"]
    plants = eligible_plants(registration["reporting_entity_id"])

    lookback = [str(year - k) for k in range(constants.LOOKBACK_YEARS, 0, -1)]
    required_years = lookback if basis == "FIVE_YEAR_AVERAGE" else [str(year - 1)]

    for plant in plants:
        history = plant.get("annual_head_history") or {}
        for y in required_years:
            if y not in history:
                raise ApiError(
                    ERR_INCOMPLETE_SLAUGHTER_HISTORY,
                    "Plant %s is missing slaughter history for %s." % (plant["plant_code"], y),
                )

    if not plants:
        raise ApiError(
            ERR_NO_ELIGIBLE_PLANTS,
            "The reporting entity has no plant in status ACTIVE or IDLE.",
        )

    if basis == "FIVE_YEAR_AVERAGE":
        pooled = 0
        for plant in plants:
            history = plant["annual_head_history"]
            for y in lookback:
                pooled += int(history[y])
        measured_head = pooled // constants.LOOKBACK_YEARS
    else:
        prior = str(year - 1)
        measured_head = sum(int(p["annual_head_history"][prior]) for p in plants)

    threshold_head = constants.THRESHOLD_HEAD_BY_SPECIES[entity["species_scope"]]
    outcome = "MANDATORY" if measured_head >= threshold_head else "EXEMPT"
    return measured_head, threshold_head, outcome


# ---------------------------------------------------------------------------
# submission_lateness
# ---------------------------------------------------------------------------
def apply_lateness(sub, window):
    deadline = window["_submission_deadline_utc"]
    delta_seconds = (clock.now() - deadline).total_seconds()
    delta_minutes = math.floor(delta_seconds / 60.0)
    lateness = max(0, int(delta_minutes))
    sub["lateness_minutes"] = lateness
    sub["is_late"] = lateness > 0
    sub["days_late"] = -((-lateness) // constants.MINUTES_PER_DAY)


# ---------------------------------------------------------------------------
# forward_commitment_peak
# ---------------------------------------------------------------------------
def check_forward_commitment_peak(plant, new_start, new_end, new_head):
    intervals = []
    for record in db.transaction_records.values():
        if record["purchase_type"] != "FORWARD_CONTRACT":
            continue
        owner = db.submissions.get(record["submission_id"])
        if owner is None or owner["plant_id"] != plant["id"]:
            continue
        if owner["status"] not in constants.SUBMISSION_NON_TERMINAL_STATUSES:
            continue
        intervals.append(
            (
                record["_forward_delivery_start"].date(),
                record["_forward_delivery_end"].date(),
                int(record["head_count"]),
            )
        )
    intervals.append((new_start.date(), new_end.date(), int(new_head)))

    probe_days = {start for (start, _end, _head) in intervals}
    peak = 0
    for day in probe_days:
        total = sum(head for (start, end, head) in intervals if start <= day <= end)
        if total > peak:
            peak = total

    cap = int(plant.get("forward_commitment_cap_head") or 0)
    if peak > cap:
        raise ApiError(
            ERR_FORWARD_COMMITMENT_CAP_EXCEEDED,
            "Peak forward commitment %d head exceeds the plant cap of %d head." % (peak, cap),
        )


# ---------------------------------------------------------------------------
# market_report_aggregation
# ---------------------------------------------------------------------------
def aggregate_market_report(report, window):
    accepted = [
        s
        for s in db.submissions.values()
        if s["reporting_window_id"] == window["id"] and s["status"] == "ACCEPTED"
    ]
    report["source_submission_count"] = len(accepted)

    entity_by_submission = {}
    for sub in accepted:
        plant = db.plants.get(sub["plant_id"])
        entity_by_submission[sub["id"]] = plant["reporting_entity_id"] if plant else None
    submission_ids = set(entity_by_submission.keys())

    variant = report["weighting_variant"]
    volume_by_entity = {}
    priced_pairs = []  # (weight, price)
    prices = []

    if window["report_class"] == "LIVE_ANIMAL":
        items = [
            t for t in db.transaction_records.values() if t["submission_id"] in submission_ids
        ]
        if report["purchase_type_filter"] == "NEGOTIATED_ONLY":
            priced = [t for t in items if t["purchase_type"] in ("NEGOTIATED", "NEGOTIATED_GRID")]
        else:
            priced = [t for t in items if t["purchase_type"] != "PACKER_OWNED"]

        total_head = sum(int(t["head_count"]) for t in items)
        report["total_head"] = total_head
        report["total_pounds"] = None
        volume_total = dec(total_head)

        for t in items:
            owner = entity_by_submission.get(t["submission_id"])
            volume_by_entity[owner] = volume_by_entity.get(owner, dec(0)) + dec(t["head_count"])

        for t in priced:
            if variant == "HEAD_WEIGHTED":
                weight = dec(t["head_count"])
            else:
                weight = dec(t["head_count"]) * dec(t["avg_carcass_weight_cwt"])
            price = dec(t["avg_net_price_per_cwt"])
            priced_pairs.append((weight, price))
            prices.append(price)
    else:
        items = [l for l in db.wholesale_lots.values() if l["submission_id"] in submission_ids]
        priced = items  # every wholesale lot is priced

        total_pounds = dec(0)
        for l in items:
            total_pounds += dec(l["total_pounds"])
        report["total_head"] = None
        report["total_pounds"] = money(total_pounds)
        volume_total = total_pounds

        for l in items:
            owner = entity_by_submission.get(l["submission_id"])
            volume_by_entity[owner] = volume_by_entity.get(owner, dec(0)) + dec(l["total_pounds"])

        for l in priced:
            weight = dec(l["load_count"]) if variant == "HEAD_WEIGHTED" else dec(l["total_pounds"])
            price = dec(l["price_per_cwt"])
            priced_pairs.append((weight, price))
            prices.append(price)

    report["reporter_count"] = len({e for e in entity_by_submission.values()})

    if volume_total is None or volume_total == 0:
        report["max_reporter_share_pct"] = pct(0)
    else:
        largest = max(volume_by_entity.values()) if volume_by_entity else dec(0)
        report["max_reporter_share_pct"] = pct(dec(100) * largest / volume_total)

    if not priced_pairs:
        report["weighted_average_price_per_cwt"] = None
        report["price_low_per_cwt"] = None
        report["price_high_per_cwt"] = None
    else:
        numerator = dec(0)
        denominator = dec(0)
        for weight, price in priced_pairs:
            numerator += weight * price
            denominator += weight
        if denominator == 0:
            report["weighted_average_price_per_cwt"] = None
        else:
            report["weighted_average_price_per_cwt"] = money(numerator / denominator)
        report["price_low_per_cwt"] = min(prices)
        report["price_high_per_cwt"] = max(prices)

    report["computed_at"] = clock.iso_now()


# ---------------------------------------------------------------------------
# confidentiality_suppression
# ---------------------------------------------------------------------------
def evaluate_confidentiality(report, window):
    """Returns the FIRST failing guideline, or None when the report clears."""
    if window["report_class"] == "LIVE_ANIMAL":
        volume_metric = report["total_head"]
    else:
        volume_metric = report["total_pounds"]

    if report["weighted_average_price_per_cwt"] is None:
        return "NO_ELIGIBLE_DATA"
    if int(report["reporter_count"] or 0) < int(window["min_reporter_count"]):
        return "INSUFFICIENT_REPORTERS"
    if dec(report["max_reporter_share_pct"] or 0) > dec(window["max_single_reporter_share_pct"]):
        return "DOMINANT_REPORTER"
    if dec(volume_metric if volume_metric is not None else 0) < dec(window["min_reported_head"]):
        return "INSUFFICIENT_VOLUME"
    return None


def mask_withheld(report):
    report["weighted_average_price_per_cwt"] = None
    report["price_low_per_cwt"] = None
    report["price_high_per_cwt"] = None
    report["total_head"] = None
    report["total_pounds"] = None


# ---------------------------------------------------------------------------
# audit_discrepancy
# ---------------------------------------------------------------------------
def _rate(verified, reported):
    if verified == 0 and reported == 0:
        return pct(0)
    if verified == 0 and reported != 0:
        return pct(100)
    return pct(dec(100) * abs(dec(verified) - dec(reported)) / dec(verified))


def compute_audit_discrepancy(case, sub):
    reported_head = dec(sub["reported_head"] or 0)
    reported_value = dec(sub["reported_value_dollars"] or 0)
    verified_head = dec(case["verified_head"])
    verified_value = dec(case["verified_value_dollars"])

    head_rate = _rate(verified_head, reported_head)
    value_rate = _rate(verified_value, reported_value)

    materiality = dec(case["materiality_pct"])
    head_material = head_rate > materiality
    value_material = value_rate > materiality

    if head_material and value_material:
        finding = "MATERIAL_BOTH"
    elif head_material:
        finding = "MATERIAL_HEAD"
    elif value_material:
        finding = "MATERIAL_VALUE"
    else:
        finding = "IMMATERIAL"
    return head_rate, value_rate, finding


# ---------------------------------------------------------------------------
# penalty_assessment_amount + delinquency_points_and_tier
# ---------------------------------------------------------------------------
def governing_registration(reporting_entity_id):
    """Firm's determination file for the logical clock's calendar year in ACTIVE or SUSPENDED."""
    year = clock.now().year
    candidates = [
        r
        for r in db.registrations.values()
        if r["reporting_entity_id"] == reporting_entity_id
        and r["determination_year"] == year
        and r["status"] in ("ACTIVE", "SUSPENDED")
    ]
    if not candidates:
        return None
    return db.ordered(candidates)[-1]


def day_tier_multiplier(violation_type, days_late):
    if violation_type != "LATE_FILING":
        return dec("1.00")
    if days_late == 0:
        return dec("1.00")
    if 1 <= days_late <= 2:
        return dec("1.00")
    if 3 <= days_late <= 7:
        return dec("1.50")
    return dec("2.25")


def repeat_multiplier(repeat_index):
    if repeat_index == 0:
        return dec("1.00")
    if repeat_index == 1:
        return dec("1.50")
    if repeat_index == 2:
        return dec("2.00")
    return dec("3.00")


def compute_penalty(entity, violation_type, submission, registration):
    """Pinned evaluation order (PRD §3.8): pre-assessment reads, money, then points."""
    points_before = int(entity["delinquency_points"] or 0)
    tier_at_assessment = constants.tier(points_before)

    base_amount_cents = constants.BASE_CENTS_BY_VIOLATION[violation_type]
    days_late = int(submission["days_late"] or 0) if violation_type == "LATE_FILING" else 0
    day_mult = day_tier_multiplier(violation_type, days_late)

    repeat_index = len(
        [
            a
            for a in db.penalty_assessments.values()
            if a["reporting_entity_id"] == entity["id"]
            and a["violation_type"] == violation_type
            and a["status"] in ("ASSESSED", "PAID")
        ]
    )
    repeat_mult = repeat_multiplier(repeat_index)

    if registration is None:
        volume_factor = dec("1.000")
        suspension_surcharge = dec("1.00")
    else:
        uplift = dec(registration["measured_head"] or 0) / constants.VOLUME_FACTOR_HEAD_DIVISOR
        if uplift > constants.VOLUME_FACTOR_MAX_UPLIFT:
            uplift = constants.VOLUME_FACTOR_MAX_UPLIFT
        volume_factor = round_half_up(dec(1) + uplift, 3)
        suspension_surcharge = (
            dec("1.25") if registration["status"] == "SUSPENDED" else dec("1.00")
        )

    raw = dec(base_amount_cents) * day_mult * repeat_mult * volume_factor * suspension_surcharge
    rounded = int(round_half_up(raw, 0))
    assessed_amount_cents = min(constants.PER_ASSESSMENT_CAP_CENTS, rounded)

    points = constants.POINTS_BY_VIOLATION[violation_type]
    if tier_at_assessment == "TIER_2":
        points *= constants.TIER_2_POINT_DOUBLING

    return {
        "days_late": days_late,
        "base_amount_cents": base_amount_cents,
        "repeat_index": repeat_index,
        "day_tier_multiplier": day_mult,
        "repeat_multiplier": repeat_mult,
        "volume_factor": volume_factor,
        "suspension_surcharge": suspension_surcharge,
        "assessed_amount_cents": assessed_amount_cents,
        "points": points,
        "delinquency_tier_at_assessment": tier_at_assessment,
        "points_before": points_before,
    }
