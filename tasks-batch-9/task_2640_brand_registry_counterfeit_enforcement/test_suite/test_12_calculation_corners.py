"""Arithmetic boundaries of the Brand Registry & Counterfeit Enforcement API.

Every test in this module drives one derived number to a boundary the PRD
describes explicitly — a ladder rung, an inclusive threshold, a clamp, a
non-monotonic fee band or a precedence between two projections — and checks the
persisted value against the same formula recomputed independently.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _to_whole_second(instant: str) -> str:
    """Server instants carry three fractional digits; deadline walks do not."""
    if "." in instant:
        return instant.split(".", 1)[0] + "Z"
    return instant


def test_pending_registration_scores_strength_030_and_fails_to_substantiate(api):
    """A PENDING mark scores the third rung and cannot carry a claim to 85.00.

    PRD §3.5: "Otherwise, if the registration's status is `PENDING`, `registration_strength` is 0.30."
    PRD §3.5: "On success the claim lands in status `DRAFT`, its `registration_strength` and `preliminary_score` are derived immediately, `substantiation_score` starts at 0.00, `dismissal_reason_code` starts null, and the listing's `enforcement_status` advances `NONE → CLAIM_OPEN` with the listing's `version` incremented by 1."
    PRD §3.5: "If the result falls below 85.00 the request is refused with `ERR_CLAIM_NOT_SUBSTANTIATED` (HTTP 422) and **nothing at all is persisted** — not the freshly computed score, not `updated_at`, not `version`."
    Design: Corner/calculations/pending_registration_scores_strength_030_and_fails_to_substantiate
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api, authorized_msrp_cents=10000)
    registration = fixtures.create_registration(
        api, brand["id"], nice_class=8, status=constants.REGISTRATION_STATUS_PENDING)
    seller = fixtures.create_seller(api)
    listing = fixtures.create_listing(api, brand["id"], seller["id"], price_cents=0, nice_class=8)
    listing = fixtures.screen_listing(api, listing["id"], 1.00, 1.00)
    assertions.assert_listing_screening(
        listing, 1.00, 1.00, 1.0000, 1.0000,
        constants.MONITOR_STATUS_FLAGGED, constants.VIOLATION_TYPE_COUNTERFEIT)

    claim = fixtures.create_claim(
        api, brand["id"], listing["id"], registration["id"],
        claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK)
    expected_preliminary = assertions.preliminary_score(1.0000, 0.30)
    assert expected_preliminary == 54.00, f"Expected 54.00, got {expected_preliminary}"
    assertions.assert_score_2dp(claim["registration_strength"], 0.30, "registration_strength")
    assertions.assert_score_2dp(claim["preliminary_score"], expected_preliminary, "preliminary_score")
    assertions.assert_score_2dp(claim["substantiation_score"], 0.00, "substantiation_score")
    assert claim["status"] == constants.CLAIM_STATUS_DRAFT, (
        f"Expected {constants.CLAIM_STATUS_DRAFT}, got {claim['status']}")

    expected_full = assertions.full_substantiation_score(1.0000, 0.30)
    assert expected_full == 67.50, f"Expected 67.50, got {expected_full}"
    assert expected_full < constants.SUBSTANTIATION_THRESHOLD, (
        f"Expected {expected_full} below {constants.SUBSTANTIATION_THRESHOLD}")

    before = fixtures.read_claim(api, claim["id"])
    response = api.substantiate_claim(claim["id"], headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.CLAIM_NOT_SUBSTANTIATED)

    after = fixtures.read_claim(api, claim["id"])
    assertions.assert_unchanged(before, after)
    assert after["status"] == constants.CLAIM_STATUS_DRAFT, (
        f"Expected {constants.CLAIM_STATUS_DRAFT}, got {after['status']}")
    assertions.assert_score_2dp(after["substantiation_score"], 0.00, "substantiation_score")


