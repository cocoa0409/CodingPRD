"""Chaperones: background-check lifecycle, the expiry sweep, flag cascades,
assignment ownership, uniqueness constraints, and cross-trip overlap rules."""
from test_helpers import (
    ApiErrorId,
    add_cleared_chaperone_to_trip,
    advance_check,
    assert_same_instant,
    create_chaperone,
    create_cleared_chaperone,
    create_confirmed_registration,
    create_program,
    create_trip,
    get_trip,
    initiate_background_check,
    make_chaperone_headers,
    make_director_headers,
    propose_assignment,
    respond_assignment,
    set_clock,
    setup_program_with_open_trip,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = make_director_headers()


class TestBackgroundCheckLifecycle:
    def test_background_check_lifecycle_and_uniqueness(self, api):
        """PRD §3.8: "Initiating a background check — optionally with a
        `vendor_reference` — requires that the chaperone have no other check in
        `INITIATED` or `SCREENING` (`ERR_SCREENING_IN_PROGRESS_EXISTS`,
        HTTP 409); the new check is `INITIATED`. Advancing with `to_status` of
        `SCREENING` requires the check to be `INITIATED`; from `SCREENING`, the
        director advances either to `CLEARED` or to `FLAGGED` — any other
        reachability is `ERR_CHECK_STATE_FORBIDS_ACTION`". "A `CLEARED` outcome
        stamps `cleared_at` from the logical clock and computes `expires_at` as
        exactly 730 days after `cleared_at`".

        Design: Corner/state_machines/background_check_lifecycle_and_uniqueness
        """
        program = create_program()
        chaperone = create_chaperone(program["id"])

        check = initiate_background_check(chaperone["id"])
        assert check["status"] == "INITIATED"

        # INITIATED cannot jump straight to CLEARED.
        e_skip = api.advance_background_check(check["id"],
                                              {"to_status": "CLEARED"},
                                              DIRECTOR)
        validate_error(e_skip, ApiErrorId.ERR_CHECK_STATE_FORBIDS_ACTION, 409)

        # A second check while one is INITIATED, then while SCREENING.
        e_dup1 = api.create_background_check(chaperone["id"], DIRECTOR)
        validate_error(e_dup1, ApiErrorId.ERR_SCREENING_IN_PROGRESS_EXISTS, 409)
        advance_check(check["id"], "SCREENING")
        e_dup2 = api.create_background_check(chaperone["id"], DIRECTOR)
        validate_error(e_dup2, ApiErrorId.ERR_SCREENING_IN_PROGRESS_EXISTS, 409)

        cleared = advance_check(check["id"], "CLEARED", vendor_reference="v-1")
        assert cleared["status"] == "CLEARED"
        # The clock still reads the default 2026-08-01T00:00:00Z.
        assert_same_instant(cleared["cleared_at"], "2026-08-01T00:00:00Z",
                            "cleared_at")
        assert_same_instant(cleared["expires_at"], "2028-07-31T00:00:00Z",
                            "expires_at = cleared_at + 730 days")

        # No advance transitions exist out of CLEARED.
        e_term = api.advance_background_check(check["id"],
                                              {"to_status": "SCREENING"},
                                              DIRECTOR)
        validate_error(e_term, ApiErrorId.ERR_CHECK_STATE_FORBIDS_ACTION, 409)

        # A CLEARED check is not in {INITIATED, SCREENING}: renewal is legal.
        renewal = api.create_background_check(chaperone["id"], DIRECTOR,
                                              {"vendor_reference": "renewal"})
        assert validate_success(renewal, 201)["status"] == "INITIATED"


class TestScreeningExpirySweep:
    def test_screening_expiry_sweep_at_exact_expiry_cascades(self, api):
        """PRD §3.8: "When the logical clock advances to or past a `CLEARED`
        check's `expires_at`, the expiry sweep moves the check to `EXPIRED`
        (terminal) and cascades: every assignment of that chaperone in
        `PROPOSED` or `CONFIRMED` whose trip's end instant — midnight UTC on the
        day after the trip's `end_date` — is at or after the `expires_at` is
        removed with `removal_reason` of `AUTO_SCREENING`; the affected trips
        recompute cleared counts and ratio compliance".

        Design: Corner/state_machines/screening_expiry_sweep_at_exact_expiry_cascades
        """
        program = create_program()
        # Trip end instant == 2028-07-31T00:00:00Z, exactly the check's
        # expires_at ("at or after" is boundary-inclusive on both sides).
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           start_date="2028-07-28", end_date="2028-07-30",
                           emergency_protocol_text="")
        chaperone, check, assignment = add_cleared_chaperone_to_trip(
            trip["id"], program["id"])
        assert assignment["status"] == "CONFIRMED"

        # One day before expiry: the sweep has not fired.
        set_clock("2028-07-30T00:00:00Z")
        checks, _ = validate_paginated(
            api.list_background_checks(chaperone["id"], DIRECTOR))
        assert checks[0]["status"] == "CLEARED"

        # At exactly expires_at (>= boundary): EXPIRED with the cascade.
        set_clock("2028-07-31T00:00:00Z")
        checks_after, _ = validate_paginated(
            api.list_background_checks(chaperone["id"], DIRECTOR))
        assert checks_after[0]["status"] == "EXPIRED"

        asg_after = api.get_chaperone_assignment(assignment["id"], DIRECTOR) \
            .json()["data"]
        assert asg_after["status"] == "REMOVED"
        assert asg_after["removal_reason"] == "AUTO_SCREENING"

        trip_after = get_trip(trip["id"])
        assert trip_after["cleared_chaperone_count"] == 0


