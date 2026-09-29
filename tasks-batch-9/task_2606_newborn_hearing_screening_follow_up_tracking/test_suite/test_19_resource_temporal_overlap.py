"""Two calendars with two different interval rules: a provider's, and a family's."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import factories, fixtures
from test_helpers.test_users import (
    make_audiologist_headers,
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()

BIRTH = "2026-08-02T00:00:00Z"


def _clinic_with_two_audiologists(client):
    """One audiologist already staffing a nine-to-ten window, and a colleague who is free."""
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    first = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    second = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A2", "R1")
    clinic_admin = make_facility_admin_headers(clinic["id"])

    def _publish(provider_id, starts_at, ends_at, total_capacity=1):
        return client.create_slot(
            factories.slot_payload(
                facility_id=clinic["id"],
                provider_id=provider_id,
                starts_at=starts_at,
                ends_at=ends_at,
                slot_type="RESCREEN",
                total_capacity=total_capacity,
            ),
            headers=clinic_admin,
        )

    base = check.assert_created(
        _publish(first["id"], "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z", 2)
    )
    return first, second, base, _publish


def test_an_intersecting_window_is_refused_while_a_touching_one_is_published(client):
    """Half-open semantics: 09:30 collides with 09:00-10:00, but 10:00 does not.

    PRD: "a new slot for a provider is rejected with `ERR_SLOT_OVERLAP` when that
    provider already staffs a slot whose window intersects the new one — that is, when
    the new window's start falls strictly before the existing window's end and the
    existing window's start falls strictly before the new window's end. Windows that
    merely touch, where the new slot's `starts_at` equals the existing slot's
    `ends_at`, are permitted"

    Design: Difficulty/resource_temporal_overlap/provider_clinic_slot_half_open_overlap_rejects_but_touching_slots_allowed
    """
    first, _, base, publish = _clinic_with_two_audiologists(client)

    collision = publish(first["id"], "2026-08-10T09:30:00Z", "2026-08-10T10:30:00Z")
    check.assert_error_envelope(collision, errors.ERR_SLOT_OVERLAP)
    assert collision.status_code == 409

    touching = check.assert_created(
        publish(first["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
    )
    check.assert_instant_equals(touching["starts_at"], "2026-08-10T10:00:00Z")
    check.assert_slot_capacity(touching, 0, 1, "OPEN")

    rows = check.assert_total_count(
        client.list_slots(headers=ADMIN, provider_id=first["id"]), 2
    )
    assert {row["id"] for row in rows} == {base["id"], touching["id"]}


def test_the_exclusivity_belongs_to_the_provider_not_the_clinic(client):
    """The window refused to one audiologist is published for the other.

    PRD: "Slots are exclusive per staffing provider under half-open semantics"

    Design: Difficulty/resource_temporal_overlap/provider_clinic_slot_half_open_overlap_rejects_but_touching_slots_allowed
    """
    first, second, base, publish = _clinic_with_two_audiologists(client)

    overlapping_from_below = publish(
        first["id"], "2026-08-10T08:30:00Z", "2026-08-10T09:30:00Z"
    )
    check.assert_error_envelope(overlapping_from_below, errors.ERR_SLOT_OVERLAP)

    touching_from_below = check.assert_created(
        publish(first["id"], "2026-08-10T08:00:00Z", "2026-08-10T09:00:00Z")
    )
    assert touching_from_below["provider_id"] == first["id"]

    for_the_colleague = check.assert_created(
        publish(second["id"], "2026-08-10T09:30:00Z", "2026-08-10T10:30:00Z")
    )
    assert for_the_colleague["provider_id"] == second["id"]
    check.assert_slot_capacity(for_the_colleague, 0, 1, "OPEN")

    check.assert_total_count(client.list_slots(headers=ADMIN, provider_id=first["id"]), 2)
    check.assert_total_count(client.list_slots(headers=ADMIN, provider_id=second["id"]), 1)
    check.assert_slot_capacity(fixtures.read_slot(client, base["id"]), 0, 2, "OPEN")


def _family_with_one_attended_visit(client):
    """An infant who has attended a nine-o'clock rescreen and needs one more visit."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    first = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    second = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A2", "R1")
    screener_headers = make_facility_screener_headers(screener["id"])

    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-W",
        guardian_contact_phone="5551301",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at="2026-08-02T05:00:00Z",
                encounter_type="BIRTH_ADMISSION",
                method="AABR",
                left_ear_result="REFER",
                right_ear_result="PASS",
            ),
            headers=screener_headers,
        )
    )
    rescreen = fixtures.episodes_of(client, infant["id"])[0]

    def _publish(provider_id, starts_at, ends_at):
        return client.create_slot(
            factories.slot_payload(
                facility_id=clinic["id"],
                provider_id=provider_id,
                starts_at=starts_at,
                ends_at=ends_at,
                slot_type="RESCREEN",
                total_capacity=1,
            ),
            headers=ADMIN,
        )

    attended_slot = check.assert_created(
        _publish(first["id"], "2026-09-10T09:00:00Z", "2026-09-10T10:00:00Z")
    )
    appointment = fixtures.book(client, rescreen["id"], attended_slot["id"], headers=ADMIN)

    # The visit happens and the ears pass, so the appointment is ATTENDED and the
    # episode resolves, leaving the infant with no active episode at all.
    fixtures.set_clock(client, "2026-09-10T10:30:00Z")
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=clinic["id"],
                performed_by_provider_id=first["id"],
                performed_at="2026-09-10T09:30:00Z",
                encounter_type="OUTPATIENT_RESCREEN",
                method="AABR",
                left_ear_result="PASS",
                right_ear_result="PASS",
                episode_id=rescreen["id"],
                appointment_id=appointment["id"],
            ),
            headers=make_audiologist_headers(first["id"]),
        )
    )
    assert fixtures.read_appointment(client, appointment["id"])["status"] == "ATTENDED"
    check.assert_episode_state(
        fixtures.read_episode(client, rescreen["id"]),
        "RESOLVED_PASS",
        closure_reason="RESCREEN_PASSED",
    )

    surveillance = fixtures.open_episode(
        client,
        infant["id"],
        "RESCREEN",
        expected_infant_version=fixtures.infant_version(client, infant["id"]),
    )
    check.assert_episode_state(surveillance, "PENDING_SCHEDULING", benchmark_days=30)
    eleven_hours_later = check.assert_created(
        _publish(second["id"], "2026-09-10T20:00:00Z", "2026-09-10T21:00:00Z")
    )
    exactly_a_day_later = check.assert_created(
        _publish(second["id"], "2026-09-11T09:00:00Z", "2026-09-11T10:00:00Z")
    )
    return {
        "infant": infant,
        "attended_slot": attended_slot,
        "attended_appointment": appointment,
        "episode": surveillance,
        "eleven_hours_later": eleven_hours_later,
        "exactly_a_day_later": exactly_a_day_later,
    }


