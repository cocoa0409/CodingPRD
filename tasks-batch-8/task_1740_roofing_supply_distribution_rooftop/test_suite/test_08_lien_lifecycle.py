"""Lien lifecycle: notice, cure period, recording cascade, release, and the
order-confirmation block."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    confirm_order,
    convert_to_order,
    create_quoted_takeoff,
    file_lien_notice,
    get_success_data,
    make_account,
    make_contractor_headers,
    make_job,
    setup_invoiced_order,
    setup_job_with_invoice_balance,
    validate_error,
    validate_success,
    ApiErrorId,
)

CREDIT = TEST_USERS["credit_analyst_headers"]


def _lien_scenario(branch_code, sku, notice_amount):
    """Invoiced order A (job carries the balance) + QUOTED order B awaiting
    confirmation + lien notice filed on the job."""
    ctx = setup_job_with_invoice_balance(branch_code=branch_code, sku=sku,
                                         roof_squares=20.0, price=2000)
    takeoff_b = create_quoted_takeoff(ctx["job"]["id"], ctx["product"]["id"],
                                      5.0, 0, 0)
    order_b = convert_to_order(takeoff_b["id"], ctx["branch"]["id"],
                               ctx["account"]["id"])
    ctx["order_b"] = order_b
    file_lien_notice(ctx["job"]["id"], notice_amount)
    return ctx


class TestLienRecordCascade:
    def test_recorded_lien_sets_account_lien_default_and_blocks_order(self, api):
        """PRD §3.7: "Recording moves the job to `LIEN_RECORDED` and, because
        a recorded lien signals default, automatically moves the parent
        contractor account to `LIEN_DEFAULT`; from that moment the job blocks
        all new order confirmations with `ERR_LIEN_BLOCKS_ORDER` (§3.4)."

        Design: Difficulty/transitive_cascade/lien_record_cascades_to_account_and_blocks_order
        """
        ctx = _lien_scenario("BR-L1", "SH-L1", 50000)
        advance_clock("2026-08-20T00:00:00Z")
        job = get_success_data(api_client.record_lien(ctx["job"]["id"], CREDIT))
        assert job["lien_status"] == "LIEN_RECORDED"
        account = get_success_data(
            api_client.get_contractor_account(ctx["account"]["id"], CREDIT))
        assert account["status"] == "LIEN_DEFAULT"

        resp = api_client.confirm_order(
            ctx["order_b"]["id"], account["version"],
            make_contractor_headers(ctx["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LIEN_BLOCKS_ORDER)

    def test_release_after_payoff_reverts_account_to_active(self, api):
        """PRD §3.7: "Releasing subtracts the notice amount from the account's
        `lien_hold_cents`, zeroes `lien_notice_amount_cents`, clears
        `notice_filed_at` back to null, and lands the job in the terminal
        `RELEASED` state; when no job account on the account remains in
        `NOTICE_FILED` or `LIEN_RECORDED`, the account's `status` reverts
        automatically to `ACTIVE`."

        Design: Difficulty/transitive_cascade/lien_record_cascades_to_account_and_blocks_order
        """
        ctx = _lien_scenario("BR-L2", "SH-L2", 50000)
        advance_clock("2026-08-20T00:00:00Z")
        get_success_data(api_client.record_lien(ctx["job"]["id"], CREDIT))
        # Pay the invoiced balance down to exactly zero.
        job = get_success_data(api_client.get_job_account(ctx["job"]["id"],
                                                          CREDIT))
        get_success_data(api_client.post_payment(
            ctx["account"]["id"],
            {"amount_cents": job["job_balance_cents"],
             "job_account_id": ctx["job"]["id"]}, CREDIT))
        released = validate_success(
            api_client.release_lien(ctx["job"]["id"], CREDIT))
        assert released["lien_status"] == "RELEASED"
        assert released["lien_notice_amount_cents"] == 0
        assert released["notice_filed_at"] is None
        account = get_success_data(
            api_client.get_contractor_account(ctx["account"]["id"], CREDIT))
        assert account["status"] == "ACTIVE"
        assert account["lien_hold_cents"] == 0
        # The cascade unwound: the blocked order can now confirm.
        confirmed = confirm_order(ctx["order_b"]["id"], ctx["account"]["id"])
        assert confirmed["status"] == "CONFIRMED"


class TestOrderConfirmBlockedByJobLien:
    def test_confirm_blocked_once_lien_recorded(self, api):
        """PRD §3.4: "Finally, a job account sitting in `LIEN_RECORDED` blocks
        confirmation outright with `ERR_LIEN_BLOCKS_ORDER`."

        The order's own state and credit are fine; the parent job's recorded
        lien is what rejects the confirm.

        Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_job_lien_recorded
        """
        ctx = setup_job_with_invoice_balance(branch_code="BR-X1",
                                             sku="SH-X1", roof_squares=10.0,
                                             price=2000)
        takeoff_b = create_quoted_takeoff(ctx["job"]["id"],
                                          ctx["product"]["id"], 5.0, 0, 0)
        order_b = convert_to_order(takeoff_b["id"], ctx["branch"]["id"],
                                   ctx["account"]["id"])
        file_lien_notice(ctx["job"]["id"], 30000)
        advance_clock("2026-08-20T00:00:00Z")
        get_success_data(api_client.record_lien(ctx["job"]["id"], CREDIT))
        account = get_success_data(
            api_client.get_contractor_account(ctx["account"]["id"], CREDIT))
        resp = api_client.confirm_order(
            order_b["id"], account["version"],
            make_contractor_headers(ctx["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LIEN_BLOCKS_ORDER)

    def test_confirm_allowed_while_lien_only_in_notice(self, api):
        """PRD §3.4: "Finally, a job account sitting in `LIEN_RECORDED` blocks
        confirmation outright with `ERR_LIEN_BLOCKS_ORDER`."
        PRD §3.7: "Filing stamps `notice_filed_at` with the current logical
        clock, moves the job to `NOTICE_FILED`, and adds the notice amount to
        the account's `lien_hold_cents`, immediately shrinking
        `credit_available_cents`."

        Control arm: a filed-but-not-recorded notice only shrinks available
        credit; it does not block confirmation.

        Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_job_lien_recorded
        """
        ctx = setup_job_with_invoice_balance(branch_code="BR-X2", sku="SH-X2",
                                             roof_squares=10.0, price=2000)
        takeoff_b = create_quoted_takeoff(ctx["job"]["id"],
                                          ctx["product"]["id"], 5.0, 0, 0)
        order_b = convert_to_order(takeoff_b["id"], ctx["branch"]["id"],
                                   ctx["account"]["id"])
        file_lien_notice(ctx["job"]["id"], 30000)
        job = get_success_data(api_client.get_job_account(ctx["job"]["id"],
                                                          CREDIT))
        assert job["lien_status"] == "NOTICE_FILED"
        confirmed = confirm_order(order_b["id"], ctx["account"]["id"])
        assert confirmed["status"] == "CONFIRMED"


class TestLienGuards:
    def test_lien_notice_requires_positive_job_balance(self, api):
        """PRD §3.7: "filing requires the job's `lien_status` to be `NONE` (an
        active lien draws `ERR_LIEN_ALREADY_ACTIVE`), requires a positive
        `job_balance_cents` (otherwise `ERR_NO_OUTSTANDING_BALANCE`), and
        requires the notice amount to be greater than zero and no more than
        the outstanding job balance (otherwise `ERR_INVALID_LIEN_AMOUNT`)."

        Design: Corner/validations/lien_notice_requires_positive_balance
        """
        account = make_account(name="NoBal Co")
        job = make_job(account["id"], job_name="Job VL6")
        resp = api_client.file_lien_notice(job["id"], 10000, CREDIT)
        validate_error(resp, ApiErrorId.ERR_NO_OUTSTANDING_BALANCE)

    def test_record_lien_within_cure_period_rejected(self, api):
        """PRD §3.7: "The job must be in `NOTICE_FILED` (otherwise
        `ERR_LIEN_NOT_IN_NOTICE`), and the cure period must have run: the
        logical clock must have reached at least ten days after
        `notice_filed_at`, otherwise the recording is rejected with
        `ERR_LIEN_CURE_PERIOD_ACTIVE`."

        Notice filed at the 2026-08-01 default clock; only 5 days elapse.

        Design: Corner/validations/record_lien_within_cure_period_rejected
        """
        ctx = setup_invoiced_order(branch_code="BR-VL7", sku="SH-VL7",
                                   roof_squares=5.0, lot_code="LOT-VL7",
                                   company_name="Cure Co")
        file_lien_notice(ctx["job"]["id"], 20000)
        advance_clock("2026-08-06T00:00:00Z")
        resp = api_client.record_lien(ctx["job"]["id"], CREDIT)
        validate_error(resp, ApiErrorId.ERR_LIEN_CURE_PERIOD_ACTIVE)
