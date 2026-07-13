"""Settle / dispute / re-settle: cascades, money conservation, precondition errors."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_mill, create_shipment, settle_shipment, dispute_shipment,
    get_municipality, setup_shipped_single_bale, setup_settled_single_bale,
    setup_two_window_shipped_bale,
)

TRADER = TEST_USERS["commodity_trader_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


# --- Difficulty: settle cascade bale -> posting -> municipality balance -------

def test_settle_sets_final_value_and_municipality_balance(api):
    """PRD §3.7: "the per-bale share is that bale's `final_value_cents` multiplied
    by the municipality's `revenue_share_pct`, rounded half up to whole cents."
    PRD §3.7: "the posting raises the municipality's `revenue_share_accrued_cents`,
    re-derives `balance_cents`, and increments the municipality's `version`."

    Design: Difficulty/transitive_cascade/settle_cascade_bale_to_posting_to_municipality_balance
    """
    ctx = setup_two_window_shipped_bale(api, revenue_share_pct=0.60,
                                        freight_cost_cents=5000)
    settle_shipment(api, ctx["ship_id"])
    bale = validate_success(api.get_bale(ctx["bale_id"], TRADER))
    assert bale["final_value_cents"] == 80500
    muni = get_municipality(api, ctx["m_id"])
    assert muni["revenue_share_accrued_cents"] == 48300
    assert muni["balance_cents"] == 48300


def test_settle_writes_revenue_share_posting(api):
    """PRD §3.7: "That share is written as a `REVENUE_SHARE` posting whose
    `amount_cents` credits the municipality; the posting raises the municipality's
    `revenue_share_accrued_cents`, re-derives `balance_cents`, and increments the
    municipality's `version`."

    Design: Difficulty/transitive_cascade/settle_cascade_bale_to_posting_to_municipality_balance
    """
    ctx = setup_two_window_shipped_bale(api, revenue_share_pct=0.60,
                                        freight_cost_cents=5000)
    settle_shipment(api, ctx["ship_id"])
    data, meta = validate_paginated(
        api.list_revenue_postings(CLERK, params={"municipality_id": ctx["m_id"]}))
    rs = [p for p in data if p["posting_type"] == "REVENUE_SHARE"]
    assert len(rs) == 1
    assert rs[0]["amount_cents"] == 48300


# --- Difficulty: dispute reverses revenue share, conserving balance ----------

def test_settle_posts_revenue_share_to_balance(api):
    """PRD §3.7: "the per-bale share is that bale's `final_value_cents` multiplied
    by the municipality's `revenue_share_pct`, rounded half up to whole cents."
    PRD §2.6: "`balance_cents`, is derived as `revenue_share_accrued_cents` plus
    `lifetime_rebate_cents` minus `lifetime_penalty_cents`."

    Design: Difficulty/compensating_invariant/dispute_reverses_revenue_share_conserving_balance
    """
    # Closing this single-bale load (residual 0 -> 0% contamination) posts a clean
    # REBATE of net_tons(10)*300 = 3000 cents per PRD §3.5, so the derived balance
    # is that rebate plus the revenue share (71000 * 0.60 = 42600) per PRD §2.6.
    ctx = setup_settled_single_bale(api, index_price_cents_per_ton=8000,
                                    revenue_share_pct=0.60, bale_net_tons=10,
                                    moisture_pct=5, quality_grade="A",
                                    freight_cost_cents=5000)
    muni = get_municipality(api, ctx["m_id"])
    assert muni["revenue_share_accrued_cents"] == 42600
    assert muni["balance_cents"] == 45600


def test_dispute_reverses_revenue_share_to_zero(api):
    """PRD §3.7: "For every `REVENUE_SHARE` posting produced for such a bale that
    has not already been reversed, a `REVERSAL` posting is written whose
    `amount_cents` is the negation of the original, and the original's `reversed`
    flag is set true; the municipality's `revenue_share_accrued_cents` and
    `balance_cents` are thereby restored to their pre-settlement values (money
    conservation), and its `version` advances."

    Design: Difficulty/compensating_invariant/dispute_reverses_revenue_share_conserving_balance
    """
    ctx = setup_settled_single_bale(api, index_price_cents_per_ton=8000,
                                    revenue_share_pct=0.60, bale_net_tons=10,
                                    moisture_pct=5, quality_grade="A",
                                    freight_cost_cents=5000)
    dispute_shipment(api, ctx["ship_id"], reason="quality reject")
    muni = get_municipality(api, ctx["m_id"])
    # The REVERSAL restores revenue_share_accrued to its pre-settlement 0; the
    # clean-close REBATE (3000) was posted before settlement and is not reversed,
    # so balance is restored to its pre-settlement value of 3000 per PRD §2.6/§3.7.
    assert muni["revenue_share_accrued_cents"] == 0
    assert muni["balance_cents"] == 3000


# --- Difficulty: dispute then re-settle cycle -------------------------------

def test_resettle_after_dispute_returns_shipment_to_settled(api):
    """PRD §3.7: "A disputed shipment can be settled again, recomputing final
    values, re-posting revenue share, and recomputing `gross_settlement_cents`,
    returning it to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/mill_shipment_dispute_resettle_cycle
    """
    ctx = setup_settled_single_bale(api, index_price_cents_per_ton=8000,
                                    revenue_share_pct=0.60, bale_net_tons=10,
                                    moisture_pct=0, quality_grade="A",
                                    freight_cost_cents=0)
    dispute_shipment(api, ctx["ship_id"], reason="weight dispute")
    ship = settle_shipment(api, ctx["ship_id"])
    assert ship["status"] == "SETTLED"


def test_resettle_after_dispute_returns_bale_to_settled(api):
    """PRD §3.7: "It moves the shipment from `SETTLED` to `DISPUTED` and carries
    each `SETTLED` bale back to `SHIPPED`."
    PRD §3.7: "A disputed shipment can be settled again, recomputing final values,
    re-posting revenue share, and recomputing `gross_settlement_cents`, returning it
    to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/mill_shipment_dispute_resettle_cycle
    """
    ctx = setup_settled_single_bale(api, index_price_cents_per_ton=8000,
                                    revenue_share_pct=0.60, bale_net_tons=10,
                                    moisture_pct=0, quality_grade="A",
                                    freight_cost_cents=0)
    dispute_shipment(api, ctx["ship_id"], reason="weight dispute")
    settle_shipment(api, ctx["ship_id"])
    bale = validate_success(api.get_bale(ctx["bale_id"], TRADER))
    assert bale["status"] == "SETTLED"


# --- Difficulty: settle requires a published index at the settle-time clock ---

def test_settle_without_in_force_index_rejected(api):
    """PRD §3.7: "Settlement further requires that an index be in force for the
    shipment's `commodity` at the current clock; if none is, the settle is refused
    with `ERR_NO_PUBLISHED_INDEX`."

    Design: Difficulty/cross_entity_state_dependency/settle_requires_published_index_at_clock
    """
    ctx = setup_shipped_single_bale(
        api, index_price_cents_per_ton=8000, revenue_share_pct=0.60,
        bale_net_tons=10, moisture_pct=0, quality_grade="A", freight_cost_cents=0,
        index_start="2026-03-01T00:00:00Z", index_end="2026-03-15T00:00:00Z")
    set_clock(api, "2026-03-20T00:00:00Z")  # outside the only window
    resp = api.settle_mill_shipment(ctx["ship_id"], TRADER)
    validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_INDEX.value)


def test_settle_with_in_force_index_succeeds(api):
    """PRD §3.7: "Settlement further requires that an index be in force for the
    shipment's `commodity` at the current clock; if none is, the settle is refused
    with `ERR_NO_PUBLISHED_INDEX`."
    PRD §2.9: "An index is "in force for a commodity at an instant" when the index
    is `PUBLISHED`, its `commodity` matches, and the instant falls at or after
    `effective_start` and strictly before `effective_end`."

    Design: Difficulty/cross_entity_state_dependency/settle_requires_published_index_at_clock
    """
    ctx = setup_shipped_single_bale(
        api, index_price_cents_per_ton=8000, revenue_share_pct=0.60,
        bale_net_tons=10, moisture_pct=0, quality_grade="A", freight_cost_cents=0)
    # clock remains 2026-03-10, inside the March window
    ship = settle_shipment(api, ctx["ship_id"])
    assert ship["status"] == "SETTLED"


# --- Difficulty: state check pre-empts the referential check on settle -------

def test_settle_building_shipment_state_error_wins(api):
    """PRD §2.10: "(5) whether the target entity is in the state the requested
    transition requires (a 409 state error); (6) cross-entity referential
    readiness, such as a published index existing at settlement or a bale's source
    load being closed before it is assigned (422)".
    PRD §3.7: "Settling is permitted only from `SHIPPED` or `DISPUTED`; any other
    state is `ERR_SHIPMENT_NOT_SHIPPED`."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_beats_no_published_index
    """
    mill = create_mill(api, "OCC")
    ship = create_shipment(api, mill["id"], "OCC", 0)  # BUILDING, no OCC index exists
    resp = api.settle_mill_shipment(ship["id"], TRADER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_SHIPPED.value)


def test_settle_building_shipment_leaves_state_unchanged(api):
    """PRD §3.7: "Settling is permitted only from `SHIPPED` or `DISPUTED`; any
    other state is `ERR_SHIPMENT_NOT_SHIPPED`."

    Design: Difficulty/priority_pair_validation_conflict/settle_state_beats_no_published_index
    """
    mill = create_mill(api, "OCC")
    ship = create_shipment(api, mill["id"], "OCC", 0)
    api.settle_mill_shipment(ship["id"], TRADER)
    still = validate_success(api.get_mill_shipment(ship["id"], TRADER))
    assert still["status"] == "BUILDING"


# --- Corner: dispute on a non-settled shipment ------------------------------

def test_dispute_non_settled_shipment_rejected(api):
    """PRD §3.7: "A dispute is permitted only from `SETTLED`, else
    `ERR_SHIPMENT_NOT_SETTLED`, and takes a `reason`."

    Design: Corner/state_machines/corner_dispute_not_settled_shipment_rejected
    """
    mill = create_mill(api, "OCC")
    ship = create_shipment(api, mill["id"], "OCC", 0)  # BUILDING
    resp = api.dispute_mill_shipment(ship["id"], {"reason": "x"}, TRADER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_SETTLED.value)
