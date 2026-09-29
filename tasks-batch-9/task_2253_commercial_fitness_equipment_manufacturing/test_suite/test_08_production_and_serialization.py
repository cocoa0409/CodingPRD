"""Serialisation at production complete and the derived asset support window."""
from test_helpers import (
    assert_instant,
    add_order_line,
    add_partner_ctx,
    arrive_ctx,
    complete_install_ctx,
    complete_production_ctx,
    confirm_ctx,
    list_all,
    quote_ctx,
    quote_order,
    read_model_revision,
    read_order,
    read_order_line,
    read_serialized_asset,
    schedule_install_ctx,
    set_logical_clock,
    setup_configured_order,
    setup_released_revision,
    sunset_revision,
    validate_paginated,
    validate_success,
)

INSTALL_DAY_START = "2027-06-01T15:00:00Z"
INSTALL_DAY_END = "2027-06-01T19:00:00Z"


def _staged_k900_order():
    """One institutional connected rower, built but not yet installed."""
    ctx = setup_configured_order(
        preset="K900", quantity=1,
        facility_overrides={"account_name": "Summit Institutional Aquatics",
                            "freight_zone": "Z1"},
    )
    quote_ctx(ctx)
    confirm_ctx(ctx)
    complete_production_ctx(ctx)
    return ctx


def _sunset_then_install(ctx, sunset_at):
    """Announce the sunset, then install the built unit on 1 June 2027."""
    set_logical_clock(sunset_at)
    ctx["revision"] = sunset_revision(ctx["revision"]["id"])
    set_logical_clock(INSTALL_DAY_START)
    add_partner_ctx(ctx, name="Summit Service Co", certified_categories=["CONNECTED"],
                    training_current_until="2028-12-31T00:00:00Z")
    schedule_install_ctx(ctx, window_start=INSTALL_DAY_START,
                         window_end=INSTALL_DAY_END, estimated_labor_hours=3.0)
    arrive_ctx(ctx)
    return complete_install_ctx(ctx, actual_labor_hours=3.0, punch_list_open_count=0)


def test_support_gap_days_discards_the_fraction_of_the_last_day(api):
    """A 269.625-day exposure is reported as 269 whole days.

    The PRD states that `support_gap_days` "is the number of whole days from
    `firmware_support_expires_at` to `warranty_expires_at`, discarding any
    fractional day, and floored at zero so it is never negative."

    Design: Difficulty/boundary_precision_check/asset_support_gap_days_floors_partial_day
    """
    ctx = _staged_k900_order()
    assert read_order(ctx["order"]["id"])["quoted_total_cents"] == 728_100

    job = _sunset_then_install(ctx, sunset_at="2026-09-05T00:00:00Z")

    assert job["status"] == "COMPLETED"
    revision = read_model_revision(ctx["revision"]["id"])
    assert revision["status"] == "SUNSET_ANNOUNCED"
    assert_instant(revision["firmware_support_until"], "2031-09-04T00:00:00Z", "firmware_support_until")
    asset = read_serialized_asset(ctx["asset"]["id"])
    assert asset["status"] == "IN_SERVICE"
    assert_instant(asset["warranty_starts_at"], INSTALL_DAY_START, "warranty_starts_at")
    assert_instant(asset["warranty_expires_at"], "2032-05-30T15:00:00Z", "warranty_expires_at")
    assert_instant(asset["firmware_support_expires_at"], "2031-09-04T00:00:00Z", "firmware_support_expires_at")
    assert asset["connectivity_support_status"] == "SUPPORT_GAP"
    assert asset["support_gap_days"] == 269
    assert asset["support_gap_days"] != 270
    assert isinstance(asset["support_gap_days"], int)
    assert asset["serial_number"] == "K900-R1-00001"
    assert asset["sequence_no"] == 1
    order = read_order(ctx["order"]["id"])
    assert order["final_total_cents"] == 728_100
    assert order["quoted_total_cents"] == 728_100


