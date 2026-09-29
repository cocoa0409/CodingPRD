"""Two contended calendars with opposite interval semantics, probed at their edges.

Each test translates one instance of the difficulty rule ``resource_temporal_overlap``.
"""
from test_helpers import (
    ApiErrorId,
    BUYER_HEADERS,
    PLANNER_HEADERS,
    activate_overlay,
    adopt_item,
    create_overlay,
    get_item,
    get_month,
    get_overlay,
    get_success_data,
    localization_overlay_payload,
    month_version,
    propose_item,
    receipt_commitment_payload,
    setup_single_month_approved_plan,
    validate_error,
    validate_success,
)


def _navy_option_bought_by_the_thousand():
    scenario = setup_single_month_approved_plan()
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-CARRY-W", color_code="NAVY",
                        lifecycle_stage="CARRYOVER", unit_cost_cents=1000,
                        retail_price_cents=2900, prior_season_sell_through_bps=7100)
    return scenario, item


def _order(api, scenario, item, units, start, end):
    month_id = scenario["m1"]["id"]
    payload = receipt_commitment_payload(
        month_id, item["id"], scenario["vendor"]["id"], month_version(month_id),
        units=units, unit_cost_cents=1000,
        ship_window_start=start, ship_window_end=end,
    )
    return api.create_receipt_commitment(payload, BUYER_HEADERS)


def test_windows_that_merely_touch_do_not_overlap_and_may_double_the_capacity(api):
    """Half-open ship windows make contiguity free: 7000 + 7000 clears a 12000 ceiling.

    PRD: "a ship window runs from `ship_window_start` inclusive to `ship_window_end` exclusive,
    and two windows overlap when the existing window's start is strictly before the candidate's
    end and the candidate's start is strictly before the existing window's end. Windows that
    merely touch -- where one ends exactly when the other starts -- do not overlap and are
    always permitted." The second order starts at the exact instant the first ends, so the first
    contributes nothing to its load even though the two together are 14000 units.

    Design: Difficulty/resource_temporal_overlap/vendor_ship_window_half_open_capacity_aggregate
    """
    scenario, item = _navy_option_bought_by_the_thousand()
    assert scenario["vendor"]["weekly_unit_capacity"] == 12000

    first = _order(api, scenario, item, 7000,
                   "2027-03-01T00:00:00Z", "2027-03-15T00:00:00Z")
    validate_success(first, expected_status=201)
    c1 = get_success_data(first)
    assert c1["commit_status"] == "PROPOSED"
    assert c1["cost_cents"] == 7_000_000
    assert c1["open_cost_cents"] == 7_000_000

    second = _order(api, scenario, item, 7000,
                    "2027-03-15T00:00:00Z", "2027-03-29T00:00:00Z")
    validate_success(second, expected_status=201)
    c2 = get_success_data(second)
    assert c2["cost_cents"] == 7_000_000

    month = get_month(scenario["m1"]["id"])
    assert month["otb_committed_cents"] == 0
    assert month["otb_open_cents"] == 18_200_000


