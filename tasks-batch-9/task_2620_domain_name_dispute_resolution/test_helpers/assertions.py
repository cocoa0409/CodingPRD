"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    NON_TERMINAL_CASE_STATUSES,
    TERMINAL_CASE_STATUSES,
)


def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """Most resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer beginning at 1"
    )


def assert_event_row_fields(data: dict, entity: str = "event row") -> None:
    """A panel ballot and a fee ledger line carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_registrar(data: dict) -> None:
    assert_common_fields(data, "Registrar")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["iana_id"], str) and 1 <= len(data["iana_id"]) <= 16
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert 1 <= data["verification_response_hours"] <= 336
    assert 1 <= data["lock_sla_hours"] <= 336
    assert isinstance(data["overdue_verification_count"], int)
    assert data["overdue_verification_count"] >= 0


def assert_domain(data: dict) -> None:
    assert_common_fields(data, "DomainName")
    assert data["domain_name"] == data["domain_name"].lower(), "domain_name is stored lowercased"
    assert 4 <= len(data["domain_name"]) <= 253
    assert is_valid_uuid(data["registrar_id"])
    assert data["lock_status"] in [
        "UNLOCKED", "LOCKED", "TRANSFER_EXECUTED", "CANCELLATION_EXECUTED",
    ]


def assert_complainant(data: dict) -> None:
    assert_common_fields(data, "Complainant")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert len(data["country_code"]) == 2 and data["country_code"].isupper()
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert isinstance(data["adverse_rdnh_findings"], int)


def assert_case(data: dict) -> None:
    assert_common_fields(data, "Case")
    assert data["status"] in NON_TERMINAL_CASE_STATUSES + TERMINAL_CASE_STATUSES
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert data["remedy_requested"] in ["TRANSFER", "CANCELLATION"]
    assert data["panel_election"] in ["SINGLE", "THREE"]
    assert data["respondent_panel_election"] in ["NONE", "THREE"]
    assert data["required_seat_count"] in [1, 3]
    assert data["fee_variant_applied"] in ["PROVISIONAL", "FINAL"]
    assert len(data["mutual_jurisdiction"]) == 2 and data["mutual_jurisdiction"].isupper()
    for money_field in (
        "assessed_fee_cents", "complainant_share_cents", "respondent_share_cents",
        "honoraria_pool_cents", "complainant_paid_cents", "respondent_paid_cents",
        "paid_cents",
    ):
        assert isinstance(data[money_field], int), f"{money_field} must be an integer number of cents"
    assert_case_money_invariants(data)


def assert_case_money_invariants(data: dict) -> None:
    """Share split and the ledger-derived totals must always reconcile."""
    assert (
        data["complainant_share_cents"] + data["respondent_share_cents"]
        == data["assessed_fee_cents"]
    ), "the complainant's share is the assessment less the respondent's share"
    assert data["paid_cents"] >= data["complainant_paid_cents"] + data["respondent_paid_cents"], (
        "paid_cents is always at least the sum of the two party subtotals"
    )


def assert_ground(data: dict) -> None:
    assert_common_fields(data, "ComplaintGround")
    assert data["ground_type"] in ["TRADEMARK_RIGHTS", "NO_LEGITIMATE_INTEREST", "BAD_FAITH"]
    assert 10 <= len(data["assertion_text"]) <= 4000
    assert 0 <= data["evidence_count"] <= 200
    assert data["sufficiency_status"] in ["SUFFICIENT", "DEFICIENT"]
    expected = "SUFFICIENT" if data["evidence_count"] >= 1 else "DEFICIENT"
    assert data["sufficiency_status"] == expected, (
        f"evidence_count {data['evidence_count']} must grade as {expected}"
    )
    assert isinstance(data["cited_decision_ids"], list)


def assert_deficiency_notice(data: dict) -> None:
    assert_common_fields(data, "DeficiencyNotice")
    assert data["status"] in ["OPEN", "CURED", "EXPIRED"]
    assert isinstance(data["deficiency_codes"], list) and 1 <= len(data["deficiency_codes"]) <= 7
    assert 1 <= data["correction_days"] <= 20
    assert data["round_number"] in [1, 2]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["correction_deadline_at"])


