"""Entity assertions and domain invariant checkers.

Each assert_* checks the common system fields (server-minted UUID id, ISO 8601
timestamps, integer version) plus status membership in the entity's declared
lifecycle vocabulary. Tests assert business fields directly; these helpers
guard envelope/shape correctness.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}: created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}: updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{label}: version must be an integer"


def assert_donor(data: dict):
    _assert_common(data, "Donor")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["vital_status"] in ("LIVING", "DECEASED")
    assert data["legacy_society_status"] in ("NONE", "ENROLLED", "RECOGNIZED", "REVOKED")
    assert isinstance(data["documented_gift_total_cents"], int)


def assert_rate_table(data: dict):
    _assert_common(data, "RateTable")
    assert isinstance(data["label"], str)
    assert isinstance(data["discount_rate_bps"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_illustration(data: dict):
    _assert_common(data, "Illustration")
    assert data["vehicle_type"] in ("CGA", "CRT_UNITRUST", "CRT_ANNUITY", "BEQUEST")
    assert isinstance(data["gift_amount_cents"], int)
    assert data["status"] in ("OPEN", "BOOKED", "SUPERSEDED")


def assert_gift_agreement(data: dict):
    _assert_common(data, "GiftAgreement")
    assert data["vehicle_type"] in ("CGA", "CRT_UNITRUST", "CRT_ANNUITY", "BEQUEST")
    assert isinstance(data["gift_amount_cents"], int)
    assert data["status"] in (
        "DRAFT", "EXECUTED", "FUNDED", "ACTIVE", "SUSPENDED",
        "MATURED", "SETTLED", "WITHDRAWN", "RESCINDED", "TERMINATED",
    )
    assert isinstance(data["received_value_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["total_scheduled_cents"], int)
    assert isinstance(data["liability_released_cents"], int)


def assert_beneficiary_designation(data: dict):
    _assert_common(data, "BeneficiaryDesignation")
    assert data["slot"] in ("PRIMARY_1", "PRIMARY_2", "CONTINGENT")
    assert isinstance(data["beneficiary_name"], str)
    assert isinstance(data["document_received"], bool)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "VERIFIED", "REJECTED", "SUPERSEDED", "REVOKED",
    )


def assert_gift_asset(data: dict):
    _assert_common(data, "GiftAsset")
    assert data["asset_kind"] in ("CASH", "SECURITIES", "REAL_ESTATE")
    assert isinstance(data["pledged_value_cents"], int)
    assert data["status"] in (
        "PLEDGED", "RECEIVED", "APPRAISED", "LIQUIDATED", "DISTRIBUTED", "RETURNED",
    )


def assert_annuity_payment(data: dict):
    _assert_common(data, "AnnuityPayment")
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("SCHEDULED", "DUE", "PAID", "DEFERRED", "LAPSED")


def assert_reserve_fund(data: dict):
    _assert_common(data, "ReserveFund")
    assert data["name"] == "CGA_RESERVE"
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["booked_target_cents"], int)
    assert isinstance(data["projected_target_cents"], int)
    assert data["booked_coverage_bps"] is None or isinstance(data["booked_coverage_bps"], int)
    assert data["posture"] in ("SOLVENT", "RESERVE_DEFICIENT")


def assert_estate(data: dict):
    _assert_common(data, "Estate")
    assert data["status"] in (
        "NOTIFIED", "PROBATE_OPEN", "CONTESTED",
        "DISTRIBUTION_PENDING", "DISTRIBUTED", "CLOSED",
    )
    assert isinstance(data["gross_proceeds_cents"], int)
    assert isinstance(data["alternate_valuation_elected"], bool)


def assert_probate_milestone(data: dict):
    _assert_common(data, "ProbateMilestone")
    assert data["kind"] in (
        "PETITION", "NOTICE_TO_CREDITORS", "INVENTORY",
        "APPRAISAL", "FINAL_ACCOUNTING", "COURT_ORDER",
    )
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in ("PENDING", "FILED", "OVERDUE", "CLOSED")


def assert_fund(data: dict):
    _assert_common(data, "Fund")
    assert isinstance(data["name"], str)
    assert data["restriction_type"] in (
        "UNRESTRICTED", "SCHOLARSHIP", "FACULTY_SUPPORT", "RESEARCH", "CAPITAL",
    )
    assert isinstance(data["minimum_endowment_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ("PROPOSED", "ENDOWED", "ACTIVE", "FROZEN", "CLOSED")


def assert_valuation_run(data: dict):
    _assert_common(data, "ValuationRun")
    assert is_iso8601_timestamp(data["coverage_start"])
    assert is_iso8601_timestamp(data["coverage_end"])
    assert is_iso8601_timestamp(data["valuation_date"])
    assert data["status"] in ("DRAFT", "POSTED")


def assert_obligation_conservation(agreement: dict, remaining_open_cents: int):
    """Obligation-mass invariant over an agreement's payment totals:
    paid + still-open + released == total scheduled."""
    total = agreement["total_scheduled_cents"]
    paid = agreement["total_paid_cents"]
    released = agreement["liability_released_cents"]
    assert paid + remaining_open_cents + released == total, (
        f"obligation mass not conserved: {paid} + {remaining_open_cents} + "
        f"{released} != {total}"
    )
