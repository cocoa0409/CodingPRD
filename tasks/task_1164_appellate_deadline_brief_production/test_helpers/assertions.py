"""Entity assertions, timestamp helpers, and domain invariant checkers (PRD §2.4, §2.7)."""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.7: calendar-day arithmetic preserves time-of-day;
# timestamps compare at one-second precision. Comparisons are done on parsed
# instants so rendering differences (e.g. fractional digits) never matter.
# ---------------------------------------------------------------------------

def parse_ts(value) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits / 'Z')."""
    assert isinstance(value, str) and value, f"expected ISO timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def add_calendar_days(value, days: int) -> datetime:
    """PRD §2.7 calendar arithmetic: add whole days, preserving time-of-day."""
    return parse_ts(value) + timedelta(days=days)


def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def assert_instant_equal(actual, expected, msg=""):
    """Assert two ISO timestamps denote the same instant (second precision)."""
    assert parse_ts(actual) == parse_ts(expected), (
        msg or f"expected instant {expected}, got {actual}"
    )


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_court(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["jurisdiction_type"] in ("FEDERAL", "STATE", "TRIBAL")
    assert isinstance(data["appeal_deadline_days"], int)
    assert isinstance(data["reply_brief_window_days"], int)
    assert isinstance(data["uses_word_count"], bool)
    assert isinstance(data["efiling_required"], bool)


def assert_attorney(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bar_number"], str) and data["bar_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["admitted_court_ids"], list)


def assert_case(data: dict):
    _assert_common_fields(data)
    assert data["posture"] in (
        "OPEN", "RECORD_PENDING", "BRIEFING", "ARGUMENT_PENDING", "DECIDED", "CLOSED"
    )
    assert isinstance(data["docket_number"], str) and data["docket_number"]
    assert data["appellant_side"] in ("APPELLANT", "APPELLEE", "CROSS_APPELLANT")


def assert_appeal_event(data: dict):
    _assert_common_fields(data)
    assert data["event_type"] in (
        "JUDGMENT_ENTERED", "NOTICE_FILED", "POST_JUDGMENT_MOTION_FILED",
        "POST_JUDGMENT_MOTION_DECIDED", "RECORD_COMPLETE", "BRIEF_FILED",
        "DECISION_ISSUED",
    )
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


def assert_deadline(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in (
        "NOTICE_OF_APPEAL", "RECORD_DESIGNATION", "TRANSCRIPT_ORDER",
        "OPENING_BRIEF", "RESPONSE_BRIEF", "REPLY_BRIEF",
        "REHEARING_PETITION", "CERT_PETITION",
    )
    assert isinstance(data["tolled"], bool)
    assert isinstance(data["met"], bool)


def assert_record(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PENDING_DESIGNATION", "DESIGNATED", "ASSEMBLING", "COMPLETE", "FILED"
    )
    assert isinstance(data["completeness_pct"], int)
    assert 0 <= data["completeness_pct"] <= 100


def assert_transcript_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "ORDERED", "IN_PREPARATION", "DELIVERED", "FILED", "CANCELLED"
    )
    assert isinstance(data["estimated_pages"], int)
    assert isinstance(data["actual_pages"], int)


def assert_briefing_schedule(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "ACTIVE", "COMPLETE", "VACATED")
    assert isinstance(data["extensions_granted_count"], int)


def assert_brief(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "READY", "EFILED", "ACCEPTED", "REJECTED", "STRICKEN"
    )
    assert data["brief_type"] in ("OPENING", "RESPONSE", "REPLY", "AMICUS")
    assert isinstance(data["over_limit"], bool)
    assert isinstance(data["page_count"], int)
    assert isinstance(data["word_count"], int)


def assert_toa(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["citation_count"], int)
    assert isinstance(data["verified_count"], int)
    assert isinstance(data["unverified_count"], int)


def assert_citation(data: dict):
    _assert_common_fields(data)
    assert data["authority_type"] in ("CASE", "STATUTE", "RULE", "SECONDARY")
    assert isinstance(data["verified"], bool)


def assert_extension_motion(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "GRANTED", "DENIED", "WITHDRAWN")
    assert data["target"] in ("OPENING", "RESPONSE", "REPLY")
    assert isinstance(data["requested_days"], int)
    assert isinstance(data["granted_days"], int)


def assert_filing(data: dict):
    _assert_common_fields(data)
    assert data["filing_type"] in (
        "NOTICE_OF_APPEAL", "RECORD", "BRIEF", "EXTENSION_MOTION",
        "REHEARING_PETITION", "CERT_PETITION",
    )
    assert data["method"] in ("EFILE", "PAPER", "HAND")
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["served_party_emails"], list)


def assert_oral_argument(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "SCHEDULED", "HELD", "WAIVED", "CONTINUED")
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["moot_completed"], bool)


def assert_decision(data: dict):
    _assert_common_fields(data)
    assert data["outcome"] in ("AFFIRMED", "REVERSED", "REMANDED", "DISMISSED", "MIXED")
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("rehearing_deadline_at", ""))


def assert_petition(data: dict):
    _assert_common_fields(data)
    assert data["petition_type"] in ("REHEARING", "REHEARING_EN_BANC", "CERTIORARI")
    assert data["status"] in ("DRAFT", "FILED", "GRANTED", "DENIED", "WITHDRAWN")


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def find_deadline(deadlines: list, kind: str) -> dict:
    """Return the single deadline row of the given kind from a deadline list."""
    matches = [d for d in deadlines if d.get("kind") == kind]
    assert len(matches) >= 1, f"no deadline of kind {kind} in {[d.get('kind') for d in deadlines]}"
    return matches[0]


def assert_schedule_dates_ordered(schedule: dict):
    """PRD §3.4 invariant: opening <= response <= reply after any shift."""
    opening = parse_ts(schedule["opening_due_at"])
    response = parse_ts(schedule["response_due_at"])
    reply = parse_ts(schedule["reply_due_at"])
    assert opening <= response <= reply, (
        f"schedule dates out of order: {opening} / {response} / {reply}"
    )
