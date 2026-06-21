"""Application submission and admissions workflow — branching SM, cascades,
yield posture, waitlist promote.

Covers Difficulty Rule 2 (yield_posture), Rule 3 (non_linear_state_machine,
both instances), Rule 7 (cross_entity_state_dependency waitlist promote),
plus related Corner side-effect verifications.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    admit_n_applications_at_school,
    api_client,
    create_school,
    make_applicant_headers,
    set_clock,
    setup_admitted_application,
    setup_aid_finalized,
    setup_ready_to_submit_application,
    setup_submitted_application,
    setup_under_review_application,
    setup_waitlisted_application,
    validate_error,
    validate_success,
)


# ─── Yield posture (Difficulty Rule 2 + Rule 6 boundary) ────────────────────

def test_yield_posture_threshold_inclusive_on_target_at_ratio_0_85(api):
    """PRD §3.2: "If the ratio is at least 1.00, the posture is OVER_TARGET;
    otherwise, if the ratio is at least 0.85, the posture is ON_TARGET;
    otherwise the posture is OPEN."
    PRD §3.2: "The thresholds are inclusive — a ratio of exactly 1.00 maps to
    OVER_TARGET, a ratio of exactly 0.85 maps to ON_TARGET".

    Design: Difficulty/combinatorial_formula/yield_posture_multi_input_nonlinear_threshold
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U Yield", state_code="CA", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=20, assumed_yield_rate=0.50,
    )
    # Drive 33 admits — projected = round(33*0.50) = 17; ratio = 17/20 = 0.85 → ON_TARGET
    admit_n_applications_at_school(33, school)
    after = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after["admitted_count"] == 33
    assert after["enrolled_count"] == 0
    assert after["yield_posture"] == "ON_TARGET"


