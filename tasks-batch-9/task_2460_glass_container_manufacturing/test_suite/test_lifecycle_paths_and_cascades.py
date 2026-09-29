"""Non-linear lifecycle loops and multi-hop cascades from a single trigger."""

from test_helpers import (
    BottleDesignStatus,
    CampaignStatus,
    ComplaintStatus,
    FurnacePosture,
    GlassColor,
    LotLogisticsStatus,
    LotQualityStatus,
    MoldOwner,
    PalletizationStandard,
    ProductionJobStatus,
    ProgramStatus,
    QualityStanding,
    SavingsTier,
    fixtures,
    validate_success,
)

LONG_CAMPAIGN_END = "2026-08-11T00:00:00Z"
AGING_BOUNDARY = "2026-08-04T00:00:00Z"
SHIP_DAY = "2026-08-06T00:00:00Z"


def _design_returned_for_changes(api):
    """A design that has been submitted once and sent back for changes."""
    customer = fixtures.create_customer(
        api,
        name="Fox Farms",
        account_code="FOX-01",
        palletization_standard=PalletizationStandard.EURO,
        complaint_ppm_threshold=5000.00,
    )
    design = fixtures.create_design(
        api,
        customer["id"],
        code="BD-06",
        color=GlassColor.FLINT,
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=10,
        target_line_speed_bpm=500.00,
        container_price_usd=0.1725,
        mold_owner=MoldOwner.PLANT,
    )
    first = fixtures.submit_design(api, design["id"])
    validate_success(
        api.request_design_changes(
            design["id"], fixtures.users.QE_RISK_SIGNER, note="reduce shoulder radius"
        )
    )
    return design, first


def _lot_at_the_aging_boundary(api):
    """A 3000000-unit lot whose 3-day aging has just elapsed on the logical clock."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-07",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Golf Glassworks",
            "account_code": "GOLF-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-07",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F07", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-07"},
        design={
            "code": "BD-07",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-07", "cavity_count": 8, "condition_score": 88},
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-07",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
    )
    fixtures.set_clock(api, AGING_BOUNDARY)
    return ctx, lot


def _short_lined_furnace_with_two_jobs(api):
    """A running job that will exhaust a 620.00 unit lining, plus a later scheduled job."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-08",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 620.00,
        },
        customer={
            "name": "India Imports",
            "account_code": "INDIA-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-08",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F08", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-08"},
        design={
            "code": "BD-08",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-08A", "cavity_count": 8, "condition_score": 90},
    )
    second_set = fixtures.create_mold_set(
        api, ctx.design_id, code="MS-08B", cavity_count=8, condition_score=90
    )
    job_a = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-08A",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    job_b = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-08B",
        window_start_at="2026-08-05T00:00:00Z",
        window_end_at="2026-08-06T00:00:00Z",
        planned_pull_tpd=300.00,
        mold_set_id=second_set["id"],
    )
    fixtures.start_job(api, job_a["id"])
    return ctx, job_a, job_b


