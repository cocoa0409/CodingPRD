"""Blend order creation, booking gates, and lifecycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, AGRON, COMPLIANCE, CREDIT, PLANT, ADMIN,
    grower_headers,
    create_grower, create_field, resulted_soil_test, create_recommendation,
    approved_recommendation, create_product,
    published_price_sheet, active_permit, receive_lot, create_blend_order,
    setup_order_pipeline, setup_booked_order)

UREA_SPEC = {"name": "UREA 46-0-0", "analysis_n_pct": 46, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}
DAP_SPEC = {"name": "DAP 18-46-0", "analysis_n_pct": 18, "analysis_p2o5_pct": 46, "analysis_k2o_pct": 0}
MOP_SPEC = {"name": "MOP 0-0-60", "analysis_n_pct": 0, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 60}
UREA_LINE = [{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}]


def _urea_ctx(api, **kwargs):
    kwargs.setdefault("products", [UREA_SPEC])
    kwargs.setdefault("prices", {"UREA 46-0-0": 52000})
    return setup_order_pipeline(**kwargs)


class TestOrderInitialState:
    def test_order_created_with_initial_dims(self, api):
        """PRD 3.5: "A blend order is created under a grower by the owning `Grower`,
        an `Agronomist`, or a `BranchAdmin`, in the combined initial state
        `fulfillment_status` of `QUOTED` and `payment_status` of `UNPAID` — two
        independent state dimensions that evolve in parallel."
        PRD 3.5: "Until batch completion, `final_total_cents`, `rebate_cents` (which
        initializes at zero), and `invoiced_at` remain unset on the order."

        Design: Corner/state_machines/blend_order_created_with_initial_dims
        """
        ctx = _urea_ctx(api, legal_name="Init State Farms", lines=UREA_LINE)
        order = ctx["order"]
        assert order["fulfillment_status"] == "QUOTED"
        assert order["payment_status"] == "UNPAID"
        assert order["rebate_cents"] == 0
        assert order["final_total_cents"] is None


class TestPerLineRoundingOrder:
    def test_per_line_then_sum_rounding_pinned(self, api):
        """PRD 3.5: "The order's `provisional_total_cents` obeys a pinned rounding
        order: each line is rounded to whole cents first, and the total is the exact
        integer sum of those rounded line amounts — the alternative sum-then-round
        order is not used, since it can differ by cents when multiple lines carry
        fractional cents."

        Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_order
        """
        ctx = setup_order_pipeline(
            legal_name="Rounding Test Co",
            products=[MOP_SPEC, {"name": "AMS 21-0-0", "analysis_n_pct": 21, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}],
            prices={"MOP 0-0-60": 44500, "AMS 21-0-0": 40100},
            lines=[
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 5.0},
                {"product_id": "AMS 21-0-0", "target_rate_lbs_per_acre": 5.0},
            ])
        order = ctx["order"]
        # per-line: round(0.125*44500)=5563, round(0.125*40100)=5013, sum 10576
        assert order["provisional_total_cents"] == 10576
        assert order["provisional_total_cents"] != 10575, \
            "the forbidden sum-then-round order would yield 10575"

        lines, _ = validate_paginated(api.list_order_lines(order["id"], PLANT))
        line_amounts = sorted(ln["line_provisional_cents"] for ln in lines)
        assert line_amounts == [5013, 5563]

    def test_line_provisional_amounts_rounded_before_sum(self, api):
        """PRD 3.5: "The `line_provisional_cents` is the `quantity_tons` multiplied
        by the `unit_price_cents`, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_order
        """
        ctx = setup_order_pipeline(
            legal_name="Rounding Test Co 2",
            products=[MOP_SPEC, {"name": "AMS 21-0-0", "analysis_n_pct": 21, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}],
            prices={"MOP 0-0-60": 44500, "AMS 21-0-0": 40100},
            lines=[
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 5.0},
                {"product_id": "AMS 21-0-0", "target_rate_lbs_per_acre": 5.0},
            ])
        lines, _ = validate_paginated(api.list_order_lines(ctx["order"]["id"], PLANT))
        by_product = {ln["product_id"]: ln for ln in lines}
        mop_line = by_product[ctx["products"]["MOP 0-0-60"]["id"]]
        ams_line = by_product[ctx["products"]["AMS 21-0-0"]["id"]]
        assert mop_line["line_provisional_cents"] == 5563, "round_half_up(0.125 x 44500)"
        assert ams_line["line_provisional_cents"] == 5013, "round_half_up(0.125 x 40100)"


class TestBookingNMPLifecycleGate:
    def test_booking_blocked_while_plan_submitted_then_admitted_after_approval(self, api):
        """PRD 3.3: "While a field's current-crop-year plan is suspended or expired —
        or simply absent or unapproved — booking a blend order on that field fails
        with `ERR_NMP_REQUIRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_approved_nmp
        """
        ctx = setup_order_pipeline(
            legal_name="Gate Farms",
            approve_nmp=False,
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=UREA_LINE)
        assert ctx["nmp"]["status"] == "SUBMITTED"

        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_NMP_REQUIRED)

        get_success_data(api.approve_nutrient_plan(ctx["nmp"]["id"], COMPLIANCE))
        booked = get_success_data(api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"])))
        assert booked["payment_status"] == "CREDIT_APPROVED"
        assert booked["fulfillment_status"] == "BOOKED", \
            "identical order, flip driven purely by the other entity's state"

    def test_booking_blocked_without_any_plan(self, api):
        """PRD 3.3: "While a field's current-crop-year plan is suspended or expired —
        or simply absent or unapproved — booking a blend order on that field fails
        with `ERR_NMP_REQUIRED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_approved_nmp
        """
        # Build a pipeline manually with no NMP at all
        grower = create_grower(legal_name="No Plan Farms")
        field = create_field(grower, name="NP Field", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = approved_recommendation(st["id"])
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        published_price_sheet(urea["id"], 52000)
        active_permit("FERTILIZER_STORAGE")
        receive_lot(urea["id"], 20)
        order = create_blend_order(
            grower, field["id"], rec["id"], 50,
            [{"product_id": urea["id"], "target_rate_lbs_per_acre": 348.1}])
        resp = api.book_blend_order(order["id"], grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_NMP_REQUIRED)


class TestNMPSuspendReinstate:
    def test_suspend_blocks_then_reinstate_admits(self, api):
        """PRD 3.3: "An approved plan may be suspended (`APPROVED → SUSPENDED`) and
        later reinstated (`SUSPENDED → APPROVED`) by a compliance officer."
        PRD 3.3: "While a field's current-crop-year plan is suspended or expired —
        or simply absent or unapproved — booking a blend order on that field fails
        with `ERR_NMP_REQUIRED` (HTTP 422)."

        Design: Corner/state_machines/nmp_suspend_blocks_then_reinstate_admits
        """
        ctx = setup_order_pipeline(
            legal_name="Reinstate Farms",
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=UREA_LINE)
        get_success_data(api.suspend_nutrient_plan(ctx["nmp"]["id"], COMPLIANCE))
        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_NMP_REQUIRED)

        get_success_data(api.reinstate_nutrient_plan(ctx["nmp"]["id"], COMPLIANCE))
        booked = get_success_data(api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"])))
        assert booked["fulfillment_status"] == "BOOKED"


class TestNitrogenCapBoundary:
    def test_cap_exact_equality_admitted_excess_rejected(self, api):
        """PRD 3.5: "the cumulative nitrogen per acre across the field's
        booked-or-later, non-cancelled orders — fulfillment states `BOOKED`,
        `SCHEDULED`, `BATCHED`, `LOADED`, `DELIVERED`, `APPLIED_CONFIRMED`, and
        `CLOSED` — plus this order's `n_lbs_per_acre` does not exceed the plan's
        `n_cap_lbs_per_acre`, with exact equality admitted and any excess rejected
        as `ERR_NITROGEN_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/nitrogen_cap_exact_equality_admitted
        """
        ctx = setup_order_pipeline(
            legal_name="Cap Boundary Farms",
            n_cap_lbs_per_acre=276,
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20})
        grower, field, rec = ctx["grower"], ctx["field"], ctx["recommendation"]
        gh = grower_headers(grower)
        urea_id = ctx["products"]["UREA 46-0-0"]["id"]

        order_a = create_blend_order(grower, field["id"], rec["id"], 50,
                                     [{"product_id": urea_id, "target_rate_lbs_per_acre": 500.0}])
        booked_a = get_success_data(api.book_blend_order(order_a["id"], gh))
        assert booked_a["payment_status"] == "CREDIT_APPROVED"

        # 100.0 x 0.46 = 46.000 exactly; cumulative 230.000 + 46.000 == 276 == cap
        order_b = create_blend_order(grower, field["id"], rec["id"], 50,
                                     [{"product_id": urea_id, "target_rate_lbs_per_acre": 100.0}])
        assert order_b["n_lbs_per_acre"] == pytest.approx(46.000, abs=1e-9)
        booked_b = get_success_data(api.book_blend_order(order_b["id"], gh))
        assert booked_b["payment_status"] == "CREDIT_APPROVED", \
            "cumulative 230.000 + 46.000 == 276.000 == cap: equality ADMITTED"

        order_c = create_blend_order(grower, field["id"], rec["id"], 50,
                                     [{"product_id": urea_id, "target_rate_lbs_per_acre": 100.1}])
        assert order_c["n_lbs_per_acre"] == pytest.approx(46.046, abs=1e-9)
        resp = api.book_blend_order(order_c["id"], gh)
        validate_error(resp, ApiErrorId.ERR_NITROGEN_CAP_EXCEEDED)
        readback = get_success_data(api.get_blend_order(order_c["id"], CREDIT))
        assert readback["fulfillment_status"] == "QUOTED"


    def test_cap_equality_boundary_quantum(self, api):
        """PRD 3.5: "The order's ... `n_lbs_per_acre` is the sum over lines of each
        line's target rate multiplied by the product's `analysis_n_pct` fraction,
        each contribution rounded half-up to three decimals."
        PRD 3.5: "with exact equality admitted and any excess rejected as
        `ERR_NITROGEN_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/nitrogen_cap_exact_equality_admitted
        """
        ctx = setup_order_pipeline(
            legal_name="Cap Boundary Farms 2",
            n_cap_lbs_per_acre=276,
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20})
        urea_id = ctx["products"]["UREA 46-0-0"]["id"]
        gh = grower_headers(ctx["grower"])
        first = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [{"product_id": urea_id, "target_rate_lbs_per_acre": 500.0}])
        get_success_data(api.book_blend_order(first["id"], gh))
        # 100.0 x 0.46 = 46.000 exactly at three decimals; 230.000 + 46.000 == 276 == cap
        order = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [{"product_id": urea_id, "target_rate_lbs_per_acre": 100.0}])
        assert order["n_lbs_per_acre"] == pytest.approx(46.000, abs=1e-9)
        booked = get_success_data(api.book_blend_order(order["id"], gh))
        assert booked["fulfillment_status"] == "BOOKED", \
            "cumulative 230.000 + 46.000 == 276.000 == cap: equality ADMITTED"


class TestPhosphorusRestriction:
    def test_phosphorus_restriction_conditional_on_zone_and_soil(self, api):
        """PRD 3.3: "Approval is the moment the phosphorus restriction is computed:
        `p_restriction_active` becomes true when the field's `watershed_zone` is
        `PROTECTED` or `CRITICAL` and the field's latest `RESULTED` soil test shows
        `p_ppm` of at least the drawdown threshold of 40 ppm."
        PRD 3.5: "when the plan's `p_restriction_active` is true, no line product
        may carry an `analysis_p2o5_pct` above zero, else `ERR_PHOSPHORUS_RESTRICTED`."

        Design: Corner/validations/phosphorus_restriction_conditional_on_zone_and_soil
        """
        ctx = setup_order_pipeline(
            legal_name="Restricted Farms",
            field_name="Wetland Edge",
            watershed_zone="PROTECTED",
            p_ppm=50, k_ppm=90, ph=6.4,
            recommendation_overrides={"rate_variant": "MAINTENANCE_RATE"},
            products=[UREA_SPEC, DAP_SPEC],
            prices={"UREA 46-0-0": 52000, "DAP 18-46-0": 61000},
            lots={"UREA 46-0-0": 20, "DAP 18-46-0": 20})
        assert ctx["nmp"]["p_restriction_active"] is True, \
            "PROTECTED zone + p 50 >= 40 at approval"

        order = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [
                {"product_id": ctx["products"]["DAP 18-46-0"]["id"], "target_rate_lbs_per_acre": 100.0},
                {"product_id": ctx["products"]["UREA 46-0-0"]["id"], "target_rate_lbs_per_acre": 348.1},
            ])
        resp = api.book_blend_order(order["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_PHOSPHORUS_RESTRICTED)
        readback = get_success_data(api.get_blend_order(order["id"], CREDIT))
        assert readback["fulfillment_status"] == "QUOTED"


class TestRecommendationReferentialGates:
    def test_field_mismatch_rejected(self, api):
        """PRD 3.5: "The recommendation must belong to the same field and the field
        to the path grower, else `ERR_RECOMMENDATION_FIELD_MISMATCH`."

        Design: Corner/validations/recommendation_field_mismatch_rejected
        """
        grower = create_grower(legal_name="Mismatch Farms", credit_limit_cents=1_000_000)
        field_a = create_field(grower, name="Field A", acres=50)
        field_b = create_field(grower, name="Field B", acres=50)
        st = resulted_soil_test(field_a["id"], grower)
        rec = approved_recommendation(st["id"])
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        published_price_sheet(urea["id"], 52000)

        resp = api.create_blend_order(
            grower["id"],
            {
                "field_id": field_b["id"],
                "recommendation_id": rec["id"],
                "acres": 50,
                "price_mode": "FLOATING",
                "lines": [{"product_id": urea["id"], "target_rate_lbs_per_acre": 348.1}],
            },
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_RECOMMENDATION_FIELD_MISMATCH)

    def test_superseded_recommendation_blocks_order_create(self, api):
        """PRD 3.2: "referencing a `SUPERSEDED` recommendation fails with
        `ERR_RECOMMENDATION_SUPERSEDED`."

        Design: Corner/validations/superseded_recommendation_blocks_order_create
        """
        grower = create_grower(legal_name="Supersede Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="SS Field", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = approved_recommendation(st["id"])
        get_success_data(api.supersede_recommendation(rec["id"], AGRON))
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        published_price_sheet(urea["id"], 52000)

        resp = api.create_blend_order(
            grower["id"],
            {
                "field_id": field["id"],
                "recommendation_id": rec["id"],
                "acres": 50,
                "price_mode": "FLOATING",
                "lines": [{"product_id": urea["id"], "target_rate_lbs_per_acre": 348.1}],
            },
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_RECOMMENDATION_SUPERSEDED)

    def test_draft_recommendation_rejected_at_create(self, api):
        """PRD 3.2: "referencing one still in `DRAFT` or `PENDING_REVIEW` fails with
        `ERR_RECOMMENDATION_NOT_APPROVED`."

        Design: Corner/errors/error_recommendation_not_approved_trigger
        """
        grower = create_grower(legal_name="Draft Rec Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="DR Field", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = create_recommendation(st["id"])  # stays DRAFT
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        published_price_sheet(urea["id"], 52000)

        resp = api.create_blend_order(
            grower["id"],
            {
                "field_id": field["id"],
                "recommendation_id": rec["id"],
                "acres": 50,
                "price_mode": "FLOATING",
                "lines": [{"product_id": urea["id"], "target_rate_lbs_per_acre": 348.1}],
            },
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_RECOMMENDATION_NOT_APPROVED)

    def test_expired_recommendation_rejected_at_create(self, api):
        """PRD 3.2: "Expiry is lazy: whenever the recommendation is read or referenced
        and the logical clock has passed `valid_until`, it is treated as `EXPIRED`, a
        terminal state alongside `SUPERSEDED`. From that point, order creation or
        booking referencing it fails with `ERR_RECOMMENDATION_EXPIRED`."

        Design: Corner/errors/error_recommendation_expired_trigger
        """
        grower = create_grower(legal_name="Expired Rec Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="ER Field", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = approved_recommendation(st["id"], valid_until="2026-08-05T00:00:00Z")
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        published_price_sheet(urea["id"], 52000)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-06T00:00:00Z"}, ADMIN))

        resp = api.create_blend_order(
            grower["id"],
            {
                "field_id": field["id"],
                "recommendation_id": rec["id"],
                "acres": 50,
                "price_mode": "FLOATING",
                "lines": [{"product_id": urea["id"], "target_rate_lbs_per_acre": 348.1}],
            },
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_RECOMMENDATION_EXPIRED)
        readback = get_success_data(api.get_recommendation(rec["id"], AGRON))
        assert readback["status"] == "EXPIRED", "lazy transition observable"


class TestPriceAvailabilityGate:
    def test_quote_without_current_price_returns_422(self, api):
        """PRD 3.4: "When no sheet qualifies at a pricing moment — order quoting,
        requoting, patching, prepay signing, or final pricing of floating lines at
        batch completion — the operation fails with `ERR_NO_CURRENT_PRICE`
        (HTTP 422)."

        Design: Corner/validations/quote_without_current_price_returns_422
        """
        grower = create_grower(legal_name="No Price Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="NP Field", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = approved_recommendation(st["id"])
        urea = create_product("UREA 46-0-0", 46, 0, 0)  # no price sheet at all

        resp = api.create_blend_order(
            grower["id"],
            {
                "field_id": field["id"],
                "recommendation_id": rec["id"],
                "acres": 50,
                "price_mode": "FLOATING",
                "lines": [{"product_id": urea["id"], "target_rate_lbs_per_acre": 348.1}],
            },
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_NO_CURRENT_PRICE)

    def test_price_sheet_lazy_expiry_at_window_end(self, api):
        """PRD 3.4: "A `PUBLISHED` sheet may be manually expired (`→ EXPIRED`) by a
        branch admin, and is lazily treated as `EXPIRED` once the clock reaches
        `effective_to`."
        PRD 3.4: "The current price of a product at any instant is the `PUBLISHED`
        sheet whose window contains that instant — `effective_from` at or before the
        instant and `effective_to` strictly after it."

        Design: Corner/cross_cutting_layers/price_sheet_lazy_expiry_at_window_end
        """
        grower = create_grower(legal_name="Window End Farms", credit_limit_cents=1_000_000)
        field = create_field(grower, name="WE Field", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = approved_recommendation(st["id"])
        urea = create_product("UREA 46-0-0", 46, 0, 0)
        sheet = published_price_sheet(
            urea["id"], 52000,
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-10T00:00:00Z")
        get_success_data(api.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, ADMIN))

        resp = api.create_blend_order(
            grower["id"],
            {
                "field_id": field["id"],
                "recommendation_id": rec["id"],
                "acres": 50,
                "price_mode": "FLOATING",
                "lines": [{"product_id": urea["id"], "target_rate_lbs_per_acre": 348.1}],
            },
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_NO_CURRENT_PRICE)
        readback = get_success_data(api.get_price_sheet(sheet["id"], ADMIN))
        assert readback["status"] == "EXPIRED", "lazy evaluation observable"


class TestCreditLimitGate:
    def test_credit_limit_exceeded_on_floating_booking(self, api):
        """PRD 3.5: "for a `FLOATING` order the fiscal gate — the grower's
        `exposure_balance_cents` plus this order's `provisional_total_cents` must not
        exceed `credit_limit_cents`, equality admitted, excess rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/errors/error_credit_limit_exceeded_trigger
        """
        ctx = setup_order_pipeline(
            legal_name="Over Limit Farms",
            credit_limit_cents=1_000_000,
            products=[UREA_SPEC, DAP_SPEC, MOP_SPEC],
            prices={"UREA 46-0-0": 52000, "DAP 18-46-0": 61000, "MOP 0-0-60": 44500},
            lots={"UREA 46-0-0": 20, "DAP 18-46-0": 20, "MOP 0-0-60": 20},
            lines=[
                {"product_id": "DAP 18-46-0", "target_rate_lbs_per_acre": 332.6},
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 365.0},
                {"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1},
            ])
        assert ctx["order"]["provisional_total_cents"] == 1365834
        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestInsufficientInventory:
    def test_insufficient_inventory_no_partial_reservation(self, api):
        """PRD 3.5: "When the total available across a product's lots falls short of
        a line's need, booking fails with `ERR_INSUFFICIENT_INVENTORY` and no partial
        reservation is kept."

        Design: Corner/errors/error_insufficient_inventory_trigger
        """
        ctx = setup_order_pipeline(
            legal_name="Short Stock Farms",
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 10})
        order = create_blend_order(
            ctx["grower"], ctx["field"]["id"], ctx["recommendation"]["id"], 50,
            [{"product_id": ctx["products"]["UREA 46-0-0"]["id"], "target_rate_lbs_per_acre": 500.0}])
        resp = api.book_blend_order(order["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

        pos = validate_success(api.get_inventory_position(ctx["products"]["UREA 46-0-0"]["id"], PLANT))
        assert pos["reserved_tons"] == 0, "no partial reservation leaked"


class TestBookTwiceAndTerminalLockdown:
    def test_book_twice_rejected_reservation_not_doubled(self, api):
        """PRD 3.5: "Any transition fired from an ineligible state is
        `ERR_INVALID_TRANSITION`."
        PRD 3.5: "A successful booking reserves inventory FIFO: for each line, the
        system walks the product's lots ordered by `received_at` ascending with
        `created_at` ascending as tie-break, taking from each lot the lesser of the
        remaining need and the lot's available tonnage until the line's
        `quantity_tons` is fully allocated, adding each allocation to that lot's
        `reserved_tons`."

        Design: Corner/state_machines/order_book_twice_rejected
        """
        ctx = setup_booked_order(
            legal_name="Twice Book Farms",
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=UREA_LINE)
        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)

        pos = validate_success(api.get_inventory_position(ctx["products"]["UREA 46-0-0"]["id"], PLANT))
        assert pos["reserved_tons"] == pytest.approx(8.703, abs=1e-9), \
            "reservation NOT doubled by the rejected second book"

    def test_cancelled_order_terminal_lockdown(self, api):
        """PRD 3.8: "Both terminal fulfillment states are `CLOSED` and `CANCELLED`."
        PRD 3.5: "Any transition fired from an ineligible state is
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/cancelled_order_terminal_lockdown
        """
        ctx = setup_order_pipeline(
            legal_name="Lockdown Farms",
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lines=UREA_LINE)
        cancelled = get_success_data(
            api.cancel_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]), payload={"reason": "changed plans"})
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"

        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


class TestMissingOrderBook:
    def test_missing_order_book_returns_404_not_409(self, api):
        """PRD 2.7: "Authentication comes first ... then authorization ..., then
        path-resource existence validated left-to-right (`ERR_RESOURCE_NOT_FOUND`),
        ... Only after those five layers come optimistic-concurrency checks
        (`ERR_STALE_VERSION`), state-transition legality (`ERR_INVALID_TRANSITION`)."

        Design: Corner/validations/missing_order_book_returns_404_not_409
        """
        resp = api.book_blend_order(NON_EXISTENT_UUID, AGRON)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


class TestPriorityPairOnBooking:
    def test_grower_state_beats_credit_fiscal_on_booking(self, api):
        """PRD 2.7: "Only after those five layers come optimistic-concurrency checks
        (`ERR_STALE_VERSION`), state-transition legality (`ERR_INVALID_TRANSITION`),
        and then the business rules in their own documented order: the
        grower-orderable gate, equipment-availability gates, nutrient-plan presence,
        nitrogen cap, phosphorus restriction, permit gates, storage capacity,
        price-window overlap, blender-window conflicts, funding deadlines,
        current-price availability, recommendation expiry, formulation feasibility,
        batch variance, truck capacity, duplicate routes, inventory sufficiency,
        blender form coverage, and finally the referential and fiscal checks —
        recommendation approval state, recommendation-to-field ownership,
        recommendation supersession, prepay-contract matching, contract-in-use,
        program enrollment, credit limits, overpayment, and overfunding."

        Design: Difficulty/priority_pair_validation_conflict/grower_state_beats_credit_fiscal_on_booking
        """
        ctx = setup_order_pipeline(
            legal_name="Tight Credit Farms",
            credit_limit_cents=1_000_000,
            products=[UREA_SPEC, DAP_SPEC, MOP_SPEC],
            prices={"UREA 46-0-0": 52000, "DAP 18-46-0": 61000, "MOP 0-0-60": 44500},
            lines=[
                {"product_id": "DAP 18-46-0", "target_rate_lbs_per_acre": 332.6},
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 365.0},
                {"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1},
            ])
        assert ctx["order"]["provisional_total_cents"] == 1365834, \
            "provisional exceeds the 1000000 limit, so the fiscal gate also fails"
        get_success_data(api.credit_hold(ctx["grower"]["id"], CREDIT))

        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ORDERABLE)

        readback = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        assert readback["fulfillment_status"] == "QUOTED"
        assert readback["payment_status"] == "UNPAID", "no partial side effects"

    def test_fiscal_gate_reports_credit_error_when_grower_active(self, api):
        """PRD 2.7: "...and finally the referential and fiscal checks —
        recommendation approval state, recommendation-to-field ownership,
        recommendation supersession, prepay-contract matching, contract-in-use,
        program enrollment, credit limits, overpayment, and overfunding."
        PRD 3.5: "for a `FLOATING` order the fiscal gate — the grower's
        `exposure_balance_cents` plus this order's `provisional_total_cents` must not
        exceed `credit_limit_cents`, equality admitted, excess rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/grower_state_beats_credit_fiscal_on_booking
        """
        # Same double-fail shape as the paired test, but with the grower ACTIVE so
        # only the fiscal gate can fire — confirming the fiscal error id is the one
        # the state error masked in the paired scenario. Inventory is fully stocked
        # so the earlier per-line sufficiency gate (PRD 3.5 ordering) cannot fire.
        ctx = setup_order_pipeline(
            legal_name="Tight Credit Farms 2",
            credit_limit_cents=1_000_000,
            products=[UREA_SPEC, DAP_SPEC, MOP_SPEC],
            prices={"UREA 46-0-0": 52000, "DAP 18-46-0": 61000, "MOP 0-0-60": 44500},
            lots={"UREA 46-0-0": 20, "DAP 18-46-0": 20, "MOP 0-0-60": 20},
            lines=[
                {"product_id": "DAP 18-46-0", "target_rate_lbs_per_acre": 332.6},
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 365.0},
                {"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1},
            ])
        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
