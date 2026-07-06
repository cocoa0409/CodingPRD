"""Business-constraint validations: onboarding gates, ledger rules, AP/forecast guards."""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId,
    create_client, create_onboarded_client, create_active_client,
    create_active_ledger_account, setup_forecast_with_min_balance,
    current_client_version,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestOnboardingGates:
    def test_activate_engagement_before_onboarded_rejected(self, api):
        """PRD §3.1: "it is allowed only when `engagement_status` is `PROSPECT` or
        `PAUSED`, and in both cases it additionally requires that `onboarding_status`
        already be `ONBOARDED`; an attempt while onboarding is incomplete is rejected
        with `ERR_ONBOARDING_INCOMPLETE`."

        Design: Corner/validations/activate_engagement_before_onboarded_409
        """
        client = create_client(retainer_tier="GROWTH")  # LEAD / PROSPECT
        resp = api.activate_engagement(client["id"], CFO)
        validate_error(resp, ApiErrorId.ERR_ONBOARDING_INCOMPLETE.value)

    def test_complete_onboarding_with_no_ledger_rejected(self, api):
        """PRD §3.1: "this transition additionally requires that the client already
        have at least one `LedgerAccount` whose `status` is `ACTIVE`, and is
        otherwise rejected with `ERR_NO_LEDGER_ACCOUNTS`."

        Design: Corner/validations/complete_onboarding_no_ledger_409
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        get_success_data(api.schedule_kickoff(cid, CFO))
        get_success_data(api.start_ledger_setup(cid, BK))  # LEDGER_SETUP, no accounts
        resp = api.complete_onboarding(cid, CFO)
        validate_error(resp, ApiErrorId.ERR_NO_LEDGER_ACCOUNTS.value)


class TestOffboardGate:
    def test_offboard_with_open_close_rejected(self, api):
        """PRD §3.1: "Offboarding is a `CFO` action permitted when
        `engagement_status` is either `ACTIVE` or `PAUSED`; it additionally requires
        `open_close_count` to be zero — that is, the client may not be offboarded
        while any non-finalized monthly close remains — and is otherwise rejected
        with `ERR_OPEN_CLOSES_EXIST`."

        Design: Corner/validations/offboard_with_open_close_409
        """
        client = create_active_client(retainer_tier="GROWTH")
        cid = client["id"]
        get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 1, "txn_count": 10}, BK))
        resp = api.offboard(cid, CFO)
        validate_error(resp, ApiErrorId.ERR_OPEN_CLOSES_EXIST.value)


class TestLedgerAccountConstraints:
    def test_duplicate_account_code_same_client_rejected(self, api):
        """PRD §3.2: "the `account_code` must be unique among the client's
        non-`ARCHIVED` accounts; reusing a code already held by an `ACTIVE` account
        of the same client is rejected with `ERR_DUPLICATE_ACCOUNT_CODE`."

        Design: Corner/validations/duplicate_account_code_same_client_409
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        create_active_ledger_account(cid, account_code="4000",
                                     account_type="REVENUE", name="Sales")
        resp = api.create_ledger_account(
            cid, {"account_code": "4000", "account_type": "REVENUE", "name": "Sales Dup"}, BK)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT_CODE.value)

    def test_parent_account_in_other_client_rejected(self, api):
        """PRD §3.2: "when a `parent_account_id` is supplied, it must reference an
        `ACTIVE` account belonging to the *same* client; a parent that lives under a
        different client, or a parent that is not `ACTIVE`, is a cross-client
        reference and is rejected with `ERR_CROSS_CLIENT_PARENT`."

        Design: Corner/validations/ledger_parent_in_other_client_422
        """
        client_a = create_client(retainer_tier="GROWTH", legal_name="AClient")
        la_a = create_active_ledger_account(
            client_a["id"], account_code="1000", account_type="ASSET", name="Cash A")
        client_b = create_client(retainer_tier="GROWTH", legal_name="BClient")
        resp = api.create_ledger_account(
            client_b["id"],
            {"account_code": "1100", "account_type": "ASSET", "name": "Sub B",
             "parent_account_id": la_a["id"]}, BK)
        validate_error(resp, ApiErrorId.ERR_CROSS_CLIENT_PARENT.value)


class TestApScheduleGate:
    def test_schedule_ap_bill_without_date_rejected(self, api):
        """PRD §3.5: "A `Bookkeeper` schedules an approved bill (`APPROVED →
        SCHEDULED`) by supplying the `scheduled_pay_date`, which is required for this
        step — scheduling without it is rejected with `ERR_MISSING_SCHEDULE_DATE`."

        Design: Corner/validations/schedule_ap_bill_missing_required_date_422
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        bill = get_success_data(api.create_ap_bill(
            cid, {"vendor_name": "V", "amount_cents": 50000,
                  "due_date": "2026-04-15T00:00:00Z"}, BK))
        get_success_data(api.approve_ap_bill(bill["id"], CFO))
        resp = api.schedule_ap_bill(bill["id"], {}, BK)
        validate_error(resp, ApiErrorId.ERR_MISSING_SCHEDULE_DATE.value)


class TestCovenantBreach:
    def test_approve_below_floor_breaches(self, api):
        """PRD §3.7: "an approval whose minimum falls below the floor is rejected
        with `ERR_COVENANT_BREACH`."

        Design: Corner/validations/covenant_breach_below_floor_422
        """
        cid, fid = setup_forecast_with_min_balance(
            covenant_floor_cents=400000, opening_balance_cents=500000, outflow_cents=100001)
        forecast = get_success_data(api.get_forecast(fid, CFO))
        assert forecast["min_projected_balance_cents"] == 399999
        cver = current_client_version(cid)
        resp = api.approve_forecast(fid, {"expected_client_version": cver}, CFO)
        validate_error(resp, ApiErrorId.ERR_COVENANT_BREACH.value)
