"""Point accrual, the promotional multiplier stack and the half-open window."""
from test_helpers import (
    ADMIN,
    MONTH_WINDOWS,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_store_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _six_category_basket():
    """A banner with three overlapping grocery promotions and one basket whose
    six lines cover every purchase category."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner()
    cycles = fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    grocery = fixtures.create_grocery_site(banner["id"], "G-003")
    member = fixtures.create_member(banner["id"], alt_id="5550000003")
    p_double = fixtures.create_promo(
        banner["id"],
        promo_code="P_DOUBLE",
        multiplier=2,
        applies_to_categories=["GROCERY", "GIFT_CARD"],
        stack_priority=10,
    )
    p_triple = fixtures.create_promo(
        banner["id"],
        promo_code="P_TRIPLE",
        multiplier=3,
        applies_to_categories=["GROCERY"],
        stack_priority=5,
    )
    fixtures.create_promo(
        banner["id"],
        promo_code="P_QUINT",
        multiplier=5,
        applies_to_categories=["GROCERY"],
        stack_priority=1,
    )
    txn = fixtures.record_basket(
        member["id"],
        grocery["id"],
        [
            factories.purchase_line("GROCERY", 1050, 1),
            factories.purchase_line("GROCERY", 175, 1),
            factories.purchase_line("GROCERY", 175, 1),
            factories.purchase_line("GIFT_CARD", 512, 1),
            factories.purchase_line("PHARMACY", 8999, 1),
            factories.purchase_line("FUEL", 4000, 12),
        ],
    )
    return {
        "banner": banner,
        "cycles": cycles,
        "grocery": grocery,
        "member": member,
        "p_double": p_double,
        "p_triple": p_triple,
        "txn": txn,
    }


def test_accrual_rounds_each_line_before_summing_across_six_categories():
    """Six lines, two of them landing on an exact half, must be rounded one by
    one and only then added up.

    PRD: "`gross_points_awarded` is the sum of the **rounded** `line_points`
    values across all lines. The order here is pinned: never sum the unrounded
    values and round once at the end."

    Design: Difficulty/combinatorial_formula/accrual_rounds_per_line_then_sums_across_six_categories
    """
    scenario = _six_category_basket()
    grocery_id = scenario["grocery"]["id"]

    posted = fixtures.post_basket(scenario["txn"]["id"], grocery_id)

    assert posted["gross_points_awarded"] == 226
    assert posted["gross_points_awarded"] != 225, (
        "225 is the forbidden sum-then-round answer"
    )
    line_points = [line["line_points"] for line in posted["line_points_breakdown"]]
    assert line_points == [63, 11, 11, 41, 100, 0]
    assert posted["subtotal_cents"] == 14911


def test_accrual_stack_cut_is_by_priority_and_writes_one_dated_lot():
    """Only the two highest-priority promotions apply, and the posted basket
    appends exactly one dated accrual lot.

    PRD: "Only the first `max_stack_count` events of that ranking are applied;
    the rest are dropped outright."

    Design: Difficulty/combinatorial_formula/accrual_rounds_per_line_then_sums_across_six_categories
    """
    scenario = _six_category_basket()
    member_id = scenario["member"]["id"]

    posted = fixtures.post_basket(scenario["txn"]["id"], scenario["grocery"]["id"])

    assert posted["applied_promo_event_ids"] == [
        scenario["p_double"]["id"],
        scenario["p_triple"]["id"],
    ]
    assert posted["posting_status"] == "POSTED"
    assert posted["accrual_status"] == "ACCRUED"

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 226
    assert member["lifetime_points"] == 226

    data, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "ACCRUAL"}
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["points_delta"] == 226
    assert data[0]["lot_expires_at"] == MONTH_WINDOWS["2026-09"][1]


def _promo_window_scenario():
    """One promotion whose window runs from the 10th to the 20th, plus two
    baskets recorded exactly on each endpoint."""
    fixtures.set_clock("2026-08-20T00:00:00Z")
    banner = fixtures.create_banner(banner_code="WIN", name="Window Banner")
    fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    grocery = fixtures.create_grocery_site(banner["id"], "G-012")
    member = fixtures.create_member(banner["id"], alt_id="5550000012")
    promo = fixtures.create_promo(
        banner["id"],
        promo_code="P_WIN",
        multiplier=2,
        applies_to_categories=["GROCERY"],
        starts_at="2026-08-10T00:00:00Z",
        ends_at="2026-08-20T00:00:00Z",
        stack_priority=10,
    )
    lines = [factories.purchase_line("GROCERY", 1000, 1)]
    at_start = fixtures.record_basket(
        member["id"], grocery["id"], lines, "2026-08-10T00:00:00Z"
    )
    at_end = fixtures.record_basket(
        member["id"], grocery["id"], lines, "2026-08-20T00:00:00Z"
    )
    return {
        "grocery": grocery,
        "member": member,
        "promo": promo,
        "at_start": at_start,
        "at_end": at_end,
    }


def test_promotion_applies_to_a_basket_transacted_exactly_at_its_start_instant():
    """The opening instant of the window is inside it, so the multiplier lands.

    PRD: "For each line, the eligible events are those belonging to the member's
    banner, in `ACTIVE` status, whose half-open window contains `transacted_at`
    (that is, whose `starts_at` is at or before `transacted_at` and whose
    `ends_at` is strictly after it), and whose `applies_to_categories` contains
    that line's `category`."

    Design: Difficulty/boundary_precision_check/promo_window_includes_starts_at_instant_and_excludes_ends_at_instant
    """
    scenario = _promo_window_scenario()

    posted = fixtures.post_basket(scenario["at_start"]["id"], scenario["grocery"]["id"])

    assert posted["gross_points_awarded"] == 20
    assert posted["applied_promo_event_ids"] == [scenario["promo"]["id"]]


def test_promotion_does_not_apply_to_a_basket_transacted_exactly_at_its_end_instant():
    """The closing instant is outside the window, so the same basket earns the
    unmultiplied award.

    PRD: "The window is **half-open**: an event applies to a basket transacted
    exactly at its `starts_at`, and does not apply to one transacted exactly at
    its `ends_at`."

    Design: Difficulty/boundary_precision_check/promo_window_includes_starts_at_instant_and_excludes_ends_at_instant
    """
    scenario = _promo_window_scenario()
    grocery_id = scenario["grocery"]["id"]

    fixtures.post_basket(scenario["at_start"]["id"], grocery_id)
    posted_at_end = fixtures.post_basket(scenario["at_end"]["id"], grocery_id)

    assert posted_at_end["gross_points_awarded"] == 10
    assert posted_at_end["applied_promo_event_ids"] == []

    member = fixtures.get_member(scenario["member"]["id"])
    assert member["available_points"] == 30
    assert member["lifetime_points"] == 30


def test_promotion_window_boundary_is_the_only_difference_between_the_two_baskets():
    """Two identical baskets differing only in `transacted_at` earn different
    point totals, which is what makes the boundary observable.

    PRD: "The `transacted_at` instant is what selects eligible promotional
    events later, and must fall inside the banner's open cycle window."

    Design: Difficulty/boundary_precision_check/promo_window_includes_starts_at_instant_and_excludes_ends_at_instant
    """
    scenario = _promo_window_scenario()
    grocery_id = scenario["grocery"]["id"]

    inside = fixtures.post_basket(scenario["at_start"]["id"], grocery_id)
    on_the_edge = fixtures.post_basket(scenario["at_end"]["id"], grocery_id)

    assert inside["subtotal_cents"] == on_the_edge["subtotal_cents"] == 1000
    assert inside["gross_points_awarded"] == 2 * on_the_edge["gross_points_awarded"]


def _overlap_banner_with_first_promotion():
    """A banner carrying one active grocery promotion at priority 10 running
    from the 1st to the 10th."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="OVL", name="Overlap Banner")
    first = fixtures.create_promo(
        banner["id"],
        promo_code="P01",
        multiplier=2,
        applies_to_categories=["GROCERY"],
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-10T00:00:00Z",
        stack_priority=10,
    )
    return banner, first


def test_back_to_back_promotions_touching_at_one_instant_are_both_allowed():
    """A window that starts exactly where the previous one ends is adjacency,
    not overlap.

    PRD: "Because windows are half-open, back-to-back events that touch at a
    single instant do not overlap and are both allowed."

    Design: Difficulty/resource_temporal_overlap/promo_half_open_windows_permit_adjacency_and_reject_true_overlap
    """
    banner, _first = _overlap_banner_with_first_promotion()

    adjacent = validate_success(
        api_client.create_promo_event(
            factories.promo_event_payload(
                banner["id"],
                promo_code="P02",
                multiplier=3,
                applies_to_categories=["GROCERY"],
                starts_at="2026-08-10T00:00:00Z",
                ends_at="2026-08-20T00:00:00Z",
                stack_priority=10,
            ),
            ADMIN,
        ),
        201,
    )

    assert adjacent["status"] == "SCHEDULED"


def test_truly_overlapping_promotions_at_equal_priority_are_refused():
    """A genuine overlap on the same category at the same priority collides,
    while a different priority or a different category does not.

    PRD: "Two events collide when they belong to the same banner, are both in
    `SCHEDULED` or `ACTIVE` status, have overlapping half-open windows, share at
    least one category in their `applies_to_categories` sets, **and** carry the
    same `stack_priority`."

    Design: Difficulty/resource_temporal_overlap/promo_half_open_windows_permit_adjacency_and_reject_true_overlap
    """
    banner, _first = _overlap_banner_with_first_promotion()
    validate_success(
        api_client.create_promo_event(
            factories.promo_event_payload(
                banner["id"],
                promo_code="P02",
                multiplier=3,
                applies_to_categories=["GROCERY"],
                starts_at="2026-08-10T00:00:00Z",
                ends_at="2026-08-20T00:00:00Z",
                stack_priority=10,
            ),
            ADMIN,
        ),
        201,
    )

    validate_error(
        api_client.create_promo_event(
            factories.promo_event_payload(
                banner["id"],
                promo_code="P03",
                multiplier=4,
                applies_to_categories=["GROCERY"],
                starts_at="2026-08-09T00:00:00Z",
                ends_at="2026-08-15T00:00:00Z",
                stack_priority=10,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value,
    )

    lower_priority = validate_success(
        api_client.create_promo_event(
            factories.promo_event_payload(
                banner["id"],
                promo_code="P04",
                multiplier=4,
                applies_to_categories=["GROCERY"],
                starts_at="2026-08-09T00:00:00Z",
                ends_at="2026-08-15T00:00:00Z",
                stack_priority=7,
            ),
            ADMIN,
        ),
        201,
    )
    assert lower_priority["stack_priority"] == 7

    other_category = validate_success(
        api_client.create_promo_event(
            factories.promo_event_payload(
                banner["id"],
                promo_code="P05",
                multiplier=4,
                applies_to_categories=["PHARMACY"],
                starts_at="2026-08-09T00:00:00Z",
                ends_at="2026-08-15T00:00:00Z",
                stack_priority=10,
            ),
            ADMIN,
        ),
        201,
    )
    assert other_category["applies_to_categories"] == ["PHARMACY"]

    _data, meta = validate_paginated(
        api_client.list_banner_promo_events(banner["id"], ADMIN)
    )
    assert meta["total_count"] == 4


def _two_recorded_baskets_at_one_lane():
    """Two identical baskets recorded at the same grocery lane, neither posted."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner(banner_code="SUS", name="Suspension Banner")
    fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    grocery = fixtures.create_grocery_site(banner["id"], "G-015")
    member = fixtures.create_member(banner["id"], alt_id="5550000015")
    lines = [factories.purchase_line("GROCERY", 30000, 1)]
    first = fixtures.record_basket(member["id"], grocery["id"], lines)
    second = fixtures.record_basket(member["id"], grocery["id"], lines)
    return {"grocery": grocery, "member": member, "first": first, "second": second}


def test_posting_at_a_suspended_grocery_site_is_refused():
    """Suspending the lane between two posts stops the second one.

    PRD: "The member's banner must be `ACTIVE` (otherwise
    `ERR_BANNER_SUSPENDED`) and the site must be `ACTIVE` (otherwise
    `ERR_SITE_SUSPENDED`)."

    Design: Difficulty/cross_entity_state_dependency/purchase_posting_gated_by_grocery_site_active_state
    """
    scenario = _two_recorded_baskets_at_one_lane()
    grocery_id = scenario["grocery"]["id"]

    first_posted = fixtures.post_basket(scenario["first"]["id"], grocery_id)
    assert first_posted["gross_points_awarded"] == 300

    suspended = fixtures.suspend_site(grocery_id)
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        api_client.post_purchase_transaction(
            scenario["second"]["id"],
            make_store_operator_headers(grocery_id),
        ),
        ApiErrorId.ERR_SITE_SUSPENDED.value,
    )


def test_a_refused_post_leaves_both_transaction_dimensions_untouched():
    """The basket the suspension refused keeps its recorded state and the
    member's balance still reflects only the first basket.

    PRD: "A basket comes into being as `RECORDED` on the posting dimension and
    `NOT_ACCRUED` on the accrual dimension, and the two advance independently
    thereafter even when a single request moves both."

    Design: Difficulty/cross_entity_state_dependency/purchase_posting_gated_by_grocery_site_active_state
    """
    scenario = _two_recorded_baskets_at_one_lane()
    grocery_id = scenario["grocery"]["id"]
    member_id = scenario["member"]["id"]

    fixtures.post_basket(scenario["first"]["id"], grocery_id)
    fixtures.suspend_site(grocery_id)
    validate_error(
        api_client.post_purchase_transaction(
            scenario["second"]["id"],
            make_store_operator_headers(grocery_id),
        ),
        ApiErrorId.ERR_SITE_SUSPENDED.value,
    )

    first = validate_success(
        api_client.get_purchase_transaction(scenario["first"]["id"], ADMIN)
    )
    assert first["posting_status"] == "POSTED"
    assert first["accrual_status"] == "ACCRUED"

    second = validate_success(
        api_client.get_purchase_transaction(scenario["second"]["id"], ADMIN)
    )
    assert second["posting_status"] == "RECORDED"
    assert second["accrual_status"] == "NOT_ACCRUED"

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 300

    _data, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "ACCRUAL"}
        )
    )
    assert meta["total_count"] == 1
