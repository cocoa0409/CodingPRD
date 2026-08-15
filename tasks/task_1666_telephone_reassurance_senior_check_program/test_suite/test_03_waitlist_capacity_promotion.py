"""Waitlist offers, promotion runs, capacity branch, occupied-slot invariant."""
from test_helpers import (
    ApiErrorId,
    add_emergency_contact,
    approve_participant,
    create_applicant,
    create_program,
    enroll_participant,
    get_program,
    get_waitlist_entry_of,
    run_promotion,
    set_clock,
    submit_for_review,
    validate_error,
    validate_success,
    waitlist_applicant,
)


def _program_with_filler_and_waitlisted(api, coordinator_headers,
                                        applicant_overrides=None, capacity=1):
    """Program at capacity: one filler ENROLLED, one applicant WAITLISTED.
    Returns (program, filler, waitlisted_participant, entry)."""
    program = create_program(total_capacity=capacity, max_reserve_slots=0)
    filler = enroll_participant({"full_name": "Fill"})
    waitlisted, entry = waitlist_applicant(applicant_overrides or {"full_name": "Wait P"})
    return program, filler, waitlisted, entry


class TestWaitlistEntryCreation:
    def test_waitlist_entry_created_with_zeroed_counters(self, api, intake_headers, coordinator_headers):
        """PRD §3.2: "A non-admitted applicant becomes `WAITLISTED`: a waitlist entry is created in status `WAITING` with `waitlist_entered_at` set to the clock, `waiting_count` increases by one, and `last_status_change_at` is stamped."
        PRD §3.3: "While `WAITING`, the entry's `offered_at`, `offer_expires_at`, and `priority_score_at_offer` are null; `declines_count` and `expires_count` track how often the applicant has declined an offer or let one lapse."

        Design: Corner/entities/waitlist_entry_created_with_zeroed_counters
        """
        program, filler, waitlisted, entry = _program_with_filler_and_waitlisted(
            api, coordinator_headers
        )
        assert entry["status"] == "WAITING"
        assert entry["declines_count"] == 0
        assert entry["expires_count"] == 0
        assert entry.get("offered_at") is None
        assert entry.get("offer_expires_at") is None
        assert entry.get("priority_score_at_offer") is None
        assert entry["waitlist_entered_at"].startswith("2026-08-01T00:00:00"), (
            f"waitlist_entered_at must be the clock at approve time, "
            f"got {entry['waitlist_entered_at']!r}"
        )


class TestOfferAcceptGates:
    def test_accept_on_waiting_entry_returns_offer_not_open(self, api, intake_headers, coordinator_headers):
        """PRD §3.3: "The entry must be `OFFERED` and the clock must not be past `offer_expires_at` — an offer expires only when the clock is strictly later than the expiry instant, so at the exact deadline the offer still stands; violations surface as `ERR_OFFER_NOT_OPEN` (and an offer the closeout has already requeued is simply no longer open)."

        Design: Corner/errors/accept_on_waiting_entry_returns_offer_not_open
        """
        program, filler, waitlisted, entry = _program_with_filler_and_waitlisted(
            api, coordinator_headers
        )
        resp = api.accept_waitlist_entry(entry["id"], intake_headers)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN, 409)
        after = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert after["status"] == "WAITING"
        participant = validate_success(api.get_participant(waitlisted["id"], intake_headers))
        assert participant["status"] == "WAITLISTED"

    def test_offer_accept_after_capacity_retaken_rejected(self, api, intake_headers, coordinator_headers):
        """PRD §3.3: "Capacity is re-checked at accept time under the same rule as admission: gross free at least one for a `CRITICAL` applicant, gross free minus the reserve at least one otherwise. If an intervening enrollment has exhausted the free slots, the accept fails with `ERR_CAPACITY_REACHED` and the entry stays `OFFERED`."

        Design: Corner/state_machines/offer_accept_after_capacity_retaken_rejected
        """
        program, filler, waitlisted, entry = _program_with_filler_and_waitlisted(
            api, coordinator_headers
        )
        # Free the slot, run the promotion so the entry is OFFERED.
        validate_success(
            api.disenroll_participant(filler["id"], {"reason": "moved"}, coordinator_headers)
        )
        run_promotion(program["id"])
        offered = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert offered["status"] == "OFFERED"
        # An intervening direct approval retakes the freed slot.
        p2 = create_applicant(full_name="P2")
        add_emergency_contact(p2["id"])
        submit_for_review(p2["id"])
        p2_after = approve_participant(p2["id"])
        assert p2_after["status"] == "ENROLLED"
        resp = api.accept_waitlist_entry(entry["id"], intake_headers)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_REACHED, 409)
        after = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert after["status"] == "OFFERED", "the failed accept leaves the entry OFFERED"


