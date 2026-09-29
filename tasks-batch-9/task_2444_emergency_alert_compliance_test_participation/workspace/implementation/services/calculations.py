"""The nine calculation rules (PRD 3.4 - 3.9).

Every monetary/score figure is carried as decimal.Decimal and rounded
half-up.  The number of rounding operations and their position is normative
(PRD 2.6).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import clock
import store
from store import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# duplicate_suppression_window
STATION_DEDUP_SECONDS = 900
WEA_MATCH_SECONDS = 1800
WEA_BUFFER_SECONDS = 120

# accessibility_pass_evaluation
CRAWL_MIN_SECONDS = Decimal("60")
TARGET_LUFS = Decimal("-24.0")
LOUDNESS_TOLERANCE_LU = Decimal("2.0")
CRAWL_POINT_RATE = Decimal("0.05")
LOUDNESS_POINT_RATE = Decimal("0.10")
COUPLING_RATE = Decimal("0.01")
CRAWL_COUPLING_CAP = Decimal("3.00")
DEFICIENCY_CAP = Decimal("8.00")
ACCESSIBILITY_PASS_MAX_POINTS = Decimal("1.00")
CAPTION_PENALTY = {
    "NONE": Decimal("0.00"),
    "CAPTION_SUPPRESSED": Decimal("1.50"),
    "CRAWL_OVERLAP": Decimal("2.00"),
}

# filing_penalty_points
PER_ENTRY_LATE_RATE = Decimal("0.065")
LATE_DAY_POINTS = Decimal("0.75")
UNCONFIRMED_RELAY_POINTS = Decimal("0.50")
RELAY_LOOKBACK_DAYS = 30
PENALTY_CAP = Decimal("25.00")
STATION_POINT_CEILING = Decimal("5.00")
FILING_DUE_DAYS = 5
FILING_GRACE_DAYS = 10
RECEIPT_WEIGHT = Decimal("1.0")
TRANSMISSION_WEIGHT = Decimal("1.8")

# outage_downtime_hours
CONTINUOUS_BREACH_HOURS = Decimal("60")
REPAIR_DEADLINE_HOURS = Decimal("48")
OBLIGATION_WINDOW_START_HOUR = 8
OBLIGATION_WINDOW_END_HOUR = 20

# station_compliance_score
BASE_SCORE = Decimal("100.00")
MISSING_SOURCE_DEDUCTION = Decimal("25.00")
SILENT_ASSIGNMENT_DEDUCTION = Decimal("10.00")
REVALIDATION_DEDUCTION = Decimal("15.00")
OUTAGE_BREACH_DEDUCTION = Decimal("10.00")
UNFILED_TEST_DEDUCTION = Decimal("20.00")
SILENCE_MAX_DAYS = 8
CERTIFICATION_WINDOW_DAYS = 365
COMPLIANT_MIN_SCORE = Decimal("90.00")
WATCH_MIN_SCORE = Decimal("75.00")

# test_event_readiness_score
READY_DEVICE_WEIGHT = Decimal("40")
SOURCE_COVERAGE_WEIGHT = Decimal("40")
RECENT_ALERT_WEIGHT = Decimal("20")
RECENT_ALERT_TARGET = Decimal("3")
RECENT_ALERT_WINDOW_DAYS = 30
READINESS_PASS_MIN = Decimal("80.00")
PREFLIGHT_HOURS = 24

# retention_until
STANDARD_RETENTION_DAYS = 730
NATIONAL_RETENTION_DAYS = 1095
SUSPENDED_EXTENSION_DAYS = 365

# inspection_completeness_score
INSPECTION_RESPONSE_DAYS = 7
LATE_RESPONSE_DEDUCTION = Decimal("20.00")
INSPECTION_SATISFIED_MIN = Decimal("100.00")


def r2(value):
    """Round half-up to two decimal places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 1. relay_rule_selection  (PRD 3.5)
# ---------------------------------------------------------------------------

def relay_rule_selection(station, plan, event_code, fips_codes):
    """Selector policy: eligibility filter, ranking, tie-break, empty fallback."""
    alert_fips = set(fips_codes)
    pool = []
    for rule in store.relay_rules_of_plan(station["state_plan_id"]):
        if rule["status"] != "ACTIVE":
            continue
        if rule["event_code"] != event_code:
            continue
        if rule["fips_codes"] and not (set(rule["fips_codes"]) & alert_fips):
            continue
        pool.append(rule)

    if not pool:
        return {
            "relay_state": "UNMATCHED_OPTIONAL",
            "matched_relay_rule_id": None,
            "relay_class_applied": "NONE",
            "forward_delay_seconds_applied": 0,
        }

    # specificity DESC, priority ASC, created_at ASC (never id)
    pool.sort(key=lambda r: (-r["specificity"], r["priority"], r["created_at"], r["_seq"]))
    selected = pool[0]

    mandatory_codes = plan["mandatory_relay_event_codes"] if plan else []
    if selected["relay_class"] == "MANDATORY" or event_code in mandatory_codes:
        relay_class_applied = "MANDATORY"
    else:
        relay_class_applied = "OPTIONAL"

    return {
        "relay_state": "RELAY_PENDING",
        "matched_relay_rule_id": selected["id"],
        "relay_class_applied": relay_class_applied,
        "forward_delay_seconds_applied": selected["forward_delay_seconds"],
    }


