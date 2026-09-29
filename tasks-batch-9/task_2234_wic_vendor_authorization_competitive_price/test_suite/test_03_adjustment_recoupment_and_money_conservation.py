"""
Reimbursement adjustment proration, the paid-claim rejection ladder, and the
apply-then-reverse money conservation of PRD 2.6, 2.7, 2.8, 2.9 and 3.8.

Every test builds its own state from scratch through the documented endpoints,
because the server is restarted against an empty database before each one.
"""

from typing import Any, Dict, List

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_TWO_HEADERS,
    DEFAULT_LOGICAL_CLOCK,
    DEFAULT_LOGICAL_CLOCK_ISO,
    SUPERVISOR_HEADERS,
    SUPERVISOR_ONE,
    AdjustmentReasonCode,
    AdjustmentStatus,
    ApiErrorId,
    CeilingBasis,
    ClaimStatus,
    EditResult,
    assert_ceiling_derivation,
    assert_claim_line_counts,
    assert_field_values,
    assert_line_recoupments,
    assert_proration_sums_per_line,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# The juice shelf price the single accepted submission reports, and the ceiling it
# derives: one peer submission against a min_submissions_for_ceiling of 3 falls
# short, so the basis is STATEWIDE_FALLBACK over that same single price; the base
# is 118, the allowance-adjusted figure is 118 x 1.05 = 123.90, the statewide cap
# is 1.25 x 118 = 147.50 and is therefore idle, and the single rounding half up at
# the end gives 124.
_JUICE_SHELF_PRICE_CENTS = 118
_JUICE_CEILING_CENTS = 124

_REVERSAL_REASON = "Overcharge finding withdrawn after vendor produced shelf tags"


def _three_juice_lines_at_the_ceiling() -> List[Dict[str, Any]]:
    """Three one-container juice lines charged exactly the published ceiling."""
    return [
        factories.claim_line_payload(
            line_number, fixtures.JUICE_UPC, 1, _JUICE_CEILING_CENTS
        )
        for line_number in (1, 2, 3)
    ]


def _adjudicated_three_line_juice_claim(api) -> Dict[str, Any]:
    """
    The catalogue, an AUTHORIZED vendor, a published juice ceiling of 124 cents,
    and one adjudicated claim whose three juice lines were each accepted at 124.
    """
    fixtures.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    return fixtures.adjudicated_claim_setup(
        api,
        lines=_three_juice_lines_at_the_ceiling(),
        with_juice=True,
        juice_price_cents=_JUICE_SHELF_PRICE_CENTS,
    )


