"""Entity assertions, instant comparison helpers, and conservation-invariant
checkers.

Instants are always compared **semantically**: both sides are parsed into an
aware ``datetime`` and the two instants are compared. Byte-for-byte comparison
of an instant string is reserved for the one place the PRD makes the rendering
itself the claim under test (see ``assert_instant_rendering``).
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CATEGORY_ORDER

# `YYYY-MM-DDTHH:MM:SS.mmmZ` - the rendering PRD §2.4 pins for every
# server-written instant.
_RENDERED_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# --- instants --------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant into an aware datetime.

    Accepts a trailing ``Z`` with or without fractional seconds, and a numeric
    UTC offset, so that a comparison never depends on how many fractional
    digits the server chose to emit.
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment.

    Both sides are parsed before comparison, so ``2026-06-01T09:00:00Z`` and
    ``2026-06-01T09:00:00.000Z`` are treated as equal.
    """
    assert actual is not None, f"{label} must not be null (expected {expected})"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"Expected {label} to be {expected}, got {actual}"


def assert_instant_offset(
    actual: str, base: str, hours: int = 0, label: str = "instant"
) -> None:
    """Assert an instant equals ``base`` advanced by a whole number of hours."""
    want = parse_instant(base) + timedelta(hours=hours)
    got = parse_instant(actual)
    assert got == want, (
        f"Expected {label} to be {base} plus {hours}h ({want.isoformat()}), got {actual}"
    )


def assert_instant_rendering(value: str, label: str = "instant") -> None:
    """Assert a server-written instant carries exactly three fractional digits
    and a trailing ``Z`` - the rendering PRD §2.4 states verbatim."""
    assert isinstance(value, str) and _RENDERED_INSTANT_RE.match(value), (
        f"Expected {label} rendered as YYYY-MM-DDTHH:MM:SS.mmmZ, got {value!r}"
    )


def assert_calendar_date(value: str, label: str = "date") -> None:
    assert isinstance(value, str) and _DATE_RE.match(value), (
        f"Expected {label} as a plain YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_calendar_month(value: str, label: str = "month") -> None:
    assert isinstance(value, str) and _MONTH_RE.match(value), (
        f"Expected {label} as a plain YYYY-MM calendar month, got {value!r}"
    )


# --- common shapes ---------------------------------------------------------


def assert_common_fields(data: Dict[str, Any], label: str) -> None:
    """id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_immutable_fields(data: Dict[str, Any], label: str) -> None:
    """id + created_at only - no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant, got {data.get('created_at')!r}"
    )
    assert "version" not in data, f"{label} is immutable and must carry no version field"
    assert "updated_at" not in data, (
        f"{label} is immutable and must carry no updated_at field"
    )


def _money(data: Dict[str, Any], field: str, label: str) -> int:
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label}.{field} must be an integer number of cents, got {value!r}"
    )
    return value


# --- per-entity assertions -------------------------------------------------


