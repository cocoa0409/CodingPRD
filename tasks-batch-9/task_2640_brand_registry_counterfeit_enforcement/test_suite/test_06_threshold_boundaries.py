"""Boundary precision: the flag threshold at exactly 0.7000, and the empty-input
sets that must derive a real zero rather than a null."""

from test_helpers import (
    ANALYST,
    MONITOR_STATUS_CLEARED,
    MONITOR_STATUS_FLAGGED,
    VIOLATION_TYPE_COPYRIGHT,
    VIOLATION_TYPE_NONE,
    ApiErrorId,
    append_items,
    assert_listing_screening,
    assert_metrics,
    assert_package_derivations,
    assert_score_4dp,
    completeness_score,
    create_evidence_package,
    create_listing,
    create_seller,
    match_score,
    read_evidence_package,
    read_metrics,
    screen_payload,
    setup_claim,
    setup_enrolled_brand,
    setup_submitted_takedown,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_score_of_exactly_0_7000_flags_and_0_6997_clears(api):
    """PRD §3.4: "Fifth, the verdict: if `match_score` is at least 0.7000 the listing's `monitor_status` becomes `FLAGGED`, and otherwise it becomes `CLEARED`."
    PRD §3.4: "The threshold comparison is inclusive — a score of exactly 0.7000 flags."
    PRD §3.4: "The same price setup with both sub-scores at 0.70 accumulates 0.315 plus 0.245 plus 0.14 for exactly 0.7000, which still flags, and classifies as `COPYRIGHT` — the image sub-score is below 0.85 so the first branch fails, the text sub-score is below 0.80 so the second fails, and the third branch holds because the image sub-score is at least 0.60 and the deviation factor is at least 0.50."
    PRD §3.4: "Dropping the text sub-score to 0.6990 accumulates 0.69965, which rounds to 0.6997, clears the listing and resets `violation_type` to `NONE`."

    Design: Difficulty/boundary_precision_check/match_score_exactly_at_flag_threshold_versus_three_ten_thousandths_below
    """
    ctx = setup_enrolled_brand(api, clock="2026-08-03T09:00:00Z")
    seller = create_seller(api)
    listing = create_listing(api, ctx["brand"]["id"], seller["id"], price_cents=3000)

    at_threshold = validate_success(
        api.screen_listing(listing["id"], screen_payload(0.70, 0.70), headers=ANALYST), 200)
    assert_listing_screening(at_threshold, 0.70, 0.70, 0.7000, 0.7000,
                             MONITOR_STATUS_FLAGGED, VIOLATION_TYPE_COPYRIGHT)
    assert_score_4dp(at_threshold["match_score"], match_score(0.70, 0.70, 0.7000), "match_score")
    assert at_threshold["version"] == 2, f"got {at_threshold['version']}"

    below = validate_success(
        api.screen_listing(listing["id"], screen_payload(0.70, 0.6990), headers=ANALYST), 200)
    assert_listing_screening(below, 0.70, 0.6990, 0.7000, 0.6997,
                             MONITOR_STATUS_CLEARED, VIOLATION_TYPE_NONE)
    assert_score_4dp(below["match_score"], match_score(0.70, 0.6990, 0.7000), "match_score")
    assert below["version"] == 3, (
        f"Every screen increments the version, got {below['version']}")


def test_a_raw_sum_below_the_threshold_rounds_up_into_it_and_flags(api):
    """PRD §3.4: "Fourth, the weighted sum plus the boost is capped at 1.0000 and then rounded half-up, exactly once, to four decimal places."
    PRD §3.4: "The threshold comparison is inclusive — a score of exactly 0.7000 flags."
    PRD §3.4: "Otherwise, if `image_match_score` is at least 0.60 **and** `price_deviation_factor` is at least 0.50, `violation_type` is `COPYRIGHT`."
    PRD §3.4: "No intermediate rounding takes place here."

    Design: Difficulty/boundary_precision_check/match_score_exactly_at_flag_threshold_versus_three_ten_thousandths_below
    """
    ctx = setup_enrolled_brand(api, clock="2026-08-03T09:00:00Z")
    seller = create_seller(api)
    listing = create_listing(api, ctx["brand"]["id"], seller["id"], price_cents=3000)

    # 0.315 plus 0.244965 plus 0.14 accumulates 0.699965, which rounds up to 0.7000.
    screened = validate_success(
        api.screen_listing(listing["id"], screen_payload(0.70, 0.6999), headers=ANALYST), 200)

    assert_score_4dp(screened["match_score"], 0.7000, "match_score")
    assert_score_4dp(screened["match_score"], match_score(0.70, 0.6999, 0.7000), "match_score")
    assert screened["monitor_status"] == MONITOR_STATUS_FLAGGED, (
        f"A rounded 0.7000 flags inclusively, got {screened['monitor_status']}")
    assert screened["violation_type"] == VIOLATION_TYPE_COPYRIGHT, (
        f"got {screened['violation_type']}")
    assert_score_4dp(screened["text_match_score"], 0.6999, "text_match_score")


def test_no_decided_notice_and_no_evidence_item_derive_explicit_zeros(api):
    """PRD §3.11: "When `decided_takedown_count` is zero the rate is exactly 0.0000 — not null, not an error, and not 1.0000."
    PRD §3.11: "Notices at `DRAFT`, `SUBMITTED`, `COUNTER_NOTICED` or `WITHDRAWN` appear in neither count: an in-flight or abandoned notice is not a marketplace decision."
    PRD §3.7: "The package lands in status `ASSEMBLING` with an empty `items` array, `item_count` 0, `required_type_coverage` 0, `completeness_score` 0.0000 and `sealed_at` null; the parent claim's `version` is incremented by 1."
    PRD §3.7: "An empty package scores 0.0000 with `item_count` 0."

    Design: Difficulty/boundary_precision_check/empty_input_sets_yield_zero_rate_and_zero_completeness_not_null
    """
    ctx = setup_submitted_takedown(api, clock="2026-08-05T09:00:00Z")
    assert ctx["takedown"]["status"] == "SUBMITTED"

    metrics = read_metrics(api, ctx["brand"]["id"])
    assert_metrics(metrics, decided_takedown_count=0, removed_takedown_count=0,
                   listing_removal_rate=0.0000, repeat_infringer_count=0,
                   open_case_count=0, enforcement_spend_cents=0)
    assert metrics["listing_removal_rate"] is not None, (
        "An empty decided set derives a zero rate, never a null")

    empty = create_evidence_package(api, ctx["claim"]["id"])
    assert_package_derivations(empty, 0, 0, 0.0000)
    assert empty["items"] == [], f"A new package carries no items, got {empty['items']}"
    assert empty["sealed_at"] is None
    assert empty["completeness_score"] is not None, (
        "An empty package derives 0.0000, never a null")


def test_a_zero_completeness_score_still_blocks_the_seal(api):
    """PRD §2.9: "**Priority 50** — the evidence package satisfies both seal conjuncts, full required-type coverage and a `completeness_score` of at least 0.8000; else `ERR_EVIDENCE_INCOMPLETE` (422). Applies to sealing a package."
    PRD §3.7: "The optional count is the number of items whose `item_type` is *not* in this claim's mandatory set — which includes a type that happens to be mandatory for some other violation type — and the optional term is that count divided by a target of 4, capped at 1."
    PRD §3.7: "`completeness_score` is seventy hundredths of the coverage term plus thirty hundredths of the optional term, rounded half-up to four decimal places."
    PRD §3.11: "When `decided_takedown_count` is zero the rate is exactly 0.0000 — not null, not an error, and not 1.0000."

    Design: Difficulty/boundary_precision_check/empty_input_sets_yield_zero_rate_and_zero_completeness_not_null
    """
    ctx = setup_claim(api, clock="2026-08-05T09:00:00Z")
    assert_metrics(read_metrics(api, ctx["brand"]["id"]),
                   listing_removal_rate=0.0000, decided_takedown_count=0,
                   removed_takedown_count=0)
    rows, _meta = validate_paginated(
        api.list_takedowns(headers=ANALYST, claim_id=ctx["claim"]["id"]))
    assert rows == [], "The brand has no notices at all in this scenario"

    package = create_evidence_package(api, ctx["claim"]["id"])
    assert_package_derivations(package, 0, 0, 0.0000)
    refused = api.seal_evidence_package(package["id"], headers=ANALYST)
    validate_error(refused, ApiErrorId.EVIDENCE_INCOMPLETE, 422)

    append_items(api, package["id"], [
        ("SELLER_PROFILE_SNAPSHOT", "SNAP-1"),
        ("PRICE_HISTORY_EXPORT", "PRICE-1"),
        ("CUSTOMER_COMPLAINT", "CC-1"),
        ("SHIPPING_LABEL_PHOTO", "SHIP-1"),
    ])

    # Four supporting items saturate the optional term but cover no mandatory type.
    supporting_only = read_evidence_package(api, package["id"])
    assert_package_derivations(supporting_only, 4, 0, 0.3000)
    assert_score_4dp(supporting_only["completeness_score"],
                     completeness_score(0, 3, 4), "completeness_score")
    still_refused = api.seal_evidence_package(package["id"], headers=ANALYST)
    validate_error(still_refused, ApiErrorId.EVIDENCE_INCOMPLETE, 422)
    assert read_evidence_package(api, package["id"])["status"] == "ASSEMBLING"
