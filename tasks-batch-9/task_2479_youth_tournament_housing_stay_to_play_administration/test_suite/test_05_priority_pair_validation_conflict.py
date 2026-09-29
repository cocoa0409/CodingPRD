"""Requests that break two rules at once, where only the earlier one is heard.

Each pair here is arranged so the losing check is genuinely violated: a second
test lifts the winning check and shows the masked error surfacing underneath.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    validate_error,
)

HM = HOUSING_MANAGER_HEADERS


def _registered_team_on_a_large_block_env(api) -> fx.Env:
    """A 13-player, 3-staff registration — a ceiling of six rooms — against a
    twenty-room block that has ample capacity for nine."""
    env = fx.executed_contract_env(api)
    fx.add_team(env)
    fx.add_registration(env)
    return env


def _draft_two_room_booking_env(api) -> fx.Env:
    """A two-room `DRAFT` booking for a six-person roster, so any manifest of
    eight occupants breaks the occupancy total."""
    env = fx.executed_contract_env(api)
    fx.add_team(env)
    fx.add_registration(env, roster_player_count=5, roster_staff_count=1)
    fx.add_booking(env, rooms_requested=2)
    return env


class TestStateBeatsFiscalOnBookingCreate:
    """Posture outranks the roster ceiling on booking creation."""

    def test_a_closed_window_is_reported_before_the_oversized_room_request(self, api):
        """Nine rooms against a ceiling of six, on an event whose window has
        shut, is refused for the posture and not for the room count.

        PRD §2.11: "Checks are evaluated in the fixed order below, and the first
        failing check produces the response; later checks are not evaluated and
        cannot mask an earlier one."

        PRD §2.11: "The governing tournament's `posture` is `OPEN`, where the
        operation requires it — otherwise `ERR_TOURNAMENT_NOT_OPEN`."

        PRD §3.1: "Operations that require `OPEN` and find something later are
        rejected with `ERR_TOURNAMENT_NOT_OPEN`; operations that require
        `BOOKING_CLOSED` or `RECONCILING` and find `OPEN` or `SETTLED` are
        rejected with `ERR_TOURNAMENT_NOT_RECONCILING`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_create
        """
        env = _registered_team_on_a_large_block_env(api)
        fx.close_booking_window(env)
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.block_id,
                registration["version"],
                rooms_requested=9,
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_TOURNAMENT_NOT_OPEN.value, expected_status=409
        )
        assert env.refresh_tournament()["posture"] == "BOOKING_CLOSED"
        assert registration["required_rooms_registered"] == 6
        assert env.refresh_block()["rooms_committed"] == 0

    def test_the_same_room_count_is_refused_on_its_own_terms_while_the_window_is_open(
        self, api
    ):
        """With the posture still `OPEN`, the very same nine-room request is
        refused on the segregated-occupancy ceiling, so the masked check was real.

        PRD §2.11: "`rooms_requested` does not exceed the registration's
        segregated-occupancy room requirement — otherwise
        `ERR_ROOMS_EXCEED_ROSTER_REQUIREMENT`."

        PRD §3.4: "`rooms_requested` may not exceed the registration's
        `required_rooms_registered` — the segregated-occupancy figure,
        deliberately not the pooled `minimum_rooms_for_compliance` — or the
        request is rejected with `ERR_ROOMS_EXCEED_ROSTER_REQUIREMENT`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_create
        """
        env = _registered_team_on_a_large_block_env(api)
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.block_id,
                registration["version"],
                rooms_requested=9,
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_ROOMS_EXCEED_ROSTER_REQUIREMENT.value,
            expected_status=422,
        )
        assert env.refresh_tournament()["posture"] == "OPEN"


class TestSafetyBeatsReferentialOnRoomingList:
    """The chaperone rule outranks the roster-total rule on a rooming list."""

    def test_the_unchaperoned_minors_are_reported_before_the_occupancy_total(self, api):
        """Two rooms of four, two of them minors and no chaperone named, is
        refused for the chaperone even though eight occupants also overrun the
        six-person roster.

        PRD §3.4: "Four content rules police the manifest, and they are checked
        in this order."

        PRD §3.4: "Every entry that reports at least one minor must supply a
        non-empty `chaperone_name`, naming the adult responsible for that room;
        otherwise `ERR_CHAPERONE_REQUIRED`."

        PRD §2.11: "Rooming list submission meets 9, 13, 14, 21, 22, 34, 35 and
        36; an entry set that both omits a chaperone and has the wrong room count
        returns `ERR_CHAPERONE_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_rooming_list
        """
        env = _draft_two_room_booking_env(api)

        response = api.submit_rooming_list(
            env.booking_id,
            f.rooming_list_payload(
                entries=[
                    f.rooming_list_entry(1, occupant_count=4, minor_occupant_count=2),
                    f.rooming_list_entry(2, occupant_count=4, minor_occupant_count=0),
                ]
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_CHAPERONE_REQUIRED.value, expected_status=422
        )
        assert env.refresh_booking()["booking_status"] == "DRAFT"

    def test_naming_the_chaperone_exposes_the_roster_overrun_underneath(self, api):
        """The identical manifest with a chaperone on the minors' room is then
        refused for its eight occupants against a roster of six.

        PRD §3.4: "Finally the total occupancy is bounded: the sum of
        `occupant_count` across the submitted entries must be at least 1 and no
        more than the registration's `roster_player_count` plus
        `roster_staff_count`, or `ERR_ROOMING_LIST_OCCUPANT_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_rooming_list
        """
        env = _draft_two_room_booking_env(api)

        response = api.submit_rooming_list(
            env.booking_id,
            f.rooming_list_payload(
                entries=[
                    f.rooming_list_entry(
                        1,
                        occupant_count=4,
                        minor_occupant_count=2,
                        chaperone_name="Dana Reyes",
                    ),
                    f.rooming_list_entry(2, occupant_count=4, minor_occupant_count=0),
                ]
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_ROOMING_LIST_OCCUPANT_MISMATCH.value,
            expected_status=422,
        )
        assert env.refresh_booking()["booking_status"] == "DRAFT"
