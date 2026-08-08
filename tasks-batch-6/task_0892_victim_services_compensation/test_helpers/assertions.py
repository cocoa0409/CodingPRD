"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §2.7)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_program(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    for f in ("total_budget_cents", "budget_committed_cents", "budget_disbursed_cents",
              "budget_recovered_cents", "budget_available_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    # §2.7 budget_available == total_budget - budget_committed
    assert data["budget_available_cents"] == data["total_budget_cents"] - data["budget_committed_cents"]


def assert_case(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "ELIGIBLE", "INELIGIBLE", "CLOSED")
    assert data["eligibility_status"] in ("UNDETERMINED", "ELIGIBLE", "INELIGIBLE")
    assert isinstance(data["victim_name"], str) and len(data["victim_name"]) > 0


def assert_claim(data: dict):
    _common(data)
    assert data["category"] in ("MEDICAL", "LOST_WAGE", "FUNERAL", "MENTAL_HEALTH")
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert data["net_claim_cents"] >= 0, "net_claim_cents floored at 0"


def assert_collateral_source(data: dict):
    _common(data)
    assert data["status"] in ("DECLARED", "CONFIRMED", "WAIVED")
    assert data["amount_cents"] >= 0


def assert_award(data: dict):
    _common(data)
    assert data["approval_status"] in ("CALCULATED", "APPROVED", "FINALIZED")
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "FULLY_PAID")
    assert data["net_award_cents"] >= 0
    assert data["amount_paid_cents"] >= 0


def assert_disbursement(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "PAID", "VOID", "CLAWED_BACK")
    assert data["amount_cents"] > 0


def assert_recovery(data: dict):
    _common(data)
    assert data["status"] in ("ORDERED", "COLLECTING", "SATISFIED", "WRITTEN_OFF")
    assert data["recovered_amount_cents"] >= 0


def assert_receipt(data: dict):
    _common(data)
    assert data["status"] in ("RECORDED", "VOID")
    assert data["amount_cents"] > 0


def assert_appeal(data: dict):
    _common(data)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "GRANTED", "DENIED")


def assert_notification(data: dict):
    # Append-only log: id + created_at only, no version / updated_at (§2.4).
    assert is_valid_uuid(data.get("id", "")), "notification id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["channel"] in ("VINE", "EMAIL", "LETTER")
    assert data["event_type"] in (
        "ELIGIBILITY_DECISION", "CLAIM_DECISION", "PAYMENT", "APPEAL_DECISION", "CASE_REOPENED"
    )
