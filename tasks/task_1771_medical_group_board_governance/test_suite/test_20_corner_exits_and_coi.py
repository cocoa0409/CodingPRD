"""Corner queue: exit initiation/finalize guards, minority-discount variants, COI review."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_buyout_approval,
    api_client,
    appraise_valuation,
    capital_call_payload,
    cast_vote,
    close_motion,
    create_and_open_motion,
    create_exit_valuation_payload,
    create_physician,
    create_policy,
    create_shareholder,
    file_coi_disclosure,
    get_exit_valuation,
    get_motion,
    get_physician,
    initiate_exit,
    list_motion_votes,
    make_physician_headers,
    review_coi_disclosure,
    set_standing,
    setup_finalized_exit,
    validate_error,
)


class TestExitInitiateGuards:
    def test_associate_and_double_initiation_rejected(self, api):
        """PRD §3.6: "The physician's `partnership_status` moves from `SHAREHOLDER` to
        `EXITING` at initiation, and the valuation starts at `INITIATED`." — the
        transition exists only from `SHAREHOLDER`, so initiating for an `ASSOCIATE`
        is an invalid state (`ERR_INVALID_STATE`).
        PRD §3.6: "Only one non-terminal valuation may exist per physician — a second
        initiation while one is in flight is rejected with
        `ERR_EXIT_ALREADY_IN_PROGRESS`."

        Design: Corner/state_machines/exit_initiate_guards
        """
        create_policy(total_shares_authorized=1000000)
        p = create_physician(full_name="Dr P", hire_date="2024-01-01T00:00:00Z")
        s = create_shareholder("Dr S", 1000, "2010-01-01T00:00:00Z")
        initiate_exit(s["id"], "VOLUNTARY")

        resp = api_client.create_exit_valuation(
            create_exit_valuation_payload(p["id"], "VOLUNTARY"),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api_client.create_exit_valuation(
            create_exit_valuation_payload(s["id"], "RETIREMENT"),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EXIT_ALREADY_IN_PROGRESS)
        assert get_physician(s["id"])["partnership_status"] == "EXITING"


class TestValuationFinalizeBeforeAppraisalRejected:
    def test_finalize_from_initiated_rejected(self, api):
        """PRD §3.6: "The valuation must also be `APPRAISED` to finalize, otherwise
        `ERR_VALUATION_NOT_APPRAISED`."

        Design: Corner/state_machines/valuation_finalize_before_appraisal_rejected
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        t = create_shareholder("Dr T", 1000, "2011-01-01T00:00:00Z")
        valuation = initiate_exit(x["id"], "VOLUNTARY")
        motion = adopt_buyout_approval(t, valuation["id"])

        resp = api_client.finalize_exit_valuation(
            valuation["id"], {"motion_id": motion["id"]},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALUATION_NOT_APPRAISED)
        assert get_exit_valuation(valuation["id"])["status"] == "INITIATED"
        assert get_physician(x["id"])["partnership_status"] == "EXITING"


class TestDeathExitWaivesMinorityDiscount:
    def test_death_and_voluntary_final_values_diverge(self, api):
        """PRD §3.6: "The final value depends on the trigger: for `VOLUNTARY` and
        `RETIREMENT` exits it is the appraised practice value multiplied by the
        ownership snapshot and by one minus `minority_discount_pct`, rounded half-up;
        for `TERMINATION` and `DEATH` the minority discount is waived, so it is simply
        the appraised practice value multiplied by the ownership snapshot, rounded
        half-up."
        Both at ownership 1/2 and appraisal 90000000: DEATH -> 45000000,
        VOLUNTARY -> 38250000.

        Design: Corner/calculations/death_exit_waives_minority_discount
        """
        create_policy(total_shares_authorized=1000000)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        w = create_shareholder("Dr W", 1000, "2011-01-01T00:00:00Z")
        vx = initiate_exit(x["id"], "DEATH")
        vw = initiate_exit(w["id"], "VOLUNTARY")

        appraised_x = appraise_valuation(vx, 90000000)
        appraised_w = appraise_valuation(vw, 90000000)
        assert appraised_x["final_value_cents"] == 45000000, (
            f"DEATH waives the discount: 90000000 * 0.5, got {appraised_x['final_value_cents']}"
        )
        assert appraised_w["final_value_cents"] == 38250000, (
            f"VOLUNTARY applies 0.85: 90000000 * 0.5 * 0.85, got {appraised_w['final_value_cents']}"
        )