def assert_client(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Client")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_calendar_date(data["date_of_birth"], "Client.date_of_birth")
    assert isinstance(data["intake_reference"], str) and data["intake_reference"]
    assert data["status"] in ("INTAKE", "ACTIVE", "SUSPENDED", "CLOSED")
    assert data["capacity_determination"] in (
        "NOT_DETERMINED",
        "RETAINS_CAPACITY",
        "DIMINISHED_CAPACITY",
        "LACKS_CAPACITY",
    )
    for field in ("capacity_determined_on", "activated_on", "closed_on"):
        assert field in data, f"Client.{field} must be present"


def assert_authorization(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Authorization")
    assert is_valid_uuid(data["client_id"])
    assert data["scope_tier"] in ("LIMITED_BILLPAY", "FULL_AGENCY", "REP_PAYEE")
    assert isinstance(data["instrument_reference"], str) and data["instrument_reference"]
    assert_calendar_date(data["effective_date"], "Authorization.effective_date")
    assert_calendar_date(data["expiry_date"], "Authorization.expiry_date")
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "REVOKED", "SUPERSEDED")
    for field in (
        "cascaded_payments_cancelled",
        "cascaded_recipients_terminated",
        "cascaded_applications_withdrawn",
    ):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_client_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ClientAccount")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    assert isinstance(data["account_label"], str) and data["account_label"]
    assert data["account_type"] in ("CHECKING", "SAVINGS", "REP_PAYEE_TRUST")
    for field in (
        "opening_balance_cents",
        "cleared_balance_cents",
        "pending_holds_cents",
        "committed_disbursements_cents",
        "available_balance_cents",
    ):
        _money(data, field, "ClientAccount")
    assert data["fraud_posture"] in ("NORMAL", "WATCH", "FROZEN")
    assert_account_invariants(data)


def assert_account_invariants(data: Dict[str, Any]) -> None:
    """PRD §2.12 identity 1: available = cleared - holds - committed."""
    expected = (
        data["cleared_balance_cents"]
        - data["pending_holds_cents"]
        - data["committed_disbursements_cents"]
    )
    assert data["available_balance_cents"] == expected, (
        "available_balance_cents must equal cleared_balance_cents minus "
        f"pending_holds_cents minus committed_disbursements_cents; expected {expected}, "
        f"got {data['available_balance_cents']}"
    )
    assert data["pending_holds_cents"] >= 0, "pending_holds_cents is floored at zero"


def assert_payee(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Payee")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["payee_name"], str) and data["payee_name"]
    assert data["payee_type"] in ("RECURRING_BILLER", "ESSENTIAL", "DISCRETIONARY")
    assert isinstance(data["remittance_reference"], str)
    assert data["status"] in ("ACTIVE", "BLOCKED")
    assert isinstance(data["settled_payment_count"], int)
    assert data["settled_payment_count"] >= 0


def assert_budget_category(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "BudgetCategory")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["category_name"], str) and data["category_name"]
    assert_calendar_month(data["budget_month"], "BudgetCategory.budget_month")
    for field in (
        "allocation_cents",
        "override_granted_cents",
        "committed_cents",
        "settled_cents",
        "remaining_cents",
        "variance_full_cents",
        "variance_ptd_cents",
    ):
        _money(data, field, "BudgetCategory")
    assert isinstance(data["override_count"], int) and data["override_count"] >= 0
    assert data["variance_direction"] in ("UNDER", "EXACT", "OVER")
    assert_budget_invariants(data)


def assert_budget_invariants(data: Dict[str, Any]) -> None:
    """PRD §2.12 identity 3: committed + remaining == allocation + override."""
    left = data["committed_cents"] + data["remaining_cents"]
    right = data["allocation_cents"] + data["override_granted_cents"]
    assert left == right, (
        "committed_cents plus remaining_cents must equal allocation_cents plus "
        f"override_granted_cents; got {left} vs {right}"
    )
    assert data["remaining_cents"] >= 0, "remaining_cents never goes negative"
    expected_direction = (
        "UNDER"
        if data["variance_ptd_cents"] > 0
        else "EXACT"
        if data["variance_ptd_cents"] == 0
        else "OVER"
    )
    assert data["variance_direction"] == expected_direction, (
        "variance_direction is keyed to variance_ptd_cents; expected "
        f"{expected_direction} for {data['variance_ptd_cents']}, got {data['variance_direction']}"
    )


def assert_surety_bond(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "SuretyBond")
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["bond_number"], str) and data["bond_number"]
    for field in (
        "coverage_cents",
        "exposure_committed_cents",
        "exposure_settled_inclusive_cents",
        "headroom_committed_cents",
    ):
        _money(data, field, "SuretyBond")
    assert_calendar_date(data["effective_date"], "SuretyBond.effective_date")
    assert_calendar_date(data["expiry_date"], "SuretyBond.expiry_date")
    assert data["status"] in ("IN_FORCE", "SUPERSEDED")
    assert data["headroom_committed_cents"] == (
        data["coverage_cents"] - data["exposure_committed_cents"]
    ), "headroom_committed_cents must equal coverage_cents minus exposure_committed_cents"


