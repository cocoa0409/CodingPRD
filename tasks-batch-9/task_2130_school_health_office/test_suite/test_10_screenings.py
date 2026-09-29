"""Screening programmes: measurement classification, the rescreen loop and the
segregated closure of a referral."""

import pytest

from test_helpers import *  # noqa: F401,F403


def test_reading_an_unknown_screening_is_a_not_found(api, admin_headers):
    """PRD §2.7: "Every referenced row exists. References are validated left to right: path
    parameters first, in URL order, then body foreign keys in the order they appear in the
    endpoint's input list. Any miss is `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/screening_get_with_unknown_id_returns_not_found
    """
    create_school(name="Sutton Elementary", building_code="SUT22")

    resp = api.get_screening(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_vision_thresholds_fork_the_screening_three_ways(api, admin_headers):
    """PRD §3.8: "For `VISION`, where the value is the Snellen denominator at twenty feet, a value
    of 30 or below is `PASS`, a value strictly above 30 and strictly below 40 is `INCONCLUSIVE`,
    and a value of 40 or above is `REFER`."
    PRD §3.8: "A `REFER` moves `SCHEDULED` → `REFERRED`, storing `outcome` as `REFER` and the
    recording nurse, setting `referral_due_at` to 30 days after the logical clock, and adding
    `SCREENING_REFERRAL` to the student's alert flags."
    PRD §3.8: "An `INCONCLUSIVE` moves `SCHEDULED` → `RESCREEN_DUE`, storing `outcome` as
    `INCONCLUSIVE` and the recording nurse, and setting `rescreen_due_at` to 14 days after the
    clock."

    Design: Corner/calculations/screening_outcome_classification_vision_boundaries_30_35_40
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Merlin Elementary", "building_code": "MRL41"},
        student_overrides={"full_name": "Mae Torres", "grade_level": 3,
                           "date_of_birth": "2017-06-16T00:00:00Z"})
    nurse_id, student_id, school_id = base["nurse"]["id"], base["student"]["id"], base["school"]["id"]
    set_clock(MONDAY_0900)
    booked = [create_screening(student_id, school_id, nurse_id, screening_type="VISION",
                               scheduled_for=slot)
              for slot in ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z", "2026-08-03T12:00:00Z")]

    passed = record_screening_result(booked[0]["id"], 30, nurse_id)
    assert passed["outcome"] == "PASS"
    assert passed["status"] == "COMPLETED"
    assert passed.get("rescreen_due_at") is None
    assert passed.get("referral_due_at") is None

    inconclusive = record_screening_result(booked[1]["id"], 35, nurse_id)
    assert inconclusive["outcome"] == "INCONCLUSIVE"
    assert inconclusive["status"] == "RESCREEN_DUE"
    assert inconclusive["rescreen_due_at"].startswith("2026-08-17T09:00:00")

    referred = record_screening_result(booked[2]["id"], 40, nurse_id)
    assert referred["outcome"] == "REFER"
    assert referred["status"] == "REFERRED"
    assert referred["referral_due_at"].startswith("2026-09-02T09:00:00")

    for row in booked:
        stored = validate_success(api.get_screening(row["id"], admin_headers))
        assert stored["screened_by_nurse_id"] == nurse_id
    student = validate_success(api.get_student(student_id, admin_headers))
    assert "SCREENING_REFERRAL" in student["alert_flags"]


def test_recording_a_second_result_on_a_completed_screening_is_refused(api, admin_headers):
    """PRD §3.8: "A `PASS` moves `SCHEDULED` → `COMPLETED`, storing `outcome` as `PASS` and the
    recording nurse."
    PRD §2.7: "The screening check guards record-result and follow-up."

    Design: Corner/state_machines/screening_record_result_twice_rejected_from_completed
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Celeste Elementary", "building_code": "CEL31"},
        student_overrides={"full_name": "Cleo Marsh", "grade_level": 2,
                           "date_of_birth": "2018-04-18T00:00:00Z"})
    nurse_id = base["nurse"]["id"]
    set_clock(MONDAY_0900)
    screening = create_screening(base["student"]["id"], base["school"]["id"], nurse_id,
                                 screening_type="VISION", scheduled_for="2026-08-03T10:00:00Z")
    first = record_screening_result(screening["id"], 20, nurse_id)
    assert first["outcome"] == "PASS"
    assert first["status"] == "COMPLETED"

    resp = api.record_screening_result(
        screening["id"], {"result_value": 45, "screened_by_nurse_id": nurse_id},
        make_nurse_headers(nurse_id))
    validate_error(resp, ApiErrorId.ERR_SCREENING_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_screening(screening["id"], admin_headers))
    assert unchanged["outcome"] == "PASS"
    assert unchanged["result_value"] == pytest.approx(20, abs=0.001)
    assert unchanged["cycle_number"] == 1


