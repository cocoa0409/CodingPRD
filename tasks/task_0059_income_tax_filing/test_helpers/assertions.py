"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_taxpayer(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["filing_status"] in (
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"
    )
    assert isinstance(data["prior_year_agi_cents"], int)
    assert isinstance(data["prior_year_total_tax_cents"], int)


def assert_tax_return(data: dict):
    _common(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["tax_year"], int)
    assert data["filing_status"] in (
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD"
    )
    assert data["status"] in (
        "DRAFT", "READY", "FILED", "REJECTED", "AMENDED", "SUPERSEDED"
    )
    assert data["deduction_method"] in ("STANDARD", "ITEMIZED")
    for f in (
        "total_income_cents", "agi_cents", "taxable_income_cents",
        "tax_before_credits_cents", "total_credits_cents", "tax_after_credits_cents",
        "total_payments_cents", "balance_due_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int, got {data.get(f)!r}"


def assert_income_document(data: dict):
    _common(data)
    assert isinstance(data["return_id"], str)
    assert data["doc_type"] in ("W2", "1099_NEC", "1099_INT", "1099_DIV", "1099_B")
    assert isinstance(data["box_amount_cents"], int)
    assert isinstance(data["federal_withholding_cents"], int)


def assert_schedule(data: dict):
    _common(data)
    assert isinstance(data["return_id"], str)
    assert data["schedule_type"] in ("A", "B", "C", "D", "E")
    assert isinstance(data["net_amount_cents"], int)


def assert_dependent(data: dict):
    _common(data)
    assert isinstance(data["return_id"], str)
    assert isinstance(data["age_years"], int)
    assert isinstance(data["is_student"], bool)
    assert isinstance(data["qualifies_ctc"], bool)


def assert_credit_claim(data: dict):
    _common(data)
    assert isinstance(data["return_id"], str)
    assert data["credit_type"] in ("EITC", "CTC", "AOTC")
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["refundable_cents"], int)


def assert_estimated_tax_payment(data: dict):
    _common(data)
    assert isinstance(data["return_id"], str)
    assert data["quarter"] in ("Q1", "Q2", "Q3", "Q4")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["on_time"], bool)


def assert_efiling_submission(data: dict):
    _common(data)
    assert isinstance(data["return_id"], str)
    assert data["status"] in ("TRANSMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["snapshot_balance_due_cents"], int)
    assert isinstance(data["superseded_by_amendment"], bool)


def assert_amended_return(data: dict):
    _common(data)
    assert isinstance(data["original_return_id"], str)
    assert isinstance(data["taxpayer_id"], str)
    assert data["status"] in ("DRAFT", "FILED")
    assert isinstance(data["corrected_balance_due_cents"], int)
    assert isinstance(data["delta_cents"], int)


def assert_balance_due_ledger_reconciles(original_balance_due: int, delta: int,
                                         corrected_balance_due: int):
    """PRD §3.7 conserved-quantity invariant: original frozen balance_due_cents plus
    the amendment's delta_cents equals the corrected_balance_due_cents, exactly."""
    assert original_balance_due + delta == corrected_balance_due, (
        f"balance-due ledger drift: {original_balance_due} + {delta} "
        f"!= {corrected_balance_due}"
    )
