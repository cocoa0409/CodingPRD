"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. StatementLine is append-only and must NOT
expose updated_at/version (PRD common-resource-properties section).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_artist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["primary_genre"], str) and data["primary_genre"]
    assert data["status"] in ("ACTIVE", "ON_HIATUS", "ARCHIVED")
    for field in ("unrecouped_advance_balance_cents", "lifetime_gross_cents",
                  "lifetime_commission_cents", "lifetime_disbursed_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "TERMINATED",
                              "EXPIRED", "SUNSET", "CLOSED")
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    assert data["touring_commission_base"] in ("GROSS", "NET_OF_EXPENSES")
    assert data["recoupment_policy"] in ("FIFO", "PRO_RATA")


def assert_rate_schedule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert data["income_type"] in ("TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT")
    assert 0 <= data["in_term_rate_bps"] <= 10000
    assert 0 <= data["sunset_rate_bps"] <= 10000
    assert data["sunset_months"] >= 0
    assert isinstance(data["effective_from_date"], str)


def assert_income_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["income_type"] in ("TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT")
    assert data["kind"] in ("ORIGINAL", "ADJUSTMENT")
    assert data["status"] in ("REPORTED", "VERIFIED", "SETTLED", "POSTED", "VOIDED")
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] > 0
    assert isinstance(data["recognition_date"], str)
    assert isinstance(data["source_name"], str)


def assert_advance(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["status"] in ("ACTIVE", "RECOUPED", "WRITTEN_OFF")
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["issued_date"], str)
    assert 1 <= data["recoup_pct_bps"] <= 10000
    assert isinstance(data["applies_to_income_types"], list)


def assert_advance_partition(data: dict):
    """The principal partition identity from the PRD advances section:
    principal equals recouped plus outstanding plus written-off."""
    assert data["principal_cents"] == (
        data["recouped_cents"] + data["outstanding_cents"] + data["written_off_cents"]
    ), (
        f"Advance partition broken: {data['principal_cents']} != "
        f"{data['recouped_cents']} + {data['outstanding_cents']} + {data['written_off_cents']}"
    )


def assert_expense(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["category"] in ("TRAVEL", "PRODUCTION", "MARKETING", "LEGAL", "OTHER")
    assert data["status"] in ("PENDING_APPROVAL", "APPROVED", "REJECTED", "REIMBURSED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_approval_request(data: dict):
    _assert_common_fields(data)
    assert data["target_type"] in ("EXPENSE", "OPPORTUNITY")
    assert data["required_approver"] in ("BUSINESS_MANAGER", "ARTIST", "FIRM_ADMIN")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "CANCELLED")


def assert_opportunity(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["income_type"] in ("TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT")
    assert data["status"] in ("RECEIVED", "UNDER_EVALUATION", "NEGOTIATING", "ACCEPTED",
                              "CONVERTED", "DECLINED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["proposed_value_cents"], int) and data["proposed_value_cents"] > 0
    assert isinstance(data["current_value_cents"], int)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 0
    assert isinstance(data["requires_artist_approval"], bool)
    assert 0 <= data["fit_score"] <= 100


def assert_engagement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["income_type"] in ("TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT")
    assert data["status"] in ("HOLD", "CONFIRMED", "COMPLETED", "SETTLED",
                              "CANCELLED", "RELEASED")
    assert isinstance(data["guarantee_cents"], int) and data["guarantee_cents"] >= 0
    assert isinstance(data["travel_buffer_hours"], int) and data["travel_buffer_hours"] >= 0


def assert_option(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert isinstance(data["agreement_id"], str)
    assert data["option_type"] in ("RECORDING_CYCLE", "ENDORSEMENT_RENEWAL",
                                   "TOUR_LEG", "MERCHANDISE")
    assert data["income_type"] in ("TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT")
    assert data["status"] in ("OPEN", "EXERCISED", "LAPSED", "WAIVED")
    assert isinstance(data["exercise_value_cents"], int) and data["exercise_value_cents"] > 0


def assert_team_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["member_role"] in ("AGENT", "BUSINESS_MANAGER", "PUBLICIST")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "ENDED")


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert data["basis"] in ("ACCRUAL", "CASH")
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "ACKNOWLEDGED",
                              "FINALIZED", "DISCARDED")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    for field in ("gross_total_cents", "commission_total_cents", "income_net_total_cents",
                  "expense_total_cents", "recoup_total_cents", "adjustment_total_cents",
                  "carry_in_cents", "net_payable_cents", "disbursed_cents",
                  "carry_out_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_statement_line(data: dict):
    # Append-only lines carry only id + created_at; updated_at and version absent.
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "statement lines must not expose updated_at"
    assert "version" not in data, "statement lines must not expose version"
    assert data["line_type"] in ("INCOME", "EXPENSE_REIMBURSEMENT",
                                 "ADVANCE_RECOUPMENT", "ADJUSTMENT")
    assert isinstance(data["statement_id"], str)
    assert isinstance(data["amount_cents"], int)


def assert_statement_conservation(data: dict):
    """The PRD statement invariant: disbursed + carry_out == net_payable after
    every generation, amendment, and disbursement."""
    assert data["disbursed_cents"] + data["carry_out_cents"] == data["net_payable_cents"], (
        f"Statement conservation broken: {data['disbursed_cents']} + "
        f"{data['carry_out_cents']} != {data['net_payable_cents']}"
    )


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert isinstance(data["statement_id"], str)
    assert data["reason"] in ("COMMISSION_RATE", "INCOME_MISSING",
                              "EXPENSE_UNAUTHORIZED", "RECOUPMENT_ERROR",
                              "SUNSET_MISCLASSIFIED", "OTHER")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED_UPHELD",
                              "RESOLVED_REJECTED", "WITHDRAWN", "ESCALATED")
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0


def assert_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["artist_id"], str)
    assert isinstance(data["scope_statement_id"], str)
    assert data["status"] in ("REQUESTED", "IN_PROGRESS", "FINDINGS_ISSUED", "CLOSED")
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
