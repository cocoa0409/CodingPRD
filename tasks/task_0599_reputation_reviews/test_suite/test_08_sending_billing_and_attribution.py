"""Send batches, per-line billing, delivery events and the two conversion-rate variants."""

from test_helpers import (
    ApiErrorId,
    assert_credit_ledger,
    assert_instant_equals,
    assert_score,
    enqueue_request,
    ingest_review,
    read_campaign,
    read_review_request,
    send_batch,
    set_clock,
    set_compliance_hold,
    setup_campaign_with_queued_requests,
    setup_running_email_campaign,
    setup_running_sms_campaign,
    validate_error,
    validate_success,
    verify_review,
)


# ---------------------------------------------------------------------------
# Billing rounds per line, then sums
# ---------------------------------------------------------------------------
def _setup_three_queued_sms_requests():
    env = setup_running_sms_campaign(num_contacts=3, daily_send_cap=10, credits_allocated=10)
    env["requests"] = [
        enqueue_request(env["campaign"]["id"], contact["id"]) for contact in env["contacts"]
    ]
    return env


def test_three_full_rate_sms_lines_round_per_line_and_total_024(api, admin_headers):
    """PRD §2.7: "Campaign billing rounds **per line, then sums**. Each individual message's
    `unit_cost` is rounded to 2 decimal places first, and only then are the rounded lines
    added together. Summing the raw products and rounding once at the end produces a
    different — and wrong — figure. Three SMS messages at the full rate, for example, are
    three separately-rounded lines of 0.08 each, totalling 0.24; they are not 0.23."
    PRD §3.6: "The base rate is 7.5 tenths of a cent per SMS — 0.075 — and 1.2 tenths of a
    cent per email — 0.012."

    Design: Difficulty/combinatorial_formula/campaign_billing_round_per_line_then_sum
    """
    env = _setup_three_queued_sms_requests()

    result = validate_success(
        api.send_batch(env["campaign"]["id"], {"batch_size": 3}, admin_headers)
    )
    assert result["sent_count"] == 3
    assert_score(result["billing_cost"], 0.24, "send-batch billing_cost")

    assert_score(read_campaign(env["campaign"]["id"])["billing_cost"], 0.24, "Campaign.billing_cost")


def test_each_sms_line_carries_its_own_rounded_unit_cost_and_send_index(api, admin_headers):
    """PRD §3.6: "Each request that goes out receives a `send_index` — a 1-based counter that
    runs across the campaign's whole lifetime, assigned as the maximum index already handed
    out in this campaign plus one, distributed across the batch in `created_at` ascending
    order — a `sent_at` stamp at the current logical instant, and a `unit_cost`."
    PRD §3.6: "The discount is a full 1.00 for the first 100 messages of the campaign's
    lifetime, drops to 0.90 for messages with a `send_index` from 101 through 500 inclusive,
    and drops again to 0.80 for every message beyond the 500th."
    PRD §3.6: "Per sent request, `credits_reserved` falls by one and `credits_consumed` rises
    by one"

    Design: Difficulty/combinatorial_formula/campaign_billing_round_per_line_then_sum
    """
    env = _setup_three_queued_sms_requests()
    send_batch(env["campaign"]["id"], 3)

    requests = [read_review_request(request["id"]) for request in env["requests"]]
    for index, request in enumerate(requests, start=1):
        assert request["status"] == "SENT"
        assert request["send_index"] == index, "send_index runs in created_at ascending order"
        assert_score(request["unit_cost"], 0.08, f"unit_cost of send_index {index}")

    campaign = read_campaign(env["campaign"]["id"])
    assert_credit_ledger(campaign, reserved=0, consumed=3, released=0)


# ---------------------------------------------------------------------------
# The FROZEN gate outranks the daily send cap
# ---------------------------------------------------------------------------
def _setup_frozen_location_with_an_over_cap_batch():
    env = setup_campaign_with_queued_requests(
        num_requests=2, name="Capped", daily_send_cap=1, credits_allocated=10
    )
    set_compliance_hold(env["location"]["id"], True)
    return env


