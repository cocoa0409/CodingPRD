"""Term closeout: enrollment/account sweeps, forfeiture, refunds, and settlement
gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_term_week,
    close_term,
    create_and_publish_plan,
    create_holder,
    create_merchant,
    create_settlement_draft,
    create_term,
    create_verified_card,
    enroll_holder,
    file_dispute,
    fund_account,
    get_success_data,
    grant_provisional_credit,
    make_bursar_headers,
    make_cardholder_headers,
    open_account,
    open_term,
    post_pos_transaction,
    request_refund,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import activate_merchant

DINING = TEST_USERS["dining_manager_headers"]
BURSAR = TEST_USERS["bursar_headers"]
ADMIN = TEST_USERS["card_office_admin_headers"]


class TestTermCloseCascade:
    def test_close_closes_enrollments_and_sweeps_healthy_accounts(self, api):
        """PRD §3.7: "First, every enrollment of the term in `ACTIVE` becomes
        `CLOSED` — unused swipes simply lapse with no compensation — and every
        enrollment still `ASSIGNED` becomes `CANCELLED`. Second, each enrollment
        closure sweeps the enrollment-linked `DINING_DOLLARS` account for the term
        from `OPEN` or `FROZEN` into `CLOSE_PENDING`"

        Design: Difficulty/transitive_cascade/term_close_enrollment_account_forfeiture_cascade
        """
        ids = _setup_term_close_scenario(api)
        close_term(ids["term_id"])

        enrollment = get_success_data(api.get_enrollment(ids["ea_id"], DINING))
        assert enrollment["status"] == "CLOSED"

        acct_a, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": ids["ha_id"],
                                       "term_id": ids["term_id"]}))
        assert len(acct_a) == 1
        assert acct_a[0]["status"] == "CLOSE_PENDING"
        assert acct_a[0]["balance_cents"] == 9700  # 10000 grant - 300 spent

    def test_close_forfeits_sub_threshold_accounts(self, api):
        """PRD §3.7: "each account entering `CLOSE_PENDING` at term close is
        immediately evaluated against the forfeiture threshold: when its
        `balance_cents` is below the minimum refund amount of 1000 cents, the
        account posts a `FORFEIT` entry for its full balance and continues straight
        to `FORFEITED`, zeroing it."

        Design: Difficulty/transitive_cascade/term_close_enrollment_account_forfeiture_cascade
        """
        ids = _setup_term_close_scenario(api)
        close_term(ids["term_id"])

        acct_b, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": ids["hb_id"],
                                       "term_id": ids["term_id"]}))
        assert len(acct_b) == 1
        assert acct_b[0]["status"] == "FORFEITED"
        assert acct_b[0]["balance_cents"] == 0

        forfeits, _ = validate_paginated(
            api.list_ledger_entries(BURSAR, {"account_id": acct_b[0]["id"],
                                             "entry_type": "FORFEIT"}))
        assert len(forfeits) == 1
        assert forfeits[0]["amount_cents"] == 500  # 10000 - 5000 - 4500


class TestRefundVariants:
    def test_refund_auto_excludes_unresolved_provisional(self, api):
        """PRD §3.7: "`FULL_BALANCE`, which refunds the account's entire
        `balance_cents`, is selectable only when that unresolved sum is zero;
        whenever unresolved provisional credits exist, the request is computed
        under `AUTO_EXCLUDING_PROVISIONAL`, which refunds the balance minus the
        unresolved provisional sum, floored at zero."
        PRD §3.7: "when a residual remains — the residue of provisional credits
        excluded from the refund — the account stays `CLOSE_PENDING`, and a later
        refund request may capture the residue once those disputes resolve."

        Design: Corner/calculations/refund_auto_excludes_unresolved_provisional
        """
        ids = _setup_refund_with_provisional(api, spends=(1200,),
                                             dispute_index=0)
        account_id = ids["account_id"]
        request = request_refund(account_id, ids["h_id"])
        assert request["refund_variant"] == "AUTO_EXCLUDING_PROVISIONAL"
        assert request["amount_cents"] == 8800  # 10000 - 1200 unresolved

        validate_success(api.approve_refund_request(
            request["id"], make_bursar_headers("bursar-1")), 200)
        paid = validate_success(
            api.pay_refund_request(request["id"], make_bursar_headers("bursar-2")),
            200)
        assert paid["status"] == "PAID"

        account = get_success_data(api.get_account(account_id, BURSAR))
        assert account["balance_cents"] == 1200
        assert account["status"] == "CLOSE_PENDING"

    def test_refund_full_balance_pays_out_and_closes(self, api):
        """PRD §3.7: "`FULL_BALANCE`, which refunds the account's entire
        `balance_cents`, is selectable only when that unresolved sum is zero"
        PRD §3.7: "Payment of an `APPROVED` request requires the payer to differ
        from the `approved_by` (`ERR_SOD_PAYER_IS_APPROVER`), records `paid_by`,
        and posts a `REFUND_PAYOUT` entry of the request's `amount_cents`. When the
        payout zeroes the account's `balance_cents`, the account becomes
        `REFUNDED`"

        Design: Corner/calculations/refund_full_balance_pays_out_and_closes
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-RF")
        plan = create_and_publish_plan(plan_code="P-RF",
                                       eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        holder = create_holder(university_id="U91007", full_name="Ali RefF",
                               email="ali@x.edu")
        enroll_holder(holder["id"], plan["id"], term["id"])
        accounts, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": holder["id"],
                                       "term_id": term["id"]}))
        account_id = accounts[0]["id"]
        set_clock("2026-12-14T00:00:00Z")
        close_term(term["id"])

        request = request_refund(account_id, holder["id"])
        assert request["refund_variant"] == "FULL_BALANCE"
        assert request["amount_cents"] == 10000

        validate_success(api.approve_refund_request(
            request["id"], make_bursar_headers("bursar-1")), 200)
        paid = validate_success(
            api.pay_refund_request(request["id"], make_bursar_headers("bursar-2")),
            200)
        assert paid["status"] == "PAID"
        account = get_success_data(api.get_account(account_id, BURSAR))
        assert account["balance_cents"] == 0
        assert account["status"] == "REFUNDED"

    def test_refund_below_minimum_after_provisional_exclusion_rejected(self, api):
        """PRD §3.7: "In both variants the computed `amount_cents` must be at
        least the minimum refund amount of 1000 cents, or the request is rejected
        with `ERR_REFUND_BELOW_MINIMUM`."

        Design: Corner/calculations/refund_below_minimum_after_provisional_exclusion_rejected
        """
        ids = _setup_refund_with_provisional(
            api, spends=(5000, 3500, 700), dispute_index=2)
        resp = api.create_refund_request(ids["account_id"],
                                         make_cardholder_headers(ids["h_id"]))
        validate_error(resp, ApiErrorId.ERR_REFUND_BELOW_MINIMUM)  # 1500-700 = 800
        requests, _ = validate_paginated(
            api.list_refund_requests(BURSAR, {"account_id": ids["account_id"]}))
        assert requests == []


