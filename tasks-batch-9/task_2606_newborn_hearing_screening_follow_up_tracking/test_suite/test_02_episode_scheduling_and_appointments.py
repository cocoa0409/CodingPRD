"""Booking an episode into a clinic slot, and the guards around that edge."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_navigator_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()


def _community_network(client, navigator_languages=None):
    """A midwife practice, an audiology clinic, and the staff behind both."""
    practice = fixtures.create_facility(client, "MW1", "MIDWIFE_PRACTICE", "R1")
    screener = fixtures.create_provider(client, practice["id"], "SCREENER", "S1", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    navigator = fixtures.create_provider(
        client,
        clinic["id"],
        "NAVIGATOR",
        "N1",
        "R1",
        languages=navigator_languages,
    )
    fixtures.set_clock(client, clock.at(hours=6))
    return {
        "practice": practice,
        "screener": screener,
        "clinic": clinic,
        "audiologist": audiologist,
        "navigator": navigator,
        "screener_headers": make_facility_screener_headers(screener["id"]),
        "clinic_admin": make_facility_admin_headers(clinic["id"]),
        "navigator_headers": make_navigator_headers(navigator["id"]),
    }


def _home_birth_infant(client, network, birth_datetime=CLOCK_START, **overrides):
    payload = factories.infant_payload(
        birth_facility_id=network["practice"]["id"],
        birth_datetime=birth_datetime,
        birth_setting="HOME_BIRTH",
        guardian_name=overrides.pop("guardian_name", "G-H"),
        guardian_contact_phone=overrides.pop("guardian_contact_phone", "5553001"),
        **overrides
    )
    return check.assert_created(
        client.create_infant(payload, headers=network["screener_headers"])
    )


def _publish_rescreen_slot(client, network, starts_at, ends_at, total_capacity=None):
    return check.assert_created(
        client.create_slot(
            factories.slot_payload(
                facility_id=network["clinic"]["id"],
                provider_id=network["audiologist"]["id"],
                starts_at=starts_at,
                ends_at=ends_at,
                slot_type="RESCREEN",
                total_capacity=total_capacity,
            ),
            headers=network["clinic_admin"],
        )
    )


def test_booking_moves_the_capture_episode_to_scheduled(client):
    """The first booking schedules the episode and re-derives its attempt count.

    PRD: "Its `attempt_count` always equals the number of appointments on it whose
    status is `BOOKED`, `ATTENDED`, or `NO_SHOW`."

    Design: Corner/state_machines/episode_pending_scheduling_to_scheduled_on_booking
    """
    network = _community_network(client)
    infant = _home_birth_infant(client, network)
    episode = fixtures.episodes_of(client, infant["id"])[0]
    slot = _publish_rescreen_slot(client, network, "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")

    response = client.create_appointment(
        factories.appointment_payload(episode_id=episode["id"], slot_id=slot["id"]),
        headers=network["navigator_headers"],
    )
    appointment = check.assert_created(response)
    assert appointment["status"] == "BOOKED"
    assert appointment["infant_id"] == infant["id"]
    assert appointment["interpreter_needed"] is False
    assert appointment["linked_navigation_task_id"] is None

    stored_episode = fixtures.read_episode(client, episode["id"])
    check.assert_episode_state(
        stored_episode, "SCHEDULED", benchmark_days=30, attempt_count=1
    )
    assert stored_episode["episode_type"] == "INITIAL_SCREEN"
    check.assert_instant_equals(stored_episode["due_date"], "2026-08-31T00:00:00Z")

    check.assert_slot_capacity(fixtures.read_slot(client, slot["id"]), 1, 0, "FULL")
    check.assert_risk(fixtures.read_infant(client, infant["id"]), 15, "ELEVATED")


def test_booking_into_a_full_slot_is_refused(client):
    """A capacity-1 slot admits one family; the second booking is refused.

    PRD: "the slot must have `remaining_capacity` of at least 1, that is `status`
    `OPEN`, else `ERR_SLOT_FULL`"

    Design: Corner/state_machines/booking_into_a_full_slot_returns_slot_full
    """
    network = _community_network(client)
    first_infant = _home_birth_infant(
        client, network, guardian_name="G-H1", guardian_contact_phone="5553101"
    )
    second_infant = _home_birth_infant(
        client,
        network,
        birth_datetime=clock.at(hours=1),
        guardian_name="G-H2",
        guardian_contact_phone="5553102",
    )
    first_episode = fixtures.episodes_of(client, first_infant["id"])[0]
    second_episode = fixtures.episodes_of(client, second_infant["id"])[0]
    slot = _publish_rescreen_slot(
        client, network, "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z", total_capacity=1
    )
    fixtures.book(
        client, first_episode["id"], slot["id"], headers=network["navigator_headers"]
    )

    response = client.create_appointment(
        factories.appointment_payload(episode_id=second_episode["id"], slot_id=slot["id"]),
        headers=network["navigator_headers"],
    )
    check.assert_error_envelope(response, errors.ERR_SLOT_FULL)

    check.assert_episode_state(
        fixtures.read_episode(client, second_episode["id"]),
        "PENDING_SCHEDULING",
        attempt_count=0,
    )
    check.assert_slot_capacity(fixtures.read_slot(client, slot["id"]), 1, 0, "FULL")
    check.assert_total_count(
        client.list_appointments(headers=ADMIN, slot_id=slot["id"]), 1
    )


def test_interpreter_booking_reserves_units_and_links_the_task(client):
    """Asking for interpreter support mints, assigns and funds the session task.

    PRD: "The cost of a task is a base of 2 units, plus a further 3 units when the
    infant's `interpreter_required` flag is set, plus a further 4 units when the
    `task_type` is `HOME_VISIT`."

    Design: Corner/state_machines/interpreter_booking_reserves_five_units_and_links_the_task
    """
    network = _community_network(client, navigator_languages=["EN", "ES"])
    infant = _home_birth_infant(
        client,
        network,
        guardian_name="G-ES",
        guardian_contact_phone="5553201",
        preferred_language="ES",
        interpreter_required=True,
    )
    episode = fixtures.episodes_of(client, infant["id"])[0]
    slot = _publish_rescreen_slot(
        client, network, "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z", total_capacity=2
    )

    appointment = check.assert_created(
        client.create_appointment(
            factories.appointment_payload(
                episode_id=episode["id"], slot_id=slot["id"], interpreter_needed=True
            ),
            headers=network["navigator_headers"],
        )
    )
    assert appointment["status"] == "BOOKED"
    assert appointment["interpreter_needed"] is True
    task_id = appointment["linked_navigation_task_id"]
    assert task_id is not None

    task = fixtures.read_task(client, task_id)
    assert task["task_type"] == "INTERPRETER_SESSION"
    assert task["episode_id"] == episode["id"]
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == network["navigator"]["id"]
    assert task["units_reserved"] == 5
    assert task["budget_shortfall_flag"] is False

    practice = fixtures.read_facility(client, network["practice"]["id"])
    check.assert_facility_ledger(practice, navigation_budget_units_remaining=35)
    check.assert_slot_capacity(fixtures.read_slot(client, slot["id"]), 1, 1, "OPEN")
    check.assert_risk(fixtures.read_infant(client, infant["id"]), 7, "LOW")


def test_a_scheduled_episode_cannot_be_booked_again(client):
    """A second booking on the same episode is refused on the episode's state.

    PRD: "the episode must be in `PENDING_SCHEDULING`, else
    `ERR_EPISODE_NOT_SCHEDULABLE`"

    Design: Corner/state_machines/second_booking_on_a_scheduled_episode_returns_episode_not_schedulable
    """
    network = _community_network(client)
    infant = _home_birth_infant(
        client, network, guardian_contact_phone="5553301"
    )
    episode = fixtures.episodes_of(client, infant["id"])[0]
    first_slot = _publish_rescreen_slot(
        client, network, "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"
    )
    second_slot = _publish_rescreen_slot(
        client, network, "2026-08-07T09:00:00Z", "2026-08-07T10:00:00Z"
    )
    fixtures.book(client, episode["id"], first_slot["id"], headers=network["navigator_headers"])

    response = client.create_appointment(
        factories.appointment_payload(episode_id=episode["id"], slot_id=second_slot["id"]),
        headers=network["navigator_headers"],
    )
    check.assert_error_envelope(response, errors.ERR_EPISODE_NOT_SCHEDULABLE)

    check.assert_episode_state(
        fixtures.read_episode(client, episode["id"]), "SCHEDULED", attempt_count=1
    )
    second_stored = fixtures.read_slot(client, second_slot["id"])
    assert second_stored["booked_count"] == 0
    assert second_stored["status"] == "OPEN"


def test_closing_an_episode_cancels_its_appointment_and_frees_the_slot(client):
    """Closing the episode reaches into the appointment and the slot ledger.

    PRD: "It advances to `CLOSED_DECLINED` with the supplied reason and `closed_at`
    set to the logical clock, any appointment on it still in `BOOKED` becomes
    `CANCELLED` and releases its slot capacity"

    Design: Corner/state_machines/episode_close_cancels_the_booked_appointment_and_frees_slot_capacity
    """
    network = _community_network(client)
    infant = _home_birth_infant(
        client, network, guardian_name="G-X", guardian_contact_phone="5553701"
    )
    episode = fixtures.episodes_of(client, infant["id"])[0]
    slot = _publish_rescreen_slot(client, network, "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    appointment = fixtures.book(
        client, episode["id"], slot["id"], headers=network["navigator_headers"]
    )

    closed = check.assert_ok(
        client.close_episode(
            episode["id"],
            {"closure_reason": "FAMILY_DECLINED"},
            headers=network["navigator_headers"],
        )
    )
    check.assert_episode_state(
        closed, "CLOSED_DECLINED", closure_reason="FAMILY_DECLINED", attempt_count=0
    )
    check.assert_instant_equals(closed["closed_at"], clock.at(hours=6))

    assert fixtures.read_appointment(client, appointment["id"])["status"] == "CANCELLED"
    check.assert_slot_capacity(fixtures.read_slot(client, slot["id"]), 0, 1, "OPEN")


@pytest.mark.parametrize(
    "ends_at",
    ["2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"],
    ids=["backwards", "zero_length"],
)
def test_a_slot_window_that_does_not_advance_is_refused(client, ends_at):
    """Neither a backwards window nor a zero-length one can hold an appointment.

    PRD: "An `ends_at` that is not strictly after `starts_at` is rejected with
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/slot_ending_before_it_starts_returns_invalid_window
    """
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))

    refused = client.create_slot(
        factories.slot_payload(
            facility_id=clinic["id"],
            provider_id=audiologist["id"],
            starts_at="2026-08-05T09:00:00Z",
            ends_at=ends_at,
            slot_type="RESCREEN",
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(refused, errors.ERR_INVALID_WINDOW)
    check.assert_total_count(
        client.list_slots(headers=ADMIN, provider_id=audiologist["id"]), 0
    )


def test_the_slot_type_rule_waits_for_the_episode_to_resolve(client):
    """An unknown episode is a not-found; the resolved one exposes the type mismatch.

    PRD: "the slot's `slot_type` must be `RESCREEN` for an `INITIAL_SCREEN` or
    `RESCREEN` episode and `DIAGNOSTIC` for a `DIAGNOSTIC` episode, else
    `ERR_SLOT_TYPE_MISMATCH`"

    Design: Corner/validations/slot_type_check_runs_only_after_the_episode_row_is_resolved
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-CS",
        guardian_contact_phone="5555001",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at=clock.at(hours=4),
                encounter_type="BIRTH_ADMISSION",
                method="OAE",
                left_ear_result="REFER",
                right_ear_result="REFER",
            ),
            headers=make_facility_screener_headers(screener["id"]),
        )
    )
    navigator_headers = make_navigator_headers(navigator["id"])
    diagnostic = fixtures.open_diagnostic_episode(client, infant["id"])
    slot = check.assert_created(
        client.create_slot(
            factories.slot_payload(
                facility_id=clinic["id"],
                provider_id=audiologist["id"],
                starts_at="2026-08-05T09:00:00Z",
                ends_at="2026-08-05T10:00:00Z",
                slot_type="RESCREEN",
            ),
            headers=make_facility_admin_headers(clinic["id"]),
        )
    )

    ghost_episode = client.create_appointment(
        factories.appointment_payload(
            episode_id="00000000-0000-4000-8000-0000000000bb", slot_id=slot["id"]
        ),
        headers=navigator_headers,
    )
    check.assert_error_envelope(ghost_episode, errors.ERR_EPISODE_NOT_FOUND)

    wrong_type = client.create_appointment(
        factories.appointment_payload(episode_id=diagnostic["id"], slot_id=slot["id"]),
        headers=navigator_headers,
    )
    check.assert_error_envelope(wrong_type, errors.ERR_SLOT_TYPE_MISMATCH)

    check.assert_episode_state(
        fixtures.read_episode(client, diagnostic["id"]), "PENDING_SCHEDULING", attempt_count=0
    )
    check.assert_slot_capacity(fixtures.read_slot(client, slot["id"]), 0, 1, "OPEN")


