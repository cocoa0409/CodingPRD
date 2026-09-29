"""Screening encounters: aggregation, temporal range, linkage and single-shot guards."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_audiologist_headers,
    make_facility_screener_headers,
    make_navigator_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()


def _hospital_with_screener(client):
    """BH1 with one screener, clock six hours after the reference birth instant."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    return hospital, screener, make_facility_screener_headers(screener["id"])


def _newborn(client, hospital, headers, birth_datetime=CLOCK_START, phone="5550000"):
    return check.assert_created(
        client.create_infant(
            factories.infant_payload(
                birth_facility_id=hospital["id"],
                birth_datetime=birth_datetime,
                birth_setting="INPATIENT",
                gestational_age_weeks=39,
                guardian_name="G-EN",
                guardian_contact_phone=phone,
            ),
            headers=headers,
        )
    )


def _screen(client, hospital, screener, headers, infant_id, performed_at, **kwargs):
    return client.create_encounter(
        factories.encounter_payload(
            infant_id=infant_id,
            facility_id=hospital["id"],
            performed_by_provider_id=screener["id"],
            performed_at=performed_at,
            **kwargs
        ),
        headers=headers,
    )


def test_discharge_mints_a_chase_episode_only_for_the_unscreened_baby(client):
    """The same discharge body cascades for one infant and not for the other.

    PRD: "If the infant's `screening_status` was still `NOT_SCREENED` at the moment
    of discharge, `discharged_unscreened` is set to true, and — provided the infant
    has no episode in `PENDING_SCHEDULING`, `SCHEDULED`, or `ESCALATED_DIAGNOSTIC` —
    an `INITIAL_SCREEN` episode is created in `PENDING_SCHEDULING` so the baby is
    chased in the community rather than lost."

    Design: Corner/state_machines/discharge_opens_an_initial_screen_episode_only_when_unscreened
    """
    hospital, screener, screener_headers = _hospital_with_screener(client)
    unscreened = _newborn(client, hospital, screener_headers, CLOCK_START, "5553901")
    passed = _newborn(client, hospital, screener_headers, clock.at(hours=1), "5553902")
    check.assert_created(
        _screen(
            client,
            hospital,
            screener,
            screener_headers,
            passed["id"],
            clock.at(hours=4),
            encounter_type="BIRTH_ADMISSION",
            left_ear_result="PASS",
            right_ear_result="PASS",
        )
    )

    discharge_at = clock.at(hours=5)
    stamped_unscreened = check.assert_ok(
        client.discharge_infant(
            unscreened["id"], {"discharge_datetime": discharge_at}, headers=screener_headers
        )
    )
    stamped_passed = check.assert_ok(
        client.discharge_infant(
            passed["id"], {"discharge_datetime": discharge_at}, headers=screener_headers
        )
    )

    check.assert_instant_equals(stamped_unscreened["discharge_datetime"], discharge_at)
    assert stamped_unscreened["discharged_unscreened"] is True
    assert stamped_unscreened["screening_status"] == "NOT_SCREENED"
    assert stamped_unscreened["version"] == 2

    chase = check.assert_total_count(
        client.list_episodes(headers=ADMIN, infant_id=unscreened["id"]), 1
    )[0]
    assert chase["episode_type"] == "INITIAL_SCREEN"
    check.assert_episode_state(chase, "PENDING_SCHEDULING", benchmark_days=30)
    check.assert_instant_equals(chase["due_date"], "2026-08-31T00:00:00Z")

    check.assert_instant_equals(stamped_passed["discharge_datetime"], discharge_at)
    assert stamped_passed["discharged_unscreened"] is False
    assert stamped_passed["screening_status"] == "PASSED"
    check.assert_total_count(client.list_episodes(headers=ADMIN, infant_id=passed["id"]), 0)