class TestRefundRequestGuards:
    def test_refund_request_on_open_account_rejected(self, api):
        """PRD §3.7: "requesting against an account in any other state is rejected
        with `ERR_ACCOUNT_NOT_CLOSABLE`"

        Design: Corner/validations/refund_request_on_open_account_rejected
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U92017", full_name="Amy Open",
                               email="amy@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        account = open_account(holder["id"], "CAMPUS_CASH")
        fund_account(account["id"], 2000)

        resp = api.create_refund_request(account["id"],
                                         make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_CLOSABLE)

    def test_second_pending_refund_request_rejected(self, api):
        """PRD §3.7: "requesting while another request on the same account is
        `REQUESTED` or `APPROVED` is rejected with `ERR_PENDING_REFUND_EXISTS`."

        Design: Corner/validations/second_pending_refund_request_rejected
        """
        holder, account = _setup_withdrawn_with_close_pending(api, 2000)
        request_refund(account["id"], holder["id"])
        resp = api.create_refund_request(account["id"],
                                         make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_PENDING_REFUND_EXISTS)

    def test_refund_pay_before_approval_rejected(self, api):
        """PRD §3.7: "Payment of an `APPROVED` request requires the payer to
        differ from the `approved_by` (`ERR_SOD_PAYER_IS_APPROVER`)" — payment is
        defined only from `APPROVED`.
        PRD §2.10: "**State transition legality** — the target resource's state
        permits the requested transition, including terminal-state lockout,
        invalid-from rejection, and any state-machine precondition, else
        `ERR_INVALID_STATE_TRANSITION` (409)."

        Design: Corner/state_machines/refund_pay_before_approval_rejected
        """
        holder, account = _setup_withdrawn_with_close_pending(api, 2000)
        request = request_refund(account["id"], holder["id"])
        assert request["refund_variant"] == "FULL_BALANCE"
        assert request["amount_cents"] == 2000

        resp = api.pay_refund_request(request["id"], make_bursar_headers("bursar-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        still = get_success_data(api.get_refund_request(request["id"], BURSAR))
        assert still["status"] == "REQUESTED"


class TestRefundSegregationOfDuties:
    def test_refund_sod_adjuster_approver_payer_chain(self, api):
        """PRD §3.7: "Approval requires the approver's `X-User-ID` to differ from
        the account's `last_adjusted_by` — the bursar user who last posted a manual
        adjustment to that account may not approve its refund
        (`ERR_SOD_ADJUSTER_CANNOT_APPROVE`)"
        PRD §3.7: "Payment of an `APPROVED` request requires the payer to differ
        from the `approved_by` (`ERR_SOD_PAYER_IS_APPROVER`), records `paid_by`,
        and posts a `REFUND_PAYOUT` entry of the request's `amount_cents`."

        Design: Corner/rbac/refund_sod_adjuster_approver_payer_chain
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U94004", full_name="Sid Refund",
                               email="sid@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        account = open_account(holder["id"], "CAMPUS_CASH")
        fund_account(account["id"], 2000, key="sid-f",
                     headers=make_bursar_headers("bursar-1"))
        fresh = get_success_data(api.get_account(account["id"], BURSAR))
        adj = api.adjust_account(
            account["id"],
            {"amount_cents": 500, "direction": "CREDIT", "reason": "goodwill",
             "expected_account_version": fresh["version"]},
            make_bursar_headers("bursar-3"))
        validate_success(adj, 201)

        get_success_data(api.withdraw_card_holder(holder["id"], ADMIN))
        request = request_refund(account["id"], holder["id"])
        assert request["amount_cents"] == 2500  # 2000 fund + 500 adjustment

        bad_approve = api.approve_refund_request(request["id"],
                                                 make_bursar_headers("bursar-3"))
        validate_error(bad_approve, ApiErrorId.ERR_SOD_ADJUSTER_CANNOT_APPROVE)
        validate_success(api.approve_refund_request(
            request["id"], make_bursar_headers("bursar-4")), 200)

        bad_pay = api.pay_refund_request(request["id"],
                                         make_bursar_headers("bursar-4"))
        validate_error(bad_pay, ApiErrorId.ERR_SOD_PAYER_IS_APPROVER)
        paid = validate_success(api.pay_refund_request(
            request["id"], make_bursar_headers("bursar-5")), 200)
        assert paid["status"] == "PAID"

        account_now = get_success_data(api.get_account(account["id"], BURSAR))
        assert account_now["balance_cents"] == 0
        assert account_now["status"] == "REFUNDED"


