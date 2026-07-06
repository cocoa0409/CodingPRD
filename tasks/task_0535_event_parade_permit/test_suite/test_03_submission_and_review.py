"""Submit-for-review gates (empty plan, capacity, double-booking, OCC) and the
multi-department review lifecycle (approve, revision loop, veto, quorum, mismatch).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    make_applicant_headers, make_reviewer_headers, officer_headers,
    create_venue, create_applicant, create_closure_schedule, create_application,
    add_segment, get_venue_version, get_reviews_by_department,
    setup_draft_with_segment, setup_under_review, STAFFING,
)
import test_helpers.factories as F


# ==========================================================================
# Submit gates — empty route plan (queue A)
# ==========================================================================
def test_empty_route_plan_blocks_submit(api):
    """PRD §3.4: "The application must already carry at least one route segment, or
    the submit is rejected with ERR_ROUTE_PLAN_EMPTY."

    Design: Difficulty/boundary_precision_check/empty_route_plan_blocks_submit
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="RALLY",
                             expected_attendance=500,
                             occupy_start="2026-06-13T10:00:00Z",
                             occupy_end="2026-06-13T14:00:00Z")
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.submit_for_review(app["id"], {"expected_venue_version": venue["version"]}, hdrs)
    validate_error(resp, ApiErrorId.ERR_ROUTE_PLAN_EMPTY, expected_status=409)
    after = validate_success(api.get_application(app["id"], hdrs))
    assert after["status"] == "DRAFT"


def test_submit_with_one_segment_succeeds_to_under_review(api):
    """PRD §3.4: "On a first, successful submit from DRAFT, the application transitions
    DRAFT → UNDER_REVIEW and four DepartmentReview children are created, one per
    department — POLICE, FIRE, EMS, and PUBLIC_WORKS — each born PENDING."

    Design: Difficulty/boundary_precision_check/empty_route_plan_blocks_submit
    """
    ctx = setup_draft_with_segment(attendance=500, max_capacity=6000)
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    resp = api.submit_for_review(ctx["application"]["id"],
                                 {"expected_venue_version": ctx["venue_v0"]}, hdrs)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "UNDER_REVIEW"
    reviews = get_reviews_by_department(ctx["application"]["id"])
    assert set(reviews.keys()) == {"POLICE", "FIRE", "EMS", "PUBLIC_WORKS"}


# ==========================================================================
# Capacity boundary (queue B) and capacity-vs-double-booking priority (queue A)
# ==========================================================================
def test_capacity_boundary_equal_allows_submit(api):
    """PRD §3.4: "The expected_attendance must not exceed the venue's max_capacity, or
    the submit is rejected with ERR_CAPACITY_EXCEEDED."

    Design: Corner/validations/capacity_boundary_equal_allows_submit
    """
    ctx = setup_draft_with_segment(attendance=1000, max_capacity=1000, buffer=60,
                                   venue_type="PLAZA", event_kind="PARADE",
                                   occupy_start="2026-07-02T10:00:00Z",
                                   occupy_end="2026-07-02T14:00:00Z",
                                   closure_start="2026-07-02T09:00:00Z",
                                   closure_end="2026-07-02T15:00:00Z")
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    resp = api.submit_for_review(ctx["application"]["id"],
                                 {"expected_venue_version": ctx["venue_v0"]}, hdrs)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "UNDER_REVIEW"  # 1000 <= 1000 passes