class TestCoiClearedAndTerminalMotionFlagHaveNoCascade:
    def test_cleared_then_terminal_flag_record_only(self, api):
        """PRD §3.7: "A `CLEARED` outcome has no recusal effect."
        PRD §3.7: "If the related motion is already terminal, the flag is recorded but
        no recusal cascade runs."

        Design: Corner/state_machines/coi_cleared_and_terminal_motion_flag_have_no_cascade
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Minor")
        )
        vote = cast_vote(motion["id"], b, "FOR")

        d1 = file_coi_disclosure(b, "Minor stockholding", related_motion_id=motion["id"])
        cleared = review_coi_disclosure(d1["id"], "CLEARED", review_note="de minimis")
        assert cleared["status"] == "CLEARED"
        motion_after_clear = get_motion(motion["id"])
        assert motion_after_clear["votes_for"] == 1
        assert motion_after_clear["recused_physician_ids"] == []

        closed = close_motion(motion["id"])
        assert closed["status"] == "ADOPTED"

        d2 = file_coi_disclosure(b, "Late-discovered conflict", related_motion_id=motion["id"])
        flagged = review_coi_disclosure(d2["id"], "FLAGGED")
        assert flagged["status"] == "FLAGGED"

        motion_after = get_motion(motion["id"])
        assert motion_after["status"] == "ADOPTED"
        assert motion_after["recused_physician_ids"] == []
        votes, _meta = list_motion_votes(motion["id"])
        b_votes = [v for v in votes if v["id"] == vote["id"]]
        assert b_votes[0]["status"] == "CAST", "no retroactive cascade on a terminal motion"


class TestCoiReviewPendingBlocksVote:
    def test_filed_disclosure_blocks_until_cleared(self, api):
        """PRD §3.7: "The disclosure also gates future ballots: a physician with a
        `FILED` disclosure related to a motion cannot vote on it until review completes
        (`ERR_COI_REVIEW_PENDING`), and a physician recused by a `FLAGGED` disclosure
        cannot vote on it at all (`ERR_VOTER_RECUSED`)."

        Design: Corner/state_machines/coi_review_pending_blocks_vote
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Minor")
        )
        disclosure = file_coi_disclosure(b, "Possible conflict", related_motion_id=motion["id"])

        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "FOR"}, make_physician_headers(b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_COI_REVIEW_PENDING)

        review_coi_disclosure(disclosure["id"], "CLEARED")
        vote = cast_vote(motion["id"], b, "FOR")
        assert vote["status"] == "CAST"
        assert get_motion(motion["id"])["votes_for"] == 1


class TestStandingDimensionCyclicAndExitedLockout:
    def test_standing_cycle_and_exited_immutability(self, api):
        """PRD §3.1: "The `standing` dimension starts at `GOOD_STANDING` and moves
        freely among `GOOD_STANDING`, `PROBATION`, and `SUSPENDED` at a `BoardAdmin`'s
        direction — the standing-update call takes the target `standing` value and an
        optional `note` — with one restriction: standing cannot be changed on an
        `EXITED` physician (`ERR_INVALID_STATE`)."
        PRD §3.1: "`EXITED` is terminal, and an `EXITED` physician is immutable — any
        attempted mutation is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/standing_dimension_cyclic_and_exited_lockout
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        y = create_shareholder("Dr Y", 1000, "2011-01-01T00:00:00Z")
        setup_finalized_exit(x, y, trigger_type="DEATH")

        assert set_standing(y["id"], "PROBATION")["standing"] == "PROBATION"
        assert set_standing(y["id"], "SUSPENDED")["standing"] == "SUSPENDED"
        assert set_standing(y["id"], "GOOD_STANDING")["standing"] == "GOOD_STANDING"
        y_after = get_physician(y["id"])
        assert y_after["partnership_status"] == "SHAREHOLDER", (
            "standing and partnership_status are independent dimensions"
        )

        resp = api_client.set_physician_standing(
            x["id"], {"standing": "PROBATION"}, TEST_USERS["board_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
