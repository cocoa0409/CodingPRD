"""Portal submission, idempotent replay, and the clock sweeps (PRD §2.4, §3.1, §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    approve_institutional,
    assert_submission_package,
    finalize_budget,
    get_proposal,
    get_success_data,
    get_version,
    make_approved_proposal,
    make_context,
    make_org,
    make_pi_headers,
    make_proposal,
    make_sub_commitment,
    open_review,
    pledge_cost_share,
    reset_clock,
    route_proposal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestSubmissionPackage:
    def _setup_approved(self, api):
        reset_clock()
        return make_approved_proposal()

    def test_submit_mints_package_discoverable_via_reverse_list(self, api):
        """PRD §3.8: "A successful submission mints a **SubmissionPackage** — a
        server-generated `portal_confirmation_code`, a `submitted_at` taken from
        the logical clock, and a `status` of `ACCEPTED_BY_PORTAL`, its only
        state". PRD §2.4: "Before any administrative intervention, the logical
        clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/submission_package_via_reverse_list
        """
        env = self._setup_approved(api)
        prop_id = env["proposal"]["id"]
        pkg = validate_success(
            api.submit_proposal(prop_id, {"idempotency_key": "pkg-1"}, DIRECTOR),
            201,
        )
        assert_submission_package(pkg)
        assert pkg["status"] == "ACCEPTED_BY_PORTAL"
        assert pkg["submitted_at"] == "2026-08-01T00:00:00Z"
        listing = get_success_data(api.list_submission_packages(prop_id, DIRECTOR))
        assert len(listing) == 1
        assert listing[0]["portal_confirmation_code"] == pkg["portal_confirmation_code"]
        assert listing[0]["proposal_id"] == prop_id

    def test_submit_replay_returns_original_package(self, api):
        """PRD §3.8: "The request carries an `idempotency_key` unique per
        proposal: replaying a submission with a key already used by one of this
        proposal's packages returns the original package rather than submitting
        twice." PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one with every modification".

        Design: Corner/cross_cutting_layers/submit_idempotent_replay
        """
        env = self._setup_approved(api)
        prop_id = env["proposal"]["id"]
        first = validate_success(
            api.submit_proposal(prop_id, {"idempotency_key": "idem-1"}, DIRECTOR),
            201,
        )
        v_after_submit = get_version(prop_id)
        # Replay returns the original package; any 2xx satisfies the contract.
        replay = get_success_data(
            api.submit_proposal(prop_id, {"idempotency_key": "idem-1"}, DIRECTOR)
        )
        assert replay["portal_confirmation_code"] == first["portal_confirmation_code"]
        # The replay is side-effect-free: no new modification, no version bump
        assert get_version(prop_id) == v_after_submit
        packages = get_success_data(api.list_submission_packages(prop_id, DIRECTOR))
        assert len(packages) == 1
        assert packages[0]["portal_confirmation_code"] == first["portal_confirmation_code"]

    def test_submit_with_new_key_after_submit_rejected(self, api):
        """PRD §3.8: "The proposal must be `INSTITUTIONALLY_APPROVED` (else
        `ERR_PROPOSAL_INVALID_STATE`)".

        Design: Corner/cross_cutting_layers/submit_idempotent_replay
        """
        env = self._setup_approved(api)
        prop_id = env["proposal"]["id"]
        api.submit_proposal(prop_id, {"idempotency_key": "idem-1"}, DIRECTOR)
        resp = api.submit_proposal(prop_id, {"idempotency_key": "idem-2"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value)


class TestInternalDeadlineBoundary:
    def _setup_pair(self, api):
        """Two INSTITUTIONALLY_APPROVED proposals on an opportunity whose
        internal deadline is 2026-08-31T17:00:00Z (sponsor 2026-09-05, lead 5)."""
        reset_clock()
        env1 = make_approved_proposal()
        ctx = env1["ctx"]
        second = make_proposal(
            ctx["opp"]["id"], ctx["pi"]["id"], title="D2",
            project_start_on="2027-09-01", project_end_on="2028-08-31",
        )
        add_budget_line(second["id"], fiscal_year=2028, amount_cents=10_000_000)
        finalize_budget(second["id"])
        route_proposal(second["id"])
        approve_institutional(second["id"])
        return env1["proposal"], get_proposal(second["id"])

    def test_submit_exactly_at_deadline_allowed(self, api):
        """PRD §2.4: "Portal submission is permitted while the logical clock is
        at or before `internal_deadline_at`; a submission landing exactly on the
        deadline instant is allowed."

        Design: Difficulty/boundary_precision_check/internal_deadline_boundary
        """
        p1, _p2 = self._setup_pair(api)
        reset_clock("2026-08-31T17:00:00Z")
        pkg = validate_success(
            api.submit_proposal(p1["id"], {"idempotency_key": "sub-d1"}, DIRECTOR),
            201,
        )
        assert pkg["status"] == "ACCEPTED_BY_PORTAL"

    def test_submit_one_second_late_refused(self, api):
        """PRD §2.4: "A submission attempted after that instant is refused with
        `ERR_INTERNAL_DEADLINE_PASSED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/internal_deadline_boundary
        """
        _p1, p2 = self._setup_pair(api)
        reset_clock("2026-08-31T17:00:01Z")
        resp = api.submit_proposal(p2["id"], {"idempotency_key": "sub-d2"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INTERNAL_DEADLINE_PASSED.value)


class TestSubmitPriority:
    def _setup_late_approved(self, api):
        """INSTITUTIONALLY_APPROVED proposal; clock then advanced past the
        sponsor deadline so the opportunity sweeps closed."""
        reset_clock()
        env = make_approved_proposal()
        return env

    def test_closed_opportunity_error_beats_deadline_error(self, api):
        """PRD §2.8: "8. **Referential usability.** The parent opportunity must
        still be `PUBLISHED` for proposal creation, institutional approval, and
        portal submission (`ERR_OPPORTUNITY_CLOSED`, 409). 9. **Temporal
        gates.** The submission clock must not have passed the internal deadline
        (`ERR_INTERNAL_DEADLINE_PASSED`, 422)".

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_submit
        """
        env = self._setup_late_approved(api)
        reset_clock("2026-09-06T00:00:00Z")
        # Both conditions hold: opportunity swept INTAKE_CLOSED and clock past
        # the internal deadline — the referential error wins.
        resp = api.submit_proposal(
            env["proposal"]["id"], {"idempotency_key": "sub-late-1"}, DIRECTOR
        )
        validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_CLOSED.value)

    def test_approved_proposal_survives_sweep(self, api):
        """PRD §3.1: "a proposal that already reached `INSTITUTIONALLY_APPROVED`
        survives the sweep, though its later submission will be stopped by
        `ERR_OPPORTUNITY_CLOSED` or `ERR_INTERNAL_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_submit
        """
        env = self._setup_late_approved(api)
        reset_clock("2026-09-06T00:00:00Z")
        prop = get_proposal(env["proposal"]["id"])
        assert prop["status"] == "INSTITUTIONALLY_APPROVED"
        opp = validate_success(
            api.get_funding_opportunity(env["ctx"]["opp"]["id"], DIRECTOR)
        )
        assert opp["status"] == "INTAKE_CLOSED"


class TestDeadlineSweepCascade:
    def _setup(self, api):
        """BUDGET_LOCKED proposal with PENDING review, PLEDGED cost-share, and
        DRAFT sub commitment, on an opportunity about to be swept."""
        reset_clock()
        ctx = make_context()
        org = make_org(legal_name="Sub", uei="UEI-SWP1")
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="Sweep")
        make_sub_commitment(
            prop["id"], org["id"], subaward_amount_cents=500_000,
            statement_of_work_received=False, budget_received=False,
        )
        add_budget_line(prop["id"], amount_cents=10_000_000)
        finalize_budget(prop["id"])
        pledge_cost_share(prop["id"], 1_000_000)
        open_review(prop["id"], "IRB")
        return ctx, prop

    def test_sweep_closes_opportunity_and_withdraws_proposal(self, api):
        """PRD §3.1: "When the logical clock is set, the sweep transitions every
        still-`PUBLISHED` opportunity whose `sponsor_deadline_at` has passed into
        `INTAKE_CLOSED`, its terminal state. The closure cascades: each of the
        opportunity's proposals in `DRAFT`, `BUDGET_LOCKED`, `ROUTED`, or
        `RETURNED_FOR_REVISION` is moved to `WITHDRAWN`".

        Design: Difficulty/transitive_cascade/deadline_sweep_cascade
        """
        ctx, prop = self._setup(api)
        reset_clock("2026-09-06T00:00:00Z")
        opp = validate_success(
            api.get_funding_opportunity(ctx["opp"]["id"], DIRECTOR)
        )
        assert opp["status"] == "INTAKE_CLOSED"
        data = get_proposal(prop["id"])
        assert data["status"] == "WITHDRAWN"
        # recomputed after the cascade: no APPROVED commitments remain
        assert data["total_approved_cost_share_cents"] == 0

    def test_sweep_cascades_to_children(self, api):
        """PRD §3.1: "For every withdrawn proposal, its compliance reviews in
        `PENDING` or `INFO_REQUESTED` are `CANCELLED`, its cost-share commitments
        move from `PLEDGED` to `WITHDRAWN` and from `APPROVED` to `RELEASED`, and
        its subrecipient commitments in `DRAFT`, `VERIFIED`, or `STALE` are
        `VOIDED`".

        Design: Difficulty/transitive_cascade/deadline_sweep_cascade
        """
        _ctx, prop = self._setup(api)
        reset_clock("2026-09-06T00:00:00Z")
        reviews = get_success_data(api.list_compliance_reviews(prop["id"], DIRECTOR))
        assert reviews[0]["status"] == "CANCELLED"
        commitments = get_success_data(
            api.list_cost_share_commitments(prop["id"], DIRECTOR)
        )
        assert commitments[0]["status"] == "WITHDRAWN"
        subs = get_success_data(
            api.list_subrecipient_commitments(prop["id"], DIRECTOR)
        )
        assert subs[0]["status"] == "VOIDED"
