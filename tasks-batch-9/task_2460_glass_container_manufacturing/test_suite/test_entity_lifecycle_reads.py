"""Field-level contracts: creation defaults, reads, listings and body foreign keys."""

from test_helpers import (
    ApiErrorId,
    CampaignStatus,
    FormingMachineStatus,
    FurnacePosture,
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
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

LONG_CAMPAIGN_END = "2026-08-11T00:00:00Z"


def test_01_a_furnace_create_seeds_every_computed_field(api):
    """The create returns 201 with the six server-initialised fields at their defaults.

    PRD: "The server initialises the rest: `current_color` is `FLINT`, `posture`
    is `OPERATING`, `refractory_consumed_units` is 0, `refractory_remaining_pct`
    is 100.00, `reserved_pull_tons` is 0, and `campaign_count` is 0."

    Design: Corner/entities/furnace_create_returns_all_declared_fields
    """
    created = validate_success(
        api.create_furnace(
            factories.furnace_payload(
                code="FUR-E1", design_pull_tpd=300.00, refractory_life_total_units=100000.00
            ),
            fixtures.users.PLANT_MANAGER,
        ),
        201,
    )

    assert created["code"] == "FUR-E1"
    assert created["design_pull_tpd"] == 300.00
    assert created["refractory_life_total_units"] == 100000.00
    assert created["current_color"] == GlassColor.FLINT
    assert created["refractory_consumed_units"] == 0.00
    assert created["refractory_remaining_pct"] == 100.00
    assert created["posture"] == FurnacePosture.OPERATING
    assert created["reserved_pull_tons"] == 0.00
    assert created["campaign_count"] == 0
    assert created["version"] == 1
    assert created["id"] and created["created_at"] and created["updated_at"]


def test_02_the_furnace_read_shows_the_campaign_the_create_response_never_saw(api):
    """After one campaign the stored row reads campaign_count 1 and version 2.

    PRD: "Creating a campaign is also a mutation of the furnace: `campaign_count`
    increases by 1 and the furnace's `version` increases by 1."

    Design: Corner/entities/furnace_retrieval_returns_stored_fields
    """
    furnace = fixtures.create_furnace(
        api, code="FUR-E2", design_pull_tpd=300.00, refractory_life_total_units=100000.00
    )
    campaign = fixtures.create_campaign(
        api,
        furnace["id"],
        code="CMP-E2",
        target_pull_tpd=300.00,
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
    )

    stored = validate_success(api.get_furnace(furnace["id"], fixtures.users.PLANT_MANAGER))

    assert furnace["campaign_count"] == 0
    assert stored["code"] == "FUR-E2"
    assert stored["design_pull_tpd"] == 300.00
    assert stored["campaign_count"] == 1
    assert stored["version"] == 2
    assert stored["posture"] == FurnacePosture.OPERATING
    assert stored["refractory_remaining_pct"] == 100.00
    assert campaign["status"] == CampaignStatus.PLANNED


def test_03_the_design_listing_pages_within_one_customers_scope(api):
    """A limit of 2 over three designs reports total_count 3 and never leaks the fourth.

    PRD: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before pagination)
    and `has_more` (true when records remain beyond the current page)."

    Design: Corner/entities/bottle_design_listing_filters_by_customer_and_paginates
    """
    customer_a = fixtures.create_customer(api, name="Alpha Ales", account_code="CUST-A")
    customer_b = fixtures.create_customer(api, name="Bravo Brews", account_code="CUST-B")
    owned = [
        fixtures.create_design(api, customer_a["id"], code=code)["id"]
        for code in ("BD-A1", "BD-A2", "BD-A3")
    ]
    foreign = fixtures.create_design(api, customer_b["id"], code="BD-B1")

    rows, meta = validate_paginated(
        api.list_bottle_designs(
            fixtures.users.MOLD_ENGINEER, customer_id=customer_a["id"], limit=2
        )
    )

    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(rows) == 2
    assert all(row["customer_id"] == customer_a["id"] for row in rows)
    assert foreign["id"] not in [row["id"] for row in rows]

    tail, tail_meta = validate_paginated(
        api.list_bottle_designs(
            fixtures.users.MOLD_ENGINEER, customer_id=customer_a["id"], limit=2, offset=2
        )
    )

    assert len(tail) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False
    assert tail[0]["id"] in owned


def test_04_an_unknown_mold_set_id_answers_with_the_entitys_own_code(api):
    """A well-formed but unknown id is a 404, not a 400 and not an empty body.

    PRD: "Each entity has its own not-found code: `ERR_FURNACE_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_BATCH_RECIPE_NOT_FOUND`,
    `ERR_COLOR_CHANGE_NOT_FOUND`, `ERR_FORMING_MACHINE_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_BOTTLE_DESIGN_NOT_FOUND`,
    `ERR_MOLD_SET_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PRODUCTION_JOB_NOT_FOUND`, `ERR_PACK_LOT_NOT_FOUND` and
    `ERR_COMPLAINT_NOT_FOUND`, each at HTTP 404."

    Design: Corner/entities/mold_set_detail_unknown_id_returns_not_found
    """
    customer = fixtures.create_customer(api, name="Charlie Cellars", account_code="CUST-E4")
    design = fixtures.create_design(api, customer["id"], code="BD-E4")
    existing = fixtures.create_mold_set(api, design["id"], code="MS-E4")

    validate_error(
        api.get_mold_set(NON_EXISTENT_UUID, fixtures.users.MOLD_ENGINEER),
        ApiErrorId.ERR_MOLD_SET_NOT_FOUND,
        404,
    )
    still_there = validate_success(
        api.get_mold_set(existing["id"], fixtures.users.MOLD_ENGINEER)
    )

    assert still_there["status"] == MoldSetStatus.AVAILABLE


def test_05_a_furnace_create_without_its_nameplate_pull_persists_nothing(api):
    """Omitting design_pull_tpd is a 400 and leaves the code free for the retry.

    PRD: "Field-level validation inspects each submitted field in isolation:
    required fields present, types correct, enum values among the declared
    members, numbers inside their declared ranges and decimal precision,
    timestamps well formed."

    PRD: "Failures here are `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/furnace_create_missing_design_pull_tpd_rejected
    """
    payload = factories.furnace_payload(code="FUR-E5", refractory_life_total_units=100000.00)
    payload.pop("design_pull_tpd")

    validate_error(
        api.create_furnace(payload, fixtures.users.PLANT_MANAGER),
        ApiErrorId.ERR_VALIDATION,
        400,
    )
    _rows, meta = validate_paginated(api.list_furnaces(fixtures.users.PLANT_MANAGER))

    assert meta["total_count"] == 0

    retried = validate_success(
        api.create_furnace(
            factories.furnace_payload(
                code="FUR-E5", design_pull_tpd=300.00, refractory_life_total_units=100000.00
            ),
            fixtures.users.PLANT_MANAGER,
        ),
        201,
    )

    assert retried["code"] == "FUR-E5"


def test_06_the_changeover_buffer_default_applies_on_absence_only(api):
    """An omitted buffer becomes 45 while an explicit 0 stays 0.

    PRD: "The optional `changeover_buffer_minutes` is the mandatory idle buffer
    appended after every job window on that machine; when the payload omits it the
    machine takes 45 minutes, and any supplied value must be at least 0 and no
    more than 240."

    PRD: "A newly registered machine has `status` `IDLE` and `mounted_cavities`
    of 0."

    Design: Corner/entities/forming_machine_changeover_buffer_defaults_to_forty_five
    """
    furnace = fixtures.create_furnace(api, code="FUR-E6")
    payload = factories.forming_machine_payload(furnace["id"], code="IS-E6A")
    payload.pop("changeover_buffer_minutes")

    defaulted = validate_success(
        api.create_forming_machine(payload, fixtures.users.PLANT_MANAGER), 201
    )

    assert defaulted["changeover_buffer_minutes"] == 45
    assert defaulted["status"] == FormingMachineStatus.IDLE
    assert defaulted["mounted_cavities"] == 0

    explicit = validate_success(
        api.create_forming_machine(
            factories.forming_machine_payload(
                furnace["id"], code="IS-E6B", changeover_buffer_minutes=0
            ),
            fixtures.users.PLANT_MANAGER,
        ),
        201,
    )

    assert explicit["changeover_buffer_minutes"] == 0


def test_07_the_close_mints_a_lot_whose_every_field_is_derived(api):
    """No lot field is client-supplied: the close derives the code, tonnage and yields.

    PRD: "Every pack lot created at a completed close carries the traceability
    chain as its own references — the originating job, the campaign, the bottle
    design and the customer — and a `lot_code` printed on the pallet label,
    derived as the job's `code` followed by the suffix `-L1` and unique across all
    lots."

    PRD: "A new lot has `reject_units` 0, `net_packed_units` equal to
    `packed_units`, `major_ppm` and `minor_ppm` 0, `final_yield_pct` 0,
    `pallet_count` 0 and `shipped_at` null."

    PRD: "The allowance starts at 3 days."

    Design: Corner/entities/pack_lot_computed_fields_are_derived_at_job_close
    """
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "FUR-E7",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Echo Elixirs",
            "account_code": "CUST-E7",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-E7",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-E7", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-E7"},
        design={
            "code": "BD-E7",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-E7", "cavity_count": 8, "condition_score": 90},
    )
    closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-E7",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    _lots, meta = validate_paginated(
        api.list_pack_lots(fixtures.users.QE_INSPECTOR, production_job_id=closed["id"])
    )

    assert closed["status"] == ProductionJobStatus.COMPLETED
    assert meta["total_count"] == 1
    assert lot["lot_code"] == "PJ-E7-L1"
    assert lot["packed_units"] == 3000000
    assert lot["unit_weight_g"] == 190.00
    assert lot["reject_units"] == 0
    assert lot["net_packed_units"] == 3000000
    assert lot["major_ppm"] == 0.0
    assert lot["minor_ppm"] == 0.0
    assert lot["provisional_yield_pct"] == 95.00
    assert lot["final_yield_pct"] == 0.00
    assert lot["palletization_standard"] == PalletizationStandard.EURO
    assert lot["pallet_count"] == 0
    assert lot["aged_until_at"] == "2026-08-04T00:00:00.000Z"
    assert lot["quality_status"] == LotQualityStatus.PENDING_INSPECTION
    assert lot["logistics_status"] == LotLogisticsStatus.IN_AGING
    assert lot["shipped_at"] is None
    assert lot["production_job_id"] == closed["id"]
    assert lot["campaign_id"] == ctx.campaign_id
    assert lot["bottle_design_id"] == ctx.design_id
    assert lot["customer_id"] == ctx.customer_id


