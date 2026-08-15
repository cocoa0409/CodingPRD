"""Meetings, quorum, resolutions, and role-based access control: context
headers, role gates, voting discipline, the notice precondition, quorum
boundary semantics, ceiling division, and the parallel state dimensions."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    advance_clock,
    assert_meeting,
    cast_ballot,
    create_cooperative,
    create_meeting,
    create_purchase_application_payload,
    create_resolution_payload,
    get_meeting,
    make_board_member_headers,
    make_managing_agent_headers,
    make_shareholder_headers,
    open_resolution,
    send_notice,
    setup_coop_with_owner,
    setup_meeting_env,
    setup_meeting_in_session,
    submit_purchase_app,
    validate_error,
    validate_success,
)


class TestAuthAndRBAC:
    def test_missing_context_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming
        the role under which the operator acts. A request missing either header,
        or carrying a malformed value, is rejected with
        `ERR_MISSING_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/unauthenticated_missing_header
        """
        resp = api.list_cooperatives(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER,
                       expected_status=400)

    def test_shareholder_cannot_create_resolution(self, api):
        """PRD §2.1: "A request whose `X-User-Role` is not among the
        roles permitted for the target endpoint (as enumerated in §4) is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "`BoardOfficer` — a board president, treasurer, or
        secretary. Schedules interviews, opens and withdraws resolutions,
        manages charge schedules and meetings, records transfers, escalates or
        withdraws arrears actions, and rules on sublets."
        PRD §2.1: "`Shareholder` — a co-op unit owner. Initiates purchase
        applications as seller, requests sublets and alterations, performs
        renovation lifecycle actions, and casts ballots."

        Design: Corner/validations/unauthorized_role_shareholder_cannot_create_resolution
        """
        env = setup_coop_with_owner()
        resp = api.create_resolution(
            env["coop"]["id"],
            create_resolution_payload("SET_POLICY", "Cooperative",
                                      env["coop"]["id"]),
            make_shareholder_headers(env["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_board_member_cannot_certify_application(self, api):
        """PRD §2.1: "`BoardMember` — a board director. Sits on interview
        panels and casts votes on resolutions."
        PRD §2.1: "`ManagingAgent` — the building's external managing
        agent. Certifies the completeness of purchase packages, posts and voids
        payments, and issues arrears notices; it cannot vote, schedule
        interviews, or sit on panels."
        PRD §2.1: "A request whose `X-User-Role` is not among the roles
        permitted for the target endpoint (as enumerated in §4) is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/board_member_cannot_certify_application
        """
        env = setup_coop_with_owner()
        app = validate_success(api.create_purchase_application(
            env["coop"]["id"],
            create_purchase_application_payload(env["unit"]["id"],
                                                env["owner"]["id"]),
            make_shareholder_headers(env["owner"]["id"])), 201)
        submit_purchase_app(env["coop"]["id"], app["id"], env["owner"]["id"])
        resp = api.certify_purchase_application(
            env["coop"]["id"], app["id"], make_board_member_headers("bm-1"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_managing_agent_cannot_vote_on_resolution(self, api):
        """PRD §2.1: "Certifies the completeness of purchase packages,
        posts and voids payments, and issues arrears notices; it cannot vote,
        schedule interviews, or sit on panels."
        PRD §2.1: "A request whose `X-User-Role` is not among the roles
        permitted for the target endpoint (as enumerated in §4) is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/managing_agent_cannot_vote_on_resolution
        """
        coop = create_cooperative(name="RBAC3")
        resolution = open_resolution(coop["id"], "SET_POLICY", "Cooperative",
                                     coop["id"])
        resp = api.cast_vote(coop["id"], resolution["id"], {"vote_choice": "FOR"},
                             make_managing_agent_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

    def test_shareholder_cannot_advance_clock(self, api):
        """PRD §2.5: "it thereafter advances only when a `PlatformAdmin`
        explicitly sets it through the clock-advance capability, passing the
        target instant as `to_iso8601`."
        PRD §2.1: "A request whose `X-User-Role` is not among the roles
        permitted for the target endpoint (as enumerated in §4) is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/shareholder_cannot_advance_clock
        """
        env = setup_coop_with_owner()
        resp = api.set_clock(env["coop"]["id"], "2026-09-01T00:00:00Z",
                             make_shareholder_headers(env["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


class TestResolutionVotingDiscipline:
    def test_withdraw_after_vote_cast_rejected(self, api):
        """PRD §3.2: "A `BoardOfficer` may also withdraw a resolution,
        but only while it is still `OPEN` and not a single vote has been cast;
        withdrawing after any vote exists is rejected with
        `ERR_RESOLUTION_ALREADY_VOTED` (HTTP 409), and withdrawal sets
        `closed_at` like any other closure."

        Design: Corner/state_machines/resolution_withdraw_forbidden_after_vote_cast
        """
        coop = create_cooperative(name="WV Coop")
        resolution = open_resolution(coop["id"], "SET_POLICY", "Cooperative",
                                     coop["id"],
                                     payload_json={"flip_tax_percent_bps": 250})
        vote = validate_success(api.cast_vote(
            coop["id"], resolution["id"], {"vote_choice": "FOR"},
            make_board_member_headers("bm-1")), 201)
        assert vote["resolution_id"] == resolution["id"]

        resp = api.withdraw_resolution(coop["id"], resolution["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_RESOLUTION_ALREADY_VOTED,
                       expected_status=409)

    def test_duplicate_vote_by_same_member_rejected(self, api):
        """PRD §3.2: "A member who attempts to vote twice on the same
        resolution is rejected with `ERR_VOTER_ALREADY_CAST` (HTTP 409)."

        Design: Corner/state_machines/duplicate_vote_by_same_voter_rejected
        """
        coop = create_cooperative(name="DupV")
        resolution = open_resolution(coop["id"], "SET_POLICY", "Cooperative",
                                     coop["id"])
        validate_success(api.cast_vote(coop["id"], resolution["id"],
                                       {"vote_choice": "FOR"},
                                       make_board_member_headers("bm-1")), 201)
        resp = api.cast_vote(coop["id"], resolution["id"],
                             {"vote_choice": "AGAINST"},
                             make_board_member_headers("bm-1"))
        validate_error(resp, ApiErrorId.ERR_VOTER_ALREADY_CAST, expected_status=409)


class TestMeetingLifecycle:
    def test_open_requires_notice_sent(self, api):
        """PRD §3.9: "Sending notice to the shareholders moves
        `preparation_state` from `PREPARING` to `NOTICE_SENT`, and only then may
        the officer open the meeting — opening requires both that notice has
        been sent and that the logical clock has reached `scheduled_at` —
        moving `meeting_status` from `SCHEDULED` to `IN_SESSION`."
        PRD §2.9: "the target resource is in a state from which the
        requested transition exists; failure yields `ERR_INVALID_STATE`
        (HTTP 409)".

        Design: Corner/state_machines/meeting_open_requires_notice_sent
        """
        coop = create_cooperative(name="Prep Coop")
        meeting = create_meeting(coop["id"])
        assert meeting["preparation_state"] == "PREPARING"
        advance_clock(coop["id"], "2026-08-20T18:30:00Z")
        resp = api.open_meeting(coop["id"], meeting["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_close_without_quorum_adjourns_meeting(self, api):
        """PRD §3.9: "If quorum is not met, closing instead moves the
        meeting from `IN_SESSION` to `ADJOURNED_NO_QUORUM`: every `SUBMITTED`
        ballot becomes `INVALIDATED` and `preparation_state` becomes
        `ADJOURNED`."
        PRD §3.9: "a meeting that adjourns without quorum lands in
        `QUORUM_FAILED`."

        Design: Corner/errors/error_meeting_no_quorum
        """
        env = setup_meeting_in_session(shares_list=(100,))
        coop_id = env["coop"]["id"]
        meeting = env["meeting"]
        assert meeting["meeting_status"] == "IN_SESSION"
        assert meeting["shares_represented"] == 0

        closed = validate_success(api.close_meeting(coop_id, meeting["id"],
                                                    {"open_seats": 3}, OFFICER), 200)
        assert closed["meeting_status"] == "ADJOURNED_NO_QUORUM"
        assert closed["quorum_state"] == "QUORUM_FAILED"
        assert closed["preparation_state"] == "ADJOURNED"
        assert_meeting(closed)


class TestQuorumBoundaries:
    def test_quorum_met_exactly_at_threshold(self, api):
        """PRD §3.9: "When `shares_represented` reaches the threshold the
        `quorum_state` becomes `QUORUM_MET`; equality counts — representation
        exactly at the threshold is met, not pending."
        PRD §3.9: "the quorum threshold is the smallest whole number of
        shares that is at least the cooperative's `total_shares` multiplied by
        `annual_meeting_quorum_percent_bps` out of ten thousand".

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold_counts_met
        """
        env = setup_meeting_in_session(shares_list=(100, 100))
        coop_id = env["coop"]["id"]
        # total_shares = 200, quorum 5000 bps -> threshold exactly 100 shares.
        ballot = cast_ballot(coop_id, env["meeting"]["id"], env["owners"][0]["id"])
        assert ballot["shares_voted"] == 100
        meeting = get_meeting(coop_id, env["meeting"]["id"])
        assert meeting["shares_represented"] == 100, "exactly at the threshold"
        assert meeting["quorum_state"] == "QUORUM_MET", "equality counts as met"

    def test_quorum_pending_one_share_below_threshold(self, api):
        """PRD §3.9: "While the meeting is `SCHEDULED` or `IN_SESSION`
        below the threshold, quorum remains `QUORUM_PENDING`".

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold_counts_met
        """
        env = setup_meeting_in_session(shares_list=(99, 101))
        coop_id = env["coop"]["id"]
        # total_shares = 200, threshold = 100; a 99-share ballot is one below.
        ballot = cast_ballot(coop_id, env["meeting"]["id"], env["owners"][0]["id"])
        assert ballot["shares_voted"] == 99
        meeting = get_meeting(coop_id, env["meeting"]["id"])
        assert meeting["shares_represented"] == 99
        assert meeting["quorum_state"] == "QUORUM_PENDING"

    def test_quorum_threshold_uses_ceiling_division(self, api):
        """PRD §3.9: "the quorum threshold is the smallest whole number
        of shares that is at least the cooperative's `total_shares` multiplied
        by `annual_meeting_quorum_percent_bps` out of ten thousand — ceiling
        division, so any fraction rounds up."
        PRD §3.9: "The meeting's `shares_represented` is the sum of
        `shares_voted` over its ballots in `SUBMITTED` or `COUNTED` status".

        Design: Corner/calculations/quorum_ceiling_division_precision
        """
        env = setup_meeting_in_session(shares_list=(1, 1, 1))
        coop_id = env["coop"]["id"]
        meeting_id = env["meeting"]["id"]
        # total_shares = 3 at 5000 bps -> ceil(1.5) = 2 shares for quorum.
        cast_ballot(coop_id, meeting_id, env["owners"][0]["id"])
        meeting = get_meeting(coop_id, meeting_id)
        assert meeting["shares_represented"] == 1
        assert meeting["quorum_state"] == "QUORUM_PENDING", \
            "1 share is below the ceiling of 1.5"

        cast_ballot(coop_id, meeting_id, env["owners"][1]["id"],
                    ballot_kind="PROXY")
        meeting = get_meeting(coop_id, meeting_id)
        assert meeting["shares_represented"] == 2
        assert meeting["quorum_state"] == "QUORUM_MET", \
            "2 shares reaches the ceiling-of-1.5 threshold"


class TestMeetingParallelDimensions:
    def test_notice_sent_leaves_quorum_pending(self, api):
        """PRD §3.9: "A meeting's state has two orthogonal dimensions:
        the `preparation_state`, which begins at `PREPARING`, and the
        `quorum_state`, which begins at `QUORUM_PENDING`; the externally visible
        `meeting_status`, beginning at `SCHEDULED`, derives from the combination
        of the two."
        PRD §3.9: "Sending notice to the shareholders moves
        `preparation_state` from `PREPARING` to `NOTICE_SENT`".

        Design: Difficulty/non_linear_state_machine/meeting_parallel_dimensions_preparation_and_quorum
        """
        env = setup_meeting_env(shares_list=(100,))
        coop_id = env["coop"]["id"]
        meeting = create_meeting(coop_id)
        assert meeting["preparation_state"] == "PREPARING"
        assert meeting["quorum_state"] == "QUORUM_PENDING"
        assert meeting["meeting_status"] == "SCHEDULED"

        noticed = send_notice(coop_id, meeting["id"])
        assert noticed["preparation_state"] == "NOTICE_SENT"
        assert noticed["quorum_state"] == "QUORUM_PENDING", \
            "notice moves only the preparation dimension"
        assert noticed["shares_represented"] == 0

    def test_quorum_met_leaves_preparation_state_unchanged(self, api):
        """PRD §3.9: "At cast time the server derives `shares_voted` from
        the shareholder's active ledger entries — the sum of shares the
        shareholder controls at that moment — stamps `cast_at`, and files the
        ballot in `SUBMITTED` status."
        PRD §3.9: "When `shares_represented` reaches the threshold the
        `quorum_state` becomes `QUORUM_MET`; equality counts — representation
        exactly at the threshold is met, not pending."

        Design: Difficulty/non_linear_state_machine/meeting_parallel_dimensions_preparation_and_quorum
        """
        env = setup_meeting_in_session(shares_list=(100,))
        coop_id = env["coop"]["id"]
        meeting_id = env["meeting"]["id"]
        # Sole shareholder holds all 100 shares; threshold is 50.
        ballot = cast_ballot(coop_id, meeting_id, env["owners"][0]["id"])
        assert ballot["shares_voted"] == 100
        assert ballot["ballot_status"] == "SUBMITTED"

        meeting = get_meeting(coop_id, meeting_id)
        assert meeting["quorum_state"] == "QUORUM_MET"
        assert meeting["preparation_state"] == "NOTICE_SENT", \
            "ballots move only the quorum dimension"
        assert meeting["shares_represented"] == 100
        assert meeting["meeting_status"] == "IN_SESSION"
