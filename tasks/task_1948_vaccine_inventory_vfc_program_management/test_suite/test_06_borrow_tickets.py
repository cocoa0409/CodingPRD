"""Inter-stock borrowing, payback reconciliation, OCC, and conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_borrow_ticket,
    create_borrow_ticket_payload,
    create_payback_payload,
    get_lot,
    get_site,
    get_ticket,
    make_borrow_ticket,
    make_private_lot,
    make_product,
    make_public_lot,
    make_public_lots,
    make_site,
    make_unit,
    open_excursion,
    record_payback_ok,
    setup_open_borrow,
    validate_error,
)

VM = TEST_USERS["vaccine_manager_headers"]


class TestBorrowOpening:
    def test_same_stock_borrow_rejected(self, api):
        """PRD §3.7: "The two lots must sit on opposite sides of the divide
        consistently with the declared direction: a same-stock borrow, or a
        direction inconsistent with the two lots' `stock_type` values, is
        rejected with `ERR_SAME_STOCK_BORROW`."

        Design: Corner/validations/same_stock_borrow_rejected
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        pub = make_public_lots(site["id"], unit["id"], product["id"], [6, 4])
        lot_a, lot_b = pub["lot_ids"]
        resp = api.create_borrow_ticket(
            site["id"],
            create_borrow_ticket_payload(
                lot_a, lot_b, direction="PUBLIC_FROM_PRIVATE", borrowed_quantity=2
            ),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_STOCK_BORROW)

    def test_open_moves_lender_on_hand_but_not_borrower(self, api):
        """PRD §3.7: "Opening the ticket moves value but not product between
        the books: the lender lot's `quantity_on_hand` decreases by
        `borrowed_quantity` as the physical doses leave it, while the borrower
        lot's `quantity_borrowed_in` increases by the same amount to record the
        IOU — its `quantity_on_hand` does not change, because the physical
        doses went into a patient, not onto a shelf."

        Design: Difficulty/compensating_invariant/payback_conserves_doses_across_paying_and_lender_lots
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PUBLIC_FROM_PRIVATE")
        pub = get_lot(ctx["pub_lot_id"])
        priv = get_lot(ctx["priv_lot"]["id"])
        assert pub["quantity_on_hand"] == 10, "borrower lot on-hand is unchanged"
        assert pub["quantity_borrowed_in"] == 4
        assert priv["quantity_on_hand"] == 4, "lender lot loses the 4 physical doses"
        # The 4 borrowed doses are gone from inventory: 10 + 4 = 14 remain.
        assert pub["quantity_on_hand"] + priv["quantity_on_hand"] == 14

    def test_full_payback_restores_lender_and_conserves_total(self, api):
        """PRD §3.7: "A successful payback adds the quantity to
        `paid_back_quantity`, draws it out of the paying lot's
        `quantity_on_hand`, returns it to the lender lot's `quantity_on_hand`,
        and amortizes the borrower lot's `quantity_borrowed_in` by the same
        amount".

        Design: Difficulty/compensating_invariant/payback_conserves_doses_across_paying_and_lender_lots
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PUBLIC_FROM_PRIVATE")
        ticket = ctx["ticket"]
        record_payback_ok(
            ctx["site"]["id"], ticket["id"], 4,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=ticket["version"],
        )
        pub = get_lot(ctx["pub_lot_id"])
        priv = get_lot(ctx["priv_lot"]["id"])
        assert pub["quantity_on_hand"] == 6, "paying lot gives up 4 doses"
        assert pub["quantity_borrowed_in"] == 0, "borrower IOU fully amortized"
        assert priv["quantity_on_hand"] == 8, "lender lot is made whole"
        # Payback shifts doses between lots; it never creates or destroys them.
        assert pub["quantity_on_hand"] + priv["quantity_on_hand"] == 14


