"""
Redemption claim adjudication and the transaction edits (PRD 3.7).

Three families of facts are pinned here: the strict boundary between a line
charged exactly at the ceiling and a line charged one cent above it, the
dependency of adjudication on a *published* price cycle rather than a merely
closed one, and the effect of delisting a UPC between claim submission and
adjudication. Every precondition is built through the documented endpoints.
"""

from typing import Any, Dict, List

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_ONE,
    DEFAULT_LOGICAL_CLOCK,
    DEFAULT_LOGICAL_CLOCK_ISO,
    SUPERVISOR_HEADERS,
    AdjustmentReasonCode,
    AdjustmentStatus,
    CeilingBasis,
    CeilingStatus,
    ClaimStatus,
    EditCode,
    EditResult,
    FoodItemStatus,
    PriceCycleStatus,
    SubmissionStatus,
    SupersededReason,
    assert_adjudicated_total_is_sum_of_allowed,
    assert_authorized_food_item,
    assert_ceiling_derivation,
    assert_claim_line,
    assert_claim_line_counts,
    assert_field_values,
    assert_line_recoupments,
    assert_price_ceiling,
    assert_price_submission,
    assert_proration_sums_per_line,
    assert_redemption_claim,
    assert_reimbursement_adjustment,
    assert_vendor,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# The maximum allowable reimbursement the canonical single-price setup publishes
# for milk: one contributing shelf price of 320 cents on the statewide fallback
# basis, the five per cent allowance applied, the cap of 1.25 x 320 = 400 idle,
# and one rounding at the end -> 320 x 1.05 = 336.0 -> 336.
_MILK_MAR_CENTS = 336
# The same derivation over a juice shelf price of 118 cents: 118 x 1.05 = 123.9,
# cap 1.25 x 118 = 147.5 idle, one rounding -> 124.
_JUICE_SHELF_PRICE_CENTS = 118
_JUICE_MAR_CENTS = 124

_DELIST_REASON = "Bottler withdrew the 64 oz size"


def _lines_of(api, claim_id: str) -> List[Dict[str, Any]]:
    """The claim's lines in ascending ``line_number`` order."""
    lines, _ = validate_paginated(
        api.list_claim_lines(
            ANALYST_HEADERS, {"redemption_claim_id": claim_id, "limit": 100}
        )
    )
    return sorted(lines, key=lambda line: line["line_number"])


def _claim_at_around_the_milk_ceiling(api) -> Dict[str, Any]:
    """
    The published milk ceiling plus a three-line claim straddling it.

    The lines are charged exactly at the ceiling, one cent above it, and one cent
    below it, one container each.
    """
    fixtures.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    bundle = fixtures.published_ceiling_setup(api)
    assert bundle["milk_ceiling"]["mar_cents"] == _MILK_MAR_CENTS, (
        f"setup expected a published milk ceiling of {_MILK_MAR_CENTS}, "
        f"got {bundle['milk_ceiling']}"
    )
    bundle["claim"] = fixtures.file_claim(
        api,
        bundle["vendor"]["id"],
        [
            factories.claim_line_payload(
                1, fixtures.MILK_UPC, 1, 336, medical_doc_on_file=False
            ),
            factories.claim_line_payload(
                2, fixtures.MILK_UPC, 1, 337, medical_doc_on_file=False
            ),
            factories.claim_line_payload(
                3, fixtures.MILK_UPC, 1, 335, medical_doc_on_file=False
            ),
        ],
        claim_month="2026-07",
    )
    return bundle


def _claim_awaiting_a_published_cycle(api) -> Dict[str, Any]:
    """An AUTHORIZED vendor, a still-OPEN cycle, and one SUBMITTED claim on it."""
    fixtures.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    bundle = fixtures.authorized_vendor_setup(api)
    bundle["claim"] = fixtures.file_claim(
        api,
        bundle["vendor"]["id"],
        [
            factories.claim_line_payload(
                1, fixtures.MILK_UPC, 2, 400, medical_doc_on_file=False
            )
        ],
        claim_month="2026-07",
    )
    return bundle


