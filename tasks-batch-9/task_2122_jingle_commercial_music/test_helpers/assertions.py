"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CUE_TOTAL_BPS

PROJECT_STATUSES = [
    "DRAFT", "BRIEFING", "IN_DEMO", "IN_PRODUCTION", "DELIVERED", "CLOSED", "ON_HOLD",
]
BUDGET_POSTURES = ["HEALTHY", "CONSTRAINED", "FROZEN"]
BRIEF_STATUSES = ["DRAFT", "APPROVED", "SUPERSEDED"]
DEMO_STATUSES = [
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "SHORTLISTED", "SELECTED", "ARCHIVED",
]
AFM_MEMBER_STATUSES = ["SIGNATORY_CLEARED", "NON_UNION", "SUSPENDED"]
SESSION_CALL_STATUSES = [
    "SCHEDULED", "SUSPENDED_BUDGET", "CONFIRMED", "COMPLETED",
    "CANCELLED_INSIDE_WINDOW", "CANCELLED_OUTSIDE_WINDOW",
]
BOOKING_STATUSES = ["BOOKED", "WAGE_ACCRUED", "PENALTY_ACCRUED", "RELEASED"]
LICENSE_DEAL_STATUSES = [
    "DRAFT", "PROPOSED", "ACCEPTED", "ACTIVE", "RENEWAL_DUE", "LAPSED", "SUPERSEDED",
]
MASTER_STATUSES = ["PENDING", "STEMS_DELIVERED", "CLIENT_APPROVED"]
CUESHEET_STATUSES = ["NOT_FILED", "FILED", "REGISTERED"]
CUE_ENTRY_STATUSES = ["ALLOCATED", "VOIDED"]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant coming back from the API."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, field: str = "instant") -> None:
    """Compare a server-stamped instant against the expected logical-clock instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {field} to be {expected_iso}, got {actual}")


def assert_common_fields(data: dict, entity: str = "resource") -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1")


def assert_client(data: dict) -> None:
    assert_common_fields(data, "Client")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["agency_code"], str) and 1 <= len(data["agency_code"]) <= 16
    assert isinstance(data["billing_email"], str) and data["billing_email"]


def assert_project(data: dict) -> None:
    assert_common_fields(data, "Project")
    assert is_valid_uuid(data["client_id"]), "Project.client_id must be a Client id"
    assert isinstance(data["title"], str) and data["title"]
    for field in ("budget_cents", "committed_cents", "available_cents", "spent_cents"):
        assert isinstance(data[field], int), f"Project.{field} must be integer cents"
    assert data["status"] in PROJECT_STATUSES, f"unexpected Project.status {data['status']}"
    assert data["budget_posture"] in BUDGET_POSTURES
    assert data["status_before_hold"] is None or data["status_before_hold"] in PROJECT_STATUSES
    assert_ledger_conserved(data)


def assert_creative_brief(data: dict) -> None:
    assert_common_fields(data, "CreativeBrief")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["tempo_bpm"], int) and 40 <= data["tempo_bpm"] <= 240
    assert isinstance(data["mood_tags"], list) and len(data["mood_tags"]) >= 1
    assert isinstance(data["target_markets"], list) and len(data["target_markets"]) >= 1
    assert isinstance(data["required_lengths"], list) and len(data["required_lengths"]) >= 1
    assert data["status"] in BRIEF_STATUSES


def assert_composer(data: dict) -> None:
    assert_common_fields(data, "Composer")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["pro_affiliation"] in ["ASCAP", "BMI", "SESAC", "NONE"]


def assert_demo(data: dict) -> None:
    assert_common_fields(data, "Demo")
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["composer_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["demo_fee_cents"], int) and data["demo_fee_cents"] > 0
    assert isinstance(data["submitted_length_seconds"], int) and data["submitted_length_seconds"] > 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["accrued_fee_cents"], int)
    assert data["status"] in DEMO_STATUSES


def assert_musician(data: dict) -> None:
    assert_common_fields(data, "Musician")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["instrument"], str) and data["instrument"]
    assert isinstance(data["scale_hourly_cents"], int) and data["scale_hourly_cents"] > 0
    assert data["afm_member_status"] in AFM_MEMBER_STATUSES


def assert_studio_room(data: dict) -> None:
    assert_common_fields(data, "StudioRoom")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["capacity_players"], int) and data["capacity_players"] > 0
    assert data["status"] in ["ACTIVE", "MAINTENANCE"]


def assert_session_call(data: dict) -> None:
    assert_common_fields(data, "SessionCall")
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["studio_room_id"])
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])
    assert parse_instant(data["scheduled_end_utc"]) > parse_instant(data["scheduled_start_utc"]), (
        "scheduled_end_utc must be strictly after scheduled_start_utc")
    for field in ("studio_cost_cents", "wage_estimate_cents", "committed_cents",
                  "wage_total_cents", "settled_total_cents", "wage_liability_cents"):
        assert isinstance(data[field], int), f"SessionCall.{field} must be integer cents"
    assert isinstance(data["scheduled_hours"], (int, float))
    assert isinstance(data["billed_hours"], (int, float))
    assert data["status"] in SESSION_CALL_STATUSES


def assert_musician_booking(data: dict) -> None:
    assert_common_fields(data, "MusicianBooking")
    assert is_valid_uuid(data["session_call_id"])
    assert is_valid_uuid(data["musician_id"])
    assert isinstance(data["is_leader"], bool)
    assert isinstance(data["doubles_count"], int) and 0 <= data["doubles_count"] <= 4
    assert isinstance(data["line_wage_cents"], int)
    assert isinstance(data["pension_health_cents"], int)
    assert data["status"] in BOOKING_STATUSES


def assert_license_deal(data: dict) -> None:
    assert_common_fields(data, "LicenseDeal")
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["demo_id"])
    assert data["license_structure"] in ["BUYOUT", "TERM"]
    if data["license_structure"] == "TERM":
        assert data["term_months"] in [12, 24, 36], (
            f"A TERM grant must carry term_months 12, 24 or 36; got {data.get('term_months')}")
    else:
        assert data.get("term_months") is None, (
            f"term_months is forbidden on a BUYOUT grant; got {data.get('term_months')}")
    assert isinstance(data["market_codes"], list) and len(data["market_codes"]) >= 1
    assert len(set(data["market_codes"])) == len(data["market_codes"]), (
        "market_codes must be duplicate-free")
    assert isinstance(data["creative_fee_cents"], int) and data["creative_fee_cents"] > 0
    for field in ("license_fee_quoted_cents", "license_fee_invoiced_cents",
                  "renewal_count", "renewal_fee_cents", "counter_round_count"):
        assert isinstance(data[field], int), f"LicenseDeal.{field} must be an integer"
    assert data["status"] in LICENSE_DEAL_STATUSES
    assert isinstance(data["drafted_by_user_id"], str) and data["drafted_by_user_id"]


def assert_reuse_extension(data: dict) -> None:
    assert_common_fields(data, "ReuseExtension")
    assert is_valid_uuid(data["license_deal_id"])
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert data["market_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["admin_pct"] in [5, 7, 10]
    for field in ("reuse_base_cents", "admin_fee_cents", "reuse_total_cents"):
        assert isinstance(data[field], int), f"ReuseExtension.{field} must be integer cents"
    assert data["reuse_total_cents"] == data["reuse_base_cents"] + data["admin_fee_cents"], (
        "reuse_total_cents must be reuse_base_cents plus admin_fee_cents")
    assert data["status"] == "ACTIVE"


def assert_deliverable(data: dict) -> None:
    assert_common_fields(data, "Deliverable")
    assert is_valid_uuid(data["license_deal_id"])
    assert data["master_status"] in MASTER_STATUSES
    assert data["cuesheet_status"] in CUESHEET_STATUSES
    assert isinstance(data["delivered_lengths"], list)
    assert isinstance(data["stem_manifest"], list)
    assert isinstance(data["unallocated_bps"], int) and 0 <= data["unallocated_bps"] <= CUE_TOTAL_BPS


def assert_cue_sheet_entry(data: dict) -> None:
    assert_common_fields(data, "CueSheetEntry")
    assert is_valid_uuid(data["deliverable_id"])
    assert is_valid_uuid(data["composer_id"])
    assert data["role"] in ["COMPOSER", "ARRANGER", "PUBLISHER"]
    assert isinstance(data["declared_weight"], int) and data["declared_weight"] >= 1
    assert isinstance(data["share_bps"], int) and 0 <= data["share_bps"] <= CUE_TOTAL_BPS
    assert data["status"] in CUE_ENTRY_STATUSES


def assert_library_track(data: dict) -> None:
    assert_common_fields(data, "LibraryTrack")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["blanket_fee_cents"], int) and data["blanket_fee_cents"] >= 0
    assert isinstance(data["per_market_fee_cents"], int) and data["per_market_fee_cents"] >= 0
    assert isinstance(data["max_markets"], int) and data["max_markets"] >= 1
    assert isinstance(data["min_length_seconds"], int) and data["min_length_seconds"] >= 1
    assert data["status"] in ["ACTIVE", "RETIRED"]


# --- Domain invariants -----------------------------------------------------

def assert_ledger_conserved(project: dict) -> None:
    """The three buckets must sum to exactly budget_cents after every request."""
    total = project["committed_cents"] + project["available_cents"] + project["spent_cents"]
    assert total == project["budget_cents"], (
        "committed_cents + available_cents + spent_cents must equal budget_cents; got "
        f"{project['committed_cents']} + {project['available_cents']} + "
        f"{project['spent_cents']} = {total} against budget {project['budget_cents']}")


def assert_ledger(project: dict, committed: int, available: int, spent: int) -> None:
    """Assert the three ledger buckets and the conservation law together."""
    assert project["committed_cents"] == committed, (
        f"Expected committed_cents {committed}, got {project['committed_cents']}")
    assert project["available_cents"] == available, (
        f"Expected available_cents {available}, got {project['available_cents']}")
    assert project["spent_cents"] == spent, (
        f"Expected spent_cents {spent}, got {project['spent_cents']}")
    assert_ledger_conserved(project)


def assert_cue_shares_conserved(deliverable: dict, entries) -> None:
    """Allocated share_bps plus unallocated_bps must equal exactly 10,000."""
    allocated = sum(e["share_bps"] for e in entries if e["status"] == "ALLOCATED")
    total = allocated + deliverable["unallocated_bps"]
    assert total == CUE_TOTAL_BPS, (
        "share_bps of all ALLOCATED lines plus unallocated_bps must equal 10000; got "
        f"{allocated} + {deliverable['unallocated_bps']} = {total}")