def test_duplicate_required_item_neither_covers_nor_counts_as_optional(api):
    """Repeating a covered exhibit type raises item_count and nothing else.

    PRD §3.7: "A second item of a type that is already covered is ignored by both terms: it adds no further coverage and it is not counted as an optional item, though it does still increase `item_count`."
    PRD §3.7: "Two conditions must both hold: `required_type_coverage` must equal the full count of mandatory types for the claim's violation type, **and** `completeness_score` must be at least 0.8000."
    PRD §3.7: "If either fails, the seal is refused with `ERR_EVIDENCE_INCOMPLETE` (HTTP 422)."
    Design: Corner/calculations/duplicate_required_item_neither_covers_nor_counts_as_optional
    """
    ctx = fixtures.setup_claim(
        api, clock="2026-08-05T09:00:00Z",
        claimed_violation_type=constants.VIOLATION_TYPE_TRADEMARK)
    required_types = assertions.required_types_for(constants.VIOLATION_TYPE_TRADEMARK)
    assert len(required_types) == 3, f"Expected 3 mandatory types, got {len(required_types)}"

    package = fixtures.create_evidence_package(api, ctx["claim"]["id"])
    assertions.assert_package_derivations(package, 0, 0, 0.0000)

    package = fixtures.append_items(api, package["id"], [(required_types[0], "SCREEN-1")])
    assertions.assert_package_derivations(
        package, 1, 1, assertions.completeness_score(1, 3, 0))
    assertions.assert_score_4dp(package["completeness_score"], 0.2333, "completeness_score")

    package = fixtures.append_items(api, package["id"], [(required_types[0], "SCREEN-2")])
    assertions.assert_package_derivations(
        package, 2, 1, assertions.completeness_score(1, 3, 0))
    assertions.assert_score_4dp(package["completeness_score"], 0.2333, "completeness_score")

    package = fixtures.append_items(
        api, package["id"], [(required_types[1], "CERT-1"), (required_types[2], "MARK-1")])
    assertions.assert_package_derivations(
        package, 4, 3, assertions.completeness_score(3, 3, 0))
    assertions.assert_score_4dp(package["completeness_score"], 0.7000, "completeness_score")

    before = fixtures.read_evidence_package(api, package["id"])
    response = api.seal_evidence_package(package["id"], headers=fixtures.ANALYST)
    validate_error(response, ApiErrorId.EVIDENCE_INCOMPLETE)
    after = fixtures.read_evidence_package(api, package["id"])
    assertions.assert_unchanged(before, after)
    assert after["status"] == constants.PACKAGE_STATUS_ASSEMBLING, (
        f"Expected {constants.PACKAGE_STATUS_ASSEMBLING}, got {after['status']}")
    assert after["sealed_at"] is None, f"Expected sealed_at null, got {after['sealed_at']}"

    package = fixtures.append_items(
        api, package["id"],
        [(constants.ITEM_SELLER_PROFILE_SNAPSHOT, "PROF-1"),
         (constants.ITEM_PRICE_HISTORY_EXPORT, "PRICE-1")])
    assertions.assert_package_derivations(
        package, 6, 3, assertions.completeness_score(3, 3, 2))
    assertions.assert_score_4dp(package["completeness_score"], 0.8500, "completeness_score")
    sealed = fixtures.seal_evidence_package(api, package["id"])
    assert sealed["status"] == constants.PACKAGE_STATUS_SEALED, (
        f"Expected {constants.PACKAGE_STATUS_SEALED}, got {sealed['status']}")
    assert sealed["item_count"] == 6, f"Expected item_count 6, got {sealed['item_count']}"


