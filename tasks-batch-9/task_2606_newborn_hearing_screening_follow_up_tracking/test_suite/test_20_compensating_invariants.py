"""Two ledgers that must return to where they started when a write is reversed."""

import pytest

from test_helpers import assertions as check
from test_helpers import factories, fixtures
from test_helpers.test_users import (
    make_facility_screener_headers,
    make_navigator_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()

BIRTH = "2026-08-02T00:00:00Z"
SLOT_START = "2026-08-10T09:00:00Z"


def _interpreter_booking(client):
    """A Spanish-speaking family booked with interpreter support, five units deep."""
    hospital = fixtures.create_facility(
        client, "BH1", "BIRTH_HOSPITAL", "R1", navigation_budget_units_total=40
    )
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    navigator = fixtures.create_provider(
        client, hospital["id"], "NAVIGATOR", "N1", "R1", languages=["EN", "ES"]
    )
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    navigator_headers = make_navigator_headers(navigator["id"])

    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        preferred_language="ES",
        interpreter_required=True,
        guardian_name="G-T",
        guardian_contact_phone="5551401",
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
                right_ear_result="REFER",
            ),
            headers=make_facility_screener_headers(screener["id"]),
        )
    )
    episode = fixtures.episodes_of(client, infant["id"])[0]
    slot = check.assert_created(
        client.create_slot(
            factories.slot_payload(
                facility_id=clinic["id"],
                provider_id=audiologist["id"],
                starts_at=SLOT_START,
                ends_at="2026-08-10T10:00:00Z",
                slot_type="RESCREEN",
                total_capacity=1,
            ),
            headers=ADMIN,
        )
    )
    appointment = fixtures.book(
        client, episode["id"], slot["id"], interpreter_needed=True, headers=navigator_headers
    )
    return {
        "hospital": hospital,
        "navigator": navigator,
        "navigator_headers": navigator_headers,
        "infant": infant,
        "episode": episode,
        "slot": slot,
        "appointment": appointment,
    }


def test_the_interpreter_task_takes_five_units_out_of_the_budget(client):
    """Two base units plus three for the interpreter, debited at the booking.

    PRD: "The cost of a task is a base of 2 units, plus a further 3 units when the
    infant's `interpreter_required` flag is set, plus a further 4 units when the
    `task_type` is `HOME_VISIT`."

    Design: Difficulty/compensating_invariant/navigation_budget_units_released_when_interpreter_appointment_cancelled
    """
    scenario = _interpreter_booking(client)
    task_id = scenario["appointment"]["linked_navigation_task_id"]
    assert task_id is not None

    task = fixtures.read_task(client, task_id)
    assert task["task_type"] == "INTERPRETER_SESSION"
    assert task["units_reserved"] == 5
    assert task["budget_shortfall_flag"] is False
    assert task["funding_facility_id"] == scenario["hospital"]["id"]
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == scenario["navigator"]["id"]

    debited = fixtures.read_facility(client, scenario["hospital"]["id"])
    check.assert_facility_ledger(debited, navigation_budget_units_remaining=35)
    assert debited["navigation_budget_units_total"] == 40
    check.assert_budget_conservation(
        debited, fixtures.tasks_of(client, scenario["infant"]["id"])
    )


def test_cancelling_the_appointment_returns_every_unit_it_held(client):
    """The cancelled task keeps no reservation, and the budget lands back on forty.

    PRD: "**Navigation budget conservation**: a facility's
    `navigation_budget_units_remaining` plus the sum of `units_reserved` across its
    navigation tasks whose `status` is `UNASSIGNED`, `OPEN`, or `COMPLETED` always
    equals its `navigation_budget_units_total`. A task that is cancelled releases its
    units; a task that is completed does not, because completed work has been
    consumed."

    Design: Difficulty/compensating_invariant/navigation_budget_units_released_when_interpreter_appointment_cancelled
    """
    scenario = _interpreter_booking(client)
    task_id = scenario["appointment"]["linked_navigation_task_id"]

    closed = fixtures.close_appointment(
        client,
        scenario["appointment"]["id"],
        "CANCELLED",
        reason="family rescheduling",
        headers=scenario["navigator_headers"],
    )
    assert closed["status"] == "CANCELLED"

    released_task = fixtures.read_task(client, task_id)
    assert released_task["status"] == "CANCELLED"
    restored = fixtures.read_facility(client, scenario["hospital"]["id"])
    check.assert_facility_ledger(restored, navigation_budget_units_remaining=40)
    check.assert_budget_conservation(
        restored, fixtures.tasks_of(client, scenario["infant"]["id"])
    )
    assert fixtures.read_provider(client, scenario["navigator"]["id"])["open_task_count"] == 0

    check.assert_slot_capacity(fixtures.read_slot(client, scenario["slot"]["id"]), 0, 1, "OPEN")
    check.assert_episode_state(
        fixtures.read_episode(client, scenario["episode"]["id"]),
        "PENDING_SCHEDULING",
        attempt_count=0,
    )
    # The cancelled task no longer relieves the score, and nothing else scores.
    check.assert_risk(fixtures.read_infant(client, scenario["infant"]["id"]), 0, "LOW")