def test_the_rescreen_loop_is_capped_at_three_cycles(api, admin_headers):
    """PRD §3.8: "`SCHEDULE_RESCREEN` applies to a screening at `RESCREEN_DUE` whose
    `cycle_number` is still below 3: it increments `cycle_number` by one, sets `scheduled_for` to
    the newly supplied instant, clears both `outcome` and `result_value` back to null, and returns
    the screening to `SCHEDULED`, closing the cycle `SCHEDULED` → `RESCREEN_DUE` → `SCHEDULED`."
    PRD §3.8: "A fourth round, requested when `cycle_number` already stands at 3, is refused with
    `ERR_RESCREEN_LIMIT_REACHED` (HTTP 409) at ladder position 46."

    Design: Corner/state_machines/screening_rescreen_cycle_capped_at_three_rounds
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Juniper Elementary", "building_code": "JUN38"},
        student_overrides={"full_name": "Jun Park", "grade_level": 2,
                           "date_of_birth": "2018-12-12T00:00:00Z"})
    nurse_id = base["nurse"]["id"]
    set_clock(MONDAY_0900)
    screening = create_screening(base["student"]["id"], base["school"]["id"], nurse_id,
                                 screening_type="VISION", scheduled_for="2026-08-03T10:00:00Z")
    assert screening["cycle_number"] == 1
    assert screening["status"] == "SCHEDULED"

    first = record_screening_result(screening["id"], 35, nurse_id)
    assert first["outcome"] == "INCONCLUSIVE"
    assert first["status"] == "RESCREEN_DUE"
    assert first["rescreen_due_at"].startswith("2026-08-17T09:00:00")

    second_round = screening_follow_up(screening["id"], nurse_id, "SCHEDULE_RESCREEN",
                                       scheduled_for="2026-08-10T10:00:00Z")
    assert second_round["cycle_number"] == 2
    assert second_round["status"] == "SCHEDULED"
    assert second_round.get("outcome") is None
    assert second_round.get("result_value") is None

    record_screening_result(screening["id"], 35, nurse_id)
    third_round = screening_follow_up(screening["id"], nurse_id, "SCHEDULE_RESCREEN",
                                      scheduled_for="2026-08-17T10:00:00Z")
    assert third_round["cycle_number"] == 3
    record_screening_result(screening["id"], 35, nurse_id)

    resp = api.screening_follow_up(
        screening["id"],
        {"action": "SCHEDULE_RESCREEN", "scheduled_for": "2026-08-24T10:00:00Z"},
        make_nurse_headers(nurse_id))
    validate_error(resp, ApiErrorId.ERR_RESCREEN_LIMIT_REACHED.value, 409)

    unchanged = validate_success(api.get_screening(screening["id"], admin_headers))
    assert unchanged["cycle_number"] == 3
    assert unchanged["status"] == "RESCREEN_DUE"


def test_the_nurse_who_found_the_problem_may_not_close_the_referral(api, admin_headers):
    """PRD §3.8: "`CLOSE_REFERRAL` applies to a screening at `REFERRED`: it requires a supplied
    `referral_outcome` of `TREATED`, `NO_ACTION` or `LOST_TO_FOLLOWUP`, and it requires the acting
    `X-User-ID` to differ from the stored `screened_by_nurse_id` — the nurse who found the problem
    may not be the one who declares it resolved."
    PRD §2.9: "All three violations return the same code, `ERR_SEGREGATION_OF_DUTIES` (HTTP 403),
    and that check sits at ladder position 22 — guarding dose preparation, the dose outcome step,
    screening follow-up and disclosure release."
    PRD §3.8: "On success `referral_outcome` is stored, `referral_completed_at` is stamped with the
    clock, the screening becomes `CLOSED`, and `SCREENING_REFERRAL` is dropped from the student's
    alert flags when no other screening for that student remains `REFERRED`."

    Design: Corner/rbac/recording_nurse_cannot_close_her_own_screening_referral
    """
    school = create_school(name="Grove Elementary", building_code="GRV67")
    nurse_one = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    nurse_two = create_nurse(full_name="Gia Moreno", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse_one["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    create_coverage(nurse_two["id"], school["id"], weekday="MON", start_minute=480, end_minute=780)
    student = create_student(school["id"], full_name="Gil Ashford", grade_level=3,
                             date_of_birth="2017-09-19T00:00:00Z")
    set_clock(MONDAY_0900)
    screening = create_screening(student["id"], school["id"], nurse_one["id"],
                                 screening_type="VISION", scheduled_for="2026-08-03T10:00:00Z")
    referred = record_screening_result(screening["id"], 45, nurse_one["id"])
    assert referred["outcome"] == "REFER"
    assert referred["status"] == "REFERRED"
    assert referred["screened_by_nurse_id"] == nurse_one["id"]
    assert referred["referral_due_at"].startswith("2026-09-02T09:00:00")

    resp = api.screening_follow_up(
        screening["id"], {"action": "CLOSE_REFERRAL", "referral_outcome": "TREATED"},
        make_nurse_headers(nurse_one["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    held = validate_success(api.get_screening(screening["id"], admin_headers))
    assert held["status"] == "REFERRED"
    assert held.get("referral_completed_at") is None

    closed = validate_success(api.screening_follow_up(
        screening["id"], {"action": "CLOSE_REFERRAL", "referral_outcome": "TREATED"},
        make_nurse_headers(nurse_two["id"])))
    assert closed["status"] == "CLOSED"
    assert closed["referral_outcome"] == "TREATED"
    assert closed["referral_completed_at"].startswith("2026-08-03T09:00:00")
    student_row = validate_success(api.get_student(student["id"], admin_headers))
    assert "SCREENING_REFERRAL" not in student_row["alert_flags"]