def _adopted_program_and_investigated_complaint(api):
    """A CRITICAL-bound complaint on a customer whose design carries an ADOPTED program."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-09",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Hotel Hospitality",
            "account_code": "HOTEL-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 2000.00,
        },
        campaign={
            "code": "CMP-09",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F09", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-09"},
        design={
            "code": "BD-09",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1725,
            "mold_owner": MoldOwner.CUSTOMER,
        },
        mold_set={
            "code": "MS-09",
            "cavity_count": 8,
            "owner": MoldOwner.CUSTOMER,
            "condition_score": 90,
        },
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=2001000,
        code="PJ-09",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
    )
    fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="BLISTER",
        rejected_units=1000,
        inspected_at="2026-08-01T00:00:00Z",
    )
    fixtures.release_lot(api, lot["id"], fixtures.users.QE_RELEASER)
    fixtures.set_clock(api, SHIP_DAY)
    fixtures.palletize_lot(api, lot["id"])
    fixtures.ship_lot(api, lot["id"])

    program = fixtures.adopted_program(
        api,
        ctx.design_id,
        ctx.customer_id,
        code="LW-09",
        target_weight_g=180.00,
        annual_volume_units=10000000,
        resin_free_glass_price_per_kg=0.1650,
    )
    complaint = fixtures.file_complaint(
        api,
        ctx.customer_id,
        lot["id"],
        code="CO-09",
        reported_at=SHIP_DAY,
        affected_units=5000,
        filling_line_speed_bpm=520.00,
    )
    investigated = validate_success(
        api.investigate_complaint(
            complaint["id"],
            {"attribution": "PLANT", "findings": "checked finish on returned units"},
            fixtures.users.QE_INVESTIGATOR,
        )
    )
    return ctx, lot, program, complaint, investigated


def test_01_resubmission_after_changes_requested_relengthens_the_lead_time(api):
    """The second visit to SUBMITTED counts a revision and pushes 60 days to 67.

    PRD: "Resubmission moves it `CHANGES_REQUESTED → SUBMITTED` again, and this
    path differs from a first submission in one important way: `revision_count`
    increases by 1 first, and both the risk index and the lead time are then
    recomputed with the new revision count, so each round trip through review
    lengthens the promise by another 7 days."

    Design: Difficulty/non_linear_state_machine/bottle_design_changes_requested_resubmit_cycle_relengthens_lead_time
    """
    design, first = _design_returned_for_changes(api)

    assert first["lead_time_days"] == 60
    assert first["revision_count"] == 0

    resubmitted = validate_success(
        api.submit_bottle_design(design["id"], fixtures.users.MOLD_ENGINEER)
    )

    assert resubmitted["revision_count"] == 1
    assert resubmitted["lead_time_days"] == 67


def test_02_risk_signoff_is_reachable_only_from_the_second_submitted_visit(api):
    """After the loop closes the design signs off and records its signer.

    PRD: "Sign-off records the acting `X-User-ID` as `risk_signed_by_user_id`."

    Design: Difficulty/non_linear_state_machine/bottle_design_changes_requested_resubmit_cycle_relengthens_lead_time
    """
    design, _first = _design_returned_for_changes(api)
    validate_success(api.submit_bottle_design(design["id"], fixtures.users.MOLD_ENGINEER))

    signed = validate_success(
        api.risk_signoff_bottle_design(design["id"], fixtures.users.QE_RISK_SIGNER)
    )

    assert signed["status"] == BottleDesignStatus.RISK_SIGNED
    assert signed["risk_signed_by_user_id"] == fixtures.users.QE_RISK_SIGNER_ID
    assert signed["lead_time_days"] == 67


def test_03_palletizing_advances_logistics_while_quality_still_pends(api):
    """The lot reaches PALLETIZED with 1667 pallets and no quality decision yet.

    PRD: "Note that the logistics dimension advances independently of the quality
    dimension: a lot may be palletized while its `quality_status` is still
    `PENDING_INSPECTION`, and indeed usually is, which is exactly why a later
    inspection reading has to recompute `pallet_count`."

    Design: Difficulty/non_linear_state_machine/pack_lot_quality_and_logistics_dimensions_advance_independently
    """
    _ctx, lot = _lot_at_the_aging_boundary(api)

    assert lot["aged_until_at"] == "2026-08-04T00:00:00.000Z"

    palletized = validate_success(api.palletize_pack_lot(lot["id"], fixtures.users.WAREHOUSE))

    assert palletized["logistics_status"] == LotLogisticsStatus.PALLETIZED
    assert palletized["quality_status"] == LotQualityStatus.PENDING_INSPECTION
    assert palletized["pallet_count"] == 1667


def test_04_a_reading_on_a_palletized_lot_recomputes_the_pallet_count(api):
    """25000 rejects drop an already palletized lot from 1667 pallets to 1653.

    PRD: "If the lot has already been palletized, the new `net_packed_units` also
    forces `pallet_count` to be recomputed, since fewer good containers may mean
    fewer pallets."

    Design: Difficulty/non_linear_state_machine/pack_lot_quality_and_logistics_dimensions_advance_independently
    """
    _ctx, lot = _lot_at_the_aging_boundary(api)
    fixtures.palletize_lot(api, lot["id"])

    fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="BLISTER",
        rejected_units=25000,
        inspected_at=AGING_BOUNDARY,
    )
    current = fixtures.read_lot(api, lot["id"])

    assert current["net_packed_units"] == 2975000
    assert current["minor_ppm"] == 8333.3
    assert current["pallet_count"] == 1653


def test_05_shipping_needs_both_dimensions_to_have_advanced(api):
    """Once released and palletized the lot ships and stamps the clock instant.

    PRD: "A shipped lot has `shipped_at` set to the logical clock's current value
    and its `version` increased by 1."

    Design: Difficulty/non_linear_state_machine/pack_lot_quality_and_logistics_dimensions_advance_independently
    """
    _ctx, lot = _lot_at_the_aging_boundary(api)
    fixtures.palletize_lot(api, lot["id"])
    fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="BLISTER",
        rejected_units=25000,
        inspected_at=AGING_BOUNDARY,
    )

    released = fixtures.release_lot(api, lot["id"], fixtures.users.QE_RELEASER)
    assert released["quality_status"] == LotQualityStatus.RELEASED
    assert released["logistics_status"] == LotLogisticsStatus.PALLETIZED
    assert released["pallet_count"] == 1653

    shipped = validate_success(api.ship_pack_lot(lot["id"], fixtures.users.WAREHOUSE))

    assert shipped["logistics_status"] == LotLogisticsStatus.SHIPPED
    assert shipped["shipped_at"] == "2026-08-04T00:00:00.000Z"


def test_06_job_close_drives_the_lining_past_the_rebuild_threshold(api):
    """600.00 wear units on a 620.00 unit lining leave 3.23 percent and REBUILD_DUE.

    PRD: "Otherwise, if `refractory_remaining_pct` is 5.00 or lower, posture is
    `REBUILD_DUE`."

    PRD: "Wind-down is not always a human decision — closing a job that drives
    the furnace's `refractory_remaining_pct` to 5.00 or below triggers the same
    `ACTIVE → WIND_DOWN` transition automatically, with the same cascade."

    Design: Difficulty/transitive_cascade/job_close_refractory_threshold_cascades_winddown_and_cancels_scheduled_job
    """
    ctx, job_a, _job_b = _short_lined_furnace_with_two_jobs(api)

    closed = fixtures.close_job(api, job_a["id"], "COMPLETED", produced_units=3000000)
    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    campaign = fixtures.read_campaign(api, ctx.campaign_id)

    assert closed["refractory_wear_units"] == 600.00
    assert closed["status"] == ProductionJobStatus.COMPLETED
    assert furnace["refractory_consumed_units"] == 600.00
    assert furnace["refractory_remaining_pct"] == 3.23
    assert furnace["posture"] == FurnacePosture.REBUILD_DUE
    assert campaign["status"] == CampaignStatus.WIND_DOWN
    assert campaign["melt_tons_charged"] == 600.00


def test_07_the_automatic_wind_down_cancels_the_later_job_and_frees_its_tons(api):
    """The cascade reaches the sibling job and returns the furnace reservation to 0.00.

    PRD: "Wind-down cascades: every job on the campaign still in `SCHEDULED`
    whose `window_start_at` is on or after the logical clock at the wind-down
    instant is moved to `CANCELLED`, and each cancelled job's
    `reserved_melt_tons` is subtracted from the furnace's `reserved_pull_tons`."

    Design: Difficulty/transitive_cascade/job_close_refractory_threshold_cascades_winddown_and_cancels_scheduled_job
    """
    ctx, job_a, job_b = _short_lined_furnace_with_two_jobs(api)

    fixtures.close_job(api, job_a["id"], "COMPLETED", produced_units=3000000)
    later = fixtures.read_job(api, job_b["id"])
    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    lot = fixtures.lot_for_job(api, job_a["id"])

    assert later["status"] == ProductionJobStatus.CANCELLED
    assert furnace["reserved_pull_tons"] == 0.00
    assert lot["provisional_yield_pct"] == 95.00
    assert lot["quality_status"] == LotQualityStatus.PENDING_INSPECTION


def test_08_plant_attribution_pulls_the_shipped_lot_back_out_of_release(api):
    """Investigation returns the lot and re-quarantines the glass already sold.

    PRD: "When the attribution is `PLANT` or `SHARED`, the investigation reaches
    back into the warehouse: the lot moves `SHIPPED → RETURNED` on its logistics
    dimension, and if its `quality_status` is `RELEASED` it is pushed back to
    `QUARANTINED`, with the lot's `version` incremented by 1."

    Design: Difficulty/transitive_cascade/complaint_plant_attribution_cascades_quarantine_standing_and_program_suspension
    """
    _ctx, lot, program, complaint, _investigated = _adopted_program_and_investigated_complaint(api)

    current = fixtures.read_lot(api, lot["id"])
    assessed = fixtures.read_program(api, program["id"])

    assert current["logistics_status"] == LotLogisticsStatus.RETURNED
    assert current["quality_status"] == LotQualityStatus.QUARANTINED
    assert assessed["gross_savings_usd"] == 16500.00
    assert assessed["savings_tier"] == SavingsTier.TIER_A
    assert assessed["breakage_risk_delta"] == 0.00
    assert complaint["breakage_ppm"] == 2500.0


def test_09_credited_settlement_cascades_standing_to_critical_and_suspends_the_program(api):
    """One settlement credits 465.75, turns the customer CRITICAL and suspends the pilot.

    PRD: "And when a settlement drives the standing to `CRITICAL`, every
    lightweighting program in `PILOT` or `ADOPTED` on any of that customer's
    designs is moved to `SUSPENDED`, each with its own `version` incremented by
    1."

    Design: Difficulty/transitive_cascade/complaint_plant_attribution_cascades_quarantine_standing_and_program_suspension
    """
    ctx, _lot, program, complaint, _investigated = _adopted_program_and_investigated_complaint(api)

    settled = validate_success(
        api.settle_complaint(
            complaint["id"], {"settlement": "CREDIT"}, fixtures.users.customer_rep(ctx.customer_id)
        )
    )
    customer = fixtures.read_customer(api, ctx.customer_id)
    suspended = fixtures.read_program(api, program["id"])

    assert settled["affected_pallets"] == 3
    assert settled["credit_usd"] == 465.75
    assert settled["status"] == ComplaintStatus.CREDIT_ISSUED
    assert customer["credit_issued_usd"] == 465.75
    assert customer["weighted_breakage_ppm"] == 2500.00
    assert customer["quality_standing"] == QualityStanding.CRITICAL
    assert suspended["status"] == ProgramStatus.SUSPENDED
