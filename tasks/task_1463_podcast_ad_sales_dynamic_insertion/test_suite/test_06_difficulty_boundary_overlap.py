"""Difficulty queue A — boundary_precision_check + resource_temporal_overlap
(4 instances, 8 tests)."""

from test_helpers import (
    ADOPS,
    ApiErrorId,
    add_line_item,
    create_advertiser,
    create_campaign,
    create_episode,
    create_invoice,
    create_show,
    get_episode,
    get_line_item,
    get_show,
    list_make_goods_for_campaign,
    setup_measured_delivery,
    setup_selling_scenario,
    validate_error,
    validate_success,
)


def _setup_adjacent_flights():
    """Show + three different TECHNOLOGY advertisers; CA [08-01, 09-01) with an
    ACTIVE line item; CB [09-01, 10-01) with LI_B DRAFT; CC [08-15, 09-15) with
    LI_C DRAFT. All campaigns ACTIVE with APPROVED copies."""
    show = create_show(title="Boundary Bay", content_category="TECHNOLOGY",
                       avg_downloads_30d=10000)
    create_episode(show["id"], title="POOL", publish_at="2026-08-05T00:00:00Z",
                   measurement_window_days=30, slot_capacity=2)
    specs = {
        "A": ("A1", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", True),
        "B": ("A2", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", False),
        "C": ("A3", "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z", False),
    }
    ctxs = {}
    for key, (adv_name, start, end, activate_li) in specs.items():
        ctx = setup_selling_scenario(
            with_episode=False, advertiser_name=adv_name, category="TECHNOLOGY",
            booked_impressions=10, cpm_cents=1000,
            flight_start=start, flight_end=end,
        )
        ctx["show"] = show
        ctx["line_item"] = add_line_item(
            ctx, target="show", position="MID_ROLL", reserved_impressions=10,
            priority=10, activate=activate_li,
        )
        ctxs[key] = ctx
    return ctxs


def _setup_slot_capacity_trio():
    """Episode slot_capacity 2; three ACTIVE campaigns (distinct categories)
    each with a DRAFT episode-targeted line item."""
    show = create_show(title="Slot City", content_category="TECHNOLOGY",
                       avg_downloads_30d=10000)
    episode = create_episode(show["id"], title="E1", publish_at="2026-08-01T00:00:00Z",
                             measurement_window_days=30, slot_capacity=2)
    ctxs = []
    for name, category, priority in (
        ("SlotA", "TECHNOLOGY", 10),
        ("SlotB", "FINTECH", 9),
        ("SlotC", "ALCOHOL", 8),
    ):
        ctx = setup_selling_scenario(
            with_episode=False, advertiser_name=name, category=category,
            booked_impressions=10, cpm_cents=1000,
        )
        ctx["show"] = show
        ctx["episode"] = episode
        ctx["line_item"] = add_line_item(
            ctx, target="episode", position="MID_ROLL", reserved_impressions=10,
            priority=priority, activate=False,
        )
        ctxs.append(ctx)
    return {"show": show, "episode": episode, "buyers": ctxs}


# =========================================================================
# exclusivity_adjacent_flights_end_equals_start
# =========================================================================

def test_adjacent_flight_end_equals_start_is_not_overlap(api):
    """PRD §3.4: "Two half-open flight intervals overlap when the first flight's start is strictly before the second flight's end, and the second flight's start is strictly before the first flight's end."

    Design: Difficulty/boundary_precision_check/exclusivity_adjacent_flights_end_equals_start
    """
    ctxs = _setup_adjacent_flights()
    # CB.flight_start == CA.flight_end: adjacency, not positive-duration overlap.
    resp = api.transition_line_item(ctxs["B"]["line_item"]["id"],
                                    {"action": "ACTIVATE"}, ADOPS)
    line_item = validate_success(resp)
    assert line_item["status"] == "ACTIVE", (
        "Adjacent same-category activation must succeed under half-open flights"
    )


def test_one_day_overlap_on_same_show_fails(api):
    """PRD §3.4: "**Category exclusivity**: no other `ACTIVE` line item belonging to a *different* advertiser of the *same* category may target the same show with a flight overlapping the candidate's flight, else `ERR_CATEGORY_EXCLUSIVE_CONFLICT`."

    Design: Difficulty/boundary_precision_check/exclusivity_adjacent_flights_end_equals_start
    """
    ctxs = _setup_adjacent_flights()
    # CC [2026-08-15, 2026-09-15) intersects CA's [2026-08-01, 2026-09-01).
    resp = api.transition_line_item(ctxs["C"]["line_item"]["id"],
                                    {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_EXCLUSIVE_CONFLICT)
    assert get_line_item(ctxs["C"]["line_item"]["id"])["status"] == "DRAFT"


# =========================================================================
# shortfall_zero_vs_one_makegood_threshold
# =========================================================================

def _setup_threshold_pair():
    """Campaigns CX (800 delivered vs 800 booked) and CY (799 vs 800), both
    ACTUAL_DELIVERY cpm 1000, each on its own show; measured and ENDED."""
    ctxs = {}
    for key, downloads in (("full", 800), ("short", 799)):
        ctx = setup_measured_delivery(
            booked_impressions=800, cpm_cents=1000, downloads=downloads,
            reserved_impressions=100, category="CPG_FOOD",
            end_campaign_too=True,
        )
        ctxs[key] = ctx
    return ctxs


def test_delivered_exactly_booked_creates_no_makegood(api):
    """PRD §3.7: "`shortfall_impressions` is `booked_impressions` minus `delivered_impressions_billed`, floored at zero."
    PRD §3.7: "If `shortfall_impressions` is greater than zero at creation, the system automatically creates exactly one **MakeGood** for the campaign in `OFFERED` status"

    Design: Difficulty/boundary_precision_check/shortfall_zero_vs_one_makegood_threshold
    """
    ctxs = _setup_threshold_pair()
    invoice = create_invoice(ctxs["full"]["campaign"]["id"])
    assert invoice["delivered_impressions_billed"] == 800
    assert invoice["shortfall_impressions"] == 0, (
        "delivered == booked exactly means zero shortfall"
    )
    assert list_make_goods_for_campaign(ctxs["full"]["campaign"]["id"]) == []


def test_delivered_one_below_booked_creates_makegood_for_one(api):
    """PRD §3.7: "If `shortfall_impressions` is greater than zero at creation, the system automatically creates exactly one **MakeGood** for the campaign in `OFFERED` status, recording the `campaign_id`, the `invoice_id` that documented the shortfall, and `granted_impressions` equal to the invoice's `shortfall_impressions`."

    Design: Difficulty/boundary_precision_check/shortfall_zero_vs_one_makegood_threshold
    """
    ctxs = _setup_threshold_pair()
    invoice = create_invoice(ctxs["short"]["campaign"]["id"])
    assert invoice["shortfall_impressions"] == 1, (
        f"delivered == booked - 1 must yield shortfall 1, got "
        f"{invoice['shortfall_impressions']}"
    )
    make_goods = list_make_goods_for_campaign(ctxs["short"]["campaign"]["id"])
    assert len(make_goods) == 1
    assert make_goods[0]["granted_impressions"] == 1
    assert make_goods[0]["status"] == "OFFERED"


# =========================================================================
# category_exclusivity_half_open_overlap_rejected
# =========================================================================

def _setup_overlap_pair():
    """Two different FINTECH advertisers; CA [08-01, 09-01) ACTIVE with LI_A
    ACTIVE (reserved 10); CB [08-15, 09-15) ACTIVE with LI_B DRAFT."""
    show = create_show(title="Overlap FM", content_category="BUSINESS",
                       avg_downloads_30d=10000)
    create_episode(show["id"], title="POOL", publish_at="2026-08-05T00:00:00Z",
                   measurement_window_days=30, slot_capacity=2)
    ctx_a = setup_selling_scenario(
        with_episode=False, advertiser_name="FinA", category="FINTECH",
        booked_impressions=10, cpm_cents=1000,
        flight_start="2026-08-01T00:00:00Z", flight_end="2026-09-01T00:00:00Z",
    )
    ctx_a["show"] = show
    ctx_a["line_item"] = add_line_item(ctx_a, target="show", position="MID_ROLL",
                                       reserved_impressions=10, priority=10)
    ctx_b = setup_selling_scenario(
        with_episode=False, advertiser_name="FinB", category="FINTECH",
        booked_impressions=10, cpm_cents=1000,
        flight_start="2026-08-15T00:00:00Z", flight_end="2026-09-15T00:00:00Z",
    )
    ctx_b["show"] = show
    ctx_b["line_item"] = add_line_item(ctx_b, target="show", position="MID_ROLL",
                                       reserved_impressions=10, priority=10,
                                       activate=False)
    return {"show": show, "a": ctx_a, "b": ctx_b}


def test_overlapping_same_category_activation_rejected(api):
    """PRD §3.4: "**Category exclusivity**: no other `ACTIVE` line item belonging to a *different* advertiser of the *same* category may target the same show with a flight overlapping the candidate's flight, else `ERR_CATEGORY_EXCLUSIVE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/category_exclusivity_half_open_overlap_rejected
    """
    ctx = _setup_overlap_pair()
    resp = api.transition_line_item(ctx["b"]["line_item"]["id"],
                                    {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_EXCLUSIVE_CONFLICT)


def test_rejected_activation_preserves_pool_and_draft_state(api):
    """PRD §3.4: "New line items are `DRAFT` and hold no reservation."
    PRD §3.1: "`reserved_impressions` is the sum of `reserved_impressions` over the show's `ACTIVE` run-of-show line items, and `available_impressions` is the difference"

    Design: Difficulty/resource_temporal_overlap/category_exclusivity_half_open_overlap_rejected
    """
    ctx = _setup_overlap_pair()
    resp = api.transition_line_item(ctx["b"]["line_item"]["id"],
                                    {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_EXCLUSIVE_CONFLICT)
    line_item = get_line_item(ctx["b"]["line_item"]["id"])
    assert line_item["status"] == "DRAFT"
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 10, (
        f"Only LI_A's reservation may be held, got {show['reserved_impressions']}"
    )
    assert show["available_impressions"] == show["forecast_impressions"] - 10


# =========================================================================
# episode_slot_aggregate_capacity_overflow
# =========================================================================

def test_two_overlapping_episode_line_items_fit_capacity(api):
    """PRD §3.4: "**Episode slot capacity** (episode-targeted items): the count of other `ACTIVE` episode-targeted line items on that episode whose campaign flights overlap the candidate's flight must be less than the episode's `slot_capacity`, else `ERR_SLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/episode_slot_aggregate_capacity_overflow
    """
    ctx = _setup_slot_capacity_trio()
    buyers = ctx["buyers"]
    for buyer in buyers[:2]:
        resp = api.transition_line_item(buyer["line_item"]["id"],
                                        {"action": "ACTIVATE"}, ADOPS)
        assert validate_success(resp)["status"] == "ACTIVE"
    # The third overlapping activation exceeds the aggregate capacity of 2.
    resp = api.transition_line_item(buyers[2]["line_item"]["id"],
                                    {"action": "ACTIVATE"}, ADOPS)
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED)
    assert get_line_item(buyers[2]["line_item"]["id"])["status"] == "DRAFT"


def test_slots_in_use_reflects_two_successful_activations(api):
    """PRD §3.4: "an episode-targeted item triggers recomputation of the episode's `slots_in_use`, defined as the count of `ACTIVE` episode-targeted line items whose campaign flight contains the current logical-clock instant (`slots_free`, the capacity minus that count, is what remains sellable)."

    Design: Difficulty/resource_temporal_overlap/episode_slot_aggregate_capacity_overflow
    """
    ctx = _setup_slot_capacity_trio()
    for buyer in ctx["buyers"][:2]:
        resp = api.transition_line_item(buyer["line_item"]["id"],
                                        {"action": "ACTIVATE"}, ADOPS)
        assert validate_success(resp)["status"] == "ACTIVE"
    episode = get_episode(ctx["episode"]["id"])
    assert episode["slots_in_use"] == 2, (
        f"slots_in_use must be 2 after two activations, got {episode['slots_in_use']}"
    )