class TestLendingBalanceVariants:
    def test_balance_ignores_private_from_public_tickets(self, api):
        """PRD §2.7: "The second balance is `private_lending_balance`: the
        sum, across all `OPEN` and `PARTIALLY_REPAID` borrow tickets at the
        site whose `direction` is `PUBLIC_FROM_PRIVATE`, of each ticket's
        `borrowed_quantity` minus its `paid_back_quantity`." A site holding
        only a PRIVATE_FROM_PUBLIC ticket owes nothing to private stock.

        Design: Difficulty/dual_variant_calc/private_lending_balance_net_vs_gross_directional
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PRIVATE_FROM_PUBLIC")
        site = get_site(ctx["site"]["id"])
        assert site["private_lending_balance"] == 0, (
            "only PUBLIC_FROM_PRIVATE tickets feed private_lending_balance"
        )

    def test_private_from_public_borrow_moves_physical_doses_only(self, api):
        """PRD §3.7: "the lender lot's `quantity_on_hand` decreases by
        `borrowed_quantity` as the physical doses leave it, while the borrower
        lot's `quantity_borrowed_in` increases by the same amount to record the
        IOU — its `quantity_on_hand` does not change".

        Design: Difficulty/dual_variant_calc/private_lending_balance_net_vs_gross_directional
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PRIVATE_FROM_PUBLIC")
        pub = get_lot(ctx["pub_lot_id"])
        priv = get_lot(ctx["priv_lot"]["id"])
        assert pub["quantity_on_hand"] == 6, "public lender gives up 4 doses"
        assert priv["quantity_on_hand"] == 8, "borrower lot on-hand unchanged"
        assert priv["quantity_borrowed_in"] == 4, "borrower lot carries the IOU"


