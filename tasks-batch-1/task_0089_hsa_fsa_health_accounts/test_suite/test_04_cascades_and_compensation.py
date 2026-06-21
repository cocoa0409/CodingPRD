"""Transitive cascades (disburse depth-3, settle carryover depth-2) and compensating
invariants (reimburse->clawback conserves the FSA pool; contribute->reverse conserves HSA
principal).

Translates Difficulty/transitive_cascade and Difficulty/compensating_invariant instances.
"""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS,
    setup_reimbursed_hsa, setup_active_fsa, setup_active_hsa,
    create_approved_claim, reimburse_single_claim, get_account,
    settle_plan_year, find_carryover_account,
    assert_fsa_election_pool_conserved,
)

ADMIN = TEST_USERS["plan_admin_headers"]


# --- Disburse cascade depth-3: claim -> ledger -> balance -> depletion ---

def test_disburse_appends_reimbursement_ledger_entry(api):
    """PRD §3.6: "the claim moves from `APPROVED` to `REIMBURSED`, a `REIMBURSEMENT`
    `LedgerEntry` for its `reimbursable_amount_cents` is appended".

    Hop 1 of the cascade: the disburse appends a 100000 REIMBURSEMENT ledger row and the
    claim reaches REIMBURSED.

    Design: Difficulty/transitive_cascade/disburse_cascade_depth3_claim_ledger_account_depletion
    """
    py, p, acc, claim = setup_reimbursed_hsa(contribution_cents=100000, claim_cents=100000)
    assert claim["status"] == "REIMBURSED"
    rows, _ = validate_paginated(api.get_account_ledger_entries(
        acc["id"], ADMIN, params={"entry_type": "REIMBURSEMENT"}))
    assert len(rows) == 1, f"expected one REIMBURSEMENT entry, got {len(rows)}"
    assert rows[0]["amount_cents"] == 100000


def test_disburse_cascades_to_zero_balance_and_depletion(api):
    """PRD §3.6: "and the account's `reimbursed_cents` and `available_balance_cents` are
    recomputed (a cascade that mutates the account). If a claim is reimbursed but its
    `available_balance_cents` reaches zero, the account's `funding_status` moves from
    `ACTIVE` to `DEPLETED`".

    Hops 2-3: the ledger drives the balance recompute to 0, which flips funding_status to
    DEPLETED.

    Design: Difficulty/transitive_cascade/disburse_cascade_depth3_claim_ledger_account_depletion
    """
    py, p, acc, claim = setup_reimbursed_hsa(contribution_cents=100000, claim_cents=100000)
    assert acc["available_balance_cents"] == 0, (
        f"balance recomputed to 0; got {acc['available_balance_cents']}")
    assert acc["funding_status"] == "DEPLETED"


# --- Settle cascade depth-2: settle -> CLOSED with carryover -> new next-year account ---

def test_settle_closes_account_and_records_forfeiture_remainder(api):
    """PRD §3.8: "the carryover bucket is filled first to the smaller of the unused balance
    and `carryover_cap_cents`, and the remainder of the unused balance forfeits".
    PRD §3.8: "its `funding_status` moves to `CLOSED` (terminal)".

    Hop 1: a 100000 HEALTH_FSA with cap 66000 settles to CLOSED with forfeited 34000.

    Design: Difficulty/transitive_cascade/settle_cascade_depth2_carryover_creates_next_year_account
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=100000,
        auto_adjudication_threshold_cents=1000000,
        plan_year_overrides={"label": "PY-CARRY", "fsa_relief_mode": "CARRYOVER",
                             "carryover_cap_cents": 66000})
    settle_plan_year(py["id"])
    settled = validate_success(api.get_account(acc["id"], ADMIN))
    assert settled["funding_status"] == "CLOSED"
    assert settled["forfeited_cents"] == 34000, (
        f"100000 - 66000; expected 34000, got {settled['forfeited_cents']}")
    rows, _ = validate_paginated(api.get_account_ledger_entries(
        acc["id"], ADMIN, params={"entry_type": "CARRYOVER_OUT"}))
    assert len(rows) == 1 and rows[0]["amount_cents"] == 66000


def test_settle_carryover_creates_linked_next_year_account(api):
    """PRD §3.8: "a new destination Health FSA `Account` is created for the same
    `participant_id` and the same `plan_year_id` ... credited with `carried_in_cents` equal
    to the carried amount, and stamped with `carryover_source_account_id` pointing back at
    the source account".

    Hop 2: the carryover itself creates a destination account credited 66000.

    Design: Difficulty/transitive_cascade/settle_cascade_depth2_carryover_creates_next_year_account
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=100000,
        auto_adjudication_threshold_cents=1000000,
        plan_year_overrides={"label": "PY-CARRY", "fsa_relief_mode": "CARRYOVER",
                             "carryover_cap_cents": 66000})
    settle_plan_year(py["id"])
    dest = find_carryover_account(acc["id"])
    assert dest is not None, "carryover created a destination account"
    assert dest["carried_in_cents"] == 66000
    assert dest["carryover_source_account_id"] == acc["id"]


