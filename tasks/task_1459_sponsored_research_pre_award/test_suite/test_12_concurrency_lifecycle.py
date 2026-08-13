"""Optimistic concurrency, versioning, and terminal-state lockdown
(PRD §2.5, §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    add_budget_line,
    assert_proposal,
    assert_proposal_invariants,
    create_offer_payload,
    create_proposal_payload,
    finalize_budget,
    get_proposal,
    get_version,
    make_context,
    make_locked_proposal,
    make_pi,
    make_pi_headers,
    make_proposal,
    make_submitted_proposal,
    reset_clock,
    route_proposal,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestOccOnFinalize:
    def _setup(self, api):
        reset_clock()
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="OCC")
        add_budget_line(prop["id"], amount_cents=10_000_000)
        # The line add advanced the proposal's version (PRD §2.5/§3.3), so
        # re-read the live record before handing it to callers that OCC-guard
        # on `prop["version"]`.
        return get_proposal(prop["id"])

    def test_first_finalize_advances_version(self, api):
        """PRD §3.3: "Finalization freezes the budget into an immutable
        **BudgetSnapshot** ... a per-proposal `snapshot_index` ascending from 1"
        and "the write is OCC-guarded per §2.7". PRD §2.5: "`version`
        (integer): a system-managed integer that increments by one with every
        modification".

        Design: Corner/cross_cutting_layers/occ_stale_version_on_budget_finalize
        """
        prop = self._setup(api)
        snap = finalize_budget(prop["id"], expected_version=prop["version"])
        assert snap["snapshot_index"] == 1

    def test_replayed_version_rejected_stale(self, api):
        """PRD §2.7: "When the supplied value does not equal the proposal's
        current `version` — because some other accepted write has advanced it
        since the client read — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_budget_finalize
        """
        prop = self._setup(api)
        finalize_budget(prop["id"], expected_version=prop["version"])
        # Re-finalize from BUDGET_LOCKED is legitimate, but this writer's
        # version went stale when the first finalize bumped it.
        resp = api.create_budget_finalization(
            prop["id"], {"expected_proposal_version": prop["version"]}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_finalize_without_version_is_malformed(self, api):
        """PRD §2.7: "Each requires the request body to carry
        `expected_proposal_version`, a non-optional field holding the proposal
        `version` the client last observed." PRD §2.8: "structurally malformed
        payloads — a missing required field ... — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/finalize_missing_required_version_rejected
        """
        prop = self._setup(api)
        resp = api.create_budget_finalization(prop["id"], {}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestOccOnNegotiationOffer:
    def _setup(self, api):
        reset_clock()
        return make_submitted_proposal(idempotency_key="sub-occ-1")

    def test_first_offer_opens_round(self, api):
        """PRD §3.8: "Each **NegotiationOffer** receives a per-proposal
        `round_index` ascending from 1 and starts `PROPOSED`".

        Design: Corner/cross_cutting_layers/occ_stale_version_on_negotiation_offer
        """
        env = self._setup(api)
        prop = env["proposal"]
        offer = validate_success(
            api.create_negotiation_offer(
                prop["id"],
                create_offer_payload(prop["version"],
                                     offered_total_cents=14_000_000),
                DIRECTOR,
            ),
            201,
        )
        assert offer["round_index"] == 1
        assert offer["status"] == "PROPOSED"

    def test_replayed_version_rejected_stale(self, api):
        """PRD §2.7: "Exactly two write operations participate in optimistic
        concurrency control: finalizing a proposal's budget, and opening a
        negotiation round on a proposal. ... When the supplied value does not
        equal the proposal's current `version` — because some other accepted
        write has advanced it since the client read — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_negotiation_offer
        """
        env = self._setup(api)
        prop = env["proposal"]
        stale_version = prop["version"]
        validate_success(
            api.create_negotiation_offer(
                prop["id"],
                create_offer_payload(stale_version,
                                     offered_total_cents=14_000_000),
                DIRECTOR,
            ),
            201,
        )
        # A new round would legitimately supersede the open offer, but this
        # writer's version is now stale.
        resp = api.create_negotiation_offer(
            prop["id"],
            create_offer_payload(stale_version, origin="INSTITUTION",
                                 offered_total_cents=14_500_000),
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


class TestVersionDiscipline:
    def test_version_walks_one_per_mutation(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one with every modification, including modifications
        caused by cascading side effects rather than a direct client write."
        PRD §3.3: "A new proposal is `DRAFT` with `version` 1" and "Every line
        add or delete increments the proposal's `version`."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="V",
                             pi_effort_pct=10.00)
        assert prop["version"] == 1
        patched = validate_success(
            api.patch_proposal(prop["id"], {"title": "V2"},
                               make_pi_headers(ctx["pi"]["id"])),
            200,
        )
        assert patched["version"] == 2
        add_budget_line(prop["id"], category="TRAVEL", description="t",
                        amount_cents=100)
        assert get_proposal(prop["id"])["version"] == 3


class TestTerminalLockdown:
    def _setup_withdrawn(self, api):
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="W",
                             pi_effort_pct=10.00)
        validate_success(
            api.withdraw_proposal(prop["id"], make_pi_headers(ctx["pi"]["id"])),
            200,
        )
        return ctx, get_proposal(prop["id"])

    def test_patch_on_withdrawn_rejected(self, api):
        """PRD §3.3: "While the proposal is `DRAFT` or `RETURNED_FOR_REVISION`,
        the owning PI may edit the scalar fields ... Editing from any other
        status is rejected with `ERR_PROPOSAL_INVALID_STATE`".

        Design: Corner/state_machines/withdrawn_proposal_terminal_lockdown
        """
        ctx, prop = self._setup_withdrawn(api)
        assert prop["status"] == "WITHDRAWN"
        resp = api.patch_proposal(
            prop["id"], {"title": "revive?"}, make_pi_headers(ctx["pi"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value)

    def test_finalize_on_withdrawn_rejected(self, api):
        """PRD §3.3: "A `PreAwardAnalyst` may finalize from `DRAFT`,
        `BUDGET_LOCKED`, or `JIT_REQUESTED` — any other status yields
        `ERR_PROPOSAL_INVALID_STATE`".

        Design: Corner/state_machines/withdrawn_proposal_terminal_lockdown
        """
        _ctx, prop = self._setup_withdrawn(api)
        resp = api.create_budget_finalization(
            prop["id"], {"expected_proposal_version": prop["version"]}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value)


class TestProposalLifecycleBasics:
    def test_initial_state(self, api):
        """PRD §3.3: "A new proposal is `DRAFT` with `version` 1:
        `current_snapshot_id` and `pinned_budget_snapshot_id` are null, all three
        totals are zero, `fa_rate_pct_applied` and `applied_rate_source` are null
        until the first finalization, `total_approved_cost_share_cents` and
        `total_effective_cost_share_cents` are zero with `is_cost_share_adequate`
        false, `compliance_posture` reads `CLEAR` ..."

        Design: Corner/state_machines/proposal_initial_state_draft
        """
        ctx = make_context()
        resp = api.create_proposal(
            create_proposal_payload(
                ctx["opp"]["id"], ctx["pi"]["id"], title="Init",
                pi_effort_pct=10.00, fa_base_type="MTDC",
            ),
            make_pi_headers(ctx["pi"]["id"]),
        )
        data = validate_success(resp, 201)
        assert_proposal(data)
        assert_proposal_invariants(data)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["total_direct_cents"] == 0
        assert data["compliance_posture"] == "CLEAR"

    def test_finalize_from_routed_rejected(self, api):
        """PRD §3.3: "A `PreAwardAnalyst` may finalize from `DRAFT`,
        `BUDGET_LOCKED`, or `JIT_REQUESTED` — any other status yields
        `ERR_PROPOSAL_INVALID_STATE`".

        Design: Corner/state_machines/finalize_from_routed_rejected
        """
        reset_clock()
        env = make_locked_proposal()
        route_proposal(env["proposal"]["id"])
        # OCC version is satisfied; only the state precondition can fire
        resp = api.create_budget_finalization(
            env["proposal"]["id"],
            {"expected_proposal_version": get_version(env["proposal"]["id"])},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value)