def assert_payment(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Payment")
    for field in ("account_id", "payee_id", "authorization_id", "budget_category_id"):
        assert is_valid_uuid(data[field]), f"Payment.{field} must be a UUID"
    for field in ("amount_cents", "service_fee_cents", "total_charge_cents"):
        _money(data, field, "Payment")
    assert data["channel"] in ("CHECK", "ACH", "BILLER_DIRECT")
    assert data["approval_status"] in (
        "PENDING_SECOND_APPROVAL",
        "APPROVED",
        "REJECTED",
    ), (
        "no read of a payment ever returns PREPARED; got "
        f"{data['approval_status']!r}"
    )
    assert data["settlement_status"] in (
        "SCHEDULED",
        "IN_FLIGHT",
        "SETTLED",
        "RETURNED",
        "CANCELLED",
        "STOPPED",
    )
    assert data["total_charge_cents"] == data["amount_cents"] + data["service_fee_cents"], (
        "total_charge_cents must equal amount_cents plus service_fee_cents"
    )
    assert_calendar_date(
        data["projected_settlement_date"], "Payment.projected_settlement_date"
    )
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["duplicate_override"], bool)
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_dispute(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Dispute")
    assert is_valid_uuid(data["payment_id"])
    assert data["reason_code"] in (
        "UNAUTHORIZED",
        "WRONG_AMOUNT",
        "GOODS_NOT_RECEIVED",
        "SCAM_INDUCED",
    )
    _money(data, "disputed_amount_cents", "Dispute")
    _money(data, "provisional_credit_cents", "Dispute")
    assert_calendar_date(data["filed_on"], "Dispute.filed_on")
    assert isinstance(data["days_since_settlement"], int)
    assert data["status"] in ("FILED", "PROVISIONAL_CREDITED", "UPHELD", "DENIED")


def assert_reconciliation_period(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ReconciliationPeriod")
    assert is_valid_uuid(data["account_id"])
    assert_calendar_month(data["period_month"], "ReconciliationPeriod.period_month")
    assert data["status"] in ("OPEN", "IN_REVIEW", "CLOSED", "REOPENED", "LOCKED")
    for field in (
        "imported_line_count",
        "open_exception_count",
        "unreconciled_entry_count",
        "reopen_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["has_retro_adjustment"], bool)


def assert_statement_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "StatementLine")
    assert is_valid_uuid(data["period_id"])
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    _money(data, "amount_cents", "StatementLine")
    assert_calendar_date(data["line_date"], "StatementLine.line_date")
    assert data["match_status"] in (
        "UNMATCHED",
        "MATCHED",
        "EXCEPTION",
        "RESOLVED_MATCHED",
        "RESOLVED_WRITTEN_OFF",
    )


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    assert_immutable_fields(data, "LedgerEntry")
    assert is_valid_uuid(data["account_id"])
    assert data["entry_type"] in (
        "DEPOSIT",
        "DISBURSEMENT",
        "SERVICE_FEE",
        "STOP_PAYMENT_FEE",
        "RETURN_REVERSAL",
        "NSF_FEE",
        "DISPUTE_PROVISIONAL_CREDIT",
        "DISPUTE_CREDIT_REVERSAL",
        "BENEFIT_AWARD",
    )
    _money(data, "amount_cents", "LedgerEntry")
    assert_calendar_date(data["entry_date"], "LedgerEntry.entry_date")
    assert isinstance(data["frozen"], bool)


def assert_fraud_alert(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "FraudAlert")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["payment_id"])
    assert data["reason_code"] in (
        "UNRECOGNIZED_PAYEE",
        "AMOUNT_ANOMALY",
        "CHANNEL_ANOMALY",
        "THIRD_PARTY_REPORT",
    )
    assert isinstance(data["intake_risk_score"], int)
    assert 10 <= data["intake_risk_score"] <= 110
    assert data["intake_risk_band"] in ("LOW", "MEDIUM", "HIGH")
    assert is_iso8601_timestamp(data["ack_due_at"])
    assert data["status"] in (
        "NEW",
        "ESCALATED",
        "ACKNOWLEDGED",
        "CONFIRMED_FRAUD",
        "DISMISSED",
    )


def assert_benefit_application(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "BenefitApplication")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["authorization_id"])
    assert data["program"] in ("SSI", "MEDICAID", "SNAP", "LIHEAP")
    _money(data, "asserted_monthly_income_cents", "BenefitApplication")
    _money(data, "countable_resources_gross_cents", "BenefitApplication")
    _money(data, "countable_resources_net_cents", "BenefitApplication")
    assert isinstance(data["resource_items"], list)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "DENIED",
        "APPEALED",
        "WITHDRAWN",
    )
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0
    assert isinstance(data["retro_months"], int)
    assert isinstance(data["retro_award_cents"], int)


