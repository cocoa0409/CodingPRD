"""Move-out cascade (Cascade B), the two reconciliation balance variants, and
the collections-referral lifecycle including the re-referral cycle."""
from test_helpers import (
    ApiErrorId,
    add_charge,
    create_notice,
    create_plan,
    file_dispute,
    get_ledger,
    list_charges,
    list_referrals,
    move_out_lease,
    record_and_post_payment,
    resolve_dispute,
    return_payment,
    set_clock,
    setup_ended_lease_with_referral,
    setup_property_tenant_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def test_moveout_forward_vs_chronological_balance(api):
    """PRD 3.9: "The forward-looking variant is the sum of outstanding balances over
    the lease's `OPEN` and `PARTIALLY_PAID` charges, counting every open charge at face
    value, including charges due after the move-out date — an acceleration view of what
    is owed. The chronological variant answers a different question — what was actually
    due by the move-out date — and computes it as follows. Charges whose `due_date`
    lies after the move-out date contribute nothing. Any other charge due on or before
    the move-out date contributes its outstanding balance, with one exception: a `RENT`
    charge whose period straddles the move-out — its `period_start_date` on or before
    the move-out date and the move-out date strictly before its `period_end_date` —
    contributes a prorated amount instead."
    PRD 3.9: "A referral's `referred_balance_cents` always uses the chronological
    variant, and it is recomputed whenever a charge on the lease changes while the
    referral remains `PENDING`."

    Design: Difficulty/dual_variant_calc/moveout_forward_vs_chronological_balance
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    add_charge(
        lease_id, amount_cents=200000,
        period_start_date="2026-09-01", period_end_date="2026-09-30", due_date="2026-09-01",
    )
    set_clock("2026-08-20T00:00:00Z")
    move_out_lease(lease_id, "2026-08-20")

    ledger = get_ledger(lease_id)
    assert ledger["forward_balance_cents"] == 400000, (
        f"Forward variant counts both charges at face value: expected 400000, got {ledger['forward_balance_cents']}"
    )
    # chronological: September charge excluded; August prorated round_half_up(200000 * 19 / 31) = 122581
    assert ledger["chronological_balance_cents"] == 122581, (
        f"Chronological variant must prorate the straddling August charge to 122581, got {ledger['chronological_balance_cents']}"
    )

    referrals = list_referrals(lease_id)
    assert len(referrals) == 1
    assert referrals[0]["referred_balance_cents"] == 122581
    assert referrals[0]["status"] == "PENDING"


def test_moveout_zero_balance_creates_no_referral(api):
    """PRD 3.9: "The transition fires Cascade B: the lease moves from `ACTIVE` to
    `ENDED` and records the `move_out_date`; every `DRAFT` notice on the lease is
    cancelled with `cancel_reason` `MOVE_OUT`; every plan in `DRAFT` or `ACTIVE` is
    cancelled with `cancel_reason` `MOVE_OUT`; and a move-out reconciliation is
    computed whose chronological balance, when greater than zero, produces a `PENDING`
    collections referral carrying that balance as its `referred_balance_cents` — while
    a zero balance produces no referral at all."

    Design: Difficulty/dual_variant_calc/moveout_forward_vs_chronological_balance
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, amount_cents=200000)
    record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)

    set_clock("2026-08-20T00:00:00Z")
    move_out_lease(lease_id, "2026-08-20")

    referrals = list_referrals(lease_id)
    assert referrals == [], "A paid ledger nets to zero, so no referral may be created at move-out"


