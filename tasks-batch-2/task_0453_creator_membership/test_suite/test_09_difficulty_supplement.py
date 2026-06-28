"""Second-angle coverage for each depth (difficulty) instance.

Every difficulty instance is covered by at least two tests. This file holds the
complementary facet (boundary counterpart, opposite branch, or a distinct side
effect of the same rule) for instances whose first test lives in files 01-07.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_creator_headers,
    make_patron_headers,
    make_platform_admin_headers,
    ApiErrorId,
    set_clock,
    create_creator,
    create_published_tier,
    create_patron,
    create_active_pledge,
    create_draft_pledge,
    first_pledge_charge,
    settle_charge,
    get_pledge,
    setup_active_membership,
    setup_per_creation_membership,
    setup_creator_with_succeeded_charges,
    setup_pledge_in_grace,
    setup_lapsed_pledge_with_offer,
    setup_cancelled_lapsed_pledge,
    create_paid_post,
    publish_post,
    sweep_payout,
    open_conversation,
)

ADMIN = make_platform_admin_headers()


# ---- dual_variant_calc already has 2+2 tests (file 01 / file 02) ----


# ---- combinatorial_formula ----
def test_per_creation_single_publish_bills_full_fee_under_cap(api):
    """PRD §3.6: "The charge amount is then the smaller of the tier's
    `per_creation_fee_cents` and that remaining cap."

    Design: Difficulty/combinatorial_formula/cf_per_creation_cap_nested_min_max
    """
    s = setup_per_creation_membership(
        clock="2026-06-10T00:00:00Z", per_creation_fee_cents=500, per_creation_monthly_cap_cents=1200,
    )
    creator_id, pledge_id = s["creator"]["id"], s["pledge"]["id"]
    post = create_paid_post(creator_id, min_tier_rank=1)
    publish_post(post["id"], creator_id)

    data, _ = validate_paginated(api_client.list_charges(ADMIN, params={"pledge_id": pledge_id}))
    pc = [c for c in data if c["charge_kind"] == "PER_CREATION"]
    assert len(pc) == 1
    # min(500, 1200-0) = 500.
    assert pc[0]["gross_amount_cents"] == 500, f"Expected 500, got {pc[0]['gross_amount_cents']}"


def test_processing_fee_is_zero_when_net_is_zero(api):
    """PRD §3.7: "If the charge's `net_amount_cents` is zero — the wallet covered
    the whole gross — the `processing_fee_cents` is zero."

    Design: Difficulty/combinatorial_formula/cf_processing_fee_per_line_then_sum
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    creator_id, pledge_id = s["creator"]["id"], s["pledge"]["id"]
    # Refund the 750 initial charge so the patron's wallet holds 750.
    api_client.refund_charge(s["init_charge"]["id"], make_creator_headers(creator_id))

    # A 750 charge is fully covered by wallet → net 0.
    ch = get_success_data(api_client.create_charge(
        {"pledge_id": pledge_id, "charge_kind": "CYCLE_RENEWAL", "gross_amount_cents": 750}, ADMIN))
    assert ch["net_amount_cents"] == 0
    settled = settle_charge(ch["id"], "SUCCEEDED")
    assert settled["processing_fee_cents"] == 0, (
        f"processing fee must be 0 when net is 0, got {settled['processing_fee_cents']}"
    )