def test_capacity_vs_double_booking_priority(api):
    """PRD §3.4: "The expected_attendance must not exceed the venue's max_capacity, or
    the submit is rejected with ERR_CAPACITY_EXCEEDED. The venue occupancy window ...
    must not overlap the booked window of any other non-terminal application on the
    same venue, or the submit is rejected with ERR_VENUE_DOUBLE_BOOKED." PRD §2.6:
    "Where two checks guard the same endpoint, the earlier one in this ordering
    surfaces first and masks the later one."

    Design: Difficulty/priority_pair_validation_conflict/capacity_vs_double_booking_priority
    """
    venue = create_venue(venue_type="PLAZA", max_capacity=1000, setup_buffer_minutes=60)
    sched1 = create_closure_schedule(corridor_name="A St", min_gap_minutes=30)
    sched2 = create_closure_schedule(corridor_name="B St", min_gap_minutes=30)
    u1 = create_applicant(org_name="Org G1", contact_email="g1@x.com")
    u2 = create_applicant(org_name="Org G2", contact_email="g2@x.com")
    # App1: fits capacity (800), books [10:00,14:00]
    app1 = create_application(venue["id"], u1["id"], event_kind="PARADE",
                              expected_attendance=800,
                              occupy_start="2026-06-09T10:00:00Z",
                              occupy_end="2026-06-09T14:00:00Z")
    add_segment(app1["id"], u1["id"], sched1["id"], segment_label="A 1-3",
                closure_start="2026-06-09T09:00:00Z", closure_end="2026-06-09T15:00:00Z")
    api.submit_for_review(app1["id"], {"expected_venue_version": venue["version"]},
                          make_applicant_headers(u1["id"]))
    venue_v1 = get_venue_version(venue["id"])
    # App2: exceeds capacity (2000 > 1000) AND overlaps [12:00,16:00]
    app2 = create_application(venue["id"], u2["id"], event_kind="FESTIVAL",
                              expected_attendance=2000,
                              occupy_start="2026-06-09T12:00:00Z",
                              occupy_end="2026-06-09T16:00:00Z")
    add_segment(app2["id"], u2["id"], sched2["id"], segment_label="B 1-3",
                closure_start="2026-06-09T11:00:00Z", closure_end="2026-06-09T17:00:00Z")
    resp = api.submit_for_review(app2["id"], {"expected_venue_version": venue_v1},
                                 make_applicant_headers(u2["id"]))
    # capacity (business rule earlier in §3 ordering) masks double-booking
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)


def test_capacity_vs_double_booking_priority_leaves_second_app_draft(api):
    """PRD §3.4: "The expected_attendance must not exceed the venue's max_capacity, or
    the submit is rejected with ERR_CAPACITY_EXCEEDED." PRD §2.6: "Where two checks
    guard the same endpoint, the earlier one in this ordering surfaces first and masks
    the later one." (Second angle: the masked ERR_VENUE_DOUBLE_BOOKED never surfaces
    and the rejected application remains DRAFT.)

    Design: Difficulty/priority_pair_validation_conflict/capacity_vs_double_booking_priority
    """
    venue = create_venue(venue_type="PLAZA", max_capacity=1000, setup_buffer_minutes=60)
    sched1 = create_closure_schedule(corridor_name="AA St", min_gap_minutes=30)
    sched2 = create_closure_schedule(corridor_name="BB St", min_gap_minutes=30)
    u1 = create_applicant(org_name="Org H1", contact_email="h1@x.com")
    u2 = create_applicant(org_name="Org H2", contact_email="h2@x.com")
    app1 = create_application(venue["id"], u1["id"], event_kind="PARADE",
                              expected_attendance=800,
                              occupy_start="2026-08-09T10:00:00Z",
                              occupy_end="2026-08-09T14:00:00Z")
    add_segment(app1["id"], u1["id"], sched1["id"], segment_label="AA 1-3",
                closure_start="2026-08-09T09:00:00Z", closure_end="2026-08-09T15:00:00Z")
    api.submit_for_review(app1["id"], {"expected_venue_version": venue["version"]},
                          make_applicant_headers(u1["id"]))
    venue_v1 = get_venue_version(venue["id"])
    app2 = create_application(venue["id"], u2["id"], event_kind="FESTIVAL",
                              expected_attendance=2000,
                              occupy_start="2026-08-09T12:00:00Z",
                              occupy_end="2026-08-09T16:00:00Z")
    add_segment(app2["id"], u2["id"], sched2["id"], segment_label="BB 1-3",
                closure_start="2026-08-09T11:00:00Z", closure_end="2026-08-09T17:00:00Z")
    resp = api.submit_for_review(app2["id"], {"expected_venue_version": venue_v1},
                                 make_applicant_headers(u2["id"]))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)
    after = validate_success(api.get_application(app2["id"], make_applicant_headers(u2["id"])))
    assert after["status"] == "DRAFT"


