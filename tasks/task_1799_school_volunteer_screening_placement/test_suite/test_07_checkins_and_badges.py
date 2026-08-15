"""Campus check-in windows, singleton visits, badges, and check-out rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    check_in_volunteer,
    check_out_volunteer,
    create_active_volunteer,
    create_campus,
    create_lincoln_campus,
    create_open_opportunity,
    create_orient_module,
    get_success_data,
    make_volunteer_headers,
    request_placement,
    confirm_placement,
    set_clock,
    setup_volunteer_with_confirmed_placement,
    validate_error,
    validate_paginated,
    validate_success,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestCheckInWindowAndSingleton:
    def test_checkin_window_lower_bound_inclusive(self, api):
        """PRD: "Timing is also enforced: the current logical time must fall
        within the closed interval running from thirty minutes before the
        opportunity's `starts_at` through its `ends_at`, inclusive at both
        ends, or the check-in is rejected with `ERR_OUTSIDE_CHECKIN_WINDOW`."
        PRD: "A volunteer may hold at most one open visit at a time, across all
        campuses: checking in while another check-in is still `OPEN` fails with
        `ERR_OPEN_CHECKIN_EXISTS`."

        Design: Difficulty/resource_temporal_overlap/checkin_buffer_window_and_singleton
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Buffer Beth", email="beth@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]
        campus = scenario["campus"]

        # 13:29 is one minute before the buffered window opens.
        set_clock("2026-08-10T13:29:00Z")
        early = api.create_check_in(
            {"campus_id": campus["id"], "placement_id": placement["id"]},
            make_volunteer_headers(vid))
        validate_error(early, ApiErrorId.ERR_OUTSIDE_CHECKIN_WINDOW)

        # 13:30 is exactly thirty minutes before starts_at: inclusive bound.
        set_clock("2026-08-10T13:30:00Z")
        visit = validate_success(api.create_check_in(
            {"campus_id": campus["id"], "placement_id": placement["id"]},
            make_volunteer_headers(vid)), 201)
        assert visit["status"] == "OPEN"
        assert visit["badge_code"] == "LNC-0001"

        # A second visit while one is OPEN is rejected.
        duplicate = api.create_check_in({"campus_id": campus["id"]},
                                        make_volunteer_headers(vid))
        validate_error(duplicate, ApiErrorId.ERR_OPEN_CHECKIN_EXISTS)

    def test_second_open_checkin_rejected(self, api):
        """PRD: "A volunteer may hold at most one open visit at a time, across
        all campuses: checking in while another check-in is still `OPEN` fails
        with `ERR_OPEN_CHECKIN_EXISTS`."

        Design: Difficulty/resource_temporal_overlap/checkin_buffer_window_and_singleton
        """
        recruited = create_active_volunteer("Wandering Wes", "wes@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus_a = create_lincoln_campus()
        campus_b = create_campus(name="Jefferson Middle", campus_code="JEF",
                                 badge_prefix="JEF")

        set_clock("2026-08-05T09:00:00Z")
        first = check_in_volunteer(campus_a["id"], vid)
        assert first["status"] == "OPEN"

        # The singleton rule spans campuses: a walk-in elsewhere still fails.
        second = api.create_check_in({"campus_id": campus_b["id"]},
                                     make_volunteer_headers(vid))
        validate_error(second, ApiErrorId.ERR_OPEN_CHECKIN_EXISTS)


class TestPlacementLinkedCheckIn:
    def test_checkin_rejected_when_placement_cancelled(self, api):
        """PRD: "The placement must be `CONFIRMED` (else
        `ERR_PLACEMENT_INVALID_STATE`); the placement must belong to the
        check-in's volunteer (else `ERR_PLACEMENT_VOLUNTEER_MISMATCH`); and the
        placement's opportunity must be hosted at the campus named in the
        payload (else `ERR_PLACEMENT_CAMPUS_MISMATCH`)."

        Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_placement_cancelled
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Checkin Cher", email="cher@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]
        campus = scenario["campus"]

        validate_success(api.cancel_placement(
            placement["id"], make_volunteer_headers(vid)), 200)

        # Even inside the service window, the CANCELLED placement gates.
        set_clock("2026-08-10T14:30:00Z")
        resp = api.create_check_in(
            {"campus_id": campus["id"], "placement_id": placement["id"]},
            make_volunteer_headers(vid))
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_INVALID_STATE)

        _, meta = validate_paginated(api.list_check_ins(
            DC, params={"volunteer_id": vid}))
        assert meta["total_count"] == 0

    def test_checkin_rejected_when_placement_not_confirmed(self, api):
        """PRD: "The placement must be `CONFIRMED` (else
        `ERR_PLACEMENT_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/checkin_blocked_when_placement_cancelled
        """
        recruited = create_active_volunteer("Pending Pat", "ppat@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=2)
        placement = request_placement(opp["id"], vid)
        assert placement["status"] == "REQUESTED"

        set_clock("2026-08-10T14:30:00Z")
        resp = api.create_check_in(
            {"campus_id": campus["id"], "placement_id": placement["id"]},
            make_volunteer_headers(vid))
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_INVALID_STATE)

    def test_campus_mismatch_on_checkin_rejected(self, api):
        """PRD: "The placement must be `CONFIRMED` (else
        `ERR_PLACEMENT_INVALID_STATE`); the placement must belong to the
        check-in's volunteer (else `ERR_PLACEMENT_VOLUNTEER_MISMATCH`); and the
        placement's opportunity must be hosted at the campus named in the
        payload (else `ERR_PLACEMENT_CAMPUS_MISMATCH`)."

        Design: Corner/endpoints/campus_mismatch_on_checkin_rejected
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Mismatch Max", email="max@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]
        other_campus = create_campus(name="Jefferson Middle",
                                     campus_code="JEF", badge_prefix="JEF")

        set_clock("2026-08-10T14:30:00Z")
        resp = api.create_check_in(
            {"campus_id": other_campus["id"],
             "placement_id": placement["id"]},
            make_volunteer_headers(vid))
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_CAMPUS_MISMATCH)

        _, meta = validate_paginated(api.list_check_ins(
            DC, params={"volunteer_id": vid}))
        assert meta["total_count"] == 0


class TestReferentialBeatsTemporal:
    def _two_volunteer_setup(self):
        """A holds a CONFIRMED placement; B is ACTIVE with no placements."""
        module = create_orient_module()
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=3)
        owner = create_active_volunteer("Owner Olive", "olive@x.com",
                                        "SUPERVISED", module=module)["volunteer"]
        intruder = create_active_volunteer("Intruder Ivan", "ivan@x.com",
                                           "SUPERVISED", module=module)["volunteer"]
        placement = request_placement(opp["id"], owner["id"])
        confirm_placement(placement["id"])
        return campus, placement, owner, intruder

    def test_checkin_foreign_placement_before_window_returns_mismatch(self, api):
        """PRD: "Every request is evaluated against a fixed, ordered pipeline
        of validation stages, and the first stage that fails determines the
        error returned — later stages are never consulted once an earlier one
        has rejected the request."
        PRD: "**Body referential coherence.** Cross-resource claims in the
        payload must hold: hour logging references a placement owned by the
        acting volunteer (`ERR_PLACEMENT_VOLUNTEER_MISMATCH`), and a
        placement-linked check-in requires that the placement belong to the
        check-in's volunteer (`ERR_PLACEMENT_VOLUNTEER_MISMATCH`) and that the
        placement's opportunity be hosted at the campus named in the payload
        (`ERR_PLACEMENT_CAMPUS_MISMATCH`)."
        PRD: "**Temporal windows**, evaluated in endpoint order: the hour-entry
        `worked_date` must fall inside the placement's opportunity window
        (`ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW`); a placement-linked check-in
        must occur inside the check-in window (`ERR_OUTSIDE_CHECKIN_WINDOW`)"

        Design: Difficulty/priority_pair_validation_conflict/hour_entry_referential_beats_temporal
        """
        campus, placement, _, intruder = self._two_volunteer_setup()

        # 13:00 is outside the buffered window [13:30, 17:00]; the foreign
        # placement also fails referential coherence, which runs first.
        set_clock("2026-08-10T13:00:00Z")
        resp = api.create_check_in(
            {"campus_id": campus["id"], "placement_id": placement["id"]},
            make_volunteer_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_VOLUNTEER_MISMATCH)

        _, meta = validate_paginated(api.list_check_ins(
            DC, params={"volunteer_id": intruder["id"]}))
        assert meta["total_count"] == 0

    def test_checkin_foreign_placement_after_window_returns_mismatch(self, api):
        """PRD: "Every request is evaluated against a fixed, ordered pipeline
        of validation stages, and the first stage that fails determines the
        error returned — later stages are never consulted once an earlier one
        has rejected the request."
        PRD: "**Body referential coherence.** Cross-resource claims in the
        payload must hold: hour logging references a placement owned by the
        acting volunteer (`ERR_PLACEMENT_VOLUNTEER_MISMATCH`), and a
        placement-linked check-in requires that the placement belong to the
        check-in's volunteer (`ERR_PLACEMENT_VOLUNTEER_MISMATCH`) and that the
        placement's opportunity be hosted at the campus named in the payload
        (`ERR_PLACEMENT_CAMPUS_MISMATCH`)."
        PRD: "**Temporal windows**, evaluated in endpoint order: the hour-entry
        `worked_date` must fall inside the placement's opportunity window
        (`ERR_HOURS_OUTSIDE_PLACEMENT_WINDOW`); a placement-linked check-in
        must occur inside the check-in window (`ERR_OUTSIDE_CHECKIN_WINDOW`)"

        Design: Difficulty/priority_pair_validation_conflict/hour_entry_referential_beats_temporal
        """
        campus, placement, _, intruder = self._two_volunteer_setup()

        # 18:00 is past ends_at (17:00); the foreign placement fails the
        # earlier referential stage.
        set_clock("2026-08-10T18:00:00Z")
        resp = api.create_check_in(
            {"campus_id": campus["id"], "placement_id": placement["id"]},
            make_volunteer_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_PLACEMENT_VOLUNTEER_MISMATCH)

        _, meta = validate_paginated(api.list_check_ins(
            DC, params={"volunteer_id": intruder["id"]}))
        assert meta["total_count"] == 0


class TestCheckOut:
    def test_checkout_closed_checkin_rejected(self, api):
        """PRD: "Checking out moves a visit from `OPEN` to `CLOSED`; acting on
        a visit that is not `OPEN` is rejected with
        `ERR_CHECKIN_INVALID_STATE`. The server stamps `checked_out_at` from
        the logical clock and records a `close_reason`: `SELF` when the owning
        volunteer checks out, `ADMIN` when a `CampusAdmin` or
        `DistrictCoordinator` does it."

        Design: Corner/state_machines/checkout_closed_checkin_rejected
        """
        recruited = create_active_volunteer("Walkin Will", "will@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()

        set_clock("2026-08-05T09:00:00Z")
        visit = check_in_volunteer(campus["id"], vid)
        closed = validate_success(api.check_out(
            visit["id"], make_volunteer_headers(vid)), 200)
        assert closed["status"] == "CLOSED"
        assert closed["close_reason"] == "SELF"

        second = api.check_out(visit["id"], make_volunteer_headers(vid))
        validate_error(second, ApiErrorId.ERR_CHECKIN_INVALID_STATE)

        still = get_success_data(api.get_check_in(visit["id"], DC))
        assert still["status"] == "CLOSED"
        assert still["close_reason"] == "SELF"


class TestBadgeIssuance:
    def test_badge_code_sequencing_and_daily_reset(self, api):
        """PRD: "The sequence number for a new check-in is one plus the count
        of existing check-ins at the same campus on the same UTC day, in any
        status, with equal timestamps ordered by `created_at` ascending; the
        sequence resets each day and is scoped per campus."
        PRD: "The resulting `badge_code` is the campus's `badge_prefix`, a
        hyphen, and the sequence number zero-padded to four digits — the third
        check-in of the day at a campus with prefix LNC receives LNC-0003."

        Design: Corner/calculations/badge_code_sequencing_and_daily_reset
        """
        module = create_orient_module()
        campus = create_lincoln_campus()
        v1 = create_active_volunteer("Badge One", "b1@x.com", "SUPERVISED",
                                     module=module)["volunteer"]
        v2 = create_active_volunteer("Badge Two", "b2@x.com", "SUPERVISED",
                                     module=module)["volunteer"]

        set_clock("2026-08-10T09:00:00Z")
        first = check_in_volunteer(campus["id"], v1["id"])
        second = check_in_volunteer(campus["id"], v2["id"])
        assert first["badge_code"] == "LNC-0001"
        assert second["badge_code"] == "LNC-0002"

        check_out_volunteer(first["id"], v1["id"])
        check_out_volunteer(second["id"], v2["id"])

        set_clock("2026-08-11T09:00:00Z")
        next_day = check_in_volunteer(campus["id"], v1["id"])
        assert next_day["badge_code"] == "LNC-0001", (
            "The badge sequence resets each UTC day")
