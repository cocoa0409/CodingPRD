"""Who may act, on whose data, and who is disqualified by an earlier decision.

The five roles each own operations no other role may take, two of them are
further narrowed to their own team or their own hotel, and three independence
rules disqualify an operator who has already decided something related.
"""

from test_helpers import (
    EXCEPTION_REVIEWER_2_HEADERS,
    EXCEPTION_REVIEWER_2_ID,
    EXCEPTION_REVIEWER_HEADERS,
    EXCEPTION_REVIEWER_ID,
    HOUSING_MANAGER_HEADERS,
    RIGHTS_HOLDER_2_HEADERS,
    RIGHTS_HOLDER_2_ID,
    RIGHTS_HOLDER_HEADERS,
    RIGHTS_HOLDER_ID,
    ApiErrorId,
    ComplaintCategory,
    ComplaintOutcome,
    ComplaintRoute,
    DistributionAction,
    NegotiationAction,
    RemedyType,
    ReviewAction,
    TeamAction,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_hotel_rep_headers,
    make_rights_holder_headers,
    make_team_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS
REVIEWER = EXCEPTION_REVIEWER_HEADERS
OTHER_REVIEWER = EXCEPTION_REVIEWER_2_HEADERS
RIGHTS = RIGHTS_HOLDER_HEADERS
OTHER_RIGHTS = RIGHTS_HOLDER_2_HEADERS

_RIVAL_HOTEL = {
    "name": "Rival Suites Metro",
    "city": "Metro",
    "distance_miles_from_venue": 5.0,
}


def _investigating_complaint_env(api) -> fx.Env:
    """A registered team whose complaint has been routed to investigation."""
    env = fx.registered_team_env(api)
    fx.add_complaint(env, registration_id=env.registration_id)
    fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)
    return env


def _appealed_exception_env(api) -> fx.Env:
    """A denied exemption the team has appealed, so the original reviewer is now
    disqualified from deciding it again."""
    env = fx.denied_exception_env(api)
    env.exception_request = get_success_data(
        api.team_action_exception_request(
            env.exception_request["id"],
            f.team_action_payload(TeamAction.APPEAL.value),
            env.team_headers,
        )
    )
    return env


def _cited_denial_complaint_env(api) -> fx.Env:
    """A complaint under investigation that disputes a denied exemption."""
    env = fx.denied_exception_env(api)
    fx.add_complaint(
        env,
        registration_id=env.registration_id,
        cited_exception_request_id=env.exception_request["id"],
        category=ComplaintCategory.POLICY_FAIRNESS.value,
        narrative="the medical exemption was denied without reading the letter",
    )
    fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)
    return env


def _upheld_rebate_complaint_env(api) -> fx.Env:
    """A calculated payout on an event where the first rights holder has already
    upheld a rebate-transparency complaint."""
    env = fx.calculated_distribution_env(api)
    fx.add_complaint(
        env,
        registration_id=env.registration_id,
        category=ComplaintCategory.REBATE_TRANSPARENCY.value,
        narrative="the rebate arithmetic was never shown to the club",
    )
    fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)
    fx.adjudicate_complaint(
        env,
        ComplaintOutcome.UPHOLD.value,
        RemedyType.NONE.value,
        headers=RIGHTS,
    )
    return env


