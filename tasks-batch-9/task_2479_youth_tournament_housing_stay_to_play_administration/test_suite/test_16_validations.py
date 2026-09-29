"""Content gates that decide a request from the numbers it carries.

A share split that misses unity, a booking filed after the housing deadline, a
block that is already effectively full, and the local-team exemption that only a
nearby team may claim — each rule is shown refusing the bad request and then
accepting the neighbouring good one.
"""

from test_helpers import (
    EXCEPTION_REVIEWER_HEADERS,
    EXCEPTION_REVIEWER_ID,
    HOUSING_MANAGER_HEADERS,
    ApiErrorId,
    ExceptionReasonCode,
    ReviewAction,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS
REVIEWER = EXCEPTION_REVIEWER_HEADERS

_LOCAL_TEAM_OVERRIDES = {
    "name": "Metro United 16U",
    "home_city": "Metro",
    "org_contact_email": "metro@example.com",
    "distance_miles_from_venue": 10.0,
}


def _restricted_block_env(api) -> fx.Env:
    """A ten-room block driven to ``RESTRICTED`` by nine confirmed rooms.

    Two visiting teams confirm four and five rooms on the event's only block, so
    ``utilization_pct`` lands on exactly 0.9000.
    """
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 10})

    first_team = fx.create_team(api, name="Riverside FC 16U")
    first_registration = fx.add_registration(env, team=first_team)
    first_booking = fx.add_booking(
        env, registration=first_registration, block=env.block, rooms_requested=4
    )
    fx.submit_rooming_list(env, booking=first_booking, rooms=4)
    fx.confirm_booking(env, booking=first_booking)

    second_team = fx.create_team(
        api, name="Lakeside SC 16U", org_contact_email="lakeside@example.com"
    )
    second_registration = fx.add_registration(env, team=second_team)
    second_booking = fx.add_booking(
        env, registration=second_registration, block=env.block, rooms_requested=5
    )
    fx.submit_rooming_list(
        env,
        booking=second_booking,
        entries=[
            f.rooming_list_entry(1, occupant_count=4),
            f.rooming_list_entry(2, occupant_count=4),
            f.rooming_list_entry(3, occupant_count=4),
            f.rooming_list_entry(4, occupant_count=3),
            f.rooming_list_entry(5, occupant_count=1),
        ],
    )
    fx.confirm_booking(env, booking=second_booking)
    return env


def _oversold_hold_env(api) -> fx.Env:
    """A five-room block carrying one unconfirmed four-room hold."""
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 5})
    holding_team = fx.create_team(api, name="Riverside FC 16U")
    holding_registration = fx.add_registration(env, team=holding_team)
    env.holding_booking = fx.add_booking(
        env, registration=holding_registration, block=env.block, rooms_requested=4
    )
    fx.add_team(env, name="Lakeside SC 16U", org_contact_email="lakeside@example.com")
    fx.add_registration(env)
    return env


def _local_team_under_review_env(api) -> fx.Env:
    """A ten-mile team whose four-room ``LOCAL_TEAM`` filing sits at review."""
    env = fx.registered_team_env(api, team_overrides=dict(_LOCAL_TEAM_OVERRIDES))
    fx.add_exception_request(
        env,
        reason_code=ExceptionReasonCode.LOCAL_TEAM.value,
        requested_rooms_exempt=4,
        justification="the team sleeps at home, ten miles from the venue",
    )
    fx.review_exception(env, ReviewAction.START_REVIEW.value)
    return env


