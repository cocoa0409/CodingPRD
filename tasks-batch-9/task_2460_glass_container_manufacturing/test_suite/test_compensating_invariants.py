"""Reservations that must be handed back exactly, with no drift and no leakage."""

from test_helpers import (
    ApiErrorId,
    FormingMachineStatus,
    GlassColor,
    MoldOwner,
    MoldSetStatus,
    PalletizationStandard,
    ProductionJobStatus,
    fixtures,
    validate_error,
    validate_success,
)

LONG_CAMPAIGN_END = "2026-08-11T00:00:00Z"


def _campaign_with_its_whole_pool_reserved(api):
    """A 600.00 ton pool held entirely by one scheduled job, plus spare tooling."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-18",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Quebec Quenchers",
            "account_code": "QUEBEC-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-18",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": "2026-08-03T00:00:00Z",
        },
        recipe={"code": "BR-F18", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-18"},
        design={
            "code": "BD-18",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-18A", "cavity_count": 8, "condition_score": 90},
    )
    second_set = fixtures.create_mold_set(
        api, ctx.design_id, code="MS-18B", cavity_count=8, condition_score=90
    )
    job = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-18A",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    return ctx, job, second_set


def _machine_still_carrying_the_finished_jobs_tooling(api):
    """A closed job whose 20-cavity set is still mounted on a 30-cavity machine."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-19",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Romeo Roasters",
            "account_code": "ROMEO-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-19",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F19", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-19", "max_cavities": 30, "changeover_buffer_minutes": 45},
        design={
            "code": "BD-19",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 20,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-19A", "cavity_count": 20, "condition_score": 90},
    )
    small_set = fixtures.create_mold_set(
        api, ctx.design_id, code="MS-19B", cavity_count=12, condition_score=90
    )
    first = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-19A",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    fixtures.start_job(api, first["id"])
    fixtures.close_job(api, first["id"], "COMPLETED", produced_units=3000000)
    second = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-19B",
        window_start_at="2026-08-04T00:00:00Z",
        window_end_at="2026-08-06T00:00:00Z",
        planned_pull_tpd=300.00,
        mold_set_id=small_set["id"],
    )
    return ctx, second, small_set


def test_01_a_fully_reserved_pool_refuses_a_second_identical_job(api):
    """With 600.00 of 600.00 tons reserved there is nothing left to schedule.

    PRD: "Available tons are that pool less the campaign's `melt_tons_charged`
    less the furnace's `reserved_pull_tons`, again rounded half up to 2 decimals."

    Design: Difficulty/compensating_invariant/job_cancel_returns_reserved_melt_tons_to_the_campaign_pull_pool
    """
    ctx, job, second_set = _campaign_with_its_whole_pool_reserved(api)
    furnace = fixtures.read_furnace(api, ctx.furnace_id)

    assert job["reserved_melt_tons"] == 600.00
    assert furnace["reserved_pull_tons"] == 600.00

    # A second forming machine on the same furnace, so the identical window is
    # uncontended and the exhausted pull pool is the first check that can fail.
    second_machine = fixtures.create_forming_machine(api, ctx.furnace_id, code="IS-18B")
    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-18B",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
        forming_machine_id=second_machine["id"],
        mold_set_id=second_set["id"],
    )
    validate_error(
        api.create_production_job(payload, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_PULL_CAPACITY_EXCEEDED,
        409,
    )


def test_02_cancelling_hands_the_whole_reservation_back_and_charges_no_melt(api):
    """The cancel returns exactly 600.00 tons and leaves the ledger at 0.00.

    PRD: "The job's `reserved_melt_tons` is subtracted from the furnace's
    `reserved_pull_tons`, the furnace's `version` increases by 1, and the job's
    `version` increases by 1."

    PRD: "Nothing is charged to the campaign ledger — a cancelled job never melted
    anything."

    Design: Difficulty/compensating_invariant/job_cancel_returns_reserved_melt_tons_to_the_campaign_pull_pool
    """
    ctx, job, _second_set = _campaign_with_its_whole_pool_reserved(api)

    cancelled = validate_success(api.cancel_production_job(job["id"], fixtures.users.SCHEDULER))
    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    campaign = fixtures.read_campaign(api, ctx.campaign_id)

    assert cancelled["status"] == ProductionJobStatus.CANCELLED
    assert furnace["reserved_pull_tons"] == 0.00
    assert campaign["melt_tons_charged"] == 0.00


def test_03_the_released_pool_and_window_admit_the_identical_job_again(api):
    """Re-creating the same job in the same window lands back on 600.00 with no drift.

    PRD: "The job may only be scheduled when its `reserved_melt_tons` is less
    than or equal to the available tons; anything larger exhausts the pool and is
    refused with `ERR_PULL_CAPACITY_EXCEEDED`."

    Design: Difficulty/compensating_invariant/job_cancel_returns_reserved_melt_tons_to_the_campaign_pull_pool
    """
    ctx, job, second_set = _campaign_with_its_whole_pool_reserved(api)
    fixtures.cancel_job(api, job["id"])

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-18C",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
        mold_set_id=second_set["id"],
    )
    recreated = validate_success(
        api.create_production_job(payload, fixtures.users.SCHEDULER), 201
    )
    furnace = fixtures.read_furnace(api, ctx.furnace_id)

    assert recreated["status"] == ProductionJobStatus.SCHEDULED
    assert recreated["reserved_melt_tons"] == 600.00
    assert furnace["reserved_pull_tons"] == 600.00


