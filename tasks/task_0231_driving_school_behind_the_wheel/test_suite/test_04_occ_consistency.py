"""Optimistic concurrency, derived wallet reconciliation, and immediate
consistency.

Corner-design queue B: sections `cross_cutting_complexity_layers`,
`consistency_model`.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_student, create_package, create_active_enrollment,
    setup_road_scheduling_context, student_version,
    create_lesson_payload, create_wallet_entry_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def test_occ_stale_student_version_on_schedule_rejected(api):
    """PRD §2.10: "if another write has advanced the student's version in the
    meantime — a prior lesson completion that bumped the hour ledgers, a permit
    recording, or any other mutation — the client's view of the student's
    remaining road hours and milestone status is stale, and the create is
    rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_student_version_on_schedule_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context()  # record-permit advanced the version
    live = student_version(ctx["student"]["id"])
    payload = create_lesson_payload(
        ctx["student"]["id"], ctx["enrollment"]["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        live - 1,  # stale: one behind the live version
        instructor_id=ctx["instructor"]["id"], vehicle_id=ctx["vehicle"]["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_STUDENT_VERSION, expected_status=412)


def test_occ_correct_student_version_on_schedule_succeeds(api):
    """PRD §2.10: "The schedule-lesson request must carry
    `expected_student_version`, a non-optional field whose value is the
    `version` of the target `Student` as the client last observed it."
    PRD §3.6: "For a road lesson, that `duration_hours` is added to the
    student's `scheduled_road_hours` at creation. Scheduling advances the
    student's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_student_version_on_schedule_succeeds
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context()
    live = student_version(ctx["student"]["id"])
    payload = create_lesson_payload(
        ctx["student"]["id"], ctx["enrollment"]["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        live,
        instructor_id=ctx["instructor"]["id"], vehicle_id=ctx["vehicle"]["id"],
    )
    lesson = validate_success(api.create_lesson(payload, ADMIN), expected_status=201)
    assert lesson["status"] == "SCHEDULED"
    student = validate_success(api.get_student(ctx["student"]["id"], ADMIN))
    assert student["scheduled_road_hours"] == 2
    assert student["version"] == live + 1


def test_derived_wallet_balance_reconciles_after_two_entries(api):
    """PRD §2.9: "Each student has a wallet whose running balance,
    `wallet_balance_cents`, is the signed sum of that student's wallet entries.
    ... A positive `amount_cents` raises the balance and a negative one lowers
    it; the student's `wallet_balance_cents` is re-derived from the entries
    rather than stored independently."

    Design: Corner/cross_cutting_complexity_layers/derived_wallet_balance_reconciles_after_two_entries
    """
    set_clock("2026-06-01T00:00:00.000Z")
    stu = create_student(full_name="Dwf Stu", email="dwf@x.com",
                        date_of_birth="1990-01-01")
    api.create_wallet_entry(
        create_wallet_entry_payload(stu["id"], 5000, "ADMIN_ADJUSTMENT"), ADMIN
    )
    api.create_wallet_entry(
        create_wallet_entry_payload(stu["id"], -1500, "ADMIN_ADJUSTMENT"), ADMIN
    )
    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["wallet_balance_cents"] == 3500


def test_activate_enrollment_response_reflects_immediate_state(api):
    """PRD §3.4: "Activation ... drives the enrollment from `DRAFT` to `ACTIVE`
    ... the system computes the net charge into `final_price_cents` ... sets the
    status to `ACTIVE`, bubbles a `PROSPECT` student to `ENROLLED` as described
    in §3.3."
    PRD §3.4: "for an adult with no promo on the same package, only the bundle
    flat applies and both percentage steps are skipped."

    Design: Corner/consistency_model/activate_enrollment_response_reflects_immediate_state
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    stu = create_student(full_name="Im Med", email="immed@x.com",
                        date_of_birth="1990-01-01")
    enr = create_active_enrollment(stu["id"], pkg["id"])
    assert enr["status"] == "ACTIVE"
    assert enr["final_price_cents"] == 85000
    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["status"] == "ENROLLED"