def test_two_visits_eleven_hours_apart_are_refused_though_the_windows_never_meet(client):
    """The buffer measures start instants, so non-overlapping windows still collide.

    PRD: "no other appointment of the same infant whose status is `BOOKED` or
    `ATTENDED` may sit on a slot whose `starts_at` is strictly less than 24 hours away
    from the requested slot's `starts_at` in either direction — the absolute difference
    must be at least 86400 seconds, and exactly 24 hours apart is allowed — else
    `ERR_FAMILY_BURDEN_BUFFER`"

    Design: Difficulty/resource_temporal_overlap/family_burden_buffer_rejects_11_hours_apart_but_allows_exactly_24_hours
    """
    scenario = _family_with_one_attended_visit(client)

    refused = client.create_appointment(
        factories.appointment_payload(
            episode_id=scenario["episode"]["id"],
            slot_id=scenario["eleven_hours_later"]["id"],
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(refused, errors.ERR_FAMILY_BURDEN_BUFFER)
    assert refused.status_code == 409

    check.assert_slot_capacity(
        fixtures.read_slot(client, scenario["eleven_hours_later"]["id"]), 0, 1, "OPEN"
    )
    check.assert_episode_state(
        fixtures.read_episode(client, scenario["episode"]["id"]),
        "PENDING_SCHEDULING",
        attempt_count=0,
    )
    check.assert_total_count(
        client.list_appointments(headers=ADMIN, infant_id=scenario["infant"]["id"]), 1
    )


def test_a_visit_exactly_a_day_later_is_allowed(client):
    """Eighty-six thousand four hundred seconds is far enough apart, to the second.

    PRD: "the encounter's `appointment_id` appointment moves `BOOKED → ATTENDED`, and
    the slot's `booked_count` is deliberately left unchanged, because an attended
    appointment still occupies its capacity."

    Design: Difficulty/resource_temporal_overlap/family_burden_buffer_rejects_11_hours_apart_but_allows_exactly_24_hours
    """
    scenario = _family_with_one_attended_visit(client)
    check.assert_error_envelope(
        client.create_appointment(
            factories.appointment_payload(
                episode_id=scenario["episode"]["id"],
                slot_id=scenario["eleven_hours_later"]["id"],
            ),
            headers=ADMIN,
        ),
        errors.ERR_FAMILY_BURDEN_BUFFER,
    )

    booked = check.assert_created(
        client.create_appointment(
            factories.appointment_payload(
                episode_id=scenario["episode"]["id"],
                slot_id=scenario["exactly_a_day_later"]["id"],
            ),
            headers=ADMIN,
        )
    )
    assert booked["status"] == "BOOKED"
    assert booked["infant_id"] == scenario["infant"]["id"]

    check.assert_episode_state(
        fixtures.read_episode(client, scenario["episode"]["id"]),
        "SCHEDULED",
        attempt_count=1,
    )
    check.assert_slot_capacity(
        fixtures.read_slot(client, scenario["exactly_a_day_later"]["id"]), 1, 0, "FULL"
    )
    # The earlier visit was attended, so it still holds the capacity it booked.
    assert (
        fixtures.read_appointment(client, scenario["attended_appointment"]["id"])["status"]
        == "ATTENDED"
    )
    check.assert_slot_capacity(
        fixtures.read_slot(client, scenario["attended_slot"]["id"]), 1, 0, "FULL"
    )