def test_04_a_closed_job_leaves_its_cavities_occupied(api):
    """The machine is idle again but the 20 mounted cavities block the next set.

    PRD: "And mounting must fit: the set's `cavity_count` added to the machine's
    current `mounted_cavities` may not exceed the machine's `max_cavities`, else
    `ERR_CAVITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/compensating_invariant/mold_unmount_returns_cavities_to_the_machine_capacity_pool
    """
    ctx, second, small_set = _machine_still_carrying_the_finished_jobs_tooling(api)
    machine = fixtures.read_machine(api, ctx.machine_id)
    mounted = fixtures.read_mold_set(api, ctx.mold_set_id)

    assert machine["mounted_cavities"] == 20
    assert machine["status"] == FormingMachineStatus.IDLE
    assert mounted["status"] == MoldSetStatus.MOUNTED

    validate_error(
        api.start_production_job(second["id"], fixtures.users.SCHEDULER),
        ApiErrorId.ERR_CAVITY_CAPACITY_EXCEEDED,
        409,
    )
    current = fixtures.read_job(api, second["id"])
    waiting = fixtures.read_mold_set(api, small_set["id"])

    assert current["status"] == ProductionJobStatus.SCHEDULED
    assert waiting["status"] == MoldSetStatus.AVAILABLE


def test_05_unmounting_returns_exactly_those_cavities_to_the_machine(api):
    """The unmount subtracts 20, clears the machine link and keeps the mount history.

    PRD: "`MOUNTED → AVAILABLE` is the engineer's unmount: it requires the set to
    be `MOUNTED` and requires that no job referencing this set is in `RUNNING`,
    else `ERR_RUNNING_JOB_PRESENT`; it clears `forming_machine_id`, subtracts the
    set's `cavity_count` from the machine's `mounted_cavities`, increments the
    machine's `version` by 1, and increments the set's own `version` by 1."

    Design: Difficulty/compensating_invariant/mold_unmount_returns_cavities_to_the_machine_capacity_pool
    """
    ctx, _second, _small_set = _machine_still_carrying_the_finished_jobs_tooling(api)

    unmounted = validate_success(
        api.unmount_mold_set(ctx.mold_set_id, fixtures.users.MOLD_ENGINEER)
    )
    machine = fixtures.read_machine(api, ctx.machine_id)

    assert unmounted["status"] == MoldSetStatus.AVAILABLE
    assert unmounted["forming_machine_id"] is None
    assert unmounted["mount_count"] == 1
    assert machine["mounted_cavities"] == 0


def test_06_the_refused_start_succeeds_once_the_cavities_are_free(api):
    """The 12-cavity set mounts cleanly and the changeover costs 120 minutes.

    PRD: "The cavity penalty depends on the absolute difference between the mold
    set's `cavity_count` and the design's `cavity_count`: 0 minutes when the two
    are equal, 15 minutes when the difference is 1 or 2, 35 minutes when it is 3,
    4 or 5, and 60 minutes when it is greater than 5."

    Design: Difficulty/compensating_invariant/mold_unmount_returns_cavities_to_the_machine_capacity_pool
    """
    ctx, second, small_set = _machine_still_carrying_the_finished_jobs_tooling(api)
    validate_error(
        api.start_production_job(second["id"], fixtures.users.SCHEDULER),
        ApiErrorId.ERR_CAVITY_CAPACITY_EXCEEDED,
        409,
    )
    validate_success(api.unmount_mold_set(ctx.mold_set_id, fixtures.users.MOLD_ENGINEER))

    started = validate_success(api.start_production_job(second["id"], fixtures.users.SCHEDULER))
    machine = fixtures.read_machine(api, ctx.machine_id)
    mounted = fixtures.read_mold_set(api, small_set["id"])

    assert started["status"] == ProductionJobStatus.RUNNING
    assert started["changeover_minutes"] == 120
    assert machine["mounted_cavities"] == 12
    assert mounted["status"] == MoldSetStatus.MOUNTED
