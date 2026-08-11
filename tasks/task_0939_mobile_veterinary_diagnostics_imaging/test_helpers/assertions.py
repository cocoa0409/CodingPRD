"""Entity assertions, instant comparison and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ADMIN_FEE_RATE_PERCENT


# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant.

    The PRD says client-supplied datetimes "are interpreted as instants and
    compared as instants; a client-supplied value that carries a different
    textual form denotes the same moment and must compare equal to it".  This
    accepts a trailing ``Z``, an explicit ``+00:00`` offset, and any number of
    fractional-second digits.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, message: str = ""):
    """Compare two datetimes as instants, never as strings.

    ``2026-05-01T00:00:00.000Z`` and ``2026-05-01T00:00:00Z`` denote the same
    moment and must compare equal.
    """
    assert actual is not None, f"expected instant {expected!r}, got None. {message}"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, (
        f"expected instant {expected!r} but got {actual!r} "
        f"(parsed {want.isoformat()} vs {got.isoformat()}). {message}"
    )


def assert_instant_is_null(actual, message: str = ""):
    assert actual is None, f"expected null instant, got {actual!r}. {message}"


def round_half_up(value: float) -> int:
    """Round half up, away from zero, as PRD section 2.6 requires."""
    from decimal import Decimal, ROUND_HALF_UP

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_admin_fee_cents(base_cents: int, trip_share_cents: int, stat_surcharge_cents: int) -> int:
    """One single rounding applied to the study's subtotal (PRD section 3.9 step 5)."""
    subtotal = base_cents + trip_share_cents + stat_surcharge_cents
    return round_half_up(subtotal * ADMIN_FEE_RATE_PERCENT / 100.0)


def expected_trip_share_allocation(trip_fee_cents: int, size: int):
    """Floor the share, then hand the leftover out one cent at a time to the
    earliest-created members (PRD section 3.9 step 3)."""
    if size <= 0:
        return []
    base = trip_fee_cents // size
    leftover = trip_fee_cents - base * size
    return [base + (1 if i < leftover else 0) for i in range(size)]


