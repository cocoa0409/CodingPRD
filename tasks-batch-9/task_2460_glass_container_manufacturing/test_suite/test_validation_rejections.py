"""Business-rule validations: the satisfied path, the refused path and the boundary between them."""

from test_helpers import (
    ApiErrorId,
    CampaignStatus,
    ComplaintStatus,
    DefectClass,
    FurnacePosture,
    GlassColor,
    LotLogisticsStatus,
    LotQualityStatus,
    MoldFamily,
    PalletizationStandard,
    ProductionJobStatus,
    Role,
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
    kwargs.setdefault(
        "campaign",
        {
            "code": f"CMP-{suffix}",
            "target_pull_tpd": 300.00,
            "window_start_at": CAMPAIGN_START,
            "window_end_at": CAMPAIGN_END,
        },
    )
    kwargs.setdefault("recipe", {"code": f"BR-{suffix}"})
    kwargs.setdefault(
        "machine",
        {"code": f"IS-{suffix}", "max_cavities": 40, "primary_mold_family": MoldFamily.NNPB},
    )
    kwargs.setdefault("mold_set", {"code": f"MS-{suffix}"})
    return fixtures.bring_up_plant(api, **kwargs)


def test_01_a_job_that_satisfies_every_rule_moves_its_reservation_onto_the_furnace(api):
    """The accepted create reserves 600.00 tons, projects both wear variants and charges nothing.

    PRD: "A candidate job's own demand is its `planned_pull_tpd` multiplied by its
    window length in days, rounded half up to 2 decimals, and that figure is
    stored as the job's `reserved_melt_tons`."

    PRD: "The server computes `reserved_melt_tons` from the planned pull and
    window length, adds that figure to the furnace's `reserved_pull_tons`,
    increments the furnace's `version` by 1, and records both refractory
    projections at once: `projected_refractory_units_nominal` from the nominal
    variant and `projected_refractory_units_stress_adjusted` from the
    stress-adjusted variant, both over the job's own window using the job's
    recipe colour."

    PRD: "A successfully scheduled job is created in `status` `SCHEDULED` with
    `changeover_minutes` 0, `refractory_wear_units` 0, `produced_units` 0 and
    `outcome_note` null."

    Design: Corner/validations/job_create_with_every_rule_satisfied_reserves_melt_tons
    """
    ctx = _ten_day_plant(api, "V1", design={"code": "BD-V1"})

    created = validate_success(
        api.create_production_job(
            fixtures.job_payload_for(
                api,
                ctx,
                code="PJ-V1",
                window_start_at=CAMPAIGN_START,
                window_end_at=JOB_END,
                planned_pull_tpd=300.00,
            ),
            fixtures.users.SCHEDULER,
        ),
        201,
    )

    assert created["status"] == ProductionJobStatus.SCHEDULED
    assert created["reserved_melt_tons"] == 600.00
    assert created["projected_refractory_units_nominal"] == 600.00
    assert created["projected_refractory_units_stress_adjusted"] == 600.00
    assert created["changeover_minutes"] == 0
    assert created["refractory_wear_units"] == 0.00
    assert created["produced_units"] == 0
    assert created["outcome_note"] is None

    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    assert furnace["reserved_pull_tons"] == 600.00

    campaign = fixtures.read_campaign(api, ctx.campaign_id)
    assert campaign["melt_tons_charged"] == 0.00


def test_02_the_cullet_purity_ceiling_binds_flint_only(api):
    """92.00 percent cullet is a 422 on FLINT and a legal 201 on AMBER.

    PRD: "On top of that type range sits a colour-purity limit: a `FLINT` recipe
    may not exceed 90.00 percent cullet, because flint glass shows contamination
    that amber and green hide."

    PRD: "Cullet is also a wear driver, and the recipe carries that exposure as
    `cullet_stress_factor`: the amount by which `cullet_ratio_pct` exceeds 45.00,
    floored at zero, divided by 100, rounded half up to 4 decimals."

    PRD: "New recipes are created with `approved` false; approval by a
    `BatchHouseTech` sets `approved` to true and is the gate that lets production
    use the recipe at all."

    Design: Corner/validations/cullet_ratio_above_flint_purity_limit_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-V2")

    refused = api.create_batch_recipe(
        factories.batch_recipe_payload(
            furnace["id"], code="BR-V2-FLINT", color=GlassColor.FLINT, cullet_ratio_pct=92.00
        ),
        fixtures.users.BATCH_TECH,
    )
    validate_error(refused, ApiErrorId.ERR_CULLET_RATIO_UNSAFE, 422)

    _rows, meta = validate_paginated(
        api.list_furnace_batch_recipes(furnace["id"], fixtures.users.BATCH_TECH)
    )
    assert meta["total_count"] == 0

    amber = validate_success(
        api.create_batch_recipe(
            factories.batch_recipe_payload(
                furnace["id"], code="BR-V2-AMBER", color=GlassColor.AMBER, cullet_ratio_pct=92.00
            ),
            fixtures.users.BATCH_TECH,
        ),
        201,
    )
    assert amber["cullet_stress_factor"] == 0.4700
    assert amber["approved"] is False

    flint_at_ceiling = validate_success(
        api.create_batch_recipe(
            factories.batch_recipe_payload(
                furnace["id"], code="BR-V2-FLINT-AT", color=GlassColor.FLINT,
                cullet_ratio_pct=90.00,
            ),
            fixtures.users.BATCH_TECH,
        ),
        201,
    )
    assert flint_at_ceiling["cullet_stress_factor"] == 0.4500


def test_03_the_over_pull_ceiling_is_a_multiple_of_the_nameplate(api):
    """350.00 tpd is refused on a 300.00 tpd furnace while 345.00 reserves 690.00 tons.

    PRD: "A job may never request more than 1.15 times the furnace's
    `design_pull_tpd`, which is the fifteen-percent over-pull the lining can
    tolerate at all; and while the furnace's posture is `RESTRICTED`, the job may
    not exceed `design_pull_tpd` at all, because a furnace with 15.00 percent or
    less of its refractory life left is no longer permitted to be pushed."

    PRD: "A candidate job's own demand is its `planned_pull_tpd` multiplied by its
    window length in days, rounded half up to 2 decimals, and that figure is
    stored as the job's `reserved_melt_tons`."

    Design: Corner/validations/over_pull_limit_exceeded_on_job_create
    """
    ctx = _ten_day_plant(
        api, "V3", design={"code": "BD-V3"}, approve_recipe=False, design_state="DRAFT"
    )
    window = {"window_start_at": CAMPAIGN_START, "window_end_at": JOB_END}

    refused = api.create_production_job(
        fixtures.job_payload_for(
            api, ctx, code="PJ-V3-OVER", planned_pull_tpd=350.00, **window
        ),
        fixtures.users.SCHEDULER,
    )
    validate_error(refused, ApiErrorId.ERR_OVER_PULL_LIMIT, 422)

    untouched = fixtures.read_furnace(api, ctx.furnace_id)
    assert untouched["reserved_pull_tons"] == 0.00

    accepted = validate_success(
        api.create_production_job(
            fixtures.job_payload_for(
                api, ctx, code="PJ-V3-AT", planned_pull_tpd=345.00, **window
            ),
            fixtures.users.SCHEDULER,
        ),
        201,
    )
    assert accepted["reserved_melt_tons"] == 690.00
    assert fixtures.read_furnace(api, ctx.furnace_id)["reserved_pull_tons"] == 690.00


def test_04_a_restricted_furnace_tightens_the_ceiling_to_the_nameplate_itself(api):
    """At 14.29 percent remaining, 310.00 tpd is refused although 1.15 x 300.00 is 345.00.

    PRD: "Otherwise, if `refractory_remaining_pct` is 15.00 or lower, posture is
    `RESTRICTED`."

    PRD: "A job may never request more than 1.15 times the furnace's
    `design_pull_tpd`, which is the fifteen-percent over-pull the lining can
    tolerate at all; and while the furnace's posture is `RESTRICTED`, the job may
    not exceed `design_pull_tpd` at all, because a furnace with 15.00 percent or
    less of its refractory life left is no longer permitted to be pushed."

    PRD: "both move the job's `reserved_melt_tons` out of the furnace's
    `reserved_pull_tons` and into the campaign's `melt_tons_charged`"

    Design: Corner/validations/restricted_posture_blocks_pull_above_design_pull
    """
    ctx = _ten_day_plant(
        api,
        "V4",
        furnace={"code": "FUR-V4", "design_pull_tpd": 300.00,
                 "refractory_life_total_units": 700.00},
        design={"code": "BD-V4"},
    )
    first = fixtures.schedule_job(
        api, ctx, code="PJ-V4A", window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
        planned_pull_tpd=300.00,
    )
    fixtures.start_job(api, first["id"])
    fixtures.close_job(api, first["id"], "COMPLETED", produced_units=3000000)

    worn = fixtures.read_furnace(api, ctx.furnace_id)
    assert worn["refractory_remaining_pct"] == 14.29
    assert worn["posture"] == FurnacePosture.RESTRICTED
    assert worn["reserved_pull_tons"] == 0.00

    window = {"window_start_at": SECOND_JOB_START, "window_end_at": SECOND_JOB_END}
    refused = api.create_production_job(
        fixtures.job_payload_for(
            api, ctx, code="PJ-V4B-OVER", planned_pull_tpd=310.00, **window
        ),
        fixtures.users.SCHEDULER,
    )
    validate_error(refused, ApiErrorId.ERR_OVER_PULL_LIMIT, 422)

    accepted = validate_success(
        api.create_production_job(
            fixtures.job_payload_for(
                api, ctx, code="PJ-V4B-AT", planned_pull_tpd=300.00, **window
            ),
            fixtures.users.SCHEDULER,
        ),
        201,
    )
    assert accepted["reserved_melt_tons"] == 600.00
    assert fixtures.read_campaign(api, ctx.campaign_id)["melt_tons_charged"] == 600.00


def test_05_equal_campaign_window_endpoints_are_refused_one_second_short(api):
    """A campaign whose window ends exactly when it starts is a 422, not a field violation.

    PRD: "The window must end strictly after it starts, else
    `ERR_WINDOW_ORDER_INVALID`."

    PRD: "Creating a campaign is also a mutation of the furnace: `campaign_count`
    increases by 1 and the furnace's `version` increases by 1."

    Design: Corner/validations/campaign_window_order_invalid_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-V5")

    refused = api.create_campaign(
        factories.campaign_payload(
            furnace["id"],
            code="CMP-V5",
            target_pull_tpd=300.00,
            window_start_at=CAMPAIGN_END,
            window_end_at=CAMPAIGN_END,
        ),
        fixtures.users.PLANT_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_WINDOW_ORDER_INVALID, 422)

    untouched = fixtures.read_furnace(api, furnace["id"])
    assert untouched["campaign_count"] == 0
    assert untouched["version"] == 1

    accepted = validate_success(
        api.create_campaign(
            factories.campaign_payload(
                furnace["id"],
                code="CMP-V5-OK",
                target_pull_tpd=300.00,
                window_start_at=CAMPAIGN_END,
                window_end_at="2026-08-11T00:00:01Z",
            ),
            fixtures.users.PLANT_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == CampaignStatus.PLANNED

    mutated = fixtures.read_furnace(api, furnace["id"])
    assert mutated["campaign_count"] == 1
    assert mutated["version"] == 2


def test_06_job_containment_is_inclusive_of_the_campaign_endpoints(api):
    """A job overrunning the campaign end is refused; one ending exactly on it is accepted.

    PRD: "it must sit entirely inside the campaign window, starting at or after
    the campaign's `window_start_at` and ending at or before the campaign's
    `window_end_at`, else `ERR_JOB_WINDOW_OUTSIDE_CAMPAIGN`"

    PRD: "A candidate job's own demand is its `planned_pull_tpd` multiplied by its
    window length in days, rounded half up to 2 decimals, and that figure is
    stored as the job's `reserved_melt_tons`."

    Design: Corner/validations/job_window_outside_campaign_window_rejected
    """
    ctx = _ten_day_plant(
        api, "V6", design={"code": "BD-V6"}, approve_recipe=False, design_state="DRAFT"
    )

    refused = api.create_production_job(
        fixtures.job_payload_for(
            api,
            ctx,
            code="PJ-V6-OUT",
            window_start_at="2026-08-10T00:00:00Z",
            window_end_at="2026-08-12T00:00:00Z",
            planned_pull_tpd=300.00,
        ),
        fixtures.users.SCHEDULER,
    )
    validate_error(refused, ApiErrorId.ERR_JOB_WINDOW_OUTSIDE_CAMPAIGN, 422)

    assert fixtures.read_furnace(api, ctx.furnace_id)["reserved_pull_tons"] == 0.00

    accepted = validate_success(
        api.create_production_job(
            fixtures.job_payload_for(
                api,
                ctx,
                code="PJ-V6-IN",
                window_start_at="2026-08-09T00:00:00Z",
                window_end_at=CAMPAIGN_END,
                planned_pull_tpd=300.00,
            ),
            fixtures.users.SCHEDULER,
        ),
        201,
    )
    assert accepted["reserved_melt_tons"] == 600.00


def test_07_the_reject_ceiling_is_cumulative_across_readings(api):
    """After a 2,000,000-unit reading, 1,000,001 more is refused and 1,000,000 empties the lot.

    PRD: "Cumulative rejects may not exceed the lot's `packed_units`: a reading
    that would push the running total of `rejected_units` past what was packed is
    refused with `ERR_REJECTS_EXCEED_PACKED`."

    PRD: "Each accepted reading recomputes the lot's `reject_units` as the sum of
    `rejected_units` over all its readings regardless of class, recomputes
    `net_packed_units` as `packed_units` less `reject_units`, recomputes both
    parts-per-million figures, and increments the lot's `version` by 1."

    PRD: "`major_ppm` is one million times the summed `rejected_units` of readings
    whose class is `MAJOR`, divided by the lot's gross `packed_units`, rounded
    half up to 1 decimal; `minor_ppm` is the same computation over readings whose
    class is `MINOR`."

    Design: Corner/validations/cumulative_rejects_exceeding_packed_units_rejected
    """
    ctx = _ten_day_plant(
        api, "V7", design={"code": "BD-V7", "nominal_weight_g": 190.00}
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api, ctx, produced_units=3000000, code="PJ-V7",
        window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
    )
    fixtures.record_reading(
        api, lot["id"], defect_class=DefectClass.MINOR, defect_code="BLISTER",
        rejected_units=2000000,
    )

    refused = api.record_inspection_result(
        lot["id"],
        factories.inspection_result_payload(
            defect_class=DefectClass.MAJOR, defect_code="STONE", rejected_units=1000001
        ),
        fixtures.users.QE_INSPECTOR,
    )
    validate_error(refused, ApiErrorId.ERR_REJECTS_EXCEED_PACKED, 422)

    partial = fixtures.read_lot(api, lot["id"])
    assert partial["reject_units"] == 2000000
    assert partial["net_packed_units"] == 1000000
    assert partial["version"] == 2

    validate_success(
        api.record_inspection_result(
            lot["id"],
            factories.inspection_result_payload(
                defect_class=DefectClass.MAJOR, defect_code="STONE", rejected_units=1000000
            ),
            fixtures.users.QE_INSPECTOR,
        ),
        201,
    )

    emptied = fixtures.read_lot(api, lot["id"])
    assert emptied["net_packed_units"] == 0
    assert emptied["major_ppm"] == 333333.3
    assert emptied["minor_ppm"] == 666666.7

    disposed = validate_success(
        api.release_pack_lot(lot["id"], fixtures.users.QE_RELEASER)
    )
    assert disposed["quality_status"] == LotQualityStatus.QUARANTINED
    assert disposed["final_yield_pct"] == 0.00


def test_08_the_complaint_ceiling_is_the_net_rather_than_the_gross_units(api):
    """2,999,001 affected units is refused on a lot whose net is 2,999,000.

    PRD: "And `affected_units` may not exceed the lot's `net_packed_units`, else
    `ERR_AFFECTED_UNITS_EXCEED_LOT`."

    PRD: "The server computes `breakage_ppm` immediately as one million times
    `affected_units` divided by the lot's `net_packed_units`, rounded half up to
    1 decimal — the customer's breakage rate expressed against the good glass
    actually delivered."

    PRD: "A filed complaint begins in `status` `OPEN` with `attribution`
    `UNDETERMINED`, `credit_usd` 0, `affected_pallets` 0 and
    `investigated_by_user_id` null."

    Design: Corner/validations/complaint_affected_units_exceeding_lot_rejected
    """
    ctx = _ten_day_plant(
        api, "V8", customer={"account_code": "ACC-V8"},
        design={"code": "BD-V8", "nominal_weight_g": 190.00},
    )
    lot = fixtures.shipped_lot(
        api,
        ctx,
        produced_units=3000000,
        readings=[{"defect_class": DefectClass.MINOR, "rejected_units": 1000}],
        job_overrides={
            "code": "PJ-V8",
            "window_start_at": CAMPAIGN_START,
            "window_end_at": JOB_END,
        },
    )
    assert lot["packed_units"] == 3000000
    assert lot["net_packed_units"] == 2999000

    refused = api.create_complaint(
        factories.complaint_payload(
            ctx.customer_id, lot["id"], code="CP-V8-OVER", affected_units=2999001
        ),
        ctx.rep_headers,
    )
    validate_error(refused, ApiErrorId.ERR_AFFECTED_UNITS_EXCEED_LOT, 422)

    accepted = validate_success(
        api.create_complaint(
            factories.complaint_payload(
                ctx.customer_id, lot["id"], code="CP-V8-AT", affected_units=2999000
            ),
            ctx.rep_headers,
        ),
        201,
    )
    assert accepted["status"] == ComplaintStatus.OPEN
    assert accepted["breakage_ppm"] == 1000000.0
    assert accepted["affected_pallets"] == 0
    assert accepted["credit_usd"] == 0.00


def test_09_code_uniqueness_is_enforced_per_collection(api):
    """A duplicate furnace code is a 409 while the same string is free on machines.

    PRD: "Human-readable identifiers are unique within their own collection: a
    furnace `code`, a campaign `code`, a recipe `code`, a machine `code`, a design
    `code`, a mold-set `code`, a job `code`, a program `code`, a complaint `code`,
    a customer `account_code`, and a pack lot's `lot_code` may each be used only
    once."

    PRD: "A collision is `ERR_CODE_NOT_UNIQUE` (HTTP 409). Codes are 1 to 32
    characters, except `lot_code`, which is 1 to 40 characters, and a customer
    `name`, which is 1 to 120 characters and is not required to be unique."

    Design: Corner/validations/duplicate_code_on_create_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-V9", design_pull_tpd=300.00)
    fixtures.create_customer(api, name="Sable Bottling", account_code="CUST-V9")

    refused = api.create_furnace(
        factories.furnace_payload(code="FUR-V9", design_pull_tpd=250.00),
        fixtures.users.PLANT_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_CODE_NOT_UNIQUE, 409)

    rows, meta = validate_paginated(api.list_furnaces(fixtures.users.PLANT_MANAGER))
    assert meta["total_count"] == 1
    assert rows[0]["design_pull_tpd"] == 300.00

    duplicate_account = api.create_customer(
        factories.customer_payload(name="Sable Bottling North", account_code="CUST-V9"),
        fixtures.users.PLANT_MANAGER,
    )
    validate_error(duplicate_account, ApiErrorId.ERR_CODE_NOT_UNIQUE, 409)

    machine = validate_success(
        api.create_forming_machine(
            factories.forming_machine_payload(furnace["id"], code="FUR-V9"),
            fixtures.users.PLANT_MANAGER,
        ),
        201,
    )
    assert machine["code"] == "FUR-V9"


def test_10_a_renegotiated_pallet_standard_strands_the_packed_lot(api):
    """Switching the customer to GMA blocks the ship until the standard is switched back.

    PRD: "Lots already packed keep the pattern that was snapshotted onto them at
    pack time, which means a lot packed to the old standard can never be shipped
    again: at shipment the lot's own `palletization_standard` must still equal the
    customer's current one, and a lot left stranded by a renegotiation is refused
    with `ERR_PALLET_STANDARD_MISMATCH`."

    PRD: "A shipped lot has `shipped_at` set to the logical clock's current value
    and its `version` increased by 1."

    PRD: "Most resources also carry an `updated_at` timestamp in the same format,
    refreshed on every mutation, and a `version` integer that starts at 1 when the
    resource is created and increases by exactly 1 on every mutation the server
    applies — including mutations applied as a cascade from another entity's
    operation, not only those requested directly."

    Design: Corner/validations/pallet_standard_change_blocks_ship_until_reverted
    """
    ctx = _ten_day_plant(
        api,
        "V10",
        customer={"account_code": "ACC-V10", "palletization_standard": PalletizationStandard.EURO},
        design={"code": "BD-V10", "nominal_weight_g": 190.00},
    )
    lot = fixtures.released_lot(
        api,
        ctx,
        produced_units=3000000,
        readings=[{"defect_class": DefectClass.MINOR, "rejected_units": 1000}],
        job_overrides={
            "code": "PJ-V10",
            "window_start_at": CAMPAIGN_START,
            "window_end_at": JOB_END,
        },
    )
    fixtures.set_clock(api, lot["aged_until_at"])
    palletized = fixtures.palletize_lot(api, lot["id"])
    assert palletized["pallet_count"] == 1667

    validate_success(
        api.patch_customer_palletization_standard(
            ctx.customer_id,
            factories.palletization_standard_payload(PalletizationStandard.GMA),
            fixtures.users.PLANT_MANAGER,
        )
    )

    stranded = api.ship_pack_lot(lot["id"], fixtures.users.WAREHOUSE)
    validate_error(stranded, ApiErrorId.ERR_PALLET_STANDARD_MISMATCH, 409)

    held = fixtures.read_lot(api, lot["id"])
    assert held["logistics_status"] == LotLogisticsStatus.PALLETIZED
    assert held["shipped_at"] is None
    assert held["palletization_standard"] == PalletizationStandard.EURO
    assert held["pallet_count"] == 1667

    reverted = validate_success(
        api.patch_customer_palletization_standard(
            ctx.customer_id,
            factories.palletization_standard_payload(PalletizationStandard.EURO),
            fixtures.users.PLANT_MANAGER,
        )
    )
    assert reverted["version"] == 3

    shipped = validate_success(api.ship_pack_lot(lot["id"], fixtures.users.WAREHOUSE))
    assert shipped["logistics_status"] == LotLogisticsStatus.SHIPPED
    assert shipped["shipped_at"] == "2026-08-04T00:00:00.000Z"


def test_11_a_rep_within_its_own_scope_still_cannot_claim_another_customers_lot(api):
    """Filing for the rep's own customer on a foreign lot is a 422, not a scope violation.

    PRD: "The rep's `X-User-ID` must equal the `customer_id` in the body, else
    `ERR_CUSTOMER_SCOPE_VIOLATION`."

    PRD: "The lot must belong to the complaining customer, and its bottle design
    must belong to that customer too, else `ERR_LOT_CUSTOMER_MISMATCH`."

    PRD: "The server computes `breakage_ppm` immediately as one million times
    `affected_units` divided by the lot's `net_packed_units`, rounded half up to
    1 decimal — the customer's breakage rate expressed against the good glass
    actually delivered."

    Design: Corner/validations/complaint_lot_customer_mismatch_rejected
    """
    ctx = _ten_day_plant(
        api,
        "V11",
        customer={"name": "Alder Filling", "account_code": "CUST-V11-A"},
        design={"code": "BD-V11", "nominal_weight_g": 190.00},
    )
    outsider = fixtures.create_customer(
        api, name="Birchwood Filling", account_code="CUST-V11-B"
    )
    lot = fixtures.shipped_lot(
        api,
        ctx,
        produced_units=3000000,
        readings=[{"defect_class": DefectClass.MINOR, "rejected_units": 1000}],
        job_overrides={
            "code": "PJ-V11",
            "window_start_at": CAMPAIGN_START,
            "window_end_at": JOB_END,
        },
    )
    assert lot["customer_id"] == ctx.customer_id

    refused = api.create_complaint(
        factories.complaint_payload(
            outsider["id"], lot["id"], code="CP-V11-B", affected_units=5000
        ),
        fixtures.users.customer_rep(outsider["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_LOT_CUSTOMER_MISMATCH, 422)

    _rows, meta = validate_paginated(
        api.list_complaints(fixtures.users.QE_INVESTIGATOR)
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_complaint(
            factories.complaint_payload(
                ctx.customer_id, lot["id"], code="CP-V11-A", affected_units=5000
            ),
            ctx.rep_headers,
        ),
        201,
    )
    assert accepted["status"] == ComplaintStatus.OPEN
    assert accepted["breakage_ppm"] == 1667.2


def test_12_the_identity_headers_are_checked_before_the_body(api):
    """An empty user id is a 401 even on a body that would otherwise be a 400.

    PRD: "Checks fire in a fixed precedence, and the first failing check determines
    the response."

    PRD: "1. `X-User-Role` present and one of the seven declared roles, else
    `ERR_UNAUTHENTICATED`.
    2. `X-User-ID` present and non-empty, else `ERR_MISSING_USER_ID`."

    PRD: "A furnace is registered with a nameplate `design_pull_tpd` (tons per
    day, greater than 0 and no more than 600, 2 decimals) and a
    `refractory_life_total_units` budget (greater than 0, 2 decimals)
    representing the wear units its lining can absorb before the current campaign
    must end."

    PRD: "Field-level validation inspects each submitted field in isolation:
    required fields present, types correct, enum values among the declared
    members, numbers inside their declared ranges and decimal precision,
    timestamps well formed."

    Design: Corner/validations/missing_user_id_header_rejected
    """
    out_of_range = factories.furnace_payload(code="FUR-V12", design_pull_tpd=700.00)

    anonymous = api.create_furnace(
        out_of_range, fixtures.users.headers_with_empty_user_id(Role.PLANT_MANAGER)
    )
    validate_error(anonymous, ApiErrorId.ERR_MISSING_USER_ID, 401)

    _rows, meta = validate_paginated(api.list_furnaces(fixtures.users.PLANT_MANAGER))
    assert meta["total_count"] == 0

    named = api.create_furnace(out_of_range, fixtures.users.PLANT_MANAGER)
    validate_error(named, ApiErrorId.ERR_VALIDATION, 400)

    roleless = api.create_furnace(
        out_of_range, fixtures.users.headers_without_role(fixtures.users.PLANT_MANAGER_ID)
    )
    validate_error(roleless, ApiErrorId.ERR_UNAUTHENTICATED, 401)
