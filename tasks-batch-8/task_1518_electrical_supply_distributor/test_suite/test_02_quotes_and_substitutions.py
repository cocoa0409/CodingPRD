"""Quote lifecycle (draft/submit/revise/award/expiry), the revise OCC guard,
and substitution requests."""
from test_helpers import (
    BRANCH_MGR,
    SALES_REP,
    ApiErrorId,
    api_client,
    assert_quote,
    assert_quote_line,
    assert_substitution_request,
    add_quote_line,
    create_contractor,
    create_ea_item,
    create_job_account,
    create_quote,
    create_submitted_quote,
    get_quote,
    get_quote_line,
    get_substitution_request,
    revise_quote,
    set_clock,
    setup_credit_hold_scenario,
    setup_draft_quote_with_substitution,
    submit_quote,
    validate_error,
    validate_success,
)


class TestQuoteCreation:

    def test_quote_created_in_draft_initial(self):
        """PRD section 3.4: "The quote starts in `DRAFT` with `revision_no`
        set to 1 and with `award_month` and `award_index_value` still null."

        Design: Corner/state_machines/quote_created_in_draft_initial
        """
        contractor = create_contractor("Tango Electric", 100_000)
        job = create_job_account(contractor["id"], "Init Job",
                                 jobsite_address="24 Site Rd")
        resp = api_client.create_quote(
            {"job_account_id": job["id"], "valid_until": "2027-01-01"},
            SALES_REP)
        data = validate_success(resp, expected_status=201)
        assert_quote(data)
        assert data["status"] == "DRAFT"
        assert data["revision_no"] == 1
        assert data["award_month"] is None
        assert data["award_index_value"] is None



class TestQuoteStateGates:

    def test_award_from_draft_rejected(self):
        """PRD section 3.4: "A quote that is not currently `SUBMITTED` cannot
        be revised or awarded; such attempts fail with
        `ERR_QUOTE_NOT_SUBMITTED`."

        Design: Corner/state_machines/award_from_draft_rejected
        """
        contractor = create_contractor("Uniform Electric", 100_000)
        job = create_job_account(contractor["id"], "Draft Job",
                                 jobsite_address="25 Site Rd")
        quote = create_quote(job["id"])
        resp = api_client.award_quote(quote["id"], BRANCH_MGR)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_SUBMITTED)
        assert get_quote(quote["id"])["status"] == "DRAFT"

    def test_revise_from_draft_rejected(self):
        """PRD section 3.4: "A quote that is not currently `SUBMITTED` cannot
        be revised or awarded; such attempts fail with
        `ERR_QUOTE_NOT_SUBMITTED`."

        Design: Corner/state_machines/revise_from_draft_rejected
        """
        contractor = create_contractor("Victor Electric", 100_000)
        job = create_job_account(contractor["id"], "Revise Job",
                                 jobsite_address="26 Site Rd")
        quote = create_quote(job["id"])
        resp = api_client.revise_quote(
            quote["id"], {"expected_quote_version": quote["version"]},
            SALES_REP)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_SUBMITTED)
        assert get_quote(quote["id"])["status"] == "DRAFT"

    def test_submit_quote_with_no_lines_rejected(self):
        """PRD section 3.4: "the quote must carry at least one line
        (`ERR_QUOTE_HAS_NO_LINES`)."

        Design: Corner/state_machines/submit_quote_with_no_lines_rejected
        """
        contractor = create_contractor("Whiskey Electric", 100_000)
        job = create_job_account(contractor["id"], "Empty Job",
                                 jobsite_address="27 Site Rd")
        quote = create_quote(job["id"])
        resp = api_client.submit_quote(quote["id"], SALES_REP)
        validate_error(resp, ApiErrorId.ERR_QUOTE_HAS_NO_LINES)
        assert get_quote(quote["id"])["status"] == "DRAFT"



class TestQuoteExpiry:

    def test_expired_quote_lazy_transition_on_award(self):
        """PRD section 3.4: "the logical clock's date must not have passed
        `valid_until` — if it has, the attempt is rejected with
        `ERR_QUOTE_EXPIRED` and the quote transitions to `EXPIRED`".
        PRD section 3.4: "Expiry is lazy across the board: any read or
        transition attempt against a `DRAFT` or `SUBMITTED` quote whose
        `valid_until` has passed moves it to `EXPIRED`, which is terminal."

        Design: Corner/state_machines/expired_quote_lazy_transition_on_read
        """
        contractor = create_contractor("Xray Electric", 100_000)
        item = create_ea_item(list_price_cents=2500)
        job = create_job_account(contractor["id"], "Expiry Job",
                                 jobsite_address="28 Site Rd")
        quote = create_submitted_quote(job["id"], [(item["id"], 1, 2500)],
                                       valid_until="2026-08-10")
        assert quote["status"] == "SUBMITTED"
        set_clock("2026-08-20T00:00:00Z")

        resp = api_client.award_quote(quote["id"], BRANCH_MGR)
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
        assert get_quote(quote["id"])["status"] == "EXPIRED"