# ==========================================================================
# Venue double-booking with buffer (queue A)
# ==========================================================================
def test_venue_buffered_interval_double_booking(api):
    """PRD §2.7: "it expands the candidate application's occupancy window by
    setup_buffer_minutes at both the start and the end, and rejects the booking if
    that expanded window overlaps the (likewise-relevant) booked window of any other
    non-terminal application on the same venue. This is a closed-interval buffer
    test: touching within the buffer counts as a conflict." PRD §3.4: rejection is
    "ERR_VENUE_DOUBLE_BOOKED".

    Design: Difficulty/resource_temporal_overlap/venue_buffered_interval_double_booking
    """
    venue = create_venue(venue_type="PARK", max_capacity=5000, setup_buffer_minutes=60)
    sched1 = create_closure_schedule(corridor_name="M1 St", min_gap_minutes=30)
    sched2 = create_closure_schedule(corridor_name="M2 St", min_gap_minutes=30)
    u1 = create_applicant(org_name="Org M1", contact_email="m1@x.com")
    u2 = create_applicant(org_name="Org M2", contact_email="m2@x.com")
    app1 = create_application(venue["id"], u1["id"], event_kind="PARADE",
                              expected_attendance=2000,
                              occupy_start="2026-06-16T10:00:00Z",
                              occupy_end="2026-06-16T14:00:00Z")
    add_segment(app1["id"], u1["id"], sched1["id"], segment_label="M1 1-3",
                closure_start="2026-06-16T09:00:00Z", closure_end="2026-06-16T15:00:00Z")
    api.submit_for_review(app1["id"], {"expected_venue_version": venue["version"]},
                          make_applicant_headers(u1["id"]))
    venue_v1 = get_venue_version(venue["id"])
    # App2 [14:30,18:00]+60 => [13:30,19:00] collides with App1 [09:00,15:00] at 13:30<15:00
    app2 = create_application(venue["id"], u2["id"], event_kind="FESTIVAL",
                              expected_attendance=2000,
                              occupy_start="2026-06-16T14:30:00Z",
                              occupy_end="2026-06-16T18:00:00Z")
    add_segment(app2["id"], u2["id"], sched2["id"], segment_label="M2 1-3",
                closure_start="2026-06-16T13:30:00Z", closure_end="2026-06-16T19:00:00Z")
    resp = api.submit_for_review(app2["id"], {"expected_venue_version": venue_v1},
                                 make_applicant_headers(u2["id"]))
    validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED, expected_status=409)
    after = validate_success(api.get_application(app2["id"], make_applicant_headers(u2["id"])))
    assert after["status"] == "DRAFT"