def _lot_of_three_million_units(api, suffix):
    """A PENDING_INSPECTION lot of 3000000 units at 190.00 g on a EURO customer."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": f"FUR-{suffix}",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Foxtrot Foods",
            "account_code": f"CUST-{suffix}",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": f"CMP-{suffix}",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": f"BR-{suffix}", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": f"IS-{suffix}"},
        design={
            "code": f"BD-{suffix}",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": f"MS-{suffix}", "cavity_count": 8, "condition_score": 90},
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code=f"PJ-{suffix}",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    return ctx, lot


def test_08_a_reading_is_stamped_with_the_recording_engineers_own_id(api):
    """The body carries only the observation; the actor comes from the header.

    PRD: "The lot it belongs to is identified by `pack_lot_id`, and the server
    stamps `recorded_by_user_id` from the acting `X-User-ID`, which is what later
    makes the rework two-person control enforceable."

    Design: Corner/entities/inspection_result_records_actor_from_user_id_header
    """
    _ctx, lot = _lot_of_three_million_units(api, "E8")

    reading = validate_success(
        api.record_inspection_result(
            lot["id"],
            factories.inspection_result_payload(
                defect_class="MINOR",
                defect_code="CHECK_CRACK",
                rejected_units=100,
                inspected_at="2026-08-01T00:00:00Z",
            ),
            fixtures.users.QE_INSPECTOR,
        ),
        201,
    )
    current = fixtures.read_lot(api, lot["id"])

    assert reading["recorded_by_user_id"] == fixtures.users.QE_INSPECTOR_ID
    assert reading["pack_lot_id"] == lot["id"]
    assert reading["defect_class"] == "MINOR"
    assert reading["rejected_units"] == 100
    assert current["reject_units"] == 100
    assert current["net_packed_units"] == 2999900
    assert current["minor_ppm"] == 33.3
    assert current["major_ppm"] == 0.0


def test_09_a_correction_is_a_second_append_only_reading(api):
    """The reading has no version and the first row survives the second untouched.

    PRD: "The single exception is the inspection reading: an `InspectionResult`
    carries only `id` and `created_at`. It has neither `updated_at` nor `version`,
    because a reading taken on the inspection line is an immutable observation
    that is never amended."

    Design: Corner/entities/inspection_result_is_immutable_and_carries_no_version
    """
    _ctx, lot = _lot_of_three_million_units(api, "E9")
    first = fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="CHECK_CRACK",
        rejected_units=100,
        inspected_at="2026-08-01T00:00:00Z",
    )

    second = validate_success(
        api.record_inspection_result(
            lot["id"],
            factories.inspection_result_payload(
                defect_class="MINOR",
                defect_code="STONE",
                rejected_units=50,
                inspected_at="2026-08-01T00:00:00Z",
            ),
            fixtures.users.QE_INSPECTOR,
        ),
        201,
    )
    rows, meta = validate_paginated(
        api.list_inspection_results(lot["id"], fixtures.users.QE_INSPECTOR)
    )
    current = fixtures.read_lot(api, lot["id"])

    assert second["id"] != first["id"]
    assert "version" not in first
    assert "version" not in second
    assert meta["total_count"] == 2

    kept = [row for row in rows if row["id"] == first["id"]][0]

    assert kept["rejected_units"] == 100
    assert kept["defect_code"] == "CHECK_CRACK"
    assert current["reject_units"] == 150
    assert current["net_packed_units"] == 2999850


def test_10_recipe_type_checks_answer_before_the_purity_rule(api):
    """An unknown colour and a 95.01 ratio are 400s; 95.00 is accepted at 0.5000 stress.

    PRD: "Soda ash must be greater than 0 with 2 decimals; colorant may be 0 or
    more with 2 decimals; the cullet ratio must be at least 0.00 and no more than
    95.00 with 2 decimals as a matter of type range."

    PRD: "Cullet is also a wear driver, and the recipe carries that exposure as
    `cullet_stress_factor`: the amount by which `cullet_ratio_pct` exceeds 45.00,
    floored at zero, divided by 100, rounded half up to 4 decimals."

    Design: Corner/entities/batch_recipe_out_of_range_and_bad_enum_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-E10")

    validate_error(
        api.create_batch_recipe(
            factories.batch_recipe_payload(
                furnace["id"], code="BR-E10A", color="BLUE", cullet_ratio_pct=40.00
            ),
            fixtures.users.BATCH_TECH,
        ),
        ApiErrorId.ERR_VALIDATION,
        400,
    )
    over_range = validate_error(
        api.create_batch_recipe(
            factories.batch_recipe_payload(
                furnace["id"],
                code="BR-E10B",
                color=GlassColor.AMBER,
                cullet_ratio_pct=95.01,
                colorant_kg_per_ton=3.50,
            ),
            fixtures.users.BATCH_TECH,
        ),
        ApiErrorId.ERR_VALIDATION,
        400,
    )

    assert over_range["error_id"] != ApiErrorId.ERR_CULLET_RATIO_UNSAFE

    accepted = validate_success(
        api.create_batch_recipe(
            factories.batch_recipe_payload(
                furnace["id"],
                code="BR-E10C",
                color=GlassColor.AMBER,
                cullet_ratio_pct=95.00,
                colorant_kg_per_ton=3.50,
            ),
            fixtures.users.BATCH_TECH,
        ),
        201,
    )
    _rows, meta = validate_paginated(
        api.list_furnace_batch_recipes(furnace["id"], fixtures.users.BATCH_TECH)
    )

    assert accepted["cullet_stress_factor"] == 0.5000
    assert meta["total_count"] == 1


