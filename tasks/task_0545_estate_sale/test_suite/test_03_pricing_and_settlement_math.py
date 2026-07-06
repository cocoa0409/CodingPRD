"""Pricing engine and settlement math: markdown day-index, silent-auction winner resolution,
tiered commission, card-fee rounding, estimated-vs-final net divergence, and buyout advances.

Literal expected values are taken from the design indices and are not recomputed here.
"""
from test_helpers import (
    validate_success,
    APPRAISER, CASHIER,
    set_clock, listed_fixed_lot, listed_bid_lot, new_bid,
    contracted_project, new_lot, research_and_price,
    settled_ready_consignment_sale,
    make_appraiser_headers, make_sale_manager_headers,
)


# ---- Difficulty: boundary_precision_check / markdown_day_index_boundary_at_exactly_one_day --
def test_markdown_at_exactly_one_day_applies_day1_discount(api):
    """PRD §3.4: "The **day index** is the number of whole days elapsed since the event's
    `start_at`: take the current logical-clock time minus `start_at` in seconds, divide by the
    number of seconds in one day (86400), discard the fractional part, and clamp the result so
    it is never below zero." "On day index 1 the discount fraction is `markdown_day1_pct`
    (default 0.25)."

    Design: Difficulty/boundary_precision_check/markdown_day_index_boundary_at_exactly_one_day
    """
    ctx = listed_fixed_lot(api, list_price_cents=10000, reserve_price_cents=100)
    set_clock("2026-06-02T00:00:00Z", api)  # exactly one day after 2026-06-01T00:00:00Z start
    resp = api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    data = validate_success(resp, 201)
    assert data["final_price_cents"] == 7500


def test_markdown_just_before_one_day_is_full_price(api):
    """PRD §3.4: "On day index 0 there is no discount." "The realized price is the lot's
    `list_price_cents` multiplied by one minus the applicable discount fraction, rounded half up
    to whole cents."

    Design: Difficulty/boundary_precision_check/markdown_day_index_boundary_at_exactly_one_day
    """
    ctx = listed_fixed_lot(api, list_price_cents=10000, reserve_price_cents=100)
    set_clock("2026-06-01T23:59:59Z", api)  # one second short of a full day -> day index 0
    resp = api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    data = validate_success(resp, 201)
    assert data["final_price_cents"] == 10000


# ---- Corner: calculations / markdown_day2_price_correct ------------------------------------
def test_markdown_day2_price_correct(api):
    """PRD §3.4: "On day index 2 it is `markdown_day2_pct` (default 0.50)." "The realized price
    is the lot's `list_price_cents` multiplied by one minus the applicable discount fraction,
    rounded half up to whole cents."

    Design: Corner/calculations/markdown_day2_price_correct
    """
    ctx = listed_fixed_lot(api, list_price_cents=10000, reserve_price_cents=100)
    set_clock("2026-06-03T00:00:00Z", api)  # day index 2
    resp = api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    data = validate_success(resp, 201)
    assert data["final_price_cents"] == 5000


# ---- Difficulty: boundary_precision_check / bid_close_with_empty_bid_set_falls_back_to_unsold
def test_bid_close_empty_set_marks_unsold(api):
    """PRD §3.4: "For a bid lot with no `PLACED` bids at all, closing instead sends the lot
    straight to `UNSOLD` as an empty-set fallback, leaving `winning_bid_id` null and recomputing
    the project's `unsold_lot_count`."

    Design: Difficulty/boundary_precision_check/bid_close_with_empty_bid_set_falls_back_to_unsold
    """
    ctx = listed_bid_lot(api, bid_mode="SECOND_PRICE", reserve_price_cents=4000,
                         min_increment_cents=500, list_price_cents=8000)
    resp = api.patch_lot(ctx["lot_id"], {"status": "BID_CLOSED"}, APPRAISER)
    data = validate_success(resp, 200)
    assert data["status"] == "UNSOLD"


def test_bid_close_empty_set_leaves_winner_null(api):
    """PRD §3.4: "For a bid lot with no `PLACED` bids at all, closing instead sends the lot
    straight to `UNSOLD` as an empty-set fallback, leaving `winning_bid_id` null and recomputing
    the project's `unsold_lot_count`."

    Design: Difficulty/boundary_precision_check/bid_close_with_empty_bid_set_falls_back_to_unsold
    """
    ctx = listed_bid_lot(api, bid_mode="SECOND_PRICE", reserve_price_cents=4000,
                         min_increment_cents=500, list_price_cents=8000)
    resp = api.patch_lot(ctx["lot_id"], {"status": "BID_CLOSED"}, APPRAISER)
    data = validate_success(resp, 200)
    assert data["winning_bid_id"] is None