def _claim_over_milk_and_juice(api) -> Dict[str, Any]:
    """Published ceilings for milk and juice, and a two-line claim over both."""
    fixtures.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    bundle = fixtures.published_ceiling_setup(
        api, with_juice=True, juice_price_cents=_JUICE_SHELF_PRICE_CENTS
    )
    bundle["claim"] = fixtures.file_claim(
        api,
        bundle["vendor"]["id"],
        [
            factories.claim_line_payload(
                1, fixtures.MILK_UPC, 1, 336, medical_doc_on_file=False
            ),
            factories.claim_line_payload(
                2, fixtures.JUICE_UPC, 2, 124, medical_doc_on_file=False
            ),
        ],
        claim_month="2026-07",
    )
    return bundle


# ---------------------------------------------------------------------------
# The E05 boundary and the per-line proration rounding
# ---------------------------------------------------------------------------


def test_claim_line_charged_exactly_at_the_ceiling_is_accepted_at_full_price(api):
    """
    Only a charge strictly above the ceiling is reduced; equality pays in full.

    "**`E05`** — a ceiling exists and was consulted, so the ceiling's `mar_cents` is
    recorded on the line as `applied_mar_cents`."
    "If the line's `charged_unit_price_cents` is strictly greater than that ceiling,
    the line's `edit_result` becomes `ACCEPTED_REDUCED` with `edit_code` `E05`, and
    its `allowed_cents` is the ceiling's `mar_cents` multiplied by `quantity` — the
    vendor is paid at the ceiling, not at what it charged."
    "If the charged price equals or falls below the ceiling, the line's `edit_result`
    is `ACCEPTED`, its `edit_code` stays null, and its `allowed_cents` is
    `charged_unit_price_cents` multiplied by `quantity`."
    "The boundary matters: a charge exactly equal to the ceiling is accepted at full
    price, not reduced."

    Design: Difficulty/boundary_precision_check/claim_line_at_exactly_the_ceiling_is_accepted_not_reduced
    """
    bundle = _claim_at_around_the_milk_ceiling(api)

    validate_success(
        api.adjudicate_claim(bundle["claim"]["id"], None, ANALYST_HEADERS)
    )

    line_one, line_two, line_three = _lines_of(api, bundle["claim"]["id"])
    assert_claim_line(
        line_one,
        line_number=1,
        edit_result=EditResult.ACCEPTED.value,
        edit_code=None,
        applied_mar_cents=336,
        allowed_cents=336,  # 336 charged == 336 ceiling, paid at 336 x 1
    )
    assert_claim_line(
        line_two,
        line_number=2,
        edit_result=EditResult.ACCEPTED_REDUCED.value,
        edit_code=EditCode.E05.value,
        applied_mar_cents=336,
        allowed_cents=336,  # 337 charged > 336 ceiling, paid at the ceiling x 1
    )
    assert_claim_line(
        line_three,
        line_number=3,
        edit_result=EditResult.ACCEPTED.value,
        edit_code=None,
        applied_mar_cents=336,
        allowed_cents=335,  # 335 charged < 336 ceiling, paid at 335 x 1
    )


