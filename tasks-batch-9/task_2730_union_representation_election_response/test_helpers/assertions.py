"""Entity assertions, timestamp helpers and domain invariant checkers."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import HOLIDAY_CALENDAR


# --------------------------------------------------------------------------
# Timestamp handling: instants are compared as instants, never as raw strings,
# so a server that renders a different number of fractional digits still
# satisfies an equality assertion about the instant it wrote.
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(actual: str, expected: str) -> bool:
    """True when both strings denote the same UTC instant, whatever their precision."""
    return parse_instant(actual) == parse_instant(expected)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant"):
    """Assert two ISO 8601 instants denote the same moment (precision-insensitive)."""
    assert actual is not None, f"{label} must be present, got None"
    assert instants_equal(actual, expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_instants_equal(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Assert two recorded instants match each other, precision-insensitively."""
    assert actual is not None and expected is not None, (
        f"{label}: both instants must be present, got {actual!r} and {expected!r}"
    )
    assert instants_equal(actual, expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_timestamp_millis(value: str, label: str = "timestamp"):
    """Assert an instant is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"
    assert value.endswith("Z"), f"{label} must be rendered in UTC with a Z suffix: {value!r}"
    assert "." in value, f"{label} must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional-second digits, got {value!r}"
    )


def plus_days(instant: str, days: int) -> str:
    """Exact day arithmetic on an instant, preserving the time of day."""
    return (parse_instant(instant) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_hours(instant: str, hours: int) -> str:
    """Exact hour arithmetic on an instant, with no calendar skipping."""
    return (parse_instant(instant) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_business_days(anchor_date: str, count: int) -> str:
    """Add business days to a YYYY-MM-DD anchor, never counting the anchor day.

    Monday-Friday count; the fixed holiday set does not. The result is the end of
    the resulting day, 23:59:59Z.
    """
    current = datetime.strptime(anchor_date[:10], "%Y-%m-%d").date()
    counted = 0
    while counted < count:
        current = current + timedelta(days=1)
        if current.weekday() < 5 and current.isoformat() not in HOLIDAY_CALENDAR:
            counted += 1
    return f"{current.isoformat()}T23:59:59Z"


# --------------------------------------------------------------------------
# Common row properties
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "row"):
    """Every persisted row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID with no prefix"
    assert "-" in str(data.get("id", "")), f"{label}.id must be a plain UUID"
    assert_timestamp_millis(data.get("created_at", ""), f"{label}.created_at")
    assert_timestamp_millis(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_version_is(data: dict, expected: int, label: str = "row"):
    assert data.get("version") == expected, (
        f"{label}.version expected {expected}, got {data.get('version')}"
    )


def assert_absent(data: dict, field: str, label: str = "row"):
    """A field the PRD says is absent must be missing or null."""
    assert data.get(field) is None, (
        f"{label}.{field} must be absent, got {data.get(field)!r}"
    )


def assert_two_decimals(value, label: str = "value"):
    assert value is not None, f"{label} must be present"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_petition(data: dict):
    assert_common_fields(data, "petition")
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert data["petition_type"] in ("RC", "RM", "RD")
    assert isinstance(data["union_name"], str)
    assert data["case_status"] in (
        "RECEIVED", "SCOPE_ANALYSIS", "SOI_VERIFIED", "ELECTION_SET", "VOTING_CLOSED",
        "TALLY_POSTED", "OBJECTIONS_PENDING", "RERUN_DIRECTED", "CERTIFIED", "DISMISSED",
    )
    assert data["case_posture"] in ("OPEN", "BLOCKED", "IMPOUNDED")
    assert data["showing_verdict"] in ("PENDING", "SUFFICIENT", "INSUFFICIENT")
    assert data["certification_outcome"] in (
        "NONE", "CERTIFICATION_OF_REPRESENTATIVE", "CERTIFICATION_OF_RESULTS",
    )
    for field in (
        "total_classified_headcount", "included_headcount", "excluded_headcount",
        "pending_headcount", "pending_objection_count", "blocking_charge_count",
    ):
        assert isinstance(data[field], int), f"petition.{field} must be an integer"
    assert isinstance(data["retraining_required"], bool)
    assert_headcount_conservation(data)


def assert_headcount_conservation(petition: dict):
    """included + excluded + pending must always equal total_classified_headcount."""
    total = petition["included_headcount"] + petition["excluded_headcount"] + petition["pending_headcount"]
    assert total == petition["total_classified_headcount"], (
        "headcount conservation broken: "
        f"{petition['included_headcount']} + {petition['excluded_headcount']} + "
        f"{petition['pending_headcount']} != {petition['total_classified_headcount']}"
    )


def assert_classification(data: dict):
    assert_common_fields(data, "classification")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["headcount"], int) and data["headcount"] >= 1
    assert isinstance(data["avg_hourly_wage_cents"], int) and data["avg_hourly_wage_cents"] >= 1
    assert data["employer_position"] in ("INCLUDE", "EXCLUDE")
    assert data["union_position"] in ("INCLUDE", "EXCLUDE")
    assert data["scope_ruling"] in ("PENDING", "INCLUDED", "EXCLUDED", "MOOT")
    for factor in (
        "supervision_overlap", "skills_overlap", "functional_integration",
        "interchange_rate", "work_conditions_overlap",
    ):
        assert 0 <= data[factor] <= 100, f"classification.{factor} must be 0-100"
    if data.get("coi_score") is not None:
        assert_two_decimals(data["coi_score"], "classification.coi_score")
        assert data["coi_recommendation"] in (
            "SHARED_COMMUNITY", "CONTESTED_COMMUNITY", "DISTINCT_COMMUNITY", "MANDATORY_EXCLUSION",
        )


def assert_election_agreement(data: dict):
    assert_common_fields(data, "election_agreement")
    assert data["agreement_type"] in ("STIPULATED", "CONSENT")
    assert data["proposed_voting_method"] in ("MANUAL", "MAIL", "MIXED")
    assert data["status"] in (
        "PROPOSED", "STIPULATED_APPROVED", "HEARING_REQUESTED", "DIRECTED", "VOID",
    )
    assert data["route"] in ("PENDING", "STIPULATED", "DIRECTED")


def assert_voter_list(data: dict):
    assert_common_fields(data, "voter_list")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "DEFICIENT", "REJECTED", "SUPERSEDED", "CANCELLED",
    )
    assert isinstance(data["total_entry_count"], int)
    assert isinstance(data["complete_entry_count"], int)
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["resubmission_count"], int)
    if data.get("completeness_pct") is not None:
        assert_two_decimals(data["completeness_pct"], "voter_list.completeness_pct")
    if data.get("list_grade") is not None:
        assert data["list_grade"] in (
            "COMPLIANT", "MINOR_DEFECT", "MATERIAL_DEFECT", "GROSSLY_DEFICIENT",
        )


