"""
Temporal overlap of contended resources in the Digital Estate Fiduciary Access
API.

Two intervals in this contract obey opposite conventions, and both are exercised
here: a provider's review window is half-open, so an adjacent submission is
allowed, while a refund claim's period is closed, so touching endpoints collide —
and a denied claim hands its days back.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f, fixtures
from test_helpers.api_errors import ERR_CLAIM_PERIOD_OVERLAP, ERR_REQUEST_WINDOW_OVERLAP
from test_helpers.assertions import assert_fields, assert_not_null_fields
from test_helpers.constants import (
    CLAIM_ACTION_DENY,
    CLAIM_ACTION_START_REVIEW,
    CLAIM_DENIED,
    CLAIM_FILED,
    REQUEST_DRAFT,
    REQUEST_SUBMITTED,
    REQ_ACTION_SUBMIT,
)
from test_helpers.test_users import make_platform_compliance_headers


def _instant(value: str) -> datetime:
    """Read an ISO 8601 UTC instant, tolerating any fractional-second width."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _two_packages_contending_for_one_window(api):
    """Package A holds [2026-08-01, 2026-08-15); package B waits in DRAFT."""
    fixtures.set_clock(api)
    platform = fixtures.register_platform(api)
    ctx = fixtures.authorized_estate(api, "PR-2737-U")
    request_a = fixtures.draft_request(api, ctx, platform["id"], platform["form_code"])
    submitted_a = fixtures.submit_request(api, ctx, request_a["id"])
    assert _instant(submitted_a["review_window_start"]) == _instant("2026-08-01T00:00:00Z"), (
        f"Package A should open at the clock, got {submitted_a['review_window_start']!r}"
    )
    assert _instant(submitted_a["review_window_end"]) == _instant("2026-08-15T00:00:00Z"), (
        f"Package A should run 14 days, got {submitted_a['review_window_end']!r}"
    )
    request_b = fixtures.draft_request(api, ctx, platform["id"], platform["form_code"])
    return platform, ctx, request_a, request_b