class TestOfferExpiry:
    def test_offer_expiry_strictly_greater_than_ttl(self, api, intake_headers, coordinator_headers):
        """PRD §3.3: "The entry must be `OFFERED` and the clock must not be past `offer_expires_at` — an offer expires only when the clock is strictly later than the expiry instant, so at the exact deadline the offer still stands; violations surface as `ERR_OFFER_NOT_OPEN` (and an offer the closeout has already requeued is simply no longer open)."
        PRD §3.3: "Offers can also lapse: the daily closeout finds every `OFFERED` entry whose expiry is strictly past, returns it to `WAITING`, increments `expires_count`, and clears the offer fields; the second lapse removes the entry with `removal_reason` `MAX_EXPIRES` and likewise exits the participant."

        Design: Corner/calculations/offer_expiry_strictly_greater_than_ttl
        """
        program, filler, waitlisted, entry = _program_with_filler_and_waitlisted(
            api, coordinator_headers
        )
        validate_success(
            api.disenroll_participant(filler["id"], {"reason": "moved"}, coordinator_headers)
        )
        set_clock("2026-08-03T10:00:00Z")
        run_promotion(program["id"])
        offered = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert offered["status"] == "OFFERED"
        assert offered["offer_expires_at"].startswith("2026-08-06T10:00:00"), (
            f"offer_expires_at must be offered_at + 72h, got {offered['offer_expires_at']!r}"
        )
        # At exactly the expiry instant the offer still stands.
        set_clock("2026-08-06T10:00:00Z")
        close1 = validate_success(api.daily_closeout(program["id"], coordinator_headers))
        assert entry["id"] not in close1["expired_offer_entry_ids"]
        still = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert still["status"] == "OFFERED"
        # One second past: the closeout requeues the offer.
        set_clock("2026-08-06T10:00:01Z")
        close2 = validate_success(api.daily_closeout(program["id"], coordinator_headers))
        assert entry["id"] in close2["expired_offer_entry_ids"]
        after = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert after["status"] == "WAITING"
        assert after["expires_count"] == 1, "requeue at one lapse; MAX_EXPIRES is 2"


class TestPromotionRunShape:
    def test_promotion_run_epoch_increments_on_empty_run(self, api, intake_headers, coordinator_headers):
        """PRD §3.3: "The run increments `promotion_epoch` and the program's `version` exactly once, and returns the new `epoch`, the `offers_created` count, the `offered_entry_ids`, and `gross_free_after`."

        Design: Corner/endpoints/promotion_run_epoch_increments_on_empty_run
        """
        program, filler, waitlisted, entry = _program_with_filler_and_waitlisted(
            api, coordinator_headers
        )
        validate_success(
            api.disenroll_participant(filler["id"], {"reason": "moved"}, coordinator_headers)
        )
        run1 = run_promotion(program["id"])
        assert run1["epoch"] == 1
        assert run1["offers_created"] == 1
        assert run1["offered_entry_ids"] == [entry["id"]]
        # The entry is OFFERED now; a second run has no WAITING entries.
        run2 = run_promotion(program["id"])
        assert run2["epoch"] == 2
        assert run2["offers_created"] == 0
        assert run2["offered_entry_ids"] == []


class TestSurveyOnWaitlisted:
    def test_survey_on_waitlisted_participant_returns_not_enrolled(self, api, intake_headers, coordinator_headers):
        """PRD §3.5: "Creating one requires the participant to be `ENROLLED` — operations on schedules, assignments, and surveys all demand that status and fail with `ERR_PARTICIPANT_NOT_ENROLLED` otherwise —"
        PRD §3.9: "An `IntakeWorker` issues a survey to an enrolled participant for a `period_month` (a `YYYY-MM` string); at most one survey exists per participant per period, a duplicate failing with `ERR_SURVEY_PERIOD_DUPLICATE`."

        Design: Corner/errors/survey_on_waitlisted_participant_returns_not_enrolled
        """
        program, filler, waitlisted, entry = _program_with_filler_and_waitlisted(
            api, coordinator_headers
        )
        resp = api.issue_satisfaction_survey(
            waitlisted["id"], {"period_month": "2026-08"}, intake_headers
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ENROLLED, 409)


