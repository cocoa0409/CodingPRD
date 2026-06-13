"""Access control, the parent-portal guardian check, withdrawal validations, and
optimistic-concurrency stale-version guards.

Covers corner instances under rbac, endpoints (portal), validations (withdraw),
and cross_cutting_complexity_layers (OCC).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    build_user_headers,
    make_teacher_headers, make_state_reporting_officer_headers,
    make_parent_headers,
    fixtures as fx,
)

REG = TEST_USERS["registrar_headers"]
TEACH = TEST_USERS["teacher_headers"]


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------
def test_teacher_cannot_create_school(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    POST /schools is authorized for Registrar only (PRD §4 endpoint table), so a
    Teacher caller hits the role-permission rule above.

    Design: Corner/rbac/teacher_cannot_create_school
    """
    resp = api.create_school(
        {"name": "Nope", "state_code": "CA"}, make_teacher_headers("teacher-1"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_registrar_cannot_finalize_report_card(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    POST /report-cards/{id}/finalize is authorized for Teacher only (PRD §4 endpoint
    table), so a Registrar caller hits the role-permission rule above.

    Design: Corner/rbac/registrar_cannot_finalize_report_card
    """
    ctx = fx.setup_report_card_ready_single_section(grading_mode="STANDARDS", mastery_level=3)
    rc = ctx["report_card"]
    resp = api.finalize_report_card(rc["id"], {"expected_report_card_version": rc["version"]}, REG)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role is not one of these
    five known role names, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bad_headers = build_user_headers("someone", "NotARole")
    resp = api.get_student(NON_EXISTENT_UUID, bad_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
                   expected_status=400)


# ---------------------------------------------------------------------------
# endpoints + validations[priority=4] (guardian check)
# ---------------------------------------------------------------------------
def test_parent_portal_summary_returns_own_child(api):
    """PRD §2.4: "when a Parent reads any resource scoped to a child — the portal
    summary, the student record, the child's daily attendance, report cards, or
    discipline incidents — the server confirms that the caller's X-User-ID is present
    in the targeted student's guardian set before returning data."

    Design: Corner/endpoints/portal_summary_returns_own_child
    """
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    validate_success(
        api.link_guardian(student["id"], {"guardian_user_id": "parent-1"}, REG),
        expected_status=201)
    summary = validate_success(api.get_portal_summary(student["id"], make_parent_headers("parent-1")))
    assert summary["id"] == student["id"], "portal summary returns the requested child"


def test_parent_not_guardian_denied(api):
    """PRD §2.4: "A parent whose identifier is not in that set receives
    ERR_NOT_GUARDIAN_OF_STUDENT."

    Design: Corner/rbac/parent_not_guardian_denied
    """
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    validate_success(
        api.link_guardian(student["id"], {"guardian_user_id": "parent-1"}, REG),
        expected_status=201)
    resp = api.get_portal_summary(student["id"], make_parent_headers("parent-9"))
    validate_error(resp, ApiErrorId.ERR_NOT_GUARDIAN_OF_STUDENT.value, expected_status=403)


# ---------------------------------------------------------------------------
# validations (withdraw edges)
# ---------------------------------------------------------------------------
def test_withdraw_exit_before_entry_rejected(api):
    """PRD §3.3: "The supplied exit_day_index must be at least the entry_day_index —
    a smaller value yields ERR_INVALID_EXIT_DAY".

    Design: Corner/validations/withdraw_exit_before_entry_rejected
    """
    school = fx.create_school()
    fx.advance_clock(school["id"], 3)
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"], entry_day_index=2)
    resp = api.withdraw_enrollment(enr["id"], {"exit_day_index": 1}, REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_EXIT_DAY.value, expected_status=422)


def test_withdraw_exit_in_future_rejected(api):
    """PRD §3.3: "and must not be in the future relative to the school's
    current_school_day_index; a larger value yields ERR_EXIT_DAY_IN_FUTURE."

    Design: Corner/validations/withdraw_exit_in_future_rejected
    """
    school = fx.create_school()
    fx.advance_clock(school["id"], 3)
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"], entry_day_index=1)
    resp = api.withdraw_enrollment(enr["id"], {"exit_day_index": 5}, REG)
    validate_error(resp, ApiErrorId.ERR_EXIT_DAY_IN_FUTURE.value, expected_status=422)


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers (OCC)
# ---------------------------------------------------------------------------
def test_finalize_with_stale_report_card_version_rejected(api):
    """PRD §2.9: "A report card's version advances whenever a standards score is
    upserted against any of the enrollment's sections, because that upsert reconciles
    the report card's derived grades."
    PRD §2.9: "If a finalize arrives carrying an expected_report_card_version that no
    longer matches the report card's current version, the finalize is rejected with
    ERR_STALE_VERSION and HTTP 412 — this prevents a client from freezing line_items
    over grades it never observed."

    Design: Corner/cross_cutting_complexity_layers/occ_report_card_finalize_stale_version
    """
    school = fx.create_school()
    student = fx.create_student(school["id"], grade_level="9")
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"], grading_mode="STANDARDS")
    section = fx.create_section(course["id"], period=1)
    sa = fx.seat(enr["id"], section["id"])
    fx.post_standard_score(sa["id"], "C.1", mastery_level=3, weight=1.0)
    rc = fx.open_report_card(enr["id"])         # version captured here as rcv0
    rcv0 = rc["version"]
    fx.post_standard_score(sa["id"], "C.2", mastery_level=4, weight=1.0)  # bumps rc.version
    resp = api.finalize_report_card(rc["id"], {"expected_report_card_version": rcv0}, TEACH)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    refreshed = validate_success(api.get_report_card(rc["id"], TEACH))
    assert refreshed["status"] == "DRAFT", "report card stays DRAFT after stale finalize"


def test_certify_with_stale_report_version_rejected(api):
    """PRD §2.9: "a draft funding report's version advances each time it is recomputed
    against current attendance and membership; if a certify arrives carrying an
    expected_report_version that no longer matches the report's current version, the
    certify is rejected with ERR_STALE_VERSION and HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/occ_ada_certify_stale_after_recompute
    """
    school = fx.create_school(ada_method="AGGREGATE_MEMBERSHIP")
    rep = fx.draft_ada_report(school["id"], as_of_day_index=0, drafter_user_id="registrar-d")
    repv0 = rep["version"]
    validate_success(api.recompute_ada_report(rep["id"], build_user_headers("registrar-d", "Registrar")))
    resp = api.certify_ada_report(
        rep["id"], {"expected_report_version": repv0},
        make_state_reporting_officer_headers("officer-1"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    refreshed = validate_success(api.get_ada_report(rep["id"], REG))
    assert refreshed["status"] == "DRAFT", "report stays DRAFT after stale certify"
