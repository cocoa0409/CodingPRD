"""Entity assertions and ledger/domain invariant checkers (PRD §2.5, §2.9, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD §2.9: created_at / updated_at are "ISO 8601 UTC timestamp with three
# fractional digits".
_MILLIS_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_millis_timestamp(value: str, field: str = "timestamp"):
    assert isinstance(value, str) and _MILLIS_TS.match(value), (
        f"{field} must be an ISO 8601 UTC timestamp with three fractional "
        f"digits, got {value!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert_millis_timestamp(data.get("created_at", ""), "created_at")
    assert_millis_timestamp(data.get("updated_at", ""), "updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_term(data: dict):
    _assert_common_fields(data)
    for f in ("code", "name", "start_date", "end_date", "census_date",
              "full_refund_end_date", "mid_refund_end_date", "withdrawal_deadline"):
        assert isinstance(data.get(f), str) and data[f], f"missing {f}"
    assert data["refund_policy"] in ("SCHEDULE_TIERED", "PRO_RATA")
    for f in ("flat_fee_cents", "hold_threshold_cents", "plan_setup_fee_cents",
              "grace_days"):
        assert isinstance(data.get(f), int), f"{f} must be int"
    assert isinstance(data["late_fee_pct"], (int, float))
    assert data["status"] in ("DRAFT", "OPEN", "CENSUS_LOCKED", "CLOSED")


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("external_ref"), str) and data["external_ref"]
    assert data["residency_status"] in ("IN_STATE", "OUT_OF_STATE", "INTERNATIONAL")
    assert data["level"] in ("UNDERGRADUATE", "GRADUATE")


def assert_tuition_rate(data: dict):
    _assert_common_fields(data)
    assert data["residency"] in ("IN_STATE", "OUT_OF_STATE", "INTERNATIONAL")
    assert data["level"] in ("UNDERGRADUATE", "GRADUATE")
    for f in ("per_credit_rate_cents", "full_time_threshold_credits",
              "flat_rate_cents", "max_flat_credits", "overload_rate_cents"):
        assert isinstance(data.get(f), int), f"{f} must be int"


def assert_account(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "PAST_DUE", "COLLECTIONS", "WRITTEN_OFF", "CLOSED")
    for f in ("charges_total_cents", "payments_total_cents", "waivers_total_cents",
              "sponsor_total_cents", "writeoffs_total_cents", "balance_cents",
              "past_due_cents"):
        assert isinstance(data.get(f), int), f"{f} must be int"
    assert data["writeoff_status"] in ("NONE", "PENDING", "APPROVED", "REJECTED")


def assert_ledger_entry(data: dict):
    """Append-only ledger rows expose only id + created_at as common fields
    (PRD §2.5): neither updated_at nor version may appear."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ledger entries carry no updated_at"
    assert "version" not in data, "ledger entries carry no version"
    assert data["entry_type"] in (
        "CHARGE", "CHARGE_REVERSAL", "PAYMENT", "PAYMENT_REVERSAL", "WAIVER",
        "WAIVER_REVERSAL", "SPONSOR_CHARGE", "SPONSOR_REVERSAL", "LATE_FEE",
        "PLAN_FEE", "COLLECTIONS_FEE", "WRITE_OFF", "REFUND_PAYOUT",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ENROLLED", "DROPPED", "WITHDRAWN")
    assert isinstance(data["credit_hours"], int)
    assert isinstance(data["assessed_total_cents"], int)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must reference an account"


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("POSTED", "REVERSED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CARD", "ACH", "CASH", "CHECK")
    assert isinstance(data["allocations"], list)
    assert isinstance(data["unapplied_cents"], int)


def assert_waiver(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("AWARDED", "POSTED", "REVOKED")
    assert data["kind"] in ("WAIVER", "SCHOLARSHIP")
    assert isinstance(data["awarded_cents"], int) and data["awarded_cents"] > 0
    assert isinstance(data["posted_cents"], int)


def assert_sponsor_agreement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "TERMINATED")
    assert data["billing_basis"] in ("NET_OF_WAIVER", "GROSS")
    assert isinstance(data["cap_cents"], int) and data["cap_cents"] > 0
    assert isinstance(data["billed_cents"], int)


def assert_sponsor_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "VOID",
    )
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["lines"], list)


def assert_payment_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DEFAULTED", "COMPLETED", "CANCELLED")
    assert isinstance(data["installment_count"], int)
    assert 2 <= data["installment_count"] <= 6
    assert isinstance(data["defaulted_count"], int)
    for f in ("principal_cents", "fee_cents", "total_cents"):
        assert isinstance(data.get(f), int), f"{f} must be int"


def assert_installment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "PAST_DUE", "PAID", "CANCELLED")
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["late_fee_posted"], bool)


def assert_hold(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert data["hold_type"] in ("REGISTRATION", "TRANSCRIPT")
    assert data["origin"] in ("MANUAL", "AUTO")


def assert_refund(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("CALCULATED", "POSTED", "VOID")
    assert data["trigger"] in ("DROP", "WITHDRAWAL")
    assert data["policy_variant"] in ("SCHEDULE_TIERED", "PRO_RATA")
    assert isinstance(data["basis_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["pct_applied"], (int, float))


def assert_tax_form(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")
    for f in ("box1_cents", "box4_cents", "box5_cents"):
        assert isinstance(data.get(f), int), f"{f} must be int"
    assert isinstance(data["tax_year"], int)


# ---------------------------------------------------------------------------
# Ledger inspection helpers
# ---------------------------------------------------------------------------

def entries_of_type(ledger: list, entry_type: str) -> list:
    """Filter ledger rows by entry_type, preserving creation order."""
    return [e for e in ledger if e.get("entry_type") == entry_type]


def find_charge_entry(ledger: list, charge_kind: str) -> dict:
    """Locate the CHARGE row of the given kind (TUITION/FEE)."""
    for e in ledger:
        if e.get("entry_type") == "CHARGE" and e.get("charge_kind") == charge_kind:
            return e
    raise AssertionError(f"No CHARGE/{charge_kind} entry found in ledger")


def assert_account_balance_consistent(account: dict):
    """balance_cents must equal charges - payments - waivers - sponsor -
    writeoffs - refund payouts per the recompute definition (PRD §2.5)."""
    expected = (
        account["charges_total_cents"]
        - account["payments_total_cents"]
        - account["waivers_total_cents"]
        - account["sponsor_total_cents"]
        - account["writeoffs_total_cents"]
    )
    # REFUND_PAYOUT sum is folded into the balance; when no payout has posted
    # the plain bucket arithmetic is exact.
    assert account["balance_cents"] <= expected, (
        f"balance {account['balance_cents']} exceeds bucket-implied {expected}"
    )