class TestPaybackBoundary:
    def test_exact_remaining_payback_closes_ticket(self, api):
        """PRD §3.7: "a payback of exactly the remaining balance is allowed
        and closes the ticket" and "When the cumulative payback equals
        `borrowed_quantity` the ticket moves automatically to `REPAID`".

        Design: Difficulty/boundary_precision_check/payback_remaining_boundary_exact_remaining_closes_ticket
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PUBLIC_FROM_PRIVATE")
        ticket = ctx["ticket"]
        result = record_payback_ok(
            ctx["site"]["id"], ticket["id"], 4,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=ticket["version"],
        )
        assert_borrow_ticket(result)
        assert result["status"] == "REPAID"
        assert result["paid_back_quantity"] == 4

    def test_payback_on_repaid_ticket_rejected(self, api):
        """PRD §3.7: "the ticket must be `OPEN` or `PARTIALLY_REPAID`
        (`ERR_INVALID_STATE`)" and "`REPAID` and `VOIDED` are terminal."

        Design: Difficulty/boundary_precision_check/payback_remaining_boundary_exact_remaining_closes_ticket
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PUBLIC_FROM_PRIVATE")
        ticket = ctx["ticket"]
        record_payback_ok(
            ctx["site"]["id"], ticket["id"], 4,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=ticket["version"],
        )
        current = get_ticket(ticket["id"])
        resp = api.record_payback(
            ctx["site"]["id"], ticket["id"],
            create_payback_payload(1, ctx["pub_lot_id"], current["version"]),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_payback_above_remaining_rejected(self, api):
        """PRD §3.7: "the cumulative `paid_back_quantity` plus this
        `payback_quantity` must not exceed `borrowed_quantity`
        (`ERR_PAYBACK_EXCEEDS_BORROWED`)".

        Design: Difficulty/boundary_precision_check/payback_remaining_boundary_exact_remaining_closes_ticket
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PUBLIC_FROM_PRIVATE")
        ticket = ctx["ticket"]
        record_payback_ok(
            ctx["site"]["id"], ticket["id"], 3,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=ticket["version"],
        )
        current = get_ticket(ticket["id"])
        assert current["status"] == "PARTIALLY_REPAID"
        resp = api.record_payback(
            ctx["site"]["id"], ticket["id"],
            create_payback_payload(2, ctx["pub_lot_id"], current["version"]),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_PAYBACK_EXCEEDS_BORROWED)


class TestPaybackLotAvailability:
    def _setup_two_units(self):
        site = make_site()
        u1 = make_unit(site["id"], unit_label="U1")
        u2 = make_unit(site["id"], unit_label="U2")
        product = make_product()
        pub = make_public_lot(site["id"], u2["id"], product["id"], 10)
        priv = make_private_lot(site["id"], u1["id"], product["id"],
                                quantity_on_hand=8)
        ticket = make_borrow_ticket(
            site["id"], priv["id"], pub["lot_id"], "PUBLIC_FROM_PRIVATE", 4
        )
        return {"site": site, "u1": u1, "u2": u2, "pub_lot_id": pub["lot_id"],
                "priv_lot": priv, "ticket": ticket}

    def test_partial_payback_lands_in_partially_repaid(self, api):
        """PRD §3.7: "any smaller payment lands it in (or keeps it in)
        `PARTIALLY_REPAID`, the self-loop permitting as many partial paybacks
        as needed."

        Design: Difficulty/cross_entity_state_dependency/borrow_ticket_payback_gated_by_lot_availability
        """
        ctx = self._setup_two_units()
        result = record_payback_ok(
            ctx["site"]["id"], ctx["ticket"]["id"], 2,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=ctx["ticket"]["version"],
        )
        assert result["status"] == "PARTIALLY_REPAID"
        assert result["paid_back_quantity"] == 2

    def test_payback_rejected_when_paying_lot_quarantined(self, api):
        """PRD §3.7: "the paying lot must be `AVAILABLE`
        (`ERR_LOT_NOT_AVAILABLE`) holding at least `payback_quantity` doses
        (`ERR_INSUFFICIENT_STOCK`)". The ticket stays open; the failure is on
        the paying lot's state.

        Design: Difficulty/cross_entity_state_dependency/borrow_ticket_payback_gated_by_lot_availability
        """
        ctx = self._setup_two_units()
        record_payback_ok(
            ctx["site"]["id"], ctx["ticket"]["id"], 2,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=ctx["ticket"]["version"],
        )
        open_excursion(ctx["u2"]["id"], recorded_at="2026-08-03T10:00:00Z")
        current = get_ticket(ctx["ticket"]["id"])
        resp = api.record_payback(
            ctx["site"]["id"], ctx["ticket"]["id"],
            create_payback_payload(2, ctx["pub_lot_id"], current["version"]),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)


class TestVoidAndOcc:
    def test_void_blocked_after_partial_payback(self, api):
        """PRD §3.7: "A ticket opened in error can be voided, but only while
        it is `OPEN` (`ERR_INVALID_STATE`), only while `paid_back_quantity` is
        still zero (`ERR_TICKET_HAS_PAYBACK`)". A partial payback moves the
        ticket to `PARTIALLY_REPAID`, and PRD §2.12 runs the state check
        (`ERR_INVALID_STATE`) before endpoint-specific business rules.

        Design: Corner/state_machines/borrow_ticket_void_blocked_after_partial_payback
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PUBLIC_FROM_PRIVATE")
        record_payback_ok(
            ctx["site"]["id"], ctx["ticket"]["id"], 1,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=ctx["ticket"]["version"],
        )
        resp = api.void_borrow_ticket(ctx["site"]["id"], ctx["ticket"]["id"], VM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_stale_ticket_version_rejected(self, api):
        """PRD §2.8: "Recording a payback against a borrow ticket requires the
        field `expected_borrow_ticket_version`, carrying the ticket's `version`
        as the caller last observed it. If the ticket's current `version`
        differs — for example because another partial payback was posted after
        the caller's read, advancing the version and changing
        `paid_back_quantity` — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_payback_stale_ticket_version_returns_412
        """
        ctx = setup_open_borrow(public_doses=10, private_doses=8, borrow_qty=4,
                                direction="PUBLIC_FROM_PRIVATE")
        original_version = ctx["ticket"]["version"]
        record_payback_ok(
            ctx["site"]["id"], ctx["ticket"]["id"], 1,
            paying_lot_id=ctx["pub_lot_id"],
            expected_borrow_ticket_version=original_version,
        )
        resp = api.record_payback(
            ctx["site"]["id"], ctx["ticket"]["id"],
            create_payback_payload(1, ctx["pub_lot_id"], original_version),
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
