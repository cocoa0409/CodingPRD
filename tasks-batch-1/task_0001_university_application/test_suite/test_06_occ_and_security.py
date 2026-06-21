"""Optimistic concurrency on admit (OCC), enrollment-uniqueness aggregate,
compensating invariants, and RBAC.

Covers Difficulty Rule 8 instance 2 (enrollment_uniqueness_open_ended),
Rule 9 (compensating_invariant — both instances), plus Corner OCC happy-path,
Corner RBAC denial set, and Corner stale-version trigger.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_aid_package_payload,
    create_application_payload,
    create_school,
    make_applicant_headers,
    set_clock,
    setup_admitted_application,
    setup_aid_finalized,
    setup_applicant_with_fap,
    setup_ready_to_submit_application,
    setup_submitted_application,
    setup_under_review_application,
    validate_error,
    validate_success,
)


# ─── OCC: stale-version trigger (Corner) ───────────────────────────────────

def test_admit_with_stale_version_returns_stale_error(api):
    """PRD §2.7: "the admission decision that drives an Application from
    UNDER_REVIEW to ADMITTED. That request must include a non-optional input
    field named expected_application_version whose value is the version
    integer the writer last observed on the target Application. If the value
    does not equal the row's current version at the moment the server
    processes the request, the operation is rejected with ERR_STALE_VERSION
    and HTTP status 412."

    Design: Corner/validations/stale_version_admit_stub
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, ur = setup_under_review_application(
        email_suffix="sv", rec_ratings=[4, 4],
    )
    observed_version = ur["version"]
    # Another writer (PlatformAdmin) submits a third recommendation — this
    # recomputes composite_score (per PRD §3.5) and bumps Application.version.
    from test_helpers import create_submitted_recommendation
    create_submitted_recommendation(
        applicant, school, recommender_email="r3_sv@late.edu", rating=5,
    )
    # Stale version triggers ERR_STALE_VERSION (HTTP 412)
    res = api.admit_application(
        ur["id"], observed_version, TEST_USERS["admissions_headers"]
    )
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(
        api.get_application(ur["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after["status"] == "UNDER_REVIEW"


def test_admit_with_correct_version_succeeds(api):
    """PRD §2.7: "the admission decision that drives an Application from
    UNDER_REVIEW to ADMITTED. That request must include a non-optional input
    field named expected_application_version whose value is the version
    integer the writer last observed on the target Application."
    PRD §2.4: "version is an integer that starts at 1 at creation and
    increments by exactly one on every server-acknowledged mutation of the
    row".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, ur = setup_under_review_application(email_suffix="occok")
    observed = ur["version"]
    admitted = validate_success(
        api.admit_application(ur["id"], observed, TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert admitted["status"] == "ADMITTED"
    assert admitted["version"] == observed + 1


# ─── Enrollment-uniqueness aggregate (Difficulty Rule 8 instance 2) ────────

def test_enrollment_uniqueness_blocks_second_enroll(api):
    """PRD §3.9: "the applicant does not already have another Application in
    ENROLLED status — the aggregate-capacity rule, enforced by
    ERR_ENROLLMENT_ALREADY_DECLARED, says an applicant can be enrolled in at
    most one school across the lifetime of their account (an open-ended
    occupation interval starting at the enroll instant)."

    Design: Difficulty/resource_temporal_overlap/enrollment_uniqueness_aggregate_capacity_one_over_open_ended_window
    """
    set_clock("2026-09-01T00:00:00Z")
    s_e1 = create_school(name="U E1", state_code="RI", admission_track="REGULAR")
    # Use ROLLING for the second school so review may begin before deadline (PRD §3.6).
    s_e2 = create_school(
        name="U E2", state_code="NH", admission_track="ROLLING",
        deadline_iso="2027-04-01T00:00:00Z",
        decision_release_iso="2027-06-15T00:00:00Z",
    )
    applicant = setup_applicant_with_fap(
        email="ee@u.edu", gpa=3.80, sat_total=1400, residency="IN_STATE",
    )
    # First app — admit, finalize aid, enroll.
    _, _, admitted_1, _ = setup_aid_finalized(
        school=s_e1, applicant=applicant, email_suffix="ee1",
    )
    enrolled_1 = validate_success(
        api.enroll_application(admitted_1["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert enrolled_1["status"] == "ENROLLED"
    # Second app (rolling) — ready, submit, review, admit, draft+finalize aid.
    _, _, ready_2 = setup_ready_to_submit_application(
        school=s_e2, applicant=applicant, email_suffix="ee2",
    )
    submitted_2 = validate_success(
        api.submit_application(ready_2["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    under_review_2 = validate_success(
        api.begin_review_application(submitted_2["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    admitted_2 = validate_success(
        api.admit_application(
            under_review_2["id"], under_review_2["version"],
            TEST_USERS["admissions_headers"],
        ),
        expected_status=200,
    )
    aid_2_drafted = validate_success(
        api.create_aid_package(
            create_aid_package_payload(admitted_2["id"]),
            TEST_USERS["financial_aid_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.finalize_aid_package(
            aid_2_drafted["id"], TEST_USERS["financial_aid_headers"]
        ),
        expected_status=200,
    )
    # Trigger: second enroll attempt → ERR_ENROLLMENT_ALREADY_DECLARED
    res = api.enroll_application(admitted_2["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ENROLLMENT_ALREADY_DECLARED")
    after_2 = validate_success(
        api.get_application(admitted_2["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after_2["status"] == "ADMITTED"
    after_1 = validate_success(
        api.get_application(admitted_1["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after_1["status"] == "ENROLLED"


# ─── Compensating invariants (Difficulty Rule 9 — both instances) ──────────

def test_submit_then_withdraw_preserves_submission_count(api):
    """PRD §3.1: "It is recomputed only at the boundary crossings: incremented
    when an application transitions from DRAFT to SUBMITTED, decremented when
    an application transitions from SUBMITTED back to WITHDRAWN."
    PRD §3.9: "Withdrawing from SUBMITTED additionally decrements the
    applicant's submitted_application_count by one; withdrawing from DRAFT
    does not (the application was never counted)."

    Design: Difficulty/compensating_invariant/submit_withdraw_preserves_applicant_submission_count
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, _, submitted = setup_submitted_application(email_suffix="inv1")
    a_mid = validate_success(
        api.get_applicant(applicant["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert a_mid["submitted_application_count"] == 1
    withdrawn = validate_success(
        api.withdraw_application(submitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    a_after = validate_success(
        api.get_applicant(applicant["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert a_after["submitted_application_count"] == 0


def test_admit_then_decline_preserves_decision_volume(api):
    """PRD §3.6: "Admitting transitions the application from UNDER_REVIEW to
    ADMITTED, stamps decision_at with the logical clock, increments the
    linked school's admitted_count by one".
    PRD §3.9: "when the source was ADMITTED, decrements the school's
    admitted_count and recomputes yield_posture".

    Design: Difficulty/compensating_invariant/admit_decline_preserves_school_decision_volume
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, ur = setup_under_review_application(
        email_suffix="inv2", gpa=3.80, sat_total=1400,
    )
    admitted = validate_success(
        api.admit_application(ur["id"], ur["version"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    s_after_admit = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert s_after_admit["admitted_count"] == 1
    assert s_after_admit["declined_count"] == 0
    declined = validate_success(
        api.decline_application(admitted["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert declined["status"] == "DECLINED"
    s_after_decline = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert s_after_decline["admitted_count"] == 0
    assert s_after_decline["declined_count"] == 1
    # Conservation of admitted_count + declined_count across the round-trip
    volume_before = s_after_admit["admitted_count"] + s_after_admit["declined_count"]
    volume_after = s_after_decline["admitted_count"] + s_after_decline["declined_count"]
    assert volume_before == volume_after == 1


# ─── RBAC denials (Corner) ────────────────────────────────────────────────

def test_rbac_applicant_cannot_admit_application(api):
    """PRD §2.1: "Once authentication succeeds, the server checks whether the
    role is permitted for the requested operation per §1.7 of this contract
    (reflected in the Authorized Role column of §4); a role that authenticates
    but is not on the endpoint's allow-list is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/rbac_applicant_cannot_admit_application
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, _, ur = setup_under_review_application(email_suffix="rb")
    res = api.admit_application(
        ur["id"], ur["version"], make_applicant_headers(applicant["id"])
    )
    validate_error(res, "ERR_UNAUTHORIZED")
    after = validate_success(
        api.get_application(ur["id"], make_applicant_headers(applicant["id"])),
        expected_status=200,
    )
    assert after["status"] == "UNDER_REVIEW"


def test_rbac_admissions_cannot_create_aid_package(api):
    """PRD §2.1: "a role that authenticates but is not on the endpoint's
    allow-list is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/rbac_admissions_cannot_create_aid_package
    """
    set_clock("2026-09-01T00:00:00Z")
    _, _, admitted = setup_admitted_application(email_suffix="rbf")
    res = api.create_aid_package(
        create_aid_package_payload(admitted["id"]),
        TEST_USERS["admissions_headers"],
    )
    validate_error(res, "ERR_UNAUTHORIZED")


def test_rbac_applicant_owner_mismatch_blocks_withdraw(api):
    """PRD §2.1: "every ownership check on a resource that references an
    applicant — an Application via its applicant_id... compares the relevant
    foreign-key field to X-User-ID and rejects a mismatch with
    ERR_FORBIDDEN_OWNER_MISMATCH."

    Design: Corner/rbac/rbac_applicant_owner_mismatch_blocks_withdraw
    """
    from test_helpers import create_applicant, create_draft_application
    school = create_school(name="U OM", state_code="WV")
    a = create_applicant(email="om_a@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    b = create_applicant(email="om_b@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    app = create_draft_application(a, school)
    # B attempts to withdraw A's application.
    res = api.withdraw_application(app["id"], make_applicant_headers(b["id"]))
    validate_error(res, "ERR_FORBIDDEN_OWNER_MISMATCH")


def test_rbac_anonymous_unauthenticated_on_protected_endpoint(api):
    """PRD §2.1: "Every request other than the two explicit anonymous
    endpoints (applicant self-registration and the test-driving clock setter
    — see §2.1.1 below) must carry two HTTP headers: X-User-ID and
    X-User-Role.... Any missing header, malformed header, or role string
    outside that enumeration is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/rbac_anonymous_unauthenticated_on_protected_endpoint
    """
    # GET /applications is auth-required; call without headers.
    res = api.list_applications({})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Clock singleton (Corner endpoint) ────────────────────────────────────

def test_clock_set_returns_singleton(api):
    """PRD §2.10: "The platform maintains a singleton logical clock used for
    every deadline comparison. The clock's only mutable field is current_utc,
    an ISO 8601 UTC timestamp. A PlatformAdmin test-driving capability accepts
    a request body containing a to_iso8601 field and overwrites current_utc
    with that value; a read capability returns the singleton's current value."

    Design: Corner/endpoints/clock_set_returns_singleton
    """
    set_res = api.set_clock("2026-07-04T12:00:00Z")
    validate_success(set_res, expected_status=200)
    read = validate_success(
        api.get_clock(TEST_USERS["platform_admin_headers"]),
        expected_status=200,
    )
    assert read["current_utc"] == "2026-07-04T12:00:00Z"
