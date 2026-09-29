"""Qualified-lot counting and the seasonal build-ahead quota, both at their bounds.

PRD.md section 3.2 states lot qualification as a conjunction of eight clauses whose
comparison directions are individually pinned, including a minimum shot mass that is
rounded to three decimals *before* the comparison runs. PRD.md section 3.3 consumes
that count on the release gate and on the two unblocking edges. PRD.md section 3.7
then floors the build-ahead cap, counts the committed quantity as a live aggregate
rather than a counter, and orders the window test strictly ahead of the quota test.
"""

from test_helpers import (
    DEFAULT_ZONE_CODE,
    ApiErrorId,
    advance_unit_to_sellable,
    assert_at_most_scale,
    assert_instant_equals,
    create_demand_bucket,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    get_success_data,
    release_storage_payload,
    reserve_charge,
    run_cycle_to_demold,
    schedule_cycle,
    set_clock,
    store_payload,
    store_unit,
    warehouse_version,
    zone,
    validate_error,
)

# Every attribute of a lot that the PM-CVI model below accepts, so a single key can
# be overridden to build a one-clause near miss.
_P5_QUALIFYING_LOT = {
    "resin_grade": "HDPE_XL",
    "melt_index_g10min": 4.0,
    "color_code": "SEAFOAM",
    "color_delta_e": 0.5,
    "additive_package_code": "UV12",
    "regrind_pct_by_mass": 10.0,
    "cost_cents_per_kg": 200,
    "received_kg": 50.0,
    "expires_on": "2027-12-31",
}


def _p5_near_miss(**broken):
    """Create a lot that qualifies on every clause except the ones overridden."""
    return create_resin_lot(**dict(_P5_QUALIFYING_LOT, **broken))


def _p5_exact(actual, expected, places, label):
    """Assert a derived decimal is stored at its declared scale and exact value."""
    assert_at_most_scale(actual, places, label)
    assert dec(actual) == dec(expected), f"{label}: expected {expected}, got {actual!r}"


def _p5_charge_cycle(ctx, cycle, lot, **charge_overrides):
    """Attach one reserved charge to ``cycle`` and make it the context's cycle."""
    ctx["molding_cycle"] = cycle
    ctx["molding_cycle_id"] = cycle["id"]
    return reserve_charge(ctx, cycle, lot, **charge_overrides)


def _p5_two_hull_plant():
    """A plant whose model is 1.2000 cube into a 100.0000 cube single-zone site.

    The default mould is two-cavity, so one demould mints two hulls of the same
    model — the pair PRD.md section 3.7 needs for a nest group and for a quota that
    admits one hull and refuses the other.
    """
    return create_plant_baseline(
        model_overrides={"gross_cube_m3": 1.2, "nest_factor": 0.5},
        warehouse_overrides={
            "footprint_capacity_cube_m3": 100.0,
            "zones": [zone(DEFAULT_ZONE_CODE, 100.0)],
        },
    )


def _p5_two_sellable_hulls(ctx, order, lot):
    """Drive one two-cavity cycle to demould and pass both hulls to SELLABLE."""
    cycle = schedule_cycle(ctx, order)
    _p5_charge_cycle(ctx, cycle, lot)
    run_cycle_to_demold(ctx)
    hulls = ctx["finished_units"]
    assert len(hulls) == 2, f"a two-cavity mould mints two hulls, got {len(hulls)}"
    return [advance_unit_to_sellable(ctx, hull) for hull in hulls]


