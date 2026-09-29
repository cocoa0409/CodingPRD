"""The delayed-onset registry and the loss-to-follow-up risk score."""

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
    make_program_auditor_headers,
)

ADMIN = make_program_admin_headers()
AUDITOR = make_program_auditor_headers()


def _birth_hospital(client):
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    return hospital, screener, make_facility_screener_headers(screener["id"])


def _inpatient(client, hospital, phone):
    return fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=CLOCK_START,
        birth_setting="INPATIENT",
        guardian_name="G-RF",
        guardian_contact_phone=phone,
    )


def test_the_surveillance_clock_is_180_days_for_the_highest_risk_codes(client):
    """Two entries minted together diverge on their due date by code class alone.

    PRD: "For the three highest-risk codes — `CMV`, `BACTERIAL_MENINGITIS`, and
    `ECMO` — the entry's `surveillance_due_date` is the infant's `birth_datetime`
    advanced by exactly 180 days; every other code is given exactly 270 days."

    Design: Corner/calculations/surveillance_due_date_180_for_high_risk_codes_and_270_otherwise
    """
    hospital, _, screener_headers = _birth_hospital(client)
    infant = _inpatient(client, hospital, "5554001")

    high_risk = fixtures.register_risk_factor(
        client, infant["id"], "CMV", clock.at(hours=2), headers=screener_headers
    )
    standard = fixtures.register_risk_factor(
        client, infant["id"], "FAMILY_HISTORY", clock.at(hours=2), headers=screener_headers
    )

    check.assert_instant_equals(high_risk["surveillance_due_date"], "2027-01-28T00:00:00Z")
    assert high_risk["status"] == "ACTIVE"
    assert high_risk["source"] == "BIRTH_FACILITY"
    assert high_risk["surveillance_result"] is None

    check.assert_instant_equals(standard["surveillance_due_date"], "2027-04-28T00:00:00Z")
    assert standard["status"] == "ACTIVE"

    scored = fixtures.read_infant(client, infant["id"])
    assert scored["risk_factor_count"] == 2
    check.assert_risk(scored, 8, "LOW")


def test_cleared_entries_leave_the_score_without_leaving_the_registry(client):
    """A surveillance pass empties the risk term while the rows remain readable.

    PRD: "The **risk-factor term** is 4 points for each open registry entry, capped at
    16 points — the smaller of 16 and 4 times the count of that infant's entries in
    `ACTIVE`, `SURVEILLANCE_DUE`, or `SURVEILLANCE_OVERDUE`."

    Design: Corner/calculations/risk_score_counts_only_open_registry_entries_after_surveillance_clears_them
    """
    hospital, screener, screener_headers = _birth_hospital(client)
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    infant = _inpatient(client, hospital, "5554101")
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at=clock.at(hours=3),
                encounter_type="BIRTH_ADMISSION",
                method="OAE",
                left_ear_result="PASS",
                right_ear_result="PASS",
            ),
            headers=screener_headers,
        )
    )
    for code in ("CMV", "SYNDROME"):
        fixtures.register_risk_factor(
            client, infant["id"], code, clock.at(hours=2), headers=screener_headers
        )

    loaded = fixtures.read_infant(client, infant["id"])
    check.assert_risk(loaded, 8, "LOW")
    assert loaded["risk_factor_count"] == 2

    surveillance = check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=clinic["id"],
                performed_by_provider_id=audiologist["id"],
                performed_at=clock.at(hours=5),
                encounter_type="SURVEILLANCE",
                method="OAE",
                left_ear_result="PASS",
                right_ear_result="PASS",
            ),
            headers=make_audiologist_headers(audiologist["id"]),
        )
    )
    assert surveillance["overall_result"] == "PASS"
    assert surveillance["encounter_type"] == "SURVEILLANCE"

    for entry in fixtures.risk_entries_of(client, infant["id"]):
        assert entry["status"] == "CLEARED"
        assert entry["surveillance_result"] == "PASS"
        # PRD: surveillance_recorded_at is the logical clock, not the encounter instant.
        check.assert_instant_equals(entry["surveillance_recorded_at"], clock.at(hours=6))

    cleared = fixtures.read_infant(client, infant["id"])
    check.assert_risk(cleared, 0, "LOW")
    assert cleared["risk_factor_count"] == 0
    assert cleared["screening_status"] == "PASSED"
    check.assert_total_count(
        client.list_risk_factor_entries(infant["id"], headers=ADMIN, status="CLEARED"), 2
    )


