"""Entity assertions and domain invariant checkers for the COBRA
Administration API. Uses the framework's generic validators internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PLAN_STATUSES = ["ACTIVE", "TERMINATED"]
_BENEFICIARY_STATUSES = [
    "ACTIVE_EMPLOYEE_COVERAGE", "COBRA_ELIGIBLE", "COBRA_ENROLLED", "COVERAGE_ENDED",
]
_EVENT_STATUSES = ["RECORDED", "NOTICE_SENT", "ELECTED", "LAPSED", "VOID"]
_NOTICE_STATUSES = ["OUTSTANDING", "ELECTED", "EXPIRED"]
_ENROLLMENT_STATUSES = ["PENDING_INITIAL_PREMIUM", "ACTIVE", "TERMINATED"]
_INVOICE_STATUSES = ["OPEN", "PAID", "VOID"]
_PAYMENT_STATUSES = ["POSTED", "REFUNDED"]
_SUBSIDY_STATUSES = ["ACTIVE", "REVOKED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["applicable_premium_cents"], int) and data["applicable_premium_cents"] > 0
    assert data["status"] in _PLAN_STATUSES, f"bad plan status {data['status']!r}"


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["relationship"] in ["EMPLOYEE", "SPOUSE", "DEPENDENT"]
    assert data["status"] in _BENEFICIARY_STATUSES, f"bad beneficiary status {data['status']!r}"


def assert_event(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert data["event_type"] in [
        "TERMINATION", "REDUCTION_OF_HOURS", "DIVORCE",
        "DEATH_OF_EMPLOYEE", "MEDICARE_ENTITLEMENT", "DEPENDENT_AGE_OUT",
    ]
    assert isinstance(data["max_coverage_months"], int)
    assert data["status"] in _EVENT_STATUSES, f"bad event status {data['status']!r}"


def assert_notice(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert data["status"] in _NOTICE_STATUSES, f"bad notice status {data['status']!r}"


def assert_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["notice_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["base_max_months"], int)
    assert isinstance(data["extension_months"], int)
    assert isinstance(data["disability_extension"], bool)
    assert data["status"] in _ENROLLMENT_STATUSES, f"bad enrollment status {data['status']!r}"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["monthly_premium_cents"], int)
    for f in ("amount_invoiced_cents", "amount_paid_cents", "amount_subsidized_cents",
              "amount_refunded_cents", "credit_balance_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert_ledger_conservation(data)


def assert_ledger_conservation(data: dict):
    """The conserved money identity (PRD §2.6): credit_balance_cents ==
    amount_paid_cents + amount_subsidized_cents - amount_invoiced_cents -
    amount_refunded_cents, and the balance must never fall below zero."""
    expected = (
        data["amount_paid_cents"]
        + data["amount_subsidized_cents"]
        - data["amount_invoiced_cents"]
        - data["amount_refunded_cents"]
    )
    assert data["credit_balance_cents"] == expected, (
        f"credit_balance_cents {data['credit_balance_cents']} != "
        f"paid+subsidized-invoiced-refunded {expected}"
    )
    assert data["credit_balance_cents"] >= 0, "credit_balance_cents must never be negative"


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["coverage_month"], str)
    assert isinstance(data["coverage_month_index"], int)
    assert isinstance(data["gross_premium_cents"], int)
    assert data["proration_mode"] in ["FULL_MONTH", "DAILY_PRORATED"]
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["subsidy_applied_cents"], int)
    assert isinstance(data["beneficiary_owed_cents"], int)
    assert data["beneficiary_owed_cents"] == data["amount_due_cents"] - data["subsidy_applied_cents"], (
        "beneficiary_owed_cents must equal amount_due_cents - subsidy_applied_cents"
    )
    assert data["status"] in _INVOICE_STATUSES, f"bad invoice status {data['status']!r}"


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["target_coverage_month"], str)
    assert isinstance(data["deemed_full_payment"], bool)
    assert data["status"] in _PAYMENT_STATUSES, f"bad payment status {data['status']!r}"


def assert_subsidy(data: dict):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["subsidy_pct"], (int, float))
    assert isinstance(data["start_month"], str)
    assert isinstance(data["end_month"], str)
    assert data["status"] in _SUBSIDY_STATUSES, f"bad subsidy status {data['status']!r}"


def assert_certificate(data: dict):
    """HIPAA certificate is immutable (PRD §2.4): carries id + created_at only,
    with no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "certificate id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["creditable_months"], int)
    assert data["issued_reason"] in [
        "RUN_TO_TERM", "NONPAYMENT", "OTHER_GROUP_COVERAGE",
        "MEDICARE_ENTITLEMENT", "PLAN_TERMINATED",
    ]


def date_equals(actual, expected_date: str) -> bool:
    """Compare a server date/datetime field against a YYYY-MM-DD calendar date.

    The PRD stamps dates as ISO 8601 instants; date-valued fields such as
    paid_through_date, actual_end_date, coverage_through, scheduled_end_date,
    and election_deadline carry a calendar date that may be serialized either
    as a bare 'YYYY-MM-DD' or as a full ISO timestamp on that day. This matches
    the calendar-day prefix so the assertion is robust to either serialization
    while still pinning the exact day (PRD §2.6 date precision)."""
    if actual is None:
        return False
    return str(actual).startswith(expected_date)


def assert_no_version_field(data: dict):
    """Assert an immutable record exposes neither version nor updated_at
    (PRD §2.4 — the HIPAA certificate exception)."""
    assert "version" not in data, "immutable certificate must not carry a version field"
    assert "updated_at" not in data, "immutable certificate must not carry an updated_at field"
