"""Cascading effects: the run-cycle lapse chain, the refund ledger cascade,
wallet conservation on a failed charge, and scheduled offer expiry.

Covers the transitive-cascade and compensating-invariant (wallet) depth
instances plus the scheduled-actions corner instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    get_success_data,
    make_creator_headers,
    make_patron_headers,
    make_platform_admin_headers,
    set_clock,
    setup_active_membership,
    setup_pledge_in_grace,
    setup_lapsed_pledge_with_offer,
    settle_charge,
    first_pledge_charge,
    get_pledge,
)

ADMIN = make_platform_admin_headers()


def test_run_cycle_lapse_cascade_decrements_count_and_creates_offer(api):
    """PRD §3.3: "any pledge in `GRACE` whose `grace_deadline` is at or before
    the current clock advances on the billing axis from `GRACE` to the terminal
    `LAPSED`, and this triggers the same cancellation cascade as a manual cancel
    — the pledge's `lifecycle_status` is moved to `CANCELLED`, the owning tier's
    `active_pledge_count` is decremented, `lapsed_at` is set — and, in addition,
    a `WinBackOffer` is auto-created for the freshly lapsed pledge."

    Design: Difficulty/transitive_cascade/tc_grace_lapse_cancel_cascade
    """
    s = setup_pledge_in_grace(clock="2026-06-01T00:00:00Z", monthly_fee_cents=1500)
    pledge_id, tier_id = s["pledge"]["id"], s["tier"]["id"]
    assert s["pledge"]["billing_status"] == "GRACE", s["pledge"]["billing_status"]

    # grace_deadline = 2026-06-01 + 7d = 2026-06-08; advance past it.
    set_clock("2026-06-09T00:00:00Z")
    run = api_client.run_billing_cycle(ADMIN)
    validate_success(run, 200)

    pledge = get_pledge(pledge_id)
    assert pledge["billing_status"] == "LAPSED", f"link 1: billing must be LAPSED, got {pledge['billing_status']}"
    assert pledge["lifecycle_status"] == "CANCELLED", (
        f"link 2: lifecycle must be CANCELLED, got {pledge['lifecycle_status']}"
    )
    tier = get_success_data(api_client.get_tier(tier_id, ADMIN))
    assert tier["active_pledge_count"] == 0, f"link 3: count must decrement to 0, got {tier['active_pledge_count']}"

    offers, meta = validate_paginated(api_client.list_win_back_offers(ADMIN, params={"pledge_id": pledge_id}))
    offered = [o for o in offers if o["status"] == "OFFERED"]
    assert len(offered) == 1, f"link 3: one OFFERED win-back offer must be auto-created, got {len(offered)}"


def test_refund_ledger_cascade_decrements_pending_and_credits_wallet(api):
    """PRD §3.5: "Refunding returns the charge's `net_amount_cents` to the
    patron's `wallet_credit_cents`, decreases the creator's
    `pending_payout_cents` by that same `net_amount_cents` (conserving the
    pending balance), and decreases the pledge's `current_cycle_charged_cents` by
    the charge's `gross_amount_cents`."

    Design: Difficulty/transitive_cascade/tc_refund_ledger_cascade
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", platform_plan="STARTER",
                               monthly_fee_cents=1500)
    creator_id, patron_id = s["creator"]["id"], s["patron"]["id"]
    charge_id = s["init_charge"]["id"]  # net 750, SUCCEEDED in setup

    before = get_success_data(api_client.get_creator(creator_id, ADMIN))
    assert before["pending_payout_cents"] == 750

    refund = api_client.refund_charge(charge_id, make_creator_headers(creator_id))
    refunded = validate_success(refund, 200)
    assert refunded["status"] == "REFUNDED", refunded["status"]

    after = get_success_data(api_client.get_creator(creator_id, ADMIN))
    assert after["pending_payout_cents"] == 0, f"pending must drop by net to 0, got {after['pending_payout_cents']}"
    patron = get_success_data(api_client.get_patron(patron_id, ADMIN))
    assert patron["wallet_credit_cents"] == 750, (
        f"net must be returned to wallet, got {patron['wallet_credit_cents']}"
    )


def test_wallet_conserved_across_apply_then_failed_charge(api):
    """PRD §3.5: "the `wallet_applied_cents` is the portion of the patron's
    `wallet_credit_cents` consumed against this charge, bounded between zero and
    `gross_amount_cents`, and the `net_amount_cents` is the gross minus the
    wallet applied."
    PRD §3.5: "When the outcome is failure, the charge moves from `PENDING` to
    `FAILED`, the `wallet_applied_cents` that had been consumed is refunded back
    into the patron's `wallet_credit_cents` so that wallet value is conserved".

    Design: Difficulty/compensating_invariant/ci_wallet_conserved_on_failed_charge
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    creator_id, patron_id, pledge_id = s["creator"]["id"], s["patron"]["id"], s["pledge"]["id"]

    # Refund the initial 750 net charge → wallet_credit_cents becomes 750.
    api_client.refund_charge(s["init_charge"]["id"], make_creator_headers(creator_id))
    assert get_success_data(api_client.get_patron(patron_id, ADMIN))["wallet_credit_cents"] == 750

    # A new 750 charge fully consumes wallet (wallet_applied=750, net=0).
    ch2 = get_success_data(api_client.create_charge(
        {"pledge_id": pledge_id, "charge_kind": "CYCLE_RENEWAL", "gross_amount_cents": 750}, ADMIN))
    assert ch2["wallet_applied_cents"] == 750, f"wallet should fully apply, got {ch2['wallet_applied_cents']}"
    assert ch2["net_amount_cents"] == 0, f"net should be 0, got {ch2['net_amount_cents']}"

    # The charge FAILS → wallet_applied returned, wallet conserved at 750.
    settle_charge(ch2["id"], "FAILED")
    after = get_success_data(api_client.get_patron(patron_id, ADMIN))
    assert after["wallet_credit_cents"] == 750, (
        f"wallet must be conserved (750 consumed then 750 returned), got {after['wallet_credit_cents']}"
    )


def test_run_cycle_expires_offer_past_window(api):
    """PRD §3.3: "any `WinBackOffer` still in `OFFERED` whose `expires_at` is now
    in the past — that is, the current clock has moved beyond `expires_at` —
    advances to the terminal `EXPIRED` and can no longer be redeemed."

    Design: Corner/cross_cutting_complexity_layers/scheduled_offer_expires_on_run_cycle
    """
    # Lapse on 2026-04-01 → offer expires_at = 2026-05-31; advance to 2026-06-02.
    s = setup_lapsed_pledge_with_offer(lapse_clock="2026-04-01T00:00:00Z", monthly_fee_cents=1500,
                                       discount_pct=0.30)
    set_clock("2026-06-02T00:00:00Z")

    run = api_client.run_billing_cycle(ADMIN)
    data = validate_success(run, 200)
    assert s["offer"]["id"] in data["expired_offer_ids"], (
        f"offer {s['offer']['id']} must be reported in expired_offer_ids"
    )

    offer = get_success_data(api_client.get_win_back_offer(s["offer"]["id"], ADMIN))
    assert offer["status"] == "EXPIRED", f"offer must be EXPIRED, got {offer['status']}"