def test_yield_posture_boundary_exact_0_85_maps_on_target(api):
    """PRD §3.2: "The thresholds are inclusive — a ratio of exactly 1.00 maps
    to OVER_TARGET, a ratio of exactly 0.85 maps to ON_TARGET — and the
    posture is recomputed every time admitted_count or enrolled_count
    changes, which in practice means every Application status transition into
    or out of ADMITTED or ENROLLED."

    Design: Difficulty/boundary_precision_check/yield_posture_exact_0_85_ratio_maps_on_target
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U Bdry", state_code="OR", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=20, assumed_yield_rate=0.50,
    )
    admit_n_applications_at_school(32, school)
    after_32 = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    # projected = round(32*0.50) = 16; ratio = 0.80 → OPEN
    assert after_32["yield_posture"] == "OPEN"
    # 33rd admit puts us exactly at 0.85
    admit_n_applications_at_school(1, school, email_prefix="bdry33")
    after_33 = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after_33["admitted_count"] == 33
    assert after_33["yield_posture"] == "ON_TARGET"


# ─── 3-way fork from UNDER_REVIEW (Difficulty Rule 3 instance 1) ────────────

def test_under_review_admit_branch_increments_school_counters(api):
    """PRD §3.6: "Admitting transitions the application from UNDER_REVIEW to
    ADMITTED, stamps decision_at with the logical clock, increments the linked
    school's admitted_count by one, recomputes the school's yield_posture as
    described in §3.2, refreshes the application's updated_at, and bumps its
    version."

    Design: Difficulty/non_linear_state_machine/application_branching_under_review_three_way_fork
    """
    set_clock("2026-09-01T00:00:00Z")
    _, school, ur = setup_under_review_application(email_suffix="fork_a")
    admitted = validate_success(
        api.admit_application(ur["id"], ur["version"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert admitted["status"] == "ADMITTED"
    assert admitted["decision_at"] is not None
    after_school = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after_school["admitted_count"] == 1
    assert after_school["denied_count"] == 0


def test_under_review_waitlist_branch_creates_pending_waitlist_entry(api):
    """PRD §3.6: "Waitlisting transitions the application from UNDER_REVIEW to
    WAITLISTED... and creates a new WaitlistEntry row whose application_id is
    the application's id, whose status is PENDING".

    Design: Difficulty/non_linear_state_machine/application_branching_under_review_three_way_fork
    """
    set_clock("2026-09-01T00:00:00Z")
    _, school, ur = setup_under_review_application(email_suffix="fork_w")
    waitlisted = validate_success(
        api.waitlist_application(ur["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert waitlisted["status"] == "WAITLISTED"
    from test_helpers import validate_paginated
    data, _ = validate_paginated(
        api.list_waitlist_entries(
            TEST_USERS["admissions_headers"], params={"application_id": ur["id"]},
        )
    )
    assert len(data) == 1
    assert data[0]["status"] == "PENDING"
    assert data[0]["application_id"] == ur["id"]


def test_under_review_deny_branch_increments_denied_count(api):
    """PRD §3.6: "Denying transitions the application from UNDER_REVIEW to
    DENIED, stamps decision_at, increments the school's denied_count by one".

    Design: Difficulty/non_linear_state_machine/application_branching_under_review_three_way_fork
    """
    set_clock("2026-09-01T00:00:00Z")
    _, school, ur = setup_under_review_application(email_suffix="fork_d")
    denied = validate_success(
        api.deny_application(ur["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert denied["status"] == "DENIED"
    after_school = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after_school["denied_count"] == 1
    assert after_school["admitted_count"] == 0


# ─── WaitlistEntry 2-way fork (Difficulty Rule 3 instance 2) ────────────────

def test_waitlist_entry_promoted_branch_via_school_promote(api):
    """PRD §3.6: "Off the waitlist, an officer may promote the lowest-rank
    PENDING entry to admitted, but only when the school's yield_posture
    equals OPEN."
    PRD §3.6: "it transitions the parent application from WAITLISTED to
    ADMITTED, overwrites decision_at with the current logical clock, cascades
    the WaitlistEntry from PENDING to PROMOTED and stamps promoted_at,
    increments the school's admitted_count, and recomputes yield_posture."

    Design: Difficulty/non_linear_state_machine/waitlist_entry_branching_pending_two_way_fork
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, waitlisted = setup_waitlisted_application(
        email_suffix="wlp",
        school_overrides={
            "name": "U WLPromote",
            "target_class_size": 1000,
            "assumed_yield_rate": 0.10,
            "deadline_iso": "2026-10-01T00:00:00Z",
        },
    )
    promoted = validate_success(
        api.promote_waitlist(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert promoted["status"] == "ADMITTED"
    # Look up the waitlist entry by application
    from test_helpers import validate_paginated
    data, _ = validate_paginated(
        api.list_waitlist_entries(
            TEST_USERS["admissions_headers"], params={"application_id": waitlisted["id"]},
        )
    )
    assert len(data) == 1
    entry = data[0]
    assert entry["status"] == "PROMOTED"
    assert entry["promoted_at"] is not None


def test_waitlist_entry_released_branch_via_applicant_decline(api):
    """PRD §3.9: "Declining is the applicant's other terminal choice and is
    allowed from either ADMITTED or WAITLISTED."
    PRD §3.9: "when the source was WAITLISTED, the corresponding PENDING
    WaitlistEntry cascades to RELEASED".

    Design: Difficulty/non_linear_state_machine/waitlist_entry_branching_pending_two_way_fork
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, waitlisted = setup_waitlisted_application(email_suffix="wld")
    declined = validate_success(
        api.decline_application(
            waitlisted["id"], make_applicant_headers(applicant["id"])
        ),
        expected_status=200,
    )
    assert declined["status"] == "DECLINED"
    from test_helpers import validate_paginated
    data, _ = validate_paginated(
        api.list_waitlist_entries(
            TEST_USERS["admissions_headers"], params={"application_id": waitlisted["id"]},
        )
    )
    assert len(data) == 1
    entry = data[0]
    assert entry["status"] == "RELEASED"
    assert entry.get("promoted_at") is None


# ─── Cross-entity: waitlist promote requires yield_posture OPEN ────────────

def test_waitlist_promote_blocked_when_yield_posture_not_open(api):
    """PRD §3.6: "A waitlist promote attempt against a school whose posture is
    ON_TARGET or OVER_TARGET is rejected with ERR_YIELD_TARGET_REACHED — the
    posture gate exists so a school cannot over-admit once its projected yield
    has caught up with its target_class_size."

    Design: Difficulty/cross_entity_state_dependency/waitlist_promote_requires_school_yield_posture_open_application_school
    """
    set_clock("2026-09-01T00:00:00Z")
    school = create_school(
        name="U CS2", state_code="GA", admission_track="REGULAR",
        deadline_iso="2026-10-01T00:00:00Z",
        decision_release_iso="2027-03-15T00:00:00Z",
        target_class_size=10, assumed_yield_rate=0.50,
    )
    # 17 admits → projected=round(8.5)=9; ratio=9/10=0.90 → ON_TARGET
    admit_n_applications_at_school(17, school, email_prefix="cs2")
    school_after = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert school_after["yield_posture"] in {"ON_TARGET", "OVER_TARGET"}
    # Create one more application that gets WAITLISTED
    late_applicant, _, waitlisted = setup_waitlisted_application(
        school=school, email_suffix="cs2_wl_late",
    )
    # Promote attempt rejected
    res = api.promote_waitlist(school["id"], TEST_USERS["admissions_headers"])
    validate_error(res, "ERR_YIELD_TARGET_REACHED")
    after = validate_success(
        api.get_application(waitlisted["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert after["status"] == "WAITLISTED"


def test_waitlist_promote_succeeds_when_yield_posture_open(api):
    """PRD §3.6: "Off the waitlist, an officer may promote the lowest-rank
    PENDING entry to admitted, but only when the school's yield_posture
    equals OPEN."

    Design: Difficulty/cross_entity_state_dependency/waitlist_promote_requires_school_yield_posture_open_application_school
    """
    set_clock("2026-09-01T00:00:00Z")
    applicant, school, waitlisted = setup_waitlisted_application(
        email_suffix="wlok",
        school_overrides={
            "name": "U WLOK",
            "target_class_size": 1000,
            "assumed_yield_rate": 0.10,
            "deadline_iso": "2026-10-01T00:00:00Z",
        },
    )
    school_before = validate_success(
        api.get_school(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert school_before["yield_posture"] == "OPEN"
    promoted = validate_success(
        api.promote_waitlist(school["id"], TEST_USERS["admissions_headers"]),
        expected_status=200,
    )
    assert promoted["status"] == "ADMITTED"


# ─── Listing — Corner endpoint claim ──────────────────────────────────────

def test_list_applications_filtered_by_applicant_id(api, platform_admin_headers):
    """PRD §3.10: "Application listing supports filtering by applicant_id,
    school_id, and status in addition to the universal limit and offset."

    Design: Corner/endpoints/list_applications_filtered_by_applicant_id
    """
    from test_helpers import create_applicant, create_draft_application, validate_paginated
    s1 = create_school(name="U LF1", state_code="MD")
    s2 = create_school(name="U LF2", state_code="VA")
    a = create_applicant(email="lf_a@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    b = create_applicant(email="lf_b@u.edu", gpa_unweighted=3.0, residency="IN_STATE")
    create_draft_application(a, s1)
    create_draft_application(b, s2)
    data, _ = validate_paginated(
        api.list_applications(
            make_applicant_headers(a["id"]), params={"applicant_id": a["id"]}
        )
    )
    assert len(data) == 1
    assert data[0]["applicant_id"] == a["id"]