def test_move_out_cancels_draft_notice_and_plan(api):
    """PRD 3.9: "The transition fires Cascade B: the lease moves from `ACTIVE` to
    `ENDED` and records the `move_out_date`; every `DRAFT` notice on the lease is
    cancelled with `cancel_reason` `MOVE_OUT`; every plan in `DRAFT` or `ACTIVE` is
    cancelled with `cancel_reason` `MOVE_OUT`; and a move-out reconciliation is
    computed whose chronological balance, when greater than zero, produces a `PENDING`
    collections referral carrying that balance as its `referred_balance_cents` — while
    a zero balance produces no referral at all."
    PRD 3.7: "Issuance is a `PropertyManager` act that moves the notice from `DRAFT`
    to `ISSUED`; issuing from any other status is rejected with
    `ERR_NOTICE_INVALID_TRANSITION`."

    Design: Corner/state_machines/move_out_cancels_draft_notice_and_plan
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    notice = create_notice(lease_id, [rent["id"]])
    plan = create_plan(lease_id, [damage["id"]])

    set_clock("2026-08-20T00:00:00Z")
    lease = move_out_lease(lease_id, "2026-08-20")
    assert lease["status"] == "ENDED"

    from test_helpers import list_notices, get_plan
    notice_after = [n for n in list_notices(lease_id) if n["id"] == notice["id"]][0]
    assert notice_after["status"] == "CANCELLED"
    assert notice_after["cancel_reason"] == "MOVE_OUT"

    plan_after = get_plan(plan["id"])
    assert plan_after["status"] == "CANCELLED"
    assert plan_after["cancel_reason"] == "MOVE_OUT"

    response = api.transition_notice(notice["id"], {"action": "ISSUE"}, PM)
    validate_error(response, ApiErrorId.ERR_NOTICE_INVALID_TRANSITION)

    # Chronological balance: straddling August rent prorated to 122581 + damage 10000.
    referrals = list_referrals(lease_id)
    assert referrals[0]["referred_balance_cents"] == 132581


def test_lease_ended_terminal_lockdown(api):
    """PRD 3.9: "Requesting move-out while the lease is still in `DRAFT` is rejected
    with `ERR_LEASE_NOT_ACTIVE`; requesting it on an already-ended lease is rejected
    with `ERR_LEASE_ALREADY_ENDED`."
    PRD 3.1: "Requesting activation on a lease that is no longer in `DRAFT` is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/lease_ended_terminal_lockdown
    """
    from test_helpers import create_lease
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=15000)
    lease2 = create_lease(ctx["property"]["id"], ctx["tenant"]["id"], unit_label="102", activate=True)

    set_clock("2026-08-20T00:00:00Z")
    ended = move_out_lease(lease_id, "2026-08-20")
    assert ended["status"] == "ENDED"

    response = api.transition_lease(lease_id, {"action": "MOVE_OUT", "move_out_date": "2026-08-20"}, PM)
    validate_error(response, ApiErrorId.ERR_LEASE_ALREADY_ENDED)

    response2 = api.transition_lease(lease2["id"], {"action": "ACTIVATE"}, PM)
    validate_error(response2, ApiErrorId.ERR_INVALID_REQUEST)


def test_referral_threshold_equality(api):
    """PRD 3.9: "A `PropertyManager` refers a `PENDING` referral by naming the
    `agency_name`; two gates guard the act — no dispute on the lease may be `OPEN` or
    `REOPENED` (`ERR_BLOCKING_DISPUTE`), and the referred balance must be at least the
    property's `collections_threshold_cents`, with a balance exactly equal to the
    threshold qualifying (`ERR_REFERRAL_THRESHOLD_NOT_MET`)."

    Design: Difficulty/boundary_precision_check/referral_threshold_equality
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=10000)
    ref_at_threshold = ctx["referrals"][0]
    referred = validate_success(
        api.transition_referral(ref_at_threshold["id"], {"action": "REFER", "agency_name": "Agency One"}, PM)
    )
    assert referred["status"] == "REFERRED", "A balance exactly equal to the threshold qualifies"


