"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


_LOAN_SERVICING = ["CURRENT", "DELINQUENT_OCCUPANCY", "DELINQUENT_PROPERTY_CHARGE"]
_LOAN_DISPOSITION = ["ACTIVE", "DUE_AND_PAYABLE", "DEFERRED", "IN_RESOLUTION", "TERMINATED"]
_DRAW_TYPES = ["LUMP_SUM", "LINE_OF_CREDIT", "TENURE", "TERM"]
_DISB_STATUS = ["REQUESTED", "APPROVED", "DISBURSED", "REJECTED", "VOIDED"]
_DISB_KIND = ["INITIAL", "LINE_DRAW", "SCHEDULED"]
_LESA_STATUS = ["FUNDED", "EXHAUSTED"]
_LESA_MODE = ["FULLY_FUNDED", "PARTIALLY_FUNDED"]
_CHARGE_TYPE = ["PROPERTY_TAX", "HAZARD_INSURANCE"]
_PCP_STATUS = ["POSTED", "REVERSED"]
_CERT_STATUS = ["PENDING", "CERTIFIED", "DELINQUENT"]
_EVENT_TYPE = ["BORROWER_DEATH", "PERMANENT_VACANCY", "SALE_OF_PROPERTY", "TAX_INSURANCE_DEFAULT"]
_EVENT_STATUS = ["RECORDED", "ACKNOWLEDGED"]
_DEFERRAL_STATUS = ["ACTIVE", "TERMINATED"]
_RES_PATH = ["PAYOFF", "SHORT_SALE", "FORECLOSURE"]
_RES_STATUS = ["INITIATED", "SETTLED", "CANCELLED"]
_LEDGER_TYPE = ["ADVANCE", "INTEREST_ACCRUAL", "MIP_ACCRUAL", "LESA_DRAW", "REVERSAL"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version int >= 1"


def _assert_appendonly_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not carry a version field"
    assert "updated_at" not in data, "append-only entity must not carry an updated_at field"


def assert_lender(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["hud_lending_limit_cents"], int) and data["hud_lending_limit_cents"] > 0
    assert is_iso8601_timestamp(data["clock_utc"]), "clock_utc must be ISO 8601"


def assert_loan(data: dict):
    _assert_common(data)
    assert data["draw_type"] in _DRAW_TYPES, f"unexpected draw_type {data['draw_type']!r}"
    assert data["servicing_status"] in _LOAN_SERVICING
    assert data["disposition_status"] in _LOAN_DISPOSITION
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["principal_balance_cents"], int)
    assert isinstance(data["available_line_of_credit_cents"], int)
    assert isinstance(data["months_elapsed"], int)


def assert_disbursement(data: dict):
    _assert_common(data)
    assert data["status"] in _DISB_STATUS
    assert data["kind"] in _DISB_KIND
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["approved_amount_cents"], int)


def assert_lesa(data: dict):
    _assert_common(data)
    assert data["status"] in _LESA_STATUS
    assert data["funding_mode"] in _LESA_MODE
    assert isinstance(data["initial_amount_cents"], int)
    assert isinstance(data["drawn_cents"], int)
    assert isinstance(data["remaining_cents"], int)


def assert_property_charge_payment(data: dict):
    _assert_common(data)
    assert data["status"] in _PCP_STATUS
    assert data["charge_type"] in _CHARGE_TYPE
    assert isinstance(data["amount_cents"], int)


def assert_occupancy_certification(data: dict):
    _assert_common(data)
    assert data["status"] in _CERT_STATUS
    assert isinstance(data["certification_year"], int)


def assert_maturity_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in _EVENT_TYPE
    assert data["status"] in _EVENT_STATUS


def assert_nbs_deferral(data: dict):
    _assert_common(data)
    assert data["status"] in _DEFERRAL_STATUS


def assert_resolution(data: dict):
    _assert_common(data)
    assert data["path"] in _RES_PATH
    assert data["status"] in _RES_STATUS
    assert isinstance(data["payoff_amount_cents"], int)
    assert isinstance(data["deficiency_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_appendonly_common(data)
    assert data["entry_type"] in _LEDGER_TYPE
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_principal_capacity_conserved(loan: dict, gross_limit_cents: int):
    """principal_balance_cents + available_line_of_credit_cents == gross limit
    for a LINE_OF_CREDIT loan with no LESA carve-out (PRD §3.5 conserved
    principal-capacity invariant)."""
    total = loan["principal_balance_cents"] + loan["available_line_of_credit_cents"]
    assert total == gross_limit_cents, (
        f"principal capacity drift: balance({loan['principal_balance_cents']}) + "
        f"line({loan['available_line_of_credit_cents']}) = {total}, expected {gross_limit_cents}"
    )


def assert_lesa_pool_conserved(lesa: dict):
    """drawn_cents + remaining_cents == initial_amount_cents (PRD §3.8)."""
    total = lesa["drawn_cents"] + lesa["remaining_cents"]
    assert total == lesa["initial_amount_cents"], (
        f"LESA pool drift: drawn({lesa['drawn_cents']}) + remaining({lesa['remaining_cents']}) "
        f"= {total}, expected initial_amount_cents {lesa['initial_amount_cents']}"
    )
