"""Optimistic concurrency on the booking and the time-boxed weather hold."""

from test_helpers import (
    ERR_STALE_BOOKING_VERSION,
    assert_instant,
    assert_money,
    assert_one_decimal,
    assert_posture,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_TEST_UTC
from test_helpers.factories import participant_payload
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    create_booking,
    create_course,
    create_funded_client,
    observe_weather,
    set_clock,
    staffed_course,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_group_coordinator_headers

CLOCK_AFTER_HOLD_UTC = "2026-08-10T09:00:00Z"
HOLD_UNTIL_UTC = "2026-08-10T08:30:00Z"
STRIKE_DISTANCE_KM = 6.0
CALM_WIND_KPH = 10.0
MILD_TEMP_C = 24.0


class TestQuoteVersionGuard:
    """A quote run computed from a roster the writer never saw is refused outright."""

    def test_replaying_the_creation_version_after_a_roster_write_is_refused(self, api):
        """The roster addition consumed the version, so the stale quote cannot run.

        PRD 2.11: "Running or re-running a quote requires `expected_booking_version`
        in the request body as a non-optional field, carrying the `version` of the
        booking the client last read. If it does not equal the booking's current
        `version`, the quote is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP
        412)."

        PRD 3.6: "Every roster write increments the owning booking's `version`."

        PRD 3.5: "Every successful run increments `quote_index` and the booking's
        `version`."

        Design: Corner/complexity_layers/quote_with_a_stale_booking_version_rejected
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        gc_id = create_funded_client(api, amount_cents=0)
        b_id, v0 = create_booking(api, course_id, gc_id, 1)
        add_blocks(
            api, b_id, [(1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z")]
        )
        add_participant(api, gc_id, b_id, "ADULT")

        validate_error(
            api.quote_booking(b_id, {"expected_booking_version": v0}, PROGRAM_DIRECTOR),
            ERR_STALE_BOOKING_VERSION,
            412,
        )

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["status"] == "DRAFT"
        assert booking["quote_index"] == 0
        assert_money(booking["quoted_total_cents"], 0, "quoted_total_cents")


class TestParticipantVersionGuard:
    """Two roster writers cannot both spend the same observed version."""

    def test_a_second_roster_write_on_the_same_version_is_refused(self, api):
        """The first addition bumped the version, so the replay never lands.

        PRD 2.11: "Adding a participant to a booking likewise requires
        `expected_booking_version` in the request body as a non-optional field,
        matched against the booking's current `version`, and a mismatch is rejected
        with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

        PRD 2.11: "A roster addition supersedes the booking's frozen
        `billable_head_count` and its `roster_status`, and nothing else in the
        specification would refuse it, so this is the only guard that stops a
        coordinator from extending a roster whose quote or screening posture it has
        not seen."

        PRD 3.6: "The participant is `BLOCKED` if `agreement_signed` is false, or
        `health_form_status` is `MISSING`, or the participant is a minor whose
        `guardian_signature_provided` is false."

        Design: Corner/complexity_layers/participant_added_with_a_stale_booking_version_rejected
        """
        set_clock(api, CLOCK_TEST_UTC)
        course_id = create_course(api)
        gc_id = create_funded_client(api, amount_cents=0)
        gc_headers = make_group_coordinator_headers(gc_id)
        b_id, v0 = create_booking(api, course_id, gc_id, 2)

        first = validate_success(
            api.create_participant(participant_payload(b_id, v0, "ADULT"), gc_headers), 201
        )
        assert first["screening_status"] == "BLOCKED"

        validate_error(
            api.create_participant(participant_payload(b_id, v0, "CHAPERONE"), gc_headers),
            ERR_STALE_BOOKING_VERSION,
            412,
        )

        rows, meta = validate_paginated(
            api.list_participants(PROGRAM_DIRECTOR, params={"booking_id": b_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

        booking = validate_success(api.get_booking(b_id, PROGRAM_DIRECTOR))
        assert booking["roster_status"] == "BLOCKED"


class TestLightningHoldIsTimeBoxed:
    """The stop lasts thirty minutes, not as long as the reading stays on the record."""

    def test_the_checkpoint_releases_an_expired_hold_and_reopens_the_site(self, api):
        """The strike distance is unchanged and the site still reopens once the window passes.

        PRD 3.9: "Lightning at 8.0 km or nearer is a stop: it sets the course's
        `lightning_hold_until` to the later of its existing value and the
        observation's `observed_at` plus thirty minutes."

        PRD 3.9: "A hold counts as active while `lightning_hold_until` is set and
        lies strictly after the current clock instant; expired holds are cleared by
        the daily opening checkpoint before posture is re-derived, which is what
        allows a stopped site to reopen."

        PRD 3.1: "Step two clears `lightning_hold_until` when it is at or before the
        current clock instant."

        PRD 2.5: "`latest_lightning_distance_km` is greater than 8.0 and at most
        16.0. Result: `RESTRICTED`, reason `LIGHTNING_WATCH`."

        Design: Corner/complexity_layers/lightning_hold_expiry_released_by_the_daily_open_checkpoint
        """
        set_clock(api, CLOCK_TEST_UTC)
        world = staffed_course(api)

        observation = observe_weather(
            api,
            world["course_id"],
            world["f1_headers"],
            observed_at=CLOCK_TEST_UTC,
            lightning_distance_km=STRIKE_DISTANCE_KM,
            wind_speed_kph=CALM_WIND_KPH,
            air_temp_c=MILD_TEMP_C,
        )

        assert observation["resulting_posture"] == "CLOSED"
        assert observation["resulting_posture_reason"] == "LIGHTNING_STOP"
        assert_instant(observation["hold_until"], HOLD_UNTIL_UTC, "hold_until")

        closed = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert_posture(closed, "CLOSED", "LIGHTNING_STOP")

        set_clock(api, CLOCK_AFTER_HOLD_UTC)

        opened = validate_success(api.daily_open(world["course_id"], PROGRAM_DIRECTOR))

        assert_posture(opened, "OPEN", "NONE")
        assert opened["lightning_hold_until"] is None
        assert_one_decimal(
            opened["latest_lightning_distance_km"],
            STRIKE_DISTANCE_KM,
            "latest_lightning_distance_km",
        )
        assert opened["daily_open_index"] == 1
