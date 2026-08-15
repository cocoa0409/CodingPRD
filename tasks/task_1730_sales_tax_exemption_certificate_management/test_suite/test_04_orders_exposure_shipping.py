"""Order capture math, the HELD_FOR_CERT gating dependency, the certificate
approval cascade, compensating cancel, and the shipping exposure gate."""
from test_helpers import (
    ApiErrorId,
    THRESHOLDS,
    assert_order,
    assert_order_amount_invariants,
    create_approved_certificate,
    create_held_order,
    create_onboarded_customer,
    create_order_payload,
    create_order_with_lines,
    create_tenant,
    add_exemption_reason,
    setup_blocked_exposure_scenario,
    setup_tenant_config,
    submit_order,
    validate_error,
    validate_success,
)


class TestOrderMath:
    def test_order_line_extended_cents_computed(self, api, order_clerk_headers):
        """PRD §3.5: "The line's `extended_cents` is the exact integer product of `quantity` and `unit_price_cents`, and every line addition recomputes the order's `subtotal_cents` as the sum of `extended_cents` across all lines and increments the order's `version`."

        Design: Corner/entities/order_line_extended_cents_computed
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        order = create_order_with_lines(tenant["id"], cust["id"], [])  # DRAFT, no lines
        res = api.add_order_line(
            tenant["id"], order["id"],
            {"sku": "ABC", "quantity": 3, "unit_price_cents": 250, "is_exempt_claimed": True},
            order_clerk_headers)
        line = validate_success(res, 201)
        assert line["extended_cents"] == 750, (
            f"extended_cents must be 3 * 250 = 750, got {line['extended_cents']}")

    def test_order_subtotal_aggregation(self, api, order_clerk_headers):
        """PRD §3.5: "The line's `extended_cents` is the exact integer product of `quantity` and `unit_price_cents`, and every line addition recomputes the order's `subtotal_cents` as the sum of `extended_cents` across all lines and increments the order's `version`."

        Design: Corner/calculations/order_subtotal_aggregation
        """
        tenant = create_tenant(legal_name="T1")
        add_exemption_reason(tenant["id"], code="RES", requires_certificate=False,
                             allowed_form_types=[])
        cust = create_onboarded_customer(tid=tenant["id"])
        order = create_order_with_lines(
            tenant["id"], cust["id"],
            [("A", 2, 100, False), ("B", 3, 50, False)])
        fetched = validate_success(api.get_order(tenant["id"], order["id"], order_clerk_headers), 200)
        # 2*100 + 3*50 = 350
        assert fetched["subtotal_cents"] == 350, (
            f"subtotal_cents must be the sum of extended_cents (350), got {fetched['subtotal_cents']}")


class TestOrderSubmitGate:
    def test_order_submit_with_zero_lines_rejected(self, api, order_clerk_headers):
        """PRD §3.5: "Submitting an order validates, in global priority order: the order must be in `DRAFT` (else `ERR_INVALID_STATE_TRANSITION`); the order must have at least one line (else `ERR_ORDER_EMPTY`, HTTP 422) — this check precedes the onboarding check, so an empty order on a customer with incomplete onboarding surfaces `ERR_ORDER_EMPTY`;"

        Design: Corner/state_machines/order_submit_with_zero_lines_rejected
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])  # onboarding complete: isolated failure
        order = create_order_with_lines(tenant["id"], cust["id"], [])
        res = api.submit_order(tenant["id"], order["id"], order_clerk_headers)
        validate_error(res, ApiErrorId.ERR_ORDER_EMPTY, expected_status=422)

    def test_order_ship_in_held_state_rejected(self, api, fulfillment_clerk_headers):
        """PRD §3.5: "The order must genuinely be in `READY_TO_SHIP` — which by construction means its covered amount equals its exempt amount; a ship attempt in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/order_ship_in_held_state_rejected
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        order = create_held_order(tenant["id"], cust["id"],
                                  lines=(("ABC-1", 1, 100, True),))
        assert order["status"] == "HELD_FOR_CERT"
        res = api.ship_order(tenant["id"], order["id"], fulfillment_clerk_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)


class TestOrderHeldUntilCertApproved:
    def test_order_released_by_matching_cert_approval(self, api, auditor_headers):
        """PRD §3.3: "For every order of this customer sitting in `HELD_FOR_CERT` whose `ship_to_state` matches the certificate's `ship_to_state`, the system recomputes `covered_amount_cents` under §3.5; any order whose `uncovered_amount_cents` thereby falls to zero is released, transitioning `HELD_FOR_CERT` → `READY_TO_SHIP` with its own `version` increment, and the released exposure comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`."

        Design: Difficulty/cross_entity_state_dependency/order_held_until_cert_approved
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        # EX-prefixed SKU: fully covered under either coverage mode once a
        # matching APPROVED cert exists (PRD §3.5).
        order = create_held_order(tenant["id"], cust["id"],
                                  lines=(("EX-1", 1, 5000, True),))
        assert order["status"] == "HELD_FOR_CERT"

        # No /orders call is made after this point: the release must be driven
        # entirely by the certificate approval.
        create_approved_certificate(tenant["id"], cust["id"])
        after = validate_success(api.get_order(tenant["id"], order["id"], auditor_headers), 200)
        assert after["status"] == "READY_TO_SHIP", (
            f"cert approval must release the held order, got {after['status']}")

    def test_order_stays_held_when_other_state_cert_approved(self, api, auditor_headers):
        """PRD §3.3: "For every order of this customer sitting in `HELD_FOR_CERT` whose `ship_to_state` matches the certificate's `ship_to_state`, the system recomputes `covered_amount_cents` under §3.5; any order whose `uncovered_amount_cents` thereby falls to zero is released, transitioning `HELD_FOR_CERT` → `READY_TO_SHIP` with its own `version` increment, and the released exposure comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`."

        Design: Difficulty/cross_entity_state_dependency/order_held_until_cert_approved
        """
        tenant = setup_tenant_config(rule_specs=[{"state_code": "CA"}, {"state_code": "TX"}])
        cust = create_onboarded_customer(tid=tenant["id"], primary_ship_to_state="CA")
        order = create_held_order(tenant["id"], cust["id"],
                                  lines=(("EX-1", 1, 5000, True),), ship_to_state="CA")
        assert order["status"] == "HELD_FOR_CERT"

        # A TX certificate does not match the CA order's ship_to_state.
        create_approved_certificate(tenant["id"], cust["id"],
                                    cert_overrides={"ship_to_state": "TX"})
        after = validate_success(api.get_order(tenant["id"], order["id"], auditor_headers), 200)
        assert after["status"] == "HELD_FOR_CERT", (
            "approval for a non-matching ship_to_state must not release the order")


