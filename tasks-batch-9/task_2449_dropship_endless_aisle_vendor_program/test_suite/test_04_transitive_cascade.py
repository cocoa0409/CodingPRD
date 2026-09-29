"""Multi-hop cascades: a vendor cancellation that reaches from one line all the way to
the vendor's money ledger, and a probation scorecard that reaches from a performance
document down to an untransmitted order line."""

from test_helpers import (
    TEST_USERS,
    assert_item_conservation,
    create_seeded_scorecard,
    make_vendor_user_headers,
    order_lines_of,
    place_order,
    refresh_item,
    refresh_line,
    refresh_order,
    refresh_vendor,
    setup_transmitted_line,
    setup_vendor_with_active_offer,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


def _serviceability_rules_of(api, vendor_id):
    body = api.list_serviceability_rules(vendor_id, _ADMIN, params={"limit": 100})
    return body.json()["data"]


def _setup_probation_scorecard(api, suffix, order_ref):
    """An ACTIVE vendor with one live offer, one untransmitted line, and a DRAFT scorecard
    seeded to land in the PROBATION band.

    The seeds are 5000 bps on time, 3000 bps cancelled and 2500 bps defective, so the
    composite is 0.50*5000 + 0.30*7000 + 0.20*7500 = 6100 bps, i.e. 61.00 out of 100.
    """
    base = setup_vendor_with_active_offer(api, suffix=suffix)
    order = place_order(api, base["item_id"], quantity=3, order_ref=order_ref)
    scorecard = create_seeded_scorecard(
        api,
        base["vendor_id"],
        avg_ship_hours=55.5,
        on_time_bps=5000,
        cancellation_bps=3000,
        defect_bps=2500,
        period_start="2026-07-01",
        period_end="2026-07-31",
    )
    line = order_lines_of(api, order["id"])[0]
    return {
        **base,
        "order_id": order["id"],
        "line_id": line["id"],
        "scorecard_id": scorecard["id"],
    }


# ─── Vendor cancellation: line → offer → order → ledger ───


def test_vendor_cancellation_releases_the_offer_reservation(api):
    """PRD §3.6: "**Hop one** sets the line's `status` to `CANCELLED_BY_VENDOR`, reduces the sourcing offer's `reserved_units` by the line's `quantity`, raises that offer's `lifetime_released_units` by the same amount, and recomputes its `available_units`."

    The first hop of the cascade: the line leaves the open set and the two units it was
    holding on the offer are released back into availability.

    Design: Difficulty/transitive_cascade/vendor_cancel_line_cascades_four_levels_to_the_vendor_settlement_ledger
    """
    state = setup_transmitted_line(
        api, quantity=2, order_ref="ORD-CASCADE-A1", suffix="CCA"
    )
    assert refresh_item(api, state["item_id"])["reserved_units"] == 2

    validate_success(
        api.cancel_line(state["line_id"], make_vendor_user_headers(state["vendor_id"]))
    )

    assert refresh_line(api, state["line_id"])["status"] == "CANCELLED_BY_VENDOR"
    item = refresh_item(api, state["item_id"])
    assert item["reserved_units"] == 0
    assert item["lifetime_reserved_units"] == 2
    assert item["lifetime_released_units"] == 2
    assert item["lifetime_shipped_units"] == 0
    assert item["available_units"] == 55
    assert_item_conservation(item)


def test_vendor_cancellation_closes_the_order_out_unfulfilled(api):
    """PRD §3.6: "**Hop three**, caused by hop two landing `fulfillment_status` on `CANCELLED` while `financial_status` is still `PENDING`, sets `financial_status` to `REFUNDED` with `refunded_cents` at 0 and `net_retail_cents` at 0 — the order closes out unfulfilled, so there is nothing to capture and nothing to refund."

    Two hops removed from the line the vendor touched: the order's only line is gone, so
    its money rolls up to zero and both axes settle on cancelled and refunded.

    Design: Difficulty/transitive_cascade/vendor_cancel_line_cascades_four_levels_to_the_vendor_settlement_ledger
    """
    state = setup_transmitted_line(
        api, quantity=2, order_ref="ORD-CASCADE-B1", suffix="CCB"
    )

    validate_success(
        api.cancel_line(state["line_id"], make_vendor_user_headers(state["vendor_id"]))
    )

    order = refresh_order(api, state["order_id"])
    assert order["fulfillment_status"] == "CANCELLED"
    assert order["financial_status"] == "REFUNDED"
    assert order["total_retail_cents"] == 0
    assert order["total_cost_cents"] == 0
    assert order["margin_cents"] == 0
    assert order["refunded_cents"] == 0
    assert order["net_retail_cents"] == 0


def test_vendor_cancellation_posts_the_penalty_onto_the_vendor_ledger(api):
    """PRD §3.6: "**Hop four**, caused by hop three closing the order out unfulfilled, posts the vendor cancellation penalty: 500 cents for each line of this order whose current offer belongs to that vendor and whose `status` is `CANCELLED_BY_VENDOR` after the cascade, added to that vendor's `chargeback_balance_cents` and subtracted in the same amount from its `settlement_balance_cents`."

    The terminal hop lands three entities away from the cancelled line, on the vendor's
    money: one cancelled line means 500 cents of chargeback and minus 500 of settlement,
    a matched pair that leaves their sum at the zero it started from.

    Design: Difficulty/transitive_cascade/vendor_cancel_line_cascades_four_levels_to_the_vendor_settlement_ledger
    """
    state = setup_transmitted_line(
        api, quantity=2, order_ref="ORD-CASCADE-C1", suffix="CCC"
    )
    before = refresh_vendor(api, state["vendor_id"])
    assert before["settlement_balance_cents"] == 0
    assert before["chargeback_balance_cents"] == 0

    validate_success(
        api.cancel_line(state["line_id"], make_vendor_user_headers(state["vendor_id"]))
    )

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["chargeback_balance_cents"] == 500
    assert vendor["settlement_balance_cents"] == -500
    assert (
        vendor["settlement_balance_cents"] + vendor["chargeback_balance_cents"] == 0
    ), "no line shipped, so the two balances must still sum to zero"


# ─── Probation publication: scorecard → vendor → coverage → offer → line ───


def test_publishing_a_probation_scorecard_suspends_the_active_vendor(api):
    """PRD §3.9: "Publishing a `PROBATION` tier onto a vendor that is currently `ACTIVE` does more than relabel it: the vendor is suspended in the same request, `ACTIVE → SUSPENDED`, with `suspension_reason` set to `SCORECARD_PROBATION`, and the full suspension cascade runs."

    The seeded scorecard scores 61.00, which bands as PROBATION, and publishing it drives
    the vendor out of ACTIVE without anybody calling the suspend endpoint.

    Design: Difficulty/transitive_cascade/scorecard_publish_probation_cascades_to_suppress_offer_and_backorder_line
    """
    state = _setup_probation_scorecard(api, suffix="PBA", order_ref="ORD-PROB-A1")
    vendor_version = refresh_vendor(api, state["vendor_id"])["version"]

    published = validate_success(
        api.publish_scorecard(state["scorecard_id"], vendor_version, _ADMIN)
    )

    assert published["status"] == "PUBLISHED"
    assert float(published["composite_score"]) == 61.00
    assert published["tier"] == "PROBATION"

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["onboarding_status"] == "SUSPENDED"
    assert vendor["suspension_reason"] == "SCORECARD_PROBATION"


def test_publication_overwrites_the_vendor_tier_and_promise_padding(api):
    """PRD §3.9: "On success the scorecard moves `DRAFT → PUBLISHED`, `published_at` is stamped from the logical clock, the vendor's `performance_tier` is overwritten with the scorecard's `tier`, the vendor's `promise_padding_days` is overwritten with the scorecard's `promise_padding_days`, and the vendor's `version` increments by 1."

    The first hop out of the scorecard writes the vendor row: PROBATION carries five
    padding days, replacing the two an unrated vendor started with.

    Design: Difficulty/transitive_cascade/scorecard_publish_probation_cascades_to_suppress_offer_and_backorder_line
    """
    state = _setup_probation_scorecard(api, suffix="PBB", order_ref="ORD-PROB-B1")
    before = refresh_vendor(api, state["vendor_id"])
    assert before["performance_tier"] == "UNRATED"
    assert before["promise_padding_days"] == 2

    published = validate_success(
        api.publish_scorecard(state["scorecard_id"], before["version"], _ADMIN)
    )
    assert published["promise_padding_days"] == 5

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["performance_tier"] == "PROBATION"
    assert vendor["promise_padding_days"] == 5
    assert vendor["version"] > before["version"]


def test_probation_suspension_inactivates_every_live_coverage_row(api):
    """PRD §3.9: "**Hop one** sets every serviceability rule of that vendor whose `status` is `ACTIVE` to `INACTIVE` and marks each of those rows with `inactivated_by_suspension` true."

    The coverage row the vendor went live on is taken down by the platform's own hand,
    and is flagged as such so reinstatement can tell it apart from a retired row.

    Design: Difficulty/transitive_cascade/scorecard_publish_probation_cascades_to_suppress_offer_and_backorder_line
    """
    state = _setup_probation_scorecard(api, suffix="PBC", order_ref="ORD-PROB-C1")
    rules_before = _serviceability_rules_of(api, state["vendor_id"])
    assert len(rules_before) == 1
    assert rules_before[0]["status"] == "ACTIVE"
    assert rules_before[0]["inactivated_by_suspension"] is False
    vendor_version = refresh_vendor(api, state["vendor_id"])["version"]

    validate_success(
        api.publish_scorecard(state["scorecard_id"], vendor_version, _ADMIN)
    )

    rules = _serviceability_rules_of(api, state["vendor_id"])
    assert len(rules) == 1
    assert rules[0]["status"] == "INACTIVE"
    assert rules[0]["inactivated_by_suspension"] is True


def test_probation_suspension_suppresses_the_vendor_offer(api):
    """PRD §3.9: "**Hop two**, caused by hop one stripping the vendor of live coverage, sets every offer of that vendor whose `status` is `ACTIVE` to `SUPPRESSED` with `suppression_reason` `VENDOR_SUSPENDED` and forces each such offer's `available_units` to 0."

    Two hops from the published document, the offer leaves the endless aisle with a
    reason that only vendor reinstatement can clear, and its availability is forced flat.

    Design: Difficulty/transitive_cascade/scorecard_publish_probation_cascades_to_suppress_offer_and_backorder_line
    """
    state = _setup_probation_scorecard(api, suffix="PBD", order_ref="ORD-PROB-D1")
    assert refresh_item(api, state["item_id"])["status"] == "ACTIVE"
    vendor_version = refresh_vendor(api, state["vendor_id"])["version"]

    validate_success(
        api.publish_scorecard(state["scorecard_id"], vendor_version, _ADMIN)
    )

    item = refresh_item(api, state["item_id"])
    assert item["status"] == "SUPPRESSED"
    assert item["suppression_reason"] == "VENDOR_SUSPENDED"
    assert item["available_units"] == 0


def test_probation_suspension_backorders_the_untransmitted_line(api):
    """PRD §3.9: "**Hop three**, caused by hop two withdrawing those offers, moves every order line still in `PENDING_TRANSMIT` that sources one of the hop-two offers to `BACKORDERED`; lines already transmitted, acknowledged, shipped or cancelled are left alone."

    The deepest hop reaches a line on an order that nobody touched: it was waiting in
    PENDING_TRANSMIT on the suppressed offer, so it is pushed to BACKORDERED.

    Design: Difficulty/transitive_cascade/scorecard_publish_probation_cascades_to_suppress_offer_and_backorder_line
    """
    state = _setup_probation_scorecard(api, suffix="PBE", order_ref="ORD-PROB-E1")
    assert refresh_line(api, state["line_id"])["status"] == "PENDING_TRANSMIT"
    vendor_version = refresh_vendor(api, state["vendor_id"])["version"]

    validate_success(
        api.publish_scorecard(state["scorecard_id"], vendor_version, _ADMIN)
    )

    line = refresh_line(api, state["line_id"])
    assert line["status"] == "BACKORDERED"
    assert line["quantity"] == 3


def test_probation_suspension_rederives_the_owning_order_fulfillment_status(api):
    """PRD §3.9: "**Hop four**, caused by hop three, re-derives the `fulfillment_status` of every order owning a hop-three line."

    The final hop touches the order: its one line is backordered, which is still an open
    line with nothing shipped, so the fulfillment axis re-derives to OPEN.

    Design: Difficulty/transitive_cascade/scorecard_publish_probation_cascades_to_suppress_offer_and_backorder_line
    """
    state = _setup_probation_scorecard(api, suffix="PBF", order_ref="ORD-PROB-F1")
    vendor_version = refresh_vendor(api, state["vendor_id"])["version"]

    validate_success(
        api.publish_scorecard(state["scorecard_id"], vendor_version, _ADMIN)
    )

    order = refresh_order(api, state["order_id"])
    assert order["fulfillment_status"] == "OPEN"
    assert order["financial_status"] == "PENDING"