def test_the_risk_factor_term_stops_at_sixteen_points(client):
    """A fifth open entry cannot push the term past its cap.

    PRD: "The **risk-factor term** is 4 points for each open registry entry, capped at
    16 points — the smaller of 16 and 4 times the count of that infant's entries in
    `ACTIVE`, `SURVEILLANCE_DUE`, or `SURVEILLANCE_OVERDUE`."

    Design: Corner/calculations/risk_factor_points_cap_at_sixteen_with_five_open_entries
    """
    hospital, _, screener_headers = _birth_hospital(client)
    infant = _inpatient(client, hospital, "5554201")

    for code in (
        "CMV",
        "FAMILY_HISTORY",
        "CRANIOFACIAL_ANOMALY",
        "SYNDROME",
        "ECMO",
    ):
        fixtures.register_risk_factor(
            client, infant["id"], code, clock.at(hours=1), headers=screener_headers
        )

    capped = fixtures.read_infant(client, infant["id"])
    assert capped["risk_factor_count"] == 5
    check.assert_risk(capped, 16, "ELEVATED")
    check.assert_total_count(
        client.list_risk_factor_entries(infant["id"], headers=ADMIN, status="ACTIVE"), 5
    )


def test_the_negative_relief_term_is_clamped_once_on_the_total(client):
    """The same relief zeroes one infant's score and merely reduces the other's.

    PRD: "The seven terms are added together, and the resulting raw total is then
    clamped once — never term by term — to lie between 0 and 100 inclusive: any
    negative total becomes 0 and any total above 100 becomes 100."

    Design: Corner/calculations/risk_score_clamp_applies_once_to_the_summed_raw_value
    """
    hospital, _, hospital_screener = _birth_hospital(client)
    practice = fixtures.create_facility(client, "MW1", "MIDWIFE_PRACTICE", "R1")
    practice_screener = fixtures.create_provider(client, practice["id"], "SCREENER", "S2", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    navigator_headers = make_navigator_headers(navigator["id"])

    inpatient = _inpatient(client, hospital, "5554401")
    home_birth = fixtures.create_infant(
        client,
        practice["id"],
        birth_datetime=CLOCK_START,
        birth_setting="HOME_BIRTH",
        guardian_name="G-W2",
        guardian_contact_phone="5554402",
    )

    inpatient_task = fixtures.create_task(
        client,
        inpatient["id"],
        "OUTREACH_CALL",
        assigned_provider_id=navigator["id"],
        headers=navigator_headers,
    )
    home_birth_task = fixtures.create_task(
        client,
        home_birth["id"],
        "OUTREACH_CALL",
        assigned_provider_id=navigator["id"],
        headers=navigator_headers,
    )

    check.assert_risk(fixtures.read_infant(client, inpatient["id"]), 0, "LOW")
    check.assert_risk(fixtures.read_infant(client, home_birth["id"]), 7, "LOW")

    assert inpatient_task["funding_facility_id"] == hospital["id"]
    assert inpatient_task["units_reserved"] == 2
    assert home_birth_task["funding_facility_id"] == practice["id"]
    assert home_birth_task["units_reserved"] == 2
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=38
    )
    check.assert_facility_ledger(
        fixtures.read_facility(client, practice["id"]), navigation_budget_units_remaining=38
    )
    assert fixtures.read_provider(client, navigator["id"])["open_task_count"] == 2


def test_the_critical_band_opens_at_exactly_forty_five_points(client):
    """One more registry entry is the four points that rewrite the band.

    PRD: "The `priority_band` is read off the final score: `CRITICAL` when the score is
    45 or more, `HIGH` when it is at least 30 but below 45, `ELEVATED` when it is at
    least 15 but below 30, and `LOW` otherwise."

    Design: Corner/consistency_model/risk_band_crosses_into_critical_at_exactly_forty_five_points
    """
    practice = fixtures.create_facility(client, "MW1", "MIDWIFE_PRACTICE", "R1")
    screener = fixtures.create_provider(client, practice["id"], "SCREENER", "S1", "R1")
    screener_headers = make_facility_screener_headers(screener["id"])
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1", languages=["EN"])
    fixtures.set_clock(client, clock.at(hours=6))
    infant = fixtures.create_infant(
        client,
        practice["id"],
        birth_datetime=CLOCK_START,
        birth_setting="HOME_BIRTH",
        gestational_age_weeks=39,
        preferred_language="ZH",
        interpreter_required=True,
        guardian_name="G-CB",
        guardian_contact_phone="5556701",
    )
    fixtures.register_risk_factor(
        client, infant["id"], "FAMILY_HISTORY", clock.at(hours=4), headers=screener_headers
    )
    fixtures.set_clock(client, "2026-08-26T00:00:00Z")

    before = check.assert_ok(client.get_timeliness(infant["id"], headers=AUDITOR))
    check.assert_timeliness_panel(
        before,
        effective_age_days=25,
        benchmark_age_basis="CHRONOLOGICAL",
    )

    second = fixtures.register_risk_factor(
        client,
        infant["id"],
        "CRANIOFACIAL_ANOMALY",
        "2026-08-26T00:00:00Z",
        headers=screener_headers,
    )
    assert second["status"] == "ACTIVE"
    assert fixtures.read_infant(client, infant["id"])["risk_factor_count"] == 2

    after = check.assert_ok(client.get_timeliness(infant["id"], headers=AUDITOR))
    check.assert_timeliness_panel(after, ltf_risk_score=45, priority_band="CRITICAL")
    check.assert_risk(fixtures.read_infant(client, infant["id"]), 45, "CRITICAL")
