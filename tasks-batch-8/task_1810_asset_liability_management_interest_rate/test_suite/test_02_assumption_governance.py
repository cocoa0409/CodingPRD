"""Assumption-set governance: drafting, submission, approval, supersession,
segregation of duties, and validation ordering (PRD §2.9, §2.10, §3.2)."""
from test_helpers import (
    AN1,
    CH1,
    ApiErrorId,
    assert_assumption_set,
    assert_version_incremented,
    create_approved_set,
    create_assumption_set,
    create_book,
    create_run,
    create_shock_scenario,
    get_assumption_set,
    get_success_data,
    make_analyst_headers,
    make_chair_headers,
    prepayment_params,
    setup_book1_active,
    submit_assumption_set,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_prepayment_set(book_id: str, creator: str = "an-1") -> dict:
    return create_assumption_set(book_id, "PREPAYMENT", prepayment_params(),
                                 creator)


class TestRevisionCycle:
    def test_assumption_set_revision_cycle_reaches_approved(self, api):
        """PRD §3.2: "Rejection by the `ALCOChair` returns the set `SUBMITTED
        → DRAFT` for revision, accompanied by a `reason`, and the
        draft–submit–reject cycle may repeat as many times as needed."
        PRD §3.2: "the server stamps `approved_by_user_id` with the approver
        and `approved_at` with the logical clock."

        Design: Difficulty/non_linear_state_machine/assumption_set_revision_cycle
        """
        book = create_book()
        s = _draft_prepayment_set(book["id"], creator="an-1")
        assert s["status"] == "DRAFT"
        assert s["created_by_user_id"] == "an-1"
        submit_assumption_set(s["id"], "an-1")
        rejected = get_success_data(api.reject_assumption_set(
            s["id"], {"reason": "CPR too low"}, CH1))
        assert rejected["status"] == "DRAFT", (
            "rejection returns the set to DRAFT for revision")
        edited = get_success_data(api.patch_assumption_set(
            s["id"],
            {"params": prepayment_params(12.0, 2.5)},
            make_analyst_headers("an-1")))
        assert edited["params"]["base_cpr_pct"] == 12.0
        submit_assumption_set(s["id"], "an-1")
        approved = get_success_data(
            api.approve_assumption_set(s["id"], CH1))
        assert_assumption_set(approved)
        assert approved["status"] == "APPROVED"
        assert approved["created_by_user_id"] == "an-1"
        assert approved["approved_by_user_id"] == "ch-1"

    def test_assumption_set_revision_cycle_version_increments(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments with every mutation of the resource." PRD §3.2: "the
        draft–submit–reject cycle may repeat as many times as needed."

        Design: Difficulty/non_linear_state_machine/assumption_set_revision_cycle
        """
        book = create_book()
        s = _draft_prepayment_set(book["id"], creator="an-1")
        previous = s["version"]
        for resp in (
            api.submit_assumption_set(s["id"], make_analyst_headers("an-1")),
            api.reject_assumption_set(s["id"], {"reason": "revise"}, CH1),
            api.patch_assumption_set(
                s["id"], {"params": prepayment_params(12.0, 2.5)},
                make_analyst_headers("an-1")),
            api.submit_assumption_set(s["id"], make_analyst_headers("an-1")),
            api.approve_assumption_set(s["id"], CH1),
        ):
            data = get_success_data(resp)
            assert_version_incremented(data["version"], previous)
            previous = data["version"]
        assert get_assumption_set(s["id"])["status"] == "APPROVED"


class TestApprovalSupersession:
    def _setup_two_sets_and_run(self, api):
        ctx = setup_book1_active(with_security_and_borrowing=False)
        book_id = ctx["book"]["id"]
        sa = create_approved_set(book_id, "PREPAYMENT",
                                 prepayment_params(10.0, 2.0))
        ds = create_approved_set(book_id, "DEPOSIT_DECAY",
                                 {"base_annual_decay_pct": 5.0,
                                  "surge_decay_per_100bps": 1.0})
        bs = create_approved_set(book_id, "DEPOSIT_BETA",
                                 {"up_beta_pct": 40.0, "down_beta_pct": 20.0,
                                  "lag_months": 6})
        sc = create_shock_scenario(book_id, 200, "UP200")
        run = create_run(book_id, sc["id"], sa["id"], ds["id"], bs["id"])
        sb = create_assumption_set(book_id, "PREPAYMENT",
                                   prepayment_params(12.0, 2.5), "an-1")
        submit_assumption_set(sb["id"], "an-1")
        return ctx, sa, sb, run

    def test_approve_approve_keeps_single_approved_per_domain(self, api):
        """PRD §3.2: "Approval has three cascades: any other `APPROVED` set in
        the same book and domain transitions to `SUPERSEDED`; every simulation
        run that pinned a newly superseded set has its `assumption_stale` flag
        set to `true`; and the server stamps `approved_by_user_id` with the
        approver and `approved_at` with the logical clock."

        Design: Difficulty/compensating_invariant/approve_approve_keeps_single_approved_per_domain
        """
        ctx, sa, sb, run = self._setup_two_sets_and_run(api)
        approved = get_success_data(api.approve_assumption_set(sb["id"], CH1))
        assert approved["status"] == "APPROVED"
        assert get_assumption_set(sa["id"])["status"] == "SUPERSEDED"
        rows, meta = validate_paginated(api.list_assumption_sets(
            ctx["book"]["id"], AN1,
            params={"domain": "PREPAYMENT", "status": "APPROVED"}))
        assert meta["total_count"] == 1, (
            "exactly one APPROVED set per (book, domain) must survive")
        assert rows[0]["id"] == sb["id"]

    def test_approve_approve_flags_pinning_run_stale(self, api):
        """PRD §3.2: "Approval has three cascades: any other `APPROVED` set in
        the same book and domain transitions to `SUPERSEDED`; every simulation
        run that pinned a newly superseded set has its `assumption_stale` flag
        set to `true`; and the server stamps `approved_by_user_id` with the
        approver and `approved_at` with the logical clock." PRD §3.2: "A
        set's `assumption_stale` semantics on the run side are definitional:
        the flag is `true` whenever any pinned set is no longer `APPROVED`."

        Design: Difficulty/compensating_invariant/approve_approve_keeps_single_approved_per_domain
        """
        ctx, sa, sb, run = self._setup_two_sets_and_run(api)
        assert run["assumption_stale"] is False
        get_success_data(api.approve_assumption_set(sb["id"], CH1))
        stale_run = validate_success(api.get_simulation_run(run["id"], AN1))
        assert stale_run["assumption_stale"] is True, (
            "the run pinning the superseded set must flip assumption_stale")


class TestSubmissionValidation:
    def test_submit_already_submitted_set_rejected(self, api):
        """PRD §3.2: "Submission moves the set `DRAFT → SUBMITTED`". PRD §2.9:
        "the target resource's current state permits the requested transition
        (`ERR_INVALID_STATE_TRANSITION`, `ERR_BOOK_NOT_ACTIVE`,
        `ERR_BOOK_ACTIVATION_INCOMPLETE`)." PRD §2.5: "`version` (integer): a
        system-managed integer that increments with every mutation of the
        resource."

        Design: Corner/state_machines/submit_already_submitted_set_rejected
        """
        book = create_book()
        s = _draft_prepayment_set(book["id"])
        submitted = submit_assumption_set(s["id"], "an-1")
        assert submitted["status"] == "SUBMITTED"
        version_before = submitted["version"]
        resp = api.submit_assumption_set(s["id"], AN1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_assumption_set(s["id"])
        assert after["status"] == "SUBMITTED"
        assert after["version"] == version_before, (
            "a rejected transition must not mutate the resource")

    def test_params_mismatch_domain_rejected(self, api):
        """PRD §3.2: "submission validates that the keys of `params` exactly
        match the schema of the set's domain — extra or missing keys are
        rejected with `ERR_ASSUMPTION_PARAMS_MISMATCH` (HTTP 422)."

        Design: Corner/validations/params_mismatch_domain_rejected
        """
        book = create_book()
        # PREPAYMENT params on a DEPOSIT_BETA domain: the keys do not match
        # the domain schema. The PRD pins the check to submission, so the
        # error must fire by submit time at the latest.
        resp_create = api.create_assumption_set(
            book["id"],
            {"domain": "DEPOSIT_BETA", "params": prepayment_params()},
            AN1)
        if resp_create.status_code >= 400:
            validate_error(resp_create,
                           ApiErrorId.ERR_ASSUMPTION_PARAMS_MISMATCH)
            return
        s = get_success_data(resp_create)
        resp = api.submit_assumption_set(s["id"], AN1)
        validate_error(resp, ApiErrorId.ERR_ASSUMPTION_PARAMS_MISMATCH)


class TestApprovalAccessAndSegregation:
    def test_analyst_cannot_approve_assumption_set_forbidden(self, api):
        """PRD §3.2: "Approval is reserved for the `ALCOChair` and moves the
        set `SUBMITTED → APPROVED`." PRD §2.1: "a caller whose role is not
        permitted for the endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/analyst_cannot_approve_assumption_set_forbidden
        """
        book = create_book()
        s = _draft_prepayment_set(book["id"])
        submit_assumption_set(s["id"], "an-1")
        resp = api.approve_assumption_set(s["id"], AN1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_assumption_set(s["id"])["status"] == "SUBMITTED"

    def test_self_approve_violates_segregation(self, api):
        """PRD §3.2: "The approver's `X-User-ID` must differ from the recorded
        `created_by_user_id`; an operator approving their own draft is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/rbac/self_approve_violates_segregation
        """
        book = create_book()
        # The same operator id drafts (as analyst) and approves (as chair).
        s = _draft_prepayment_set(book["id"], creator="ch-1")
        submit_assumption_set(s["id"], "ch-1")
        resp = api.approve_assumption_set(s["id"], make_chair_headers("ch-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_assumption_set(s["id"])["status"] == "SUBMITTED"

    def test_state_beats_segregation_on_reapprove(self, api):
        """PRD §2.9: "Beyond path resolution, every request is evaluated
        against twelve classes of checks in a fixed priority order, and an
        earlier failure masks every later one" — state-transition legality
        (class 6) precedes segregation of duties (class 7).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_reapprove
        """
        book = create_book()
        s = create_approved_set(book_id=book["id"], domain="PREPAYMENT",
                                params=prepayment_params(), creator_user_id="an-1",
                                approver_user_id="ch-1")
        # Already APPROVED (state failure) AND caller is the creator
        # (segregation failure): the state error must win.
        resp = api.approve_assumption_set(s["id"], make_chair_headers("an-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_assumption_set(s["id"])["status"] == "APPROVED"

    def test_reapprove_by_other_chair_also_state_rejected(self, api):
        """PRD §3.2: "Approval is reserved for the `ALCOChair` and moves the
        set `SUBMITTED → APPROVED`." — no approve transition exists from
        `APPROVED`, so a non-creator chair re-approving is rejected on state
        grounds alone. PRD §2.9: "the target resource's current state permits
        the requested transition (`ERR_INVALID_STATE_TRANSITION`,
        `ERR_BOOK_NOT_ACTIVE`, `ERR_BOOK_ACTIVATION_INCOMPLETE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_reapprove
        """
        book = create_book()
        s = create_approved_set(book_id=book["id"], domain="PREPAYMENT",
                                params=prepayment_params(), creator_user_id="an-1",
                                approver_user_id="ch-1")
        resp = api.approve_assumption_set(s["id"], make_chair_headers("ch-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_assumption_set(s["id"])
        assert after["status"] == "APPROVED"
        assert after["approved_by_user_id"] == "ch-1", (
            "the original approval record is untouched")