class TestWaitlistPriorityMultifactorRanking:
    """HIGH/APS/10-day/alone (155) outranks HIGH/HOSPITAL_DISCHARGE/11-day
    (132) who entered a day earlier, and MODERATE/SELF/12-day (74).

    All three entrants are non-CRITICAL so every entrant is gated by the same
    non-critical budget: with gross free 1 and reserve 0 the budget is exactly
    1, which makes "exactly one offer, to the top-ranked entry" the only
    outcome the PRD pins (§3.3 defines CRITICAL offers against gross free
    capacity and non-critical offers against the budget without stating
    whether a CRITICAL offer also decrements the budget — a CRITICAL entrant
    here would make the offer count depend on that unpinned reading)."""

    def _setup_three_waitlisted(self, api, coordinator_headers):
        program = create_program(total_capacity=1, max_reserve_slots=0)
        filler = enroll_participant({"full_name": "Fill"}, {"accepts_24h": True})
        # PC: MODERATE/SELF, waitlisted at 2026-08-01 (score 74 at run time).
        pc = create_applicant(
            full_name="PC", age_band="AGE_75_84", lives_alone=False, mobility="LIMITED",
            chronic_conditions_count=3, recent_hospitalization=True,
        )
        add_emergency_contact(pc["id"])
        submit_for_review(pc["id"])
        approve_participant(pc["id"])
        # PB: HIGH/HOSPITAL_DISCHARGE (65), waitlisted at 2026-08-02 (score 132).
        set_clock("2026-08-02T00:00:00Z")
        pb = create_applicant(
            full_name="PB", date_of_birth="1941-03-02", referral_source="HOSPITAL_DISCHARGE",
            age_band="AGE_85_PLUS", lives_alone=False, mobility="LIMITED",
            cognitive_concern=True, chronic_conditions_count=3,
        )
        add_emergency_contact(pb["id"], accepts_24h=True)
        submit_for_review(pb["id"])
        approve_participant(pb["id"])
        # PA: HIGH/APS_REFERRAL/lives_alone (75), waitlisted at 2026-08-03 (155).
        set_clock("2026-08-03T00:00:00Z")
        pa = create_applicant(
            full_name="PA", date_of_birth="1936-03-03", referral_source="APS_REFERRAL",
            age_band="AGE_85_PLUS", lives_alone=True, mobility="LIMITED",
            cognitive_concern=True, chronic_conditions_count=0,
        )
        add_emergency_contact(pa["id"], accepts_24h=True)
        submit_for_review(pa["id"])
        approve_participant(pa["id"])
        set_clock("2026-08-13T09:00:00Z")
        validate_success(
            api.disenroll_participant(filler["id"], {"reason": "moved away"}, coordinator_headers)
        )
        set_clock("2026-08-13T10:00:00Z")
        entries = {p["id"]: get_waitlist_entry_of(p["id"]) for p in (pa, pb, pc)}
        return program, pa, pb, pc, entries

    def test_highest_scored_late_entrant_wins_the_offer(self, api, coordinator_headers):
        """PRD §3.3: "Then it scores every `WAITING` entry with a raw score: tier points — 100 for `CRITICAL`, 70 for `HIGH`, 40 for `MODERATE`, 10 for `LOW`, taken from the participant's intake `acuity_tier` — plus source points — 50 for `APS_REFERRAL`, 40 for `HOSPITAL_DISCHARGE`, 30 for `OTHER_PROVIDER`, 20 for `FAMILY`, 10 for `SELF` — plus 2 points per whole day waited, counting at most thirty days between `waitlist_entered_at` and the clock, plus a 15-point bonus when the participant lives alone."
        PRD §3.3: "Entries are ranked by final score descending, ties broken by `waitlist_entered_at` ascending and then by the participant's `created_at` ascending — never by identifier."

        Design: Difficulty/combinatorial_formula/waitlist_priority_multifactor_ranking
        """
        program, pa, pb, pc, entries = self._setup_three_waitlisted(api, coordinator_headers)
        result = run_promotion(program["id"])
        assert result["offers_created"] == 1
        assert result["offered_entry_ids"] == [entries[pa["id"]]["id"]]
        entry_pa = validate_success(
            api.get_waitlist_entry(entries[pa["id"]]["id"], coordinator_headers)
        )
        assert entry_pa["status"] == "OFFERED"
        assert entry_pa["priority_score_at_offer"] == 155, (
            "70 HIGH + 50 APS_REFERRAL + 2*min(10,30) days + 15 lives-alone = 155"
        )

    def test_earlier_entrants_with_lower_scores_stay_waiting(self, api, coordinator_headers):
        """PRD §3.3: "Entries are ranked by final score descending, ties broken by `waitlist_entered_at` ascending and then by the participant's `created_at` ascending — never by identifier."
        PRD §3.3: "Entries beyond the offer window stay `WAITING`."

        Design: Difficulty/combinatorial_formula/waitlist_priority_multifactor_ranking
        """
        program, pa, pb, pc, entries = self._setup_three_waitlisted(api, coordinator_headers)
        run_promotion(program["id"])
        # PB entered a day before PA but scores 132 < 155; pure FIFO over the
        # single non-critical budget slot would have offered PC (earliest entry).
        entry_pb = validate_success(
            api.get_waitlist_entry(entries[pb["id"]]["id"], coordinator_headers)
        )
        entry_pc = validate_success(
            api.get_waitlist_entry(entries[pc["id"]]["id"], coordinator_headers)
        )
        assert entry_pb["status"] == "WAITING"
        assert entry_pb.get("priority_score_at_offer") is None
        assert entry_pc["status"] == "WAITING"
        assert entry_pc.get("priority_score_at_offer") is None


