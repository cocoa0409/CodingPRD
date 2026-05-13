"""Ratings, composite computation, low-rating investigation, and tier
recomputation (PRD §3.9).
"""

import pytest

from test_helpers import (
    OPERATOR_HEADERS,
    drive_order_to,
    expected_composite_score,
    expected_new_rating_score,
    expected_tier,
    get_personnel,
    make_customer_headers,
    rate_completed_order,
    rating_payload,
    setup_basic_scenario,
    setup_order_in_state,
    setup_personnel_with_rating_history,
    validate_error,
    validate_success,
)


# =============================================================================
# Rating preconditions
# =============================================================================


def test_rate_before_customer_accept_rejected(api):
    """PRD §3.9: "A rating against an order whose status is not
    ACCEPTED_BY_CUSTOMER is rejected with ERR_RATING_NOT_ALLOWED."

    Claim: rate an order in COMPLETED state → ERR_RATING_NOT_ALLOWED 422.
    """
    ctx, order = setup_order_in_state("COMPLETED")
    res = api.rate_order(
        order["id"],
        rating_payload(),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(res, "ERR_RATING_NOT_ALLOWED", expected_status=422)


def test_rate_out_of_range_score_rejected(api):
    """PRD §3.9: "A dimension score outside the 1-to-5 range is rejected
    with ERR_RATING_OUT_OF_RANGE."

    Claim: quality_score=6 → ERR_RATING_OUT_OF_RANGE 422.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    res = api.rate_order(
        order["id"],
        rating_payload(quality_score=6),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(res, "ERR_RATING_OUT_OF_RANGE", expected_status=422)


def test_rate_zero_score_rejected(api):
    """PRD §3.9: "A dimension score outside the 1-to-5 range is rejected
    with ERR_RATING_OUT_OF_RANGE."

    Claim: attitude_score=0 → ERR_RATING_OUT_OF_RANGE 422.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    res = api.rate_order(
        order["id"],
        rating_payload(attitude_score=0),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(res, "ERR_RATING_OUT_OF_RANGE", expected_status=422)


def test_double_rating_rejected(api):
    """PRD §3.9: "Only one rating exists per order: a second attempt is
    rejected with ERR_RATING_ALREADY_EXISTS."

    Claim: a second rate call on the same order → ERR_RATING_ALREADY_EXISTS 409.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    api.rate_order(
        order["id"], rating_payload(), make_customer_headers(ctx["customer"]["id"])
    )
    res = api.rate_order(
        order["id"], rating_payload(), make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(res, "ERR_RATING_ALREADY_EXISTS", expected_status=409)


# =============================================================================
# Composite calculation
# =============================================================================


def test_composite_score_weighted_sum(api):
    """PRD §3.9: "a composite score is computed as the weighted sum of the
    three dimensions: 0.5 times quality_score, plus 0.3 times
    punctuality_score, plus 0.2 times attitude_score. The result is rounded
    half-up to four decimal places."

    Claim: quality=5, punctuality=3, attitude=1 → composite_score=3.6.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    res = api.rate_order(
        order["id"],
        rating_payload(quality_score=5, punctuality_score=3, attitude_score=1),
        make_customer_headers(ctx["customer"]["id"]),
    )
    body = validate_success(res, expected_status=201)
    expected = expected_composite_score(5, 3, 1)
    assert body["composite_score"] == expected
    # 0.5*5 + 0.3*3 + 0.2*1 = 2.5 + 0.9 + 0.2 = 3.6
    assert body["composite_score"] == 3.6


# =============================================================================
# Low-rating investigation
# =============================================================================


def test_low_composite_opens_investigation(api):
    """PRD §3.9: "When the composite is strictly less than 3.0, the rating
    row's investigation_status is set to OPEN automatically; otherwise it is
    left at NONE."

    Claim: composite < 3.0 → investigation_status == "OPEN".
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    # composite = 0.5*2 + 0.3*2 + 0.2*2 = 2.0 (strictly less than 3.0)
    res = api.rate_order(
        order["id"],
        rating_payload(quality_score=2, punctuality_score=2, attitude_score=2),
        make_customer_headers(ctx["customer"]["id"]),
    )
    body = validate_success(res, expected_status=201)
    assert body["composite_score"] == 2.0
    assert body["investigation_status"] == "OPEN"


def test_composite_at_3_0_leaves_investigation_none(api):
    """PRD §3.9: "When the composite is strictly less than 3.0, the rating
    row's investigation_status is set to OPEN automatically; otherwise it is
    left at NONE."

    Claim: composite exactly 3.0 → investigation_status == "NONE" (strict <).
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    # 0.5*3 + 0.3*3 + 0.2*3 = 3.0
    res = api.rate_order(
        order["id"],
        rating_payload(quality_score=3, punctuality_score=3, attitude_score=3),
        make_customer_headers(ctx["customer"]["id"]),
    )
    body = validate_success(res, expected_status=201)
    assert body["composite_score"] == 3.0
    assert body["investigation_status"] == "NONE"


def test_close_investigation_moves_to_closed(api):
    """PRD §3.9: "An open investigation is closed by a PlatformOperator
    through the close-investigation endpoint, which moves investigation_status
    from OPEN to CLOSED without further preconditions or side effects."

    Claim: close-investigation on an OPEN rating moves it to CLOSED.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    res_rate = api.rate_order(
        order["id"],
        rating_payload(quality_score=2, punctuality_score=2, attitude_score=2),
        make_customer_headers(ctx["customer"]["id"]),
    )
    rating = res_rate.json()["data"]
    assert rating["investigation_status"] == "OPEN"
    res = api.close_investigation(rating["id"], OPERATOR_HEADERS)
    body = validate_success(res)
    assert body["investigation_status"] == "CLOSED"


# =============================================================================
# Tier recomputation (PRD §3.9)
# =============================================================================


def test_tier_bronze_when_rating_count_below_5(api):
    """PRD §3.9: "when rating_count is fewer than 5 the tier is BRONZE because
    the sample is insufficient."

    Claim: after 4 ratings, personnel.tier == BRONZE regardless of score.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    rate_completed_order(ctx, order, 5, 5, 5)
    # Refresh personnel from server
    assignee_id = order["assigned_personnel_id"]
    p = get_personnel(assignee_id)
    assert p["rating_count"] == 1
    assert p["tier"] == "BRONZE"


def test_tier_promotes_to_gold_at_4_5_boundary(api):
    """PRD §3.9: "the tier is PLATINUM when rating_score is at least 4.8,
    GOLD when at least 4.5 but below 4.8, SILVER when at least 4.0 but below
    4.5, and BRONZE otherwise. The floor comparisons are inclusive — a score
    exactly at 4.8 places the personnel at PLATINUM, not at GOLD."

    Claim: rating_score=4.5 with rating_count>=5 → tier=GOLD (inclusive floor).
    """
    # Build personnel with 4 ratings each composite 4.5 → score=4.5, count=4.
    # Share a unique pref_language marker so the test's 5th order also routes
    # specifically to this personnel.
    from test_helpers import (
        _unique_iso_language,
        create_customer,
        create_service_item,
        drive_order_to,
        iso_in,
    )
    marker = _unique_iso_language()
    p, _ = setup_personnel_with_rating_history(
        target_count=4, target_score=4.5, pref_language=marker
    )
    assert p["rating_count"] == 4
    assert p["rating_score"] == 4.5
    # Still BRONZE because count < 5.
    assert p["tier"] == "BRONZE"
    # Now add a fifth rating with composite 4.5 → running average stays 4.5,
    # count becomes 5.
    ctx = {
        "customer": create_customer(pref_language=marker),
        "service_item": create_service_item(required_skill_tag="CLEANING"),
        "personnel": p,
        "certification": None,
    }
    sched = iso_in(hours=48 + 5 * 60)
    order = drive_order_to(ctx, "ACCEPTED_BY_CUSTOMER", scheduled_start_at=sched)
    rate_completed_order(ctx, order, 5, 4, 4)  # composite=4.5
    p_after = get_personnel(p["id"])
    assert p_after["rating_count"] == 5
    assert p_after["rating_score"] == 4.5
    assert p_after["tier"] == "GOLD"
