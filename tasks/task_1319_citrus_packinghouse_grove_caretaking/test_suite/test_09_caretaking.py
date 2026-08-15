"""Caretaking services and grower billing: rate tiers, the chemical markup,
per-line rounding order, enrollment and acreage gates, invoice payments,
dispute/reissue cycles, and grower-standing gates."""
from test_helpers import (
    ApiErrorId,
    assert_service_order,
    create_caretaking_order_payload,
    create_completed_order,
    create_draft_invoice,
    get_caretaking_invoice,
    get_caretaking_order,
    get_grower,
    get_success_data,
    set_clock,
    setup_enrolled_grove,
    setup_issued_invoice,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import create_grove, create_grower
from test_helpers.test_users import TEST_USERS, make_grower_headers

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestRollupRoundingOrder:
    def test_per_line_rounding_of_prune_lines(self, api):
        """PRD §3.7: "the system derives the order's `rate_tier` from the
        grove's `acreage` — `SMALL` below 40 acres, `MEDIUM` from 40 through
        120 acres inclusive, `LARGE` above 120 — and computes
        `line_amount_cents` as two components, each rounded half-up to whole
        cents before they are summed, never re-rounded afterward. The labor
        component is `acres_treated` multiplied by the per-acre rate for the
        service and tier". PRUNE on SMALL bills 5500 cents per acre, so
        round_half_up(3.333 * 5500) = 18332.

        Design: Difficulty/combinatorial_formula/caretaking_rollup_rounding_order
        """
        scenario = setup_enrolled_grove("CR1", acreage=30)
        first = create_completed_order(scenario["grove"]["id"], "PRUNE",
                                       "2026-08-01", 3.333)
        second = create_completed_order(scenario["grove"]["id"], "PRUNE",
                                        "2026-08-01", 3.333)
        assert first["rate_tier"] == "SMALL"
        assert first["line_amount_cents"] == 18332, \
            "round_half_up(3.333 * 5500) per line"
        assert second["line_amount_cents"] == 18332

    def test_invoice_total_sums_rounded_lines(self, api):
        """PRD §3.7: "`total_cents` is set to the sum of the member orders'
        `line_amount_cents`" and "each rounded half-up to whole cents before
        they are summed, never re-rounded afterward" — two lines of 18332 sum
        to 36664, not the 36663 a sum-then-round order would give. PRD §3.7:
        "On issue, every swept order moves `COMPLETED` → the terminal
        `INVOICED` with its `invoice_id` set, and the grower's
        `caretaking_balance_cents` rises by `total_cents`".

        Design: Difficulty/combinatorial_formula/caretaking_rollup_rounding_order
        """
        scenario = setup_enrolled_grove("CR1B", acreage=30)
        first = create_completed_order(scenario["grove"]["id"], "PRUNE",
                                       "2026-08-01", 3.333)
        second = create_completed_order(scenario["grove"]["id"], "PRUNE",
                                        "2026-08-01", 3.333)
        invoice = create_draft_invoice(scenario["grower"]["id"])
        assert invoice["total_cents"] == 36664, \
            "per-line rounded then summed; NOT round_half_up(36663.0)"
        assert set(invoice["line_order_ids"]) == {first["id"], second["id"]}
        issued = validate_success(api_client.issue_caretaking_invoice(
            invoice["id"], ACCOUNTANT))
        assert issued["status"] == "ISSUED"
        for order_id in (first["id"], second["id"]):
            order = get_caretaking_order(order_id)
            assert order["status"] == "INVOICED"
            assert order["invoice_id"] == invoice["id"]
        assert get_grower(scenario["grower"]["id"])[
            "caretaking_balance_cents"] == 36664


class TestRateTierBoundaries:
    def test_caretaking_rate_tier_boundaries(self, api):
        """PRD §3.7: "`SMALL` below 40 acres, `MEDIUM` from 40 through 120
        acres inclusive, `LARGE` above 120" and the per-acre MOW rates
        "`MOW` 1800, 1700, 1500" — one MOW acre at each edge bills
        1800 / 1700 / 1700 / 1500.

        Design: Corner/calculations/caretaking_rate_tier_boundaries
        """
        scenario = setup_enrolled_grove("CA5", acreage=39.99)
        grower_id = scenario["grower"]["id"]
        grove_40 = create_grove(grower_id, "M1", "HAMLIN", 40, "POLK", True)
        grove_120 = create_grove(grower_id, "M2", "HAMLIN", 120, "POLK", True)
        grove_120_01 = create_grove(grower_id, "L1", "HAMLIN", 120.01, "POLK", True)
        cases = [
            (scenario["grove"]["id"], "SMALL", 1800),   # 39.99 acres
            (grove_40["id"], "MEDIUM", 1700),           # 40 acres (lower edge)
            (grove_120["id"], "MEDIUM", 1700),          # 120 acres (upper edge)
            (grove_120_01["id"], "LARGE", 1500),        # 120.01 acres
        ]
        for grove_id, tier, expected_line in cases:
            order = create_completed_order(grove_id, "MOW", "2026-08-01", 1)
            assert order["rate_tier"] == tier, f"grove {grove_id} tier"
            assert order["line_amount_cents"] == expected_line, \
                f"{tier} MOW rate x 1 acre"


class TestChemicalMarkup:
    def test_chemical_markup_only_for_spray(self, api):
        """PRD §3.7: "an optional `chemical_cost_cents` that defaults to zero
        and must remain zero unless the service is `SPRAY`
        (`ERR_CHEMICAL_COST_NOT_ALLOWED`)" and "the chemical component,
        present only for `SPRAY`, is `chemical_cost_cents` marked up by twelve
        percent". A 10-acre SMALL SPRAY with 5000 chemical bills
        42000 + round_half_up(5000 * 1.12) = 47600.

        Design: Corner/calculations/chemical_markup_only_for_spray
        """
        scenario = setup_enrolled_grove("CA6", acreage=30)
        resp = api_client.create_caretaking_order(
            create_caretaking_order_payload(scenario["grove"]["id"], "FERTILIZE",
                                            "2026-08-01", 5,
                                            chemical_cost_cents=5000),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_CHEMICAL_COST_NOT_ALLOWED)
        order = create_completed_order(scenario["grove"]["id"], "SPRAY",
                                       "2026-08-01", 10,
                                       chemical_cost_cents=5000)
        assert order["line_amount_cents"] == 42000 + 5600
        assert order["chemical_cost_cents"] == 5000


class TestEnrollmentAndAcreageGates:
    def test_caretaking_requires_enrollment(self, api):
        """PRD §3.7: "The grove must be enrolled in the program —
        `caretaking_enrolled` true, else `ERR_CARETAKING_NOT_ENROLLED`".

        Design: Corner/validations/caretaking_requires_enrollment
        """
        set_clock("2026-08-01T00:00:00Z")
        grower = create_grower("GR-V9", "Enrollment Groves")
        grove_no = create_grove(grower["id"], "N1", "HAMLIN", 30, "POLK", False)
        grove_yes = create_grove(grower["id"], "Y1", "HAMLIN", 30, "POLK", True)
        resp = api_client.create_caretaking_order(
            create_caretaking_order_payload(grove_no["id"], "MOW", "2026-08-01", 5),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_CARETAKING_NOT_ENROLLED)
        order = validate_success(api_client.create_caretaking_order(
            create_caretaking_order_payload(grove_yes["id"], "MOW", "2026-08-01", 5),
            SUPERVISOR), expected_status=201)
        assert order["status"] == "REQUESTED"

    def test_acres_treated_grove_boundary(self, api):
        """PRD §3.7: "`acres_treated` greater than zero and no more than the
        grove's `acreage` — an excess fails with `ERR_ACRES_EXCEED_GROVE`" —
        30.0 acres on a 30-acre grove is the inclusive boundary; 30.001 is an
        excess.

        Design: Corner/validations/acres_treated_grove_boundary
        """
        scenario = setup_enrolled_grove("V5", acreage=30)
        order = validate_success(api_client.create_caretaking_order(
            create_caretaking_order_payload(scenario["grove"]["id"], "MOW",
                                            "2026-08-01", 30.0),
            SUPERVISOR), expected_status=201)
        assert order["acres_treated"] == 30.0
        resp = api_client.create_caretaking_order(
            create_caretaking_order_payload(scenario["grove"]["id"], "MOW",
                                            "2026-08-01", 30.001),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ACRES_EXCEED_GROVE)


class TestOrderDefaults:
    def test_caretaking_order_defaults_and_nullable_fields(self, api):
        """PRD §3.7: "An order is born `REQUESTED` with `rate_tier`,
        `line_amount_cents`, and `invoice_id` unset" and "an optional
        `chemical_cost_cents` that defaults to zero".

        Design: Corner/entities/caretaking_order_defaults_and_nullable_fields
        """
        scenario = setup_enrolled_grove("E13", acreage=30)
        order = validate_success(api_client.create_caretaking_order(
            create_caretaking_order_payload(scenario["grove"]["id"], "PRUNE",
                                            "2026-08-01", 5),
            SUPERVISOR), expected_status=201)
        assert_service_order(order)
        assert order["status"] == "REQUESTED"
        assert order["chemical_cost_cents"] == 0
        assert order.get("rate_tier") is None
        assert order.get("line_amount_cents") is None
        assert order.get("invoice_id") is None


class TestInvoicePayments:
    def test_invoice_payment_bounds(self, api):
        """PRD §3.7: "The amount must be positive (`ERR_PAYMENT_AMOUNT_INVALID`,
        HTTP 400) and no more than the invoice's remaining balance —
        `total_cents` minus `paid_cents` — with an excess rejected as
        `ERR_INVOICE_OVERPAYMENT`. A payment smaller than the remaining
        balance moves `ISSUED` → `PARTIALLY_PAID`; one exactly equal to the
        remaining balance moves `ISSUED` → `PAID`, and a later such payment
        moves `PARTIALLY_PAID` → `PAID`, which is terminal."

        Design: Corner/validations/invoice_payment_bounds
        """
        scenario = setup_issued_invoice("V6")
        invoice = scenario["invoice"]
        assert invoice["total_cents"] == 20000
        grower_headers = make_grower_headers(scenario["grower"]["id"])
        resp = api_client.pay_caretaking_invoice(
            invoice["id"], {"amount_cents": 0}, grower_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)
        resp = api_client.pay_caretaking_invoice(
            invoice["id"], {"amount_cents": 20001}, grower_headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_OVERPAYMENT)
        partial = validate_success(api_client.pay_caretaking_invoice(
            invoice["id"], {"amount_cents": 5000}, grower_headers),
            expected_status=201)
        assert partial["status"] == "PARTIALLY_PAID"
        assert partial["paid_cents"] == 5000
        assert get_grower(scenario["grower"]["id"])[
            "caretaking_balance_cents"] == 15000
        final = validate_success(api_client.pay_caretaking_invoice(
            invoice["id"], {"amount_cents": 15000}, grower_headers),
            expected_status=201)
        assert final["status"] == "PAID"
        assert final["paid_cents"] == 20000
        assert get_grower(scenario["grower"]["id"])[
            "caretaking_balance_cents"] == 0


class TestInvoiceReissueBounds:
    def test_invoice_reissue_bounds(self, api):
        """PRD §3.7: "A `PoolAccountant` then reissues, moving `DISPUTED` →
        `ISSUED` with an `adjusted_total_cents` that must be positive, no more
        than the original total, and at least the `paid_cents` already
        collected (`ERR_INVALID_REQUEST` otherwise); the invoice's
        `total_cents` becomes the adjusted figure".

        Design: Corner/state_machines/invoice_reissue_bounds
        """
        scenario = setup_issued_invoice("SM9")
        invoice = scenario["invoice"]
        validate_success(api_client.dispute_caretaking_invoice(
            invoice["id"], make_grower_headers(scenario["grower"]["id"])))
        resp = api_client.reissue_caretaking_invoice(
            invoice["id"], {"adjusted_total_cents": 20001}, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        resp = api_client.reissue_caretaking_invoice(
            invoice["id"], {"adjusted_total_cents": 0}, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Exactly the original total is the inclusive upper bound.
        reissued = validate_success(api_client.reissue_caretaking_invoice(
            invoice["id"], {"adjusted_total_cents": 20000}, ACCOUNTANT))
        assert reissued["status"] == "ISSUED"
        assert reissued["total_cents"] == 20000


class TestDisputeReissueCycle:
    def test_first_dispute_reissue_loop(self, api):
        """PRD §3.7: "the owning `Grower` moves an `ISSUED` invoice to
        `DISPUTED`, which suspends the open amount — `total_cents` minus
        `paid_cents` — from the grower's `caretaking_balance_cents` while the
        dispute is open." and "the grower's `caretaking_balance_cents` rises
        by the adjusted total minus `paid_cents`. The dispute-and-reissue loop
        may repeat."

        Design: Difficulty/non_linear_state_machine/caretaking_invoice_dispute_reissue_cycle
        """
        scenario = setup_issued_invoice("IC1")
        invoice_id = scenario["invoice"]["id"]
        grower_headers = make_grower_headers(scenario["grower"]["id"])
        disputed = validate_success(api_client.dispute_caretaking_invoice(
            invoice_id, grower_headers))
        assert disputed["status"] == "DISPUTED"
        assert get_grower(scenario["grower"]["id"])[
            "caretaking_balance_cents"] == 0, "the open 20000 is suspended"
        reissued = validate_success(api_client.reissue_caretaking_invoice(
            invoice_id, {"adjusted_total_cents": 15000}, ACCOUNTANT))
        assert reissued["status"] == "ISSUED"
        assert reissued["total_cents"] == 15000
        assert get_grower(scenario["grower"]["id"])[
            "caretaking_balance_cents"] == 15000, "loop 1 closes at the adjusted total"

    def test_second_loop_then_payment_closes_cycle(self, api):
        """PRD §3.7: "The dispute-and-reissue loop may repeat." — a second
        DISPUTED → ISSUED pass at 12000 followed by a payment of the exact
        remaining balance moves the invoice `ISSUED` → `PAID` ("which is
        terminal") and zeroes the grower's caretaking balance.

        Design: Difficulty/non_linear_state_machine/caretaking_invoice_dispute_reissue_cycle
        """
        scenario = setup_issued_invoice("IC1B")
        invoice_id = scenario["invoice"]["id"]
        grower_headers = make_grower_headers(scenario["grower"]["id"])
        validate_success(api_client.dispute_caretaking_invoice(
            invoice_id, grower_headers))
        validate_success(api_client.reissue_caretaking_invoice(
            invoice_id, {"adjusted_total_cents": 15000}, ACCOUNTANT))
        validate_success(api_client.dispute_caretaking_invoice(
            invoice_id, grower_headers))
        second = validate_success(api_client.reissue_caretaking_invoice(
            invoice_id, {"adjusted_total_cents": 12000}, ACCOUNTANT))
        assert second["status"] == "ISSUED"
        assert second["total_cents"] == 12000
        assert get_grower(scenario["grower"]["id"])[
            "caretaking_balance_cents"] == 12000, "loop 2 closes — the cycle repeats"
        paid = validate_success(api_client.pay_caretaking_invoice(
            invoice_id, {"amount_cents": 12000}, grower_headers),
            expected_status=201)
        assert paid["status"] == "PAID"
        assert paid["paid_cents"] == 12000
        assert get_grower(scenario["grower"]["id"])[
            "caretaking_balance_cents"] == 0


class TestIssueGatedByGrowerStatus:
    def _setup_draft_then_terminate(self, tag):
        scenario = setup_enrolled_grove(tag, acreage=30)
        order = create_completed_order(scenario["grove"]["id"], "MOW",
                                       "2026-08-01", 11.111)
        invoice = create_draft_invoice(scenario["grower"]["id"])
        # Termination is permitted: both ledgers are zero while the invoice
        # is still DRAFT (PRD §3.1).
        get_success_data(api_client.terminate_grower(
            scenario["grower"]["id"], ACCOUNTANT))
        return scenario, order, invoice

    def test_issue_rejected_after_grower_terminated(self, api):
        """PRD §3.7: "Issuance requires the grower not to be `TERMINATED`
        (`ERR_GROWER_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/invoice_issue_gated_by_grower_status
        """
        scenario, _order, invoice = self._setup_draft_then_terminate("CE3")
        assert get_grower(scenario["grower"]["id"])["status"] == "TERMINATED"
        resp = api_client.issue_caretaking_invoice(invoice["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ACTIVE)

    def test_rejected_issue_leaves_invoice_and_order_untouched(self, api):
        """PRD §3.7: "On issue, every swept order moves `COMPLETED` → the
        terminal `INVOICED` with its `invoice_id` set" — with issuance refused
        under a terminated grower, no such side effect occurs: the invoice
        remains `DRAFT` and the order remains `COMPLETED` with no
        `invoice_id`.

        Design: Difficulty/cross_entity_state_dependency/invoice_issue_gated_by_grower_status
        """
        scenario, order, invoice = self._setup_draft_then_terminate("CE3B")
        validate_error(api_client.issue_caretaking_invoice(invoice["id"], ACCOUNTANT),
                       ApiErrorId.ERR_GROWER_NOT_ACTIVE)
        invoice_after = get_caretaking_invoice(invoice["id"])
        assert invoice_after["status"] == "DRAFT"
        order_after = get_caretaking_order(order["id"])
        assert order_after["status"] == "COMPLETED"
        assert order_after.get("invoice_id") is None


class TestTerminateBlockedByBalance:
    def test_grower_terminate_blocked_with_open_balance(self, api):
        """PRD §3.1: "Termination moves a grower from either `ACTIVE` or
        `SUSPENDED` to `TERMINATED`, which is terminal, and is permitted only
        when both ledgers are clean — `advance_outstanding_cents` is zero and
        `caretaking_balance_cents` is zero; if either balance remains, the
        termination is refused with `ERR_GROWER_NOT_ACTIVE`." and
        "Terminating a grower also cancels every caretaking service order of
        the grower's groves that is still in `REQUESTED` or `SCHEDULED`
        status."

        Design: Corner/errors/grower_terminate_blocked_with_open_balance
        """
        scenario = setup_issued_invoice("ER8")
        grower_id = scenario["grower"]["id"]
        # A second order stays SCHEDULED (service_date inside the period but
        # never completed, so the invoice sweep did not capture it).
        open_order = get_success_data(api_client.create_caretaking_order(
            create_caretaking_order_payload(scenario["grove"]["id"], "MOW",
                                            "2026-08-05", 2), SUPERVISOR))
        get_success_data(api_client.schedule_caretaking_order(
            open_order["id"], SUPERVISOR))
        resp = api_client.terminate_grower(grower_id, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ACTIVE)
        # Paying the 20000-cent invoice in full cleans the ledger.
        validate_success(api_client.pay_caretaking_invoice(
            scenario["invoice"]["id"], {"amount_cents": 20000}, ACCOUNTANT),
            expected_status=201)
        terminated = validate_success(api_client.terminate_grower(
            grower_id, ACCOUNTANT))
        assert terminated["status"] == "TERMINATED"
        assert get_caretaking_order(open_order["id"])["status"] == "CANCELLED", \
            "termination cancels the grove's SCHEDULED orders"