# ---- Difficulty: dual_variant_calc / winning_bid_first_price_vs_second_price ----------------
def _bid_lot_with_three_bids(api, bid_mode):
    ctx = listed_bid_lot(api, bid_mode=bid_mode, reserve_price_cents=10000,
                         min_increment_cents=1000, list_price_cents=20000)
    # Same PLACED set {12000, 13000, 15000}; placed ascending so each clears the increment floor.
    new_bid(ctx["lot_id"], 12000, "b1", api)
    new_bid(ctx["lot_id"], 13000, "b3", api)
    new_bid(ctx["lot_id"], 15000, "b2", api)
    return ctx["lot_id"]


def test_winning_bid_first_price_pays_own_high_bid(api):
    """PRD §3.4: "Under `FIRST_PRICE`, the winner pays their own high bid — the highest
    candidate `amount_cents`."

    Design: Difficulty/dual_variant_calc/winning_bid_first_price_vs_second_price
    """
    lot_id = _bid_lot_with_three_bids(api, "FIRST_PRICE")
    resp = api.patch_lot(lot_id, {"status": "BID_CLOSED"}, APPRAISER)
    data = validate_success(resp, 200)
    assert data["winning_bid_price_cents"] == 15000


def test_winning_bid_second_price_pays_second_plus_increment(api):
    """PRD §3.4: "Under `SECOND_PRICE`, if a second-highest candidate exists, the winner pays
    the smaller of their own high bid and the second-highest candidate's `amount_cents` plus the
    lot's `min_increment_cents`."

    Design: Difficulty/dual_variant_calc/winning_bid_first_price_vs_second_price
    """
    lot_id = _bid_lot_with_three_bids(api, "SECOND_PRICE")
    resp = api.patch_lot(lot_id, {"status": "BID_CLOSED"}, APPRAISER)
    data = validate_success(resp, 200)
    assert data["winning_bid_price_cents"] == 14000


# ---- Difficulty: dual_variant_calc / settlement_estimated_vs_final_net_diverges -------------
def _card_day1_sale_ready_to_settle(api):
    return settled_ready_consignment_sale(
        lots=[{"list_price_cents": 300000, "reserve_price_cents": 1000, "title": "Dining set"},
              {"list_price_cents": 400000, "reserve_price_cents": 1000, "title": "China cabinet"}],
        payment_method="CARD",
        sell_clock="2026-06-02T10:00:00Z",
        sale_start="2026-06-01T00:00:00Z",
        sale_end="2026-06-03T00:00:00Z",
        minimum_commission_cents=50000,
        api=api,
    )


def test_estimated_net_snapshot_frozen_at_sale_setup(api):
    """PRD §3.3: "`estimated_gross_consignment_cents` is set to the sum of `list_price_cents`
    across all `CONSIGNMENT` lots that are then in one of the states `PRICED`, `STAGED`,
    `TAGGED`, or `LISTED`." "`estimated_net_to_client_cents` is set to the estimated gross
    consignment minus the estimated commission — with no card fees subtracted, because at
    snapshot time no card transactions have occurred yet."

    Design: Difficulty/dual_variant_calc/settlement_estimated_vs_final_net_diverges
    """
    ctx = _card_day1_sale_ready_to_settle(api)
    assert ctx["project"]["estimated_net_to_client_cents"] == 440000


def test_final_settlement_net_diverges_from_estimate(api):
    """PRD §3.8: "`gross_consignment_cents`: the sum of `final_price_cents` over the project's
    `RECORDED` transactions whose lot's `handling_type` is `CONSIGNMENT`."
    PRD §3.8: "`net_to_client_cents`: `gross_consignment_cents` minus `commission_cents` minus
    `card_fees_cents`."

    Design: Difficulty/dual_variant_calc/settlement_estimated_vs_final_net_diverges
    """
    ctx = _card_day1_sale_ready_to_settle(api)
    resp = api.create_settlement(
        {"project_id": ctx["project_id"], "expected_project_version": ctx["settling_version"]},
        make_sale_manager_headers("mgr-1"),
    )
    data = validate_success(resp, 201)
    assert data["gross_consignment_cents"] == 525000
    assert data["net_to_client_cents"] == 302275


# ---- Difficulty: combinatorial_formula / commission_marginal_tiered_rate --------------------
def _cash_full_price_sale_ready_to_settle(api):
    return settled_ready_consignment_sale(
        lots=[{"list_price_cents": 300000, "reserve_price_cents": 1000, "title": "Sofa"},
              {"list_price_cents": 400000, "reserve_price_cents": 1000, "title": "Rug"}],
        payment_method="CASH",
        sell_clock="2026-06-01T00:00:00Z",
        sale_start="2026-06-01T00:00:00Z",
        sale_end="2026-06-02T00:00:00Z",
        minimum_commission_cents=50000,
        api=api,
    )


