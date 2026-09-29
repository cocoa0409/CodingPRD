"""Constant selection, rounding order and input-set filtering inside the formulas."""

from test_helpers import (
    ApiErrorId,
    BottleDesignStatus,
    ComplaintAttribution,
    ComplaintStatus,
    DefectClass,
    FormingMachineStatus,
    LotLogisticsStatus,
    LotQualityStatus,
    MoldFamily,
    MoldSetStatus,
    PalletizationStandard,
    ProductionJobStatus,
    QualityStanding,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

CAMPAIGN_START = "2026-08-01T00:00:00Z"
CAMPAIGN_END = "2026-08-11T00:00:00Z"
JOB_END = "2026-08-03T00:00:00Z"


def _ten_day_plant(api, suffix, design=None, customer=None):
    """A furnace, ten-day ACTIVE campaign, approved recipe, machine, design and tooling."""
    return fixtures.bring_up_plant(
        api,
        furnace={"code": f"FUR-{suffix}", "design_pull_tpd": 300.00,
                 "refractory_life_total_units": 100000.00},
        customer=customer,
        campaign={
            "code": f"CMP-{suffix}",
            "target_pull_tpd": 300.00,
            "window_start_at": CAMPAIGN_START,
            "window_end_at": CAMPAIGN_END,
        },
        recipe={"code": f"BR-{suffix}", "cullet_ratio_pct": 40.00},
        machine={"code": f"IS-{suffix}", "max_cavities": 40,
                 "primary_mold_family": MoldFamily.NNPB, "changeover_buffer_minutes": 45},
        design=design,
        mold_set={"code": f"MS-{suffix}"},
    )


def test_01_a_foreign_family_swap_multiplies_the_base_and_takes_the_larger_penalty(api):
    """A BLOW_BLOW set on an NNPB machine with cavity delta 4 and condition 80 costs 125 minutes.

    PRD: "That base is multiplied by 1.5 when the mold set's `mold_family` differs
    from the machine's `primary_mold_family`, and left as it is when they match —
    a foreign family means the machine has to be re-tooled, not merely re-molded."

    PRD: "The cavity penalty depends on the absolute difference between the mold
    set's `cavity_count` and the design's `cavity_count`: 0 minutes when the two
    are equal, 15 minutes when the difference is 1 or 2, 35 minutes when it is 3,
    4 or 5, and 60 minutes when it is greater than 5."

    PRD: "The condition penalty depends on the set's `condition_score`: 0 minutes
    at 85 or above, 10 minutes from 71 through 84, and 25 minutes at 70 or below."

    PRD: "The mold set moves `AVAILABLE → MOUNTED`, takes the job's
    `forming_machine_id` as its own, has its `mount_count` increased by 1 and its
    `version` increased by 1."

    Design: Corner/calculations/changeover_minutes_constants_applied_on_foreign_family_swap
    """
    ctx = _ten_day_plant(
        api,
        "C1",
        design={"code": "BD-C1", "cavity_count": 8},
    )
    mold_set = validate_success(
        api.get_mold_set(ctx.mold_set_id, fixtures.users.MOLD_ENGINEER)
    )
    assert mold_set["status"] == MoldSetStatus.AVAILABLE

    # Replace the matching tooling with a foreign-family set of 12 cavities.
    foreign = validate_success(
        api.create_mold_set(
            factories.mold_set_payload(
                ctx.design_id,
                code="MS-C1-FOREIGN",
                cavity_count=12,
                mold_family=MoldFamily.BLOW_BLOW,
                condition_score=80,
            ),
            fixtures.users.MOLD_ENGINEER,
        ),
        201,
    )

    job = fixtures.schedule_job(
        api,
        ctx,
        code="PJ-C1",
        window_start_at=CAMPAIGN_START,
        window_end_at=JOB_END,
        planned_pull_tpd=300.00,
        mold_set_id=foreign["id"],
    )
    assert job["changeover_minutes"] == 0
    assert job["reserved_melt_tons"] == 600.00

    started = validate_success(api.start_production_job(job["id"], fixtures.users.SCHEDULER))

    assert started["status"] == ProductionJobStatus.RUNNING
    # 60 x 1.5 = 90 swap minutes, plus max(cavity 35, condition 10) = 35.
    assert started["changeover_minutes"] == 125
    assert started["reserved_melt_tons"] == 600.00

    mounted = fixtures.read_mold_set(api, foreign["id"])
    assert mounted["status"] == MoldSetStatus.MOUNTED
    assert mounted["mount_count"] == 1
    assert mounted["forming_machine_id"] == ctx.machine_id
    assert mounted["version"] == 2

    machine = fixtures.read_machine(api, ctx.machine_id)
    assert machine["mounted_cavities"] == 12
    assert machine["status"] == FormingMachineStatus.RUNNING


def test_02_the_risk_index_sums_unrounded_terms_before_rounding_once(api):
    """A 170.00 g / 500.00 ml / 1.50 mm / 600.00 bpm design scores exactly 52.80.

    PRD: "Its thinness term is the amount by which 0.36 exceeds the design's
    grams of glass per millilitre of capacity — that is, `nominal_weight_g`
    divided by `capacity_ml` — floored at zero and then multiplied by 100."

    PRD: "A wall penalty of 8 applies when `min_wall_thickness_mm` is strictly
    below 1.60, and 0 otherwise."

    PRD: "The raw score is 8 times the thinness term, plus 12 times the speed
    term, plus 6 times the history term, plus the wall penalty; none of those
    intermediates is rounded."

    PRD: "A risk surcharge is then added: nothing when `breakage_risk_index` is
    30.00 or lower, 10 days when it is above 30.00 and at most 45.00, and 25 days
    when it is above 45.00."

    Design: Corner/calculations/breakage_risk_index_precision_with_thin_wall_penalty
    """
    customer = fixtures.create_customer(api, name="Cascade Filling", account_code="ACC-C2")
    design = fixtures.create_design(
        api,
        customer["id"],
        code="BD-C2",
        capacity_ml=500.00,
        nominal_weight_g=170.00,
        min_wall_thickness_mm=1.50,
        cavity_count=10,
        target_line_speed_bpm=600.00,
    )
    assert design["breakage_risk_index"] == 0.00
    assert design["lead_time_days"] == 0

    submitted = validate_success(
        api.submit_bottle_design(design["id"], fixtures.users.MOLD_ENGINEER)
    )

    assert submitted["status"] == BottleDesignStatus.SUBMITTED
    # 8 x 2.0 + 12 x 2.4 + 6 x 0 + 8 = 16 + 28.8 + 8.
    assert submitted["breakage_risk_index"] == 52.80
    # 45 base + 3 cavity groups x 5 + 0 revisions + 25 surcharge.
    assert submitted["lead_time_days"] == 85
    assert submitted["revision_count"] == 0
    assert submitted["version"] == 2

    owner = fixtures.read_customer(api, customer["id"])
    assert owner["quality_standing"] == QualityStanding.GOOD


def test_03_the_signoff_cap_refuses_56_and_admits_exactly_55(api):
    """The cap comparison is strictly greater-than, so 55.00 signs off and 56.00 does not.

    PRD: "Risk sign-off moves the design `SUBMITTED → RISK_SIGNED` and is
    permitted only when `breakage_risk_index` is 55.00 or lower; a design above
    that cap cannot be signed at all and is refused with
    `ERR_RISK_INDEX_ABOVE_CAP`, which in practice sends the engineer back to add
    glass or thicken the wall."

    PRD: "The raw score is 8 times the thinness term, plus 12 times the speed
    term, plus 6 times the history term, plus the wall penalty; none of those
    intermediates is rounded."

    Design: Corner/calculations/breakage_risk_index_at_signoff_cap_boundary
    """
    customer = fixtures.create_customer(api, name="Harbour Beverages", account_code="ACC-C3")
    shape = {
        "capacity_ml": 400.00,
        "min_wall_thickness_mm": 1.80,
        "cavity_count": 8,
        "target_line_speed_bpm": 250.00,
    }
    over = fixtures.create_submitted_design(
        api, customer["id"], code="BD-C3-OVER", nominal_weight_g=122.00, **shape
    )
    at_cap = fixtures.create_submitted_design(
        api, customer["id"], code="BD-C3-AT", nominal_weight_g=122.50, **shape
    )

    # 8 x 5.5 + 12 x 1.0 = 44 + 12.
    assert over["breakage_risk_index"] == 56.00
    # 8 x 5.375 + 12 x 1.0 = 43 + 12.
    assert at_cap["breakage_risk_index"] == 55.00

    refused = api.risk_signoff_bottle_design(over["id"], fixtures.users.QE_RISK_SIGNER)
    validate_error(refused, ApiErrorId.ERR_RISK_INDEX_ABOVE_CAP, 422)

    blocked = fixtures.read_design(api, over["id"])
    assert blocked["status"] == BottleDesignStatus.SUBMITTED
    assert blocked["risk_signed_by_user_id"] is None
    assert blocked["breakage_risk_index"] == 56.00

    signed = validate_success(
        api.risk_signoff_bottle_design(at_cap["id"], fixtures.users.QE_RISK_SIGNER)
    )
    assert signed["status"] == BottleDesignStatus.RISK_SIGNED
    assert signed["breakage_risk_index"] == 55.00
    assert signed["lead_time_days"] == 80


def test_04_major_ppm_at_exactly_2500_quarantines_while_one_reject_fewer_releases(api):
    """7500 rejects on 3,000,000 packed give 2500.0 and quarantine; 7499 give 2499.7 and release.

    PRD: "`major_ppm` is one million times the summed `rejected_units` of readings
    whose class is `MAJOR`, divided by the lot's gross `packed_units`, rounded
    half up to 1 decimal; `minor_ppm` is the same computation over readings whose
    class is `MINOR`."

    PRD: "Both parts-per-million comparisons are inclusive: a lot at exactly
    2500.0 major is quarantined, not released."

    PRD: "A `QUARANTINED` lot also computes `final_yield_pct` and adds its reject
    tonnage to `reject_loss_tons`, but adds nothing to `packed_tons`, because
    nothing has been passed for sale yet."

    PRD: "Net packed tonnage is `net_packed_units` multiplied by `unit_weight_g`
    divided by 1,000,000, rounded half up to 2 decimals; reject tonnage is the
    same conversion applied to `reject_units`."

    Design: Corner/calculations/lot_quality_disposition_major_ppm_at_limit_quarantines
    """
    ctx = _ten_day_plant(
        api, "C4", design={"code": "BD-C4", "nominal_weight_g": 190.00, "cavity_count": 8}
    )
    second_set = validate_success(
        api.create_mold_set(
            factories.mold_set_payload(ctx.design_id, code="MS-C4B"),
            fixtures.users.MOLD_ENGINEER,
        ),
        201,
    )

    _closed_a, lot_a = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-C4A",
        window_start_at=CAMPAIGN_START,
        window_end_at=JOB_END,
    )
    _closed_b, lot_b = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-C4B",
        window_start_at="2026-08-03T01:00:00Z",
        window_end_at="2026-08-05T01:00:00Z",
        mold_set_id=second_set["id"],
    )

    fixtures.record_reading(
        api, lot_a["id"], defect_class=DefectClass.MAJOR, defect_code="THIN_WALL",
        rejected_units=7500,
    )
    fixtures.record_reading(
        api, lot_b["id"], defect_class=DefectClass.MAJOR, defect_code="THIN_WALL",
        rejected_units=7499,
    )

    quarantined = validate_success(
        api.release_pack_lot(lot_a["id"], fixtures.users.QE_RELEASER)
    )

    assert quarantined["quality_status"] == LotQualityStatus.QUARANTINED
    assert quarantined["major_ppm"] == 2500.0
    assert quarantined["minor_ppm"] == 0.0
    assert quarantined["reject_units"] == 7500
    assert quarantined["net_packed_units"] == 2992500
    assert quarantined["final_yield_pct"] == 94.76

    released = validate_success(
        api.release_pack_lot(lot_b["id"], fixtures.users.QE_RELEASER)
    )
    assert released["quality_status"] == LotQualityStatus.RELEASED
    assert released["major_ppm"] == 2499.7
    assert released["net_packed_units"] == 2992501
    assert released["final_yield_pct"] == 94.76

    campaign = fixtures.read_campaign(api, ctx.campaign_id)
    assert campaign["packed_tons"] == 568.58
    # 1.43 from the quarantined lot plus 1.42 from the released one.
    assert campaign["reject_loss_tons"] == 2.85