def test_three_no_shows_close_the_booking_door_on_the_episode(client, registry):
    """A fourth attempt is refused, and the past slot fails its earlier check first.

    PRD: "the episode's `attempt_count` must be below 3, else
    `ERR_ATTEMPT_LIMIT_REACHED`"

    Design: Corner/errors/fourth_booking_after_three_no_shows_is_rejected_at_the_attempt_limit
    """
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-AL",
        guardian_contact_phone="5556201",
    )
    referred = fixtures.refer_at_birth(client, registry, infant["id"], clock.at(hours=4))
    episode = referred["episode"]
    slots = [
        fixtures.publish_slot(
            client, registry, "2026-08-%02dT09:00:00Z" % day, "2026-08-%02dT10:00:00Z" % day
        )
        for day in (5, 7, 9, 11)
    ]

    for slot, day in zip(slots[:3], (5, 7, 9)):
        appointment = fixtures.book(client, episode["id"], slot["id"], headers=registry.n1)
        fixtures.set_clock(client, "2026-08-%02dT10:00:00Z" % day)
        fixtures.close_appointment(
            client,
            appointment["id"],
            "NO_SHOW",
            reason="family did not attend",
            headers=registry.n1,
        )
    third_appointment = appointment

    exhausted = fixtures.read_episode(client, episode["id"])
    check.assert_episode_state(exhausted, "PENDING_SCHEDULING", attempt_count=3)
    scored = fixtures.read_infant(client, infant["id"])
    assert scored["missed_appointment_count"] == 3
    check.assert_risk(scored, 18, "ELEVATED")
    for slot in slots[:3]:
        check.assert_slot_capacity(fixtures.read_slot(client, slot["id"]), 0, 1, "OPEN")

    fourth = client.create_appointment(
        factories.appointment_payload(episode_id=episode["id"], slot_id=slots[3]["id"]),
        headers=registry.n1,
    )
    check.assert_error_envelope(fourth, errors.ERR_ATTEMPT_LIMIT_REACHED)
    check.assert_slot_capacity(fixtures.read_slot(client, slots[3]["id"]), 0, 1, "OPEN")

    double_close = client.close_appointment(
        third_appointment["id"],
        {"disposition": "CANCELLED", "reason": "double close"},
        headers=registry.n1,
    )
    check.assert_error_envelope(double_close, errors.ERR_APPOINTMENT_NOT_OPEN)
    assert fixtures.read_appointment(client, third_appointment["id"])["status"] == "NO_SHOW"

    past_slot = client.create_appointment(
        factories.appointment_payload(episode_id=episode["id"], slot_id=slots[0]["id"]),
        headers=registry.n1,
    )
    check.assert_error_envelope(past_slot, errors.ERR_SLOT_IN_PAST)
