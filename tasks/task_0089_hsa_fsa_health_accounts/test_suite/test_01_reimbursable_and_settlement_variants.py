"""Dual-variant calculations: forward-looking vs chronological reimbursable amount,
and carryover-vs-forfeit year-end settlement.

Translates Difficulty/dual_variant_calc and Difficulty/combinatorial_formula (settlement
waterfall) instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_disburser_headers,
    setup_hsa_with_contribution, setup_active_fsa, create_approved_claim,
    create_batch, get_account, reimburse_single_claim, file_claim_as_admin,
    approve_claim, settle_plan_year, find_carryover_account,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_hsa_approve_uses_forward_looking_election_ceiling(api):
    """PRD §3.5: "The projected basis is `elected_amount_cents` minus `reimbursed_cents`
    for an HSA (the full annual target, projecting payroll that has not yet posted)".
    PRD §3.5: "The stored `reimbursable_amount_cents` is the smaller of the claim's
    `claimed_amount_cents` and the projected basis floored at zero".

    On an HSA contributed only 100000 toward a 437500 election, approving a 150000 claim
    stores reimbursable_amount_cents=150000 (ceiling is the projected election 437500, not
    cash on hand).

    Design: Difficulty/dual_variant_calc/reimbursable_forward_vs_chronological_on_hsa_claim
    """
    py, p, acc = setup_hsa_with_contribution(contribution_cents=100000,
                                             elected_amount_cents=437500)
    claim = file_claim_as_admin(acc["id"], service_date="2026-03-01",
                                expense_category="MEDICAL",
                                claimed_amount_cents=150000, substantiated=True)
    approved = approve_claim(claim["id"])
    assert approved["status"] == "APPROVED"
    assert approved["reimbursable_amount_cents"] == 150000, (
        f"forward-looking ceiling is the 437500 election; expected 150000, "
        f"got {approved['reimbursable_amount_cents']}")


def test_hsa_disburse_rejects_when_cash_below_stored_reimbursable(api):
    """PRD §3.5: "If cash on hand is less than the claim's stored
    `reimbursable_amount_cents`, the disbursement of that claim is rejected with
    `ERR_INSUFFICIENT_FUNDS` (HTTP 422): the forward-looking approval had over-projected
    an HSA whose payroll contributions had not yet landed."

    The 150000 claim approved against a 437500 election is rejected at disburse because
    cash-on-hand is only 100000; the claim stays APPROVED.

    Design: Difficulty/dual_variant_calc/reimbursable_forward_vs_chronological_on_hsa_claim
    """
    py, p, acc = setup_hsa_with_contribution(contribution_cents=100000,
                                             elected_amount_cents=437500)
    claim = file_claim_as_admin(acc["id"], service_date="2026-03-01",
                                expense_category="MEDICAL",
                                claimed_amount_cents=150000, substantiated=True)
    approve_claim(claim["id"])
    batch = create_batch(p["id"], [claim["id"]])
    live = get_account(acc["id"])
    disb_headers = make_disburser_headers("disb-1")
    resp = api.disburse_batch(
        batch["id"], {"expected_account_version": live["version"]}, disb_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)

    claim_after = validate_success(api.get_claim(claim["id"], ADMIN))
    assert claim_after["status"] == "APPROVED", "disburse rejected; claim unchanged"


def test_health_fsa_carryover_splits_unused_into_carryover_and_forfeit(api):
    """PRD §3.8: "A Health FSA under `CARRYOVER` performs a two-bucket waterfall: the
    carryover bucket is filled first to the smaller of the unused balance and
    `carryover_cap_cents`, and the remainder of the unused balance forfeits; its
    `forfeited_cents` is therefore the unused balance minus the carried-over amount."

    Unused 135000 with cap 66000 → carryover 66000, forfeited 69000.

    Design: Difficulty/dual_variant_calc/settlement_carryover_vs_forfeit_on_health_fsa_account
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=1000000,
        plan_year_overrides={"label": "PY-CARRY", "fsa_relief_mode": "CARRYOVER",
                             "carryover_cap_cents": 66000})
    # Reimburse 200000 so available_balance_cents = 335000 - 200000 = 135000.
    claim = create_approved_claim(acc["id"], service_date="2026-05-01",
                                  expense_category="MEDICAL",
                                  claimed_amount_cents=200000, substantiated=True)
    reimburse_single_claim(p["id"], claim["id"], acc["id"])

    settle_plan_year(py["id"])
    settled = validate_success(api.get_account(acc["id"], ADMIN))
    assert settled["forfeited_cents"] == 69000, (
        f"CARRYOVER variant: 135000 - min(135000,66000); expected 69000, "
        f"got {settled['forfeited_cents']}")
    assert settled["funding_status"] == "CLOSED"