class TestTermSettleGating:
    def test_term_settle_blocked_by_outstanding_refund(self, api):
        """PRD §3.7: "Settling requires that no refund request in `REQUESTED` or
        `APPROVED` exists on any account bound to the term
        (`ERR_REFUNDS_OUTSTANDING`)"

        Design: Corner/validations/term_settle_blocked_by_outstanding_refund
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-SBL")
        plan = create_and_publish_plan(plan_code="P-SBL",
                                       eligible_holder_types=["STUDENT_COMMUTER"])
        open_term(term["id"])
        holder = create_holder(university_id="U92018", full_name="Bo Settle",
                               email="bo@x.edu")
        enroll_holder(holder["id"], plan["id"], term["id"])
        accounts, _ = validate_paginated(
            api.list_accounts(BURSAR, {"holder_id": holder["id"],
                                       "term_id": term["id"]}))
        set_clock("2026-12-14T00:00:00Z")
        close_term(term["id"])
        request_refund(accounts[0]["id"], holder["id"])

        resp = api.settle_term(term["id"], DINING)
        validate_error(resp, ApiErrorId.ERR_REFUNDS_OUTSTANDING)
        still = get_success_data(api.get_term(term["id"], DINING))
        assert still["status"] == "CLOSED"

    def test_term_settle_and_merchant_terminate_blocked_by_open_settlement(self,
                                                                           api):
        """PRD §3.7: "no merchant settlement for the term sits in `DRAFT`,
        `SUBMITTED`, or `APPROVED` (`ERR_SETTLEMENTS_OUTSTANDING`)"
        PRD §3.9: "termination requires that no settlement of the merchant sits in
        `DRAFT`, `SUBMITTED`, or `APPROVED` (`ERR_SETTLEMENTS_OUTSTANDING`)"

        Design: Corner/validations/term_settle_and_merchant_terminate_blocked_by_open_settlement
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-SBO")
        open_term(term["id"])
        merchant = create_merchant(merchant_code="M-SBO", commission_bps=100,
                                   category="OTHER")
        activate_merchant(merchant["id"])
        create_settlement_draft(merchant["id"], term["id"])
        set_clock("2026-12-14T00:00:00Z")
        close_term(term["id"])

        settle_resp = api.settle_term(term["id"], DINING)
        validate_error(settle_resp, ApiErrorId.ERR_SETTLEMENTS_OUTSTANDING)
        term_now = get_success_data(api.get_term(term["id"], DINING))
        assert term_now["status"] == "CLOSED"

        terminate_resp = api.terminate_merchant(merchant["id"], BURSAR)
        validate_error(terminate_resp, ApiErrorId.ERR_SETTLEMENTS_OUTSTANDING)
        merchant_now = get_success_data(api.get_merchant(merchant["id"], BURSAR))
        assert merchant_now["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _setup_term_close_scenario(api):
    """FALLCL OPEN since week 1; plan COMM5-CL published (dining 10000); holder A
    enrolled (spent 300 -> 9700) and holder B enrolled (spent 9500 -> 500); clock
    moved past end_date."""
    set_clock("2026-08-24T09:00:00Z")
    term = create_term(term_code="FALLCL")
    plan = create_and_publish_plan(
        plan_code="COMM5-CL",
        eligible_holder_types=["STUDENT_COMMUTER", "STUDENT_RESIDENT"])
    open_term(term["id"])
    ha = create_holder(university_id="U5002", full_name="Ivy A", email="ivy@x.edu")
    hb = create_holder(university_id="U5003", full_name="Jay B", email="jay@x.edu")
    ea = enroll_holder(ha["id"], plan["id"], term["id"])
    enroll_holder(hb["id"], plan["id"], term["id"])
    ca = create_verified_card(ha["id"])
    cb = create_verified_card(hb["id"])
    post_pos_transaction(ca["id"], "DINING_DOLLARS", 300, key="cl-a1")
    post_pos_transaction(cb["id"], "DINING_DOLLARS", 5000, key="cl-b1")
    post_pos_transaction(cb["id"], "DINING_DOLLARS", 4500, key="cl-b2")
    set_clock("2026-12-14T00:00:00Z")
    return {"term_id": term["id"], "ha_id": ha["id"], "hb_id": hb["id"],
            "ea_id": ea["id"]}


def _setup_refund_with_provisional(api, spends, dispute_index):
    """Enrolled holder (dining grant 10000), DINING_DOLLARS purchases per
    `spends`, the spend at `dispute_index` disputed and provisionally credited,
    then the term closed."""
    set_clock("2026-08-24T09:00:00Z")
    term = create_term(term_code="T-RA")
    plan = create_and_publish_plan(plan_code="P-RA",
                                   eligible_holder_types=["STUDENT_COMMUTER"])
    open_term(term["id"])
    holder = create_holder(university_id="U91006", full_name="Zoe RefA",
                           email="zoe@x.edu")
    enroll_holder(holder["id"], plan["id"], term["id"])
    card = create_verified_card(holder["id"])
    txs = [post_pos_transaction(card["id"], "DINING_DOLLARS", amount,
                                key=f"ra-{i}")
           for i, amount in enumerate(spends)]
    disputed_tx = txs[dispute_index]
    dispute = file_dispute(disputed_tx["id"], holder["id"], "SERVICE_NOT_RECEIVED")
    grant_provisional_credit(dispute["id"], analyst="fraud-1")
    set_clock("2026-12-14T00:00:00Z")
    close_term(term["id"])
    return {"h_id": holder["id"], "account_id": disputed_tx["account_id"]}


def _setup_withdrawn_with_close_pending(api, fund_cents):
    """CAMPUS_CASH funded, holder withdrawn (account sweeps to CLOSE_PENDING)."""
    set_clock("2026-08-25T09:00:00Z")
    holder = create_holder(university_id="U92006", full_name="Pam Refund",
                           email="pam@x.edu", holder_type="STAFF",
                           housing_status="OFF_CAMPUS")
    account = open_account(holder["id"], "CAMPUS_CASH")
    fund_account(account["id"], fund_cents)
    get_success_data(api.withdraw_card_holder(holder["id"], ADMIN))
    account_now = get_success_data(api.get_account(account["id"], BURSAR))
    assert account_now["status"] == "CLOSE_PENDING"
    return holder, account
