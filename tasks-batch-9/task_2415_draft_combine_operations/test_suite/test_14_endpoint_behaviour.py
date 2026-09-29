"""Endpoint behaviour on the draft floor and in the medical-sharing ledger.

Covers the clock actions and selection paths that move the draft along — a
voluntary pass, an authorized out-of-order selection, and the advance that
completes the draft — together with the bulk invitation selector's partial
success and the two read-time behaviours of a medical record share: supersession
of an earlier request from the same club, and expiry once the clock reaches the
share's window.
"""

from test_helpers import (
    ADMIN,
    assert_chart_points,
    build_declaration_open,
    build_draft_live_on_clock,
    build_granted_share,
    build_medical_evaluation,
    clock_action_payload,
    declare_prospect,
    grant_consent,
    invitation_selection_payload,
    make_club_gm_headers,
    medical_record_share_payload,
    pick_by_overall_number,
    read_club,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    read_share,
    register_prospect,
    request_share,
    selection_payload,
    set_clock,
    validate_success,
)


class TestVoluntaryPass:
    """Passing inside the clock hands the clock on without losing the pick."""

    def test_pass_marks_the_pick_voluntary_and_starts_the_next_from_now(self, api):
        """A voluntary pass records VOLUNTARY and starts the successor at the current instant.

        The passed pick keeps no selected prospect, the next pick opens at
        18:00:00.000Z with the full round-one allotment, and passing costs the
        club none of its timeouts.

        PRD: "A `ClubGM` may **pass** the pick it holds on the clock, moving it from `ON_CLOCK` to `PASSED` with `pass_reason` set to `VOLUNTARY`; the cycle must be `DRAFT_LIVE` and the current logical instant must be strictly before `deadline_at`, else `ERR_CLOCK_ALREADY_EXPIRED`."
        PRD: "Passing immediately puts the next `PENDING` pick on the clock with `on_clock_started_at` set to the current instant."

        Design: Corner/endpoints/voluntary_pass_hands_the_clock_to_the_next_pick
        """
        state = build_draft_live_on_clock(api)
        elm = state["clubs"]["ELM"]
        first = state["pick"]["r1p1"]
        second = state["pick"]["r1p2"]

        passed = validate_success(
            api.act_on_pick_clock(
                first["id"],
                clock_action_payload("PASS"),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=200,
        )

        assert passed["status"] == "PASSED"
        assert passed["pass_reason"] == "VOLUNTARY"
        assert passed["selected_prospect_id"] is None

        successor = read_pick(api, second["id"])
        assert successor["status"] == "ON_CLOCK"
        assert successor["on_clock_started_at"] == "2027-04-22T18:00:00.000Z"
        assert successor["deadline_at"] == "2027-04-22T18:10:00.000Z"

        assert read_club(api, elm["id"])["timeouts_remaining"] == 2
        assert read_cycle(api, state["cycle"]["id"])["current_overall_number"] == 2


class TestBulkInvitationSelector:
    """The selector is partial-success when the pool is smaller than asked."""

    def test_target_larger_than_the_pool_invites_everyone_available(self, api):
        """A target of five against a pool of two invites both and raises nothing.

        Only the two declared prospects enter the pool, so the selector reports
        the number it actually invited and leaves the undeclared prospect alone.

        PRD: "If the pool holds at least one prospect but fewer than `target_count`, the entire pool is invited and no error is raised."

        Design: Corner/endpoints/selector_invites_the_whole_pool_when_target_count_is_larger
        """
        state = build_declaration_open(api)
        cycle_id = state["cycle"]["id"]

        undeclared = register_prospect(api, cycle_id)
        broader = register_prospect(
            api,
            cycle_id,
            full_name="Brooks Hale",
            position_group="WR",
            school_code="STH",
            scouting_grade=88.00,
            position_group_scarcity_rank=3,
        )
        scarcer = register_prospect(
            api,
            cycle_id,
            full_name="Cade Rios",
            position_group="TE",
            school_code="EST",
            scouting_grade=88.00,
            position_group_scarcity_rank=2,
        )
        declare_prospect(api, broader)
        declare_prospect(api, scarcer)

        result = validate_success(
            api.select_combine_invitations(
                cycle_id, invitation_selection_payload(5), ADMIN
            ),
            expected_status=200,
        )

        assert result["invited_count"] == 2
        assert set(result["invited_prospect_ids"]) == {broader["id"], scarcer["id"]}

        assert read_prospect(api, broader["id"])["invitation_status"] == "INVITED"
        assert read_prospect(api, scarcer["id"])["invitation_status"] == "INVITED"
        assert read_prospect(api, undeclared["id"])["invitation_status"] == "NOT_INVITED"


class TestShareSupersession:
    """A second request from the same club for the same evaluation supersedes."""

    def test_new_request_supersedes_the_clubs_earlier_pending_request(self, api):
        """The earlier REQUESTED share for the same pair is marked SUPERSEDED.

        Filing the first share bumped the evaluation's version, so the second
        request carries the refreshed version, is created in REQUESTED with the
        requester's declared capacity, and neither share was ever granted.

        PRD: "The share is created in `REQUESTED`, the requester's identifier is stored as `requested_by_user_id` and the requester's declared capacity as `requested_by_role`, and any earlier share for the same `medical_evaluation_id` and the same `club_id` still sitting in `REQUESTED` is immediately marked `SUPERSEDED`."

        Design: Corner/endpoints/newer_share_request_supersedes_the_prior_one_for_the_same_pair
        """
        state = build_medical_evaluation(api)
        elm = state["clubs"]["ELM"]
        grant_consent(api, state["prospect"])
        first = request_share(api, state["evaluation"], elm)

        refreshed = read_evaluation(api, state["evaluation"]["id"])
        second = validate_success(
            api.create_medical_record_share(
                medical_record_share_payload(
                    refreshed["id"], elm["id"], refreshed["version"], scope="SUMMARY"
                ),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=201,
        )

        assert second["status"] == "REQUESTED"
        assert second["scope"] == "SUMMARY"
        assert second["requested_by_role"] == "ClubGM"

        assert read_share(api, first["id"])["status"] == "SUPERSEDED"

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 0
        assert evaluation["disclosure_state"] == "DISCLOSABLE"


class TestShareExpiryOnRead:
    """Access is derived from the logical clock every time the share is read."""

    def test_share_reads_as_expired_at_its_own_window_instant(self, api):
        """Once the clock reaches expires_at the share reads EXPIRED with no access.

        The clock move sweeps the granted share into EXPIRED, and the access the
        club can exercise is NONE at the exact window instant.

        PRD: "Each advance also sweeps the medical-sharing ledger: every `MedicalRecordShare` in `GRANTED` whose `expires_at` is at or before the new instant transitions to `EXPIRED`, its `effective_access` becomes `NONE`, and its evaluation's `active_share_count` is decremented by one."
        PRD: "The share's `effective_access` reports what the club can actually read right now: it equals the share's `scope` — `SUMMARY` or `FULL` — while `status` is `GRANTED` and the current logical instant is strictly before `expires_at`, and it is `NONE` in every other case, including at the exact `expires_at` instant."

        Design: Corner/endpoints/granted_share_reads_as_expired_once_the_clock_passes_the_window
        """
        state = build_granted_share(api)
        elm = state["clubs"]["ELM"]

        set_clock(api, "2027-03-15T12:00:00.000Z")

        share = validate_success(
            api.get_medical_record_share(
                state["share"]["id"], make_club_gm_headers(elm["id"])
            ),
            expected_status=200,
        )

        assert share["status"] == "EXPIRED"
        assert share["effective_access"] == "NONE"
        assert share["expires_at"] == "2027-03-15T12:00:00.000Z"

        assert read_evaluation(api, state["evaluation"]["id"])["active_share_count"] == 0


class TestOutOfOrderSelection:
    """An authorized out-of-order selection does not touch the running clock."""

    def test_out_of_order_use_leaves_the_clock_holder_untouched(self, api):
        """The authorized round-two pick is used while overall one keeps its deadline.

        The league authorized the pick and the request acknowledged the jump, so
        the pick is used out of order while the pick on the clock keeps both its
        status and its original deadline.

        PRD: "From `PENDING` the pick moves to `USED` with `selection_source` `OUT_OF_ORDER`."
        PRD: "The pick that holds the clock keeps its `deadline_at` entirely unchanged — jumping the queue steals no time from the club on the clock."

        Design: Corner/endpoints/authorized_out_of_order_selection_leaves_the_running_clock_alone
        """
        state = build_draft_live_on_clock(api)
        elm = state["clubs"]["ELM"]
        on_clock = state["pick"]["r1p1"]
        jumper = state["pick"]["r2p1"]

        validate_success(
            api.act_on_pick_clock(
                jumper["id"], clock_action_payload("AUTHORIZE_OUT_OF_ORDER"), ADMIN
            ),
            expected_status=200,
        )

        used = validate_success(
            api.create_selection(
                jumper["id"],
                selection_payload(state["prospect"]["id"], out_of_order_ack=True),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=200,
        )

        assert used["status"] == "USED"
        assert used["selection_source"] == "OUT_OF_ORDER"
        assert used["out_of_order_authorized"] is True
        assert used["selected_prospect_id"] == state["prospect"]["id"]

        holder = read_pick(api, on_clock["id"])
        assert holder["status"] == "ON_CLOCK"
        assert holder["deadline_at"] == "2027-04-22T18:10:00.000Z"

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["drafted_pick_overall_number"] == 3

        assert_chart_points(read_club(api, elm["id"])["draft_capital_points"], 1000.0)
        assert read_cycle(api, state["cycle"]["id"])["current_overall_number"] == 1


class TestDraftCompletion:
    """The advance endpoint is also the draft-completion trigger."""

    def test_advance_completes_the_draft_and_lapses_every_passed_pick(self, api):
        """When nothing remains pending the advance completes the draft and lapses the passed picks.

        Every pick expired unused, so the completing advance reports four lapsed
        picks and no pick on the clock, the cycle resets its running overall
        number, and the clubs are left with no tradable capital at all.

        PRD: "If the advance finds that no pick in the cycle remains `PENDING` or `ON_CLOCK` — every pick sits in `USED`, `PASSED`, `FORFEITED` or `LAPSED` — the cycle itself moves from `DRAFT_LIVE` to `DRAFT_COMPLETE`."
        PRD: "That transition converts every pick still in `PASSED` to `LAPSED` and sets `current_overall_number` to 0."

        Design: Corner/endpoints/final_advance_completes_the_draft_and_lapses_every_passed_pick
        """
        state = build_draft_live_on_clock(api)
        cycle_id = state["cycle"]["id"]
        elm = state["clubs"]["ELM"]

        set_clock(api, "2027-04-22T19:00:00.000Z")

        completing = None
        for _ in range(6):
            if read_cycle(api, cycle_id)["status"] == "DRAFT_COMPLETE":
                break
            completing = validate_success(
                api.advance_selection_clock(cycle_id, None, ADMIN),
                expected_status=200,
            )
        else:
            raise AssertionError("the draft never reached DRAFT_COMPLETE")

        assert completing is not None, "the draft completed without any advance"
        assert completing["lapsed_count"] == 4
        assert completing["on_clock_pick_id"] is None

        cycle = read_cycle(api, cycle_id)
        assert cycle["status"] == "DRAFT_COMPLETE"
        assert cycle["current_overall_number"] == 0

        for overall in (1, 2, 3, 4):
            pick = read_pick(
                api, pick_by_overall_number(state["picks"], overall)["id"]
            )
            assert pick["status"] == "LAPSED"
            assert pick["pass_reason"] == "EXPIRED"

        club = read_club(api, elm["id"])
        assert_chart_points(club["draft_capital_points"], 0.0)
        assert club["trade_authorization_tier"] == "SUSPENDED"