def test_send_batch_on_a_frozen_location_reports_the_freeze_not_the_send_cap(api, admin_headers):
    """PRD §2.5: "`FROZEN` blocks **every** mutating operation on the location and on every
    entity beneath it — listings, campaigns, review requests, reviews, responses,
    escalations, surveys and the widget — and it also blocks the certification checkpoint of
    §3.8, which although it reads like a read is a mutation. A blocked operation is rejected
    with `ERR_LOCATION_FROZEN` (409)."
    PRD §2.9: "8. The `FROZEN` gate (`ERR_LOCATION_FROZEN`)."
    PRD §2.9: "23. Daily send cap (`ERR_SEND_CAP_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_daily_send_cap_on_send_batch
    """
    env = _setup_frozen_location_with_an_over_cap_batch()

    # batch_size 2 against daily_send_cap 1 also breaches the fiscal rule at order 23,
    # but the FROZEN gate at order 8 is the earlier check and must be the reported failure.
    resp = api.send_batch(env["campaign"]["id"], {"batch_size": 2}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_LOCATION_FROZEN.value)


def test_the_frozen_send_batch_rejection_bills_and_sends_nothing(api, admin_headers):
    """PRD §3.8: "Setting it true takes the location from `OPEN` or from `RESTRICTED` to
    `FROZEN`, sets `compliance_hold` to true, system-pauses every `RUNNING` campaign at that
    location, reverts a `PUBLISHED` widget to `DRAFT` with a null `published_at`, appends a
    `POSTURE_CHANGED` alert, and increments the location's `version`."
    PRD §3.6: "If it would, the entire batch is rejected with `ERR_SEND_CAP_EXCEEDED` (422)
    and nothing is partially sent."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_daily_send_cap_on_send_batch
    """
    env = _setup_frozen_location_with_an_over_cap_batch()

    resp = api.send_batch(env["campaign"]["id"], {"batch_size": 2}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_LOCATION_FROZEN.value)

    campaign = read_campaign(env["campaign"]["id"])
    assert campaign["status"] == "PAUSED", "the compliance hold system-paused the campaign"
    assert campaign["credits_consumed"] == 0, "nothing may be billed by a refused batch"
    assert_score(campaign["billing_cost"], 0.00, "Campaign.billing_cost")

    for request in env["requests"]:
        reread = read_review_request(request["id"])
        assert reread["status"] != "SENT", "no request may reach SENT"
        assert reread["send_index"] is None


# ---------------------------------------------------------------------------
# Metrics with an empty billable set
# ---------------------------------------------------------------------------
def test_metrics_with_no_billable_request_returns_zero_conversion_rates(api, admin_headers):
    """PRD §3.6: "Campaign performance is reported through two deliberately different
    conversion rates, both over the same denominator: the count of that campaign's
    **billable** requests, meaning those whose `status` is `SENT`, `DELIVERED`, `CLICKED`,
    `CONVERTED` or `FAILED`. When that denominator is zero, both rates are 0.00."

    Design: Difficulty/boundary_precision_check/campaign_metrics_zero_denominator_returns_zero_rates
    """
    env = setup_running_email_campaign(num_contacts=0, name="Empty", credits_allocated=10)

    resp = api.get_campaign_metrics(env["campaign"]["id"], admin_headers)
    metrics = validate_success(resp)

    assert metrics["sent_count"] == 0
    assert_score(metrics["conversion_rate_strict"], 0.00, "conversion_rate_strict")
    assert_score(metrics["conversion_rate_broad"], 0.00, "conversion_rate_broad")


def test_metrics_with_no_billable_request_reports_full_credits_and_zero_billing(api, admin_headers):
    """PRD §3.6: "The metrics view also reports `sent_count`, `billing_cost`, and
    `credits_available` — the campaign's allocated credits less those reserved and less
    those consumed."
    PRD §3.6: "The campaign's `billing_cost` is then the **sum of those already-rounded
    per-message costs** across every billable request — every request whose `status` is
    `SENT`, `DELIVERED`, `CLICKED`, `CONVERTED` or `FAILED`, taken in `created_at` ascending
    order."

    Design: Difficulty/boundary_precision_check/campaign_metrics_zero_denominator_returns_zero_rates
    """
    env = setup_running_email_campaign(num_contacts=0, name="Empty", credits_allocated=10)

    metrics = validate_success(api.get_campaign_metrics(env["campaign"]["id"], admin_headers))
    assert_score(metrics["billing_cost"], 0.00, "billing_cost")
    assert metrics["credits_available"] == 10


