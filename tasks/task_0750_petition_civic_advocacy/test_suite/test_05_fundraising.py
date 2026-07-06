"""Campaign dual-variant tallies, the pinned fee split, refund conservation, and the
withdrawal closure-refund cascade.

Queue-A depth: campaign_funds_gross_vs_net, donation_fee_rounding_order_mode_b,
withdrawal_closure_refund_chain_depth3, campaign_funds_conserved_on_refund.
Queue-B breadth: donate_to_suspended_campaign.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    register_member, publish_petition,
    setup_campaign, create_campaign, donate, settle_donation, refund_donation,
    TEST_USERS, make_member_headers,
)

MODERATOR = TEST_USERS["moderator_headers"]
GUEST = TEST_USERS["guest_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ── dual_variant_calc / campaign_funds_gross_vs_net ──────────────────────────
def _campaign_one_settled_one_pending(api):
    ctx = setup_campaign(goal=10, campaign_goal_cents=100000)
    donor = register_member()
    d1 = donate(ctx["campaign_id"], donor["id"], 10000)
    settle_donation(d1["id"])
    donate(ctx["campaign_id"], donor["id"], 10000)   # D2 left PENDING
    return ctx


def test_gross_pledged_includes_pending_donation_at_full_amount(api):
    """PRD §2.7: "On a campaign, the provisional figure is gross_pledged_cents, the sum of
    amount_cents across every donation whose status is PENDING or SETTLED, taken at full
    gross with no fee deducted; it powers the optimistic progress bar."

    Design: Difficulty/dual_variant_calc/campaign_funds_gross_vs_net
    """
    ctx = _campaign_one_settled_one_pending(api)
    camp = get_success_data(api.get_campaign(ctx["campaign_id"], GUEST))
    assert camp["gross_pledged_cents"] == 20000


def test_funds_raised_reflects_only_settled_net(api):
    """PRD §2.7: "The official figure is funds_raised_cents, the withdrawable balance: the
    sum of net_to_campaign_cents over SETTLED donations minus the sum of
    net_to_campaign_cents over REFUNDED donations."
    PRD §3.6: "the platform_fee_cents is the donation's amount_cents multiplied by the
    platform fee rate of 2.9 percent (0.029), rounded half-up to whole cents, plus a fixed
    fee of 30 cents; the net_to_campaign_cents is the amount_cents minus that
    platform_fee_cents."

    Design: Difficulty/dual_variant_calc/campaign_funds_gross_vs_net
    """
    ctx = _campaign_one_settled_one_pending(api)
    camp = get_success_data(api.get_campaign(ctx["campaign_id"], GUEST))
    assert camp["funds_raised_cents"] == 9680


# ── combinatorial_formula / donation_fee_rounding_order_mode_b ───────────────
def _campaign_two_settled_small(api):
    ctx = setup_campaign(goal=10, campaign_goal_cents=50000)
    donor = register_member()
    d1 = donate(ctx["campaign_id"], donor["id"], 3450)
    d2 = donate(ctx["campaign_id"], donor["id"], 3455)
    settle_donation(d1["id"])
    settle_donation(d2["id"])
    ctx["d1_id"], ctx["d2_id"] = d1["id"], d2["id"]
    return ctx


def test_per_donation_fee_rounded_individually(api):
    """PRD §3.6: "the platform_fee_cents is the donation's amount_cents multiplied by the
    platform fee rate of 2.9 percent (0.029), rounded half-up to whole cents, plus a fixed
    fee of 30 cents; the net_to_campaign_cents is the amount_cents minus that
    platform_fee_cents."

    Design: Difficulty/combinatorial_formula/donation_fee_rounding_order_mode_b
    """
    ctx = _campaign_two_settled_small(api)
    d1 = get_success_data(api.get_donation(ctx["d1_id"], GUEST))
    d2 = get_success_data(api.get_donation(ctx["d2_id"], GUEST))
    assert d1["platform_fee_cents"] == 130
    assert d2["platform_fee_cents"] == 130


def test_campaign_net_sums_already_rounded_per_donation_nets(api):
    """PRD §3.6: "The roll-up order is pinned: the campaign total is the sum of the
    already-rounded per-donation nets, not the fee applied once to a summed gross —
    rounding each donation's fee first and then summing yields different cents than
    summing first and rounding once, and the former is required."

    Design: Difficulty/combinatorial_formula/donation_fee_rounding_order_mode_b
    """
    ctx = _campaign_two_settled_small(api)
    camp = get_success_data(api.get_campaign(ctx["campaign_id"], GUEST))
    assert camp["funds_raised_cents"] == 6645


# ── transitive_cascade / withdrawal_closure_refund_chain_depth3 ──────────────
def _published_petition_with_campaign_donations(api):
    ctx = publish_petition(goal=10)
    campaign = create_campaign(ctx["petition_id"], ctx["author_id"], goal_cents=100000)
    donor = register_member()
    d1 = donate(campaign["id"], donor["id"], 10000)
    settle_donation(d1["id"])                      # funds 9680
    d2 = donate(campaign["id"], donor["id"], 5000)  # PENDING
    ctx["campaign_id"] = campaign["id"]
    ctx["d1_id"], ctx["d2_id"] = d1["id"], d2["id"]
    return ctx


def test_withdrawal_closes_petition_and_campaign(api):
    """PRD §3.8: "Declaring withdrawal moves the petition from PUBLISHED to CLOSED_WITHDRAWN
    with no support preconditions."
    PRD §3.8: "The first link moves that `Campaign` — whether it was `ACTIVE` or `SUSPENDED` —
    to `CLOSED`."

    Design: Difficulty/transitive_cascade/withdrawal_closure_refund_chain_depth3
    """
    ctx = _published_petition_with_campaign_donations(api)
    closed = validate_success(api.close_petition(
        ctx["petition_id"], {"outcome": "WITHDRAWN"}, make_member_headers(ctx["author_id"])))
    assert closed["status"] == "CLOSED_WITHDRAWN"
    camp = get_success_data(api.get_campaign(ctx["campaign_id"], GUEST))
    assert camp["status"] == "CLOSED"


def test_withdrawal_refunds_pending_donation_and_conserves_settled_funds(api):
    """PRD §3.8: "The second link, fired by the campaign closing, moves every PENDING
    Donation on that campaign to REFUNDED. The third link reconciles the campaign's
    funds_raised_cents: a donation that was only pending never contributed settled net to
    the official total, so voiding it leaves funds_raised_cents unchanged, while any
    donation refunded from a settled state reverses its own net_to_campaign_cents exactly."

    Design: Difficulty/transitive_cascade/withdrawal_closure_refund_chain_depth3
    """
    ctx = _published_petition_with_campaign_donations(api)
    api.close_petition(ctx["petition_id"], {"outcome": "WITHDRAWN"},
                       make_member_headers(ctx["author_id"]))
    d1 = get_success_data(api.get_donation(ctx["d1_id"], GUEST))
    d2 = get_success_data(api.get_donation(ctx["d2_id"], GUEST))
    camp = get_success_data(api.get_campaign(ctx["campaign_id"], GUEST))
    assert d2["status"] == "REFUNDED"
    assert d1["status"] == "SETTLED"
    assert camp["funds_raised_cents"] == 9680


# ── compensating_invariant / campaign_funds_conserved_on_refund ──────────────
def test_refund_of_settled_donation_marks_it_refunded(api):
    """PRD §3.6: "Refunding a `SETTLED` donation moves it to `REFUNDED` and applies the
    compensating reversal: the campaign's `funds_raised_cents` decreases by exactly that
    donation's `net_to_campaign_cents`."

    Design: Difficulty/compensating_invariant/campaign_funds_conserved_on_refund
    """
    ctx = setup_campaign(goal=10, campaign_goal_cents=50000)
    donor = register_member()
    don = donate(ctx["campaign_id"], donor["id"], 5000)
    settle_donation(don["id"])
    refunded = validate_success(api.transition_donation(
        don["id"], {"to_status": "REFUNDED"}, ADMIN))
    assert refunded["status"] == "REFUNDED"


def test_refund_reverses_net_back_to_zero(api):
    """PRD §3.6: "Refunding a `SETTLED` donation moves it to `REFUNDED` and applies the
    compensating reversal: the campaign's `funds_raised_cents` decreases by exactly that
    donation's `net_to_campaign_cents`."

    Design: Difficulty/compensating_invariant/campaign_funds_conserved_on_refund
    """
    ctx = setup_campaign(goal=10, campaign_goal_cents=50000)
    donor = register_member()
    don = donate(ctx["campaign_id"], donor["id"], 5000)
    settle_donation(don["id"])                     # funds 4825
    refund_donation(don["id"])
    camp = get_success_data(api.get_campaign(ctx["campaign_id"], GUEST))
    assert camp["funds_raised_cents"] == 0


# ── Corner instances ─────────────────────────────────────────────────────────
def test_donate_to_suspended_campaign_rejected(api):
    """PRD §3.6: "Donations are accepted only while the campaign's status is ACTIVE; a
    donation attempted against a `SUSPENDED` or `CLOSED` campaign is rejected with
    `ERR_CAMPAIGN_SUSPENDED`."

    Design: Corner/validations/donate_to_suspended_campaign
    """
    ctx = setup_campaign(goal=10, campaign_goal_cents=10000)
    api.moderate_campaign(ctx["campaign_id"], {"action": "SUSPEND"}, MODERATOR)
    donor = register_member()
    resp = api.create_donation(
        ctx["campaign_id"], {"amount_cents": 2000}, make_member_headers(donor["id"]))
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_SUSPENDED.value, expected_status=409)
