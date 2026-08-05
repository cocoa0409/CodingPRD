"""Submission lead time, venue double-booking, optimistic concurrency, payments.

Difficulty: boundary_precision_check (lead time), resource_temporal_overlap (venue).
Corner: occ_payment_stale_version, occ_decide_stale_version, invalid_payment_amount_rejected.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_payment_payload, decide_payload, fixtures,
)
from test_helpers.test_users import TEST_USERS, make_reviewer_headers

APPLICANT = TEST_USERS["applicant_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_submit_at_exact_lead_time_boundary_succeeds(api):
    """PRD §3.3: "The current logical clock must be at or before the event start minus the
    minimum submission lead time of 14 days; a submission any later than 14 days before
    `event_start` is rejected with `ERR_SUBMISSION_TOO_LATE`."

    event_start 2026-06-15T18:00Z minus 14 days == 2026-06-01T18:00Z (inclusive).

    Design: Difficulty/boundary_precision_check/submission_lead_time_exact_boundary
    """
    ctx = fixtures.create_draft_with_documents(api)
    fixtures.set_clock(api, "2026-06-01T18:00:00Z")
    data = validate_success(api.submit_application(ctx["application"]["id"], APPLICANT))
    assert data["status"] == "SUBMITTED"


def test_submit_one_second_past_lead_time_boundary_rejected(api):
    """PRD §3.3: "The current logical clock must be at or before the event start minus the
    minimum submission lead time of 14 days; a submission any later than 14 days before
    `event_start` is rejected with `ERR_SUBMISSION_TOO_LATE`."

    One second past the 14-day boundary (2026-06-01T18:00:01Z) is too late.

    Design: Difficulty/boundary_precision_check/submission_lead_time_exact_boundary
    """
    ctx = fixtures.create_draft_with_documents(api)
    fixtures.set_clock(api, "2026-06-01T18:00:01Z")
    resp = api.submit_application(ctx["application"]["id"], APPLICANT)
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_TOO_LATE)


def test_overlapping_event_on_same_venue_rejected(api):
    """PRD §3.3: "No other application for the same `venue_id` that is currently in
    `SUBMITTED`, `UNDER_REVIEW`, `REVISIONS_REQUESTED`, `APPROVED`, or `PERMIT_ISSUED`
    may have an event interval that overlaps this one, where each interval is treated as
    half-open from `event_start` up to but not including `event_end`. An overlap is
    rejected with `ERR_VENUE_DOUBLE_BOOKED`."

    A1 [18:00,23:00) SUBMITTED; A2 [22:00,23:30) overlaps.

    Design: Difficulty/resource_temporal_overlap/venue_double_booking_overlap
    """
    venue = fixtures.create_venue(api)
    fixtures.create_submitted_application(api, venue_id=venue["id"])
    ctx2 = fixtures.create_draft_with_documents(
        api, venue_id=venue["id"],
        app_overrides={"event_start": "2026-06-15T22:00:00Z",
                       "event_end": "2026-06-15T23:30:00Z", "expected_attendance": 100})
    resp = api.submit_application(ctx2["application"]["id"], APPLICANT)
    validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED)


def test_adjacent_event_on_same_venue_allowed(api):
    """PRD §3.3: "No other application for the same `venue_id` ... may have an event
    interval that overlaps this one, where each interval is treated as half-open from
    `event_start` up to but not including `event_end`."

    A1 [18:00,23:00) and A2 [23:00,23:30) touch at the boundary; half-open intervals do
    not overlap, so A2 submits successfully.

    Design: Difficulty/resource_temporal_overlap/venue_double_booking_overlap
    """
    venue = fixtures.create_venue(api)
    fixtures.create_submitted_application(api, venue_id=venue["id"])
    ctx2 = fixtures.create_draft_with_documents(
        api, venue_id=venue["id"],
        app_overrides={"event_start": "2026-06-15T23:00:00Z",
                       "event_end": "2026-06-15T23:30:00Z", "expected_attendance": 100})
    data = validate_success(api.submit_application(ctx2["application"]["id"], APPLICANT))
    assert data["status"] == "SUBMITTED"


def test_second_payment_with_stale_version_rejected(api):
    """PRD §2.7: "When an applicant records a payment, the payment request must carry
    `expected_application_version` equal to the application's current `version`. Because a
    prior payment or a fee reconciliation legitimately changes `balance_due_cents` and
    advances `version`, a payment carrying a pre-advance version is stale and is rejected
    with `ERR_STALE_VERSION`."

    Design: Corner/cross-cutting complexity layers/occ_payment_stale_version
    """
    ctx = fixtures.create_submitted_application(api)
    app_id = ctx["application"]["id"]
    stale_version = fixtures.get_app_version(api, app_id)
    validate_success(api.create_payment(
        app_id, create_payment_payload(100, stale_version), APPLICANT), expected_status=201)
    resp = api.create_payment(app_id, create_payment_payload(100, stale_version), APPLICANT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_second_decision_with_stale_version_rejected(api):
    """PRD §2.7: "When an agency reviewer records a decision, the decision request must
    carry `expected_application_version` equal to the target application's current
    `version`. Because a different agency recording its own still-pending review
    legitimately advances the shared application (its approved or rejected counts, and
    therefore its `version`), a decision that carries a pre-advance version is stale and
    is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross-cutting complexity layers/occ_decide_stale_version
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    stale_version = fixtures.get_app_version(api, app_id)
    validate_success(api.decide_agency_review(
        reviews[0]["id"], decide_payload("APPROVE", stale_version),
        make_reviewer_headers("rev-1")))
    resp = api.decide_agency_review(
        reviews[1]["id"], decide_payload("APPROVE", stale_version),
        make_reviewer_headers("rev-2"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_zero_amount_payment_rejected(api):
    """PRD §3.7: "The amount must be strictly greater than zero, else
    `ERR_INVALID_PAYMENT_AMOUNT`."

    Design: Corner/validations/invalid_payment_amount_rejected
    """
    ctx = fixtures.create_submitted_application(api)
    app_id = ctx["application"]["id"]
    version = fixtures.get_app_version(api, app_id)
    resp = api.create_payment(app_id, create_payment_payload(0, version), APPLICANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_PAYMENT_AMOUNT)
