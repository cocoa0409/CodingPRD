"""Reviews, the two review deadlines, and the stored rating rollup that moves in
both directions."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_rating_rollup_conservation,
    assert_review,
    api_client,
    read_menu_item,
    read_review,
    set_clock,
    setup_fulfilled_order,
    setup_reviewed_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_hiding_and_unhiding_a_review_moves_the_rollup_both_ways(api):
    """PRD §3.10: "Hiding a review — available from either `SUBMITTED` or
    `RESPONDED`, and specified identically for both — sets `counts_toward_rollup` to
    false and recomputes the rollup, which may drop the average away entirely when
    the visible count falls below the minimum. Unhiding returns a `HIDDEN` review to
    `SUBMITTED`, sets `counts_toward_rollup` back to true, and recomputes the rollup
    again"
    PRD §2.10: "A menu item's `rating_count` equals the number of reviews on that
    item whose `counts_toward_rollup` is true, and its `rating_avg` is absent exactly
    when `rating_count` is below 3."
    PRD §3.10: "`rating_count` is the number of such reviews. When that count is
    below **3**, `rating_avg` is null; otherwise `rating_avg` is the sum of their
    ratings divided by the count, rounded half up to 2 decimal places."

    Design: Corner/state_machines/review_hide_then_unhide_recomputes_the_rating_rollup
    """
    s = setup_reviewed_order(rating=5)
    review = read_review(s.review_id, s.ch)
    assert_review(review)
    assert review["rating"] == 5
    assert review["counts_toward_rollup"] is True

    before = read_menu_item(s.cookie_id, s.bh)
    assert before["rating_count"] == 1
    assert before["rating_avg"] is None
    assert_rating_rollup_conservation(before)

    hidden = validate_success(
        api.moderate_review(s.review_id, {"to_status": "HIDDEN"}, ADMIN)
    )
    assert hidden["review_status"] == "HIDDEN"
    assert hidden["counts_toward_rollup"] is False
    while_hidden = read_menu_item(s.cookie_id, s.bh)
    assert while_hidden["rating_count"] == 0
    assert while_hidden["rating_avg"] is None
    assert_rating_rollup_conservation(while_hidden)

    unhidden = validate_success(
        api.moderate_review(s.review_id, {"to_status": "SUBMITTED"}, ADMIN)
    )
    assert unhidden["review_status"] == "SUBMITTED"
    assert unhidden["counts_toward_rollup"] is True
    restored = read_menu_item(s.cookie_id, s.bh)
    assert restored["rating_count"] == 1
    assert restored["rating_avg"] is None
    assert_rating_rollup_conservation(restored)


def test_a_review_submitted_at_the_window_close_instant_is_refused(api):
    """PRD §2.6: "Rung 41: the current instant is strictly before the order's
    `review_window_closes_at`, otherwise `ERR_REVIEW_WINDOW_CLOSED` (409) on review
    submission."
    PRD §3.10: "A review may be submitted only by the buyer, only on an order that
    has been fulfilled, and only while the current instant is strictly before that
    order's `review_window_closes_at`, which is its `fulfilled_at` plus **21 days**;
    a late submission is rung 41's `ERR_REVIEW_WINDOW_CLOSED`, and a second review
    for the same `order_id` is rung 37's `ERR_DUPLICATE_REVIEW`."

    Design: Corner/validations/reviewing_after_the_review_window_closes_is_rejected
    """
    s = setup_fulfilled_order()
    set_clock("2026-05-28T15:00:00Z")

    rejected = api.create_review(
        {
            "order_id": s.order_id,
            "menu_item_id": s.cookie_id,
            "rating": 4,
            "body": "Late but honest.",
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_REVIEW_WINDOW_CLOSED)

    _, meta = validate_paginated(api.list_reviews(s.ch, {"order_id": s.order_id}))
    assert meta["total_count"] == 0
    item = read_menu_item(s.cookie_id, s.bh)
    assert item["rating_count"] == 0
    assert item["rating_avg"] is None


def test_a_second_review_for_the_same_order_is_refused(api):
    """PRD §2.6: "Rung 37: no review already exists for this `order_id`, otherwise
    `ERR_DUPLICATE_REVIEW` (409) on review submission."
    PRD §3.10: "The review is created in `review_status` `SUBMITTED` with
    `counts_toward_rollup` true and with `shortfall_affected` derived from the
    reviewed order — true when that order's `shortfall_flag` is true or any refund
    movement exists against it — and the submission recomputes the menu item's rating
    rollup and bumps the item's `version`."

    Design: Corner/validations/a_second_review_for_the_same_order_is_rejected
    """
    s = setup_reviewed_order(rating=5)
    first = read_review(s.review_id, s.ch)
    assert first["shortfall_affected"] is False
    assert first["counts_toward_rollup"] is True

    rejected = api.create_review(
        {
            "order_id": s.order_id,
            "menu_item_id": s.cookie_id,
            "rating": 1,
            "body": "Second review attempt.",
        },
        s.ch,
    )
    validate_error(rejected, ApiErrorId.ERR_DUPLICATE_REVIEW)

    reviews, meta = validate_paginated(api.list_reviews(s.ch, {"order_id": s.order_id}))
    assert meta["total_count"] == 1
    assert reviews[0]["id"] == s.review_id
    assert reviews[0]["rating"] == 5
    item = read_menu_item(s.cookie_id, s.bh)
    assert item["rating_count"] == 1
    assert item["rating_avg"] is None


def test_a_baker_response_at_the_response_window_close_is_refused(api):
    """PRD §2.6: "Rung 42: the current instant is strictly before the review's
    `created_at` plus the baker response window of 14 days, otherwise
    `ERR_RESPONSE_WINDOW_CLOSED` (409) on a baker response."
    PRD §3.10: "The operator may answer a `SUBMITTED` review while the current
    instant is strictly before the review's own `created_at` plus **14 days**; a
    later attempt is rung 42's `ERR_RESPONSE_WINDOW_CLOSED`."

    Design: Corner/validations/baker_response_after_the_response_window_closes_is_rejected
    """
    s = setup_reviewed_order(rating=4)
    set_clock("2026-05-21T15:00:00Z")

    rejected = api.respond_to_review(
        s.review_id, {"baker_response": "Thank you, see you next Wednesday."}, s.bh
    )
    validate_error(rejected, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED)

    review = read_review(s.review_id, s.ch)
    assert review["review_status"] == "SUBMITTED"
    assert review["baker_response"] is None
    assert review["responded_at"] is None