class TestEachRoleOwnsItsOwnOperations:
    """The operations only one role may take, taken by that role."""

    def test_the_team_the_manager_and_the_hotel_each_take_their_own_step(self, api):
        """A team manager lodges the manifest, a housing manager confirms it and
        closes the window, and only then does the hotel report the room nights
        actually consumed.

        PRD §3.4: "A first submission moves the booking `DRAFT →
        ROOMING_LIST_SUBMITTED`, creating one row per submitted element."

        PRD §3.4: "Confirmation is a `HousingManager` action, and it is the moment
        the event commits rooms to the hotel."

        PRD §3.7: "This is the one write in the system reserved entirely to
        hotels, and it is scoped: `X-User-ID` must equal the hotel reference of
        the contract that owns the booking's block, or the request is rejected
        with `ERR_HOTEL_SCOPE_VIOLATION`."

        PRD §3.7: "Each accepted report is an immutable record carrying the
        `booking_id` it describes, its `reported_room_nights`, its optional
        `report_note`, and a server-assigned `sequence_no` equal to one more than
        the number of reports already filed against that booking — so the first
        report is number 1 and numbering rises monotonically per booking."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
        """
        env = fx.draft_booking_env(api)

        listed = validate_success(
            api.submit_rooming_list(
                env.booking_id, f.rooming_list_payload(rooms=4), env.team_headers
            ),
            expected_status=200,
        )
        confirmed = validate_success(
            api.confirm_booking(env.booking_id, HM), expected_status=200
        )
        closed = validate_success(
            api.close_booking(env.tournament_id, HM), expected_status=200
        )
        report = validate_success(
            api.create_actualization(
                env.booking_id, f.actualization_payload(12), env.hotel_headers
            ),
            expected_status=201,
        )

        assert listed["booking_status"] == "ROOMING_LIST_SUBMITTED"
        assert confirmed["booking_status"] == "CONFIRMED"
        assert closed["posture"] == "BOOKING_CLOSED"
        assert report["sequence_no"] == 1
        assert report["reported_room_nights"] == 12
        assert report["booking_id"] == env.booking_id
        booking = env.refresh_booking()
        assert booking["booking_status"] == "CHECKED_OUT"
        assert booking["actualized_room_nights"] == 12
        assert booking["rebate_status"] == "ACCRUED"
        assert booking["rebate_accrued_cents"] == 10800

    def test_the_reviewer_opens_a_review_and_the_rights_holder_closes_a_complaint(
        self, api
    ):
        """Exemption review belongs to the exception reviewer and adjudication to
        the rights holder, and each records the acting operator on the record it
        moves.

        PRD §3.6: "`START_REVIEW` moves the request `SUBMITTED → UNDER_REVIEW` and
        increments `review_round` by 1; it requires the tournament to be `OPEN`."

        PRD §3.9: "Adjudication is reserved to the `RightsHolder` and closes the
        fork."

        PRD §3.9: "Whether the complaint sat at `INVESTIGATING` or at `ESCALATED`,
        a `DISMISS` outcome sets `remedy_type` to `NONE`, `remedy_credit_cents` to
        0 and `adjudicated_by_user_id` to the acting `X-User-ID`, and carries no
        cross-entity effect whatsoever."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
        """
        env = _investigating_complaint_env(api)
        fx.add_exception_request(env)

        reviewed = validate_success(
            api.review_exception_request(
                env.exception_request["id"],
                f.review_payload(ReviewAction.START_REVIEW.value),
                REVIEWER,
            ),
            expected_status=200,
        )
        adjudicated = validate_success(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.DISMISS.value, RemedyType.NONE.value
                ),
                RIGHTS,
            ),
            expected_status=200,
        )

        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["review_round"] == 1
        assert adjudicated["status"] == "DISMISSED"
        assert adjudicated["remedy_type"] == "NONE"
        assert adjudicated["remedy_credit_cents"] == 0
        assert adjudicated["adjudicated_by_user_id"] == RIGHTS_HOLDER_ID


