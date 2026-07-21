"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_client_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["account_code"], str) and data["account_code"]
    assert isinstance(data["open_case_reserve_total_cents"], int)
    assert isinstance(data["gross_incurred_total_cents"], int)
    assert isinstance(data["recovered_total_cents"], int)


def assert_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXPIRED")
    assert isinstance(data["coverage_limit_cents"], int)
    assert isinstance(data["per_claim_expense_limit_cents"], int)


def assert_adjuster(data: dict):
    _assert_common(data)
    assert isinstance(data["authority_limit_cents"], int)
    assert isinstance(data["open_claim_count"], int)


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["vendor_type"] in (
        "INDEPENDENT_ADJUSTER", "APPRAISER", "CONTRACTOR", "DEFENSE_ATTORNEY")
    assert isinstance(data["credentialed_coverages"], list)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "INTAKE", "ASSIGNED", "INVESTIGATING", "EVALUATED", "CLOSED", "REOPENED", "CANCELLED")
    assert data["siu_status"] in ("NONE", "HELD", "CLEARED", "CONFIRMED")
    for f in ("indemnity_reserve_cents", "expense_reserve_cents", "paid_indemnity_cents",
              "paid_expense_cents", "recovered_cents", "recovered_indemnity_cents",
              "recovered_expense_cents", "gross_incurred_cents", "net_incurred_cents"):
        assert isinstance(data[f], int), f"{f} must be an int cents value"


def assert_claim_incurred_consistency(data: dict):
    """gross_incurred = paid buckets + case reserves; net = gross - recovered (PRD §2.7/§3.2)."""
    gross = (data["paid_indemnity_cents"] + data["paid_expense_cents"]
             + data["indemnity_reserve_cents"] + data["expense_reserve_cents"])
    assert data["gross_incurred_cents"] == gross, (
        f"gross_incurred_cents {data['gross_incurred_cents']} != {gross}")
    assert data["net_incurred_cents"] == gross - data["recovered_cents"], (
        "net_incurred_cents must equal gross_incurred_cents - recovered_cents")


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["assignee_type"] in ("ADJUSTER", "VENDOR")
    assert data["status"] in ("ACTIVE", "COMPLETED", "CANCELLED")


def assert_reserve_change(data: dict):
    # Append-only event: id + created_at only, NO updated_at / version.
    _assert_common(data)
    assert data["reserve_type"] in ("INDEMNITY", "EXPENSE")
    assert isinstance(data["resulting_indemnity_reserve_cents"], int)
    assert isinstance(data["resulting_expense_reserve_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_APPROVAL", "APPROVED", "REJECTED", "ISSUED", "VOID")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["requires_manager_approval"], bool)


def assert_vendor_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "PAID", "VOID")
    assert isinstance(data["amount_cents"], int)


def assert_litigation_case(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "IN_SUIT", "SETTLED", "DISMISSED", "JUDGMENT")


def assert_subrogation_case(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "DEMAND_SENT", "NEGOTIATING", "RECOVERED", "CLOSED_NO_RECOVERY")


def assert_siu_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLEARED", "CONFIRMED")


def assert_bordereau_report(data: dict):
    _assert_common(data)
    assert data["basis"] in ("PROVISIONAL", "DEVELOPED")
    assert isinstance(data["total_claim_count"], int)
    assert isinstance(data["total_incurred_dollars"], int)
    assert isinstance(data["total_paid_dollars"], int)
    assert isinstance(data["total_recovered_dollars"], int)
