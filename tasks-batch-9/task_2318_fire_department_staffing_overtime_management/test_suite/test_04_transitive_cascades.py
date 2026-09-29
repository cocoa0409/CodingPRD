"""Multi-hop cascades: a leave approval that reaches the work period and the
shift, and a company closure that reaches the offer and the money ledger.
"""

from test_helpers import STAFFING_OFFICER, assert_version_incremented, fixtures as fx
from test_helpers import validate_success


# ---------------------------------------------------------------------------
# Leave approval cascade
# ---------------------------------------------------------------------------
def _fully_staffed_shift_with_one_queued_vacation(api):
    """A two-seat company at full crew with one discretionary request waiting."""
    station = fx.create_station(
        api,
        name="Station 47",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-47",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    leaver = fx.create_firefighter(
        api,
        station["id"],
        full_name="Q Quinlan",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4237,
    )
    stayer = fx.create_firefighter(
        api,
        station["id"],
        full_name="R Rossi",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="S Sowande",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    leaver_seat = fx.seat_member(api, shift["id"], leaver["id"], engine["id"], officer["id"])
    stayer_seat = fx.seat_member(api, shift["id"], stayer["id"], engine["id"], officer["id"])

    leave = fx.file_leave(api, leaver["id"], shift["id"], "VACATION", 24)

    return {
        "station": station,
        "engine": engine,
        "leaver": leaver,
        "stayer": stayer,
        "officer": officer,
        "shift": fx.read_shift(api, shift["id"]),
        "leaver_seat": leaver_seat,
        "stayer_seat": stayer_seat,
        "leave": leave,
        "period": fx.work_period_of(api, leaver["id"]),
    }


class TestLeaveApprovalCascade:
    """One approval relieves the seat, re-prices the period and re-opens the shift."""

    def test_batch_summary_reports_the_floor_the_batch_was_measured_against(self, api):
        """The adjudication response summarises the batch rather than the shift.

        PRD 3.4: "The adjudication response summarises the batch rather than
        returning a shift: it reports the `duty_shift_id` adjudicated, the
        `leave_floor_headcount` the batch was measured against, a
        `considered_count` of requests walked, `approved_count` and
        `denied_count`, the `approved_leave_request_ids` and
        `denied_leave_request_ids` in decision order, the
        `resulting_assigned_headcount` and `resulting_staffing_posture`, and the
        `created_vacancy_count`."

        Design: Difficulty/transitive_cascade/leave_approval_cascade_relieves_seat_reprices_period_reopens_shift
        """
        world = _fully_staffed_shift_with_one_queued_vacation(api)
        assert world["shift"]["status"] == "STAFFED"
        assert world["shift"]["leave_floor_headcount"] == 1

        summary = validate_success(
            api.leave_adjudication(
                world["shift"]["id"],
                fx.make_company_officer_headers(world["officer"]["id"]),
            ),
            200,
        )

        assert summary["duty_shift_id"] == world["shift"]["id"]
        assert summary["leave_floor_headcount"] == 1
        assert summary["considered_count"] == 1
        assert summary["approved_count"] == 1
        assert summary["denied_count"] == 0
        assert summary["approved_leave_request_ids"] == [world["leave"]["id"]]
        assert summary["denied_leave_request_ids"] == []
        assert summary["created_vacancy_count"] == 1
        assert summary["resulting_assigned_headcount"] == 1
        assert summary["resulting_staffing_posture"] == "SHORT"

    def test_approval_relieves_the_seat_reprices_the_period_and_reopens_the_shift(
        self, api
    ):
        """Hop one relieves the seat, hop two mints the backfill, hop three re-derives.

        PRD 3.4: "**Hop two**, caused by hop one: the covering work period's
        scheduled hours are reduced by the seat's `scheduled_hours` and
        re-priced, and a vacancy is created in `OPEN` status with `driver` set to
        `LEAVE`, `driver_source_id` set to the leave request's id, `apparatus_id`
        copied from the relieved seat, `required_certification` copied from the
        relieved seat's `seat_certification`, and a `seat_index` continuing that
        company's seat count for the shift; the leave request's
        `backfill_vacancy_id` is set to that vacancy."

        Design: Difficulty/transitive_cascade/leave_approval_cascade_relieves_seat_reprices_period_reopens_shift
        """
        world = _fully_staffed_shift_with_one_queued_vacation(api)

        fx.adjudicate_leave(api, world["shift"]["id"], world["officer"]["id"])

        leave = fx.read_leave(api, world["leave"]["id"])
        assert leave["status"] == "APPROVED"
        assert leave["decision_order_index"] == 1
        assert leave["denial_reason"] is None
        assert leave["backfill_vacancy_id"] is not None

        relieved = fx.read_assignment(api, world["leaver_seat"]["id"])
        assert relieved["status"] == "RELIEVED"
        assert relieved["relieved_by_leave_request_id"] == leave["id"]

        period = fx.read_work_period(api, world["period"]["id"])
        assert period["scheduled_hours"] == 0
        assert period["leave_hours"] == 24
        assert period["projected_flsa_overtime_hours"] == 0
        assert period["flsa_premium_cents"] == 0

        backfill = fx.read_vacancy(api, leave["backfill_vacancy_id"])
        assert backfill["status"] == "OPEN"
        assert backfill["driver"] == "LEAVE"
        assert backfill["driver_source_id"] == leave["id"]
        assert backfill["apparatus_id"] == world["engine"]["id"]
        assert backfill["required_certification"] == "NONE"

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "HIRING"
        assert shift["assigned_headcount"] == 1
        assert shift["staffing_gap"] == 1
        assert shift["open_vacancy_count"] == 1
        assert shift["certification_gap_count"] == 0
        assert shift["staffing_posture"] == "SHORT"

        untouched = fx.read_assignment(api, world["stayer_seat"]["id"])
        assert untouched["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Company closure cascade
# ---------------------------------------------------------------------------
def _critical_shift_with_an_outstanding_hazmat_offer(api):
    """A CRITICAL shift whose hazmat seat is out to offer, behind an exempt engine."""
    station = fx.create_station(
        api,
        name="Station 48",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-48",
        apparatus_type="ENGINE",
        minimum_crew_size=4,
        required_certifications=["PARAMEDIC"],
        closure_priority=10,
        closure_exempt=True,
    )
    hazmat = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="HAZMAT-48",
        apparatus_type="HAZMAT",
        minimum_crew_size=1,
        required_certifications=["HAZMAT_TECH"],
        closure_priority=20,
    )
    technician = fx.create_firefighter(
        api,
        station["id"],
        full_name="T Tanaka",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=["HAZMAT_TECH"],
        hourly_rate_cents=4237,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")

    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    hazmat_vacancy = fx.first_vacancy(
        api,
        duty_shift_id=shift["id"],
        status="OPEN",
        required_certification="HAZMAT_TECH",
    )
    offer = fx.dispatch_offer(api, hazmat_vacancy["id"], "VOLUNTARY", 24)
    assert offer["firefighter_id"] == technician["id"]

    return {
        "station": station,
        "engine": engine,
        "hazmat": hazmat,
        "technician": technician,
        "shift": fx.read_shift(api, shift["id"]),
        "hazmat_vacancy": hazmat_vacancy,
        "offer": offer,
    }


class TestCompanyClosureCascade:
    """Closure picks the non-exempt company and unwinds everything hanging off it."""

    def test_closure_takes_the_non_exempt_company_and_lowers_required_staffing(
        self, api
    ):
        """The exempt first-due engine is never the company that closes.

        PRD 3.8: "The candidate pool is the station's apparatus that are
        `IN_SERVICE`, are not `closure_exempt`, and do not already appear in the
        shift's `closed_apparatus_ids`."

        Design: Difficulty/transitive_cascade/company_closure_cascade_rescinds_offer_and_credits_encumbrance
        """
        world = _critical_shift_with_an_outstanding_hazmat_offer(api)
        before = world["shift"]
        assert before["status"] == "HIRING"
        assert before["required_staffing"] == 5
        assert before["certification_gap_count"] == 2
        assert before["staffing_posture"] == "CRITICAL"
        assert before["open_vacancy_count"] == 5

        closed = validate_success(
            api.company_closure(
                before["id"],
                {
                    "expected_duty_shift_version": before["version"],
                    "justification": "no hazmat technician is available for this tour",
                },
                STAFFING_OFFICER,
            ),
            200,
        )

        assert world["hazmat"]["id"] in closed["closed_apparatus_ids"]
        assert world["engine"]["id"] not in closed["closed_apparatus_ids"]
        assert closed["required_staffing"] == 4
        assert closed["assigned_headcount"] == 0
        assert closed["staffing_gap"] == 4
        assert closed["certification_gap_count"] == 1
        assert closed["leave_floor_headcount"] == 2
        assert closed["open_vacancy_count"] == 4
        assert closed["staffing_posture"] == "CRITICAL"
        assert closed["status"] == "HIRING"
        assert_version_incremented(closed["version"], before["version"])

        vacancy = fx.read_vacancy(api, world["hazmat_vacancy"]["id"])
        assert vacancy["status"] == "CLOSED_BY_COMPANY_CLOSURE"

    def test_closure_rescinds_the_offer_and_credits_the_ledger_without_charging(
        self, api
    ):
        """Hop four credits the encumbrance back and charges the member nothing.

        PRD 3.7: "Crucially, a rescission charges the member **nothing** —
        neither `voluntary_ot_hours_charged` nor `ot_pass_count` moves — because
        the department, not the member, withdrew."

        Design: Difficulty/transitive_cascade/company_closure_cascade_rescinds_offer_and_credits_encumbrance
        """
        world = _critical_shift_with_an_outstanding_hazmat_offer(api)

        before_station = fx.read_station(api, world["station"]["id"])
        assert before_station["ot_committed_cents"] == 164736

        fx.close_company(
            api,
            world["shift"]["id"],
            "no hazmat technician is available for this tour",
            world["shift"]["version"],
        )

        offer = fx.read_offer(api, world["offer"]["id"])
        assert offer["status"] == "RESCINDED"
        assert offer["projected_cost_cents"] == 164736

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0
        assert station["ot_actual_cents"] == 0
        assert station["budget_posture"] == "WITHIN"

        member = fx.read_firefighter(api, world["technician"]["id"])
        assert member["pending_offer_count"] == 0
        assert member["voluntary_ot_hours_charged"] == 0
        assert member["ot_pass_count"] == 0