def test_the_capacity_test_aggregates_every_overlapping_window(api):
    """A candidate well under capacity is refused because three legal windows sum against it.

    PRD: "The system collects every other commitment of the same vendor whose `commit_status` is
    `PROPOSED` or `COMMITTED` and whose window overlaps the candidate's, sums each one's `units`
    less its `cancelled_units`, and rejects the candidate when that sum plus the candidate's own
    `units` exceeds the vendor's `weekly_unit_capacity`. Overlap alone is legal; it is only the
    summed load against capacity that is enforced." The third order sits at the exact ceiling
    (7000 + 5000 == 12000, which is not greater than 12000) and is accepted; the fourth overlaps
    all three for a load of 19000 and is refused, though its own 6000 units are far below 12000.

    Design: Difficulty/resource_temporal_overlap/vendor_ship_window_half_open_capacity_aggregate
    """
    scenario, item = _navy_option_bought_by_the_thousand()
    month_id, vendor_id = scenario["m1"]["id"], scenario["vendor"]["id"]
    version_before = month_version(month_id)

    for units, start, end in (
        (7000, "2027-03-01T00:00:00Z", "2027-03-15T00:00:00Z"),
        (7000, "2027-03-15T00:00:00Z", "2027-03-29T00:00:00Z"),
        (5000, "2027-03-20T00:00:00Z", "2027-03-25T00:00:00Z"),
    ):
        validate_success(_order(api, scenario, item, units, start, end),
                         expected_status=201)

    refused = _order(api, scenario, item, 6000,
                     "2027-03-10T00:00:00Z", "2027-03-22T00:00:00Z")
    validate_error(refused, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED, expected_status=409)

    # Nothing else can explain the refusal: the buy is 6,000,000 against an untouched
    # 18,200,000 open balance, 6000 units clear the 200-unit minimum, and the category
    # open units 19000 + 6000 stay under the authorization's 40000.
    month = get_month(month_id)
    assert month["otb_committed_cents"] == 0
    assert month["otb_received_cents"] == 0
    assert month["otb_open_cents"] == 18_200_000
    assert month["version"] == version_before + 3

    rows = get_success_data(
        api.list_receipt_commitments(BUYER_HEADERS,
                                     params={"vendor_id": vendor_id, "limit": 50}))
    assert len(rows) == 3
    assert sorted(row["units"] for row in rows) == [5000, 7000, 7000]


MARCH_CLOCK = "2027-03-05T00:00:00Z"


def _plan_with_an_adopted_new_option():
    scenario = setup_single_month_approved_plan(clock=MARCH_CLOCK)
    item = propose_item(scenario["option_plan"]["id"], scenario["vendor"]["id"],
                        sku_code="DRSS-NEW-N", color_code="CORAL",
                        lifecycle_stage="NEW", unit_cost_cents=2500,
                        retail_price_cents=6900, prior_season_sell_through_bps=0)
    return scenario, adopt_item(item["id"])


def _overlay_attempt(api, scenario, **overrides):
    payload = localization_overlay_payload(
        scenario["plan_id"], scenario["store_cluster"]["id"], **overrides)
    return api.create_localization_overlay(payload, PLANNER_HEADERS)


def test_overlay_windows_of_one_type_need_eight_clear_days_and_draft_rows_count(api):
    """Closed windows plus a seven-day buffer on each side, partitioned by overlay type.

    PRD: "A candidate is rejected with `ERR_OVERLAY_WINDOW_CONFLICT` when any other overlay with
    the same `store_cluster_id` and the same `overlay_type`, whose `status` is `DRAFT` or
    `ACTIVE`, satisfies both of these: the candidate's `effective_start` is on or before that
    overlay's `effective_end` advanced by seven days, and that overlay's `effective_start` is on
    or before the candidate's `effective_end` advanced by seven days... a gap of eight days or
    more on either side is accepted." A one-day gap and a gap of exactly seven days both fail;
    eight days passes; and a `DRAFT` neighbour reserves the calendar exactly as an `ACTIVE` one
    does, while a different `overlay_type` may occupy byte-identical days.

    Design: Difficulty/resource_temporal_overlap/overlay_closed_window_separation_buffer
    """
    scenario, _item = _plan_with_an_adopted_new_option()
    first = create_overlay(scenario["plan_id"], scenario["store_cluster"]["id"],
                           overlay_type="CLIMATE",
                           effective_start="2027-03-01T00:00:00Z",
                           effective_end="2027-03-10T00:00:00Z",
                           unit_multiplier_bps=11000)
    assert first["status"] == "DRAFT"

    one_day_gap = _overlay_attempt(
        api, scenario, overlay_type="CLIMATE",
        effective_start="2027-03-11T00:00:00Z", effective_end="2027-03-20T00:00:00Z",
        unit_multiplier_bps=10800)
    validate_error(one_day_gap, ApiErrorId.ERR_OVERLAY_WINDOW_CONFLICT,
                   expected_status=409)

    exactly_seven_days = _overlay_attempt(
        api, scenario, overlay_type="CLIMATE",
        effective_start="2027-03-17T00:00:00Z", effective_end="2027-03-26T00:00:00Z",
        unit_multiplier_bps=10800)
    validate_error(exactly_seven_days, ApiErrorId.ERR_OVERLAY_WINDOW_CONFLICT,
                   expected_status=409)

    eight_days = _overlay_attempt(
        api, scenario, overlay_type="CLIMATE",
        effective_start="2027-03-18T00:00:00Z", effective_end="2027-03-27T00:00:00Z",
        unit_multiplier_bps=10800)
    validate_success(eight_days, expected_status=201)
    still_draft = get_success_data(eight_days)
    assert still_draft["status"] == "DRAFT"

    # The only neighbour of this candidate is the DRAFT row just created.
    blocked_by_draft = _overlay_attempt(
        api, scenario, overlay_type="CLIMATE",
        effective_start="2027-03-28T00:00:00Z", effective_end="2027-03-31T00:00:00Z",
        unit_multiplier_bps=10800)
    validate_error(blocked_by_draft, ApiErrorId.ERR_OVERLAY_WINDOW_CONFLICT,
                   expected_status=409)

    other_dimension = _overlay_attempt(
        api, scenario, overlay_type="DEMOGRAPHIC",
        effective_start="2027-03-01T00:00:00Z", effective_end="2027-03-10T00:00:00Z",
        unit_multiplier_bps=10500)
    validate_success(other_dimension, expected_status=201)
    assert get_success_data(other_dimension)["effective_start"].startswith("2027-03-01")


