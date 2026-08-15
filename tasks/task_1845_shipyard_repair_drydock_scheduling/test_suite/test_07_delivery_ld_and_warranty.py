"""Delivery accounting: dual-variant liquidated damages, tier/cap/grace
interplay, warranty window boundaries, and warranty rework disposition."""
from test_helpers import (
    COMM,
    OWNER,
    PM,
    ApiErrorId,
    assert_timestamp_instant,
    award_project,
    create_change_order,
    create_draft_project,
    add_base_work_item,
    file_warranty_claim,
    get_project,
    get_success_data,
    make_shipowner_rep_headers,
    set_clock,
    setup_delivered_project,
    setup_in_dock_project,
    start_item,
    complete_item,
    submit_bid,
    validate_error,
    validate_success,
)

# 100 x 600000 = 60000000 cents: tier-2 LD rate 500000/day.
LD_ITEM_14D = {
    "description": "Hull plate renewal", "trade_code": "HULL_STEEL",
    "duration_days": 14, "quantity": 100, "unit_price_cents": 600000,
}


class TestDualVariantLiquidatedDamages:
    def test_provisional_variant_prices_forecast_lateness(self, api):
        """PRD §3.7: "While the project has not yet been delivered, a
        forward-looking provisional variant runs against the calendar date of
        `forecast_delivery_utc` and is recomputed into `provisional_ld_cents`
        on every mutation that touches the contracted price, the forecast, or
        the tier rate."

        Design: Difficulty/dual_variant_calc/liquidated_damages_provisional_vs_final
        """
        ctx = setup_in_dock_project(item_specs=[LD_ITEM_14D])
        project = get_project(ctx["project"]["id"])
        assert_timestamp_instant(
            project["forecast_delivery_utc"], "2026-08-15T00:00:00"
        )
        assert project["provisional_ld_cents"] == 1000000, (
            f"Forecast 2026-08-15 vs contract 2026-08-10: 5 late days - 3 grace "
            f"= 2 chargeable x 500000 = 1000000, got "
            f"{project['provisional_ld_cents']}"
        )

    def test_final_variant_prices_actual_delivery_date(self, api):
        """PRD §3.7: "At the delivery transition, the final variant runs once
        against the calendar date of `delivered_at_utc`, and its result is
        frozen into `liquidated_damages_cents` while the provisional figure
        freezes at its last computed value."
        PRD §3.7: "Lateness is the number of whole calendar days between the
        delivery date and the `contract_delivery_date`, floored at zero for
        early or on-time delivery."

        Design: Difficulty/dual_variant_calc/liquidated_damages_provisional_vs_final
        """
        ctx = setup_in_dock_project(item_specs=[LD_ITEM_14D])
        mid = get_project(ctx["project"]["id"])
        assert mid["provisional_ld_cents"] == 1000000

        set_clock("2026-08-05T09:00:00Z")
        start_item(ctx["items"][0]["id"])
        complete_item(ctx["items"][0]["id"])
        delivered = validate_success(api.deliver_project(ctx["project"]["id"], PM))
        assert delivered["status"] == "DELIVERED"
        assert delivered["liquidated_damages_cents"] == 0, (
            f"Actual delivery 2026-08-05 is before the 2026-08-10 contract "
            f"date: late days floor at zero. The provisional variant priced "
            f"the same project at 1000000 from the forecast — the variants "
            f"differ only in their date source. Got "
            f"{delivered['liquidated_damages_cents']}"
        )