def test_venue_buffer_touching_within_buffer_is_conflict(api):
    """PRD §2.7: "This is a closed-interval buffer test: touching within the buffer
    counts as a conflict." PRD §3.4: the buffered occupancy window "must not overlap
    the booked window of any other non-terminal application on the same venue, or the
    submit is rejected with ERR_VENUE_DOUBLE_BOOKED." (Second angle: a later, tightly
    adjacent window whose buffer expansion reaches back into App1's booked window.)

    Design: Difficulty/resource_temporal_overlap/venue_buffered_interval_double_booking
    """
    venue = create_venue(venue_type="PARK", max_capacity=5000, setup_buffer_minutes=60)
    sched1 = create_closure_schedule(corridor_name="Q1 St", min_gap_minutes=30)
    sched2 = create_closure_schedule(corridor_name="Q2 St", min_gap_minutes=30)
    u1 = create_applicant(org_name="Org Q1", contact_email="q1@x.com")
    u2 = create_applicant(org_name="Org Q2", contact_email="q2@x.com")
    # App1 booked [10:00,14:00] -> buffered [09:00,15:00]
    app1 = create_application(venue["id"], u1["id"], event_kind="PARADE",
                              expected_attendance=2000,
                              occupy_start="2026-08-16T10:00:00Z",
                              occupy_end="2026-08-16T14:00:00Z")
    add_segment(app1["id"], u1["id"], sched1["id"], segment_label="Q1 1-3",
                closure_start="2026-08-16T09:00:00Z", closure_end="2026-08-16T15:00:00Z")
    api.submit_for_review(app1["id"], {"expected_venue_version": venue["version"]},
                          make_applicant_headers(u1["id"]))
    venue_v1 = get_venue_version(venue["id"])
    # App1 booked [10:00,14:00]. App2 [15:00,18:00] -> buffered [14:00,19:00]; the
    # candidate's buffered start 14:00 exactly touches App1's *booked* end 14:00. Per
    # PRD §3.4 the other application's *booked* (un-buffered) window is used, and the
    # closed-interval buffer test makes this touch a conflict (PRD §2.7).
    app2 = create_application(venue["id"], u2["id"], event_kind="FESTIVAL",
                              expected_attendance=2000,
                              occupy_start="2026-08-16T15:00:00Z",
                              occupy_end="2026-08-16T18:00:00Z")
    add_segment(app2["id"], u2["id"], sched2["id"], segment_label="Q2 1-3",
                closure_start="2026-08-16T13:30:00Z", closure_end="2026-08-16T19:00:00Z")
    resp = api.submit_for_review(app2["id"], {"expected_venue_version": venue_v1},
                                 make_applicant_headers(u2["id"]))
    validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED, expected_status=409)


# ==========================================================================
# OCC stale venue version (queue B)
# ==========================================================================
def test_occ_stale_venue_version_on_submit(api):
    """PRD §2.10: "When expected_venue_version does not equal the venue's current
    version, the submit is rejected with ERR_STALE_VENUE_VERSION (HTTP 412)". PRD
    §3.4: submission "must carry expected_venue_version, and if it does not equal the
    venue's current version, the submit is rejected with ERR_STALE_VENUE_VERSION".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_venue_version_on_submit
    """
    ctx = setup_draft_with_segment(attendance=500, max_capacity=6000, buffer=60,
                                   event_kind="PARADE",
                                   occupy_start="2026-07-17T10:00:00Z",
                                   occupy_end="2026-07-17T14:00:00Z",
                                   closure_start="2026-07-17T09:00:00Z",
                                   closure_end="2026-07-17T15:00:00Z")
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    stale = ctx["venue_v0"] - 1
    resp = api.submit_for_review(ctx["application"]["id"], {"expected_venue_version": stale}, hdrs)
    validate_error(resp, ApiErrorId.ERR_STALE_VENUE_VERSION, expected_status=412)
    after = validate_success(api.get_application(ctx["application"]["id"], hdrs))
    assert after["status"] == "DRAFT"


