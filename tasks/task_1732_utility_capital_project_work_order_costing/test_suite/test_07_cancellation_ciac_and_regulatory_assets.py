"""Cancellation consequences: write-off dispositions, CIAC refund/forfeiture
rules, pledge expiry via the logical clock, and regulatory-asset decisions
(PRD §2.6, §3.6, §3.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_period,
    create_authorized_work_order,
    create_ciac,
    create_in_progress_work_order,
    create_period,
    create_program,
    create_received_ciac,
    create_reg_asset,
    create_schedule,
    create_work_order_payload,
    get_program,
    get_success_data,
    post_charge,
    setup_charging_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
RATES = TEST_USERS["rates_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestCiacPledgeExpiry:
    def test_ciac_pledge_expiry_receive_rejection_and_close_sweep(self, api):
        """PRD §3.6: "The logical clock must not have passed `pledge_expiry_at`; a receipt attempted after expiry is rejected with `ERR_CIAC_EXPIRED`, and the agreement flips to `EXPIRED` as a side effect of that failed attempt."
        PRD §3.6: "Expiry otherwise advances lazily and by sweep: a `PLEDGED` agreement becomes `EXPIRED` when the logical clock has passed its `pledge_expiry_at`, observed either on a receive attempt or at every period close (§3.9)."
        PRD §3.9: "Every agreement still `PLEDGED` whose `pledge_expiry_at` lies earlier than the current logical clock flips to `EXPIRED`."
        PRD §2.6: "The server keeps a logical clock rather than trusting wall-clock time. Before it has ever been set, the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time afterward. A `SystemAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant; the response reports the new reading as `current_utc`."

        Design: Corner/state_machines/ciac_pledge_expiry_receive_rejection_and_close_sweep
        """
        program = create_program(code="CAP-CIACX", authorized_amount_cents=50_000_000)
        period = create_period()
        wo = get_success_data(api.create_work_order(
            create_work_order_payload(program_id=program["id"],
                                      title="CIAC expiry order",
                                      initial_estimated_cost_cents=100_000),
            ENGINEER))
        ciac_a = create_ciac(wo["id"], pledged_cents=50_000,
                             pledge_expiry_at="2026-08-10T00:00:00Z")
        ciac_b = create_ciac(wo["id"], pledged_cents=60_000,
                             pledge_expiry_at="2026-08-10T00:00:00Z")

        clock = validate_success(
            api.set_clock("2026-09-01T00:00:00Z", ADMIN))
        assert clock["current_utc"] == "2026-09-01T00:00:00Z"

        # A receive attempted after expiry fails and flips the agreement.
        resp = api.receive_ciac_agreement(ciac_a["id"], RATES)
        validate_error(resp, ApiErrorId.ERR_CIAC_EXPIRED, 422)
        view_a = validate_success(api.get_ciac_agreement(ciac_a["id"], AUDITOR))
        assert view_a["status"] == "EXPIRED"

        # The never-touched pledge is swept to EXPIRED by the period close.
        close_period(period["id"])
        view_b = validate_success(api.get_ciac_agreement(ciac_b["id"], AUDITOR))
        assert view_b["status"] == "EXPIRED"


class TestCiacRefundForfeiture:
    def test_ciac_refund_forfeiture_depends_on_cancel_state(self, api):
        """PRD §3.7: "Because an order cancelled from `AUTHORIZED` never reached `IN_PROGRESS`, its `RECEIVED` CIAC agreements are refunded in full — `forfeited_cents` of zero and `refunded_cents` equal to the `received_cents`, the agreement ending `REFUNDED` — while any still `PLEDGED` become `CANCELLED`."
        PRD §3.7: "From `IN_PROGRESS`, the same budget release, write-off, and CIAC cascades apply with one sharpening: the refund now carries a ten percent forfeiture. The `forfeited_cents` is the `received_cents` multiplied by ten hundredths, rounded half up to a whole cent, and the `refunded_cents` is what remains of the receipt."
        PRD §3.7: "With disposition `EXPENSE`, the program's `expense_writeoff_cents` increases by the order's `cwip_cents`."

        Design: Corner/state_machines/ciac_refund_forfeiture_depends_on_cancel_state
        """
        program = create_program(code="CAP-FORF")
        create_schedule()  # MATERIAL / CAPITAL @ 0%
        create_period()

        # WO-A: authorized (never started) with a received 50,000c pledge.
        wo_a = create_authorized_work_order(program["id"], title="Cancel early",
                                            initial_estimated_cost_cents=400_000)
        ciac_a = create_received_ciac(wo_a["id"], pledged_cents=50_000)

        # WO-B: started, carrying 20,000c of CWIP and a received 50,000c pledge.
        wo_b = create_in_progress_work_order(program["id"], title="Cancel late",
                                             initial_estimated_cost_cents=400_000)
        post_charge(wo_b["id"], base_amount_cents=20_000, charge_date="2026-08-10")
        ciac_b = create_received_ciac(wo_b["id"], pledged_cents=50_000)

        # Cancel from AUTHORIZED: full refund, zero forfeiture, no disposition
        # needed because no CWIP has accrued.
        cancelled_a = validate_success(api.cancel_work_order(wo_a["id"], SUPERVISOR))
        assert cancelled_a["status"] == "CANCELLED"
        view_a = validate_success(api.get_ciac_agreement(ciac_a["id"], AUDITOR))
        assert view_a["status"] == "REFUNDED"
        assert view_a["forfeited_cents"] == 0
        assert view_a["refunded_cents"] == 50_000

        # Cancel from IN_PROGRESS: ten percent forfeiture.
        cancelled_b = validate_success(api.cancel_work_order(
            wo_b["id"], SUPERVISOR, payload={"writeoff_disposition": "EXPENSE"}))
        assert cancelled_b["status"] == "CANCELLED"
        view_b = validate_success(api.get_ciac_agreement(ciac_b["id"], AUDITOR))
        assert view_b["status"] == "REFUNDED"
        assert view_b["forfeited_cents"] == 5_000, (
            "round_half_up(50,000 * 0.10)")
        assert view_b["refunded_cents"] == 45_000

        program_view = get_program(program["id"])
        assert program_view["expense_writeoff_cents"] == 20_000


class TestWriteoffDisposition:
    def test_writeoff_disposition_required_on_cancel(self, api):
        """PRD §3.7: "From `AUTHORIZED` the consequences deepen. The committed budget is released — the program's `committed_amount_cents` decreases by the order's `approved_estimate_cents` — and whenever the order's `cwip_cents` is greater than zero, the cancellation request must carry a `writeoff_disposition`, else it is rejected with `ERR_WRITEOFF_DISPOSITION_REQUIRED` (HTTP 400); choosing `REGULATORY_DEFERRAL` additionally requires a `writeoff_amortization_months` term. With disposition `EXPENSE`, the program's `expense_writeoff_cents` increases by the order's `cwip_cents`."
        PRD §3.7: "From `IN_PROGRESS`, the same budget release, write-off, and CIAC cascades apply with one sharpening: the refund now carries a ten percent forfeiture."
        PRD §3.7: "The chosen disposition is recorded on the order as `cancel_writeoff_disposition`, taking `EXPENSE` or `REGULATORY_DEFERRAL`."

        Design: Corner/validations/writeoff_disposition_required_on_cancel
        """
        world = setup_charging_world(estimate_cents=400_000)
        program, wo = world["program"], world["work_order"]
        post_charge(wo["id"], base_amount_cents=20_000, charge_date="2026-08-05")
        assert get_success_data(api.get_work_order(wo["id"], AUDITOR))["cwip_cents"] == 20_000

        # Missing disposition while CWIP > 0.
        resp = api.cancel_work_order(wo["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_WRITEOFF_DISPOSITION_REQUIRED, 400)

        cancelled = validate_success(api.cancel_work_order(
            wo["id"], SUPERVISOR, payload={"writeoff_disposition": "EXPENSE"}))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_writeoff_disposition"] == "EXPENSE"

        program_view = get_program(program["id"])
        assert program_view["expense_writeoff_cents"] == 20_000


class TestRegulatoryAssetReject:
    def test_regulatory_asset_reject_terminal(self, api):
        """PRD §3.7: "Approval sets `approved_by_user_id` and moves `PROPOSED` → `APPROVED`; rejection moves `PROPOSED` → `REJECTED`."
        PRD §2.8: "7. State legality — the target entity is not in a legal from-state for the requested transition — `ERR_INVALID_STATE` or the domain-specific state error (`ERR_WORK_ORDER_SUSPENDED`, `ERR_PROGRAM_CLOSED`, `ERR_CHARGE_ALREADY_REVERSED`, `ERR_REVERSAL_NOT_ALLOWED`, `ERR_UNIT_ALREADY_RETIRED`, `ERR_PERIOD_ALREADY_OPEN`, `ERR_PERIOD_REOPEN_NOT_LATEST`)."

        Design: Corner/state_machines/regulatory_asset_reject_terminal
        """
        ra = create_reg_asset(description="Dubious deferral", original_cents=9_000,
                              amortization_months=3)
        rejected = validate_success(api.reject_regulatory_asset(ra["id"], CONTROLLER))
        assert rejected["status"] == "REJECTED"

        # REJECTED is terminal: approval is no longer a legal transition.
        resp = api.approve_regulatory_asset(ra["id"], CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        view = validate_success(api.get_regulatory_asset(ra["id"], AUDITOR))
        assert view["status"] == "REJECTED"
        assert view["remaining_cents"] == 9_000, "a rejected asset never amortizes"