def test_11_an_unresolvable_body_foreign_key_answers_before_the_business_rule(api):
    """The unknown furnace is a 404, so the illegal 900.00 target pull never runs.

    PRD: "6. Every foreign key in the body resolves, in declared field order,
    else the corresponding not-found code."

    Design: Corner/entities/campaign_create_with_unknown_furnace_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-E11", design_pull_tpd=300.00)

    error = validate_error(
        api.create_campaign(
            factories.campaign_payload(
                NON_EXISTENT_UUID,
                code="CMP-E11",
                target_pull_tpd=900.00,
                window_start_at="2026-08-01T00:00:00Z",
                window_end_at="2026-08-03T00:00:00Z",
            ),
            fixtures.users.PLANT_MANAGER,
        ),
        ApiErrorId.ERR_FURNACE_NOT_FOUND,
        404,
    )
    stored = fixtures.read_furnace(api, furnace["id"])
    _rows, meta = validate_paginated(
        api.list_furnace_campaigns(furnace["id"], fixtures.users.PLANT_MANAGER)
    )

    assert error["error_id"] != ApiErrorId.ERR_TARGET_PULL_EXCEEDS_DESIGN
    assert stored["campaign_count"] == 0
    assert stored["version"] == 1
    assert meta["total_count"] == 0


def test_12_a_machine_belonging_to_another_furnace_is_a_mismatch_not_a_not_found(api):
    """The foreign machine reports 422 and reserves nothing on either furnace.

    PRD: "The job's forming machine and batch recipe must both belong to the
    furnace named in `furnace_id`, and that furnace must be the campaign's
    furnace; any of those three mismatches reports `ERR_FURNACE_MISMATCH`."

    Design: Corner/entities/job_create_with_machine_from_another_furnace_rejected
    """
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "FUR-E12A",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Golf Growlers",
            "account_code": "CUST-E12",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-E12",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-E12", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-E12A"},
        design={
            "code": "BD-E12",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-E12", "cavity_count": 8, "condition_score": 90},
    )
    other_furnace = fixtures.create_furnace(
        api, code="FUR-E12B", design_pull_tpd=300.00, refractory_life_total_units=100000.00
    )
    foreign_machine = fixtures.create_forming_machine(
        api, other_furnace["id"], code="IS-E12B"
    )

    payload = fixtures.job_payload_for(
        api,
        ctx,
        code="PJ-E12",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
        forming_machine_id=foreign_machine["id"],
    )
    validate_error(
        api.create_production_job(payload, fixtures.users.SCHEDULER),
        ApiErrorId.ERR_FURNACE_MISMATCH,
        422,
    )
    _rows, meta = validate_paginated(
        api.list_production_jobs(fixtures.users.SCHEDULER, campaign_id=ctx.campaign_id)
    )

    assert fixtures.read_furnace(api, ctx.furnace_id)["reserved_pull_tons"] == 0.00
    assert fixtures.read_furnace(api, other_furnace["id"])["reserved_pull_tons"] == 0.00
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_production_job(
            {**payload, "forming_machine_id": ctx.machine_id}, fixtures.users.SCHEDULER
        ),
        201,
    )

    assert accepted["reserved_melt_tons"] == 600.00
