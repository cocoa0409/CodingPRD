"""Optimistic concurrency on the two guarded writes and the completion thresholds.

Replayed lot and campaign versions are refused with 412 and write nothing, the
lot's token advances on child writes but never on a read, and the two
completion thresholds — variance tolerance and design throughput — are shown
firing one at a time on the same request shape.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_STALE_LOT_VERSION, ERR_STALE_RUN_VERSION
from test_helpers.assertions import (
    assert_activity_index,
    assert_mass,
    assert_one_decimal,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
)
from test_helpers.types import (
    ALLOC_RESERVED,
    CHARGE_ACTIVE,
    CHARGE_DERATED,
    CHARGE_SPENT,
    CERT_UNCERTIFIED,
    DIST_IN_TANK,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_UCO,
    LOT_ACCEPTED,
    LOT_PRETREAT_REQUIRED,
    LOT_TESTED,
    PRODUCT_RENEWABLE_DIESEL,
    PRODUCT_SAF,
    RUN_COMPLETED,
    TIER_HEAVY,
    TIER_NONE,
    UNIT_IDLE,
)

HEAVY_SAMPLE = {
    "ffa_pct": 6.00,
    "moisture_pct": 1.20,
    "insolubles_ppm": 1600,
    "phosphorus_ppm": 25,
    "sampled_at": "2026-08-02T00:00:00Z",
}


def test_a_retest_quoting_the_pre_test_lot_version_is_refused_then_accepted(api):
    """PRD §2.6: "Appending a quality test to a feedstock lot requires the non-optional field
    `expected_lot_version` in the request body, carrying the `version` of the lot as the client last
    observed it. If that value does not equal the lot's current `version`, the append is rejected
    with `ERR_STALE_LOT_VERSION` and HTTP 412."
    PRD §3.2: "Because a retest supersedes the earlier governing test, the same endpoint drives
    `TESTED → PRETREAT_REQUIRED` when a later sample dispositions `PRETREAT`, and
    `PRETREAT_REQUIRED → TESTED` when a later sample dispositions `PASS` — in the latter case
    `pretreatment_tier` returns to `NONE` and the fee returns to 0.00."

    Design: Corner/cross_cutting_complexity_layers/stale_lot_version_on_quality_test_returns_conflict
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.make_lot(api, supplier["id"], mass_mt=500.000)
    lot_v0 = lot["version"]
    fx.add_quality_test(api, lot["id"], lot_v0)

    validate_error(
        api.create_quality_test(
            lot["id"], f.quality_test_payload(lot_v0, **HEAVY_SAMPLE), ANALYST_HEADERS
        ),
        ERR_STALE_LOT_VERSION,
        412,
    )

    untouched = validate_success(api.get_feedstock_lot(lot["id"], ANALYST_HEADERS))
    assert untouched["status"] == LOT_TESTED, f"got {untouched['status']}"
    assert untouched["pretreatment_tier"] == TIER_NONE, f"got {untouched['pretreatment_tier']}"
    lot_v1 = untouched["version"]
    assert lot_v1 == lot_v0 + 1, f"only the first test wrote, got {lot_v1}"

    _, meta = validate_paginated(api.list_quality_tests(lot["id"], ANALYST_HEADERS))
    assert meta["total_count"] == 1, f"the refusal filed no sample, got {meta['total_count']}"

    retest = validate_success(
        api.create_quality_test(
            lot["id"], f.quality_test_payload(lot_v1, **HEAVY_SAMPLE), ANALYST_HEADERS
        ),
        201,
    )
    assert retest["lot_id"] == lot["id"]

    superseded = validate_success(api.get_feedstock_lot(lot["id"], ANALYST_HEADERS))
    assert superseded["status"] == LOT_PRETREAT_REQUIRED, f"got {superseded['status']}"
    assert superseded["pretreatment_tier"] == TIER_HEAVY, f"got {superseded['pretreatment_tier']}"
    assert superseded["version"] == lot_v1 + 1, f"got {superseded['version']}"

    both, both_meta = validate_paginated(api.list_quality_tests(lot["id"], ANALYST_HEADERS))
    assert both_meta["total_count"] == 2, f"got {both_meta['total_count']}"
    assert len(both) == 2, f"both samples are retained, got {len(both)}"


