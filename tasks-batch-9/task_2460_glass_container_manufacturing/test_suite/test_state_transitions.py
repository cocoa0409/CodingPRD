"""Legal transitions, refused replays, terminal states and transition cascades."""

from test_helpers import (
    ApiErrorId,
    BottleDesignStatus,
    CampaignStatus,
    ColorChangeStatus,
    FurnacePosture,
    GlassColor,
    LotQualityStatus,
    MoldFamily,
    MoldOwner,
    MoldSetStatus,
    PalletizationStandard,
    ProgramStatus,
    SavingsTier,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

CAMPAIGN_START = "2026-08-01T00:00:00Z"
CAMPAIGN_END = "2026-08-11T00:00:00Z"
REBUILD_START = "2026-08-12T00:00:00Z"
REBUILD_END = "2026-08-28T00:00:00Z"


def _furnace_with_a_planned_ten_day_campaign(api, suffix):
    """A 300.00 tpd furnace carrying one PLANNED ten-day campaign."""
    furnace = fixtures.create_furnace(
        api,
        code=f"FUR-{suffix}",
        design_pull_tpd=300.00,
        refractory_life_total_units=100000.00,
    )
    campaign = fixtures.create_campaign(
        api,
        furnace["id"],
        code=f"CMP-{suffix}",
        target_pull_tpd=300.00,
        window_start_at=CAMPAIGN_START,
        window_end_at=CAMPAIGN_END,
    )
    return furnace, campaign


def _scrapped_mold_set(api):
    """A set graded 30 on its return from the mold shop, so it is terminal."""
    customer = fixtures.create_customer(api, name="Sierra Spirits", account_code="CUST-S6")
    design = fixtures.create_design(api, customer["id"], code="BD-S6")
    mold_set = fixtures.create_mold_set(api, design["id"], code="MS-S6", condition_score=90)
    fixtures.send_mold_set_to_repair(api, mold_set["id"])
    return fixtures.return_mold_set(api, mold_set["id"], 30)


def _design_risk_signed_by_the_first_engineer(api, suffix, **overrides):
    """A 500.00 ml, 190.00 g design signed off on risk by the first quality engineer."""
    customer = fixtures.create_customer(
        api, name="Tango Tonics", account_code=f"CUST-{suffix}"
    )
    design = fixtures.create_risk_signed_design(
        api,
        customer["id"],
        code=f"BD-{suffix}",
        color=GlassColor.FLINT,
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=500.00,
        container_price_usd=0.1600,
        mold_owner=MoldOwner.PLANT,
        **overrides,
    )
    return customer, design


def test_01_activation_records_the_nominal_projection_for_the_whole_window(api):
    """Ten days at 300.00 tpd on flint glass project exactly 3000.00 wear units.

    PRD: "On success the server records `projected_refractory_units_nominal` for
    the campaign window using the nominal refractory projection described below,
    re-derives the furnace's `posture`, and increments the campaign's `version` by
    1."

    PRD: "The **nominal** variant is simply the base wear units rounded half up to
    2 decimals, ignoring over-pull and cullet stress entirely; it is what a
    campaign records at activation, using `target_pull_tpd`, the campaign window,
    and the colour factor of the furnace's `current_color` at that moment."

    Design: Corner/state_machines/campaign_activate_from_planned_computes_nominal_projection
    """
    furnace, campaign = _furnace_with_a_planned_ten_day_campaign(api, "S1")

    activated = validate_success(
        api.activate_campaign(campaign["id"], fixtures.users.PLANT_MANAGER)
    )
    stored_furnace = fixtures.read_furnace(api, furnace["id"])

    assert activated["status"] == CampaignStatus.ACTIVE
    assert activated["projected_refractory_units_nominal"] == 3000.00
    assert activated["melt_tons_charged"] == 0.00
    assert activated["packed_tons"] == 0.00
    assert activated["unaccounted_loss_tons"] == 0.00
    assert activated["version"] == 2
    assert stored_furnace["posture"] == FurnacePosture.OPERATING
    assert stored_furnace["refractory_remaining_pct"] == 100.00
    assert stored_furnace["campaign_count"] == 1


def test_02_a_replayed_activation_is_refused_rather_than_silently_absorbed(api):
    """The second activate is a 409 and the side effects do not run twice.

    PRD: "Activation requires the campaign to be in `PLANNED`, requires the
    furnace's posture to be anything other than `COLD`, and requires that no other
    campaign on the same furnace is currently in `ACTIVE` or `WIND_DOWN` — a
    furnace melts one campaign at a time, and a second concurrent campaign is
    refused with `ERR_FURNACE_CAMPAIGN_CONFLICT`."

    PRD: "8. Campaign state permits the requested transition, else
    `ERR_CAMPAIGN_STATE_INVALID` — on campaign activation, wind-down, rebuild
    scheduling and closure."

    Design: Corner/state_machines/campaign_second_activate_rejected
    """
    _furnace, campaign = _furnace_with_a_planned_ten_day_campaign(api, "S2")
    fixtures.activate_campaign(api, campaign["id"])

    validate_error(
        api.activate_campaign(campaign["id"], fixtures.users.PLANT_MANAGER),
        ApiErrorId.ERR_CAMPAIGN_STATE_INVALID,
        409,
    )
    current = fixtures.read_campaign(api, campaign["id"])

    assert current["status"] == CampaignStatus.ACTIVE
    assert current["version"] == 2
    assert current["projected_refractory_units_nominal"] == 3000.00


def test_03_closure_is_unreachable_from_active(api):
    """Closing straight out of ACTIVE is refused and resets no refractory counter.

    PRD: "Closure, `REBUILD_SCHEDULED → CLOSED`, is terminal and is the plant's
    accounting moment."

    PRD: "8. Campaign state permits the requested transition, else
    `ERR_CAMPAIGN_STATE_INVALID` — on campaign activation, wind-down, rebuild
    scheduling and closure."

    Design: Corner/state_machines/campaign_close_directly_from_active_rejected
    """
    furnace, campaign = _furnace_with_a_planned_ten_day_campaign(api, "S3")
    fixtures.activate_campaign(api, campaign["id"])

    validate_error(
        api.close_campaign(campaign["id"], fixtures.users.PLANT_MANAGER),
        ApiErrorId.ERR_CAMPAIGN_STATE_INVALID,
        409,
    )
    current = fixtures.read_campaign(api, campaign["id"])
    stored_furnace = fixtures.read_furnace(api, furnace["id"])

    assert current["status"] == CampaignStatus.ACTIVE
    assert current["version"] == 2
    assert current["rebuild_window_start_at"] is None
    assert stored_furnace["refractory_consumed_units"] == 0.00
    assert stored_furnace["refractory_remaining_pct"] == 100.00
    assert stored_furnace["posture"] == FurnacePosture.OPERATING


def test_04_a_second_campaign_cannot_be_activated_beside_a_live_one(api):
    """The sibling stays PLANNED at version 1 with its projection still zero.

    PRD: "19. The furnace has no other campaign in `ACTIVE` or `WIND_DOWN`, else
    `ERR_FURNACE_CAMPAIGN_CONFLICT` — on campaign activation."

    PRD: "A newly planned campaign has `status` `PLANNED`, all five melt-ledger
    figures — `melt_tons_charged`, `packed_tons`, `transition_loss_tons`,
    `reject_loss_tons` and `unaccounted_loss_tons` — at 0,
    `projected_refractory_units_nominal` at 0, and both `rebuild_window_start_at`
    and `rebuild_window_end_at` null."

    Design: Corner/state_machines/campaign_activate_blocked_by_sibling_active_campaign
    """
    furnace, first = _furnace_with_a_planned_ten_day_campaign(api, "S4A")
    second = fixtures.create_campaign(
        api,
        furnace["id"],
        code="CMP-S4B",
        target_pull_tpd=300.00,
        window_start_at=REBUILD_START,
        window_end_at="2026-08-22T00:00:00Z",
    )
    fixtures.activate_campaign(api, first["id"])

    validate_error(
        api.activate_campaign(second["id"], fixtures.users.PLANT_MANAGER),
        ApiErrorId.ERR_FURNACE_CAMPAIGN_CONFLICT,
        409,
    )
    blocked = fixtures.read_campaign(api, second["id"])
    live = fixtures.read_campaign(api, first["id"])
    stored_furnace = fixtures.read_furnace(api, furnace["id"])

    assert blocked["status"] == CampaignStatus.PLANNED
    assert blocked["version"] == 1
    assert blocked["projected_refractory_units_nominal"] == 0.00
    assert live["status"] == CampaignStatus.ACTIVE
    assert stored_furnace["campaign_count"] == 2


def test_05_a_new_mold_set_starts_available_and_unmounted(api):
    """Tooling is idle from birth, even for a design still in DRAFT.

    PRD: "It begins with `status` `AVAILABLE`, `mount_count` 0, and
    `forming_machine_id` null, since it is not mounted anywhere."

    Design: Corner/state_machines/mold_set_initial_state_is_available
    """
    customer = fixtures.create_customer(api, name="Sierra Sodas", account_code="CUST-S5")
    design = fixtures.create_design(api, customer["id"], code="BD-S5")

    created = validate_success(
        api.create_mold_set(
            factories.mold_set_payload(
                design["id"],
                code="MS-S5",
                cavity_count=8,
                mold_family=MoldFamily.NNPB,
                owner=MoldOwner.PLANT,
                condition_score=95,
            ),
            fixtures.users.MOLD_ENGINEER,
        ),
        201,
    )
    stored_design = fixtures.read_design(api, design["id"])

    assert created["status"] == MoldSetStatus.AVAILABLE
    assert created["mount_count"] == 0
    assert created["forming_machine_id"] is None
    assert created["condition_score"] == 95
    assert created["version"] == 1
    assert stored_design["status"] == BottleDesignStatus.DRAFT


def test_06_a_scrapped_set_refuses_every_further_transition(api):
    """A grade of 30 scraps the set for good and freezes it at version 3.

    PRD: "When the submitted `condition_score` is below 40, the set is likewise
    written back with that score but moves `IN_REPAIR → SCRAPPED`, which is
    terminal — the mold shop has judged the set beyond economic repair."

    Design: Corner/state_machines/mold_set_scrapped_state_is_terminal
    """
    scrapped = _scrapped_mold_set(api)

    assert scrapped["status"] == MoldSetStatus.SCRAPPED
    assert scrapped["condition_score"] == 30
    assert scrapped["version"] == 3

    validate_error(
        api.send_mold_set_to_repair(scrapped["id"], fixtures.users.MOLD_ENGINEER),
        ApiErrorId.ERR_MOLD_SET_STATE_INVALID,
        409,
    )
    validate_error(
        api.return_mold_set_from_repair(
            scrapped["id"],
            factories.return_from_repair_payload(90),
            fixtures.users.MOLD_ENGINEER,
        ),
        ApiErrorId.ERR_MOLD_SET_STATE_INVALID,
        409,
    )
    validate_error(
        api.unmount_mold_set(scrapped["id"], fixtures.users.MOLD_ENGINEER),
        ApiErrorId.ERR_MOLD_SET_STATE_INVALID,
        409,
    )
    current = fixtures.read_mold_set(api, scrapped["id"])

    assert current["status"] == MoldSetStatus.SCRAPPED
    assert current["condition_score"] == 30
    assert current["version"] == 3


def test_07_a_transition_completes_only_once_its_window_has_elapsed(api):
    """The colour advances at the window end and not one instant earlier.

    PRD: "Completing a transition moves it `SCHEDULED → COMPLETED` and requires
    three things: the change is still `SCHEDULED`, else
    `ERR_COLOR_CHANGE_STATE_INVALID`; the logical clock has reached or passed
    `window_end_at`, else `ERR_WINDOW_NOT_ELAPSED`; and no job in `RUNNING`
    overlaps the transition window, else `ERR_RUNNING_JOB_PRESENT`."

    Design: Corner/state_machines/color_change_complete_before_window_end_rejected
    """
    furnace = fixtures.create_furnace(api, code="FUR-S7", design_pull_tpd=300.00)
    change = fixtures.schedule_color_change(
        api,
        furnace["id"],
        to_color=GlassColor.AMBER,
        window_start_at="2026-08-02T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        transition_loss_tons=90.00,
    )

    validate_error(
        api.complete_color_change(change["id"], fixtures.users.BATCH_TECH),
        ApiErrorId.ERR_WINDOW_NOT_ELAPSED,
        409,
    )
    pending = validate_success(
        api.get_color_change(change["id"], fixtures.users.BATCH_TECH)
    )
    cold_furnace = fixtures.read_furnace(api, furnace["id"])

    assert pending["status"] == ColorChangeStatus.SCHEDULED
    assert pending["version"] == 1
    assert pending["from_color"] == GlassColor.FLINT
    assert cold_furnace["current_color"] == GlassColor.FLINT
    assert cold_furnace["version"] == 1

    fixtures.set_clock(api, "2026-08-03T00:00:00Z")
    completed = validate_success(
        api.complete_color_change(change["id"], fixtures.users.BATCH_TECH)
    )
    switched = fixtures.read_furnace(api, furnace["id"])

    assert completed["status"] == ColorChangeStatus.COMPLETED
    assert switched["current_color"] == GlassColor.AMBER
    assert switched["version"] == 2


def test_08_booking_the_rebuild_aborts_only_the_transitions_inside_its_window(api):
    """The earlier transition survives, the one inside the rebuild window does not.

    PRD: "Scheduling the rebuild sets both rebuild instants on the campaign,
    forces the furnace's `posture` to `COLD`, and cascades `SCHEDULED → ABORTED`
    onto every colour change on that furnace whose `window_start_at` falls on or
    after `rebuild_window_start_at` — a transition planned into a cold furnace is
    meaningless."

    Design: Corner/state_machines/campaign_schedule_rebuild_aborts_only_colour_changes_inside_rebuild_window
    """
    furnace, campaign = _furnace_with_a_planned_ten_day_campaign(api, "S8")
    fixtures.activate_campaign(api, campaign["id"])
    early = fixtures.schedule_color_change(
        api,
        furnace["id"],
        to_color=GlassColor.AMBER,
        window_start_at="2026-08-02T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        transition_loss_tons=90.00,
    )
    late = fixtures.schedule_color_change(
        api,
        furnace["id"],
        to_color=GlassColor.GREEN,
        window_start_at="2026-08-13T00:00:00Z",
        window_end_at="2026-08-14T00:00:00Z",
        transition_loss_tons=80.00,
    )
    validate_success(api.wind_down_campaign(campaign["id"], fixtures.users.PLANT_MANAGER))

    booked = validate_success(
        api.schedule_campaign_rebuild(
            campaign["id"],
            factories.rebuild_window_payload(
                rebuild_window_start_at=REBUILD_START, rebuild_window_end_at=REBUILD_END
            ),
            fixtures.users.PLANT_MANAGER,
        )
    )
    surviving = validate_success(api.get_color_change(early["id"], fixtures.users.BATCH_TECH))
    aborted = validate_success(api.get_color_change(late["id"], fixtures.users.BATCH_TECH))
    stored_furnace = fixtures.read_furnace(api, furnace["id"])

    assert booked["status"] == CampaignStatus.REBUILD_SCHEDULED
    assert booked["rebuild_window_start_at"] == "2026-08-12T00:00:00.000Z"
    assert booked["rebuild_window_end_at"] == "2026-08-28T00:00:00.000Z"
    assert surviving["status"] == ColorChangeStatus.SCHEDULED
    assert aborted["status"] == ColorChangeStatus.ABORTED
    assert stored_furnace["posture"] == FurnacePosture.COLD
    assert stored_furnace["refractory_remaining_pct"] == 100.00
    assert stored_furnace["current_color"] == GlassColor.FLINT


def test_09_closure_relines_the_furnace_and_reconciles_the_ledger(api):
    """Melt 600.00 resolves into packed 569.81, reject 0.19 and unaccounted 30.00.

    PRD: "On closure the server recomputes `unaccounted_loss_tons` from the
    campaign melt ledger, resets the furnace's `refractory_consumed_units` to 0
    and `refractory_remaining_pct` to 100.00 to reflect the new lining, sets the
    furnace's `posture` to `OPERATING`, and increments the campaign's `version` by
    1."

    PRD: "`unaccounted_loss_tons` is the residual: melt tons charged, less packed
    tons, less transition loss tons, less reject loss tons, carried to 2 decimals
    and permitted to be zero."

    Design: Corner/state_machines/campaign_close_resets_refractory_and_reconciles_melt_ledger
    """
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "FUR-S9",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Uniform Urns",
            "account_code": "CUST-S9",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-S9",
            "target_pull_tpd": 300.00,
            "window_start_at": CAMPAIGN_START,
            "window_end_at": CAMPAIGN_END,
        },
        recipe={"code": "BR-S9", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-S9"},
        design={
            "code": "BD-S9",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 8,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={"code": "MS-S9", "cavity_count": 8, "condition_score": 90},
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-S9",
        window_start_at=CAMPAIGN_START,
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="BLISTER",
        rejected_units=1000,
        inspected_at=CAMPAIGN_START,
    )
    released = fixtures.release_lot(api, lot["id"], fixtures.users.QE_RELEASER)

    assert fixtures.read_furnace(api, ctx.furnace_id)["refractory_remaining_pct"] == 99.40

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
    closed_campaign = validate_success(
        api.close_campaign(ctx.campaign_id, fixtures.users.PLANT_MANAGER)
    )
    relined = fixtures.read_furnace(api, ctx.furnace_id)

    assert closed_campaign["status"] == CampaignStatus.CLOSED
    assert relined["refractory_consumed_units"] == 0.00
    assert relined["refractory_remaining_pct"] == 100.00
    assert relined["posture"] == FurnacePosture.OPERATING
    assert closed_campaign["melt_tons_charged"] == 600.00
    assert closed_campaign["packed_tons"] == 569.81
    assert closed_campaign["reject_loss_tons"] == 0.19
    assert closed_campaign["transition_loss_tons"] == 0.00
    assert closed_campaign["unaccounted_loss_tons"] == 30.00
    assert released["final_yield_pct"] == 94.97
    assert released["quality_status"] == LotQualityStatus.RELEASED


def test_10_the_risk_signer_may_not_also_approve(api):
    """The signer's own approve is a 403 and a second engineer's approve is a 200.

    PRD: "Approval then moves the design `RISK_SIGNED → APPROVED` and requires an
    `X-User-ID` different from `risk_signed_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`; it records the approver as `approved_by_user_id`."

    Design: Corner/state_machines/design_approve_by_the_risk_signer_rejected
    """
    _customer, design = _design_risk_signed_by_the_first_engineer(api, "S10")

    validate_error(
        api.approve_bottle_design(design["id"], fixtures.users.QE_RISK_SIGNER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    unapproved = fixtures.read_design(api, design["id"])

    assert unapproved["status"] == BottleDesignStatus.RISK_SIGNED
    assert unapproved["version"] == 3
    assert unapproved["risk_signed_by_user_id"] == fixtures.users.QE_RISK_SIGNER_ID
    assert unapproved["approved_by_user_id"] is None
    assert unapproved["breakage_risk_index"] == 24.00
    assert unapproved["lead_time_days"] == 55

    approved = validate_success(
        api.approve_bottle_design(design["id"], fixtures.users.QE_APPROVER)
    )

    assert approved["status"] == BottleDesignStatus.APPROVED
    assert approved["approved_by_user_id"] == fixtures.users.QE_APPROVER_ID
    assert approved["version"] == 4


def test_11_approving_a_successor_retires_its_predecessor(api):
    """The successor earns the 10-day credit and pushes the predecessor to OBSOLETE.

    PRD: "Approval has one cascade: if this design names a `supersedes_design_id`
    and that predecessor is itself in `APPROVED`, the predecessor is moved
    `APPROVED → OBSOLETE` and its own `version` increases by 1."

    PRD: "A design that supersedes an existing one earns a credit of 10 days,
    since the tooling lineage is already understood."

    Design: Corner/state_machines/successor_design_approval_marks_predecessor_obsolete
    """
    customer = fixtures.create_customer(api, name="Victor Vintners", account_code="CUST-S11")
    geometry = {
        "color": GlassColor.FLINT,
        "capacity_ml": 500.00,
        "nominal_weight_g": 190.00,
        "min_wall_thickness_mm": 1.80,
        "cavity_count": 8,
        "target_line_speed_bpm": 500.00,
        "container_price_usd": 0.1600,
        "mold_owner": MoldOwner.PLANT,
    }
    predecessor = fixtures.create_approved_design(
        api, customer["id"], code="BD-S11A", **geometry
    )
    successor = fixtures.create_risk_signed_design(
        api,
        customer["id"],
        code="BD-S11B",
        supersedes_design_id=predecessor["id"],
        **geometry,
    )

    assert predecessor["lead_time_days"] == 55
    assert predecessor["version"] == 4

    approved = validate_success(
        api.approve_bottle_design(successor["id"], fixtures.users.QE_APPROVER)
    )
    retired = fixtures.read_design(api, predecessor["id"])

    assert approved["status"] == BottleDesignStatus.APPROVED
    assert approved["lead_time_days"] == 45
    assert approved["breakage_risk_index"] == 24.00
    assert retired["status"] == BottleDesignStatus.OBSOLETE
    assert retired["version"] == 5
    assert retired["lead_time_days"] == 55


def test_12_a_second_program_on_one_baseline_supersedes_the_first(api):
    """The superseded program keeps its frozen economics and the design version moves on.

    PRD: "Any existing program on the same `baseline_design_id` that is not
    already terminal — that is, one in `DRAFT`, `RISK_ASSESSED`, `PILOT`,
    `ADOPTED` or `SUSPENDED` — is moved to `SUPERSEDED`, with its own `version`
    incremented by 1."

    PRD: "Opening a lightweighting program requires `expected_design_version`
    carrying the `version` of the baseline bottle design as the client last
    observed it."

    Design: Corner/state_machines/new_program_on_same_baseline_supersedes_the_previous_one
    """
    customer = fixtures.create_customer(api, name="Whisky Works", account_code="CUST-S12")
    design = fixtures.create_approved_design(
        api,
        customer["id"],
        code="BD-S12",
        color=GlassColor.FLINT,
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=8,
        target_line_speed_bpm=500.00,
        container_price_usd=0.1600,
        mold_owner=MoldOwner.PLANT,
    )
    first_version = fixtures.design_version(api, design["id"])
    first = fixtures.assessed_program(
        api,
        design["id"],
        code="LW-S12A",
        target_weight_g=185.00,
        annual_volume_units=1000000,
        resin_free_glass_price_per_kg=0.5000,
        expected_design_version=first_version,
    )
    second_version = fixtures.design_version(api, design["id"])

    second = validate_success(
        api.create_lightweighting_program(
            factories.lightweighting_program_payload(
                design["id"],
                second_version,
                code="LW-S12B",
                target_weight_g=182.00,
                annual_volume_units=1000000,
                resin_free_glass_price_per_kg=0.5000,
            ),
            fixtures.users.QE_APPROVER,
        ),
        201,
    )
    superseded = fixtures.read_program(api, first["id"])

    assert first_version == 4
    assert second_version == 5
    assert fixtures.design_version(api, design["id"]) == 6
    assert second["status"] == ProgramStatus.DRAFT
    assert second["version"] == 1
    assert second["gross_savings_usd"] == 0.00
    assert superseded["status"] == ProgramStatus.SUPERSEDED
    assert superseded["version"] == 3
    assert superseded["gross_savings_usd"] == 2500.00
    assert superseded["savings_tier"] == SavingsTier.TIER_A
    assert superseded["net_savings_usd"] == 2375.00