def test_05_a_single_critical_reading_condemns_the_whole_lot_tonnage(api):
    """One CRITICAL reading of 10 units scraps the lot and charges all 570.00 tons to rejects.

    PRD: "If any reading on the lot has `defect_class` `CRITICAL`, the lot moves
    `PENDING_INSPECTION → SCRAPPED`, no matter how few units the reading covers:
    a critical defect condemns the lot."

    PRD: "A `SCRAPPED` lot computes no final yield and adds the entire lot
    tonnage — gross packed units converted to tons — to `reject_loss_tons`."

    PRD: "`unaccounted_loss_tons` is the residual: melt tons charged, less packed
    tons, less transition loss tons, less reject loss tons, carried to 2 decimals
    and permitted to be zero."

    PRD: "In all three outcomes the campaign's `unaccounted_loss_tons` is
    re-reconciled from the updated ledger, so the residual always reflects the
    newest disposition."

    Design: Corner/calculations/lot_critical_reading_scraps_the_whole_lot
    """
    ctx = _ten_day_plant(
        api, "C5", design={"code": "BD-C5", "nominal_weight_g": 190.00, "cavity_count": 8}
    )
    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-C5",
        window_start_at=CAMPAIGN_START,
        window_end_at=JOB_END,
    )
    assert lot["provisional_yield_pct"] == 95.00

    fixtures.record_reading(
        api, lot["id"], defect_class=DefectClass.CRITICAL, defect_code="CHECK_CRACK",
        rejected_units=10,
    )

    scrapped = validate_success(api.release_pack_lot(lot["id"], fixtures.users.QE_RELEASER))

    assert scrapped["quality_status"] == LotQualityStatus.SCRAPPED
    assert scrapped["major_ppm"] == 0.0
    assert scrapped["minor_ppm"] == 0.0
    assert scrapped["provisional_yield_pct"] == 95.00
    assert scrapped["final_yield_pct"] == 0.00

    campaign = fixtures.read_campaign(api, ctx.campaign_id)
    assert campaign["melt_tons_charged"] == 600.00
    assert campaign["packed_tons"] == 0.00
    # The whole 3,000,000 x 190 g gross tonnage, not the 0.00 tons of ten rejects.
    assert campaign["reject_loss_tons"] == 570.00
    assert campaign["transition_loss_tons"] == 0.00
    assert campaign["unaccounted_loss_tons"] == 30.00