def test_a_submission_overlapping_a_live_review_window_is_refused(api):
    """
    Package B addresses the same estate, provider and request type as the live
    package A. Submitted one day before A's window ends, its prospective window
    would overlap A's by a day, so the submission is refused and B stays in DRAFT
    while A keeps the slot it holds.

    PRD: "A submission is refused with `ERR_REQUEST_WINDOW_OVERLAP` when its prospective window would overlap the window of another platform request that shares the same estate, the same `platform_id` and the same `request_type` and is currently in `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED`."

    Design: Difficulty/resource_temporal_overlap/review_window_is_half_open_so_an_adjacent_submission_is_allowed
    """
    platform, ctx, request_a, request_b = _two_packages_contending_for_one_window(api)
    fixtures.set_clock(api, "2026-08-14T00:00:00Z")

    response = api.transition_platform_request(
        request_b["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fiduciary_headers
    )
    validate_error(response, ERR_REQUEST_WINDOW_OVERLAP)

    blocked = fixtures.read_request(api, ctx, request_b["id"])
    assert_fields(blocked, status=REQUEST_DRAFT)
    assert blocked["review_window_start"] is None, "A refused submission opens no window"
    assert blocked["review_window_end"] is None, "A refused submission opens no window"

    holder = fixtures.read_request(api, ctx, request_a["id"])
    assert_fields(holder, status=REQUEST_SUBMITTED)
    assert _instant(holder["review_window_end"]) == _instant("2026-08-15T00:00:00Z"), (
        f"Package A's window must be untouched, got {holder['review_window_end']!r}"
    )


def test_a_submission_beginning_at_the_excluded_end_is_adjacent_and_allowed(api):
    """
    Submitted at exactly the instant package A's window ends, package B is
    adjacent rather than overlapping, because the end instant is outside the
    window. The submission is accepted and opens its own fourteen-day window.

    PRD: "Because the interval is half-open, a new window beginning exactly at an existing window's `review_window_end` is adjacent rather than overlapping and is allowed."

    Design: Difficulty/resource_temporal_overlap/review_window_is_half_open_so_an_adjacent_submission_is_allowed
    """
    platform, ctx, request_a, request_b = _two_packages_contending_for_one_window(api)
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")

    response = api.transition_platform_request(
        request_b["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fiduciary_headers
    )
    submitted_b = validate_success(response, 200)
    assert_fields(submitted_b, status=REQUEST_SUBMITTED)
    assert _instant(submitted_b["review_window_start"]) == _instant("2026-08-15T00:00:00Z"), (
        f"Package B should open at the clock, got {submitted_b['review_window_start']!r}"
    )
    assert _instant(submitted_b["review_window_end"]) == _instant("2026-08-29T00:00:00Z"), (
        f"Package B should run 14 days, got {submitted_b['review_window_end']!r}"
    )

    holder = fixtures.read_request(api, ctx, request_a["id"])
    assert_fields(holder, status=REQUEST_SUBMITTED)
    assert _instant(holder["review_window_start"]) == _instant("2026-08-01T00:00:00Z"), (
        f"Package A's window must be untouched, got {holder['review_window_start']!r}"
    )
    assert _instant(holder["review_window_end"]) == _instant("2026-08-15T00:00:00Z"), (
        f"Package A's window must be untouched, got {holder['review_window_end']!r}"
    )


def _term_with_one_live_claim(api):
    """A cancelled annual term carrying one FILED claim over 2026-04-01..2026-06-30."""
    fixtures.set_clock(api)
    platform = fixtures.register_subscription_platform(api)
    ctx = fixtures.authorized_estate(api, "PR-2737-V")
    bundle = fixtures.subscription_with_confirmed_order(api, ctx, platform)
    claim = fixtures.file_refund_claim(
        api, ctx, bundle["order"]["id"], "2026-04-01", "2026-06-30", pursuit_cost_cents=500
    )
    assert_fields(claim, claimed_days=91, claimed_cents=2992, status=CLAIM_FILED)
    return platform, ctx, bundle, claim


def test_a_claim_touching_a_live_claim_endpoint_is_an_overlap(api):
    """
    A live claim runs to 2026-06-30 inclusive. A new claim that starts on that
    very day shares one day with it, and because claimed periods are closed on
    both ends that shared day is a collision. The term's claimed-day total is
    left at the 91 days the live claim already holds.

    PRD: "Because these intervals are closed, **touching endpoints are an overlap**: a live claim ending on a given day blocks a new claim starting on that same day, and the collision is reported as `ERR_CLAIM_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/refund_claim_intervals_are_closed_and_a_denial_releases_the_interval
    """
    platform, ctx, bundle, claim = _term_with_one_live_claim(api)

    response = api.create_refund_claim(
        bundle["order"]["id"],
        f.refund_claim_payload("2026-06-30", "2026-09-30", pursuit_cost_cents=0),
        ctx.fiduciary_headers,
    )
    validate_error(response, ERR_CLAIM_PERIOD_OVERLAP)

    term = fixtures.read_term(api, ctx, bundle["term"]["id"])
    assert_fields(term, claimed_days_total=91)


def test_a_claim_starting_the_day_after_a_live_claim_is_accepted(api):
    """
    Moving the same three-month stretch one day later takes it clear of the live
    claim, so it is accepted. Its closed interval counts 92 days, its pro-rata
    entitlement follows from the term's annual fee, and the term's claimed-day
    total becomes the sum of both live claims.

    PRD: "The claimed period is also a **closed** interval, so `claimed_days` is the day count from `claimed_period_start` to `claimed_period_end` plus one."

    Design: Difficulty/resource_temporal_overlap/refund_claim_intervals_are_closed_and_a_denial_releases_the_interval
    """
    platform, ctx, bundle, claim = _term_with_one_live_claim(api)

    response = api.create_refund_claim(
        bundle["order"]["id"],
        f.refund_claim_payload("2026-07-01", "2026-09-30", pursuit_cost_cents=0),
        ctx.fiduciary_headers,
    )
    accepted = validate_success(response, 201)
    assert_fields(accepted, claimed_days=92, claimed_cents=3024, status=CLAIM_FILED)

    term = fixtures.read_term(api, ctx, bundle["term"]["id"])
    assert_fields(term, claimed_days_total=183)


def test_a_denied_claim_releases_its_interval_for_a_fresh_claim(api):
    """
    With both claims live the term holds 183 claimed days. Denying the first one
    hands its 91 days back, dropping the total to the 92 days the surviving claim
    holds, and the released stretch may be claimed all over again on the same
    terms.

    PRD: "Denying advances the claim to `DENIED`, stores the `denial_reason` and releases the claimed interval, so the term's `claimed_days_total` is recomputed without this claim and the same days may be claimed again."

    Design: Difficulty/resource_temporal_overlap/refund_claim_intervals_are_closed_and_a_denial_releases_the_interval
    """
    platform, ctx, bundle, claim = _term_with_one_live_claim(api)
    compliance = make_platform_compliance_headers(platform["id"])
    fixtures.file_refund_claim(api, ctx, bundle["order"]["id"], "2026-07-01", "2026-09-30")
    assert_fields(fixtures.read_term(api, ctx, bundle["term"]["id"]), claimed_days_total=183)

    validate_success(
        api.transition_refund_claim(
            claim["id"], f.claim_transition_payload(CLAIM_ACTION_START_REVIEW), compliance
        ),
        200,
    )
    denied = validate_success(
        api.transition_refund_claim(
            claim["id"],
            f.claim_transition_payload(
                CLAIM_ACTION_DENY, reason="outside provider goodwill window"
            ),
            compliance,
        ),
        200,
    )
    assert_fields(denied, status=CLAIM_DENIED)
    assert_not_null_fields(denied, "denial_reason")
    assert_fields(fixtures.read_term(api, ctx, bundle["term"]["id"]), claimed_days_total=92)

    refiled = validate_success(
        api.create_refund_claim(
            bundle["order"]["id"],
            f.refund_claim_payload("2026-04-01", "2026-06-30", pursuit_cost_cents=0),
            ctx.fiduciary_headers,
        ),
        201,
    )
    assert_fields(refiled, claimed_days=91, claimed_cents=2992, status=CLAIM_FILED)
    assert_fields(fixtures.read_term(api, ctx, bundle["term"]["id"]), claimed_days_total=183)
