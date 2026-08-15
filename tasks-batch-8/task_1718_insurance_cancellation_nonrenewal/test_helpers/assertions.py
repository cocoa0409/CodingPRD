"""Entity assertions and domain invariant checkers.

Each assert_* verifies the common-fields contract (PRD §2.5) plus the
status-enum membership and always-present fields the PRD guarantees on a
resource body. Fields the PRD only populates at later lifecycle stages
(e.g. return_premium_cents before effectiveness) are type-checked only
when present.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AppealStatus,
    CancellationCaseStatus,
    GroundCode,
    InterestType,
    LedgerEntryKind,
    NonrenewalCaseStatus,
    NonrenewalReason,
    NoticeStatus,
    PolicyStatus,
    ProfileStatus,
    RecipientKind,
    ReinstatementStatus,
    ReportStatus,
    ReturnMethod,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_state_filing_profile(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ProfileStatus]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["permissible_grounds"], list)
    assert isinstance(data["nonpayment_notice_days"], int)
    assert isinstance(data["other_grounds_notice_days"], int)
    assert isinstance(data["mortgagee_notice_days"], int)
    assert isinstance(data["nonrenewal_notice_days"], int)
    assert isinstance(data["short_rate_penalty_pct"], (int, float))
    assert isinstance(data["reinstatement_window_days"], int)
    assert isinstance(data["max_reinstatements"], int)
    assert isinstance(data["nonrenewal_content_codes"], list)


def assert_policyholder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["mailing_address"], str) and data["mailing_address"]
    assert isinstance(data["email"], str) and data["email"]


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in PolicyStatus]
    assert isinstance(data["policyholder_id"], str)
    assert isinstance(data["state_profile_id"], str)
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    assert isinstance(data["total_premium_cents"], int)
    assert data["cancellation_effective_date"] is None or isinstance(
        data["cancellation_effective_date"], str
    )
    assert isinstance(data["reinstatements_used"], int)
    assert isinstance(data["lapse_flag"], bool)


def assert_insured_interest(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert data["interest_type"] in [t.value for t in InterestType]
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    assert isinstance(data["mailing_address"], str)


def assert_cancellation_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in CancellationCaseStatus]
    assert isinstance(data["policy_id"], str)
    assert data["ground_code"] in [g.value for g in GroundCode]
    assert data["requested_by_role"] in ("Underwriter", "Policyholder")
    assert isinstance(data["requested_on_date"], str)
    # Computed at creation per PRD: return_method + earliest_effective_date.
    assert data["return_method"] in [m.value for m in ReturnMethod]
    assert isinstance(data["earliest_effective_date"], str)
    if data.get("scheduled_effective_date") is not None:
        assert isinstance(data["scheduled_effective_date"], str)
    if data.get("return_premium_cents") is not None:
        assert isinstance(data["return_premium_cents"], int)


def assert_nonrenewal_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in NonrenewalCaseStatus]
    assert isinstance(data["policy_id"], str)
    assert data["reason_code"] in [r.value for r in NonrenewalReason]
    assert isinstance(data["reason_text"], str)
    assert isinstance(data["content_codes_present"], list)
    # Computed at creation per PRD: notice_deadline_date.
    assert isinstance(data["notice_deadline_date"], str)


def assert_notice_record(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in NoticeStatus]
    assert data["recipient_kind"] in [k.value for k in RecipientKind]
    assert isinstance(data["mailed_on_date"], str)
    assert isinstance(data["tracking_code"], str)
    # Each notice serves exactly one case.
    cid = data.get("cancellation_case_id")
    nid = data.get("nonrenewal_case_id")
    assert (cid is None) != (nid is None), (
        "exactly one of cancellation_case_id / nonrenewal_case_id must be set"
    )


def assert_ledger_entry(data: dict):
    # Append-only: only id + created_at as common fields (no updated_at / version).
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert isinstance(data["policy_id"], str)
    assert data["entry_kind"] in [k.value for k in LedgerEntryKind]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["effective_date"], str)


def assert_reinstatement_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ReinstatementStatus]
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["cancellation_case_id"], str)
    assert isinstance(data["submitted_on_date"], str)
    # Computed at submission per PRD.
    assert isinstance(data["lapse_days"], int)
    assert isinstance(data["reinstatement_fee_cents"], int)


def assert_appeal_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in AppealStatus]
    assert isinstance(data["cancellation_case_id"], str)
    assert isinstance(data["policy_id"], str)
    assert data["filed_by"] in ("POLICYHOLDER", "MORTGAGEE")
    assert isinstance(data["filed_on_date"], str)
    assert isinstance(data["grounds_text"], str)


def assert_regulatory_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ReportStatus]
    assert isinstance(data["state_profile_id"], str)
    assert isinstance(data["report_period"], str) and len(data["report_period"]) == 7
    assert isinstance(data["nonrenewal_count"], int)
    assert isinstance(data["cancellation_count"], int)
    assert isinstance(data["rescinded_count"], int)


def assert_ledger_sum(entries: list, expected_cents: int):
    """Sum of amount_cents over a policy's ledger equals expected_cents."""
    total = sum(e["amount_cents"] for e in entries)
    assert total == expected_cents, (
        f"Ledger sum must be {expected_cents}, got {total} from "
        f"{[(e['entry_kind'], e['amount_cents']) for e in entries]}"
    )


def assert_no_return_entries(entries: list):
    """No RETURN_PRO_RATA / RETURN_SHORT_RATE lines exist."""
    kinds = {e["entry_kind"] for e in entries}
    assert LedgerEntryKind.RETURN_PRO_RATA.value not in kinds
    assert LedgerEntryKind.RETURN_SHORT_RATE.value not in kinds