def test_06_only_credited_complaints_enter_the_weighted_breakage_mean(api):
    """A rejected complaint at 20006.7 ppm is excluded, leaving 2600.90 and WATCH.

    PRD: "A `REJECT` settlement moves the complaint `INVESTIGATING → REJECTED`
    with no attribution requirement, leaves the customer's `credit_issued_usd`
    and `quality_standing` untouched, and computes no credit."

    PRD: "`affected_pallets` is the complaint's `affected_units` divided by that
    pallet size, rounded *up* to the next whole pallet."

    PRD: "The per-pallet amount is the units per pallet multiplied by the
    design's `container_price_usd`, multiplied by the severity share, multiplied
    by a credit factor of 0.5 — the plant pays half the glass value, the customer
    carrying the other half as its own handling exposure — and that per-pallet
    amount is rounded half up to cents **first**."

    PRD: "`weighted_breakage_ppm` is recomputed from scratch over the customer's
    complaints in `CREDIT_ISSUED` only — complaints in `OPEN`, `INVESTIGATING` or
    `REJECTED` are excluded entirely — processed in `created_at` ascending order:
    it is the sum over those complaints of `breakage_ppm` multiplied by
    `affected_units`, divided by the sum of their `affected_units`, rounded half
    up to 2 decimals, and it is 0 when no credited complaint exists."

    PRD: "`quality_standing` is then derived with strict comparisons: `CRITICAL`
    when `weighted_breakage_ppm` is strictly greater than the customer's
    `complaint_ppm_threshold`, `WATCH` when it is strictly greater than half that
    threshold, and `GOOD` otherwise."

    Design: Corner/calculations/customer_quality_standing_counts_credited_complaints_only
    """
    ctx = _ten_day_plant(
        api,
        "C6",
        customer={
            "name": "Rivermouth Bottling",
            "account_code": "ACC-C6",
            "palletization_standard": PalletizationStandard.EURO,
            "complaint_ppm_threshold": 5000.00,
        },
        design={
            "code": "BD-C6",
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.80,
            "container_price_usd": 0.1500,
            "cavity_count": 8,
        },
    )
    lot = fixtures.shipped_lot(
        api,
        ctx,
        produced_units=3000000,
        readings=[{"defect_class": DefectClass.MINOR, "rejected_units": 1000}],
        job_overrides={
            "code": "PJ-C6",
            "window_start_at": CAMPAIGN_START,
            "window_end_at": JOB_END,
        },
    )
    assert lot["net_packed_units"] == 2999000

    rejected = fixtures.file_complaint(
        api, ctx.customer_id, lot["id"], code="CP-C6A", affected_units=60000
    )
    assert rejected["breakage_ppm"] == 20006.7
    fixtures.investigate(api, rejected["id"], ComplaintAttribution.CUSTOMER)
    settled_reject = fixtures.settle(api, rejected["id"], ctx.customer_id, "REJECT")
    assert settled_reject["status"] == ComplaintStatus.REJECTED
    assert settled_reject["credit_usd"] == 0.00

    credited = fixtures.file_complaint(
        api, ctx.customer_id, lot["id"], code="CP-C6B", affected_units=7800
    )
    assert credited["breakage_ppm"] == 2600.9
    fixtures.investigate(api, credited["id"], ComplaintAttribution.PLANT)

    issued = validate_success(
        api.settle_complaint(
            credited["id"],
            factories.settle_payload("CREDIT"),
            fixtures.users.customer_rep(ctx.customer_id),
        )
    )

    assert issued["status"] == ComplaintStatus.CREDIT_ISSUED
    assert issued["affected_pallets"] == 5
    # round(1800 x 0.1500 x 0.5202 x 0.5, 2) = 70.23, and 70.23 x 5 = 351.15.
    assert issued["credit_usd"] == 351.15

    customer = fixtures.read_customer(api, ctx.customer_id)
    assert customer["credit_issued_usd"] == 351.15
    assert customer["weighted_breakage_ppm"] == 2600.90
    assert customer["quality_standing"] == QualityStanding.WATCH