def _expected_line_recoupments(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The per-line proration a 0.10 rate produces over three 124-cent lines."""
    return [
        {
            "claim_line_id": line["id"],
            "allowed_cents": 124,
            # round_half_up(124 x 0.10) = round_half_up(12.4) = 12
            "recoupment_cents": 12,
        }
        for line in lines
    ]


# ---------------------------------------------------------------------------
# Proration rounds per line and only then sums
# ---------------------------------------------------------------------------


def test_recoupment_rounds_each_claim_line_share_before_summing(api):
    """
    A prorated recoupment rounds each line's share on its own and adds the rounded
    shares, so the total is 36 rather than the 37 a single rounding would give.

    "When a reimbursement adjustment prorates a recoupment across claim lines,
    each line's share is rounded half up to a whole cent individually and the
    shares are then added. The total is whatever that sum comes to; the residual
    difference against rounding the claim total once is not redistributed to any
    line." "The participating lines are the claim's ClaimLines whose `edit_result`
    is `ACCEPTED` or `ACCEPTED_REDUCED`; lines rejected by any edit are excluded
    and contribute nothing. Those lines are ordered by ascending `line_number`, and
    for each one the server records an entry in `line_recoupments` holding the
    `claim_line_id`, that line's `allowed_cents`, and a `recoupment_cents` equal to
    the line's `allowed_cents` multiplied by the `recoupment_rate`, rounded half up
    to a whole cent. The adjustment's own `recoupment_cents` is the sum of those
    per-line figures."

    Design: Difficulty/combinatorial_formula/adjustment_proration_rounds_per_line_then_sums
    """
    bundle = _adjudicated_three_line_juice_claim(api)
    claim = bundle["claim"]

    adjustment = validate_success(
        api.create_reimbursement_adjustment(
            factories.reimbursement_adjustment_payload(
                claim["id"],
                claim["version"],
                reason_code=AdjustmentReasonCode.OVERCHARGE.value,
                recoupment_rate=0.10,
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    # 3 lines x round_half_up(124 x 0.10) = 3 x 12 = 36, not
    # round_half_up(372 x 0.10) = round_half_up(37.2) = 37.
    assert_field_values(adjustment, recoupment_cents=36)
    assert_line_recoupments(adjustment, _expected_line_recoupments(bundle["claim_lines"]))
    assert_proration_sums_per_line(adjustment)


def test_statewide_fallback_ceiling_lets_every_juice_line_pay_the_charged_price(api):
    """
    The 124-cent base the proration works from is itself derived: a lone
    submission falls back to the statewide candidate set, and a line charged
    exactly the resulting ceiling is accepted at full price.

    "When the peer count is greater than or equal to that threshold, `basis` is
    `PEER_GROUP` and the candidate set is the peer list itself. When the peer count
    falls short, `basis` is `STATEWIDE_FALLBACK` and the candidate set is rebuilt
    with the identical filter but **without** the peer-group restriction, restricted
    to submissions from vendors whose own peer group has `status` `ACTIVE`; that
    broader list is likewise sorted ascending by price with the `created_at`
    tie-break. Either way, the size of the candidate set actually used is recorded
    as `contributing_submission_count`, while `peer_submission_count` continues to
    report the peer count even when the fallback was used." "Under `PEER_MEDIAN`,
    the base is the median: for a candidate set of odd size it is the single middle
    element, and for an even size it is the mean of the two middle elements." "The
    allowance is applied first: the base is multiplied by one plus the peer group's
    `competitive_allowance_pct`, giving an allowance-adjusted figure. The statewide
    cap is computed second, as 1.25 times the smallest price in the **same**
    candidate set that produced the base — not the smallest peer price when the
    fallback was used, and not a statewide minimum computed separately. That
    unrounded cap is stored as `cap_cents`, and `cap_binding` is recorded as true
    exactly when the cap is strictly less than the allowance-adjusted figure.
    Rounding happens once, at the very end: `mar_cents` is the lesser of the
    allowance-adjusted figure and the cap, rounded half up to a whole cent." "If
    the charged price equals or falls below the ceiling, the line's `edit_result`
    is `ACCEPTED`, its `edit_code` stays null, and its `allowed_cents` is
    `charged_unit_price_cents` multiplied by `quantity`." "The boundary matters: a
    charge exactly equal to the ceiling is accepted at full price, not reduced."
    "`adjudicated_total_cents` is the sum of `allowed_cents` over all lines."

    Design: Difficulty/combinatorial_formula/adjustment_proration_rounds_per_line_then_sums
    """
    bundle = _adjudicated_three_line_juice_claim(api)

    assert_ceiling_derivation(
        bundle["juice_ceiling"],
        basis=CeilingBasis.STATEWIDE_FALLBACK.value,
        peer_submission_count=1,
        contributing_submission_count=1,
        base_cents=118,  # the median of a one-element candidate set
        cap_cents=147.5,  # 1.25 x 118, idle against 118 x 1.05 = 123.90
        cap_binding=False,
        mar_cents=_JUICE_CEILING_CENTS,  # round_half_up(123.90) = 124
    )

    lines = bundle["claim_lines"]
    for line in lines:
        assert_field_values(
            line,
            edit_result=EditResult.ACCEPTED.value,
            edit_code=None,
            applied_mar_cents=_JUICE_CEILING_CENTS,
            allowed_cents=124,  # 1 container x 124 charged, not reduced
            recouped_cents=0,
        )

    # 3 lines x 124 allowed = 372.
    assert_field_values(
        bundle["claim"],
        status=ClaimStatus.ADJUDICATED.value,
        adjudicated_total_cents=372,
        net_payable_cents=372,
        accepted_line_count=3,
        reduced_line_count=0,
        rejected_line_count=0,
    )
    assert_claim_line_counts(bundle["claim"], lines)


def test_pending_adjustment_moves_no_money_but_bumps_the_claim_version(api):
    """
    Raising an adjustment leaves it PENDING with no money moved anywhere, while
    the claim it was raised against gains one version.

    "The adjustment begins in `status` `PENDING` with `created_by_user_id` stamped
    from the acting `X-User-ID` and with `applied_by_user_id`, `applied_at`,
    `reversed_at`, and `reversal_reason` all null." "Note that a successful create
    itself increments the claim's `version` by one, so a client raising two
    adjustments in sequence must re-read the claim between them." "`net_payable_cents`
    is that total less the sum of `recoupment_cents` over the claim's reimbursement
    adjustments whose `status` is `APPLIED` — normally zero at first adjudication."
    "Applying a reimbursement adjustment moves money on the claim, on each affected
    claim line, and on the vendor."

    Design: Difficulty/combinatorial_formula/adjustment_proration_rounds_per_line_then_sums
    """
    bundle = _adjudicated_three_line_juice_claim(api)
    claim = bundle["claim"]

    adjustment = validate_success(
        api.create_reimbursement_adjustment(
            factories.reimbursement_adjustment_payload(
                claim["id"],
                claim["version"],
                reason_code=AdjustmentReasonCode.OVERCHARGE.value,
                recoupment_rate=0.10,
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert_field_values(
        adjustment,
        status=AdjustmentStatus.PENDING.value,
        applied_by_user_id=None,
        applied_at=None,
        reversed_at=None,
        reversal_reason=None,
    )

    after_create = fixtures.get_claim(api, claim["id"])
    assert_field_values(
        after_create,
        status=ClaimStatus.ADJUDICATED.value,
        adjudicated_total_cents=372,
        net_payable_cents=372,  # no APPLIED adjustment yet, so nothing deducted
        version=claim["version"] + 1,
    )
    for line in fixtures.claim_lines_of(api, claim["id"]):
        assert_field_values(line, recouped_cents=0)
    assert_field_values(
        fixtures.get_vendor(api, bundle["vendor"]["id"]), recoupment_balance_cents=0
    )


# ---------------------------------------------------------------------------
# The paid-claim state rule outranks the fiscal recoupment rule
# ---------------------------------------------------------------------------


def _paid_claim_after_one_applied_adjustment(api) -> Dict[str, Any]:
    """
    The adjudicated three-line juice claim with one 0.10 adjustment applied, which
    leaves 336 payable, and the claim then marked paid.
    """
    bundle = _adjudicated_three_line_juice_claim(api)
    claim = bundle["claim"]
    bundle["applied_adjustment"] = fixtures.raise_adjustment(
        api,
        claim["id"],
        claim["version"],
        recoupment_rate=0.10,
        headers=ANALYST_HEADERS,
    )
    fixtures.apply_adjustment(
        api, bundle["applied_adjustment"]["id"], headers=SUPERVISOR_HEADERS
    )
    fixtures.mark_paid(api, claim["id"])
    bundle["claim"] = fixtures.get_claim(api, claim["id"])
    return bundle


def test_adjustment_raised_against_a_paid_claim_is_refused_as_already_paid(api):
    """
    A claim marked paid refuses a fresh adjustment with the paid-claim error even
    though the requested recoupment would also overrun what is still payable.

    "When a request violates more than one rule, exactly one error is returned:
    the one belonging to the lowest-numbered rule in the ladder below." "On `POST
    /reimbursement-adjustments`, `POST /reimbursement-adjustments/{id}/apply`, and
    `POST /reimbursement-adjustments/{id}/reverse`, the referenced claim has not
    been marked paid — otherwise `ERR_CLAIM_ALREADY_PAID`." "On `POST
    /reimbursement-adjustments` and `POST /reimbursement-adjustments/{id}/apply`,
    the computed recoupment fits inside the claim's net payable amount — otherwise
    `ERR_RECOUPMENT_EXCEEDS_PAYABLE` (HTTP 422)." "`PAID` is terminal, and from
    that point any attempt to raise, apply, or reverse an adjustment on the claim
    is refused with `ERR_CLAIM_ALREADY_PAID`."

    Design: Difficulty/priority_pair_validation_conflict/paid_claim_state_beats_recoupment_fiscal_on_adjustment_create
    """
    bundle = _paid_claim_after_one_applied_adjustment(api)
    claim = bundle["claim"]
    # 372 adjudicated less the 36 the first adjustment recouped = 336 payable.
    assert_field_values(claim, status=ClaimStatus.PAID.value, net_payable_cents=336)

    # A rate of 1 prorates the whole 372 of allowed amounts, which overruns the 336
    # still payable, so the request violates the paid-claim rule and the fiscal
    # rule at once; the lower-numbered paid-claim rule is the one reported.
    response = api.create_reimbursement_adjustment(
        factories.reimbursement_adjustment_payload(
            claim["id"],
            claim["version"],
            reason_code=AdjustmentReasonCode.OVERCHARGE.value,
            recoupment_rate=1,
        ),
        ANALYST_TWO_HEADERS,
    )
    validate_error(response, ApiErrorId.CLAIM_ALREADY_PAID.value)


def test_refused_adjustment_on_a_paid_claim_creates_no_row_and_moves_no_money(api):
    """
    The refused create leaves the paid claim's totals, its version and its single
    existing adjustment exactly as they were.

    "Marking a claim paid is a supervisor action available from either
    `ADJUDICATED` or `ADJUSTED`, moving the claim to `PAID` and stamping `paid_at`;
    any other status is refused with `ERR_INVALID_CLAIM_STATE`." "Note that a
    successful create itself increments the claim's `version` by one, so a client
    raising two adjustments in sequence must re-read the claim between them."
    "Reversing it restores all three exactly, so that the claim's
    `adjudicated_total_cents` always equals its `net_payable_cents` plus the sum of
    `recoupment_cents` over its adjustments in status `APPLIED`, and a vendor's
    `recoupment_balance_cents` always equals the sum of `recoupment_cents` over that
    vendor's adjustments in status `APPLIED`." "`version` (integer): a counter that
    increments by one on every mutation of the row."

    Design: Difficulty/priority_pair_validation_conflict/paid_claim_state_beats_recoupment_fiscal_on_adjustment_create
    """
    bundle = _paid_claim_after_one_applied_adjustment(api)
    claim = bundle["claim"]

    api.create_reimbursement_adjustment(
        factories.reimbursement_adjustment_payload(
            claim["id"],
            claim["version"],
            reason_code=AdjustmentReasonCode.OVERCHARGE.value,
            recoupment_rate=1,
        ),
        ANALYST_TWO_HEADERS,
    )

    after = fixtures.get_claim(api, claim["id"])
    assert_field_values(
        after,
        status=ClaimStatus.PAID.value,
        adjudicated_total_cents=372,
        net_payable_cents=336,  # 372 - 36, untouched by the refused request
        version=claim["version"],  # a refused create is not a mutation
    )

    rows, meta = validate_paginated(
        api.list_reimbursement_adjustments(
            SUPERVISOR_HEADERS,
            {"redemption_claim_id": claim["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1, (
        f"a refused create must not add an adjustment row, got {meta}"
    )
    assert_field_values(
        rows[0], status=AdjustmentStatus.APPLIED.value, recoupment_cents=36
    )
    assert_field_values(
        fixtures.get_vendor(api, bundle["vendor"]["id"]), recoupment_balance_cents=36
    )


# ---------------------------------------------------------------------------
# Apply then reverse conserves the claim, the lines and the vendor balance
# ---------------------------------------------------------------------------


def _pending_juice_adjustment(api) -> Dict[str, Any]:
    """The adjudicated three-line juice claim plus one PENDING 0.10 adjustment."""
    bundle = _adjudicated_three_line_juice_claim(api)
    bundle["adjustment"] = fixtures.raise_adjustment(
        api,
        bundle["claim"]["id"],
        bundle["claim"]["version"],
        recoupment_rate=0.10,
        headers=ANALYST_HEADERS,
    )
    bundle["claim"] = fixtures.get_claim(api, bundle["claim"]["id"])
    return bundle


def test_applying_an_adjustment_moves_money_on_claim_lines_and_vendor_at_once(api):
    """
    Applying the adjustment reduces the claim's payable amount, charges each
    participating line its own prorated share, and raises the vendor's recoupment
    balance by the same total.

    "**Applying** the adjustment is a supervisor action and moves it `PENDING →
    APPLIED`." "On success, `applied_by_user_id` and `applied_at` are stamped, and
    money moves in three places at once: the claim advances `ADJUDICATED →
    ADJUSTED` with its `net_payable_cents` reduced by the adjustment's
    `recoupment_cents`, each participating claim line has its `recouped_cents`
    increased by that line's prorated share, and the vendor's
    `recoupment_balance_cents` rises by the adjustment's `recoupment_cents`."
    "Applying a reimbursement adjustment moves money on the claim, on each affected
    claim line, and on the vendor. Reversing it restores all three exactly, so that
    the claim's `adjudicated_total_cents` always equals its `net_payable_cents` plus
    the sum of `recoupment_cents` over its adjustments in status `APPLIED`, and a
    vendor's `recoupment_balance_cents` always equals the sum of `recoupment_cents`
    over that vendor's adjustments in status `APPLIED`."

    Design: Difficulty/compensating_invariant/adjustment_apply_then_reverse_conserves_claim_and_vendor_money
    """
    bundle = _pending_juice_adjustment(api)
    vendor_id = bundle["vendor"]["id"]

    # Before the apply the invariant reads 372 == 372 + 0.
    assert_field_values(
        bundle["claim"], adjudicated_total_cents=372, net_payable_cents=372
    )
    assert_field_values(
        fixtures.get_vendor(api, vendor_id), recoupment_balance_cents=0
    )
    for line in fixtures.claim_lines_of(api, bundle["claim"]["id"]):
        assert_field_values(line, recouped_cents=0)

    applied = validate_success(
        api.apply_adjustment(bundle["adjustment"]["id"], None, SUPERVISOR_HEADERS)
    )
    assert_field_values(
        applied,
        status=AdjustmentStatus.APPLIED.value,
        applied_by_user_id=SUPERVISOR_ONE,
        recoupment_cents=36,
    )

    claim = fixtures.get_claim(api, bundle["claim"]["id"])
    # 372 adjudicated less 36 recouped = 336 payable, so 372 == 336 + 36.
    assert_field_values(
        claim,
        status=ClaimStatus.ADJUSTED.value,
        adjudicated_total_cents=372,
        net_payable_cents=336,
    )
    assert (
        claim["adjudicated_total_cents"]
        == claim["net_payable_cents"] + applied["recoupment_cents"]
    ), f"the claim money invariant broke after the apply: {claim}"

    for line in fixtures.claim_lines_of(api, claim["id"]):
        # Each line carries its own rounded share of 12, never a third of 37.
        assert_field_values(line, allowed_cents=124, recouped_cents=12)

    assert_field_values(
        fixtures.get_vendor(api, vendor_id), recoupment_balance_cents=36
    )


def test_reversing_an_applied_adjustment_restores_claim_lines_and_vendor_exactly(api):
    """
    Reversing the applied adjustment returns the claim to ADJUDICATED at its full
    adjudicated total, zeroes every line's recouped amount and empties the vendor's
    recoupment balance, with no cent of rounding drift.

    "**Reversing** an applied adjustment is the compensating action, also restricted
    to a supervisor, and moves the adjustment `APPLIED → REVERSED` with a
    `reversal_reason` stored and `reversed_at` stamped." "Reversal undoes each of
    the three money effects exactly: each participating line's `recouped_cents` is
    reduced by the same share it received, returning to 0 when no other adjustment
    charged it; the vendor's `recoupment_balance_cents` is reduced by the
    adjustment's `recoupment_cents`; and the claim's `net_payable_cents` is
    restored. When no other adjustment of the claim remains in `APPLIED`, the claim
    moves back `ADJUSTED → ADJUDICATED` and its `net_payable_cents` returns to
    exactly its `adjudicated_total_cents`; when another applied adjustment survives,
    the claim stays `ADJUSTED` and its `net_payable_cents` reflects the remaining
    applied recoupments." "Before any client sets it, the logical clock reads
    exactly `2026-08-01T00:00:00Z`, and the server never falls back to real time."

    Design: Difficulty/compensating_invariant/adjustment_apply_then_reverse_conserves_claim_and_vendor_money
    """
    bundle = _pending_juice_adjustment(api)
    vendor_id = bundle["vendor"]["id"]
    fixtures.apply_adjustment(
        api, bundle["adjustment"]["id"], headers=SUPERVISOR_HEADERS
    )

    reversed_adjustment = validate_success(
        api.reverse_adjustment(
            bundle["adjustment"]["id"],
            factories.reversal_payload(_REVERSAL_REASON),
            SUPERVISOR_HEADERS,
        )
    )
    assert_field_values(
        reversed_adjustment,
        status=AdjustmentStatus.REVERSED.value,
        reversed_at=DEFAULT_LOGICAL_CLOCK_ISO,
        reversal_reason=_REVERSAL_REASON,
    )

    claim = fixtures.get_claim(api, bundle["claim"]["id"])
    # The 36 no longer sits in APPLIED, so 336 + 36 returns exactly to 372.
    assert_field_values(
        claim,
        status=ClaimStatus.ADJUDICATED.value,
        adjudicated_total_cents=372,
        net_payable_cents=372,
    )
    assert claim["net_payable_cents"] == claim["adjudicated_total_cents"], (
        f"net_payable_cents did not return to the adjudicated total: {claim}"
    )

    for line in fixtures.claim_lines_of(api, claim["id"]):
        assert_field_values(line, allowed_cents=124, recouped_cents=0)

    assert_field_values(
        fixtures.get_vendor(api, vendor_id), recoupment_balance_cents=0
    )


def test_reversal_leaves_the_proration_it_undid_on_the_record(api):
    """
    The reversal restores money without rewriting the proration it undid, and the
    claim's adjudication figures are the same before and after.

    "Reversal undoes each of the three money effects exactly: each participating
    line's `recouped_cents` is reduced by the same share it received, returning to
    0 when no other adjustment charged it; the vendor's `recoupment_balance_cents`
    is reduced by the adjustment's `recoupment_cents`; and the claim's
    `net_payable_cents` is restored." "The adjustment's own `recoupment_cents` is
    the sum of those per-line figures." "**Proration** is computed at create time,
    not at apply time." "Its identifier is stored on the claim as
    `governing_price_cycle_id`, and `adjudicated_at` takes the logical clock."
    "Note that `submitted_total_cents` was fixed at claim creation and is not
    recomputed here."

    Design: Difficulty/compensating_invariant/adjustment_apply_then_reverse_conserves_claim_and_vendor_money
    """
    bundle = _pending_juice_adjustment(api)
    lines = fixtures.claim_lines_of(api, bundle["claim"]["id"])
    assert_field_values(
        bundle["claim"],
        adjudicated_at=DEFAULT_LOGICAL_CLOCK_ISO,
        submitted_total_cents=372,  # 3 x 1 x 124 fixed at claim creation
    )

    fixtures.apply_adjustment(
        api, bundle["adjustment"]["id"], headers=SUPERVISOR_HEADERS
    )
    fixtures.reverse_adjustment(
        api, bundle["adjustment"]["id"], headers=SUPERVISOR_HEADERS
    )

    after = fixtures.get_adjustment(api, bundle["adjustment"]["id"])
    # The proration was fixed at create time; the reversal does not re-derive it.
    assert_field_values(after, recoupment_cents=36)
    assert_line_recoupments(after, _expected_line_recoupments(lines))
    assert_proration_sums_per_line(after)

    claim = fixtures.get_claim(api, bundle["claim"]["id"])
    assert_field_values(
        claim,
        adjudicated_total_cents=372,
        adjudicated_at=DEFAULT_LOGICAL_CLOCK_ISO,
        submitted_total_cents=372,
        accepted_line_count=3,
        reduced_line_count=0,
        rejected_line_count=0,
    )
