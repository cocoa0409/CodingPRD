"""Warranty claims: filing gates, labor allowance variants and cap, routing
selector, adjudication lifecycle, and the defective return leg."""
import pytest

from test_helpers import (
    ADJUSTER,
    ANY_H,
    INSTALLER,
    ApiErrorId,
    assert_hard_part_availability,
    assert_warranty_claim,
    create_min_model,
    create_transmission_model_payload,
    create_warranty_claim_payload,
    drive_order_to_calibration,
    drive_order_to_shipped,
    get_claim,
    get_order,
    get_part,
    set_clock,
    setup_approved_claim,
    setup_claim_in_transit,
    setup_salvage_promotion_scenario,
    setup_submitted_claim,
    submit_claim,
    api_client,
    validate_error,
    validate_success,
)


class TestClaimFilingGate:

    def test_claim_rejected_before_shipment(self):
        """PRD §3.8: "An `Installer` files a warranty claim against an order that must already be `SHIPPED` (`ERR_ORDER_NOT_SHIPPED`)".

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_shipped_order
        """
        model = create_min_model()
        order = drive_order_to_calibration(model["id"])
        assert order["status"] == "CALIBRATION"
        resp = api_client.create_warranty_claim(
            create_warranty_claim_payload(order["id"]), INSTALLER)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SHIPPED)

    def test_claim_accepted_after_shipment(self):
        """PRD §3.8: "The claim records the filer's `X-User-ID` as `installer_id` and opens with `claim_status` `SUBMITTED`, `return_status` `NONE`, `deny_reason` null, `labor_allowance_cents` null until approval, and `salvaged_parts` empty."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_shipped_order
        """
        _m, order, _invoice = drive_order_to_shipped()
        resp = api_client.create_warranty_claim(
            create_warranty_claim_payload(order["id"]), INSTALLER)
        claim = validate_success(resp, expected_status=201)
        assert_warranty_claim(claim)
        assert claim["claim_status"] == "SUBMITTED"
        assert claim["return_status"] == "NONE"
        assert claim["installer_id"] == "inst-1", \
            "the filer's X-User-ID is recorded as installer_id"
        assert claim["labor_allowance_cents"] is None
        assert claim["salvaged_parts"] == []

    def test_warranty_window_expired(self):
        """PRD §3.8: "Filing must occur no later than the model's `warranty_days` after the order's `shipped_at`; a later filing is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`."
        PRD §3.1: "An optional `warranty_days` sets the coverage window in days from shipment and defaults to 365 when omitted."

        Design: Corner/errors/warranty_window_expired_rejected
        """
        _m, order, _invoice = drive_order_to_shipped()
        set_clock("2027-09-05T00:00:00Z")  # 400 days after the 2026-08-01 shipment
        resp = api_client.create_warranty_claim(
            create_warranty_claim_payload(order["id"]), INSTALLER)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED)


class TestLaborAllowanceVariants:

    def test_book_hours_pays_full_guide(self):
        """PRD §3.8: "Under `BOOK_HOURS`, the payable hours are the pinned `flat_rate_hours` in full, regardless of what the installer claimed".

        Design: Difficulty/dual_variant_calc/labor_allowance_book_vs_actual_policy
        """
        _m, _o, claim = setup_approved_claim(
            claimed_labor_hours=5.0, installer_labor_rate_cents=12000,
            allowance_policy="BOOK_HOURS")
        assert claim["labor_allowance_cents"] == 72000, (
            f"BOOK_HOURS pays the full 6.0h guide at 12000c/h = 72000, "
            f"got {claim['labor_allowance_cents']}"
        )

    def test_actual_hours_pays_lesser(self):
        """PRD §3.8: "under `ACTUAL_HOURS`, the payable hours are the lesser of `claimed_labor_hours` and the pinned `flat_rate_hours`, so identical inputs pay less whenever the claim comes in under the guide."

        Design: Difficulty/dual_variant_calc/labor_allowance_book_vs_actual_policy
        """
        _m, _o, claim = setup_approved_claim(
            claimed_labor_hours=5.0, installer_labor_rate_cents=12000,
            allowance_policy="ACTUAL_HOURS")
        assert claim["labor_allowance_cents"] == 60000, (
            f"ACTUAL_HOURS pays min(5.0, 6.0) * 12000 = 60000, "
            f"got {claim['labor_allowance_cents']}"
        )
        assert claim["labor_allowance_cents"] != 72000, \
            "the two policy variants diverge on identical inputs"


