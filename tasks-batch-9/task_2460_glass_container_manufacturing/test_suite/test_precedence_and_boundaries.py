"""Which of two simultaneously violated rules answers, and inclusive boundaries."""

from test_helpers import (
    ApiErrorId,
    CampaignStatus,
    FurnacePosture,
    GlassColor,
    LotQualityStatus,
    MoldOwner,
    PalletizationStandard,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

LONG_CAMPAIGN_END = "2026-08-11T00:00:00Z"


def _planned_campaign_with_an_oversized_job(api):
    """A PLANNED 1-day campaign whose 300.00 ton pool cannot hold a 330.00 ton job."""
    return fixtures.bring_up_plant(
        api,
        activate=False,
        furnace={
            "code": "F-10",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Juliet Juices",
            "account_code": "JULIET-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-10",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": "2026-08-02T00:00:00Z",
        },
        recipe={"code": "BR-F10", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-10"},
        design={
            "code": "BD-10",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-10", "cavity_count": 8, "condition_score": 90},
    )


def _flint_furnace_with_an_occupied_machine_window(api):
    """A FLINT furnace carrying an AMBER design and one job already on the machine."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-11",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Kilo Kombucha",
            "account_code": "KILO-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-11",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F11", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-11", "changeover_buffer_minutes": 45},
        design={
            "code": "BD-F11",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-F11", "cavity_count": 8, "condition_score": 90},
    )
    amber_recipe = fixtures.create_approved_recipe(
        api,
        ctx.furnace_id,
        code="BR-A11",
        color=GlassColor.AMBER,
        cullet_ratio_pct=40.00,
        soda_ash_kg_per_ton=180.00,
        colorant_kg_per_ton=3.50,
    )
    amber_design = fixtures.create_approved_design(
        api,
        ctx.customer_id,
        code="BD-A11",
        color=GlassColor.AMBER,
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=500.00,
        container_price_usd=0.1600,
        mold_owner=MoldOwner.PLANT,
    )
    amber_set = fixtures.create_mold_set(
        api, amber_design["id"], code="MS-A11", cavity_count=8, condition_score=90
    )
    first = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-11A",
        window_start_at="2026-08-02T00:00:00Z",
        window_end_at="2026-08-04T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    return ctx, first, amber_recipe, amber_design, amber_set


def _two_linings_taking_identical_wear(api):
    """One 1000.00 unit lining and one 1005.00 unit lining, each charged 950.00 units."""
    customer = fixtures.create_customer(
        api,
        name="Lima Liqueurs",
        account_code="LIMA-01",
        palletization_standard=PalletizationStandard.EURO,
        complaint_ppm_threshold=5000.00,
    )
    design = fixtures.create_approved_design(
        api,
        customer["id"],
        code="BD-12",
        color=GlassColor.FLINT,
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=500.00,
        container_price_usd=0.1600,
        mold_owner=MoldOwner.PLANT,
    )

    arms = []
    for suffix, life in (("A", 1000.00), ("B", 1005.00)):
        furnace = fixtures.create_furnace(
            api,
            code=f"F-12{suffix}",
            design_pull_tpd=475.00,
            refractory_life_total_units=life,
        )
        campaign = fixtures.create_active_campaign(
            api,
            furnace["id"],
            code=f"CMP-12{suffix}",
            target_pull_tpd=475.00,
            window_start_at="2026-08-01T00:00:00Z",
            window_end_at=LONG_CAMPAIGN_END,
        )
        recipe = fixtures.create_approved_recipe(
            api,
            furnace["id"],
            code=f"BR-12{suffix}",
            cullet_ratio_pct=40.00,
            soda_ash_kg_per_ton=170.00,
        )
        machine = fixtures.create_forming_machine(api, furnace["id"], code=f"IS-12{suffix}")
        mold_set = fixtures.create_mold_set(
            api, design["id"], code=f"MS-12{suffix}", cavity_count=8, condition_score=90
        )
        ctx = fixtures.PlantContext(
            furnace=furnace,
            customer=customer,
            campaign=campaign,
            recipe=recipe,
            machine=machine,
            design=design,
            mold_set=mold_set,
        )
        job = fixtures.schedule_job(
            api,
            ctx,
            code=f"PJ-12{suffix}",
            window_start_at="2026-08-01T00:00:00Z",
            window_end_at="2026-08-03T00:00:00Z",
            planned_pull_tpd=475.00,
        )
        fixtures.start_job(api, job["id"])
        closed = fixtures.close_job(api, job["id"], "COMPLETED", produced_units=3000000)
        arms.append((ctx, closed))
    return arms


def _uninspected_lot(api):
    """A PENDING_INSPECTION lot of 3000000 units with no inspection reading at all."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-13",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Mike Mineral Water",
            "account_code": "MIKE-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-13",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F13", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-13"},
        design={
            "code": "BD-13",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-13", "cavity_count": 8, "condition_score": 90},
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-13",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    return ctx, lot


def test_01_a_planned_campaign_answers_before_the_pull_pool_is_measured(api):
    """The create that breaks both rules reports the campaign state, not the capacity.

    PRD: "Checks fire in a fixed precedence, and the first failing check
    determines the response."

    PRD: "The campaign must be in `ACTIVE`; scheduling against a campaign that is
    merely `PLANNED`, or already winding down, is refused with
    `ERR_CAMPAIGN_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/campaign_not_active_outranks_pull_capacity_on_job_create
    """
    ctx = _planned_campaign_with_an_oversized_job(api)

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-10A",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-02T00:00:00Z",
        planned_pull_tpd=330.00,
    )
    error = validate_error(
        api.create_production_job(payload, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE,
        409,
    )

    assert error["error_id"] != ApiErrorId.ERR_PULL_CAPACITY_EXCEEDED


def test_02_the_capacity_rule_answers_once_the_campaign_is_active(api):
    """The same payload on an ACTIVE campaign exhausts the 300.00 ton pool.

    PRD: "The job may only be scheduled when its `reserved_melt_tons` is less
    than or equal to the available tons; anything larger exhausts the pool and is
    refused with `ERR_PULL_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/campaign_not_active_outranks_pull_capacity_on_job_create
    """
    ctx = _planned_campaign_with_an_oversized_job(api)
    fixtures.activate_campaign(api, ctx.campaign_id)

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-10B",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-02T00:00:00Z",
        planned_pull_tpd=330.00,
    )
    validate_error(
        api.create_production_job(payload, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_PULL_CAPACITY_EXCEEDED,
        409,
    )
    jobs, _meta = validate_paginated(
        api.list_production_jobs(fixtures.users.SCHEDULER, campaign_id=ctx.campaign_id)
    )
    furnace = fixtures.read_furnace(api, ctx.furnace_id)

    assert jobs == []
    assert furnace["reserved_pull_tons"] == 0.00


def test_03_a_colour_mismatch_answers_before_the_machine_window_is_compared(api):
    """The AMBER create into an occupied window reports the colour, not the overlap.

    PRD: "Both the batch recipe's `color` and the bottle design's `color` must
    equal the furnace's `current_color` — the furnace melts one colour at a time
    and cannot serve a design that needs another — and a discrepancy on either
    side reports `ERR_COLOR_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/color_mismatch_outranks_machine_window_conflict_on_job_create
    """
    ctx, _first, amber_recipe, amber_design, amber_set = _flint_furnace_with_an_occupied_machine_window(api)

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-11B",
        window_start_at="2026-08-03T00:00:00Z",
        window_end_at="2026-08-05T00:00:00Z",
        planned_pull_tpd=300.00,
        batch_recipe_id=amber_recipe["id"],
        bottle_design_id=amber_design["id"],
        mold_set_id=amber_set["id"],
    )
    error = validate_error(
        api.create_production_job(payload, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_COLOR_MISMATCH,
        422,
    )

    assert error["error_id"] != ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT


def test_04_the_same_window_with_matching_colour_reports_the_overlap(api):
    """The FLINT control create proves the machine window really was contended.

    PRD: "Two jobs on the same forming machine may therefore abut exactly — one
    ending at the instant the next begins — except that the machine's mandatory
    `changeover_buffer_minutes` is appended to the earlier job's end before the
    comparison is made, so true abutment is only legal on a machine whose buffer
    is zero."

    PRD: "35. The job window does not collide on its machine, else
    `ERR_MACHINE_WINDOW_CONFLICT` — on job creation."

    Design: Difficulty/priority_pair_validation_conflict/color_mismatch_outranks_machine_window_conflict_on_job_create
    """
    ctx, _first, _recipe, _design, _set = _flint_furnace_with_an_occupied_machine_window(api)

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-11C",
        window_start_at="2026-08-03T00:00:00Z",
        window_end_at="2026-08-05T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    validate_error(
        api.create_production_job(payload, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT,
        409,
    )
    furnace = fixtures.read_furnace(api, ctx.furnace_id)

    assert furnace["reserved_pull_tons"] == 600.00


def test_05_a_lining_landing_on_exactly_five_percent_is_rebuild_due(api):
    """950.00 units out of 1000.00 leaves exactly 5.00 percent and winds the campaign down.

    PRD: "Otherwise, if `refractory_remaining_pct` is 5.00 or lower, posture is
    `REBUILD_DUE`."

    Design: Difficulty/boundary_precision_check/refractory_remaining_exactly_five_percent_flips_posture_to_rebuild_due
    """
    (ctx_a, closed_a), (_ctx_b, closed_b) = _two_linings_taking_identical_wear(api)

    assert closed_a["refractory_wear_units"] == 950.00
    assert closed_b["refractory_wear_units"] == 950.00

    furnace = fixtures.read_furnace(api, ctx_a.furnace_id)
    campaign = fixtures.read_campaign(api, ctx_a.campaign_id)

    assert furnace["refractory_remaining_pct"] == 5.00
    assert furnace["posture"] == FurnacePosture.REBUILD_DUE
    assert campaign["status"] == CampaignStatus.WIND_DOWN


def test_06_a_lining_landing_just_above_the_threshold_stays_restricted(api):
    """The identical wear on 1005.00 units leaves 5.47 percent and keeps the campaign alive.

    PRD: "Otherwise, if `refractory_remaining_pct` is 15.00 or lower, posture is
    `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/refractory_remaining_exactly_five_percent_flips_posture_to_rebuild_due
    """
    (_ctx_a, _closed_a), (ctx_b, closed_b) = _two_linings_taking_identical_wear(api)

    furnace = fixtures.read_furnace(api, ctx_b.furnace_id)
    campaign = fixtures.read_campaign(api, ctx_b.campaign_id)

    assert closed_b["refractory_wear_units"] == 950.00
    assert furnace["refractory_remaining_pct"] == 5.47
    assert furnace["posture"] == FurnacePosture.RESTRICTED
    assert campaign["status"] == CampaignStatus.ACTIVE


def test_07_release_refuses_a_lot_that_carries_no_reading_at_all(api):
    """An empty reading collection is a refusal, not a zero-reject release.

    PRD: "It requires `quality_status` to be `PENDING_INSPECTION`, else
    `ERR_LOT_STATE_INVALID`, and requires at least one inspection reading to exist
    on the lot, else `ERR_NO_INSPECTION_RECORDS` — a lot is never disposed on no
    evidence."

    Design: Difficulty/boundary_precision_check/release_with_zero_inspection_records_fails_closed
    """
    _ctx, lot = _uninspected_lot(api)

    assert lot["provisional_yield_pct"] == 95.00

    validate_error(
        api.release_pack_lot(lot["id"], fixtures.users.QE_RELEASER),
        ApiErrorId.ERR_NO_INSPECTION_RECORDS,
        409,
    )
    current = fixtures.read_lot(api, lot["id"])

    assert current["quality_status"] == LotQualityStatus.PENDING_INSPECTION
    assert current["final_yield_pct"] == 0.00


def test_08_one_minimal_reading_flips_the_same_release_to_success(api):
    """A single rejected unit releases the lot and leaves the 2-decimal yield at 95.00.

    PRD: "In every remaining case the lot moves `PENDING_INSPECTION → RELEASED`."

    Design: Difficulty/boundary_precision_check/release_with_zero_inspection_records_fails_closed
    """
    ctx, lot = _uninspected_lot(api)
    validate_error(
        api.release_pack_lot(lot["id"], fixtures.users.QE_RELEASER),
        ApiErrorId.ERR_NO_INSPECTION_RECORDS,
        409,
    )

    fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="BLISTER",
        rejected_units=1,
        inspected_at="2026-08-01T00:00:00Z",
    )
    released = validate_success(api.release_pack_lot(lot["id"], fixtures.users.QE_RELEASER))
    campaign = fixtures.read_campaign(api, ctx.campaign_id)

    assert released["quality_status"] == LotQualityStatus.RELEASED
    assert released["net_packed_units"] == 2999999
    assert released["major_ppm"] == 0.0
    assert released["minor_ppm"] == 0.3
    assert released["final_yield_pct"] == 95.00
    assert campaign["packed_tons"] == 570.00