def test_claim_aggregates_tally_the_accepted_and_reduced_lines(api):
    """
    Adjudication sums the allowed amounts and counts each edit outcome.

    "`adjudicated_total_cents` is the sum of `allowed_cents` over all lines."
    "`net_payable_cents` is that total less the sum of `recoupment_cents` over the
    claim's reimbursement adjustments whose `status` is `APPLIED` — normally zero at
    first adjudication."
    "`accepted_line_count`, `reduced_line_count`, and `rejected_line_count` count the
    lines whose `edit_result` is `ACCEPTED`, `ACCEPTED_REDUCED`, and `REJECTED`
    respectively, over every line regardless of outcome."
    "Note that `submitted_total_cents` was fixed at claim creation and is not
    recomputed here."
    "Its identifier is stored on the claim as `governing_price_cycle_id`, and
    `adjudicated_at` takes the logical clock."

    Design: Difficulty/boundary_precision_check/claim_line_at_exactly_the_ceiling_is_accepted_not_reduced
    """
    bundle = _claim_at_around_the_milk_ceiling(api)

    validate_success(
        api.adjudicate_claim(bundle["claim"]["id"], None, ANALYST_HEADERS)
    )

    claim = validate_success(
        api.get_redemption_claim(bundle["claim"]["id"], ANALYST_HEADERS)
    )
    assert_redemption_claim(
        claim,
        status=ClaimStatus.ADJUDICATED.value,
        line_count=3,
        submitted_total_cents=1008,  # 336 + 337 + 335, fixed at claim creation
        adjudicated_total_cents=1007,  # 336 + 336 + 335
        net_payable_cents=1007,  # no applied adjustment yet
        accepted_line_count=2,
        reduced_line_count=1,
        rejected_line_count=0,
        governing_price_cycle_id=bundle["cycle"]["id"],
        adjudicated_at=DEFAULT_LOGICAL_CLOCK_ISO,
    )

    lines = _lines_of(api, bundle["claim"]["id"])
    assert_adjudicated_total_is_sum_of_allowed(claim, lines)
    assert_claim_line_counts(claim, lines)


