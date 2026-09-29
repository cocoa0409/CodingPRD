"""Two variants of the same rule computed over the same entity."""

from test_helpers import (
    GlassColor,
    LotQualityStatus,
    MoldFamily,
    MoldOwner,
    PalletizationStandard,
    fixtures,
    get_success_data,
    validate_success,
)

CAMPAIGN_WINDOW_END = "2026-08-11T00:00:00Z"
TRANSITION_END = "2026-08-02T00:00:00Z"


def _amber_lot_awaiting_disposition(api):
    """A completed AMBER job whose lot carries two readings and 90.00 transition tons."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-01",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Acme Filling",
            "account_code": "ACME-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-01",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": CAMPAIGN_WINDOW_END,
        },
        recipe={
            "code": "BR-AM",
            "color": GlassColor.AMBER,
            "cullet_ratio_pct": 40.00,
            "soda_ash_kg_per_ton": 180.00,
            "colorant_kg_per_ton": 3.50,
        },
        machine={
            "code": "IS-01",
            "section_count": 10,
            "max_cavities": 40,
            "primary_mold_family": MoldFamily.NNPB,
            "changeover_buffer_minutes": 45,
        },
        design={
            "code": "BD-01",
            "color": GlassColor.AMBER,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 10,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1725,
            "mold_owner": MoldOwner.CUSTOMER,
        },
        mold_set={
            "code": "MS-01",
            "cavity_count": 12,
            "mold_family": MoldFamily.PRESS_BLOW,
            "owner": MoldOwner.CUSTOMER,
            "condition_score": 70,
        },
    )
    change = fixtures.schedule_color_change(
        api,
        ctx.furnace_id,
        to_color=GlassColor.AMBER,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at=TRANSITION_END,
        transition_loss_tons=90.00,
    )
    fixtures.set_clock(api, TRANSITION_END)
    fixtures.complete_color_change(api, change["id"])

    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-01",
        window_start_at=TRANSITION_END,
        window_end_at="2026-08-04T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    fixtures.record_readings(
        api,
        lot["id"],
        [
            {
                "defect_class": "MAJOR",
                "defect_code": "CHECK_CRACK",
                "rejected_units": 4000,
                "inspected_at": TRANSITION_END,
            },
            {
                "defect_class": "MINOR",
                "defect_code": "BIRDSWING",
                "rejected_units": 2000,
                "inspected_at": TRANSITION_END,
            },
        ],
    )
    return ctx, lot


def _over_pull_job_on_high_cullet_recipe(api):
    """A 3-day job pulling 330.00 tpd on a 300.00 tpd furnace at 55.00 percent cullet."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-02",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Boreal Beverages",
            "account_code": "BOREAL-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-02",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": CAMPAIGN_WINDOW_END,
        },
        recipe={
            "code": "BR-F55",
            "color": GlassColor.FLINT,
            "cullet_ratio_pct": 55.00,
            "soda_ash_kg_per_ton": 170.00,
            "colorant_kg_per_ton": 0.00,
        },
        machine={"code": "IS-02"},
        design={
            "code": "BD-02",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1500,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-02", "cavity_count": 8, "condition_score": 90},
    )
    job = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-02",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-04T00:00:00Z",
        planned_pull_tpd=330.00,
    )
    return ctx, job


def test_01_provisional_yield_credits_gross_units_against_reserved_melt_alone(api):
    """The lot's optimistic yield reads 95.00 the moment the job closes.

    PRD: "The provisional pack-to-melt yield is one hundred times that gross
    tonnage divided by the job's `reserved_melt_tons`, rounded half up to 2
    decimals."

    Design: Difficulty/dual_variant_calc/pack_to_melt_yield_provisional_vs_final_diverge_on_same_lot
    """
    _ctx, lot = _amber_lot_awaiting_disposition(api)

    assert lot["provisional_yield_pct"] == 95.00
    assert lot["packed_units"] == 3000000
    assert lot["unit_weight_g"] == 190.00


def test_02_final_yield_charges_net_tons_against_melt_plus_attributed_transition(api):
    """Release recomputes the same lot's yield as 82.44, not 95.00.

    PRD: "Its numerator is one hundred times the net packed tonnage rather than
    the gross, and its denominator is the job's `reserved_melt_tons` *plus* the
    colour-transition tonnage attributed to that job; the quotient is rounded
    half up to 2 decimals."

    Design: Difficulty/dual_variant_calc/pack_to_melt_yield_provisional_vs_final_diverge_on_same_lot
    """
    _ctx, lot = _amber_lot_awaiting_disposition(api)

    released = validate_success(api.release_pack_lot(lot["id"], fixtures.users.QE_RELEASER))

    assert released["quality_status"] == LotQualityStatus.RELEASED
    assert released["net_packed_units"] == 2994000
    assert released["provisional_yield_pct"] == 95.00
    assert released["final_yield_pct"] == 82.44


