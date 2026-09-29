"""The two guarded write paths: a stale infant version and a stale facility version."""

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


def test_a_version_moved_on_by_a_patch_refuses_the_episode_create(client):
    """The guard refuses a create built on a version the server has moved past.

    PRD: "Opening a follow-up episode requires a non-optional
    `expected_infant_version` field in the request body, carrying the client's last
    observed `version` of the target `Infant`. If that value does not equal the
    infant's current `version`, the request is rejected with
    `ERR_STALE_INFANT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_infant_version_on_episode_create_returns_412
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    screener_headers = make_facility_screener_headers(screener["id"])
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    navigator_headers = make_navigator_headers(navigator["id"])
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-OC",
        guardian_contact_phone="5556601",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at=clock.at(hours=4),
                encounter_type="BIRTH_ADMISSION",
                method="AABR",
                left_ear_result="REFER",
                right_ear_result="REFER",
            ),
            headers=screener_headers,
        )
    )
    rescreen = fixtures.episodes_of(client, infant["id"])[0]

    stale_version = check.assert_ok(
        client.get_infant(infant["id"], headers=navigator_headers)
    )["version"]
    assert stale_version == 2

    patched = check.assert_ok(
        client.patch_contact_preferences(
            infant["id"], {"guardian_contact_phone": "5556699"}, headers=ADMIN
        )
    )
    check.assert_versioned(patched, 3)

    payload = factories.episode_payload(
        infant_id=infant["id"],
        episode_type="DIAGNOSTIC",
        expected_infant_version=stale_version,
        supersedes_episode_id=rescreen["id"],
    )
    refused = client.create_episode(payload, headers=navigator_headers)
    check.assert_error_envelope(refused, errors.ERR_STALE_INFANT_VERSION)
    assert refused.status_code == 412
    check.assert_episode_state(
        fixtures.read_episode(client, rescreen["id"]), "PENDING_SCHEDULING"
    )
    check.assert_total_count(
        client.list_episodes(headers=ADMIN, infant_id=infant["id"]), 1
    )

    fresh_version = fixtures.infant_version(client, infant["id"])
    assert fresh_version == 3
    payload["expected_infant_version"] = fresh_version
    diagnostic = check.assert_created(client.create_episode(payload, headers=navigator_headers))
    assert diagnostic["episode_type"] == "DIAGNOSTIC"
    check.assert_episode_state(diagnostic, "PENDING_SCHEDULING", benchmark_days=90)
    check.assert_instant_equals(diagnostic["due_date"], "2026-10-30T00:00:00Z")

    check.assert_episode_state(
        fixtures.read_episode(client, rescreen["id"]),
        "SUPERSEDED",
        closure_reason="SUPERSEDED",
    )
    settled = fixtures.read_infant(client, infant["id"])
    check.assert_versioned(settled, 4)
    assert settled["screening_status"] == "DIAGNOSTIC_IN_PROGRESS"


def test_a_version_moved_on_by_an_adjustment_refuses_the_filing(client):
    """The second guard watches the facility row, not the infant row.

    PRD: "Filing a facility report requires a non-optional
    `expected_facility_version` field in the request body, carrying the client's last
    observed `version` of the target `Facility`. If that value does not equal the
    facility's current `version`, the request is rejected with
    `ERR_STALE_FACILITY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_facility_version_on_report_submit_returns_412
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    stale_version = hospital["version"]
    assert stale_version == 1
    period = fixtures.open_period(
        client, CLOCK_START, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    fixtures.set_clock(client, "2026-08-15T00:00:00Z")
    fixtures.adjust_penalty(client, hospital["id"], 2, reason="late roster update")
    adjusted = fixtures.read_facility(client, hospital["id"])
    check.assert_versioned(adjusted, 2)
    check.assert_facility_ledger(
        adjusted, penalty_points_balance=2, reporting_compliance_status="COMPLIANT"
    )

    facility_admin = make_facility_admin_headers(hospital["id"])
    payload = factories.report_payload(
        facility_id=hospital["id"],
        reporting_period_id=period["id"],
        attested_screened_count=0,
        attested_refer_count=0,
        expected_facility_version=stale_version,
    )
    refused = client.create_report(payload, headers=facility_admin)
    check.assert_error_envelope(refused, errors.ERR_STALE_FACILITY_VERSION)
    assert refused.status_code == 412
    check.assert_total_count(
        client.list_reports(headers=ADMIN, facility_id=hospital["id"]), 0
    )

    fresh_version = fixtures.facility_version(client, hospital["id"])
    assert fresh_version == 2
    payload["expected_facility_version"] = fresh_version
    filed = check.assert_created(client.create_report(payload, headers=facility_admin))
    assert filed["status"] == "SUBMITTED"
    assert filed["variance_case_count"] == 0
    assert filed["submitted_late"] is False
