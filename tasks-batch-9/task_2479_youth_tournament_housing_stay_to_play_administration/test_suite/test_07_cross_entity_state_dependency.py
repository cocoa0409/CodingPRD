"""Operations whose admissibility is decided by another entity's state.

One dependency blocks: a booking waits on the contract's execution. The other
grants: an exemption is decided without a human because the event as a whole has
run out of rooms.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    SYSTEM_AUTO,
    ApiErrorId,
    ExceptionReasonCode,
    NegotiationAction,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS

_LOCAL_JUSTIFICATION = "all families live within 10 miles of the venue"


def _negotiating_contract_with_registration_env(api) -> fx.Env:
    """A contract that has been submitted but not yet countersigned, with a team
    already registered and ready to book."""
    env = fx.negotiating_contract_env(api)
    fx.add_team(env)
    fx.add_registration(env)
    return env


def _sold_out_event_with_two_local_teams_env(api) -> fx.Env:
    """Two identically placed local teams, one of which filed before the event's
    only executed contract sold out.

    The visiting team's confirmation consumes the whole five-room block, which is
    what drives `housing_pressure` to `CONSTRAINED` between the two filings.
    """
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 5})

    team_local_first = fx.create_local_team(api, name="Metro United 16U")
    registration_first = fx.add_registration(env, team=team_local_first)
    team_local_second = fx.create_local_team(
        api, name="Metro United 14U", org_contact_email="metro14@example.com"
    )
    registration_second = fx.add_registration(env, team=team_local_second)

    request_first = fx.add_exception_request(
        env,
        registration=registration_first,
        reason_code=ExceptionReasonCode.LOCAL_TEAM.value,
        requested_rooms_exempt=4,
        justification=_LOCAL_JUSTIFICATION,
    )

    team_visiting = fx.create_team(
        api, name="Lakeside SC 16U", org_contact_email="lakeside@example.com"
    )
    registration_visiting = fx.add_registration(env, team=team_visiting)
    booking = fx.add_booking(env, registration=registration_visiting, rooms_requested=5)
    fx.submit_rooming_list(
        env,
        booking=booking,
        entries=[f.rooming_list_entry(index + 1, occupant_count=3) for index in range(5)],
    )
    fx.confirm_booking(env, booking=booking)

    env.registration = registration_first
    env.exception_request = request_first
    env.bookings = [booking]
    env.blocks = [env.block]
    env.team = team_local_second
    env.registration_second = registration_second
    return env


class TestBookingCreateRequiresContractExecuted:
    """A block only sells rooms once its own contract has been countersigned."""

    def test_a_booking_against_a_merely_negotiating_contract_is_refused(self, api):
        """The block is `OPEN` and the event is `OPEN`, but the contract has only
        been submitted, so the booking is turned away on the contract.

        PRD §3.4: "The contract owning the target block must be `EXECUTED`, or
        `ERR_CONTRACT_NOT_EXECUTED`."

        PRD §2.11: "The governing hotel contract's `status` is `EXECUTED`, where
        the operation requires it — otherwise `ERR_CONTRACT_NOT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/booking_create_requires_contract_executed
        """
        env = _negotiating_contract_with_registration_env(api)
        registration = env.refresh_registration()
        assert env.refresh_contract()["status"] == "NEGOTIATING"

        response = api.create_booking(
            f.booking_payload(
                registration["id"], env.block_id, registration["version"]
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value, expected_status=409
        )
        assert env.refresh_block()["status"] == "OPEN"

    def test_the_identical_request_succeeds_once_the_hotel_countersigns(self, api):
        """Nothing about the booking changes; only the contract does, and the same
        four-room request is then created at `DRAFT`.

        PRD §3.4: "A booking that clears all of that is created with
        `booking_status` `DRAFT` and `rebate_status` `NOT_DUE`."

        PRD §3.4: "The server computes `nights` as the whole days from
        `check_in_date` up to but not including `check_out_date`, and
        `projected_room_nights` as `rooms_requested` multiplied by `nights` — the
        pre-stay estimate that cancellation penalties are assessed against."

        PRD §3.4: "Creation alone leaves the block's `rooms_committed`,
        `rooms_available` and `utilization_pct` **untouched** — confirmation is
        the only trigger that moves them."

        Design: Difficulty/cross_entity_state_dependency/booking_create_requires_contract_executed
        """
        env = _negotiating_contract_with_registration_env(api)
        registration = env.refresh_registration()
        payload = f.booking_payload(
            registration["id"], env.block_id, registration["version"]
        )
        validate_error(
            api.create_booking(payload, HM),
            ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value,
            expected_status=409,
        )

        contract = get_success_data(
            api.negotiate_contract(
                env.contract_id,
                f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
                env.hotel_headers,
            )
        )
        booking = validate_success(api.create_booking(payload, HM), expected_status=201)

        assert contract["status"] == "EXECUTED"
        assert booking["booking_status"] == "DRAFT"
        assert booking["rooms_requested"] == 4
        assert booking["projected_room_nights"] == 12
        block = env.refresh_block()
        assert block["status"] == "OPEN"
        assert block["rooms_committed"] == 0


class TestExceptionAutoApprovalRequiresTournamentConstrained:
    """Identical local filings, decided differently by the event's own pressure."""

    def test_the_filing_made_before_the_event_sold_out_still_needs_a_reviewer(
        self, api
    ):
        """Filed while `housing_pressure` was `NORMAL`, the first local request
        sits at `SUBMITTED` with nothing granted, and its registration keeps its
        full four-room requirement.

        PRD §3.6: "A request normally lands at `SUBMITTED` with `review_round` 0,
        `appeal_count` 0, `approved_rooms_exempt` 0 and `decided_by_user_id`
        null."

        PRD §3.3: "First, `exempt_rooms_granted` becomes the sum of
        `approved_rooms_exempt` across the registration's exception requests
        whose `status` is `APPROVED`; requests sitting at `SUBMITTED`,
        `UNDER_REVIEW`, `INFO_REQUESTED` or `DENIED` contribute nothing."

        PRD §3.3: "At creation the server derives `local_team_flag` by reading the
        referenced team's `distance_miles_from_venue` and testing it against a
        local radius of thirty miles: the flag is `true` when the team's home city
        lies at or within thirty miles of the venue, and `false` otherwise."

        Design: Difficulty/cross_entity_state_dependency/exception_auto_approval_requires_tournament_constrained
        """
        env = _sold_out_event_with_two_local_teams_env(api)
        tournament = env.refresh_tournament()
        assert tournament["housing_pressure"] == "CONSTRAINED"
        assert tournament["sold_out_contract_count"] == 1

        validate_success(
            api.create_exception_request(
                f.exception_request_payload(
                    env.registration_second["id"],
                    reason_code=ExceptionReasonCode.LOCAL_TEAM.value,
                    requested_rooms_exempt=4,
                    justification=_LOCAL_JUSTIFICATION,
                ),
                HM,
            ),
            expected_status=201,
        )

        first_request = env.refresh_exception_request()
        assert first_request["status"] == "SUBMITTED"
        assert first_request["approved_rooms_exempt"] == 0
        registration = env.refresh_registration()
        assert registration["local_team_flag"] is True
        assert registration["exempt_rooms_granted"] == 0
        assert registration["effective_required_rooms"] == 4
        assert registration["status"] == "PENDING_HOUSING"

    def test_the_filing_made_after_the_event_sold_out_is_approved_by_the_system(
        self, api
    ):
        """The second, identical request short-circuits straight to `APPROVED`
        with the full grant, credited to `SYSTEM_AUTO` and with no review round
        ever opened.

        PRD §3.6: "When the `reason_code` is `LOCAL_TEAM`, the registration's
        `local_team_flag` is `true`, **and** the tournament's `housing_pressure`
        reads `CONSTRAINED`, the request is auto-approved at filing time: it goes
        straight from `SUBMITTED` to `APPROVED`, `approved_rooms_exempt` is set to
        the full `requested_rooms_exempt`, `decided_by_user_id` is set to the
        literal `SYSTEM_AUTO`, and `review_round` stays at 0 because no human
        review ever began."

        PRD §3.3: "Otherwise, if `effective_required_rooms` has fallen to 0 **and**
        `exempt_rooms_granted` is at least 1, the registration is
        `EXCEPTION_GRANTED`, recording that it was excused rather than that it
        complied."

        Design: Difficulty/cross_entity_state_dependency/exception_auto_approval_requires_tournament_constrained
        """
        env = _sold_out_event_with_two_local_teams_env(api)
        second_registration = env.registration_second

        second_request = validate_success(
            api.create_exception_request(
                f.exception_request_payload(
                    second_registration["id"],
                    reason_code=ExceptionReasonCode.LOCAL_TEAM.value,
                    requested_rooms_exempt=4,
                    justification=_LOCAL_JUSTIFICATION,
                ),
                HM,
            ),
            expected_status=201,
        )

        assert second_request["status"] == "APPROVED"
        assert second_request["approved_rooms_exempt"] == 4
        assert second_request["decided_by_user_id"] == SYSTEM_AUTO
        assert second_request["review_round"] == 0
        refreshed = get_success_data(
            api.get_team_registration(second_registration["id"], HM)
        )
        assert refreshed["local_team_flag"] is True
        assert refreshed["exempt_rooms_granted"] == 4
        assert refreshed["effective_required_rooms"] == 0
        assert refreshed["status"] == "EXCEPTION_GRANTED"