def test_recoupment_share_is_rounded_per_line_before_the_shares_are_summed(api):
    """
    Each line's prorated share rounds half up on its own and the shares then add.

    "**Per line first, then sum.** When a reimbursement adjustment prorates a
    recoupment across claim lines, each line's share is rounded half up to a whole
    cent individually and the shares are then added."
    "The total is whatever that sum comes to; the residual difference against
    rounding the claim total once is not redistributed to any line."
    "The participating lines are the claim's ClaimLines whose `edit_result` is
    `ACCEPTED` or `ACCEPTED_REDUCED`; lines rejected by any edit are excluded and
    contribute nothing."
    "Those lines are ordered by ascending `line_number`, and for each one the server
    records an entry in `line_recoupments` holding the `claim_line_id`, that line's
    `allowed_cents`, and a `recoupment_cents` equal to the line's `allowed_cents`
    multiplied by the `recoupment_rate`, rounded half up to a whole cent."
    "The adjustment's own `recoupment_cents` is the sum of those per-line figures."

    Design: Difficulty/boundary_precision_check/claim_line_at_exactly_the_ceiling_is_accepted_not_reduced
    """
    bundle = _claim_at_around_the_milk_ceiling(api)
    claim = fixtures.adjudicate(api, bundle["claim"]["id"])

    adjustment = validate_success(
        api.create_reimbursement_adjustment(
            factories.reimbursement_adjustment_payload(
                claim["id"],
                claim["version"],
                reason_code=AdjustmentReasonCode.EDIT_ERROR.value,
                recoupment_rate=0.005,
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )

    assert_line_recoupments(
        adjustment,
        [
            {"allowed_cents": 336, "recoupment_cents": 2},  # 336 x 0.005 = 1.68 -> 2
            {"allowed_cents": 336, "recoupment_cents": 2},  # 336 x 0.005 = 1.68 -> 2
            {"allowed_cents": 335, "recoupment_cents": 2},  # 335 x 0.005 = 1.675 -> 2
        ],
    )
    assert_field_values(adjustment, recoupment_cents=6)  # 2 + 2 + 2
    assert adjustment["recoupment_cents"] != 5, (
        "rounding the claim total once (1007 x 0.005 = 5.035 -> 5) is not the rule"
    )
    assert_proration_sums_per_line(adjustment)


def test_pending_adjustment_leaves_the_claim_money_untouched(api):
    """
    Raising an adjustment only prorates it; no money moves until it is applied.

    "The adjustment begins in `status` `PENDING` with `created_by_user_id` stamped
    from the acting `X-User-ID` and with `applied_by_user_id`, `applied_at`,
    `reversed_at`, and `reversal_reason` all null."
    "**Proration** is computed at create time, not at apply time."
    "A successful create increments the claim's `version` by one."
    "**Applying** the adjustment is a supervisor action and moves it `PENDING →
    APPLIED`."
    "On success, `applied_by_user_id` and `applied_at` are stamped, and money moves
    in three places at once: the claim advances `ADJUDICATED → ADJUSTED` with its
    `net_payable_cents` reduced by the adjustment's `recoupment_cents`, each
    participating claim line has its `recouped_cents` increased by that line's
    prorated share, and the vendor's `recoupment_balance_cents` rises by the
    adjustment's `recoupment_cents`."

    Design: Difficulty/boundary_precision_check/claim_line_at_exactly_the_ceiling_is_accepted_not_reduced
    """
    bundle = _claim_at_around_the_milk_ceiling(api)
    claim = fixtures.adjudicate(api, bundle["claim"]["id"])

    adjustment = validate_success(
        api.create_reimbursement_adjustment(
            factories.reimbursement_adjustment_payload(
                claim["id"],
                claim["version"],
                reason_code=AdjustmentReasonCode.EDIT_ERROR.value,
                recoupment_rate=0.005,
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )
    assert_reimbursement_adjustment(
        adjustment,
        status=AdjustmentStatus.PENDING.value,
        created_by_user_id=ANALYST_ONE,
        applied_by_user_id=None,
        applied_at=None,
        reversed_at=None,
        reversal_reason=None,
    )

    after = validate_success(api.get_redemption_claim(claim["id"], ANALYST_HEADERS))
    assert_redemption_claim(
        after,
        status=ClaimStatus.ADJUDICATED.value,  # not ADJUSTED: nothing was applied
        net_payable_cents=1007,  # unchanged while the adjustment is only PENDING
        version=claim["version"] + 1,
    )

    for line in _lines_of(api, claim["id"]):
        assert line["recouped_cents"] == 0, (
            f"no line may be charged before the adjustment is applied: {line}"
        )

    vendor = validate_success(api.get_vendor(bundle["vendor"]["id"], ANALYST_HEADERS))
    assert_vendor(vendor, recoupment_balance_cents=0)


# ---------------------------------------------------------------------------
# Adjudication depends on another aggregate reaching PUBLISHED
# ---------------------------------------------------------------------------


def test_adjudication_is_refused_until_a_price_cycle_reaches_published(api):
    """
    A closed cycle with provisional ceilings still does not unblock adjudication.

    "Adjudication requires a published price cycle to exist at or before the logical
    clock, and without one the request is refused with
    `ERR_NO_PUBLISHED_PRICE_CYCLE`."
    "The governing cycle is chosen exactly as the compliance-buy pricing chooses it:
    among cycles whose `status` is `PUBLISHED` and whose `published_at` is at or
    before the logical clock, the one with the greatest `published_at`, and where two
    share that instant, the one with the earlier `created_at`."
    "The claim's `governing_price_cycle_id`, `adjudicated_total_cents`,
    `net_payable_cents`, `adjudicated_at`, and `paid_at` are all null until
    adjudication, and `accepted_line_count`, `reduced_line_count`, and
    `rejected_line_count` all start at 0."
    "For each pair with a non-empty candidate set, a PriceCeiling row is written with
    `status` `PROVISIONAL`; the number written becomes the cycle's
    `provisional_ceiling_count`, and the number of pairs skipped for having an empty
    candidate set becomes its `skipped_pair_count`."

    Design: Difficulty/cross_entity_state_dependency/adjudicate_blocked_when_no_published_price_cycle
    """
    bundle = _claim_awaiting_a_published_cycle(api)
    claim_id = bundle["claim"]["id"]

    validate_error(
        api.adjudicate_claim(claim_id, None, ANALYST_HEADERS),
        "ERR_NO_PUBLISHED_PRICE_CYCLE",
    )
    while_open = validate_success(api.get_redemption_claim(claim_id, ANALYST_HEADERS))
    assert_redemption_claim(
        while_open,
        status=ClaimStatus.SUBMITTED.value,
        governing_price_cycle_id=None,
        adjudicated_total_cents=None,
        net_payable_cents=None,
        adjudicated_at=None,
        accepted_line_count=0,
        reduced_line_count=0,
        rejected_line_count=0,
    )

    validate_success(
        api.close_price_cycle(bundle["cycle"]["id"], None, SUPERVISOR_HEADERS)
    )
    closed = validate_success(
        api.get_price_cycle(bundle["cycle"]["id"], SUPERVISOR_HEADERS)
    )
    assert_field_values(
        closed,
        status=PriceCycleStatus.CLOSED.value,
        provisional_ceiling_count=1,
        skipped_pair_count=0,
    )
    provisional_rows, meta = validate_paginated(
        api.list_price_ceilings(
            SUPERVISOR_HEADERS,
            {
                "peer_group_id": bundle["peer_group"]["id"],
                "food_item_id": bundle["milk_item"]["id"],
                "price_cycle_id": bundle["cycle"]["id"],
                "status": CeilingStatus.PROVISIONAL.value,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 1, f"expected one provisional row, got {meta}"
    assert_price_ceiling(provisional_rows[0], mar_cents=_MILK_MAR_CENTS)

    validate_error(
        api.adjudicate_claim(claim_id, None, ANALYST_HEADERS),
        "ERR_NO_PUBLISHED_PRICE_CYCLE",
    )
    while_closed = validate_success(api.get_redemption_claim(claim_id, ANALYST_HEADERS))
    assert_redemption_claim(
        while_closed,
        status=ClaimStatus.SUBMITTED.value,
        governing_price_cycle_id=None,
        adjudicated_at=None,
    )


def test_adjudication_succeeds_once_the_cycle_publishes_its_ceilings(api):
    """
    Publication supplies the adjudication basis and the same request then succeeds.

    "Publishing moves a cycle `CLOSED → PUBLISHED` — again `ERR_INVALID_CYCLE_STATE`
    for any other status — stamps `published_at`, and performs three passes."
    "First, every PriceCeiling of this cycle still in `PROVISIONAL` moves to
    `SUPERSEDED` with `superseded_reason` `PROVISIONAL_REPLACED`."
    "When the peer count falls short, `basis` is `STATEWIDE_FALLBACK` and the
    candidate set is rebuilt with the identical filter but **without** the peer-group
    restriction, restricted to submissions from vendors whose own peer group has
    `status` `ACTIVE`; that broader list is likewise sorted ascending by price with
    the `created_at` tie-break."
    "A `VendorUnitAnalyst` adjudicates a claim that is still `SUBMITTED`, moving it
    `SUBMITTED → ADJUDICATED`; any other status is refused with
    `ERR_INVALID_CLAIM_STATE`."
    "Its identifier is stored on the claim as `governing_price_cycle_id`, and
    `adjudicated_at` takes the logical clock."

    Design: Difficulty/cross_entity_state_dependency/adjudicate_blocked_when_no_published_price_cycle
    """
    bundle = _claim_awaiting_a_published_cycle(api)
    fixtures.close_cycle(api, bundle["cycle"]["id"])
    provisional_rows, _ = validate_paginated(
        api.list_price_ceilings(
            SUPERVISOR_HEADERS,
            {
                "price_cycle_id": bundle["cycle"]["id"],
                "status": CeilingStatus.PROVISIONAL.value,
                "limit": 100,
            },
        )
    )
    provisional_id = provisional_rows[0]["id"]

    validate_success(
        api.publish_ceilings(bundle["cycle"]["id"], None, SUPERVISOR_HEADERS)
    )
    published = validate_success(
        api.get_price_cycle(bundle["cycle"]["id"], SUPERVISOR_HEADERS)
    )
    assert_field_values(
        published,
        status=PriceCycleStatus.PUBLISHED.value,
        published_ceiling_count=1,
        skipped_pair_count=0,
    )
    assert_price_ceiling(
        validate_success(api.get_price_ceiling(provisional_id, SUPERVISOR_HEADERS)),
        status=CeilingStatus.SUPERSEDED.value,
        superseded_reason=SupersededReason.PROVISIONAL_REPLACED.value,
    )
    active = fixtures.active_ceiling_for(
        api, bundle["peer_group"]["id"], bundle["milk_item"]["id"]
    )
    assert_ceiling_derivation(
        active,
        basis=CeilingBasis.STATEWIDE_FALLBACK.value,
        peer_submission_count=1,  # one peer price, short of min_submissions_for_ceiling 3
        contributing_submission_count=1,
        base_cents=320.0,
        cap_cents=400.0,  # 1.25 x 320
        cap_binding=False,  # 400.0 is not strictly less than 320 x 1.05 = 336.0
        mar_cents=_MILK_MAR_CENTS,
    )

    claim = validate_success(
        api.adjudicate_claim(bundle["claim"]["id"], None, ANALYST_HEADERS)
    )
    assert_redemption_claim(
        claim,
        status=ClaimStatus.ADJUDICATED.value,
        governing_price_cycle_id=bundle["cycle"]["id"],
        adjudicated_at=DEFAULT_LOGICAL_CLOCK_ISO,
    )


def test_line_charged_above_the_published_ceiling_is_reduced_to_the_ceiling(api):
    """
    A line charged over the ceiling is paid at the ceiling times its quantity.

    "**`E05`** — a ceiling exists and was consulted, so the ceiling's `mar_cents` is
    recorded on the line as `applied_mar_cents`."
    "If the line's `charged_unit_price_cents` is strictly greater than that ceiling,
    the line's `edit_result` becomes `ACCEPTED_REDUCED` with `edit_code` `E05`, and
    its `allowed_cents` is the ceiling's `mar_cents` multiplied by `quantity` — the
    vendor is paid at the ceiling, not at what it charged."
    "At creation the claim's `status` is `SUBMITTED`, its `line_count` is the number
    of lines created, and its `submitted_total_cents` is the sum over lines of
    `quantity` multiplied by `charged_unit_price_cents`."
    "`adjudicated_total_cents` is the sum of `allowed_cents` over all lines."
    "`accepted_line_count`, `reduced_line_count`, and `rejected_line_count` count the
    lines whose `edit_result` is `ACCEPTED`, `ACCEPTED_REDUCED`, and `REJECTED`
    respectively, over every line regardless of outcome."

    Design: Difficulty/cross_entity_state_dependency/adjudicate_blocked_when_no_published_price_cycle
    """
    bundle = _claim_awaiting_a_published_cycle(api)
    fixtures.close_cycle(api, bundle["cycle"]["id"])
    fixtures.publish_cycle(api, bundle["cycle"]["id"])

    claim = validate_success(
        api.adjudicate_claim(bundle["claim"]["id"], None, ANALYST_HEADERS)
    )

    (line,) = _lines_of(api, bundle["claim"]["id"])
    assert_claim_line(
        line,
        line_number=1,
        edit_result=EditResult.ACCEPTED_REDUCED.value,
        edit_code=EditCode.E05.value,
        applied_mar_cents=_MILK_MAR_CENTS,
        allowed_cents=672,  # 336 ceiling x quantity 2, not 400 charged x 2
    )
    assert_redemption_claim(
        claim,
        line_count=1,
        submitted_total_cents=800,  # 400 charged x 2 containers
        adjudicated_total_cents=672,
        net_payable_cents=672,
        accepted_line_count=0,
        reduced_line_count=1,
        rejected_line_count=0,
    )


# ---------------------------------------------------------------------------
# A UPC delisted between claim submission and adjudication
# ---------------------------------------------------------------------------


def test_delisting_supersedes_the_ceiling_but_spares_a_published_cycles_submission(api):
    """
    The delist cascade retires the item's ceilings and stops at a published cycle.

    "In the first hop, the item's `status` becomes `DELISTED` while `delisted_at`
    takes the logical clock and `delist_reason` is stored."
    "In the second hop, because the item is no longer authorized, every PriceCeiling
    for that item whose `status` is `PROVISIONAL` or `ACTIVE` moves to `SUPERSEDED`
    with `superseded_reason` `ITEM_DELISTED`."
    "In the third hop, because no ceiling remains to serve as an adjudication basis,
    every PriceSubmission for that item whose `status` is `SUBMITTED` or `ACCEPTED`,
    and whose price cycle is itself `OPEN` or `CLOSED`, moves to `VOIDED` with
    `voided_reason` `ITEM_DELISTED` — submissions belonging to a `PUBLISHED` cycle
    are left alone, because that cycle's history is closed."
    "In the fourth hop, because those submissions were voided, each affected vendor's
    `accepted_submission_count` is decremented and its `price_submission_complete` is
    recomputed, turning false when the delisted item had `required_for_authorization`
    set to true."

    Design: Difficulty/cross_entity_state_dependency/claim_line_rejected_when_authorized_item_delisted_after_submission
    """
    bundle = _claim_over_milk_and_juice(api)
    assert bundle["juice_ceiling"]["mar_cents"] == _JUICE_MAR_CENTS, (
        f"setup expected a published juice ceiling of {_JUICE_MAR_CENTS}, "
        f"got {bundle['juice_ceiling']}"
    )

    validate_success(
        api.delist_authorized_food_item(
            bundle["juice_item"]["id"],
            factories.delist_payload(delist_reason=_DELIST_REASON),
            SUPERVISOR_HEADERS,
        )
    )

    item = validate_success(
        api.get_authorized_food_item(bundle["juice_item"]["id"], SUPERVISOR_HEADERS)
    )
    assert_authorized_food_item(
        item,
        status=FoodItemStatus.DELISTED.value,
        delisted_at=DEFAULT_LOGICAL_CLOCK_ISO,
        delist_reason=_DELIST_REASON,
    )

    ceiling = validate_success(
        api.get_price_ceiling(bundle["juice_ceiling"]["id"], SUPERVISOR_HEADERS)
    )
    assert_price_ceiling(
        ceiling,
        status=CeilingStatus.SUPERSEDED.value,
        superseded_reason=SupersededReason.ITEM_DELISTED.value,
        mar_cents=_JUICE_MAR_CENTS,
    )

    submission = validate_success(
        api.get_price_submission(bundle["juice_submission"]["id"], SUPERVISOR_HEADERS)
    )
    assert_price_submission(
        submission,
        status=SubmissionStatus.ACCEPTED.value,
        voided_reason=None,
    )

    vendor = validate_success(
        api.get_vendor(bundle["vendor"]["id"], SUPERVISOR_HEADERS)
    )
    assert_vendor(
        vendor,
        accepted_submission_count=2,  # milk and juice, neither voided
        price_submission_complete=True,  # the delisted juice item was not required
    )


def test_claim_line_for_a_delisted_upc_is_rejected_while_its_sibling_adjudicates(api):
    """
    Item resolution reads the item's current status, so one line falls to E01.

    "For each line the item is resolved by matching the line's `upc` against the
    authorized food list, using the item's **current** `status` rather than whatever
    it was during `claim_month`; the resolved identifier is stored as the line's
    `food_item_id`, and stays null when the UPC does not resolve."
    "**`E01`** — the UPC did not resolve to any authorized food item, or the resolved
    item's `status` is `DELISTED`. The line's `edit_result` becomes `REJECTED` and its
    `allowed_cents` is 0."
    "Note that `applied_mar_cents` is set only when a ceiling was actually consulted;
    a line rejected by `E01`, `E02`, `E03`, or `E04` leaves it null."
    "If the charged price equals or falls below the ceiling, the line's `edit_result`
    is `ACCEPTED`, its `edit_code` stays null, and its `allowed_cents` is
    `charged_unit_price_cents` multiplied by `quantity`."

    Design: Difficulty/cross_entity_state_dependency/claim_line_rejected_when_authorized_item_delisted_after_submission
    """
    bundle = _claim_over_milk_and_juice(api)
    validate_success(
        api.delist_authorized_food_item(
            bundle["juice_item"]["id"],
            factories.delist_payload(delist_reason=_DELIST_REASON),
            SUPERVISOR_HEADERS,
        )
    )

    validate_success(
        api.adjudicate_claim(bundle["claim"]["id"], None, ANALYST_HEADERS)
    )

    milk_line, juice_line = _lines_of(api, bundle["claim"]["id"])
    assert_claim_line(
        juice_line,
        line_number=2,
        food_item_id=bundle["juice_item"]["id"],
        edit_result=EditResult.REJECTED.value,
        edit_code=EditCode.E01.value,
        applied_mar_cents=None,
        allowed_cents=0,
    )
    assert_claim_line(
        milk_line,
        line_number=1,
        food_item_id=bundle["milk_item"]["id"],
        edit_result=EditResult.ACCEPTED.value,
        edit_code=None,
        applied_mar_cents=_MILK_MAR_CENTS,
        allowed_cents=336,  # 336 charged == 336 ceiling, x quantity 1
    )


def test_claim_totals_exclude_the_rejected_delisted_line(api):
    """
    The rejected line contributes nothing to the adjudicated total.

    "`adjudicated_total_cents` is the sum of `allowed_cents` over all lines."
    "`net_payable_cents` is that total less the sum of `recoupment_cents` over the
    claim's reimbursement adjustments whose `status` is `APPLIED` — normally zero at
    first adjudication."
    "At creation the claim's `status` is `SUBMITTED`, its `line_count` is the number
    of lines created, and its `submitted_total_cents` is the sum over lines of
    `quantity` multiplied by `charged_unit_price_cents`."
    "`accepted_line_count`, `reduced_line_count`, and `rejected_line_count` count the
    lines whose `edit_result` is `ACCEPTED`, `ACCEPTED_REDUCED`, and `REJECTED`
    respectively, over every line regardless of outcome."

    Design: Difficulty/cross_entity_state_dependency/claim_line_rejected_when_authorized_item_delisted_after_submission
    """
    bundle = _claim_over_milk_and_juice(api)
    validate_success(
        api.delist_authorized_food_item(
            bundle["juice_item"]["id"],
            factories.delist_payload(delist_reason=_DELIST_REASON),
            SUPERVISOR_HEADERS,
        )
    )

    claim = validate_success(
        api.adjudicate_claim(bundle["claim"]["id"], None, ANALYST_HEADERS)
    )

    assert_redemption_claim(
        claim,
        status=ClaimStatus.ADJUDICATED.value,
        line_count=2,
        submitted_total_cents=584,  # 336 x 1 plus 124 x 2
        adjudicated_total_cents=336,  # only the milk line is allowed
        net_payable_cents=336,
        accepted_line_count=1,
        reduced_line_count=0,
        rejected_line_count=1,
    )
    assert_adjudicated_total_is_sum_of_allowed(
        claim, _lines_of(api, bundle["claim"]["id"])
    )
