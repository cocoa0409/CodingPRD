"""Grower accounts, credit lifecycle, payments, exposure, and ledger."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, CREDIT, grower_headers,
    create_grower, create_product, published_price_sheet,
    create_prepay_program, create_prepay_contract, fund_contract,
    setup_order_pipeline, setup_booked_order)

UREA_SPEC = {"name": "UREA 46-0-0", "analysis_n_pct": 46, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}
DAP_SPEC = {"name": "DAP 18-46-0", "analysis_n_pct": 18, "analysis_p2o5_pct": 46, "analysis_k2o_pct": 0}
MOP_SPEC = {"name": "MOP 0-0-60", "analysis_n_pct": 0, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 60}


class TestGrowerCreation:
    def test_grower_create_applies_defaults(self, api):
        """PRD 3.1: "The account opens with `credit_status` set to `ACTIVE`,
        `credit_used_cents`, `prepay_balance_cents`, and `season_closed_tons` all
        zero."
        PRD 2.4: "version, an integer that increments by exactly 1 on every mutation
        of that resource."

        Design: Corner/entities/grower_create_applies_defaults
        """
        resp = api.create_grower({"legal_name": "Default Check Farms", "credit_limit_cents": 750000}, CREDIT)
        data = validate_success(resp, 201)
        assert data["credit_status"] == "ACTIVE"
        assert data["credit_used_cents"] == 0
        assert data["prepay_balance_cents"] == 0
        assert data["season_closed_tons"] == 0
        assert data["version"] == 1

    def test_grower_missing_legal_name_returns_400(self, api):
        """PRD 2.7: "then request-body shape — required fields present, enum members
        valid, numeric ranges respected, unknown fields rejected — as
        `ERR_VALIDATION_FAILED`."

        Design: Corner/entities/grower_missing_required_legal_name_returns_400
        """
        resp = api.create_grower({"credit_limit_cents": 100000}, CREDIT)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


class TestGrowerVersion:
    def test_version_increments_on_each_mutation(self, api):
        """PRD 2.4: "Every persisted resource except the credit ledger carries four
        system-managed properties: ... and `version`, an integer that increments by
        exactly 1 on every mutation of that resource."
        PRD 3.1: "Every credit-state transition and every credit-terms update
        increments the account's `version`."

        Design: Corner/cross_cutting_layers/version_increments_on_each_mutation
        """
        grower = create_grower(legal_name="Version Farms", credit_limit_cents=100000)
        assert grower["version"] == 1
        r2 = get_success_data(api.update_credit_terms(grower["id"], {"credit_limit_cents": 200000}, CREDIT))
        assert r2["version"] == 2
        r3 = get_success_data(api.update_credit_terms(grower["id"], {"credit_limit_cents": 300000}, CREDIT))
        assert r3["version"] == 3


class TestBookingGateOnGrowerState:
    def test_booking_blocked_while_suspended_then_admitted_after_release(self, api):
        """PRD 3.1: "New financial commitments are gated on posture: signing a prepay
        contract, creating a blend order, and booking a blend order all require the
        grower's `credit_status` to be `ACTIVE`; otherwise the request is rejected
        with `ERR_GROWER_NOT_ORDERABLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_orderable_grower
        """
        ctx = setup_order_pipeline(
            legal_name="Suspend Me Farms",
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}])
        get_success_data(api.suspend_grower(ctx["grower"]["id"], CREDIT))

        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ORDERABLE)

        get_success_data(api.credit_release(ctx["grower"]["id"], CREDIT))
        booked = get_success_data(api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"])))
        assert booked["fulfillment_status"] == "BOOKED", \
            "the same order books once the grower's state flips"

    def test_booking_blocked_on_credit_hold(self, api):
        """PRD 3.1: "New financial commitments are gated on posture: signing a prepay
        contract, creating a blend order, and booking a blend order all require the
        grower's `credit_status` to be `ACTIVE`; otherwise the request is rejected
        with `ERR_GROWER_NOT_ORDERABLE` (HTTP 409)."
        PRD 3.1: "place an `ACTIVE` account on hold (`ACTIVE → CREDIT_HOLD`)."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_orderable_grower
        """
        ctx = setup_order_pipeline(
            legal_name="Hold Me Farms",
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}])
        get_success_data(api.credit_hold(ctx["grower"]["id"], CREDIT))
        resp = api.book_blend_order(ctx["order"]["id"], grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ORDERABLE)
        readback = get_success_data(api.get_blend_order(ctx["order"]["id"], CREDIT))
        assert readback["fulfillment_status"] == "QUOTED"


class TestExposureRead:
    def test_exposure_billed_vs_booked_variants(self, api):
        """PRD 3.1: "A computed exposure read reports the grower's posture under both
        credit lenses: `billed_balance_cents` (identical to `credit_used_cents`),
        `booked_exposure_cents` (the sum of `provisional_total_cents` over the
        grower's orders with `fulfillment_status` in `BOOKED` or `SCHEDULED` and
        `payment_status` other than `CANCELLED`), `exposure_balance_cents` (their
        sum), plus the account's `credit_limit_cents` and the derived
        `available_credit_cents`."

        Design: Difficulty/dual_variant_calc/grower_credit_exposure_vs_billed_balance
        """
        ctx = setup_booked_order(
            legal_name="Maple Line Farms",
            credit_limit_cents=5_000_000,
            field_name="Creek Field",
            products=[UREA_SPEC, DAP_SPEC, MOP_SPEC],
            prices={"UREA 46-0-0": 52000, "DAP 18-46-0": 61000, "MOP 0-0-60": 44500},
            lots={"UREA 46-0-0": 20, "DAP 18-46-0": 20, "MOP 0-0-60": 20},
            lines=[
                {"product_id": "DAP 18-46-0", "target_rate_lbs_per_acre": 332.6},
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 365.0},
                {"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1},
            ])
        data = validate_success(api.get_exposure(ctx["grower"]["id"], CREDIT))
        # provisional = 8.315*61000 + 9.125*44500 + 8.703*52000 = 507215+406063+452556
        assert data["billed_balance_cents"] == 0, "BILLED variant: nothing invoiced yet"
        assert data["booked_exposure_cents"] == 1365834
        assert data["exposure_balance_cents"] == 1365834
        assert data["available_credit_cents"] == 5_000_000 - 1365834
        assert data["billed_balance_cents"] != data["exposure_balance_cents"], \
            "two sanctioned variants of the same credit posture differ"

    def test_exposure_available_credit_derived(self, api):
        """PRD 3.1: "A computed exposure read reports the grower's posture under both
        credit lenses: `billed_balance_cents` (identical to `credit_used_cents`),
        `booked_exposure_cents` (the sum of `provisional_total_cents` over the
        grower's orders with `fulfillment_status` in `BOOKED` or `SCHEDULED` and
        `payment_status` other than `CANCELLED`), `exposure_balance_cents` (their
        sum), plus the account's `credit_limit_cents` and the derived
        `available_credit_cents`."

        Design: Difficulty/dual_variant_calc/grower_credit_exposure_vs_billed_balance
        """
        ctx = setup_booked_order(
            legal_name="Maple Line Farms 2",
            credit_limit_cents=5_000_000,
            products=[UREA_SPEC, DAP_SPEC, MOP_SPEC],
            prices={"UREA 46-0-0": 52000, "DAP 18-46-0": 61000, "MOP 0-0-60": 44500},
            lots={"UREA 46-0-0": 20, "DAP 18-46-0": 20, "MOP 0-0-60": 20},
            lines=[
                {"product_id": "DAP 18-46-0", "target_rate_lbs_per_acre": 332.6},
                {"product_id": "MOP 0-0-60", "target_rate_lbs_per_acre": 365.0},
                {"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1},
            ])
        data = validate_success(api.get_exposure(ctx["grower"]["id"], CREDIT))
        assert data["credit_limit_cents"] == 5_000_000
        assert data["available_credit_cents"] == data["credit_limit_cents"] - data["exposure_balance_cents"]
        assert data["exposure_balance_cents"] == data["billed_balance_cents"] + data["booked_exposure_cents"]

    def test_exposure_booked_component_tracks_order_lifecycle(self, api):
        """PRD 3.1: "`booked_exposure_cents` (the sum of `provisional_total_cents`
        over the grower's orders with `fulfillment_status` in `BOOKED` or `SCHEDULED`
        and `payment_status` other than `CANCELLED`)."

        Design: Corner/calculations/exposure_input_set_excludes_quoted_and_cancelled
        """
        ctx = setup_order_pipeline(
            legal_name="Filter Farms",
            products=[UREA_SPEC],
            prices={"UREA 46-0-0": 52000},
            lots={"UREA 46-0-0": 20},
            lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}])
        order_id = ctx["order"]["id"]
        gh = grower_headers(ctx["grower"])

        e1 = validate_success(api.get_exposure(ctx["grower"]["id"], CREDIT))
        assert e1["booked_exposure_cents"] == 0, "QUOTED excluded from the exposure input set"

        get_success_data(api.book_blend_order(order_id, gh))
        e2 = validate_success(api.get_exposure(ctx["grower"]["id"], CREDIT))
        assert e2["booked_exposure_cents"] == 452556, "BOOKED included"

        get_success_data(api.cancel_blend_order(order_id, gh))
        e3 = validate_success(api.get_exposure(ctx["grower"]["id"], CREDIT))
        assert e3["booked_exposure_cents"] == 0, "CANCELLED excluded again"


class TestOverpayment:
    def test_overpayment_rejected_and_no_ledger_entry(self, api):
        """PRD 3.1: "If the payment exceeds the total outstanding across all
        `INVOICED` orders, the entire payment is rejected with `ERR_OVERPAYMENT`
        (HTTP 422); no partial application is kept."

        Design: Corner/errors/error_overpayment_trigger
        """
        grower = create_grower(legal_name="Overpay Farms", credit_limit_cents=1_000_000)
        resp = api.post_payment(grower["id"], {"amount_cents": 1000}, CREDIT)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

        ledger, meta = validate_paginated(api.list_credit_ledger(grower["id"], CREDIT))
        assert meta["total_count"] == 0, "no ledger entry appended"


class TestLedgerEntryShape:
    def test_ledger_entry_immutable_no_version(self, api):
        """PRD 2.4: "The `CreditLedgerEntry` resource is the single exception: as an
        append-only journal it carries only `id` and `created_at`; both `updated_at`
        and `version` are absent from it."
        PRD 2.10: "Each entry records its `grower_id`, an `entry_type` drawn from
        `PREPAY_FUNDED`, `PREPAY_DRAWN`, `PREPAY_FORFEITED`, `PREPAY_REFUNDED`,
        `INVOICE_POSTED`, `PAYMENT_RECEIVED`, and `REBATE_CREDIT`; a signed
        `amount_cents` (funding and invoices positive; payments, rebates, draws,
        forfeits, and refunds negative); the `reference_id` of the originating blend
        order or prepay contract; and two snapshots —
        `resulting_credit_used_cents` and `resulting_prepay_balance_cents` —
        capturing the grower's derived balances immediately after that entry."

        Design: Corner/entities/credit_ledger_entry_immutable_no_version
        """
        grower = create_grower(legal_name="Ledger View Farms", credit_limit_cents=1_000_000)
        mop = create_product("MOP 0-0-60", 0, 0, 60)
        published_price_sheet(mop["id"], 44500)
        program = create_prepay_program()
        contract = create_prepay_contract(grower, program["id"], mop["id"], committed_tons=20)
        fund_contract(contract["id"], 100000)

        ledger, meta = validate_paginated(api.list_credit_ledger(grower["id"], CREDIT))
        assert meta["total_count"] >= 1
        entry = ledger[0]
        assert entry["entry_type"] == "PREPAY_FUNDED"
        assert entry["amount_cents"] == 100000
        assert entry["resulting_credit_used_cents"] == 0
        assert entry["resulting_prepay_balance_cents"] == 100000
        assert "id" in entry and "created_at" in entry
        assert "version" not in entry, "append-only journal must not expose version"
        assert "updated_at" not in entry, "append-only journal must not expose updated_at"


class TestGrowersPagination:
    def test_growers_list_pagination_fields(self, api):
        """PRD 2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object."

        Design: Corner/endpoints/growers_list_pagination_fields
        """
        for i in (1, 2, 3):
            create_grower(legal_name=f"Page Farm {i}", credit_limit_cents=100000)

        page1, meta1 = validate_paginated(api.list_growers(CREDIT, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_growers(CREDIT, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
