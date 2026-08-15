"""Seasonal prepay: programs, contracts, funding, settlement, and OCC."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, CREDIT, ADMIN, grower_headers,
    create_grower, create_product, published_price_sheet, create_prepay_program,
    create_prepay_contract, fund_contract, active_permit, receive_lot,
    setup_order_pipeline, book_order)

MOP_SPEC = {"name": "MOP 0-0-60", "analysis_n_pct": 0, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 60}
UREA_SPEC = {"name": "UREA 46-0-0", "analysis_n_pct": 46, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0}


def _mop_prepay_ctx(api, legal_name="Prepay Farms", committed_tons=20):
    """Grower + MOP product with sheet + FALL program + signed contract."""
    grower = create_grower(legal_name=legal_name)
    mop = create_product("MOP 0-0-60", 0, 0, 60)
    published_price_sheet(mop["id"], 44500)
    program = create_prepay_program()
    contract = create_prepay_contract(grower, program["id"], mop["id"], committed_tons=committed_tons)
    return {"grower": grower, "mop": mop, "program": program, "contract": contract}


class TestPrepayFundingDeadline:
    def test_funding_deadline_instant_inclusive(self, api):
        """PRD 3.9: "Each funding must arrive while the contract is `SIGNED` or
        `PARTIALLY_FUNDED` (else `ERR_INVALID_TRANSITION`), at or before the
        program's `funding_deadline` — the deadline instant itself is admitted and
        one second past it is rejected with `ERR_PREPAY_FUNDING_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/prepay_funding_deadline_instant_inclusive
        """
        ctx = _mop_prepay_ctx(api, legal_name="Deadline Farms")
        contract_id = ctx["contract"]["id"]

        get_success_data(api.set_clock({"to_iso8601": "2026-11-15T23:59:59Z"}, ADMIN))
        funded = fund_contract(contract_id, 253650)
        assert funded["funded_cents"] == 253650
        assert funded["status"] == "PARTIALLY_FUNDED", "funding at the exact deadline instant ADMITTED"

        get_success_data(api.set_clock({"to_iso8601": "2026-11-16T00:00:00Z"}, ADMIN))
        resp = api.fund_prepay_contract(contract_id, {"amount_cents": 1000}, CREDIT)
        validate_error(resp, ApiErrorId.ERR_PREPAY_FUNDING_DEADLINE_PASSED)
        readback = get_success_data(api.get_prepay_contract(contract_id, CREDIT))
        assert readback["funded_cents"] == 253650, "rejected funding left no trace"

    def test_funding_one_second_past_deadline_rejected(self, api):
        """PRD 3.9: "at or before the program's `funding_deadline` — the deadline
        instant itself is admitted and one second past it is rejected with
        `ERR_PREPAY_FUNDING_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/prepay_funding_deadline_instant_inclusive
        """
        ctx = _mop_prepay_ctx(api, legal_name="Deadline Farms 2")
        get_success_data(api.set_clock({"to_iso8601": "2026-11-16T00:00:00Z"}, ADMIN))
        resp = api.fund_prepay_contract(ctx["contract"]["id"], {"amount_cents": 1000}, CREDIT)
        validate_error(resp, ApiErrorId.ERR_PREPAY_FUNDING_DEADLINE_PASSED)


class TestPrepaySettleCascade:
    def test_settle_defaults_underfunded_contract_with_forfeiture(self, api):
        """PRD 3.9: "Hop one: every contract of the program in `SIGNED` or
        `PARTIALLY_FUNDED` moves to `DEFAULTED`. Hop two, per defaulted contract: the
        forfeited amount is the contract's `funded_cents` multiplied by the program's
        `default_penalty_pct`, rounded half-up to whole cents; a `PREPAY_FORFEITED`
        ledger entry posts for the negative of the forfeited amount; the grower's
        `prepay_balance_cents` decreases by the forfeited amount while the remainder
        of the funded money stays in the balance; and the grower's `version`
        increments."
        PRD 3.9: "The locked `unit_price_cents` is the current sheet's
        `price_per_ton_cents` multiplied by one minus the program's `discount_pct`,
        rounded half-up to whole cents; the `contract_value_cents` is the
        `unit_price_cents` multiplied by `committed_tons`, rounded half-up; and the
        `deposit_due_cents` is the `contract_value_cents` multiplied by the program's
        `deposit_pct`, rounded half-up."

        Design: Difficulty/transitive_cascade/prepay_deadline_default_cascade
        """
        ctx = _mop_prepay_ctx(api, legal_name="Prepay Default Co")
        contract = ctx["contract"]
        # signing math: unit round(44500*0.95)=42275; value 845500; deposit 253650
        assert contract["unit_price_cents"] == 42275
        assert contract["contract_value_cents"] == 845500
        assert contract["deposit_due_cents"] == 253650

        funded = fund_contract(contract["id"], 100000)
        assert funded["status"] == "PARTIALLY_FUNDED"

        get_success_data(api.close_enrollment(ctx["program"]["id"], ADMIN))
        get_success_data(api.set_clock({"to_iso8601": "2026-11-16T00:00:00Z"}, ADMIN))
        get_success_data(api.settle_prepay_program(ctx["program"]["id"], ADMIN))

        settled = get_success_data(api.get_prepay_contract(contract["id"], CREDIT))
        assert settled["status"] == "DEFAULTED", "hop 1"
        assert settled["forfeited_cents"] == 10000, "round_half_up(100000 x 0.10)"

        grower = get_success_data(api.get_grower(ctx["grower"]["id"], CREDIT))
        assert grower["prepay_balance_cents"] == 90000, \
            "hop 2: 100000 funded - 10000 forfeited; remainder stays as grower credit"

        ledger, _ = validate_paginated(api.list_credit_ledger(ctx["grower"]["id"], CREDIT))
        forfeit_entries = [e for e in ledger if e["entry_type"] == "PREPAY_FORFEITED"]
        assert len(forfeit_entries) == 1
        assert forfeit_entries[0]["amount_cents"] == -10000

    def test_settle_posts_forfeiture_ledger_entry(self, api):
        """PRD 3.9: "a `PREPAY_FORFEITED` ledger entry posts for the negative of the
        forfeited amount; the grower's `prepay_balance_cents` decreases by the
        forfeited amount while the remainder of the funded money stays in the
        balance."

        Design: Difficulty/transitive_cascade/prepay_deadline_default_cascade
        """
        ctx = _mop_prepay_ctx(api, legal_name="Prepay Default Co 2")
        fund_contract(ctx["contract"]["id"], 100000)
        get_success_data(api.close_enrollment(ctx["program"]["id"], ADMIN))
        get_success_data(api.set_clock({"to_iso8601": "2026-11-16T00:00:00Z"}, ADMIN))
        get_success_data(api.settle_prepay_program(ctx["program"]["id"], ADMIN))

        ledger, meta = validate_paginated(api.list_credit_ledger(ctx["grower"]["id"], CREDIT))
        assert meta["total_count"] == 2, "PREPAY_FUNDED then PREPAY_FORFEITED"
        assert ledger[0]["entry_type"] == "PREPAY_FUNDED"
        assert ledger[0]["amount_cents"] == 100000
        assert ledger[1]["entry_type"] == "PREPAY_FORFEITED"
        assert ledger[1]["amount_cents"] == -10000


class TestPrepayFundRefundConservation:
    def test_fund_then_refund_restores_balance(self, api):
        """PRD 2.10: "the grower's `prepay_balance_cents` is the sum of
        `PREPAY_FUNDED` amounts minus the absolute amounts of `PREPAY_DRAWN`,
        `PREPAY_FORFEITED`, and `PREPAY_REFUNDED` entries."
        PRD 3.9: "Refund returns the unfunded remainder of a funded position:
        available from `FUNDED` or `PARTIALLY_FUNDED`... The refund amount is
        `funded_cents` minus `drawn_cents`; a `PREPAY_REFUNDED` ledger entry posts
        for the negative of that amount, the grower's `prepay_balance_cents`
        decreases accordingly, the contract moves to `REFUNDED`."

        Design: Difficulty/compensating_invariant/prepay_fund_refund_conservation
        """
        ctx = _mop_prepay_ctx(api, legal_name="Conserve Prepay Farms")
        contract_id = ctx["contract"]["id"]

        funded = fund_contract(contract_id, 845500)
        assert funded["status"] == "FUNDED", "845500 == contract_value_cents exactly"

        mid = get_success_data(api.get_grower(ctx["grower"]["id"], CREDIT))
        assert mid["prepay_balance_cents"] == 845500, "forward action"

        refunded = get_success_data(api.refund_prepay_contract(contract_id, CREDIT))
        assert refunded["status"] == "REFUNDED"

        post = get_success_data(api.get_grower(ctx["grower"]["id"], CREDIT))
        assert post["prepay_balance_cents"] == 0, "compensating refund restores exactly"

        ledger, _ = validate_paginated(api.list_credit_ledger(ctx["grower"]["id"], CREDIT))
        types = [(e["entry_type"], e["amount_cents"]) for e in ledger]
        assert ("PREPAY_FUNDED", 845500) in types
        assert ("PREPAY_REFUNDED", -845500) in types

    def test_refund_posts_negative_ledger_entry(self, api):
        """PRD 3.9: "a `PREPAY_REFUNDED` ledger entry posts for the negative of that
        amount, the grower's `prepay_balance_cents` decreases accordingly, the
        contract moves to `REFUNDED`, and both versions increment."

        Design: Difficulty/compensating_invariant/prepay_fund_refund_conservation
        """
        ctx = _mop_prepay_ctx(api, legal_name="Conserve Prepay Farms 2")
        fund_contract(ctx["contract"]["id"], 845500)
        get_success_data(api.refund_prepay_contract(ctx["contract"]["id"], CREDIT))
        ledger, _ = validate_paginated(api.list_credit_ledger(ctx["grower"]["id"], CREDIT))
        refund_entries = [e for e in ledger if e["entry_type"] == "PREPAY_REFUNDED"]
        assert len(refund_entries) == 1
        assert refund_entries[0]["amount_cents"] == -845500
        assert refund_entries[0]["resulting_prepay_balance_cents"] == 0


class TestPrepayOverfund:
    def test_overfund_rejected_exact_value_admitted(self, api):
        """PRD 3.9: "must not push cumulative `funded_cents` beyond
        `contract_value_cents` (equality admitted, excess rejected as
        `ERR_PREPAY_OVERFUND`)."

        Design: Corner/errors/error_prepay_overfund_trigger
        """
        ctx = _mop_prepay_ctx(api, legal_name="Overfund Farms")
        resp = api.fund_prepay_contract(ctx["contract"]["id"], {"amount_cents": 845501}, CREDIT)
        validate_error(resp, ApiErrorId.ERR_PREPAY_OVERFUND)
        readback = get_success_data(api.get_prepay_contract(ctx["contract"]["id"], CREDIT))
        assert readback["funded_cents"] == 0


class TestPrepayContractMismatch:
    def test_price_locked_order_rejects_partially_funded_contract(self, api):
        """PRD 3.5: "for a `PRICE_LOCKED` order, the referenced contract belongs to
        the same grower, is `FUNDED`, its product matches at least one line, and its
        `funded_cents` minus `drawn_cents` is positive — any failure yields
        `ERR_PREPAY_CONTRACT_MISMATCH`."

        Design: Corner/errors/error_prepay_contract_mismatch_trigger
        """
        ctx = _mop_prepay_ctx(api, legal_name="Mismatch Contract Farms")
        contract = ctx["contract"]
        fund_contract(contract["id"], 100000)  # PARTIALLY_FUNDED only

        # Need an approved recommendation + NMP-free creation path (creation only needs rec APPROVED)
        from test_helpers import create_field, resulted_soil_test, approved_recommendation, create_blend_order
        field = create_field(ctx["grower"], name="MC Field", acres=50)
        st = resulted_soil_test(field["id"], ctx["grower"])
        rec = approved_recommendation(st["id"])
        resp = api.create_blend_order(
            ctx["grower"]["id"],
            {
                "field_id": field["id"],
                "recommendation_id": rec["id"],
                "acres": 50,
                "price_mode": "PRICE_LOCKED",
                "prepay_contract_id": contract["id"],
                "lines": [{"product_id": ctx["mop"]["id"], "target_rate_lbs_per_acre": 365.0}],
            },
            grower_headers(ctx["grower"]))
        validate_error(resp, ApiErrorId.ERR_PREPAY_CONTRACT_MISMATCH)


class TestContractInUse:
    def test_refund_blocked_while_open_order_references_contract(self, api):
        """PRD 3.9: "Refund returns the unfunded remainder of a funded position:
        available from `FUNDED` or `PARTIALLY_FUNDED`, blocked while any blend order
        references the contract with a `payment_status` other than `PAID` or
        `CANCELLED` (else `ERR_CONTRACT_IN_USE`)."

        Design: Corner/errors/error_contract_in_use_blocks_refund
        """
        ctx = _mop_prepay_ctx(api, legal_name="In Use Farms")
        contract = ctx["contract"]
        funded = fund_contract(contract["id"], 845500)
        assert funded["status"] == "FUNDED"

        # Full order pipeline for a PRICE_LOCKED MOP order
        from test_helpers import create_field, resulted_soil_test, approved_recommendation, approved_nutrient_plan, create_blend_order
        grower = ctx["grower"]
        field = create_field(grower, name="IU Field", acres=50)
        st = resulted_soil_test(field["id"], grower)
        rec = approved_recommendation(st["id"])
        approved_nutrient_plan(field["id"])
        active_permit("FERTILIZER_STORAGE")
        receive_lot(ctx["mop"]["id"], 20, lot_cost_cents_per_ton=36000)

        order = create_blend_order(
            grower, field["id"], rec["id"], 50,
            [{"product_id": ctx["mop"]["id"], "target_rate_lbs_per_acre": 365.0}],
            price_mode="PRICE_LOCKED", prepay_contract_id=contract["id"])
        # locked line at 42275: 9.125 t x 42275 = 385759
        assert order["provisional_total_cents"] == 385759, \
            "9.125 t at locked 42275, not floating 44500"
        booked = book_order(order["id"], grower)
        assert booked["payment_status"] == "PREPAY_APPLIED"

        resp = api.refund_prepay_contract(contract["id"], CREDIT)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_IN_USE)
        readback = get_success_data(api.get_prepay_contract(contract["id"], CREDIT))
        assert readback["status"] == "FUNDED", "contract remains FUNDED"


class TestProgramNotEnrolling:
    def test_signing_after_close_enrollment_rejected(self, api):
        """PRD 3.9: "Either way, once a program is not `ENROLLMENT_OPEN` — or the
        clock sits outside the enrollment window — contract signing fails with
        `ERR_PROGRAM_NOT_ENROLLING`."

        Design: Corner/errors/error_program_not_enrolling_trigger
        """
        grower = create_grower(legal_name="Late Signer Farms")
        mop = create_product("MOP 0-0-60", 0, 0, 60)
        published_price_sheet(mop["id"], 44500)
        program = create_prepay_program()
        get_success_data(api.close_enrollment(program["id"], ADMIN))

        gv = get_success_data(api.get_grower(grower["id"], CREDIT))["version"]
        resp = api.create_prepay_contract(
            grower["id"],
            {"prepay_program_id": program["id"], "product_id": mop["id"],
             "committed_tons": 20, "expected_grower_version": gv},
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ENROLLING)


class TestOCC:
    def test_prepay_contract_stale_grower_version_returns_412(self, api):
        """PRD 2.8: "Creating a prepay contract against a grower requires the request
        to carry `expected_grower_version` equal to the grower account's current
        `version`; if another accepted write — a prior contract creation, a funding,
        a credit transition — has advanced the grower's `version` since the client
        last observed it, the creation is rejected with `ERR_STALE_VERSION`
        (HTTP 412), because the client's view of the grower's prepay posture is
        stale."

        Design: Corner/cross_cutting_layers/occ_prepay_contract_stale_grower_version_returns_412
        """
        grower = create_grower(legal_name="OCC Farms")
        mop = create_product("MOP 0-0-60", 0, 0, 60)
        published_price_sheet(mop["id"], 44500)
        program = create_prepay_program()
        gv = grower["version"]  # 1

        first = create_prepay_contract(grower, program["id"], mop["id"], committed_tons=10,
                                       expected_grower_version=gv)
        assert first["id"], "version 1 was current for the first write"

        resp = api.create_prepay_contract(
            grower["id"],
            {"prepay_program_id": program["id"], "product_id": mop["id"],
             "committed_tons": 5, "expected_grower_version": gv},
            grower_headers(grower))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        readback = get_success_data(api.get_grower(grower["id"], CREDIT))
        assert readback["version"] == 2

    def test_patch_order_stale_version_returns_412(self, api):
        """PRD 2.8: "Updating a quoted blend order's lines or pricing inputs requires
        the request to carry `expected_blend_order_version` equal to the order's
        current `version`; a mismatch means another accepted write already recomputed
        the quoted totals the client is looking at, and the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD 3.5: "While `QUOTED`, the order may be revised by the owning grower or an
        agronomist: the update accepts `expected_blend_order_version` per §2.8, plus
        optional `acres`, `price_mode`, `prepay_contract_id`, and replacement
        `lines`; provisional pricing is recomputed and the order's `version`
        increments."

        Design: Corner/cross_cutting_layers/occ_patch_order_stale_order_version_returns_412
        """
        ctx = setup_order_pipeline(
            legal_name="OCC2 Farms",
            products=[UREA_SPEC], prices={"UREA 46-0-0": 52000},
            lines=[{"product_id": "UREA 46-0-0", "target_rate_lbs_per_acre": 348.1}])
        order = ctx["order"]
        ov = order["version"]
        urea_id = ctx["products"]["UREA 46-0-0"]["id"]
        gh = grower_headers(ctx["grower"])

        patched = get_success_data(api.patch_blend_order(order["id"], {
            "expected_blend_order_version": ov,
            "lines": [{"product_id": urea_id, "target_rate_lbs_per_acre": 300.0}],
        }, gh))
        assert patched["provisional_total_cents"] == 390000, "7.500 t x 52000"
        assert patched["version"] == 2

        resp = api.patch_blend_order(order["id"], {
            "expected_blend_order_version": ov,
            "lines": [{"product_id": urea_id, "target_rate_lbs_per_acre": 310.0}],
        }, gh)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        lines, _ = validate_paginated(api.list_order_lines(order["id"], CREDIT))
        assert lines[0]["target_rate_lbs_per_acre"] == pytest.approx(300.0), \
            "rejected patch left no trace"
