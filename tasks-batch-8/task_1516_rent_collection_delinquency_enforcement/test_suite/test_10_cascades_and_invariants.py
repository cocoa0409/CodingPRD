"""Cascade chains (A and the sweep's notice recompute) and the conserved
quantities that must survive them: the lease ledger identity and the
draft-notice live demand."""
from test_helpers import (
    add_charge,
    assert_ledger_identity,
    create_notice,
    get_ledger,
    list_allocations,
    list_charges,
    list_notices,
    post_payment,
    record_and_post_payment,
    record_payment,
    return_payment,
    run_sweep,
    set_clock,
    setup_property_tenant_lease,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_nsf_return_cascade_depth4(api):
    """PRD 3.4: "The return fires Cascade A, in a fixed order. First, the payment
    itself flips from `POSTED` to `RETURNED` and its `return_count` increases by one.
    Second, for every `APPLY` allocation the payment ever created, the system writes a
    `REVERSE` allocation of equal amount bearing the note `nsf-reversal`. Third, each
    affected charge recomputes its outstanding balance and flips back toward `OPEN`
    exactly as described in §3.2. Fourth, every `DRAFT` notice covering an affected
    charge recomputes its demanded amount, and the returned-payment fee is assessed as
    a new `NSF_FEE` charge on the lease: its amount is the lesser of the requested
    `nsf_fee_cents` and the property's `nsf_fee_cap_cents`, it is due on the current
    date, its source is `RETURN`, and its coverage period is the current date itself."
    PRD 3.7: "The `amount_demanded_cents` is a live figure while the notice remains in
    `DRAFT`, recomputed on every change to a covered charge — an allocation, a
    reversal, a waiver, or a dispute adjustment."

    Design: Difficulty/transitive_cascade/nsf_return_cascade_depth4
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)

    notice = create_notice(lease_id, [rent["id"]])
    assert notice["amount_demanded_cents"] == 204000, (
        "Draft demand embeds the provisional FLAT fee (4000) on top of the 200000 outstanding"
    )

    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)
    demand_after_post = [n for n in list_notices(lease_id) if n["id"] == notice["id"]][0]["amount_demanded_cents"]
    assert demand_after_post == 0, "The live draft demand recomputes to 0 once the covered charge is paid"

    set_clock("2026-08-03T00:00:00Z")
    returned = return_payment(payment["id"], nsf_fee_cents=3000)
    # Link 1: the payment itself flips.
    assert returned["status"] == "RETURNED"

    # Link 2: a REVERSE allocation mirrors every APPLY.
    allocs = list_allocations(params={"payment_id": payment["id"]})
    pairs = sorted((a["direction"], a["amount_cents"]) for a in allocs)
    assert ("APPLY", 200000) in pairs
    assert ("REVERSE", 200000) in pairs
    assert all(a["note"] == "nsf-reversal" for a in allocs if a["direction"] == "REVERSE")

    # Link 3: the charge flips back toward OPEN.
    rent_after = [c for c in list_charges(lease_id) if c["id"] == rent["id"]][0]
    assert rent_after["status"] == "OPEN"
    assert rent_after["outstanding_cents"] == 200000

    # Link 4: the draft notice demand recomputes (restored outstanding + provisional fee).
    demand_after_return = [n for n in list_notices(lease_id) if n["id"] == notice["id"]][0]["amount_demanded_cents"]
    assert demand_after_return == 204000

    # Link 4 (parallel branch): the NSF fee charge is created.
    nsf_fees = list_charges(lease_id, params={"kind": "NSF_FEE"})
    assert len(nsf_fees) == 1
    assert nsf_fees[0]["amount_cents"] == 3000
    assert nsf_fees[0]["due_date"] == "2026-08-03"
    assert nsf_fees[0]["source"] == "RETURN"


def test_sweep_late_fee_notice_cascade_depth3(api):
    """PRD 3.7: "The `amount_demanded_cents` is a live figure while the notice remains
    in `DRAFT`, recomputed on every change to a covered charge — an allocation, a
    reversal, a waiver, or a dispute adjustment. It is the sum of the covered charges'
    outstanding balances, plus, for each covered `RENT` charge that still has a
    positive outstanding balance and does not yet have a non-`VOID` late-fee charge for
    the same period, a provisional late fee. ... A covered rent charge that already
    carries a non-`VOID` late fee for the period contributes no provisional fee."
    PRD 3.6: "When the assessed fee is greater than zero, the sweep persists a
    `LATE_FEE` charge on the lease: due on the run date, stamped with source `SWEEP`,
    and carrying the same coverage period as the rent charge that spawned it."

    Design: Difficulty/transitive_cascade/sweep_late_fee_notice_cascade_depth3
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    notice = create_notice(lease_id, [rent["id"]])
    assert notice["amount_demanded_cents"] == 204000, "Provisional fee embedded pre-sweep"

    set_clock("2026-08-07T00:00:00Z")
    report = run_sweep()
    assert report["late_fees_assessed_count"] == 1

    fees = list_charges(lease_id, params={"kind": "LATE_FEE"})
    assert len(fees) == 1
    assert fees[0]["amount_cents"] == 4000, "FLAT 4000 sits under the 5000 cap"
    assert fees[0]["due_date"] == "2026-08-07"

    demand_after = [n for n in list_notices(lease_id) if n["id"] == notice["id"]][0]["amount_demanded_cents"]
    assert demand_after == 200000, (
        "With an assessed LATE_FEE now existing for the period, the provisional component drops out of the draft demand"
    )


def test_ledger_identity_through_nsf_cycle(api):
    """PRD 3.2: "For reconciliation, a computed ledger read of a lease — available to
    `PropertyManager` and `LeasingAgent` — reports two balance variants plus the
    identity components behind them: `forward_balance_cents`, the simple sum of
    outstanding balances over the lease's `OPEN` and `PARTIALLY_PAID` charges, counting
    every open charge at face value including charges whose due dates lie after any
    move-out (the acceleration view); `chronological_balance_cents`, the move-out-aware
    variant whose proration rules are defined with the move-out workflow in §3.9; and
    the components `total_charged_cents`, `total_waived_cents`,
    `total_applied_net_cents`, `total_outstanding_cents`, and `open_charge_count`."
    PRD 3.2: "Its `outstanding_cents` is a computed figure — the face amount, minus
    waived cents, minus the net applied cents (the sum of `APPLY` allocations minus the
    sum of `REVERSE` allocations) — recomputed on every allocation, waiver, reversal,
    or dispute adjustment."

    Design: Difficulty/compensating_invariant/ledger_identity_through_nsf_cycle
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)

    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=210000)
    ledger1 = get_ledger(lease_id)
    assert ledger1["total_charged_cents"] == 210000
    assert ledger1["total_waived_cents"] == 0
    assert ledger1["total_outstanding_cents"] == 0
    assert ledger1["total_applied_net_cents"] == 210000
    assert_ledger_identity(ledger1)

    set_clock("2026-08-03T00:00:00Z")
    return_payment(payment["id"], nsf_fee_cents=3000)
    ledger2 = get_ledger(lease_id)
    assert ledger2["total_charged_cents"] == 213000, "The new NSF_FEE 3000 charge joins the ledger"
    assert ledger2["total_waived_cents"] == 0
    assert ledger2["total_outstanding_cents"] == 213000
    assert ledger2["total_applied_net_cents"] == 0
    assert_ledger_identity(ledger2)

    set_clock("2026-08-04T00:00:00Z")
    post_payment(payment["id"])
    ledger3 = get_ledger(lease_id)
    assert ledger3["total_charged_cents"] == 213000
    assert ledger3["total_waived_cents"] == 0
    assert ledger3["total_outstanding_cents"] == 3000, (
        "Re-presentment under FEES_FIRST pays the NSF fee first, leaving 3000 of rent outstanding"
    )
    assert ledger3["total_applied_net_cents"] == 210000
    assert_ledger_identity(ledger3)


def test_nsf_return_cascade_payment_fields(api):
    """PRD 3.4: "The return fires Cascade A, in a fixed order. First, the payment
    itself flips from `POSTED` to `RETURNED` and its `return_count` increases by one."
    PRD 3.3: "On a freshly recorded payment, `posted_date`, `return_reason_code`, and
    `nsf_fee_cents` are null and `return_count` is zero; each is set only by the
    lifecycle events that produce them."

    Design: Difficulty/transitive_cascade/nsf_return_cascade_depth4
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)

    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)
    assert payment["posted_date"] is None
    assert payment["return_reason_code"] is None
    assert payment["return_count"] == 0

    post_payment(payment["id"])
    set_clock("2026-08-03T00:00:00Z")
    returned = return_payment(payment["id"], nsf_fee_cents=3000)
    assert returned["return_count"] == 1, "return_count increases by exactly one on the return"
    assert returned["return_reason_code"] == "NSF", "The supplied reason_code is preserved on the payment"