class TestCertApprovalExposureCascade:
    def test_cert_approval_releases_order_and_zeroes_uncovered(self, api, auditor_headers):
        """PRD §3.5: "when the covered amount falls short of the exempt amount the order lands in `HELD_FOR_CERT`, and its `uncovered_amount_cents` is added to both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`; when coverage is complete the order lands in `READY_TO_SHIP`."
        PRD §3.3: "For every order of this customer sitting in `HELD_FOR_CERT` whose `ship_to_state` matches the certificate's `ship_to_state`, the system recomputes `covered_amount_cents` under §3.5; any order whose `uncovered_amount_cents` thereby falls to zero is released, transitioning `HELD_FOR_CERT` → `READY_TO_SHIP` with its own `version` increment, and the released exposure comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`."

        Design: Difficulty/transitive_cascade/cert_approve_cascade_to_tenant_exposure
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        order = create_held_order(tenant["id"], cust["id"],
                                  lines=(("EX-1", 1, 5000, True),))
        assert order["status"] == "HELD_FOR_CERT"
        assert order["uncovered_amount_cents"] == 5000

        create_approved_certificate(tenant["id"], cust["id"])
        after = validate_success(api.get_order(tenant["id"], order["id"], auditor_headers), 200)
        assert_order_amount_invariants(after)
        assert after["status"] == "READY_TO_SHIP"
        assert after["covered_amount_cents"] == 5000
        assert after["uncovered_amount_cents"] == 0

    def test_cert_approval_releases_customer_and_tenant_exposure(self, api, auditor_headers):
        """PRD §3.3: "For every order of this customer sitting in `HELD_FOR_CERT` whose `ship_to_state` matches the certificate's `ship_to_state`, the system recomputes `covered_amount_cents` under §3.5; any order whose `uncovered_amount_cents` thereby falls to zero is released, transitioning `HELD_FOR_CERT` → `READY_TO_SHIP` with its own `version` increment, and the released exposure comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`."
        PRD §3.5: "Both customer and tenant exposure totals are derived sums — the customer's `blocked_exposure_cents` is always the sum of `uncovered_amount_cents` across exactly its `HELD_FOR_CERT` orders, while the tenant's `open_exposure_cents` is the sum of `uncovered_amount_cents` across all non-terminal orders in the tenant, an order being non-terminal until it reaches `CANCELLED` or `INVOICED`"

        Design: Difficulty/transitive_cascade/cert_approve_cascade_to_tenant_exposure
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        order = create_held_order(tenant["id"], cust["id"],
                                  lines=(("EX-1", 1, 5000, True),))
        cust_pre = validate_success(api.get_customer(tenant["id"], cust["id"], auditor_headers), 200)
        tenant_pre = validate_success(api.get_tenant(tenant["id"], auditor_headers), 200)
        assert cust_pre["blocked_exposure_cents"] == 5000
        assert tenant_pre["open_exposure_cents"] == 5000

        create_approved_certificate(tenant["id"], cust["id"])
        cust_post = validate_success(api.get_customer(tenant["id"], cust["id"], auditor_headers), 200)
        tenant_post = validate_success(api.get_tenant(tenant["id"], auditor_headers), 200)
        assert cust_post["blocked_exposure_cents"] == 0, (
            "released exposure must come off the customer's blocked total")
        assert tenant_post["open_exposure_cents"] == 0, (
            "released exposure must come off the tenant's open total")