# --------------------------------------------------------------------------
# Common-field shape
# --------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """id + created_at + updated_at + version, per PRD section 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict):
    """id + created_at only — no updated_at and no version at all."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only records carry no updated_at field"
    assert "version" not in data, "append-only records carry no version field"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_clinic(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["billing_hold_status"] in ("CLEAR", "HOLD")
    assert isinstance(data["business_open_minute"], int)
    assert isinstance(data["business_close_minute"], int)
    assert 0 <= data["business_open_minute"] < data["business_close_minute"] <= 1440
    assert isinstance(data["business_days"], list) and data["business_days"]


def assert_contract(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ("PREPAID_BLOCK", "PER_STUDY_LIST")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert_block_conservation(data)


def assert_mobile_unit(data: dict):
    assert_common_fields(data)
    assert data["service_status"] in ("IN_SERVICE", "OUT_OF_SERVICE", "MAINTENANCE")
    assert data["max_stops"] >= 1
    assert data["max_shift_minutes"] >= 60


def assert_equipment(data: dict):
    assert_common_fields(data)
    assert data["modality"] in ("RADIOGRAPHY", "ULTRASOUND", "CT", "ECHO")
    assert data["calibration_status"] in ("UNCALIBRATED", "VALID", "EXPIRED", "QUARANTINED")
    assert isinstance(data["usage_count_since_qc"], int) and data["usage_count_since_qc"] >= 0


def assert_technician(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["certified_modalities"], list) and data["certified_modalities"]


def assert_specialist(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "INACTIVE")
    assert isinstance(data["modality_privileges"], list) and data["modality_privileges"]
    assert isinstance(data["species_privileges"], list) and data["species_privileges"]
    assert isinstance(data["stat_eligible"], bool)
    assert data["open_read_count"] >= 0
    assert data["workload_score"] >= 0


def assert_route(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "DISPATCHED", "COMPLETED")
    assert_route_time_partition(data)


def assert_route_stop(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PLANNED", "EN_ROUTE", "ARRIVED", "SERVICED", "BUMPED", "CANCELLED",
    )
    assert data["stop_priority"] in ("ROUTINE", "STAT")
    assert isinstance(data["trip_fee_cents"], int)


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "RETURNED", "REJECTED", "SCHEDULED")
    assert data["species"] in ("CANINE", "FELINE", "EQUINE", "BOVINE", "EXOTIC")
    assert data["study_kind"] in ("MOBILE", "TELERAD")
    assert data["priority"] in ("ROUTINE", "STAT")


def assert_appointment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED",
        "CANCELLED_BY_CLINIC", "CANCELLED_BY_PROVIDER", "NO_SHOW",
    )
    assert_disposition_partition(data)


def assert_study(data: dict):
    assert_common_fields(data)
    assert data["workflow_status"] in (
        "ORDERED", "ACQUIRED", "ASSIGNED", "READ_IN_PROGRESS", "PRELIM_REPORTED",
        "FINALIZED", "REPEAT_PENDING", "CANCELLED", "NOT_PERFORMED",
    )
    assert data["qc_status"] in ("PENDING_QC", "ACCEPTED", "REPEAT_REQUIRED", "NON_DIAGNOSTIC")
    assert data["tat_status"] in ("ACCRUING", "PAUSED", "MET", "BREACHED")
    assert data["billing_status"] in ("UNBILLED", "POSTED", "REVERSED", "NON_BILLABLE")
    assert data["study_kind"] in ("MOBILE", "TELERAD")
    assert data["priority"] in ("ROUTINE", "STAT")
    assert data["priority_source"] in ("NATIVE", "UPGRADED")
    assert_tat_partition(data)


def assert_read_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "DECLINED", "HANDED_BACK", "COMPLETED", "REVOKED",
    )
    assert data["attempt_number"] >= 1


def assert_report(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ("PRELIMINARY", "FINAL", "ADDENDUM")
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETRACTED")
    assert data["report_version"] >= 1


def assert_qc_check(data: dict):
    assert_append_only_fields(data)
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["affected_study_count"], int)


def assert_peer_review(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SAMPLED", "CONCUR", "DISCORDANT")


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "FINALIZED")
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["posted_study_count"], int)


def assert_charge_line(data: dict):
    assert_common_fields(data)
    assert data["kind"] in (
        "STUDY_READ", "TRIP_FEE_SHARE", "STAT_SURCHARGE", "ADMIN_FEE", "CANCELLATION_FEE",
    )
    assert data["status"] in ("ACTIVE", "REVERSED")
    assert isinstance(data["amount_cents"], int)


def assert_block_ledger_entry(data: dict):
    assert_append_only_fields(data)
    assert data["reason"] in ("DRAW", "REFUND_QC")
    assert data["delta_studies"] in (-1, 1)


def assert_notification(data: dict):
    assert_append_only_fields(data)
    assert data["kind"] in (
        "STOP_BUMPED", "APPOINTMENT_CANCELLED", "STUDY_REPEAT_REQUIRED",
        "REPORT_PUBLISHED", "TAT_BREACHED", "STAT_UPGRADED",
    )


# --------------------------------------------------------------------------
# Conservation invariants (PRD section 2.10)
# --------------------------------------------------------------------------
def assert_block_conservation(contract: dict):
    """block_purchased_studies == block_consumed_studies + block_remaining_studies."""
    assert contract["block_purchased_studies"] == (
        contract["block_consumed_studies"] + contract["block_remaining_studies"]
    ), (
        "block conservation broken: purchased "
        f"{contract['block_purchased_studies']} != consumed "
        f"{contract['block_consumed_studies']} + remaining "
        f"{contract['block_remaining_studies']}"
    )


def assert_route_time_partition(route: dict):
    """shift span == planned_occupied_minutes + slack_minutes."""
    span = route["shift_end_minute"] - route["shift_start_minute"]
    assert span == route["planned_occupied_minutes"] + route["slack_minutes"], (
        f"route time partition broken: span {span} != occupied "
        f"{route['planned_occupied_minutes']} + slack {route['slack_minutes']}"
    )


def assert_tat_partition(study: dict):
    """tat_elapsed_minutes == tat_accrued_minutes + tat_paused_minutes, exactly."""
    assert study["tat_elapsed_minutes"] == (
        study["tat_accrued_minutes"] + study["tat_paused_minutes"]
    ), (
        f"turnaround partition broken: elapsed {study['tat_elapsed_minutes']} != "
        f"accrued {study['tat_accrued_minutes']} + paused {study['tat_paused_minutes']}"
    )


def assert_disposition_partition(appointment: dict):
    """ordered == pending + acquired + cancelled + not_performed."""
    total = (
        appointment["pending_studies_count"]
        + appointment["acquired_studies_count"]
        + appointment["cancelled_studies_count"]
        + appointment["not_performed_studies_count"]
    )
    assert appointment["ordered_studies_count"] == total, (
        f"study disposition partition broken: ordered "
        f"{appointment['ordered_studies_count']} != {total}"
    )


def assert_invoice_total_matches_active_lines(invoice: dict, lines: list):
    """An OPEN invoice's total_cents equals the sum of its ACTIVE lines."""
    active_sum = sum(line["amount_cents"] for line in lines if line["status"] == "ACTIVE")
    assert invoice["total_cents"] == active_sum, (
        f"invoice money invariant broken: total_cents {invoice['total_cents']} != "
        f"sum of ACTIVE line amounts {active_sum}"
    )
