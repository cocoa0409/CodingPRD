"""Lifecycle transitions: where a record starts, which moves are admissible from
each state, and what a terminal state refuses.
"""

from test_helpers import ApiErrorId, PAYROLL_ANALYST, STAFFING_OFFICER
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success


# ---------------------------------------------------------------------------
# Duty shift: DRAFT
# ---------------------------------------------------------------------------
class TestDutyShiftOpensInDraft:
    """Opening a shift commits to a date and a platoon, and to nothing else."""

    def test_a_newly_opened_shift_is_a_draft_with_no_vacancies(self, api):
        """Creation lands in DRAFT with the counters at their opening values.

        PRD 3.2: "The shift is created in `DRAFT` with `ops_run_index` at zero,
        `closed_apparatus_ids` empty and `assigned_headcount` at zero, and with
        `required_staffing`, `leave_floor_headcount` and `staffing_posture`
        already computed from the station's open companies."

        Design: Corner/state_machines/duty_shift_initial_state_is_draft
        """
        station = fx.create_station(
            api,
            name="Station 71",
            battalion_code="D4",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-71",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )

        shift = validate_success(
            api.create_duty_shift(
                {
                    "station_id": station["id"],
                    "shift_date": "2026-08-11",
                    "platoon": "C",
                },
                STAFFING_OFFICER,
            ),
            201,
        )

        assert shift["status"] == "DRAFT"
        assert shift["ops_run_index"] == 0
        assert shift["open_vacancy_count"] == 0
        assert shift["closed_apparatus_ids"] == []
        assert shift["version"] == 1

        # No seat plan has been committed, so no vacancy row exists yet.
        rows, meta = validate_paginated(
            api.list_vacancies(STAFFING_OFFICER, duty_shift_id=shift["id"])
        )
        assert rows == []
        assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Duty shift: publication
# ---------------------------------------------------------------------------
class TestPublication:
    """Publication materialises the seat plan and picks its destination state."""

    def test_publishing_mints_one_vacancy_per_open_seat_and_moves_to_hiring(self, api):
        """Three open seats across two companies become three OPEN vacancies.

        PRD 3.2: "Publication recomputes `required_staffing` and then
        **materialises every unfilled seat as a vacancy row**, in a deterministic
        order that a list read can reproduce."

        Design: Corner/state_machines/publish_moves_draft_shift_to_hiring_and_mints_one_vacancy_per_seat
        """
        station = fx.create_station(
            api,
            name="Station 72",
            battalion_code="D5",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-72",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        medic = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="MEDIC-72",
            apparatus_type="MEDIC",
            minimum_crew_size=1,
            required_certifications=["PARAMEDIC"],
            closure_priority=20,
        )
        draft = fx.create_duty_shift(api, station["id"], "2026-08-11", "C")

        published = validate_success(
            api.publish_duty_shift(draft["id"], STAFFING_OFFICER), 200
        )

        assert published["status"] == "HIRING"
        assert published["required_staffing"] == 3
        assert published["open_vacancy_count"] == 3
        assert published["staffing_gap"] == 3
        assert published["certification_gap_count"] == 1
        assert published["staffing_posture"] == "CRITICAL"
        assert published["version"] == 2

        rows, meta = validate_paginated(
            api.list_vacancies(STAFFING_OFFICER, duty_shift_id=draft["id"])
        )
        assert meta["total_count"] == 3
        assert all(row["status"] == "OPEN" for row in rows)
        assert all(row["driver"] == "VACANT_POSITION" for row in rows)

        paramedic_seats = [
            row for row in rows if row["required_certification"] == "PARAMEDIC"
        ]
        assert len(paramedic_seats) == 1
        assert paramedic_seats[0]["apparatus_id"] == medic["id"]

        plain_seats = [row for row in rows if row["required_certification"] == "NONE"]
        assert len(plain_seats) == 2
        assert all(row["apparatus_id"] == engine["id"] for row in plain_seats)

    def test_publishing_a_station_with_no_open_company_lands_directly_in_staffed(
        self, api
    ):
        """With nothing to crew, publication takes the zero-vacancy branch.

        PRD 3.2: "if `open_vacancy_count` came out greater than zero the shift
        moves `DRAFT → HIRING`, and if it came out at zero — every seat already
        carrying a `SCHEDULED` assignment — the shift moves `DRAFT → STAFFED`
        directly."

        Design: Corner/state_machines/publish_of_shift_with_no_open_companies_goes_straight_to_staffed
        """
        station = fx.create_station(
            api,
            name="Station 73",
            battalion_code="D5",
            minimum_staffing_floor=0,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        # An out-of-service company contributes nothing to the requirement.
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-73",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
            status="OUT_OF_SERVICE",
        )
        draft = fx.create_duty_shift(api, station["id"], "2026-08-11", "C")

        published = fx.publish_shift(api, draft["id"])

        assert published["status"] == "STAFFED"
        assert published["status"] != "HIRING"
        assert published["required_staffing"] == 0
        assert published["staffing_gap"] == 0
        assert published["certification_gap_count"] == 0
        assert published["open_vacancy_count"] == 0
        assert published["leave_floor_headcount"] == 0
        assert published["staffing_posture"] == "FULLY_STAFFED"

        _, meta = validate_paginated(
            api.list_vacancies(STAFFING_OFFICER, duty_shift_id=draft["id"])
        )
        assert meta["total_count"] == 0

    def test_publishing_twice_is_refused_and_mints_no_second_seat_plan(self, api):
        """The second publish is not idempotent; it is rejected outright.

        PRD 3.2: "Publishing the shift is the moment the department commits to a
        seat plan, and it is admissible only from `DRAFT` — a second attempt is
        refused with `ERR_SHIFT_NOT_DRAFT`."

        Design: Corner/state_machines/republish_of_already_published_shift_rejected
        """
        station = fx.create_station(
            api,
            name="Station 74",
            battalion_code="D5",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-74",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        draft = fx.create_duty_shift(api, station["id"], "2026-08-11", "C")
        published = fx.publish_shift(api, draft["id"])

        response = api.publish_duty_shift(draft["id"], STAFFING_OFFICER)

        validate_error(response, ApiErrorId.SHIFT_NOT_DRAFT.value, 409)

        after = fx.read_shift(api, draft["id"])
        assert after["status"] == "HIRING"
        assert after["open_vacancy_count"] == 1
        assert after["version"] == published["version"]

        _, meta = validate_paginated(
            api.list_vacancies(STAFFING_OFFICER, duty_shift_id=draft["id"])
        )
        assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Duty shift: close-out
# ---------------------------------------------------------------------------
def _staffed_shift_ten_days_out(api, station_name, unit, member_name):
    """One member seated REGULAR on a published shift the clock has not reached."""
    station = fx.create_station(
        api,
        name=station_name,
        battalion_code="D6",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation=unit,
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name=member_name,
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    seat = fx.seat_member(api, shift["id"], member["id"], engine["id"], member["id"])
    return {"station": station, "member": member, "shift": shift, "seat": seat}


class TestCloseOutRequiresAnElapsedShift:
    """Payroll may not close out a tour that has not happened yet."""

    def test_completing_a_future_shift_is_refused_and_nothing_is_stamped(self, api):
        """The shift date must be at or before the clock's calendar date.

        PRD 3.9: "It is admissible from `HIRING` or `STAFFED`, else
        `ERR_SHIFT_NOT_HIRING`, and only once the shift has elapsed: its
        `shift_date` must be on or before the logical clock's calendar date, else
        `ERR_SHIFT_NOT_ELAPSED`."

        Design: Corner/state_machines/complete_before_shift_date_elapsed_rejected
        """
        world = _staffed_shift_ten_days_out(api, "Station 75", "ENGINE-75", "V Vogel")

        response = api.complete_duty_shift(world["shift"]["id"], PAYROLL_ANALYST)

        validate_error(response, ApiErrorId.SHIFT_NOT_ELAPSED.value, 409)

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "STAFFED"

        seat = fx.read_assignment(api, world["seat"]["id"])
        assert seat["status"] == "SCHEDULED"
        assert seat["actual_hours"] is None

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_actual_cents"] == 0


def _completed_shift(api):
    """A tour that has elapsed and been closed out by payroll."""
    world = _staffed_shift_ten_days_out(api, "Station 76", "ENGINE-76", "W Weiss")
    fx.set_clock(api, "2026-08-12T00:00:00Z")
    fx.complete_shift(api, world["shift"]["id"])
    return world


class TestCompletedShiftIsLockedDown:
    """COMPLETED is terminal: neither the seats nor the shift accept further work."""

    def test_a_worked_seat_can_no_longer_be_cancelled(self, api):
        """Un-seating checks the seat's own state before the shift's.

        PRD 3.3: "It is admissible only on a seat still in `SCHEDULED` (else
        `ERR_ASSIGNMENT_NOT_SCHEDULED`) belonging to a shift in `HIRING` or
        `STAFFED` (else `ERR_SHIFT_NOT_HIRING`), and it is refused with
        `ERR_STAFFING_FLOOR_BREACH` when removing the body would drop
        `assigned_headcount` below the shift's `leave_floor_headcount`."

        Design: Corner/state_machines/completed_shift_locks_seat_cancellation_and_further_ops_runs
        """
        world = _completed_shift(api)

        response = api.cancel_shift_assignment(
            world["seat"]["id"],
            {"reason": "attempt to unwind a closed-out tour"},
            fx.make_company_officer_headers(world["member"]["id"]),
        )

        validate_error(response, ApiErrorId.ASSIGNMENT_NOT_SCHEDULED.value, 409)

        seat = fx.read_assignment(api, world["seat"]["id"])
        assert seat["status"] == "WORKED"
        assert seat["actual_hours"] == 24

    def test_no_further_ops_run_checkpoint_is_admissible(self, api):
        """The housekeeping checkpoint requires a live shift.

        PRD 3.7: "The `StaffingOfficer` drives the clock forward with an ops-run
        checkpoint against a shift — a housekeeping operation admissible on any
        shift in `HIRING` or `STAFFED`, else `ERR_SHIFT_NOT_HIRING`, which leaves
        a `HIRING` shift in `HIRING` and a `STAFFED` shift in `STAFFED` unless the
        work it does moves the shift itself."

        Design: Corner/state_machines/completed_shift_locks_seat_cancellation_and_further_ops_runs
        """
        world = _completed_shift(api)

        response = api.staffing_run(world["shift"]["id"], STAFFING_OFFICER)

        validate_error(response, ApiErrorId.SHIFT_NOT_HIRING.value, 409)

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "COMPLETED"
        assert shift["ops_run_index"] == 0

        # A REGULAR seat carries no overtime premium, so nothing was posted.
        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_actual_cents"] == 0


# ---------------------------------------------------------------------------
# Overtime offer: answered once, and only once
# ---------------------------------------------------------------------------
class TestOfferAnsweredOnlyOnce:
    """An accepted offer is terminal, so a change of mind is refused."""

    def test_a_second_response_is_refused_and_no_second_hire_appears(self, api):
        """The offer must still be pending for a response to be admissible.

        PRD 3.7: "The offer must be in `OFFERED` status, else
        `ERR_OFFER_NOT_PENDING`, on a shift in `HIRING` or `STAFFED`, else
        `ERR_SHIFT_NOT_HIRING`."

        Design: Corner/state_machines/second_response_to_an_answered_offer_rejected
        """
        station = fx.create_station(
            api,
            name="Station 77",
            battalion_code="D7",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-77",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="X Xiong",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
        hired = fx.hire_into_vacancy(api, vacancy["id"], member["id"], "VOLUNTARY", 24)

        response = api.respond_to_offer(
            hired["offer"]["id"],
            {"response": "DECLINE"},
            fx.make_firefighter_headers(member["id"]),
        )

        validate_error(response, ApiErrorId.OFFER_NOT_PENDING.value, 409)

        offer = fx.read_offer(api, hired["offer"]["id"])
        assert offer["status"] == "ACCEPTED"
        assert offer["projected_cost_cents"] == 144000

        assert fx.read_vacancy(api, vacancy["id"])["status"] == "FILLED"
        _, meta = validate_paginated(
            api.list_shift_assignments(
                STAFFING_OFFICER, source_offer_id=hired["offer"]["id"]
            )
        )
        assert meta["total_count"] == 1

        # The encumbrance moved once, from the offer to the seat.
        station_after = fx.read_station(api, station["id"])
        assert station_after["ot_committed_cents"] == 144000

        member_after = fx.read_firefighter(api, member["id"])
        assert member_after["voluntary_ot_hours_charged"] == 24
        assert member_after["ot_pass_count"] == 0


# ---------------------------------------------------------------------------
# Leave request: revocation is defined only from APPROVED
# ---------------------------------------------------------------------------
class TestQueuedLeaveIsNotRevocable:
    """Withdrawing an undecided request is not the revocation path."""

    def test_revoking_a_queued_request_is_refused_and_decides_nothing(self, api):
        """Only an approved request may be revoked.

        PRD 3.4: "Only the owning member may revoke, and only a request in
        `APPROVED` status — anything else is `ERR_LEAVE_NOT_REVOCABLE` — on a
        shift still in `HIRING` or `STAFFED`, else `ERR_SHIFT_NOT_HIRING`."

        Design: Corner/state_machines/revoke_of_queued_leave_rejected_as_not_revocable
        """
        station = fx.create_station(
            api,
            name="Station 78",
            battalion_code="D7",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-78",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="Y Yoon",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        seat = fx.seat_member(api, shift["id"], member["id"], engine["id"], member["id"])
        leave = fx.file_leave(api, member["id"], shift["id"], "VACATION", 24)

        response = api.revoke_leave_request(
            leave["id"], fx.make_firefighter_headers(member["id"])
        )

        validate_error(response, ApiErrorId.LEAVE_NOT_REVOCABLE.value, 409)

        after = fx.read_leave(api, leave["id"])
        assert after["status"] == "QUEUED"
        assert after["decision_order_index"] is None
        assert after["denial_reason"] is None
        assert after["backfill_vacancy_id"] is None

        assert fx.read_assignment(api, seat["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Trade request: the decision needs a countersignature first
# ---------------------------------------------------------------------------
class TestTradeDecisionRequiresCountersignature:
    """An officer cannot approve a trade the taker has not accepted."""

    def test_deciding_a_still_proposed_trade_is_refused_and_moves_no_seat(self, api):
        """APPROVE is admissible only from COUNTERSIGNED.

        PRD 3.5: "It is admissible only from `COUNTERSIGNED`, else
        `ERR_TRADE_STATE_INVALID`, and an officer who is the requester or the
        counterparty is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/trade_decision_before_countersignature_rejected
        """
        station = fx.create_station(
            api,
            name="Station 79",
            battalion_code="D8",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-79",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        giver = fx.create_firefighter(
            api,
            station["id"],
            full_name="Z Zhao",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        taker = fx.create_firefighter(
            api,
            station["id"],
            full_name="A Ames",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="B Bass",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=3,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        seat = fx.seat_member(api, shift["id"], giver["id"], engine["id"], officer["id"])
        trade = fx.propose_trade(api, giver["id"], taker["id"], shift["id"])

        response = api.decide_trade_request(
            trade["id"],
            {"decision": "APPROVE", "note": "premature approval attempt"},
            fx.make_company_officer_headers(officer["id"]),
        )

        validate_error(response, ApiErrorId.TRADE_STATE_INVALID.value, 409)

        after = fx.read_trade(api, trade["id"])
        assert after["status"] == "PROPOSED"
        assert after["revision_count"] == 0
        assert after["decided_by_user_id"] is None
        assert after["traded_assignment_id"] is None

        assert fx.read_assignment(api, seat["id"])["firefighter_id"] == giver["id"]


# ---------------------------------------------------------------------------
# Ops-run checkpoint: the four normative steps
# ---------------------------------------------------------------------------
class TestOpsRunSweepsDueOffers:
    """Step one treats non-response exactly as a decline."""

    def test_an_offer_due_at_the_clock_expires_and_returns_its_seat(self, api):
        """The expiry comparison is inclusive, and the charge is the same as a pass.

        PRD 3.7: "Every offer on this shift still in `OFFERED` whose `expires_at`
        is at or before the logical clock — the comparison is inclusive, so an
        offer expiring exactly now expires — moves to `EXPIRED`, processed in
        order of `expires_at` ascending then `created_at` ascending."

        Design: Corner/state_machines/staffing_run_expires_stale_offer_and_reopens_the_vacancy
        """
        station = fx.create_station(
            api,
            name="Station 80",
            battalion_code="D8",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-80",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="C Colby",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
        offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)

        # The response window is two hours from the offer's creation instant.
        assert offer["expires_at"].startswith("2026-08-01T02:00:00")
        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 144000

        fx.set_clock(api, "2026-08-01T02:00:00Z")
        fx.run_staffing_checkpoint(api, shift["id"])

        assert fx.read_offer(api, offer["id"])["status"] == "EXPIRED"

        reopened = fx.read_vacancy(api, vacancy["id"])
        assert reopened["status"] == "OPEN"
        assert reopened["filled_by_assignment_id"] is None

        passed_over = fx.read_firefighter(api, member["id"])
        assert passed_over["voluntary_ot_hours_charged"] == 24
        assert passed_over["ot_pass_count"] == 1
        assert passed_over["pending_offer_count"] == 0
        assert passed_over["roster_standing"] == "AVAILABLE"

        credited = fx.read_station(api, station["id"])
        assert credited["ot_committed_cents"] == 0
        assert credited["budget_posture"] == "WITHIN"

        after = fx.read_shift(api, shift["id"])
        assert after["status"] == "HIRING"
        assert after["open_vacancy_count"] == 1
        assert after["ops_run_index"] == 1


class TestOpsRunRequeuesFloorDeniedLeave:
    """Step three fires only because step two saw a fully staffed shift."""

    def test_a_floor_denied_vacation_returns_to_the_queue(self, api):
        """The denial is reopened with its reason cleared.

        PRD 3.7: "If and only if the posture that step two produced is
        `FULLY_STAFFED`, every leave request on this shift in `DENIED` status
        returns to `QUEUED` with `denial_reason` cleared to null, retaining its
        `decision_order_index` until the next adjudication overwrites it."

        Design: Corner/state_machines/staffing_run_requeues_denied_leave_when_shift_is_fully_staffed
        """
        station = fx.create_station(
            api,
            name="Station 81",
            battalion_code="D9",
            minimum_staffing_floor=2,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-09-30",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-81",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        applicant = fx.create_firefighter(
            api,
            station["id"],
            full_name="D Dowd",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        crewmate = fx.create_firefighter(
            api,
            station["id"],
            full_name="E Ellis",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="F Farid",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=3,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        seat = fx.seat_member(
            api, shift["id"], applicant["id"], engine["id"], officer["id"]
        )
        fx.seat_member(api, shift["id"], crewmate["id"], engine["id"], officer["id"])
        leave = fx.file_leave(api, applicant["id"], shift["id"], "VACATION", 24)
        fx.adjudicate_leave(api, shift["id"], officer["id"])

        # Approving would have dropped the crew below the floor of two.
        denied = fx.read_leave(api, leave["id"])
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "STAFFING_FLOOR"
        assert denied["decision_order_index"] == 1

        fx.run_staffing_checkpoint(api, shift["id"])

        requeued = fx.read_leave(api, leave["id"])
        assert requeued["status"] == "QUEUED"
        assert requeued["denial_reason"] is None

        after = fx.read_shift(api, shift["id"])
        assert after["status"] == "STAFFED"
        assert after["staffing_posture"] == "FULLY_STAFFED"
        assert after["assigned_headcount"] == 2
        assert after["ops_run_index"] == 1

        # Requeueing decides nothing about the seat.
        assert fx.read_assignment(api, seat["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Mandatory holdover: no asking, no OFFERING state
# ---------------------------------------------------------------------------
def _mandatory_holdover_station(api):
    """A station whose only hiring roster compels a holdover, on a tiny budget."""
    station = fx.create_station(
        api,
        name="Station 82",
        battalion_code="E1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=100_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-82",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    # Platoon B is on duty on 2026-08-10, the day before the target shift.
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="G Gaines",
        platoon="B",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    roster = fx.create_hiring_roster(api, station["id"], "MANDATORY_HOLDOVER", "NONE")
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
    return {
        "station": station,
        "member": member,
        "roster": roster,
        "shift": shift,
        "vacancy": vacancy,
    }


class TestMandatoryHoldoverFillsInOneCall:
    """The mandated path creates the offer and the seat in the same request."""

    def test_one_dispatch_mints_a_mandated_offer_and_a_holdover_seat(self, api):
        """The offer is born MANDATED with no response window, and the seat exists.

        PRD 3.6: "For `MANDATORY_HOLDOVER` there is no asking: the offer is
        created directly in `MANDATED` status with `expires_at` null, and the seat
        is created in the same request."

        Design: Corner/state_machines/mandatory_holdover_offer_fills_the_seat_in_one_call
        """
        world = _mandatory_holdover_station(api)

        offer = validate_success(
            api.offer_vacancy(
                world["vacancy"]["id"],
                {"hiring_mode": "MANDATORY_HOLDOVER", "offer_hours": 24},
                STAFFING_OFFICER,
            ),
            201,
        )

        assert offer["status"] == "MANDATED"
        assert offer["hiring_mode"] == "MANDATORY_HOLDOVER"
        assert offer["expires_at"] is None
        assert offer["firefighter_id"] == world["member"]["id"]
        assert offer["roster_id"] == world["roster"]["id"]
        # 4000 cents, twenty-four payable hours, at time and a half.
        assert offer["projected_cost_cents"] == 144000

        assert fx.read_vacancy(api, world["vacancy"]["id"])["status"] == "FILLED"

        seats, meta = validate_paginated(
            api.list_shift_assignments(STAFFING_OFFICER, source_offer_id=offer["id"])
        )
        assert meta["total_count"] == 1
        assert seats[0]["assignment_type"] == "HOLDOVER"
        assert seats[0]["status"] == "SCHEDULED"
        assert seats[0]["scheduled_hours"] == 24

    def test_the_holdover_is_dispatched_even_though_it_busts_the_budget(self, api):
        """The labour agreement compels the seat, so the fiscal gate is skipped.

        PRD 3.6: "**Mandatory holdover skips step two entirely**: the labor
        agreement compels the seat to be filled, so a holdover is dispatched even
        when the encumbrance pushes the station's `budget_posture` to `OVER`."

        Design: Corner/state_machines/mandatory_holdover_offer_fills_the_seat_in_one_call
        """
        world = _mandatory_holdover_station(api)

        fx.dispatch_offer(api, world["vacancy"]["id"], "MANDATORY_HOLDOVER", 24)

        # 144000 cents against a 100000-cent budget is 14,400 basis points.
        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 144000
        assert station["budget_posture"] == "OVER"

        member = fx.read_firefighter(api, world["member"]["id"])
        assert member["mandatory_holdover_count"] == 1
        assert member["ot_pass_count"] == 0
        assert member["pending_offer_count"] == 0

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "STAFFED"
        assert shift["open_vacancy_count"] == 0
        assert shift["staffing_posture"] == "FULLY_STAFFED"
