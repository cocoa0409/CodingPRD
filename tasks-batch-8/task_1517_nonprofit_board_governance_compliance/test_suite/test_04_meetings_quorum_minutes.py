"""Meetings: quorum attainment, buffered overlap, notice discipline, minutes."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


class TestQuorumBasisVariants:
    """Difficulty: dual_variant_calc / quorum_seated_vs_authorized_basis."""

    def _setup_four_active(self, api, ein, quorum_basis):
        org = fx.create_nonprofit(name="Org", ein=ein)
        fx.create_adopted_bylaws(org["id"], quorum_pct=50, quorum_basis=quorum_basis,
                                 board_size=5)
        members = []
        specs = [("Chair", "CHAIR"), ("D1", None), ("D2", None), ("D3", None)]
        for i, (name, officer) in enumerate(specs):
            m = fx.create_board_member(org["id"], name, f"{name.lower()}@x.org",
                                       skills=[["GOVERNANCE", "FINANCE", "LEGAL",
                                                "PROGRAM"][i]],
                                       officer_role=officer)
            fx.elect_member(org["id"], m["id"], start_date="2026-01-01T00:00:00Z")
            members.append(th.validate_success(api.get_board_member(m["id"], ADMIN)))
        meeting = fx.create_meeting(org["id"], start="2026-08-01T00:00:00Z")
        return org, members, meeting

    def test_seated_basis_vacancy_shrinks_quorum_and_passes(self, api):
        """PRD §3.4: "The denominator follows the adopted bylaws' `quorum_basis`:
        under `SEATED` it is the count of eligible scope members at call time, so
        vacancies shrink the requirement, while under `AUTHORIZED` it is the fixed
        seat count — the bylaws' `board_size` for a board meeting or the committee's
        `authorized_size` for a committee meeting — so vacancies do not shrink the
        requirement, and the same attendance can pass under one basis and fail under
        the other."
        PRD §3.4: "The `quorum_required` is the `quorum_pct` fraction of that base,
        rounded up to a whole seat with exact halves rounding up, and quorum is met
        when the present count is at least the requirement — equality passes — else
        the call is rejected with `ERR_QUORUM_NOT_MET`."

        Design: Difficulty/dual_variant_calc/quorum_seated_vs_authorized_basis
        """
        org, members, meeting = self._setup_four_active(api, "EIN-SEATED-1", "SEATED")
        chair, d1 = members[0], members[1]
        called = th.validate_success(api.call_to_order(
            meeting["id"], {"attendance": [chair["id"], d1["id"]]},
            th.make_board_chair_headers(chair["id"])))
        assert called["status"] == "IN_SESSION"
        assert called["quorum_base"] == 4, (
            f"SEATED base is the 4 ACTIVE members, got {called['quorum_base']}")
        assert called["quorum_required"] == 2
        assert called["quorum_met"] is True

    def test_authorized_basis_same_roster_rejected(self, api):
        """PRD §3.4: "The denominator follows the adopted bylaws' `quorum_basis`:
        under `SEATED` it is the count of eligible scope members at call time, so
        vacancies shrink the requirement, while under `AUTHORIZED` it is the fixed
        seat count — the bylaws' `board_size` for a board meeting or the committee's
        `authorized_size` for a committee meeting — so vacancies do not shrink the
        requirement, and the same attendance can pass under one basis and fail under
        the other."
        PRD §3.4: "The `quorum_required` is the `quorum_pct` fraction of that base,
        rounded up to a whole seat with exact halves rounding up, and quorum is met
        when the present count is at least the requirement — equality passes — else
        the call is rejected with `ERR_QUORUM_NOT_MET`."

        Design: Difficulty/dual_variant_calc/quorum_seated_vs_authorized_basis
        """
        org, members, meeting = self._setup_four_active(api, "EIN-AUTH-1", "AUTHORIZED")
        chair, d1 = members[0], members[1]
        # AUTHORIZED base is board_size 5 -> required ceil(0.5*5) == 3; only 2 present
        resp = api.call_to_order(
            meeting["id"], {"attendance": [chair["id"], d1["id"]]},
            th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_QUORUM_NOT_MET)
        meeting_after = th.validate_success(api.get_meeting(meeting["id"], ADMIN))
        assert meeting_after["status"] == "SCHEDULED", (
            "a rejected call to order must leave the meeting SCHEDULED")


class TestQuorumBoundary:
    """Difficulty: boundary_precision_check / quorum_exactly_met_vs_one_short."""

    def _setup_two_meetings(self, api):
        org = fx.create_nonprofit(name="Quorum Org", ein="EIN-QRM-1")
        fx.create_adopted_bylaws(org["id"], quorum_pct=50, quorum_basis="SEATED",
                                 board_size=5)
        members = []
        specs = [("Chair", "CHAIR"), ("D1", None), ("D2", None), ("D3", None)]
        for i, (name, officer) in enumerate(specs):
            m = fx.create_board_member(org["id"], name, f"{name.lower()}@x.org",
                                       skills=[["GOVERNANCE", "FINANCE", "LEGAL",
                                                "PROGRAM"][i]],
                                       officer_role=officer)
            fx.elect_member(org["id"], m["id"], start_date="2026-01-01T00:00:00Z")
            members.append(th.validate_success(api.get_board_member(m["id"], ADMIN)))
        m1 = fx.create_meeting(org["id"], start="2026-08-01T00:00:00Z")
        m2 = fx.create_meeting(org["id"], start="2026-08-01T02:00:00Z")
        return org, members, m1, m2

    def test_quorum_exactly_met_passes(self, api):
        """PRD §3.4: "The `quorum_required` is the `quorum_pct` fraction of that
        base, rounded up to a whole seat with exact halves rounding up, and quorum
        is met when the present count is at least the requirement — equality passes
        — else the call is rejected with `ERR_QUORUM_NOT_MET`."

        Design: Difficulty/boundary_precision_check/quorum_exactly_met_vs_one_short
        """
        _org, members, m1, _m2 = self._setup_two_meetings(api)
        chair, d1 = members[0], members[1]
        # SEATED base 4, pct 50 -> required 2; exactly 2 present passes on >=
        called = th.validate_success(api.call_to_order(
            m1["id"], {"attendance": [chair["id"], d1["id"]]},
            th.make_board_chair_headers(chair["id"])))
        assert called["status"] == "IN_SESSION"
        assert called["quorum_required"] == 2
        assert called["quorum_met"] is True

    def test_quorum_one_short_rejected(self, api):
        """PRD §3.4: "The `quorum_required` is the `quorum_pct` fraction of that
        base, rounded up to a whole seat with exact halves rounding up, and quorum
        is met when the present count is at least the requirement — equality passes
        — else the call is rejected with `ERR_QUORUM_NOT_MET`."

        Design: Difficulty/boundary_precision_check/quorum_exactly_met_vs_one_short
        """
        _org, members, _m1, m2 = self._setup_two_meetings(api)
        chair, d1 = members[0], members[1]
        # m2 starts 02:00; the clock must reach scheduled_start (§3.4) before the
        # quorum gate (#21) can be reached — window rules precede it (§2.7 #19).
        fx.set_clock("2026-08-01T02:00:00Z")
        resp = api.call_to_order(m2["id"], {"attendance": [d1["id"]]},
                                 th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_QUORUM_NOT_MET)
        meeting_after = th.validate_success(api.get_meeting(m2["id"], ADMIN))
        assert meeting_after["status"] == "SCHEDULED"


class TestQuorumCeil:
    def test_quorum_ceil_half_rounds_up(self, api):
        """PRD §3.4: "The `quorum_required` is the `quorum_pct` fraction of that
        base, rounded up to a whole seat with exact halves rounding up, and quorum
        is met when the present count is at least the requirement — equality passes
        — else the call is rejected with `ERR_QUORUM_NOT_MET`."
        PRD §2.9: "Quorum and review-coverage arithmetic yields whole seats or whole
        members, with exact halves always rounding up (ceiling)."

        Design: Corner/calculations/quorum_ceil_half_rounds_up
        """
        sc = fx.setup_org_with_board(num_directors=4, officers=("CHAIR",),
                                     bylaws={"quorum_pct": 50, "board_size": 5},
                                     receipts=1_000_000, ein="EIN-QC-1")
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        ids = [m["id"] for m in sc["members"]]
        m1 = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z")
        m2 = fx.create_meeting(np_id, start="2026-08-01T02:00:00Z")

        # base 5, pct 50 -> ceil(2.5) == 3; 2 present fails
        resp = api.call_to_order(m1["id"], {"attendance": ids[:2]},
                                 th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_QUORUM_NOT_MET)

        # m2 starts 02:00; advance the logical clock (§2.4) so the window rule
        # (§2.7 #19) passes and the quorum gate (#21) is what gets exercised.
        fx.set_clock("2026-08-01T02:00:00Z")
        called = th.validate_success(api.call_to_order(
            m2["id"], {"attendance": ids[:3]},
            th.make_board_chair_headers(chair["id"])))
        assert called["status"] == "IN_SESSION"
        assert called["quorum_required"] == 3, (
            f"the exact half of 5 must round up to 3, got {called['quorum_required']}")


class TestMeetingBuffer:
    """Difficulty: resource_temporal_overlap / meeting_thirty_minute_buffer_rule."""

    def test_meeting_adjacency_and_29_min_buffer_rejected(self, api):
        """PRD §2.8: "The buffer applies on both sides, so a new meeting starting at
        the exact instant another ends is still a conflict; exactly thirty minutes
        of separation passes, while twenty-nine minutes fails. Conflicts are
        rejected with `ERR_MEETING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/meeting_thirty_minute_buffer_rule
        """
        org = fx.create_nonprofit(name="Buffer Org", ein="EIN-BUF-1")
        fx.create_meeting(org["id"], start="2026-08-01T10:00:00Z", duration=60)

        resp_adjacent = api.create_meeting(
            th.create_meeting_payload(org["id"],
                                      scheduled_start="2026-08-01T11:00:00Z",
                                      duration_minutes=60, notice_waived=True),
            ADMIN)
        th.validate_error(resp_adjacent, th.ApiErrorId.ERR_MEETING_OVERLAP)

        resp_29 = api.create_meeting(
            th.create_meeting_payload(org["id"],
                                      scheduled_start="2026-08-01T11:29:00Z",
                                      duration_minutes=60, notice_waived=True),
            ADMIN)
        th.validate_error(resp_29, th.ApiErrorId.ERR_MEETING_OVERLAP)

    def test_meeting_exactly_30_min_buffer_allowed(self, api):
        """PRD §2.8: "The buffer applies on both sides, so a new meeting starting at
        the exact instant another ends is still a conflict; exactly thirty minutes
        of separation passes, while twenty-nine minutes fails. Conflicts are
        rejected with `ERR_MEETING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/meeting_thirty_minute_buffer_rule
        """
        org = fx.create_nonprofit(name="Buffer Org", ein="EIN-BUF-1")
        fx.create_meeting(org["id"], start="2026-08-01T10:00:00Z", duration=60)

        created = th.validate_success(api.create_meeting(
            th.create_meeting_payload(org["id"],
                                      scheduled_start="2026-08-01T11:30:00Z",
                                      duration_minutes=60, notice_waived=True),
            ADMIN), 201)
        th.assert_meeting(created)
        assert created["status"] == "SCHEDULED", (
            "exactly thirty minutes of separation satisfies the buffer")


class TestNoticeAndEarlyCall:
    def test_meeting_notice_and_early_call_and_duplicate_committee_name(self, api):
        """PRD §3.4: "Bylaws-level notice discipline is checked not at scheduling
        but at call to order: unless `notice_waived` is true, the `notice_sent_at`
        must fall at least seven days before the `scheduled_start`, else the call is
        rejected with `ERR_NOTICE_INSUFFICIENT`."
        PRD §3.4: "The clock must have reached the `scheduled_start`
        (`ERR_MEETING_TOO_EARLY`), the notice rule above must hold, and a committee
        meeting additionally requires the committee to be `ACTIVE`
        (`ERR_COMMITTEE_NOT_ACTIVE`)."
        PRD §3.3: "Committees are chartered by a `GovernanceAdmin` or `BoardChair`
        with a `name` unique within the nonprofit among committees that are not
        `DISSOLVED` (`ERR_DUPLICATE_COMMITTEE_NAME`)"

        Design: Corner/errors/meeting_notice_and_early_call_and_duplicate_committee_name
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-MTG-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        m1 = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z",
                               notice_waived=False,
                               notice_sent_at="2026-07-30T00:00:00Z")
        m2 = fx.create_meeting(np_id, start="2026-09-01T00:00:00Z",
                               notice_waived=True)
        fx.create_committee(np_id, name="Audit Cttee", type="AUDIT",
                            min_members=1, authorized_size=3)

        resp_notice = api.call_to_order(m1["id"], {"attendance": [chair["id"]]},
                                        chair_headers)
        th.validate_error(resp_notice, th.ApiErrorId.ERR_NOTICE_INSUFFICIENT)

        resp_early = api.call_to_order(m2["id"], {"attendance": [chair["id"]]},
                                       chair_headers)
        th.validate_error(resp_early, th.ApiErrorId.ERR_MEETING_TOO_EARLY)

        resp_dup = api.create_committee(
            th.create_committee_payload(np_id, "Audit Cttee", type="FINANCE",
                                        min_members=1, authorized_size=2), ADMIN)
        th.validate_error(resp_dup, th.ApiErrorId.ERR_DUPLICATE_COMMITTEE_NAME)