class TestQuoteSubmitJobGuard:

    def test_submit_quote_on_credit_hold_job_rejected(self):
        """PRD section 3.4: "Submitting the quote — a `SalesRep` action moving
        `DRAFT` → `SUBMITTED` — enforces three checks, evaluated in the §2.10
        order: the job account must be `OPEN` (`ERR_JOB_NOT_OPEN`)".
        PRD section 3.8: "Should that posting push `invoiced_balance_cents`
        above the contractor's `credit_limit_cents`, credit contagion follows:
        every `OPEN` job account of that contractor transitions to
        `CREDIT_HOLD`, blocking further credit approvals and quote activity
        until payments bring the balance back within the limit (§3.1)."

        Design: Corner/state_machines/submit_quote_on_credit_hold_job_rejected
        """
        world = setup_credit_hold_scenario(draft_quote_on_j1=True)
        job = world["j1"]
        assert get_quote(world["draft_quote"]["id"])["status"] == "DRAFT"
        assert api_client.get_job_account(job["id"], SALES_REP).json() \
            ["data"]["status"] == "CREDIT_HOLD"

        resp = api_client.submit_quote(world["draft_quote"]["id"], SALES_REP)
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_OPEN)
        assert get_quote(world["draft_quote"]["id"])["status"] == "DRAFT"


class TestQuoteReviseCycle:

    def test_revise_returns_to_draft_and_bumps_revision(self):
        """PRD section 3.4: "Revising moves `SUBMITTED` → `DRAFT`, increments
        `revision_no` by 1, and increments the quote's `version` by 1 — each
        revision supersedes the prior one, which is exactly why the revise
        call is guarded by `expected_quote_version` per §2.8."

        Design: Difficulty/non_linear_state_machine/quote_revise_cycle
        """
        contractor = create_contractor("Echo Electric", 10_000_000)
        item = create_ea_item(list_price_cents=2500)
        job = create_job_account(contractor["id"], "Cycle Job",
                                 jobsite_address="6 Site Rd")
        quote = create_submitted_quote(job["id"], [(item["id"], 1, 2500)])
        submitted_version = quote["version"]

        revised = revise_quote(quote["id"], submitted_version)
        assert revised["status"] == "DRAFT"
        assert revised["revision_no"] == 2, (
            f"revision_no must increment 1 -> 2 across the revise, got "
            f"{revised['revision_no']}")
        assert revised["version"] == submitted_version + 1, (
            f"revise must increment version by 1: {submitted_version} -> "
            f"{revised['version']}")

    def test_revised_quote_resubmits_and_awards(self):
        """PRD section 3.4: "Revising moves `SUBMITTED` → `DRAFT`, increments
        `revision_no` by 1, and increments the quote's `version` by 1".
        PRD section 3.4: "`award_month` records the logical clock's
        year-month, and `award_index_value` records the value of the latest
        index reading whose month is on or before the award month — null if no
        such reading exists yet."

        Design: Difficulty/non_linear_state_machine/quote_revise_cycle
        """
        contractor = create_contractor("Echo Electric", 10_000_000)
        item = create_ea_item(list_price_cents=2500)
        job = create_job_account(contractor["id"], "Cycle Job",
                                 jobsite_address="6 Site Rd")
        quote = create_submitted_quote(job["id"], [(item["id"], 1, 2500)])
        revised = revise_quote(quote["id"], quote["version"])
        # Rework the BOM on the new revision, then resubmit and award.
        add_quote_line(quote["id"], item["id"], 2, 2400)
        submit_quote(quote["id"])
        awarded = api_client.award_quote(quote["id"], BRANCH_MGR)
        data = validate_success(awarded, expected_status=200)
        assert_quote(data)
        assert data["status"] == "AWARDED"
        assert data["revision_no"] == 2
        assert data["award_month"] == "2026-08", (
            f"award_month must record the default clock's year-month, got "
            f"{data['award_month']}")
        assert data["award_index_value"] is None, (
            "no index reading exists at or before the award month, so the "
            "pinned value must be null")


