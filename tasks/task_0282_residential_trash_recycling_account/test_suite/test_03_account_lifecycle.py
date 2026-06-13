"""Account service/billing lifecycle: parallel dimensions, stop cascade, transfer-out,
billing transitions, invalid transitions, terminal lockdown. Covers difficulty rules
non_linear_state_machine (account dimensions), transitive_cascade (stop branch), and
the state_machines / endpoints / cross_cutting corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_account_holder_headers,
    ApiErrorId,
    create_active_account, create_plan, create_zone, set_clock,
    create_account, add_standard_carts, account_version,
    setup_account_with_missed_trash_credit, setup_account_with_open_invoice,
    generate_invoice_payload,
)

DISP = TEST_USERS["dispatcher_headers"]
CREW = TEST_USERS["crew_lead_headers"]


class TestParallelStatusBillingDimensions:
    def test_stopped_account_can_be_past_due(self, api):
        """PRD §3.13: "a STOPPED account can still be PAST_DUE, and an ACTIVE account can
        be IN_COLLECTIONS."
        PRD §3.13: "An account moves CURRENT → PAST_DUE when it has an OPEN invoice whose
        due_date is strictly before the new clock date, and that invoice's own status is
        set to PAST_DUE as part of the same transition."

        Design: Difficulty/non_linear_state_machine/account_parallel_status_and_billing_status_dimensions
        """
        plan = create_plan()
        zone = create_zone()
        set_clock("2026-02-25T00:00:00Z")
        acct = create_account(plan["id"], zone["id"], address="18 Oak St")
        add_standard_carts(acct["id"])
        acct = get_success_data(api.activate_start(acct["id"], DISP))
        v0 = account_version(acct["id"])
        get_success_data(api.generate_invoice(acct["id"], generate_invoice_payload(
            v0, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z"), DISP))

        # advance past due_date, then stop service
        get_success_data(api.set_clock({"to_iso8601": "2026-03-11T00:00:00Z"}, DISP))
        validate_success(api.stop_account(acct["id"], DISP), 200)

        final = validate_success(api.get_account(acct["id"], DISP), 200)
        assert final["status"] == "STOPPED"
        assert final["billing_status"] == "PAST_DUE"

    def test_billing_dimension_independent_of_service_status(self, api):
        """PRD §3.13: "every account carries a billing dimension in billing_status, which
        begins CURRENT and moves among CURRENT, PAST_DUE, and IN_COLLECTIONS independently
        of the service status."

        Design: Difficulty/non_linear_state_machine/account_parallel_status_and_billing_status_dimensions
        """
        s = setup_account_with_open_invoice(
            period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
            due_date="2026-03-10T00:00:00Z", clock="2026-02-25T00:00:00Z", address="19 Oak St")
        acct = s["account"]
        # before lapse: ACTIVE + CURRENT
        pre = validate_success(api.get_account(acct["id"], DISP), 200)
        assert pre["status"] == "ACTIVE" and pre["billing_status"] == "CURRENT"
        # lapse moves only the billing dimension
        get_success_data(api.set_clock({"to_iso8601": "2026-03-11T00:00:00Z"}, DISP))
        post = validate_success(api.get_account(acct["id"], DISP), 200)
        assert post["status"] == "ACTIVE", "service dimension untouched by billing lapse"
        assert post["billing_status"] == "PAST_DUE"


class TestStopCascade:
    def test_stop_cancels_schedules_and_expires_credits(self, api):
        """PRD §3.3: "Stopping cancels all PLANNED schedule rows, marks every ACTIVE cart
        REMOVED, and — this is the consequential cascade — expires every ISSUED
        MissedPickupCredit on the account by setting its status to EXPIRED."

        Design: Difficulty/transitive_cascade/stop_cancels_schedules_and_expires_credits_depth2
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z", address="24 Oak St")
        acct = s["account"]
        cr_id = s["credit"]["id"]
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        # pick a still-PLANNED future row (rows[0] was MISSED)
        planned = next(r for r in rows if r["status"] == "PLANNED")

        validate_success(api.stop_account(acct["id"], DISP), 200)

        row_after = validate_success(api.get_pickup_schedule(planned["id"], DISP), 200)
        assert row_after["status"] == "CANCELLED"
        credit_after = validate_success(api.get_credit(cr_id, DISP), 200)
        assert credit_after["status"] == "EXPIRED"

    def test_stop_expires_issued_credit(self, api):
        """PRD §3.3: "expires every ISSUED MissedPickupCredit on the account by setting its
        status to EXPIRED; credit is forfeited when a household simply stops."

        Design: Difficulty/transitive_cascade/stop_cancels_schedules_and_expires_credits_depth2
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z", address="25 Oak St")
        cr_id = s["credit"]["id"]
        validate_success(api.stop_account(s["account"]["id"], DISP), 200)
        credit_after = validate_success(api.get_credit(cr_id, DISP), 200)
        assert credit_after["status"] == "EXPIRED"


class TestTransferOut:
    def test_transfer_out_mints_destination_and_migrates_credit(self, api):
        """PRD §3.4: "On success the system mints a new ServiceAccount in PENDING_START
        whose transferred_from_account_id points back at the source account."
        PRD §3.4: "every ISSUED MissedPickupCredit on the source is migrated to the
        destination by re-pointing its account_id — unlike a stop, a transfer preserves
        credit across the move."

        Design: Corner/endpoints/transfer_out_creates_destination_and_migrates_credits
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z", address="88 Oak St")
        acct = s["account"]
        v = account_version(acct["id"])
        dest = validate_success(api.transfer_out(acct["id"], {
            "expected_account_version": v,
            "new_service_address": "90 Oak St",
            "new_zone_id": s["zone"]["id"],
        }, DISP), 201)
        assert dest["transferred_from_account_id"] == acct["id"]
        assert dest["status"] == "PENDING_START"

        source = validate_success(api.get_account(acct["id"], DISP), 200)
        assert source["status"] == "TRANSFERRED_OUT"

        migrated = get_success_data(api.list_account_credits(dest["id"], DISP))
        assert migrated and migrated[0]["amount_cents"] == 300
        assert migrated[0]["status"] == "ISSUED"