# ---- non_linear_state_machine ----
def test_reactivate_active_pledge_rejected(api):
    """PRD §3.2: "Reactivation is permitted only when both conditions hold —
    `lifecycle_status` is `CANCELLED` and `billing_status` is `LAPSED` —
    otherwise it is rejected with `ERR_PLEDGE_NOT_REACTIVATABLE`."

    Design: Difficulty/non_linear_state_machine/nlsm_pledge_reactivate_cycle
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    resp = api_client.reactivate_pledge(s["pledge"]["id"], make_patron_headers(s["patron"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PLEDGE_NOT_REACTIVATABLE.value)


def test_charge_succeeded_branch_sets_cycle_charged_and_fee(api):
    """PRD §3.5: "the processing fee is computed and stored (per §3.7); the
    pledge's `current_cycle_charged_cents` is increased by the charge's
    `gross_amount_cents`".

    Design: Difficulty/non_linear_state_machine/nlsm_charge_branching_fork_join
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT", platform_plan="STARTER")
    tier = create_published_tier(creator["id"], name="PLUS", monthly_fee_cents=1500)
    patron = create_patron()
    pledge = create_draft_pledge(patron["id"], creator["id"], tier["id"])
    charge = first_pledge_charge(pledge["id"])  # gross 750

    settled = settle_charge(charge["id"], "SUCCEEDED")
    # net 750 → fee round(750*.029)+30 = round(21.75)+30 = 52.
    assert settled["processing_fee_cents"] == 52, f"Expected 52, got {settled['processing_fee_cents']}"
    assert get_pledge(pledge["id"])["current_cycle_charged_cents"] == 750, (
        "current_cycle_charged_cents must rise by the gross on a SUCCEEDED settle"
    )


# ---- transitive_cascade ----
def test_run_cycle_does_not_lapse_grace_before_deadline(api):
    """PRD §3.3: "any pledge in `GRACE` whose `grace_deadline` is at or before
    the current clock advances on the billing axis from `GRACE` to the terminal
    `LAPSED`".

    Design: Difficulty/transitive_cascade/tc_grace_lapse_cancel_cascade
    """
    s = setup_pledge_in_grace(clock="2026-06-01T00:00:00Z", monthly_fee_cents=1500)
    assert s["pledge"]["billing_status"] == "GRACE"

    # grace_deadline = 2026-06-08; clock is still 2026-06-01 (before deadline).
    validate_success(api_client.run_billing_cycle(ADMIN), 200)

    pledge = get_pledge(s["pledge"]["id"])
    assert pledge["billing_status"] == "GRACE", (
        f"pledge must remain GRACE before its deadline, got {pledge['billing_status']}"
    )
    assert pledge["lifecycle_status"] == "ACTIVE", (
        f"pledge lifecycle must stay ACTIVE before lapse, got {pledge['lifecycle_status']}"
    )