class TestQuoteReviseOcc:

    def test_quote_revise_stale_version_rejected(self):
        """PRD section 2.8: "Revising a quote requires the request to carry
        `expected_quote_version`, holding the quote's `version` as last
        observed by the client. If it does not match the quote's current
        `version` — because another writer has advanced it since the client
        last read it — the revise is rejected with `ERR_STALE_QUOTE_VERSION`
        (HTTP 412), preventing the client from silently superseding a revision
        it never saw."

        Design: Corner/cross_cutting/quote_revise_stale_version_rejected
        """
        contractor = create_contractor("Whiskey Electric", 100_000)
        item = create_ea_item()
        job = create_job_account(contractor["id"], "OCC Job",
                                 jobsite_address="54 Site Rd")
        quote = create_submitted_quote(job["id"], [(item["id"], 1, 5000)])
        stale_version = quote["version"]
        revise_quote(quote["id"], stale_version)
        resubmitted = submit_quote(quote["id"])
        assert resubmitted["version"] > stale_version

        resp = api_client.revise_quote(
            quote["id"], {"expected_quote_version": stale_version}, SALES_REP)
        validate_error(resp, ApiErrorId.ERR_STALE_QUOTE_VERSION)
        current = get_quote(quote["id"])
        assert current["status"] == "SUBMITTED"
        assert current["revision_no"] == 2


class TestSubstitutions:

    def test_substitution_approve_swaps_quote_line_item(self):
        """PRD section 3.5: "Approval moves the request to `APPROVED` and
        rewrites the quote line's `catalog_item_id` to the proposed item, so
        downstream release membership checks and billing follow the
        substitute."

        Design: Corner/state_machines/substitution_approve_swaps_quote_line_item
        """
        ctx = setup_draft_quote_with_substitution()
        resp = api_client.decide_substitution_request(
            ctx["sub"]["id"], {"decision": "APPROVE"}, BRANCH_MGR)
        data = validate_success(resp, expected_status=200)
        assert_substitution_request(data)
        assert data["status"] == "APPROVED"

        line = get_quote_line(ctx["line"]["id"])
        assert_quote_line(line)
        assert line["catalog_item_id"] == ctx["item_b"]["id"], (
            f"approval must rewrite the line to the proposed item, got "
            f"{line['catalog_item_id']}")
        assert line["unit_price_cents"] == 2500, (
            "the negotiated unit price on the line is retained across the "
            "swap")

    def test_substitution_decide_approve_blocked_when_quote_submitted(self):
        """PRD section 3.5: "The proposal starts in `PROPOSED` and is only
        accepted while the owning quote — reached by following the quote line
        back to its quote — is still `DRAFT`; otherwise the proposal is
        rejected with `ERR_QUOTE_NOT_DRAFT`."
        PRD section 3.5: "the same `DRAFT`-only guard on the owning quote
        applies at decision time as well."

        Design: Difficulty/cross_entity_state_dependency/substitution_decide_blocked_by_quote_state_rejected
        """
        ctx = setup_draft_quote_with_substitution(submit_after=True)
        resp = api_client.decide_substitution_request(
            ctx["sub"]["id"], {"decision": "APPROVE"}, BRANCH_MGR)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_DRAFT)

        sub = get_substitution_request(ctx["sub"]["id"])
        assert sub["status"] == "PROPOSED", (
            f"blocked decide must leave the request PROPOSED, got "
            f"{sub['status']}")
        line = get_quote_line(ctx["line"]["id"])
        assert line["catalog_item_id"] == ctx["item_a"]["id"], (
            "a blocked approval must not rewrite the line's catalog_item_id")

    def test_substitution_decide_reject_blocked_when_quote_submitted(self):
        """PRD section 3.5: "Both outcomes are terminal, and deciding a
        request that has left `PROPOSED` is rejected with
        `ERR_SUBSTITUTION_NOT_PROPOSED`; the same `DRAFT`-only guard on the
        owning quote applies at decision time as well."

        Design: Difficulty/cross_entity_state_dependency/substitution_decide_blocked_by_quote_state_rejected
        """
        ctx = setup_draft_quote_with_substitution(submit_after=True)
        resp = api_client.decide_substitution_request(
            ctx["sub"]["id"], {"decision": "REJECT"}, BRANCH_MGR)
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_DRAFT)

        sub = get_substitution_request(ctx["sub"]["id"])
        assert sub["status"] == "PROPOSED"
        line = get_quote_line(ctx["line"]["id"])
        assert line["catalog_item_id"] == ctx["item_a"]["id"]
