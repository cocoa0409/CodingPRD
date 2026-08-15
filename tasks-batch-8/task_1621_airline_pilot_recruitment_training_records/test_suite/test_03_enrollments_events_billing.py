"""Enrollments, training-event scheduling rules, and cost billing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cost_ledger_entry,
    confirm_enrollment,
    enroll,
    get_applicant,
    get_enrollment,
    get_footprint,
    get_success_data,
    list_ledger_entries,
    make_cleared_applicant,
    make_equipment,
    make_instructor,
    make_open_class,
    make_simulator_slot,
    schedule_event,
    complete_event_at,
    set_clock,
    setup_enrollment_at_ioe_phase,
    setup_in_progress_enrollment,
    start_class,
    start_enrollment,
    validate_error,
    validate_success,
)

REC = TEST_USERS["recruiter_headers"]
TC = TEST_USERS["training_coordinator_headers"]
CS = TEST_USERS["crew_scheduler_headers"]


def _setup_sim_phase_with_first_booking(ev_s1_start="2026-08-11T09:00:00Z",
                                        ev_s1_end="2026-08-11T11:00:00Z",
                                        code="B788", sim_rate=55000):
    """Enrollment IN_PROGRESS at phase SIMULATOR; a slot 08:00-18:00 on
    2026-08-11 holding one SCHEDULED sim session taught by a SIMULATOR
    instructor. Returns ctx with equipment, applicant, training_class,
    enrollment, ground instructor, sim instructor, slot, first event."""
    ctx = setup_in_progress_enrollment(
        eq_kwargs={"code": code, "sim_rate": sim_rate, "ioe_hours": 10})
    ca1 = make_instructor("Deb Air", "CHECK_AIRMAN")
    ins_s = make_instructor("Edd Sim", "SIMULATOR")
    ev_gm = schedule_event(ctx["enrollment"]["id"], ca1["id"], "GROUND_SCHOOL",
                           "MILESTONE", "2026-08-10T10:00:00Z",
                           "2026-08-10T12:00:00Z")
    complete_event_at(ev_gm["id"], 88, "2026-08-10T10:00:00Z")
    ctx["enrollment"] = get_enrollment(ctx["enrollment"]["id"])
    assert ctx["enrollment"]["current_phase"] == "SIMULATOR"
    slot = make_simulator_slot(ctx["equipment"]["id"], "2026-08-11T08:00:00Z",
                               "2026-08-11T18:00:00Z")
    ev_s1 = schedule_event(ctx["enrollment"]["id"], ins_s["id"], "SIMULATOR",
                           "SESSION", ev_s1_start, ev_s1_end,
                           slot_id=slot["id"])
    ctx.update({"ground_instructor": ca1, "sim_instructor": ins_s,
                "slot": slot, "first_sim_event": ev_s1})
    return ctx


class TestPerLineRoundingBeforeSum:
    def _setup_two_half_cent_sim_sessions(self):
        """Equipment at 45,001 cents/hour; one GROUND SESSION, one GROUND
        MILESTONE, and two SIMULATOR SESSIONs of exactly 2.5h, all COMPLETED."""
        ctx = setup_in_progress_enrollment(
            eq_kwargs={"code": "E190", "sim_rate": 45001, "ioe_hours": 10},
            ap_kwargs={"email": "eli@x.com", "license_number": "L020",
                       "full_name": "Eli Ebb", "hours": 3100, "age": 30})
        ins_g = make_instructor("Hal Ground", "GROUND", daily_max=6)
        ins_s = make_instructor("Ivy Sim", "SIMULATOR", daily_max=6)
        en_id = ctx["enrollment"]["id"]
        ev_g = schedule_event(en_id, ins_g["id"], "GROUND_SCHOOL", "SESSION",
                              "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        complete_event_at(ev_g["id"], 91, "2026-08-10T10:00:00Z")
        ev_gm = schedule_event(en_id, ins_g["id"], "GROUND_SCHOOL", "MILESTONE",
                               "2026-08-10T13:00:00Z", "2026-08-10T15:00:00Z")
        complete_event_at(ev_gm["id"], 85, "2026-08-10T13:00:00Z")
        slot = make_simulator_slot(ctx["equipment"]["id"],
                                   "2026-08-11T08:00:00Z", "2026-08-11T18:00:00Z")
        ev_s1 = schedule_event(en_id, ins_s["id"], "SIMULATOR", "SESSION",
                               "2026-08-11T08:00:00Z", "2026-08-11T10:30:00Z",
                               slot_id=slot["id"])
        complete_event_at(ev_s1["id"], 90, "2026-08-11T08:00:00Z")
        ev_s2 = schedule_event(en_id, ins_s["id"], "SIMULATOR", "SESSION",
                               "2026-08-11T11:00:00Z", "2026-08-11T13:30:00Z",
                               slot_id=slot["id"])
        complete_event_at(ev_s2["id"], 87, "2026-08-11T11:00:00Z")
        ctx.update({"ev_s1": ev_s1, "ev_s2": ev_s2})
        return ctx

    def test_each_sim_line_rounds_half_up_before_summing(self, api):
        """PRD §2.7: "Every billable line is rounded half-up to integer cents
        first, and only then are lines summed — summing unrounded lines and
        rounding once at the end is explicitly not the algorithm, and the two
        orders can yield different totals."
        PRD §3.8: "A simulator event bills its duration — the exact elapsed
        time between `scheduled_start` and `scheduled_end`, expressed in hours
        as an exact decimal — multiplied by the fleet's
        `simulator_cost_per_hour_cents`, as a `SIMULATOR` entry."

        Design: Difficulty/combinatorial_formula/footprint_per_line_rounding_before_sum
        """
        ctx = self._setup_two_half_cent_sim_sessions()
        for key in ("ev_s1", "ev_s2"):
            event = validate_success(
                api.get_training_event(ctx[key]["id"], TC))
            # 2.5h * 45001 = 112502.5 -> round_half_up -> 112503 per line
            assert event["billed_amount_cents"] == 112503, (
                "Each 2.5-hour line rounds half-up to 112,503 cents")

    def test_footprint_total_uses_per_line_rounded_sum(self, api):
        """PRD §2.7: "Every billable line is rounded half-up to integer cents
        first, and only then are lines summed — summing unrounded lines and
        rounding once at the end is explicitly not the algorithm, and the two
        orders can yield different totals."
        PRD §3.8: "A ground-school event, completed or failed, bills a flat
        150,000 cents per session as a `GROUND_SCHOOL` entry."
        PRD §3.8: "The provisional variant is the as-booked net: the signed sum
        of all of the applicant's ledger entries, so a withdrawn pilot's
        reversals net their charges back to zero."

        Design: Difficulty/combinatorial_formula/footprint_per_line_rounding_before_sum
        """
        ctx = self._setup_two_half_cent_sim_sessions()
        footprint = get_footprint(ctx["applicant"]["id"])
        # 150000 (SESSION) + 150000 (MILESTONE) + 112503 + 112503
        assert footprint["provisional_total_cents"] == 525006, (
            "Per-line-then-sum yields 525,006; sum-then-round would yield "
            "525,005 — the pinned order is observable in the cents digit")
        assert footprint["entry_count"] == 4


class TestFootprintVariantsAfterWithdrawal:
    def _setup_trained_then_withdrawn(self):
        """One COMPLETED ground-school session (150,000) followed by an
        enrollment withdrawal that books the -150,000 REVERSAL."""
        ctx = setup_in_progress_enrollment(
            eq_kwargs={"code": "B737", "sim_rate": 45000, "ioe_hours": 10},
            ap_kwargs={"email": "dee@x.com", "license_number": "L010",
                       "full_name": "Dee Day", "hours": 2600, "age": 33})
        ins_g = make_instructor("Gus Ground", "GROUND", daily_max=6)
        ev = schedule_event(ctx["enrollment"]["id"], ins_g["id"],
                            "GROUND_SCHOOL", "SESSION",
                            "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        complete_event_at(ev["id"], 88, "2026-08-10T10:00:00Z")
        return ctx

    def test_provisional_variant_nets_to_zero_after_withdrawal(self, api):
        """PRD §3.8: "The provisional variant is the as-booked net: the signed
        sum of all of the applicant's ledger entries, so a withdrawn pilot's
        reversals net their charges back to zero."
        PRD §2.7: "Each applicant's `ledger_balance_cents` is the signed net
        sum of all of that applicant's ledger entries and is recomputed on
        every insert."

        Design: Difficulty/dual_variant_calc/footprint_provisional_vs_final_after_withdrawal
        """
        ctx = self._setup_trained_then_withdrawn()
        get_success_data(api.withdraw_enrollment(ctx["enrollment"]["id"], TC))
        footprint = get_footprint(ctx["applicant"]["id"])
        assert footprint["provisional_total_cents"] == 0, (
            "150000 charge + (-150000) reversal nets to zero")
        applicant = get_applicant(ctx["applicant"]["id"])
        assert applicant["ledger_balance_cents"] == 0
        assert footprint["entry_count"] == 2

    def test_final_variant_ignores_reversals_and_shows_consumption(self, api):
        """PRD §3.8: "The final variant recomputes gross consumption from
        source records and ignores `REVERSAL` rows entirely"
        PRD §3.8: "A withdrawn-but-partially-trained pilot therefore shows zero
        under the provisional variant and the true consumed cost under the
        final variant."

        Design: Difficulty/dual_variant_calc/footprint_provisional_vs_final_after_withdrawal
        """
        ctx = self._setup_trained_then_withdrawn()
        get_success_data(api.withdraw_enrollment(ctx["enrollment"]["id"], TC))
        footprint = get_footprint(ctx["applicant"]["id"], variant="final")
        assert footprint["final_total_cents"] == 150000, (
            "The COMPLETED session still contributes its rounded line")
        assert footprint["provisional_total_cents"] == 0
        assert footprint["provisional_total_cents"] != footprint[
            "final_total_cents"], "Same data, two valid algorithms, different money"


class TestChargeReversalInvariant:
    def _setup_two_billed_events(self):
        """GROUND SESSION (150,000), GROUND MILESTONE (150,000 flat), and a
        2-hour SIM SESSION (90,000) — all COMPLETED; balance 390,000."""
        ctx = setup_in_progress_enrollment(
            eq_kwargs={"code": "A346", "sim_rate": 45000, "ioe_hours": 10},
            ap_kwargs={"email": "mia@x.com", "license_number": "L350",
                       "full_name": "Mia Nox", "hours": 2900, "age": 30})
        ca1 = make_instructor("Nan Ope", "CHECK_AIRMAN")
        en_id = ctx["enrollment"]["id"]
        ev_g = schedule_event(en_id, ca1["id"], "GROUND_SCHOOL", "SESSION",
                              "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        complete_event_at(ev_g["id"], 95, "2026-08-10T10:00:00Z")
        ev_gm = schedule_event(en_id, ca1["id"], "GROUND_SCHOOL", "MILESTONE",
                               "2026-08-10T13:00:00Z", "2026-08-10T15:00:00Z")
        complete_event_at(ev_gm["id"], 82, "2026-08-10T13:00:00Z")
        slot = make_simulator_slot(ctx["equipment"]["id"],
                                   "2026-08-11T08:00:00Z", "2026-08-11T18:00:00Z")
        ev_s = schedule_event(en_id, ca1["id"], "SIMULATOR", "SESSION",
                              "2026-08-11T09:00:00Z", "2026-08-11T11:00:00Z",
                              slot_id=slot["id"])
        complete_event_at(ev_s["id"], 89, "2026-08-11T09:00:00Z")
        return ctx

    def test_withdrawal_returns_balance_to_pre_training_value(self, api):
        """PRD §3.3: "for every charge ledger entry of the enrollment not
        already reversed, a `REVERSAL` entry is inserted with the negated
        amount; the applicant's `ledger_balance_cents` is recomputed as the
        signed sum over all their entries"
        PRD §2.7: "Each applicant's `ledger_balance_cents` is the signed net
        sum of all of that applicant's ledger entries and is recomputed on
        every insert."

        Design: Difficulty/compensating_invariant/charge_reversal_pair_conserves_ledger_balance
        """
        ctx = self._setup_two_billed_events()
        pre = get_applicant(ctx["applicant"]["id"])
        assert pre["ledger_balance_cents"] == 390000, (
            "150000 + 150000 + 90000 consumed before withdrawal")

        get_success_data(api.withdraw_enrollment(ctx["enrollment"]["id"], TC))
        post = get_applicant(ctx["applicant"]["id"])
        assert post["ledger_balance_cents"] == 0, (
            "Charges +390,000 and REVERSAL entries -390,000 — no drift")

    def test_reversal_rows_exactly_mirror_the_charges(self, api):
        """PRD §3.3: "for every charge ledger entry of the enrollment not
        already reversed, a `REVERSAL` entry is inserted with the negated
        amount; the applicant's `ledger_balance_cents` is recomputed as the
        signed sum over all their entries"

        Design: Difficulty/compensating_invariant/charge_reversal_pair_conserves_ledger_balance
        """
        ctx = self._setup_two_billed_events()
        get_success_data(api.withdraw_enrollment(ctx["enrollment"]["id"], TC))
        reversals = list_ledger_entries(
            CS, enrollment_id=ctx["enrollment"]["id"], entry_type="REVERSAL")
        assert len(reversals) == 3, "One REVERSAL per billed line"
        assert sum(row["amount_cents"] for row in reversals) == -390000
        for row in reversals:
            assert_cost_ledger_entry(row)
        all_rows = list_ledger_entries(CS, applicant_id=ctx["applicant"]["id"])
        post = get_applicant(ctx["applicant"]["id"])
        assert post["ledger_balance_cents"] == sum(
            row["amount_cents"] for row in all_rows), (
            "The balance equals the signed sum over every ledger entry")


class TestSimulatorSlotHalfOpenAdjacency:
    def test_back_to_back_booking_at_end_boundary_allowed(self, api):
        """PRD §3.4: "it must not overlap any other `SCHEDULED` event in the
        same slot under half-open semantics, where one event's start may
        coincide with another's end and back-to-back adjacency is allowed;
        violations are rejected with `ERR_SLOT_TEMPORAL_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/simulator_slot_half_open_adjacency
        """
        ctx = _setup_sim_phase_with_first_booking()
        ins_s2 = make_instructor("Fio Sim", "SIMULATOR")
        resp = api.create_training_event(
            {"enrollment_id": ctx["enrollment"]["id"],
             "instructor_id": ins_s2["id"],
             "simulator_slot_id": ctx["slot"]["id"],
             "phase": "SIMULATOR", "event_type": "SESSION",
             "scheduled_start": "2026-08-11T11:00:00Z",
             "scheduled_end": "2026-08-11T13:00:00Z"}, TC)
        event = validate_success(resp, 201)
        assert event["status"] == "SCHEDULED", (
            "An 11:00 start touching the existing 11:00 end is not an overlap")

    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.4: "it must not overlap any other `SCHEDULED` event in the
        same slot under half-open semantics, where one event's start may
        coincide with another's end and back-to-back adjacency is allowed;
        violations are rejected with `ERR_SLOT_TEMPORAL_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/simulator_slot_half_open_adjacency
        """
        ctx = _setup_sim_phase_with_first_booking()
        ins_s3 = make_instructor("Geo Sim", "SIMULATOR")
        resp = api.create_training_event(
            {"enrollment_id": ctx["enrollment"]["id"],
             "instructor_id": ins_s3["id"],
             "simulator_slot_id": ctx["slot"]["id"],
             "phase": "SIMULATOR", "event_type": "SESSION",
             "scheduled_start": "2026-08-11T10:59:00Z",
             "scheduled_end": "2026-08-11T12:00:00Z"}, TC)
        validate_error(resp, ApiErrorId.ERR_SLOT_TEMPORAL_OVERLAP)


class TestInstructorBufferGapSemantics:
    def test_fifteen_minute_gap_rejected(self, api):
        """PRD §3.4: "The instructor separation buffer then requires any two
        non-cancelled events of the same instructor to sit at least 30 minutes
        apart end-to-start in either direction — mere non-overlap is not
        sufficient, and a gap of 0 to 29 minutes is rejected with
        `ERR_INSTRUCTOR_BUFFER_VIOLATION` (409)."

        Design: Difficulty/resource_temporal_overlap/instructor_buffer_gap_semantics
        """
        ctx = _setup_sim_phase_with_first_booking(code="B789")
        resp = api.create_training_event(
            {"enrollment_id": ctx["enrollment"]["id"],
             "instructor_id": ctx["sim_instructor"]["id"],
             "simulator_slot_id": ctx["slot"]["id"],
             "phase": "SIMULATOR", "event_type": "SESSION",
             "scheduled_start": "2026-08-11T11:15:00Z",
             "scheduled_end": "2026-08-11T13:00:00Z"}, TC)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_BUFFER_VIOLATION)

    def test_exactly_thirty_minute_gap_allowed(self, api):
        """PRD §3.4: "The instructor separation buffer then requires any two
        non-cancelled events of the same instructor to sit at least 30 minutes
        apart end-to-start in either direction — mere non-overlap is not
        sufficient, and a gap of 0 to 29 minutes is rejected with
        `ERR_INSTRUCTOR_BUFFER_VIOLATION` (409)."

        Design: Difficulty/resource_temporal_overlap/instructor_buffer_gap_semantics
        """
        ctx = _setup_sim_phase_with_first_booking(code="B789")
        resp = api.create_training_event(
            {"enrollment_id": ctx["enrollment"]["id"],
             "instructor_id": ctx["sim_instructor"]["id"],
             "simulator_slot_id": ctx["slot"]["id"],
             "phase": "SIMULATOR", "event_type": "SESSION",
             "scheduled_start": "2026-08-11T11:30:00Z",
             "scheduled_end": "2026-08-11T13:30:00Z"}, TC)
        event = validate_success(resp, 201)
        assert event["status"] == "SCHEDULED", "A 30-minute gap meets the buffer"


class TestSchedulingPriorityReferentialVsTemporal:
    def test_tier_failure_masks_slot_overlap(self, api):
        """PRD §3.4: "Next, the instructor tier must cover the phase —
        `GROUND_SCHOOL` events accept instructors of tier `GROUND` or
        `CHECK_AIRMAN`, `SIMULATOR` events accept `SIMULATOR` or `CHECK_AIRMAN`,
        and `IOE` and `CHECKRIDE` events accept only `CHECK_AIRMAN` — otherwise
        `ERR_INSTRUCTOR_NOT_QUALIFIED` (422). Temporal rules then run: a
        simulator event must be fully contained in its slot window with
        boundary equality allowed (the slot's `start_at` no later than
        `scheduled_start`, and `scheduled_end` no later than the slot's
        `end_at`), and it must not overlap any other `SCHEDULED` event in the
        same slot under half-open semantics, where one event's start may
        coincide with another's end and back-to-back adjacency is allowed;
        violations are rejected with `ERR_SLOT_TEMPORAL_OVERLAP` (409)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_event_creation
        """
        ctx = _setup_sim_phase_with_first_booking(code="E195", sim_rate=45000)
        ins_g2 = make_instructor("Wes Gnd", "GROUND")
        # Tier failure (GROUND cannot teach SIMULATOR) AND slot overlap
        # (10:00-12:00 vs 09:00-11:00) are both live; the tier rule runs first.
        resp = api.create_training_event(
            {"enrollment_id": ctx["enrollment"]["id"],
             "instructor_id": ins_g2["id"],
             "simulator_slot_id": ctx["slot"]["id"],
             "phase": "SIMULATOR", "event_type": "SESSION",
             "scheduled_start": "2026-08-11T10:00:00Z",
             "scheduled_end": "2026-08-11T12:00:00Z"}, TC)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_QUALIFIED)

    def test_slot_overlap_fires_when_tier_is_satisfied(self, api):
        """PRD §3.4: "Temporal rules then run: a simulator event must be fully
        contained in its slot window with boundary equality allowed (the slot's
        `start_at` no later than `scheduled_start`, and `scheduled_end` no
        later than the slot's `end_at`), and it must not overlap any other
        `SCHEDULED` event in the same slot under half-open semantics, where one
        event's start may coincide with another's end and back-to-back
        adjacency is allowed; violations are rejected with
        `ERR_SLOT_TEMPORAL_OVERLAP` (409)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_event_creation
        """
        ctx = _setup_sim_phase_with_first_booking(code="E195", sim_rate=45000)
        ins_s3 = make_instructor("Xan Sim", "SIMULATOR")
        # Only the overlap failure is live for a SIMULATOR-tier instructor.
        resp = api.create_training_event(
            {"enrollment_id": ctx["enrollment"]["id"],
             "instructor_id": ins_s3["id"],
             "simulator_slot_id": ctx["slot"]["id"],
             "phase": "SIMULATOR", "event_type": "SESSION",
             "scheduled_start": "2026-08-11T10:00:00Z",
             "scheduled_end": "2026-08-11T12:00:00Z"}, TC)
        validate_error(resp, ApiErrorId.ERR_SLOT_TEMPORAL_OVERLAP)


class TestEventAndEnrollmentBasics:
    def test_cost_ledger_entry_is_append_only(self, api):
        """PRD §2.5: "The single exception is the cost ledger: a
        `CostLedgerEntry` is append-only and carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from it."
        PRD §2.7: "a `provisional` flag that is always true for booked entries"

        Design: Corner/entities/cost_ledger_entry_is_append_only
        """
        ctx = setup_in_progress_enrollment(
            eq_kwargs={"code": "IM01", "sim_rate": 38000, "ioe_hours": 8},
            ap_kwargs={"email": "iml@x.com", "license_number": "L490",
                       "full_name": "Imm Ledger"})
        ins = make_instructor("Led Ger", "GROUND")
        ev = schedule_event(ctx["enrollment"]["id"], ins["id"], "GROUND_SCHOOL",
                            "SESSION", "2026-08-10T10:00:00Z",
                            "2026-08-10T12:00:00Z")
        complete_event_at(ev["id"], 90, "2026-08-10T10:00:00Z")

        rows = list_ledger_entries(CS, enrollment_id=ctx["enrollment"]["id"])
        assert len(rows) == 1, "One charge entry for the completed session"
        row = rows[0]
        assert_cost_ledger_entry(row)
        assert row["amount_cents"] == 150000
        assert row["entry_type"] == "GROUND_SCHOOL"

    def test_enrollment_second_confirm_rejected(self, api):
        """PRD §3.3: "From `TENTATIVE`, confirmation moves the enrollment to
        `CONFIRMED`."
        PRD §3.3: "Any enrollment action attempted from a disallowed state —
        including a start against a class not in session — is rejected with
        `ERR_ENROLLMENT_INVALID_STATE` (409)."

        Design: Corner/state_machines/enrollment_idempotent_second_confirm_rejected
        """
        eq = make_equipment(code="MD88", sim_rate=40000, ioe_hours=8)
        ap = make_cleared_applicant("ide@x.com", "L415", full_name="Ide Mpo")
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z")
        en = enroll(cls["id"], ap["id"])
        confirmed = confirm_enrollment(en["id"])
        assert confirmed["status"] == "CONFIRMED"
        resp = api.confirm_enrollment(en["id"], TC)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE)

    def test_milestone_score_boundary_79_vs_80(self, api):
        """PRD §3.4: "and when any milestone is completed with a score of at
        least 80, the enrollment's `current_phase` advances — `GROUND_SCHOOL` →
        `SIMULATOR`, `SIMULATOR` → `CHECKRIDE`, and `IOE` → `DONE` —
        incrementing the enrollment `version`."

        Design: Corner/state_machines/milestone_score_boundary_79_vs_80
        """
        eq = make_equipment(code="CRJ9", sim_rate=40000, ioe_hours=8)
        ap1 = make_cleared_applicant("sco1@x.com", "L417", full_name="Sco One")
        ap2 = make_cleared_applicant("sco2@x.com", "L418", full_name="Sco Two")
        cls = make_open_class(eq["id"], class_date="2026-08-10T00:00:00Z")
        en1 = enroll(cls["id"], ap1["id"])
        confirm_enrollment(en1["id"])
        en2 = enroll(cls["id"], ap2["id"])
        confirm_enrollment(en2["id"])
        set_clock("2026-08-10T09:00:00Z")
        start_class(cls["id"])
        start_enrollment(en1["id"])
        start_enrollment(en2["id"])
        ins = make_instructor("Gnd One", "GROUND")
        ev79 = schedule_event(en1["id"], ins["id"], "GROUND_SCHOOL",
                              "MILESTONE", "2026-08-10T10:00:00Z",
                              "2026-08-10T12:00:00Z")
        ev80 = schedule_event(en2["id"], ins["id"], "GROUND_SCHOOL",
                              "MILESTONE", "2026-08-10T13:00:00Z",
                              "2026-08-10T15:00:00Z")
        complete_event_at(ev79["id"], 79, "2026-08-10T10:00:00Z")
        complete_event_at(ev80["id"], 80, "2026-08-10T13:00:00Z")

        assert get_enrollment(en1["id"])["current_phase"] == "GROUND_SCHOOL", (
            "Score 79 < 80: milestone completed but the phase did not advance")
        assert get_enrollment(en2["id"])["current_phase"] == "SIMULATOR", (
            "Score 80 meets the >= 80 boundary and advances the phase")

    def test_ioe_hours_prerequisite_for_milestone(self, api):
        """PRD §3.4: "an IOE milestone may only be completed once the
        enrollment's cumulative hours across its `COMPLETED` IOE `SESSION`
        events reach the fleet's `ioe_hours_required`, otherwise the completion
        is rejected with `ERR_PHASE_PREREQUISITE_NOT_MET`"
        PRD §3.4: "and when any milestone is completed with a score of at least
        80, the enrollment's `current_phase` advances — `GROUND_SCHOOL` →
        `SIMULATOR`, `SIMULATOR` → `CHECKRIDE`, and `IOE` → `DONE` —
        incrementing the enrollment `version`."

        Design: Corner/validations/ioe_hours_prerequisite_for_milestone
        """
        ctx = setup_enrollment_at_ioe_phase(
            eq_kwargs={"code": "B733", "sim_rate": 38000, "ioe_hours": 10},
            ap_kwargs={"email": "ioe@x.com", "license_number": "L440",
                       "full_name": "Ioe Hrs"})
        en_id = ctx["enrollment"]["id"]
        ca1 = ctx["instructor"]
        # 5.0h + 4.5h = 9.5 COMPLETED IOE SESSION hours against a 10-hour gate
        io1 = schedule_event(en_id, ca1["id"], "IOE", "SESSION",
                             "2026-08-13T08:00:00Z", "2026-08-13T13:00:00Z")
        complete_event_at(io1["id"], 88, "2026-08-13T08:00:00Z")
        io2 = schedule_event(en_id, ca1["id"], "IOE", "SESSION",
                             "2026-08-14T08:00:00Z", "2026-08-14T12:30:00Z")
        complete_event_at(io2["id"], 88, "2026-08-14T08:00:00Z")
        iom = schedule_event(en_id, ca1["id"], "IOE", "MILESTONE",
                             "2026-08-15T08:00:00Z", "2026-08-15T10:00:00Z")

        set_clock("2026-08-15T08:00:00Z")
        resp = api.complete_training_event(iom["id"], {"score": 90}, TC)
        validate_error(resp, ApiErrorId.ERR_PHASE_PREREQUISITE_NOT_MET)

        # Top up 0.5h -> exactly 10.0 >= 10, then the milestone completes.
        io3 = schedule_event(en_id, ca1["id"], "IOE", "SESSION",
                             "2026-08-15T11:00:00Z", "2026-08-15T11:30:00Z")
        complete_event_at(io3["id"], 88, "2026-08-15T11:00:00Z")
        completed = validate_success(
            api.complete_training_event(iom["id"], {"score": 90}, TC))
        assert completed["status"] == "COMPLETED"
        assert get_enrollment(en_id)["current_phase"] == "DONE"

    def test_footprint_endpoint_defaults_to_provisional_variant(self, api):
        """PRD §3.8: "The training-footprint read answers "what has this pilot
        cost us?" in two variants selected by the `variant` query parameter,
        defaulting to `provisional`. The response carries `applicant_id`, the
        echoed `variant`, `provisional_total_cents`, `final_total_cents`, and
        `entry_count` — the number of ledger entries on the applicant's
        ledger."

        Design: Corner/endpoints/footprint_endpoint_defaults_to_provisional_variant
        """
        ap = make_cleared_applicant("ftp@x.com", "L453", full_name="Ft Print")
        footprint = get_footprint(ap["id"])
        assert footprint["variant"] == "provisional", (
            "The variant parameter defaults to provisional")
        assert footprint["provisional_total_cents"] == 0
        assert footprint["final_total_cents"] == 0
        assert footprint["entry_count"] == 0
        assert footprint["applicant_id"] == ap["id"]

    def test_slot_maintenance_blocked_by_bookings(self, api):
        """PRD §3.4: "Moving a slot into maintenance is blocked while any
        `SCHEDULED` training event sits inside its window — the attempt is
        rejected with `ERR_SLOT_HAS_BOOKINGS` (409) — while the return to
        available carries no such check."

        Design: Corner/errors/slot_maintenance_blocked_by_bookings
        """
        ctx = _setup_sim_phase_with_first_booking(code="FK03", sim_rate=38000)
        resp = api.toggle_simulator_slot_maintenance(ctx["slot"]["id"], TC)
        validate_error(resp, ApiErrorId.ERR_SLOT_HAS_BOOKINGS)

    def test_cancelled_event_bills_nothing(self, api):
        """PRD §3.4: "Cancellation moves `SCHEDULED` → `CANCELLED` and creates
        no ledger entry; `billed_amount_cents` stays 0."

        Design: Corner/cross_cutting_layers/cascade_cancelled_event_bills_nothing
        """
        ctx = setup_in_progress_enrollment(
            eq_kwargs={"code": "FK09", "sim_rate": 38000, "ioe_hours": 8},
            ap_kwargs={"email": "can@x.com", "license_number": "L473",
                       "full_name": "Can Cel"})
        ins = make_instructor("Gro Und Two", "GROUND")
        ev = schedule_event(ctx["enrollment"]["id"], ins["id"], "GROUND_SCHOOL",
                            "SESSION", "2026-08-12T10:00:00Z",
                            "2026-08-12T12:00:00Z")
        cancelled = validate_success(api.cancel_training_event(ev["id"], TC))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["billed_amount_cents"] == 0
        footprint = get_footprint(ctx["applicant"]["id"])
        assert footprint["provisional_total_cents"] == 0, (
            "No ledger entry exists for the cancelled event")
        assert footprint["entry_count"] == 0