class TestCapacityReserveEvaluationOrder:
    """Total 3, reserve 2; one CRITICAL waiting -> reserve 1; a MODERATE
    applicant is blocked while a CRITICAL applicant at the same instant is
    admitted into the reserved slot."""

    def _setup_reserve_scenario(self, api, coordinator_headers):
        program = create_program(total_capacity=3, max_reserve_slots=2)
        fillers = []
        for i in range(3):
            fillers.append(enroll_participant({"full_name": f"F{i+1}"}))
        # PC1 (CRITICAL) approved while the program is full -> WAITLISTED.
        pc1 = create_applicant(
            full_name="PC1", date_of_birth="1936-05-04", referral_source="APS_REFERRAL",
            age_band="AGE_85_PLUS", lives_alone=True, mobility="SEVERE",
            cognitive_concern=True, chronic_conditions_count=3, recent_hospitalization=True,
        )
        add_emergency_contact(pc1["id"], accepts_24h=True)
        submit_for_review(pc1["id"])
        pc1_after = approve_participant(pc1["id"])
        assert pc1_after["status"] == "WAITLISTED"
        # Free one slot: occupied 2, gross_free 1, critical_waiting 1, reserve 1.
        validate_success(
            api.disenroll_participant(fillers[2]["id"], {"reason": "deceased"}, coordinator_headers)
        )
        return program, pc1

    def test_moderate_blocked_by_reserved_slot(self, api, coordinator_headers):
        """PRD §3.2: "The system reads `occupied_slots`, computes gross free capacity as `total_capacity` minus occupied (the reserve is not subtracted at this point), counts `critical_waiting` — the `WAITING` waitlist entries whose participant's intake `acuity_tier` is `CRITICAL` — and computes the reserve as the smaller of `max_reserve_slots` and `critical_waiting`."
        PRD §3.2: "A `CRITICAL` applicant is admitted when gross free capacity is at least 1, and may draw on reserved slots; an applicant of any other tier is admitted when gross free capacity minus the reserve is at least 1, so the reserve genuinely protects critical-only capacity."

        Design: Difficulty/combinatorial_formula/capacity_reserve_evaluation_order
        """
        program, pc1 = self._setup_reserve_scenario(api, coordinator_headers)
        # PM1: MODERATE (10 age + 25 alone + 10 mobility + 10 chronic = 55).
        pm1 = create_applicant(
            full_name="PM1", date_of_birth="1946-05-05", age_band="AGE_75_84",
            lives_alone=True, mobility="LIMITED", chronic_conditions_count=2,
        )
        add_emergency_contact(pm1["id"])
        submit_for_review(pm1["id"])
        pm1_after = approve_participant(pm1["id"])
        assert pm1_after["status"] == "WAITLISTED", (
            "gross_free 1 - reserve 1 = 0 < 1 blocks a non-CRITICAL applicant"
        )

    def test_critical_admitted_into_reserved_slot(self, api, coordinator_headers):
        """PRD §3.2: "A `CRITICAL` applicant is admitted when gross free capacity is at least 1, and may draw on reserved slots; an applicant of any other tier is admitted when gross free capacity minus the reserve is at least 1, so the reserve genuinely protects critical-only capacity."
        PRD §3.2: "The apparently circular dependency — the reserve depends on waiting tiers, and tier-aware admission depends on the reserve — dissolves because the reserve reads only the raw intake tiers of entries already waiting, never the applicant under decision."

        Design: Difficulty/combinatorial_formula/capacity_reserve_evaluation_order
        """
        program, pc1 = self._setup_reserve_scenario(api, coordinator_headers)
        pc2 = create_applicant(
            full_name="PC2", date_of_birth="1936-05-06", referral_source="FAMILY",
            age_band="AGE_85_PLUS", lives_alone=True, mobility="SEVERE",
            cognitive_concern=True, chronic_conditions_count=3, recent_hospitalization=True,
        )
        add_emergency_contact(pc2["id"], accepts_24h=True)
        submit_for_review(pc2["id"])
        pc2_after = approve_participant(pc2["id"])
        assert pc2_after["status"] == "ENROLLED", (
            "gross_free 1 >= 1 admits a CRITICAL applicant into the reserved slot"
        )
        program_after = get_program(program["id"])
        assert program_after["occupied_slots"] == 3