def test_health_fsa_carryover_creates_destination_holding_account(api):
    """PRD §3.8: "a new destination Health FSA `Account` is created for the same
    `participant_id` and the same `plan_year_id` ... credited with `carried_in_cents` equal
    to the carried amount ... The destination is a carryover-holding account discoverable by
    listing accounts filtered on `carryover_source_account_id` equal to the source account's
    id."

    Design: Difficulty/dual_variant_calc/settlement_carryover_vs_forfeit_on_health_fsa_account
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=1000000,
        plan_year_overrides={"label": "PY-CARRY", "fsa_relief_mode": "CARRYOVER",
                             "carryover_cap_cents": 66000})
    claim = create_approved_claim(acc["id"], service_date="2026-05-01",
                                  expense_category="MEDICAL",
                                  claimed_amount_cents=200000, substantiated=True)
    reimburse_single_claim(p["id"], claim["id"], acc["id"])
    settle_plan_year(py["id"])

    resp = api.list_accounts(ADMIN, params={"carryover_source_account_id": acc["id"]})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1, f"expected exactly one carryover-holding account, got {len(rows)}"
    assert rows[0]["carried_in_cents"] == 66000, (
        f"destination carried_in_cents expected 66000, got {rows[0]['carried_in_cents']}")


def test_settlement_waterfall_orders_carryover_before_forfeit(api):
    """PRD §3.8: "the carryover bucket is filled first to the smaller of the unused balance
    and `carryover_cap_cents`, and the remainder of the unused balance forfeits".

    Unused 200000, cap 66000 → carryover 66000 computed first, then forfeit 134000.

    Design: Difficulty/combinatorial_formula/settlement_waterfall_order_mode_c
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=1000000,
        plan_year_overrides={"label": "PY-CARRY", "fsa_relief_mode": "CARRYOVER",
                             "carryover_cap_cents": 66000})
    # Reimburse 135000 so available_balance_cents = 335000 - 135000 = 200000.
    claim = create_approved_claim(acc["id"], service_date="2026-05-01",
                                  expense_category="DENTAL",
                                  claimed_amount_cents=135000, substantiated=True)
    reimburse_single_claim(p["id"], claim["id"], acc["id"])

    settle_plan_year(py["id"])
    settled = validate_success(api.get_account(acc["id"], ADMIN))
    assert settled["forfeited_cents"] == 134000, (
        f"carryover_out=min(200000,66000)=66000 first, then forfeit=200000-66000; "
        f"expected 134000, got {settled['forfeited_cents']}")


def test_settlement_waterfall_carryover_amount_capped(api):
    """PRD §3.8: "the carryover bucket is filled first to the smaller of the unused balance
    and `carryover_cap_cents`".

    The carryover-holding account is credited exactly the cap (66000) when unused (200000)
    exceeds it.

    Design: Difficulty/combinatorial_formula/settlement_waterfall_order_mode_c
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=1000000,
        plan_year_overrides={"label": "PY-CARRY", "fsa_relief_mode": "CARRYOVER",
                             "carryover_cap_cents": 66000})
    claim = create_approved_claim(acc["id"], service_date="2026-05-01",
                                  expense_category="DENTAL",
                                  claimed_amount_cents=135000, substantiated=True)
    reimburse_single_claim(p["id"], claim["id"], acc["id"])
    settle_plan_year(py["id"])

    dest = find_carryover_account(acc["id"])
    assert dest is not None, "expected one carryover-holding account"
    assert dest["carried_in_cents"] == 66000, (
        f"carried_in_cents capped at 66000, got {dest['carried_in_cents']}")