def test_refund_decrements_current_cycle_charged(api):
    """PRD §3.5: "Refunding ... decreases the pledge's
    `current_cycle_charged_cents` by the charge's `gross_amount_cents`."

    Design: Difficulty/transitive_cascade/tc_refund_ledger_cascade
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    pledge_id = s["pledge"]["id"]
    # After settle, current_cycle_charged_cents == 750 (the initial proration gross).
    assert get_pledge(pledge_id)["current_cycle_charged_cents"] == 750

    api_client.refund_charge(s["init_charge"]["id"], make_creator_headers(s["creator"]["id"]))
    assert get_pledge(pledge_id)["current_cycle_charged_cents"] == 0, (
        "current_cycle_charged_cents must drop by the refunded gross"
    )


# ---- priority_pair_validation_conflict ----
def test_close_already_closed_conversation_rejected(api):
    """PRD §3.8: "posting to, or closing, a conversation that is already
    `CLOSED` is rejected with `ERR_CONVERSATION_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_vs_messaging_gate
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    conv = open_conversation(s["creator"]["id"], s["patron"]["id"])
    creator_headers = make_creator_headers(s["creator"]["id"])
    validate_success(api_client.close_conversation(conv["id"], creator_headers), 200)

    resp = api_client.close_conversation(conv["id"], creator_headers)
    validate_error(resp, ApiErrorId.ERR_CONVERSATION_CLOSED.value)


def test_nonexistent_post_existence_beats_gate_for_qualifying_patron(api):
    """PRD §2.6: "fourth, existence of path-supplied identifiers".
    PRD §2.5: "a post `ERR_POST_NOT_FOUND`".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_existence_vs_content_gate
    """
    # Even a high-rank patron who would pass the content gate hits the existence
    # check first when the post id is bogus.
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator()
    high = create_published_tier(creator["id"], name="HIGH", rank=9, monthly_fee_cents=2500)
    patron = create_patron()
    create_active_pledge(patron["id"], creator["id"], high["id"])

    resp = api_client.request_post_access(
        "00000000-0000-4000-8000-000000000000", {"patron_id": patron["id"]},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_POST_NOT_FOUND.value)


# ---- boundary_precision_check ----
def test_per_creation_partial_charge_just_above_cap_floor(api):
    """PRD §3.6: "First, determine the remaining cap for the pledge: it is the
    tier's `per_creation_monthly_cap_cents` minus the pledge's
    `current_cycle_charged_cents`, floored at zero so it is never negative. The
    charge amount is then the smaller of the tier's `per_creation_fee_cents` and
    that remaining cap."

    Design: Difficulty/boundary_precision_check/bpc_per_creation_cap_exact_zero
    """
    # cap 900, fee 500: first publish bills 500, second bills min(500, 400)=400.
    s = setup_per_creation_membership(
        clock="2026-06-10T00:00:00Z", per_creation_fee_cents=500, per_creation_monthly_cap_cents=900,
    )
    creator_id, pledge_id = s["creator"]["id"], s["pledge"]["id"]
    p1 = create_paid_post(creator_id, min_tier_rank=1)
    p2 = create_paid_post(creator_id, min_tier_rank=1)
    publish_post(p1["id"], creator_id)
    publish_post(p2["id"], creator_id)

    data, _ = validate_paginated(api_client.list_charges(ADMIN, params={"pledge_id": pledge_id}))
    pc = [c["gross_amount_cents"] for c in data if c["charge_kind"] == "PER_CREATION"]
    assert pc == [500, 400], f"Expected [500, 400] (second capped at remaining 400), got {pc}"
    assert get_pledge(pledge_id)["current_cycle_charged_cents"] == 900


def test_win_back_offer_redeemable_at_exact_expiry_boundary(api):
    """PRD §3.6: "An offer is redeemable only while its `status` is `OFFERED` and
    the current clock is at or before its `expires_at`."

    Design: Difficulty/boundary_precision_check/bpc_win_back_window_day_boundary
    """
    # Lapse at 2026-04-01 → expires_at = 2026-05-31; reactivate AT exactly 2026-05-31.
    s = setup_lapsed_pledge_with_offer(lapse_clock="2026-04-01T00:00:00Z", monthly_fee_cents=1500,
                                       discount_pct=0.30)
    assert s["offer"]["expires_at"].startswith("2026-05-31")

    set_clock("2026-05-31T00:00:00Z")
    resp = api_client.reactivate_pledge(s["pledge"]["id"], make_patron_headers(s["patron"]["id"]))
    data = validate_success(resp, 200)
    assert data["lifecycle_status"] == "ACTIVE"
    offer = get_success_data(api_client.get_win_back_offer(s["offer"]["id"], ADMIN))
    assert offer["status"] == "REDEEMED", f"offer at exact expiry must be redeemable, got {offer['status']}"


# ---- cross_entity_state_dependency ----
def test_conversation_open_succeeds_with_active_pledge(api):
    """PRD §3.8: "When a patron opens a conversation or sends a message, the
    patron must hold a pledge to that creator whose `lifecycle_status` is
    `ACTIVE` or `PAUSED`".
    PRD §3.8: "A `Conversation` is opened by supplying the `creator_id` and
    `patron_id`; it begins `OPEN` with `message_count` initialized to 0."

    Design: Difficulty/cross_entity_state_dependency/cesd_conversation_open_requires_active_pledge
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    resp = api_client.create_conversation(
        {"creator_id": s["creator"]["id"], "patron_id": s["patron"]["id"]},
        make_patron_headers(s["patron"]["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"
    assert data["message_count"] == 0


# ---- resource_temporal_overlap ----
def test_cancelled_pledge_frees_membership_interval(api):
    """PRD §3.2: "A `CANCELLED` pledge frees the interval, and reactivation
    reuses that same pledge row rather than creating a new one."

    Design: Difficulty/resource_temporal_overlap/rto_membership_interval_exclusivity
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    plus = create_published_tier(creator["id"], name="PLUS", rank=1, monthly_fee_cents=1500)
    basic = create_published_tier(creator["id"], name="BASIC", rank=2, monthly_fee_cents=800)
    patron = create_patron()
    first = create_active_pledge(patron["id"], creator["id"], plus["id"])
    validate_success(api_client.cancel_pledge(first["id"], make_patron_headers(patron["id"])), 200)

    # Interval now free → a fresh pledge to the same creator is accepted.
    resp = api_client.create_pledge(
        {"patron_id": patron["id"], "creator_id": creator["id"], "tier_id": basic["id"]},
        make_patron_headers(patron["id"]),
    )
    validate_success(resp, 201)


def test_retiring_tier_frees_rank_slot_for_publish(api):
    """PRD §3.1: "Once retired, the tier is no longer pledgeable, and its `rank`
    and `name` are freed for reuse by future tiers."

    Design: Difficulty/resource_temporal_overlap/rto_tier_rank_slot_occupation
    """
    creator = create_creator()
    headers = make_creator_headers(creator["id"])
    ta = get_success_data(api_client.create_tier(
        {"creator_id": creator["id"], "name": "T_A", "billing_model": "MONTHLY", "rank": 2,
         "monthly_fee_cents": 1500}, headers))
    validate_success(api_client.publish_tier(ta["id"], headers), 200)
    # Retire the occupant (no members) to free rank 2.
    validate_success(api_client.retire_tier(ta["id"], headers), 200)

    tb = get_success_data(api_client.create_tier(
        {"creator_id": creator["id"], "name": "T_B", "billing_model": "MONTHLY", "rank": 2,
         "monthly_fee_cents": 2000}, headers))
    resp = api_client.publish_tier(tb["id"], headers)
    data = validate_success(resp, 200)
    assert data["status"] == "PUBLISHED", "publishing into a freed rank slot must succeed"


# ---- compensating_invariant ----
def test_pending_payout_restored_exactly_for_single_charge(api):
    """PRD §3.7: "A reversal un-sweeps: ... the creator's `pending_payout_cents`
    is increased by the sum of the `net_amount_cents` of those charges, restoring
    the balance that the sweep had removed and keeping pending earnings conserved
    across the sweep-then-reverse pair."

    Design: Difficulty/compensating_invariant/ci_pending_payout_conserved_on_payout_reverse
    """
    s = setup_creator_with_succeeded_charges([1500], platform_plan="STARTER")
    creator_id = s["creator"]["id"]
    payout = sweep_payout(creator_id, s["cycle_anchor_date"])
    assert get_success_data(api_client.get_creator(creator_id, ADMIN))["pending_payout_cents"] == 0

    validate_success(api_client.reverse_payout(payout["id"], ADMIN), 200)
    assert get_success_data(api_client.get_creator(creator_id, ADMIN))["pending_payout_cents"] == 1500, (
        "single-charge pending must be restored to exactly its net"
    )


def test_wallet_conserved_on_partial_wallet_application_then_failure(api):
    """PRD §3.5: "the `wallet_applied_cents` is the portion of the patron's
    `wallet_credit_cents` consumed against this charge, bounded between zero and
    `gross_amount_cents`, and the `net_amount_cents` is the gross minus the
    wallet applied."
    PRD §3.5: "the `wallet_applied_cents` that had been consumed is refunded back
    into the patron's `wallet_credit_cents` so that wallet value is conserved".

    Design: Difficulty/compensating_invariant/ci_wallet_conserved_on_failed_charge
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    creator_id, patron_id, pledge_id = s["creator"]["id"], s["patron"]["id"], s["pledge"]["id"]
    # Refund initial 750 → wallet 750.
    api_client.refund_charge(s["init_charge"]["id"], make_creator_headers(creator_id))
    assert get_success_data(api_client.get_patron(patron_id, ADMIN))["wallet_credit_cents"] == 750

    # Gross 1000 only partially covered by 750 wallet → applied 750, net 250.
    ch = get_success_data(api_client.create_charge(
        {"pledge_id": pledge_id, "charge_kind": "CYCLE_RENEWAL", "gross_amount_cents": 1000}, ADMIN))
    assert ch["wallet_applied_cents"] == 750
    assert ch["net_amount_cents"] == 250

    settle_charge(ch["id"], "FAILED")
    after = get_success_data(api_client.get_patron(patron_id, ADMIN))
    assert after["wallet_credit_cents"] == 750, (
        f"wallet must be conserved (750 applied then returned), got {after['wallet_credit_cents']}"
    )