class TestScreeningFlagCascade:
    def _setup_two_cleared_assignments(self, api):
        """Trip Gamma (ratio 1, OUT_OF_STATE) with 2 CONFIRMED registrations and
        2 CONFIRMED cleared chaperones: compliant at 2 >= ceil(2/1)."""
        program, trip = setup_program_with_open_trip(
            name="Gamma", destination_name="Ozarks",
            destination_type="OUT_OF_STATE", capacity_youth=10,
            base_cost_cents=80000, deposit_cents=50000, chaperone_ratio=1)
        chap1, _, asg1 = add_cleared_chaperone_to_trip(
            trip["id"], program["id"], role="LEAD", first_name="Ada",
            last_name="One", email="a1@x.org")
        chap2, _, asg2 = add_cleared_chaperone_to_trip(
            trip["id"], program["id"], role="SUPPORT", first_name="Bob",
            last_name="Two", email="b2@x.org")
        for i in (1, 2):
            create_confirmed_registration(
                trip["id"], guardian_user_id=f"guardian-{i}",
                participant_overrides={"family_key": f"fam-{i}"},
                registration_overrides={"insurance_tier": "DOMESTIC"})
        return program, trip, chap1, asg1, chap2, asg2

    def test_flagged_check_removes_assignments_with_auto_screening(self, api):
        """PRD §3.8: "A `FLAGGED` outcome cascades two hops: every assignment of
        this chaperone in `PROPOSED` or `CONFIRMED` is removed with
        `removal_reason` of `AUTO_SCREENING`, and for each affected trip the
        `cleared_chaperone_count` is recomputed and `ratio_compliant`
        re-evaluated". "The `AUTO_SCREENING` value appears only on system
        removals."

        Design: Difficulty/transitive_cascade/screening_flag_cascade_assignment_removal_ratio_flip
        """
        _, trip, _, asg1, chap2, asg2 = self._setup_two_cleared_assignments(api)
        pre = get_trip(trip["id"])
        assert pre["cleared_chaperone_count"] == 2
        assert pre["ratio_compliant"] is True

        # Renewal check on chaperone 2 (CLEARED checks do not block a new one).
        check2 = initiate_background_check(chap2["id"], "renewal-7")
        advance_check(check2["id"], "SCREENING")
        flagged = advance_check(check2["id"], "FLAGGED")
        assert flagged["status"] == "FLAGGED"

        asg2_after = api.get_chaperone_assignment(asg2["id"], DIRECTOR) \
            .json()["data"]
        assert asg2_after["status"] == "REMOVED"
        assert asg2_after["removal_reason"] == "AUTO_SCREENING"

    def test_flag_cascade_flips_ratio_compliance_and_spares_others(self, api):
        """PRD §3.8: "`required_cleared_chaperones` is `confirmed_youth_count`
        divided by the trip's `chaperone_ratio`, rounded up to a whole number ...
        and `ratio_compliant` holds when the cleared count is at least the
        requirement. This rule is recomputed on every mutation touching the
        confirmed-youth count, the ratio, the confirmed-assignment set, or the
        cleared-check set".

        Design: Difficulty/transitive_cascade/screening_flag_cascade_assignment_removal_ratio_flip
        """
        _, trip, _, asg1, chap2, asg2 = self._setup_two_cleared_assignments(api)
        check2 = initiate_background_check(chap2["id"], "renewal-7")
        advance_check(check2["id"], "SCREENING")
        advance_check(check2["id"], "FLAGGED")

        trip_after = get_trip(trip["id"])
        assert trip_after["cleared_chaperone_count"] == 1
        assert trip_after["required_cleared_chaperones"] == 2, (
            "requirement stays ceil(2/1) == 2")
        assert trip_after["ratio_compliant"] is False

        asg1_after = api.get_chaperone_assignment(asg1["id"], DIRECTOR) \
            .json()["data"]
        assert asg1_after["status"] == "CONFIRMED", (
            "the cascade touches only the flagged chaperone's assignments")