class TestTierCapGraceInterplay:
    def test_cap_binds_when_accrual_exceeds_ten_percent(self, api):
        """PRD §3.7: "The accrual is the chargeable days multiplied by the
        tier's daily rate, and the assessed damages are the lesser of that
        accrual and a cap of ten percent of the contracted price, the cap
        itself rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/liquidated_damages_tier_cap_grace_interplay
        """
        ctx = setup_in_dock_project(item_specs=[LD_ITEM_14D])
        set_clock("2026-10-10T09:00:00Z")
        start_item(ctx["items"][0]["id"])
        complete_item(ctx["items"][0]["id"])
        delivered = validate_success(api.deliver_project(ctx["project"]["id"], PM))
        assert delivered["ld_daily_rate_cents"] == 500000, (
            f"50000000 <= 60000000 <= 200000000 selects tier 2, got "
            f"{delivered['ld_daily_rate_cents']}"
        )
        assert delivered["liquidated_damages_cents"] == 6000000, (
            f"61 late days - 3 grace = 58 chargeable x 500000 = 29000000 "
            f"exceeds the 10% cap of 6000000; the nested min selects the cap. "
            f"Got {delivered['liquidated_damages_cents']}"
        )

    def test_accrual_below_cap_pays_in_full(self, api):
        """PRD §3.7: "The accrual is the chargeable days multiplied by the
        tier's daily rate, and the assessed damages are the lesser of that
        accrual and a cap of ten percent of the contracted price, the cap
        itself rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/liquidated_damages_tier_cap_grace_interplay
        """
        ctx = setup_in_dock_project(item_specs=[LD_ITEM_14D])
        set_clock("2026-08-18T09:00:00Z")
        start_item(ctx["items"][0]["id"])
        complete_item(ctx["items"][0]["id"])
        delivered = validate_success(api.deliver_project(ctx["project"]["id"], PM))
        assert delivered["liquidated_damages_cents"] == 2500000, (
            f"8 late days - 3 grace = 5 chargeable x 500000 = 2500000, below "
            f"the 6000000 cap, so the accrual branch pays in full. Got "
            f"{delivered['liquidated_damages_cents']}"
        )


class TestGraceBoundary:
    def test_delivery_exactly_three_days_late_accrues_nothing(self, api):
        """PRD §3.7: "The first three calendar days of lateness are grace days:
        chargeable days are the late days minus three, again floored at zero,
        so a delivery exactly three days late accrues nothing."

        Design: Difficulty/boundary_precision_check/delivery_exactly_at_grace_boundary_zero_ld
        """
        ctx = setup_delivered_project(
            item_specs=[LD_ITEM_14D], deliver_clock="2026-08-13T09:00:00Z"
        )
        assert ctx["project"]["status"] == "DELIVERED"
        assert ctx["project"]["liquidated_damages_cents"] == 0, (
            f"3 late days - 3 grace = 0 chargeable, got "
            f"{ctx['project']['liquidated_damages_cents']}"
        )

    def test_delivery_four_days_late_accrues_one_day(self, api):
        """PRD §3.7: "The first three calendar days of lateness are grace days:
        chargeable days are the late days minus three, again floored at zero,
        so a delivery exactly three days late accrues nothing."
        PRD §3.7: "The accrual is the chargeable days multiplied by the tier's
        daily rate"

        Design: Difficulty/boundary_precision_check/delivery_exactly_at_grace_boundary_zero_ld
        """
        ctx = setup_delivered_project(
            item_specs=[LD_ITEM_14D], deliver_clock="2026-08-14T09:00:00Z"
        )
        assert ctx["project"]["liquidated_damages_cents"] == 500000, (
            f"4 late days - 3 grace = 1 chargeable day x 500000 = 500000, got "
            f"{ctx['project']['liquidated_damages_cents']}"
        )


class TestTierBoundary:
    def test_ld_tier_boundary_exact_50m(self, api):
        """PRD §3.7: "A contracted price of at least 50000000 cents and at most
        200000000 cents ($2,000,000.00) selects 500000 cents per day
        ($5,000.00) — a contract priced at exactly 50000000 cents therefore
        falls in this middle tier."

        Design: Corner/calculations/ld_tier_boundary_exact_50m
        """
        ctx = setup_delivered_project(
            item_specs=[{
                "description": "Hull plate renewal", "trade_code": "HULL_STEEL",
                "duration_days": 5, "quantity": 100, "unit_price_cents": 500000,
            }],
            deliver_clock="2026-08-15T09:00:00Z",
        )
        project = ctx["project"]
        assert project["awarded_price_cents"] == 50000000
        assert project["ld_daily_rate_cents"] == 500000, (
            f"Exactly 50000000 selects tier 2, not tier 1's 200000, got "
            f"{project['ld_daily_rate_cents']}"
        )
        assert project["liquidated_damages_cents"] == 1000000, (
            f"(5 - 3) chargeable days x 500000 = 1000000; the 5000000 cap is "
            f"not binding. Got {project['liquidated_damages_cents']}"
        )


