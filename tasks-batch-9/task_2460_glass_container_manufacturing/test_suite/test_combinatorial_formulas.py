"""Formulas whose nesting, rounding order or key selection changes the answer."""

from test_helpers import (
    ComplaintStatus,
    FormingMachineStatus,
    GlassColor,
    MoldFamily,
    MoldOwner,
    MoldSetStatus,
    PalletizationStandard,
    ProductionJobStatus,
    ProgramStatus,
    QualityStanding,
    SavingsTier,
    fixtures,
    validate_success,
)

LONG_CAMPAIGN_END = "2026-08-11T00:00:00Z"
SHIP_DAY = "2026-08-06T00:00:00Z"


def _job_awaiting_a_foreign_family_changeover(api):
    """A PRESS_BLOW set of 12 cavities scheduled onto an NNPB machine at condition 70."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-03",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Cedar Cider",
            "account_code": "CEDAR-01",
            "palletization_standard": PalletizationStandard.GMA,
            "complaint_ppm_threshold": 4000.00,
        },
        campaign={
            "code": "CMP-03",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F03", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={
            "code": "IS-03",
            "max_cavities": 40,
            "primary_mold_family": MoldFamily.NNPB,
            "changeover_buffer_minutes": 45,
        },
        design={
            "code": "BD-03",
            "color": GlassColor.FLINT,
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "cavity_count": 10,
            "target_line_speed_bpm": 500.00,
            "container_price_usd": 0.1600,
            "mold_owner": MoldOwner.PLANT,
        },
        mold_set={
            "code": "MS-03",
            "cavity_count": 12,
            "mold_family": MoldFamily.PRESS_BLOW,
            "owner": MoldOwner.PLANT,
            "condition_score": 70,
        },
    )
    job = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-03",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
        planned_pull_tpd=300.00,
    )
    return ctx, job


def _complaint_under_investigation(api):
    """A shipped 2000000-unit lot with a PLANT-attributed complaint over 5000 units."""
    ctx = fixtures.bring_up_plant(
        api,
        furnace={
            "code": "F-04",
            "design_pull_tpd": 300.00,
            "refractory_life_total_units": 100000.00,
        },
        customer={
            "name": "Delta Dairy",
            "account_code": "DELTA-01",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        campaign={
            "code": "CMP-04",
            "target_pull_tpd": 300.00,
            "window_start_at": "2026-08-01T00:00:00Z",
            "window_end_at": LONG_CAMPAIGN_END,
        },
        recipe={"code": "BR-F04", "cullet_ratio_pct": 40.00, "soda_ash_kg_per_ton": 170.00},
        machine={"code": "IS-04"},
        design={
            "code": "BD-04",
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
            "code": "MS-04",
            "cavity_count": 8,
            "owner": MoldOwner.CUSTOMER,
            "condition_score": 92,
        },
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=2001000,
        code="PJ-04",
        window_start_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-03T00:00:00Z",
    )
    fixtures.record_reading(
        api,
        lot["id"],
        defect_class="MINOR",
        defect_code="OVERPRESS",
        rejected_units=1000,
        inspected_at="2026-08-01T00:00:00Z",
    )
    fixtures.release_lot(api, lot["id"], fixtures.users.QE_RELEASER)
    fixtures.set_clock(api, SHIP_DAY)
    fixtures.palletize_lot(api, lot["id"])
    fixtures.ship_lot(api, lot["id"])

    complaint = fixtures.file_complaint(
        api,
        ctx.customer_id,
        lot["id"],
        code="CO-01",
        reported_at=SHIP_DAY,
        affected_units=5000,
        filling_line_speed_bpm=480.00,
    )
    fixtures.investigate(api, complaint["id"], "PLANT")
    # Re-read the lot: the reading recorded above recomputed net_packed_units,
    # so the close-time snapshot captured before it is stale.
    return ctx, fixtures.read_lot(api, lot["id"]), complaint


def _assessable_program(api):
    """A DRAFT program taking 16.00 g out of a design whose risk index is 24.00."""
    customer = fixtures.create_customer(
        api,
        name="Echo Estates",
        account_code="ECHO-01",
        palletization_standard=PalletizationStandard.EURO,
        complaint_ppm_threshold=5000.00,
    )
    design = fixtures.create_approved_design(
        api,
        customer["id"],
        code="BD-05",
        color=GlassColor.FLINT,
        capacity_ml=500.00,
        nominal_weight_g=190.00,
        min_wall_thickness_mm=1.80,
        cavity_count=10,
        target_line_speed_bpm=500.00,
        container_price_usd=0.1725,
        mold_owner=MoldOwner.CUSTOMER,
    )
    program = fixtures.create_program(
        api,
        design["id"],
        code="LW-01",
        target_weight_g=174.00,
        annual_volume_units=40000000,
        resin_free_glass_price_per_kg=0.1650,
        expected_design_version=design["version"],
    )
    return design, program


def test_01_changeover_charges_only_the_greater_of_the_two_penalties(api):
    """A foreign family, cavity delta 2 and condition 70 cost exactly 115 minutes.

    PRD: "The swap minutes plus the greater of those two penalties is rounded
    half up to a whole number of minutes and then capped at 240, so no single
    changeover is ever charged more than four hours."

    Design: Difficulty/combinatorial_formula/changeover_minutes_nested_min_max_over_swap_cavity_and_condition
    """
    _ctx, job = _job_awaiting_a_foreign_family_changeover(api)

    started = validate_success(api.start_production_job(job["id"], fixtures.users.SCHEDULER))

    assert started["changeover_minutes"] == 115
    assert started["status"] == ProductionJobStatus.RUNNING


def test_02_the_same_start_mounts_the_tooling_and_occupies_the_machine(api):
    """Mounting moves the set to MOUNTED and gives the machine its 12 cavities.

    PRD: "The mold set moves `AVAILABLE → MOUNTED`, takes the job's
    `forming_machine_id` as its own, has its `mount_count` increased by 1 and its
    `version` increased by 1."

    Design: Difficulty/combinatorial_formula/changeover_minutes_nested_min_max_over_swap_cavity_and_condition
    """
    ctx, job = _job_awaiting_a_foreign_family_changeover(api)

    validate_success(api.start_production_job(job["id"], fixtures.users.SCHEDULER))
    mold_set = fixtures.read_mold_set(api, ctx.mold_set_id)
    machine = fixtures.read_machine(api, ctx.machine_id)

    assert mold_set["status"] == MoldSetStatus.MOUNTED
    assert mold_set["mount_count"] == 1
    assert mold_set["forming_machine_id"] == ctx.machine_id
    assert machine["status"] == FormingMachineStatus.RUNNING
    assert machine["mounted_cavities"] == 12


def test_03_filing_a_complaint_derives_breakage_ppm_and_whole_pallets(api):
    """5000 broken units of 2000000 delivered read 2500.0 ppm across 3 pallets.

    PRD: "`affected_pallets` is the complaint's `affected_units` divided by that
    pallet size, rounded *up* to the next whole pallet."

    Design: Difficulty/combinatorial_formula/complaint_credit_round_per_pallet_then_multiply
    """
    _ctx, lot, complaint = _complaint_under_investigation(api)

    assert lot["net_packed_units"] == 2000000
    assert complaint["breakage_ppm"] == 2500.0

    settled = validate_success(
        api.settle_complaint(
            complaint["id"], {"settlement": "CREDIT"}, fixtures.users.customer_rep(lot["customer_id"])
        )
    )

    assert settled["affected_pallets"] == 3


def test_04_credit_rounds_per_pallet_before_multiplying_by_the_pallet_count(api):
    """Three pallets at 77.625 each settle at 232.89, never 232.88.

    PRD: "The per-pallet amount is the units per pallet multiplied by the
    design's `container_price_usd`, multiplied by the severity share, multiplied
    by a credit factor of 0.5 — the plant pays half the glass value, the customer
    carrying the other half as its own handling exposure — and that per-pallet
    amount is rounded half up to cents **first**."

    Design: Difficulty/combinatorial_formula/complaint_credit_round_per_pallet_then_multiply
    """
    ctx, _lot, complaint = _complaint_under_investigation(api)

    settled = validate_success(
        api.settle_complaint(
            complaint["id"], {"settlement": "CREDIT"}, fixtures.users.customer_rep(ctx.customer_id)
        )
    )

    assert settled["credit_usd"] == 232.89
    assert settled["credit_usd"] != 232.88
    assert settled["status"] == ComplaintStatus.CREDIT_ISSUED


def test_05_credited_settlement_reweighs_the_customer_standing(api):
    """The credit lands on the customer and a weighted 2500.00 ppm stays GOOD.

    PRD: "`weighted_breakage_ppm` is recomputed from scratch over the customer's
    complaints in `CREDIT_ISSUED` only — complaints in `OPEN`, `INVESTIGATING` or
    `REJECTED` are excluded entirely — processed in `created_at` ascending order:
    it is the sum over those complaints of `breakage_ppm` multiplied by
    `affected_units`, divided by the sum of their `affected_units`, rounded half
    up to 2 decimals, and it is 0 when no credited complaint exists."

    Design: Difficulty/combinatorial_formula/complaint_credit_round_per_pallet_then_multiply
    """
    ctx, _lot, complaint = _complaint_under_investigation(api)

    validate_success(
        api.settle_complaint(
            complaint["id"], {"settlement": "CREDIT"}, fixtures.users.customer_rep(ctx.customer_id)
        )
    )
    customer = fixtures.read_customer(api, ctx.customer_id)

    assert customer["credit_issued_usd"] == 232.89
    assert customer["weighted_breakage_ppm"] == 2500.00
    assert customer["quality_standing"] == QualityStanding.GOOD


def test_06_savings_tier_is_keyed_on_gross_savings(api):
    """105600.00 gross puts the program in TIER_B even though net falls below the floor.

    PRD: "Fourth, `savings_tier` is keyed on the *gross* figure and never on the
    net: `TIER_A` when `gross_savings_usd` is below 100000.00, `TIER_B` when it
    is at least 100000.00 and below 500000.00, and `TIER_C` when it is 500000.00
    or above."

    Design: Difficulty/combinatorial_formula/lightweighting_tier_keyed_on_gross_not_net_savings
    """
    design, program = _assessable_program(api)

    assessed = validate_success(api.assess_program_risk(program["id"], fixtures.users.QE_APPROVER))

    assert design["breakage_risk_index"] == 24.00
    assert assessed["weight_saved_g"] == 16.00
    assert assessed["gross_savings_usd"] == 105600.00
    assert assessed["savings_tier"] == SavingsTier.TIER_B
    assert assessed["net_savings_usd"] == 95183.62


def test_07_reserve_and_rebate_follow_the_gross_keyed_tier(api):
    """The TIER_B base rate plus a 9.60 point delta reserves 10416.38 and rebates 28555.09.

    PRD: "Sixth, a reserve rate is derived: the tier's base rate — 0.05 for
    `TIER_A`, 0.09 for `TIER_B`, 0.14 for `TIER_C` — plus 0.0009 for each point
    of `breakage_risk_delta`, with the sum rounded half up to 5 decimals."

    Design: Difficulty/combinatorial_formula/lightweighting_tier_keyed_on_gross_not_net_savings
    """
    _design, program = _assessable_program(api)

    assessed = validate_success(api.assess_program_risk(program["id"], fixtures.users.QE_APPROVER))

    assert assessed["breakage_risk_delta"] == 9.60
    assert assessed["risk_reserve_usd"] == 10416.38
    assert assessed["customer_rebate_usd"] == 28555.09
    assert assessed["status"] == ProgramStatus.RISK_ASSESSED
