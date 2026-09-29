"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant, same_instant


# --------------------------------------------------------------------------
# Common-field helpers
# --------------------------------------------------------------------------
def assert_identity_fields(data: Dict[str, Any]) -> None:
    """Every resource carries a bare UUID ``id`` and an ISO-8601 ``created_at``."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO-8601, got {data.get('created_at')!r}"


def assert_versioned_entity(data: Dict[str, Any]) -> None:
    """Resources that carry a version also carry ``updated_at``."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO-8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_log_entity(data: Dict[str, Any]) -> None:
    """Resources carrying only ``id`` and ``created_at`` expose no version fields."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "this resource must not carry updated_at"
    assert "version" not in data, "this resource must not carry version"


def assert_same_instant(actual: Any, expected: Any, label: str = "instant") -> None:
    assert same_instant(actual, expected), (
        f"Expected {label} {expected!r}, got {actual!r} "
        f"(canonical {canonical_instant(actual)!r})"
    )


def assert_pct_precision(value: Any, label: str = "percentage") -> None:
    """Percentages are fractions of 1 rounded to two decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert 0.0 <= float(value) <= 1.0, f"{label} must be a fraction of 1, got {value}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value}"
    )


def assert_cents(value: Any, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value >= 0, f"{label} must be non-negative, got {value}"


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    meta = body["meta"]
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO-8601, got {meta['api_request_timestamp']!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_induction_cycle(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["sport_code"], str) and data["sport_code"]
    assert isinstance(data["max_inductees"], int) and data["max_inductees"] >= 1
    assert data["status"] in [
        "SETUP",
        "NOMINATIONS_OPEN",
        "SCREENING",
        "BALLOTING",
        "CERTIFIED",
        "CEREMONY_PLANNED",
        "CLOSED",
    ], f"unexpected cycle status {data['status']!r}"
    assert data["austerity_tier"] in ["FULL", "REDUCED", "MINIMAL"]
    for counter in (
        "current_round",
        "nomination_count",
        "advanced_candidacy_count",
        "special_election_used",
        "credentialed_roster_count",
        "induction_count",
        "ceremony_ready_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert_cents(data["travel_budget_cents"], "travel_budget_cents")
    assert_cents(data["travel_committed_cents"], "travel_committed_cents")


def assert_eligibility_rule(data: Dict[str, Any]) -> None:
    assert_log_entity(data)
    assert data["category"] in ["PLAYER", "COACH", "CONTRIBUTOR"]
    assert data["pathway"] in ["MODERN", "VETERANS", "POSTHUMOUS", "SPECIAL"]
    assert isinstance(data["waiting_period_years"], int)
    assert isinstance(data["min_career_seasons"], int)
    assert isinstance(data["max_ballot_appearances"], int)
    for pct in ("election_threshold_pct", "carryover_min_pct", "runoff_floor_pct"):
        assert_pct_precision(data[pct], pct)


def assert_voter_bloc(data: Dict[str, Any]) -> None:
    assert_log_entity(data)
    assert isinstance(data["bloc_code"], str) and data["bloc_code"]
    assert isinstance(data["seat_cap"], int) and data["seat_cap"] >= 1
    assert isinstance(data["seats_filled"], int) and data["seats_filled"] >= 0
    assert data["seats_filled"] <= data["seat_cap"], (
        f"seats_filled {data['seats_filled']} exceeds seat_cap {data['seat_cap']}"
    )
    assert_pct_precision(data["min_participation_pct"], "min_participation_pct")


def assert_candidate(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["category"] in ["PLAYER", "COACH", "CONTRIBUTOR"]
    assert data["hof_status"] in ["NOT_INDUCTED", "INDUCTED", "PERMANENTLY_INELIGIBLE"]
    assert isinstance(data["retirement_year"], int)
    assert isinstance(data["career_seasons"], int)
    assert isinstance(data["is_deceased"], bool)
    assert isinstance(data["ballot_appearances_used"], int)
    assert data["ballot_appearances_used"] >= 0


def assert_candidacy(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["nominated_by_elector_id"])
    assert data["pathway"] in ["MODERN", "VETERANS", "POSTHUMOUS", "SPECIAL"]
    assert data["status"] in [
        "SUBMITTED",
        "SCREENING",
        "INFO_REQUESTED",
        "ADVANCED",
        "REJECTED",
        "DEFERRED",
        "ON_BALLOT",
        "ELECTED",
        "CARRYOVER_ELIGIBLE",
        "EXPIRED",
        "ELIMINATED",
        "STRUCK",
    ], f"unexpected candidacy status {data['status']!r}"
    assert isinstance(data["eligible_from_year"], int)
    assert isinstance(data["info_request_count"], int)
    assert isinstance(data["latest_round_votes"], int)


def assert_elector(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data["bloc_id"])
    assert isinstance(data["is_screening_member"], bool)
    assert data["status"] in ["PROVISIONAL", "CREDENTIALED", "SUSPENDED", "LAPSED"]
    assert isinstance(data["consecutive_missed_cycles"], int)
    assert data["consecutive_missed_cycles"] >= 0


def assert_ballot(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["cycle_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["voting_status"] in ["DRAFT", "OPEN", "CLOSED", "EXPIRED"]
    assert data["tally_status"] in [
        "NOT_TALLIED",
        "PENDING_AUDIT",
        "AUDIT_REJECTED",
        "AUDIT_CERTIFIED",
    ]
    assert data["outcome"] in [
        None,
        "ELECTION_COMPLETE",
        "RUNOFF_REQUIRED",
        "NO_ELECTION",
    ]
    for counter in (
        "max_votes_per_elector",
        "slot_count",
        "ballots_cast",
        "total_selections_counted",
        "credentialed_roster_at_close",
        "threshold_votes_provisional",
        "threshold_votes_final",
        "elected_slot_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )


def assert_ballot_slot(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["ballot_id"])
    assert is_valid_uuid(data["candidacy_id"])
    assert isinstance(data["candidate_name_snapshot"], str)
    assert data["pathway_snapshot"] in ["MODERN", "VETERANS", "POSTHUMOUS", "SPECIAL"]
    assert isinstance(data["candidacy_version_pinned"], int)
    assert data["status"] in [
        "LISTED",
        "ELECTED",
        "NOT_ELECTED",
        "CARRIED_TO_RUNOFF",
        "STRUCK",
    ]
    assert isinstance(data["votes_received"], int) and data["votes_received"] >= 0
    assert_pct_precision(data["vote_pct"], "vote_pct")


def assert_vote_submission(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["ballot_id"])
    assert is_valid_uuid(data["elector_id"])
    assert data["status"] in ["COUNTED", "WITHDRAWN", "INVALIDATED"]
    assert isinstance(data["selection_count"], int) and data["selection_count"] >= 0
    assert isinstance(data["is_abstention"], bool)
    assert isinstance(data["ballot_version_after"], int)
    assert is_iso8601_timestamp(data["cast_at"])


def assert_induction(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["candidacy_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert data["status"] in ["ANNOUNCED", "ENSHRINED"]
    assert data["travel_status"] in ["PENDING", "REQUESTED", "APPROVED", "WAIVED"]
    assert data["artifact_status"] in ["AWAITED", "RECEIVED", "EXEMPT"]
    assert data["exhibit_status"] in ["NOT_PLANNED", "INSTALLED"]
    assert data["delegation_type"] in ["LIVING", "POSTHUMOUS_DELEGATION"]
    assert isinstance(data["ceremony_ready"], bool)
    assert isinstance(data["artifact_count"], int) and data["artifact_count"] >= 0


def assert_travel_grant(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["induction_id"])
    assert data["variant"] in ["LIVING_INDUCTEE", "POSTHUMOUS_DELEGATION"]
    assert data["austerity_tier_applied"] in ["FULL", "REDUCED", "MINIMAL"]
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED", "CANCELLED"]
    assert isinstance(data["nights"], int) and data["nights"] >= 0
    assert isinstance(data["traveler_count"], int) and data["traveler_count"] >= 1
    assert_cents(data["award_cents"], "award_cents")
    assert_cents(data["requested_airfare_cents"], "requested_airfare_cents")


def assert_exhibit_case(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["case_code"], str) and data["case_code"]
    assert isinstance(data["capacity_artifacts"], int) and data["capacity_artifacts"] >= 1
    assert isinstance(data["changeover_buffer_days"], int)
    assert isinstance(data["artifacts_installed"], int)
    assert 0 <= data["artifacts_installed"] <= data["capacity_artifacts"], (
        f"artifacts_installed {data['artifacts_installed']} exceeds capacity "
        f"{data['capacity_artifacts']}"
    )


def assert_exhibit_installation(data: Dict[str, Any]) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["induction_id"])
    assert is_valid_uuid(data["exhibit_case_id"])
    assert data["status"] in ["INSTALLED", "WITHDRAWN"]
    assert isinstance(data["artifact_count"], int) and data["artifact_count"] >= 1
    assert is_iso8601_timestamp(data["display_starts_on"])
    assert is_iso8601_timestamp(data["display_ends_on"])


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_ballot_secrecy(submission: Dict[str, Any], *, revealed: bool) -> None:
    """``selected_slot_ids`` is readable only by the auditor role."""
    if revealed:
        assert isinstance(submission.get("selected_slot_ids"), list), (
            "an auditor must be able to read selected_slot_ids"
        )
    else:
        assert submission.get("selected_slot_ids", None) is None, (
            "selected_slot_ids must be null for every role except IndependentAuditor, "
            f"got {submission.get('selected_slot_ids')!r}"
        )


def assert_version_bumped_by_one(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"] + 1, (
        f"version must increase by exactly 1, went {before['version']} -> {after['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version must not change, went {before['version']} -> {after['version']}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )


def assert_ordered_by_created_at_then_id(rows: list) -> None:
    keys = [(canonical_instant(r["created_at"]), r["id"]) for r in rows]
    assert keys == sorted(keys), f"rows must be ordered by created_at then id, got {keys}"
