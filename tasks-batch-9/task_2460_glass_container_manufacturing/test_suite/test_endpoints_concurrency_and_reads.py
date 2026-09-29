"""Sub-resource reads, the default clock, optimistic concurrency and read-your-write visibility."""

from test_helpers import (
    ApiErrorId,
    CampaignStatus,
    ColorChangeStatus,
    DefectClass,
    FurnacePosture,
    GlassColor,
    MoldFamily,
    PalletizationStandard,
    ProductionJobStatus,
    ProgramStatus,
    QualityStanding,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CAMPAIGN_START = "2026-08-01T00:00:00Z"
CAMPAIGN_END = "2026-08-11T00:00:00Z"
JOB_END = "2026-08-03T00:00:00Z"
SECOND_JOB_START = "2026-08-03T01:00:00Z"
SECOND_JOB_END = "2026-08-05T01:00:00Z"


def _ten_day_plant(api, suffix, **kwargs):
    """A furnace with a ten-day ACTIVE campaign at design pull, plus the usual assets."""
    kwargs.setdefault(
        "furnace",
        {"code": f"FUR-{suffix}", "design_pull_tpd": 300.00,
         "refractory_life_total_units": 100000.00},
    )
    kwargs.setdefault("customer", {"account_code": f"ACC-{suffix}"})
    kwargs.setdefault(
        "campaign",
        {
            "code": f"CMP-{suffix}",
            "target_pull_tpd": 300.00,
            "window_start_at": CAMPAIGN_START,
            "window_end_at": CAMPAIGN_END,
        },
    )
    kwargs.setdefault("recipe", {"code": f"BR-{suffix}", "cullet_ratio_pct": 40.00})
    kwargs.setdefault(
        "machine",
        {"code": f"IS-{suffix}", "max_cavities": 40, "primary_mold_family": MoldFamily.NNPB},
    )
    kwargs.setdefault("design", {"code": f"BD-{suffix}", "nominal_weight_g": 190.00})
    kwargs.setdefault("mold_set", {"code": f"MS-{suffix}"})
    return fixtures.bring_up_plant(api, **kwargs)


def test_01_the_reading_sub_resource_is_parent_scoped_and_class_filtered(api):
    """Filtering MAJOR returns the single matching row; the unfiltered read keeps both in order.

    PRD: "List endpoints additionally accept filters drawn from the entity's own
    attributes, and filters combine conjunctively."

    PRD: "Results are ordered by `created_at` ascending in every list endpoint, so
    a stable page boundary is guaranteed for a collection that is not being written
    to."

    PRD: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before pagination)
    and `has_more` (true when records remain beyond the current page)."

    PRD: "Each accepted reading recomputes the lot's `reject_units` as the sum of
    `rejected_units` over all its readings regardless of class, recomputes
    `net_packed_units` as `packed_units` less `reject_units`, recomputes both
    parts-per-million figures, and increments the lot's `version` by 1."

    Design: Corner/endpoints/inspection_results_sub_resource_listing_filters_by_defect_class
    """
    ctx = _ten_day_plant(api, "E1")
    _job, lot = fixtures.completed_job_with_lot(
        api, ctx, produced_units=3000000, code="PJ-E1",
        window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
    )
    fixtures.record_reading(
        api, lot["id"], headers=fixtures.users.QE_INSPECTOR,
        defect_class=DefectClass.MINOR, defect_code="BLISTER", rejected_units=100,
    )
    fixtures.record_reading(
        api, lot["id"], headers=fixtures.users.QE_APPROVER,
        defect_class=DefectClass.MAJOR, defect_code="CHECK_CRACK", rejected_units=200,
    )

    rows, meta = validate_paginated(
        api.list_inspection_results(
            lot["id"], fixtures.users.QE_INSPECTOR, defect_class=DefectClass.MAJOR
        )
    )
    assert meta["total_count"] == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["rejected_units"] == 200
    assert rows[0]["defect_code"] == "CHECK_CRACK"
    assert rows[0]["recorded_by_user_id"] == fixtures.users.QE_APPROVER_ID

    every, all_meta = validate_paginated(
        api.list_inspection_results(lot["id"], fixtures.users.QE_INSPECTOR)
    )
    assert all_meta["total_count"] == 2
    assert [row["defect_class"] for row in every] == [DefectClass.MINOR, DefectClass.MAJOR]

    counted = fixtures.read_lot(api, lot["id"])
    assert counted["reject_units"] == 300
    assert counted["net_packed_units"] == 2999700


def test_02_the_untouched_clock_sits_on_the_epoch_to_the_second(api):
    """A window ending exactly on 2026-08-01 completes; one ending a second later does not.

    PRD: "Before any client sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

    PRD: "Completing a transition moves it `SCHEDULED → COMPLETED` and requires
    three things: the change is still `SCHEDULED`, else
    `ERR_COLOR_CHANGE_STATE_INVALID`; the logical clock has reached or passed
    `window_end_at`, else `ERR_WINDOW_NOT_ELAPSED`; and no job in `RUNNING`
    overlaps the transition window, else `ERR_RUNNING_JOB_PRESENT`."

    PRD: "Completion is the only way the furnace's `current_color` advances: it is
    set to the change's `to_color`, and the furnace's `version` increases by 1."

    Design: Corner/endpoints/clock_defaults_to_2026_08_01_for_window_boundaries
    """
    first = fixtures.create_furnace(api, code="FUR-E2-A", design_pull_tpd=300.00)
    second = fixtures.create_furnace(api, code="FUR-E2-B", design_pull_tpd=300.00)
    on_the_epoch = fixtures.schedule_color_change(
        api,
        first["id"],
        to_color=GlassColor.AMBER,
        window_start_at="2026-07-30T00:00:00Z",
        window_end_at=CAMPAIGN_START,
        transition_loss_tons=30.00,
    )
    one_second_late = fixtures.schedule_color_change(
        api,
        second["id"],
        to_color=GlassColor.GREEN,
        window_start_at="2026-07-30T00:00:00Z",
        window_end_at="2026-08-01T00:00:01Z",
        transition_loss_tons=30.00,
    )

    completed = validate_success(
        api.complete_color_change(on_the_epoch["id"], fixtures.users.BATCH_TECH)
    )
    assert completed["status"] == ColorChangeStatus.COMPLETED

    advanced = fixtures.read_furnace(api, first["id"])
    assert advanced["current_color"] == GlassColor.AMBER
    assert advanced["version"] == 2

    refused = api.complete_color_change(one_second_late["id"], fixtures.users.BATCH_TECH)
    validate_error(refused, ApiErrorId.ERR_WINDOW_NOT_ELAPSED, 409)

    unchanged = fixtures.read_furnace(api, second["id"])
    assert unchanged["current_color"] == GlassColor.FLINT
    assert unchanged["version"] == 1

    held = validate_success(
        api.get_color_change(one_second_late["id"], fixtures.users.BATCH_TECH)
    )
    assert held["status"] == ColorChangeStatus.SCHEDULED
    assert held["to_color"] == GlassColor.GREEN


def test_03_the_campaign_sub_resource_never_leaks_across_furnaces(api):
    """Each furnace lists only its own campaigns, and the status filter narrows to one.

    PRD: "Nested resources are addressed hierarchically and path identifiers are
    resolved strictly left to right, with the first unresolvable identifier
    deciding the error."

    PRD: "List endpoints additionally accept filters drawn from the entity's own
    attributes, and filters combine conjunctively."

    PRD: "Creating a campaign is also a mutation of the furnace: `campaign_count`
    increases by 1 and the furnace's `version` increases by 1."

    Design: Corner/endpoints/furnace_campaign_sub_resource_scoped_to_parent
    """
    first = fixtures.create_furnace(api, code="FUR-E3-A", design_pull_tpd=300.00)
    second = fixtures.create_furnace(api, code="FUR-E3-B", design_pull_tpd=300.00)

    active = fixtures.create_campaign(
        api, first["id"], code="CMP-E3-A1", target_pull_tpd=300.00,
        window_start_at=CAMPAIGN_START, window_end_at=CAMPAIGN_END,
    )
    fixtures.activate_campaign(api, active["id"])
    planned = fixtures.create_campaign(
        api, first["id"], code="CMP-E3-A2", target_pull_tpd=300.00,
        window_start_at="2026-08-12T00:00:00Z", window_end_at="2026-08-22T00:00:00Z",
    )
    other = fixtures.create_campaign(
        api, second["id"], code="CMP-E3-B1", target_pull_tpd=300.00,
        window_start_at=CAMPAIGN_START, window_end_at=CAMPAIGN_END,
    )

    rows, meta = validate_paginated(
        api.list_furnace_campaigns(first["id"], fixtures.users.PLANT_MANAGER)
    )
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [active["id"], planned["id"]]
    assert [row["status"] for row in rows] == [CampaignStatus.ACTIVE, CampaignStatus.PLANNED]
    assert other["id"] not in [row["id"] for row in rows]

    filtered, filtered_meta = validate_paginated(
        api.list_furnace_campaigns(
            first["id"], fixtures.users.PLANT_MANAGER, status=CampaignStatus.PLANNED
        )
    )
    assert filtered_meta["total_count"] == 1
    assert [row["id"] for row in filtered] == [planned["id"]]

    foreign, foreign_meta = validate_paginated(
        api.list_furnace_campaigns(second["id"], fixtures.users.PLANT_MANAGER)
    )
    assert foreign_meta["total_count"] == 1
    assert [row["id"] for row in foreign] == [other["id"]]

    assert fixtures.read_furnace(api, first["id"])["campaign_count"] == 2
    assert fixtures.read_furnace(api, second["id"])["campaign_count"] == 1


def test_04_the_pallet_standard_patch_touches_one_field_and_returns_the_customer(api):
    """The narrow write returns the whole updated customer with every other field intact.

    PRD: "A customer may renegotiate its pallet pattern, and a `PlantManager`
    records the change by supplying the new `palletization_standard`."

    PRD: "Most resources also carry an `updated_at` timestamp in the same format,
    refreshed on every mutation, and a `version` integer that starts at 1 when the
    resource is created and increases by exactly 1 on every mutation the server
    applies — including mutations applied as a cascade from another entity's
    operation, not only those requested directly."

    PRD: "`weighted_breakage_ppm` is recomputed from scratch over the customer's
    complaints in `CREDIT_ISSUED` only — complaints in `OPEN`, `INVESTIGATING` or
    `REJECTED` are excluded entirely — processed in `created_at` ascending order:
    it is the sum over those complaints of `breakage_ppm` multiplied by
    `affected_units`, divided by the sum of their `affected_units`, rounded half up
    to 2 decimals, and it is 0 when no credited complaint exists."

    Design: Corner/endpoints/customer_palletization_standard_patch_returns_updated_entity
    """
    customer = fixtures.create_customer(
        api,
        name="Tau Filling",
        account_code="CUST-E4",
        palletization_standard=PalletizationStandard.EURO,
        complaint_ppm_threshold=5000.00,
    )

    patched = validate_success(
        api.patch_customer_palletization_standard(
            customer["id"],
            factories.palletization_standard_payload(PalletizationStandard.GMA),
            fixtures.users.PLANT_MANAGER,
        )
    )
    assert patched["palletization_standard"] == PalletizationStandard.GMA
    assert patched["version"] == 2
    assert patched["name"] == "Tau Filling"
    assert patched["account_code"] == "CUST-E4"
    assert patched["complaint_ppm_threshold"] == 5000.00
    assert patched["quality_standing"] == QualityStanding.GOOD
    assert patched["weighted_breakage_ppm"] == 0.00
    assert patched["credit_issued_usd"] == 0.00


def test_05_a_furnace_version_is_spent_by_the_very_create_that_uses_it(api):
    """The pre-campaign version is already stale, and each successful create stales its own.

    PRD: "Scheduling a production job requires `expected_furnace_version` carrying
    the `version` of the target furnace as the client last observed it."

    PRD: "If `expected_furnace_version` does not equal the furnace's current
    `version`, the create is rejected with `ERR_STALE_FURNACE_VERSION` (HTTP 412)
    rather than silently over-subscribing the furnace."

    PRD: "The server computes `reserved_melt_tons` from the planned pull and
    window length, adds that figure to the furnace's `reserved_pull_tons`,
    increments the furnace's `version` by 1, and records both refractory
    projections at once: `projected_refractory_units_nominal` from the nominal
    variant and `projected_refractory_units_stress_adjusted` from the
    stress-adjusted variant, both over the job's own window using the job's recipe
    colour."

    Design: Corner/cross_cutting_layers/job_create_with_a_stale_furnace_version_rejected
    """
    furnace = fixtures.create_furnace(
        api, code="FUR-CC1", design_pull_tpd=300.00, refractory_life_total_units=100000.00
    )
    stale_version = furnace["version"]
    assert stale_version == 1

    customer = fixtures.create_customer(api, name="Uxbridge Filling", account_code="CUST-CC1")
    campaign = fixtures.create_campaign(
        api, furnace["id"], code="CMP-CC1", target_pull_tpd=300.00,
        window_start_at=CAMPAIGN_START, window_end_at=CAMPAIGN_END,
    )
    fixtures.activate_campaign(api, campaign["id"])
    recipe = fixtures.create_approved_recipe(api, furnace["id"], code="BR-CC1")
    machine = fixtures.create_forming_machine(
        api, furnace["id"], code="IS-CC1", max_cavities=40,
        primary_mold_family=MoldFamily.NNPB,
    )
    design = fixtures.create_design(api, customer["id"], code="BD-CC1")

    current_version = fixtures.furnace_version(api, furnace["id"])
    assert current_version > stale_version

    def _payload(code, expected, window_start, window_end):
        return factories.production_job_payload(
            campaign["id"],
            furnace["id"],
            machine["id"],
            recipe["id"],
            design["id"],
            expected,
            code=code,
            window_start_at=window_start,
            window_end_at=window_end,
            planned_pull_tpd=300.00,
        )

    refused = api.create_production_job(
        _payload("PJ-CC1-STALE", stale_version, CAMPAIGN_START, JOB_END),
        fixtures.users.SCHEDULER,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_FURNACE_VERSION, 412)

    untouched = fixtures.read_furnace(api, furnace["id"])
    assert untouched["reserved_pull_tons"] == 0.00
    assert untouched["version"] == current_version

    first = validate_success(
        api.create_production_job(
            _payload("PJ-CC1-A", current_version, CAMPAIGN_START, JOB_END),
            fixtures.users.SCHEDULER,
        ),
        201,
    )
    assert first["reserved_melt_tons"] == 600.00

    advanced = fixtures.read_furnace(api, furnace["id"])
    assert advanced["version"] == current_version + 1
    assert advanced["reserved_pull_tons"] == 600.00

    replayed = api.create_production_job(
        _payload("PJ-CC1-B", current_version, SECOND_JOB_START, SECOND_JOB_END),
        fixtures.users.SCHEDULER,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_FURNACE_VERSION, 412)

    validate_success(
        api.create_production_job(
            _payload("PJ-CC1-B", current_version + 1, SECOND_JOB_START, SECOND_JOB_END),
            fixtures.users.SCHEDULER,
        ),
        201,
    )

    settled = fixtures.read_furnace(api, furnace["id"])
    assert settled["version"] == current_version + 2
    assert settled["reserved_pull_tons"] == 1200.00


def test_06_a_design_version_is_spent_by_the_program_create_that_uses_it(api):
    """The sign-off version is stale after approval, and each program create stales its own.

    PRD: "If `expected_design_version` does not equal the design's current
    `version`, the create is rejected with `ERR_STALE_DESIGN_VERSION` (HTTP 412)."

    PRD: "Every one of these transitions increments the design's `version` by 1,
    and a transition attempted from the wrong state is refused with
    `ERR_DESIGN_STATE_INVALID`."

    PRD: "Any existing program on the same `baseline_design_id` that is not already
    terminal — that is, one in `DRAFT`, `RISK_ASSESSED`, `PILOT`, `ADOPTED` or
    `SUSPENDED` — is moved to `SUPERSEDED`, with its own `version` incremented by
    1."

    PRD: "Most resources also carry an `updated_at` timestamp in the same format,
    refreshed on every mutation, and a `version` integer that starts at 1 when the
    resource is created and increases by exactly 1 on every mutation the server
    applies — including mutations applied as a cascade from another entity's
    operation, not only those requested directly."

    Design: Corner/cross_cutting_layers/program_create_with_a_stale_design_version_rejected
    """
    customer = fixtures.create_customer(api, name="Verity Filling", account_code="CUST-CC2")
    design = fixtures.create_risk_signed_design(
        api,
        customer["id"],
        code="BD-CC2",
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        target_line_speed_bpm=500.00,
    )
    signed_version = design["version"]
    assert signed_version == 3

    approved = validate_success(
        api.approve_bottle_design(design["id"], fixtures.users.QE_APPROVER)
    )
    assert approved["version"] == 4

    refused = api.create_lightweighting_program(
        factories.lightweighting_program_payload(
            design["id"], signed_version, code="LW-CC2-P1", target_weight_g=189.00
        ),
        fixtures.users.QE_APPROVER,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_DESIGN_VERSION, 412)

    assert fixtures.read_design(api, design["id"])["version"] == 4

    _rows, meta = validate_paginated(
        api.list_lightweighting_programs(
            fixtures.users.QE_APPROVER, baseline_design_id=design["id"]
        )
    )
    assert meta["total_count"] == 0

    first = validate_success(
        api.create_lightweighting_program(
            factories.lightweighting_program_payload(
                design["id"], 4, code="LW-CC2-P1", target_weight_g=189.00
            ),
            fixtures.users.QE_APPROVER,
        ),
        201,
    )
    assert first["status"] == ProgramStatus.DRAFT
    assert fixtures.read_design(api, design["id"])["version"] == 5

    replayed = api.create_lightweighting_program(
        factories.lightweighting_program_payload(
            design["id"], 4, code="LW-CC2-P2", target_weight_g=188.00
        ),
        fixtures.users.QE_APPROVER,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_DESIGN_VERSION, 412)

    validate_success(
        api.create_lightweighting_program(
            factories.lightweighting_program_payload(
                design["id"], 5, code="LW-CC2-P2", target_weight_g=188.00
            ),
            fixtures.users.QE_APPROVER,
        ),
        201,
    )

    assert fixtures.read_program(api, first["id"])["status"] == ProgramStatus.SUPERSEDED
    assert fixtures.read_design(api, design["id"])["version"] == 6


def test_07_every_value_the_close_writes_is_readable_on_the_next_call(api):
    """The close response and the immediately following reads already agree, with no polling.

    PRD: "Both branches require the job to be in `RUNNING`, else
    `ERR_JOB_STATE_INVALID`; both compute `refractory_wear_units` from the
    stress-adjusted refractory variant and charge it to the furnace, adding it to
    `refractory_consumed_units`, recomputing `refractory_remaining_pct` and
    re-deriving `posture`; both move the job's `reserved_melt_tons` out of the
    furnace's `reserved_pull_tons` and into the campaign's `melt_tons_charged`;
    both move the forming machine `RUNNING → IDLE` with its `version` increased by
    1; and both increment the job's `version` by 1."

    PRD: "The stress multiplier is one, plus 2.0 times the fractional over-pull,
    plus 0.8 times the recipe's cullet stress factor, where fractional over-pull is
    the amount by which the job's `planned_pull_tpd` exceeds the furnace's
    `design_pull_tpd` divided by that same `design_pull_tpd`, floored at zero so
    that pulling at or below design contributes nothing."

    PRD: "It creates exactly one pack lot, tying together the job that formed it,
    the campaign that paid for the melt, the design it realises and the customer
    that ordered it, so that a complaint arriving months later can be traced back
    to the furnace hour that produced the glass."

    PRD: "The provisional pack-to-melt yield is one hundred times that gross
    tonnage divided by the job's `reserved_melt_tons`, rounded half up to 2
    decimals."

    Design: Corner/consistency_model/job_close_cascade_is_visible_in_the_same_response
    """
    ctx = _ten_day_plant(api, "CM1")
    job = fixtures.schedule_job(
        api, ctx, code="PJ-CM1", window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
        planned_pull_tpd=300.00,
    )
    assert job["reserved_melt_tons"] == 600.00
    fixtures.start_job(api, job["id"])

    closed = validate_success(
        api.close_production_job(
            job["id"],
            factories.close_job_payload("COMPLETED", produced_units=3000000),
            fixtures.users.SCHEDULER,
        )
    )
    assert closed["status"] == ProductionJobStatus.COMPLETED
    assert closed["produced_units"] == 3000000
    assert closed["refractory_wear_units"] == 600.00

    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    assert furnace["refractory_consumed_units"] == 600.00
    assert furnace["refractory_remaining_pct"] == 99.40
    assert furnace["reserved_pull_tons"] == 0.00
    assert furnace["posture"] == FurnacePosture.OPERATING

    campaign = fixtures.read_campaign(api, ctx.campaign_id)
    assert campaign["melt_tons_charged"] == 600.00
    assert campaign["packed_tons"] == 0.00

    rows, meta = validate_paginated(
        api.list_pack_lots(fixtures.users.QE_RELEASER, production_job_id=job["id"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["packed_units"] == 3000000
    assert rows[0]["unit_weight_g"] == 190.00
    assert rows[0]["provisional_yield_pct"] == 95.00
