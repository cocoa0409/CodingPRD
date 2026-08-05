"""Optimistic concurrency on the site version and on the visit's own version."""

from test_helpers import (
    ApiErrorId,
    amend_encounter,
    api_client,
    read_site,
    read_visit,
    setup_clinic,
    setup_completed_visit,
    validate_error,
    validate_success,
)


def test_second_booking_with_stale_site_version_rejected():
    """PRD §2.9: "**Booking an appointment** — `POST /appointments` — requires
    `expected_site_version`, carrying the client's last observed `version` of the
    target `Site`. Every booking, cancellation, no-show, reschedule and check-in at a
    site changes that site's day-level slot accounting and advances the site's
    `version`, so a booking still carrying an earlier value has priced its remaining
    capacity from a stale view and is rejected with `ERR_STALE_VERSION`. A client
    recovers by re-reading the site and retrying with the current value."

    Design: Corner/cross_cutting_complexity_layers/stale_site_version_on_second_booking_returns_conflict
    """
    world = setup_clinic(
        employer={"legal_name": "OCC Site Co", "employer_code": "OCS"},
        site={"site_name": "OCS Clinic"},
        eligibility={"subscriber_external_id": "S-5301", "member_external_id": "M-5301"},
        participant={"display_name": "OCC Tester"},
    )
    stale_version = read_site(world.site_id, world.participant_headers)["version"]

    validate_success(
        api_client.create_appointment(
            {
                "participant_id": world.participant_id,
                "site_id": world.site_id,
                "provider_id": world.clinician_id,
                "visit_type": "PRIMARY_CARE",
                "scheduled_start": "2026-06-08T09:00:00Z",
                "expected_site_version": stale_version,
            },
            world.participant_headers,
        ),
        201,
    )

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T10:00:00Z",
            "expected_site_version": stale_version,
        },
        world.participant_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    site = read_site(world.site_id)
    assert site["slots_held_count"] == 1, "the rejected booking created nothing"
    assert site["version"] == stale_version + 1


def test_second_amendment_with_stale_visit_version_rejected():
    """PRD §2.9: "**Amending a visit** — `POST /visits/{visit_id}/amend` — requires
    `expected_visit_version`, carrying the client's last observed `version` of the
    `Visit` being amended. Here the parent is the resource itself: an amendment
    supersedes previously recorded encounter content, so an amendment carrying an
    earlier value would overwrite content the client never saw, and is rejected with
    `ERR_STALE_VERSION`."
    PRD §3.5: "Each successful amendment increments the visit's `version` by one,
    which means a client that amends twice from one cached read has its second
    amendment refused with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/stale_visit_version_on_second_amend_returns_conflict
    """
    world = setup_completed_visit(
        visit_type="PRIMARY_CARE",
        scheduled_start="2026-06-08T09:00:00Z",
        visit_clock="2026-06-08T10:00:00Z",
        employer={"legal_name": "OCC Visit Co", "employer_code": "OCV"},
        site={"site_name": "OCV Clinic"},
        eligibility={"subscriber_external_id": "S-5501", "member_external_id": "M-5501"},
        participant={"display_name": "OCV Tester"},
        completion={"clinical_note": "original"},
    )
    stale_version = world.visit["version"]

    amend_encounter(
        world.visit_id, world.clinician_id, stale_version, clinical_note="first amendment"
    )

    response = api_client.amend_visit(
        world.visit_id,
        {"expected_visit_version": stale_version, "clinical_note": "second amendment"},
        world.clinician_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    visit = read_visit(world.visit_id, world.clinician_id)
    assert visit["amendment_count"] == 1
    assert visit["clinical_note"] == "first amendment"
    assert visit["encounter_status"] == "AMENDED"