# ---------------------------------------------------------------------------
# 2. duplicate_suppression_window  (PRD 3.5)
# ---------------------------------------------------------------------------

def duplicate_suppression_window(station_id, event_code, originator_sequence,
                                 fips_codes, received_at):
    """Two-phase duplicate avoidance.

    Phase A: half-open [t - 900s, t), no buffer, no FIPS test.
    Phase B: closed [w - 120s, w + 1800s + 120s], FIPS intersection required.
    All comparisons at whole-second granularity.
    """
    t = clock.whole_seconds(received_at)
    lower = t - STATION_DEDUP_SECONDS

    # ---- PHASE A: station repeat -----------------------------------------
    candidates = []
    for row in store.alerts_of_station(station_id):
        if row["originator_sequence"] != originator_sequence:
            continue
        if row["event_code"] != event_code:
            continue
        rt = clock.whole_seconds(row["received_at"])
        if lower <= rt < t:
            candidates.append(row)
    if candidates:
        # greatest received_at; tie-break earliest created_at
        candidates.sort(key=lambda r: (-clock.whole_seconds(r["received_at"]),
                                       r["created_at"], r["_seq"]))
        reference = candidates[0]
        return {
            "relay_state": "SUPPRESSED_DUPLICATE",
            "suppression_source": "STATION_REPEAT",
            "suppression_reference_alert_id": reference["id"],
        }

    # ---- PHASE B: wireless coordination ----------------------------------
    alert_fips = set(fips_codes)
    for notice in store.wea_notices_of_station(station_id):
        if notice["originator_sequence"] != originator_sequence:
            continue
        if notice["event_code"] != event_code:
            continue
        w = clock.whole_seconds(notice["wea_sent_at"])
        win_lo = w - WEA_BUFFER_SECONDS
        win_hi = w + WEA_MATCH_SECONDS + WEA_BUFFER_SECONDS
        if win_lo <= t <= win_hi and (set(notice["fips_codes"]) & alert_fips):
            return {
                "relay_state": "SUPPRESSED_DUPLICATE",
                "suppression_source": "WIRELESS_NOTICE",
                "suppression_reference_alert_id": None,
            }

    return {
        "relay_state": None,
        "suppression_source": "NONE",
        "suppression_reference_alert_id": None,
    }


# ---------------------------------------------------------------------------
# 3. accessibility_pass_evaluation  (PRD 3.5)
# ---------------------------------------------------------------------------

def accessibility_pass_evaluation(visual_crawl_seconds, audio_loudness_lufs,
                                  caption_interaction):
    crawl_shortfall = max(Decimal("0"), CRAWL_MIN_SECONDS - Decimal(visual_crawl_seconds))
    loudness_excess = max(
        Decimal("0.0"),
        abs(Decimal(audio_loudness_lufs) - TARGET_LUFS) - LOUDNESS_TOLERANCE_LU,
    )
    caption_penalty = CAPTION_PENALTY[caption_interaction]

    coupled_points = min(CRAWL_COUPLING_CAP, crawl_shortfall * loudness_excess * COUPLING_RATE)
    base_points = crawl_shortfall * CRAWL_POINT_RATE + loudness_excess * LOUDNESS_POINT_RATE

    # single rounding, applied once, AFTER the outer min()
    points = r2(min(DEFICIENCY_CAP, base_points + coupled_points + caption_penalty))
    state = (
        "ACCESSIBILITY_PASSED"
        if points <= ACCESSIBILITY_PASS_MAX_POINTS
        else "ACCESSIBILITY_FAILED"
    )
    return points, state


# ---------------------------------------------------------------------------
# 4. filing_penalty_points  (PRD 3.7)
# ---------------------------------------------------------------------------

def late_days_for(filed_at, filing_deadline_at):
    if filed_at <= filing_deadline_at:
        return 0
    seconds = Decimal(str((filed_at - filing_deadline_at).total_seconds()))
    return int((seconds / Decimal(86400)).to_integral_value(rounding=ROUND_CEILING))


def unconfirmed_mandatory_relay_count(station_id, filed_at):
    lo = filed_at - timedelta(days=RELAY_LOOKBACK_DAYS)
    count = 0
    for alert in store.alerts_of_station(station_id):
        if alert["relay_class_applied"] != "MANDATORY":
            continue
        if alert["relay_state"] != "RELAY_PENDING":
            continue
        if lo <= alert["received_at"] <= filed_at:
            count += 1
    return count


