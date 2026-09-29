"""Gates that read another entity's state, and the three interval conventions."""

from test_helpers import (
    ApiErrorId,
    ColorChangeStatus,
    ComplaintStatus,
    FormingMachineStatus,
    GlassColor,
    LotLogisticsStatus,
    LotQualityStatus,
    MoldOwner,
    MoldSetStatus,
    PalletizationStandard,
    ProductionJobStatus,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

LONG_CAMPAIGN_END = "2026-08-11T00:00:00Z"
SHIP_DAY = "2026-08-06T00:00:00Z"


def _job_scheduled_against_a_risk_signed_design(api):
    """A job whose design stopped at RISK_SIGNED, so start has an unmet dependency."""
    ctx = fixtures.bring_up_plant(
        api,
        design_state="RISK_SIGNED",
        furnace={
            "code": "F-14",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "November Nectars",
            "account_code": "NOVEMBER-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-14",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F14", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-14", "max_cavities": 40},
        design={
            "code": "BD-14",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-14", "cavity_count": 8, "condition_score": 90},
    )
    job = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-14",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    return ctx, job


def _palletized_lot_never_shipped(api):
    """A RELEASED, PALLETIZED lot of 2000000 good units still inside the plant."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-15",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Oscar Olives",
            "account_code": "OSCAR-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-15",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F15", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-15"},
        design={
            "code": "BD-15",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.CUSTOMER,
        },
        mold_set={
            "code": "MS-15",
            "cavity_count": 8,
            "owner": MoldOwner.CUSTOMER,
            "condition_score": 90,
        },
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=2001000,
        code="PJ-15",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="STONE",
        rejected_units=1000,
        inspected_at="2026-08-01T00:00:00Z",
    )
    fixtures.release_lot(api, lot["id"], fixtures.users.QE_RELEASER)
    fixtures.set_clock(api, SHIP_DAY)
    fixtures.palletize_lot(api, lot["id"])
    return ctx, lot


def _machine_with_one_scheduled_window(api):
    """A machine holding a job over 08-02 to 08-04, with a 45 minute mandatory buffer."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-16",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Papa Preserves",
            "account_code": "PAPA-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-16",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F16", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-16", "changeover_buffer_minutes": 45},
        design={
            "code": "BD-16",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-16A", "cavity_count": 8, "condition_score": 90},
    )
    second_set = fixtures.create_mold_set(
        api, ctx.design_id, code="MS-16B", cavity_count=8, condition_score=90
    )
    first = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-16A",
        window_start_at="2026-08-02T00:00:00Z",
        window_end_at="2026-08-04T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    return ctx, first, second_set


def _furnace_with_one_scheduled_transition(api):
    """A FLINT furnace carrying a single scheduled transition over 08-01 to 08-02."""
    furnace = fixtures.create_furnace(
        api,
        code="F-17",
        design_pull_tpd=300.00,
        refractory_life_total_units=100000.00,
    )
    change = fixtures.schedule_color_change(
        api,
        furnace["id"],
        to_color=GlassColor.AMBER,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-02T00:00:00Z",
        transition_loss_tons=90.00,
    )
    return furnace, change


def test_01_start_is_refused_while_the_design_is_only_risk_signed(api):
    """The job is scheduled fine but cannot start against an unapproved design.

    PRD: "The batch recipe's `approved` flag must be true and the bottle design
    must be in `APPROVED`; the design is checked first and reports
    `ERR_DESIGN_NOT_APPROVED`, the recipe second and reports
    `ERR_RECIPE_NOT_APPROVED`."

    PRD: "A successfully scheduled job is created in `status` `SCHEDULED` with
    `changeover_minutes` 0, `refractory_wear_units` 0, `produced_units` 0 and
    `outcome_note` null."

    Design: Difficulty/cross_entity_state_dependency/job_start_blocked_until_bottle_design_reaches_approved
    """
    ctx, job = _job_scheduled_against_a_risk_signed_design(api)

    validate_error(
        api.start_production_job(job["id"], fixtures.users.SCHEDULER),
        ApiErrorId.ERR_DESIGN_NOT_APPROVED,
        409,
    )
    current = fixtures.read_job(api, job["id"])
    mold_set = fixtures.read_mold_set(api, ctx.mold_set_id)
    machine = fixtures.read_machine(api, ctx.machine_id)

    assert current["status"] == ProductionJobStatus.SCHEDULED
    assert current["changeover_minutes"] == 0
    assert mold_set["status"] == MoldSetStatus.AVAILABLE
    assert machine["mounted_cavities"] == 0
    assert machine["status"] == FormingMachineStatus.IDLE


def test_02_approving_the_design_lets_the_identical_start_through(api):
    """A second quality engineer's approval unblocks the start and costs 60 minutes.

    PRD: "Changeover downtime is a weighted penalty on a base of 60 minutes."

    Design: Difficulty/cross_entity_state_dependency/job_start_blocked_until_bottle_design_reaches_approved
    """
    ctx, job = _job_scheduled_against_a_risk_signed_design(api)
    validate_error(
        api.start_production_job(job["id"], fixtures.users.SCHEDULER),
        ApiErrorId.ERR_DESIGN_NOT_APPROVED,
        409,
    )

    validate_success(api.approve_bottle_design(ctx.design_id, fixtures.users.QE_APPROVER))
    started = validate_success(api.start_production_job(job["id"], fixtures.users.SCHEDULER))
    mold_set = fixtures.read_mold_set(api, ctx.mold_set_id)
    machine = fixtures.read_machine(api, ctx.machine_id)

    assert started["status"] == ProductionJobStatus.RUNNING
    assert started["changeover_minutes"] == 60
    assert mold_set["status"] == MoldSetStatus.MOUNTED
    assert machine["mounted_cavities"] == 8


def test_03_a_complaint_cannot_name_a_lot_that_never_left_the_plant(api):
    """Filing against a PALLETIZED lot is refused and persists nothing.

    PRD: "The lot must be in `logistics_status` `SHIPPED`, since a lot still in
    the plant cannot have broken at a customer, else `ERR_LOT_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/complaint_create_blocked_until_pack_lot_reaches_shipped
    """
    ctx, lot = _palletized_lot_never_shipped(api)

    payload = factories.complaint_payload(
        ctx.customer_id,
        lot["id"],
        code="CO-15",
        reported_at=SHIP_DAY,
        affected_units=4000,
        filling_line_speed_bpm=460.00,
    )
    error = validate_error(
        api.create_complaint(payload, ctx.rep_headers),
        ApiErrorId.ERR_LOT_STATE_INVALID,
        409,
    )
    complaints, _meta = validate_paginated(
        api.list_complaints(ctx.rep_headers, customer_id=ctx.customer_id)
    )
    current = fixtures.read_lot(api, lot["id"])

    assert error["error_id"] != ApiErrorId.ERR_CODE_NOT_UNIQUE
    assert complaints == []
    assert current["quality_status"] == LotQualityStatus.RELEASED
    assert current["logistics_status"] == LotLogisticsStatus.PALLETIZED


def test_04_shipping_the_lot_admits_the_identical_complaint(api):
    """The same body succeeds once the glass has shipped, reading 2000.0 ppm.

    PRD: "The server computes `breakage_ppm` immediately as one million times
    `affected_units` divided by the lot's `net_packed_units`, rounded half up to 1
    decimal — the customer's breakage rate expressed against the good glass
    actually delivered."

    Design: Difficulty/cross_entity_state_dependency/complaint_create_blocked_until_pack_lot_reaches_shipped
    """
    ctx, lot = _palletized_lot_never_shipped(api)
    payload = factories.complaint_payload(
        ctx.customer_id,
        lot["id"],
        code="CO-15",
        reported_at=SHIP_DAY,
        affected_units=4000,
        filling_line_speed_bpm=460.00,
    )
    validate_error(
        api.create_complaint(payload, ctx.rep_headers),
        ApiErrorId.ERR_LOT_STATE_INVALID,
        409,
    )

    fixtures.ship_lot(api, lot["id"])
    filed = validate_success(api.create_complaint(payload, ctx.rep_headers), 201)
    current = fixtures.read_lot(api, lot["id"])

    assert filed["status"] == ComplaintStatus.OPEN
    assert filed["breakage_ppm"] == 2000.0
    assert current["logistics_status"] == LotLogisticsStatus.SHIPPED


def test_05_a_job_starting_at_the_earlier_windows_end_still_collides(api):
    """The mandatory buffer pushes the occupied window past the abutting start.

    PRD: "Two jobs on the same forming machine may therefore abut exactly — one
    ending at the instant the next begins — except that the machine's mandatory
    `changeover_buffer_minutes` is appended to the earlier job's end before the
    comparison is made, so true abutment is only legal on a machine whose buffer
    is zero."

    Design: Difficulty/resource_temporal_overlap/forming_machine_half_open_windows_plus_changeover_buffer
    """
    ctx, _first, second_set = _machine_with_one_scheduled_window(api)

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-16B",
        window_start_at="2026-08-04T00:00:00Z",
        window_end_at="2026-08-06T00:00:00Z",
        planned_pull_tpd=300.00,
        mold_set_id=second_set["id"],
    )
    validate_error(
        api.create_production_job(payload, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT,
        409,
    )
    furnace = fixtures.read_furnace(api, ctx.furnace_id)

    assert furnace["reserved_pull_tons"] == 600.00


def test_06_a_job_starting_exactly_after_the_buffer_is_accepted(api):
    """Forty-five minutes later the same window is free and reserves its own 600.00 tons.

    PRD: "A candidate job's own demand is its `planned_pull_tpd` multiplied by its
    window length in days, rounded half up to 2 decimals, and that figure is
    stored as the job's `reserved_melt_tons`."

    Design: Difficulty/resource_temporal_overlap/forming_machine_half_open_windows_plus_changeover_buffer
    """
    ctx, _first, second_set = _machine_with_one_scheduled_window(api)
    blocked = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-16B",
        window_start_at="2026-08-04T00:00:00Z",
        window_end_at="2026-08-06T00:00:00Z",
        planned_pull_tpd=300.00,
        mold_set_id=second_set["id"],
    )
    validate_error(
        api.create_production_job(blocked, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT,
        409,
    )

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-16C",
        window_start_at="2026-08-04T00:45:00Z",
        window_end_at="2026-08-06T00:45:00Z",
        planned_pull_tpd=300.00,
        mold_set_id=second_set["id"],
    )
    accepted = validate_success(
        api.create_production_job(payload, fixtures.users.SCHEDULER), 201
    )
    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    jobs, _meta = validate_paginated(
        api.list_production_jobs(fixtures.users.SCHEDULER, campaign_id=ctx.campaign_id)
    )

    assert accepted["status"] == ProductionJobStatus.SCHEDULED
    assert accepted["reserved_melt_tons"] == 600.00
    assert furnace["reserved_pull_tons"] == 1200.00
    assert sorted(job["code"] for job in jobs) == ["PJ-16A", "PJ-16C"]


