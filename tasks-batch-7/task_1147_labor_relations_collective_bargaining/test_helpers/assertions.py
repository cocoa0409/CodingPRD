"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_union(data: dict):
    _assert_common(data, "Union")
    assert isinstance(data.get("name"), str) and data["name"], "Union.name required"
    assert isinstance(data.get("union_code"), str) and data["union_code"], "Union.union_code required"
    assert data.get("status") in {"ACTIVE", "TRUSTEED", "DECERTIFIED"}
    assert isinstance(data.get("open_information_request_count"), int)
    assert data["open_information_request_count"] >= 0


def assert_agreement(data: dict):
    _assert_common(data, "CollectiveAgreement")
    assert data.get("status") in {"DRAFT", "ACTIVE", "EXPIRED", "EXTENDED", "REPLACED", "ARCHIVED"}
    assert data.get("posture") in {"NEGOTIATING", "OPEN", "SUNSET", "CRITICAL", "UNCOVERED", "CLOSED"}
    assert isinstance(data.get("envelope_committed_cents"), int)
    assert isinstance(data.get("extension_count"), int)
    assert data.get("deadline_mode") in {"BUSINESS", "CALENDAR"}


def assert_clause(data: dict):
    _assert_common(data, "Clause")
    assert data.get("interpretation_status") in {
        "UNINTERPRETED", "UNDER_REVIEW", "INTERPRETED", "DISPUTED", "RESOLVED",
    }
    assert isinstance(data.get("article_ref"), str) and data["article_ref"], "Clause.article_ref required"


def assert_session(data: dict):
    _assert_common(data, "BargainingSession")
    assert data.get("status") in {"SCHEDULED", "IN_SESSION", "COMPLETED", "CANCELLED", "NO_SHOW"}


def assert_proposal(data: dict):
    _assert_common(data, "Proposal")
    assert data.get("status") in {
        "DRAFT", "TENDERED", "ON_TABLE", "COUNTERED", "ACCEPTED",
        "REJECTED", "WITHDRAWN", "IMPLEMENTED", "VOID",
    }
    assert data.get("side") in {"EMPLOYER", "UNION"}
    assert data.get("proposal_type") in {"ECONOMIC", "NON_ECONOMIC"}
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1


def assert_costing_scenario(data: dict):
    _assert_common(data, "CostingScenario")
    assert data.get("status") in {"DRAFT", "COMPUTED", "REVIEWED", "LOCKED", "SUPERSEDED"}
    assert data.get("scenario_mode") in {"PROVISIONAL", "FINAL"}


def assert_ratification_vote(data: dict):
    _assert_common(data, "RatificationVote")
    assert data.get("status") in {"SCHEDULED", "OPEN", "RATIFIED", "REJECTED"}
    assert isinstance(data.get("eligible_voter_count"), int) and data["eligible_voter_count"] >= 1


def assert_side_letter(data: dict):
    _assert_common(data, "SideLetter")
    assert data.get("status") in {"DRAFT", "PENDING_LEGAL", "EXECUTED", "EXPIRED", "SUPERSEDED"}
    assert data.get("letter_type") in {"SIDE_LETTER", "MOA", "MOU"}


def assert_past_practice(data: dict):
    _assert_common(data, "PastPractice")
    assert data.get("status") in {
        "ASSERTED", "DOCUMENTED", "VERIFIED", "DISPUTED", "NOTICE_GIVEN", "ABANDONED",
    }
    assert isinstance(data.get("occurrence_count"), int) and data["occurrence_count"] >= 1


def assert_information_request(data: dict):
    _assert_common(data, "InformationRequest")
    assert data.get("status") in {
        "RECEIVED", "ACKNOWLEDGED", "IN_PROGRESS", "FULFILLED",
        "PARTIALLY_FULFILLED", "OBJECTED",
    }
    assert isinstance(data.get("is_overdue"), bool)
    assert isinstance(data.get("extension_count"), int)


def assert_expiration_task(data: dict):
    _assert_common(data, "ExpirationTask")
    assert data.get("status") in {"PENDING", "IN_PROGRESS", "DONE", "MISSED"}
    assert isinstance(data.get("completed_late"), bool)