class TestAllowanceCapAndRouting:

    def test_labor_allowance_cap_binds(self):
        """PRD §3.8: "`labor_allowance_cents` is the lesser of that raw allowance and the pinned `labor_cap_cents` — an uncapped allowance exactly equal to the cap pays the cap value."
        PRD §3.8: "otherwise a `labor_allowance_cents` of at least 50000 cents routes `RETURN_TO_PLANT`".

        Design: Corner/calculations/labor_allowance_cap_boundary
        """
        hd_model = create_min_model(**create_transmission_model_payload(
            model_code="HD-10L90", year_start=2019, year_end=2024,
            model="Silverado HD", core_deposit_cents=80000,
            flat_rate_hours=8.0, labor_cap_cents=90000))
        _m, _o, claim = setup_approved_claim(
            model=hd_model, failure_code="PRESSURE_LEAK",
            claimed_labor_hours=7.5, installer_labor_rate_cents=12000,
            allowance_policy="BOOK_HOURS")
        assert claim["labor_allowance_cents"] == 90000, \
            "the cap binds over the raw 8.0h * 12000c = 96000"
        assert claim["routing_type"] == "RETURN_TO_PLANT", \
            "90000 >= 50000 routes the defective unit back to the plant"
        assert claim["return_required"] is True
        assert claim["return_status"] == "ISSUED"

    def test_routing_threshold_boundary(self):
        """PRD §3.8: "The routing selector then computes `routing_type` top to bottom with the first matching rule winning: an `ELECTRICAL_TCM` failure routes `RETURN_TO_DISTRIBUTOR`; otherwise a `labor_allowance_cents` of at least 50000 cents routes `RETURN_TO_PLANT`; anything else routes `LOCAL_SCRAP`."
        PRD §3.8: "`return_required` is true unless the routing is `LOCAL_SCRAP`, and when a return is required the claim's `return_status` opens `NONE` → `ISSUED`."

        Design: Corner/calculations/routing_selector_value_boundary
        """
        lt_model = create_min_model(**create_transmission_model_payload(
            model_code="LT-6T40", year_start=2012, year_end=2018,
            model="Cruze", core_deposit_cents=30000, flat_rate_hours=5.0))
        _m, order, _invoice = drive_order_to_shipped(model=lt_model)

        claim_eq = submit_claim(order["id"], installer_labor_rate_cents=10000,
                                allowance_policy="BOOK_HOURS")
        claim_below = submit_claim(order["id"], installer_labor_rate_cents=9999,
                                   allowance_policy="BOOK_HOURS")

        approved_eq = validate_success(
            api_client.approve_claim(claim_eq["id"], ADJUSTER))
        assert approved_eq["labor_allowance_cents"] == 50000, "5.0h * 10000c = 50000"
        assert approved_eq["routing_type"] == "RETURN_TO_PLANT", \
            "the 50000-cent routing threshold is inclusive"
        assert approved_eq["return_required"] is True
        assert approved_eq["return_status"] == "ISSUED"

        approved_below = validate_success(
            api_client.approve_claim(claim_below["id"], ADJUSTER))
        assert approved_below["labor_allowance_cents"] == 49995, "5.0h * 9999c = 49995"
        assert approved_below["routing_type"] == "LOCAL_SCRAP"
        assert approved_below["return_required"] is False
        assert approved_below["return_status"] == "NONE", \
            "no return leg opens for LOCAL_SCRAP"