def test_referral_threshold_one_cent_below_rejected(api):
    """PRD 3.9: "A `PropertyManager` refers a `PENDING` referral by naming the
    `agency_name`; two gates guard the act — no dispute on the lease may be `OPEN` or
    `REOPENED` (`ERR_BLOCKING_DISPUTE`), and the referred balance must be at least the
    property's `collections_threshold_cents`, with a balance exactly equal to the
    threshold qualifying (`ERR_REFERRAL_THRESHOLD_NOT_MET`)."

    Design: Difficulty/boundary_precision_check/referral_threshold_equality
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=9999)
    ref_below = ctx["referrals"][0]
    response = api.transition_referral(ref_below["id"], {"action": "REFER", "agency_name": "Agency One"}, PM)
    validate_error(response, ApiErrorId.ERR_REFERRAL_THRESHOLD_NOT_MET)


def test_referral_blocked_by_open_dispute(api):
    """PRD 2.9 rule 14: "A plan may not be approved while any notice on the lease is
    `SERVED` (`ERR_ACTIVE_NOTICE_BLOCKS_PLAN`); a referral may not proceed while any
    dispute on the lease is `OPEN` or `REOPENED` (`ERR_BLOCKING_DISPUTE`)."

    Design: Difficulty/cross_entity_state_dependency/referral_blocked_by_open_dispute
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=15000)
    lease_id = ctx["lease"]["id"]
    ref = ctx["referrals"][0]
    dispute = file_dispute(lease_id, ctx["charge"]["id"], ctx["tenant"]["id"], reason="charge contested")

    response = api.transition_referral(ref["id"], {"action": "REFER", "agency_name": "Agency One"}, PM)
    validate_error(response, ApiErrorId.ERR_BLOCKING_DISPUTE)

    resolve_dispute(dispute["id"], outcome="UPHELD")
    referred = validate_success(
        api.transition_referral(ref["id"], {"action": "REFER", "agency_name": "Agency One"}, PM)
    )
    assert referred["status"] == "REFERRED"


def test_referral_referred_recalled_referred_cycle(api):
    """PRD 3.9: "From `REFERRED`, the referral may be settled — moving to the terminal
    `SETTLED` — or recalled with an operator-supplied `recall_reason`, moving to
    `RECALLED`. A recalled referral is not dead: it may be referred again under the
    same two gates, refreshing `referred_date` and `agency_name`, completing the cycle
    `REFERRED` → `RECALLED` → `REFERRED`."

    Design: Difficulty/non_linear_state_machine/referral_referred_recalled_referred_cycle
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=150000)
    ref = ctx["referrals"][0]

    r1 = validate_success(api.transition_referral(ref["id"], {"action": "REFER", "agency_name": "Agency One"}, PM))
    assert r1["status"] == "REFERRED"

    r2 = validate_success(
        api.transition_referral(ref["id"], {"action": "RECALL", "recall_reason": "debtor contacted office"}, PM)
    )
    assert r2["status"] == "RECALLED"

    r3 = validate_success(api.transition_referral(ref["id"], {"action": "REFER", "agency_name": "Agency Two"}, PM))
    assert r3["status"] == "REFERRED"
    assert r3["agency_name"] == "Agency Two", "Re-referral refreshes agency_name"
    assert r3["referred_date"] == "2026-08-20", "Re-referral re-stamps referred_date with the current date"
    assert r3["referred_balance_cents"] == 150000


def test_referral_settle_from_pending_rejected(api):
    """PRD 3.9: "Any transition not permitted from the referral's current status —
    settling while still `PENDING`, or referring an already-`REFERRED` referral — is
    rejected with `ERR_REFERRAL_INVALID_TRANSITION`."

    Design: Corner/state_machines/referral_settle_from_pending_rejected
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=15000)
    ref = ctx["referrals"][0]
    assert ref["status"] == "PENDING"

    response = api.transition_referral(ref["id"], {"action": "SETTLE"}, PM)
    validate_error(response, ApiErrorId.ERR_REFERRAL_INVALID_TRANSITION)