# ==========================================================================
# Review lifecycle — revision loop (queue A)
# ==========================================================================
def test_review_revision_loop_cycle(api):
    """PRD §3.5: "Requesting changes moves the review PENDING → CHANGES_REQUESTED ...
    and the parent application automatically transitions UNDER_REVIEW →
    REVISION_REQUESTED so the applicant can revise and resubmit." PRD §3.4: "Every
    DepartmentReview that had been moved to CHANGES_REQUESTED is reset back to
    PENDING so those departments can re-examine the revised plan."

    Design: Difficulty/non_linear_state_machine/review_revision_loop_cycle
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RALLY",
                             occupy_start="2026-06-05T10:00:00Z",
                             occupy_end="2026-06-05T14:00:00Z",
                             closure_start="2026-06-05T09:00:00Z",
                             closure_end="2026-06-05T15:00:00Z")
    app_id = ctx["application"]["id"]
    police = ctx["reviews"]["POLICE"]
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    api.request_changes_review(app_id, police, {"note": "Move stage 200ft"},
                               make_reviewer_headers("POLICE"))
    inter = validate_success(api.get_application(app_id, officer_headers()))
    assert inter["status"] == "REVISION_REQUESTED"
    venue_v1 = get_venue_version(ctx["venue"]["id"])
    resp = api.submit_for_review(app_id, {"expected_venue_version": venue_v1}, hdrs)
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "UNDER_REVIEW"
    police_rev = validate_success(api.get_review(app_id, police, officer_headers()))
    assert police_rev["status"] == "PENDING"  # reset from CHANGES_REQUESTED


def test_request_changes_drops_app_to_revision_requested(api):
    """PRD §3.5: "Requesting changes moves the review PENDING → CHANGES_REQUESTED ...
    the parent application automatically transitions UNDER_REVIEW →
    REVISION_REQUESTED so the applicant can revise and resubmit."

    Design: Difficulty/non_linear_state_machine/review_revision_loop_cycle
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RALLY",
                             occupy_start="2026-06-05T10:00:00Z",
                             occupy_end="2026-06-05T14:00:00Z")
    app_id = ctx["application"]["id"]
    police = ctx["reviews"]["POLICE"]
    resp = api.request_changes_review(app_id, police, {"note": "revise"},
                                      make_reviewer_headers("POLICE"))
    review = validate_success(resp, expected_status=200)
    assert review["status"] == "CHANGES_REQUESTED"
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "REVISION_REQUESTED"


# ==========================================================================
# Review lifecycle — branching fork/join: veto -> DENIED (queue A)
# ==========================================================================
def test_application_branching_fork_join_veto_denies(api):
    """PRD §3.5: "A single veto immediately drives the parent application UNDER_REVIEW
    → DENIED". PRD §3.7: "When any department vetoes, the application moves
    UNDER_REVIEW → DENIED: every PLANNED route segment is moved to RELEASED".

    Design: Difficulty/non_linear_state_machine/application_branching_fork_join
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="PARADE",
                             occupy_start="2026-06-06T10:00:00Z",
                             occupy_end="2026-06-06T14:00:00Z")
    app_id = ctx["application"]["id"]
    segs = validate_success(api.list_route_segments(app_id, officer_headers()))
    seg_id = segs[0]["id"]
    api.veto_review(app_id, ctx["reviews"]["FIRE"], {"note": "Insufficient fire lanes"},
                    make_reviewer_headers("FIRE"))
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "DENIED"
    seg = validate_success(api.get_route_segment(app_id, seg_id, officer_headers()))
    assert seg["status"] == "RELEASED"


def test_application_branching_fork_join_veto_sets_has_veto(api):
    """PRD §3.5: "the has_veto flag is true if any review is VETOED." PRD §3.5: "A
    single veto immediately drives the parent application UNDER_REVIEW → DENIED".
    (Second angle: the VETOED review's own status plus the derived has_veto flag on
    the DENIED-branch target, distinguishing it from the approve/revision branches.)

    Design: Difficulty/non_linear_state_machine/application_branching_fork_join
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="PARADE",
                             occupy_start="2026-08-06T10:00:00Z",
                             occupy_end="2026-08-06T14:00:00Z")
    app_id = ctx["application"]["id"]
    ems = ctx["reviews"]["EMS"]
    review = validate_success(api.veto_review(app_id, ems, {"note": "No staging"},
                                              make_reviewer_headers("EMS")))
    assert review["status"] == "VETOED"
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "DENIED"
    assert app["has_veto"] is True


