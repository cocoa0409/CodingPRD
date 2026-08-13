"""Delivery, the 72-hour revision window, project close-out, and invoices."""
from test_helpers import (
    ApiErrorId,
    assert_delivery,
    assert_invoice,
    assert_revision_window_math,
    create_session,
    list_project_invoices,
    make_client_headers,
    parse_utc,
    set_clock,
    setup_delivered_project,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import AGENT, CD, ENGINEER


class TestDeliveryTriggersInvoices:
    def test_delivery_generates_buyout_and_session_fee_invoices(self, api):
        """PRD §3.8: "delivery is the platform's invoicing moment: a `BUYOUT`
        invoice in `PENDING` status is generated referencing the usage terms'
        `buyout_cents`, and a `SESSION_FEE` invoice in `PENDING` status is
        generated for every `COMPLETED` `PRIMARY` or `RETAKE` session not yet
        invoiced."

        Design: Difficulty/transitive_cascade/delivery_triggers_invoice_and_window_chain
        """
        ctx = setup_delivered_project()
        assert ctx["project"]["status"] == "DELIVERED"
        invoices = ctx["invoices"]
        kinds = sorted(i["invoice_kind"] for i in invoices)
        assert kinds == ["BUYOUT", "SESSION_FEE"], (
            f"expected one BUYOUT and one SESSION_FEE invoice, got {kinds}"
        )
        for inv in invoices:
            assert_invoice(inv)
            assert inv["status"] == "PENDING"
        buyout = [i for i in invoices if i["invoice_kind"] == "BUYOUT"][0]
        # UNION 80000, DIGITAL, 1 spot: buyout = 80000 * 1.50 = 120000.
        assert buyout["total_cents"] == 120000

    def test_close_issues_all_pending_invoices(self, api):
        """PRD §3.8: "Either path moves the project `DELIVERED → CLOSED` and
        issues every `PENDING` invoice on the project, stamping each
        `issued_at` with the clock."

        Design: Difficulty/transitive_cascade/delivery_triggers_invoice_and_window_chain
        """
        ctx = setup_delivered_project()
        project = ctx["project"]
        resp = api.close_project(project["id"],
                                 make_client_headers(ctx["client"]["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CLOSED"
        for inv in list_project_invoices(project["id"]):
            assert inv["status"] == "ISSUED"
            assert inv["issued_at"] is not None


class TestRevisionWindow:
    def test_revision_at_exactly_72h_is_accepted(self, api):
        """PRD §2.9: "a revision request arriving at exactly that instant is
        still accepted, because the rule is that a request is accepted whenever
        the clock is less than or equal to `revision_window_closes_at`."

        Design: Difficulty/boundary_precision_check/revision_window_exactly_at_72h
        """
        ctx = setup_delivered_project()
        # Delivered at 2026-08-02T11:00:00Z -> window closes 2026-08-05T11:00:00Z.
        set_clock("2026-08-05T11:00:00Z")
        resp = api.request_revision(ctx["project"]["id"],
                                    make_client_headers(ctx["client"]["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CAST"

    def test_revision_after_window_closes_is_rejected(self, api):
        """PRD §3.8: "A request after the window closes is rejected with
        `ERR_TEMPORAL_VIOLATION`". PRD §3.8: "The platform closes it
        automatically once the clock has moved strictly past
        `revision_window_closes_at` with `revision_requested` still false"
        (once auto-closed, the request also fails the state check, so either
        error honestly reports the rejection).

        Design: Difficulty/boundary_precision_check/revision_window_exactly_at_72h
        """
        ctx = setup_delivered_project()
        set_clock("2026-08-05T11:00:01Z")  # one second past the closing instant
        resp = api.request_revision(ctx["project"]["id"],
                                    make_client_headers(ctx["client"]["id"]))
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_TEMPORAL_VIOLATION, ApiErrorId.ERR_INVALID_STATE])


class TestDeliveredToCastCycle:
    def test_request_revision_reverts_project_to_cast(self, api):
        """PRD §3.8: "A granted revision sets `revision_requested` to true and
        reverts the project `DELIVERED → CAST`, opening a retake-and-pickup
        round".

        Design: Difficulty/non_linear_state_machine/project_delivered_to_cast_cycle
        """
        ctx = setup_delivered_project()
        set_clock("2026-08-03T11:00:00Z")  # delivered_at + 24h: inside window
        resp = api.request_revision(ctx["project"]["id"],
                                    make_client_headers(ctx["client"]["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CAST"
        delivery = validate_success(
            api.get_delivery(ctx["delivery"]["id"], ENGINEER), expected_status=200)
        assert delivery["revision_requested"] is True

    def test_retake_session_allowed_after_revision(self, api):
        """PRD §3.8: "a `RETAKE` session may now be scheduled and confirmed".
        PRD §3.6: "confirming a `RETAKE` session requires the project's
        delivery to have `revision_requested` set to true".

        Design: Difficulty/non_linear_state_machine/project_delivered_to_cast_cycle
        """
        ctx = setup_delivered_project()
        set_clock("2026-08-03T11:00:00Z")
        validate_success(
            api.request_revision(ctx["project"]["id"],
                                 make_client_headers(ctx["client"]["id"])),
            expected_status=200,
        )
        # Project is back in CAST, so session creation is allowed again.
        retake = create_session(ctx["project"]["id"], ctx["studio"],
                                session_kind="RETAKE",
                                start_at="2026-08-04T10:00:00Z",
                                duration_minutes=60)
        resp = api.confirm_session(retake["id"], CD)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CONFIRMED"


class TestRevisionWindowComputation:
    def test_revision_window_closes_at_delivered_plus_72h(self, api):
        """PRD §3.8: "The record's `revision_window_hours` is the constant 72,
        and `revision_window_closes_at` is derived as `delivered_at` plus 72
        hours."

        Design: Corner/calculations/revision_window_closes_at_delivered_plus_72h
        """
        ctx = setup_delivered_project()
        delivery = ctx["delivery"]
        assert_delivery(delivery)
        assert parse_utc(delivery["delivered_at"]) == parse_utc("2026-08-02T11:00:00Z")
        assert parse_utc(delivery["revision_window_closes_at"]) == parse_utc(
            "2026-08-05T11:00:00Z")
        assert_revision_window_math(delivery)


class TestInvoiceLifecycle:
    def test_invoice_issue_from_pending_to_issued(self, api):
        """PRD §3.9: "An invoice begins `PENDING`, becomes `ISSUED` either when
        an `Agent` issues it manually or when the project closes (which issues
        all pending invoices at once, stamping `issued_at` from the clock)".

        Design: Corner/state_machines/invoice_issue_from_pending_to_issued
        """
        ctx = setup_delivered_project()
        invoice = ctx["invoices"][0]
        assert invoice["status"] == "PENDING"
        resp = api.issue_invoice(invoice["id"], AGENT)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ISSUED"
        assert data["issued_at"] is not None
        assert parse_utc(data["issued_at"]) == parse_utc("2026-08-02T11:00:00Z")

    def test_invoice_terminal_paid_lockdown(self, api):
        """PRD §3.9: "an `ISSUED` invoice is settled when an `Agent` marks it
        `PAID`." PRD §2.10: "then whether the target resource is in a valid
        state for the requested transition (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/invoice_terminal_paid_lockdown
        """
        ctx = setup_delivered_project()
        invoice = ctx["invoices"][0]
        validate_success(api.issue_invoice(invoice["id"], AGENT), expected_status=200)
        paid = validate_success(api.mark_invoice_paid(invoice["id"], AGENT),
                                expected_status=200)
        assert paid["status"] == "PAID"
        resp = api.issue_invoice(invoice["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