def test_one_untested_ear_refers_while_two_untested_is_incomplete(client):
    """The ear-pair aggregation separates a protocol failure from a genuine refer.

    PRD: "When both `left_ear_result` and `right_ear_result` are `PASS`,
    `overall_result` is `PASS`. When both ears are `NOT_TESTED`, `overall_result` is
    `INCOMPLETE`. In every other combination `overall_result` is `REFER` — which
    means a single untested ear cannot certify a pass, because `NOT_TESTED` in
    exactly one ear is treated as a refer for that ear."

    Design: Corner/calculations/one_untested_ear_aggregates_to_refer_while_two_untested_is_incomplete
    """
    hospital, screener, screener_headers = _hospital_with_screener(client)
    one_ear = _newborn(client, hospital, screener_headers, CLOCK_START, "5554301")
    no_ears = _newborn(client, hospital, screener_headers, clock.at(hours=1), "5554302")

    partial = check.assert_created(
        _screen(
            client,
            hospital,
            screener,
            screener_headers,
            one_ear["id"],
            clock.at(hours=4),
            encounter_type="BIRTH_ADMISSION",
            method="OAE",
            left_ear_result="NOT_TESTED",
            right_ear_result="PASS",
        )
    )
    neither = check.assert_created(
        _screen(
            client,
            hospital,
            screener,
            screener_headers,
            no_ears["id"],
            clock.at(hours=4),
            encounter_type="BIRTH_ADMISSION",
            method="OAE",
            left_ear_result="NOT_TESTED",
            right_ear_result="NOT_TESTED",
        )
    )
    assert partial["overall_result"] == "REFER"
    assert neither["overall_result"] == "INCOMPLETE"

    for infant in (one_ear, no_ears):
        stored = fixtures.read_infant(client, infant["id"])
        assert stored["screening_status"] == "REFERRED"
        episode = check.assert_total_count(
            client.list_episodes(headers=ADMIN, infant_id=infant["id"]), 1
        )[0]
        assert episode["episode_type"] == "RESCREEN"
        assert episode["benchmark_days"] == 30


def test_event_instant_must_lie_between_birth_and_the_clock(client):
    """One hour early and one hour late are both rejected; the clock instant is not.

    PRD: "Event instants must fall inside the closed range that begins at the
    infant's `birth_datetime` and ends at the logical clock — this covers a screening
    encounter's `performed_at`, a diagnostic evaluation's `evaluation_datetime`, a risk
    entry's `identified_at`, the `discharge_datetime` recorded at discharge, and the
    `ifsp_date` recorded at enrollment — and a violation of any of them is rejected
    with `ERR_TIMESTAMP_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/validations/encounter_performed_at_before_birth_or_after_the_clock_is_rejected
    """
    hospital, screener, screener_headers = _hospital_with_screener(client)
    infant = _newborn(client, hospital, screener_headers, CLOCK_START, "5554701")

    too_early = _screen(
        client,
        hospital,
        screener,
        screener_headers,
        infant["id"],
        clock.at(hours=-1),
        encounter_type="BIRTH_ADMISSION",
        method="OAE",
        left_ear_result="PASS",
        right_ear_result="PASS",
    )
    check.assert_error_envelope(too_early, errors.ERR_TIMESTAMP_OUT_OF_RANGE)

    too_late = _screen(
        client,
        hospital,
        screener,
        screener_headers,
        infant["id"],
        clock.at(hours=7),
        encounter_type="BIRTH_ADMISSION",
        method="OAE",
        left_ear_result="PASS",
        right_ear_result="PASS",
    )
    check.assert_error_envelope(too_late, errors.ERR_TIMESTAMP_OUT_OF_RANGE)

    on_the_clock = check.assert_created(
        _screen(
            client,
            hospital,
            screener,
            screener_headers,
            infant["id"],
            clock.at(hours=6),
            encounter_type="BIRTH_ADMISSION",
            method="OAE",
            left_ear_result="PASS",
            right_ear_result="PASS",
        )
    )
    assert on_the_clock["age_days_at_encounter"] == 0
    assert on_the_clock["overall_result"] == "PASS"
    assert fixtures.read_infant(client, infant["id"])["screening_status"] == "PASSED"
    check.assert_total_count(client.list_encounters(headers=ADMIN, infant_id=infant["id"]), 1)