class TestDerivedFieldReconciliation:
    def test_provisional_ld_recomputed_on_schedule_delta(self, api):
        """PRD §3.4: "The forecast redelivery instant, `forecast_delivery_utc`,
        is then `actual_dock_in_utc` plus `critical_path_days` whole days plus
        the sum of `schedule_delta_days` across the project's `APPROVED` change
        orders"
        PRD §3.5: "Third, the change order's `schedule_delta_days` joins the
        approved-delta sum, so `forecast_delivery_utc` and
        `provisional_ld_cents` are recomputed."

        Design: Corner/cross_cutting_layers/provisional_ld_recomputed_on_schedule_delta
        """
        ctx = setup_in_dock_project(item_specs=[{
            "description": "Line 1", "trade_code": "HULL_STEEL",
            "duration_days": 3, "quantity": 100, "unit_price_cents": 600000,
        }])
        pre = get_project(ctx["project"]["id"])
        assert pre["provisional_ld_cents"] == 0, (
            "Forecast 2026-08-04 precedes the 2026-08-10 contract date"
        )
        assert_timestamp_instant(pre["forecast_delivery_utc"], "2026-08-04T00:00:00")

        co = create_change_order(
            ctx["project"]["id"],
            description="Growth with schedule impact", trade_code="HULL_STEEL",
            pricing_mode="LUMP_SUM", duration_days=1, schedule_delta_days=10,
            quantity=0.2, unit_price_cents=500000,
        )
        validate_success(api.approve_change_order(co["id"], COMM))

        post = get_project(ctx["project"]["id"])
        assert post["contracted_price_cents"] == 60100000
        assert_timestamp_instant(post["forecast_delivery_utc"], "2026-08-14T00:00:00")
        assert post["provisional_ld_cents"] == 500000, (
            f"2026-08-14 is 4 days late; 4 - 3 grace = 1 x 500000 = 500000, "
            f"got {post['provisional_ld_cents']}"
        )


