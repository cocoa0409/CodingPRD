"""Each declared error code raised on its own path, with the recovery that clears it."""

from test_helpers import (
    ApiErrorId,
    BottleDesignStatus,
    CampaignStatus,
    ColorChangeStatus,
    ComplaintAttribution,
    ComplaintStatus,
    CustomerDecision,
    DefectClass,
    FormingMachineStatus,
    FurnacePosture,
    GlassColor,
    LotQualityStatus,
    MoldFamily,
    MoldSetStatus,
    NON_EXISTENT_UUID,
    ProductionJobStatus,
    ProgramStatus,
    QualityStanding,
    SavingsTier,
    Settlement,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CAMPAIGN_START = "2026-08-01T00:00:00Z"
CAMPAIGN_END = "2026-08-11T00:00:00Z"
JOB_END = "2026-08-03T00:00:00Z"
REBUILD_START = "2026-08-12T00:00:00Z"
REBUILD_END = "2026-08-28T00:00:00Z"


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
    kwargs.setdefault("recipe", {"code": f"BR-{suffix}"})
    kwargs.setdefault(
        "machine",
        {"code": f"IS-{suffix}", "max_cavities": 40, "primary_mold_family": MoldFamily.NNPB},
    )
    kwargs.setdefault("design", {"code": f"BD-{suffix}"})
    kwargs.setdefault("mold_set", {"code": f"MS-{suffix}"})
    return fixtures.bring_up_plant(api, **kwargs)


def test_01_a_capped_target_index_blocks_the_pilot_but_not_the_reject(api):
    """A risk delta of 88.00 refuses PILOT on healthy economics, and REJECT still closes it.

    PRD: "A `PILOT` decision moves the program `RISK_ASSESSED → PILOT`, and it is
    capped: a program whose `breakage_risk_delta` exceeds 30.00 cannot be piloted
    and is refused with `ERR_RISK_DELTA_ABOVE_CAP`, and a program whose customer
    is in `quality_standing` `CRITICAL` cannot be piloted either — a customer
    already breaking bottles is not given a thinner one."

    PRD: "The delta is that re-evaluated index less the baseline design's stored
    `breakage_risk_index`, rounded half up to 2 decimals."

    PRD: "Seventh, `risk_reserve_usd` is `gross_savings_usd` multiplied by that
    reserve rate, rounded half up to 2 decimals, and `net_savings_usd` is
    `gross_savings_usd` less `risk_reserve_usd`, rounded half up to 2 decimals."

    PRD: "A `REJECT` decision moves the program `RISK_ASSESSED → REJECTED`, which
    is terminal; the reject branch carries no risk-delta cap and no standing
    requirement, because declining a proposal is always permitted."

    Design: Corner/errors/risk_delta_above_cap_blocks_the_pilot_decision
    """
    customer = fixtures.create_customer(api, name="Cobalt Filling", account_code="CUST-X1")
    design = fixtures.create_approved_design(
        api,
        customer["id"],
        code="BD-X1",
        capacity_ml=400.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=250.00,
    )
    assert design["breakage_risk_index"] == 12.00

    program = fixtures.assessed_program(
        api,
        design["id"],
        code="LW-X1",
        target_weight_g=100.00,
        annual_volume_units=1000000,
        resin_free_glass_price_per_kg=0.5000,
    )
    assert program["breakage_risk_delta"] == 88.00
    assert program["gross_savings_usd"] == 45000.00
    assert program["savings_tier"] == SavingsTier.TIER_A
    assert program["risk_reserve_usd"] == 5814.00
    assert program["net_savings_usd"] == 39186.00
    assert program["customer_rebate_usd"] == 7837.20

    refused = api.program_customer_decision(
        program["id"],
        factories.customer_decision_payload(CustomerDecision.PILOT),
        fixtures.users.customer_rep(customer["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_RISK_DELTA_ABOVE_CAP, 422)

    held = fixtures.read_program(api, program["id"])
    assert held["status"] == ProgramStatus.RISK_ASSESSED
    assert held["version"] == 2
    assert held["pilot_decided_by_user_id"] is None

    declined = validate_success(
        api.program_customer_decision(
            program["id"],
            factories.customer_decision_payload(CustomerDecision.REJECT),
            fixtures.users.customer_rep(customer["id"]),
        )
    )
    assert declined["status"] == ProgramStatus.REJECTED
    assert declined["version"] == 3


def test_02_the_target_weight_must_be_strictly_lighter_than_the_baseline(api):
    """200.00 g is refused against a 190.00 g baseline while 189.00 g is accepted.

    PRD: "The target weight must be strictly lighter than the baseline design's
    `nominal_weight_g`; a target that is equal or heavier is not a lightweighting
    proposal at all and is refused with `ERR_TARGET_WEIGHT_NOT_LIGHTER`."

    PRD: "Opening a lightweighting program requires `expected_design_version`
    carrying the `version` of the baseline bottle design as the client last
    observed it."

    PRD: "Most resources also carry an `updated_at` timestamp in the same format,
    refreshed on every mutation, and a `version` integer that starts at 1 when the
    resource is created and increases by exactly 1 on every mutation the server
    applies — including mutations applied as a cascade from another entity's
    operation, not only those requested directly."

    PRD: "A new program begins in `DRAFT` with `weight_saved_g`,
    `gross_savings_usd`, `breakage_risk_delta`, `risk_reserve_usd`,
    `net_savings_usd` and `customer_rebate_usd` all 0, `savings_tier` `TIER_A`,
    and `pilot_decided_by_user_id` null."

    Design: Corner/errors/program_target_weight_not_lighter_rejected
    """
    customer = fixtures.create_customer(api, name="Dunmore Filling", account_code="CUST-X2")
    design = fixtures.create_approved_design(
        api,
        customer["id"],
        code="BD-X2",
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=500.00,
    )
    assert design["version"] == 4

    refused = api.create_lightweighting_program(
        factories.lightweighting_program_payload(
            design["id"], 4, code="LW-X2-HEAVY", target_weight_g=200.00
        ),
        fixtures.users.QE_APPROVER,
    )
    validate_error(refused, ApiErrorId.ERR_TARGET_WEIGHT_NOT_LIGHTER, 422)

    assert fixtures.read_design(api, design["id"])["version"] == 4

    _rows, meta = validate_paginated(
        api.list_lightweighting_programs(
            fixtures.users.QE_APPROVER, baseline_design_id=design["id"]
        )
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_lightweighting_program(
            factories.lightweighting_program_payload(
                design["id"], 4, code="LW-X2-LIGHT", target_weight_g=189.00
            ),
            fixtures.users.QE_APPROVER,
        ),
        201,
    )
    assert accepted["status"] == ProgramStatus.DRAFT
    assert accepted["weight_saved_g"] == 0.00
    assert fixtures.read_design(api, design["id"])["version"] == 5


def test_03_a_campaign_may_not_plan_above_the_furnace_nameplate(api):
    """350.00 tpd is refused on a 300.00 tpd furnace; 300.00 tpd plans cleanly.

    PRD: "The campaign's target pull may not exceed the furnace's nameplate
    `design_pull_tpd`; a plan that asks the furnace for more than it was built
    for is refused with `ERR_TARGET_PULL_EXCEEDS_DESIGN`."

    PRD: "Creating a campaign is also a mutation of the furnace: `campaign_count`
    increases by 1 and the furnace's `version` increases by 1."

    Design: Corner/errors/campaign_target_pull_above_design_pull_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-X3", design_pull_tpd=300.00)

    refused = api.create_campaign(
        factories.campaign_payload(
            furnace["id"],
            code="CMP-X3",
            target_pull_tpd=350.00,
            window_start_at=CAMPAIGN_START,
            window_end_at=CAMPAIGN_END,
        ),
        fixtures.users.PLANT_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_TARGET_PULL_EXCEEDS_DESIGN, 422)

    untouched = fixtures.read_furnace(api, furnace["id"])
    assert untouched["campaign_count"] == 0
    assert untouched["version"] == 1

    accepted = validate_success(
        api.create_campaign(
            factories.campaign_payload(
                furnace["id"],
                code="CMP-X3-AT",
                target_pull_tpd=300.00,
                window_start_at=CAMPAIGN_START,
                window_end_at=CAMPAIGN_END,
            ),
            fixtures.users.PLANT_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == CampaignStatus.PLANNED

    mutated = fixtures.read_furnace(api, furnace["id"])
    assert mutated["campaign_count"] == 1
    assert mutated["version"] == 2


def test_04_the_mold_set_must_hang_off_the_jobs_own_design(api):
    """A sibling design's tooling is refused although both sets are AVAILABLE NNPB sets.

    PRD: "When a `mold_set_id` is supplied, the set must belong to the job's
    bottle design, else `ERR_MOLD_SET_DESIGN_MISMATCH`."

    PRD: "It begins with `status` `AVAILABLE`, `mount_count` 0, and
    `forming_machine_id` null, since it is not mounted anywhere."

    PRD: "A candidate job's own demand is its `planned_pull_tpd` multiplied by its
    window length in days, rounded half up to 2 decimals, and that figure is
    stored as the job's `reserved_melt_tons`."

    Design: Corner/errors/mold_set_from_another_design_rejected_on_job_create
    """
    ctx = _ten_day_plant(
        api, "X4", design={"code": "BD-X4-A"}, mold_set={"code": "MS-X4-A"},
        design_state="DRAFT",
    )
    other_design = fixtures.create_design(
        api, ctx.customer_id, code="BD-X4-B", color=GlassColor.FLINT
    )
    other_set = fixtures.create_mold_set(api, other_design["id"], code="MS-X4-B")

    window = {"window_start_at": CAMPAIGN_START, "window_end_at": JOB_END}
    refused = api.create_production_job(
        fixtures.job_payload_for(
            api, ctx, code="PJ-X4", planned_pull_tpd=300.00,
            mold_set_id=other_set["id"], **window
        ),
        fixtures.users.SCHEDULER,
    )
    validate_error(refused, ApiErrorId.ERR_MOLD_SET_DESIGN_MISMATCH, 422)

    assert fixtures.read_furnace(api, ctx.furnace_id)["reserved_pull_tons"] == 0.00

    spared = fixtures.read_mold_set(api, other_set["id"])
    assert spared["status"] == MoldSetStatus.AVAILABLE
    assert spared["forming_machine_id"] is None

    accepted = validate_success(
        api.create_production_job(
            fixtures.job_payload_for(
                api, ctx, code="PJ-X4-OK", planned_pull_tpd=300.00,
                mold_set_id=ctx.mold_set_id, **window
            ),
            fixtures.users.SCHEDULER,
        ),
        201,
    )
    assert accepted["reserved_melt_tons"] == 600.00


def test_05_live_production_holds_the_campaign_open(api):
    """Wind-down is refused while the job runs and succeeds the moment it closes.

    PRD: "Winding a campaign down moves it `ACTIVE → WIND_DOWN` and requires that
    no production job on the campaign is in `RUNNING` — a wind-down attempted
    over live production is refused with `ERR_RUNNING_JOB_PRESENT`."

    PRD: "On success the server records `projected_refractory_units_nominal` for
    the campaign window using the nominal refractory projection described below,
    re-derives the furnace's `posture`, and increments the campaign's `version` by
    1."

    Design: Corner/errors/running_job_blocks_campaign_wind_down
    """
    ctx = _ten_day_plant(api, "X5")
    job = fixtures.schedule_job(
        api, ctx, code="PJ-X5", window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
        planned_pull_tpd=300.00,
    )
    fixtures.start_job(api, job["id"])

    refused = api.wind_down_campaign(ctx.campaign_id, fixtures.users.PLANT_MANAGER)
    validate_error(refused, ApiErrorId.ERR_RUNNING_JOB_PRESENT, 409)

    held = fixtures.read_campaign(api, ctx.campaign_id)
    assert held["status"] == CampaignStatus.ACTIVE
    assert held["version"] == 2

    assert fixtures.read_job(api, job["id"])["status"] == ProductionJobStatus.RUNNING
    assert fixtures.read_furnace(api, ctx.furnace_id)["reserved_pull_tons"] == 600.00

    fixtures.close_job(api, job["id"], "COMPLETED", produced_units=3000000)

    wound_down = validate_success(
        api.wind_down_campaign(ctx.campaign_id, fixtures.users.PLANT_MANAGER)
    )
    assert wound_down["status"] == CampaignStatus.WIND_DOWN
    assert wound_down["version"] == 3


def test_06_a_job_whose_window_already_opened_survives_wind_down_and_blocks_the_rebuild(api):
    """The cascade spares a job that opened before the clock, and it refuses the rebuild.

    PRD: "Wind-down cascades: every job on the campaign still in `SCHEDULED`
    whose `window_start_at` is on or after the logical clock at the wind-down
    instant is moved to `CANCELLED`, and each cancelled job's
    `reserved_melt_tons` is subtracted from the furnace's `reserved_pull_tons`."

    PRD: "A `SCHEDULED` job whose window has *already opened* is deliberately
    left untouched, for the plant to close or cancel by hand; that surviving job
    is exactly why a rebuild cannot yet be scheduled, and it will refuse the
    rebuild with `ERR_OPEN_JOBS_PRESENT` until it is dealt with."

    PRD: "Scheduling the rebuild sets both rebuild instants on the campaign,
    forces the furnace's `posture` to `COLD`, and cascades `SCHEDULED → ABORTED`
    onto every colour change on that furnace whose `window_start_at` falls on or
    after `rebuild_window_start_at` — a transition planned into a cold furnace is
    meaningless."

    PRD: "The job's `reserved_melt_tons` is subtracted from the furnace's
    `reserved_pull_tons`, the furnace's `version` increases by 1, and the job's
    `version` increases by 1."

    Design: Corner/errors/scheduled_job_inside_its_window_blocks_schedule_rebuild
    """
    ctx = _ten_day_plant(api, "X6", design_state="DRAFT")
    job = fixtures.schedule_job(
        api, ctx, code="PJ-X6", window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
        planned_pull_tpd=300.00,
    )
    assert job["reserved_melt_tons"] == 600.00

    fixtures.set_clock(api, "2026-08-02T00:00:00Z")
    validate_success(api.wind_down_campaign(ctx.campaign_id, fixtures.users.PLANT_MANAGER))

    rebuild = factories.rebuild_window_payload(
        rebuild_window_start_at=REBUILD_START, rebuild_window_end_at=REBUILD_END
    )
    refused = api.schedule_campaign_rebuild(
        ctx.campaign_id, rebuild, fixtures.users.PLANT_MANAGER
    )
    validate_error(refused, ApiErrorId.ERR_OPEN_JOBS_PRESENT, 409)

    assert fixtures.read_job(api, job["id"])["status"] == ProductionJobStatus.SCHEDULED

    held = fixtures.read_campaign(api, ctx.campaign_id)
    assert held["status"] == CampaignStatus.WIND_DOWN
    assert held["rebuild_window_start_at"] is None

    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    assert furnace["reserved_pull_tons"] == 600.00
    assert furnace["posture"] == FurnacePosture.OPERATING

    cancelled = fixtures.cancel_job(api, job["id"])
    assert cancelled["status"] == ProductionJobStatus.CANCELLED
    assert fixtures.read_furnace(api, ctx.furnace_id)["reserved_pull_tons"] == 0.00

    scheduled = validate_success(
        api.schedule_campaign_rebuild(ctx.campaign_id, rebuild, fixtures.users.PLANT_MANAGER)
    )
    assert scheduled["status"] == CampaignStatus.REBUILD_SCHEDULED
    assert fixtures.read_furnace(api, ctx.furnace_id)["posture"] == FurnacePosture.COLD


def test_07_a_lot_awaiting_disposition_holds_the_campaign_open(api):
    """Closure is refused while the lot is PENDING_INSPECTION and resets the lining after.

    PRD: "It requires that every pack lot on the campaign has left
    `PENDING_INSPECTION` — that is, each is in `RELEASED`, `QUARANTINED` or
    `SCRAPPED` — and a campaign with a lot still awaiting disposition is refused
    with `ERR_OPEN_LOTS_PRESENT`."

    PRD: "On closure the server recomputes `unaccounted_loss_tons` from the
    campaign melt ledger, resets the furnace's `refractory_consumed_units` to 0
    and `refractory_remaining_pct` to 100.00 to reflect the new lining, sets the
    furnace's `posture` to `OPERATING`, and increments the campaign's `version` by
    1."

    PRD: "The provisional pack-to-melt yield is one hundred times that gross
    tonnage divided by the job's `reserved_melt_tons`, rounded half up to 2
    decimals."

    Design: Corner/errors/open_pack_lot_blocks_campaign_close
    """
    ctx = _ten_day_plant(api, "X7", design={"code": "BD-X7", "nominal_weight_g": 190.00})
    _job, lot = fixtures.completed_job_with_lot(
        api, ctx, produced_units=3000000, code="PJ-X7",
        window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
    )
    validate_success(api.wind_down_campaign(ctx.campaign_id, fixtures.users.PLANT_MANAGER))
    validate_success(
        api.schedule_campaign_rebuild(
            ctx.campaign_id,
            factories.rebuild_window_payload(
                rebuild_window_start_at=REBUILD_START, rebuild_window_end_at=REBUILD_END
            ),
            fixtures.users.PLANT_MANAGER,
        )
    )

    refused = api.close_campaign(ctx.campaign_id, fixtures.users.PLANT_MANAGER)
    validate_error(refused, ApiErrorId.ERR_OPEN_LOTS_PRESENT, 409)

    held = fixtures.read_campaign(api, ctx.campaign_id)
    assert held["status"] == CampaignStatus.REBUILD_SCHEDULED
    assert held["version"] == 4

    open_lot = fixtures.read_lot(api, lot["id"])
    assert open_lot["quality_status"] == LotQualityStatus.PENDING_INSPECTION
    assert open_lot["provisional_yield_pct"] == 95.00

    worn = fixtures.read_furnace(api, ctx.furnace_id)
    assert worn["refractory_consumed_units"] == 600.00
    assert worn["posture"] == FurnacePosture.COLD

    fixtures.record_reading(
        api, lot["id"], defect_class=DefectClass.MINOR, defect_code="BLISTER",
        rejected_units=1000,
    )
    fixtures.release_lot(api, lot["id"])

    closed = validate_success(api.close_campaign(ctx.campaign_id, fixtures.users.PLANT_MANAGER))
    assert closed["status"] == CampaignStatus.CLOSED
    assert fixtures.read_furnace(api, ctx.furnace_id)["refractory_consumed_units"] == 0.00


def test_08_settlement_is_gated_twice_by_the_same_state_code(api):
    """CREDIT is refused on an OPEN complaint and again on an UNDETERMINED investigation.

    PRD: "Both branches require the complaint to be in `INVESTIGATING`, both
    require the rep's `X-User-ID` to equal the complaint's `customer_id`, and both
    increment the complaint's `version` by 1."

    PRD: "A `CREDIT` settlement moves the complaint `INVESTIGATING →
    CREDIT_ISSUED` and carries two extra conditions: the `attribution` must be
    `PLANT` or `SHARED`, so a complaint still `UNDETERMINED` or attributed to
    `CUSTOMER` cannot be credited and is refused with
    `ERR_COMPLAINT_STATE_INVALID`; and the settling `X-User-ID` must differ from
    `investigated_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "A `REJECT` settlement moves the complaint `INVESTIGATING → REJECTED`
    with no attribution requirement, leaves the customer's `credit_issued_usd` and
    `quality_standing` untouched, and computes no credit."

    Design: Corner/errors/complaint_settle_before_investigation_rejected
    """
    ctx = _ten_day_plant(
        api, "X8", customer={"account_code": "CUST-X8"},
        design={"code": "BD-X8", "nominal_weight_g": 190.00},
    )
    lot = fixtures.shipped_lot(
        api,
        ctx,
        produced_units=3000000,
        readings=[{"defect_class": DefectClass.MINOR, "rejected_units": 1000}],
        job_overrides={
            "code": "PJ-X8",
            "window_start_at": CAMPAIGN_START,
            "window_end_at": JOB_END,
        },
    )
    complaint = fixtures.file_complaint(
        api, ctx.customer_id, lot["id"], code="CP-X8", affected_units=5000
    )

    too_early = api.settle_complaint(
        complaint["id"], factories.settle_payload(Settlement.CREDIT), ctx.rep_headers
    )
    validate_error(too_early, ApiErrorId.ERR_COMPLAINT_STATE_INVALID, 409)

    held = fixtures.read_complaint(api, complaint["id"])
    assert held["status"] == ComplaintStatus.OPEN
    assert held["attribution"] == ComplaintAttribution.UNDETERMINED
    assert held["credit_usd"] == 0.00
    assert held["version"] == 1

    customer = fixtures.read_customer(api, ctx.customer_id)
    assert customer["credit_issued_usd"] == 0.00
    assert customer["quality_standing"] == QualityStanding.GOOD

    fixtures.investigate(api, complaint["id"], ComplaintAttribution.UNDETERMINED)

    still_refused = api.settle_complaint(
        complaint["id"], factories.settle_payload(Settlement.CREDIT), ctx.rep_headers
    )
    validate_error(still_refused, ApiErrorId.ERR_COMPLAINT_STATE_INVALID, 409)

    rejected = validate_success(
        api.settle_complaint(
            complaint["id"], factories.settle_payload(Settlement.REJECT), ctx.rep_headers
        )
    )
    assert rejected["status"] == ComplaintStatus.REJECTED
    assert rejected["credit_usd"] == 0.00
    assert fixtures.read_customer(api, ctx.customer_id)["credit_issued_usd"] == 0.00


def test_09_adoption_is_reachable_only_from_the_customers_pilot(api):
    """Adopt is refused from DRAFT and from RISK_ASSESSED, and the economics never move.

    PRD: "Adoption is the `PlantManager`'s call and moves the program `PILOT →
    ADOPTED`."

    PRD: "14. Program state permits the requested transition, else
    `ERR_PROGRAM_STATE_INVALID` — on program assess-risk, customer decision,
    adoption and suspension."

    PRD: "Sixth, a reserve rate is derived: the tier's base rate — 0.05 for
    `TIER_A`, 0.09 for `TIER_B`, 0.14 for `TIER_C` — plus 0.0009 for each point of
    `breakage_risk_delta`, with the sum rounded half up to 5 decimals."

    PRD: "Eighth, `customer_rebate_usd` is `net_savings_usd` multiplied by the
    tier's rebate rate — 0.20 for `TIER_A`, 0.30 for `TIER_B`, 0.40 for `TIER_C` —
    rounded half up to 2 decimals."

    Design: Corner/errors/program_adopt_before_pilot_rejected
    """
    customer = fixtures.create_customer(api, name="Ellwood Filling", account_code="CUST-X9")
    design = fixtures.create_approved_design(
        api,
        customer["id"],
        code="BD-X9",
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=500.00,
    )
    assert design["breakage_risk_index"] == 24.00

    program = fixtures.create_program(
        api,
        design["id"],
        code="LW-X9",
        target_weight_g=185.00,
        annual_volume_units=1000000,
        resin_free_glass_price_per_kg=0.5000,
    )

    from_draft = api.adopt_program(program["id"], fixtures.users.PLANT_MANAGER)
    validate_error(from_draft, ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409)

    held = fixtures.read_program(api, program["id"])
    assert held["status"] == ProgramStatus.DRAFT
    assert held["version"] == 1
    assert held["gross_savings_usd"] == 0.00

    assessed = fixtures.assess_program(api, program["id"])
    assert assessed["status"] == ProgramStatus.RISK_ASSESSED
    assert assessed["gross_savings_usd"] == 2500.00
    assert assessed["savings_tier"] == SavingsTier.TIER_A
    assert assessed["breakage_risk_delta"] == 0.00
    assert assessed["risk_reserve_usd"] == 125.00
    assert assessed["net_savings_usd"] == 2375.00
    assert assessed["customer_rebate_usd"] == 475.00

    from_assessed = api.adopt_program(program["id"], fixtures.users.PLANT_MANAGER)
    validate_error(from_assessed, ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409)

    fixtures.decide_program(api, program["id"], customer["id"], CustomerDecision.PILOT)

    adopted = validate_success(api.adopt_program(program["id"], fixtures.users.PLANT_MANAGER))
    assert adopted["status"] == ProgramStatus.ADOPTED
    assert adopted["version"] == 4


def test_10_closing_a_job_that_never_started_fires_none_of_the_close_effects(api):
    """A close on a SCHEDULED job is refused and mints no lot, wear or ledger charge.

    PRD: "Both branches require the job to be in `RUNNING`, else
    `ERR_JOB_STATE_INVALID`; both compute `refractory_wear_units` from the
    stress-adjusted refractory variant and charge it to the furnace, adding it to
    `refractory_consumed_units`, recomputing `refractory_remaining_pct` and
    re-deriving `posture`; both move the job's `reserved_melt_tons` out of the
    furnace's `reserved_pull_tons` and into the campaign's `melt_tons_charged`;
    both move the forming machine `RUNNING → IDLE` with its `version` increased by
    1; and both increment the job's `version` by 1."

    PRD: "A successfully scheduled job is created in `status` `SCHEDULED` with
    `changeover_minutes` 0, `refractory_wear_units` 0, `produced_units` 0 and
    `outcome_note` null."

    Design: Corner/errors/closing_a_scheduled_job_rejected
    """
    ctx = _ten_day_plant(api, "X10", design_state="DRAFT")
    job = fixtures.schedule_job(
        api, ctx, code="PJ-X10", window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
        planned_pull_tpd=300.00,
    )

    refused = api.close_production_job(
        job["id"],
        factories.close_job_payload("COMPLETED", produced_units=3000000),
        fixtures.users.SCHEDULER,
    )
    validate_error(refused, ApiErrorId.ERR_JOB_STATE_INVALID, 409)

    held = fixtures.read_job(api, job["id"])
    assert held["status"] == ProductionJobStatus.SCHEDULED
    assert held["version"] == 1
    assert held["produced_units"] == 0
    assert held["refractory_wear_units"] == 0.00

    furnace = fixtures.read_furnace(api, ctx.furnace_id)
    assert furnace["refractory_consumed_units"] == 0.00
    assert furnace["reserved_pull_tons"] == 600.00

    assert fixtures.read_campaign(api, ctx.campaign_id)["melt_tons_charged"] == 0.00

    _rows, meta = validate_paginated(
        api.list_pack_lots(fixtures.users.QE_RELEASER, production_job_id=job["id"])
    )
    assert meta["total_count"] == 0


def test_11_risk_signoff_needs_a_submission_to_sign(api):
    """Sign-off on a DRAFT design is refused, and the derived promises are still zero.

    PRD: "Every one of these transitions increments the design's `version` by 1,
    and a transition attempted from the wrong state is refused with
    `ERR_DESIGN_STATE_INVALID`."

    PRD: "A drafted design begins in `status` `DRAFT` with `revision_count` 0,
    `breakage_risk_index` 0, `lead_time_days` 0, and both `risk_signed_by_user_id`
    and `approved_by_user_id` null."

    PRD: "Risk sign-off moves the design `SUBMITTED → RISK_SIGNED` and is
    permitted only when `breakage_risk_index` is 55.00 or lower; a design above
    that cap cannot be signed at all and is refused with
    `ERR_RISK_INDEX_ABOVE_CAP`, which in practice sends the engineer back to add
    glass or thicken the wall."

    Design: Corner/errors/risk_signoff_on_a_draft_design_rejected
    """
    customer = fixtures.create_customer(api, name="Fairhaven Filling", account_code="CUST-X11")
    design = fixtures.create_design(
        api,
        customer["id"],
        code="BD-X11",
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=500.00,
    )

    refused = api.risk_signoff_bottle_design(design["id"], fixtures.users.QE_RISK_SIGNER)
    validate_error(refused, ApiErrorId.ERR_DESIGN_STATE_INVALID, 409)

    held = fixtures.read_design(api, design["id"])
    assert held["status"] == BottleDesignStatus.DRAFT
    assert held["version"] == 1
    assert held["risk_signed_by_user_id"] is None
    assert held["breakage_risk_index"] == 0.00
    assert held["lead_time_days"] == 0

    fixtures.submit_design(api, design["id"])

    signed = validate_success(
        api.risk_signoff_bottle_design(design["id"], fixtures.users.QE_RISK_SIGNER)
    )
    assert signed["status"] == BottleDesignStatus.RISK_SIGNED
    assert signed["breakage_risk_index"] == 24.00
    assert signed["lead_time_days"] == 55


def test_12_recipe_approval_is_checked_at_start_and_not_at_schedule(api):
    """The job schedules against an unapproved recipe and only the start refuses.

    PRD: "The batch recipe's `approved` flag must be true and the bottle design
    must be in `APPROVED`; the design is checked first and reports
    `ERR_DESIGN_NOT_APPROVED`, the recipe second and reports
    `ERR_RECIPE_NOT_APPROVED`."

    PRD: "New recipes are created with `approved` false; approval by a
    `BatchHouseTech` sets `approved` to true and is the gate that lets production
    use the recipe at all."

    PRD: "The swap minutes plus the greater of those two penalties is rounded half
    up to a whole number of minutes and then capped at 240, so no single
    changeover is ever charged more than four hours."

    Design: Corner/errors/job_start_with_unapproved_recipe_rejected
    """
    ctx = _ten_day_plant(api, "X12", approve_recipe=False)
    job = fixtures.schedule_job(
        api, ctx, code="PJ-X12", window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
        planned_pull_tpd=300.00,
    )

    refused = api.start_production_job(job["id"], fixtures.users.SCHEDULER)
    validate_error(refused, ApiErrorId.ERR_RECIPE_NOT_APPROVED, 409)

    held = fixtures.read_job(api, job["id"])
    assert held["status"] == ProductionJobStatus.SCHEDULED
    assert held["changeover_minutes"] == 0

    assert fixtures.read_mold_set(api, ctx.mold_set_id)["status"] == MoldSetStatus.AVAILABLE

    machine = fixtures.read_machine(api, ctx.machine_id)
    assert machine["status"] == FormingMachineStatus.IDLE
    assert machine["mounted_cavities"] == 0

    assert validate_success(
        api.get_batch_recipe(ctx.recipe_id, fixtures.users.BATCH_TECH)
    )["approved"] is False

    fixtures.approve_batch_recipe(api, ctx.recipe_id)

    started = validate_success(api.start_production_job(job["id"], fixtures.users.SCHEDULER))
    assert started["status"] == ProductionJobStatus.RUNNING
    assert started["changeover_minutes"] == 60


def test_13_a_cold_furnace_refuses_the_next_activation_until_the_rebuild_closes(api):
    """Activation on a COLD furnace is refused although the lining reads 100.00 percent.

    PRD: "Activation moves the campaign `PLANNED → ACTIVE` and is the moment the
    plant commits. Activation requires the campaign to be in `PLANNED`, requires
    the furnace's posture to be anything other than `COLD`, and requires that no
    other campaign on the same furnace is currently in `ACTIVE` or `WIND_DOWN` — a
    furnace melts one campaign at a time, and a second concurrent campaign is
    refused with `ERR_FURNACE_CAMPAIGN_CONFLICT`."

    PRD: "18. Furnace posture permits the operation, else
    `ERR_FURNACE_POSTURE_BLOCKED` — on campaign activation and job start."

    PRD: "The **nominal** variant is simply the base wear units rounded half up to
    2 decimals, ignoring over-pull and cullet stress entirely; it is what a
    campaign records at activation, using `target_pull_tpd`, the campaign window,
    and the colour factor of the furnace's `current_color` at that moment."

    PRD: "A newly planned campaign has `status` `PLANNED`, all five melt-ledger
    figures — `melt_tons_charged`, `packed_tons`, `transition_loss_tons`,
    `reject_loss_tons` and `unaccounted_loss_tons` — at 0,
    `projected_refractory_units_nominal` at 0, and both `rebuild_window_start_at`
    and `rebuild_window_end_at` null."

    Design: Corner/errors/campaign_activation_on_a_cold_furnace_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-X13", design_pull_tpd=300.00)
    first = fixtures.create_campaign(
        api, furnace["id"], code="CMP-X13-A", target_pull_tpd=300.00,
        window_start_at=CAMPAIGN_START, window_end_at=CAMPAIGN_END,
    )
    fixtures.activate_campaign(api, first["id"])
    validate_success(api.wind_down_campaign(first["id"], fixtures.users.PLANT_MANAGER))
    validate_success(
        api.schedule_campaign_rebuild(
            first["id"],
            factories.rebuild_window_payload(
                rebuild_window_start_at=REBUILD_START, rebuild_window_end_at=REBUILD_END
            ),
            fixtures.users.PLANT_MANAGER,
        )
    )
    second = fixtures.create_campaign(
        api, furnace["id"], code="CMP-X13-B", target_pull_tpd=300.00,
        window_start_at=REBUILD_START, window_end_at="2026-08-22T00:00:00Z",
    )

    refused = api.activate_campaign(second["id"], fixtures.users.PLANT_MANAGER)
    validate_error(refused, ApiErrorId.ERR_FURNACE_POSTURE_BLOCKED, 409)

    cold = fixtures.read_furnace(api, furnace["id"])
    assert cold["posture"] == FurnacePosture.COLD
    assert cold["refractory_remaining_pct"] == 100.00

    held = fixtures.read_campaign(api, second["id"])
    assert held["status"] == CampaignStatus.PLANNED
    assert held["version"] == 1
    assert held["projected_refractory_units_nominal"] == 0.00

    closed = validate_success(api.close_campaign(first["id"], fixtures.users.PLANT_MANAGER))
    assert closed["status"] == CampaignStatus.CLOSED
    assert fixtures.read_furnace(api, furnace["id"])["posture"] == FurnacePosture.OPERATING

    activated = validate_success(
        api.activate_campaign(second["id"], fixtures.users.PLANT_MANAGER)
    )
    assert activated["status"] == CampaignStatus.ACTIVE
    assert activated["projected_refractory_units_nominal"] == 3000.00


def test_14_an_aborted_colour_change_refuses_both_completion_and_a_second_abort(api):
    """ABORTED is terminal, the furnace never leaves FLINT and the abort was the only write.

    PRD: "Completing a transition moves it `SCHEDULED → COMPLETED` and requires
    three things: the change is still `SCHEDULED`, else
    `ERR_COLOR_CHANGE_STATE_INVALID`; the logical clock has reached or passed
    `window_end_at`, else `ERR_WINDOW_NOT_ELAPSED`; and no job in `RUNNING`
    overlaps the transition window, else `ERR_RUNNING_JOB_PRESENT`."

    PRD: "An abort leaves the furnace's `current_color` untouched, charges nothing
    to any campaign, and increments the colour change's `version` by 1."

    PRD: "17. A colour change is `SCHEDULED`, else
    `ERR_COLOR_CHANGE_STATE_INVALID` — on colour-change completion and abort."

    Design: Corner/errors/completing_an_aborted_color_change_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-X14", design_pull_tpd=300.00)
    change = fixtures.schedule_color_change(
        api,
        furnace["id"],
        to_color=GlassColor.AMBER,
        window_start_at="2026-07-28T00:00:00Z",
        window_end_at="2026-07-30T00:00:00Z",
        transition_loss_tons=30.00,
    )
    validate_success(
        api.abort_color_change(change["id"], fixtures.users.BATCH_TECH, reason="Order pulled")
    )

    refused = api.complete_color_change(change["id"], fixtures.users.BATCH_TECH)
    validate_error(refused, ApiErrorId.ERR_COLOR_CHANGE_STATE_INVALID, 409)

    held = validate_success(api.get_color_change(change["id"], fixtures.users.BATCH_TECH))
    assert held["status"] == ColorChangeStatus.ABORTED
    assert held["version"] == 2

    untouched = fixtures.read_furnace(api, furnace["id"])
    assert untouched["current_color"] == GlassColor.FLINT
    assert untouched["version"] == 1

    twice = api.abort_color_change(change["id"], fixtures.users.BATCH_TECH)
    validate_error(twice, ApiErrorId.ERR_COLOR_CHANGE_STATE_INVALID, 409)


def test_15_every_collection_answers_an_unknown_id_with_its_own_code(api):
    """One unresolvable uuid produces twelve distinct not-found codes, all at 404.

    PRD: "Each entity has its own not-found code: `ERR_FURNACE_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_BATCH_RECIPE_NOT_FOUND`,
    `ERR_COLOR_CHANGE_NOT_FOUND`, `ERR_FORMING_MACHINE_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_BOTTLE_DESIGN_NOT_FOUND`,
    `ERR_MOLD_SET_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PRODUCTION_JOB_NOT_FOUND`, `ERR_PACK_LOT_NOT_FOUND` and
    `ERR_COMPLAINT_NOT_FOUND`, each at HTTP 404."

    PRD: "Reading the inspection readings of a lot whose identifier does not
    resolve yields `ERR_PACK_LOT_NOT_FOUND` and never an empty list, and the
    campaigns of a non-existent furnace yield `ERR_FURNACE_NOT_FOUND`."

    PRD: "5. Every path identifier resolves, left to right, else the
    corresponding not-found code."

    Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found_codes
    """
    pm = fixtures.users.PLANT_MANAGER
    qe = fixtures.users.QE_APPROVER

    validate_error(
        api.get_campaign(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_CAMPAIGN_NOT_FOUND, 404
    )
    validate_error(
        api.get_batch_recipe(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_BATCH_RECIPE_NOT_FOUND, 404
    )
    validate_error(
        api.get_color_change(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_COLOR_CHANGE_NOT_FOUND, 404
    )
    validate_error(
        api.get_forming_machine(NON_EXISTENT_UUID, pm),
        ApiErrorId.ERR_FORMING_MACHINE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_customer(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_CUSTOMER_NOT_FOUND, 404
    )
    validate_error(
        api.get_bottle_design(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_BOTTLE_DESIGN_NOT_FOUND, 404
    )
    validate_error(
        api.get_mold_set(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_MOLD_SET_NOT_FOUND, 404
    )
    validate_error(
        api.get_lightweighting_program(NON_EXISTENT_UUID, qe),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_production_job(NON_EXISTENT_UUID, pm),
        ApiErrorId.ERR_PRODUCTION_JOB_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_pack_lot(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_PACK_LOT_NOT_FOUND, 404
    )
    validate_error(
        api.get_complaint(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_COMPLAINT_NOT_FOUND, 404
    )
    validate_error(
        api.get_furnace(NON_EXISTENT_UUID, pm), ApiErrorId.ERR_FURNACE_NOT_FOUND, 404
    )
    validate_error(
        api.list_inspection_results(NON_EXISTENT_UUID, pm),
        ApiErrorId.ERR_PACK_LOT_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_furnace_campaigns(NON_EXISTENT_UUID, pm),
        ApiErrorId.ERR_FURNACE_NOT_FOUND,
        404,
    )