class TestRevenueShareUnity:
    """The three party shares must add up to exactly one."""

    def test_a_split_totalling_more_than_one_is_refused(self, api):
        """Halves and thirds that sum to 1.10 cannot be a revenue split, so the
        event is never created.

        PRD §3.1: "The three share fractions, each expressed with two decimal
        places, must add up to exactly one; any other total is rejected with
        `ERR_REVENUE_SHARE_NOT_UNITY`."

        PRD §2.11: "The three revenue-share percentages sum to exactly one —
        otherwise `ERR_REVENUE_SHARE_NOT_UNITY`."

        Design: Corner/validations/revenue_shares_not_summing_to_unity_rejected
        """
        response = api.create_tournament(
            f.tournament_payload(
                share_pct_organizer=0.5,
                share_pct_rights_holder=0.3,
                share_pct_destination=0.3,
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_REVENUE_SHARE_NOT_UNITY.value, expected_status=422
        )

    def test_a_split_of_thirty_four_and_two_thirty_threes_is_accepted(self, api):
        """A split that lands exactly on one is stored verbatim, and the event
        opens with three nights and no contracts behind it.

        PRD §3.1: "The three share fractions, each expressed with two decimal
        places, must add up to exactly one; any other total is rejected with
        `ERR_REVENUE_SHARE_NOT_UNITY`."

        PRD §3.1: "When both hold, the server computes `night_count` as the
        number of whole days from `start_date` up to but not including `end_date`
        — the event window is half-open, so the night that begins on `end_date`
        is not part of the event."

        PRD §3.1: "A new tournament begins with `posture` at `OPEN`,
        `housing_pressure` at `NORMAL`, and both derived contract counters —
        `executed_contract_count` and `sold_out_contract_count` — at 0."

        Design: Corner/validations/revenue_shares_at_exact_unity_accepted
        """
        response = api.create_tournament(
            f.tournament_payload(
                share_pct_organizer=0.34,
                share_pct_rights_holder=0.33,
                share_pct_destination=0.33,
            ),
            HM,
        )

        tournament = validate_success(response, expected_status=201)
        assert tournament["share_pct_organizer"] == 0.34
        assert tournament["share_pct_rights_holder"] == 0.33
        assert tournament["share_pct_destination"] == 0.33
        assert tournament["night_count"] == 3
        assert tournament["posture"] == "OPEN"
        assert tournament["housing_pressure"] == "NORMAL"
        assert tournament["executed_contract_count"] == 0
        assert tournament["sold_out_contract_count"] == 0


class TestRestrictedBlockServesOnlyUnhousedTeams:
    """At ninety percent committed, a block stops selling to housed teams."""

    def test_an_exception_granted_team_is_turned_away_from_the_restricted_block(
        self, api
    ):
        """The last room of a restricted block is refused to a team that has
        already been excused from the housing program altogether.

        PRD §3.4: "While a block's `status` is `OPEN` or `RESTRICTED`, it reads
        `RESTRICTED` whenever `utilization_pct` is at or above 0.90 — ninety
        percent of the held rooms committed — and `OPEN` otherwise."

        PRD §3.4: "When the target block's `status` is `RESTRICTED`, the
        referenced registration's `status` must be `PENDING_HOUSING`; a team that
        already reads `HOUSING_COMPLIANT`, `EXCEPTION_GRANTED` or
        `NON_COMPLIANT` is turned away with
        `ERR_BLOCK_RESTRICTED_TO_UNHOUSED_TEAMS`."

        Design: Corner/validations/restricted_block_refuses_already_housed_team
        """
        env = _restricted_block_env(api)
        block = env.refresh_block()
        assert block["rooms_committed"] == 9
        assert block["utilization_pct"] == 0.9
        assert block["status"] == "RESTRICTED"

        excused_team = fx.create_team(
            api, name="Hillcrest FC 16U", org_contact_email="hillcrest@example.com"
        )
        excused_registration = fx.add_registration(env, team=excused_team)
        excused_request = fx.add_exception_request(
            env,
            registration=excused_registration,
            reason_code=ExceptionReasonCode.FINANCIAL_HARDSHIP.value,
            requested_rooms_exempt=4,
            justification="the club cannot fund four rooms of official housing",
        )
        fx.review_exception(env, ReviewAction.START_REVIEW.value, request=excused_request)
        fx.review_exception(
            env,
            ReviewAction.APPROVE.value,
            request=excused_request,
            approved_rooms_exempt=4,
        )
        excused_registration = get_success_data(
            api.get_team_registration(excused_registration["id"], HM)
        )
        assert excused_registration["status"] == "EXCEPTION_GRANTED"

        response = api.create_booking(
            f.booking_payload(
                excused_registration["id"],
                env.block_id,
                excused_registration["version"],
                rooms_requested=1,
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_BLOCK_RESTRICTED_TO_UNHOUSED_TEAMS.value,
            expected_status=409,
        )
        assert env.refresh_block()["rooms_committed"] == 9

    def test_a_still_pending_team_may_take_the_last_room_of_the_same_block(self, api):
        """The identical one-room request from a team that still needs housing is
        exactly what the restriction exists to protect, so it is created.

        PRD §3.4: "When the target block's `status` is `RESTRICTED`, the
        referenced registration's `status` must be `PENDING_HOUSING`; a team that
        already reads `HOUSING_COMPLIANT`, `EXCEPTION_GRANTED` or
        `NON_COMPLIANT` is turned away with
        `ERR_BLOCK_RESTRICTED_TO_UNHOUSED_TEAMS`."

        PRD §3.4: "A booking that clears all of that is created with
        `booking_status` `DRAFT` and `rebate_status` `NOT_DUE`."

        Design: Corner/validations/restricted_block_refuses_already_housed_team
        """
        env = _restricted_block_env(api)
        assert env.refresh_block()["status"] == "RESTRICTED"

        pending_team = fx.create_team(
            api, name="Hillcrest FC 16U", org_contact_email="hillcrest@example.com"
        )
        pending_registration = fx.add_registration(env, team=pending_team)
        assert pending_registration["status"] == "PENDING_HOUSING"

        response = api.create_booking(
            f.booking_payload(
                pending_registration["id"],
                env.block_id,
                pending_registration["version"],
                rooms_requested=1,
            ),
            HM,
        )

        booking = validate_success(response, expected_status=201)
        assert booking["booking_status"] == "DRAFT"
        assert booking["rebate_status"] == "NOT_DUE"
        assert booking["rooms_requested"] == 1


class TestBookingDeadline:
    """No further rooms may be booked once the deadline instant has passed."""

    def test_a_booking_filed_a_day_after_the_deadline_is_refused(self, api):
        """The event is still `OPEN` and the block still has nineteen free rooms,
        but the clock has moved past the booking deadline.

        PRD §3.4: "The logical clock must be at or before the tournament's
        `booking_deadline`; a booking attempted after that instant is rejected
        with `ERR_BOOKING_DEADLINE_PASSED`, and the comparison is inclusive so a
        booking landing exactly on the deadline is accepted."

        PRD §2.11: "The logical clock is at or before the tournament's
        `booking_deadline` on booking creation — otherwise
        `ERR_BOOKING_DEADLINE_PASSED`."

        Design: Corner/validations/booking_after_deadline_rejected
        """
        env = fx.registered_team_env(api)
        registration = env.refresh_registration()
        fx.set_clock(api, "2026-09-02T00:00:00Z")

        response = api.create_booking(
            f.booking_payload(
                registration["id"], env.block_id, registration["version"]
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_BOOKING_DEADLINE_PASSED.value, expected_status=422
        )
        assert env.refresh_tournament()["posture"] == "OPEN"
        assert env.refresh_block()["rooms_committed"] == 0
        assert env.refresh_registration()["committed_rooms"] == 0


class TestBlockOversellGuard:
    """The capacity guard counts held rooms, not just committed ones."""

    def test_an_unconfirmed_four_room_hold_blocks_a_second_two_room_request(self, api):
        """Four of five rooms are held by a booking still at `DRAFT`, and that is
        enough to refuse a two-room request even though the block's own committed
        counters still read zero.

        PRD §3.4: "If that held occupancy plus the new `rooms_requested` would
        exceed the block's `block_size_rooms` on any single night, the request is
        rejected with `ERR_BLOCK_CAPACITY_EXCEEDED`."

        PRD §3.4: "The held set intentionally counts unconfirmed bookings, so a
        block cannot be oversold at creation time even though the persisted
        committed counters do not move until confirmation."

        PRD §3.4: "Creation alone leaves the block's `rooms_committed`,
        `rooms_available` and `utilization_pct` **untouched** — confirmation is
        the only trigger that moves them."

        Design: Corner/validations/block_oversell_guard_counts_unconfirmed_holds
        """
        env = _oversold_hold_env(api)
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.block_id,
                registration["version"],
                rooms_requested=2,
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_BLOCK_CAPACITY_EXCEEDED.value, expected_status=409
        )
        block = env.refresh_block()
        assert block["rooms_committed"] == 0
        assert block["rooms_available"] == 5
        assert block["utilization_pct"] == 0.0
        assert block["status"] == "OPEN"
        assert env.refresh_booking(env.holding_booking)["booking_status"] == "DRAFT"


class TestLocalExemptionEligibility:
    """Only a team inside the thirty-mile radius may claim the local exemption."""

    def test_a_team_a_hundred_and_twenty_miles_out_cannot_claim_it(self, api):
        """A visiting team whose registration was flagged non-local is refused
        the local exemption at filing.

        PRD §3.3: "At creation the server derives `local_team_flag` by reading
        the referenced team's `distance_miles_from_venue` and testing it against
        a local radius of thirty miles: the flag is `true` when the team's home
        city lies at or within thirty miles of the venue, and `false` otherwise."

        PRD §3.6: "A `LOCAL_TEAM` request is admissible only when the
        registration's `local_team_flag` is `true`; a non-local team asking for
        the local exemption is rejected with `ERR_LOCAL_EXEMPTION_NOT_ELIGIBLE`."

        Design: Corner/validations/local_exemption_rejects_distant_team_only
        """
        env = fx.registered_team_env(api)
        assert env.refresh_registration()["local_team_flag"] is False

        response = api.create_exception_request(
            f.local_exception_request_payload(env.registration_id), HM
        )

        validate_error(
            response,
            ApiErrorId.ERR_LOCAL_EXEMPTION_NOT_ELIGIBLE.value,
            expected_status=422,
        )

    def test_a_team_ten_miles_out_files_the_same_request_successfully(self, api):
        """The identical filing from a ten-mile team is admitted and waits for a
        reviewer, with nothing granted yet.

        PRD §3.6: "A `LOCAL_TEAM` request is admissible only when the
        registration's `local_team_flag` is `true`; a non-local team asking for
        the local exemption is rejected with `ERR_LOCAL_EXEMPTION_NOT_ELIGIBLE`."

        PRD §3.6: "A request normally lands at `SUBMITTED` with `review_round` 0,
        `appeal_count` 0, `approved_rooms_exempt` 0 and `decided_by_user_id`
        null."

        Design: Corner/validations/local_exemption_rejects_distant_team_only
        """
        env = fx.registered_team_env(api, team_overrides=dict(_LOCAL_TEAM_OVERRIDES))
        assert env.refresh_registration()["local_team_flag"] is True
        assert env.refresh_tournament()["housing_pressure"] == "NORMAL"

        response = api.create_exception_request(
            f.local_exception_request_payload(env.registration_id), HM
        )

        request = validate_success(response, expected_status=201)
        assert request["status"] == "SUBMITTED"
        assert request["requested_rooms_exempt"] == 4
        assert request["approved_rooms_exempt"] == 0
        assert request["review_round"] == 0
        assert request["appeal_count"] == 0
        assert request["decided_by_user_id"] is None


class TestApprovalRangeOutranksAllOrNothing:
    """The range check on an approval is heard before the local all-or-nothing rule."""

    def test_granting_five_of_four_requested_rooms_is_refused_on_the_range(self, api):
        """Five rooms against a four-room local request breaks both the range
        rule and the all-or-nothing rule, and the range rule is the one heard.

        PRD §2.11: "Checks are evaluated in the fixed order below, and the first
        failing check produces the response; later checks are not evaluated and
        cannot mask an earlier one."

        PRD §2.11: "On approval, `approved_rooms_exempt` is supplied and falls in
        the permitted range — otherwise `ERR_APPROVED_EXEMPTION_OUT_OF_RANGE`."

        PRD §3.6: "When the `action` is `APPROVE`, `approved_rooms_exempt` must
        be supplied and must be at least 1 and no more than the original
        `requested_rooms_exempt`; a missing, zero, or oversized value is rejected
        with `ERR_APPROVED_EXEMPTION_OUT_OF_RANGE`."

        Design: Corner/validations/exemption_range_check_runs_before_all_or_nothing_check
        """
        env = _local_team_under_review_env(api)

        response = api.review_exception_request(
            env.exception_request["id"],
            f.review_payload(ReviewAction.APPROVE.value, approved_rooms_exempt=5),
            REVIEWER,
        )

        validate_error(
            response,
            ApiErrorId.ERR_APPROVED_EXEMPTION_OUT_OF_RANGE.value,
            expected_status=422,
        )
        assert env.refresh_exception_request()["status"] == "UNDER_REVIEW"

    def test_an_in_range_partial_grant_then_surfaces_the_all_or_nothing_rule(self, api):
        """Two of the four requested rooms is inside the range but still refused,
        because a local exemption is all-or-nothing; the full four-room grant is
        then accepted and excuses the team outright.

        PRD §3.6: "A partial local grant is rejected with
        `ERR_PARTIAL_LOCAL_EXEMPTION_FORBIDDEN`."

        PRD §3.6: "`APPROVE` moves it `UNDER_REVIEW → APPROVED`, requires the
        tournament to be `OPEN`, sets `approved_rooms_exempt` from the payload and
        `decided_by_user_id` to the acting `X-User-ID`, then recomputes the
        registration's `exempt_rooms_granted`, `effective_required_rooms` and
        `status` — which may move to `EXCEPTION_GRANTED` or to
        `HOUSING_COMPLIANT` — and refreshes the registration's `updated_at` and
        increments its `version` by 1."

        PRD §3.3: "Otherwise, if `effective_required_rooms` has fallen to 0
        **and** `exempt_rooms_granted` is at least 1, the registration is
        `EXCEPTION_GRANTED`, recording that it was excused rather than that it
        complied."

        Design: Corner/validations/exemption_range_check_runs_before_all_or_nothing_check
        """
        env = _local_team_under_review_env(api)

        partial = api.review_exception_request(
            env.exception_request["id"],
            f.review_payload(ReviewAction.APPROVE.value, approved_rooms_exempt=2),
            REVIEWER,
        )
        validate_error(
            partial,
            ApiErrorId.ERR_PARTIAL_LOCAL_EXEMPTION_FORBIDDEN.value,
            expected_status=422,
        )

        full = api.review_exception_request(
            env.exception_request["id"],
            f.review_payload(ReviewAction.APPROVE.value, approved_rooms_exempt=4),
            REVIEWER,
        )

        request = validate_success(full, expected_status=200)
        assert request["status"] == "APPROVED"
        assert request["approved_rooms_exempt"] == 4
        assert request["decided_by_user_id"] == EXCEPTION_REVIEWER_ID
        registration = env.refresh_registration()
        assert registration["exempt_rooms_granted"] == 4
        assert registration["effective_required_rooms"] == 0
        assert registration["status"] == "EXCEPTION_GRANTED"
