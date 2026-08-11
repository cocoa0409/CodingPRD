"""Quorum snapshot vs rolling re-evaluation, fixed-floor override, ABSENT
exclusion, and the >= boundary on open_vote."""
from test_helpers import (
    ApiErrorId,
    add_directors,
    cast_ballot,
    convene_meeting,
    create_meeting_resolution,
    get_success_data,
    open_vote_as_chair,
    record_attendance,
    schedule_noticed_meeting,
    set_clock,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    setup_in_session_meeting,
    setup_vote_open_resolution,
    table_resolution,
    validate_error,
    validate_success,
    SECRETARY,
)
from test_helpers import api_client


class TestQuorumSnapshotVsRolling:
    """Difficulty instance: quorum_snapshot_vs_rolling_on_late_arrival.

    5 ACTIVE directors, bylaws quorum_percent=60 / quorum_fixed_count=1 ->
    required = max(1, ceil(60*5/100)) = 3. Only D1, D2 present at convene
    (snapshot fails); D3 arrives REMOTE after convene; open_vote re-evaluates
    rolling presence and succeeds.
    """

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(5, name="Corp Q")
        d1, d2, d3, _d4, _d5 = directors
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        record_attendance(m["id"], d1["id"], "IN_PERSON")
        record_attendance(m["id"], d2["id"], "IN_PERSON")
        set_clock("2026-06-20T10:00:00Z")
        convene_meeting(m["id"], d1["id"])
        r = create_meeting_resolution(corp["id"], m["id"], title="R budget", text="Approve budget")
        table_resolution(r["id"])
        # Late arrival recorded after convene.
        record_attendance(m["id"], d3["id"], "REMOTE")
        return corp, d1, d2, d3, m, r

    def test_snapshot_frozen_at_convene(self, api):
        """PRD §3.4: "At the call to order the server stamps `convened_at` and
        freezes a quorum snapshot onto the meeting: `quorum_required_count` is
        the greater of the pinned bylaws' `quorum_fixed_count` and the ceiling
        of `quorum_percent` multiplied by the corporation's current `ACTIVE`
        director count and divided by one hundred ...; `quorum_present_snapshot`
        counts the meeting's attendance records whose `attendance_mode` is
        `IN_PERSON`, `REMOTE`, or `PROXY`, excluding `ABSENT`; and `quorum_met`
        records whether presence reached the requirement, with an exact
        head-count tie counting as quorum present."

        Design: Difficulty/dual_variant_calc/quorum_snapshot_vs_rolling_on_late_arrival
        """
        _corp, _d1, _d2, _d3, m, _r = self._setup(api)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["quorum_required_count"] == 3
        assert after["quorum_present_snapshot"] == 2
        assert after["quorum_met"] is False

    def test_rolling_open_vote_admits_late_arrival(self, api):
        """PRD §3.6: "rolling quorum: a fresh count of the meeting's attendance
        records with `attendance_mode` in `IN_PERSON`, `REMOTE`, or `PROXY`
        must reach the stored `quorum_required_count`, else
        `ERR_QUORUM_NOT_MET` (HTTP 422). Because this rolling presence is
        re-evaluated at every vote opening from all current attendance records,
        directors who arrive after a failed convene snapshot can still lift
        the meeting over quorum."

        Design: Difficulty/dual_variant_calc/quorum_snapshot_vs_rolling_on_late_arrival
        """
        _corp, d1, _d2, _d3, _m, r = self._setup(api)
        from test_helpers import make_chair_headers

        resp = api.open_vote(r["id"], make_chair_headers(d1["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "VOTE_OPEN"


class TestQuorumFixedFloorOverridesPercent:
    """Corner instance: quorum_fixed_floor_overrides_percent.

    quorum_percent=50 over 4 directors gives ceil(2.0)=2 but quorum_fixed_count=4
    wins via the max() floor. 3 of 4 present still fails quorum.
    """

    def _setup(self, api):
        corp, bylaws = setup_corporation_with_adopted_bylaws(
            name="Corp C1", quorum_percent=50, quorum_fixed_count=4
        )
        directors = add_directors(corp["id"], 4)
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        record_attendance(m["id"], directors[0]["id"], "IN_PERSON")
        record_attendance(m["id"], directors[1]["id"], "IN_PERSON")
        record_attendance(m["id"], directors[2]["id"], "REMOTE")
        set_clock("2026-06-20T10:00:00Z")
        convene_meeting(m["id"], d1["id"])
        return corp, directors, m

    def test_fixed_floor_forces_required_count(self, api):
        """PRD §3.4: "`quorum_required_count` is the greater of the pinned
        bylaws' `quorum_fixed_count` and the ceiling of `quorum_percent`
        multiplied by the corporation's current `ACTIVE` director count and
        divided by one hundred — the ceiling is applied to the percentage
        product first, and only then is the maximum taken."

        Design: Corner/calculations/quorum_fixed_floor_overrides_percent
        """
        _corp, _directors, m = self._setup(api)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["quorum_required_count"] == 4, (
            f"expected fixed floor 4 to override percent result 2, got {after['quorum_required_count']}"
        )
        assert after["quorum_present_snapshot"] == 3
        assert after["quorum_met"] is False


class TestQuorumExcludesAbsent:
    """Corner instance: quorum_excludes_absent_records."""

    def test_absent_records_excluded_from_present_count(self, api):
        """PRD §3.4: "`quorum_present_snapshot` counts the meeting's attendance
        records whose `attendance_mode` is `IN_PERSON`, `REMOTE`, or `PROXY`,
        excluding `ABSENT`."

        Design: Corner/calculations/quorum_excludes_absent_records
        """
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp C2")
        d1, d2, _d3 = directors
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        record_attendance(m["id"], d1["id"], "IN_PERSON")
        record_attendance(m["id"], d2["id"], "ABSENT")
        set_clock("2026-06-20T10:00:00Z")
        convene_meeting(m["id"], d1["id"])
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        # required = max(1, ceil(60*3/100)) = max(1, 2) = 2
        assert after["quorum_required_count"] == 2
        assert after["quorum_present_snapshot"] == 1, (
            f"ABSENT record must be excluded, got snapshot {after['quorum_present_snapshot']}"
        )
        assert after["quorum_met"] is False


class TestQuorumBoundary:
    """Difficulty instance: quorum_exactly_at_required_count.

    5 directors, required=3, exactly 3 present at open_vote -> succeeds.
    """

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(5, name="Corp B1")
        d1, d2, d3 = directors[0], directors[1], directors[2]
        m = setup_in_session_meeting(
            corp["id"], d1["id"], [d1["id"], d2["id"], d3["id"]]
        )
        r = create_meeting_resolution(corp["id"], m["id"], title="Boundary", text="text")
        table_resolution(r["id"])
        return corp, d1, m, r

    def test_exactly_required_count_meets_quorum(self, api):
        """PRD §3.4: "and `quorum_met` records whether presence reached the
        requirement, with an exact head-count tie counting as quorum present."

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_required_count
        """
        _corp, _d1, m, _r = self._setup(api)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["quorum_required_count"] == 3
        assert after["quorum_met"] is True

    def test_open_vote_succeeds_at_boundary(self, api):
        """PRD §3.6: "a fresh count of the meeting's attendance records with
        `attendance_mode` in `IN_PERSON`, `REMOTE`, or `PROXY` must reach the
        stored `quorum_required_count`, else `ERR_QUORUM_NOT_MET` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_required_count
        """
        _corp, d1, _m, r = self._setup(api)
        from test_helpers import make_chair_headers

        resp = api.open_vote(r["id"], make_chair_headers(d1["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "VOTE_OPEN"


class TestOpenVoteBelowQuorumRejected:
    """Corner instance: open_vote_below_quorum_rejected."""

    def test_open_vote_below_quorum_rejected(self, api):
        """PRD §3.6: "rolling quorum: a fresh count of the meeting's attendance
        records with `attendance_mode` in `IN_PERSON`, `REMOTE`, or `PROXY`
        must reach the stored `quorum_required_count`, else `ERR_QUORUM_NOT_MET`
        (HTTP 422)."

        Design: Corner/errors/open_vote_below_quorum_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(5, name="Corp R1")
        d1, d2 = directors[0], directors[1]
        m = setup_in_session_meeting(corp["id"], d1["id"], [d1["id"], d2["id"]])
        r = create_meeting_resolution(corp["id"], m["id"], title="R", text="t")
        table_resolution(r["id"])
        from test_helpers import make_chair_headers

        resp = api.open_vote(r["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["status"] == "TABLED"
