"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_COMMITTEE_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"]
_SETTLEMENT_STATUSES = ["RECORDED", "DEPOSITED", "REFUNDED", "VOIDED"]
_REVIEW_STATUSES = ["UNREVIEWED", "FLAGGED", "CLEARED"]
_REPORT_STATUSES = ["DRAFT", "FILED", "UNDER_AUDIT", "SUPERSEDED"]
_PENALTY_STATUSES = ["NONE", "ASSESSED", "WAIVED"]


def assert_committee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "committee id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["committee_type"] in ["CANDIDATE", "PAC", "PARTY"]
    assert data["status"] in _COMMITTEE_STATUSES
    assert data["solvency_status"] in ["SOLVENT", "DEFICIT"]
    for f in ("total_receipts_cents", "total_disbursements_cents",
              "total_penalties_cents", "cash_on_hand_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert isinstance(data["version"], int)


def assert_committee_ledger(data: dict):
    """The pinned committee ledger derivation (§2.9) must hold on any committee snapshot."""
    coh = data["total_receipts_cents"] - data["total_disbursements_cents"] - data["total_penalties_cents"]
    assert data["cash_on_hand_cents"] == coh, (
        f"cash_on_hand_cents must equal receipts - disbursements - penalties; "
        f"got {data['cash_on_hand_cents']} expected {coh}"
    )
    expected_solvency = "DEFICIT" if coh < 0 else "SOLVENT"
    assert data["solvency_status"] == expected_solvency, (
        f"solvency_status must be {expected_solvency} for cash_on_hand {coh}"
    )


def assert_contribution(data: dict):
    assert is_valid_uuid(data.get("id", "")), "contribution id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["settlement_status"] in _SETTLEMENT_STATUSES
    assert data["review_status"] in _REVIEW_STATUSES
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["matchable_amount_cents"], int)


def assert_expenditure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "expenditure id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int)


def assert_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "report id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in _REPORT_STATUSES
    assert data["penalty_status"] in _PENALTY_STATUSES
    assert isinstance(data["amendment_seq"], int)
    assert isinstance(data["total_receipts_cents"], int)
    assert isinstance(data["penalty_amount_cents"], int)


def assert_registrant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "registrant id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["ACTIVE", "TERMINATED"]
    assert isinstance(data["total_committed_spend_cents"], int)
    assert isinstance(data["total_certified_spend_cents"], int)


def assert_client(data: dict):
    assert is_valid_uuid(data.get("id", "")), "client id must be a bare UUID"
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_activity(data: dict):
    assert is_valid_uuid(data.get("id", "")), "activity id must be a bare UUID"
    assert data["status"] in ["RECORDED", "VOIDED"]
    assert isinstance(data["amount_cents"], int)
