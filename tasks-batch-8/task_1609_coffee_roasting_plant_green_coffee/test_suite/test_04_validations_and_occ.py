"""RBAC, OCC (stale-version), and validation-priority conflict tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_shipment,
    create_counterparty,
    create_fixed_contract,
    create_hedge,
    create_ptbf_contract,
    get_contract,
    get_lot_for_shipment,
    make_risk_manager_headers,
    make_trader_headers,
    record_price_fix,
    receive_shipment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    walk_shipment_to_arrived,
)

TRADER = TEST_USERS["trader_headers"]
RISK = TEST_USERS["risk_manager_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]
HEAD_ROASTER = TEST_USERS["head_roaster_headers"]
ROAST_OP = TEST_USERS["roast_operator_headers"]
QA = TEST_USERS["qa_grader_headers"]
PLANNER = TEST_USERS["fulfillment_planner_headers"]


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, declaring the
        operational capacity in which they act."
        PRD §2.1: "A request with missing or malformed headers, or whose
        declared role is not one of these nine names, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        set_clock()
        # No headers at all
        resp = api.list_counterparties({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:
    def test_forbidden_role_denied(self, api):
        """PRD §2.1: "A request whose role is recognized but not authorized
        for the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "A `Trader` registers one by supplying a
        `counterparty_ref`"

        Design: Corner/validations/forbidden_role_denied
        """
        set_clock()
        resp = api.create_counterparty(
            {"counterparty_ref": "SUP-FRB", "legal_name": "Forbidden",
             "counterparty_kind": "SUPPLIER", "credit_limit_usd": 1000},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_trader_cannot_approve_own_hedge_via_role(self, api):
        """PRD §3.3: "Approval belongs to the `RiskManager`."
        PRD §2.1: "A request whose role is recognized but not authorized for
        the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/trader_cannot_approve_own_hedge_via_role
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-RB")
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-RB",
                                         total_lbs=1000, differential=0.25)
        hedge = create_hedge(contract["id"], hedge_lbs=100, entry_price=1.80,
                              trader_headers=make_trader_headers("trader-rb"))
        # A Trader calling approve hits RBAC (role check), not SoD.
        resp = api.approve_futures_hedge(
            hedge["id"], make_trader_headers("trader-rb"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_roast_operator_cannot_approve_recipe(self, api):
        """PRD §3.7: "Approval is the governance gate, exercised by the
        `HeadRoaster` and guarded by the `expected_product_version` OCC
        rule of §2.9 against the parent product."
        PRD §2.1: "A request whose role is recognized but not authorized
        for the target operation is rejected with `ERR_FORBIDDEN` (HTTP
        403)."

        Design: Corner/roles/roast_operator_cannot_approve_recipe
        """
        set_clock()
        profile = validate_success(api.create_roast_profile(
            {"profile_code": "RP-RR", "charge_temp_c": 200,
             "target_drop_temp_c": 210, "expected_yield_loss_pct": 0.16,
             "shrinkage_alert_band_pct": 0.02},
            HEAD_ROASTER), 201)
        product = validate_success(api.create_product(
            {"sku": "P-RR", "display_name": "RR P", "channel": "WHOLESALE",
             "target_roast_profile_id": profile["id"], "freshness_days": 30},
            HEAD_ROASTER), 201)
        recipe = validate_success(
            api.create_recipe(product["id"], HEAD_ROASTER), 201)
        validate_success(api.add_recipe_component(
            recipe["id"], {"required_grade": "SHB", "component_pct": 1.0},
            HEAD_ROASTER), 201)
        resp = api.approve_recipe(
            recipe["id"],
            {"expected_product_version": product["version"]},
            ROAST_OP,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOccStaleVersion:
    def test_occ_stale_version_on_short_close(self, api):
        """PRD §2.9: "Short-closing a contract carries the identical guard:
        the request must carry `expected_contract_version` matching the
        contract's current `version`, and a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_version_on_short_close
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-OSC", credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-OSC",
                                         total_lbs=5000, differential=0.25)
        v0 = contract["version"]
        shipment = book_shipment(contract["id"], shipment_ref="SH-OSC",
                                  planned_lbs=2000)
        walk_shipment_to_arrived(shipment["id"])
        receive_shipment(shipment["id"], 2000, lot_code="L-OSC")
        # Receipt advanced Contract.version, so the held v0 is now stale.
        resp = api.short_close_contract(
            contract["id"], {"expected_contract_version": v0}, TRADER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_stale_version_on_recipe_approve(self, api):
        """PRD §2.9: "Approving a blend recipe is guarded against the parent
        product instead: the request must carry `expected_product_version`
        matching the product's current `version`, because a competing recipe
        approval may have superseded the recipe landscape since the client
        last read the product; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_version_on_recipe_approve
        """
        set_clock()
        profile = validate_success(api.create_roast_profile(
            {"profile_code": "RP-ORA", "charge_temp_c": 200,
             "target_drop_temp_c": 210, "expected_yield_loss_pct": 0.16,
             "shrinkage_alert_band_pct": 0.02},
            HEAD_ROASTER), 201)
        product = validate_success(api.create_product(
            {"sku": "P-ORA", "display_name": "ORA P", "channel": "WHOLESALE",
             "target_roast_profile_id": profile["id"], "freshness_days": 30},
            HEAD_ROASTER), 201)
        v0 = product["version"]
        recipe1 = validate_success(
            api.create_recipe(product["id"], HEAD_ROASTER), 201)
        validate_success(api.add_recipe_component(
            recipe1["id"], {"required_grade": "SHB", "component_pct": 1.0},
            HEAD_ROASTER), 201)
        # First approve advances Product.version
        validate_success(api.approve_recipe(
            recipe1["id"], {"expected_product_version": v0}, HEAD_ROASTER))
        recipe2 = validate_success(
            api.create_recipe(product["id"], HEAD_ROASTER), 201)
        validate_success(api.add_recipe_component(
            recipe2["id"], {"required_grade": "HG", "component_pct": 1.0},
            HEAD_ROASTER), 201)
        # Replaying the stale product version is rejected with ERR_STALE_VERSION
        resp = api.approve_recipe(
            recipe2["id"], {"expected_product_version": v0}, HEAD_ROASTER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestDeliveryWindowValidation:
    def test_invalid_delivery_window_end_before_start(self, api):
        """PRD §3.1: "The window end must be strictly after the start; a
        non-positive window is rejected with `ERR_INVALID_DELIVERY_WINDOW`."

        Design: Corner/validations/invalid_delivery_window_end_before_start
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-IDW")
        resp = api.create_contract(
            supplier["id"],
            {"contract_ref": "C-IDW", "pricing_mode": "FIXED_OUTRIGHT",
             "coffee_grade": "SHB", "total_lbs": 1000,
             "fixed_price_usd_per_lb": 2.00,
             "delivery_window_start": "2026-09-30T00:00:00Z",
             "delivery_window_end": "2026-09-01T00:00:00Z"},
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DELIVERY_WINDOW)


class TestOverFixAndQuantityValidation:
    def test_over_fix_rejected(self, api):
        """PRD §3.2: "Second the over-fix cap: the cumulative
        `fixed_lbs_accum` plus the new `fix_lbs` must not exceed the
        contract's `total_lbs`, otherwise `ERR_OVER_FIX`."

        Design: Corner/validations/over_fix_rejected
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-OF", credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-OF",
                                         total_lbs=1000, differential=0.25)
        record_price_fix(contract["id"], 800, 1.80, contract["version"])
        c = get_contract(contract["id"])
        # 800 + 201 = 1001 > 1000 total_lbs -> ERR_OVER_FIX
        resp = api.create_price_fix(
            contract["id"],
            {"fix_lbs": 201, "futures_price_usd_per_lb": 1.80,
             "expected_contract_version": c["version"]},
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_OVER_FIX)

    def test_invalid_fix_quantity_zero(self, api):
        """PRD §3.2: "Third the quantity sanity check: `fix_lbs` must be
        strictly positive and `futures_price_usd_per_lb` strictly positive,
        otherwise `ERR_INVALID_FIX_QUANTITY`."

        Design: Corner/validations/invalid_fix_quantity_zero
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-IFQ")
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-IFQ",
                                         total_lbs=1000, differential=0.25)
        resp = api.create_price_fix(
            contract["id"],
            {"fix_lbs": 0, "futures_price_usd_per_lb": 1.80,
             "expected_contract_version": contract["version"]},
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FIX_QUANTITY)


class TestPriorityPairConflict:
    def test_stale_version_precedes_credit_limit(self, api):
        """PRD §2.8: "After existence comes state legality — the target
        entity must be in a state that permits the requested transition,
        otherwise `ERR_INVALID_STATE` (HTTP 409). Then optimistic
        concurrency, where applicable (§2.9), yields `ERR_STALE_VERSION`
        (HTTP 412). Only after all of these do the domain business rules
        run, each producing its own specific 422 error."
        PRD §3.2: "First the credit gate: the fix must not push the
        counterparty's **provisional** open exposure above
        `credit_limit_usd`, otherwise the fix is refused with
        `ERR_CREDIT_LIMIT_EXCEEDED`"

        Design: Difficulty/priority_pair_validation_conflict/stale_version_precedes_credit_limit
        """
        set_clock()
        # credit_limit_usd is 20000 so the trigger fix would violate the credit
        # gate, but the OCC stale-version must fire first.
        supplier = create_counterparty(ref="SUP-P1", legal_name="Priority One",
                                        credit_limit_usd=20000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-P1",
                                         total_lbs=10000, differential=0.25)
        v0 = contract["version"]
        # Small first fix advances the contract version.
        record_price_fix(contract["id"], 100, 1.50, v0)
        # Replay the stale v0 with a much larger fix that would also violate credit.
        resp = api.create_price_fix(
            contract["id"],
            {"fix_lbs": 5000, "futures_price_usd_per_lb": 2.00,
             "expected_contract_version": v0},
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_precedes_credit_limit_version_unchanged(self, api):
        """PRD §2.9: "Recording a price-fix against a contract requires
        the request to carry `expected_contract_version` holding the
        contract `version` the client last observed. If the contract's
        current `version` has advanced since — because another writer
        posted a fix, a receipt landed, or the contract was short-closed
        — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Difficulty/priority_pair_validation_conflict/stale_version_precedes_credit_limit
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-P1B", credit_limit_usd=20000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-P1B",
                                         total_lbs=10000, differential=0.25)
        v0 = contract["version"]
        # Advance the contract version with a legitimate first fix.
        record_price_fix(contract["id"], 100, 1.50, v0)
        # Stale replay must be rejected; contract state unchanged.
        resp = api.create_price_fix(
            contract["id"],
            {"fix_lbs": 5000, "futures_price_usd_per_lb": 2.00,
             "expected_contract_version": v0},
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # No new fix persisted: fixed_lbs_accum still 100.
        c = get_contract(contract["id"])
        assert c["fixed_lbs_accum"] == 100

    def test_segregation_of_duties_precedes_over_hedge(self, api):
        """PRD §3.3: "Two business validations guard it, evaluated in order:
        first segregation of duties — the approver must not be the trader
        who submitted the hedge, per §2.10, otherwise
        `ERR_SEGREGATION_OF_DUTIES`; then the over-hedge cap — the cumulative
        `hedge_lbs` across the contract's already-`APPROVED` hedges plus this
        hedge's pounds must not exceed the contract's `unpriced_lbs` at
        approval time, otherwise `ERR_OVER_HEDGE`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_over_hedge
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-P2", credit_limit_usd=1000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-P2",
                                         total_lbs=1000, differential=0.20)
        # Hedge submitted by user "shared-user-001" (as Trader).
        # hedge_lbs 5000 > unpriced 1000, so the over-hedge check would also fail.
        hedge = create_hedge(
            contract["id"], hedge_side="BUY_FUTURES", hedge_lbs=5000,
            entry_price=1.80,
            trader_headers=make_trader_headers("shared-user-001"),
        )
        # Same X-User-ID as submitter, but with RiskManager role. RBAC passes
        # (RiskManager is the authorized role), then the SoD check fires first.
        resp = api.approve_futures_hedge(
            hedge["id"], make_risk_manager_headers("shared-user-001"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_segregation_of_duties_precedes_over_hedge_hedge_still_working(
            self, api):
        """PRD §3.3: "Two business validations guard it, evaluated in
        order: first segregation of duties — the approver must not be the
        trader who submitted the hedge, per §2.10, otherwise
        `ERR_SEGREGATION_OF_DUTIES`; then the over-hedge cap — the
        cumulative `hedge_lbs` across the contract's already-`APPROVED`
        hedges plus this hedge's pounds must not exceed the contract's
        `unpriced_lbs` at approval time, otherwise `ERR_OVER_HEDGE`."
        PRD §2.10: "The approving user's `X-User-ID` must differ from the
        submitting trader's `X-User-ID` recorded when the hedge was
        created; the same person may not approve their own hedge."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_over_hedge
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-P2B", credit_limit_usd=1000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-P2B",
                                         total_lbs=1000, differential=0.20)
        hedge = create_hedge(
            contract["id"], hedge_side="BUY_FUTURES", hedge_lbs=5000,
            entry_price=1.80,
            trader_headers=make_trader_headers("self-approver"),
        )
        resp = api.approve_futures_hedge(
            hedge["id"], make_risk_manager_headers("self-approver"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # Hedge stays WORKING (the failed approval is not persisted)
        h = validate_success(api.get_futures_hedge(hedge["id"], TRADER))
        assert h["hedge_status"] == "WORKING"


class TestCrossEntityStateDependency:
    def test_financing_pledge_blocked_by_lot_not_released(self, api):
        """PRD §3.6: "Two validations guard the pledge, evaluated in order:
        first facility headroom — the line's `utilized_usd` plus the new
        reserve's advance must not exceed `facility_limit_usd`, otherwise
        `ERR_FACILITY_LIMIT_EXCEEDED`; then pledgeability — the lot must be
        in `RELEASED` and `reserved_lbs` must not exceed the lot's
        `available_lbs` at pledge time, otherwise `ERR_LOT_NOT_PLEDGEABLE`."

        Design: Difficulty/cross_entity_state_dependency/financing_pledge_blocked_by_lot_not_released
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-FIN")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-FIN", total_lbs=1000,
            fixed_price=2.00,
        )
        shipment = book_shipment(contract["id"], shipment_ref="SH-FIN",
                                  planned_lbs=1000)
        walk_shipment_to_arrived(shipment["id"])
        receive_shipment(shipment["id"], 1000, lot_code="L-FIN")
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["lot_status"] == "QUARANTINE", (
            "precondition: lot is QUARANTINE (no cupping finalized)"
        )
        line = validate_success(api.create_financing_line(
            {"lender_name": "Bank F", "facility_limit_usd": 10000,
             "advance_rate_pct": 0.50},
            RISK,
        ), 201)
        resp = api.create_financing_reserve(
            line["id"],
            {"green_lot_id": lot["id"], "reserved_lbs": 500},
            RISK,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_PLEDGEABLE)

    def test_financing_pledge_blocked_by_lot_not_released_no_reserve_persisted(
            self, api):
        """PRD §3.6: "then pledgeability — the lot must be in `RELEASED`
        and `reserved_lbs` must not exceed the lot's `available_lbs` at
        pledge time, otherwise `ERR_LOT_NOT_PLEDGEABLE`."

        Design: Difficulty/cross_entity_state_dependency/financing_pledge_blocked_by_lot_not_released
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-FIN2")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-FIN2", total_lbs=1000,
            fixed_price=2.00,
        )
        shipment = book_shipment(contract["id"], shipment_ref="SH-FIN2",
                                  planned_lbs=1000)
        walk_shipment_to_arrived(shipment["id"])
        receive_shipment(shipment["id"], 1000, lot_code="L-FIN2")
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["lot_status"] == "QUARANTINE"
        line = validate_success(api.create_financing_line(
            {"lender_name": "Bank F2", "facility_limit_usd": 10000,
             "advance_rate_pct": 0.50},
            RISK,
        ), 201)
        resp = api.create_financing_reserve(
            line["id"],
            {"green_lot_id": lot["id"], "reserved_lbs": 500},
            RISK,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_PLEDGEABLE)
        # No FinancingReserve was persisted for this line
        reserves, meta = validate_paginated(
            api.list_financing_reserves(
                RISK, params={"financing_line_id": line["id"]}))
        assert meta["total_count"] == 0