def test_07_a_thin_wall_design_adds_two_aging_days_before_palletization(api):
    """A 1.50 mm design ages to 2026-08-06, refusing a palletize at 2026-08-05T12:00.

    PRD: "Every lot is stamped at creation with an `aged_until_at` instant before
    which it may not be palletized, computed as the lot's `created_at` plus an
    aging allowance in whole days."

    PRD: "It gains 2 more days when the lot's bottle design has a
    `min_wall_thickness_mm` strictly below 1.60, because thin-walled containers
    are more prone to delayed stress failure."

    PRD: "It requires `logistics_status` to be `IN_AGING`, else
    `ERR_LOT_STATE_INVALID`, and requires the logical clock to have reached or
    passed `aged_until_at`, else `ERR_WINDOW_NOT_ELAPSED`."

    PRD: "It sets `pallet_count` to the lot's `net_packed_units` divided by the
    units the lot's own snapshot `palletization_standard` holds — 1800 for
    `EURO_1200x800`, 2100 for `GMA_1200x1000` — rounded *up* to the next whole
    pallet, and increments the lot's `version` by 1."

    PRD: "Note that the logistics dimension advances independently of the quality
    dimension: a lot may be palletized while its `quality_status` is still
    `PENDING_INSPECTION`, and indeed usually is, which is exactly why a later
    inspection reading has to recompute `pallet_count`."

    Design: Corner/calculations/warehouse_aging_extends_for_thin_wall_designs
    """
    ctx = _ten_day_plant(
        api,
        "C7",
        customer={
            "name": "Glenpark Cellars",
            "account_code": "ACC-C7",
            "palletization_standard": PalletizationStandard.GMA,
            "complaint_ppm_threshold": 5000.00,
        },
        design={
            "code": "BD-C7",
            "capacity_ml": 500.00,
            "nominal_weight_g": 190.00,
            "min_wall_thickness_mm": 1.50,
            "target_line_speed_bpm": 500.00,
            "cavity_count": 8,
        },
    )
    design = fixtures.read_design(api, ctx.design_id)
    assert design["breakage_risk_index"] == 32.00
    assert design["lead_time_days"] == 65

    _closed, lot = fixtures.completed_job_with_lot(
        api,
        ctx,
        produced_units=3000000,
        code="PJ-C7",
        window_start_at=CAMPAIGN_START,
        window_end_at=JOB_END,
    )
    # 3 base days plus 2 for the thin wall, counted from the 2026-08-01 close.
    assert lot["aged_until_at"] == "2026-08-06T00:00:00.000Z"
    assert lot["palletization_standard"] == PalletizationStandard.GMA

    fixtures.set_clock(api, "2026-08-05T12:00:00Z")
    too_early = api.palletize_pack_lot(lot["id"], fixtures.users.WAREHOUSE)
    validate_error(too_early, ApiErrorId.ERR_WINDOW_NOT_ELAPSED, 409)

    still_aging = fixtures.read_lot(api, lot["id"])
    assert still_aging["logistics_status"] == LotLogisticsStatus.IN_AGING
    assert still_aging["pallet_count"] == 0

    fixtures.set_clock(api, "2026-08-06T00:00:00Z")
    palletized = validate_success(
        api.palletize_pack_lot(lot["id"], fixtures.users.WAREHOUSE)
    )

    assert palletized["logistics_status"] == LotLogisticsStatus.PALLETIZED
    # 3,000,000 net units over 2100 per GMA pallet, rounded up.
    assert palletized["pallet_count"] == 1429
    assert palletized["palletization_standard"] == PalletizationStandard.GMA
    assert palletized["quality_status"] == LotQualityStatus.PENDING_INSPECTION