def test_a_gap_shorter_than_one_whole_day_is_reported_as_zero(api):
    """Fifteen hours of exposure floor to zero while the verdict stays SUPPORT_GAP.

    The PRD states that the status is "`SUNSET_TRACKED` when that horizon is at or
    after `warranty_expires_at`, or `SUPPORT_GAP` when it falls strictly before",
    and that the day count discards "any fractional day".

    Design: Difficulty/boundary_precision_check/asset_support_gap_days_floors_partial_day
    """
    ctx = _staged_k900_order()

    _sunset_then_install(ctx, sunset_at="2027-06-01T00:00:00Z")

    revision = read_model_revision(ctx["revision"]["id"])
    assert_instant(revision["firmware_support_until"], "2032-05-30T00:00:00Z", "firmware_support_until")
    asset = read_serialized_asset(ctx["asset"]["id"])
    assert_instant(asset["warranty_expires_at"], "2032-05-30T15:00:00Z", "warranty_expires_at")
    assert_instant(asset["firmware_support_expires_at"], "2032-05-30T00:00:00Z", "firmware_support_expires_at")
    assert asset["connectivity_support_status"] == "SUPPORT_GAP", (
        "the horizon still falls strictly before the warranty end"
    )
    assert asset["support_gap_days"] == 0
    assert asset["support_gap_days"] != 1


def test_serial_numbers_and_sequence_numbers_are_minted_in_line_order(
    api, order_planner_headers
):
    """Three units across two lines take sequence numbers one, two and three.

    The PRD states that "the counter is consumed in a fixed order: lines are
    processed by their `created_at` ascending, and within a line the units are
    numbered by ascending unit index" and that the serial is composed "from the
    revision's `revision_code`, a hyphen, and `sequence_no` zero-padded to five
    digits."

    Design: Corner/entities/serialized_asset_serial_number_and_sequence_no_are_system_derived
    """
    ctx = setup_configured_order(preset="T900", quantity=2)
    first_line = ctx["line"]
    second_line = add_order_line(ctx, quantity=1, layout_zone_label="Cardio Zone B")
    quote_ctx(ctx)
    assert ctx["order"]["line_subtotal_cents"] == 1_526_241
    assert ctx["order"]["quoted_total_cents"] == 1_680_929
    confirm_ctx(ctx)

    order = validate_success(api.complete_order_production(ctx["order"]["id"],
                                                           order_planner_headers))

    assert order["fulfillment_status"] == "STAGED"
    assets, meta = validate_paginated(
        api.list_serialized_assets(order_planner_headers,
                                   params={"facility_id": ctx["facility"]["id"]})
    )
    assert meta["total_count"] == 3
    by_sequence = sorted(assets, key=lambda asset: asset["sequence_no"])
    assert [asset["sequence_no"] for asset in by_sequence] == [1, 2, 3]
    assert [asset["serial_number"] for asset in by_sequence] == [
        "T900-R1-00001", "T900-R1-00002", "T900-R1-00003",
    ]
    assert [asset["order_line_id"] for asset in by_sequence] == [
        first_line["id"], first_line["id"], second_line["id"],
    ]
    for asset in by_sequence:
        assert asset["status"] == "BUILT"
        assert asset["connectivity_support_status"] == "NOT_APPLICABLE"
        assert asset["warranty_starts_at"] is None
        assert asset["installed_firmware_release_id"] is None
    assert read_order_line(first_line["id"])["assets_minted_count"] == 2
    assert read_order_line(second_line["id"])["assets_minted_count"] == 1


