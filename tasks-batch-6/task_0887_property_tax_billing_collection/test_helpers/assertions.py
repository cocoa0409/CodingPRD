"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Assertions check only fields
the PRD promises on a resource (PRD 2.4 common fields plus each entity's own
fields). LedgerEntry is append-only (PRD 2.4): id + created_at only.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, append_only: bool = False):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if not append_only:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be a positive int"


def assert_tax_year(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["first_installment_due_date"], str)
    assert isinstance(data["second_installment_due_date"], str)


def assert_escrow_agent(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["servicer_code"], str) and data["servicer_code"]


def assert_parcel(data: dict):
    _assert_common(data)
    assert isinstance(data["parcel_number"], str) and data["parcel_number"]
    assert isinstance(data["owner_name"], str)
    assert isinstance(data["assessed_value_cents"], int) and data["assessed_value_cents"] >= 0
    assert data["property_class"] in ("RESIDENTIAL", "COMMERCIAL", "AGRICULTURAL", "INDUSTRIAL")
    assert isinstance(data["homestead"], bool)


def assert_tax_bill(data: dict):
    _assert_common(data)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["tax_year_id"], str)
    for f in ("gross_tax_cents", "exemption_credit_cents", "net_tax_cents",
              "abatement_credit_cents", "total_charged_cents", "total_paid_cents",
              "total_applied_cents", "balance_cents", "overpayment_cents",
              "delinquent_principal_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    assert data["collection_status"] in ("CURRENT", "PARTIALLY_PAID", "PAID", "DELINQUENT")
    assert data["sale_status"] in ("NONE", "IN_TAX_SALE", "REDEEMED", "SOLD")


def assert_installment(data: dict):
    _assert_common(data)
    assert data["sequence"] in (1, 2)
    for f in ("principal_due_cents", "penalty_cents", "interest_cents",
              "paid_cents", "balance_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    assert data["status"] in ("PENDING", "PARTIALLY_PAID", "PAID", "DELINQUENT")


def assert_relief_application(data: dict):
    _assert_common(data)
    assert data["relief_class"] in ("EXEMPTION", "ABATEMENT")
    assert data["relief_type"] in ("HOMESTEAD", "SENIOR", "HARDSHIP", "DISABLED_VETERAN")
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED")
    assert isinstance(data["info_request_count"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["bill_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["tender_type"] in ("CASH", "CHECK", "ACH", "CARD")
    assert data["source"] in ("COUNTER", "ESCROW", "ONLINE")
    assert data["status"] in ("POSTED", "REVERSED")
    assert isinstance(data["allocation"], list)


def assert_ledger_entry(data: dict):
    # Append-only: id + created_at only, no updated_at, no version (PRD 2.4).
    _assert_common(data, append_only=True)
    assert data["entry_type"] in ("CHARGE", "PENALTY", "INTEREST", "PAYMENT",
                                  "REVERSAL", "ABATEMENT", "REFUND")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["bill_id"], str)


def assert_refund(data: dict):
    _assert_common(data)
    assert isinstance(data["bill_id"], str)
    assert data["mode"] in ("GROSS_OVERPAYMENT", "NET_OF_DELINQUENCY")
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["bill_id"], str)
    assert data["status"] in ("REFERRED", "REDEEMED", "SOLD")


# ----- Domain invariant checkers (PRD 2.11) -----
def assert_ledger_balance_conservation(bill: dict, ledger_entries: list):
    """PRD 2.11: balance_cents == sum of every LedgerEntry.amount_cents."""
    total = sum(e["amount_cents"] for e in ledger_entries)
    assert bill["balance_cents"] == total, \
        f"balance_cents {bill['balance_cents']} != ledger sum {total}"


def assert_cash_conservation(bill: dict, approved_refund_total_cents: int):
    """PRD 2.11: total_applied_cents == total_paid_cents - sum(APPROVED refunds)."""
    expected = bill["total_paid_cents"] - approved_refund_total_cents
    assert bill["total_applied_cents"] == expected, \
        f"total_applied_cents {bill['total_applied_cents']} != {expected}"
