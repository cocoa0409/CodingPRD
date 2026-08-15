"""Official certification gates, double-booking interval semantics, deck
coverage at event start, and assignment release."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_entry,
    add_event,
    add_official,
    add_swimmer,
    add_team,
    confirm_assignment,
    create_meet,
    create_open_meet,
    get_success_data,
    propose_assignment,
    seed_meet,
    setup_in_progress_event,
    start_event,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


def _three_window_meet(api, meet_name="OV1"):
    """Meet with events A [540,570), B [570,600), C [555,585) on one session."""
    meet = create_meet(meet_name=meet_name)
    ev_a = add_event(meet["id"], event_number=1, stroke="FREESTYLE",
                     scheduled_start_minute=540, scheduled_end_minute=570)
    ev_b = add_event(meet["id"], event_number=2, stroke="BACKSTROKE",
                     scheduled_start_minute=570, scheduled_end_minute=600)
    ev_c = add_event(meet["id"], event_number=3, gender="F",
                     stroke="FREESTYLE",
                     scheduled_start_minute=555, scheduled_end_minute=585)
    return meet, ev_a, ev_b, ev_c


class TestCertificationValidity:
    def test_certification_expiry_equality_boundary(self, api):
        """PRD §3.5: "the official's `certifications` must contain the proposed
        `role_on_deck`, and `certification_expires_on` must fall on or after
        the event's `session_date` — a certification expiring exactly on the
        session date remains valid — with failures rejected as
        `ERR_CERTIFICATION_INVALID`."

        Design: Corner/validations/certification_expiry_equality_boundary
        """
        meet = create_meet(meet_name="CE1")
        event = add_event(meet["id"])  # session_date 2026-08-15
        off_ok = add_official(meet["id"], full_name="Ref Ok",
                              lsc_membership_id="LSC-ROK",
                              certifications=["REFEREE"],
                              certification_expires_on="2026-08-15")
        off_ex = add_official(meet["id"], full_name="Ref Ex",
                              lsc_membership_id="LSC-REX",
                              certifications=["REFEREE"],
                              certification_expires_on="2026-08-14")
        ok = validate_success(
            api.create_official_assignment(
                event["id"], {"official_id": off_ok["id"],
                              "role_on_deck": "REFEREE"}, DIRECTOR),
            expected_status=201)
        assert ok["status"] == "PROPOSED", \
            "expiry exactly on the session date remains valid"
        resp = api.create_official_assignment(
            event["id"], {"official_id": off_ex["id"],
                          "role_on_deck": "REFEREE"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INVALID)


class TestCertificationVsConflictPriority:
    """Difficulty pair: certification (pipeline tier 7) masks double-booking
    (tier 13) when one proposal violates both."""

    def _setup(self, api):
        meet = create_meet(meet_name="PC2")
        ev_a = add_event(meet["id"], event_number=1, stroke="FREESTYLE",
                         scheduled_start_minute=540, scheduled_end_minute=570)
        ev_b = add_event(meet["id"], event_number=2, stroke="BACKSTROKE",
                         scheduled_start_minute=555, scheduled_end_minute=585)
        off_x = add_official(meet["id"], full_name="Off X",
                             lsc_membership_id="LSC-X1",
                             certifications=["STARTER"])
        oa_x = propose_assignment(ev_a["id"], off_x["id"], "STARTER")
        confirm_assignment(oa_x["id"], off_x["id"])
        return off_x, ev_b

    def test_dual_violation_reports_certification(self, api):
        """PRD §2.10: "7. **Official certification** — deck-assignment proposals
        (`ERR_CERTIFICATION_INVALID`)" precedes "13. **Official
        double-booking** — overlapping deck assignments
        (`ERR_OFFICIAL_ASSIGNMENT_CONFLICT`)", and "A request failing two
        checks always reports the earlier tier's error."

        Design: Difficulty/priority_pair_validation_conflict/assignment_safety_vs_constraint_priority
        """
        off_x, ev_b = self._setup(api)
        # off_x lacks STROKE_TURN_JUDGE certification AND [555,585) overlaps
        # the CONFIRMED [540,570): both tiers fail, tier 7 must surface.
        resp = api.create_official_assignment(
            ev_b["id"], {"official_id": off_x["id"],
                         "role_on_deck": "STROKE_TURN_JUDGE"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INVALID)

    def test_missing_certification_alone_rejected(self, api):
        """PRD §3.5: "the official's `certifications` must contain the proposed
        `role_on_deck`, and `certification_expires_on` must fall on or after
        the event's `session_date` — a certification expiring exactly on the
        session date remains valid — with failures rejected as
        `ERR_CERTIFICATION_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/assignment_safety_vs_constraint_priority
        """
        meet = create_meet(meet_name="PC2b")
        ev_a = add_event(meet["id"], event_number=1, stroke="FREESTYLE",
                         scheduled_start_minute=540, scheduled_end_minute=570)
        ev_far = add_event(meet["id"], event_number=3, stroke="BUTTERFLY",
                           scheduled_start_minute=660, scheduled_end_minute=690)
        off_x = add_official(meet["id"], full_name="Off X",
                             lsc_membership_id="LSC-X1",
                             certifications=["STARTER"])
        oa_x = propose_assignment(ev_a["id"], off_x["id"], "STARTER")
        confirm_assignment(oa_x["id"], off_x["id"])
        # Non-overlapping window: only the certification tier can fail.
        resp = api.create_official_assignment(
            ev_far["id"], {"official_id": off_x["id"],
                           "role_on_deck": "STROKE_TURN_JUDGE"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INVALID)


class TestOfficialDoubleBooking:
    """Difficulty pair: half-open interval semantics — adjacency is lawful,
    genuine overlap is rejected."""

    def test_adjacent_assignments_allowed(self, api):
        """PRD §3.5: "Because each interval excludes its own end minute,
        back-to-back assignments whose windows merely touch — one ending
        exactly when the next begins — are lawful".

        Design: Difficulty/resource_temporal_overlap/official_half_open_adjacency_vs_overlap
        """
        _meet, ev_a, ev_b, _ev_c = _three_window_meet(api)
        off_r = add_official(_meet["id"], full_name="Ref R",
                             lsc_membership_id="LSC-R1",
                             certifications=["REFEREE"])
        oa_a = propose_assignment(ev_a["id"], off_r["id"], "REFEREE")
        confirm_assignment(oa_a["id"], off_r["id"], as_referee=True)
        # [570,600) begins exactly when the CONFIRMED [540,570) ends.
        oa_b = propose_assignment(ev_b["id"], off_r["id"], "REFEREE")
        confirmed = confirm_assignment(oa_b["id"], off_r["id"],
                                       as_referee=True)
        assert confirmed["status"] == "CONFIRMED", \
            "end == start adjacency is allowed (half-open intervals)"

    def test_overlapping_assignment_rejected(self, api):
        """PRD §3.5: "while genuine overlaps fail with
        `ERR_OFFICIAL_ASSIGNMENT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/official_half_open_adjacency_vs_overlap
        """
        meet, ev_a, _ev_b, ev_c = _three_window_meet(api, meet_name="OV1b")
        off_r = add_official(meet["id"], full_name="Ref R",
                             lsc_membership_id="LSC-R1",
                             certifications=["REFEREE"])
        oa_a = propose_assignment(ev_a["id"], off_r["id"], "REFEREE")
        confirm_assignment(oa_a["id"], off_r["id"], as_referee=True)
        # [555,585) genuinely overlaps the CONFIRMED [540,570).
        resp = api.create_official_assignment(
            ev_c["id"], {"official_id": off_r["id"], "role_on_deck": "REFEREE"},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OFFICIAL_ASSIGNMENT_CONFLICT)


class TestDeckCoverageGate:
    """Difficulty pair: SwimEvent x OfficialAssignment — event start reads the
    confirmation state of another entity."""

    def _setup_proposed_only(self, api, meet_name="XD2"):
        """Meet SEEDED with one verified entry; coverage PROPOSED only."""
        meet = create_open_meet(meet_name=meet_name)
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        verify_entry(entry["id"])
        referee = add_official(meet["id"], full_name="Ref R",
                               lsc_membership_id="LSC-R1",
                               certifications=["REFEREE"])
        judge = add_official(meet["id"], full_name="Jud J",
                             lsc_membership_id="LSC-J1",
                             certifications=["STROKE_TURN_JUDGE"])
        oa_ref = propose_assignment(event["id"], referee["id"], "REFEREE")
        oa_jud = propose_assignment(event["id"], judge["id"],
                                    "STROKE_TURN_JUDGE")
        seed_meet(meet["id"])
        return meet, event, referee, judge, oa_ref, oa_jud

    def test_proposed_coverage_is_not_coverage(self, api):
        """PRD §3.7: "deck coverage must be complete — at least one `CONFIRMED`
        assignment with `role_on_deck` `REFEREE` and at least one `CONFIRMED`
        assignment with `role_on_deck` `STROKE_TURN_JUDGE` must exist for the
        event, failing which the start is refused with
        `ERR_OFFICIAL_COVERAGE_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/event_start_gated_by_official_coverage
        """
        _meet, event, _r, _j, _oa_r, _oa_j = self._setup_proposed_only(api)
        resp = api.start_event(event["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OFFICIAL_COVERAGE_INCOMPLETE)

    def test_start_succeeds_once_coverage_confirmed(self, api):
        """PRD §3.7: "deck coverage must be complete — at least one `CONFIRMED`
        assignment with `role_on_deck` `REFEREE` and at least one `CONFIRMED`
        assignment with `role_on_deck` `STROKE_TURN_JUDGE` must exist for the
        event". PRD §3.7: "Starting a race is the director's call and moves the
        event from `SEEDED` to `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/event_start_gated_by_official_coverage
        """
        _meet, event, referee, judge, oa_ref, oa_jud = \
            self._setup_proposed_only(api, meet_name="XD2b")
        confirm_assignment(oa_ref["id"], referee["id"], as_referee=True)
        confirm_assignment(oa_jud["id"], judge["id"])
        started = validate_success(api.start_event(event["id"], DIRECTOR))
        assert started["status"] == "IN_PROGRESS"


class TestAssignmentRelease:
    def test_release_confirmed_assignment_blocked_after_start(self, api):
        """PRD §3.5: "a `CONFIRMED` assignment may be released only while its
        event stands in `PENDING` or `SEEDED`; once the event is underway,
        release fails with `ERR_EVENT_ALREADY_UNDERWAY`."

        Design: Corner/errors/release_confirmed_assignment_blocked_after_start
        """
        workspace = setup_in_progress_event(meet_name="RE13")
        oa_jud = workspace["coverage"]["oa_judge"]
        resp = api.release_official_assignment(oa_jud["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EVENT_ALREADY_UNDERWAY)