def test_strike_decay_treats_exactly_180_days_as_fresh_and_181_as_halved(api):
    """One removal strike is worth 12.55 at 180 days old and 6.28 at 181.

    PRD §3.3: "A strike whose age is 180 days or fewer is **fresh** and carries its full base weight; a strike whose age is 181 days or more is **decayed** and carries half its base weight."
    PRD §3.3: "The age boundary is therefore inclusive on the fresh side: at exactly 180 days a strike is still fresh, and at 181 days it is decayed."
    PRD §3.3: "Each strike's decayed contribution is rounded half-up to two decimal places **before** any summation."
    Design: Corner/calculations/strike_decay_treats_exactly_180_days_as_fresh_and_181_as_halved
    """
    ctx = fixtures.setup_removed_takedown(api, clock="2026-08-05T09:00:00Z")
    takedown = ctx["takedown"]
    assert takedown["status"] == constants.TAKEDOWN_STATUS_APPROVED_REMOVED, (
        f"Expected {constants.TAKEDOWN_STATUS_APPROVED_REMOVED}, got {takedown['status']}")
    assert _to_whole_second(takedown["decided_at"]) == "2026-08-05T09:00:00Z", (
        f"Expected decided_at 2026-08-05T09:00:00Z, got {takedown['decided_at']}")
    expected_contest_deadline = assertions.add_business_days(
        "2026-08-05T09:00:00Z", constants.COUNTER_NOTICE_FILING_BUSINESS_DAYS)
    assert expected_contest_deadline == "2026-08-19T09:00:00Z", (
        f"Expected 2026-08-19T09:00:00Z, got {expected_contest_deadline}")
    assert _to_whole_second(takedown["counter_notice_deadline_at"]) == expected_contest_deadline, (
        f"Expected {expected_contest_deadline}, got {takedown['counter_notice_deadline_at']}")

    fresh = assertions.strike_contribution(constants.STRIKE_BASE_TAKEDOWN_REMOVAL, 0)
    assert fresh == 12.55, f"Expected 12.55, got {fresh}"
    seller = fixtures.read_seller(api, ctx["seller"]["id"])
    assertions.assert_seller_strikes(seller, 12.55, 12.55, constants.SELLER_STATUS_ACTIVE)

    # Exactly 180 whole days after the removal decision the strike is still fresh.
    fixtures.set_clock(api, "2027-02-01T09:00:00Z")
    sweep = fixtures.run_sweep(api)
    assertions.assert_all_sweep_counts_zero(sweep)
    still_fresh = assertions.strike_contribution(constants.STRIKE_BASE_TAKEDOWN_REMOVAL, 180)
    assert still_fresh == 12.55, f"Expected 12.55, got {still_fresh}"
    seller = fixtures.read_seller(api, ctx["seller"]["id"])
    assertions.assert_seller_strikes(seller, 12.55, 12.55, constants.SELLER_STATUS_ACTIVE)

    # One more day of age halves the base and rounds 6.275 up to 6.28.
    fixtures.set_clock(api, "2027-02-02T09:00:00Z")
    sweep = fixtures.run_sweep(api)
    assertions.assert_sweep_counts(
        sweep, escalated_seller_count=0, blocked_seller_count=0, deescalated_seller_count=0)
    decayed = assertions.strike_contribution(constants.STRIKE_BASE_TAKEDOWN_REMOVAL, 181)
    assert decayed == 6.28, f"Expected 6.28, got {decayed}"
    seller = fixtures.read_seller(api, ctx["seller"]["id"])
    assertions.assert_seller_strikes(
        seller, decayed, assertions.strike_total([decayed]), constants.SELLER_STATUS_ACTIVE)
    assertions.assert_seller_strikes(seller, 6.28, 6.28, constants.SELLER_STATUS_ACTIVE)


