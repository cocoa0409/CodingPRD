"""Difficulty queue: temporal overlap geometries, graduation boundary,
priority ordering, and capacity/pairing conservation (PRD §2.6, §3.6–§3.8)."""
import pytest

from test_helpers import (
    PAT_PERFECT_SCORES,
    TEST_USERS,
    ApiErrorId,
    assert_date_prefix,
    create_approved_raiser,
    create_certified_trainer,
    create_class_payload,
    create_cleared_dog,
    create_dog_payload,
    create_eligible_entry,
    create_match_ready_dog,
    make_evaluator_headers,
    propose_and_accept_match,
    setup_graduated_partnership,
    setup_in_session_enrollment,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]


class TestTrainerClassHalfOpenOverlap:
    """Difficulty/resource_temporal_overlap/trainer_class_half_open_overlap."""

    def test_adjacent_class_at_ends_on_is_allowed(self, api):
        """PRD §3.7: "The lead trainer's other non-cancelled classes occupy the
        half-open interval from `starts_on` inclusive to `ends_on` exclusive,
        and two such intervals overlap when the new class's `starts_on` is
        earlier than the other's `ends_on` and the new class's `ends_on` is
        later than the other's `starts_on`; an overlap is rejected with
        `ERR_TRAINER_SCHEDULE_CONFLICT`, while mere adjacency — one class's
        `ends_on` exactly equal to the other's `starts_on` — is allowed."

        Class B starting exactly when class A ends is allowed.

        Design: Difficulty/resource_temporal_overlap/trainer_class_half_open_overlap
        """
        trainer = create_certified_trainer()
        class_a = validate_success(
            api.create_class(
                create_class_payload(
                    lead_trainer_id=trainer["id"],
                    starts_on="2026-09-01",
                    ends_on="2026-10-15",
                ),
                TD,
            ),
            expected_status=201,
        )
        assert class_a["status"] == "PLANNED"
        class_b = validate_success(
            api.create_class(
                create_class_payload(
                    lead_trainer_id=trainer["id"],
                    starts_on="2026-10-15",
                    ends_on="2026-11-30",
                ),
                TD,
            ),
            expected_status=201,
        )
        assert class_b["status"] == "PLANNED"

    def test_overlapping_class_rejected(self, api):
        """PRD §3.7: "two such intervals overlap when the new class's
        `starts_on` is earlier than the other's `ends_on` and the new class's
        `ends_on` is later than the other's `starts_on`; an overlap is rejected
        with `ERR_TRAINER_SCHEDULE_CONFLICT`."

        Class C [2026-11-29, 2026-12-15) overlaps class B
        [2026-10-15, 2026-11-30).

        Design: Difficulty/resource_temporal_overlap/trainer_class_half_open_overlap
        """
        trainer = create_certified_trainer()
        validate_success(
            api.create_class(
                create_class_payload(
                    lead_trainer_id=trainer["id"],
                    starts_on="2026-09-01",
                    ends_on="2026-10-15",
                ),
                TD,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_class(
                create_class_payload(
                    lead_trainer_id=trainer["id"],
                    starts_on="2026-10-15",
                    ends_on="2026-11-30",
                ),
                TD,
            ),
            expected_status=201,
        )
        resp = api.create_class(
            create_class_payload(
                lead_trainer_id=trainer["id"],
                starts_on="2026-11-29",
                ends_on="2026-12-15",
            ),
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_TRAINER_SCHEDULE_CONFLICT)


class TestEvaluatorPatBufferOverlap:
    """Difficulty/resource_temporal_overlap/evaluator_pat_buffer_overlap."""

    def test_pat_inside_30_minute_buffer_rejected(self, api):
        """PRD §3.7: "an evaluator is occupied for the 60-minute window from
        `scheduled_at` up to but not including `scheduled_at` plus 60 minutes,
        buffered by 30 minutes on each side, and a new `SCHEDULED` or scored
        test for the same evaluator whose buffered window intersects another's
        is rejected with `ERR_EVALUATOR_SCHEDULE_CONFLICT` — windows exactly
        30 minutes apart are allowed."

        A PAT at 11:29 collides with the 10:00-11:00 window's 30-minute
        post-buffer.

        Design: Difficulty/resource_temporal_overlap/evaluator_pat_buffer_overlap
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-10T10:00:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        resp = api.create_pat(
            ctx["enrollment"]["id"],
            {"scheduled_at": "2026-10-10T11:29:00Z"},
            make_evaluator_headers(evaluator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_SCHEDULE_CONFLICT)

    def test_pat_exactly_at_buffer_edge_allowed(self, api):
        """PRD §3.7: "windows exactly 30 minutes apart are allowed."

        A PAT at exactly 11:30 satisfies the buffer and is created as
        attempt_number 2.

        Design: Difficulty/resource_temporal_overlap/evaluator_pat_buffer_overlap
        """
        ctx = setup_in_session_enrollment()
        evaluator = create_certified_trainer(pat_certified=True)
        first = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-10T10:00:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        assert first["attempt_number"] == 1
        second = validate_success(
            api.create_pat(
                ctx["enrollment"]["id"],
                {"scheduled_at": "2026-10-10T11:30:00Z"},
                make_evaluator_headers(evaluator["id"]),
            ),
            expected_status=201,
        )
        assert second["attempt_number"] == 2
        assert second["status"] == "SCHEDULED"


class TestFollowupMinGapSemantics:
    """Difficulty/resource_temporal_overlap/followup_min_gap_semantics."""

    def test_manual_followup_five_days_from_auto_rejected(self, api):
        """PRD §3.8: "A manual `due_on` must sit at least 7 days away from the
        `due_on` of every other non-`WAIVED` follow-up of the same partnership
        — a gap of exactly 7 days is allowed, anything closer is rejected with
        `ERR_FOLLOWUP_TOO_SOON`."

        Auto follow-up due 2027-01-14; manual 2027-01-19 is a 5-day gap.

        Design: Difficulty/resource_temporal_overlap/followup_min_gap_semantics
        """
        ctx = setup_graduated_partnership()
        resp = api.create_followup(
            ctx["partnership"]["id"], {"due_on": "2027-01-19"}, TD
        )
        validate_error(resp, ApiErrorId.ERR_FOLLOWUP_TOO_SOON)

    def test_manual_followup_exactly_seven_days_allowed(self, api):
        """PRD §3.8: "a gap of exactly 7 days is allowed, anything closer is
        rejected with `ERR_FOLLOWUP_TOO_SOON`."

        Manual 2027-01-21 is exactly 7 days after the auto follow-up due
        2027-01-14 and is created SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/followup_min_gap_semantics
        """
        ctx = setup_graduated_partnership()
        followup = validate_success(
            api.create_followup(
                ctx["partnership"]["id"], {"due_on": "2027-01-21"}, TD
            ),
            expected_status=201,
        )
        assert followup["status"] == "SCHEDULED"
        assert followup["auto_generated"] is False


class TestAttendanceExact85Graduation:
    """Difficulty/boundary_precision_check/attendance_exact_85_graduation."""

    def test_attendance_85_0_is_inclusive_pass(self, api):
        """PRD §3.7: "the enrollment is `ENROLLED`; its class is in
        `GRADUATION_REVIEW`; `attendance_pct` is at least 85.0 inclusive
        (otherwise `ERR_ATTENDANCE_BELOW_THRESHOLD`); and a public access test
        for the enrollment exists with status `SCORED_PASS` (otherwise
        `ERR_GRADUATION_REQUIREMENTS`)."
        PRD §3.7: "`attendance_pct` is recomputed as sessions attended divided
        by the class's `total_sessions`, multiplied by 100, rounded half-up to
        1 decimal place."

        17/20 sessions = 85.0 exactly -> graduation succeeds.

        Design: Difficulty/boundary_precision_check/attendance_exact_85_graduation
        """
        ctx = setup_in_session_enrollment(
            attendance=17, pat_scores=PAT_PERFECT_SCORES
        )
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["attendance_pct"] == pytest.approx(85.0, abs=0.01)
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN)
        )
        validate_success(api.begin_graduation_review(ctx["clazz"]["id"], TD))
        partnership = validate_success(
            api.graduate_enrollment(ctx["enrollment"]["id"], TD),
            expected_status=201,
        )
        assert partnership["status"] == "ACTIVE"
        enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], TD))
        assert enrollment["status"] == "GRADUATED"

    def test_graduation_cascade_side_effects(self, api):
        """PRD §3.7: "Graduation moves the enrollment to `GRADUATED` and fires
        the placement cascade: a `Partnership` is created with `status`
        `ACTIVE`, `activated_at` set to the current logical time, and
        `recert_due_at` set to `activated_at` plus 365 days; three follow-ups
        are auto-created in `SCHEDULED` with `due_on` at the activation date
        plus 90, plus 180, and plus 270 days respectively, each with
        `auto_generated` true; the dog moves from `TEAM_TRAINING` to `PLACED`;
        the applicant moves from `TEAM_TRAINING` to `PLACED`; the match record
        moves from `ACCEPTED` to `COMPLETED`; and the waitlist entry moves
        from `MATCHED` to `CLOSED`."

        Graduation at clock 2026-10-16: activated 2026-10-16, recert due
        2027-10-16, follow-ups due 2027-01-14 / 2027-04-14 / 2027-07-13.

        Design: Difficulty/boundary_precision_check/attendance_exact_85_graduation
        """
        ctx = setup_in_session_enrollment(
            attendance=17, pat_scores=PAT_PERFECT_SCORES
        )
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN)
        )
        validate_success(api.begin_graduation_review(ctx["clazz"]["id"], TD))
        partnership = validate_success(
            api.graduate_enrollment(ctx["enrollment"]["id"], TD),
            expected_status=201,
        )
        assert_date_prefix(partnership["activated_at"], "2026-10-16", "activated_at")
        assert_date_prefix(partnership["recert_due_at"], "2027-10-16", "recert_due_at")
        dog = validate_success(api.get_dog(ctx["dog"]["id"], TD))
        assert dog["status"] == "PLACED"
        applicant = validate_success(api.get_applicant(ctx["applicant"]["id"], COORD))
        assert applicant["application_status"] == "PLACED"
        match = validate_success(api.get_match(ctx["match"]["id"], COORD))
        assert match["status"] == "COMPLETED"
        entry = validate_success(api.get_waitlist_entry(ctx["entry"]["id"], COORD))
        assert entry["status"] == "CLOSED"
        followups = validate_success(
            api.list_partnership_followups(partnership["id"], TD)
        )
        assert len(followups) == 3
        due_dates = sorted(f["due_on"][:10] for f in followups)
        assert due_dates == ["2027-01-14", "2027-04-14", "2027-07-13"]
        assert all(f["status"] == "SCHEDULED" for f in followups)
        assert all(f["auto_generated"] is True for f in followups)


class TestExistenceVsStatePriorityOnMatchProposal:
    """Difficulty/priority_pair_validation_conflict/existence_vs_constraint_priority_on_match_proposal."""

    def test_unknown_entry_id_yields_reference_not_found(self, api):
        """PRD §2.6: "Every request passes through a fixed pipeline of checks,
        evaluated in this order: ... 6. **Body references** — body-supplied
        references (`waitlist_entry_id`, ...) must resolve to existing
        resources; failures return `ERR_REFERENCE_NOT_FOUND` (HTTP 404). ...
        9. **From-state membership** — the resource must be in a declared
        from-state for the requested transition (`ERR_INVALID_STATE`, HTTP
        409)."

        A proposal naming a non-existent waitlist_entry_id against a
        REGISTERED dog surfaces ERR_REFERENCE_NOT_FOUND (existence, step 6,
        precedes state, step 9).

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_constraint_priority_on_match_proposal
        """
        dog = validate_success(
            api.create_dog(create_dog_payload(), ADMIN),
            expected_status=201,
        )
        resp = api.create_match_proposal(
            dog["id"],
            {
                "waitlist_entry_id": "00000000-0000-0000-0000-000000000000",
                "expected_dog_version": dog["version"],
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_reference_error_status_is_404_not_state_409(self, api):
        """PRD §2.6: "6. **Body references** — body-supplied references
        (`waitlist_entry_id`, ...) must resolve to existing resources; failures
        return `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."
        PRD §5: ERR_REFERENCE_NOT_FOUND is listed at HTTP 404.

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_constraint_priority_on_match_proposal
        """
        dog = validate_success(
            api.create_dog(create_dog_payload(), ADMIN),
            expected_status=201,
        )
        resp = api.create_match_proposal(
            dog["id"],
            {
                "waitlist_entry_id": "00000000-0000-0000-0000-000000000000",
                "expected_dog_version": dog["version"],
            },
            COORD,
        )
        assert resp.status_code == 404, (
            f"body-reference failure must be 404, got {resp.status_code}"
        )
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_REFERENCE_NOT_FOUND"


class TestRaiserCapacityConservation:
    """Difficulty/compensating_invariant/raiser_capacity_conservation."""

    def test_placement_increments_count_and_activates_raiser(self, api):
        """PRD §3.6: "A created placement is `ACTIVE`, with `started_on` set
        from the logical clock, `ended_on` null, the dog moving to
        `RAISER_PLACED`, the raiser's `current_dog_count` increasing by 1, and
        an `APPROVED` raiser moving to `ACTIVE` on their first placement."

        Design: Difficulty/compensating_invariant/raiser_capacity_conservation
        """
        dog = create_cleared_dog()
        raiser = create_approved_raiser(foster_capacity=2)
        placement = validate_success(
            api.create_raiser_placement(
                dog["id"], {"puppy_raiser_id": raiser["id"]}, TD
            ),
            expected_status=201,
        )
        assert placement["status"] == "ACTIVE"
        raiser_now = validate_success(api.get_puppy_raiser(raiser["id"], ADMIN))
        assert raiser_now["current_dog_count"] == 1
        assert raiser_now["status"] == "ACTIVE"
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "RAISER_PLACED"

    def test_early_return_and_replace_leave_zero_drift(self, api):
        """PRD §3.6: "Early return — available to a `TrainingDirector`, or to
        the raiser acting on their own placement ... — moves the placement to
        `EARLY_RETURN` and recalls the dog from `RAISER_PLACED` to `RECALLED`,
        with the same raiser count and timestamp effects."
        PRD §3.4: "The first placement created for an `APPROVED` raiser moves
        them to `ACTIVE`; when their `current_dog_count` later returns to 0 on
        a completion or early return, they drop back to `APPROVED`."

        Place (count 1), early-return (count 0, ACTIVE -> APPROVED), place a
        second dog (count 1 again): forward + compensating actions leave no
        drift.

        Design: Difficulty/compensating_invariant/raiser_capacity_conservation
        """
        dog1 = create_cleared_dog()
        dog2 = create_cleared_dog()
        raiser = create_approved_raiser(foster_capacity=2)
        pl1 = validate_success(
            api.create_raiser_placement(
                dog1["id"], {"puppy_raiser_id": raiser["id"]}, TD
            ),
            expected_status=201,
        )
        validate_success(api.early_return_raiser_placement(pl1["id"], TD))
        raiser_now = validate_success(api.get_puppy_raiser(raiser["id"], ADMIN))
        assert raiser_now["current_dog_count"] == 0
        assert raiser_now["status"] == "APPROVED"
        dog1_now = validate_success(api.get_dog(dog1["id"], TD))
        assert dog1_now["status"] == "RECALLED"
        pl2 = validate_success(
            api.create_raiser_placement(
                dog2["id"], {"puppy_raiser_id": raiser["id"]}, TD
            ),
            expected_status=201,
        )
        assert pl2["status"] == "ACTIVE"
        raiser_now = validate_success(api.get_puppy_raiser(raiser["id"], ADMIN))
        assert raiser_now["current_dog_count"] == 1
        assert raiser_now["status"] == "ACTIVE"


class TestMatchPairingConservation:
    """Difficulty/compensating_invariant/match_pairing_conservation."""

    def test_accept_sets_all_three_parties_together(self, api):
        """PRD §3.7: "then fires the three-way mirror: the dog moves
        `MATCH_READY` to `MATCHED`, the entry moves `ELIGIBLE` to `MATCHED`,
        and the applicant moves `MATCH_ELIGIBLE` to `MATCHED`."

        Design: Difficulty/compensating_invariant/match_pairing_conservation
        """
        dog, _r, _t = create_match_ready_dog()
        applicant, entry, _c = create_eligible_entry()
        match = propose_and_accept_match(dog, entry)
        assert match["status"] == "ACCEPTED"
        assert validate_success(api.get_dog(dog["id"], TD))["status"] == "MATCHED"
        entry_now = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert entry_now["status"] == "MATCHED"
        applicant_now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert applicant_now["application_status"] == "MATCHED"

    def test_dissolve_restores_all_three_and_ratchets_audit_count(self, api):
        """PRD §3.7: "Dissolving an `ACCEPTED` match — by an
        `IntakeCoordinator` directly, or by the career-change, withdrawal,
        enrollment-withdrawal, and PAT-fail cascades — reverts the dog from
        `MATCHED` to `MATCH_READY` ..., reverts the entry from `MATCHED` to
        `ELIGIBLE` while incrementing `dissolved_match_count` and recomputing
        `rank_score`, and moves the applicant from `MATCHED` to
        `MATCH_ELIGIBLE`."

        Design: Difficulty/compensating_invariant/match_pairing_conservation
        """
        dog, _r, _t = create_match_ready_dog()
        applicant, entry, _c = create_eligible_entry()
        match = propose_and_accept_match(dog, entry)
        dissolved = validate_success(api.dissolve_match(match["id"], COORD))
        assert dissolved["status"] == "DISSOLVED"
        assert validate_success(api.get_dog(dog["id"], TD))["status"] == "MATCH_READY"
        entry_now = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert entry_now["status"] == "ELIGIBLE"
        assert entry_now["dissolved_match_count"] == 1
        applicant_now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert applicant_now["application_status"] == "MATCH_ELIGIBLE"
