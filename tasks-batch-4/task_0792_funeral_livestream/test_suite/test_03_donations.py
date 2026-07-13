"""Donation ledger: per-donation rounding, pledged-vs-net divergence, the
settle roll-up cascade, and the refund compensation invariant.

Queue-A instances under dual_variant_calc, combinatorial_formula (donation side),
transitive_cascade, compensating_invariant; plus the queue-B settle-idempotency
corner.
"""
from test_helpers import (
    TEST_USERS,
    validate_error, ApiErrorId,
    setup_published_memorial_order, setup_settled_donation,
    create_donation, transition_donation, get_home, get_order, get_donation,
    api_client,
)

ADMIN = TEST_USERS["admin_headers"]


def _order_with_donations(settled_grosses, pledged_grosses=()):
    """Published-memorial order; settle each gross in settled_grosses, leave
    each pledged_grosses PLEDGED. Returns (base, settled_ids)."""
    base = setup_published_memorial_order()
    settled_ids = []
    for g in settled_grosses:
        d = create_donation(base["order"]["id"], g)
        transition_donation(d["id"], "SETTLE")
        settled_ids.append(d["id"])
    for g in pledged_grosses:
        create_donation(base["order"]["id"], g)
    return base, settled_ids


# --- dual_variant_calc: pledged gross vs settled net -------------------------
def test_home_pledged_total_sums_gross_over_pledged_and_settled(api):
    """PRD §3.9: "The home's `donations_pledged_cents` is the sum of
    `gross_amount_cents` over the home's donations that are either `PLEDGED` or
    `SETTLED`, while the net totals sum only `SETTLED` donations — so the pledged
    total and the net total diverge both by the fee and by the status filter."

    Design: Difficulty/dual_variant_calc/donation_pledged_gross_vs_settled_net_diverges
    """
    base, _ = _order_with_donations([1000, 2550], pledged_grosses=[500])
    home = get_home(base["home"]["id"])
    assert home["donations_pledged_cents"] == 4050  # 1000 + 2550 + 500 (gross)


def test_home_net_total_sums_net_over_settled_only_and_diverges(api):
    """PRD §3.9: "The home's `donations_pledged_cents` is the sum of
    `gross_amount_cents` over the home's donations that are either `PLEDGED` or
    `SETTLED`, while the net totals sum only `SETTLED` donations — so the pledged
    total and the net total diverge both by the fee and by the status filter."

    Design: Difficulty/dual_variant_calc/donation_pledged_gross_vs_settled_net_diverges
    """
    base, _ = _order_with_donations([1000, 2550], pledged_grosses=[500])
    home = get_home(base["home"]["id"])
    assert home["donations_net_cents"] == 3387  # 941 + 2446 (net over SETTLED only)
    assert home["donations_pledged_cents"] != home["donations_net_cents"]


# --- combinatorial_formula: per-donation rounding before summing -------------
def test_per_donation_fee_and_net_rounded_individually(api):
    """PRD §3.9: "the per-donation `fee_cents` is the gross amount multiplied by
    2.9 percent, rounded half up to the nearest cent, plus a flat 30 cents, and
    `net_amount_cents` is the gross amount minus that fee."

    Design: Difficulty/combinatorial_formula/donation_net_rounds_per_donation_before_summing
    """
    base, settled_ids = _order_with_donations([1000, 2550])
    d1 = get_donation(settled_ids[0])
    d2 = get_donation(settled_ids[1])
    assert d1["fee_cents"] == 59 and d1["net_amount_cents"] == 941       # round(29.0)+30
    assert d2["fee_cents"] == 104 and d2["net_amount_cents"] == 2446     # round(73.95)+30


def test_order_net_is_sum_of_per_donation_nets(api):
    """PRD §2.10: "each donation's fee is rounded individually before any totals
    are summed (the system never sums gross amounts and then applies a single fee)."
    PRD §3.9: "Settlement then recomputes the order's `donations_net_cents` (the
    sum of `net_amount_cents` over that order's `SETTLED` donations)".

    Design: Difficulty/combinatorial_formula/donation_net_rounds_per_donation_before_summing
    """
    base, _ = _order_with_donations([1000, 2550])
    order = get_order(base["order"]["id"])
    assert order["donations_net_cents"] == 3387  # 941 + 2446, not sum-then-round 3417


# --- transitive_cascade: settle rolls up order then home ---------------------
def test_settle_sets_order_net_from_donation_net(api):
    """PRD §3.9: "Settlement then recomputes the order's `donations_net_cents`
    (the sum of `net_amount_cents` over that order's `SETTLED` donations), and
    that recompute cascades to the home's `donations_net_cents` (the sum over
    the home's `SETTLED` donations)."

    Design: Difficulty/transitive_cascade/settle_donation_rolls_up_order_then_home_net
    """
    base = setup_settled_donation(1000)
    assert base["donation"]["net_amount_cents"] == 941
    order = get_order(base["order"]["id"])
    assert order["donations_net_cents"] == 941


def test_settle_cascades_order_net_to_home_net(api):
    """PRD §3.9: "Settlement then recomputes the order's `donations_net_cents`
    (the sum of `net_amount_cents` over that order's `SETTLED` donations), and
    that recompute cascades to the home's `donations_net_cents` (the sum over
    the home's `SETTLED` donations)."

    Design: Difficulty/transitive_cascade/settle_donation_rolls_up_order_then_home_net
    """
    base = setup_settled_donation(1000)
    home = get_home(base["home"]["id"])
    assert home["donations_net_cents"] == 941


# --- compensating_invariant: refund restores the net ledger ------------------
def test_refund_settled_donation_marks_refunded(api):
    """PRD §3.9: "Refunding advances a donation's `status` to `REFUNDED` from
    either `PLEDGED` or `SETTLED`".

    Design: Difficulty/compensating_invariant/refund_settled_donation_restores_home_net_cents
    """
    base = setup_settled_donation(1000)
    refunded = transition_donation(base["donation"]["id"], "REFUND")
    assert refunded["status"] == "REFUNDED"


def test_refund_settled_donation_restores_order_and_home_net_to_zero(api):
    """PRD §3.9: "Refunding a donation that had already `SETTLED` is a
    compensating adjustment: its `net_amount_cents` is removed from the order's
    `donations_net_cents`, and that recompute cascades to the home's
    `donations_net_cents`, so the settled totals stay conserved."

    Design: Difficulty/compensating_invariant/refund_settled_donation_restores_home_net_cents
    """
    base = setup_settled_donation(1000)
    transition_donation(base["donation"]["id"], "REFUND")
    order = get_order(base["order"]["id"])
    home = get_home(base["home"]["id"])
    assert order["donations_net_cents"] == 0
    assert home["donations_net_cents"] == 0


# --- Queue B: settling an already-settled donation is not a no-op ------------
def test_settle_already_settled_donation_rejected(api):
    """PRD §3.9: "Settling advances a donation's `status` from `PLEDGED` to
    `SETTLED` (otherwise `ERR_DONATION_NOT_PLEDGED`)".

    Design: Corner/state_machines/settle_already_settled_donation_returns_not_pledged
    """
    base = setup_settled_donation(1000)
    resp = api.transition_donation(base["donation"]["id"], {"action": "SETTLE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DONATION_NOT_PLEDGED)