class TestLifecycleGuards:
    def test_deliver_from_draft_returns_invalid_state(self, api):
        """PRD §3.7: "From `WORK_COMPLETE`, a `ProjectManager` delivers the
        vessel, moving the project to `DELIVERED`."
        PRD §2.9: "State preconditions: the generic check that the requested
        transition is defined from the target's current state
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/deliver_from_draft_returns_invalid_state
        """
        project = create_draft_project()
        resp = api.deliver_project(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_award_from_draft_returns_invalid_state(self, api):
        """PRD §3.3: "Award is a `CommercialApprover` act that moves a
        submitted project from `BID_SUBMITTED` to `CONTRACTED`, and it freezes
        commercial terms."
        PRD §2.9: "State preconditions: the generic check that the requested
        transition is defined from the target's current state
        (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/award_from_draft_returns_invalid_state
        """
        project = create_draft_project()
        add_base_work_item(project["id"], description="Line 1")
        resp = api.award_project(project["id"], COMM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWarrantyWindowSweep:
    def test_project_closes_after_warranty_end_sweep(self, api):
        """PRD §3.7: "Delivery stamps `delivered_at_utc` with the current
        logical time, runs the final liquidated-damages variant against the
        actual delivery date and freezes the result into
        `liquidated_damages_cents`, opens the warranty window by setting
        `warranty_end_utc` to the delivery instant plus `warranty_days`
        calendar days, freezes `provisional_ld_cents` at its last computed
        value, and increments the project's `version` by one."
        PRD §2.5: "Second, any repair project still in `DELIVERED` whose
        `warranty_end_utc` lies strictly before the new logical time
        transitions to the terminal `CLOSED` state, incrementing the project's
        `version` by one."

        Design: Corner/state_machines/project_closes_after_warranty_end_sweep
        """
        ctx = setup_delivered_project(deliver_clock="2026-08-05T09:00:00Z")
        project = ctx["project"]
        assert_timestamp_instant(project["warranty_end_utc"], "2026-11-03T09:00:00")

        set_clock("2026-11-03T09:00:00Z")
        at_end = get_project(project["id"])
        assert at_end["status"] == "DELIVERED", (
            "The sweep uses a strict comparison — exactly at warranty_end the "
            "project is not closed"
        )

        set_clock("2026-11-03T09:00:01Z")
        past = get_project(project["id"])
        assert past["status"] == "CLOSED", (
            "One second past the boundary the sweep closes the project"
        )


class TestWarrantyClaims:
    def test_warranty_claim_at_exact_window_end_allowed_then_expired(self, api):
        """PRD §3.8: "The project must be `DELIVERED` and the current logical
        time must be at or before `warranty_end_utc` — filing exactly at the
        window's end instant is allowed — or the filing is rejected with
        `ERR_WARRANTY_EXPIRED`."

        Design: Corner/errors/warranty_claim_at_exact_window_end_allowed_then_expired
        """
        ctx = setup_delivered_project(deliver_clock="2026-08-05T09:00:00Z")
        item_id = ctx["items"][0]["id"]

        set_clock("2026-11-03T09:00:00Z")
        claim = file_warranty_claim(
            ctx["project"]["id"], item_id,
            description="Filed exactly at warranty end",
        )
        assert claim["status"] == "FILED", "The filing boundary is inclusive"

        set_clock("2026-11-03T09:00:01Z")
        resp = api.create_warranty_claim(
            {
                "project_id": ctx["project"]["id"],
                "work_item_id": item_id,
                "description": "One second too late",
            },
            make_shipowner_rep_headers("owner_9"),
        )
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)

    def test_claim_item_from_other_project_returns_work_item_not_in_project(self, api):
        """PRD §3.8: "And the named work item must actually belong to the named
        project, or the filing is rejected with
        `ERR_WORK_ITEM_NOT_IN_PROJECT`."

        Design: Corner/errors/claim_item_from_other_project_returns_work_item_not_in_project
        """
        ctx1 = setup_delivered_project()
        ctx2 = setup_delivered_project()

        resp = api.create_warranty_claim(
            {
                "project_id": ctx2["project"]["id"],
                "work_item_id": ctx1["items"][0]["id"],
                "description": "Cross-project reference",
            },
            OWNER,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ITEM_NOT_IN_PROJECT)

    def test_warranty_accept_spawns_zero_priced_rework_and_auto_closes(self, api):
        """PRD §3.8: "Accepting a claim — supplying `rework_duration_days` for
        the repair — moves it from `FILED` to `ACCEPTED` and materialises a
        zero-priced rework work item: its `origin_kind` is `WARRANTY_REWORK`,
        its `line_total_cents` is zero, its `trade_code` and `description` are
        copied from the defective item, its `duration_days` takes the supplied
        rework duration, and the new item's id is recorded on the claim as
        `rework_work_item_id`. The yard absorbs rework cost, so the project's
        `contracted_price_cents` is unchanged."
        PRD §3.8: "When that rework item completes, the claim closes itself,
        moving from `ACCEPTED` to `CLOSED`."
        PRD §3.4: "a `WARRANTY_REWORK` line may start while its project is
        `DELIVERED`"

        Design: Corner/endpoints/warranty_accept_spawns_zero_priced_rework_and_auto_closes
        """
        ctx = setup_delivered_project(item_specs=[{
            "description": "Line 1", "trade_code": "PIPING", "duration_days": 1,
            "quantity": 1, "unit_price_cents": 100000,
        }])
        defective = ctx["items"][0]
        claim = file_warranty_claim(
            ctx["project"]["id"], defective["id"],
            description="Weld seam porosity found post-delivery",
        )

        accepted = validate_success(api.accept_warranty_claim(
            claim["id"], {"rework_duration_days": 2}, PM
        ))
        assert accepted["status"] == "ACCEPTED"
        rework_id = accepted["rework_work_item_id"]
        assert rework_id is not None

        rework = get_success_data(api.get_work_item(rework_id, PM))
        assert rework["origin_kind"] == "WARRANTY_REWORK"
        assert rework["line_total_cents"] == 0
        assert rework["trade_code"] == defective["trade_code"]
        assert rework["description"] == defective["description"]
        assert rework["duration_days"] == 2

        project_after_accept = get_project(ctx["project"]["id"])
        assert project_after_accept["contracted_price_cents"] == 100000, (
            "The yard absorbs rework cost — the contract price is unchanged"
        )

        start_item(rework_id)
        complete_item(rework_id)
        closed = get_success_data(api.get_warranty_claim(claim["id"], PM))
        assert closed["status"] == "CLOSED", (
            "The claim auto-closes exactly when its rework item completes"
        )
