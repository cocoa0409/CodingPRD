"""Role exclusivity, the shared read surface, customer scoping and the two-person controls."""

from test_helpers import (
    ApiErrorId,
    ComplaintAttribution,
    ComplaintStatus,
    DefectClass,
    FurnacePosture,
    LotLogisticsStatus,
    LotQualityStatus,
    MoldFamily,
    PalletizationStandard,
    QualityStanding,
    Settlement,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

CAMPAIGN_START = "2026-08-01T00:00:00Z"
CAMPAIGN_END = "2026-08-11T00:00:00Z"
JOB_END = "2026-08-03T00:00:00Z"
AGED_UNTIL = "2026-08-04T00:00:00Z"


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
    kwargs.setdefault(
        "design", {"code": f"BD-{suffix}", "nominal_weight_g": 190.00}
    )
    kwargs.setdefault("mold_set", {"code": f"MS-{suffix}"})
    return fixtures.bring_up_plant(api, **kwargs)


def test_01_recipe_approval_belongs_to_the_batch_house_alone(api):
    """The manager and the quality engineer are both refused; only the tech flips the flag.

    PRD: "A `BatchHouseTech` alone registers and approves batch recipes and plans,
    completes or aborts colour changes."

    PRD: "When both headers are well formed but the role is not among those
    authorised for the operation, the request fails with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."

    PRD: "New recipes are created with `approved` false; approval by a
    `BatchHouseTech` sets `approved` to true and is the gate that lets production
    use the recipe at all."

    Design: Corner/rbac/plant_manager_cannot_approve_a_batch_recipe
    """
    furnace = fixtures.create_furnace(api, code="FUR-R1", design_pull_tpd=300.00)
    recipe = fixtures.create_batch_recipe(
        api, furnace["id"], code="BR-R1", cullet_ratio_pct=40.00
    )

    as_manager = api.approve_batch_recipe(recipe["id"], fixtures.users.PLANT_MANAGER)
    validate_error(as_manager, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    held = validate_success(api.get_batch_recipe(recipe["id"], fixtures.users.BATCH_TECH))
    assert held["approved"] is False
    assert held["version"] == 1

    as_quality = api.approve_batch_recipe(recipe["id"], fixtures.users.QE_APPROVER)
    validate_error(as_quality, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    approved = validate_success(
        api.approve_batch_recipe(recipe["id"], fixtures.users.BATCH_TECH)
    )
    assert approved["approved"] is True
    assert approved["version"] == 2


def test_02_the_furnace_read_is_shared_by_the_plant_but_closed_to_the_customer(api):
    """Five plant roles read the same furnace; the rep is refused yet still reads itself.

    PRD: "The same scoping governs the reads a `CustomerRep` may perform —
    customers, designs, programs, pack lots, inspection readings and complaints,
    all scoped to the represented customer."

    PRD: "When both headers are well formed but the role is not among those
    authorised for the operation, the request fails with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."

    PRD: "From that percentage plus the state of the furnace's campaigns the
    server derives `posture`, evaluated as an ordered cascade with the first
    matching rule winning."

    PRD: "In every other case posture is `OPERATING`. Both comparisons are
    inclusive on a two-decimal percentage."

    Design: Corner/rbac/every_operating_role_shares_the_furnace_read
    """
    furnace = fixtures.create_furnace(
        api, code="FUR-R2", design_pull_tpd=300.00, refractory_life_total_units=100000.00
    )
    customer = fixtures.create_customer(api, name="Granby Filling", account_code="CUST-R2")

    read = validate_success(api.get_furnace(furnace["id"], fixtures.users.PLANT_MANAGER))
    assert read["code"] == "FUR-R2"
    assert read["posture"] == FurnacePosture.OPERATING
    assert read["refractory_remaining_pct"] == 100.00

    for headers in (
        fixtures.users.SCHEDULER,
        fixtures.users.BATCH_TECH,
        fixtures.users.MOLD_ENGINEER,
        fixtures.users.QE_INSPECTOR,
        fixtures.users.WAREHOUSE,
    ):
        shared = validate_success(api.get_furnace(furnace["id"], headers))
        assert shared["code"] == "FUR-R2"

    rep = fixtures.users.customer_rep(customer["id"])
    refused = api.get_furnace(furnace["id"], rep)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    own = validate_success(api.get_customer(customer["id"], rep))
    assert own["account_code"] == "CUST-R2"


def test_03_palletization_belongs_to_the_warehouse_even_on_a_fully_aged_lot(api):
    """The role check outranks the elapsed aging window, and the warehouse packs 1667 pallets.

    PRD: "A `WarehouseOperator` alone palletizes and ships lots. A `CustomerRep`
    alone records the customer's pilot-or-reject decision, files complaints, and
    settles them."

    PRD: "It sets `pallet_count` to the lot's `net_packed_units` divided by the
    units the lot's own snapshot `palletization_standard` holds — 1800 for
    `EURO_1200x800`, 2100 for `GMA_1200x1000` — rounded *up* to the next whole
    pallet, and increments the lot's `version` by 1."

    PRD: "Note that the logistics dimension advances independently of the quality
    dimension: a lot may be palletized while its `quality_status` is still
    `PENDING_INSPECTION`, and indeed usually is, which is exactly why a later
    inspection reading has to recompute `pallet_count`."

    Design: Corner/rbac/batch_house_tech_cannot_palletize_an_aged_lot
    """
    ctx = _ten_day_plant(
        api, "R3", customer={"account_code": "CUST-R3",
                             "palletization_standard": PalletizationStandard.EURO},
    )
    _job, lot = fixtures.completed_job_with_lot(
        api, ctx, produced_units=3000000, code="PJ-R3",
        window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
    )
    fixtures.set_clock(api, AGED_UNTIL)

    as_tech = api.palletize_pack_lot(lot["id"], fixtures.users.BATCH_TECH)
    validate_error(as_tech, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    held = fixtures.read_lot(api, lot["id"])
    assert held["logistics_status"] == LotLogisticsStatus.IN_AGING
    assert held["pallet_count"] == 0
    assert held["aged_until_at"] == "2026-08-04T00:00:00.000Z"

    as_manager = api.palletize_pack_lot(lot["id"], fixtures.users.PLANT_MANAGER)
    validate_error(as_manager, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    packed = validate_success(api.palletize_pack_lot(lot["id"], fixtures.users.WAREHOUSE))
    assert packed["logistics_status"] == LotLogisticsStatus.PALLETIZED
    assert packed["pallet_count"] == 1667
    assert packed["quality_status"] == LotQualityStatus.PENDING_INSPECTION


def test_04_settlement_scope_comes_only_from_the_acting_user_id(api):
    """The wrong rep holds the right role and is still refused; the right rep credits 135.03.

    PRD: "A `CustomerRep` acting on a program or complaint belonging to any other
    customer is rejected with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."

    PRD: "A severity share is then taken as the complaint's `breakage_ppm` divided
    by the customer's `complaint_ppm_threshold`, rounded half up to 4 decimals and
    capped at 1.0000, so breaching the contractual threshold pays in full and
    nothing more."

    PRD: "`credit_usd` is then that rounded per-pallet amount multiplied by
    `affected_pallets`, rounded half up to 2 decimals."

    PRD: "`quality_standing` is then derived with strict comparisons: `CRITICAL`
    when `weighted_breakage_ppm` is strictly greater than the customer's
    `complaint_ppm_threshold`, `WATCH` when it is strictly greater than half that
    threshold, and `GOOD` otherwise."

    Design: Corner/rbac/customer_rep_cannot_settle_another_customers_complaint
    """
    ctx = _ten_day_plant(
        api,
        "R4",
        customer={"name": "Halden Filling", "account_code": "CUST-R4-A",
                  "palletization_standard": PalletizationStandard.EURO,
                  "complaint_ppm_threshold": 5000.00},
        design={"code": "BD-R4", "nominal_weight_g": 190.00,
                "min_wall_thickness_mm": 1.80, "container_price_usd": 0.1500},
    )
    outsider = fixtures.create_customer(
        api,
        name="Ilkley Filling",
        account_code="CUST-R4-B",
        palletization_standard=PalletizationStandard.EURO,
        complaint_ppm_threshold=5000.00,
    )
    lot = fixtures.shipped_lot(
        api,
        ctx,
        produced_units=3000000,
        readings=[{"defect_class": DefectClass.MINOR, "rejected_units": 1000}],
        job_overrides={
            "code": "PJ-R4",
            "window_start_at": CAMPAIGN_START,
            "window_end_at": JOB_END,
        },
    )
    complaint = fixtures.file_complaint(
        api, ctx.customer_id, lot["id"], code="CP-R4", affected_units=5000
    )
    fixtures.investigate(api, complaint["id"], ComplaintAttribution.SHARED)

    refused = api.settle_complaint(
        complaint["id"],
        factories.settle_payload(Settlement.CREDIT),
        fixtures.users.customer_rep(outsider["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION, 403)

    held = fixtures.read_complaint(api, complaint["id"])
    assert held["status"] == ComplaintStatus.INVESTIGATING
    assert held["credit_usd"] == 0.00
    assert held["version"] == 2

    assert fixtures.read_customer(api, ctx.customer_id)["credit_issued_usd"] == 0.00
    assert fixtures.read_customer(api, outsider["id"])["credit_issued_usd"] == 0.00

    settled = validate_success(
        api.settle_complaint(
            complaint["id"], factories.settle_payload(Settlement.CREDIT), ctx.rep_headers
        )
    )
    assert settled["status"] == ComplaintStatus.CREDIT_ISSUED
    assert settled["breakage_ppm"] == 1667.2
    assert settled["affected_pallets"] == 3
    assert settled["credit_usd"] == 135.03

    customer = fixtures.read_customer(api, ctx.customer_id)
    assert customer["credit_issued_usd"] == 135.03
    assert customer["weighted_breakage_ppm"] == 1667.20
    assert customer["quality_standing"] == QualityStanding.GOOD


def test_05_the_rework_control_bars_the_recording_inspector_by_identity(api):
    """qe-1 recorded the quarantining reading, so only a different engineer may rework it.

    PRD: "After rework, a `QualityEngineer` may move it `QUARANTINED → RELEASED`,
    provided the acting `X-User-ID` differs from every `recorded_by_user_id` on
    that lot's inspection readings; a rework release signed by one of the
    inspectors is refused with `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "A quarantined lot's rework releaser must differ from *every* engineer
    who recorded any inspection reading on that lot — one shared identifier
    anywhere in the lot's reading history is enough to refuse."

    PRD: "A `QUARANTINED` lot also computes `final_yield_pct` and adds its reject
    tonnage to `reject_loss_tons`, but adds nothing to `packed_tons`, because
    nothing has been passed for sale yet."

    PRD: "The rework release adds the lot's net packed tonnage to the campaign's
    `packed_tons`, recomputes `final_yield_pct` on the same final-variant rule,
    re-reconciles the campaign's `unaccounted_loss_tons`, and increments the lot's
    `version` by 1."

    Design: Corner/rbac/rework_release_by_the_recording_inspector_rejected
    """
    ctx = _ten_day_plant(api, "R5")
    _job, lot = fixtures.completed_job_with_lot(
        api, ctx, produced_units=3000000, code="PJ-R5",
        window_start_at=CAMPAIGN_START, window_end_at=JOB_END,
    )
    fixtures.record_reading(
        api,
        lot["id"],
        headers=fixtures.users.QE_RISK_SIGNER,
        defect_class=DefectClass.MAJOR,
        defect_code="STONE",
        rejected_units=10000,
    )
    quarantined = fixtures.release_lot(api, lot["id"], fixtures.users.QE_APPROVER)
    assert quarantined["quality_status"] == LotQualityStatus.QUARANTINED
    assert quarantined["major_ppm"] == 3333.3

    refused = api.rework_release_pack_lot(lot["id"], fixtures.users.QE_RISK_SIGNER)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    held = fixtures.read_lot(api, lot["id"])
    assert held["quality_status"] == LotQualityStatus.QUARANTINED
    assert held["final_yield_pct"] == 94.68
    assert held["net_packed_units"] == 2990000

    ledger = fixtures.read_campaign(api, ctx.campaign_id)
    assert ledger["packed_tons"] == 0.00
    assert ledger["reject_loss_tons"] == 1.90

    reworked = validate_success(
        api.rework_release_pack_lot(lot["id"], fixtures.users.QE_INSPECTOR)
    )
    assert reworked["quality_status"] == LotQualityStatus.RELEASED

    assert fixtures.read_campaign(api, ctx.campaign_id)["packed_tons"] == 568.10