def test_draft_overlays_never_move_the_multiplier_and_activation_stacks_by_dimension(api):
    """The same rows that reserve the calendar are ignored by the calculation until ACTIVE.

    PRD: an overlay applies only when "its `status` is `ACTIVE`, and the logical clock falls
    inside its closed window", and "Overlays in `DRAFT`, `EXPIRED` or `SUPERSEDED` never
    participate". PRD then pins the stacking: "`CLIMATE` first, then `DEMOGRAPHIC`, then
    `VOLUME`... the running value is multiplied by that overlay's `unit_multiplier_bps`, divided
    by ten thousand, and **rounded half up before the next dimension is applied**". The NEW-item
    forecast is the `BETTER` benchmark 5500 times the cluster's 11500 sales index times the
    multiplier over one hundred million, rounded half up.

    Design: Difficulty/resource_temporal_overlap/overlay_closed_window_separation_buffer
    """
    scenario, item = _plan_with_an_adopted_new_option()
    cluster_id = scenario["store_cluster"]["id"]
    assert item["sell_through_basis"] == "NEW_ITEM_BASIS"
    assert item["effective_overlay_multiplier_bps"] == 10000
    assert item["sell_through_bps"] == 6325

    climate = create_overlay(scenario["plan_id"], cluster_id, overlay_type="CLIMATE",
                             effective_start="2027-03-01T00:00:00Z",
                             effective_end="2027-03-10T00:00:00Z",
                             unit_multiplier_bps=11000)
    demographic = create_overlay(scenario["plan_id"], cluster_id,
                                 overlay_type="DEMOGRAPHIC",
                                 effective_start="2027-03-01T00:00:00Z",
                                 effective_end="2027-03-10T00:00:00Z",
                                 unit_multiplier_bps=10500)
    unchanged = get_item(item["id"])
    assert unchanged["effective_overlay_multiplier_bps"] == 10000
    assert unchanged["sell_through_bps"] == 6325

    activate_overlay(climate["id"])
    assert get_overlay(climate["id"])["status"] == "ACTIVE"
    after_climate = get_item(item["id"])
    assert after_climate["effective_overlay_multiplier_bps"] == 11000
    assert after_climate["sell_through_bps"] == 6958

    activate_overlay(demographic["id"])
    after_both = get_item(item["id"])
    assert after_both["effective_overlay_multiplier_bps"] == 11550
    assert after_both["sell_through_bps"] == 7305