def test_a_rescreen_must_name_its_own_appointment_to_close_the_episode(client, registry):
    """The wrong appointment is a linkage failure; the right triple resolves the loop.

    PRD: "the encounter's `episode_id`, when supplied, must name an episode of the
    same infant, and its `appointment_id`, when supplied, must name an appointment on
    that same episode; either disagreement is `ERR_LINKAGE_MISMATCH`."

    Design: Corner/endpoints/rescreen_encounter_links_episode_and_appointment_or_returns_linkage_mismatch
    """
    fixtures.set_clock(client, clock.at(hours=6))
    first = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-L1",
        guardian_contact_phone="5555301",
    )
    second = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=clock.at(hours=1),
        birth_setting="INPATIENT",
        guardian_name="G-L2",
        guardian_contact_phone="5555302",
    )
    for infant in (first, second):
        fixtures.record_encounter(
            client,
            registry,
            infant["id"],
            clock.at(hours=4),
            encounter_type="BIRTH_ADMISSION",
            left_ear_result="REFER",
            right_ear_result="PASS",
        )
    episode_one = fixtures.episodes_of(client, first["id"])[0]
    episode_two = fixtures.episodes_of(client, second["id"])[0]
    slot = fixtures.publish_slot(
        client,
        registry,
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        total_capacity=2,
    )
    appointment_one = fixtures.book(
        client, episode_one["id"], slot["id"], headers=registry.n1
    )
    appointment_two = fixtures.book(
        client, episode_two["id"], slot["id"], headers=registry.n1
    )
    fixtures.set_clock(client, "2026-08-05T10:00:00Z")

    def rescreen(appointment_id):
        return client.create_encounter(
            factories.encounter_payload(
                infant_id=first["id"],
                facility_id=registry.ac_id,
                performed_by_provider_id=registry.a1_id,
                performed_at="2026-08-05T09:30:00Z",
                encounter_type="OUTPATIENT_RESCREEN",
                method="AABR",
                left_ear_result="PASS",
                right_ear_result="PASS",
                episode_id=episode_one["id"],
                appointment_id=appointment_id,
            ),
            headers=registry.a1,
        )

    check.assert_error_envelope(rescreen(appointment_two["id"]), errors.ERR_LINKAGE_MISMATCH)
    assert fixtures.read_appointment(client, appointment_one["id"])["status"] == "BOOKED"
    assert fixtures.read_appointment(client, appointment_two["id"])["status"] == "BOOKED"

    encounter = check.assert_created(rescreen(appointment_one["id"]))
    assert encounter["overall_result"] == "PASS"
    assert encounter["age_days_at_encounter"] == 4
    assert encounter["before_discharge"] is False

    assert fixtures.read_appointment(client, appointment_one["id"])["status"] == "ATTENDED"
    assert fixtures.read_appointment(client, appointment_two["id"])["status"] == "BOOKED"

    closed = fixtures.read_episode(client, episode_one["id"])
    check.assert_episode_state(closed, "RESOLVED_PASS", closure_reason="RESCREEN_PASSED")
    assert closed["timeliness_status"] == "ON_TIME"
    check.assert_instant_equals(closed["closed_at"], "2026-08-05T10:00:00Z")
    assert fixtures.read_infant(client, first["id"])["screening_status"] == "PASSED"

    check.assert_slot_capacity(fixtures.read_slot(client, slot["id"]), 2, 0, "FULL")