def test_sweep_late_fee_notice_cascade_draft_demand_live_recompute(api):
    """PRD 3.7: "The `amount_demanded_cents` is a live figure while the notice remains
    in `DRAFT`, recomputed on every change to a covered charge — an allocation, a
    reversal, a waiver, or a dispute adjustment. It is the sum of the covered charges'
    outstanding balances, plus, for each covered `RENT` charge that still has a
    positive outstanding balance and does not yet have a non-`VOID` late-fee charge for
    the same period, a provisional late fee."

    Design: Difficulty/transitive_cascade/sweep_late_fee_notice_cascade_depth3
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    notice = create_notice(lease_id, [rent["id"]])
    assert notice["amount_demanded_cents"] == 204000

    # A partial payment (100000 >= 25% floor) reduces the covered charge's
    # outstanding; the DRAFT demand recomputes to outstanding + provisional fee.
    payment = record_payment(lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=100000)
    post_payment(payment["id"])
    demand = [n for n in list_notices(lease_id) if n["id"] == notice["id"]][0]["amount_demanded_cents"]
    assert demand == 104000, (
        f"DRAFT demand recomputes on every covered-charge change: 100000 outstanding + 4000 provisional, got {demand}"
    )


def test_ledger_identity_components_after_waiver(api):
    """PRD 3.2: "Its `outstanding_cents` is a computed figure — the face amount, minus
    waived cents, minus the net applied cents (the sum of `APPLY` allocations minus the
    sum of `REVERSE` allocations) — recomputed on every allocation, waiver, reversal,
    or dispute adjustment."
    PRD 3.5: "A full waiver — one whose amount equals the charge's outstanding balance
    — adds the amount to the charge's `waived_cents`, drives `outstanding_cents` to
    zero, and moves the charge to `WAIVED` from either `OPEN` or `PARTIALLY_PAID`."

    Design: Difficulty/compensating_invariant/ledger_identity_through_nsf_cycle
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    add_charge(lease_id, amount_cents=200000)

    validate_success(api.waive_charge(damage["id"], {"amount_cents": 10000, "reason": "goodwill"}, PM))

    ledger = get_ledger(lease_id)
    assert ledger["total_charged_cents"] == 210000
    assert ledger["total_waived_cents"] == 10000
    assert ledger["total_outstanding_cents"] == 200000
    assert ledger["total_applied_net_cents"] == 0
    assert_ledger_identity(ledger)