def assert_voter_list_entry(data: dict):
    assert_common_fields(data, "voter_list_entry")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["on_leave_type"] in ("NONE", "SICK", "FMLA", "MILITARY", "PERMANENT_LAYOFF")
    assert data["eligibility_status"] in ("ELIGIBLE", "INELIGIBLE", "CHALLENGED")
    assert isinstance(data["missing_field_count"], int)
    assert 0 <= data["missing_field_count"] <= 5
    assert isinstance(data["is_statutory_content_complete"], bool)
    assert data["is_statutory_content_complete"] == (data["missing_field_count"] == 0), (
        "is_statutory_content_complete is true exactly when missing_field_count is 0"
    )
    if data["eligibility_status"] != "INELIGIBLE":
        assert data.get("ineligibility_reason") is None


def assert_supervisor(data: dict):
    assert_common_fields(data, "supervisor")
    assert data["training_status"] in ("UNTRAINED", "TRAINED")
    assert isinstance(data["span_of_control"], int) and data["span_of_control"] >= 0
    assert isinstance(data["has_hire_fire_authority"], bool)
    assert isinstance(data["training_attempt_count"], int)
    assert isinstance(data["violation_count"], int)


def assert_campaign_communication(data: dict):
    assert_common_fields(data, "campaign_communication")
    assert data["channel"] in (
        "EMAIL", "LETTER", "DIGITAL_POST", "SMALL_GROUP_MEETING", "CAPTIVE_AUDIENCE_MEETING",
    )
    assert data["audience_scope"] in ("UNIT_WIDE", "CLASSIFICATION", "INDIVIDUAL")
    assert data["status"] in (
        "DRAFT", "PENDING_LEGAL_REVIEW", "REVISION_REQUIRED", "APPROVED", "DELIVERED", "BLOCKED",
    )
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert isinstance(data["peerless_plywood_violation"], bool)
    assert isinstance(data["revision_round"], int)
    if data["status"] != "BLOCKED":
        assert data.get("blocked_reason") is None


