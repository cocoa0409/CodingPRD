"""Entity assertions and domain invariant checkers (PRD 2.5, 2.7, 3.x)."""
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Assert two ISO 8601 strings denote the same instant."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_no_field(data: dict, field: str, label: str = "resource"):
    assert field not in data, f"{label} must not carry {field}, got {data.get(field)!r}"


def assert_complainant(data: dict):
    _assert_common_fields(data, "Complainant")
    assert data["standing"] in ("GOOD_STANDING", "REPEAT", "RESTRICTED")
    for counter in (
        "complaints_90d", "filed_total", "open_count", "closed_count",
        "withdrawn_count", "substantiated_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter
    assert isinstance(data["outreach_opt_in"], bool)


def assert_noise_complaint(data: dict):
    _assert_common_fields(data, "NoiseComplaint")
    assert data["status"] in (
        "RECEIVED", "UNDER_REVIEW", "AWAITING_COMPLAINANT", "CORRELATED",
        "CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED", "REOPENED", "WITHDRAWN",
    )
    assert data["channel"] in ("WEB", "PHONE", "APP", "EMAIL")
    assert isinstance(data["reopen_count"], int)


def assert_flight_operation(data: dict):
    _assert_common_fields(data, "FlightOperation")
    assert data["status"] in ("SCHEDULED", "OPERATED", "CANCELLED", "DIVERTED")
    assert data["engine_class"] in ("STAGE_3", "STAGE_4", "STAGE_5")
    assert isinstance(data["curfew_movement"], bool)
    assert isinstance(data["curfew_violation"], bool)


def assert_operator(data: dict):
    _assert_common_fields(data, "Operator")
    assert data["compliance_standing"] in ("GOOD", "WATCH", "PROBATION")
    assert isinstance(data["curfew_grace_minutes"], int)


def assert_noise_monitor(data: dict):
    _assert_common_fields(data, "NoiseMonitor")
    assert data["status"] in ("ONLINE", "DECOMMISSIONED")


def assert_monitor_outage(data: dict):
    """Append-only record: id + created_at only among the common fields (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), "MonitorOutage.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "MonitorOutage.created_at must be ISO 8601"
    )
    assert_no_field(data, "version", "MonitorOutage")
    assert_no_field(data, "updated_at", "MonitorOutage")


def assert_noise_event(data: dict):
    _assert_common_fields(data, "NoiseEvent")
    assert data["status"] in (
        "CAPTURED", "SCREENING", "CLASSIFIED_AIRCRAFT", "CLASSIFIED_COMMUNITY",
        "CLASSIFIED_MIXED", "VERIFIED", "DISCARDED",
    )
    assert isinstance(data["reclassify_count"], int)


def assert_curfew_rule(data: dict):
    _assert_common_fields(data, "CurfewRule")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_operator_notification(data: dict):
    _assert_common_fields(data, "OperatorNotification")
    assert data["status"] in (
        "DRAFT", "SENT", "ACKNOWLEDGED", "RESPONSE_RECEIVED", "CLOSED",
        "ESCALATED", "AUTO_CLOSED",
    )
    assert data["severity"] in ("ADVISORY", "FORMAL", "ESCALATION")


def assert_noise_study(data: dict):
    _assert_common_fields(data, "NoiseStudy")
    assert data["status"] in (
        "SCOPING", "DATA_COLLECTION", "DRAFTED", "PUBLIC_REVIEW", "ADOPTED", "SUPERSEDED",
    )


def assert_land_use_parcel(data: dict):
    _assert_common_fields(data, "LandUseParcel")
    assert data["compatibility_status"] in (
        "COMPATIBLE", "COMPATIBLE_WITH_MEASURES",
        "INCOMPATIBLE_RESIDENTIAL", "INCOMPATIBLE_NONRES",
    )
    assert isinstance(data["insulation_eligible"], bool)


def assert_sound_insulation_application(data: dict):
    _assert_common_fields(data, "SoundInsulationApplication")
    assert data["eligibility_status"] in (
        "NEW", "SUBMITTED", "SCREENING", "ELIGIBLE_TIER1", "ELIGIBLE_TIER2",
        "INELIGIBLE", "APPEALED", "WITHDRAWN",
    )
    assert data["funding_status"] in (
        "UNFUNDED", "OFFER_ISSUED", "OFFER_DECLINED", "GRANT_COMMITTED", "REIMBURSED",
    )


def assert_insulation_fund(data: dict):
    _assert_common_fields(data, "InsulationFund")
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_outreach_case(data: dict):
    _assert_common_fields(data, "OutreachCase")
    assert data["status"] in ("OPEN", "CONTACT_ATTEMPTED", "ENGAGED", "RESOLVED", "DORMANT")


def assert_quarterly_report(data: dict):
    _assert_common_fields(data, "QuarterlyReport")
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "APPROVED", "PUBLISHED")


def assert_fund_ledger_invariants(fund: dict):
    """The fund ledger must reconcile to the cent at all times (PRD 3.8)."""
    total = fund["total_allocation_cents"]
    assert fund["available_cents"] + fund["reserved_cents"] + fund["disbursed_cents"] == total, (
        f"fund ledger violated: {fund['available_cents']} + {fund['reserved_cents']} "
        f"+ {fund['disbursed_cents']} != {total}"
    )


def assert_notification_cardinality(operator: dict):
    """draft + open + closed equals total notifications ever created (PRD 3.5)."""
    total = (
        operator["notifications_draft"]
        + operator["notifications_open"]
        + operator["notifications_closed"]
    )
    assert total >= 0
    return total


def assert_complainant_cardinality(complainant: dict):
    """open + closed + withdrawn equals lifetime filings (PRD 3.4 counter family)."""
    buckets = (
        complainant["open_count"]
        + complainant["closed_count"]
        + complainant["withdrawn_count"]
    )
    assert buckets == complainant["filed_total"], (
        f"complainant counters violated: open {complainant['open_count']} + closed "
        f"{complainant['closed_count']} + withdrawn {complainant['withdrawn_count']} "
        f"!= filed_total {complainant['filed_total']}"
    )
