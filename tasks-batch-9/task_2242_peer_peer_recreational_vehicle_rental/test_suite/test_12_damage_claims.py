"""Damage claims: the frozen photo comparison, the bounded review cycle, and
the adjudication waterfall that fills the deductible before the plan pays."""

from test_helpers import (
    ApiErrorId,
    CLAIMS_ADJUSTER_HEADERS,
    CauseCode,
    ClaimStatus,
    ComparisonVerdict,
    PLATFORM_ADMIN_HEADERS,
    PhotoPhase,
    SettlementStatus,
    Zone,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ALL_ZONES = (
    Zone.EXTERIOR_FRONT,
    Zone.EXTERIOR_REAR,
    Zone.INTERIOR,
    Zone.ROOF,
    Zone.UNDERCARRIAGE,
)
FOUR_ZONES = (
    Zone.EXTERIOR_FRONT,
    Zone.EXTERIOR_REAR,
    Zone.INTERIOR,
    Zone.ROOF,
)


def _file_claim(api, world, booking_id, **overrides):
    """The raw intake call, so refusals can be inspected as well as successes."""
    return api.create_damage_claim(
        factories.damage_claim_payload(booking_id, **overrides),
        world.owner_headers,
    )


def _claim_count(api, booking_id):
    _rows, meta = validate_paginated(
        api.list_damage_claims(
            factories.page_params(booking_id=booking_id), PLATFORM_ADMIN_HEADERS
        )
    )
    return meta["total_count"]


def _complete_info_round(api, world, claim_id, note, answer):
    """One full INFO_REQUESTED -> UNDER_REVIEW loop."""
    validate_success(
        api.request_claim_info(
            claim_id, factories.info_request_payload(note), CLAIMS_ADJUSTER_HEADERS
        ),
        200,
    )
    return validate_success(
        api.respond_to_claim_info(
            claim_id, factories.info_response_payload(answer), world.owner_headers
        ),
        200,
    )


def _trip_with_flagged_rear_baseline(api, world):
    """A returned trip whose pre-trip rear photo already showed the damage."""
    confirmed = fixtures.seed_confirmed_booking(api, world)
    fixtures.record_meter_reading(
        api,
        world,
        confirmed["id"],
        "PRE_TRIP",
        42000,
        120.0,
        "2026-08-29T15:00:00Z",
        as_owner=True,
    )
    for zone in ALL_ZONES:
        fixtures.record_trip_photo(
            api,
            world,
            confirmed["id"],
            PhotoPhase.PRE_TRIP,
            zone,
            damage_flagged=zone == Zone.EXTERIOR_REAR,
            as_owner=True,
            image_ref=f"s3://trip/pre-{zone.lower()}.jpg",
        )
    fixtures.start_trip(api, world, confirmed["id"])
    fixtures.record_post_trip_evidence(api, world, confirmed["id"])
    return fixtures.return_trip(api, world, confirmed["id"])


def test_the_third_information_request_is_refused(api):
    """PRD 3.8: "the pause is permitted only while the claim's `info_rounds_used` is
    strictly below two, and a third information request on a claim that has already
    used its two rounds is refused with `ERR_INFO_ROUND_LIMIT_REACHED`." The claim is
    still sitting in a legal origin state, since "`UNDER_REVIEW` and `INFO_REQUESTED`
    thus form a bounded revision cycle: at most two completed round trips per claim."

    Design: Difficulty/non_linear_state_machine/damage_claim_review_cycle_is_bounded_at_two_info_rounds
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    claim = fixtures.seed_claim_under_review(api, world, returned["id"])
    _complete_info_round(
        api,
        world,
        claim["id"],
        "Send the repair estimate from a certified shop.",
        "Estimate attached.",
    )
    _complete_info_round(
        api,
        world,
        claim["id"],
        "Send a second photograph of the seam.",
        "Second photograph attached.",
    )

    third = api.request_claim_info(
        claim["id"],
        factories.info_request_payload("Third request - one more photo of the seam."),
        CLAIMS_ADJUSTER_HEADERS,
    )
    validate_error(third, ApiErrorId.INFO_ROUND_LIMIT_REACHED, 422)

    stored = validate_success(
        api.get_damage_claim(claim["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["status"] == ClaimStatus.UNDER_REVIEW
    assert stored["info_rounds_used"] == 2
    assert stored["comparison_verdict"] == ComparisonVerdict.NEW_DAMAGE
    assert stored["pre_photo_count"] == 1
    assert stored["post_photo_count"] == 1


def test_each_completed_round_trip_counts_on_the_claim_and_the_booking(api):
    """PRD 3.8: answering moves the claim "`INFO_REQUESTED → UNDER_REVIEW`,
    incrementing the claim's `info_rounds_used` by one, incrementing the booking's
    `info_round_count` by one, and incrementing both the claim's and the booking's
    `version`." The budget is spent by completed loops, not by requests, so the
    second request is still legal while "a third information request on a claim that
    has already used its two rounds is refused with `ERR_INFO_ROUND_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/damage_claim_review_cycle_is_bounded_at_two_info_rounds
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    claim = fixtures.seed_claim_under_review(api, world, returned["id"])

    after_first = _complete_info_round(
        api,
        world,
        claim["id"],
        "Send the repair estimate from a certified shop.",
        "Estimate attached.",
    )
    assert after_first["status"] == ClaimStatus.UNDER_REVIEW
    assert after_first["info_rounds_used"] == 1
    midway = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert midway["info_round_count"] == 1

    after_second = _complete_info_round(
        api,
        world,
        claim["id"],
        "Send a second photograph of the seam.",
        "Second photograph attached.",
    )
    assert after_second["info_rounds_used"] == 2

    booking = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert booking["info_round_count"] == 2
    assert booking["settlement_status"] == SettlementStatus.DISPUTED


def test_a_zone_with_no_post_trip_photograph_has_no_baseline(api):
    """PRD 3.8: intake "requires that the claimed zone have a usable evidentiary
    baseline: there must be at least one `PRE_TRIP` trip photo **and** at least one
    `POST_TRIP` trip photo on the booking for that exact `damage_zone`. A zone with no
    baseline photo, or no comparison photo, is refused with
    `ERR_PHOTO_BASELINE_MISSING` — and this is exactly the boundary that the
    four-of-five photo coverage rule at handover and return leaves reachable."

    Design: Difficulty/boundary_precision_check/damage_zone_with_zero_post_trip_photos_is_the_empty_baseline_boundary
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world, post_zones=FOUR_ZONES)
    assert returned["settlement_status"] == SettlementStatus.RECONCILING

    response = _file_claim(
        api,
        world,
        returned["id"],
        cause_code=CauseCode.TIRE_BLOWOUT,
        damage_zone=Zone.UNDERCARRIAGE,
        claimed_amount_cents=180000,
        description="Stone strike on the fresh-water tank shield.",
    )
    validate_error(response, ApiErrorId.PHOTO_BASELINE_MISSING, 422)

    unchanged = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert unchanged["settlement_status"] == SettlementStatus.RECONCILING
    assert _claim_count(api, returned["id"]) == 0

    _rows, meta = validate_paginated(
        api.list_trip_photos(
            factories.page_params(
                booking_id=returned["id"], phase=PhotoPhase.POST_TRIP
            ),
            PLATFORM_ADMIN_HEADERS,
        )
    )
    assert meta["total_count"] == 4


def test_a_zone_photographed_in_both_phases_admits_the_claim(api):
    """PRD 3.8: the baseline test reads only the claimed zone, and where both phases
    exist the frozen comparison applies: "`pre_photo_count` is the number of those
    photos whose `phase` is `PRE_TRIP`, and `post_photo_count` the number whose
    `phase` is `POST_TRIP`." Intake then "moves the booking's settlement dimension
    `RECONCILING → DISPUTED` and increments the booking's `version`."

    Design: Difficulty/boundary_precision_check/damage_zone_with_zero_post_trip_photos_is_the_empty_baseline_boundary
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world, post_zones=FOUR_ZONES)

    claim = validate_success(
        _file_claim(
            api,
            world,
            returned["id"],
            damage_zone=Zone.EXTERIOR_REAR,
            claimed_amount_cents=180000,
            description="Rear cap cracked.",
        ),
        201,
    )

    assert claim["status"] == ClaimStatus.SUBMITTED
    assert claim["comparison_verdict"] == ComparisonVerdict.NEW_DAMAGE
    assert claim["pre_photo_count"] == 1
    assert claim["post_photo_count"] == 1

    disputed = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert disputed["settlement_status"] == SettlementStatus.DISPUTED


def test_the_comparison_ignores_every_zone_but_the_claimed_one(api):
    """PRD 3.8: "It restricts attention to the booking's trip photos in the claim's
    `damage_zone`, ignoring every other zone entirely." With no flag inside that zone
    the last branch of the precedence applies: "otherwise, if any of the post-trip
    photos in that zone has `damage_flagged` true, the verdict is `NEW_DAMAGE`;
    otherwise the verdict is `NO_VISIBLE_CHANGE`."

    Design: Corner/calculations/photo_comparison_reads_only_the_claimed_zone
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)

    claim = validate_success(
        _file_claim(
            api,
            world,
            returned["id"],
            damage_zone=Zone.INTERIOR,
            description="Dinette panel cracked during the trip",
        ),
        201,
    )

    assert claim["status"] == ClaimStatus.SUBMITTED
    assert claim["comparison_verdict"] == ComparisonVerdict.NO_VISIBLE_CHANGE
    assert claim["pre_photo_count"] == 1
    assert claim["post_photo_count"] == 1
    assert claim["info_rounds_used"] == 0
    assert claim["gross_amount_cents"] == 0

    disputed = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert disputed["settlement_status"] == SettlementStatus.DISPUTED


def test_damage_visible_before_the_trip_beats_the_same_damage_after_it(api):
    """PRD 3.8: "The `comparison_verdict` follows a pinned precedence: if any of the
    pre-trip photos in that zone has `damage_flagged` true, the verdict is
    `PRE_EXISTING`; otherwise, if any of the post-trip photos in that zone has
    `damage_flagged` true, the verdict is `NEW_DAMAGE`; otherwise the verdict is
    `NO_VISIBLE_CHANGE`. A flagged pre-trip photograph therefore beats a flagged
    post-trip photograph — the damage was already there."

    Design: Corner/calculations/flagged_pre_trip_photo_outranks_a_flagged_post_trip_photo
    """
    world = fixtures.seed_marketplace(api)
    returned = _trip_with_flagged_rear_baseline(api, world)

    claim = validate_success(
        _file_claim(
            api,
            world,
            returned["id"],
            damage_zone=Zone.EXTERIOR_REAR,
            description="Rear panel dent claimed after the trip",
        ),
        201,
    )

    assert claim["comparison_verdict"] == ComparisonVerdict.PRE_EXISTING
    assert claim["pre_photo_count"] == 1
    assert claim["post_photo_count"] == 1
    assert claim["status"] == ClaimStatus.SUBMITTED

    disputed = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert disputed["settlement_status"] == SettlementStatus.DISPUTED


def test_three_claims_fill_the_renters_bucket_before_the_plan_pays(api):
    """PRD 3.8: "If the claim's `cause_code` appears in the booking's protection
    plan's `excluded_causes`, `gross_amount_cents` is 0 — **exclusion beats every
    verdict**". Otherwise the verdict factor applies — "10000 basis points, the full
    amount, for `NEW_DAMAGE`; 5000 basis points, half, for `NO_VISIBLE_CHANGE`" — and
    the split follows: "`renter_charge_cents` is the smaller of `gross_amount_cents`
    and the plan's `deductible_cents`. `plan_paid_cents` is `gross_amount_cents` minus
    `renter_charge_cents`. `owner_payout_cents` is the full `gross_amount_cents`".

    Design: Corner/calculations/three_claims_fill_the_deductible_bucket_before_the_plan_pays
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    excluded = validate_success(
        _file_claim(
            api,
            world,
            returned["id"],
            cause_code=CauseCode.AWNING_WIND,
            damage_zone=Zone.ROOF,
            claimed_amount_cents=80000,
            description="Awning arm bent by a gust",
        ),
        201,
    )
    halved = validate_success(
        _file_claim(
            api,
            world,
            returned["id"],
            damage_zone=Zone.INTERIOR,
            description="Dinette panel cracked during the trip",
        ),
        201,
    )
    full = validate_success(
        _file_claim(
            api,
            world,
            returned["id"],
            damage_zone=Zone.EXTERIOR_REAR,
            description="Rear wall crushed against a post",
        ),
        201,
    )
    for claim_id in (excluded["id"], halved["id"], full["id"]):
        fixtures.start_claim_review(api, claim_id)

    denied = validate_success(
        api.adjudicate_claim(
            excluded["id"], factories.adjudication_payload(), CLAIMS_ADJUSTER_HEADERS
        ),
        200,
    )
    assert denied["status"] == ClaimStatus.DENIED
    assert denied["gross_amount_cents"] == 0
    assert denied["renter_charge_cents"] == 0
    assert denied["plan_paid_cents"] == 0
    assert denied["owner_payout_cents"] == 0

    partial = validate_success(
        api.adjudicate_claim(
            halved["id"], factories.adjudication_payload(), CLAIMS_ADJUSTER_HEADERS
        ),
        200,
    )
    assert partial["status"] == ClaimStatus.PARTIAL
    assert partial["gross_amount_cents"] == 110000
    assert partial["renter_charge_cents"] == 110000
    assert partial["plan_paid_cents"] == 0
    assert partial["owner_payout_cents"] == 110000

    approved = validate_success(
        api.adjudicate_claim(
            full["id"], factories.adjudication_payload(), CLAIMS_ADJUSTER_HEADERS
        ),
        200,
    )
    assert approved["status"] == ClaimStatus.APPROVED
    assert approved["gross_amount_cents"] == 220000
    assert approved["renter_charge_cents"] == 150000
    assert approved["plan_paid_cents"] == 70000
    assert approved["owner_payout_cents"] == 220000

    booking = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert booking["settlement_status"] == SettlementStatus.RECONCILING
    assert booking["final_total_cents"] == 411876
    assert booking["balance_due_cents"] == 265813

    rows = fixtures.collect_ledger_entries(api, returned["id"])
    assert len(rows) == 6
    assert sum(row["amount_cents"] for row in rows) == 0


def test_a_submitted_claim_cannot_be_adjudicated(api):
    """PRD 3.8: adjudication is the adjuster's decision on a claim already in review,
    since a `ClaimsAdjuster` "opens a submitted claim, moving it `SUBMITTED →
    UNDER_REVIEW` and incrementing its `version`". PRD 2.8 rung 12: "**Claim state**
    — the claim's `status` is a legal origin for the requested claim transition,
    otherwise `ERR_CLAIM_STATE_INVALID` (409). Applies to opening review, requesting
    information, responding to an information request, adjudication and withdrawal".

    Design: Corner/errors/adjudicating_a_claim_before_review_is_rejected
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    claim = validate_success(
        _file_claim(
            api,
            world,
            returned["id"],
            damage_zone=Zone.INTERIOR,
            description="Dinette panel cracked during the trip",
        ),
        201,
    )
    assert claim["status"] == ClaimStatus.SUBMITTED

    response = api.adjudicate_claim(
        claim["id"], factories.adjudication_payload(), CLAIMS_ADJUSTER_HEADERS
    )
    validate_error(response, ApiErrorId.CLAIM_STATE_INVALID, 409)

    stored = validate_success(
        api.get_damage_claim(claim["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["status"] == ClaimStatus.SUBMITTED
    assert stored["gross_amount_cents"] == 0
    assert stored["renter_charge_cents"] == 0


def test_an_override_amount_without_a_reason_is_refused(api):
    """PRD 3.8: "Adjudication is the adjuster's decision, and it takes two optional
    inputs: an `override_amount_cents` manual gross figure and an `override_reason`
    justification. Whenever `override_amount_cents` is supplied, `override_reason`
    must be present and non-empty, otherwise the adjudication is refused with
    `ERR_ADJUDICATION_OVERRIDE_REASON_REQUIRED`; that same requirement guards all
    three adjudication outcomes identically."

    Design: Corner/errors/override_amount_without_a_reason_is_rejected
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    claim = fixtures.seed_claim_under_review(
        api,
        world,
        returned["id"],
        damage_zone=Zone.INTERIOR,
        description="Dinette panel cracked during the trip",
    )
    assert claim["status"] == ClaimStatus.UNDER_REVIEW

    response = api.adjudicate_claim(
        claim["id"],
        factories.adjudication_payload(override_amount_cents=100000),
        CLAIMS_ADJUSTER_HEADERS,
    )
    validate_error(response, ApiErrorId.ADJUDICATION_OVERRIDE_REASON_REQUIRED, 422)

    stored = validate_success(
        api.get_damage_claim(claim["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["status"] == ClaimStatus.UNDER_REVIEW
    assert stored["override_amount_cents"] is None
    assert stored["gross_amount_cents"] == 0


def test_a_claim_filed_after_settlement_is_refused(api):
    """PRD 3.8: "Intake requires the booking's `settlement_status` to be either
    `RECONCILING` or `DISPUTED` — the second value is deliberate, so that a further
    claim may be filed while an earlier one is still open — and any other settlement
    state is refused with `ERR_BOOKING_SETTLEMENT_CLOSED`." PRD 2.8 rung 15 adds that
    "A booking already `SETTLED` or `REFUNDED` accepts no claim activity whatsoever."

    Design: Corner/errors/claim_filed_after_settlement_is_rejected
    """
    world = fixtures.seed_marketplace(api)
    settled = fixtures.seed_settled_booking(api, world)
    assert settled["settlement_status"] == SettlementStatus.SETTLED

    response = _file_claim(
        api,
        world,
        settled["id"],
        cause_code=CauseCode.TIRE_BLOWOUT,
        damage_zone=Zone.UNDERCARRIAGE,
        claimed_amount_cents=90000,
        description="Blowout discovered a week after settlement",
    )
    validate_error(response, ApiErrorId.BOOKING_SETTLEMENT_CLOSED, 409)

    assert _claim_count(api, settled["id"]) == 0

    stored = validate_success(
        api.get_booking(settled["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["settlement_status"] == SettlementStatus.SETTLED
    assert stored["final_total_cents"] == 151876