class TestCapacityAdmissionBoundary:
    def _setup_two_applicants(self, api):
        program = create_program(total_capacity=2, max_reserve_slots=0)
        filler = enroll_participant({"full_name": "F1"})
        p2 = create_applicant(full_name="P2")
        add_emergency_contact(p2["id"])
        submit_for_review(p2["id"])
        p3 = create_applicant(full_name="P3")
        add_emergency_contact(p3["id"])
        submit_for_review(p3["id"])
        return program, filler, p2, p3

    def test_admission_at_exactly_one_free_slot(self, api, intake_headers):
        """PRD §3.2: "A `CRITICAL` applicant is admitted when gross free capacity is at least 1, and may draw on reserved slots; an applicant of any other tier is admitted when gross free capacity minus the reserve is at least 1, so the reserve genuinely protects critical-only capacity."
        PRD §3.2: "An admitted applicant becomes `ENROLLED`: `occupied_slots` increases by one and the program's `version` increments, and `enrolled_at` and `last_status_change_at` are stamped."

        Design: Difficulty/boundary_precision_check/capacity_admission_at_exact_free_slot_boundary
        """
        program, filler, p2, p3 = self._setup_two_applicants(api)
        p2_after = approve_participant(p2["id"])
        assert p2_after["status"] == "ENROLLED", (
            "gross_free == 1 admits — the rule is >= 1, not > 1"
        )
        program_after = get_program(program["id"])
        assert program_after["occupied_slots"] == 2

    def test_admission_blocked_at_zero_free_slots(self, api, intake_headers):
        """PRD §3.2: "an applicant of any other tier is admitted when gross free capacity minus the reserve is at least 1"
        PRD §3.2: "A non-admitted applicant becomes `WAITLISTED`: a waitlist entry is created in status `WAITING` with `waitlist_entered_at` set to the clock, `waiting_count` increases by one, and `last_status_change_at` is stamped."

        Design: Difficulty/boundary_precision_check/capacity_admission_at_exact_free_slot_boundary
        """
        program, filler, p2, p3 = self._setup_two_applicants(api)
        approve_participant(p2["id"])  # takes the last free slot
        p3_after = approve_participant(p3["id"])
        assert p3_after["status"] == "WAITLISTED", "gross_free == 0 waitlists"
        program_after = get_program(program["id"])
        assert program_after["occupied_slots"] == 2
        assert program_after["waiting_count"] == 1


