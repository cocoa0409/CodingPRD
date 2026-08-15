"""Scan-event ingest: match/unmatch resolution, negative valuation on returns,
compensating voids, idempotency keys, append-only shape, and synchronous
consistency of side effects."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_scan_event,
    get_balance,
    get_success_data,
    new_price_directive,
    new_statement,
    post_matched_sale,
    post_scan,
    setup_shop,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["jobber_admin_headers"]


class TestScanValuation:
    def test_return_scan_negative_valuation(self, api):
        """PRD section 3.6: "Line value follows the event type: a `SALE`
        contributes its unit price times `quantity` as positive
        `line_value_cents`; a `RETURN` contributes the same magnitude negated;
        a `VOID` copies its target's `unit_price_cents` and `is_promo_priced`
        verbatim and contributes the negation of the target's
        `line_value_cents`."

        Design: Corner/calculations/return_scan_negative_valuation
        """
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 5, "2026-08-01T09:00:00Z",
                          client_event_id="rt-sale")
        ret = get_success_data(post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="RETURN", quantity=2,
            scanned_at="2026-08-01T10:00:00Z", client_event_id="rt-ret"))
        assert ret["line_value_cents"] == -400, (
            "negative valuation at the same resolved price 200")
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["gross_scanned_sales_cents"] == 600, "1000 - 400"
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == -3
        assert balance["lifetime_scanned_units"] == 5
        assert balance["lifetime_customer_return_units"] == 2
        assert balance["stock_posture"] == "DEPLETED", (
            "on-hand below zero reads DEPLETED")


class TestUnmatchedScanLifecycle:
    def test_unmatched_excluded_then_resolved(self, api):
        """PRD section 3.6: "If any of those conditions fails, the scan is
        still persisted but lands `UNMATCHED`: no price resolution occurs,
        `unit_price_cents` remains unset, `line_value_cents` and
        `jobber_funding_cents` carry no value, `is_promo_priced` is false, and
        nothing touches inventory."
        PRD section 3.9: "First, `gross_scanned_sales_cents` sums
        `line_value_cents` over the matched scans whose `scanned_at` falls in
        the window."

        Design: Corner/calculations/unmatched_scan_excluded_then_resolved
        """
        # No price directive at ingest: the scan lands UNMATCHED.
        ctx = setup_shop(with_directive=False,
                         agreement_overrides={"estimated_shrink_rate": 0.0})
        scan = get_success_data(post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="SALE", quantity=4, scanned_at="2026-08-01T09:00:00Z",
            client_event_id="fl-1"))
        assert scan["status"] == "UNMATCHED"
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["gross_scanned_sales_cents"] == 0, (
            "UNMATCHED scans are excluded from the statement input set")
        # Repair the master data, then resolve.
        new_price_directive(ctx["agreement"]["id"], ctx["product"]["id"],
                            price_cents=200)
        resolved = validate_success(
            api.resolve_scan_event(scan["id"], ADMIN), 200)
        assert resolved["status"] == "MATCHED"
        assert resolved["unit_price_cents"] == 200

    def test_scan_on_suspended_agreement_goes_unmatched(self, api):
        """PRD section 3.6: "A scan lands `MATCHED` when all of the following
        hold: the agreement is `ACTIVE`, the product belongs to the agreement's
        program, and an `EFFECTIVE` price directive exists for the agreement
        and product with `effective_from` no later than `scanned_at`."
        PRD section 3.6: "A `JobberAdmin` may later resolve an `UNMATCHED` scan
        once the master data has been fixed; resolution re-runs the match and,
        when the conditions now hold, applies exactly the same valuation,
        inventory, and reorder effects as a natively matched scan."

        Design: Corner/validations/scan_on_suspended_agreement_goes_unmatched
        """
        ctx = setup_shop()
        validate_success(api.suspend_agreement(
            ctx["agreement"]["id"], {"reason": "audit review"}, ADMIN), 200)
        scan = get_success_data(post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="SALE", quantity=2, scanned_at="2026-08-01T10:00:00Z",
            client_event_id="ss-1"))
        assert scan["status"] == "UNMATCHED", (
            "persisted with 201, not an error, despite the SUSPENDED agreement")
        validate_success(api.resume_agreement(ctx["agreement"]["id"], ADMIN),
                         200)
        resolved = validate_success(
            api.resolve_scan_event(scan["id"], ADMIN), 200)
        assert resolved["status"] == "MATCHED"
        assert resolved["unit_price_cents"] == 200


class TestVoidTargetRules:
    def test_void_of_unmatched_scan_rejected(self, api):
        """PRD section 3.6: "The exception is the void family: a `VOID` whose
        target is missing, `UNMATCHED`, itself a `VOID`, on a different
        agreement, or of mismatched quantity is not persisted at all — it is
        rejected outright with `ERR_VOID_TARGET_INVALID`."

        Design: Corner/state_machines/scan_void_of_unmatched_rejected
        """
        # No price directive: the target scan lands UNMATCHED.
        ctx = setup_shop(with_directive=False)
        target = get_success_data(post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="SALE", quantity=3, scanned_at="2026-08-01T09:00:00Z",
            client_event_id="vt-1"))
        assert target["status"] == "UNMATCHED"
        res = post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="VOID", quantity=3, scanned_at="2026-08-01T09:05:00Z",
            client_event_id="vt-void", void_of_event_id=target["id"])
        validate_error(res, ApiErrorId.ERR_VOID_TARGET_INVALID)

    def test_double_void_rejected(self, api):
        """PRD section 3.6: "The exception is the void family: a `VOID` whose
        target is missing, `UNMATCHED`, itself a `VOID`, on a different
        agreement, or of mismatched quantity is not persisted at all — it is
        rejected outright with `ERR_VOID_TARGET_INVALID`."

        Design: Corner/errors/double_void_rejected
        """
        ctx = setup_shop()
        sale = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            5, "2026-08-01T10:00:00Z", client_event_id="dv-sale")
        void1 = get_success_data(post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="VOID", quantity=5, scanned_at="2026-08-01T10:05:00Z",
            client_event_id="dv-void1", void_of_event_id=sale["id"]))
        assert void1["status"] == "MATCHED"
        res = post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="VOID", quantity=5, scanned_at="2026-08-01T10:10:00Z",
            client_event_id="dv-void2", void_of_event_id=void1["id"])
        validate_error(res, ApiErrorId.ERR_VOID_TARGET_INVALID)


class TestScanIdempotency:
    def test_duplicate_client_event_id_rejected(self, api):
        """PRD section 3.6: "a `client_event_id` that serves as the retailer's
        idempotency key: a `client_event_id` already ingested for the same
        agreement is rejected with `ERR_DUPLICATE_SCAN_EVENT`."

        Design: Corner/validations/duplicate_scan_event_rejected
        """
        ctx = setup_shop()
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 1, "2026-08-01T09:00:00Z",
                          client_event_id="dup-1")
        res = post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="SALE", quantity=1, scanned_at="2026-08-01T09:00:00Z",
            client_event_id="dup-1")
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SCAN_EVENT)
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["lifetime_scanned_units"] == 1, (
            "the replay was not double-counted")


class TestScanEventShape:
    def test_scan_event_has_no_version_fields(self, api):
        """PRD section 2.4: "A `ScanEvent` is an append-only ledger entry: it
        carries `id` and `created_at` only, and both `updated_at` and
        `version` are absent. Scan events are never updated or deleted after
        ingest; any correction happens exclusively through a compensating void
        event, as described in §3.6."

        Design: Corner/entities/scan_event_has_no_version_fields
        """
        ctx = setup_shop()
        scan = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            1, "2026-08-01T09:00:00Z", client_event_id="imm-1")
        assert_scan_event(scan)


class TestScanConsistency:
    def test_ingest_response_carries_matched_valuation(self, api):
        """PRD section 3.6: "Ingest resolves synchronously."
        PRD section 2.10: "All such side effects are atomic within the
        triggering request — a cascade either applies in full or the request
        fails outright."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        ctx = setup_shop()
        scan = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            2, "2026-08-01T10:00:00Z", client_event_id="ic-1")
        assert scan["status"] == "MATCHED"
        assert scan["unit_price_cents"] == 200
        assert scan["line_value_cents"] == 400
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == -2, (
            "side effects are visible in the same request epoch")