# --- Compensating invariant: FSA election pool conserved across reimburse + clawback ---

def test_fsa_pool_conserved_after_reimbursement(api):
    """PRD §3.5: "`elected_amount_cents` plus `carried_in_cents` minus `reimbursed_cents` for
    a Health FSA or DCFSA".

    After reimbursing 80000 on a 335000 election: available 255000 + reimbursed 80000 ==
    335000.

    Design: Difficulty/compensating_invariant/reimburse_then_clawback_conserves_fsa_election_pool
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=1000000)
    claim = create_approved_claim(acc["id"], service_date="2026-04-01",
                                  expense_category="MEDICAL",
                                  claimed_amount_cents=80000, substantiated=True)
    reimburse_single_claim(p["id"], claim["id"], acc["id"])
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["available_balance_cents"] == 255000
    assert after["reimbursed_cents"] == 80000
    assert_fsa_election_pool_conserved(after, 335000)


def test_clawback_restores_fsa_pool_with_zero_drift(api):
    """PRD §3.7: "A `PlanAdmin` may instead claw back a `REIMBURSED` claim: this appends a
    compensating `REIMBURSEMENT_REVERSAL` `LedgerEntry` for the claim's
    `reimbursable_amount_cents`, recomputes the account's `reimbursed_cents` and
    `available_balance_cents`, and moves the claim to `VOIDED`."

    After the clawback the pool returns to 335000 with reimbursed_cents back to 0.

    Design: Difficulty/compensating_invariant/reimburse_then_clawback_conserves_fsa_election_pool
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=1000000)
    claim = create_approved_claim(acc["id"], service_date="2026-04-01",
                                  expense_category="MEDICAL",
                                  claimed_amount_cents=80000, substantiated=True)
    reimburse_single_claim(p["id"], claim["id"], acc["id"])
    validate_success(api.void_claim(claim["id"], ADMIN))

    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["available_balance_cents"] == 335000
    assert after["reimbursed_cents"] == 0
    assert_fsa_election_pool_conserved(after, 335000)
    claim_after = validate_success(api.get_claim(claim["id"], ADMIN))
    assert claim_after["status"] == "VOIDED"


# --- Compensating invariant: HSA contributed principal conserved across contribute + reverse ---

def test_reverse_contribution_restores_hsa_principal_to_zero(api):
    """PRD §3.3: "Reversing a `POSTED` contribution — a `PlanAdmin` correction — moves that
    contribution's `status` from `POSTED` to `REVERSED`, appends a `CONTRIBUTION_REVERSAL`
    `LedgerEntry`, recomputes `contributed_cents` and `available_balance_cents`".

    A 50000 contribution then reversed returns contributed_cents and
    available_balance_cents to 0 with no drift.

    Design: Difficulty/compensating_invariant/contribute_then_reverse_conserves_hsa_contributed_principal
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    contrib = validate_success(api.create_contribution(
        acc["id"],
        {"amount_cents": 50000, "source": "PAYROLL", "posted_at": "2026-02-01T00:00:00Z",
         "expected_account_version": acc["version"]}, ADMIN), expected_status=201)
    live = get_account(acc["id"])
    validate_success(api.reverse_contribution(
        acc["id"], contrib["id"], {"expected_account_version": live["version"]}, ADMIN))

    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["contributed_cents"] == 0, (
        f"principal conserved to baseline; got {after['contributed_cents']}")
    assert after["available_balance_cents"] == 0


def test_reverse_contribution_appends_reversal_ledger_entry(api):
    """PRD §3.3: "appends a `CONTRIBUTION_REVERSAL` `LedgerEntry`, recomputes
    `contributed_cents` and `available_balance_cents`".
    PRD §2.5: "The `amount_cents` on a ledger entry is always a positive integer recording
    the magnitude of the event".

    The reversal of a 50000 contribution appends exactly one CONTRIBUTION_REVERSAL entry of
    magnitude 50000.

    Design: Difficulty/compensating_invariant/contribute_then_reverse_conserves_hsa_contributed_principal
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    contrib = validate_success(api.create_contribution(
        acc["id"],
        {"amount_cents": 50000, "source": "PAYROLL", "posted_at": "2026-02-01T00:00:00Z",
         "expected_account_version": acc["version"]}, ADMIN), expected_status=201)
    live = get_account(acc["id"])
    validate_success(api.reverse_contribution(
        acc["id"], contrib["id"], {"expected_account_version": live["version"]}, ADMIN))

    rows, _ = validate_paginated(api.get_account_ledger_entries(
        acc["id"], ADMIN, params={"entry_type": "CONTRIBUTION_REVERSAL"}))
    assert len(rows) == 1 and rows[0]["amount_cents"] == 50000
