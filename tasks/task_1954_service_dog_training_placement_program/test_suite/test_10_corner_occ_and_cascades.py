"""Corner queue: OCC stale-version rules, clock sweep, retire/career-change
cascades, withdraw guard on PLACED, support reopen window, immediate
consistency, RBAC scoping (PRD §2.1, §2.7, §2.8, §3.1, §3.4, §3.6–§3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_certified_trainer,
    create_class_enrolling,
    create_eligible_entry,
    create_match_ready_dog,
    create_puppy_raiser_payload,
    enroll_match,
    make_applicant_headers,
    make_trainer_headers,
    propose_and_accept_match,
    setup_graduated_partnership,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]


class TestEnrollmentOccStaleVersion:
    """Corner/cross_cutting_complexity_layers/enrollment_occ_stale_version_rejected."""

    def test_stale_class_version_rejected(self, api):
        """PRD §2.7: "**Creating an enrollment** against a class requires the
        non-optional field `expected_class_version`, carrying the client's
        last observed `version` of that `TeamTrainingClass`. If the class's
        version has advanced since the client read it — for example another
        writer has just enrolled a pair, legitimately consuming a seat — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Pair A enrolls (version bumps); pair B's enrollment carrying the
        pre-enrollment version is rejected even though a seat remains.

        Design: Corner/cross_cutting_complexity_layers/enrollment_occ_stale_version_rejected
        """
        trainer = create_certified_trainer()
        pairs = []
        for _ in range(2):
            dog, _r, _t = create_match_ready_dog()
            _applicant, entry, _c = create_eligible_entry()
            match = propose_and_accept_match(dog, entry)
            pairs.append(match)
        clazz = create_class_enrolling(trainer["id"], capacity=2)
        stale_version = validate_success(api.get_class(clazz["id"], TD))["version"]
        enrollment_a = enroll_match(clazz, pairs[0])
        assert enrollment_a["status"] == "ENROLLED"
        resp = api.create_enrollment(
            clazz["id"],
            {"match_id": pairs[1]["id"], "expected_class_version": stale_version},
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        match_b = validate_success(api.get_match(pairs[1]["id"], COORD))
        assert match_b["status"] == "ACCEPTED"
        clazz_now = validate_success(api.get_class(clazz["id"], TD))
        assert clazz_now["enrolled_count"] == 1


class TestMatchProposalOccStaleVersion:
    """Corner/cross_cutting_complexity_layers/match_proposal_occ_stale_version_rejected."""

    def test_stale_dog_version_rejected(self, api):
        """PRD §2.7: "**Proposing a match** against a dog requires the
        non-optional field `expected_dog_version`, carrying the client's last
        observed `version` of that `Dog`. A mismatch with the dog's current
        `version` is rejected with `ERR_STALE_DOG_VERSION` (HTTP 412)."
        PRD §3.7: "A created match record is `PROPOSED`, with
        `proposed_by_user_id` set to the acting operator id,
        `rank_score_at_match` capturing the entry's `rank_score` at proposal
        time, and the dog's `version` incrementing by 1."

        The first proposal bumps the dog version without leaving MATCH_READY;
        the second proposal with the stale version is rejected.

        Design: Corner/cross_cutting_complexity_layers/match_proposal_occ_stale_version_rejected
        """
        dog, _r, _t = create_match_ready_dog()
        _applicant, entry, _c = create_eligible_entry()
        stale_version = validate_success(api.get_dog(dog["id"], TD))["version"]
        m1 = validate_success(
            api.create_match_proposal(
                dog["id"],
                {
                    "waitlist_entry_id": entry["id"],
                    "expected_dog_version": stale_version,
                },
                COORD,
            ),
            expected_status=201,
        )
        assert m1["status"] == "PROPOSED"
        resp = api.create_match_proposal(
            dog["id"],
            {
                "waitlist_entry_id": entry["id"],
                "expected_dog_version": stale_version,
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DOG_VERSION)
        matches = validate_success(api.list_dog_matches(dog["id"], TD))
        assert len(matches) == 1


class TestRecertificationOccStaleVersion:
    """Corner/cross_cutting_complexity_layers/recertification_occ_stale_version_rejected."""

    def test_stale_partnership_version_rejected(self, api):
        """PRD §2.7: "**Scheduling a recertification** against a partnership
        requires the non-optional field `expected_partnership_version`,
        carrying the client's last observed `version` of that `Partnership`.
        A mismatch is rejected with `ERR_STALE_PARTNERSHIP_VERSION` (HTTP
        412)."
        PRD §3.8: "the scheduling itself increments the partnership's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/recertification_occ_stale_version_rejected
        """
        ctx = setup_graduated_partnership()
        partnership = ctx["partnership"]
        evaluator = ctx["evaluator"]
        stale_version = validate_success(
            api.get_partnership(partnership["id"], TD)
        )["version"]
        recert = validate_success(
            api.create_recertification(
                partnership["id"],
                {
                    "scheduled_on": "2027-10-20",
                    "evaluator_id": evaluator["id"],
                    "expected_partnership_version": stale_version,
                },
                TD,
            ),
            expected_status=201,
        )
        assert recert["status"] == "SCHEDULED"
        resp = api.create_recertification(
            partnership["id"],
            {
                "scheduled_on": "2027-10-21",
                "evaluator_id": evaluator["id"],
                "expected_partnership_version": stale_version,
            },
            TD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PARTNERSHIP_VERSION)
        recerts = validate_success(
            api.list_partnership_recertifications(partnership["id"], TD)
        )
        assert len(recerts) == 1


class TestFollowupMissedByClockSweep:
    """Corner/cross_cutting_complexity_layers/followup_missed_by_clock_sweep."""

    def test_first_followup_swept_to_missed(self, api):
        """PRD §2.8: "Two transitions fire during the sweep: a `FollowUp`
        still `SCHEDULED` whose current logical date is more than 7 days past
        its `due_on` becomes `MISSED`; and a `Partnership` in `ACTIVE` whose
        current logical date is later than its `recert_due_at` with no
        `COMPLETED_PASS` recertification recorded since activation becomes
        `RECERT_DUE`."
        PRD §2.5: "the response reports the new `current_utc` plus the counts
        `swept_followups_missed` and `swept_partnerships_recert_due`."

        At 2027-01-22 the 2027-01-14 follow-up is 8 days past due (grace 7
        elapsed); the 2027-04-14 and 2027-07-13 follow-ups remain SCHEDULED,
        and the partnership (due 2027-10-16) stays ACTIVE.

        Design: Corner/cross_cutting_complexity_layers/followup_missed_by_clock_sweep
        """
        ctx = setup_graduated_partnership()
        partnership = ctx["partnership"]
        sweep = validate_success(
            api.set_clock({"to_iso8601": "2027-01-22T00:00:00Z"}, ADMIN)
        )
        assert sweep["swept_followups_missed"] == 1
        followups = validate_success(
            api.list_partnership_followups(partnership["id"], TD)
        )
        by_due = {f["due_on"][:10]: f["status"] for f in followups}
        assert by_due["2027-01-14"] == "MISSED"
        assert by_due["2027-04-14"] == "SCHEDULED"
        assert by_due["2027-07-13"] == "SCHEDULED"
        now = validate_success(api.get_partnership(partnership["id"], TD))
        assert now["status"] == "ACTIVE"


class TestPartnershipRetireCascades:
    """Corner/cross_cutting_complexity_layers/partnership_retire_cascades_dog_and_followups."""

    def test_retire_cascades_to_dog_and_followups(self, api):
        """PRD §3.8: "Retiring a partnership from `ACTIVE`, `RECERT_DUE`, or
        `SUSPENDED` moves it to the terminal `RETIRED`, moves the placed dog
        from `PLACED` to `RETIRED`, and waives every open — `SCHEDULED` —
        follow-up."

        Design: Corner/cross_cutting_complexity_layers/partnership_retire_cascades_dog_and_followups
        """
        ctx = setup_graduated_partnership()
        partnership = ctx["partnership"]
        retired = validate_success(api.retire_partnership(partnership["id"], TD))
        assert retired["status"] == "RETIRED"
        dog = validate_success(api.get_dog(ctx["dog"]["id"], TD))
        assert dog["status"] == "RETIRED"
        followups = validate_success(
            api.list_partnership_followups(partnership["id"], TD)
        )
        assert len(followups) == 3
        assert all(f["status"] == "WAIVED" for f in followups)


class TestSupportReopenWindowExpired:
    """Corner/cross_cutting_complexity_layers/support_reopen_window_expired_rejected."""

    def test_reopen_after_14_days_rejected(self, api):
        """PRD §3.9: "The client then has a 14-day window: the applicant who
        owns the partnership may reopen a `RESOLVED` request while the logical
        time is within 14 days of `resolved_at` — later attempts are rejected
        with `ERR_REOPEN_WINDOW_EXPIRED`, and acting on someone else's request
        is `ERR_OWNERSHIP_SCOPE`."

        Resolved at 2026-10-16; reopen at 2026-10-31 is 15 days later.

        Design: Corner/cross_cutting_complexity_layers/support_reopen_window_expired_rejected
        """
        ctx = setup_graduated_partnership()
        applicant_h = make_applicant_headers(ctx["applicant"]["id"])
        sr = validate_success(
            api.create_support_request(
                ctx["partnership"]["id"],
                {"category": "EQUIPMENT", "description": "harness frayed"},
                applicant_h,
            ),
            expected_status=201,
        )
        validate_success(
            api.triage_support_request(sr["id"], {"priority": "MEDIUM"}, TD)
        )
        validate_success(
            api.start_support_request(
                sr["id"], {"assigned_trainer_id": ctx["trainer"]["id"]}, TD
            )
        )
        resolved = validate_success(
            api.resolve_support_request(
                sr["id"],
                {"resolution_note": "replacement shipped"},
                make_trainer_headers(ctx["trainer"]["id"]),
            )
        )
        assert resolved["resolved_at"] is not None
        validate_success(
            api.set_clock({"to_iso8601": "2026-10-31T00:00:00Z"}, ADMIN)
        )
        resp = api.reopen_support_request(sr["id"], applicant_h)
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)
        now = validate_success(api.get_support_request(sr["id"], TD))
        assert now["status"] == "RESOLVED"


class TestWithdrawPlacedApplicantRejected:
    """Corner/cross_cutting_complexity_layers/withdraw_placed_applicant_rejected."""

    def test_withdraw_on_placed_rejected(self, api):
        """PRD §3.1: "Withdrawal is available from every non-terminal state
        except `PLACED` — that is, from `SUBMITTED`, `IN_REVIEW`,
        `NEEDS_INFO`, `WAITLISTED`, `MATCH_ELIGIBLE`, `MATCHED`, or
        `TEAM_TRAINING`; attempting it elsewhere is `ERR_INVALID_STATE`. (A
        `PLACED` applicant exits the program through partnership dissolution,
        §3.8.)"

        Design: Corner/cross_cutting_complexity_layers/withdraw_placed_applicant_rejected
        """
        ctx = setup_graduated_partnership()
        applicant = ctx["applicant"]
        assert applicant["application_status"] == "PLACED"
        resp = api.withdraw_applicant(applicant["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert now["application_status"] == "PLACED"
        partnership = validate_success(
            api.get_partnership(ctx["partnership"]["id"], TD)
        )
        assert partnership["status"] == "ACTIVE"


class TestCareerChangeFromMatchedCascade:
    """Corner/cross_cutting_complexity_layers/career_change_from_matched_cascade."""

    def test_career_change_on_matched_dog_dissolves_match(self, api):
        """PRD §3.6: "From `MATCHED` or `TEAM_TRAINING`, the accepted match
        record becomes `DISSOLVED`, which itself reverts the waitlist entry
        from `MATCHED` to `ELIGIBLE` — incrementing `dissolved_match_count`
        and recomputing rank — and moves the applicant from `MATCHED` or
        `TEAM_TRAINING` to `MATCH_ELIGIBLE`."
        PRD §3.6: "the reason is recorded as `career_change_reason` and the
        dog lands in the terminal state `CAREER_CHANGED`."

        Design: Corner/cross_cutting_complexity_layers/career_change_from_matched_cascade
        """
        dog, _r, _t = create_match_ready_dog()
        applicant, entry, _c = create_eligible_entry()
        match = propose_and_accept_match(dog, entry)
        changed = validate_success(
            api.career_change_dog(
                dog["id"],
                {"reason_category": "TEMPERAMENT",
                 "notes": "resource guarding emerged"},
                TD,
            )
        )
        assert changed["status"] == "CAREER_CHANGED"
        assert changed["career_change_reason"] == "TEMPERAMENT"
        match_now = validate_success(api.get_match(match["id"], COORD))
        assert match_now["status"] == "DISSOLVED"
        entry_now = validate_success(api.get_waitlist_entry(entry["id"], COORD))
        assert entry_now["status"] == "ELIGIBLE"
        assert entry_now["dissolved_match_count"] == 1
        applicant_now = validate_success(api.get_applicant(applicant["id"], COORD))
        assert applicant_now["application_status"] == "MATCH_ELIGIBLE"


class TestApproveResponseImmediatelyConsistent:
    """Corner/consistency_model/approve_response_immediately_consistent."""

    def test_approve_response_and_entry_visible_immediately(self, api):
        """PRD §3.1: "Approval stamps `approved_by_user_id` with the acting
        operator id, moves the applicant to `WAITLISTED`, and creates the
        waitlist entry described in §3.2."
        PRD §3.2: "Approval creates a `WaitlistEntry` with `status` `PENDING`,
        `listed_at` set to the logical-clock timestamp, `raised_cents` 0,
        `dissolved_match_count` 0, `requirement_final_cents` null, and
        `requirement_provisional_cents` computed by the provisional variant of
        the fundraising rule below."

        FACILITY @ 12,000,000 income -> 0% credit, 15% subsidy on gross
        900,000 -> provisional 765,000, visible on the next read.

        Design: Corner/consistency_model/approve_response_immediately_consistent
        """
        from test_helpers import create_applicant_with_accepted_assessment
        applicant, _a = create_applicant_with_accepted_assessment(
            track="FACILITY",
            income_cents=12_000_000,
            required_tasks=("GUIDE_NAVIGATION",),
            home_score=5,
        )
        approved = validate_success(api.approve_applicant(applicant["id"], COORD))
        assert approved["application_status"] == "WAITLISTED"
        entries = validate_success(
            api.list_applicant_waitlist_entries(applicant["id"], COORD)
        )
        assert len(entries) == 1
        assert entries[0]["status"] == "PENDING"
        assert entries[0]["requirement_provisional_cents"] == 765_000


class TestTrainerOwnershipOnMilestones:
    """Corner/rbac/trainer_cannot_record_milestone_for_other_trainers_dog_returns_403."""

    def test_other_trainer_rejected_primary_succeeds(self, api):
        """PRD §3.6: "A `Trainer` actor must be the dog's `primary_trainer_id`
        (otherwise `ERR_OWNERSHIP_SCOPE`); a `TrainingDirector` actor records
        the milestone with `recorded_by_trainer_id` set to the dog's
        `primary_trainer_id`."

        Design: Corner/rbac/trainer_cannot_record_milestone_for_other_trainers_dog_returns_403
        """
        from test_helpers import create_dog_in_advanced_training
        dog, _r, trainer, _pl = create_dog_in_advanced_training()
        other = create_certified_trainer()
        resp = api.create_milestone(
            dog["id"],
            {"category": "OBEDIENCE", "score": 70},
            make_trainer_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SCOPE)
        milestone = validate_success(
            api.create_milestone(
                dog["id"],
                {"category": "OBEDIENCE", "score": 70},
                make_trainer_headers(trainer["id"]),
            ),
            expected_status=201,
        )
        assert milestone["id"]


class TestRaiserAdminIsProgramAdminExclusive:
    """Corner/rbac/raiser_admin_is_programadmin_exclusive."""

    def test_coordinator_cannot_create_raiser(self, api):
        """PRD §2.1: "When the role is declared but is not listed among the
        roles authorized for the endpoint, the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/puppy-raisers is authorized for ProgramAdmin only.

        Design: Corner/rbac/raiser_admin_is_programadmin_exclusive
        """
        resp = api.create_puppy_raiser(create_puppy_raiser_payload(), COORD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        from test_helpers import validate_paginated
        data, _meta = validate_paginated(api.list_puppy_raisers(ADMIN))
        assert len(data) == 0
