"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments by one"


def assert_lessor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["home_state_code"], str)
    assert isinstance(data["sales_tax_rate_bps"], int)
    assert isinstance(data["property_tax_rate_bps"], int)
    assert isinstance(data["portfolio_value_cents"], int)
    assert data["portfolio_value_cents"] >= 0


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("PENDING", "APPROVED", "SUSPENDED")


def assert_credit_application(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_legal_name"], str)
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["credit_score"], int)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED_FOR_INFO", "APPROVED", "DECLINED",
    )


def assert_lessee(data: dict):
    _assert_common(data)
    assert isinstance(data["approved_credit_cents"], int)
    assert isinstance(data["committed_credit_cents"], int)
    assert isinstance(data["available_credit_cents"], int)


def assert_lease(data: dict):
    _assert_common(data)
    assert data["lease_type"] in ("FMV", "DOLLAR_OUT", "TRAC")
    assert isinstance(data["equipment_cost_cents"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["monthly_rate_factor_bps"], int)
    assert data["lifecycle_status"] in (
        "ORIGINATION", "BOOKED", "ACTIVE", "END_OF_TERM", "TERMINATED",
    )
    assert data["funding_status"] in ("PENDING_FUNDING", "FUNDED")


def assert_equipment_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str)
    assert isinstance(data["original_cost_cents"], int)
    assert data["status"] in ("ON_LEASE", "RETURNED", "LISTED", "SOLD", "DISPOSED")


def assert_schedule_line(data: dict):
    _assert_common(data)
    assert isinstance(data["installment_number"], int)
    assert isinstance(data["base_rent_cents"], int)
    assert isinstance(data["is_advance"], bool)
    assert data["status"] in ("SCHEDULED", "INVOICED", "PAID", "WAIVED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["base_rent_cents"], int)
    assert isinstance(data["sales_tax_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert data["status"] in ("OPEN", "PAID", "VOID")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("CLEARED", "REVERSED")


def assert_ucc_filing(data: dict):
    _assert_common(data)
    assert isinstance(data["jurisdiction_state_code"], str)
    assert data["status"] in ("PENDING", "FILED", "LAPSED", "TERMINATED")


def assert_tax_assessment(data: dict):
    _assert_common(data)
    assert data["tax_type"] in ("SALES_USE", "PROPERTY")
    assert isinstance(data["taxable_base_cents"], int)
    assert isinstance(data["tax_amount_cents"], int)
    assert data["status"] in ("ASSESSED", "REMITTED")


def assert_addon(data: dict):
    _assert_common(data)
    assert data["kind"] in ("ADD_ON", "UPGRADE")
    assert isinstance(data["added_cost_cents"], int)
    assert data["status"] in ("PROPOSED", "APPLIED", "REJECTED")


def assert_eot_election(data: dict):
    _assert_common(data)
    assert data["election"] in ("RENEW", "RETURN", "BUYOUT")
    assert data["status"] in ("ELECTED", "EXERCISED", "CANCELLED")


def assert_credit_envelope_conserved(lessee: dict):
    """Invariant (PRD §3.3): committed + available == approved credit."""
    assert (
        lessee["committed_credit_cents"] + lessee["available_credit_cents"]
        == lessee["approved_credit_cents"]
    ), (
        "credit envelope must conserve: "
        f"committed {lessee['committed_credit_cents']} + available "
        f"{lessee['available_credit_cents']} != approved "
        f"{lessee['approved_credit_cents']}"
    )