def test_a_second_allocation_quoting_the_stale_campaign_version_moves_no_blend(api):
    """PRD §2.6: "Creating a feedstock allocation against a campaign requires the non-optional field
    `expected_run_version` in the request body, carrying the campaign's `version` as the client last
    observed it. A mismatch against the campaign's current `version` is rejected with
    `ERR_STALE_RUN_VERSION` and HTTP 412."
    PRD §2.6: "Adding further allocations to a campaign that is still in planning is likewise
    legitimate and repeatable, and each allocation rewrites the campaign's reserved mass, its blend
    carbon intensity and its hydrogen requirement; a client working from a stale blend picture would
    silently move the carbon intensity another writer had just established."

    Design: Corner/cross_cutting_complexity_layers/stale_run_version_on_second_allocation_returns_conflict
    """
    supplier = fx.verified_supplier(api, feedstock_types=[FEEDSTOCK_UCO, FEEDSTOCK_TALLOW])
    lot_a = fx.accepted_lot(
        api, supplier["id"], mass_mt=200.000, attested_ci_gco2e_per_mj=32.50
    )
    lot_b = fx.accepted_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=200.000,
        attested_ci_gco2e_per_mj=24.90,
        purchase_price_usd_per_mt=880.00,
    )
    plant = fx.commissioned_unit(api)
    run = fx.make_run(api, plant["unit"]["id"], plant["charge"]["id"])
    rv1 = run["version"]
    fx.allocate(api, run["id"], lot_a["id"], 200.000, expected_version=rv1)

    validate_error(
        api.create_allocation(
            run["id"], f.allocation_payload(lot_b["id"], 200.000, rv1), TRADER_HEADERS
        ),
        ERR_STALE_RUN_VERSION,
        412,
    )

    refused = validate_success(api.get_processing_run(run["id"], TRADER_HEADERS))
    assert_mass(refused["reserved_mass_mt"], 200.000, "reserved_mass_mt")
    assert refused["blend_ci_gco2e_per_mj"] == 32.50, f"got {refused['blend_ci_gco2e_per_mj']}"
    rv2 = refused["version"]
    assert rv2 == rv1 + 1, f"only the first allocation wrote, got {rv2}"

    lot_b_after = validate_success(api.get_feedstock_lot(lot_b["id"], TRADER_HEADERS))
    assert_mass(lot_b_after["remaining_mass_mt"], 200.000, "remaining_mass_mt")
    assert_mass(lot_b_after["allocated_mass_mt"], 0.000, "allocated_mass_mt")

    second = validate_success(
        api.create_allocation(
            run["id"], f.allocation_payload(lot_b["id"], 200.000, rv2), TRADER_HEADERS
        ),
        201,
    )
    assert second["status"] == ALLOC_RESERVED, f"got {second['status']}"

    blended = validate_success(api.get_processing_run(run["id"], TRADER_HEADERS))
    assert_mass(blended["reserved_mass_mt"], 400.000, "reserved_mass_mt")
    assert blended["blend_ci_gco2e_per_mj"] == 28.70, f"got {blended['blend_ci_gco2e_per_mj']}"

    lines, lines_meta = validate_paginated(api.list_run_allocations(run["id"], TRADER_HEADERS))
    assert lines_meta["total_count"] == 2, f"got {lines_meta['total_count']}"
    assert all(row["status"] == ALLOC_RESERVED for row in lines), f"got {lines}"