def test_commission_marginal_tiered_rate(api):
    """PRD §3.8: "The tiered part is computed marginally: the portion of the consignment gross
    up to the first-tier threshold of 500000 cents is charged at the first-tier rate of 40
    percent, and any portion above 500000 cents is charged at the second-tier rate of 30
    percent; these two tier amounts are added together and that single aggregate sum is rounded
    half up to whole cents. The commission is then the larger of that rounded tiered amount and
    the project's `minimum_commission_cents`."

    Design: Difficulty/combinatorial_formula/commission_marginal_tiered_rate
    """
    ctx = _cash_full_price_sale_ready_to_settle(api)
    resp = api.create_settlement(
        {"project_id": ctx["project_id"], "expected_project_version": ctx["settling_version"]},
        make_sale_manager_headers("mgr-1"),
    )
    data = validate_success(resp, 201)
    assert data["commission_cents"] == 260000


def test_cash_sale_incurs_no_card_fees(api):
    """PRD §3.8: "`card_fees_cents`: the total card processing charged against consignment
    sales. For each `RECORDED` `CARD` transaction on a `CONSIGNMENT` lot, its individual fee is
    that transaction's `final_price_cents` multiplied by the 2.9% card rate, rounded half up to
    whole cents; these already-rounded per-transaction fees are then summed."

    Design: Difficulty/combinatorial_formula/commission_marginal_tiered_rate
    """
    ctx = _cash_full_price_sale_ready_to_settle(api)
    resp = api.create_settlement(
        {"project_id": ctx["project_id"], "expected_project_version": ctx["settling_version"]},
        make_sale_manager_headers("mgr-1"),
    )
    data = validate_success(resp, 201)
    assert data["card_fees_cents"] == 0


# ---- Difficulty: combinatorial_formula / card_fee_round_per_transaction_then_sum ------------
def _card_half_cent_sale_ready_to_settle(api):
    return settled_ready_consignment_sale(
        lots=[{"list_price_cents": 500, "reserve_price_cents": 100, "title": "Mug A"},
              {"list_price_cents": 500, "reserve_price_cents": 100, "title": "Mug B"}],
        payment_method="CARD",
        sell_clock="2026-06-01T00:00:00Z",
        sale_start="2026-06-01T00:00:00Z",
        sale_end="2026-06-02T00:00:00Z",
        minimum_commission_cents=0,
        api=api,
    )


def test_card_fee_rounds_per_transaction_then_sums(api):
    """PRD §3.8: "these already-rounded per-transaction fees are then summed. The rounding
    happens per transaction and only then are the results summed — never the reverse."

    Design: Difficulty/combinatorial_formula/card_fee_round_per_transaction_then_sum
    """
    ctx = _card_half_cent_sale_ready_to_settle(api)
    resp = api.create_settlement(
        {"project_id": ctx["project_id"], "expected_project_version": ctx["settling_version"]},
        make_sale_manager_headers("mgr-1"),
    )
    data = validate_success(resp, 201)
    assert data["card_fees_cents"] == 30


def test_card_fee_settlement_gross_consignment(api):
    """PRD §3.8: "`gross_consignment_cents`: the sum of `final_price_cents` over the project's
    `RECORDED` transactions whose lot's `handling_type` is `CONSIGNMENT`."

    Design: Difficulty/combinatorial_formula/card_fee_round_per_transaction_then_sum
    """
    ctx = _card_half_cent_sale_ready_to_settle(api)
    resp = api.create_settlement(
        {"project_id": ctx["project_id"], "expected_project_version": ctx["settling_version"]},
        make_sale_manager_headers("mgr-1"),
    )
    data = validate_success(resp, 201)
    assert data["gross_consignment_cents"] == 1000


# ---- Corner: calculations / approve_buyout_records_advance_and_converts ---------------------
def test_approve_buyout_converts_and_records_advance(api):
    """PRD §3.5: "Approval flips the lot's `handling_type` to `BUYOUT`, stamps
    `buyout_price_cents` and the approving manager's `X-User-ID` as `approved_buyout_by_user_id`,
    adds the advance to the project's `buyout_advances_cents`, and increments the project's
    `version` by one."

    Design: Corner/calculations/approve_buyout_records_advance_and_converts
    """
    _, project = contracted_project(api)
    lot = new_lot(project["id"], api, title="Antique desk", list_price_cents=8000,
                  reserve_price_cents=100, researcher_headers=make_appraiser_headers("APP1"))
    research_and_price(lot["id"], api, list_price_cents=8000,
                       researcher_headers=make_appraiser_headers("APP1"))
    resp = api.approve_buyout(lot["id"], {"buyout_price_cents": 5000}, make_sale_manager_headers("MGR1"))
    data = validate_success(resp, 200)
    assert data["handling_type"] == "BUYOUT"
    assert data["buyout_price_cents"] == 5000
    proj = validate_success(api.get_project(project["id"], make_sale_manager_headers("MGR1")))
    assert proj["buyout_advances_cents"] == 5000