class TestBillingTransitions:
    def test_due_date_lapse_flips_invoice_and_account_past_due(self, api):
        """PRD §3.13: "An account moves CURRENT → PAST_DUE when it has an OPEN invoice
        whose due_date is strictly before the new clock date, and that invoice's own
        status is set to PAST_DUE as part of the same transition."

        Design: Corner/cross_cutting_complexity_layers/invoice_due_date_lapse_transitions_billing_past_due
        """
        s = setup_account_with_open_invoice(
            period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
            due_date="2026-03-10T00:00:00Z", clock="2026-02-25T00:00:00Z", address="96 Oak St")
        acct, inv = s["account"], s["invoice"]
        get_success_data(api.set_clock({"to_iso8601": "2026-03-11T00:00:00Z"}, DISP))
        inv_after = validate_success(api.get_invoice(inv["id"], DISP), 200)
        assert inv_after["status"] == "PAST_DUE"
        acct_after = validate_success(api.get_account(acct["id"], DISP), 200)
        assert acct_after["billing_status"] == "PAST_DUE"

    def test_pay_settles_invoice_and_returns_billing_current(self, api):
        """PRD §3.12: "A payment creates a payment record whose status is always APPLIED."
        PRD §3.12: "Payment is allowed against an invoice in either OPEN or PAST_DUE
        status, advancing it to PAID in both cases."
        PRD §3.12: "the system then re-evaluates the account's billing_status: when no OPEN
        or PAST_DUE invoice remains on the account, the billing dimension returns to CURRENT."

        Design: Corner/endpoints/pay_invoice_exact_amount_settles_and_returns_billing_current
        """
        s = setup_account_with_open_invoice(address="86 Oak St")
        acct, inv = s["account"], s["invoice"]
        holder = make_account_holder_headers(acct["id"])
        pay = validate_success(api.pay_invoice(
            inv["id"], {"amount_cents": inv["amount_due_cents"], "method": "MANUAL"}, holder), 201)
        assert pay["status"] == "APPLIED"
        inv_after = validate_success(api.get_invoice(inv["id"], DISP), 200)
        assert inv_after["status"] == "PAID"
        acct_after = validate_success(api.get_account(acct["id"], DISP), 200)
        assert acct_after["billing_status"] == "CURRENT"


class TestInvalidTransitionsAndLockdown:
    def test_activate_already_active_returns_invalid_state(self, api):
        """PRD §2.6: "then the state-transition legality check that the target resource is
        in a state from which the requested transition is defined (ERR_INVALID_STATE)."
        PRD §3.3: "A Dispatcher activates service on a PENDING_START account, advancing it
        PENDING_START → ACTIVE."

        Design: Corner/state_machines/activate_already_active_account_returns_invalid_state
        """
        _, _, acct = create_active_account(address="56 Oak St")
        validate_error(api.activate_start(acct["id"], DISP), ApiErrorId.ERR_INVALID_STATE.value)

    def test_resume_non_suspended_returns_invalid_state(self, api):
        """PRD §3.3: "Resuming a SUSPENDED account moves it SUSPENDED → ACTIVE and
        regenerates the PLANNED schedule rows for the next 28 days."
        PRD §2.6: "the state-transition legality check that the target resource is in a
        state from which the requested transition is defined (ERR_INVALID_STATE)."

        Design: Corner/state_machines/resume_account_that_is_not_suspended_returns_invalid_state
        """
        _, _, acct = create_active_account(address="58 Oak St")
        validate_error(api.resume_account(acct["id"], DISP), ApiErrorId.ERR_INVALID_STATE.value)

    def test_stop_then_stop_again_terminal_lockdown(self, api):
        """PRD §3.3: "Stopping ends service permanently and is reachable from either ACTIVE
        or SUSPENDED, in both cases moving the account to STOPPED."
        PRD §2.6: "the state-transition legality check that the target resource is in a
        state from which the requested transition is defined (ERR_INVALID_STATE)."

        Design: Corner/state_machines/stop_account_then_stop_again_terminal_lockdown
        """
        _, _, acct = create_active_account(address="60 Oak St")
        validate_success(api.stop_account(acct["id"], DISP), 200)
        validate_error(api.stop_account(acct["id"], DISP), ApiErrorId.ERR_INVALID_STATE.value)