def assert_family_recipient(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "FamilyRecipient")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["authorization_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["relationship"] in (
        "CHILD",
        "SPOUSE",
        "SIBLING",
        "OTHER_RELATIVE",
        "TRUSTED_FRIEND",
    )
    assert isinstance(data["permitted_categories"], list)
    for category in data["permitted_categories"]:
        assert category in CATEGORY_ORDER
    assert data["subscription_status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["report_count"], int) and data["report_count"] >= 0


def assert_family_report(data: Dict[str, Any]) -> None:
    assert_immutable_fields(data, "FamilyReport")
    assert is_valid_uuid(data["recipient_id"])
    assert_calendar_month(data["report_month"], "FamilyReport.report_month")
    for field in ("requested_categories", "included_categories", "withheld_categories"):
        assert isinstance(data[field], list), f"FamilyReport.{field} must be an array"
    assert isinstance(data["is_provisional"], bool)
    _money(data, "total_disbursed_cents", "FamilyReport")
    _money(data, "closing_available_balance_cents", "FamilyReport")
    assert is_iso8601_timestamp(data["generated_at"])
    assert_disclosure_closure(data)


def assert_disclosure_closure(data: Dict[str, Any]) -> None:
    """PRD §2.12 identity 5: included and withheld partition requested."""
    requested = list(data["requested_categories"])
    included = list(data["included_categories"])
    withheld = list(data["withheld_categories"])
    assert set(included) & set(withheld) == set(), (
        "included_categories and withheld_categories must not intersect; got "
        f"{included} and {withheld}"
    )
    assert set(included) | set(withheld) == set(requested), (
        "included_categories and withheld_categories must together equal "
        f"requested_categories; got {included} + {withheld} vs {requested}"
    )
    for label, values in (
        ("requested_categories", requested),
        ("included_categories", included),
        ("withheld_categories", withheld),
    ):
        assert_category_order(values, label)


def assert_category_order(values: List[str], label: str) -> None:
    """Every category array is emitted in the fixed order of PRD §3.9."""
    expected = [c for c in CATEGORY_ORDER if c in values]
    assert values == expected, (
        f"{label} must be emitted in the fixed category order {CATEGORY_ORDER}; got {values}"
    )


def assert_coordination_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CoordinationRequest")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["subject"], str) and data["subject"]
    assert data["tier"] in ("URGENT", "ROUTINE", "INFORMATIONAL")
    assert isinstance(data["assigned_member_user_id"], str)
    assert is_iso8601_timestamp(data["ack_due_at"])
    assert isinstance(data["reroute_count"], int) and data["reroute_count"] >= 0
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "COMPLETED", "ESCALATED")


def assert_audit_entry(data: Dict[str, Any]) -> None:
    assert_immutable_fields(data, "AuditEntry")
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["operation"], str) and data["operation"]
    assert data["outcome"] in ("SUCCESS", "REJECTED")
    assert data["disclosure_category"] in tuple(CATEGORY_ORDER) + ("ADMINISTRATION",)
    assert is_iso8601_timestamp(data["recorded_at"])


# --- cross-entity invariant helpers ---------------------------------------


def assert_ledger_identity(account: Dict[str, Any], entries: List[Dict[str, Any]]) -> None:
    """PRD §2.12 identity 2: cleared - opening == the signed sum of entries."""
    signed_sum = sum(entry["amount_cents"] for entry in entries)
    delta = account["cleared_balance_cents"] - account["opening_balance_cents"]
    assert delta == signed_sum, (
        "cleared_balance_cents minus opening_balance_cents must equal the signed sum "
        f"of the account's ledger entries; got {delta} vs {signed_sum}"
    )


def expected_service_fee_cents(amount_cents: int) -> int:
    """The band table of PRD §3.3, selected from the pre-fee principal alone."""
    if amount_cents < 50000:
        return 250
    if amount_cents < 250000:
        return 500
    return 900


def entry_types(entries: List[Dict[str, Any]]) -> List[str]:
    return [entry["entry_type"] for entry in entries]


def find_entries(entries: List[Dict[str, Any]], entry_type: str) -> List[Dict[str, Any]]:
    return [entry for entry in entries if entry["entry_type"] == entry_type]


def assert_field_absent_or_null(
    data: Dict[str, Any], field: str, label: str = ""
) -> None:
    value = data.get(field)
    assert value is None, f"{label or field} must read null, got {value!r}"


def assert_optional_instant(value: Optional[str], label: str) -> None:
    if value is not None:
        assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 instant"
