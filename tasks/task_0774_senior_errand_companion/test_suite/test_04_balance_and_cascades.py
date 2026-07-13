"""Cascades and conserved quantities: the depth-3 client-suspend cascade, the
invoice-void → claim-withdraw cascade, and the compensating balance / committed-
minutes invariants."""
from test_helpers import (
    setup_submitted_claim,
    setup_finalized_invoice,
    setup_assigned_visit,
    create_cleared_bonded_caregiver,
    create_client,
    validate_success,
    get_success_data,
    create_schedule_payload,
    create_assignment_payload,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def _suspend_cascade_ctx(api):
    """Active client + ACTIVE weekly THU schedule + one generated SCHEDULED visit on
    2026-03-05 + a cleared bonded caregiver CONFIRMED on it (committed 180)."""
    caregiver = create_cleared_bonded_caregiver(api)
    client = create_client(api)
    schedule = get_success_data(
        api.create_schedule(
            client["id"],
            create_schedule_payload(
                task_type="COMPANION", frequency="WEEKLY", day_of_week="THU",
                start_time="09:00", duration_minutes=180,
                start_date="2026-03-01T00:00:00Z", end_date="2026-03-31T00:00:00Z",
            ),
            COORD,
        )
    )
    visits = get_success_data(
        api.generate_visits(
            schedule["id"], {"from_date": "2026-03-05T00:00:00Z", "to_date": "2026-03-05T23:59:59Z"}, COORD
        )
    )
    assert len(visits) == 1, f"expected one generated visit, got {len(visits)}"
    visit = visits[0]
    assignment = get_success_data(
        api.create_assignment(visit["id"], create_assignment_payload(caregiver["id"], visit["version"]), COORD)
    )
    return {"client": client, "schedule": schedule, "visit": visit, "assignment": assignment, "caregiver": caregiver}


class TestClientSuspendCascade:
    def test_suspend_pauses_schedule_and_cancels_visit(self, api):
        """PRD §2.8: "The client moves to SUSPENDED; then, as hop one, every
        RecurringSchedule owned by that client that is currently ACTIVE moves to
        PAUSED. Pausing a schedule is itself hop two: every Visit belonging to that
        schedule that is still SCHEDULED moves to CANCELLED."

        Design: Difficulty/transitive_cascade/client_suspend_cascade_depth3
        """
        ctx = _suspend_cascade_ctx(api)
        suspended = validate_success(api.suspend_client(ctx["client"]["id"], COORD))
        assert suspended["status"] == "SUSPENDED", f"expected SUSPENDED, got {suspended['status']}"
        schedule = validate_success(api.get_schedule(ctx["schedule"]["id"], COORD))
        assert schedule["status"] == "PAUSED", f"expected schedule PAUSED, got {schedule['status']}"
        visit = validate_success(api.get_visit(ctx["visit"]["id"], COORD))
        assert visit["status"] == "CANCELLED", f"expected visit CANCELLED, got {visit['status']}"

    def test_suspend_cancels_assignment_and_releases_committed_minutes(self, api):
        """PRD §2.8: "Cancelling a visit is hop three: every CONFIRMED Assignment on
        it moves to CANCELLED (releasing that caregiver's committed minutes), and any
        DRAFT Invoice for the visit moves to VOID."

        Design: Difficulty/transitive_cascade/client_suspend_cascade_depth3
        """
        ctx = _suspend_cascade_ctx(api)
        validate_success(api.suspend_client(ctx["client"]["id"], COORD))
        assignment = validate_success(api.get_assignment(ctx["assignment"]["id"], COORD))
        assert assignment["status"] == "CANCELLED", f"expected assignment CANCELLED, got {assignment['status']}"
        caregiver = validate_success(api.get_caregiver(ctx["caregiver"]["id"], COORD))
        assert caregiver["committed_minutes"] == 0, (
            f"committed minutes must be released to 0, got {caregiver['committed_minutes']}"
        )


class TestInvoiceVoidCascade:
    def test_void_moves_invoice_to_void(self, api):
        """PRD §3.6: "Voiding an invoice that is already VOID is rejected with
        ERR_INVOICE_ALREADY_VOID. VOID is terminal."
        PRD §3.6: "A clerk may also void an invoice."

        Design: Difficulty/transitive_cascade/invoice_void_cascade_withdraws_claim
        """
        ctx = setup_submitted_claim(api)
        voided = validate_success(api.void_invoice(ctx["invoice"]["id"], BILLING))
        assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"

    def test_void_withdraws_submitted_claim(self, api):
        """PRD §2.8: "A finalized invoice being voided reverses its debit from the
        client's balance, and then, as hop two, every ReimbursementClaim against that
        invoice in DRAFT, SUBMITTED, NEEDS_INFO, or APPROVED status moves to
        WITHDRAWN"

        Design: Difficulty/transitive_cascade/invoice_void_cascade_withdraws_claim
        """
        ctx = setup_submitted_claim(api)
        validate_success(api.void_invoice(ctx["invoice"]["id"], BILLING))
        claim = validate_success(api.get_claim(ctx["claim"]["id"], BILLING))
        assert claim["status"] == "WITHDRAWN", f"expected claim WITHDRAWN, got {claim['status']}"

    def test_void_reverses_client_balance_to_zero(self, api):
        """PRD §3.6: "a FINALIZED invoice being voided subtracts its total_cents back
        out of the client's outstanding_balance_cents and triggers the
        claim-withdrawal cascade of §2.8."

        Design: Difficulty/transitive_cascade/invoice_void_cascade_withdraws_claim
        """
        ctx = setup_submitted_claim(api)
        validate_success(api.void_invoice(ctx["invoice"]["id"], BILLING))
        client = validate_success(api.get_client(ctx["client"]["id"], COORD))
        assert client["outstanding_balance_cents"] == 0, (
            f"balance must return to 0 after void, got {client['outstanding_balance_cents']}"
        )


class TestVoidRestoresBalance:
    def test_finalize_then_void_leaves_invoice_void(self, api):
        """PRD §3.6: "A BillingClerk finalizes a draft invoice, moving it
        DRAFT → FINALIZED and adding its total_cents to the client's
        outstanding_balance_cents."

        Design: Difficulty/compensating_invariant/void_restores_client_outstanding_balance
        """
        ctx = setup_finalized_invoice(api)
        voided = validate_success(api.void_invoice(ctx["invoice"]["id"], BILLING))
        assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"

    def test_finalize_then_void_conserves_balance_at_zero(self, api):
        """PRD §3.6: "it is the sum of total_cents over that client's FINALIZED
        invoices, minus the sum of reimbursed_cents over that client's APPROVED
        reimbursement claims."

        Design: Difficulty/compensating_invariant/void_restores_client_outstanding_balance
        """
        ctx = setup_finalized_invoice(api)
        validate_success(api.void_invoice(ctx["invoice"]["id"], BILLING))
        client = validate_success(api.get_client(ctx["client"]["id"], COORD))
        assert client["outstanding_balance_cents"] == 0, (
            f"finalize+void must conserve balance at 0, got {client['outstanding_balance_cents']}"
        )


class TestCancelAssignmentRestoresMinutes:
    def test_cancel_assignment_moves_to_cancelled(self, api):
        """PRD §3.4: "cancelling a CONFIRMED assignment moves it CONFIRMED →
        CANCELLED, subtracts this visit's scheduled minutes from the caregiver's
        committed_minutes, and clears the visit's caregiver_id if it still points at
        that caregiver."

        Design: Difficulty/compensating_invariant/cancel_assignment_restores_committed_minutes
        """
        ctx = setup_assigned_visit(api)  # 09:00-12:00 = 180 scheduled minutes
        cancelled = validate_success(api.cancel_assignment(ctx["assignment"]["id"], COORD))
        assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"

    def test_cancel_assignment_restores_committed_minutes_to_zero(self, api):
        """PRD §3.2: "The committed_minutes figure is the sum, in minutes, of the
        scheduled length (scheduled_end minus scheduled_start) of every visit the
        caregiver holds a CONFIRMED assignment on; superseded and cancelled
        assignments never contribute."

        Design: Difficulty/compensating_invariant/cancel_assignment_restores_committed_minutes
        """
        ctx = setup_assigned_visit(api)
        validate_success(api.cancel_assignment(ctx["assignment"]["id"], COORD))
        caregiver = validate_success(api.get_caregiver(ctx["caregiver"]["id"], COORD))
        assert caregiver["committed_minutes"] == 0, (
            f"committed minutes must return to 0, got {caregiver['committed_minutes']}"
        )