class TestChaperoneRespondOwnership:
    def test_chaperone_respond_ownership_and_terminal_lockdown(self, api):
        """PRD §3.8: "The assigned chaperone — and only that chaperone, matched
        by `X-User-ID` against the assignment's `chaperone_id`
        (`ERR_NOT_RESOURCE_OWNER`) — responds: `decision` of `ACCEPT` confirms
        the assignment ... `decision` of `DECLINE` moves it to `DECLINED`,
        terminal. Responding to an assignment not `PROPOSED` is
        `ERR_ASSIGNMENT_STATE_FORBIDS_ACTION`."

        Design: Corner/rbac/chaperone_respond_ownership_and_terminal_lockdown
        """
        program = create_program()
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           start_date="2027-06-15", end_date="2027-06-16",
                           emergency_protocol_text="")
        chap_a, _ = create_cleared_chaperone(
            program["id"], first_name="Ada", last_name="A", email="a@x.org")
        chap_b = create_chaperone(program["id"], first_name="Bob",
                                  last_name="B", email="b@x.org")
        assignment = propose_assignment(trip["id"], chap_a["id"], "LEAD")

        # B cannot answer A's assignment.
        e_own = api.respond_chaperone_assignment(
            assignment["id"], {"decision": "ACCEPT"},
            make_chaperone_headers(chap_b["id"]))
        validate_error(e_own, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        declined = respond_assignment(assignment["id"], chap_a["id"],
                                      "DECLINE")
        assert declined["status"] == "DECLINED"

        # DECLINED is terminal.
        e_term = api.respond_chaperone_assignment(
            assignment["id"], {"decision": "ACCEPT"},
            make_chaperone_headers(chap_a["id"]))
        validate_error(e_term, ApiErrorId.ERR_ASSIGNMENT_STATE_FORBIDS_ACTION,
                       409)


class TestAssignmentUniqueness:
    def test_duplicate_lead_and_duplicate_assignment_constraints(self, api):
        """PRD §3.8: "at most one assignment with `role` of `LEAD` per trip among
        `PROPOSED` and `CONFIRMED` (`ERR_DUPLICATE_LEAD_CHAPERONE`, HTTP 409); no
        other non-terminal assignment for the same (trip, chaperone) pair
        (`ERR_DUPLICATE_ASSIGNMENT`, HTTP 409)".

        Design: Corner/validations/duplicate_lead_and_duplicate_assignment_constraints
        """
        program = create_program()
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           start_date="2027-06-15", end_date="2027-06-16",
                           emergency_protocol_text="")
        chap_a, _ = create_cleared_chaperone(program["id"], first_name="Ada",
                                             last_name="A", email="a@x.org")
        chap_b, _ = create_cleared_chaperone(program["id"], first_name="Bob",
                                             last_name="B", email="b@x.org")
        propose_assignment(trip["id"], chap_a["id"], "LEAD")

        e_lead = api.create_chaperone_assignment(
            {"trip_id": trip["id"], "chaperone_id": chap_b["id"],
             "role": "LEAD"}, DIRECTOR)
        validate_error(e_lead, ApiErrorId.ERR_DUPLICATE_LEAD_CHAPERONE, 409)

        e_dup = api.create_chaperone_assignment(
            {"trip_id": trip["id"], "chaperone_id": chap_a["id"],
             "role": "SUPPORT"}, DIRECTOR)
        validate_error(e_dup, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT, 409)

        ok = api.create_chaperone_assignment(
            {"trip_id": trip["id"], "chaperone_id": chap_b["id"],
             "role": "SUPPORT"}, DIRECTOR)
        assert validate_success(ok, 201)["status"] == "PROPOSED"