class TestSharedOperationsAcceptEitherRole:
    """Registration and booking are open to the housing manager and the team alike."""

    def test_registration_succeeds_from_the_organizer_and_from_the_team(self, api):
        """Two identical rosters are registered, one by the housing manager and one
        by the team's own manager, and both derive the same pair of room
        requirements.

        PRD §3.3: "Either a `HousingManager` or the team's own `TeamManager`
        submits `tournament_id`, `team_id`, `roster_player_count` (at least 1) and
        `roster_staff_count` (at least 0), and the tournament must be `OPEN`."

        PRD §3.3: "A roster of 13 players and 3 staff yields four player rooms plus
        two staff rooms, so `required_rooms_registered` is 6, while the pooled
        computation divides 16 by four and yields `minimum_rooms_for_compliance` of
        4 — six rooms bookable at most, four rooms required at least, from
        identical inputs."

        PRD §3.3: "The rest of the registration record is initialised to
        `exempt_rooms_granted` of 0, `effective_required_rooms` equal to
        `minimum_rooms_for_compliance`, `committed_rooms` of 0 and `status`
        `PENDING_HOUSING`."

        Design: Corner/rbac/shared_operations_accept_either_permitted_role
        """
        env = fx.executed_contract_env(api)
        organizer_team = fx.create_team(api, name="Riverside FC 16U")
        self_serving_team = fx.create_team(
            api, name="Lakeside SC 16U", org_contact_email="lakeside@example.com"
        )

        by_organizer = validate_success(
            api.create_team_registration(
                f.team_registration_payload(env.tournament_id, organizer_team["id"]), HM
            ),
            expected_status=201,
        )
        by_team = validate_success(
            api.create_team_registration(
                f.team_registration_payload(
                    env.tournament_id, self_serving_team["id"]
                ),
                make_team_manager_headers(self_serving_team["id"]),
            ),
            expected_status=201,
        )

        for registration in (by_organizer, by_team):
            assert registration["required_rooms_registered"] == 6
            assert registration["minimum_rooms_for_compliance"] == 4
            assert registration["required_room_nights"] == 18
            assert registration["exempt_rooms_granted"] == 0
            assert registration["effective_required_rooms"] == 4
            assert registration["committed_rooms"] == 0
            assert registration["status"] == "PENDING_HOUSING"

    def test_booking_succeeds_from_the_organizer_and_from_the_team_and_reads_back_to_the_hotel(
        self, api
    ):
        """The housing manager books for one team and the other team books for
        itself; both holds are `DRAFT` and the hotel may read one back without
        being the one who created it.

        PRD §3.4: "Either a `HousingManager` or the team's own `TeamManager`
        creates a booking with `registration_id`, `room_block_id`,
        `rooms_requested` (at least 1), the stay as `check_in_date` and
        `check_out_date`, and the mandatory `expected_registration_version`
        described in §2.8."

        PRD §3.4: "The server computes `nights` as the whole days from
        `check_in_date` up to but not including `check_out_date`, and
        `projected_room_nights` as `rooms_requested` multiplied by `nights` — the
        pre-stay estimate that cancellation penalties are assessed against."

        PRD §3.4: "Creation alone leaves the block's `rooms_committed`,
        `rooms_available` and `utilization_pct` **untouched** — confirmation is
        the only trigger that moves them."

        Design: Corner/rbac/shared_operations_accept_either_permitted_role
        """
        env = fx.registered_team_env(api)
        self_serving_team = fx.create_team(
            api, name="Lakeside SC 16U", org_contact_email="lakeside@example.com"
        )
        self_serving_registration = fx.add_registration(env, team=self_serving_team)
        organizer_registration = env.refresh_registration()

        by_organizer = validate_success(
            api.create_booking(
                f.booking_payload(
                    organizer_registration["id"],
                    env.block_id,
                    organizer_registration["version"],
                ),
                HM,
            ),
            expected_status=201,
        )
        by_team = validate_success(
            api.create_booking(
                f.booking_payload(
                    self_serving_registration["id"],
                    env.block_id,
                    self_serving_registration["version"],
                ),
                make_team_manager_headers(self_serving_team["id"]),
            ),
            expected_status=201,
        )
        read_by_hotel = validate_success(
            api.get_booking(by_team["id"], env.hotel_headers), expected_status=200
        )

        for booking in (by_organizer, by_team):
            assert booking["booking_status"] == "DRAFT"
            assert booking["rooms_requested"] == 4
            assert booking["projected_room_nights"] == 12
        assert read_by_hotel["id"] == by_team["id"]
        assert env.refresh_block()["rooms_committed"] == 0


