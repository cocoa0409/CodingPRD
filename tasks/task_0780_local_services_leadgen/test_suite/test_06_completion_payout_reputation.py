"""Completion payout arithmetic and the two rating variants (published vs
provisional)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers, make_pro_headers,
    create_category, create_customer, create_verified_pro, create_request,
    distribute_once, lead_for, create_slot, reset_clock, set_clock,
    create_quote_payload, create_booking_payload, create_review_payload,
    setup_completed_booking,
)

ADMIN = TEST_USERS["admin_headers"]


def test_completion_payout_rounds_each_fee_before_subtracting(api):
    """PRD 3.6: "The payout is computed in a pinned order: first the commission
    is the price multiplied by fifteen percent, rounded half-up to a whole cent
    on its own; second the processing fee is the price multiplied by
    two-point-nine percent plus a flat thirty cents, also rounded half-up to a
    whole cent on its own; third the payout is the price minus the already-rounded
    commission minus the already-rounded processing fee."

    Design: Difficulty/combinatorial_formula/booking_payout_independent_fee_rounding_mode_b
    """
    ctx = setup_completed_booking(api=api, amount_cents=10000)
    assert ctx["booking"]["status"] == "COMPLETED"
    # commission=round(1500.0)=1500; processing=round(290+30)=320; 10000-1500-320.
    assert ctx["booking"]["payout_cents"] == 8180


def test_completion_payout_independent_rounding_second_price_point(api):
    """PRD 3.6: "The payout is computed in a pinned order: first the commission
    is the price multiplied by fifteen percent, rounded half-up to a whole cent
    on its own; second the processing fee is the price multiplied by
    two-point-nine percent plus a flat thirty cents, also rounded half-up to a
    whole cent on its own; third the payout is the price minus the already-rounded
    commission minus the already-rounded processing fee."

    Design: Difficulty/combinatorial_formula/booking_payout_independent_fee_rounding_mode_b
    """
    ctx = setup_completed_booking(api=api, amount_cents=20000)
    # commission=round(3000.0)=3000; processing=round(580+30)=610; 20000-3000-610.
    assert ctx["booking"]["payout_cents"] == 16390


def _pro_with_published_and_pending_review(api):
    """Pro PR with two COMPLETED bookings; review A(5) PUBLISHED, review B(1)
    left PENDING. Returns {pro, review_b}."""
    reset_clock(api)
    cat = create_category(api, min_rating_to_receive_leads=0.0)
    cust_a = create_customer(api)
    cust_b = create_customer(api)
    pr = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    pid = pr["id"]
    slot_a = create_slot(pid, "2026-03-05T08:00:00Z", "2026-03-05T20:00:00Z", api=api)
    slot_b = create_slot(pid, "2026-03-06T08:00:00Z", "2026-03-06T20:00:00Z", api=api)

    # Booking A -> completed -> reviewed 5 -> published.
    req_a = create_request(cust_a["id"], cat["id"], api=api, description="a")
    distribute_once(req_a["id"], req_a["version"], api=api)
    lead_a = lead_for(req_a["id"], pid, api=api)
    get_success_data(api.contact_lead(lead_a["id"], make_pro_headers(pid)))
    q_a = get_success_data(api.create_quote(create_quote_payload(lead_a["id"]), make_pro_headers(pid)))
    bk_a = get_success_data(api.create_booking(
        create_booking_payload(q_a["id"], slot_a["id"], "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        make_customer_headers(cust_a["id"])))
    set_clock("2026-03-05T12:00:00Z", api)
    get_success_data(api.complete_booking(bk_a["id"], make_pro_headers(pid)))
    rev_a = get_success_data(api.create_review(create_review_payload(bk_a["id"], rating=5),
                                               make_customer_headers(cust_a["id"])))
    get_success_data(api.publish_review(rev_a["id"], ADMIN))

    # Booking B -> completed -> reviewed 1 (left PENDING).
    req_b = create_request(cust_b["id"], cat["id"], api=api, description="b")
    distribute_once(req_b["id"], req_b["version"], api=api)
    lead_b = lead_for(req_b["id"], pid, api=api)
    get_success_data(api.contact_lead(lead_b["id"], make_pro_headers(pid)))
    q_b = get_success_data(api.create_quote(create_quote_payload(lead_b["id"]), make_pro_headers(pid)))
    bk_b = get_success_data(api.create_booking(
        create_booking_payload(q_b["id"], slot_b["id"], "2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z"),
        make_customer_headers(cust_b["id"])))
    set_clock("2026-03-06T12:00:00Z", api)
    get_success_data(api.complete_booking(bk_b["id"], make_pro_headers(pid)))
    rev_b = get_success_data(api.create_review(create_review_payload(bk_b["id"], rating=1),
                                               make_customer_headers(cust_b["id"])))
    return {"pro_id": pid, "review_b": rev_b}


def test_published_rating_averages_published_reviews_only(api):
    """PRD 3.6: "A pro's public reputation, rating_avg, is the mean rating over
    that pro's PUBLISHED reviews, rounded half-up to two decimals, with
    rating_count being the number of such published reviews; when the pro has no
    published reviews both are their zero defaults."

    Design: Difficulty/dual_variant_calc/pro_rating_published_vs_provisional_divergence
    """
    ctx = _pro_with_published_and_pending_review(api)
    pro = get_success_data(api.get_pro(ctx["pro_id"], ADMIN))
    assert pro["rating_avg"] == 5.00
    assert pro["rating_count"] == 1


def test_provisional_rating_includes_pending_reviews(api):
    """PRD 3.6: "A pro's internal provisional_rating — the value the distribution
    engine gates on — is the mean rating over that pro's reviews whose status is
    PENDING or PUBLISHED, also rounded half-up to two decimals, and 0.0 when that
    set is empty."
    PRD 3.6: "the review copies the booking's customer and pro as customer_id and
    pro_id, and begins in moderation status PENDING."

    Design: Difficulty/dual_variant_calc/pro_rating_published_vs_provisional_divergence
    """
    ctx = _pro_with_published_and_pending_review(api)
    review_b = get_success_data(api.get_review(ctx["review_b"]["id"], ADMIN))
    pro = get_success_data(api.get_pro(ctx["pro_id"], ADMIN))
    assert review_b["status"] == "PENDING"
    assert pro["provisional_rating"] == 3.00


def test_review_rating_out_of_range_rejected(api):
    """PRD 3.6: "A rating outside the integer range 1 through 5 is rejected with
    ERR_INVALID_REQUEST; note that the range check is applied before the
    per-booking uniqueness check."

    Design: Corner/validations/review_rating_out_of_range_returns_invalid_request
    """
    ctx = setup_completed_booking(api=api)
    resp = api.create_review(create_review_payload(ctx["booking"]["id"], rating=6),
                             make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_second_review_for_booking_rejected(api):
    """PRD 3.6: "at most one review may exist per booking, and a second attempt
    is rejected with ERR_DUPLICATE_REVIEW."

    Design: Corner/validations/duplicate_review_returns_conflict
    """
    ctx = setup_completed_booking(api=api)
    cid = ctx["customer"]["id"]
    get_success_data(api.create_review(create_review_payload(ctx["booking"]["id"], rating=5),
                                       make_customer_headers(cid)))
    resp = api.create_review(create_review_payload(ctx["booking"]["id"], rating=3),
                             make_customer_headers(cid))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REVIEW)