def test_03_release_reconciles_the_campaign_melt_ledger(api):
    """The released lot settles packed, reject and transition tons, leaving 30.00 unaccounted.

    PRD: "`unaccounted_loss_tons` is the residual: melt tons charged, less
    packed tons, less transition loss tons, less reject loss tons, carried to 2
    decimals and permitted to be zero."

    Design: Difficulty/dual_variant_calc/pack_to_melt_yield_provisional_vs_final_diverge_on_same_lot
    """
    ctx, lot = _amber_lot_awaiting_disposition(api)

    validate_success(api.release_pack_lot(lot["id"], fixtures.users.QE_RELEASER))
    campaign = fixtures.read_campaign(api, ctx.campaign_id)

    assert campaign["melt_tons_charged"] == 690.00
    assert campaign["packed_tons"] == 568.86
    assert campaign["transition_loss_tons"] == 90.00
    assert campaign["reject_loss_tons"] == 1.14
    assert campaign["unaccounted_loss_tons"] == 30.00


def test_04_both_ppm_figures_divide_by_gross_packed_units(api):
    """4000 major and 2000 minor rejects on 3000000 packed read 1333.3 and 666.7.

    PRD: "`major_ppm` is one million times the summed `rejected_units` of
    readings whose class is `MAJOR`, divided by the lot's gross `packed_units`,
    rounded half up to 1 decimal; `minor_ppm` is the same computation over
    readings whose class is `MINOR`."

    Design: Difficulty/dual_variant_calc/pack_to_melt_yield_provisional_vs_final_diverge_on_same_lot
    """
    _ctx, lot = _amber_lot_awaiting_disposition(api)

    current = fixtures.read_lot(api, lot["id"])

    assert current["major_ppm"] == 1333.3
    assert current["minor_ppm"] == 666.7


def test_05_nominal_projection_ignores_over_pull_and_cullet_stress(api):
    """330.00 tpd over 3 FLINT days projects 990.00 nominal wear units.

    PRD: "The **nominal** variant is simply the base wear units rounded half up
    to 2 decimals, ignoring over-pull and cullet stress entirely; it is what a
    campaign records at activation, using `target_pull_tpd`, the campaign
    window, and the colour factor of the furnace's `current_color` at that
    moment."

    Design: Difficulty/dual_variant_calc/refractory_wear_nominal_vs_stress_adjusted_diverge_on_same_job
    """
    _ctx, job = _over_pull_job_on_high_cullet_recipe(api)

    projection = validate_success(
        api.get_job_refractory_projection(job["id"], fixtures.users.SCHEDULER)
    )

    assert job["projected_refractory_units_nominal"] == 990.00
    assert projection["projected_refractory_units_nominal"] == 990.00


def test_06_stress_adjusted_projection_applies_the_unrounded_multiplier(api):
    """The same job projects 1267.20 once over-pull and cullet stress are weighted.

    PRD: "The stress multiplier is one, plus 2.0 times the fractional over-pull,
    plus 0.8 times the recipe's cullet stress factor, where fractional over-pull
    is the amount by which the job's `planned_pull_tpd` exceeds the furnace's
    `design_pull_tpd` divided by that same `design_pull_tpd`, floored at zero so
    that pulling at or below design contributes nothing."

    Design: Difficulty/dual_variant_calc/refractory_wear_nominal_vs_stress_adjusted_diverge_on_same_job
    """
    ctx, job = _over_pull_job_on_high_cullet_recipe(api)

    projection = validate_success(
        api.get_job_refractory_projection(job["id"], fixtures.users.SCHEDULER)
    )

    assert ctx.recipe["cullet_stress_factor"] == 0.1000
    assert job["projected_refractory_units_stress_adjusted"] == 1267.20
    assert projection["projected_refractory_units_stress_adjusted"] == 1267.20


def test_07_close_charges_the_stress_adjusted_variant_to_the_furnace(api):
    """Closing leaves 98.73 percent of the lining, not the nominal 99.01.

    PRD: "Both branches require the job to be in `RUNNING`, else
    `ERR_JOB_STATE_INVALID`; both compute `refractory_wear_units` from the
    stress-adjusted refractory variant and charge it to the furnace, adding it
    to `refractory_consumed_units`, recomputing `refractory_remaining_pct` and
    re-deriving `posture`; both move the job's `reserved_melt_tons` out of the
    furnace's `reserved_pull_tons` and into the campaign's `melt_tons_charged`;
    both move the forming machine `RUNNING → IDLE` with its `version` increased
    by 1; and both increment the job's `version` by 1."

    Design: Difficulty/dual_variant_calc/refractory_wear_nominal_vs_stress_adjusted_diverge_on_same_job
    """
    ctx, job = _over_pull_job_on_high_cullet_recipe(api)
    get_success_data(api.start_production_job(job["id"], fixtures.users.SCHEDULER))

    closed = validate_success(
        api.close_production_job(
            job["id"],
            {"outcome": "COMPLETED", "produced_units": 1500000},
            fixtures.users.SCHEDULER,
        )
    )
    furnace = fixtures.read_furnace(api, ctx.furnace_id)

    assert closed["refractory_wear_units"] == 1267.20
    assert furnace["refractory_consumed_units"] == 1267.20
    assert furnace["refractory_remaining_pct"] == 98.73
    assert furnace["refractory_remaining_pct"] != 99.01
    assert furnace["posture"] == "OPERATING"