def test_nsf_after_moveout_creates_pending_referral(api):
    """PRD 3.4: "Because a bank return can arrive after a resident has moved out, the
    lease may be either `ACTIVE` or `ENDED` at return time; attempting the return on a
    payment that is not currently `POSTED` is rejected with
    `ERR_PAYMENT_INVALID_TRANSITION`."
    PRD 3.4: "Finally, any `PENDING` collections referral on the lease recomputes its
    referred balance; and if the lease is already `ENDED`, has no collections referral
    at all, and the reversal leaves the chronological move-out balance greater than
    zero, a new `PENDING` referral carrying that balance is created on the spot."

    Design: Corner/cross_cutting_layers/nsf_after_moveout_creates_pending_referral
    """
    ctx = setup_property_tenant_lease()
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=200000)

    set_clock("2026-08-20T00:00:00Z")
    move_out_lease(lease_id, "2026-08-20")
    assert list_referrals(lease_id) == [], "A paid ledger yields no referral at move-out"

    set_clock("2026-08-21T00:00:00Z")
    returned = return_payment(payment["id"], nsf_fee_cents=3000)
    assert returned["status"] == "RETURNED", "A return is legal on an ENDED lease"

    referrals = list_referrals(lease_id)
    assert len(referrals) == 1
    assert referrals[0]["status"] == "PENDING"
    assert referrals[0]["referred_balance_cents"] == 122581, (
        "Chronological balance after the reversal: prorated August rent 122581; the 3000 NSF fee "
        "due 2026-08-21 is after the 2026-08-20 move-out and contributes nothing"
    )

    rent_after = [c for c in list_charges(lease_id) if c["id"] == rent["id"]][0]
    assert rent_after["status"] == "OPEN"
    assert rent_after["outstanding_cents"] == 200000


def test_referral_cycle_refer_from_referred_rejected(api):
    """PRD 3.9: "Any transition not permitted from the referral's current status —
    settling while still `PENDING`, or referring an already-`REFERRED` referral — is
    rejected with `ERR_REFERRAL_INVALID_TRANSITION`."
    PRD 3.9: "A recalled referral is not dead: it may be referred again under the same
    two gates, refreshing `referred_date` and `agency_name`, completing the cycle
    `REFERRED` → `RECALLED` → `REFERRED`."

    Design: Difficulty/non_linear_state_machine/referral_referred_recalled_referred_cycle
    """
    ctx = setup_ended_lease_with_referral(charge_amount_cents=150000)
    ref = ctx["referrals"][0]

    validate_success(api.transition_referral(ref["id"], {"action": "REFER", "agency_name": "Agency One"}, PM))
    # Re-referral is only legal from RECALLED: REFER from REFERRED is rejected.
    response = api.transition_referral(ref["id"], {"action": "REFER", "agency_name": "Agency Two"}, PM)
    validate_error(response, ApiErrorId.ERR_REFERRAL_INVALID_TRANSITION)


def test_referral_blocked_by_reopened_dispute(api):
    """PRD 2.9 rule 14: "A plan may not be approved while any notice on the lease is
    `SERVED` (`ERR_ACTIVE_NOTICE_BLOCKS_PLAN`); a referral may not proceed while any
    dispute on the lease is `OPEN` or `REOPENED` (`ERR_BLOCKING_DISPUTE`)."

    Design: Difficulty/cross_entity_state_dependency/referral_blocked_by_open_dispute
    """
    from test_helpers import reopen_dispute
    ctx = setup_ended_lease_with_referral(charge_amount_cents=15000)
    lease_id = ctx["lease"]["id"]
    ref = ctx["referrals"][0]
    dispute = file_dispute(lease_id, ctx["charge"]["id"], ctx["tenant"]["id"], reason="charge contested")
    resolve_dispute(dispute["id"], outcome="UPHELD")
    reopen_dispute(dispute["id"], ctx["tenant"]["id"])

    # A REOPENED dispute blocks REFER exactly as an OPEN one does.
    response = api.transition_referral(ref["id"], {"action": "REFER", "agency_name": "Agency One"}, PM)
    validate_error(response, ApiErrorId.ERR_BLOCKING_DISPUTE)
