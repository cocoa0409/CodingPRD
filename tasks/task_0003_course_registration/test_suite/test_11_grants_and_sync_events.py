"""DepartmentAccessGrant lifecycle, cross-department flow, sync-event fan-out."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, TEST_USERS,
    SYNC_TARGETS,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, advance_clock,
    setup_cross_department_world, grant_cross_department_access,
    create_offering, create_course, create_student, open_offering,
    submit_enrollment, submit_enrollment_success, get_enrollment_request,
    list_student_sync_events, settle_tuition,
)


def test_grant_creation_status_active(api, registrar_headers):
    """PRD §3.9: "A Registrar administers cross-department permissions through
    DepartmentAccessGrant rows." PRD §2.10: "A grant has a status of ACTIVE
    on creation and may be moved to REVOKED."

    Claim: POST /department-access-grants → status=ACTIVE.
    """
    world = setup_cross_department_world()
    grant = grant_cross_department_access(
        source_department_id=world["department_home"]["id"],
        target_department_id=world["department_other"]["id"],
        categories=["GENERAL"],
    )
    assert grant["status"] == "ACTIVE"


def test_grant_revoke_blocks_subsequent_enrollments(api, registrar_headers):
    """PRD §3.9: "A Registrar can revoke a DepartmentAccessGrant at any time,
    advancing it from ACTIVE to REVOKED. After revocation, the
    cross-department check in priority 6 of §2.9 will reject any further
    enrollment requests that depended on that grant, but already-APPROVED
    enrollments are unaffected — revocation is forward-looking, not
    retroactive."

    Claim: After REVOKE, a NEW cross-department enrollment is rejected with
    ERR_CROSS_DEPARTMENT_ACCESS_DENIED.
    """
    world = setup_cross_department_world()
    grant = grant_cross_department_access(
        source_department_id=world["department_home"]["id"],
        target_department_id=world["department_other"]["id"],
        categories=["GENERAL"],
    )
    api.revoke_department_access_grant(grant["id"], TEST_USERS["registrar_headers"])

    course_other = create_course(world["department_other"]["id"], credits=3.0)
    offering = create_offering(
        term_id=world["term"]["id"], course_id=course_other["id"],
        campus_id=world["campus"]["id"], instructor_id=world["instructor_other"]["id"],
        base_capacity=5,
        scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 600}],
    )
    open_offering(offering["id"])
    res = submit_enrollment(world["student"], offering["id"])
    validate_error(res, "ERR_CROSS_DEPARTMENT_ACCESS_DENIED")


def test_enrollment_approved_emits_sync_event_to_all_four_systems(api, registrar_headers):
    """PRD §2.12 + §3.4: ENROLLMENT_APPROVED is fanned out to all four
    downstream systems. ("an ENROLLMENT_APPROVED SyncEvent is emitted to all
    four downstream systems")

    Claim: an APPROVED enrollment emits an ENROLLMENT_APPROVED SyncEvent
    targeting all four systems.
    """
    world = setup_basic_world(student_year=1)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"

    events = list_student_sync_events(world["student"]["id"])
    matching = [e for e in events if e["event_type"] == "ENROLLMENT_APPROVED"]
    assert matching, f"Expected ENROLLMENT_APPROVED event in {events}"
    targets = set(matching[-1]["target_systems"])
    assert targets == set(SYNC_TARGETS["ENROLLMENT_APPROVED"]), (
        f"Expected fan-out to {SYNC_TARGETS['ENROLLMENT_APPROVED']}, got {targets}"
    )


def test_tuition_billed_emits_only_to_finance(api, registrar_headers):
    """PRD §2.12: "TUITION_BILLED, sent only to FINANCE."

    Claim: an APPROVED enrollment emits a TUITION_BILLED SyncEvent whose
    target_systems is {FINANCE} only.
    """
    world = setup_basic_world(student_year=1)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 2, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"

    events = list_student_sync_events(world["student"]["id"])
    matching = [e for e in events if e["event_type"] == "TUITION_BILLED"]
    assert matching, f"Expected TUITION_BILLED event in {events}"
    targets = set(matching[-1]["target_systems"])
    assert targets == {"FINANCE"}, (
        f"Expected TUITION_BILLED to FINANCE only; got {targets}"
    )


def test_tuition_paid_emits_to_finance_library_dormitory(api, registrar_headers, finance_headers):
    """PRD §2.12: "TUITION_PAID, sent to FINANCE, LIBRARY, and DORMITORY."

    Claim: settle-tuition emits TUITION_PAID with the three-system fan-out.
    """
    world = setup_basic_world(student_year=1)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 3, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    settle_tuition(er["id"])

    events = list_student_sync_events(world["student"]["id"])
    matching = [e for e in events if e["event_type"] == "TUITION_PAID"]
    assert matching, f"Expected TUITION_PAID event in {events}"
    targets = set(matching[-1]["target_systems"])
    assert targets == {"FINANCE", "LIBRARY", "DORMITORY"}, (
        f"Expected TUITION_PAID to FINANCE/LIBRARY/DORMITORY; got {targets}"
    )


def test_sync_event_no_version_or_updated_at(api, registrar_headers):
    """PRD §2.4: "Two resources omit updated_at and version because they are
    immutable once written by the system: a WaitlistEntry and a SyncEvent
    both carry only id and created_at."

    Claim: SyncEvent rows have no updated_at and no version fields.
    """
    world = setup_basic_world(student_year=1)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 4, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    submit_enrollment_success(world["student"], co["offering"]["id"])
    events = list_student_sync_events(world["student"]["id"])
    assert events, "Expected at least one SyncEvent for the student"
    for e in events:
        assert "updated_at" not in e, f"SyncEvent should not have updated_at: {e}"
        assert "version" not in e, f"SyncEvent should not have version: {e}"
