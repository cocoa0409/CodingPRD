"""The error surface: the 401/403 split at the header, member ownership on the
line member's own records, and one distinct 404 code per reference class.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    PAYROLL_ANALYST,
    STAFFING_OFFICER,
    ApiErrorId,
    fixtures as fx,
    headers_with_unknown_role,
    headers_without_role,
    validate_error,
    validate_paginated,
)


# ---------------------------------------------------------------------------
# 401 at the header, before any resource is touched
# ---------------------------------------------------------------------------
_STATION_PAYLOAD = {
    "name": "Station X",
    "battalion_code": "F9",
    "minimum_staffing_floor": 1,
    "fiscal_ot_budget_cents": 500_000,
    "fiscal_period_start_date": "2026-08-01",
    "fiscal_period_end_date": "2026-08-31",
}


class TestMissingOrUnknownRoleHeader:
    def test_a_station_create_without_a_role_header_is_unauthenticated(self, api):
        """PRD 2.1: "Every request to the API - without exception, including
        reads - must carry two headers: `X-User-ID`, identifying the acting
        user, and `X-User-Role`, declaring the capacity in which they act. ... A
        request that omits either header, or that presents an `X-User-Role`
        value outside those four, is rejected with `ERR_UNAUTHENTICATED`
        (401)."  The body below is a perfectly valid station, so nothing but the
        missing header can be the cause, and PRD 2.6 puts authentication first
        of all: nothing is written.

        Design: Corner/errors/station_create_without_a_role_header_is_unauthenticated
        """
        response = api.create_station(_STATION_PAYLOAD, headers_without_role())
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

        body = response.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"]
        assert body["data"]["message"]

        # No station came into existence.
        rows, meta = validate_paginated(
            api.list_stations(STAFFING_OFFICER, battalion_code="F9")
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_role_outside_the_declared_four_is_401_and_not_403(self, api):
        """PRD 2.1: "Four roles exist, spelled exactly as follows:
        `StaffingOfficer`, `CompanyOfficer`, `Firefighter`, and
        `PayrollAnalyst`. A request that omits either header, or that presents
        an `X-User-Role` value outside those four, is rejected with
        `ERR_UNAUTHENTICATED` (401). A request whose role is one of the four but
        is not among the roles authorised for the endpoint being called is
        rejected with `ERR_FORBIDDEN_ROLE` (403)."  `BattalionChief` is outside
        the set, so the unrecognised role fails authentication rather than
        authorisation - even on a read the PRD's endpoint table opens to "All
        roles".

        Design: Corner/errors/station_create_without_a_role_header_is_unauthenticated
        """
        response = api.list_stations(headers_with_unknown_role())
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] != ApiErrorId.FORBIDDEN_ROLE.value
        assert body["meta"]["api_request_id"]
        assert body["data"]["message"]


# ---------------------------------------------------------------------------
# 403 for a recognised role acting outside its authorisation list
# ---------------------------------------------------------------------------
def _shift_with_one_open_seat(api):
    """One single-seat company, one eligible member, and a published shift."""
    station = fx.create_station(
        api,
        name="Station 124",
        battalion_code="F9",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-124",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="E Escobar",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    return {
        "station": station,
        "engine": engine,
        "member": member,
        "shift": shift,
    }


class TestRoleAuthorisationOnSeating:
    def test_a_payroll_analyst_cannot_seat_a_member(self, api):
        """PRD 2.1: "The `PayrollAnalyst` closes out elapsed shifts, records
        hour adjustments, and reads the two station analytics; it has no
        staffing authority of any kind."  The endpoint table authorises `POST
        /fire-ops/shift-assignments` for `CompanyOfficer` alone, and PRD 2.6
        ranks role authorisation second: "**Role authorisation** -
        `ERR_FORBIDDEN_ROLE` (403). This also precedes existence, so a
        `Firefighter` attempting a company closure on a non-existent shift
        receives 403, not 404."  The payload here is otherwise flawless, so the
        403 is the role and the shift is untouched.

        Design: Corner/errors/seating_a_member_as_payroll_analyst_is_forbidden
        """
        world = _shift_with_one_open_seat(api)
        shift = world["shift"]

        response = api.create_shift_assignment(
            {
                "duty_shift_id": shift["id"],
                "firefighter_id": world["member"]["id"],
                "apparatus_id": world["engine"]["id"],
                "assignment_type": "REGULAR",
                "seat_certification": "NONE",
                "scheduled_hours": 24,
                "expected_duty_shift_version": shift["version"],
            },
            PAYROLL_ANALYST,
        )
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE.value, 403)

        after = fx.read_shift(api, shift["id"])
        assert after["assigned_headcount"] == 0
        assert after["open_vacancy_count"] == 1
        assert after["version"] == shift["version"]

        _, meta = validate_paginated(
            api.list_shift_assignments(STAFFING_OFFICER, duty_shift_id=shift["id"])
        )
        assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# 403 for the right role acting on somebody else's record
# ---------------------------------------------------------------------------
def _seated_member_and_a_live_offer_for_a_colleague(api):
    """A two-seat company: one member seated, the other holding the offer.

    PRD 3.6 excludes from the candidate pool anybody who "must hold no
    `SCHEDULED` assignment on this shift", and ranks the `VOLUNTARY` remainder
    by `voluntary_ot_hours_charged` ascending then `seniority_rank` ascending,
    so the offer necessarily goes to the junior unseated member rather than to
    the captain.
    """
    station = fx.create_station(
        api,
        name="Station 125",
        battalion_code="G1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=900_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-125",
        apparatus_type="ENGINE",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    seated = fx.create_firefighter(
        api,
        station["id"],
        full_name="F Fenner",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    offered = fx.create_firefighter(
        api,
        station["id"],
        full_name="G Gorman",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="H Hobbs",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    seat = fx.seat_member(
        api,
        shift["id"],
        seated["id"],
        engine["id"],
        officer["id"],
        expected_duty_shift_version=shift["version"],
    )
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
    offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)
    assert offer["firefighter_id"] == offered["id"]
    return {
        "station": station,
        "engine": engine,
        "seated": seated,
        "offered": offered,
        "officer": officer,
        "shift": shift,
        "seat": seat,
        "vacancy": vacancy,
        "offer": offer,
    }


class TestMemberOwnership:
    def test_leave_filed_for_a_colleague_is_rejected(self, api):
        """PRD 3.4: "A member files their own leave request, naming their
        `firefighter_id` ... A member filing for another member is rejected with
        `ERR_NOT_RESOURCE_OWNER`".  PRD 2.6 places it fifth: "**Member
        ownership** - `ERR_NOT_RESOURCE_OWNER` (403), on the five member-scoped
        actions named in 2.1."  The header role is the correct `Firefighter` and
        both members and the shift exist, so only the mismatched `X-User-ID` can
        explain the refusal, and nothing is queued.

        Design: Corner/errors/leave_filed_on_behalf_of_another_member_is_rejected
        """
        world = _seated_member_and_a_live_offer_for_a_colleague(api)

        response = api.create_leave_request(
            {
                "firefighter_id": world["seated"]["id"],
                "duty_shift_id": world["shift"]["id"],
                "leave_type": "VACATION",
                "requested_hours": 24,
            },
            fx.make_firefighter_headers(world["offered"]["id"]),
        )
        validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)

        _, meta = validate_paginated(
            api.list_leave_requests(STAFFING_OFFICER, duty_shift_id=world["shift"]["id"])
        )
        assert meta["total_count"] == 0
        assert fx.read_assignment(api, world["seat"]["id"])["status"] == "SCHEDULED"

    def test_answering_another_members_offer_is_rejected(self, api):
        """PRD 3.7: "An offered member answers their own offer with a
        `response`, and only their own: a caller whose `X-User-ID` is not the
        offer's `firefighter_id` is refused with `ERR_NOT_RESOURCE_OWNER`."  The
        refusal runs before any state transition (PRD 2.6 puts ownership at 5
        and state admissibility at 8), so the offer stays `OFFERED`, the vacancy
        stays `OFFERING`, and neither member's roster counters move.

        Design: Corner/errors/leave_filed_on_behalf_of_another_member_is_rejected
        """
        world = _seated_member_and_a_live_offer_for_a_colleague(api)

        response = api.respond_to_offer(
            world["offer"]["id"],
            {"response": "ACCEPT"},
            fx.make_firefighter_headers(world["seated"]["id"]),
        )
        validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)

        assert fx.read_offer(api, world["offer"]["id"])["status"] == "OFFERED"
        assert fx.read_vacancy(api, world["vacancy"]["id"])["status"] == "OFFERING"

        wrong_caller = fx.read_firefighter(api, world["seated"]["id"])
        assert wrong_caller["voluntary_ot_hours_charged"] == 0
        rightful = fx.read_firefighter(api, world["offered"]["id"])
        assert rightful["pending_offer_count"] == 1
        assert fx.read_assignment(api, world["seat"]["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# One 404 code per reference class
# ---------------------------------------------------------------------------
class TestNotFoundCodesByReferenceClass:
    def test_each_aggregate_root_reports_its_own_not_found_code(self, api):
        """PRD 2.6: "The specific code identifies the reference class:
        `ERR_STATION_NOT_FOUND` for a station reference,
        `ERR_FIREFIGHTER_NOT_FOUND` for `firefighter_id`,
        `acting_supervisor_id`, `requesting_firefighter_id` or
        `counterparty_firefighter_id`, `ERR_DUTY_SHIFT_NOT_FOUND` for
        `duty_shift_id`, `ERR_VACANCY_NOT_FOUND` for a vacancy reference,
        `ERR_OFFER_NOT_FOUND` for an overtime offer reference,
        `ERR_LEAVE_REQUEST_NOT_FOUND` for a leave request reference,
        `ERR_TRADE_REQUEST_NOT_FOUND` for a trade request reference, and
        `ERR_RESOURCE_NOT_FOUND` for every other reference class ... The path
        parameters covered by the station, member, shift, vacancy, offer, leave
        and trade codes are `station_id`, `firefighter_id`, `duty_shift_id`,
        `vacancy_id`, `overtime_offer_id`, `leave_request_id` and
        `trade_request_id` respectively."

        Design: Corner/errors/unknown_ids_return_their_own_not_found_codes
        """
        probes = [
            (
                api.get_duty_shift(NON_EXISTENT_UUID, STAFFING_OFFICER),
                ApiErrorId.DUTY_SHIFT_NOT_FOUND.value,
            ),
            (
                api.get_overtime_offer(NON_EXISTENT_UUID, STAFFING_OFFICER),
                ApiErrorId.OFFER_NOT_FOUND.value,
            ),
            (
                api.get_leave_request(NON_EXISTENT_UUID, STAFFING_OFFICER),
                ApiErrorId.LEAVE_REQUEST_NOT_FOUND.value,
            ),
            (
                api.get_trade_request(NON_EXISTENT_UUID, STAFFING_OFFICER),
                ApiErrorId.TRADE_REQUEST_NOT_FOUND.value,
            ),
        ]
        for response, expected in probes:
            validate_error(response, expected, 404)
            assert response.json()["response_type"] == "error"

    def test_the_supporting_resources_share_the_generic_not_found_code(self, api):
        """PRD 2.6: "... and `ERR_RESOURCE_NOT_FOUND` for every other reference
        class - an `apparatus_id`, a `hiring_roster_id`, a
        `shift_assignment_id` or a `work_period_id`."  All four reads are open
        to "All roles" in the endpoint table, so the work-period probe below is
        authorised as `PayrollAnalyst` and still resolves to the same 404 code.

        Design: Corner/errors/unknown_ids_return_their_own_not_found_codes
        """
        probes = [
            api.get_apparatus(NON_EXISTENT_UUID, STAFFING_OFFICER),
            api.get_hiring_roster(NON_EXISTENT_UUID, STAFFING_OFFICER),
            api.get_shift_assignment(NON_EXISTENT_UUID, STAFFING_OFFICER),
            api.get_work_period(NON_EXISTENT_UUID, PAYROLL_ANALYST),
        ]
        for response in probes:
            validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND.value, 404)
            assert response.json()["response_type"] == "error"