class TestCancelReleasesExposure:
    def test_cancel_held_order_restores_customer_blocked_exposure(self, api, auditor_headers, order_clerk_headers):
        """PRD §3.5: "Cancelling a held order releases its blocked exposure: the order's `uncovered_amount_cents` comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`."

        Design: Difficulty/compensating_invariant/order_cancel_releases_exposure
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        cust_0 = validate_success(api.get_customer(tenant["id"], cust["id"], auditor_headers), 200)
        assert cust_0["blocked_exposure_cents"] == 0

        order = create_held_order(tenant["id"], cust["id"],
                                  lines=(("ABC-1", 1, 5000, True),))
        cust_mid = validate_success(api.get_customer(tenant["id"], cust["id"], auditor_headers), 200)
        assert cust_mid["blocked_exposure_cents"] == 5000

        cancelled = validate_success(api.cancel_order(tenant["id"], order["id"], order_clerk_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        cust_post = validate_success(api.get_customer(tenant["id"], cust["id"], auditor_headers), 200)
        assert cust_post["blocked_exposure_cents"] == 0, (
            "cancel must restore blocked_exposure_cents to its pre-submit value")

    def test_cancel_held_order_restores_tenant_open_exposure(self, api, auditor_headers, order_clerk_headers):
        """PRD §3.5: "Cancelling a held order releases its blocked exposure: the order's `uncovered_amount_cents` comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`."

        Design: Difficulty/compensating_invariant/order_cancel_releases_exposure
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        tenant_0 = validate_success(api.get_tenant(tenant["id"], auditor_headers), 200)
        assert tenant_0["open_exposure_cents"] == 0

        order = create_held_order(tenant["id"], cust["id"],
                                  lines=(("ABC-1", 1, 5000, True),))
        tenant_mid = validate_success(api.get_tenant(tenant["id"], auditor_headers), 200)
        assert tenant_mid["open_exposure_cents"] == 5000

        cancelled = validate_success(api.cancel_order(tenant["id"], order["id"], order_clerk_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        tenant_post = validate_success(api.get_tenant(tenant["id"], auditor_headers), 200)
        assert tenant_post["open_exposure_cents"] == 0, (
            "cancel must restore open_exposure_cents to its pre-submit value")


class TestShippingGateThreshold:
    def test_ship_blocked_at_exactly_100k_exposure(self, api, fulfillment_clerk_headers, auditor_headers):
        """PRD §3.5: "And the customer's total blocked exposure must sit below the block threshold of ten million cents ($100,000.00): when the customer's `blocked_exposure_cents` is equal to or greater than $100,000.00 the ship is rejected with `ERR_BLOCKED_EXPOSURE_AT_LIMIT` (HTTP 409). The comparison is inclusive at the threshold — a customer at exactly $100,000.00 of blocked exposure cannot ship, while a customer at $99,999.99 can."

        Design: Difficulty/boundary_precision_check/block_threshold_at_exactly_100k
        """
        scenario = setup_blocked_exposure_scenario(THRESHOLDS["BLOCK_THRESHOLD_CENTS"])
        tid = scenario["tenant"]["id"]
        small = scenario["small_order"]
        assert small["status"] == "READY_TO_SHIP"
        cust = validate_success(
            api.get_customer(tid, scenario["customer"]["id"], auditor_headers), 200)
        assert cust["blocked_exposure_cents"] == THRESHOLDS["BLOCK_THRESHOLD_CENTS"]

        res = api.ship_order(tid, small["id"], fulfillment_clerk_headers)
        validate_error(res, ApiErrorId.ERR_BLOCKED_EXPOSURE_AT_LIMIT, expected_status=409)
        after = validate_success(api.get_order(tid, small["id"], auditor_headers), 200)
        assert after["status"] == "READY_TO_SHIP", "rejected ship must not move the order"

    def test_ship_allowed_one_cent_below_threshold(self, api, fulfillment_clerk_headers, auditor_headers):
        """PRD §3.5: "And the customer's total blocked exposure must sit below the block threshold of ten million cents ($100,000.00): when the customer's `blocked_exposure_cents` is equal to or greater than $100,000.00 the ship is rejected with `ERR_BLOCKED_EXPOSURE_AT_LIMIT` (HTTP 409). The comparison is inclusive at the threshold — a customer at exactly $100,000.00 of blocked exposure cannot ship, while a customer at $99,999.99 can."

        Design: Difficulty/boundary_precision_check/block_threshold_at_exactly_100k
        """
        scenario = setup_blocked_exposure_scenario(THRESHOLDS["BLOCK_THRESHOLD_CENTS"] - 1)
        tid = scenario["tenant"]["id"]
        small = scenario["small_order"]
        assert small["status"] == "READY_TO_SHIP"
        cust = validate_success(
            api.get_customer(tid, scenario["customer"]["id"], auditor_headers), 200)
        assert cust["blocked_exposure_cents"] == THRESHOLDS["BLOCK_THRESHOLD_CENTS"] - 1

        shipped = validate_success(api.ship_order(tid, small["id"], fulfillment_clerk_headers), 200)
        assert shipped["status"] == "SHIPPED"
        assert_order(shipped)
