"""Home-visit temporal guards and validation precedence (PRD §2.10, §3.3, §3.8).

Depth coverage for the same-enrollment half-open overlap, the date-agnostic session
intersection, the state-before-temporal precedence on home-visit creation, and the
duplicate-before-age-band precedence on submit.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_active_enrollment,
    add_home_visit, create_home_visit_payload,
    create_program, create_cohort, create_family, create_application,
    submit_application,
)

ES = TEST_USERS["enrollment_specialist_headers"]
PA = TEST_USERS["program_admin_headers"]
FSW = TEST_USERS["family_services_worker_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / home_visit_overlaps_same_enrollment_half_open
# ---------------------------------------------------------------------------
def test_overlapping_home_visit_window_rejected(api):
    """PRD §3.8: "The proposed window may not overlap an existing non-cancelled home
    visit for the same enrollment on the same `scheduled_date`; because the interval is
    half-open, windows that merely touch at a boundary do not overlap, but any genuine
    overlap is rejected with `ERR_HOME_VISIT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/home_visit_overlaps_same_enrollment_half_open
    """
    b = setup_active_enrollment()
    add_home_visit(b["enrollment"]["id"], "2026-04-01", "13:00", "14:00")
    resp = api.create_home_visit(
        create_home_visit_payload(b["enrollment"]["id"], "2026-04-01", "13:30", "14:30"), FSW)
    validate_error(resp, ApiErrorId.ERR_HOME_VISIT_OVERLAP)


def test_touching_home_visit_window_allowed(api):
    """PRD §3.8: "because the interval is half-open, windows that merely touch at a
    boundary do not overlap, but any genuine overlap is rejected with
    `ERR_HOME_VISIT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/home_visit_overlaps_same_enrollment_half_open
    """
    b = setup_active_enrollment()
    add_home_visit(b["enrollment"]["id"], "2026-04-01", "13:00", "14:00")
    resp = api.create_home_visit(
        create_home_visit_payload(b["enrollment"]["id"], "2026-04-01", "14:00", "15:00"), FSW)
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / home_visit_intersects_cohort_session_window
# ---------------------------------------------------------------------------
def test_home_visit_during_session_rejected(api):
    """PRD §3.8: "The proposed window also may not intersect the child's cohort daily
    session window `[session_start, session_end)` as a time-of-day comparison, evaluated
    regardless of the calendar date; an intersection is rejected with
    `ERR_VISIT_DURING_SESSION`."

    Design: Difficulty/resource_temporal_overlap/home_visit_intersects_cohort_session_window
    """
    b = setup_active_enrollment()  # cohort session 09:00-12:00
    resp = api.create_home_visit(
        create_home_visit_payload(b["enrollment"]["id"], "2026-04-02", "10:00", "11:00"), FSW)
    validate_error(resp, ApiErrorId.ERR_VISIT_DURING_SESSION)


def test_home_visit_touching_session_end_allowed(api):
    """PRD §3.8: "The proposed window also may not intersect the child's cohort daily
    session window `[session_start, session_end)` as a time-of-day comparison, evaluated
    regardless of the calendar date; an intersection is rejected with
    `ERR_VISIT_DURING_SESSION`."

    Design: Difficulty/resource_temporal_overlap/home_visit_intersects_cohort_session_window
    """
    b = setup_active_enrollment()  # session [09:00,12:00); [12:00,13:00) does not intersect
    resp = api.create_home_visit(
        create_home_visit_payload(b["enrollment"]["id"], "2026-04-02", "12:00", "13:00"), FSW)
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / homevisit_state_beats_temporal_overlap
# ---------------------------------------------------------------------------
def test_enrollment_not_active_beats_home_visit_overlap(api):
    """PRD §2.10: "State-precondition checks follow (in the order:
    eligibility-verification-requires-submitted, waitlist-requires-eligible,
    accept-or-decline-requires-pending-offer, sub-resource-creation-requires-active-enrollment,
    and the invalid-state checks for transition-plan completion, offer expiry, and
    home-visit completion). Business rules follow those (duplicate application, age band,
    offer expiry timing, home-visit overlap, home-visit-during-session, transition
    prerequisites, empty eligible pool, and the stale-version check)."
    PRD §3.8: "A home visit may only be scheduled while the enrollment is `ACTIVE`,
    otherwise `ERR_ENROLLMENT_NOT_ACTIVE` is returned."

    Design: Difficulty/priority_pair_validation_conflict/homevisit_state_beats_temporal_overlap
    """
    b = setup_active_enrollment()
    enr_id = b["enrollment"]["id"]
    add_home_visit(enr_id, "2026-04-01", "13:00", "14:00")
    validate_success(api.withdraw_enrollment(enr_id, PA))
    resp = api.create_home_visit(
        create_home_visit_payload(enr_id, "2026-04-01", "13:30", "14:30"), FSW)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)


def test_active_enrollment_overlap_yields_overlap_error(api):
    """PRD §2.10: "Business rules follow those (duplicate application, age band, offer
    expiry timing, home-visit overlap, home-visit-during-session, transition
    prerequisites, empty eligible pool, and the stale-version check)."
    PRD §3.8: "any genuine overlap is rejected with `ERR_HOME_VISIT_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/homevisit_state_beats_temporal_overlap
    """
    b = setup_active_enrollment()  # enrollment stays ACTIVE -> state guard passes
    enr_id = b["enrollment"]["id"]
    add_home_visit(enr_id, "2026-04-01", "13:00", "14:00")
    resp = api.create_home_visit(
        create_home_visit_payload(enr_id, "2026-04-01", "13:30", "14:30"), FSW)
    validate_error(resp, ApiErrorId.ERR_HOME_VISIT_OVERLAP)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / submit_duplicate_beats_age_out_of_band
# ---------------------------------------------------------------------------
def _program_with_two_cohorts():
    program = create_program()
    coh_p4 = create_cohort(program["id"], age_band="PRESCHOOL_4",
                           min_age_months=48, max_age_months=60)
    coh_td = create_cohort(program["id"], age_band="TODDLER",
                           min_age_months=12, max_age_months=35)
    return program, coh_p4, coh_td


def test_duplicate_application_beats_age_out_of_band(api):
    """PRD §2.10: "Business rules follow those (duplicate application, age band, offer
    expiry timing, home-visit overlap, home-visit-during-session, transition
    prerequisites, empty eligible pool, and the stale-version check)."
    PRD §3.3: "First, no other non-terminal application may already exist for the same
    `family_id` and `child_dob` within the same `program_id`; a collision is rejected
    with `ERR_DUPLICATE_APPLICATION`."

    Design: Difficulty/priority_pair_validation_conflict/submit_duplicate_beats_age_out_of_band
    """
    program, coh_p4, coh_td = _program_with_two_cohorts()
    family = create_family(categorical_eligibility="TANF")
    app1 = create_application(program["id"], coh_p4["id"], family["id"], child_dob="2022-01-10")
    submit_application(app1["id"])  # first submit, in-band -> SUBMITTED (non-terminal)
    app2 = create_application(program["id"], coh_td["id"], family["id"], child_dob="2022-01-10")
    resp = api.submit_application(app2["id"], ES)  # duplicate AND age-out-of-band
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)


def test_age_out_of_band_alone_yields_age_error(api):
    """PRD §3.3: "Second, the child's computed `age_months_at_cutoff` must fall inside
    the target cohort's inclusive age band — that is, at least `min_age_months` and at
    most `max_age_months` — otherwise the submission is rejected with
    `ERR_AGE_OUT_OF_BAND`."

    Design: Difficulty/priority_pair_validation_conflict/submit_duplicate_beats_age_out_of_band
    """
    program, coh_p4, coh_td = _program_with_two_cohorts()
    family = create_family(categorical_eligibility="TANF")
    # Single application (no duplicate), targeting TODDLER with a 55-month child.
    app = create_application(program["id"], coh_td["id"], family["id"], child_dob="2022-01-10")
    resp = api.submit_application(app["id"], ES)
    validate_error(resp, ApiErrorId.ERR_AGE_OUT_OF_BAND)
