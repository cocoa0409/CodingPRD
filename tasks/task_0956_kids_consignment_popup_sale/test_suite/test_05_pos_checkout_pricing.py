"""POS tickets: presale pass gating, scans, checkout rules, validation order.

NOTE: the difficulty instance combinatorial_formula/per_line_rounding_then_sum
is intentionally NOT translated: its setup tags items at price_cents 525, which
violates the PRD §3.3 rule that the tag price "must be a whole multiple of 50
cents" — no PRD-faithful implementation can create those items, so the
instance's precomputed line values (446/401/802) are unreachable. Gap logged.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    checkout_transaction,
    close_intake,
    create_event,
    get_event,
    get_item,
    get_transaction,
    open_intake,
    open_transaction,
    scan_barcode,
    setup_item_on_floor,
    start_presale,
    start_sale,
    validate_error,
    validate_success,
)


class TestPresalePassGating:

    def test_presale_transaction_without_pass_rejected(self, api, cashier_headers):
        """PRD §3.8: "During `PRESALE_DAY` the pass is mandatory: opening a ticket without a valid `ACTIVE` pass is rejected with `ERR_PRESALE_PASS_REQUIRED` (HTTP 403), and a pass that has been revoked or is otherwise not `ACTIVE` fails with `ERR_PASS_NOT_ACTIVE`."
        PRD §3.8: "At creation the server snapshots the pass's `discount_pct` into the transaction's `pass_discount_pct` — 0 when no pass is attached — so later revocation or reissuance can never rewrite an open ticket's economics."

        Design: Corner/validations/presale_transaction_without_pass_rejected
        """
        event = create_event()
        open_intake(event["id"])
        close_intake(event["id"])
        start_presale(event["id"])

        resp = api.create_pos_transaction({"sale_event_id": event["id"]},
                                          cashier_headers)
        validate_error(resp, ApiErrorId.ERR_PRESALE_PASS_REQUIRED)

        start_sale(event["id"])
        tx = open_transaction(event["id"])
        assert tx["status"] == "OPEN", (
            "During SALE_ACTIVE a ticket without a pass must open"
        )
        assert tx["pass_discount_pct"] == 0, (
            "pass_discount_pct snapshots to 0 when no pass is attached"
        )


class TestScanErrors:

    def test_scan_unknown_barcode_returns_404(self, api, cashier_headers):
        """PRD §3.8: "The barcode must resolve to an item of the transaction's own event, or the scan is rejected with `ERR_BARCODE_NOT_FOUND`, and the item must currently be `ON_FLOOR`, or the scan fails with `ERR_ITEM_NOT_ON_FLOOR`."

        Design: Corner/errors/scan_unknown_barcode_returns_404
        """
        event = create_event()
        open_intake(event["id"])
        close_intake(event["id"])
        start_presale(event["id"])
        start_sale(event["id"])
        tx = open_transaction(event["id"])

        resp = api.scan_line(tx["id"], {"barcode": "C9999-0001"}, cashier_headers)
        validate_error(resp, ApiErrorId.ERR_BARCODE_NOT_FOUND)


class TestCheckoutRules:

    def _open_ticket_with_1000_line(self):
        ctx = setup_item_on_floor(price_cents=1000)
        tx = open_transaction(ctx["event"]["id"])
        scan_barcode(tx["id"], ctx["barcode"])
        return ctx, tx

    def test_insufficient_tender_alone_returns_402(self, api, cashier_headers):
        """PRD §3.8: "It requires at least one current line — an empty ticket is rejected with `ERR_EMPTY_TRANSACTION` — and the tendered amount must cover the total: submitting `tendered_cents` below `total_cents` fails with `ERR_INSUFFICIENT_TENDER` (HTTP 402)."

        Design: Corner/errors/insufficient_tender_alone_returns_402
        """
        ctx, tx = self._open_ticket_with_1000_line()
        resp = api.checkout(tx["id"], {"tendered_cents": 500}, cashier_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TENDER)

        assert get_transaction(tx["id"])["status"] == "OPEN", (
            "A rejected checkout must leave the ticket OPEN"
        )
        assert get_item(ctx["item"]["id"])["status"] == "IN_CART", (
            "A rejected checkout must leave the scanned item IN_CART"
        )

    def test_second_checkout_on_completed_transaction_rejected(self, api, cashier_headers):
        """PRD §2.8: "fifth, the target entity's lifecycle state (the `ERR_*_WRONG_STATE` family, plus `ERR_TRANSACTION_NOT_OPEN`, `ERR_PASS_NOT_ACTIVE`, and `ERR_SETTLEMENTS_LOCKED`)".
        PRD §2.10: "the event's `sold_gross_cents` always equals the sum of `total_cents` over the event's `COMPLETED` transactions".

        Design: Corner/state_machines/completed_transaction_second_checkout_rejected
        """
        ctx, tx = self._open_ticket_with_1000_line()
        checkout_transaction(tx["id"], 1000)

        resp = api.checkout(tx["id"], {"tendered_cents": 1000}, cashier_headers)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_OPEN)

        assert get_event(ctx["event"]["id"])["sold_gross_cents"] == 1000, (
            "A rejected second checkout must not double-count the sale"
        )

    def test_checkout_response_immediately_consistent(self, api, cashier_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.8: "On success the ticket records `tendered_cents`, computes `change_cents` as the tendered amount minus the total, and moves `OPEN` → `COMPLETED`."

        Design: Corner/consistency_model/checkout_response_immediately_consistent
        """
        ctx = setup_item_on_floor(price_cents=1500)
        tx = open_transaction(ctx["event"]["id"])
        scan_barcode(tx["id"], ctx["barcode"])

        resp = api.checkout(tx["id"], {"tendered_cents": 2000}, cashier_headers)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        assert data["subtotal_cents"] == 1500
        assert data["total_cents"] == 1500
        assert data["discount_cents"] == 0
        assert data["tendered_cents"] == 2000
        assert data["change_cents"] == 500, (
            "The checkout 200 response itself must carry the final totals"
        )


