"""Transitions a caller may only make once a neighbouring entity permits it."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_PANEL_NOT_TRANSFERRED,
    ERR_SCORECARD_NOT_FINAL,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    assert_fields,
    assign_enrollee,
    build_single_member_funded_pool,
    close_incurral,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_scorecard,
    finalize_scorecard,
    give_exit_notice,
    list_pool_distributions,
    propose_settlement,
    read_agreement,
    read_assignment,
    read_enrollee,
    read_physician,
    read_pool,
    reserve_pool,
    set_clock,
    state_payload,
    terminate_assignment,
)


def _physician_under_notice_still_holding_a_member(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api, continuity_of_care_days=90, max_panel_size=5
    )
    physician = create_active_physician(api, agreement["id"])
    enrollee = create_enrollee(api, agreement["id"], external_member_id="X-0001")
    assignment = assign_enrollee(api, enrollee["id"], physician["id"])

    set_clock(api, "2026-03-01T00:00:00Z")
    noticed = give_exit_notice(api, physician["id"])
    return {
        "agreement": agreement,
        "physician": noticed,
        "enrollee": enrollee,
        "assignment": assignment,
    }


def _attempt_exit(api, physician_id):
    return api.set_physician_state(
        physician_id, state_payload("EXITED"), NETWORK_MANAGER_HEADERS
    )


class TestPhysicianExitBlockedByActiveAssignment:
    def test_exit_is_refused_while_a_live_member_remains_on_the_panel(self, api):
        """PRD §3.2: "A `NetworkManager` may take `NOTICE_GIVEN → EXITED` only
        when `credential_status` is `NOTICE_GIVEN` and zero assignments held by
        that physician sit in `ACTIVE`, `TRANSFER_PROPOSED` or
        `TRANSFER_ACCEPTED`; a physician still holding live or in-flight members
        is refused with `ERR_PANEL_NOT_TRANSFERRED`."

        Design: Difficulty/cross_entity_state_dependency/physician_exit_blocked_by_active_assignment
        """
        built = _physician_under_notice_still_holding_a_member(api)
        assert built["physician"]["continuity_of_care_until"] == "2026-05-30T00:00:00Z"

        validate_error(
            _attempt_exit(api, built["physician"]["id"]), ERR_PANEL_NOT_TRANSFERRED, 422
        )

        unchanged = read_physician(api, built["physician"]["id"])
        assert unchanged["credential_status"] == "NOTICE_GIVEN"
        assert unchanged["panel_status"] == "CLOSED_TO_NEW"

    def test_terminating_the_assignment_clears_every_dependent_counter(self, api):
        """PRD §3.4: "The transition sets `status` to `TERMINATED` and stamps
        `term_date` with the current logical clock instant; it recomputes the
        physician's `panel_size` downward by one, clears the enrollee's
        `assigned_physician_id` to null, recomputes the agreement's
        `total_assigned_members` downward by one, and advances the assignment's
        `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/physician_exit_blocked_by_active_assignment
        """
        built = _physician_under_notice_still_holding_a_member(api)
        validate_error(
            _attempt_exit(api, built["physician"]["id"]), ERR_PANEL_NOT_TRANSFERRED, 422
        )

        set_clock(api, "2026-05-30T00:00:00Z")
        terminated = terminate_assignment(api, built["assignment"]["id"])

        assert_fields(
            terminated, {"status": "TERMINATED", "term_date": "2026-05-30T00:00:00Z"}
        )
        assert read_enrollee(api, built["enrollee"]["id"])["assigned_physician_id"] is None
        assert read_physician(api, built["physician"]["id"])["panel_size"] == 0
        assert read_agreement(api, built["agreement"]["id"])["total_assigned_members"] == 0

    def test_exit_succeeds_once_the_panel_is_clear_and_drives_the_panel_dimension(
        self, api
    ):
        """PRD §3.2: "When the exit does succeed it drives the panel dimension
        too: `credential_status` becomes `EXITED` and `panel_status` becomes
        `TRANSFERRED`, whether the panel dimension stood at `TRANSFER_PENDING` or
        at `CLOSED_TO_NEW` immediately before."

        Design: Difficulty/cross_entity_state_dependency/physician_exit_blocked_by_active_assignment
        """
        built = _physician_under_notice_still_holding_a_member(api)
        set_clock(api, "2026-05-30T00:00:00Z")
        terminate_assignment(api, built["assignment"]["id"])

        exited = validate_success(_attempt_exit(api, built["physician"]["id"]), 200)
        assert_fields(
            exited, {"credential_status": "EXITED", "panel_status": "TRANSFERRED"}
        )
        assert read_assignment(api, built["assignment"]["id"])["status"] == "TERMINATED"


def _reserved_pool_with_a_draft_scorecard(api):
    built = build_single_member_funded_pool(api, base_pmpm_cents=20000)
    built["scorecard"] = create_scorecard(
        api,
        built["physician"]["id"],
        measurement_period="2026",
        hedis_composite_bps=7000,
        access_score_bps=7000,
        patient_experience_bps=7000,
        attributed_member_months=12,
    )

    set_clock(api, "2027-01-01T00:00:00Z")
    close_incurral(api, built["pool"]["id"])
    built["pool"] = reserve_pool(api, built["pool"]["id"])
    return built


def _attempt_proposal(api, pool_id):
    return api.set_risk_pool_state(
        pool_id, state_payload("SETTLEMENT_PROPOSED"), IPA_ADMIN_HEADERS
    )


class TestSettlementProposalBlockedByDraftScorecard:
    def test_a_draft_scorecard_blocks_the_proposal_outright(self, api):
        """PRD §3.8: "A physician in scope whose only scorecard for that year is
        `DRAFT` or `SUPERSEDED` blocks the proposal outright rather than being
        quietly skipped, and the refusal is `ERR_SCORECARD_NOT_FINAL`."

        Design: Difficulty/cross_entity_state_dependency/pool_settlement_proposal_blocked_by_non_final_scorecard
        """
        built = _reserved_pool_with_a_draft_scorecard(api)
        assert built["scorecard"]["status"] == "DRAFT"
        assert_fields(
            built["pool"],
            {
                "status": "RESERVED",
                "funded_cents": 20000,
                "paid_claims_cents": 0,
                "ibnr_reserve_cents": 0,
            },
        )

        validate_error(
            _attempt_proposal(api, built["pool"]["id"]), ERR_SCORECARD_NOT_FINAL, 422
        )

        blocked = read_pool(api, built["pool"]["id"])
        assert_fields(
            blocked,
            {
                "status": "RESERVED",
                "surplus_tier": None,
                "shared_savings_pool_cents": 0,
            },
        )
        assert list_pool_distributions(api, built["pool"]["id"]) == []

    def test_finalisation_publishes_the_composite_onto_the_physician(self, api):
        """PRD §3.8: "`SUPERSEDED` is terminal; only a scorecard whose `status` is
        `FINAL` ever contributes to a physician's `quality_composite_bps`, and
        `DRAFT` and `SUPERSEDED` scorecards never do."

        Design: Difficulty/cross_entity_state_dependency/pool_settlement_proposal_blocked_by_non_final_scorecard
        """
        built = _reserved_pool_with_a_draft_scorecard(api)
        validate_error(
            _attempt_proposal(api, built["pool"]["id"]), ERR_SCORECARD_NOT_FINAL, 422
        )

        final = finalize_scorecard(api, built["scorecard"]["id"])
        assert_fields(
            final,
            {
                "status": "FINAL",
                "composite_score_bps": 7000,
                "withhold_release_bps": 7500,
            },
        )
        assert (
            read_physician(api, built["physician"]["id"])["quality_composite_bps"] == 7000
        )

    def test_the_proposal_runs_the_waterfall_once_the_scorecard_is_final(self, api):
        """PRD §3.8: "Step nine computes `shared_savings_pool_cents` as
        `distributable_surplus_cents` multiplied by the tier's shared-savings
        share — 0 basis points for `NONE`, 4000 for `TIER_1`, 5000 for `TIER_2`
        and 6000 for `TIER_3` — as a proportion of 10000, rounded half up to
        whole cents."

        Design: Difficulty/cross_entity_state_dependency/pool_settlement_proposal_blocked_by_non_final_scorecard
        """
        built = _reserved_pool_with_a_draft_scorecard(api)
        finalize_scorecard(api, built["scorecard"]["id"])
        proposed = propose_settlement(api, built["pool"]["id"])

        assert_fields(
            proposed,
            {
                "status": "SETTLEMENT_PROPOSED",
                "raw_surplus_cents": 20000,
                "surplus_tier": "TIER_3",
                "admin_fee_cents": 2000,
                "distributable_surplus_cents": 18000,
                "shared_savings_pool_cents": 10800,
            },
        )

    def test_the_single_participant_takes_the_whole_shared_savings_pool(self, api):
        """PRD §3.8: "Run second against the pool's `shared_savings_pool_cents`
        using the shared-savings weighting, the procedure produces each
        participant's `shared_savings_cents`."

        Design: Difficulty/cross_entity_state_dependency/pool_settlement_proposal_blocked_by_non_final_scorecard
        """
        built = _reserved_pool_with_a_draft_scorecard(api)
        finalize_scorecard(api, built["scorecard"]["id"])
        propose_settlement(api, built["pool"]["id"])

        distributions = list_pool_distributions(api, built["pool"]["id"])
        assert len(distributions) == 1
        assert_fields(
            distributions[0],
            {
                "physician_id": built["physician"]["id"],
                "panel_member_months_bps": 10000,
                "withhold_share_cents": 0,
                "shared_savings_cents": 10800,
                "net_distribution_cents": 10800,
                "status": "PROPOSED",
            },
        )