def filing_penalty_points(test_event, station_id, filed_at):
    late_days = late_days_for(filed_at, test_event["filing_deadline_at"])

    # PINNED ROUNDING ORDER: round each entry to 2dp FIRST, then sum.
    entry_subtotal = Decimal("0.00")
    for entry in store.log_entries_of_event(test_event["id"]):
        weight = RECEIPT_WEIGHT if entry["entry_kind"] == "RECEIPT" else TRANSMISSION_WEIGHT
        entry_subtotal += r2(Decimal(late_days) * PER_ENTRY_LATE_RATE * weight)

    lateness_points = r2(Decimal(late_days) * LATE_DAY_POINTS)
    relay_count = unconfirmed_mandatory_relay_count(station_id, filed_at)
    unconfirmed_relay_points = r2(Decimal(relay_count) * UNCONFIRMED_RELAY_POINTS)

    penalty_points = r2(
        min(PENALTY_CAP, entry_subtotal + lateness_points + unconfirmed_relay_points)
    )
    return {
        "late_days": late_days,
        "entry_subtotal_points": r2(entry_subtotal),
        "lateness_points": lateness_points,
        "unconfirmed_relay_points": unconfirmed_relay_points,
        "penalty_points": penalty_points,
    }


# ---------------------------------------------------------------------------
# 5. outage_downtime_hours  (PRD 3.4) — dual variant
# ---------------------------------------------------------------------------

def outage_downtime_hours(detected_at, restored_at):
    seconds = Decimal(str((restored_at - detected_at).total_seconds()))
    continuous = r2(seconds / Decimal(3600))
    continuous_breached = continuous > CONTINUOUS_BREACH_HOURS

    obligation_seconds = Decimal("0")
    day = detected_at.astimezone(timezone.utc).date()
    end_day = restored_at.astimezone(timezone.utc).date()
    while day <= end_day:
        win_start = datetime(day.year, day.month, day.day,
                            OBLIGATION_WINDOW_START_HOUR, 0, 0, tzinfo=timezone.utc)
        win_end = datetime(day.year, day.month, day.day,
                          OBLIGATION_WINDOW_END_HOUR, 0, 0, tzinfo=timezone.utc)
        start = max(detected_at, win_start)
        finish = min(restored_at, win_end)
        if finish > start:
            obligation_seconds += Decimal(str((finish - start).total_seconds()))
        day = day + timedelta(days=1)

    obligation = r2(obligation_seconds / Decimal(3600))
    obligation_breached = obligation > REPAIR_DEADLINE_HOURS
    return {
        "continuous_downtime_hours": continuous,
        "continuous_clock_breached": continuous_breached,
        "obligation_downtime_hours": obligation,
        "obligation_breached": obligation_breached,
    }


# ---------------------------------------------------------------------------
# 7. test_event_readiness_score  (PRD 3.6)
# ---------------------------------------------------------------------------

def test_event_readiness_score(station, plan):
    devices = store.devices_of_station(station["id"])
    ready_device_count = sum(1 for d in devices if d["status"] == "READY")
    countable_device_count = sum(
        1 for d in devices if d["status"] in ("REGISTERED", "READY", "FAILED")
    )
    ready_ratio = Decimal(ready_device_count) / Decimal(max(1, countable_device_count))

    required_source_count = plan["required_source_count"] if plan else 0
    coverage_ratio = min(
        Decimal(1),
        Decimal(station["accessible_source_count"]) / Decimal(max(1, required_source_count)),
    )

    now = clock.now()
    lo = now - timedelta(days=RECENT_ALERT_WINDOW_DAYS)
    recent_alert_count = sum(
        1 for a in store.alerts_of_station(station["id"]) if lo <= a["received_at"] <= now
    )
    recent_ratio = min(Decimal(1), Decimal(recent_alert_count) / RECENT_ALERT_TARGET)

    score = r2(
        READY_DEVICE_WEIGHT * ready_ratio
        + SOURCE_COVERAGE_WEIGHT * coverage_ratio
        + RECENT_ALERT_WEIGHT * recent_ratio
    )
    return score


# ---------------------------------------------------------------------------
# 8. retention_until  (PRD 3.6)
# ---------------------------------------------------------------------------

def retention_for(test_event, station, logged_at):
    base_days = (
        NATIONAL_RETENTION_DAYS
        if test_event["test_type"] == "NATIONAL"
        else STANDARD_RETENTION_DAYS
    )
    extension = (
        SUSPENDED_EXTENSION_DAYS
        if station["compliance_posture"] == "SUSPENDED_FILINGS"
        else 0
    )
    retention_days_applied = base_days + extension
    return retention_days_applied, logged_at + timedelta(days=retention_days_applied)


# ---------------------------------------------------------------------------
# 9. inspection_completeness_score  (PRD 3.9)
# ---------------------------------------------------------------------------

def inspection_completeness_score(inspection, responded_at):
    requested = inspection["requested_document_kinds"]
    provided = inspection["provided_document_kinds"]
    matched = len(set(provided) & set(requested))
    raw = r2(Decimal(100) * Decimal(matched) / Decimal(max(1, len(requested))))
    if responded_at <= inspection["response_due_at"]:
        return raw
    return r2(max(Decimal("0.00"), raw - LATE_RESPONSE_DEDUCTION))