class TestAdjournmentSettlesFloor:
    def test_adjourn_tables_open_motion_preserving_votes(self, api):
        """PRD §3.4: "Adjournment, again by the `BoardChair`, moves the meeting to
        `ADJOURNED` and settles the floor: every motion of the meeting still
        `VOTING_OPEN` or `TABLED` is set to `TABLED` with its recorded votes
        preserved."

        Design: Corner/state_machines/adjourn_tables_open_motion_preserving_votes
        """
        sc = fx.setup_voting_scenario(num_members=2, category="GOVERNANCE",
                                      ein="EIN-AJ-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, d1 = sc["chair"], sc["members"][1]
        fx.cast_vote(np_id, sc["motion"]["id"], d1, "AYE")

        adjourned = th.validate_success(api.adjourn_meeting(
            sc["meeting"]["id"], th.make_board_chair_headers(chair["id"])))
        assert adjourned["status"] == "ADJOURNED"

        motion = th.validate_success(api.get_motion(sc["motion"]["id"], ADMIN))
        assert motion["status"] == "TABLED", (
            f"adjournment must table the still-open motion, got {motion['status']}")
        assert motion["votes_for"] == 1, "the recorded AYE survives the auto-table"


class TestMinutesWorkflow:
    def test_minutes_reject_redraft_then_approve_cycle(self, api):
        """PRD §3.4: "Rejection follows the same meeting-validity rule via
        `rejecting_meeting_id` (`ERR_MINUTES_APPROVAL_MEETING_INVALID`) and sends
        the meeting back to `ADJOURNED`, clearing both `minutes_text` and
        `minutes_recorded_by` so the draft must be re-created — the deliberate
        `ADJOURNED`-to-`MINUTES_DRAFTED` cycle that lets a board correct its record
        across sittings."
        PRD §3.4: "Approval moves the minutes to `MINUTES_APPROVED`."

        Design: Corner/state_machines/minutes_reject_redraft_then_approve_cycle
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-MN-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])

        m1 = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z")
        m2 = fx.create_meeting(np_id, start="2026-08-15T00:00:00Z")
        m3 = fx.create_meeting(np_id, start="2026-08-16T00:00:00Z")
        fx.call_to_order(m1["id"], chair, [chair["id"]])
        adjourned = th.validate_success(api.adjourn_meeting(m1["id"], chair_headers))
        drafted = th.validate_success(api.record_minutes(
            m1["id"], {"expected_meeting_version": adjourned["version"],
                       "minutes_text": "draft v1"}, ADMIN))
        assert drafted["status"] == "MINUTES_DRAFTED"

        fx.set_clock("2026-08-15T00:00:00Z")
        fx.call_to_order(m2["id"], chair, [chair["id"]])
        rejected = th.validate_success(api.reject_minutes(
            m1["id"], {"rejecting_meeting_id": m2["id"]}, chair_headers))
        assert rejected["status"] == "ADJOURNED", (
            f"rejection sends the meeting back to ADJOURNED, got {rejected['status']}")
        assert rejected.get("minutes_text") in (None, ""), (
            "rejection clears minutes_text so the draft must be re-created")

        redrafted = th.validate_success(api.record_minutes(
            m1["id"], {"expected_meeting_version": rejected["version"],
                       "minutes_text": "draft v2"}, ADMIN))
        assert redrafted["status"] == "MINUTES_DRAFTED"

        fx.set_clock("2026-08-16T00:00:00Z")
        fx.call_to_order(m3["id"], chair, [chair["id"]])
        approved = th.validate_success(api.approve_minutes(
            m1["id"], {"approving_meeting_id": m3["id"]}, chair_headers))
        assert approved["status"] == "MINUTES_APPROVED"

    def test_minutes_approval_same_or_foreign_scope_rejected(self, api):
        """PRD §3.4: "Approval happens at a later sitting of the same body: the
        `BoardChair` approves the draft by reference to an `approving_meeting_id`,
        which must name a different meeting of the same scope — the same nonprofit
        and the same `committee_id`, with both null counting as the same scope —
        that is currently `IN_SESSION`, else `ERR_MINUTES_APPROVAL_MEETING_INVALID`"

        Design: Corner/state_machines/minutes_approval_same_or_foreign_scope_rejected
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",),
                                     ein="EIN-MS-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, reviewer = sc["chair"], sc["members"][1]
        chair_headers = th.make_board_chair_headers(chair["id"])
        fx.clear_coi_for_all(np_id, [chair, reviewer], fiscal_year=2026)
        committee, _appts = fx.setup_active_committee(
            np_id, chair, [chair], name="Gov", type="GOVERNANCE",
            min_members=1, authorized_size=3)

        m1 = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z")
        fx.call_to_order(m1["id"], chair, [chair["id"]])
        adjourned = th.validate_success(api.adjourn_meeting(m1["id"], chair_headers))
        th.validate_success(api.record_minutes(
            m1["id"], {"expected_meeting_version": adjourned["version"],
                       "minutes_text": "draft"}, ADMIN))

        cm1 = fx.create_meeting(np_id, start="2026-08-02T00:00:00Z",
                                committee_id=committee["id"])
        fx.set_clock("2026-08-02T00:00:00Z")
        fx.call_to_order(cm1["id"], chair, [chair["id"]])

        resp_self = api.approve_minutes(
            m1["id"], {"approving_meeting_id": m1["id"]}, chair_headers)
        th.validate_error(resp_self, th.ApiErrorId.ERR_MINUTES_APPROVAL_MEETING_INVALID)

        resp_scope = api.approve_minutes(
            m1["id"], {"approving_meeting_id": cm1["id"]}, chair_headers)
        th.validate_error(resp_scope, th.ApiErrorId.ERR_MINUTES_APPROVAL_MEETING_INVALID)

        meeting_after = th.validate_success(api.get_meeting(m1["id"], ADMIN))
        assert meeting_after["status"] == "MINUTES_DRAFTED"


class TestMinutesOcc:
    def test_minutes_record_occ_stale_version_rejected(self, api):
        """PRD §2.6: "`POST /boardgov/meetings/{id}/minutes` requires
        `expected_meeting_version`, carrying the client's last observed `version` of
        the meeting. If another writer has advanced the meeting's version since the
        client last read it — for example, because a colleague legitimately recorded
        a replacement draft — the request is rejected with `ERR_STALE_VERSION` (HTTP
        412), preventing a minutes writer from overwriting a draft it has not
        observed."
        PRD §3.4: "The first recording moves an `ADJOURNED` meeting to
        `MINUTES_DRAFTED`; a later recording stays in `MINUTES_DRAFTED` and replaces
        the draft; either way the meeting records the caller as
        `minutes_recorded_by` and its `version` increments by 1."

        Design: Corner/cross_cutting_layers/minutes_record_occ_stale_version_rejected
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",),
                                     ein="EIN-OC2-1", receipts=1_000_000)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        meeting = fx.create_meeting(np_id, start="2026-08-01T00:00:00Z")
        fx.call_to_order(meeting["id"], chair, [chair["id"]])
        adjourned = th.validate_success(api.adjourn_meeting(meeting["id"], chair_headers))
        mv = adjourned["version"]

        first = th.validate_success(api.record_minutes(
            meeting["id"], {"expected_meeting_version": mv,
                            "minutes_text": "first"}, ADMIN))
        assert first["status"] == "MINUTES_DRAFTED"
        assert first["version"] == mv + 1

        th.validate_error(api.record_minutes(
            meeting["id"], {"expected_meeting_version": mv,
                            "minutes_text": "stale overwrite"}, ADMIN),
            th.ApiErrorId.ERR_STALE_VERSION, 412)

        second = th.validate_success(api.record_minutes(
            meeting["id"], {"expected_meeting_version": first["version"],
                            "minutes_text": "second"}, ADMIN))
        assert second["minutes_text"] == "second"
        assert second["version"] == first["version"] + 1