class TestScanRbac:
    def test_jobber_admin_cannot_ingest_scan(self, api):
        """PRD section 2.1: "Each endpoint declares the roles authorized to
        invoke it; a request whose `X-User-Role` is not in the endpoint's role
        list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /scan-events lists RetailerManager as its only
        authorized role.

        Design: Corner/rbac/rbac_jobber_admin_cannot_ingest_scan
        """
        ctx = setup_shop()
        res = api.create_scan_event(
            {"store_agreement_id": ctx["agreement"]["id"],
             "product_id": ctx["product"]["id"], "event_type": "SALE",
             "quantity": 1, "scanned_at": "2026-08-01T10:00:00Z",
             "client_event_id": "rs-1"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestSaleVoidConservation:
    def test_void_negates_line_value_and_statement_gross(self, api):
        """PRD section 3.6: "a `VOID` copies its target's `unit_price_cents`
        and `is_promo_priced` verbatim and contributes the negation of the
        target's `line_value_cents`."
        PRD section 3.9: "Second, `scanned_units` nets the window's unit
        movement — sales add, returns subtract, and voids reverse their
        target's quantity — and `promo_scan_units` counts the units scanned at
        promo price."

        Design: Difficulty/compensating_invariant/sale_then_void_cents_conserved
        """
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        sale = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            5, "2026-08-01T10:00:00Z", client_event_id="sale-1")
        assert sale["line_value_cents"] == 1000
        void = get_success_data(post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="VOID", quantity=5, scanned_at="2026-08-01T10:05:00Z",
            client_event_id="void-1", void_of_event_id=sale["id"]))
        assert void["line_value_cents"] == -1000, (
            "exact negation of the target")
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["gross_scanned_sales_cents"] == 0
        assert statement["scanned_units"] == 0
        assert statement["retailer_margin_cents"] == 0
        assert statement["net_payable_to_jobber_cents"] == 0

    def test_void_restores_inventory_counters(self, api):
        """PRD section 3.6: "a `VOID` reverses its target's units and
        counters."
        PRD section 3.6: "The balance obeys one invariant: on hand equals
        delivered minus scanned plus customer returns minus shrink minus vendor
        returns, and it may legitimately go negative when unscanned shelf stock
        sells through."

        Design: Difficulty/compensating_invariant/sale_then_void_cents_conserved
        """
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        sale = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            5, "2026-08-01T10:00:00Z", client_event_id="sale-1")
        get_success_data(post_scan(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            event_type="VOID", quantity=5, scanned_at="2026-08-01T10:05:00Z",
            client_event_id="void-1", void_of_event_id=sale["id"]))
        balance = get_balance(ctx["agreement"]["id"], ctx["product"]["id"])
        assert balance["on_hand_units"] == 0, "SALE -5 then VOID +5"
        assert balance["lifetime_scanned_units"] == 0