def test_the_three_single_shot_guards_on_one_infant_all_hold(client, registry):
    """A second birth screen, a second open episode and a second discharge are refused.

    PRD: "At most one `BIRTH_ADMISSION` encounter may ever exist for a given infant —
    a second is rejected with `ERR_DUPLICATE_BIRTH_SCREEN`."

    Design: Corner/errors/duplicate_birth_screen_second_open_episode_and_second_discharge_are_rejected
    """
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-DU",
        guardian_contact_phone="5556101",
    )
    first_screen = fixtures.record_encounter(
        client,
        registry,
        infant["id"],
        clock.at(hours=4),
        encounter_type="BIRTH_ADMISSION",
        left_ear_result="REFER",
        right_ear_result="PASS",
    )
    fixtures.set_clock(client, clock.at(days=1))
    discharged = check.assert_ok(
        client.discharge_infant(
            infant["id"], {"discharge_datetime": clock.at(days=1)}, headers=registry.s1
        )
    )
    version_after_discharge = discharged["version"]

    duplicate_screen = client.create_encounter(
        factories.encounter_payload(
            infant_id=infant["id"],
            facility_id=registry.bh_id,
            performed_by_provider_id=registry.s1_id,
            performed_at=clock.at(hours=5),
            encounter_type="BIRTH_ADMISSION",
            method="AABR",
            left_ear_result="PASS",
            right_ear_result="PASS",
        ),
        headers=registry.s1,
    )
    check.assert_error_envelope(duplicate_screen, errors.ERR_DUPLICATE_BIRTH_SCREEN)
    kept = check.assert_total_count(
        client.list_encounters(headers=ADMIN, infant_id=infant["id"]), 1
    )
    assert kept[0]["id"] == first_screen["id"]

    second_episode = client.create_episode(
        factories.episode_payload(
            infant_id=infant["id"],
            episode_type="DIAGNOSTIC",
            expected_infant_version=version_after_discharge,
        ),
        headers=registry.n1,
    )
    check.assert_error_envelope(second_episode, errors.ERR_ACTIVE_EPISODE_EXISTS)
    open_episodes = check.assert_total_count(
        client.list_episodes(headers=ADMIN, infant_id=infant["id"]), 1
    )
    assert open_episodes[0]["status"] == "PENDING_SCHEDULING"

    second_discharge = client.discharge_infant(
        infant["id"], {"discharge_datetime": clock.at(days=1)}, headers=registry.s1
    )
    check.assert_error_envelope(second_discharge, errors.ERR_INFANT_ALREADY_DISCHARGED)
    stored = fixtures.read_infant(client, infant["id"])
    check.assert_instant_equals(stored["discharge_datetime"], clock.at(days=1))
    assert stored["version"] == version_after_discharge


def test_a_future_birth_and_a_surveillance_screen_without_a_registry_entry_are_refused(
    client, registry
):
    """Two independent guards, each shown failing and then passing.

    PRD: "Such an encounter may only be recorded for an infant who has at least one
    registry entry in `ACTIVE`, `SURVEILLANCE_DUE`, or `SURVEILLANCE_OVERDUE`;
    otherwise it is refused with `ERR_NO_OPEN_RISK_FACTOR`."

    Design: Corner/errors/future_birth_and_surveillance_without_a_registry_entry_are_rejected
    """
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-SV",
        guardian_contact_phone="5556301",
    )

    future_baby = client.create_infant(
        factories.infant_payload(
            birth_facility_id=registry.bh_id,
            birth_datetime=clock.at(days=1),
            birth_setting="INPATIENT",
            gestational_age_weeks=39,
            guardian_name="G-FU",
            guardian_contact_phone="5556302",
        ),
        headers=registry.s1,
    )
    check.assert_error_envelope(future_baby, errors.ERR_BIRTH_DATETIME_IN_FUTURE)
    check.assert_total_count(
        client.list_infants(headers=ADMIN, birth_facility_id=registry.bh_id), 1
    )

    def surveillance():
        return client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=registry.ac_id,
                performed_by_provider_id=registry.a1_id,
                performed_at=clock.at(hours=5),
                encounter_type="SURVEILLANCE",
                method="OAE",
                left_ear_result="PASS",
                right_ear_result="PASS",
            ),
            headers=registry.a1,
        )

    check.assert_error_envelope(surveillance(), errors.ERR_NO_OPEN_RISK_FACTOR)
    check.assert_total_count(client.list_encounters(headers=ADMIN, infant_id=infant["id"]), 0)

    entry = fixtures.register_risk_factor(
        client, infant["id"], "CMV", clock.at(hours=4), headers=registry.s1
    )
    assert entry["status"] == "ACTIVE"
    assert entry["source"] == "BIRTH_FACILITY"
    check.assert_instant_equals(entry["surveillance_due_date"], "2027-01-28T00:00:00Z")
    scored = fixtures.read_infant(client, infant["id"])
    assert scored["risk_factor_count"] == 1
    check.assert_risk(scored, 4, "LOW")

    accepted = check.assert_created(surveillance())
    assert accepted["encounter_type"] == "SURVEILLANCE"
    assert accepted["overall_result"] == "PASS"
    cleared = fixtures.risk_entries_of(client, infant["id"])[0]
    assert cleared["status"] == "CLEARED"
    assert cleared["surveillance_result"] == "PASS"