def test_support_window_reads_not_applicable_and_supported_side_by_side(
    api, order_planner_headers
):
    """One install, two verdicts: an unconnected unit and a never-sunset console.

    The PRD states that "If the model is not connected, `firmware_support_expires_at`
    is null, `support_gap_days` is 0, and `connectivity_support_status` is
    `NOT_APPLICABLE`" and that otherwise, with a null `firmware_support_until`,
    "`firmware_support_expires_at` is null, `support_gap_days` is 0, and the status
    is `SUPPORTED`, an open-ended commitment."

    Design: Corner/calculations/support_window_derives_not_applicable_and_supported_baselines
    """
    ctx = setup_configured_order(preset="T900", quantity=1)
    console = setup_released_revision(
        "C700", rig_overrides={"name": "RIG-B", "parallel_station_count": 2,
                               "supported_duty_classes": ["FULL_COMMERCIAL"]},
    )
    add_order_line(ctx, revision=console["revision"], model=console["model"],
                   quantity=1, layout_zone_label="Connected Row")
    quote_ctx(ctx)
    assert ctx["order"]["quoted_total_cents"] == 1_199_310
    confirm_ctx(ctx)
    complete_production_ctx(ctx)
    add_partner_ctx(ctx)
    schedule_install_ctx(ctx)
    arrive_ctx(ctx)

    complete_install_ctx(ctx, actual_labor_hours=4.5, punch_list_open_count=0)

    treadmill = list_all(api.list_serialized_assets,
                         {"model_revision_id": ctx["revision"]["id"]})[0]
    rower = list_all(api.list_serialized_assets,
                     {"model_revision_id": console["revision"]["id"]})[0]
    assert treadmill["serial_number"] == "T900-R1-00001"
    assert treadmill["status"] == "IN_SERVICE"
    assert treadmill["connectivity_support_status"] == "NOT_APPLICABLE"
    assert treadmill["firmware_support_expires_at"] is None
    assert treadmill["support_gap_days"] == 0
    assert rower["serial_number"] == "C700-R1-00001"
    assert rower["status"] == "IN_SERVICE"
    assert rower["connectivity_support_status"] == "SUPPORTED"
    assert rower["firmware_support_expires_at"] is None
    assert rower["support_gap_days"] == 0
    assert rower["installed_firmware_release_id"] is None, (
        "certifying a build is not loading it"
    )
    for asset in (treadmill, rower):
        assert_instant(asset["warranty_starts_at"], "2026-08-01T00:00:00Z", "warranty_starts_at")
        assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")
    order = read_order(ctx["order"]["id"])
    assert order["quoted_total_cents"] == 1_199_310
    assert order["final_total_cents"] == 1_199_310


def test_production_mints_one_asset_per_unit_and_nothing_for_a_voided_line(
    api, order_planner_headers
):
    """The voided line mints no assets and vanishes from the re-quote.

    The PRD states that "Finally each `ACTIVE` line's `assets_minted_count` is set
    to the number of units minted from it" and that each asset's
    "`connectivity_support_status` is initialised at this point: `NOT_APPLICABLE`
    for units of a model that is not connected".

    Design: Corner/endpoints/production_completion_mints_one_asset_per_unit_of_each_active_line
    """
    ctx = setup_configured_order(preset="T900", quantity=2)
    kept_line = ctx["line"]
    doomed_line = add_order_line(ctx, quantity=1, finish_codes=["CLUB_RED"],
                                 layout_zone_label="Cardio Zone B")
    quote_ctx(ctx)
    assert ctx["order"]["quoted_total_cents"] == 1_688_879

    voided = validate_success(api.void_order_line(doomed_line["id"],
                                                  order_planner_headers))

    assert voided["status"] == "VOIDED"
    after_void = read_order(ctx["order"]["id"])
    assert after_void["billing_status"] == "UNQUOTED"
    assert after_void["line_subtotal_cents"] == 1_017_494
    assert float(after_void["chargeable_weight_kg"]) == 425.0
    requoted = quote_order(ctx["order"]["id"])
    assert requoted["quoted_total_cents"] == 1_120_619
    ctx["order"] = requoted
    confirm_ctx(ctx)

    order = validate_success(api.complete_order_production(ctx["order"]["id"],
                                                           order_planner_headers))

    assert order["fulfillment_status"] == "STAGED"
    assert order["config_status"] == "CONFIRMED"
    kept_assets, kept_meta = validate_paginated(
        api.list_serialized_assets(order_planner_headers,
                                   params={"order_line_id": kept_line["id"]})
    )
    assert kept_meta["total_count"] == 2
    assert [asset["sequence_no"] for asset in kept_assets] == [1, 2]
    for asset in kept_assets:
        assert asset["status"] == "BUILT"
        assert asset["facility_id"] == ctx["facility"]["id"]
        assert asset["warranty_starts_at"] is None
        assert asset["connectivity_support_status"] == "NOT_APPLICABLE"
    _, voided_meta = validate_paginated(
        api.list_serialized_assets(order_planner_headers,
                                   params={"order_line_id": doomed_line["id"]})
    )
    assert voided_meta["total_count"] == 0
    assert read_order_line(kept_line["id"])["assets_minted_count"] == 2
    doomed = read_order_line(doomed_line["id"])
    assert doomed["assets_minted_count"] == 0
    assert doomed["status"] == "VOIDED"