def test_07_a_transition_sharing_one_endpoint_overlaps_the_earlier_one(api):
    """Colour-change windows are closed, so 08-02 is inside the first change.

    PRD: "First, colour-change windows are closed intervals and may not overlap
    another colour change on the same furnace that is in `SCHEDULED` or
    `COMPLETED`; because the intervals are closed, sharing a single endpoint
    counts as an overlap."

    Design: Difficulty/resource_temporal_overlap/color_change_closed_intervals_and_rolling_thirty_day_cap_on_furnace
    """
    furnace, first = _furnace_with_one_scheduled_transition(api)

    assert first["window_end_at"] == "2026-08-02T00:00:00.000Z"

    payload = factories.color_change_payload(
        furnace["id"],
        to_color=GlassColor.GREEN,
        window_start_at="2026-08-02T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        transition_loss_tons=80.00,
    )
    validate_error(
        api.create_color_change(payload, fixtures.users.BATCH_TECH),
        ApiErrorId.ERR_COLOR_CHANGE_WINDOW_CONFLICT,
        409,
    )


def test_08_the_fifth_transition_inside_thirty_days_exhausts_the_allowance(api):
    """Three more transitions are accepted and the fifth is rate-refused.

    PRD: "Third, transitions are rate-limited: counting the change being scheduled
    together with every colour change already on the furnace in `SCHEDULED` or
    `COMPLETED` whose `window_start_at` falls within the 30 days ending at the new
    change's `window_start_at` — that is, on or after the instant exactly 30 days
    earlier and on or before the new start itself — the total may not exceed
    four."

    Design: Difficulty/resource_temporal_overlap/color_change_closed_intervals_and_rolling_thirty_day_cap_on_furnace
    """
    furnace, _first = _furnace_with_one_scheduled_transition(api)

    for to_color, start, end, loss in (
        (GlassColor.GREEN, "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z", 80.00),
        (GlassColor.AMBER, "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z", 70.00),
        (GlassColor.GREEN, "2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z", 70.00),
    ):
        accepted = validate_success(
            api.create_color_change(
                factories.color_change_payload(
                    furnace["id"],
                    to_color=to_color,
                    window_start_at=start,
                    window_end_at=end,
                    transition_loss_tons=loss,
                ),
                fixtures.users.BATCH_TECH,
            ),
            201,
        )
        assert accepted["status"] == ColorChangeStatus.SCHEDULED

    validate_error(
        api.create_color_change(
            factories.color_change_payload(
                furnace["id"],
                to_color=GlassColor.AMBER,
                window_start_at="2026-08-09T00:00:00Z",
                window_end_at="2026-08-10T00:00:00Z",
                transition_loss_tons=70.00,
            ),
            fixtures.users.BATCH_TECH,
        ),
        ApiErrorId.ERR_COLOR_CHANGE_RATE_EXCEEDED,
        409,
    )
    changes, _meta = validate_paginated(
        api.list_furnace_color_changes(furnace["id"], fixtures.users.BATCH_TECH)
    )

    assert len(changes) == 4
    assert all(change["status"] == ColorChangeStatus.SCHEDULED for change in changes)
