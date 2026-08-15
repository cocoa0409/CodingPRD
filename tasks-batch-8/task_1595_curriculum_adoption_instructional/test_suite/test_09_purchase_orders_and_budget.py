"""Purchase orders: pin gating and OCC on creation, receipt/payment
boundaries, close/cancel compensation, the money-conservation invariant, and
the cycle activation gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    PROCUREMENT,
    TEST_USERS,
    assert_budget_money_conservation,
    cancel_po,
    close_po,
    create_po_fresh,
    create_purchase_order,
    get_cycle,
    get_cycle_version,
    get_ledger,
    get_purchase_order,
    issue_po,
    pay_po,
    receive_po,
    setup_cycle_distributing,
    setup_cycle_procuring,
    transition_cycle,
    transition_quote,
    validate_error,
)

DIRECTOR = TEST_USERS["curriculum_director_headers"]


class TestPoCreatePinGating:
    def test_po_create_rejected_for_rejected_pool_quote(self, api):
        """PRD §3.6: "The named quote must be the cycle's currently pinned
        selection: its status must be `SELECTED`, it must be the quote
        recorded in `pinned_quote_id`, and its current `version` must equal
        the cycle's `quote_version_pin`; a quote that was never selected, was
        superseded, or had its pin cleared by a clarification fails with
        `ERR_QUOTE_NOT_SELECTED`."

        Design: Difficulty/cross_entity_state_dependency/po_create_requires_selected_pinned_quote
        """
        ctx = setup_cycle_procuring()  # quotes[0] SELECTED, quotes[1] REJECTED
        rejected_quote = ctx["quotes"][1]
        assert rejected_quote["status"] == "REJECTED"
        validate_error(
            create_purchase_order(ctx["cycle"]["id"], rejected_quote["id"], 10),
            ApiErrorId.ERR_QUOTE_NOT_SELECTED)

    def test_po_create_rejected_after_clarification_clears_pin(self, api):
        """PRD §3.5: "sending a `SELECTED` quote to `CLARIFICATION_REQUESTED`
        clears the cycle's pin — both `pinned_quote_id` and
        `quote_version_pin` return to null — because the quote under
        clarification is no longer the version the district agreed to buy."
        PRD §3.6: "a quote that was never selected, was superseded, or had
        its pin cleared by a clarification fails with `ERR_QUOTE_NOT_SELECTED`."

        Design: Difficulty/cross_entity_state_dependency/po_create_requires_selected_pinned_quote
        """
        ctx = setup_cycle_procuring()
        selected = ctx["selected_quote"]
        transition_quote(selected["id"], "CLARIFICATION_REQUESTED")

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["pinned_quote_id"] is None, "clarification clears the pin"
        assert cycle["quote_version_pin"] is None

        validate_error(
            create_purchase_order(ctx["cycle"]["id"], selected["id"], 10),
            ApiErrorId.ERR_QUOTE_NOT_SELECTED)


class TestPoCreateOcc:
    def test_occ_po_create_stale_version_rejected(self, api):
        """PRD §2.8: "If `expected_cycle_version` does not equal the cycle's
        current `version`, the request is rejected with
        `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
        PRD §3.6: "supersedes any existing `DRAFT` purchase order of the same
        cycle (that draft moves to `SUPERSEDED`), and bumps the cycle's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_po_create_stale_version_rejected
        """
        ctx = setup_cycle_procuring(appropriation=5000)
        stale_version = get_cycle_version(ctx["cycle"]["id"])
        po1 = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                              10)  # advances the cycle version

        # A second create carrying the pre-PO1 version is stale.
        validate_error(
            create_purchase_order(ctx["cycle"]["id"],
                                  ctx["selected_quote"]["id"], 5,
                                  expected_cycle_version=stale_version),
            ApiErrorId.ERR_STALE_CYCLE_VERSION)
        assert get_purchase_order(po1["id"])["order_status"] == "DRAFT", (
            "a rejected write must not supersede the existing draft")

        # The same create with the fresh version succeeds and supersedes PO1.
        po2 = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"], 5)
        assert po2["total_amount"] == pytest.approx(50.00, abs=0.01)
        assert get_purchase_order(po1["id"])["order_status"] == "SUPERSEDED"


class TestReceiptBoundary:
    def test_over_receipt_boundary(self, api):
        """PRD §3.6: "A receipt may never push the cumulative
        `received_print_qty` beyond the ordered `print_quantity`; an
        over-receipt is rejected with `ERR_OVER_RECEIPT`."
        PRD §3.6: "advances the order to `PARTIALLY_RECEIVED` while copies
        remain outstanding, or to `RECEIVED` when the cumulative count
        reaches `print_quantity`."

        Design: Corner/calculations/over_receipt_boundary
        """
        ctx = setup_cycle_procuring(
            quote_specs=(
                {"publisher_name": "PubA", "print_unit_price": 10.00,
                 "print_quantity": 5, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
                {"publisher_name": "PubB", "print_unit_price": 12.00,
                 "print_quantity": 5, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
            ))
        po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"], 5)
        issue_po(po["id"])

        first = receive_po(po["id"], 3)
        assert first["order_status"] == "PARTIALLY_RECEIVED"

        validate_error(api.receive_purchase_order(
            po["id"], {"qty_received": 3},
            TEST_USERS["warehouse_manager_headers"]),
            ApiErrorId.ERR_OVER_RECEIPT)

        final = receive_po(po["id"], 2)  # cumulative exactly 5
        assert final["order_status"] == "RECEIVED"
        # The first receipt already flipped the cycle to DISTRIBUTING.
        assert get_cycle(ctx["cycle"]["id"])["status"] == "DISTRIBUTING"


class TestPaymentBoundary:
    def test_pay_remaining_boundary(self, api):
        """PRD §3.6: "The amount may not exceed the outstanding balance —
        `total_amount` minus `amount_paid` — or the payment fails with
        `ERR_PAYMENT_EXCEEDS_BALANCE`; paying exactly the outstanding balance
        is permitted."
        PRD §3.6: "subtracts the amount from the ledger's `encumbered_total`,
        and adds it to `expended_total`."

        Design: Corner/calculations/pay_remaining_boundary
        """
        ctx = setup_cycle_procuring(appropriation=500)
        po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                             10)  # total 100.00
        issue_po(po["id"])
        pay_po(po["id"], 60)

        validate_error(api.pay_purchase_order(po["id"], {"amount": 40.01},
                                              PROCUREMENT),
                       ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        paid = pay_po(po["id"], 40)  # exactly the remaining balance
        assert paid["payment_status"] == "PAID"

        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["encumbered_total"] == pytest.approx(0.00, abs=0.01)
        assert ledger["expended_total"] == pytest.approx(100.00, abs=0.01)
        assert ledger["available_balance"] == pytest.approx(400.00, abs=0.01)
        assert_budget_money_conservation(ledger)


class TestIssueCancelConservation:
    @staticmethod
    def _setup(api):
        """PROCURING cycle; awarded quote priced 80.00 print / 25.00 digital
        with a 0.10 bundle discount; appropriation 50000.00."""
        return setup_cycle_procuring(
            quote_specs=(
                {"publisher_name": "PubA", "print_unit_price": 80.00,
                 "print_quantity": 500, "digital_seat_rate": 25.00,
                 "digital_seat_count": 480, "bundle_discount_pct": 0.10,
                 "training_sessions": 1, "license_years": 1},
                {"publisher_name": "PubB", "print_unit_price": 90.00,
                 "print_quantity": 500, "digital_seat_rate": 25.00,
                 "digital_seat_count": 480, "bundle_discount_pct": 0,
                 "training_sessions": 0, "license_years": 0},
            ),
            appropriation=50000)

    def test_issue_encumbers_total_and_conserves_money(self, api):
        """PRD §3.6: "Issuing is the fiscal commitment: a
        `ProcurementOfficer` issues a `DRAFT` order, moving it to `ISSUED`
        and its payment dimension from `UNENCUMBERED` to `ENCUMBERED`, adding
        the full `total_amount` to the ledger's `encumbered_total`."
        PRD §2.10: "Money is conserved by invariant: at every instant, the
        appropriation total equals the sum of the available balance, the
        encumbered total, and the expended total."

        Design: Difficulty/compensating_invariant/budget_issue_cancel_conservation
        """
        ctx = self._setup(api)
        po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                             200, digital_seat_count=180)
        # print 80.00x200 = 16000.00; digital 25.00x180 = 4500.00 discounted
        # to 4050.00; total 20050.00.
        assert po["total_amount"] == pytest.approx(20050.00, abs=0.01)
        assert get_ledger(ctx["cycle"]["id"])["available_balance"] == \
            pytest.approx(50000.00, abs=0.01)

        issue_po(po["id"])
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["encumbered_total"] == pytest.approx(20050.00, abs=0.01)
        assert ledger["available_balance"] == pytest.approx(29950.00, abs=0.01)
        assert ledger["expended_total"] == pytest.approx(0.00, abs=0.01)
        assert_budget_money_conservation(ledger)

    def test_cancel_releases_encumbrance_exactly(self, api):
        """PRD §3.6: "when the order carried an encumbrance (its payment
        status was `ENCUMBERED` or `PARTIALLY_PAID`), the unpaid remainder —
        `total_amount` minus `amount_paid` — is released from the ledger's
        `encumbered_total`, while `expended_total` is left unchanged: money
        already paid stays expended."
        PRD §2.10: "Money is conserved by invariant: at every instant, the
        appropriation total equals the sum of the available balance, the
        encumbered total, and the expended total."

        Design: Difficulty/compensating_invariant/budget_issue_cancel_conservation
        """
        ctx = self._setup(api)
        po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                             200, digital_seat_count=180)
        issue_po(po["id"])
        cancelled = cancel_po(po["id"])
        assert cancelled["payment_status"] == "RELEASED"

        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["encumbered_total"] == pytest.approx(0.00, abs=0.01)
        assert ledger["available_balance"] == pytest.approx(50000.00, abs=0.01), \
            "the cancel compensates the issue exactly"
        assert ledger["expended_total"] == pytest.approx(0.00, abs=0.01)
        assert_budget_money_conservation(ledger)


class TestIssueErrorPriority:
    def test_state_error_outranks_fiscal_on_second_issue(self, api):
        """PRD §2.7: "Every request is evaluated against an ordered cascade
        of checks; a rejection at an earlier tier masks every later tier."
        PRD §2.7: "5. State: the target entity — and any cross-entity gate,
        such as the cycle status required for pilot activation — is in the
        required from-state (`ERR_INVALID_STATE`, `ERR_UNRESOLVED_PILOTS`,
        `ERR_OPEN_WORK_REMAINS`)."

        Design: Difficulty/priority_pair_validation_conflict/po_issue_state_error_outranks_fiscal
        """
        ctx = setup_cycle_procuring(
            quote_specs=(
                {"publisher_name": "PubA", "print_unit_price": 9.00,
                 "print_quantity": 100, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
                {"publisher_name": "PubB", "print_unit_price": 11.00,
                 "print_quantity": 100, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
            ),
            appropriation=1000)
        po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                             100)  # total 900.00
        issue_po(po["id"])  # encumbered 900.00, available 100.00

        # The second issue violates the from-state rule (tier 5) AND the
        # fiscal envelope (tier 12; 900.00 > 100.00) — the state error wins.
        validate_error(api.issue_purchase_order(po["id"], PROCUREMENT),
                       ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_second_issue_leaves_ledger_unchanged(self, api):
        """PRD §2.10: "Money is conserved by invariant: at every instant, the
        appropriation total equals the sum of the available balance, the
        encumbered total, and the expended total."
        PRD §2.7: "Every request is evaluated against an ordered cascade of
        checks; a rejection at an earlier tier masks every later tier."

        Design: Difficulty/priority_pair_validation_conflict/po_issue_state_error_outranks_fiscal
        """
        ctx = setup_cycle_procuring(
            quote_specs=(
                {"publisher_name": "PubA", "print_unit_price": 9.00,
                 "print_quantity": 100, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
                {"publisher_name": "PubB", "print_unit_price": 11.00,
                 "print_quantity": 100, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
            ),
            appropriation=1000)
        po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                             100)
        issue_po(po["id"])

        api.issue_purchase_order(po["id"], PROCUREMENT)  # rejected
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["encumbered_total"] == pytest.approx(900.00, abs=0.01)
        assert ledger["expended_total"] == pytest.approx(0.00, abs=0.01)
        assert ledger["available_balance"] == pytest.approx(100.00, abs=0.01)
        assert_budget_money_conservation(ledger)


class TestPoCloseGate:
    def test_po_close_requires_paid(self, api):
        """PRD §3.6: "A fully received order moves from `RECEIVED` to
        `CLOSED`, but only once its `payment_status` is `PAID`; closing
        earlier fails with `ERR_PO_NOT_CLOSABLE`."

        Design: Corner/validations/po_close_requires_paid
        """
        ctx = setup_cycle_distributing()  # PO 100.00 fully received
        pay_po(ctx["po"]["id"], 60)
        validate_error(api.transition_purchase_order(
            ctx["po"]["id"], {"to_state": "CLOSED"}, PROCUREMENT),
            ApiErrorId.ERR_PO_NOT_CLOSABLE)

        pay_po(ctx["po"]["id"], 40)
        closed = close_po(ctx["po"]["id"])
        assert closed["order_status"] == "CLOSED"
        assert get_purchase_order(ctx["po"]["id"])["payment_status"] == "PAID"


class TestCycleActivationGate:
    def test_cycle_activate_open_work_rejected(self, api):
        """PRD §3.7: "every purchase order of the cycle must be in `CLOSED`,
        `CANCELLED`, or `SUPERSEDED`, and every distribution order for the
        adopted material must be `RECEIVED` or `CANCELLED`, or the transition
        fails with `ERR_OPEN_WORK_REMAINS`."

        Design: Corner/state_machines/cycle_activate_open_work_rejected
        """
        ctx = setup_cycle_distributing()  # PO RECEIVED but unpaid: open work
        validate_error(api.transition_cycle(ctx["cycle"]["id"],
                                            {"to_state": "ACTIVE"}, DIRECTOR),
                       ApiErrorId.ERR_OPEN_WORK_REMAINS)

        pay_po(ctx["po"]["id"], ctx["po"]["total_amount"])
        close_po(ctx["po"]["id"])
        updated = transition_cycle(ctx["cycle"]["id"], "ACTIVE")
        assert updated["status"] == "ACTIVE"
