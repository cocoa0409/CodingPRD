"""Entity assertions and domain invariant checkers for the HELOC platform."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_heloc(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in [
        "APPLICATION", "DRAW", "REPAYMENT", "FROZEN", "DEFAULTED", "CLOSED",
    ]
    assert data["lien_position"] in ["FIRST", "SECOND"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert isinstance(data["current_apr_bps"], int)
    assert isinstance(data["version"], int)


def assert_heloc_credit_invariant(data: dict):
    """In DRAW, available_credit + current_balance == credit_limit (PRD §3.4):
    available credit is the credit limit minus the current balance, floored at 0."""
    assert data["current_balance_cents"] >= 0
    assert data["available_credit_cents"] >= 0
    if data["status"] == "DRAW":
        assert (
            data["current_balance_cents"] + data["available_credit_cents"]
            == data["credit_limit_cents"]
        ), (
            f"balance {data['current_balance_cents']} + available "
            f"{data['available_credit_cents']} != credit_limit {data['credit_limit_cents']}"
        )


def assert_borrower(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kyc_status"] in ["PENDING", "CLEARED", "REJECTED"]
    assert 300 <= data["credit_score"] <= 850


def assert_property(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_draw(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["BOOKED", "REVERSED"]
    assert isinstance(data["amount_cents"], int)


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["fee_applied_cents"], int)
    assert isinstance(data["interest_applied_cents"], int)
    assert isinstance(data["principal_applied_cents"], int)


def assert_payment_conserves_remittance(data: dict):
    """PRD §3.6: the three buckets always sum exactly to amount_cents."""
    total = (
        data["fee_applied_cents"]
        + data["interest_applied_cents"]
        + data["principal_applied_cents"]
    )
    assert total == data["amount_cents"], (
        f"fee+interest+principal {total} != amount_cents {data['amount_cents']}"
    )


def assert_covenant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["covenant_type"] in ["MAX_CLTV", "MIN_DSCR", "MAX_DELINQUENCY_DAYS"]
    assert data["status"] in ["SATISFIED", "BREACHED", "CURED"]


def assert_fee_assessment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["fee_type"] in ["ANNUAL", "EARLY_CLOSURE"]
    assert data["settlement_status"] in ["OUTSTANDING", "SETTLED", "WAIVED"]


def assert_lien_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["position"] in ["FIRST", "SECOND"]
    assert data["status"] in ["RECORDED", "RELEASED"]


def assert_default_event(data: dict):
    """DefaultEvent is an immutable audit record (PRD §2.4): only id + created_at,
    no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["trigger_type"] in ["MAX_CLTV", "MIN_DSCR", "MAX_DELINQUENCY_DAYS"]


def assert_index_rate(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["index_name"] == "PRIME"
    assert isinstance(data["superseded"], bool)