class TestExclusiveOperationsAreClosedToOtherRoles:
    """A role outside an endpoint's list is refused before anything else is read."""

    def test_the_housing_managers_own_operations_are_refused_to_everyone_else(
        self, api
    ):
        """Confirming a booking, triaging a complaint and holding a room block all
        belong to the housing manager alone, and each is refused to a different
        outsider without changing anything.

        PRD §2.11: "The acting role appears in the endpoint's authorised-role list
        — otherwise `ERR_ROLE_NOT_PERMITTED`."

        PRD §3.4: "Confirmation is a `HousingManager` action, and it is the moment
        the event commits rooms to the hotel."

        PRD §3.9: "A `HousingManager` supplies a `route` of either `INVESTIGATE`,
        moving the complaint `FILED → INVESTIGATING`, or `ESCALATE`, moving it
        `FILED → ESCALATED`."

        Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
        """
        env = fx.rooming_list_env(api)
        fx.add_complaint(env, registration_id=env.registration_id)

        validate_error(
            api.confirm_booking(env.booking_id, env.team_headers),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            expected_status=403,
        )
        validate_error(
            api.triage_complaint(
                env.complaint["id"],
                f.triage_payload(ComplaintRoute.INVESTIGATE.value),
                env.hotel_headers,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            expected_status=403,
        )
        validate_error(
            api.create_room_block(f.room_block_payload(env.contract_id), RIGHTS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            expected_status=403,
        )

        assert env.refresh_booking()["booking_status"] == "ROOMING_LIST_SUBMITTED"
        complaint = env.refresh_complaint()
        assert complaint["status"] == "FILED"
        assert complaint["route"] is None
        blocks, meta = validate_paginated(
            api.list_contract_room_blocks(env.contract_id, HM)
        )
        assert meta["total_count"] == 1

    def test_review_and_adjudication_are_refused_to_the_wrong_operator(self, api):
        """The housing manager may not review an exemption and the exception
        reviewer may not adjudicate a complaint, so both records stay where they
        were.

        PRD §2.11: "The acting role appears in the endpoint's authorised-role list
        — otherwise `ERR_ROLE_NOT_PERMITTED`."

        PRD §3.6: "Human review runs through a four-action capability reserved to
        the `ExceptionReviewer`, which supplies an `action` and optionally
        `approved_rooms_exempt` and a `decision_note`."

        PRD §3.9: "Adjudication is reserved to the `RightsHolder` and closes the
        fork."

        Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
        """
        env = _investigating_complaint_env(api)
        fx.add_exception_request(env)

        validate_error(
            api.review_exception_request(
                env.exception_request["id"],
                f.review_payload(ReviewAction.START_REVIEW.value),
                HM,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            expected_status=403,
        )
        validate_error(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.DISMISS.value, RemedyType.NONE.value
                ),
                REVIEWER,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            expected_status=403,
        )

        request = env.refresh_exception_request()
        assert request["status"] == "SUBMITTED"
        assert request["review_round"] == 0
        complaint = env.refresh_complaint()
        assert complaint["status"] == "INVESTIGATING"
        assert complaint["adjudicated_by_user_id"] is None


class TestTeamManagerScope:
    """A team manager may only act inside its own team's registration."""

    def test_another_teams_manager_cannot_cancel_this_booking(self, api):
        """A stranger's cancellation is refused on scope, and the owning team's
        identical call then cancels the very same booking.

        PRD §2.1: "A `TeamManager` may only act where `X-User-ID` equals the team
        reference of the registration the target resource belongs to; a violation
        yields `ERR_TEAM_SCOPE_VIOLATION` and HTTP 403."

        PRD §3.5: "Cancellation is available to a `HousingManager` or to the
        team's own `TeamManager`, and it accepts a free-text
        `cancellation_reason`."

        PRD §3.5: "From twenty-one days out up to forty-four,
        `penalty_room_nights` is one quarter of `projected_room_nights`, rounded
        **up** to a whole room night."

        Design: Corner/rbac/team_manager_cannot_reach_another_teams_registration
        """
        env = fx.draft_booking_env(api)
        outsider = fx.create_team(
            api, name="Lakeside SC 16U", org_contact_email="lakeside@example.com"
        )

        validate_error(
            api.cancel_booking(
                env.booking_id,
                f.cancel_payload(),
                make_team_manager_headers(outsider["id"]),
            ),
            ApiErrorId.ERR_TEAM_SCOPE_VIOLATION.value,
            expected_status=403,
        )
        assert env.refresh_booking()["booking_status"] == "DRAFT"

        cancelled = validate_success(
            api.cancel_booking(env.booking_id, f.cancel_payload(), env.team_headers),
            expected_status=200,
        )

        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "team withdrew from the event"
        assert cancelled["penalty_room_nights"] == 3
        assert cancelled["penalty_cents"] == 44700

    def test_another_teams_manager_cannot_book_against_this_registration(self, api):
        """Booking rooms for someone else's registration is refused on scope, and
        no hold is created at all.

        PRD §2.1: "This guards seven operations: `POST
        /housing/team-registrations`, `POST /housing/bookings`, `POST
        /housing/bookings/{id}/rooming-list`, `POST
        /housing/bookings/{id}/cancel`, `POST /housing/exception-requests`, `POST
        /housing/exception-requests/{id}/team-action` and `POST
        /housing/complaints`."

        PRD §2.11: "A `TeamManager` is acting within its own team's registration
        scope — otherwise `ERR_TEAM_SCOPE_VIOLATION`."

        Design: Corner/rbac/team_manager_cannot_reach_another_teams_registration
        """
        env = fx.registered_team_env(api)
        outsider = fx.create_team(
            api, name="Lakeside SC 16U", org_contact_email="lakeside@example.com"
        )
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"], env.block_id, registration["version"]
            ),
            make_team_manager_headers(outsider["id"]),
        )

        validate_error(
            response, ApiErrorId.ERR_TEAM_SCOPE_VIOLATION.value, expected_status=403
        )
        bookings, meta = validate_paginated(
            api.list_bookings(HM, {"registration_id": registration["id"]})
        )
        assert meta["total_count"] == 0
        assert bookings == []