# ---------------------------------------------------------------------------
# STRICT vs BROAD attribution
# ---------------------------------------------------------------------------
def _setup_campaign_with_two_sends_and_two_reviews():
    env = setup_running_email_campaign(
        num_contacts=2, name="Spring Asks", daily_send_cap=10, credits_allocated=10
    )
    campaign_id = env["campaign"]["id"]
    env["requests"] = [
        enqueue_request(campaign_id, contact["id"]) for contact in env["contacts"]
    ]
    send_batch(campaign_id, 2)

    set_clock("2026-05-05T00:00:00Z")
    linked = ingest_review(
        env["location"]["id"],
        site="GOOGLE",
        external_review_id="g-r1",
        author_name="Carla",
        rating=5,
        text="Great",
        posted_at="2026-05-05T00:00:00Z",
        review_request_id=env["requests"][0]["id"],
    )
    verify_review(linked["id"])
    organic = ingest_review(
        env["location"]["id"],
        site="YELP",
        external_review_id="y-r1",
        author_name="Walk In",
        rating=4,
        text="Nice",
        posted_at="2026-05-05T12:00:00Z",
    )
    env["linked_review"] = linked
    env["organic_review"] = organic
    return env


def test_strict_and_broad_conversion_rates_diverge_on_identical_data(api, admin_headers):
    """PRD §3.6: "The **STRICT** rate, surfaced as `conversion_rate_strict`, is the number the
    platform bills marketing performance on. Its numerator counts reviews that are explicitly
    linked to one of this campaign's billable requests, whose `moderation_state` is
    `VERIFIED`, and whose `posted_at` falls inside that specific request's own 14-day window
    opening at its `sent_at` (start included, end excluded)."
    PRD §3.6: "The **BROAD** rate, surfaced as `conversion_rate_broad`, is the halo number
    shown to the customer. It ignores the request link entirely and ignores verification: its
    numerator counts every review at the campaign's location whose `moderation_state` is
    `UNVERIFIED` or `VERIFIED` and whose `posted_at` falls inside a single 14-day window
    opening at the campaign's own `activated_at` (start included, end excluded)."

    Design: Difficulty/dual_variant_calc/campaign_conversion_strict_vs_broad_diverge
    """
    env = _setup_campaign_with_two_sends_and_two_reviews()

    metrics = validate_success(api.get_campaign_metrics(env["campaign"]["id"], admin_headers))

    assert metrics["sent_count"] == 2, "two billable requests form the shared denominator"
    assert_score(metrics["conversion_rate_strict"], 50.00, "conversion_rate_strict")
    assert_score(metrics["conversion_rate_broad"], 100.00, "conversion_rate_broad")
    assert metrics["conversion_rate_strict"] != metrics["conversion_rate_broad"], (
        "the same data must yield two different percentages"
    )
    assert_score(metrics["billing_cost"], 0.02, "billing_cost of two EMAIL lines")


def test_an_in_window_linked_review_converts_only_its_own_request(api, admin_headers):
    """PRD §3.6: "**Attribution.** When a review is ingested carrying a `review_request_id`, the
    named request converts — from `SENT`, from `DELIVERED` or from `CLICKED` — to `CONVERTED`,
    and the new review's `id` is stamped into the request's `converted_review_id` (an identity
    record only, never a decision input). Conversion happens only if the review's `posted_at`
    falls inside the attribution window that opens at the request's `sent_at` and runs for 14
    days, with the opening instant included and the closing instant excluded."

    Design: Difficulty/dual_variant_calc/campaign_conversion_strict_vs_broad_diverge
    """
    env = _setup_campaign_with_two_sends_and_two_reviews()

    converted = read_review_request(env["requests"][0]["id"])
    assert converted["status"] == "CONVERTED"
    assert converted["converted_review_id"] == env["linked_review"]["id"]

    untouched = read_review_request(env["requests"][1]["id"])
    assert untouched["status"] == "SENT", "the organic review is linked to no request"
    assert untouched["converted_review_id"] is None