def test_the_lot_token_advances_on_each_child_write_and_never_on_a_read(api):
    """PRD §2.4: "`updated_at` is the same format and records the most recent mutation; on creation
    it equals `created_at`."
    PRD §3.2: "Acceptance is the gate to the reactor. A `QualityAnalyst` accepts a lot whose status
    is exactly `TESTED` **and** whose `pretreatment_tier` is `NONE`, moving it `TESTED → ACCEPTED`
    and bumping its `version`."
    PRD §2.7: "7. Optimistic concurrency, as described in §2.6 — `ERR_STALE_LOT_VERSION` or
    `ERR_STALE_RUN_VERSION`, 412."

    Design: Corner/cross_cutting_complexity_layers/lot_version_increments_on_every_write_and_never_on_a_read
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.make_lot(api, supplier["id"], mass_mt=500.000)
    lot_v0 = lot["version"]

    read_v0 = validate_success(api.get_feedstock_lot(lot["id"], ANALYST_HEADERS))
    assert read_v0["version"] == lot_v0, f"a read is not a write, got {read_v0['version']}"
    assert read_v0["updated_at"] == read_v0["created_at"], f"got {read_v0['updated_at']}"

    fx.add_quality_test(api, lot["id"], read_v0["version"])
    read_v1 = validate_success(api.get_feedstock_lot(lot["id"], ANALYST_HEADERS))
    assert read_v1["version"] == lot_v0 + 1, f"got {read_v1['version']}"
    assert read_v1["status"] == LOT_TESTED, f"got {read_v1['status']}"

    validate_success(api.accept_lot(lot["id"], ANALYST_HEADERS))
    read_v2 = validate_success(api.get_feedstock_lot(lot["id"], ANALYST_HEADERS))
    assert read_v2["version"] == lot_v0 + 2, f"got {read_v2['version']}"
    assert read_v2["status"] == LOT_ACCEPTED, f"got {read_v2['status']}"
    assert read_v2["created_at"] == read_v0["created_at"], f"got {read_v2['created_at']}"

    for _ in range(3):
        again = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
        assert again["version"] == lot_v0 + 2, f"got {again['version']}"
        assert again["updated_at"] == read_v2["updated_at"], f"got {again['updated_at']}"

    validate_error(
        api.create_quality_test(
            lot["id"], f.quality_test_payload(read_v1["version"]), ANALYST_HEADERS
        ),
        ERR_STALE_LOT_VERSION,
        412,
    )


def test_a_twelve_point_yield_shortfall_derates_the_charge_it_ran_on(api):
    """PRD §3.6: "`yield_variance_pct` is `final_yield_pct` less `provisional_yield_pct`, rounded to
    3 decimal places, and `yield_variance_flag` is set when the absolute value of that variance is
    strictly greater than the 2.000 percentage-point tolerance."
    PRD §3.6: "Separately, when `yield_variance_flag` is `true` **and** the charge is still `ACTIVE`
    after the throughput effect has been applied, the charge is derated: `ACTIVE → DERATED`, the
    charge's `version` is bumped, and as a further consequence the owning unit's
    `requires_turnaround` is set to `true` with the unit's `version` bumped."
    PRD §3.3: "The `activity_index` is then 1.0000 reduced by 0.0125 for every thousand metric
    tonnes of cumulative throughput — that is, 1.0000 less the product of 0.0125 and the cumulative
    throughput divided by 1000 — with the result held at a floor of 0.6000 if the arithmetic would
    take it lower, and rounded half up to 4 decimal places."

    Design: Corner/cross_cutting_complexity_layers/yield_variance_beyond_tolerance_derates_the_charge
    """
    ctx = fx.completed_campaign(
        api, measured_rd_mt=280.000, measured_saf_mt=0.000, target_saf_share_pct=0.00
    )
    run = ctx["run"]

    assert run["status"] == RUN_COMPLETED, f"got {run['status']}"
    assert run["provisional_yield_pct"] == 82.000, f"got {run['provisional_yield_pct']}"
    assert run["final_yield_pct"] == 70.000, f"got {run['final_yield_pct']}"
    assert run["yield_variance_pct"] == -12.000, f"got {run['yield_variance_pct']}"
    assert run["yield_variance_flag"] is True, f"got {run['yield_variance_flag']}"

    charges, _ = validate_paginated(
        api.list_catalyst_charges(ctx["unit"]["id"], OPERATOR_HEADERS)
    )
    assert len(charges) == 1, f"got {len(charges)}"
    charge = charges[0]
    assert charge["status"] == CHARGE_DERATED, f"got {charge['status']}"
    assert_mass(charge["cumulative_throughput_mt"], 400.000, "cumulative_throughput_mt")
    assert_activity_index(charge["activity_index"], 0.9950)

    unit = validate_success(api.get_unit(ctx["unit"]["id"], OPERATOR_HEADERS))
    assert unit["requires_turnaround"] is True, f"got {unit['requires_turnaround']}"
    assert unit["status"] == UNIT_IDLE, f"got {unit['status']}"

    batches, batch_meta = validate_paginated(
        api.list_product_batches(OFFICER_A_HEADERS, {"run_id": run["id"]})
    )
    assert batch_meta["total_count"] == 1, f"diesel only, got {batch_meta['total_count']}"
    batch = batches[0]
    assert batch["product_type"] == PRODUCT_RENEWABLE_DIESEL, f"got {batch['product_type']}"
    assert_mass(batch["mass_mt"], 280.000, "mass_mt")
    assert_one_decimal(batch["volume_gal"], 86240.0, "volume_gal")
    assert batch["cert_status"] == CERT_UNCERTIFIED, f"got {batch['cert_status']}"
    assert batch["distribution_status"] == DIST_IN_TANK, f"got {batch['distribution_status']}"


def test_reaching_design_throughput_spends_the_charge_at_the_variance_boundary(api):
    """PRD §3.6: "If the recomputed `cumulative_throughput_mt` has reached the charge's
    `design_throughput_mt` — at or above it — the charge transitions to `SPENT` and the owning
    unit's `requires_turnaround` is set to `true`, signalling that a catalyst-change outage must be
    scheduled; this applies identically whether the charge was `ACTIVE → SPENT` or `DERATED →
    SPENT`, and in both cases the charge's `version` is bumped."
    PRD §3.6: "The ordering matters and the interaction is one-way: a charge that the throughput
    effect has already moved to `SPENT` is **not** pulled back down to `DERATED`, because `SPENT` is
    the more advanced condition."
    PRD §3.6: "Its `volume_gal` is that `mass_mt` multiplied by a per-product conversion factor —
    308.0 gallons per metric tonne for `RENEWABLE_DIESEL` and 322.0 for `SAF` — rounded half up to
    1 decimal place."

    Design: Corner/cross_cutting_complexity_layers/cumulative_throughput_at_design_spends_the_charge_at_the_variance_boundary
    """
    plant = fx.commissioned_unit(api, charge={"design_throughput_mt": 300.0})
    supplier = fx.verified_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.accepted_lot(api, supplier["id"], mass_mt=500.000)
    contract = fx.make_contract(api)
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=10.00
    )
    fx.allocate(api, run["id"], lot["id"], 400.000, expected_version=run["version"])
    fx.make_nomination(api, contract["id"], run["id"])
    secured = validate_success(api.secure_hydrogen(run["id"], OPERATOR_HEADERS))
    assert secured["provisional_yield_pct"] == 82.000, f"got {secured['provisional_yield_pct']}"

    fx.move_clock(api, "2026-09-01T00:00:00Z")
    validate_success(api.start_run(run["id"], OPERATOR_HEADERS))
    fx.move_clock(api, "2026-09-06T00:00:00Z")

    completed = validate_success(
        api.complete_run(
            run["id"], f.completion_payload(290.000, 30.000), OPERATOR_HEADERS
        )
    )
    assert completed["status"] == RUN_COMPLETED, f"got {completed['status']}"
    assert completed["final_yield_pct"] == 80.000, f"got {completed['final_yield_pct']}"
    assert completed["yield_variance_pct"] == -2.000, f"got {completed['yield_variance_pct']}"
    assert completed["yield_variance_flag"] is False, (
        f"exactly at tolerance is not beyond it, got {completed['yield_variance_flag']}"
    )

    charges, _ = validate_paginated(
        api.list_catalyst_charges(plant["unit"]["id"], OPERATOR_HEADERS)
    )
    charge = charges[0]
    assert charge["status"] == CHARGE_SPENT, f"spent, never derated, got {charge['status']}"
    assert charge["status"] != CHARGE_ACTIVE
    assert_mass(charge["cumulative_throughput_mt"], 400.000, "cumulative_throughput_mt")
    assert_activity_index(charge["activity_index"], 0.9950)

    unit = validate_success(api.get_unit(plant["unit"]["id"], OPERATOR_HEADERS))
    assert unit["requires_turnaround"] is True, f"got {unit['requires_turnaround']}"

    batches, batch_meta = validate_paginated(
        api.list_product_batches(OFFICER_A_HEADERS, {"run_id": run["id"]})
    )
    assert batch_meta["total_count"] == 2, f"got {batch_meta['total_count']}"
    by_type = {row["product_type"]: row for row in batches}
    diesel = by_type[PRODUCT_RENEWABLE_DIESEL]
    jet = by_type[PRODUCT_SAF]
    assert_mass(diesel["mass_mt"], 290.000, "mass_mt")
    assert_one_decimal(diesel["volume_gal"], 89320.0, "volume_gal")
    assert_mass(jet["mass_mt"], 30.000, "mass_mt")
    assert_one_decimal(jet["volume_gal"], 9660.0, "volume_gal")
    for row in (diesel, jet):
        assert row["cert_status"] == CERT_UNCERTIFIED, f"got {row['cert_status']}"
        assert row["distribution_status"] == DIST_IN_TANK, f"got {row['distribution_status']}"