def assert_verification(data: dict) -> None:
    assert_common_fields(data, "RegistrarVerification")
    assert data["status"] in ["REQUESTED", "RESPONDED", "OVERDUE"]
    assert is_iso8601_timestamp(data["requested_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0


def assert_notification(data: dict) -> None:
    assert_common_fields(data, "RespondentNotification")
    assert data["channel"] in ["EMAIL", "POSTAL", "COURIER"]
    assert data["status"] in ["SENT", "DELIVERED", "UNDELIVERABLE"]
    assert 1 <= data["attempt_number"] <= 5
    assert data["transmission_allowance_days"] in [0, 2, 5]
    assert is_iso8601_timestamp(data["dispatched_at"])


def assert_response(data: dict) -> None:
    assert_common_fields(data, "Response")
    assert 10 <= len(data["content_summary"]) <= 4000
    assert data["timeliness"] in ["ON_TIME", "LATE"]
    assert isinstance(data["requests_three_member_panel"], bool)
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_panelist(data: dict) -> None:
    assert_common_fields(data, "Panelist")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert len(data["nationality_code"]) == 2 and data["nationality_code"].isupper()
    assert data["status"] in ["AVAILABLE", "UNAVAILABLE", "SUSPENDED"]
    assert 1 <= data["max_overlapping_engagements"] <= 20
    assert isinstance(data["active_case_load"], int) and data["active_case_load"] >= 0


def assert_appointment(data: dict) -> None:
    assert_common_fields(data, "PanelistAppointment")
    assert data["seat"] in ["SOLE", "PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2"]
    assert data["status"] in [
        "NOMINATED", "WAIVER_PENDING", "ACCEPTED", "CONFLICTED",
        "DECLINED", "REPLACED", "DISCHARGED",
    ]
    assert data["nominated_by"] in ["COMPLAINANT", "RESPONDENT", "PROVIDER"]
    assert isinstance(data["selected_by_provider"], bool)
    assert isinstance(data["honoraria_cents"], int)
    if data.get("conflict_score") is not None:
        assert 0.0 <= float(data["conflict_score"]) <= 100.00
        assert round(float(data["conflict_score"]), 2) == float(data["conflict_score"]), (
            "conflict_score carries two decimal places"
        )
    assert isinstance(data.get("conflict_factors", []), list)


def assert_conflict_factors_sorted(data: dict) -> None:
    factors = data.get("conflict_factors") or []
    assert factors == sorted(factors), "conflict_factors are sorted in ascending order"


def assert_decision(data: dict) -> None:
    assert_common_fields(data, "Decision")
    assert data["status"] in ["DRAFT", "ISSUED", "STAYED", "IMPLEMENTED", "VOIDED"]
    assert data["publication_status"] in ["UNPUBLISHED", "PUBLISHED", "REDACTED"]
    if data.get("outcome") is not None:
        assert data["outcome"] in ["TRANSFER", "CANCELLATION", "COMPLAINT_DENIED"]
    if data.get("outcome_basis") is not None:
        assert data["outcome_basis"] in ["STRICT_MAJORITY", "PRESIDING_CASTING"]
    assert isinstance(data["rdnh_finding"], bool)
    assert isinstance(data["dissent_present"], bool)
    for count in ("transfer_votes", "cancellation_votes", "deny_votes"):
        assert isinstance(data[count], int) and data[count] >= 0


def assert_vote(data: dict) -> None:
    assert_event_row_fields(data, "PanelVote")
    assert data["vote"] in ["TRANSFER", "CANCELLATION", "DENY"]
    assert data["seat"] in ["SOLE", "PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2"]
    assert isinstance(data["rdnh_vote"], bool)
    assert is_iso8601_timestamp(data["cast_at"])


def assert_fee_transaction(data: dict) -> None:
    assert_event_row_fields(data, "FeeTransaction")
    assert data["kind"] in ["FILING_FEE", "PANEL_SUPPLEMENT", "REFUND", "WRITE_OFF"]
    assert data["payer"] in ["COMPLAINANT", "RESPONDENT", "PROVIDER"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] != 0
    assert -10000000 <= data["amount_cents"] <= 10000000
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_court_challenge(data: dict) -> None:
    assert_common_fields(data, "CourtChallenge")
    assert data["status"] in ["FILED", "DISMISSED", "WITHDRAWN", "SUSTAINED"]
    assert data["filed_by"] in ["COMPLAINANT", "RESPONDENT"]
    assert len(data["jurisdiction"]) == 2
    assert is_iso8601_timestamp(data["filed_at"])


def assert_precedent_entry(data: dict) -> None:
    assert_common_fields(data, "PrecedentEntry")
    assert data["redaction_level"] in ["NONE", "PARTY_NAMES", "FULL"]
    assert isinstance(data["precedent_tags"], list) and 1 <= len(data["precedent_tags"]) <= 10
    assert isinstance(data["superseded"], bool)
    assert isinstance(data["citable"], bool)
    assert isinstance(data["citation_count"], int) and data["citation_count"] >= 0
    assert float(data["precedent_weight"]) >= 0.0
    expected_citable = data["redaction_level"] != "FULL" and data["superseded"] is False
    assert data["citable"] is expected_citable, (
        "an entry is citable when its redaction_level is not FULL and superseded is false"
    )


def assert_error_envelope_wrote_nothing(before: dict, after: dict, entity: str = "row") -> None:
    """A refusal writes nothing: the row's version and updated_at stand still."""
    assert after["version"] == before["version"], (
        f"{entity}.version moved from {before['version']} to {after['version']} on a refused request"
    )
    assert after["updated_at"] == before["updated_at"], (
        f"{entity}.updated_at was refreshed on a refused request"
    )


def assert_honoraria_waterfall(appointments: list, pool_cents: int) -> None:
    """Accepted seats' honoraria_cents must sum to the pool exactly."""
    accepted = [a for a in appointments if a["status"] == "ACCEPTED"]
    total = sum(a["honoraria_cents"] for a in accepted)
    assert total == pool_cents, (
        f"accepted seats' honoraria_cents sum to {total}, expected the pool {pool_cents}"
    )
