"""Delinquency cure cycle, auction fork-join, depth-3 cascades, transfer count invariant.

Queue A (Difficulty) translations: non_linear_state_machine, transitive_cascade,
compensating_invariant (occupancy count conservation).
"""
import pytest
from test_helpers import (
    validate_success, validate_paginated,
    TEST_USERS, make_tenant_headers,
    setup_activated, setup_auction_opened, setup_auction_scheduled,
    setup_delinquent_past_90, setup_transfer_requested,
    set_clock, pay,
    api_client,
)

FM = TEST_USERS["facility_manager_headers"]
LIEN = TEST_USERS["lien_administrator_headers"]


# ─── non_linear_state_machine / lease delinquency cure cycle ───

def test_lease_delinquent_then_cured_back_to_active(api):
    """PRD §3.5: "When a billing run flags an invoice on an `ACTIVE` lease as overdue ...
    the lease moves `ACTIVE → DELINQUENT`."
    PRD §3.5: "a lease in `DELINQUENT` or `PRE_LIEN` status moves back to `ACTIVE`, all
    its overdue invoices that the payment fully covers settle to `PAID`, and the lease's
    `days_past_due` resets to zero."

    Design: Difficulty/non_linear_state_machine/nonlinear_lease_delinquency_cure_cycle
    """
    # Climate @10000 -> invoice 12000; advance past grace, billing-cycle -> DELINQUENT
    # with +2000 late fee (balance 14000).
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    set_clock("2026-04-20T00:00:00Z")
    validate_success(api.run_billing_cycle(ctx["facility"]["id"], FM), 200)
    delinquent = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert delinquent["status"] == "DELINQUENT"
    assert delinquent["balance_cents"] == 14000
    # Full payment cures back to ACTIVE.
    pay(ctx["lease"]["id"], 14000, ctx["tenant"]["id"])
    cured = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert cured["status"] == "ACTIVE"
    assert cured["balance_cents"] == 0
    assert cured["days_past_due"] == 0


def test_lease_cure_resets_days_past_due(api):
    """PRD §3.6: "A successful payment that drives the lease's balance to zero triggers
    the full cure cascade: a `DELINQUENT` or `PRE_LIEN` lease returns to `ACTIVE` with
    `days_past_due` reset to zero."

    Design: Difficulty/non_linear_state_machine/nonlinear_lease_delinquency_cure_cycle
    """
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    set_clock("2026-04-20T00:00:00Z")
    validate_success(api.run_billing_cycle(ctx["facility"]["id"], FM), 200)
    before = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert before["days_past_due"] > 0
    pay(ctx["lease"]["id"], 14000, ctx["tenant"]["id"])
    after = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert after["days_past_due"] == 0
    assert after["status"] == "ACTIVE"


# ─── non_linear_state_machine / auction fork-join (SOLD branch) ───

def test_auction_completes_sale_sold_branch(api):
    """PRD §3.8: "On completion the proceeding moves `SCHEDULED → SOLD` and the
    surplus-distribution waterfall runs against the proceeds. ... The lease moves
    `AUCTION_SCHEDULED → AUCTIONED` ... The vacated unit moves to `AVAILABLE`."

    Design: Difficulty/non_linear_state_machine/nonlinear_auction_fork_join_scheduled_branches
    """
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  past_due_date="2026-07-02T00:00:00Z")
    sold = validate_success(
        api.complete_sale(ctx["auction"]["id"], {"sale_proceeds_cents": 60000}, LIEN), 200)
    assert sold["status"] == "SOLD"
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease["status"] == "AUCTIONED"
    unit = validate_success(api.get_unit(ctx["unit"]["id"], FM), 200)
    assert unit["status"] == "AVAILABLE", \
        "SOLD branch frees the unit (REDEEMED branch would not)"


def test_auction_redeem_branch_restores_lease(api):
    """PRD §3.9: "Redemption is defined while the proceeding is in `NOTICE_SENT`,
    `LIEN_FILED`, or `SCHEDULED` status and the lease is in `LIEN` or `AUCTION_SCHEDULED`;
    it moves the proceeding to `REDEEMED`, returns the lease to `ACTIVE`, and resets
    `days_past_due` to zero, with no unit or insurance change."

    Design: Difficulty/non_linear_state_machine/nonlinear_auction_fork_join_scheduled_branches
    """
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  past_due_date="2026-07-02T00:00:00Z")
    # Pay the full outstanding balance so redemption is permitted, then redeem.
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    pay(ctx["lease"]["id"], lease["balance_cents"], ctx["tenant"]["id"])
    redeemed = validate_success(
        api.redeem_auction(ctx["auction"]["id"], make_tenant_headers(ctx["tenant"]["id"])), 200)
    assert redeemed["status"] == "REDEEMED"
    lease_after = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease_after["status"] == "ACTIVE"
    # REDEEMED branch leaves the unit occupied (no unit change).
    unit = validate_success(api.get_unit(ctx["unit"]["id"], FM), 200)
    assert unit["status"] == "OCCUPIED"


# ─── transitive_cascade / auction-sold depth-3 ───