def assert_election_round(data: dict):
    assert_common_fields(data, "election_round")
    assert data["status"] in (
        "SCHEDULED", "SUSPENDED", "POLLS_OPEN", "POLLS_CLOSED", "TALLY_POSTED",
        "TALLY_REVISED", "SET_ASIDE", "ROUND_CERTIFIED",
    )
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["ballots_impounded"], bool)
    for field in (
        "scheduled_session_count", "closed_session_count", "ballots_cast_total",
        "provisional_votes_for", "provisional_votes_against", "provisional_void_count",
        "challenged_open_count", "challenged_counted_for_count",
        "challenged_counted_against_count", "challenged_voided_count",
        "challenged_withdrawn_count",
    ):
        assert isinstance(data[field], int), f"election_round.{field} must be an integer"
    assert_ballot_conservation(data)


def assert_ballot_conservation(round_row: dict):
    """Every physical ballot in the box stays accounted for across the buckets."""
    accounted = (
        round_row["provisional_votes_for"] + round_row["challenged_counted_for_count"]
        + round_row["provisional_votes_against"] + round_row["challenged_counted_against_count"]
        + round_row["provisional_void_count"] + round_row["challenged_voided_count"]
        + round_row["challenged_withdrawn_count"] + round_row["challenged_open_count"]
    )
    assert accounted == round_row["ballots_cast_total"], (
        f"ballot conservation broken: buckets sum to {accounted} but "
        f"ballots_cast_total is {round_row['ballots_cast_total']}"
    )


def assert_poll_session(data: dict):
    assert_common_fields(data, "poll_session")
    assert data["status"] in ("SCHEDULED", "CANCELLED", "CLOSED")
    assert data["method"] in ("MANUAL", "MAIL")
    for field in (
        "votes_for_count", "votes_against_count", "void_count", "challenged_ballot_count",
        "employer_observer_count", "union_observer_count",
    ):
        assert isinstance(data[field], int), f"poll_session.{field} must be an integer"
    assert isinstance(data["observer_roster"], list)


def assert_challenged_ballot(data: dict):
    assert_common_fields(data, "challenged_ballot")
    assert data["challenger_party"] in ("EMPLOYER", "UNION", "BOARD")
    assert data["basis"] in ("SUPERVISOR", "NOT_ON_LIST", "OUTSIDE_UNIT", "IDENTITY", "LAID_OFF")
    assert data["resolution"] in ("OPEN", "COUNTED_FOR", "COUNTED_AGAINST", "VOIDED", "WITHDRAWN")
    assert isinstance(data["reopen_count"], int)
    if data["resolution"] == "OPEN":
        assert data.get("resolved_at") is None


def assert_objection(data: dict):
    assert_common_fields(data, "objection")
    assert data["status"] in ("FILED", "SUSTAINED", "OVERRULED")
    assert data["filed_by_party"] in ("EMPLOYER", "UNION")
    assert data["ground_code"] in (
        "PROHIBITED_SUPERVISOR_CONDUCT", "CAPTIVE_AUDIENCE_TIMING", "LIST_DEFICIENCY",
        "POLLING_IRREGULARITY", "THIRD_PARTY_CONDUCT",
    )
    assert isinstance(data["affects_results"], bool)
    assert isinstance(data["rerun_directed"], bool)
    assert isinstance(data["alleged_affected_voter_count"], int)


def assert_ulp_charge(data: dict):
    assert_common_fields(data, "ulp_charge")
    assert data["status"] in ("FILED", "MERIT_FOUND", "DISMISSED", "SETTLED")
    assert data["charging_party"] in ("UNION", "EMPLOYER", "INDIVIDUAL")
    assert data["charged_party"] in ("EMPLOYER", "UNION")
    assert data["section_code"] in ("8A1", "8A3", "8A5", "8B1A")
    assert isinstance(data["blocking_requested"], bool)


# --------------------------------------------------------------------------
# Envelope helpers
# --------------------------------------------------------------------------
def assert_success_envelope(response, expected_response_type: str = "object"):
    """Assert the documented success envelope, including response_type."""
    body = response.json()
    assert "meta" in body and "response_type" in body and "data" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']}"
    )
    assert_timestamp_millis(body["meta"]["api_request_timestamp"], "meta.api_request_timestamp")
    assert body["response_type"] == expected_response_type, (
        f"expected response_type {expected_response_type}, got {body['response_type']}"
    )
    return body


def assert_pagination_meta(response, limit: int, offset: int, total_count: int, has_more: bool):
    body = response.json()
    meta = body["meta"]
    assert meta["limit"] == limit, f"meta.limit expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more expected {has_more}, got {meta['has_more']}"
    )
    return body["data"]


def assert_no_pagination_meta(response):
    """Single-resource reads and action endpoints carry no pagination fields."""
    meta = response.json()["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta or meta[field] is None, (
            f"meta must not carry pagination field {field} on this response"
        )


def assert_ordered_by_created_at(rows):
    """List results are ordered by created_at ascending."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "list results must be ordered by created_at ascending"