class TestHotelRepresentativeScope:
    """A hotel representative may only act inside its own contract."""

    def test_another_hotels_representative_cannot_report_these_room_nights(self, api):
        """A rival property's report is refused on scope, and the hosting hotel's
        identical report then checks the booking out.

        PRD §3.7: "This is the one write in the system reserved entirely to
        hotels, and it is scoped: `X-User-ID` must equal the hotel reference of
        the contract that owns the booking's block, or the request is rejected
        with `ERR_HOTEL_SCOPE_VIOLATION`."

        PRD §3.7: "The **reservation axis**, `booking_status`, runs `DRAFT →
        ROOMING_LIST_SUBMITTED → CONFIRMED → CHECKED_OUT` with `CANCELLED` as an
        alternate terminal, and the first accepted actualization report is what
        advances it `CONFIRMED → CHECKED_OUT` — provided no report already exists
        for that booking."

        Design: Corner/rbac/hotel_representative_cannot_report_for_another_hotel
        """
        env = fx.closed_window_env(api)
        rival = fx.create_hotel(api, **_RIVAL_HOTEL)

        validate_error(
            api.create_actualization(
                env.booking_id,
                f.actualization_payload(12),
                make_hotel_rep_headers(rival["id"]),
            ),
            ApiErrorId.ERR_HOTEL_SCOPE_VIOLATION.value,
            expected_status=403,
        )
        assert env.refresh_booking()["booking_status"] == "CONFIRMED"

        report = validate_success(
            api.create_actualization(
                env.booking_id, f.actualization_payload(12), env.hotel_headers
            ),
            expected_status=201,
        )

        assert report["sequence_no"] == 1
        booking = env.refresh_booking()
        assert booking["booking_status"] == "CHECKED_OUT"
        assert booking["actualized_room_nights"] == 12

    def test_another_hotels_representative_cannot_countersign_this_contract(self, api):
        """A rival property cannot execute a contract it is not party to, while the
        contracted hotel's countersignature is recorded against its own identifier.

        PRD §2.1: "This guards four operations: `POST
        /housing/hotel-contracts/{id}/negotiation`, `POST
        /housing/bookings/{id}/actualizations`, `POST
        /housing/rebate-invoices/{id}/lifecycle` and `POST
        /housing/rebate-invoices/{id}/remit`."

        PRD §3.2: "A `COUNTERSIGN` action moves the contract `NEGOTIATING →
        EXECUTED`, again requiring the tournament to be `OPEN`; it records
        `countersigned_by_hotel_id` as the acting `X-User-ID`, then recomputes the
        tournament's `executed_contract_count` and `sold_out_contract_count` and
        re-derives its `housing_pressure`."

        Design: Corner/rbac/hotel_representative_cannot_report_for_another_hotel
        """
        env = fx.negotiating_contract_env(api)
        rival = fx.create_hotel(api, **_RIVAL_HOTEL)

        validate_error(
            api.negotiate_contract(
                env.contract_id,
                f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
                make_hotel_rep_headers(rival["id"]),
            ),
            ApiErrorId.ERR_HOTEL_SCOPE_VIOLATION.value,
            expected_status=403,
        )
        assert env.refresh_contract()["status"] == "NEGOTIATING"

        contract = validate_success(
            api.negotiate_contract(
                env.contract_id,
                f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
                env.hotel_headers,
            ),
            expected_status=200,
        )

        assert contract["status"] == "EXECUTED"
        assert contract["countersigned_by_hotel_id"] == env.hotel_id
        assert env.refresh_tournament()["executed_contract_count"] == 1