class TestOccupiedSlotsInvariant:
    def _setup_enrolled_and_waitlisted(self, api):
        program = create_program(total_capacity=1, max_reserve_slots=0)
        pa = enroll_participant({"full_name": "Inv A"})
        pb, entry = waitlist_applicant({"full_name": "Inv B"})
        return program, pa, pb, entry

    def test_suspend_resume_pair_conserves_occupied_slots(self, api, coordinator_headers):
        """PRD §2.8: "`occupied_slots` counts the participants whose status is `ENROLLED`, `SUSPENDED`, or `WELFARE_HOLD` — suspension and welfare hold do not free a slot."
        PRD §3.6: "The participant keeps occupying a program slot — `occupied_slots` does not change."

        Design: Difficulty/compensating_invariant/occupied_slots_conserved_across_suspend_resume_and_swap
        """
        program, pa, pb, entry = self._setup_enrolled_and_waitlisted(api)
        assert pb["status"] == "WAITLISTED"
        validate_success(
            api.suspend_participant(pa["id"], {"reason": "respite"}, coordinator_headers)
        )
        assert get_program(program["id"])["occupied_slots"] == 1, (
            "SUSPENDED still occupies a slot"
        )
        validate_success(api.resume_participant(pa["id"], coordinator_headers))
        assert get_program(program["id"])["occupied_slots"] == 1, (
            "resume leaves the count at its pre-pair value"
        )

    def test_disenroll_then_waitlist_accept_restores_slot_count(self, api, intake_headers, coordinator_headers):
        """PRD §2.8: "`occupied_slots` counts the participants whose status is `ENROLLED`, `SUSPENDED`, or `WELFARE_HOLD` — suspension and welfare hold do not free a slot."
        PRD §3.3: "On success the entry becomes `ACCEPTED`, the participant moves from `WAITLISTED` to `ENROLLED` with `enrolled_at` and `last_status_change_at` stamped, `occupied_slots` increases by one, `waiting_count` decreases by one, and the program's `version` increments."

        Design: Difficulty/compensating_invariant/occupied_slots_conserved_across_suspend_resume_and_swap
        """
        program, pa, pb, entry = self._setup_enrolled_and_waitlisted(api)
        validate_success(
            api.disenroll_participant(pa["id"], {"reason": "moved"}, coordinator_headers)
        )
        assert get_program(program["id"])["occupied_slots"] == 0
        run_promotion(program["id"])
        accepted = validate_success(api.accept_waitlist_entry(entry["id"], intake_headers))
        assert accepted["status"] == "ACCEPTED"
        program_after = get_program(program["id"])
        assert program_after["occupied_slots"] == 1, (
            "the disenroll+accept swap restores occupied_slots to exactly 1"
        )
        assert program_after["waiting_count"] == 0


class TestWaitlistOfferDeclineRequeueLoop:
    def _setup_offered_entry(self, api, coordinator_headers):
        program = create_program(total_capacity=1, max_reserve_slots=0)
        filler = enroll_participant({"full_name": "Fill"})
        pa, entry = waitlist_applicant({"full_name": "PA"})
        validate_success(
            api.disenroll_participant(filler["id"], {"reason": "moved"}, coordinator_headers)
        )
        run_promotion(program["id"])
        return program, pa, entry

    def test_decline_requeues_then_second_run_reoffers(self, api, intake_headers, coordinator_headers):
        """PRD §3.3: "Declining an offer returns the entry from `OFFERED` to `WAITING`: `declines_count` increments and the offer fields are cleared."
        PRD §3.3: "Each offered entry moves to `OFFERED` with `offered_at` set to the clock, `offer_expires_at` set to the clock plus the program's `offer_ttl_hours`, and `priority_score_at_offer` recording the final score."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_decline_requeue_loop
        """
        program, pa, entry = self._setup_offered_entry(api, coordinator_headers)
        st1 = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert st1["status"] == "OFFERED"
        declined = validate_success(api.decline_waitlist_entry(entry["id"], intake_headers))
        assert declined["status"] == "WAITING"
        assert declined["declines_count"] == 1, "decline requeues: OFFERED -> WAITING"
        run_promotion(program["id"])
        st3 = validate_success(api.get_waitlist_entry(entry["id"], intake_headers))
        assert st3["status"] == "OFFERED", "WAITING -> OFFERED again on the second run"

    def test_second_decline_removes_entry_and_exits_participant(self, api, intake_headers, coordinator_headers):
        """PRD §3.3: "When the increment reaches two declines, the entry is removed outright with `removal_reason` `MAX_DECLINES` and the participant exits the waitlist."
        PRD §3.3: "Every removal path moves the participant from `WAITLISTED` to `EXITED`, decrements `waiting_count`, and stamps `last_status_change_at` — the timestamp the reapplication clock later measures from."

        Design: Difficulty/non_linear_state_machine/waitlist_offer_decline_requeue_loop
        """
        program, pa, entry = self._setup_offered_entry(api, coordinator_headers)
        validate_success(api.decline_waitlist_entry(entry["id"], intake_headers))
        run_promotion(program["id"])
        removed = validate_success(api.decline_waitlist_entry(entry["id"], intake_headers))
        assert removed["status"] == "REMOVED"
        assert removed["declines_count"] == 2, "the boundary is exactly 2 declines"
        assert removed["removal_reason"] == "MAX_DECLINES"
        participant = validate_success(api.get_participant(pa["id"], intake_headers))
        assert participant["status"] == "EXITED"
