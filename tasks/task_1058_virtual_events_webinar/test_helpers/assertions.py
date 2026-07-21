"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and any number of
    fractional-second digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "instant"):
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} {expected_iso}, got {actual}"
    )


def shift_iso(base_iso: str, **delta) -> str:
    """Return base_iso shifted by the given timedelta keywords, rendered as UTC."""
    moved = parse_instant(base_iso) + timedelta(**delta)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_event(data: dict):
    _assert_common_fields(data, "event")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["state"] in [
        "DRAFT", "PUBLISHED", "LIVE", "ENDED", "SETTLED", "CANCELLED",
    ], f"unexpected event state {data['state']!r}"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    for counter in (
        "registered_count",
        "gross_collected_cents",
        "streamed_minutes_total",
        "published_recording_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"event.{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert isinstance(data["settlement_adjustment_cents"], int)


def assert_ticket_type(data: dict):
    _assert_common_fields(data, "ticket_type")
    assert data["tier"] in ["GENERAL", "VIP", "SPONSOR", "SPEAKER"]
    assert data["gating_level"] in ["LIVE_ONLY", "ON_DEMAND", "BOTH"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["quota"], int) and data["quota"] >= 1
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert data["availability_status"] in ["AVAILABLE", "SOLD_OUT"]


def assert_registration(data: dict):
    _assert_common_fields(data, "registration")
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert data["attendance_status"] in [
        "WAITLISTED", "REGISTERED", "CHECKED_IN", "ATTENDED", "NO_SHOW", "WITHDRAWN",
    ]
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["watched_minutes"], int) and data["watched_minutes"] >= 0
    assert isinstance(data["accepted_meeting_count"], int)
    assert data["final_amount_due_cents"] is None or isinstance(
        data["final_amount_due_cents"], int
    )


def assert_track(data: dict):
    _assert_common_fields(data, "track")
    assert isinstance(data["scheduled_session_count"], int)
    assert data["scheduled_session_count"] >= 0


def assert_session(data: dict):
    _assert_common_fields(data, "session")
    assert data["state"] in ["DRAFT", "SCHEDULED", "LIVE", "COMPLETED", "CANCELLED"]
    assert data["session_type"] in ["LIVE", "SIMULIVE", "ON_DEMAND"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["accepted_speaker_count"], int)
    assert parse_instant(data["ends_at"]) > parse_instant(data["starts_at"])


def assert_speaker(data: dict):
    _assert_common_fields(data, "speaker")
    assert data["engagement_status"] in ["UNASSIGNED", "ENGAGED"]
    assert isinstance(data["accepted_session_count"], int)
    expected = "ENGAGED" if data["accepted_session_count"] >= 1 else "UNASSIGNED"
    assert data["engagement_status"] == expected, (
        "engagement_status reads ENGAGED whenever accepted_session_count is one or "
        f"more; got {data['engagement_status']} at count {data['accepted_session_count']}"
    )


def assert_session_speaker(data: dict):
    _assert_common_fields(data, "session_speaker")
    assert data["state"] in ["INVITED", "ACCEPTED", "DECLINED", "WITHDRAWN", "RELEASED"]
    assert data["speaking_role"] in ["HOST", "PANELIST", "MODERATOR"]
    assert isinstance(data["invite_round"], int) and data["invite_round"] >= 1


def assert_broadcast(data: dict):
    _assert_common_fields(data, "broadcast")
    assert data["state"] in ["SCHEDULED", "PREVIEW", "LIVE", "ENDED", "ABORTED"]
    assert data["ingest_region"] in ["US_EAST", "US_WEST", "EU_WEST", "AP_SOUTH"]
    assert isinstance(data["streamed_minutes"], int) and data["streamed_minutes"] >= 0


def assert_recording(data: dict):
    _assert_common_fields(data, "recording")
    assert data["state"] in [
        "PENDING", "PROCESSING", "READY", "PUBLISHED", "RETRACTED", "DELETED",
    ]
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 0
    assert isinstance(data["view_count"], int) and data["view_count"] >= 0


def assert_sponsor(data: dict):
    _assert_common_fields(data, "sponsor")
    assert data["package_tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert data["contract_status"] in ["UNSIGNED", "SIGNED"]


def assert_booth(data: dict):
    _assert_common_fields(data, "booth")
    assert data["state"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "CHANGES_REQUESTED", "LIVE", "SUSPENDED",
    ]
    assert isinstance(data["lead_quota"], int) and data["lead_quota"] >= 0
    assert isinstance(data["captured_lead_count"], int)
    assert isinstance(data["stream_minutes_total"], int)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_lead(data: dict):
    _assert_common_fields(data, "lead")
    assert isinstance(data["booth_visits"], int)
    assert isinstance(data["doc_downloads"], int)
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert data["score_variant"] in ["BOOTH_WEIGHTED", "ENGAGEMENT_WEIGHTED"]
    assert isinstance(data["is_hot"], bool)
    assert data["is_hot"] == (data["score"] >= 60), (
        f"is_hot must be true exactly when score is at least 60; score={data['score']}, "
        f"is_hot={data['is_hot']}"
    )


def assert_match_request(data: dict):
    _assert_common_fields(data, "match_request")
    assert data["state"] in ["PENDING", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED"]
    assert parse_instant(data["window_end"]) > parse_instant(data["window_start"])


def assert_settlement(data: dict):
    _assert_common_fields(data, "settlement")
    assert data["subject_type"] in ["EVENT", "SPONSOR"]
    assert data["state"] in ["DRAFT", "ISSUED", "PAID", "VOID"]
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        for key in ("label", "units", "unit_cents", "line_total_cents"):
            assert key in line, f"settlement line item is missing {key}: {line}"
        assert isinstance(line["line_total_cents"], int), (
            f"line_total_cents must be whole cents, got {line['line_total_cents']!r}"
        )
    for key in (
        "subtotal_cents", "tax_cents", "platform_fee_cents",
        "total_cents", "organizer_payout_cents",
    ):
        assert isinstance(data[key], int), (
            f"settlement.{key} must be an integer number of cents, got {data[key]!r}"
        )


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------

def assert_seat_inventory_conservation(ticket_type: dict, registrations: list):
    """sold_count equals the count of registrations on that ticket type whose
    attendance_status is neither WAITLISTED nor WITHDRAWN."""
    holding = [
        r for r in registrations
        if r["ticket_type_id"] == ticket_type["id"]
        and r["attendance_status"] not in ("WAITLISTED", "WITHDRAWN")
    ]
    assert ticket_type["sold_count"] == len(holding), (
        f"Expected sold_count {len(holding)} (seat-holding rows), got "
        f"{ticket_type['sold_count']}"
    )


def assert_collected_money_conservation(event: dict, registrations: list):
    """gross_collected_cents equals the sum of amount_paid_cents over PAID rows."""
    expected = sum(
        r["amount_paid_cents"] for r in registrations if r["payment_status"] == "PAID"
    )
    assert event["gross_collected_cents"] == expected, (
        f"Expected gross_collected_cents {expected}, got {event['gross_collected_cents']}"
    )


def assert_availability_matches_quota(ticket_type: dict):
    expected = "SOLD_OUT" if ticket_type["quota"] - ticket_type["sold_count"] <= 0 else "AVAILABLE"
    assert ticket_type["availability_status"] == expected, (
        f"Expected availability_status {expected} at sold_count "
        f"{ticket_type['sold_count']} of quota {ticket_type['quota']}, got "
        f"{ticket_type['availability_status']}"
    )


def assert_line_item(line: dict, label: str, units, unit_cents, line_total_cents: int):
    assert line["label"] == label, f"Expected line label {label}, got {line['label']}"
    assert line["units"] == units, (
        f"Expected {label} units {units}, got {line['units']}"
    )
    assert float(line["unit_cents"]) == float(unit_cents), (
        f"Expected {label} unit_cents {unit_cents}, got {line['unit_cents']}"
    )
    assert line["line_total_cents"] == line_total_cents, (
        f"Expected {label} line_total_cents {line_total_cents}, got "
        f"{line['line_total_cents']}"
    )