class TestAppealNeedsAFreshReviewer:
    """Once an appeal is filed, the original decider is disqualified."""

    def test_the_original_reviewer_may_neither_approve_nor_deny_the_appeal(self, api):
        """The reviewer who recorded the denial is turned away from both decisions
        on the appealed request, which stays under review.

        PRD §2.10: "When an exception request's appeal counter is at least 1, an
        approve or deny action whose `X-User-ID` equals the request's recorded
        `decided_by_user_id` is rejected with `ERR_SOD_SAME_REVIEWER` and HTTP
        403."

        PRD §3.6: "an `APPEAL` action moves the request `DENIED → UNDER_REVIEW` and
        increments both `appeal_count` and `review_round` by 1."

        PRD §3.6: "Once `appeal_count` is at least 1, the reviewer who recorded the
        original decision may no longer approve or deny this request; an attempt
        yields `ERR_SOD_SAME_REVIEWER`."

        Design: Corner/rbac/appeal_reviewer_cannot_be_the_original_decider
        """
        env = _appealed_exception_env(api)
        request = env.refresh_exception_request()
        assert request["status"] == "UNDER_REVIEW"
        assert request["appeal_count"] == 1
        assert request["review_round"] == 2
        assert request["decided_by_user_id"] == EXCEPTION_REVIEWER_ID

        validate_error(
            api.review_exception_request(
                request["id"],
                f.review_payload(
                    ReviewAction.DENY.value, decision_note="still unconvinced"
                ),
                REVIEWER,
            ),
            ApiErrorId.ERR_SOD_SAME_REVIEWER.value,
            expected_status=403,
        )
        validate_error(
            api.review_exception_request(
                request["id"],
                f.review_payload(ReviewAction.APPROVE.value, approved_rooms_exempt=1),
                REVIEWER,
            ),
            ApiErrorId.ERR_SOD_SAME_REVIEWER.value,
            expected_status=403,
        )
        assert env.refresh_exception_request()["status"] == "UNDER_REVIEW"

    def test_a_second_reviewer_decides_the_appeal_and_the_grant_lands(self, api):
        """A different reviewer approves the single room, and the registration's
        effective requirement falls from four rooms to three.

        PRD §2.10: "Before any appeal has been filed, the same reviewer may freely
        decide, request information and decide again."

        PRD §3.6: "`APPROVE` moves it `UNDER_REVIEW → APPROVED`, requires the
        tournament to be `OPEN`, sets `approved_rooms_exempt` from the payload and
        `decided_by_user_id` to the acting `X-User-ID`, then recomputes the
        registration's `exempt_rooms_granted`, `effective_required_rooms` and
        `status` — which may move to `EXCEPTION_GRANTED` or to
        `HOUSING_COMPLIANT` — and refreshes the registration's `updated_at` and
        increments its `version` by 1."

        PRD §3.3: "Second, `effective_required_rooms` becomes
        `minimum_rooms_for_compliance` less `exempt_rooms_granted`, floored at 0 so
        it can never go negative."

        Design: Corner/rbac/appeal_reviewer_cannot_be_the_original_decider
        """
        env = _appealed_exception_env(api)

        approved = validate_success(
            api.review_exception_request(
                env.exception_request["id"],
                f.review_payload(ReviewAction.APPROVE.value, approved_rooms_exempt=1),
                OTHER_REVIEWER,
            ),
            expected_status=200,
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_rooms_exempt"] == 1
        assert approved["decided_by_user_id"] == EXCEPTION_REVIEWER_2_ID
        registration = env.refresh_registration()
        assert registration["exempt_rooms_granted"] == 1
        assert registration["effective_required_rooms"] == 3
        assert registration["status"] == "PENDING_HOUSING"


class TestAdjudicatorMayNotBeTheCitedDecider:
    """The operator who denied an exemption cannot judge the complaint about it."""

    def test_the_denying_operators_identifier_is_refused_on_both_outcomes(self, api):
        """A rights holder acting under the denying reviewer's identifier is
        refused whether it would dismiss or uphold, and the complaint stays under
        investigation.

        PRD §2.10: "When a complaint carries a cited exception request, an
        adjudication whose `X-User-ID` equals that request's `decided_by_user_id`
        is rejected with `ERR_SOD_ADJUDICATOR_CONFLICT` and HTTP 403."

        PRD §3.9: "Segregation of duties applies first: when the complaint carries
        a `cited_exception_request_id`, the acting `X-User-ID` may not equal that
        request's `decided_by_user_id`, or the request is rejected with
        `ERR_SOD_ADJUDICATOR_CONFLICT`."

        Design: Corner/rbac/exception_decider_cannot_adjudicate_the_complaint_citing_it
        """
        env = _cited_denial_complaint_env(api)
        conflicted = make_rights_holder_headers(EXCEPTION_REVIEWER_ID)

        validate_error(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.DISMISS.value, RemedyType.NONE.value
                ),
                conflicted,
            ),
            ApiErrorId.ERR_SOD_ADJUDICATOR_CONFLICT.value,
            expected_status=403,
        )
        validate_error(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.UPHOLD.value, RemedyType.NONE.value
                ),
                conflicted,
            ),
            ApiErrorId.ERR_SOD_ADJUDICATOR_CONFLICT.value,
            expected_status=403,
        )

        complaint = env.refresh_complaint()
        assert complaint["status"] == "INVESTIGATING"
        assert complaint["adjudicated_by_user_id"] is None

    def test_an_unconflicted_rights_holder_dismisses_the_same_complaint(self, api):
        """A rights holder with no part in the denial closes the complaint, and the
        exemption decision it disputed is left exactly as it was.

        PRD §3.9: "Whether the complaint sat at `INVESTIGATING` or at `ESCALATED`,
        a `DISMISS` outcome sets `remedy_type` to `NONE`, `remedy_credit_cents` to
        0 and `adjudicated_by_user_id` to the acting `X-User-ID`, and carries no
        cross-entity effect whatsoever."

        PRD §3.9: "Both `UPHELD` and `DISMISSED` are terminal."

        Design: Corner/rbac/exception_decider_cannot_adjudicate_the_complaint_citing_it
        """
        env = _cited_denial_complaint_env(api)

        dismissed = validate_success(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.DISMISS.value, RemedyType.NONE.value
                ),
                RIGHTS,
            ),
            expected_status=200,
        )

        assert dismissed["status"] == "DISMISSED"
        assert dismissed["remedy_type"] == "NONE"
        assert dismissed["remedy_credit_cents"] == 0
        assert dismissed["adjudicated_by_user_id"] == RIGHTS_HOLDER_ID
        request = env.refresh_exception_request()
        assert request["status"] == "DENIED"
        assert request["approved_rooms_exempt"] == 0