class TestAdjudicationGates:

    def test_double_approve_rejected(self):
        """PRD §3.8: "Approval requires `SUBMITTED` (`ERR_CLAIM_NOT_REVIEWABLE`)".

        Design: Corner/errors/double_approve_rejected
        """
        _m, _o, claim = setup_approved_claim()
        assert claim["labor_allowance_cents"] == 72000
        assert claim["return_status"] == "ISSUED"

        resp = api_client.approve_claim(claim["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE)
        after = get_claim(claim["id"])
        assert after["labor_allowance_cents"] == 72000, \
            "a rejected re-approval must not recompute the allowance"
        assert after["return_status"] == "ISSUED", \
            "no second return leg opens"

    def test_pay_before_approve_rejected(self):
        """PRD §3.8: "Payment requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_PAYABLE`)".

        Design: Corner/errors/pay_before_approve_rejected
        """
        _m, _o, claim = setup_submitted_claim(failure_code="CONVERTER_FAILURE",
                                              allowance_policy="ACTUAL_HOURS")
        resp = api_client.pay_claim(claim["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)
        after = get_claim(claim["id"])
        assert after["claim_status"] == "SUBMITTED"

    def test_pay_blocked_until_return_dispositioned(self):
        """PRD §3.8: "when a return is required, the return leg must already be `DISPOSITIONED` (`ERR_RETURN_NOT_RECEIVED`)".

        Design: Corner/errors/pay_blocked_until_return_dispositioned
        """
        _m, _o, claim = setup_claim_in_transit()
        assert claim["return_status"] == "IN_TRANSIT"
        resp = api_client.pay_claim(claim["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_RECEIVED)
        after = get_claim(claim["id"])
        assert after["claim_status"] == "APPROVED", \
            "a blocked payment must not advance the claim"


class TestReturnLeg:

    def test_return_ship_before_approve_rejected(self):
        """PRD §3.8: "ships the defective unit back while the claim is `APPROVED` and the return leg is `ISSUED` (`ERR_RETURN_NOT_SHIPPABLE`)".

        Design: Corner/errors/return_ship_before_approve_rejected
        """
        _m, _o, claim = setup_submitted_claim()
        assert claim["return_status"] == "NONE"
        resp = api_client.return_ship_claim(claim["id"], INSTALLER)
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_SHIPPABLE)

    def test_return_receive_before_ship_rejected(self):
        """PRD §3.8: "A `WarrantyAdjuster` receives and dispositions an `IN_TRANSIT` return (`ERR_RETURN_NOT_RECEIVABLE`), moving it to `DISPOSITIONED`".

        Design: Corner/errors/return_receive_before_ship_rejected
        """
        _m, _o, claim = setup_approved_claim(failure_code="PRESSURE_LEAK")
        assert claim["return_status"] == "ISSUED"
        resp = api_client.return_receive_claim(claim["id"], {}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_RECEIVABLE)
        after = get_claim(claim["id"])
        assert after["return_status"] == "ISSUED"


class TestSalvageRestockPromotion:

    def test_salvage_restock_promotes_part_hold(self):
        """PRD §3.8: "each `salvaged_parts` line supplied at receipt restocks inventory by adding its `qty` back to that part's `qty_on_hand`, and the availability increase fires the `PART_HOLD` promotion scan of §2.9."
        PRD §3.8: "Payment requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_PAYABLE`) and, when a return is required, the return leg must already be `DISPOSITIONED` (`ERR_RETURN_NOT_RECEIVED`)".

        Design: Corner/complexity_layers/return_receive_salvage_promotes_part_hold_order
        """
        ctx = setup_salvage_promotion_scenario()
        part, o2, claim = ctx["part"], ctx["o2"], ctx["claim"]
        assert get_part(part["id"])["qty_on_hand"] == 0, \
            "order1's ship consumed both units"

        resp = api_client.return_receive_claim(
            claim["id"],
            {"salvaged_parts": [{"hard_part_id": part["id"], "qty": 2}]},
            ADJUSTER,
        )
        received = validate_success(resp)
        assert received["return_status"] == "DISPOSITIONED"

        part_after = get_part(part["id"])
        assert part_after["qty_on_hand"] == 2, "salvage restocks the part"
        assert part_after["qty_reserved"] == 2, \
            "the promotion re-reserves the restocked units"
        assert_hard_part_availability(part_after)

        promoted = get_order(o2["id"])
        assert promoted["status"] == "ASSEMBLY", \
            f"the PART_HOLD order must auto-promote, got {promoted['status']}"
        assert promoted["reserved_parts"][0]["qty"] == 2

        pay = validate_success(api_client.pay_claim(claim["id"], ADJUSTER))
        assert pay["claim_status"] == "PAID", \
            "once the return is dispositioned the pay gate is satisfied"