def _late_report_assessed_at_nine(client):
    """A late filing with two variance cases, assessed and carried on the ledger."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    period = fixtures.open_period(
        client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"
    )
    fixtures.set_clock(client, "2026-08-05T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-05T00:00:00Z",
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-D",
        guardian_contact_phone="5551501",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at="2026-08-05T04:00:00Z",
                encounter_type="BIRTH_ADMISSION",
                method="OAE",
                left_ear_result="PASS",
                right_ear_result="PASS",
            ),
            headers=make_facility_screener_headers(screener["id"]),
        )
    )

    fixtures.set_clock(client, "2026-09-03T00:00:00Z")
    report = fixtures.file_report(
        client, hospital["id"], period["id"], attested_screened_count=3, attested_refer_count=0
    )
    fixtures.review_report(client, report["id"], "ACCEPT", note="variance acknowledged")
    fixtures.set_clock(client, "2026-09-04T00:00:00Z")
    fixtures.close_period(client, period["id"])
    return hospital, report


def test_the_late_filing_is_assessed_nine_points_and_the_ledger_shows_them(client):
    """Seven base points, a quarter added for the tier, rounded half up once.

    PRD: "The surcharge tier is keyed on the pre-surcharge total, that is the base
    points added to the carryover: a total of 4 or less attracts no surcharge, a total
    from 5 through 9 attracts a 25 percent surcharge, and a total of 10 or more
    attracts a 50 percent surcharge. The surcharge then multiplies the **base points
    only** — never the carryover — and that single product is rounded half-up to a
    whole number to give the report's `assessed_penalty_points`."

    Design: Difficulty/compensating_invariant/penalty_points_ledger_restored_exactly_when_waiver_reverses_assessment
    """
    hospital, report = _late_report_assessed_at_nine(client)

    assessed = fixtures.read_report(client, report["id"])
    assert assessed["status"] == "ACCEPTED"
    assert assessed["submitted_late"] is True
    assert assessed["variance_case_count"] == 2
    assert assessed["assessed_penalty_points"] == 9

    ledger = fixtures.read_facility(client, hospital["id"])
    check.assert_facility_ledger(
        ledger,
        penalty_points_balance=9,
        reporting_compliance_status="WATCH",
        manual_adjustment_points_total=0,
    )
    assert (
        ledger["penalty_points_balance"]
        == assessed["assessed_penalty_points"] + ledger["manual_adjustment_points_total"]
    )


def test_the_waiver_subtracts_the_assessment_exactly_and_keeps_the_record(client):
    """The points leave the balance while the assessment itself stays on the report.

    PRD: "A waiver advances the report `ACCEPTED → PENALTY_WAIVED`, drops the
    facility's `penalty_points_balance` by the waived `assessed_penalty_points`,
    re-derives `reporting_compliance_status` from the new balance, and increments the
    facility's `version` by 1."

    Design: Difficulty/compensating_invariant/penalty_points_ledger_restored_exactly_when_waiver_reverses_assessment
    """
    hospital, report = _late_report_assessed_at_nine(client)
    before = fixtures.read_facility(client, hospital["id"])
    assert before["penalty_points_balance"] == 9

    reason = "documented data-system outage during the reporting window"
    waived = fixtures.waive_penalty(client, report["id"], reason)
    assert waived["status"] == "PENALTY_WAIVED"
    assert waived["waiver_reason"] == reason
    assert waived["assessed_penalty_points"] == 9

    after = fixtures.read_facility(client, hospital["id"])
    check.assert_facility_ledger(
        after,
        penalty_points_balance=0,
        reporting_compliance_status="COMPLIANT",
        manual_adjustment_points_total=0,
    )
    check.assert_versioned(after, before["version"] + 1)