# ---------------------------------------------------------------------------
# Send-batch corner cases
# ---------------------------------------------------------------------------
def test_a_batch_beyond_the_daily_cap_is_rejected_whole(api, admin_headers):
    """PRD §3.6: "The daily cap is then checked **for the batch as a whole**: the number of
    this campaign's requests already moved to `SENT` on the current UTC calendar day, plus the
    number this batch would send, must not exceed `daily_send_cap`. If it would, the entire
    batch is rejected with `ERR_SEND_CAP_EXCEEDED` (422) and nothing is partially sent."

    Design: Corner/validations/send_batch_over_daily_cap_is_rejected_whole
    """
    env = setup_campaign_with_queued_requests(
        num_requests=2, sites=("GOOGLE",), name="Capped",
        daily_send_cap=1, credits_allocated=5,
    )

    resp = api.send_batch(env["campaign"]["id"], {"batch_size": 2}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_SEND_CAP_EXCEEDED.value)

    for request in env["requests"]:
        assert read_review_request(request["id"])["status"] == "QUEUED", "nothing is partially sent"

    campaign = read_campaign(env["campaign"]["id"])
    assert campaign["credits_consumed"] == 0
    assert_score(campaign["billing_cost"], 0.00, "Campaign.billing_cost")


def test_a_batch_smaller_than_the_queue_drains_only_the_oldest_requests(api, admin_headers):
    """PRD §3.6: "**Sending a batch.** A `LocationManager` drains up to `batch_size` `QUEUED`
    requests to `SENT`, taking them in `created_at` ascending order."
    PRD §3.6: "The batch operation answers with the number of requests it sent, the number of
    requests `remaining_queued` behind them, the campaign's new `billing_cost`, and the
    `campaign_status`."
    PRD §3.6: "`QUEUED` and `SUPPRESSED` requests are not billable and contribute nothing."

    Design: Corner/endpoints/send_batch_smaller_than_queue_sends_a_partial_batch
    """
    env = setup_campaign_with_queued_requests(
        num_requests=3, sites=("GOOGLE",), daily_send_cap=10, credits_allocated=10
    )

    result = validate_success(
        api.send_batch(env["campaign"]["id"], {"batch_size": 2}, admin_headers)
    )
    assert result["sent_count"] == 2
    assert result["remaining_queued"] == 1
    assert_score(result["billing_cost"], 0.02, "billing_cost of two EMAIL lines")
    assert result["campaign_status"] == "RUNNING"

    first = read_review_request(env["requests"][0]["id"])
    second = read_review_request(env["requests"][1]["id"])
    third = read_review_request(env["requests"][2]["id"])

    assert first["status"] == "SENT" and first["send_index"] == 1
    assert_score(first["unit_cost"], 0.01, "unit_cost of send_index 1")
    assert second["status"] == "SENT" and second["send_index"] == 2
    assert_score(second["unit_cost"], 0.01, "unit_cost of send_index 2")
    assert third["status"] == "QUEUED"
    assert third["send_index"] is None
    assert third["unit_cost"] is None

    campaign = read_campaign(env["campaign"]["id"])
    assert_credit_ledger(campaign, reserved=1, consumed=2, released=0)


def test_delivery_events_advance_a_sent_request_through_the_status_chain(api, admin_headers):
    """PRD §3.6: "**Delivery outcomes.** The delivery connector reports back through a
    `PlatformAdmin`-only callback carrying an `event_type`. `DELIVERED` advances a `SENT`
    request to `DELIVERED`. `CLICKED` advances a `DELIVERED` request to `CLICKED`."
    PRD §3.6: "the campaign's `sent_count`, which is the number of its requests that have
    reached `SENT`, `DELIVERED`, `CLICKED`, `CONVERTED` or `FAILED`, is refreshed."

    Design: Corner/endpoints/review_request_delivery_events_advance_the_status_chain
    """
    env = setup_campaign_with_queued_requests(
        num_requests=1, sites=("GOOGLE",), daily_send_cap=5, credits_allocated=5
    )
    request_id = env["requests"][0]["id"]
    send_batch(env["campaign"]["id"], 1)

    delivered = validate_success(
        api.send_request_event(request_id, {"event_type": "DELIVERED"}, admin_headers)
    )
    assert delivered["status"] == "DELIVERED"

    clicked = validate_success(
        api.send_request_event(request_id, {"event_type": "CLICKED"}, admin_headers)
    )
    assert clicked["status"] == "CLICKED"
    assert_instant_equals(clicked["sent_at"], "2026-05-01T00:00:00Z", "ReviewRequest.sent_at")

    metrics = validate_success(api.get_campaign_metrics(env["campaign"]["id"], admin_headers))
    assert metrics["sent_count"] == 1, "a CLICKED request still counts once as billable"
    assert_score(metrics["billing_cost"], 0.01, "billing_cost")
