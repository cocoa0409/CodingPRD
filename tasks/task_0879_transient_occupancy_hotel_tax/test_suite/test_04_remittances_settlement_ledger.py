"""Remittance clearing/reversal, the independent settlement axis, ledger
conservation, the state-vs-fiscal priority conflict, and FK-reverse listings."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_remittance, assert_balance_equals_ledger,
    TEST_USERS, make_operator_headers,
    single_line, setup_operator_with_property,
    create_draft_return, create_and_file_return, amend_return,
    create_remittance, create_cleared_remittance, get_operator,
)

ADMIN = TEST_USERS["taxadmin_headers"]


# ============================================================
# Difficulty: non_linear_state_machine/return_parallel_filing_and_settlement_axes
# ============================================================
def _filed_partial_then_amended(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_and_file_return(api, op["id"], single_line(prop["id"], 1000000))  # tax 120000
    create_cleared_remittance(api, ret["id"], 50000)  # settlement PARTIAL
    amend_return(api, ret["id"], op["id"], single_line(prop["id"], 1000000))
    return op, validate_success(api.get_return(ret["id"], ADMIN), 200)


def test_amend_leaves_settlement_axis_untouched(api):
    """PRD 2.7: "A return also carries a settlement axis that is entirely independent
    of its filing axis and is driven only by cleared remittances (Section 3.6)."

    Design: Difficulty/non_linear_state_machine/return_parallel_filing_and_settlement_axes
    """
    _, ret = _filed_partial_then_amended(api)
    assert ret["filing_status"] == "AMENDED"
    assert ret["settlement_status"] == "PARTIAL"


def test_amend_preserves_amount_paid(api):
    """PRD 3.6: "Define `amount_paid_cents` as the sum of `amount_cents` over the
    return's `CLEARED` remittances. If that total is zero or below the return is
    `UNPAID`; if it is above zero but strictly less than `total_due_cents` the return
    is `PARTIAL`".

    Design: Difficulty/non_linear_state_machine/return_parallel_filing_and_settlement_axes
    """
    _, ret = _filed_partial_then_amended(api)
    assert ret["amount_paid_cents"] == 50000
    assert ret["settlement_status"] == "PARTIAL"


# ============================================================
# Difficulty: compensating_invariant/ledger_conservation_on_remittance_reverse
# ============================================================
def _filed_paid_then_reversed(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_and_file_return(api, op["id"], single_line(prop["id"], 1000000))  # tax 120000
    rem = create_cleared_remittance(api, ret["id"], 120000)  # balance 0, PAID
    reversed_rem = validate_success(api.reverse_remittance(rem["id"], ADMIN), 200)
    return op, ret, reversed_rem


def test_reverse_restores_balance_no_drift(api):
    """PRD 3.6: "Reversal posts a compensating `REMITTANCE_REVERSAL` ledger entry for
    the positive amount, restoring the balance so it still equals the ledger sum, and
    recomputes settlement".

    Design: Difficulty/compensating_invariant/ledger_conservation_on_remittance_reverse
    """
    op, ret, reversed_rem = _filed_paid_then_reversed(api)
    assert_remittance(reversed_rem)
    assert reversed_rem["status"] == "REVERSED"
    after_op = get_operator(api, op["id"])
    assert after_op["account_balance_cents"] == 120000


def test_reverse_conserves_ledger_and_drops_settlement(api):
    """PRD 2.6: "An operator's `account_balance_cents` is a computed field defined as
    the exact sum of `amount_signed_cents` over all ledger entries for that operator,
    with no status filter and no exclusions — the ledger is the single source of
    truth and the balance never drifts from it."
    PRD 3.6: "recomputes settlement — which can drop a return from `PAID` back to
    `PARTIAL` when the reversal pushes the paid total below the total due."

    Design: Difficulty/compensating_invariant/ledger_conservation_on_remittance_reverse
    """
    op, ret, _ = _filed_paid_then_reversed(api)
    after_op = get_operator(api, op["id"])
    entries = validate_success(api.list_operator_ledger_entries(op["id"], ADMIN), 200)
    assert_balance_equals_ledger(after_op, entries)
    after_ret = validate_success(api.get_return(ret["id"], ADMIN), 200)
    # amount_paid back to 0 (only cleared remittances count) -> UNPAID.
    assert after_ret["settlement_status"] == "UNPAID"


# ============================================================
# Difficulty: priority_pair_validation_conflict/state_beats_fiscal_on_remittance_clear
# ============================================================
def _draft_return_with_huge_received_remittance(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))  # never filed
    rem = create_remittance(api, ret["id"], 999999999)  # RECEIVED
    return op, ret, rem


def test_clear_on_draft_return_state_error_wins(api):
    """PRD 3.6: "The parent return's filing status must be `FILED` or `AMENDED`,
    otherwise the clear is rejected with `ERR_INVALID_STATE`."
    PRD 2.9: "A check earlier in this order takes precedence over any later one that
    might also apply to the same request."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_remittance_clear
    """
    op, ret, rem = _draft_return_with_huge_received_remittance(api)
    resp = api.clear_remittance(rem["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_clear_on_draft_return_leaves_remittance_received(api):
    """PRD 3.6: "A new remittance begins in `RECEIVED`; it has no ledger effect until
    it clears."
    PRD 3.6: "The parent return's filing status must be `FILED` or `AMENDED`,
    otherwise the clear is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_remittance_clear
    """
    op, ret, rem = _draft_return_with_huge_received_remittance(api)
    api.clear_remittance(rem["id"], ADMIN)
    assert validate_success(api.get_remittance(rem["id"], ADMIN), 200)["status"] == "RECEIVED"


# ---- Corner: endpoints/list_ledger_entries_for_operator_fk_reverse ----
def test_list_ledger_entries_after_file_and_clear(api):
    """PRD 3.4: "On a successful filing the server sets `filing_status` to `FILED`,
    stamps `filed_at` from the logical clock, computes `tax_due_cents`, and posts a
    `TAX_DUE` ledger entry for that amount (a positive debit)".
    PRD 3.6: "On clearing, the server posts a `REMITTANCE` ledger entry for the
    negative of the amount (a credit that reduces what the operator owes)".

    Design: Corner/endpoints/list_ledger_entries_for_operator_fk_reverse
    """
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_and_file_return(api, op["id"], single_line(prop["id"], 1000000))
    create_cleared_remittance(api, ret["id"], 120000)
    entries = validate_success(api.list_operator_ledger_entries(op["id"], ADMIN), 200)
    assert isinstance(entries, list)
    assert len(entries) == 2
    assert get_operator(api, op["id"])["account_balance_cents"] == 0


# ---- Corner: endpoints/list_returns_for_operator_fk_reverse ----
def test_list_returns_for_operator(api):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD 4 (endpoint catalogue): "GET `/operators/{id}/returns` — List returns for an
    operator".

    Design: Corner/endpoints/list_returns_for_operator_fk_reverse
    """
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 1000000))
    data = validate_success(api.list_operator_returns(op["id"], make_operator_headers(op["id"])), 200)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == ret["id"]
