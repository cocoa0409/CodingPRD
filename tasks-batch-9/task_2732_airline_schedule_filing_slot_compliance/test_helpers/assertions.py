"""Entity assertions, timestamp canonicalisation and domain invariant checkers."""

import re
from typing import Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AT_RISK_THRESHOLD_PCT,
    CHARGE_PER_LEG_CENTS,
    COMPENSATION_RATE_CENTS,
    EXPEDITE_RATE_PCT,
    PENALTY_CAP,
    PENALTY_PER_AT_RISK_SLOT,
    PENALTY_PER_CURFEW_VIOLATION,
    PENALTY_PER_GATE_OVERFLOW,
    PENALTY_PER_MCT_VIOLATION,
    PENALTY_PER_UNSLOTTED_LEG,
    SCORE_BASE,
    TIER_MULTIPLIER_PCT,
)

# ─── Timestamp handling ───────────────────────────────────────────────────
# A server may legitimately serialise the same instant with milliseconds,
# microseconds or no fractional part at all. Every equality comparison in the
# suite goes through canonical_iso8601() so that a width difference never
# masquerades as a contract violation.

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(?:[Zz]|\+00:?00)$"
)


def canonical_iso8601(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to `YYYY-MM-DDTHH:MM:SS.mmmZ`.

    Returns the input unchanged when it is None or unparseable, so that a
    genuinely malformed value still fails the comparison it is used in.
    """
    if not isinstance(value, str):
        return value
    m = _TS_RE.match(value.strip())
    if not m:
        return value
    y, mo, d, h, mi, s, frac = m.groups()
    millis = int(round(float("0." + frac) * 1000)) if frac else 0
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}.{millis:03d}Z"


def assert_timestamp_equals(actual, expected, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants irrespective of fractional-second width."""
    assert canonical_iso8601(actual) == canonical_iso8601(expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_iso_timestamp(value, label: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


def assert_uuid(value, label: str = "id") -> None:
    assert is_valid_uuid(value), f"{label} must be a bare UUID string, got {value!r}"


# ─── Envelope / audit-field helpers ───────────────────────────────────────

def assert_audit_fields(data: dict, expected_version: Optional[int] = None) -> None:
    """id + created_at + updated_at + version, as eleven of the twelve
    resource types carry them."""
    assert_uuid(data.get("id"))
    assert_iso_timestamp(data.get("created_at"), "created_at")
    assert_iso_timestamp(data.get("updated_at"), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_keys_absent(data: dict, *keys: str) -> None:
    for key in keys:
        assert key not in data, (
            f"{key!r} must be absent from the response body, found {data.get(key)!r}"
        )


def assert_two_decimal_number(value, label: str = "value") -> None:
    """Percentages and scores are JSON numbers carried to two decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {type(value).__name__}: {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value)), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_integer_cents(value, label: str = "amount") -> None:
    """Monetary values are integer counts of cents, never strings, never
    fractional."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got "
        f"{type(value).__name__}: {value!r}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_carrier(data: dict) -> None:
    assert_audit_fields(data)
    assert re.fullmatch(r"[A-Z0-9]{2}", data["iata_code"]), data["iata_code"]
    assert re.fullmatch(r"[A-Z]{3}", data["icao_code"]), data["icao_code"]
    assert re.fullmatch(r"[A-Z]{2}", data["country_code"]), data["country_code"]
    assert isinstance(data["is_home_carrier"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["held_series_count"], int)
    assert data["held_series_count"] >= 0


def assert_station(data: dict) -> None:
    assert_audit_fields(data)
    assert re.fullmatch(r"[A-Z]{3}", data["iata_code"]), data["iata_code"]
    assert re.fullmatch(r"[A-Z]{2}", data["country_code"]), data["country_code"]
    assert data["coordination_level"] in (
        "LEVEL_1_NON_COORDINATED",
        "LEVEL_2_FACILITATED",
        "LEVEL_3_COORDINATED",
    )
    assert -720 <= data["utc_offset_minutes"] <= 840
    assert data["gate_count"] >= 1
    for field in ("curfew_start_local_minutes", "curfew_end_local_minutes"):
        if data[field] is not None:
            assert 0 <= data[field] <= 1439, f"{field} out of range"
    assert data["min_connect_domestic_minutes"] >= 0
    assert data["min_connect_international_minutes"] >= 0
    assert data["min_turn_override_minutes"] >= 0
    assert isinstance(data["maintenance_capable"], bool)


def assert_season(data: dict) -> None:
    assert_audit_fields(data)
    assert isinstance(data["season_code"], str) and 2 <= len(data["season_code"]) <= 4
    for field in (
        "start_date",
        "end_date",
        "slot_return_deadline_utc",
        "filing_change_window_close_utc",
    ):
        assert_iso_timestamp(data[field], field)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "ARCHIVED")
    assert isinstance(data["held_series_count"], int)


def assert_aircraft(data: dict) -> None:
    assert_audit_fields(data)
    assert_uuid(data["carrier_id"], "carrier_id")
    assert_uuid(data["base_station_id"], "base_station_id")
    assert 4 <= len(data["registration"]) <= 8
    assert re.fullmatch(r"[A-Z0-9]{3,4}", data["fleet_type_code"])
    assert data["seats"] >= 1
    assert data["min_turn_minutes"] >= 0
    assert data["max_daily_block_minutes"] >= 1
    assert data["required_check_minutes"] >= 0
    assert isinstance(data["maintenance_check_required"], bool)
    assert data["status"] in ("IN_SERVICE", "MAINTENANCE_GROUNDED", "RETIRED")
    assert data["assigned_leg_count"] >= 0
    assert data["maintenance_opportunity_minutes"] >= 0
    assert data["cumulative_ground_minutes"] >= 0
    assert data["rotation_feasibility_status"] in (
        "UNCHECKED",
        "FEASIBLE",
        "INFEASIBLE_CONTINUITY",
        "INFEASIBLE_TURN",
        "INFEASIBLE_BLOCK_CAP",
    )
    if data["assigned_leg_count"] == 0:
        assert data["rotation_feasibility_status"] == "UNCHECKED", (
            "rotation_feasibility_status is UNCHECKED only while "
            "assigned_leg_count == 0"
        )
    else:
        assert data["rotation_feasibility_status"] != "UNCHECKED"


def assert_schedule_version(data: dict) -> None:
    assert_audit_fields(data)
    assert_uuid(data["carrier_id"], "carrier_id")
    assert_uuid(data["season_id"], "season_id")
    assert 1 <= len(data["version_label"]) <= 40
    assert data["filing_status"] in (
        "DRAFT",
        "VALIDATED",
        "FILED",
        "SUPERSEDED",
        "WITHDRAWN",
    )
    assert data["compliance_state"] in ("CLEAN", "WARNED", "BLOCKED")
    assert_integer_cents(data["filing_charge_budget_cents"], "filing_charge_budget_cents")
    assert_integer_cents(
        data["filing_charge_accrued_cents"], "filing_charge_accrued_cents"
    )
    assert data["filing_charge_budget_cents"] >= 0
    assert data["filing_charge_accrued_cents"] >= 0
    for counter in (
        "leg_count",
        "unslotted_leg_count",
        "curfew_violation_count",
        "mct_violation_count",
        "gate_overflow_count",
        "at_risk_slot_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter
    assert_two_decimal_number(
        data["schedule_compliance_score"], "schedule_compliance_score"
    )
    assert 0.00 <= data["schedule_compliance_score"] <= 100.00


def assert_flight_leg(data: dict) -> None:
    assert_audit_fields(data)
    assert_uuid(data["schedule_version_id"], "schedule_version_id")
    assert 3 <= len(data["flight_number"]) <= 8
    assert_uuid(data["origin_station_id"], "origin_station_id")
    assert_uuid(data["dest_station_id"], "dest_station_id")
    assert data["origin_station_id"] != data["dest_station_id"]
    assert_iso_timestamp(data["dep_utc"], "dep_utc")
    assert_iso_timestamp(data["arr_utc"], "arr_utc")
    assert data["status"] in (
        "DRAFT",
        "ASSIGNED",
        "SLOT_BACKED",
        "FILED",
        "REFILE_REQUIRED",
        "CANCELLED",
    )
    assert isinstance(data["marketing_carrier_ids"], list)
    assert len(data["marketing_carrier_ids"]) <= 4
    assert isinstance(data["block_minutes"], int) and data["block_minutes"] > 0
    assert isinstance(data["is_international"], bool)
    assert isinstance(data["mct_shortfall_minutes"], int)
    assert data["mct_shortfall_minutes"] >= 0
    for counter in ("booked_first", "booked_business", "booked_economy"):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter
    assert isinstance(data["open_obligation_count"], int)
    assert data["open_obligation_count"] >= 0


def assert_slot_holding(data: dict) -> None:
    assert_audit_fields(data)
    assert_uuid(data["station_id"], "station_id")
    assert_uuid(data["season_id"], "season_id")
    assert_uuid(data["carrier_id"], "carrier_id")
    assert data["movement_type"] in ("ARRIVAL", "DEPARTURE")
    assert_iso_timestamp(data["slot_time_utc"], "slot_time_utc")
    assert re.fullmatch(r"[1-7]{1,7}", data["days_of_week"]), data["days_of_week"]
    digits = list(data["days_of_week"])
    assert digits == sorted(set(digits)), (
        "days_of_week digits must be distinct and strictly ascending"
    )
    assert 1 <= data["series_weeks"] <= 26
    assert isinstance(data["historic_precedence"], bool)
    assert data["holding_status"] in (
        "HELD",
        "RETURNED",
        "TRANSFERRED_OUT",
        "LOST",
        "EXPIRED",
    )
    assert data["planned_operations"] == data["series_weeks"] * len(digits), (
        "planned_operations is series_weeks multiplied by the number of digits "
        "in days_of_week"
    )
    assert data["attached_operations"] >= 0
    assert data["credited_operations"] >= 0
    assert_two_decimal_number(data["utilization_pct"], "utilization_pct")
    assert_two_decimal_number(
        data["utilization_pct_as_filed"], "utilization_pct_as_filed"
    )
    assert isinstance(data["at_risk_of_loss"], bool)


def assert_slot_utilization_record(data: dict) -> None:
    """The immutable log row: only id and created_at, no updated_at, no
    version."""
    assert_uuid(data.get("id"))
    assert_iso_timestamp(data.get("created_at"), "created_at")
    assert_keys_absent(data, "updated_at", "version")
    assert_uuid(data["slot_holding_id"], "slot_holding_id")
    assert_iso_timestamp(data["operation_date"], "operation_date")
    assert data["outcome"] in (
        "OPERATED",
        "CANCELLED_CARRIER",
        "CANCELLED_ATC",
        "NOT_OPERATED",
        "RETURNED_IN_TIME",
    )
    assert isinstance(data["credited"], bool)
    assert isinstance(data["recorded_by_user_id"], str)
    assert data["recorded_by_user_id"] != ""


def assert_slot_transaction(data: dict) -> None:
    assert_audit_fields(data)
    assert data["kind"] in ("EXCHANGE", "TRANSFER")
    assert_uuid(data["initiating_carrier_id"], "initiating_carrier_id")
    assert_uuid(data["counterparty_carrier_id"], "counterparty_carrier_id")
    assert data["initiating_carrier_id"] != data["counterparty_carrier_id"]
    assert_uuid(data["offered_slot_holding_id"], "offered_slot_holding_id")
    assert data["status"] in (
        "PROPOSED",
        "COUNTERPARTY_ACCEPTED",
        "COUNTERPARTY_REJECTED",
        "COORDINATOR_DENIED",
        "EXECUTED",
        "WITHDRAWN",
    )
    assert_iso_timestamp(data["response_deadline_utc"], "response_deadline_utc")
    assert isinstance(data["proposed_by_user_id"], str)


def assert_filing_submission(data: dict) -> None:
    assert_audit_fields(data)
    assert_uuid(data["schedule_version_id"], "schedule_version_id")
    assert data["distribution_system"] in ("IATA_SSIM", "OAG", "GDS_ATPCO")
    assert data["change_window"] in ("STANDARD", "EXPEDITED", "EMERGENCY")
    assert data["status"] in ("QUEUED", "TRANSMITTED", "ACKNOWLEDGED", "REJECTED")
    assert isinstance(data["changed_leg_count"], int)
    assert data["changed_leg_count"] >= 0
    assert_integer_cents(data["base_charge_subtotal_cents"], "base_charge_subtotal_cents")
    assert_integer_cents(data["expedite_fee_cents"], "expedite_fee_cents")
    assert_integer_cents(data["total_charge_cents"], "total_charge_cents")
    assert_two_decimal_number(data["expedite_rate_pct"], "expedite_rate_pct")
    assert data["codeshare_sync_status"] in (
        "NOT_REQUIRED",
        "PENDING_ACK",
        "SYNCHRONIZED",
    )
    assert isinstance(data["codeshare_ack_carrier_ids"], list)
    assert isinstance(data["resync_required"], bool)
    assert isinstance(data["submitted_by_user_id"], str)


def assert_route_authority(data: dict) -> None:
    assert_audit_fields(data)
    assert_uuid(data["carrier_id"], "carrier_id")
    assert re.fullmatch(r"[A-Z]{2}", data["origin_country_code"])
    assert re.fullmatch(r"[A-Z]{2}", data["dest_country_code"])
    assert data["origin_country_code"] != data["dest_country_code"]
    assert data["freedom_type"] in ("THIRD_FOURTH", "FIFTH", "SEVENTH")
    assert data["weekly_frequency_cap"] >= 1
    assert_iso_timestamp(data["granted_from_utc"], "granted_from_utc")
    assert_iso_timestamp(data["granted_until_utc"], "granted_until_utc")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")


def assert_notification_obligation(data: dict) -> None:
    assert_audit_fields(data)
    assert_uuid(data["flight_leg_id"], "flight_leg_id")
    assert data["trigger_kind"] in ("RETIME", "CANCELLATION", "SLOT_LOSS")
    assert isinstance(data["change_magnitude_minutes"], int)
    assert data["change_magnitude_minutes"] >= 0
    for cabin in ("booked_first", "booked_business", "booked_economy"):
        assert isinstance(data[cabin], int) and data[cabin] >= 0, cabin
    assert data["booked_total"] == (
        data["booked_first"] + data["booked_business"] + data["booked_economy"]
    ), "booked_total is the sum of the three cabin snapshots"
    assert data["booked_total"] > 0, "no row is persisted for a booked total of zero"
    assert data["obligation_tier"] in ("ADVISORY", "MANDATORY_REACCOMMODATION")
    assert_integer_cents(data["compensation_cents"], "compensation_cents")
    assert_iso_timestamp(data["notify_deadline_utc"], "notify_deadline_utc")
    assert data["status"] in ("PENDING", "DISPATCHED", "WAIVED")
    if data["dispatched_channel"] is not None:
        assert data["dispatched_channel"] in ("EMAIL", "SMS", "AGENCY_QUEUE")
    assert isinstance(data["late_dispatch"], bool)


# ─── Domain invariant checkers ────────────────────────────────────────────

def expected_compliance_score(
    curfew_violation_count: int = 0,
    mct_violation_count: int = 0,
    gate_overflow_count: int = 0,
    unslotted_leg_count: int = 0,
    at_risk_slot_count: int = 0,
) -> float:
    """The weighted score of PRD §3.7: a capped penalty subtracted from
    100.00."""
    raw = (
        curfew_violation_count * PENALTY_PER_CURFEW_VIOLATION
        + mct_violation_count * PENALTY_PER_MCT_VIOLATION
        + gate_overflow_count * PENALTY_PER_GATE_OVERFLOW
        + unslotted_leg_count * PENALTY_PER_UNSLOTTED_LEG
        + at_risk_slot_count * PENALTY_PER_AT_RISK_SLOT
    )
    capped = min(raw, PENALTY_CAP)
    return round(max(0.00, SCORE_BASE - capped) + 1e-9, 2)


def expected_compliance_state(score: float, at_risk_slot_count: int) -> str:
    if at_risk_slot_count >= 1 or score < 60.00:
        return "BLOCKED"
    if score < 85.00:
        return "WARNED"
    return "CLEAN"


def assert_score_matches_counters(version: dict) -> None:
    """The score and the posture must agree with the five counters on the same
    row."""
    expected = expected_compliance_score(
        version["curfew_violation_count"],
        version["mct_violation_count"],
        version["gate_overflow_count"],
        version["unslotted_leg_count"],
        version["at_risk_slot_count"],
    )
    assert version["schedule_compliance_score"] == pytest.approx(expected, abs=0.005), (
        f"score {version['schedule_compliance_score']} does not match the "
        f"weighted penalty of its counters (expected {expected})"
    )
    expected_state = expected_compliance_state(
        version["schedule_compliance_score"], version["at_risk_slot_count"]
    )
    assert version["compliance_state"] == expected_state, (
        f"compliance_state {version['compliance_state']} does not follow from "
        f"score {version['schedule_compliance_score']} and at_risk_slot_count "
        f"{version['at_risk_slot_count']} (expected {expected_state})"
    )


def assert_utilization_math(holding: dict) -> None:
    """Both utilization variants share planned_operations as denominator."""
    planned = holding["planned_operations"]
    if planned == 0:
        assert holding["utilization_pct"] == pytest.approx(0.00)
        assert holding["utilization_pct_as_filed"] == pytest.approx(0.00)
        return
    as_operated = round(holding["credited_operations"] * 100 / planned + 1e-9, 2)
    as_filed = round(holding["attached_operations"] * 100 / planned + 1e-9, 2)
    assert holding["utilization_pct"] == pytest.approx(as_operated, abs=0.005), (
        f"utilization_pct should be {as_operated}, got {holding['utilization_pct']}"
    )
    assert holding["utilization_pct_as_filed"] == pytest.approx(as_filed, abs=0.005), (
        f"utilization_pct_as_filed should be {as_filed}, got "
        f"{holding['utilization_pct_as_filed']}"
    )
    expected_at_risk = (
        holding["holding_status"] == "HELD"
        and holding["attached_operations"] >= 1
        and holding["utilization_pct_as_filed"] < AT_RISK_THRESHOLD_PCT
    )
    assert holding["at_risk_of_loss"] is expected_at_risk, (
        "at_risk_of_loss is true exactly when the series is still HELD, "
        "attached_operations is at least 1, and utilization_pct_as_filed is "
        f"strictly below 80.00 (expected {expected_at_risk})"
    )


def expected_charge_breakdown(changed_leg_count: int, change_window: str) -> dict:
    """The five ordered steps of PRD §3.8."""
    raw = changed_leg_count * CHARGE_PER_LEG_CENTS
    if changed_leg_count <= 5:
        surcharge_pct = 0.00
    elif changed_leg_count <= 20:
        surcharge_pct = 12.50
    else:
        surcharge_pct = 22.00
    subtotal = int((raw * (100 + surcharge_pct)) / 100 + 0.5)
    rate = EXPEDITE_RATE_PCT[change_window]
    fee = int((subtotal * rate) / 100 + 0.5)
    return {
        "changed_leg_count": changed_leg_count,
        "base_charge_subtotal_cents": subtotal,
        "expedite_rate_pct": rate,
        "expedite_fee_cents": fee,
        "total_charge_cents": subtotal + fee,
    }


def assert_charge_breakdown(submission: dict) -> None:
    expected = expected_charge_breakdown(
        submission["changed_leg_count"], submission["change_window"]
    )
    for field, value in expected.items():
        if field == "expedite_rate_pct":
            assert submission[field] == pytest.approx(value, abs=0.005), (
                f"{field}: expected {value}, got {submission[field]}"
            )
        else:
            assert submission[field] == value, (
                f"{field}: expected {value}, got {submission[field]}"
            )
    assert submission["total_charge_cents"] == (
        submission["base_charge_subtotal_cents"] + submission["expedite_fee_cents"]
    )


def expected_compensation_cents(
    booked_first: int, booked_business: int, booked_economy: int, tier: str
) -> int:
    """Each cabin amount is rounded to whole cents first, and only then are the
    three summed (PRD §3.9)."""
    multiplier = TIER_MULTIPLIER_PCT[tier]
    total = 0
    for count, rate_key in (
        (booked_first, "first"),
        (booked_business, "business"),
        (booked_economy, "economy"),
    ):
        amount = count * COMPENSATION_RATE_CENTS[rate_key] * multiplier / 100
        total += int(amount + 0.5)
    return total


def assert_compensation(obligation: dict) -> None:
    expected = expected_compensation_cents(
        obligation["booked_first"],
        obligation["booked_business"],
        obligation["booked_economy"],
        obligation["obligation_tier"],
    )
    assert obligation["compensation_cents"] == expected, (
        f"compensation_cents should be {expected} with each cabin rounded "
        f"before summing, got {obligation['compensation_cents']}"
    )


def assert_charge_ledger_matches_submissions(version: dict, submissions: list) -> None:
    """filing_charge_accrued_cents always equals the sum of total_charge_cents
    over the version's TRANSMITTED or ACKNOWLEDGED submissions."""
    expected = sum(
        s["total_charge_cents"]
        for s in submissions
        if s["status"] in ("TRANSMITTED", "ACKNOWLEDGED")
    )
    assert version["filing_charge_accrued_cents"] == expected, (
        f"filing_charge_accrued_cents should be {expected}, got "
        f"{version['filing_charge_accrued_cents']}"
    )
