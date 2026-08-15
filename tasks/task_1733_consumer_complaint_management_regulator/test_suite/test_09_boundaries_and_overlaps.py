"""Boundary-precision and interval-overlap tests (PRD §3.2, §3.7, §3.8, §3.10)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, headers_for,
    assert_instant_equals, assert_trend_snapshot, assert_quality_review,
    setup_reference_data, setup_complaint, intake_complaint,
    intake_portal_complaint, claim_review, complete_review,
    create_and_complete_rca,
    set_clock, get_product, get_review,
    list_complaint_referrals, list_product_snapshots,
)

MANAGER = TEST_USERS["complaint_manager_headers"]
HANDLER = TEST_USERS["case_handler_headers"]


def test_referral_deadline_inclusive_boundary_on_time_vs_late(api):
    """PRD §3.2: "The timeliness comparison used later is inclusive: a response
    submitted exactly at `response_due_at` counts as on time."
    PRD §3.8: "Submission stamps `submitted_at` from the logical clock, moves the
    referral to `RESPONSE_SUBMITTED`, derives `timeliness` as `ON_TIME` when
    `submitted_at` is at or before `response_due_at` and `LATE` otherwise,
    recomputes the parent complaint's `timeliness_score`, appends
    `REFERRAL_RESPONDED` on the complaint, and bumps the referral's `version`."

    Design: Difficulty/boundary_precision_check/referral_deadline_inclusive_boundary_on_time_vs_late
    """
    refs = setup_reference_data("BND-PROD", "CFPB_PORTAL", "BND.CAT", portal=True)
    ca = intake_complaint("BND-PROD", "CFPB_PORTAL", "BND.CAT",
                          complainant_ref="CUST-801", narrative="boundary A",
                          portal_ref="CFPB-BND-A")
    cb = intake_complaint("BND-PROD", "CFPB_PORTAL", "BND.CAT",
                          complainant_ref="CUST-802", narrative="boundary B",
                          portal_ref="CFPB-BND-B")
    ref_a = list_complaint_referrals(ca["id"])[0]
    ref_b = list_complaint_referrals(cb["id"])[0]

    set_clock("2026-08-16T00:00:00Z")  # exactly response_due_at
    submitted_a = validate_success(api.submit_referral_response(
        ref_a["id"], {"response_text": "Exactly at deadline."}, HANDLER,
    ))
    set_clock("2026-08-16T00:00:01Z")  # one second past
    submitted_b = validate_success(api.submit_referral_response(
        ref_b["id"], {"response_text": "One second past deadline."}, HANDLER,
    ))

    assert submitted_a["timeliness"] == "ON_TIME", (
        "the deadline instant itself is on time (inclusive comparison)"
    )
    assert_instant_equals(submitted_a["submitted_at"], "2026-08-16T00:00:00Z",
                          "submitted_at A")
    assert submitted_b["timeliness"] == "LATE"
    assert_instant_equals(submitted_b["submitted_at"], "2026-08-16T00:00:01Z",
                          "submitted_at B")


def test_referral_deadline_one_second_before_is_on_time(api):
    """PRD §3.2: "The timeliness comparison used later is inclusive: a response
    submitted exactly at `response_due_at` counts as on time."
    PRD §3.8: "Submission stamps `submitted_at` from the logical clock, moves the
    referral to `RESPONSE_SUBMITTED`, derives `timeliness` as `ON_TIME` when
    `submitted_at` is at or before `response_due_at` and `LATE` otherwise,
    recomputes the parent complaint's `timeliness_score`, appends
    `REFERRAL_RESPONDED` on the complaint, and bumps the referral's `version`."

    Design: Difficulty/boundary_precision_check/referral_deadline_inclusive_boundary_on_time_vs_late
    """
    complaint, referral = intake_portal_complaint(
        "BND-EARLY", "CFPB_PORTAL", "BND.EARLY", narrative="one second early",
        portal_ref="CFPB-BND-C",
    )
    set_clock("2026-08-15T23:59:59Z")  # one second before the 2026-08-16 deadline
    submitted = validate_success(api.submit_referral_response(
        referral["id"], {"response_text": "Just inside the window."}, HANDLER,
    ))
    assert submitted["timeliness"] == "ON_TIME"
    assert_instant_equals(submitted["response_due_at"], "2026-08-16T00:00:00Z",
                          "response_due_at")


def test_empty_window_never_warns_even_with_high_open_count(api):
    """PRD §3.10: "Then `substantiation_rate_bps` is derived in basis points: 0
    when `complaint_count` is 0, otherwise the substantiated count times 10000
    divided by the complaint count, floored to an integer."
    PRD §3.10: "An empty window never warns, regardless of the live open count."

    Design: Difficulty/boundary_precision_check/empty_window_never_warns_and_zero_restitution_rejected
    """
    refs = setup_reference_data("EMPTY-PROD", "WEB", "GEN.OTHER")
    pid = refs["product"]["id"]
    for i in range(10):
        intake_complaint("EMPTY-PROD", "WEB", "GEN.OTHER",
                         complainant_ref=f"CUST-9{i + 1:02d}", narrative=f"x{i + 1}")
    assert get_product(pid)["open_complaint_count"] == 10

    snapshot = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-09-01T00:00:00Z",
                  "period_end_at": "2026-09-30T23:59:59Z"}, MANAGER,
        ),
        expected_status=201,
    )
    assert_trend_snapshot(snapshot)
    assert snapshot["complaint_count"] == 0
    assert snapshot["substantiation_rate_bps"] == 0
    assert snapshot["early_warning"] is False, (
        "the complaint_count >= 3 guard dominates: an empty window never warns"
    )
    assert get_product(pid)["early_warning_active"] is False


def test_window_below_min_count_never_warns_even_at_full_rate(api):
    """PRD §3.10: "Finally `early_warning` is true when `complaint_count` is at
    least 3 **and** at least one of two conditions holds —
    `substantiation_rate_bps` is at least 5000, or the live open count is at
    least 10."
    PRD §3.10: "An empty window never warns, regardless of the live open count."

    Design: Difficulty/boundary_precision_check/empty_window_never_warns_and_zero_restitution_rejected
    """
    refs = setup_reference_data("MIN-PROD", "WEB", "GEN.MIN")
    pid = refs["product"]["id"]
    for i in range(2):
        complaint = intake_complaint("MIN-PROD", "WEB", "GEN.MIN",
                                     complainant_ref=f"CUST-M{i}", narrative=f"m{i}")
        create_and_complete_rca(complaint["id"], "SUBSTANTIATED", "MIN-PROD")

    snapshot = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-08-01T00:00:00Z",
                  "period_end_at": "2026-08-31T23:59:59Z"}, MANAGER,
        ),
        expected_status=201,
    )
    assert_trend_snapshot(snapshot)
    assert snapshot["complaint_count"] == 2
    assert snapshot["substantiated_count"] == 2
    assert snapshot["substantiation_rate_bps"] == 10000
    assert snapshot["early_warning"] is False, (
        "complaint_count 2 is below the minimum of 3, so even a full rate must "
        "not warn"
    )


def test_qa_review_window_half_open_touching_endpoints_allowed(api):
    """PRD §3.7: "One reviewer may not hold two `OPEN` reviews whose half-open
    intervals intersect: touching endpoints — one window's end exactly equal to
    the other's start — do not overlap, but any genuine intersection is refused
    with `ERR_REVIEW_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/qa_review_window_half_open_touching_endpoints_allowed
    """
    refs = setup_reference_data("HO-PROD", "WEB", "GEN.SERVICE")
    ca = intake_complaint("HO-PROD", "WEB", "GEN.SERVICE",
                          complainant_ref="CUST-1201", narrative="A")
    cb = intake_complaint("HO-PROD", "WEB", "GEN.SERVICE",
                          complainant_ref="CUST-1202", narrative="B")
    reviewer = headers_for("QAReviewer", "user_qa_7")
    first = validate_success(
        api.claim_quality_review(ca["id"], {"window_start_at": "2026-08-01T00:00:00Z",
                                            "window_end_at": "2026-08-10T00:00:00Z"},
                                 reviewer),
        expected_status=201,
    )
    assert first["status"] == "OPEN"

    # Adjacent claim: the shared endpoint 2026-08-10 is NOT an overlap.
    adjacent = validate_success(
        api.claim_quality_review(cb["id"], {"window_start_at": "2026-08-10T00:00:00Z",
                                            "window_end_at": "2026-08-20T00:00:00Z"},
                                 reviewer),
        expected_status=201,
    )
    assert_quality_review(adjacent)
    assert adjacent["status"] == "OPEN"

    # Genuine interior intersection IS refused.
    overlapping = api.claim_quality_review(
        cb["id"], {"window_start_at": "2026-08-05T00:00:00Z",
                   "window_end_at": "2026-08-12T00:00:00Z"}, reviewer,
    )
    validate_error(overlapping, ApiErrorId.ERR_REVIEW_WINDOW_OVERLAP)


def test_qa_review_window_frees_after_completion(api):
    """PRD §3.7: "One reviewer may not hold two `OPEN` reviews whose half-open
    intervals intersect: touching endpoints — one window's end exactly equal to
    the other's start — do not overlap, but any genuine intersection is refused
    with `ERR_REVIEW_WINDOW_OVERLAP`."
    PRD §3.7: "Completing a review is restricted to the owning reviewer: the
    acting `X-User-ID` must equal the review's `reviewer_user_id` (otherwise
    `ERR_REVIEW_NOT_OWNED`), the review must be `OPEN` (otherwise
    `ERR_INVALID_STATE_TRANSITION`), the supplied `outcome` must be `PASS` or
    `FAIL` (otherwise `ERR_INVALID_REQUEST`), and segregation of duties bars the
    reviewer from completing a review on a complaint whose `owner_user_id` equals
    their own identifier (`ERR_SOD_SELF_REVIEW`)."

    Design: Difficulty/resource_temporal_overlap/qa_review_window_half_open_touching_endpoints_allowed
    """
    refs = setup_reference_data("HO-FREE", "WEB", "GEN.FREE")
    ca = intake_complaint("HO-FREE", "WEB", "GEN.FREE",
                          complainant_ref="CUST-F1", narrative="A")
    cb = intake_complaint("HO-FREE", "WEB", "GEN.FREE",
                          complainant_ref="CUST-F2", narrative="B")
    reviewer_id = "user_qa_free"
    first = claim_review(ca["id"], reviewer_id, "2026-08-01T00:00:00Z",
                         "2026-08-10T00:00:00Z")
    complete_review(first["id"], "PASS", reviewer_id)
    assert get_review(first["id"])["status"] == "COMPLETED"

    # The completed review is no longer OPEN, so an intersecting window succeeds.
    overlapping = validate_success(
        api.claim_quality_review(
            cb["id"], {"window_start_at": "2026-08-05T00:00:00Z",
                       "window_end_at": "2026-08-12T00:00:00Z"},
            headers_for("QAReviewer", reviewer_id),
        ),
        expected_status=201,
    )
    assert overlapping["status"] == "OPEN"


def test_trend_snapshot_closed_interval_shared_boundary_is_overlap(api):
    """PRD §3.10: "Windows for the same product must not overlap under
    closed-interval semantics: a new window is refused with
    `ERR_SNAPSHOT_WINDOW_OVERLAP` whenever its start falls at or before an
    existing snapshot's end while that snapshot's start falls at or before the
    new window's end — two windows sharing exactly one boundary date count as
    overlapping."

    Design: Difficulty/resource_temporal_overlap/trend_snapshot_closed_interval_shared_boundary_is_overlap
    """
    refs = setup_reference_data("CI-PROD", "WEB", "GEN.CI")
    pid = refs["product"]["id"]
    first = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-07-01T00:00:00Z",
                  "period_end_at": "2026-08-01T00:00:00Z"}, MANAGER,
        ),
        expected_status=201,
    )

    # Shared boundary date 2026-08-01 counts as overlap under closed semantics.
    touching = api.create_trend_snapshot(
        pid, {"period_start_at": "2026-08-01T00:00:00Z",
              "period_end_at": "2026-08-31T23:59:59Z"}, MANAGER,
    )
    validate_error(touching, ApiErrorId.ERR_SNAPSHOT_WINDOW_OVERLAP)
    assert len(list_product_snapshots(pid)) == 1

    # A window strictly after the closed end is disjoint and accepted.
    disjoint = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-08-02T00:00:00Z",
                  "period_end_at": "2026-08-31T23:59:59Z"}, MANAGER,
        ),
        expected_status=201,
    )
    assert_trend_snapshot(disjoint)
    assert len(list_product_snapshots(pid)) == 2


def test_trend_snapshot_reverse_direction_shared_boundary_is_overlap(api):
    """PRD §3.10: "Windows for the same product must not overlap under
    closed-interval semantics: a new window is refused with
    `ERR_SNAPSHOT_WINDOW_OVERLAP` whenever its start falls at or before an
    existing snapshot's end while that snapshot's start falls at or before the
    new window's end — two windows sharing exactly one boundary date count as
    overlapping."

    Design: Difficulty/resource_temporal_overlap/trend_snapshot_closed_interval_shared_boundary_is_overlap
    """
    refs = setup_reference_data("CI-REV", "WEB", "GEN.CIR")
    pid = refs["product"]["id"]
    validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-08-01T00:00:00Z",
                  "period_end_at": "2026-08-31T23:59:59Z"}, MANAGER,
        ),
        expected_status=201,
    )

    # A new window ending exactly on the existing window's start also overlaps.
    touching = api.create_trend_snapshot(
        pid, {"period_start_at": "2026-07-01T00:00:00Z",
              "period_end_at": "2026-08-01T00:00:00Z"}, MANAGER,
    )
    validate_error(touching, ApiErrorId.ERR_SNAPSHOT_WINDOW_OVERLAP)
    assert len(list_product_snapshots(pid)) == 1

    # A window ending strictly before the existing start is disjoint.
    disjoint = validate_success(
        api.create_trend_snapshot(
            pid, {"period_start_at": "2026-07-01T00:00:00Z",
                  "period_end_at": "2026-07-31T00:00:00Z"}, MANAGER,
        ),
        expected_status=201,
    )
    assert_trend_snapshot(disjoint)
    assert len(list_product_snapshots(pid)) == 2