def test_qualified_lot_count_admits_only_the_lot_on_every_inclusive_bound(
    api, admin_headers
):
    """Five one-clause misses and an 18.999 kg lot count zero; a 19.000 kg edge lot counts one.

    PRD.md section 3.2 states the predicate as a conjunction with each comparison
    direction pinned: "A lot qualifies for a hull model when *all* of the following
    hold: the lot's `status` is `AVAILABLE`, so `QUARANTINED`, `EXPIRED` and
    `DEPLETED` lots never qualify; the lot's `resin_grade` exactly equals the model's
    `resin_grade`; the lot's `additive_package_code` exactly equals the model's
    `required_additive_package_code`; either the lot's `color_code` exactly equals the
    model's `master_color_code` *or* the lot's `color_delta_e` is at most the model's
    `max_color_delta_e`, a lot sitting exactly at the maximum delta-E qualifying; the
    lot's `melt_index_g10min` lies inside the model's band with *both* bounds
    inclusive, from `min_melt_index_g10min` to `max_melt_index_g10min`; the lot's
    `regrind_pct_by_mass` is at most the model's `max_regrind_pct`, a lot exactly at
    the ceiling qualifying; the lot's `expires_on` is on or after the logical clock's
    calendar date, so a lot expiring today still qualifies; and the lot's
    `available_kg` is at least the model's minimum shot mass, computed as
    `nominal_charge_kg` multiplied by one minus `charge_tolerance_pct` divided by 100,
    with that threshold rounded to three decimals *before* the comparison."  PRD.md
    section 3.3 spends that count twice: "when the qualified-lot count is zero the
    order moves `DRAFT` to `BLOCKED_RESIN` with `blocked_reason`
    `NO_QUALIFIED_RESIN_LOT`", and "An order in `BLOCKED_RESIN` for which a qualified
    lot has returned to `AVAILABLE` moves to `READY_TO_SCHEDULE` with `blocked_reason`
    cleared **only if** the target site's `posture` is not `FROZEN`".  PRD.md section
    3.2 makes lot intake one of those unblocking events: "Intake is itself an
    unblocking event: every order sitting in `BLOCKED_RESIN` that this new lot
    qualifies for is moved to `READY_TO_SCHEDULE`, or to `BLOCKED_WAREHOUSE` when that
    order's target site posture is `FROZEN`."

    Design: Corner/calculations/calc_aggregation_qualified_lot_count_every_clause_at_its_inclusive_bound
    """
    ctx = create_plant_baseline(
        model_overrides={
            "resin_grade": "HDPE_XL",
            "master_color_code": "SEAFOAM",
            "max_color_delta_e": 1.5,
            "required_additive_package_code": "UV12",
            "max_regrind_pct": 30.0,
            "min_melt_index_g10min": 2.5,
            "max_melt_index_g10min": 6.0,
            "nominal_charge_kg": 20.0,
            "charge_tolerance_pct": 5.0,
        },
        mold_overrides={"cavity_count": 1, "nominal_charge_kg": 20.0},
    )
    # One broken conjunct each: the grade enum, the additive string, both branches of
    # the colour clause at once, the top of the melt band, and the regrind ceiling.
    _p5_near_miss(resin_grade="MDPE")
    _p5_near_miss(additive_package_code="UV11")
    _p5_near_miss(color_code="TIDEWATER", color_delta_e=1.51)
    _p5_near_miss(melt_index_g10min=6.01)
    _p5_near_miss(regrind_pct_by_mass=30.01)

    site = api.read_entity("get_warehouse", ctx["warehouse_id"], admin_headers)
    assert site["posture"] == "NORMAL", (
        "an empty site is NORMAL, so nothing in this test can divert an order to "
        f"BLOCKED_WAREHOUSE, got {site['posture']}"
    )

    order = create_production_order(ctx, ordered_qty=1, release=False)
    blocked = get_success_data(api.release_production_order(order["id"], admin_headers))
    assert blocked["status"] == "BLOCKED_RESIN", (
        "a zero qualified-lot count is a soft outcome on the release gate, not an "
        f"error, got {blocked['status']}"
    )
    assert blocked["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT", (
        f"expected NO_QUALIFIED_RESIN_LOT, got {blocked['blocked_reason']!r}"
    )

    # round(20.000 * (1 - 5.00 / 100), 3) = 19.000, so 18.999 kg is one thousandth short.
    _p5_near_miss(received_kg=18.999)
    still_blocked = api.read_entity("get_production_order", order["id"], admin_headers)
    assert still_blocked["status"] == "BLOCKED_RESIN", (
        "the threshold is rounded to three decimals before the at-least comparison, "
        f"so 18.999 does not reach 19.000, got {still_blocked['status']}"
    )
    assert still_blocked["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT", (
        f"expected NO_QUALIFIED_RESIN_LOT, got {still_blocked['blocked_reason']!r}"
    )

    # Every remaining clause sits exactly on its own inclusive bound at once: the
    # colour differs from the master but delta-E equals the maximum, the melt index
    # equals the bottom of the band, the regrind equals the ceiling, the expiry equals
    # the clock's calendar date, and the mass equals the rounded threshold.
    edge = _p5_near_miss(
        color_code="TIDEWATER",
        color_delta_e=1.5,
        melt_index_g10min=2.5,
        regrind_pct_by_mass=30.0,
        received_kg=19.0,
        expires_on="2026-08-01",
    )
    assert edge["status"] == "AVAILABLE", (
        f"a lot expiring on the clock date is not expired, got {edge['status']}"
    )
    _p5_exact(edge["available_kg"], "19.000", 3, "available_kg on intake")

    unblocked = api.read_entity("get_production_order", order["id"], admin_headers)
    assert unblocked["status"] == "READY_TO_SCHEDULE", (
        "the single edge lot qualifies, so the count rose to 1 and the order "
        f"unblocked, got {unblocked['status']}"
    )
    assert unblocked["blocked_reason"] is None, (
        f"blocked_reason is cleared on unblocking, got {unblocked['blocked_reason']!r}"
    )


def test_build_ahead_cap_floors_then_reverses_when_storage_is_released(
    api, admin_headers, planner_headers
):
    """A forecast of 3 at 60.00 percent caps at 1, and releasing the stored hull frees it.

    PRD.md section 3.7: "A bucket's `build_ahead_cap_qty` is the floor of
    `forecast_qty` multiplied by `build_ahead_cap_pct` divided by 100. Its
    `build_ahead_committed_qty` is the count of hulls whose `demand_bucket_id` is this
    bucket, whose `build_status` is `SELLABLE` and whose `logistics_status` is `STORED`
    or `LOADED`. The admission test at store time is applied to the post-increment
    count: when `build_ahead_committed_qty` plus 1 exceeds `build_ahead_cap_qty` the
    store is refused with `ERR_BUILD_AHEAD_CAP_EXCEEDED` (HTTP 409). Storing the hull
    that lands exactly *on* the cap is accepted; the next one is refused."  PRD.md
    section 3.1 confirms the flooring with its own worked pair: "Flooring is
    load-bearing: a `forecast_qty` of 25 at 60.00 caps at 15, and a `forecast_qty` of
    26 also caps at 15."  PRD.md section 3.7 then makes the release reverse it: the
    hull "moves `STORED` to `UNALLOCATED`, its `warehouse_id`, `storage_zone_code`,
    `stored_at` and `demand_bucket_id` are cleared, its `stored_footprint_cube_m3` is
    set to 0.0000 and `is_zone_anchor` to false", and "The bucket's
    `build_ahead_committed_qty` is recomputed downward".  Because the count is an
    aggregate and not a counter — PRD.md section 2.10: "a demand bucket's
    `build_ahead_committed_qty` is always the count of its charged units that are
    `SELLABLE` and physically present (`STORED` or `LOADED`)" — the freed slot is
    reusable and the cap keeps biting on every later attempt.

    Design: Corner/calculations/calc_aggregation_build_ahead_cap_floors_then_reverses_on_release
    """
    ctx = _p5_two_hull_plant()
    lot = create_resin_lot()
    bucket = create_demand_bucket(ctx, forecast_qty=3, build_ahead_cap_pct=60.0)
    # floor(3 * 60.00 / 100) = floor(1.8) = 1; rounding half-up would give 2.
    assert bucket["build_ahead_cap_qty"] == 1, (
        f"expected a floored cap of 1, got {bucket['build_ahead_cap_qty']}"
    )
    assert bucket["build_ahead_committed_qty"] == 0, "a new bucket commits nothing"

    order = create_production_order(ctx, ordered_qty=2, demand_bucket_id=bucket["id"])
    first, second = _p5_two_sellable_hulls(ctx, order, lot)

    stored = store_unit(ctx, first)
    assert stored["logistics_status"] == "STORED", (
        "0 + 1 does not exceed the cap of 1, so the hull landing exactly on the cap "
        f"is admitted, got {stored['logistics_status']}"
    )
    assert stored["storage_zone_code"] == DEFAULT_ZONE_CODE, (
        f"the site's only zone is chosen, got {stored['storage_zone_code']!r}"
    )
    assert stored["is_zone_anchor"] is True, (
        "the first hull of its site-zone-model group opens the nest group, got "
        f"{stored['is_zone_anchor']!r}"
    )
    _p5_exact(stored["stored_footprint_cube_m3"], "1.2000", 4, "anchor footprint")
    assert stored["demand_bucket_id"] == bucket["id"], (
        "demand_bucket_id is copied from the producing order at storage time, got "
        f"{stored['demand_bucket_id']!r}"
    )

    at_cap = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert at_cap["build_ahead_committed_qty"] == 1, (
        f"one physically present SELLABLE hull counts, got {at_cap['build_ahead_committed_qty']}"
    )

    validate_error(
        api.store_finished_unit(
            second["id"],
            store_payload(warehouse_version(ctx["warehouse_id"])),
            planner_headers,
        ),
        ApiErrorId.BUILD_AHEAD_CAP_EXCEEDED,
    )
    refused = api.read_entity("get_finished_unit", second["id"], planner_headers)
    assert refused["logistics_status"] == "UNALLOCATED", (
        f"the refused hull never left UNALLOCATED, got {refused['logistics_status']}"
    )
    _p5_exact(refused["stored_footprint_cube_m3"], "0.0000", 4, "refused hull footprint")

    released = get_success_data(
        api.release_storage(
            first["id"],
            release_storage_payload("pulled for a dealer demo, freeing the seasonal quota"),
            planner_headers,
        )
    )
    assert released["logistics_status"] == "UNALLOCATED", (
        f"expected UNALLOCATED, got {released['logistics_status']}"
    )
    for field in ("warehouse_id", "storage_zone_code", "stored_at", "demand_bucket_id"):
        assert released[field] is None, (
            f"release-storage clears {field}, got {released[field]!r}"
        )
    _p5_exact(released["stored_footprint_cube_m3"], "0.0000", 4, "released footprint")
    assert released["is_zone_anchor"] is False, (
        f"the anchor flag is cleared on release, got {released['is_zone_anchor']!r}"
    )

    freed = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert freed["build_ahead_committed_qty"] == 0, (
        "the count is recomputed downward from the surviving stored hulls, got "
        f"{freed['build_ahead_committed_qty']}"
    )

    # No follower occupied the group — the second hull had been refused — so no anchor
    # is promoted and the site's committed cube really does fall to zero.
    empty_site = api.read_entity("get_warehouse", ctx["warehouse_id"], planner_headers)
    _p5_exact(empty_site["committed_cube_m3"], "0.0000", 4, "committed cube after release")
    _p5_exact(empty_site["utilization_pct"], "0.00", 2, "utilization after release")
    assert empty_site["posture"] == "NORMAL", f"expected NORMAL, got {empty_site['posture']}"

    admitted = store_unit(ctx, second)
    assert admitted["logistics_status"] == "STORED", (
        "the freed slot is reusable because the quota is an aggregate, not a "
        f"once-per-unit allowance, got {admitted['logistics_status']}"
    )
    assert admitted["is_zone_anchor"] is True, (
        "the group was emptied, so this hull opens a new one and pays the full cube, "
        f"got {admitted['is_zone_anchor']!r}"
    )
    _p5_exact(admitted["stored_footprint_cube_m3"], "1.2000", 4, "new anchor footprint")

    refilled = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert refilled["build_ahead_committed_qty"] == 1, (
        f"the bucket is back at its cap, got {refilled['build_ahead_committed_qty']}"
    )

    validate_error(
        api.store_finished_unit(
            first["id"],
            store_payload(warehouse_version(ctx["warehouse_id"])),
            planner_headers,
        ),
        ApiErrorId.BUILD_AHEAD_CAP_EXCEEDED,
    )

    final_site = api.read_entity("get_warehouse", ctx["warehouse_id"], planner_headers)
    _p5_exact(final_site["committed_cube_m3"], "1.2000", 4, "final committed cube")
    # 1.2000 / 100.0000 * 100 = 1.20 exactly.
    _p5_exact(final_site["utilization_pct"], "1.20", 2, "final utilization")
    assert final_site["posture"] == "NORMAL", f"expected NORMAL, got {final_site['posture']}"


def test_build_ahead_window_bounds_are_inclusive_and_checked_before_the_quota(
    api, planner_headers
):
    """The same store is WINDOW_MISMATCH on 08-31, admitted on 09-01, CAP_EXCEEDED on 09-30 and WINDOW_MISMATCH on 10-01.

    PRD.md section 3.7 fixes both the inclusivity and the ordering: "Four gates apply
    in priority order. First, the site's `posture` must not be `FROZEN`, otherwise
    `ERR_WAREHOUSE_FROZEN` (HTTP 409). Second, when the producing order names a
    `demand_bucket_id`, the logical clock's calendar date must lie inside that bucket's
    window from `window_start_on` through `window_end_on`, **both bounds inclusive**,
    otherwise `ERR_BUILD_AHEAD_WINDOW_MISMATCH` (HTTP 409) — and when the date is out
    of window the quota check is never reached at all. Third, an eligible zone must
    exist, otherwise `ERR_NO_ELIGIBLE_ZONE` (HTTP 409). Fourth, the bucket's quota and
    then the site's total cube must both hold."  PRD.md section 2.5 says which part of
    the clock is read: "Dates supplied as `YYYY-MM-DD` — a resin lot's `expires_on`, a
    demand bucket's `window_start_on` and `window_end_on` — are compared against the
    calendar date of the logical clock in UTC, never against its time of day."  PRD.md
    section 3.7 supplies the stamp: storing "stamps `stored_at` from the logical clock".

    Because the window is consulted first, a bucket already at its cap reports
    ERR_BUILD_AHEAD_WINDOW_MISMATCH one day past `window_end_on` and
    ERR_BUILD_AHEAD_CAP_EXCEEDED on `window_end_on` itself — the identical request
    changes error id purely because the clock crossed midnight.

    Design: Corner/calculations/calc_variant_selection_build_ahead_window_boundary_then_out_of_window
    """
    ctx = _p5_two_hull_plant()
    lot = create_resin_lot()
    bucket = create_demand_bucket(
        ctx,
        forecast_qty=3,
        build_ahead_cap_pct=60.0,
        window_start_on="2026-09-01",
        window_end_on="2026-09-30",
    )
    assert bucket["build_ahead_cap_qty"] == 1, (
        f"floor(3 * 60.00 / 100) = 1, got {bucket['build_ahead_cap_qty']}"
    )

    order = create_production_order(ctx, ordered_qty=2, demand_bucket_id=bucket["id"])
    first, second = _p5_two_sellable_hulls(ctx, order, lot)

    # One day before the window opens, with the quota entirely free.
    set_clock("2026-08-31T12:00:00Z")
    validate_error(
        api.store_finished_unit(
            first["id"],
            store_payload(warehouse_version(ctx["warehouse_id"])),
            planner_headers,
        ),
        ApiErrorId.BUILD_AHEAD_WINDOW_MISMATCH,
    )
    untouched = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert untouched["build_ahead_committed_qty"] == 0, (
        "the quota would have admitted this hull, so the refusal came from the window "
        f"gate alone, got {untouched['build_ahead_committed_qty']}"
    )

    # Midnight on window_start_on: the lower bound is inclusive.
    set_clock("2026-09-01T00:00:00Z")
    stored = store_unit(ctx, first)
    assert stored["logistics_status"] == "STORED", (
        f"window_start_on itself is in window, got {stored['logistics_status']}"
    )
    assert_instant_equals(stored["stored_at"], "2026-09-01T00:00:00Z", "stored_at")
    assert stored["demand_bucket_id"] == bucket["id"], (
        f"demand_bucket_id is copied from the order, got {stored['demand_bucket_id']!r}"
    )
    assert stored["is_zone_anchor"] is True, (
        f"the first hull of the group anchors it, got {stored['is_zone_anchor']!r}"
    )
    _p5_exact(stored["stored_footprint_cube_m3"], "1.2000", 4, "anchor footprint")

    at_cap = api.read_entity("get_demand_forecast_bucket", bucket["id"], planner_headers)
    assert at_cap["build_ahead_committed_qty"] == 1, (
        f"expected 1, got {at_cap['build_ahead_committed_qty']}"
    )
    assert at_cap["build_ahead_cap_qty"] == 1, (
        f"the cap is unchanged by a store, got {at_cap['build_ahead_cap_qty']}"
    )

    # The last second of window_end_on is still in window, so the quota is what bites.
    set_clock("2026-09-30T23:59:59Z")
    validate_error(
        api.store_finished_unit(
            second["id"],
            store_payload(warehouse_version(ctx["warehouse_id"])),
            planner_headers,
        ),
        ApiErrorId.BUILD_AHEAD_CAP_EXCEEDED,
    )

    # One second later the calendar date has left the window and the same request,
    # against the same full bucket, reports the window failure instead.
    set_clock("2026-10-01T00:00:00Z")
    validate_error(
        api.store_finished_unit(
            second["id"],
            store_payload(warehouse_version(ctx["warehouse_id"])),
            planner_headers,
        ),
        ApiErrorId.BUILD_AHEAD_WINDOW_MISMATCH,
    )

    refused = api.read_entity("get_finished_unit", second["id"], planner_headers)
    assert refused["logistics_status"] == "UNALLOCATED", (
        f"three refused stores left the hull UNALLOCATED, got {refused['logistics_status']}"
    )
    site = api.read_entity("get_warehouse", ctx["warehouse_id"], planner_headers)
    _p5_exact(site["committed_cube_m3"], "1.2000", 4, "committed cube after the four attempts")
    _p5_exact(site["utilization_pct"], "1.20", 2, "utilization after the four attempts")
