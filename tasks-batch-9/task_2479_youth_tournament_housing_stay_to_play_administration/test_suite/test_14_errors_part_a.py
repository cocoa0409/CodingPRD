"""Refusals that must name one exact error identifier, part one.

Resolution and identity failures, role-per-action and posture gates, the appeal
cap, and the date-and-window rules on events, blocks and stays. Every test drives
a request that breaks exactly one rule and reads the target back afterwards to
show the refused write moved nothing.
"""

from test_helpers import (
    EXCEPTION_REVIEWER_2_HEADERS,
    EXCEPTION_REVIEWER_2_ID,
    HOUSING_MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    UNKNOWN_TEAM_MANAGER_HEADERS,
    ApiErrorId,
    InvoiceLifecycleAction,
    ReviewAction,
    TeamAction,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _lone_tournament_env(api) -> fx.Env:
    """One tournament and nothing else, so every body reference except the
    tournament's own is bound to miss."""
    env = fx.Env(client=api)
    env.tournament = fx.create_tournament(api)
    return env


def _tournament_and_team_env(api) -> fx.Env:
    """One tournament and one team, so a rejected registration can only be
    failing on the acting identity."""
    env = _lone_tournament_env(api)
    env.team = fx.create_team(api)
    return env


def _released_block_env(api) -> fx.Env:
    """A registered team facing a twenty-room block that has already been handed
    back to the hotel, with the booking deadline still ahead."""
    env = fx.registered_team_env(api)
    fx.set_clock(api, "2026-08-26T00:00:00Z")
    validate_success(api.release_room_block(env.block_id, HM))
    return env


def _closed_window_draft_booking_env(api) -> fx.Env:
    """A four-room booking still at `DRAFT` on an event whose housing window has
    already shut."""
    env = fx.draft_booking_env(api)
    fx.close_booking_window(env)
    return env


def _appeal_spent_env(api) -> fx.Env:
    """An exception request denied, appealed once and denied again by a second
    reviewer, so its single appeal is spent."""
    env = fx.denied_exception_env(api)
    validate_success(
        api.team_action_exception_request(
            env.exception_request["id"],
            f.team_action_payload(TeamAction.APPEAL.value),
            env.team_headers,
        )
    )
    fx.review_exception(
        env,
        ReviewAction.DENY.value,
        headers=EXCEPTION_REVIEWER_2_HEADERS,
        decision_note="still insufficient",
    )
    return env


class TestResolutionAndIdentity:
    """Missing rows and unrecognised actors."""

    def test_each_missing_resource_type_answers_with_its_own_not_found_code(self, api):
        """Eleven probes against the same fabricated identifier — some through the
        path, some through a body reference — each answer with the not-found code
        of the type that was missing.

        PRD §2.6: "The 404 error identifier is chosen by the type of resource that
        was not found: `ERR_TOURNAMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_ROOM_BLOCK_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
        `ERR_BOOKING_NOT_FOUND`, `ERR_EXCEPTION_REQUEST_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` or
        `ERR_DISTRIBUTION_NOT_FOUND`."

        PRD §2.6: "Each reference must resolve to an existing row, and the 404
        identifier is again chosen by referenced type, drawn from
        `ERR_TOURNAMENT_NOT_FOUND`, `ERR_HOTEL_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_ROOM_BLOCK_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_EXCEPTION_REQUEST_NOT_FOUND` and `ERR_INVOICE_NOT_FOUND`."

        Design: Corner/errors/not_found_error_id_selected_by_resource_type
        """
        env = _lone_tournament_env(api)

        validate_error(
            api.get_tournament(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_TOURNAMENT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.create_hotel_contract(
                f.hotel_contract_payload(env.tournament_id, NON_EXISTENT_UUID), HM
            ),
            ApiErrorId.ERR_HOTEL_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.create_team_registration(
                f.team_registration_payload(env.tournament_id, NON_EXISTENT_UUID), HM
            ),
            ApiErrorId.ERR_TEAM_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_hotel_contract(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_CONTRACT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.release_room_block(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_ROOM_BLOCK_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_team_registration(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_booking(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_BOOKING_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_exception_request(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_EXCEPTION_REQUEST_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_complaint(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_rebate_invoice(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_INVOICE_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            api.get_revenue_distribution(NON_EXISTENT_UUID, HM),
            ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND.value,
            expected_status=404,
        )

    def test_absent_headers_an_undeclared_role_and_an_unknown_actor_all_differ(
        self, api
    ):
        """A request with no credentials, a request naming a role that does not
        exist, and a team manager whose identifier belongs to no team each earn a
        different refusal.

        PRD §2.1: "If either header is absent or present but empty, the request is
        rejected with `ERR_MISSING_AUTH_HEADERS` and HTTP 401."

        PRD §2.1: "If `X-User-Role` carries a value that is not one of the five
        roles enumerated below, the request is rejected with `ERR_UNKNOWN_ROLE` and
        HTTP 401."

        PRD §2.1: "For both of these entity-backed roles, an `X-User-ID` that
        matches no row of the backing entity — no `Team` for a `TeamManager`, no
        `Hotel` for a `HotelRepresentative` — is rejected with
        `ERR_ACTOR_IDENTITY_UNKNOWN` and HTTP 403."

        Design: Corner/errors/missing_auth_headers_and_invalid_role_rejected
        """
        env = _tournament_and_team_env(api)

        validate_error(
            api.get_tournament(env.tournament_id, NO_HEADERS),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
            expected_status=401,
        )
        validate_error(
            api.get_tournament(env.tournament_id, UNKNOWN_ROLE_HEADERS),
            ApiErrorId.ERR_UNKNOWN_ROLE.value,
            expected_status=401,
        )
        validate_error(
            api.create_team_registration(
                f.team_registration_payload(env.tournament_id, env.team["id"]),
                UNKNOWN_TEAM_MANAGER_HEADERS,
            ),
            ApiErrorId.ERR_ACTOR_IDENTITY_UNKNOWN.value,
            expected_status=403,
        )


class TestRoleAndActionGates:
    """A permitted role reaching for the other role's action."""

    def test_a_hotel_representative_may_not_issue_the_invoice_it_is_billed_on(
        self, api
    ):
        """The hotel may dispute an invoice but not issue it, so its `ISSUE`
        attempt is refused for the action rather than for the role, and the invoice
        stays in draft.

        PRD §2.1: "On `POST /housing/rebate-invoices/{id}/lifecycle`, the values
        `ISSUE` and `WRITE_OFF` require `HousingManager` while `DISPUTE` requires
        `HotelRepresentative`."

        PRD §2.1: "A permitted role asking for an action that belongs to the other
        role is rejected with `ERR_ACTION_ROLE_MISMATCH` and HTTP 403."

        Design: Corner/errors/hotel_representative_issuing_invoice_rejected
        """
        env = fx.invoiced_env(api)

        response = api.invoice_lifecycle(
            env.invoice_id,
            f.lifecycle_payload(InvoiceLifecycleAction.ISSUE.value),
            env.hotel_headers,
        )

        validate_error(
            response, ApiErrorId.ERR_ACTION_ROLE_MISMATCH.value, expected_status=403
        )
        assert env.refresh_invoice()["status"] == "DRAFT"
        assert env.refresh_tournament()["posture"] == "BOOKING_CLOSED"


class TestPostureAndStateGates:
    """Operations reaching for a phase of the event that has not arrived."""

    def test_a_hotel_cannot_report_room_nights_while_the_window_is_still_open(
        self, api
    ):
        """A perfectly confirmed booking still cannot be actualized until the
        housing window has shut, and the booking's own figures are untouched.

        PRD §3.7: "The governing tournament's `posture` must be `BOOKING_CLOSED` or
        `RECONCILING`, or the request is rejected with
        `ERR_TOURNAMENT_NOT_RECONCILING`."

        Design: Corner/errors/actualization_while_tournament_open_rejected
        """
        env = fx.confirmed_booking_env(api)
        assert env.refresh_tournament()["posture"] == "OPEN"

        response = api.create_actualization(
            env.booking_id,
            f.actualization_payload(12, report_note="premature report"),
            env.hotel_headers,
        )

        validate_error(
            response,
            ApiErrorId.ERR_TOURNAMENT_NOT_RECONCILING.value,
            expected_status=409,
        )
        booking = env.refresh_booking()
        assert booking["booking_status"] == "CONFIRMED"
        assert booking["actualized_room_nights"] == 0
        assert booking["rebate_status"] == "NOT_DUE"

    def test_a_released_block_sells_no_more_rooms(self, api):
        """Once the unsold remainder has gone back to the hotel the block is out of
        the market, even though its twenty rooms are nominally unsold.

        PRD §3.4: "The block itself must be `OPEN` or `RESTRICTED`; a `RELEASED` or
        `SETTLED` block no longer sells rooms and yields `ERR_BLOCK_NOT_BOOKABLE`."

        PRD §3.2: "Both source states behave identically: the transition freezes
        `rooms_released_unsold` at `block_size_rooms` minus `rooms_committed`, sets
        `rooms_available` to 0, leaves `rooms_committed` untouched, then recomputes
        the contract's `block_posture` and, from that, the tournament's
        `housing_pressure`."

        Design: Corner/errors/booking_on_released_block_rejected
        """
        env = _released_block_env(api)
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"], env.block_id, registration["version"]
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_BLOCK_NOT_BOOKABLE.value, expected_status=409
        )
        block = env.refresh_block()
        assert block["status"] == "RELEASED"
        assert block["rooms_released_unsold"] == 20

    def test_a_booking_that_never_reached_confirmation_cannot_be_actualized(self, api):
        """With the window closed the posture rule is satisfied, so a hotel report
        against a booking still at draft is refused on the reservation state and no
        report row is written.

        PRD §3.7: "The booking's `booking_status` must be `CONFIRMED` for the first
        report on that booking and `CHECKED_OUT` for any subsequent report; anything
        else is rejected with `ERR_BOOKING_NOT_CONFIRMED`."

        Design: Corner/errors/actualization_of_draft_booking_rejected
        """
        env = _closed_window_draft_booking_env(api)
        assert env.refresh_tournament()["posture"] == "BOOKING_CLOSED"

        response = api.create_actualization(
            env.booking_id,
            f.actualization_payload(12, report_note="hotel reported an unconfirmed stay"),
            env.hotel_headers,
        )

        validate_error(
            response, ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value, expected_status=409
        )
        assert env.refresh_booking()["booking_status"] == "DRAFT"
        _, meta = validate_paginated(api.list_actualization_reports(env.booking_id, HM))
        assert meta["total_count"] == 0

    def test_no_revenue_can_be_split_from_an_invoice_that_has_collected_nothing(
        self, api
    ):
        """An issued invoice with an empty ledger cannot fund a distribution, even
        with the event already reconciling and the version guard satisfied.

        PRD §3.9: "The source invoice's `status` must be `PARTIALLY_PAID` or `PAID`;
        a distribution requested from an invoice that has collected nothing is
        rejected with `ERR_INVOICE_NOT_COLLECTED`."

        Design: Corner/errors/distribution_from_issued_invoice_rejected
        """
        env = fx.issued_invoice_env(api)
        invoice = env.refresh_invoice()

        response = api.create_revenue_distribution(
            f.revenue_distribution_payload(
                env.tournament_id, invoice["id"], invoice["version"]
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_INVOICE_NOT_COLLECTED.value, expected_status=409
        )
        assert env.refresh_tournament()["posture"] == "RECONCILING"
        invoice = env.refresh_invoice()
        assert invoice["status"] == "ISSUED"
        assert invoice["collected_cents"] == 0

    def test_a_team_gets_one_appeal_and_no_more(self, api):
        """A request already denied on appeal cannot be appealed a second time, and
        the refusal neither reopens the request nor spends another cycle.

        PRD §3.6: "That loop is capped at one appeal: an `APPEAL` against a request
        whose `appeal_count` already stands at 1 is rejected with
        `ERR_APPEAL_LIMIT_REACHED`, which is what makes the cycle terminate."

        Design: Corner/errors/second_appeal_rejected
        """
        env = _appeal_spent_env(api)

        response = api.team_action_exception_request(
            env.exception_request["id"],
            f.team_action_payload(TeamAction.APPEAL.value),
            env.team_headers,
        )

        validate_error(
            response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, expected_status=409
        )
        request = env.refresh_exception_request()
        assert request["status"] == "DENIED"
        assert request["appeal_count"] == 1
        assert request["decided_by_user_id"] == EXCEPTION_REVIEWER_2_ID


class TestDateAndWindowGates:
    """Date pairs, block windows and release deadlines."""

    def test_an_event_window_must_run_forwards_and_hold_at_least_one_night(self, api):
        """A backwards window and a zero-length window are refused alike, because
        the later date has to be strictly the later one.

        PRD §3.1: "The `end_date` must be strictly after the `start_date`; a pair
        where the later date is not strictly greater is rejected with
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/errors/inverted_date_pair_rejected
        """
        validate_error(
            api.create_tournament(
                f.tournament_payload(
                    name="Backwards Cup",
                    start_date="2026-09-13",
                    end_date="2026-09-10",
                ),
                HM,
            ),
            ApiErrorId.ERR_INVALID_DATE_RANGE.value,
            expected_status=422,
        )
        validate_error(
            api.create_tournament(
                f.tournament_payload(
                    name="Zero Night Cup",
                    start_date="2026-09-10",
                    end_date="2026-09-10",
                ),
                HM,
            ),
            ApiErrorId.ERR_INVALID_DATE_RANGE.value,
            expected_status=422,
        )

    def test_a_stay_may_not_run_past_the_last_night_the_block_holds(self, api):
        """The block holds nights from the 10th to the 13th, so a checkout on the
        14th falls outside it and commits nothing.

        PRD §3.4: "The stay must sit inside the block's held window: `check_in_date`
        at or after the block's `arrival_date` and `check_out_date` at or before the
        block's `departure_date`, or `ERR_STAY_OUTSIDE_BLOCK_WINDOW`."

        Design: Corner/errors/stay_outside_block_window_rejected
        """
        env = fx.registered_team_env(api)
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.block_id,
                registration["version"],
                check_in_date="2026-09-10",
                check_out_date="2026-09-14",
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_STAY_OUTSIDE_BLOCK_WINDOW.value,
            expected_status=422,
        )
        assert env.refresh_block()["rooms_committed"] == 0

    def test_a_block_may_not_arrive_more_than_two_days_before_the_event(self, api):
        """For an event starting on the 10th the earliest legal arrival is the 8th,
        so a block arriving on the 7th is one day outside the padded envelope and
        the contract picks up no contracted volume.

        PRD §3.2: "The block window must also sit inside the event window padded by
        two days on each side — that is, `arrival_date` must be no earlier than two
        days before the tournament's `start_date`, and `departure_date` no later
        than two days after its `end_date`; a window outside that envelope is
        rejected with `ERR_BLOCK_OUTSIDE_EVENT_WINDOW`."

        Design: Corner/errors/block_beyond_event_window_pad_rejected
        """
        env = fx.draft_contract_env(api)

        response = api.create_room_block(
            f.room_block_payload(
                env.contract_id, block_size_rooms=10, arrival_date="2026-09-07"
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_BLOCK_OUTSIDE_EVENT_WINDOW.value,
            expected_status=422,
        )
        contract = env.refresh_contract()
        assert contract["status"] == "DRAFT"
        assert contract["contracted_room_nights"] == 0

    def test_a_block_may_not_be_scheduled_to_release_before_the_contract_cutoff(
        self, api
    ):
        """Against a cutoff of the 20th, a release deadline on the 19th is refused,
        because the hotel's exposure is measured from the cutoff onwards.

        PRD §3.2: "The `release_deadline` must fall at or after the owning
        contract's `cutoff_date`; an earlier deadline is rejected with
        `ERR_RELEASE_DEADLINE_BEFORE_CUTOFF`."

        Design: Corner/errors/release_deadline_before_cutoff_rejected
        """
        env = fx.draft_contract_env(api)

        response = api.create_room_block(
            f.room_block_payload(
                env.contract_id, block_size_rooms=10, release_deadline="2026-08-19"
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_RELEASE_DEADLINE_BEFORE_CUTOFF.value,
            expected_status=422,
        )
        assert env.refresh_contract()["contracted_room_nights"] == 0


class TestRoomingListContentRules:
    """The manifest's own structural rules."""

    def test_a_gap_in_the_room_numbering_is_refused(self, api):
        """Rooms numbered 1, 2, 3 and 5 for a four-room booking carry the right
        number of entries but skip room 4, so the manifest is refused on its
        numbering and the booking stays at draft.

        PRD §3.4: "The `room_index` values across the submitted entries must form
        the contiguous sequence from 1 through the booking's `rooms_requested`, with
        no duplicates and no gaps; anything else is `ERR_ROOMING_LIST_INDEX_INVALID`."

        Design: Corner/errors/rooming_list_index_gap_rejected
        """
        env = fx.draft_booking_env(api)

        response = api.submit_rooming_list(
            env.booking_id,
            f.rooming_list_payload(
                entries=[
                    f.rooming_list_entry(1),
                    f.rooming_list_entry(2),
                    f.rooming_list_entry(3),
                    f.rooming_list_entry(5),
                ]
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_ROOMING_LIST_INDEX_INVALID.value,
            expected_status=422,
        )
        assert env.refresh_booking()["booking_status"] == "DRAFT"