def test_auction_sold_cascades_lease_unit_insurance(api):
    """PRD §3.8: "The lease moves `AUCTION_SCHEDULED → AUCTIONED` ... The vacated unit
    moves to `AVAILABLE`, its `current_lease_id` is cleared to null, and the facility's
    `occupied_unit_count` is recomputed. Any active insurance policy on the lease is
    cancelled with its `coverage_end` set to the current clock."

    Design: Difficulty/transitive_cascade/cascade_auction_sold_to_lease_to_unit_to_insurance_depth3
    """
    # insurance_required lease with STANDARD policy ACTIVE.
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  with_insurance="STANDARD",
                                  past_due_date="2026-07-02T00:00:00Z")
    policy_id = ctx["policy"]["id"]
    validate_success(
        api.complete_sale(ctx["auction"]["id"], {"sale_proceeds_cents": 60000}, LIEN), 200)
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease["status"] == "AUCTIONED"
    unit = validate_success(api.get_unit(ctx["unit"]["id"], FM), 200)
    assert unit["status"] == "AVAILABLE"
    fac = validate_success(api.get_facility(ctx["facility"]["id"], FM), 200)
    assert fac["occupied_unit_count"] == 0
    policy = validate_success(api.get_insurance_policy(policy_id, FM), 200)
    assert policy["status"] == "CANCELLED"


def test_auction_sold_clears_lease_balance(api):
    """PRD §3.8: "The lease's `balance_cents` is set to zero and an `AUCTION_SETTLEMENT`
    ledger entry is appended."

    Design: Difficulty/transitive_cascade/cascade_auction_sold_to_lease_to_unit_to_insurance_depth3
    """
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  with_insurance="STANDARD",
                                  past_due_date="2026-07-02T00:00:00Z")
    validate_success(
        api.complete_sale(ctx["auction"]["id"], {"sale_proceeds_cents": 60000}, LIEN), 200)
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease["balance_cents"] == 0
    entries, _ = validate_paginated(
        api.list_ledger_entries(FM, params={"lease_id": ctx["lease"]["id"]}))
    settlements = [e for e in entries if e["entry_type"] == "AUCTION_SETTLEMENT"]
    assert len(settlements) >= 1, f"expected an AUCTION_SETTLEMENT entry, got {entries}"


# ─── transitive_cascade / payment-cure depth-3 ───

def test_payment_cure_cancels_open_proceeding(api):
    """PRD §3.6: "A successful payment that drives the lease's balance to zero triggers
    the full cure cascade: a `DELINQUENT` or `PRE_LIEN` lease returns to `ACTIVE` with
    `days_past_due` reset to zero, any open auction proceeding in `NOTICE_SENT` or
    `LIEN_FILED` is `CANCELLED`, and a `LAPSED` insurance policy returns to `ACTIVE`."

    Design: Difficulty/transitive_cascade/cascade_payment_cure_to_invoice_to_lease_to_auction_depth3
    """
    # Auction opened (NOTICE_SENT), lease LIEN, outstanding 14000.
    ctx = setup_auction_opened(climate=True, rate=10000,
                               past_due_date="2026-07-02T00:00:00Z")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    pay(ctx["lease"]["id"], lease["balance_cents"], ctx["tenant"]["id"])
    lease_after = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease_after["status"] == "ACTIVE"
    assert lease_after["balance_cents"] == 0
    auction = validate_success(api.get_auction_proceeding(ctx["auction"]["id"], LIEN), 200)
    assert auction["status"] == "CANCELLED"


def test_payment_cure_marks_overdue_invoice_paid(api):
    """PRD §3.6: "the invoice moves to `PAID` if it is now fully covered or to `PARTIAL`
    if only partly covered."

    Design: Difficulty/transitive_cascade/cascade_payment_cure_to_invoice_to_lease_to_auction_depth3
    """
    ctx = setup_auction_opened(climate=True, rate=10000,
                               past_due_date="2026-07-02T00:00:00Z")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    pay(ctx["lease"]["id"], lease["balance_cents"], ctx["tenant"]["id"])
    invoices, _ = validate_paginated(
        api.list_invoices(FM, params={"lease_id": ctx["lease"]["id"]}))
    assert all(i["status"] == "PAID" for i in invoices), \
        f"all covered invoices should be PAID, got {[i['status'] for i in invoices]}"


# ─── compensating_invariant / transfer conserves occupied_unit_count ───

def test_transfer_conserves_occupied_unit_count(api):
    """PRD §3.10: "Because one unit is vacated as another is occupied within the facility,
    the facility's `occupied_unit_count` is unchanged across the move."

    Design: Difficulty/compensating_invariant/invariant_transfer_conserves_occupied_unit_count
    """
    ctx = setup_transfer_requested(from_rate=10000, to_rate=18000)
    before = validate_success(api.get_facility(ctx["facility"]["id"], FM), 200)
    assert before["occupied_unit_count"] == 1
    set_clock("2026-04-16T00:00:00Z")
    validate_success(api.complete_transfer(ctx["transfer"]["id"], FM), 200)
    after = validate_success(api.get_facility(ctx["facility"]["id"], FM), 200)
    assert after["occupied_unit_count"] == 1, "conserved across the move"
    u1 = validate_success(api.get_unit(ctx["u1"]["id"], FM), 200)
    u2 = validate_success(api.get_unit(ctx["u2"]["id"], FM), 200)
    assert u1["status"] == "AVAILABLE"
    assert u2["status"] == "OCCUPIED"


def test_transfer_resnapshots_lease_unit_and_rate(api):
    """PRD §3.10: "The lease's `unit_id` is updated to the destination, and its snapshot
    `monthly_rate_cents` and `climate_controlled` are updated to the new unit's rate and
    climate flag."

    Design: Difficulty/compensating_invariant/invariant_transfer_conserves_occupied_unit_count
    """
    ctx = setup_transfer_requested(from_rate=10000, to_rate=18000)
    set_clock("2026-04-16T00:00:00Z")
    validate_success(api.complete_transfer(ctx["transfer"]["id"], FM), 200)
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease["unit_id"] == ctx["u2"]["id"]
    assert lease["monthly_rate_cents"] == 18000