# ==========================================================================
# Veto requires note (queue B)
# ==========================================================================
def test_veto_without_note_rejected(api):
    """PRD §3.5: "A veto requires a non-empty note giving the reason, and a veto
    submitted without one is rejected with ERR_VETO_REASON_REQUIRED (HTTP 422)."

    Design: Corner/validations/veto_without_note_rejected
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="PARADE",
                             occupy_start="2026-07-07T10:00:00Z",
                             occupy_end="2026-07-07T14:00:00Z")
    app_id = ctx["application"]["id"]
    police = ctx["reviews"]["POLICE"]
    resp = api.veto_review(app_id, police, {}, make_reviewer_headers("POLICE"))
    validate_error(resp, ApiErrorId.ERR_VETO_REASON_REQUIRED, expected_status=422)
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "UNDER_REVIEW"


# ==========================================================================
# Quorum bubble-up: all four APPROVED -> CONDITIONALLY_APPROVED (queue A)
# ==========================================================================
def test_quorum_all_four_approved_conditionally_approved_with_invoice(api):
    """PRD §3.5: "When approval causes all four to be APPROVED (so quorum_met becomes
    true and has_veto remains false), the application automatically transitions
    UNDER_REVIEW → CONDITIONALLY_APPROVED". PRD §3.6: "the system computes the
    staffing cost-recovery estimate and creates or refreshes the application's
    Invoice ... sets balance_due to the sum of fee_component and
    cost_recovery_estimate".

    Design: Difficulty/combinatorial_formula/cost_recovery_round_per_line_then_overhead
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RACE",
                             occupy_start="2026-06-04T10:00:00Z",
                             occupy_end="2026-06-04T14:00:00Z")
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    for dept in ["POLICE", "FIRE", "EMS"]:
        api.approve_review(app_id, reviews[dept], STAFFING[dept], make_reviewer_headers(dept))
    # fourth approval fires quorum
    api.approve_review(app_id, reviews["PUBLIC_WORKS"], STAFFING["PUBLIC_WORKS"],
                       make_reviewer_headers("PUBLIC_WORKS"))
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "CONDITIONALLY_APPROVED"
    invoices = validate_success(api.list_invoices(app_id, officer_headers()))
    inv = invoices[0]
    # lines 1600+720+360+480=3160, *1.15 = 3634.00
    assert inv["cost_recovery_estimate"] == 3634.00
    # balance_due = 875 fee (MEDIUM 3000 + 1 segment) + 3634 estimate
    assert inv["balance_due"] == 4509.00


def test_cost_recovery_round_per_line_then_overhead(api):
    """PRD §3.6: "for each department, a staffing line is planned_personnel multiplied
    by planned_hours multiplied by hourly_rate, rounded to cents. The four rounded
    lines are summed to a subtotal, the subtotal is then multiplied by one plus the
    0.15 overhead rate, and that product is rounded half-up to two decimals to give
    the total. The rounding order is binding: round each line first, then sum, then
    apply overhead, then round the total."

    Design: Difficulty/combinatorial_formula/cost_recovery_round_per_line_then_overhead
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RACE",
                             occupy_start="2026-06-04T10:00:00Z",
                             occupy_end="2026-06-04T14:00:00Z")
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    for dept in ["POLICE", "FIRE", "EMS", "PUBLIC_WORKS"]:
        api.approve_review(app_id, reviews[dept], STAFFING[dept], make_reviewer_headers(dept))
    invoices = validate_success(api.list_invoices(app_id, officer_headers()))
    assert invoices[0]["cost_recovery_estimate"] == 3634.00


# ==========================================================================
# Department mismatch (queue B)
# ==========================================================================
def test_reviewer_wrong_department_denied(api):
    """PRD §3.5: "that the acting reviewer's department matches the review's department
    (else ERR_DEPARTMENT_MISMATCH)". PRD §2.1: "the server compares that department
    against the department of the review being acted upon; a mismatch is rejected
    with ERR_DEPARTMENT_MISMATCH (HTTP 403)."

    Design: Corner/rbac/reviewer_wrong_department_denied
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RALLY",
                             occupy_start="2026-07-12T10:00:00Z",
                             occupy_end="2026-07-12T14:00:00Z")
    app_id = ctx["application"]["id"]
    police = ctx["reviews"]["POLICE"]
    # FIRE reviewer acting on POLICE review
    resp = api.approve_review(app_id, police, STAFFING["POLICE"], make_reviewer_headers("FIRE"))
    validate_error(resp, ApiErrorId.ERR_DEPARTMENT_MISMATCH, expected_status=403)