class TestChaperoneTripOverlap:
    def _setup_three_trips_with_confirmed_lead(self, api):
        """Chaperone CONFIRMED on T1 2027-06-15..06-25; T2 shares the boundary
        date 06-25; T3 starts the day after T1 ends."""
        program = create_program()
        common = {"destination_type": "OUT_OF_STATE", "capacity_youth": 10,
                  "base_cost_cents": 80000, "deposit_cents": 50000,
                  "chaperone_ratio": 5}
        t1 = create_trip(program["id"], name="T1", start_date="2027-06-15",
                         end_date="2027-06-25", **common)
        t2 = create_trip(program["id"], name="T2", start_date="2027-06-25",
                         end_date="2027-06-30", **common)
        t3 = create_trip(program["id"], name="T3", start_date="2027-06-26",
                         end_date="2027-06-30", **common)
        chaperone, _ = create_cleared_chaperone(program["id"])
        asg1 = propose_assignment(t1["id"], chaperone["id"], "LEAD")
        asg1 = respond_assignment(asg1["id"], chaperone["id"], "ACCEPT")
        return chaperone, asg1, t1, t2, t3

    def test_shared_boundary_date_conflicts(self, api):
        """PRD §3.8: "if the chaperone is already `PROPOSED` or `CONFIRMED` on a
        trip whose closed date interval (start date through end date, inclusive
        of both boundary dates) intersects this trip's, the proposal is
        `ERR_CHAPERONE_TRIP_OVERLAP` (HTTP 409), and note that merely sharing a
        boundary date does conflict."

        Design: Difficulty/resource_temporal_overlap/chaperone_trip_overlap_closed_interval_shared_boundary_conflicts
        """
        chaperone, asg1, _, t2, _ = \
            self._setup_three_trips_with_confirmed_lead(api)
        resp = api.create_chaperone_assignment(
            {"trip_id": t2["id"], "chaperone_id": chaperone["id"],
             "role": "LEAD"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CHAPERONE_TRIP_OVERLAP, 409)

    def test_day_after_start_is_legal_and_prior_assignment_untouched(self, api):
        """PRD §3.8: "no overlap with another trip — if the chaperone is already
        `PROPOSED` or `CONFIRMED` on a trip whose closed date interval (start
        date through end date, inclusive of both boundary dates) intersects this
        trip's, the proposal is `ERR_CHAPERONE_TRIP_OVERLAP` (HTTP 409)" —
        [06-26, 06-30] shares no date with [06-15, 06-25].

        Design: Difficulty/resource_temporal_overlap/chaperone_trip_overlap_closed_interval_shared_boundary_conflicts
        """
        chaperone, asg1, _, _, t3 = \
            self._setup_three_trips_with_confirmed_lead(api)
        created = api.create_chaperone_assignment(
            {"trip_id": t3["id"], "chaperone_id": chaperone["id"],
             "role": "LEAD"}, DIRECTOR)
        assert validate_success(created, 201)["status"] == "PROPOSED"

        asg1_after = api.get_chaperone_assignment(asg1["id"], DIRECTOR) \
            .json()["data"]
        assert asg1_after["status"] == "CONFIRMED", (
            "the rejected overlap attempt mutated nothing")


class TestScreeningSafetyBeatsOverlap:
    def _setup_expiring_screening_with_overlap(self, api):
        """Clock rewound so a fresh CLEARED check expires 2027-06-28: valid
        through T1 (end instant 2027-06-26) but not T2 (end instant
        2027-07-01); T1 and T2 overlap on closed dates 06-20..06-25."""
        set_clock("2025-06-28T00:00:00Z")
        program = create_program(name="Youth 2025", ministry_year="2025-2026")
        common = {"destination_type": "OUT_OF_STATE", "capacity_youth": 10,
                  "base_cost_cents": 80000, "deposit_cents": 50000,
                  "chaperone_ratio": 5}
        t1 = create_trip(program["id"], name="T1", start_date="2027-06-15",
                         end_date="2027-06-25", **common)
        t2 = create_trip(program["id"], name="T2", start_date="2027-06-20",
                         end_date="2027-06-30", **common)
        chaperone, check = create_cleared_chaperone(program["id"])
        asg1 = propose_assignment(t1["id"], chaperone["id"], "LEAD")
        respond_assignment(asg1["id"], chaperone["id"], "ACCEPT")
        return chaperone, check, asg1, t1, t2

    def test_screening_error_precedes_overlap_error(self, api):
        """PRD §3.8: "The safety gate runs before the constraint gates: the
        chaperone must hold a `CLEARED` background check whose `expires_at` is at
        or after the trip's end instant — valid *through* the trip, boundary
        inclusive — else `ERR_SCREENING_NOT_VALID_THROUGH_TRIP` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_assignment_screening_beats_overlap
        """
        chaperone, check, _, _, t2 = \
            self._setup_expiring_screening_with_overlap(api)
        assert_same_instant(check["expires_at"], "2027-06-28T00:00:00Z",
                            "expires_at (cleared 2025-06-28 + 730 days)")

        # T2 needs validity through 2027-07-01T00:00:00Z; the screening lapses
        # 2027-06-28 — and T2 also overlaps T1. Safety (priority 8) wins over
        # the constraint (priority 11).
        resp = api.create_chaperone_assignment(
            {"trip_id": t2["id"], "chaperone_id": chaperone["id"],
             "role": "SUPPORT"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_VALID_THROUGH_TRIP,
                       422)

    def test_rejected_proposal_creates_no_assignment_row(self, api):
        """PRD §3.8: "A valid proposal is `PROPOSED`." — a proposal rejected by
        the safety gate leaves no assignment behind, and the chaperone's
        existing CONFIRMED assignment on T1 is untouched.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_assignment_screening_beats_overlap
        """
        chaperone, _, asg1, _, t2 = \
            self._setup_expiring_screening_with_overlap(api)
        api.create_chaperone_assignment(
            {"trip_id": t2["id"], "chaperone_id": chaperone["id"],
             "role": "SUPPORT"}, DIRECTOR)

        _, meta = validate_paginated(
            api.list_chaperone_assignments(DIRECTOR,
                                           params={"trip_id": t2["id"]}))
        assert meta["total_count"] == 0

        asg1_after = api.get_chaperone_assignment(asg1["id"], DIRECTOR) \
            .json()["data"]
        assert asg1_after["status"] == "CONFIRMED"
