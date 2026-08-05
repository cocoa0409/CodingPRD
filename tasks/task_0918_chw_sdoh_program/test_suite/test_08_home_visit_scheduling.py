"""Scheduling home visits: the half-open slot convention, the two-person safety
rule and the enrolment precondition that sits above it."""

from test_helpers import (
    ApiErrorId,
    assert_home_visit,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_home_visit_payload
from test_helpers.test_users import SUPERVISOR


def test_a_visit_starting_when_another_ends_is_accepted(api):
    """PRD §2.8: "**Home-visit slots are half-open.** A visit occupies its
    `scheduled_start` inclusively and its `scheduled_end` exclusively. Two slots
    for the same worker collide when the new slot's start falls strictly before
    the existing slot's end *and* the existing slot's start falls strictly
    before the new slot's end. Touching slots therefore do **not** collide: a
    visit beginning at exactly the instant another ends is accepted. There is no
    buffer between visits of any kind."
    PRD §3.5: "A newly created visit begins with `scheduling_status` of
    `SCHEDULED`, `documentation_status` of `DRAFT`, `amendment_count` 0, and
    `completed_at`, `attested_at` and `visit_note` all null."

    Design: Difficulty/boundary_precision_check/half_open_visit_slot_touching_boundary_is_accepted
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-015", mrn="MRN-140", full_name="Edge Case",
    )
    fx.schedule_visit(
        chw_headers, patient["id"], worker["id"],
        "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
    )

    data = validate_success(
        api.create_home_visit(
            create_home_visit_payload(
                patient["id"], worker["id"],
                "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z",
            ),
            chw_headers,
        ),
        201,
    )
    assert_home_visit(data)
    assert data["scheduling_status"] == "SCHEDULED", (
        "a slot beginning exactly when the previous one ends is accepted"
    )
    assert data["documentation_status"] == "DRAFT"
    assert data["amendment_count"] == 0
    assert data["completed_at"] is None
    assert data["attested_at"] is None
    assert data["visit_note"] is None
    assert_same_instant(
        data["scheduled_start"], "2026-06-02T10:00:00Z", "visit.scheduled_start"
    )


def test_a_visit_starting_one_minute_early_collides(api):
    """PRD §3.5: "A collision exists when the new slot's `scheduled_start` falls
    strictly before the existing slot's `scheduled_end` and the existing slot's
    `scheduled_start` falls strictly before the new slot's `scheduled_end`, and
    it is rejected with `ERR_VISIT_SLOT_CONFLICT` (HTTP 409). Because the
    interval is half-open, a new visit starting at exactly the instant an
    existing one ends is accepted."

    Design: Difficulty/boundary_precision_check/half_open_visit_slot_touching_boundary_is_accepted
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-015B", mrn="MRN-140B", full_name="Edge Case",
    )
    fx.schedule_visit(
        chw_headers, patient["id"], worker["id"],
        "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
    )
    fx.schedule_visit(
        chw_headers, patient["id"], worker["id"],
        "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z",
    )

    response = api.create_home_visit(
        create_home_visit_payload(
            patient["id"], worker["id"],
            "2026-06-02T09:59:00Z", "2026-06-02T10:30:00Z",
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_VISIT_SLOT_CONFLICT.value, 409)

    _rows, meta = validate_paginated(
        api.list_home_visits(chw_headers, params={"assigned_chw_id": worker["id"]})
    )
    assert meta["total_count"] == 2, (
        f"only the two accepted visits exist, got {meta['total_count']}"
    )


def test_a_worker_in_the_second_slot_still_consumes_that_workers_time(api):
    """PRD §3.5: "At rung 13, the slot-collision rule: for each worker named on
    the new visit — in the `assigned_chw_id` role or the `second_chw_id` role,
    since both consume that worker's time — the server looks for an existing
    visit naming that same worker in either role whose `scheduling_status` is
    `SCHEDULED`, `EN_ROUTE` or `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/worker_visit_slots_half_open_including_second_worker_role
    """
    first_worker, patient, first_headers = fx.program_with_patient(
        employee_code="W-021", mrn="MRN-200", full_name="Slot Case",
    )
    second, second_headers = fx.second_worker(employee_code="W-022")
    fx.schedule_visit(
        first_headers, patient["id"], first_worker["id"],
        "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
    )

    response = api.create_home_visit(
        create_home_visit_payload(
            patient["id"], second["id"],
            "2026-06-02T09:30:00Z", "2026-06-02T10:30:00Z",
            second_chw_id=first_worker["id"],
        ),
        second_headers,
    )
    validate_error(response, ApiErrorId.ERR_VISIT_SLOT_CONFLICT.value, 409)


def test_the_second_worker_slot_obeys_the_same_half_open_boundary(api):
    """PRD §2.8: "**Home-visit slots are half-open.** A visit occupies its
    `scheduled_start` inclusively and its `scheduled_end` exclusively. Two slots
    for the same worker collide when the new slot's start falls strictly before
    the existing slot's end *and* the existing slot's start falls strictly
    before the new slot's end. Touching slots therefore do **not** collide: a
    visit beginning at exactly the instant another ends is accepted. There is no
    buffer between visits of any kind."
    PRD §3.5: "Visits can be read individually — the read returns both axes —
    and listed, with the listing filtering on `patient_id`, `assigned_chw_id`,
    `second_chw_id`, `scheduling_status` and `documentation_status`."

    Design: Difficulty/resource_temporal_overlap/worker_visit_slots_half_open_including_second_worker_role
    """
    first_worker, patient, first_headers = fx.program_with_patient(
        employee_code="W-021B", mrn="MRN-200B", full_name="Slot Case",
    )
    second, second_headers = fx.second_worker(employee_code="W-022B")
    fx.schedule_visit(
        first_headers, patient["id"], first_worker["id"],
        "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
    )

    overlapping = api.create_home_visit(
        create_home_visit_payload(
            patient["id"], second["id"],
            "2026-06-02T09:30:00Z", "2026-06-02T10:30:00Z",
            second_chw_id=first_worker["id"],
        ),
        second_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_VISIT_SLOT_CONFLICT.value, 409)

    touching = validate_success(
        api.create_home_visit(
            create_home_visit_payload(
                patient["id"], second["id"],
                "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z",
                second_chw_id=first_worker["id"],
            ),
            second_headers,
        ),
        201,
    )
    assert touching["scheduling_status"] == "SCHEDULED", (
        "touching at 10:00:00 does not collide under half-open semantics"
    )
    assert touching["second_chw_id"] == first_worker["id"]

    _rows, meta = validate_paginated(
        api.list_home_visits(
            first_headers, params={"second_chw_id": first_worker["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one visit names that worker in the second slot, got {meta['total_count']}"
    )


def test_enrolment_is_checked_before_the_two_person_safety_rule(api):
    """PRD §2.5: "**Cross-entity state precondition** — a related row is in the
    state the operation requires (`ERR_INSTRUMENT_NOT_PUBLISHED`,
    `ERR_RESOURCE_ORG_SUSPENDED`, `ERR_PATIENT_NOT_ENROLLED` or
    `ERR_INVALID_STATE`, each 409)."
    PRD §3.5: "A `CHW` or a `Supervisor` schedules a visit by supplying the
    `patient_id`, the `assigned_chw_id` of the worker who will own and attest
    it, a `scheduled_start`, a `scheduled_end`, and optionally a
    `second_chw_id`. The patient must be `ENROLLED`."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_rung9_preempts_two_person_safety_rung11
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-013", enroll=False,
        mrn="MRN-120", full_name="Sky Bennett", address_safety_flag=True,
    )
    assert patient["enrollment_status"] == "PROSPECTIVE"
    assert patient["address_safety_flag"] is True

    response = api.create_home_visit(
        create_home_visit_payload(
            patient["id"], worker["id"],
            "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z",
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_ENROLLED.value, 409)


def test_once_enrolled_the_identical_request_reports_the_two_person_rule(api):
    """PRD §3.5: "At rung 11, the safety rule: when the patient's
    `address_safety_flag` is true, a `second_chw_id` is **mandatory**, and
    omitting it is rejected with `ERR_TWO_PERSON_VISIT_REQUIRED` (HTTP 422). The
    visit records the outcome of that rule in `two_person_required`, copied from
    the patient's `address_safety_flag` at creation."
    PRD §2.5: "**Safety** — the two-person home-visit rule
    (`ERR_TWO_PERSON_VISIT_REQUIRED`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_rung9_preempts_two_person_safety_rung11
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-013B", enroll=False,
        mrn="MRN-120B", full_name="Sky Bennett", address_safety_flag=True,
    )
    payload = create_home_visit_payload(
        patient["id"], worker["id"],
        "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z",
    )

    before = api.create_home_visit(payload, chw_headers)
    validate_error(before, ApiErrorId.ERR_PATIENT_NOT_ENROLLED.value, 409)

    enrolled = validate_success(
        api.update_patient(patient["id"], {"enrollment_action": "ENROLL"}, SUPERVISOR)
    )
    assert enrolled["enrollment_status"] == "ENROLLED"

    after = api.create_home_visit(payload, chw_headers)
    validate_error(after, ApiErrorId.ERR_TWO_PERSON_VISIT_REQUIRED.value, 422)

    _rows, meta = validate_paginated(
        api.list_home_visits(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "neither refused request created a visit"