def test_test_buy_tier_ladder_is_non_monotonic_across_the_5000_cent_boundary(api):
    """One extra cent of subtotal makes the whole order 149 cents cheaper.

    PRD §3.6: "A subtotal of exactly 5000 takes the first band inclusively, giving a fee of 750 and a total of 5750, while a subtotal of 5001 takes the second band, giving a fee of 600 and a total of only 5601 — one extra cent of subtotal makes the order 149 cents cheaper overall."
    PRD §3.6: "Otherwise `billable_total_cents` is added to the brand's `enforcement_spend_cents` and the brand's `version` is incremented by 1."
    Design: Corner/calculations/test_buy_tier_ladder_is_non_monotonic_across_the_5000_cent_boundary
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api, authorized_msrp_cents=10000)
    registration = fixtures.create_registration(api, brand["id"], nice_class=8)

    claims = []
    for _ in range(2):
        seller = fixtures.create_seller(api)
        listing = fixtures.create_listing(
            api, brand["id"], seller["id"], price_cents=3000, nice_class=8)
        fixtures.screen_listing(api, listing["id"], 0.92, 0.88)
        claims.append(fixtures.create_claim(
            api, brand["id"], listing["id"], registration["id"],
            claimed_violation_type=constants.VIOLATION_TYPE_COUNTERFEIT))

    # A subtotal of exactly 5000 sits in the first band inclusively.
    at_boundary = fixtures.create_test_buy(
        api, claims[0]["id"], purchase_price_cents=4500, shipping_cents=500, lab_fee_cents=0)
    assertions.assert_test_buy_pricing(at_boundary, 4500, 500, 0)
    assertions.assert_cents(at_boundary["subtotal_cents"], 5000, "subtotal_cents")
    assertions.assert_score_2dp(at_boundary["service_fee_rate"], 0.15, "service_fee_rate")
    assertions.assert_cents(at_boundary["service_fee_cents"], 750, "service_fee_cents")
    assertions.assert_cents(at_boundary["billable_total_cents"], 5750, "billable_total_cents")

    # One cent more of subtotal drops into the second band and costs less overall.
    past_boundary = fixtures.create_test_buy(
        api, claims[1]["id"], purchase_price_cents=4500, shipping_cents=501, lab_fee_cents=0)
    assertions.assert_test_buy_pricing(past_boundary, 4500, 501, 0)
    assertions.assert_cents(past_boundary["subtotal_cents"], 5001, "subtotal_cents")
    assertions.assert_score_2dp(past_boundary["service_fee_rate"], 0.12, "service_fee_rate")
    assertions.assert_cents(past_boundary["service_fee_cents"], 600, "service_fee_cents")
    assertions.assert_cents(past_boundary["billable_total_cents"], 5601, "billable_total_cents")

    saving = at_boundary["billable_total_cents"] - past_boundary["billable_total_cents"]
    assert saving == 149, f"Expected 149, got {saving}"

    brand = fixtures.read_brand(api, brand["id"])
    assertions.assert_cents(brand["enforcement_spend_cents"], 11351, "enforcement_spend_cents")


def test_brand_posture_prefers_an_active_enrollment_over_a_submitted_one(api):
    """The strongest posture the brand holds anywhere wins, then falls back.

    PRD §3.1: "If any enrolment of the brand is `ACTIVE`, the brand is `ENROLLED`."
    PRD §3.1: "Otherwise, if any enrolment of the brand is `SUBMITTED`, the brand is `ENROLLMENT_PENDING`."
    PRD §3.1: "Consequently a brand walks `DRAFT → ENROLLMENT_PENDING` on its first enrolment, `ENROLLMENT_PENDING → ENROLLED` when an enrolment is activated, `ENROLLED → ENROLLMENT_PENDING` when the last active enrolment leaves the active state while a submitted one remains, `ENROLLED → ENROLLMENT_LAPSED` when the last active enrolment is suspended, superseded or auto-suspended by the sweep and no submitted enrolment remains, `ENROLLMENT_PENDING → ENROLLMENT_LAPSED` when the last submitted enrolment is superseded, and `ENROLLMENT_LAPSED → ENROLLMENT_PENDING` on a re-enrolment."
    Design: Corner/calculations/brand_posture_prefers_an_active_enrollment_over_a_submitted_one
    """
    ctx = fixtures.setup_enrolled_brand(api, clock="2026-08-05T09:00:00Z")
    amazon = ctx["enrollment"]
    assert amazon["enrollment_status"] == constants.ENROLLMENT_STATUS_ACTIVE, (
        f"Expected {constants.ENROLLMENT_STATUS_ACTIVE}, got {amazon['enrollment_status']}")
    brand = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected {constants.BRAND_STATUS_ENROLLED}, got {brand['status']}")

    ebay = fixtures.create_enrollment(
        api, ctx["brand"]["id"], ctx["registration"]["id"],
        marketplace_code=constants.MARKETPLACE_EBY, requested_nice_class=8)
    assert ebay["enrollment_status"] == constants.ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected {constants.ENROLLMENT_STATUS_SUBMITTED}, got {ebay['enrollment_status']}")
    brand = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand["status"] == constants.BRAND_STATUS_ENROLLED, (
        f"Expected {constants.BRAND_STATUS_ENROLLED} while one enrolment is ACTIVE, "
        f"got {brand['status']}")

    suspended = fixtures.suspend_enrollment(
        api, amazon["id"], constants.SUSPENSION_REASON_MANUAL)
    assert suspended["enrollment_status"] == constants.ENROLLMENT_STATUS_SUSPENDED, (
        f"Expected {constants.ENROLLMENT_STATUS_SUSPENDED}, got {suspended['enrollment_status']}")
    assert suspended["suspension_reason_code"] == constants.SUSPENSION_REASON_MANUAL, (
        f"Expected {constants.SUSPENSION_REASON_MANUAL}, "
        f"got {suspended['suspension_reason_code']}")
    assert suspended["superseded_by_enrollment_id"] is None, (
        f"Expected superseded_by_enrollment_id null, "
        f"got {suspended['superseded_by_enrollment_id']}")

    brand = fixtures.read_brand(api, ctx["brand"]["id"])
    assert brand["status"] == constants.BRAND_STATUS_ENROLLMENT_PENDING, (
        f"Expected {constants.BRAND_STATUS_ENROLLMENT_PENDING} once only the SUBMITTED "
        f"enrolment remains, got {brand['status']}")


def test_takedown_deadline_uses_the_ten_business_day_wlm_sla(api):
    """Filing through a WLM enrolment buys ten business days, not five.

    PRD §2.5: "A takedown notice's marketplace decision deadline is measured from the moment of submission, and the allowance depends on which marketplace the filing enrolment covers: five business days on `AMZ`, eight business days on `EBY` and ten business days on `WLM`."
    PRD §3.8: "On a successful filing, `submitted_by_rep_id` is stamped with the acting `X-User-ID`, `submitted_at` is stamped from the logical clock, `round_number` becomes 1, and `decision_due_at` is computed by advancing `submitted_at` by the marketplace's own service-level allowance — five business days for `AMZ`, eight for `EBY`, ten for `WLM` — read from the filing enrolment's `marketplace_code`."
    Design: Corner/calculations/takedown_deadline_uses_the_ten_business_day_wlm_sla
    """
    ctx = fixtures.setup_drafted_takedown(
        api, clock="2026-08-17T09:00:00Z",
        enrollment={"marketplace_code": constants.MARKETPLACE_WLM})
    assert ctx["enrollment"]["marketplace_code"] == constants.MARKETPLACE_WLM, (
        f"Expected {constants.MARKETPLACE_WLM}, got {ctx['enrollment']['marketplace_code']}")
    draft = ctx["takedown"]
    assert draft["status"] == constants.TAKEDOWN_STATUS_DRAFT, (
        f"Expected {constants.TAKEDOWN_STATUS_DRAFT}, got {draft['status']}")
    assert draft["round_number"] == 0, f"Expected round_number 0, got {draft['round_number']}"
    assert draft["submitted_at"] is None, (
        f"Expected submitted_at null, got {draft['submitted_at']}")
    assert draft["decision_due_at"] is None, (
        f"Expected decision_due_at null, got {draft['decision_due_at']}")

    filed = fixtures.submit_takedown(api, draft["id"], ctx["representative"]["id"])
    assert filed["status"] == constants.TAKEDOWN_STATUS_SUBMITTED, (
        f"Expected {constants.TAKEDOWN_STATUS_SUBMITTED}, got {filed['status']}")
    assert filed["round_number"] == 1, f"Expected round_number 1, got {filed['round_number']}"
    assert filed["submitted_by_rep_id"] == ctx["representative"]["id"], (
        f"Expected {ctx['representative']['id']}, got {filed['submitted_by_rep_id']}")
    assert _to_whole_second(filed["submitted_at"]) == "2026-08-17T09:00:00Z", (
        f"Expected submitted_at 2026-08-17T09:00:00Z, got {filed['submitted_at']}")

    expected_due = assertions.add_business_days(
        "2026-08-17T09:00:00Z",
        constants.TAKEDOWN_DECISION_SLA_BUSINESS_DAYS[constants.MARKETPLACE_WLM])
    assert expected_due == "2026-08-31T09:00:00Z", (
        f"Expected 2026-08-31T09:00:00Z, got {expected_due}")
    assert _to_whole_second(filed["decision_due_at"]) == expected_due, (
        f"Expected decision_due_at {expected_due}, got {filed['decision_due_at']}")

    amazon_due = assertions.add_business_days(
        "2026-08-17T09:00:00Z",
        constants.TAKEDOWN_DECISION_SLA_BUSINESS_DAYS[constants.MARKETPLACE_AMZ])
    assert amazon_due == "2026-08-24T09:00:00Z", f"Expected 2026-08-24T09:00:00Z, got {amazon_due}"
    assert _to_whole_second(filed["decision_due_at"]) != amazon_due, (
        "A WLM filing must not inherit the five-business-day AMZ allowance")

    listing = fixtures.read_listing(api, ctx["listing"]["id"])
    assert listing["enforcement_status"] == constants.ENFORCEMENT_STATUS_TAKEDOWN_PENDING, (
        f"Expected {constants.ENFORCEMENT_STATUS_TAKEDOWN_PENDING}, "
        f"got {listing['enforcement_status']}")


def test_price_above_msrp_clamps_the_deviation_factor_to_zero(api):
    """A listing dearer than the authorised reference deviates 0.0000, never less.

    PRD §3.4: "That raw ratio is then clamped into the range 0 through 1 — a listing priced above the authorised reference produces a negative ratio, which clamps to zero, so the factor is never negative — and rounded half-up to four decimal places to yield `price_deviation_factor`."
    PRD §3.4: "A reference of 10000 cents against a price of 3000 cents gives 0.7000; against a price of 9500 cents it gives 0.0500; against a price of 12000 cents it gives 0.0000."
    PRD §3.4: "Fifth, the verdict: if `match_score` is at least 0.7000 the listing's `monitor_status` becomes `FLAGGED`, and otherwise it becomes `CLEARED`."
    PRD §3.4: "Every screen increments the listing's `version` by 1, whether it flags or clears."
    Design: Corner/calculations/price_above_msrp_clamps_the_deviation_factor_to_zero
    """
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    brand = fixtures.create_brand(api, authorized_msrp_cents=10000)
    seller = fixtures.create_seller(api)
    listing = fixtures.create_listing(
        api, brand["id"], seller["id"], price_cents=12000, nice_class=8)
    assertions.assert_common_fields(listing, expected_version=1)
    assert listing["monitor_status"] == constants.MONITOR_STATUS_NEW, (
        f"Expected {constants.MONITOR_STATUS_NEW}, got {listing['monitor_status']}")

    expected_deviation = assertions.price_deviation_factor(10000, 12000)
    assert expected_deviation == 0.0000, f"Expected 0.0000, got {expected_deviation}"

    response = api.screen_listing(
        listing["id"], factories.screen_payload(0.50, 0.40), headers=fixtures.ANALYST)
    cleared = validate_success(response, 200)
    expected_cleared_match = assertions.match_score(0.50, 0.40, expected_deviation)
    assert expected_cleared_match == 0.3650, f"Expected 0.3650, got {expected_cleared_match}"
    assertions.assert_listing_screening(
        cleared, 0.50, 0.40, 0.0000, expected_cleared_match,
        constants.MONITOR_STATUS_CLEARED, constants.VIOLATION_TYPE_NONE)
    assertions.assert_common_fields(cleared, expected_version=2)

    # A clearing screen still counts, so the second screen lands on version 3.
    response = api.screen_listing(
        listing["id"], factories.screen_payload(0.92, 0.88), headers=fixtures.ANALYST)
    flagged = validate_success(response, 200)
    expected_flagged_match = assertions.match_score(0.92, 0.88, expected_deviation)
    assert expected_flagged_match == 0.7220, f"Expected 0.7220, got {expected_flagged_match}"
    assertions.assert_listing_screening(
        flagged, 0.92, 0.88, 0.0000, expected_flagged_match,
        constants.MONITOR_STATUS_FLAGGED, constants.VIOLATION_TYPE_COUNTERFEIT)
    assertions.assert_common_fields(flagged, expected_version=3)


def test_seller_risk_boost_adds_003_once_standalone_points_pass_ten(api):
    """An escalated seller's screen carries the 0.03 rung, not the 0.05 rung.

    PRD §3.4: "Otherwise, if the seller's `standalone_strike_points` is at least 10.00, the boost is 0.03."
    PRD §3.4: "Note that this ladder consults the *standalone* variant, not the cluster variant, and that only the first matching rung applies."
    PRD §3.10: "On success, a seizure-confirmed strike of 25.15 base points — the heaviest single charge in the domain — is attributed to that seller with an effective instant equal to `concluded_at`, both strike variants are recomputed, the seller escalates to `UNDER_INVESTIGATION` when its cluster total reaches 25.00 and is auto-blocked when it reaches 60.00, and every row touched has its `version` incremented by 1."
    Design: Corner/calculations/seller_risk_boost_adds_003_once_standalone_points_pass_ten
    """
    ctx = fixtures.setup_enrolled_brand(api, clock="2026-08-05T09:00:00Z")
    ctx["seller"] = fixtures.create_seller(api)

    # A clean seller attracts no boost at all, which fixes the unboosted baseline.
    control_listing = fixtures.create_listing(
        api, ctx["brand"]["id"], ctx["seller"]["id"], price_cents=3000, nice_class=8)
    control_listing = fixtures.screen_listing(api, control_listing["id"], 0.92, 0.88)
    unboosted = assertions.match_score(0.92, 0.88, 0.7000)
    assert unboosted == 0.8620, f"Expected 0.8620, got {unboosted}"
    assertions.assert_listing_screening(
        control_listing, 0.92, 0.88, 0.7000, unboosted,
        constants.MONITOR_STATUS_FLAGGED, constants.VIOLATION_TYPE_COUNTERFEIT)

    ctx = fixtures.setup_escalated_seller_via_diversion(api, ctx)
    escalated_seller = ctx["seller"]
    assertions.assert_seller_strikes(
        escalated_seller, constants.STRIKE_BASE_SEIZURE_CONFIRMED,
        constants.STRIKE_BASE_SEIZURE_CONFIRMED, constants.SELLER_STATUS_UNDER_INVESTIGATION)
    assert escalated_seller["standalone_strike_points"] >= constants.SELLER_RISK_BOOST_STANDALONE_THRESHOLD, (
        f"Expected at least {constants.SELLER_RISK_BOOST_STANDALONE_THRESHOLD}, "
        f"got {escalated_seller['standalone_strike_points']}")
    assert escalated_seller["status"] != constants.SELLER_STATUS_BLOCKED, (
        "A 25.15-point seller is UNDER_INVESTIGATION, so the 0.05 rung must not apply")

    boosted_listing = fixtures.create_listing(
        api, ctx["brand"]["id"], ctx["seller"]["id"], price_cents=3000, nice_class=8)
    boosted_listing = fixtures.screen_listing(api, boosted_listing["id"], 0.92, 0.88)
    boosted = assertions.match_score(
        0.92, 0.88, 0.7000, constants.SELLER_RISK_BOOST_STANDALONE)
    assert boosted == 0.8920, f"Expected 0.8920, got {boosted}"
    assertions.assert_listing_screening(
        boosted_listing, 0.92, 0.88, 0.7000, boosted,
        constants.MONITOR_STATUS_FLAGGED, constants.VIOLATION_TYPE_COUNTERFEIT)

    difference = round(boosted - unboosted, 4)
    assert difference == 0.03, f"Expected the boost to add 0.03, got {difference}"