class TestValidationPrecedence:

    def _voided_ticket(self, api, cashier_headers):
        event = create_event()
        open_intake(event["id"])
        close_intake(event["id"])
        start_presale(event["id"])
        start_sale(event["id"])
        tx = open_transaction(event["id"])
        validate_success(api.void_transaction(tx["id"], cashier_headers))
        assert get_transaction(tx["id"])["status"] == "VOIDED"
        return tx

    def test_voided_checkout_state_error_beats_tender(self, api, cashier_headers):
        """PRD §2.8: "fifth, the target entity's lifecycle state (the `ERR_*_WRONG_STATE` family, plus `ERR_TRANSACTION_NOT_OPEN`, `ERR_PASS_NOT_ACTIVE`, and `ERR_SETTLEMENTS_LOCKED`)" and "ninth, at checkout only, tender sufficiency (`ERR_INSUFFICIENT_TENDER`)".

        Design: Difficulty/priority_pair_validation_conflict/voided_transaction_checkout_state_beats_tender
        """
        tx = self._voided_ticket(api, cashier_headers)

        # tendered_cents 0 violates both the state rule and the fiscal rule.
        resp = api.checkout(tx["id"], {"tendered_cents": 0}, cashier_headers)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_OPEN)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_INSUFFICIENT_TENDER, (
            "The state rule (fifth) outranks the fiscal rule (ninth)"
        )

    def test_voided_checkout_with_sufficient_tender_still_state_error(
        self, api, cashier_headers
    ):
        """PRD §2.8: "fifth, the target entity's lifecycle state (the `ERR_*_WRONG_STATE` family, plus `ERR_TRANSACTION_NOT_OPEN`, `ERR_PASS_NOT_ACTIVE`, and `ERR_SETTLEMENTS_LOCKED`)" and "ninth, at checkout only, tender sufficiency (`ERR_INSUFFICIENT_TENDER`)".

        Design: Difficulty/priority_pair_validation_conflict/voided_transaction_checkout_state_beats_tender
        """
        tx = self._voided_ticket(api, cashier_headers)

        # Even a tender that would cover any total cannot rescue a VOIDED ticket.
        resp = api.checkout(tx["id"], {"tendered_cents": 999999}, cashier_headers)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_OPEN)
