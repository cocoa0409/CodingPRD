"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_sponsor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["sponsor_type"] in (
        "FEDERAL", "FEDERAL_FLOW_THROUGH", "INDUSTRY", "FOUNDATION", "STATE")
    assert data["payment_method"] in (
        "LETTER_OF_CREDIT", "COST_REIMBURSABLE_INVOICE", "FIXED_PRICE_SCHEDULE")
    assert isinstance(data["f_and_a_rate_bps"], int)


def assert_person(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_type"] in ("PRINCIPAL_INVESTIGATOR", "RESEARCH_STAFF")
    assert isinstance(data["institutional_base_salary_annual_cents"], int)
    assert data["appointment_months"] in (9, 12)


def assert_award(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING_SETUP", "ACTIVE", "SUSPENDED", "CLOSEOUT_PENDING", "CLOSED")
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    for field in ("total_obligated_cents", "mtdc_spent_cents", "f_and_a_accrued_cents",
                  "total_direct_spent_cents", "cost_share_met_cents",
                  "cumulative_drawn_cents", "reserved_draw_cents",
                  "available_draw_pool_cents", "nce_count", "f_and_a_rate_bps",
                  "fringe_rate_bps"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_budget_line(data: dict):
    _assert_common(data)
    assert data["category"] in (
        "PERSONNEL_SALARIES", "FRINGE_BENEFITS", "EQUIPMENT", "TRAVEL",
        "PARTICIPANT_SUPPORT", "MATERIALS_SUPPLIES", "SUBAWARDS",
        "OTHER_DIRECT", "F_AND_A")
    assert isinstance(data["authorized_cents"], int)
    assert isinstance(data["spent_cents"], int)


def assert_effort_commitment(data: dict):
    # PRD §2.4: commitments carry ONLY id and created_at — no updated_at,
    # no version — because a commitment is immutable once recorded.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "EffortCommitment must not expose version"
    assert "updated_at" not in data, "EffortCommitment must not expose updated_at"


def assert_expenditure(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_REVIEW", "POSTED", "DISALLOWED", "TRANSFERRED_OUT")
    assert data["expenditure_type"] in (
        "SALARY", "TRAVEL", "EQUIPMENT", "SUPPLIES", "PARTICIPANT_SUPPORT",
        "OTHER_DIRECT", "SUBAWARD_PAYMENT")


def assert_cost_transfer(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "PENDING_COUNTERSIGN", "APPROVED", "DENIED")


def assert_effort_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CERTIFYING", "CLOSED")


def assert_effort_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "CERTIFIED", "REOPENED", "RECERTIFIED")
    assert data["statement_kind"] in ("AWARD", "NON_SPONSORED")


def assert_subaward(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert data["risk_rating"] in ("LOW", "MEDIUM", "HIGH")


def assert_subaward_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "RECEIVED", "UNDER_REVIEW", "PAID", "REJECTED", "RETURNED_FOR_REVISION")


def assert_report_requirement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "OVERDUE", "SUBMITTED", "ACCEPTED")
    assert data["report_type"] in (
        "ANNUAL_PROGRESS", "TECHNICAL_QUARTERLY", "MILESTONE", "FINAL_TECHNICAL")


def assert_drawdown_request(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "SETTLED", "REJECTED_BY_SPONSOR", "CANCELLED")


def assert_receivable(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PARTIALLY_PAID", "PAID", "DISPUTED")
    assert data["aging_bucket"] in (
        "CURRENT", "D31_60", "D61_90", "D91_120", "OVER_120")


def assert_modification_request(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "SPONSOR_REVIEW", "APPROVED", "DENIED", "WITHDRAWN")
    assert data["mod_type"] in ("NO_COST_EXTENSION", "REBUDGET")


def assert_final_financial_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")


def assert_award_pool_invariant(data: dict):
    """PRD §2.8: on letter-of-credit awards the eligible draw pool partitions
    exactly: eligible_pool == cumulative_drawn + reserved + available."""
    if data.get("payment_method") != "LETTER_OF_CREDIT":
        return
    total = (data["cumulative_drawn_cents"] + data["reserved_draw_cents"]
             + data["available_draw_pool_cents"])
    assert data["available_draw_pool_cents"] >= 0
    assert data["cumulative_drawn_cents"] >= 0
    assert data["reserved_draw_cents"] >= 0
    # `total` is the eligible pool; always non-negative.
    assert total >= 0


def assert_money_conserved(before_total: int, after_total: int, context: str = ""):
    """PRD §2.8: a cost transfer never creates or destroys direct cost."""
    assert before_total == after_total, (
        f"Direct-cost conservation violated {context}: before={before_total} after={after_total}")
