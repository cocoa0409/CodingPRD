"""RBAC enforcement and optimistic concurrency control (PRD §2.1, §2.7, §3.9).

Corner queue (rbac): instructor cannot confirm (peer-role), student cannot cancel
   another student's add-on (ownership), missing auth headers.
Corner queue (cross_cutting / OCC): contract close with correct version succeeds,
   confirm with stale cohort version 412, cohort version increments on confirm.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_student_headers,
    create_contract, create_cohort, create_student, create_placed_student,
    create_enrollment, confirm, close_contract_payload, confirm_enrollment_payload,
    latest_cohort_version,
)

REG = TEST_USERS["registrar_headers"]
INSTR = TEST_USERS["instructor_headers"]


# =====================================================================
# Corner / rbac / instructor_cannot_confirm_enrollment_forbidden
# =====================================================================
def test_instructor_cannot_confirm_enrollment(api):
    """PRD §2.1: "The Registrar owns the cohort and enrollment lifecycle: creating
    cohorts and enrollments, confirming placements, withdrawing and completing
    enrollments"
    PRD §2.1: "When the headers are present and well-formed but the declared role is
    not permitted to invoke the requested operation, the request is rejected with
    ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/instructor_cannot_confirm_enrollment_forbidden
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    validate_error(
        api.confirm_enrollment(enr["id"], confirm_enrollment_payload(cohort["version"], require_seat=True), INSTR),
        ApiErrorId.ERR_FORBIDDEN.value)


# =====================================================================
# Corner / rbac / student_cannot_cancel_other_students_addon_forbidden
# =====================================================================
def test_student_cannot_cancel_other_students_addon(api):
    """PRD §2.1: "When X-User-Role is Student, X-User-ID is the id of the acting
    Student; ownership checks on any resource that references a Student compare that
    resource's student foreign key to X-User-ID. ... When an ownership-bound role acts
    on a resource it does not own, the request is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/student_cannot_cancel_other_students_addon_forbidden
    """
    cohort = create_cohort(level="B1", track="GENERAL", schedule_block="MORNING")
    stu_a = create_student(track="GENERAL")
    stu_b = create_student(track="GENERAL")
    enr = create_enrollment(stu_a["id"], cohort["id"])
    # Student A creates their own add-on (ownership-correct).
    add_on = get_success_data(api.create_add_on(
        {"student_id": stu_a["id"], "enrollment_id": enr["id"], "add_on_type": "CONVERSATION_CLUB", "units": 4},
        make_student_headers(stu_a["id"])))
    # Student B attempts to cancel A's add-on -> X-User-ID != owning student_id.
    validate_error(api.cancel_add_on(add_on["id"], make_student_headers(stu_b["id"])),
                   ApiErrorId.ERR_FORBIDDEN.value)


# =====================================================================
# Corner / rbac / missing_auth_headers_returns_unauthenticated
# =====================================================================
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that is missing either header, or that supplies a
    malformed value, on an endpoint that requires authentication is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    payload = {
        "name": "NoAuth", "level": "B1", "track": "GENERAL", "capacity": 5, "weekly_hours": 18,
        "term_start": "2026-05-04T00:00:00Z", "term_end": "2026-08-01T00:00:00Z",
        "total_sessions": 40, "base_tuition_cents": 100000, "schedule_block": "MORNING",
    }
    # No X-User-ID / X-User-Role headers at all.
    validate_error(api.raw_request("POST", "/cohorts", payload, headers={}),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


# =====================================================================
# Corner / cross_cutting / contract_close_correct_version_succeeds
# =====================================================================
def test_contract_close_correct_version_succeeds(api):
    """PRD §2.7: "The close request must carry expected_contract_version carrying the
    client's last observed version of the target CorporateContract."
    PRD §3.9: "every currently ENROLLED enrollment sponsored by the contract is
    terminated ... and the contract's version is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/contract_close_correct_version_succeeds
    """
    contract = create_contract(contracted_seats=2, discount_tier="BRONZE", company_name="ClO")
    assert contract["version"] == 1
    data = validate_success(api.close_corporate_contract(
        contract["id"], close_contract_payload(contract["version"]), REG))
    assert data["status"] == "CLOSED"
    assert data["version"] == 2, f"close bumps version 1 -> 2, got {data['version']}"


# =====================================================================
# Corner / cross_cutting / confirm_stale_cohort_version_returns_412
# =====================================================================
def test_confirm_stale_cohort_version_returns_412(api):
    """PRD §2.7: "If the cohort's version has advanced since the client last read it —
    for instance because another confirm has already consumed the last remaining seat
    and thereby legitimately superseded this client's stale view of remaining capacity
    — the request is rejected with ERR_STALE_COHORT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/confirm_stale_cohort_version_returns_412
    """
    cohort = create_cohort(level="B1", track="GENERAL", capacity=2, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING")
    stale_version = cohort["version"]
    stu_a = create_placed_student(level="B1", track="GENERAL")
    enr_a = create_enrollment(stu_a["id"], cohort["id"])
    confirm(enr_a["id"], stale_version, require_seat=True)  # bumps cohort version
    stu_b = create_placed_student(level="B1", track="GENERAL")
    enr_b = create_enrollment(stu_b["id"], cohort["id"])
    # Confirm B with the now-stale pre-bump version.
    validate_error(
        api.confirm_enrollment(enr_b["id"], confirm_enrollment_payload(stale_version, require_seat=True), REG),
        ApiErrorId.ERR_STALE_COHORT_VERSION.value)
    after = validate_success(api.get_enrollment(enr_b["id"], REG))
    assert after["status"] == "PLACEMENT_PENDING"


# =====================================================================
# Corner / cross_cutting / version_increments_on_each_cohort_mutation
# =====================================================================
def test_cohort_version_increments_on_confirm(api):
    """PRD §3.3: "Every confirm increments the cohort's version by one as part of its
    side effects, whichever branch it takes."
    PRD §2.4: "The version field is an integer that starts at its initial value on
    creation and increments by one on every mutation of the resource"

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_cohort_mutation
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    assert cohort["version"] == 1, "cohort version starts at 1"
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    after = validate_success(api.get_cohort(cohort["id"], REG))
    assert after["version"] == 2, f"+1 on confirm, got {after['version']}"