# ==========================================================================
# Invalid transitions / idempotency (queue B)
# ==========================================================================
def test_approve_review_already_approved_returns_not_pending(api):
    """PRD §3.5: "Every review action requires that the review itself is PENDING (else
    ERR_REVIEW_NOT_PENDING)". PRD §3.5: "Approving a review moves it PENDING →
    APPROVED."

    Design: Corner/state_machines/approve_review_already_approved_returns_not_pending
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="RALLY",
                             occupy_start="2026-06-27T10:00:00Z",
                             occupy_end="2026-06-27T14:00:00Z")
    app_id = ctx["application"]["id"]
    police = ctx["reviews"]["POLICE"]
    api.approve_review(app_id, police, STAFFING["POLICE"], make_reviewer_headers("POLICE"))
    resp = api.approve_review(app_id, police, STAFFING["POLICE"], make_reviewer_headers("POLICE"))
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_PENDING, expected_status=409)


def test_review_approve_requires_app_under_review(api):
    """PRD §3.5: "that the parent application is UNDER_REVIEW (else
    ERR_APPLICATION_NOT_UNDER_REVIEW)". PRD §3.5: "A single veto immediately drives
    the parent application UNDER_REVIEW → DENIED".

    Design: Difficulty/cross_entity_state_dependency/review_approve_requires_app_under_review
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="PARADE",
                             occupy_start="2026-06-15T10:00:00Z",
                             occupy_end="2026-06-15T14:00:00Z")
    app_id = ctx["application"]["id"]
    # FIRE vetoes -> app DENIED; POLICE still PENDING
    api.veto_review(app_id, ctx["reviews"]["FIRE"], {"note": "No hydrant clearance"},
                    make_reviewer_headers("FIRE"))
    resp = api.approve_review(app_id, ctx["reviews"]["POLICE"], STAFFING["POLICE"],
                              make_reviewer_headers("POLICE"))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_UNDER_REVIEW, expected_status=409)
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "DENIED"


def test_request_changes_requires_app_under_review(api):
    """PRD §3.5: "that the parent application is UNDER_REVIEW (else
    ERR_APPLICATION_NOT_UNDER_REVIEW)." PRD §3.5: "A single veto immediately drives
    the parent application UNDER_REVIEW → DENIED". (Second angle: a still-PENDING
    review's request-changes is also gated on the parent being UNDER_REVIEW; once a
    sibling veto flips the app to DENIED it fails the same cross-entity check.)

    Design: Difficulty/cross_entity_state_dependency/review_approve_requires_app_under_review
    """
    ctx = setup_under_review(attendance=3000, max_capacity=6000, buffer=60,
                             event_kind="PARADE",
                             occupy_start="2026-08-15T10:00:00Z",
                             occupy_end="2026-08-15T14:00:00Z")
    app_id = ctx["application"]["id"]
    api.veto_review(app_id, ctx["reviews"]["FIRE"], {"note": "No clearance"},
                    make_reviewer_headers("FIRE"))
    resp = api.request_changes_review(app_id, ctx["reviews"]["EMS"], {"note": "revise"},
                                      make_reviewer_headers("EMS"))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_UNDER_REVIEW, expected_status=409)


def test_submit_from_conditionally_approved_returns_not_draft(api):
    """PRD §3.4: "Submission is permitted from DRAFT and, during the revision loop,
    from REVISION_REQUESTED; attempting it from any other state is rejected with
    ERR_APPLICATION_NOT_DRAFT."

    Design: Corner/state_machines/submit_from_conditionally_approved_returns_not_draft
    """
    from test_helpers import setup_conditionally_approved
    ctx = setup_conditionally_approved(attendance=3000, max_capacity=6000, buffer=60,
                                       event_kind="FESTIVAL",
                                       occupy_start="2026-06-26T10:00:00Z",
                                       occupy_end="2026-06-26T14:00:00Z")
    app_id = ctx["application"]["id"]
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    venue_v_now = get_venue_version(ctx["venue"]["id"])
    resp = api.submit_for_review(app_id, {"expected_venue_version": venue_v_now}, hdrs)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT, expected_status=409)
    app = validate_success(api.get_application(app_id, officer_headers()))
    assert app["status"] == "CONDITIONALLY_APPROVED"
