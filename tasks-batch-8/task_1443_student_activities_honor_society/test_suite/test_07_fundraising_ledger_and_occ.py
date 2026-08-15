"""The activity fund: fundraiser submission fiscal gate, approval ladder with
segregation of duties and OCC on the chapter version, execution-time ledger
cascade, and the fund-balance roll-up."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_fundraiser,
    assert_ledger_entry,
    clear_ledger_entry,
    create_fundraiser,
    execute_fundraiser,
    find_ledger_entry,
    get_chapter,
    list_ledger_entries,
    make_advisor_headers,
    make_director_headers,
    make_officer_headers,
    setup_chapter_with_officer,
    setup_funded_chapter,
    setup_fundraiser_director_approved,
    setup_fundraiser_submitted,
    submit_fundraiser,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADVISOR = TEST_USERS["advisor_headers"]


class TestFiscalGateOnSubmit:
    def test_upfront_above_balance_rejected(self):
        """PRD section 3.5: "the chapter's `fund_balance_cents` must be at
        least the request's `upfront_cost_cents` — a chapter may never commit
        to front money it does not have, and an overcommitted request is
        rejected with `ERR_INSUFFICIENT_CHAPTER_FUNDS` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_fundraiser_submit
        """
        env = setup_chapter_with_officer(office="PRESIDENT")
        fundraiser = create_fundraiser(env["chapter"]["id"], env["role"],
                                       env["officer_member"],
                                       upfront_cost_cents=5000)
        resp = api_client.submit_fundraiser(
            env["chapter"]["id"], fundraiser["id"],
            make_officer_headers(env["officer_member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CHAPTER_FUNDS)
        after = validate_success(api_client.get_fundraiser(
            env["chapter"]["id"], fundraiser["id"], ADVISOR))
        assert after["status"] == "DRAFT"
        chapter = get_chapter(env["chapter"]["id"])
        assert chapter["fund_balance_cents"] == 0

    def test_upfront_equal_to_balance_is_sufficient(self):
        """PRD section 3.5: "the chapter's `fund_balance_cents` must be at
        least the request's `upfront_cost_cents`" — an upfront cost exactly
        equal to the balance satisfies "at least".

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_fundraiser_submit
        """
        env = setup_funded_chapter(5000)
        chapter = get_chapter(env["chapter"]["id"])
        assert chapter["fund_balance_cents"] == 5000
        fundraiser = create_fundraiser(env["chapter"]["id"], env["role"],
                                       env["officer_member"],
                                       upfront_cost_cents=5000)
        submitted = submit_fundraiser(env["chapter"]["id"], fundraiser["id"],
                                      env["officer_member"])
        assert submitted["status"] == "SUBMITTED"


class TestApprovalLadder:
    def test_director_with_advisors_identity_rejected(self):
        """PRD section 3.5: "The second rung belongs to the
        `ActivitiesDirector`, who must not be the same identity as the advisor
        recorded on the first rung: a director approval whose `X-User-ID`
        equals `advisor_approved_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 409)."

        Design: Corner/validations/segregation_of_duties_director_equals_advisor_rejected
        """
        env = setup_fundraiser_submitted(upfront_cost_cents=0)
        ch_id, fr_id = env["chapter"]["id"], env["fundraiser"]["id"]
        chapter = get_chapter(ch_id)
        approved = validate_success(api_client.advisor_approve_fundraiser(
            ch_id, fr_id,
            {"expected_chapter_version": chapter["version"]},
            make_advisor_headers("shared_user")))
        assert approved["status"] == "ADVISOR_APPROVED"
        assert approved["advisor_approved_by_user_id"] == "shared_user"
        resp = api_client.director_approve_fundraiser(
            ch_id, fr_id, make_director_headers("shared_user"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_advisor_approve_with_stale_chapter_version_rejected(self):
        """PRD section 2.9: "If the chapter's current `version` does not match
        — because, for example, another writer has recorded a ledger entry that
        legitimately advanced the chapter's fiscal posture since the client
        read it — the approval is rejected with `ERR_STALE_CHAPTER_VERSION`
        (HTTP 412), preventing the advisor from approving against a fund
        balance they never saw."

        Design: Corner/errors/err_stale_chapter_version_on_advisor_approve
        """
        env = setup_fundraiser_submitted(upfront_cost_cents=0)
        ch_id, fr_id = env["chapter"]["id"], env["fundraiser"]["id"]
        current = get_chapter(ch_id)["version"]
        stale = current - 1
        assert stale >= 1
        resp = api_client.advisor_approve_fundraiser(
            ch_id, fr_id, {"expected_chapter_version": stale}, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_STALE_CHAPTER_VERSION)
        after = validate_success(api_client.get_fundraiser(ch_id, fr_id,
                                                           ADVISOR))
        assert after["status"] == "SUBMITTED"

    def test_officer_cannot_advisor_approve(self):
        """PRD section 2.1: "Once authenticated, access to each operation is
        restricted by role per the endpoint catalogue in §4; an authenticated
        caller attempting an operation outside their role is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 3.5: "The first rung is the advisor's, and it is
        OCC-guarded per §2.9: the approval must carry
        `expected_chapter_version` matching the chapter's current `version`,
        and a stale view — one that predates, say, a freshly recorded ledger
        entry — is rejected with `ERR_STALE_CHAPTER_VERSION` (HTTP 412)."

        Design: Corner/rbac/officer_cannot_advisor_approve_fundraiser
        """
        env = setup_fundraiser_submitted(upfront_cost_cents=0)
        ch_id, fr_id = env["chapter"]["id"], env["fundraiser"]["id"]
        chapter = get_chapter(ch_id)
        resp = api_client.advisor_approve_fundraiser(
            ch_id, fr_id, {"expected_chapter_version": chapter["version"]},
            make_officer_headers(env["officer_member"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestExecutionLedgerCascade:
    def test_execute_writes_pending_deposit_and_computes_net(self):
        """PRD section 3.5: "the system computes `actual_net_cents` as the
        gross receipts minus the request's `upfront_cost_cents`, and the
        request moves from `DIRECTOR_APPROVED` to `EXECUTED`."
        PRD section 3.5: "Execution writes the ledger: a `FundLedgerEntry` of
        type `FUNDRAISER_DEPOSIT` is created with `amount_cents` equal to the
        net proceeds and a status of `PENDING`, and, when the fronted cost was
        greater than zero, a second entry of type `UPFRONT_COST_DISBURSEMENT`
        is created with `amount_cents` equal to the negated upfront cost and a
        status of `CLEARED`."

        Design: Difficulty/transitive_cascade/fundraiser_execute_cascade_ledger_chapter
        """
        env = setup_fundraiser_director_approved(upfront_cost_cents=0)
        fundraiser = execute_fundraiser(env, 50000)
        assert_fundraiser(fundraiser)
        assert fundraiser["status"] == "EXECUTED"
        assert fundraiser["actual_net_cents"] == 50000
        deposit = find_ledger_entry(env["chapter"]["id"], "FUNDRAISER_DEPOSIT",
                                    fundraiser["id"])
        assert_ledger_entry(deposit)
        assert deposit["amount_cents"] == 50000
        assert deposit["status"] == "PENDING"

    def test_clear_deposit_then_close_recomputes_balance(self):
        """PRD section 3.5: "Closing is the fundraiser's final act, from
        `EXECUTED` to `CLOSED`, and the advisor may close only once the deposit
        has actually landed: the ledger entry tied to this fundraiser via
        `fundraiser_id` with type `FUNDRAISER_DEPOSIT` must be `CLEARED`, else
        the close is rejected with `ERR_DEPOSIT_NOT_CLEARED` (HTTP 409)."
        PRD section 3.5: "The balance rule itself is exact: `fund_balance_cents`
        is the sum of `amount_cents` over precisely the chapter's entries in
        `CLEARED` status — `PENDING` entries are excluded, and since every
        amount is stored as integer cents, no rounding arises anywhere in the
        roll-up."

        Design: Difficulty/transitive_cascade/fundraiser_execute_cascade_ledger_chapter
        """
        env = setup_fundraiser_director_approved(upfront_cost_cents=0)
        fundraiser = execute_fundraiser(env, 50000)
        deposit = find_ledger_entry(env["chapter"]["id"], "FUNDRAISER_DEPOSIT",
                                    fundraiser["id"])
        cleared = clear_ledger_entry(env["chapter"]["id"], deposit["id"])
        assert cleared["status"] == "CLEARED"
        chapter = get_chapter(env["chapter"]["id"])
        assert chapter["fund_balance_cents"] == 50000
        closed = validate_success(api_client.close_fundraiser(
            env["chapter"]["id"], fundraiser["id"], ADVISOR))
        assert closed["status"] == "CLOSED"


class TestFundBalanceRollup:
    def test_pending_deposit_excluded_from_balance(self):
        """PRD section 3.5: "The balance rule itself is exact:
        `fund_balance_cents` is the sum of `amount_cents` over precisely the
        chapter's entries in `CLEARED` status — `PENDING` entries are excluded,
        and since every amount is stored as integer cents, no rounding arises
        anywhere in the roll-up."
        PRD section 2.8: "All monetary amounts in the system are integers of
        cents: fundraiser goals and costs, ledger amounts, dues amounts, the
        fund balance, and dues arrears are all whole numbers of cents with no
        fractional part."

        Design: Difficulty/combinatorial_formula/fund_balance_rollup_per_entry_rounding
        """
        env = setup_fundraiser_director_approved(upfront_cost_cents=0)
        fundraiser = execute_fundraiser(env, 133334)
        deposit = find_ledger_entry(env["chapter"]["id"], "FUNDRAISER_DEPOSIT",
                                    fundraiser["id"])
        assert deposit["entry_type"] == "FUNDRAISER_DEPOSIT"
        assert deposit["amount_cents"] == 133334
        assert isinstance(deposit["amount_cents"], int)
        assert deposit["status"] == "PENDING"
        # PENDING entries are excluded: the balance is still zero.
        chapter = get_chapter(env["chapter"]["id"])
        assert chapter["fund_balance_cents"] == 0

    def test_cleared_deposit_sums_into_balance(self):
        """PRD section 3.5: "The balance rule itself is exact:
        `fund_balance_cents` is the sum of `amount_cents` over precisely the
        chapter's entries in `CLEARED` status — `PENDING` entries are excluded,
        and since every amount is stored as integer cents, no rounding arises
        anywhere in the roll-up."
        PRD section 3.5: "The advisor clears a pending entry — only while the
        chapter is `ACTIVE` — and clearing recomputes the chapter's
        `fund_balance_cents`; when the cleared entry is a
        `NATIONAL_DUES_PAYMENT`, the chapter's `dues_arrears_cents` is
        recomputed as well."

        Design: Difficulty/combinatorial_formula/fund_balance_rollup_per_entry_rounding
        """
        env = setup_fundraiser_director_approved(upfront_cost_cents=0)
        fundraiser = execute_fundraiser(env, 133334)
        deposit = find_ledger_entry(env["chapter"]["id"], "FUNDRAISER_DEPOSIT",
                                    fundraiser["id"])
        clear_ledger_entry(env["chapter"]["id"], deposit["id"])
        chapter = get_chapter(env["chapter"]["id"])
        assert chapter["fund_balance_cents"] == 133334
        entries = list_ledger_entries(env["chapter"]["id"])
        assert sum(e["amount_cents"] for e in entries
                   if e["status"] == "CLEARED") == 133334
