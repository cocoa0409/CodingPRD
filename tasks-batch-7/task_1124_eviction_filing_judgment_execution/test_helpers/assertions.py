"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(s):
    assert isinstance(s, str) and s, f"expected an ISO 8601 instant, got {s!r}"
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected: str):
    """Compare two ISO 8601 UTC instants semantically.

    The PRD pins instant VALUES (e.g. "The cure_deadline falls at 23:59:59Z
    on the calendar date that is statutory_cure_days days after served_on";
    "computes the appeal_deadline as entered_at plus the jurisdictional
    appeal window"). It mandates a three-fractional-digit rendering only for
    created_at/updated_at (§2.4) and the envelope timestamp (§2.2); for all
    other instants §2.6 requires only "ISO 8601 UTC timestamps", so both
    "...59Z" and "...59.000Z" renderings are faithful. Compare the instants,
    not the raw strings.
    """
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: {actual!r} denotes a different instant than {expected!r}"
    )

from .types import (
    AnswerStatus,
    BillingMode,
    CaseReason,
    CaseStatus,
    EntryType,
    FeeStatus,
    HearingStatus,
    JudgmentStatus,
    JurisdictionCode,
    NoticeStatus,
    NoticeType,
    PackageStatus,
    ReferralStatus,
    ReportType,
    ServiceMethod,
    ServiceResult,
    StorageStatus,
    TenancyStatus,
    UnitStatus,
    WritStatus,
)


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_version:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        # Immutable ledger records: updated_at / version must be ABSENT.
        assert "updated_at" not in data, "ledger record must not expose updated_at"
        assert "version" not in data, "ledger record must not expose version"


def assert_landlord(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_unit(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in UnitStatus]
    assert data["jurisdiction_code"] in [j.value for j in JurisdictionCode]
    assert isinstance(data["street_address"], str)
    assert isinstance(data["unit_label"], str)
    assert isinstance(data["landlord_id"], str)


def assert_tenancy(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in TenancyStatus]
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["tenant_full_name"], str) and data["tenant_full_name"]
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] > 0
    assert isinstance(data["lease_start_date"], str)


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in CaseStatus]
    assert data["case_reason"] in [r.value for r in CaseReason]
    assert isinstance(data["tenancy_id"], str)
    assert isinstance(data["landlord_id"], str)
    assert isinstance(data.get("case_number"), str) and data["case_number"].startswith("EV-")


def assert_notice(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in NoticeStatus]
    assert data["notice_type"] in [t.value for t in NoticeType]
    assert isinstance(data["case_id"], str)
    assert isinstance(data["served_on"], str)
    assert isinstance(data["statutory_cure_days"], int)
    assert is_iso8601_timestamp(data.get("cure_deadline", ""))


def assert_filing_package(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in PackageStatus]
    assert data["fee_status"] in [s.value for s in FeeStatus]
    assert isinstance(data["case_id"], str)
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert isinstance(data["defendant_names"], list) and len(data["defendant_names"]) >= 1
    assert isinstance(data["jury_demanded"], bool)
    assert isinstance(data["efiled"], bool)
    assert isinstance(data["filing_fee_cents"], int)
    assert isinstance(data["fee_paid_cents"], int)


def assert_service_attempt(data: dict):
    _assert_common(data, with_version=False)
    assert data["method"] in [m.value for m in ServiceMethod]
    assert data["result"] in [r.value for r in ServiceResult]
    assert isinstance(data["case_id"], str)
    assert isinstance(data["defendant_name"], str)
    assert is_iso8601_timestamp(data.get("served_at", ""))
    assert isinstance(data["server_user_id"], str)
    assert isinstance(data["server_role"], str)


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in HearingStatus]
    assert isinstance(data["case_id"], str)
    assert isinstance(data["courtroom"], str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))


def assert_answer(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in AnswerStatus]
    assert isinstance(data["case_id"], str)
    assert isinstance(data["defense_codes"], list) and len(data["defense_codes"]) >= 1
    assert isinstance(data["mediation_requested"], bool)


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in ReferralStatus]
    assert isinstance(data["answer_id"], str)
    assert isinstance(data["mediator_id"], str)
    assert isinstance(data["session_date"], str)


def assert_judgment(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in JudgmentStatus]
    assert isinstance(data["case_id"], str)
    assert isinstance(data["possession_granted"], bool)
    for f in ("rent_awarded_cents", "damages_cents", "late_fee_cents", "court_costs_cents"):
        assert isinstance(data[f], int) and data[f] >= 0
    assert isinstance(data["interest_cents"], int)
    assert isinstance(data["total_awarded_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert is_iso8601_timestamp(data.get("entered_at", ""))
    assert is_iso8601_timestamp(data.get("appeal_deadline", ""))


def assert_writ(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in WritStatus]
    assert isinstance(data["judgment_id"], str)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["writ_fee_paid_cents"], int)


def assert_storage_record(data: dict):
    _assert_common(data)
    assert data["status"] in [s.value for s in StorageStatus]
    assert data["billing_mode"] in [m.value for m in BillingMode]
    assert isinstance(data["writ_id"], str)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["daily_fee_cents"], int)
    assert isinstance(data["accrued_charge_cents"], int)
    assert is_iso8601_timestamp(data.get("stored_at", ""))
    assert is_iso8601_timestamp(data.get("disposal_eligible_on", ""))


def assert_collection_entry(data: dict):
    _assert_common(data, with_version=False)
    assert data["entry_type"] in [t.value for t in EntryType]
    assert isinstance(data["judgment_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["allocation"], dict)
    assert isinstance(data["resulting_outstanding_cents"], int)
    assert isinstance(data["recorded_by"], str)


def assert_rental_history_report(data: dict):
    _assert_common(data)
    assert data["report_type"] in [t.value for t in ReportType]
    assert isinstance(data["tenancy_id"], str)
    assert isinstance(data["landlord_id"], str)
    assert isinstance(data["superseded"], bool)
    assert isinstance(data.get("bureau_reference"), str) and data[
        "bureau_reference"
    ].startswith("RHR-")
    assert is_iso8601_timestamp(data.get("event_at", ""))