class TestPayoutApproverMayNotHaveUpheldTheRebateComplaint:
    """Upholding a rebate-transparency complaint disqualifies the payout approver."""

    def test_the_upholding_rights_holder_cannot_approve_the_split(self, api):
        """The rights holder that upheld the event's rebate-transparency complaint
        is refused the approval, and the split stays merely calculated.

        PRD §2.10: "If any complaint on the same tournament has category
        `REBATE_TRANSPARENCY`, status `UPHELD`, and an `adjudicated_by_user_id`
        equal to the acting `X-User-ID`, the approve action on a revenue
        distribution of that tournament is rejected with
        `ERR_SOD_DISTRIBUTION_APPROVER_CONFLICT` and HTTP 403."

        PRD §3.9: "A new distribution opens at `status` `CALCULATED` with
        `approved_by_user_id` null."

        Design: Corner/rbac/rebate_complaint_adjudicator_cannot_approve_the_distribution
        """
        env = _upheld_rebate_complaint_env(api)
        assert env.refresh_complaint()["status"] == "UPHELD"

        response = api.advance_distribution(
            env.distribution_id, f.advance_payload(DistributionAction.APPROVE.value), RIGHTS
        )

        validate_error(
            response,
            ApiErrorId.ERR_SOD_DISTRIBUTION_APPROVER_CONFLICT.value,
            expected_status=403,
        )
        distribution = env.refresh_distribution()
        assert distribution["status"] == "CALCULATED"
        assert distribution["approved_by_user_id"] is None

    def test_a_second_rights_holder_approves_the_same_split(self, api):
        """A rights holder who adjudicated nothing on this event approves the
        identical distribution, and its own identifier is recorded as approver.

        PRD §3.9: "`APPROVE`, a rights-holder action, moves it `CALCULATED →
        APPROVED` and sets `approved_by_user_id` to the acting `X-User-ID` — but
        only after the distribution-approver conflict check of §2.10 clears: if any
        complaint on the same `tournament_id` has `category`
        `REBATE_TRANSPARENCY`, `status` `UPHELD`, and an `adjudicated_by_user_id`
        equal to the acting `X-User-ID`, the approval is refused with
        `ERR_SOD_DISTRIBUTION_APPROVER_CONFLICT`."

        Design: Corner/rbac/rebate_complaint_adjudicator_cannot_approve_the_distribution
        """
        env = _upheld_rebate_complaint_env(api)

        approved = validate_success(
            api.advance_distribution(
                env.distribution_id, f.advance_payload(DistributionAction.APPROVE.value), OTHER_RIGHTS
            ),
            expected_status=200,
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == RIGHTS_HOLDER_2_ID
