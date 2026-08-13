"""Crisis shifts and walk-in visits: claiming, OCC, rooming, dispositions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_shift,
    create_claimed_shift,
    create_counselor,
    create_crisis_shift,
    create_crisis_visit_payload,
    create_intake,
    create_queued_visit,
    create_student,
    get_episode_for_student,
    make_clinical_director_headers,
    make_counselor_headers,
    make_triage_screener_headers,
    setup_stabilized_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
CD_HEADERS = TEST_USERS["clinical_director_headers"]


class TestShiftTemporalValidity:

    def test_shift_end_before_start_rejected(self):
        """PRD section 3.7: "each names its `coverage_date` (a calendar date
        in year-month-day form), a `shift_kind` of either `WALK_IN` (daytime
        walk-in coverage) or `AFTER_HOURS` (the phone line), and the
        `starts_at` and `ends_at` bounds — the end must lie strictly after the
        start, or creation is rejected with `ERR_TEMPORAL_INVALID`."

        Design: Corner/validations/shift_end_before_start_rejected
        """
        resp = api_client.create_crisis_shift(
            {
                "coverage_date": "2026-08-05",
                "shift_kind": "WALK_IN",
                "starts_at": "2026-08-05T12:00:00Z",
                "ends_at": "2026-08-05T08:00:00Z",
            },
            CD_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID)


class TestCheckInCoverage:

    def test_checkin_without_claimed_shift_rejected(self):
        """PRD section 3.7: "Check-in requires the target shift to be
        `CLAIMED`; without claimed coverage the check-in is rejected with
        `ERR_NO_CRISIS_COVERAGE`."

        Design: Corner/validations/crisis_checkin_without_claimed_shift_rejected
        """
        counselor = create_counselor(license_id="LIC-V4",
                                     specialties=["CRISIS"])
        shift = create_crisis_shift()  # UNCLAIMED
        student = create_student("V400", "Walkin Stud")
        resp = api_client.create_crisis_visit(
            create_crisis_visit_payload(student["id"], shift["id"],
                                        presenting_risk_band="HIGH"),
            make_triage_screener_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_CRISIS_COVERAGE)

    def test_critical_intake_without_coverage_rejected(self):
        """PRD section 3.3: "A `CRITICAL` band routes to `CRISIS_PROTOCOL`,
        but only when crisis coverage actually exists: there must be a walk-in
        shift (`WALK_IN` kind) in `CLAIMED` status whose window from
        `starts_at` up to (but not including) `ends_at` contains the current
        logical clock. Without such coverage the completion fails with
        `ERR_NO_CRISIS_COVERAGE` and the disposition remains `PENDING`."

        Design: Corner/errors/error_no_crisis_coverage_on_critical_intake
        """
        counselor = create_counselor(license_id="LIC-R5",
                                     specialties=["TRIAGE"])
        student = create_student("R500", "Crit Nocover")
        intake = create_intake(student["id"], counselor["id"],
                               phq9=15, gad7=5, attempt=True)  # 60 -> CRITICAL
        assert intake["risk_band"] == "CRITICAL"
        resp = api_client.complete_intake_assessment(
            intake["id"], {}, make_triage_screener_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_CRISIS_COVERAGE)
        reread = validate_success(api_client.get_intake_assessment(
            intake["id"], make_triage_screener_headers(counselor["id"])))
        assert reread["disposition"] == "PENDING", \
            "a failed crisis routing leaves the disposition PENDING"


class TestShiftClaimOcc:

    def test_claim_with_correct_version_succeeds_and_bumps(self):
        """PRD section 3.7: "Claiming is a counselor action guarded by
        optimistic concurrency: the payload's `expected_crisis_shift_version`
        must match the shift's current `version` or the claim is rejected with
        `ERR_STALE_VERSION`."
        PRD section 2.4: "The `version` field is a system-managed integer that
        increments by one on every mutation of the resource and underpins
        optimistic concurrency control."

        Design: Corner/complexity_layers/occ_correct_version_succeeds_and_bumps
        """
        counselor = create_counselor(license_id="LIC-L1",
                                     specialties=["CRISIS"])
        shift = create_crisis_shift(shift_kind="AFTER_HOURS",
                                    starts_at="2026-08-01T20:00:00Z",
                                    ends_at="2026-08-02T02:00:00Z")
        claimed = validate_success(api_client.claim_crisis_shift(
            shift["id"],
            {"expected_crisis_shift_version": shift["version"]},
            make_counselor_headers(counselor["id"])))
        assert claimed["status"] == "CLAIMED"
        assert claimed["claimed_by_id"] == counselor["id"]
        assert claimed["version"] == shift["version"] + 1, \
            "a successful claim increments the version by exactly one"

    def test_claim_with_stale_version_rejected(self):
        """PRD section 2.7: "If the shift's current `version` no longer
        matches — because another write, such as a claim or a release,
        advanced it after the client read the shift — the claim is rejected
        with `ERR_STALE_VERSION`."

        Design: Corner/errors/error_stale_version_on_shift_claim
        """
        c_a = create_counselor(license_id="LIC-R3A", specialties=["CRISIS"])
        c_b = create_counselor(license_id="LIC-R3B", specialties=["CRISIS"])
        shift = create_crisis_shift()
        stale_version = shift["version"]
        claim_shift(shift["id"], c_a["id"], stale_version)
        validate_success(api_client.release_crisis_shift(
            shift["id"], make_counselor_headers(c_a["id"])))
        resp = api_client.claim_crisis_shift(
            shift["id"], {"expected_crisis_shift_version": stale_version},
            make_counselor_headers(c_b["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        current = validate_success(api_client.get_crisis_shift(
            shift["id"], make_counselor_headers(c_b["id"])))
        assert current["status"] == "RELEASED"
        assert current["claimed_by_id"] is None


class TestShiftClaimOverlap:

    def test_claim_overlapping_shift_rejected(self):
        """PRD section 3.7: "The claimant must be active, and the claimant
        must not already hold another claimed shift whose window overlaps this
        one — overlapping claims are rejected with `ERR_SCHEDULE_CONFLICT`."

        Claimed 08:00-12:00; claiming 11:00-13:00 straddles it.

        Design: Difficulty/resource_temporal_overlap/crisis_shift_claim_overlap_aggregate_semantics
        """
        counselor = create_counselor(license_id="LIC-16",
                                     specialties=["CRISIS"])
        sh_a = create_crisis_shift(coverage_date="2026-08-02",
                                   starts_at="2026-08-02T08:00:00Z",
                                   ends_at="2026-08-02T12:00:00Z")
        sh_c = create_crisis_shift(coverage_date="2026-08-02",
                                   shift_kind="AFTER_HOURS",
                                   starts_at="2026-08-02T11:00:00Z",
                                   ends_at="2026-08-02T13:00:00Z")
        claim_shift(sh_a["id"], counselor["id"], sh_a["version"])
        resp = api_client.claim_crisis_shift(
            sh_c["id"], {"expected_crisis_shift_version": sh_c["version"]},
            make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)

    def test_claim_adjacent_shift_succeeds(self):
        """PRD section 3.7: "The claimant must be active, and the claimant
        must not already hold another claimed shift whose window overlaps this
        one — overlapping claims are rejected with `ERR_SCHEDULE_CONFLICT`."

        Claimed 08:00-12:00; claiming 12:00-16:00 touches the endpoint but
        shares no span of time, so it is legal across the counselor's claimed
        portfolio.

        Design: Difficulty/resource_temporal_overlap/crisis_shift_claim_overlap_aggregate_semantics
        """
        counselor = create_counselor(license_id="LIC-16",
                                     specialties=["CRISIS"])
        sh_a = create_crisis_shift(coverage_date="2026-08-02",
                                   starts_at="2026-08-02T08:00:00Z",
                                   ends_at="2026-08-02T12:00:00Z")
        sh_b = create_crisis_shift(coverage_date="2026-08-02",
                                   starts_at="2026-08-02T12:00:00Z",
                                   ends_at="2026-08-02T16:00:00Z")
        claim_shift(sh_a["id"], counselor["id"], sh_a["version"])
        claimed_b = claim_shift(sh_b["id"], counselor["id"], sh_b["version"])
        assert claimed_b["status"] == "CLAIMED"
        assert claimed_b["claimed_by_id"] == counselor["id"]


class TestShiftReleaseGuard:

    def test_release_blocked_while_visit_in_room(self):
        """PRD section 3.7: "A claimed shift may be released by the claiming
        counselor or the director, returning to `RELEASED` with
        `claimed_by_id` cleared — but release is blocked while any visit on
        that shift is currently `IN_ROOM`."
        PRD section 2.8: "State eligibility — the target resource must be in a
        state from which the requested transition exists, including
        terminal-state lockdown and repeat triggers (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/crisis_shift_release_blocked_while_visit_in_room
        """
        counselor = create_counselor(license_id="LIC-S9",
                                     specialties=["CRISIS"])
        shift = create_claimed_shift(counselor["id"])
        student = create_student("SS900", "Inroom Stud")
        visit = create_queued_visit(student["id"], shift["id"], "HIGH",
                                    counselor["id"])
        validate_success(api_client.room_crisis_visit(
            visit["id"], make_counselor_headers(counselor["id"])))
        resp = api_client.release_crisis_shift(
            shift["id"], make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = validate_success(api_client.get_crisis_shift(
            shift["id"], make_counselor_headers(counselor["id"])))
        assert current["status"] == "CLAIMED"


class TestRoomSerializationAndOwnership:

    def test_second_room_attempt_blocked(self):
        """PRD section 3.7: "The shift's claiming counselor moves a queued
        visit to `IN_ROOM`, and at most one visit per shift may be in the room
        at a time — a second room attempt while another visit on the same
        shift is `IN_ROOM` is rejected with `ERR_ROOM_OCCUPIED`."

        Design: Corner/state_machines/crisis_visit_room_second_visit_blocked
        """
        counselor = create_counselor(license_id="LIC-S6",
                                     specialties=["CRISIS"])
        shift = create_claimed_shift(counselor["id"])
        s_a = create_student("SS601", "V1 Stud")
        s_b = create_student("SS602", "V2 Stud")
        v1 = create_queued_visit(s_a["id"], shift["id"], "HIGH",
                                 counselor["id"])
        v2 = create_queued_visit(s_b["id"], shift["id"], "MODERATE",
                                 counselor["id"])
        c_headers = make_counselor_headers(counselor["id"])
        validate_success(api_client.room_crisis_visit(v1["id"], c_headers))
        resp = api_client.room_crisis_visit(v2["id"], c_headers)
        validate_error(resp, ApiErrorId.ERR_ROOM_OCCUPIED)
        current = validate_success(api_client.get_crisis_visit(
            v2["id"], c_headers))
        assert current["status"] == "QUEUED"

    def test_room_after_shift_release_rejected_unauthorized(self):
        """PRD section 2.1: "A `Counselor` may complete or record no-show
        determinations only on sessions whose `counselor_id` equals their own
        id, may close or reopen only episodes whose `primary_counselor_id`
        equals their own id, may room or stabilize only crisis visits attached
        to shifts they have claimed, may publish or cancel only group programs
        they facilitate, and may release only crisis shifts they personally
        claimed."
        PRD section 2.1: "Ownership violations are authorization failures —
        they are rejected with `ERR_UNAUTHORIZED` (HTTP 403), never with a
        state-transition error."

        After the claimant releases the shift, claimed_by_id is null and the
        same counselor no longer passes the ownership gate.

        Design: Difficulty/cross_entity_state_dependency/crisis_visit_room_requires_claimed_shift
        """
        counselor = create_counselor(license_id="LIC-14",
                                     specialties=["CRISIS"])
        shift = create_claimed_shift(counselor["id"])
        student = create_student("S1400", "Visit Stud")
        visit = create_queued_visit(student["id"], shift["id"], "MODERATE",
                                    counselor["id"])
        c_headers = make_counselor_headers(counselor["id"])
        validate_success(api_client.release_crisis_shift(shift["id"], c_headers))
        resp = api_client.room_crisis_visit(visit["id"], c_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        current = validate_success(api_client.get_crisis_visit(
            visit["id"], c_headers))
        assert current["status"] == "QUEUED"

    def test_room_by_non_claiming_counselor_rejected(self):
        """PRD section 2.1: "may room or stabilize only crisis visits attached
        to shifts they have claimed" and "Ownership violations are
        authorization failures — they are rejected with `ERR_UNAUTHORIZED`
        (HTTP 403), never with a state-transition error."

        The shift is CLAIMED, but by counselor A; counselor B's room attempt
        fails the ownership gate.

        Design: Difficulty/cross_entity_state_dependency/crisis_visit_room_requires_claimed_shift
        """
        c_a = create_counselor(license_id="LIC-14A", specialties=["CRISIS"])
        c_b = create_counselor(license_id="LIC-14B", specialties=["CRISIS"])
        shift = create_claimed_shift(c_a["id"])
        student = create_student("S1401", "Visit Stud Two")
        visit = create_queued_visit(student["id"], shift["id"], "HIGH",
                                    c_a["id"])
        resp = api_client.room_crisis_visit(
            visit["id"], make_counselor_headers(c_b["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        current = validate_success(api_client.get_crisis_visit(
            visit["id"], make_counselor_headers(c_a["id"])))
        assert current["status"] == "QUEUED"


class TestVisitEscalationCycle:

    def test_escalate_deescalate_cycle(self):
        """PRD section 3.7: "The claiming counselor then stabilizes the visit
        (`IN_ROOM` to `STABILIZED`); the same stabilize action also serves as
        the de-escalation loop, returning an `ESCALATED` visit to
        `STABILIZED`. Escalation itself — `STABILIZED` to `ESCALATED` — may be
        invoked by the claiming counselor or the director, and a visit may
        loop between `STABILIZED` and `ESCALATED` more than once."

        Design: Difficulty/non_linear_state_machine/crisis_visit_escalation_cycle
        """
        counselor, student, shift, visit = setup_stabilized_visit(
            counselor_license="LIC-5", student_number="S500",
            presenting_band="HIGH")
        c_headers = make_counselor_headers(counselor["id"])
        esc = validate_success(
            api_client.escalate_crisis_visit(visit["id"], c_headers))
        assert esc["status"] == "ESCALATED"
        back = validate_success(
            api_client.stabilize_crisis_visit(visit["id"], c_headers))
        assert back["status"] == "STABILIZED", "the de-escalation loop closes"
        esc2 = validate_success(
            api_client.escalate_crisis_visit(visit["id"], c_headers))
        assert esc2["status"] == "ESCALATED", "the cycle may repeat"

    def test_disposition_return_to_care_creates_open_episode(self):
        """PRD section 3.7: "`RETURN_TO_CARE`: if the student has no episode
        currently `OPEN`, the system creates one — status `OPEN`,
        `primary_counselor_id` set to the shift's claiming counselor,
        `intake_assessment_id` left null, `academic_term` set to the term of
        the currently published policy (or the literal `INTERSESSION` when
        none exists), and `session_limit` derived per §3.4 using the visit's
        `presenting_risk_band` in place of an intake band."
        PRD section 3.7: "Disposition is the terminal routing, invoked by the
        claiming counselor or the director from `STABILIZED`, with a payload
        `disposition` that must be one of `RETURN_TO_CARE`,
        `COMMUNITY_REFERRAL`, or `EMERGENCY_TRANSPORT`; any other value is
        rejected with `ERR_RISK_BAND_VIOLATION`."

        Design: Difficulty/non_linear_state_machine/crisis_visit_escalation_cycle
        """
        counselor, student, shift, visit = setup_stabilized_visit(
            counselor_license="LIC-5", student_number="S500",
            presenting_band="HIGH")
        c_headers = make_counselor_headers(counselor["id"])
        # Exercise the loop once before the terminal routing.
        validate_success(api_client.escalate_crisis_visit(visit["id"], c_headers))
        validate_success(api_client.stabilize_crisis_visit(visit["id"], c_headers))
        done = validate_success(api_client.disposition_crisis_visit(
            visit["id"], {"disposition": "RETURN_TO_CARE"}, c_headers))
        assert done["status"] == "DISPOSITIONED"
        assert done["disposition"] == "RETURN_TO_CARE"
        episode = get_episode_for_student(student["id"], counselor["id"])
        assert episode["status"] == "OPEN"
        assert episode["intake_assessment_id"] is None
        assert episode["primary_counselor_id"] == counselor["id"]
