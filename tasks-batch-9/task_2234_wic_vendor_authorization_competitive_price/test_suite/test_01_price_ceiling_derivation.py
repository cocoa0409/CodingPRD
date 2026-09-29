"""
Deriving the maximum allowable reimbursement (PRD 3.4).

Two families of facts are pinned here: the divergence between the provisional
sweep run at cycle close and the final sweep run at publication, and the pinned
step order that lets the statewide cap clamp an allowance-adjusted percentile
base. Every precondition is built from scratch through the documented endpoints.
"""

from typing import Any, Dict, List

from test_helpers import (
    SUPERVISOR_HEADERS,
    CeilingBasis,
    CeilingStatus,
    MarMethod,
    PriceCycleStatus,
    StoreType,
    SupersededReason,
    assert_ceiling_derivation,
    assert_field_values,
    assert_price_ceiling,
    fixtures,
    validate_paginated,
    validate_success,
)

# The four shelf prices the divergence scenario collects for one item in one
# peer group: the first is never reviewed and so lives only in the provisional
# candidate set, the other three are accepted.
_UNREVIEWED_PRICE_CENTS = 300
_ACCEPTED_PRICE_CENTS = (320, 349, 410)
_REPORTED_VOLUMES_CENTS = (7_000_000, 8_000_000, 9_000_000)

# The peer group the percentile scenario needs: a nearest-rank seventy-fifth
# percentile criterion with an eight per cent competitive allowance.
_PERCENTILE_PEER_GROUP: Dict[str, Any] = {
    "code": "PG-MED-B",
    "store_type": StoreType.MEDIUM_GROCERY.value,
    "min_monthly_redemption_cents": 1_000_000,
    "max_monthly_redemption_cents": 4_999_999,
    "mar_method": MarMethod.PEER_PERCENTILE_75.value,
    "competitive_allowance_pct": 0.08,
    "min_submissions_for_ceiling": 3,
    "min_stock_multiplier": 1.0,
}
_PERCENTILE_PRICES = (200, 250, 400)
_PERCENTILE_VOLUMES = (1_200_000, 2_200_000, 3_200_000)


def _peer_group_with_one_unreviewed_shelf_price(api) -> Dict[str, Any]:
    """
    One peer group, one item, one open cycle, and four reported shelf prices.

    The 300-cent price is left in ``SUBMITTED``; 320, 349 and 410 are accepted.
    """
    bundle = fixtures.bootstrap_catalogue(api)
    item_id = bundle["milk_item"]["id"]
    cycle_id = bundle["cycle"]["id"]

    unreviewed_vendor = fixtures.vendor_in_review(
        api, store_name="Alpha Market", reported_monthly_redemption_cents=6_000_000
    )
    bundle["unreviewed_submission"] = fixtures.submit_price(
        api,
        unreviewed_vendor["id"],
        item_id,
        cycle_id,
        _UNREVIEWED_PRICE_CENTS,
    )

    accepted: List[Dict[str, Any]] = []
    for index, (price, volume) in enumerate(
        zip(_ACCEPTED_PRICE_CENTS, _REPORTED_VOLUMES_CENTS), start=1
    ):
        vendor = fixtures.vendor_in_review(
            api,
            store_name=f"Peer Market {index}",
            reported_monthly_redemption_cents=volume,
        )
        submission = fixtures.submit_price(api, vendor["id"], item_id, cycle_id, price)
        accepted.append(fixtures.accept_submission(api, submission["id"]))
    bundle["accepted_submissions"] = accepted
    return bundle


def _ceilings_for_pair(api, bundle: Dict[str, Any], status: str):
    """The maximum allowable reimbursement rows of one pair in one status."""
    return validate_paginated(
        api.list_price_ceilings(
            SUPERVISOR_HEADERS,
            {
                "peer_group_id": bundle["peer_group"]["id"],
                "food_item_id": bundle["milk_item"]["id"],
                "price_cycle_id": bundle["cycle"]["id"],
                "status": status,
                "limit": 100,
            },
        )
    )


def _decimal_field(row: Dict[str, Any], field: str) -> float:
    """``base_cents`` and ``cap_cents`` stay unrounded decimals on the row."""
    return float(row[field])


# ---------------------------------------------------------------------------
# Closing a cycle previews the ceilings from the provisional candidate set
# ---------------------------------------------------------------------------


def test_provisional_ceiling_admits_the_unreviewed_shelf_price(api):
    """
    Closing a cycle prices the pair from SUBMITTED prices as well as ACCEPTED ones.

    "The `PROVISIONAL` variant, run at cycle close, admits submissions in
    `SUBMITTED` as well as `ACCEPTED` — the preview therefore includes prices no
    analyst has yet vetted."
    "Closing moves a cycle `OPEN → CLOSED` — a cycle in any other status is refused
    with `ERR_INVALID_CYCLE_STATE` — stamps `closed_at` with the logical clock, and
    sweeps every pair consisting of an `ACTIVE` peer group and an `ACTIVE` authorized
    food item."
    "For each pair with a non-empty candidate set, a PriceCeiling row is written with
    `status` `PROVISIONAL`; the number written becomes the cycle's
    `provisional_ceiling_count`, and the number of pairs skipped for having an empty
    candidate set becomes its `skipped_pair_count`."
    "When the peer count is greater than or equal to that threshold, `basis` is
    `PEER_GROUP` and the candidate set is the peer list itself."
    "Under `PEER_MEDIAN`, the base is the median: for a candidate set of odd size it
    is the single middle element, and for an even size it is the mean of the two
    middle elements."
    "The allowance is applied first: the base is multiplied by one plus the peer
    group's `competitive_allowance_pct`, giving an allowance-adjusted figure."
    "The statewide cap is computed second, as 1.25 times the smallest price in the
    **same** candidate set that produced the base — not the smallest peer price when
    the fallback was used, and not a statewide minimum computed separately."
    "Rounding happens once, at the very end: `mar_cents` is the lesser of the
    allowance-adjusted figure and the cap, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/mar_provisional_vs_final_diverges_on_milk_ceiling
    """
    bundle = _peer_group_with_one_unreviewed_shelf_price(api)

    validate_success(
        api.close_price_cycle(bundle["cycle"]["id"], None, SUPERVISOR_HEADERS)
    )

    cycle = validate_success(
        api.get_price_cycle(bundle["cycle"]["id"], SUPERVISOR_HEADERS)
    )
    assert_field_values(
        cycle,
        status=PriceCycleStatus.CLOSED.value,
        provisional_ceiling_count=1,  # one ACTIVE peer group x one ACTIVE item
        skipped_pair_count=0,
    )

    rows, meta = _ceilings_for_pair(api, bundle, CeilingStatus.PROVISIONAL.value)
    assert meta["total_count"] == 1, f"expected one provisional row, got {meta}"
    assert_ceiling_derivation(
        rows[0],
        basis=CeilingBasis.PEER_GROUP.value,
        peer_submission_count=4,  # 300 SUBMITTED plus 320, 349, 410 ACCEPTED
        contributing_submission_count=4,
        base_cents=334.5,  # even size 4: mean of the two middle prices (320 + 349) / 2
        cap_cents=375.0,  # 1.25 x 300, the smallest price in the same candidate set
        cap_binding=False,  # 375.0 is not strictly less than 334.5 x 1.05 = 351.225
        mar_cents=351,  # one rounding, at the end: round_half_up(351.225)
    )


def test_published_ceiling_admits_only_accepted_shelf_prices(api):
    """
    Publishing reprices the same pair from the accepted prices alone and diverges.

    "The `FINAL` variant, run at publication, admits only `ACCEPTED` submissions, so
    a submission that was never reviewed silently drops out, shifting both the base
    and the cap's minimum."
    "On identical data the two variants can and routinely will produce different
    `mar_cents`, different `basis` values, and different `cap_binding` flags for the
    same pair."
    "Second, the same pair sweep runs again and writes a fresh PriceCeiling row with
    `status` `ACTIVE` for every pair with a non-empty candidate set, setting
    `published_ceiling_count` and `skipped_pair_count` from that sweep."
    "The response to publication reports the `price_cycle_id`, the resulting
    `status`, the `published_ceiling_count`, the `skipped_pair_count`, a
    `superseded_ceiling_count` covering every row this call moved to `SUPERSEDED`,
    and the `published_at` instant."
    "Under `PEER_MEDIAN`, the base is the median: for a candidate set of odd size it
    is the single middle element, and for an even size it is the mean of the two
    middle elements."
    "Rounding happens once, at the very end: `mar_cents` is the lesser of the
    allowance-adjusted figure and the cap, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/mar_provisional_vs_final_diverges_on_milk_ceiling
    """
    bundle = _peer_group_with_one_unreviewed_shelf_price(api)
    fixtures.close_cycle(api, bundle["cycle"]["id"])
    provisional_rows, _ = _ceilings_for_pair(api, bundle, CeilingStatus.PROVISIONAL.value)
    provisional_mar_cents = provisional_rows[0]["mar_cents"]

    summary = validate_success(
        api.publish_ceilings(bundle["cycle"]["id"], None, SUPERVISOR_HEADERS)
    )
    assert_field_values(
        summary,
        price_cycle_id=bundle["cycle"]["id"],
        status=PriceCycleStatus.PUBLISHED.value,
        published_ceiling_count=1,
        skipped_pair_count=0,
        superseded_ceiling_count=1,  # only the provisional row of this same cycle
    )

    rows, meta = _ceilings_for_pair(api, bundle, CeilingStatus.ACTIVE.value)
    assert meta["total_count"] == 1, f"expected one active row, got {meta}"
    assert_ceiling_derivation(
        rows[0],
        basis=CeilingBasis.PEER_GROUP.value,
        peer_submission_count=3,  # the never-reviewed 300 drops out of the final set
        contributing_submission_count=3,
        base_cents=349.0,  # odd size 3: the single middle price of 320, 349, 410
        cap_cents=400.0,  # 1.25 x 320, the smallest price in the final candidate set
        cap_binding=False,  # 400.0 is not strictly less than 349 x 1.05 = 366.45
        mar_cents=366,  # round_half_up(366.45)
    )

    assert rows[0]["mar_cents"] - provisional_mar_cents == 15, (
        "the two variants must disagree by 15 cents on identical submission data: "
        f"{rows[0]['mar_cents']} against {provisional_mar_cents}"
    )


def test_provisional_row_is_superseded_when_the_cycle_publishes(api):
    """
    Publication retires the preview row without rewriting the number it previewed.

    "First, every PriceCeiling of this cycle still in `PROVISIONAL` moves to
    `SUPERSEDED` with `superseded_reason` `PROVISIONAL_REPLACED`."
    "Both `base_cents` and `cap_cents` remain unrounded decimals on the row, so that
    an appeal can retrace the arithmetic."
    "`version` (integer): a counter that increments by one on every mutation of the
    row."
    "A mutation for the purposes of `updated_at` and `version` includes changes the
    client did not directly request."

    Design: Difficulty/dual_variant_calc/mar_provisional_vs_final_diverges_on_milk_ceiling
    """
    bundle = _peer_group_with_one_unreviewed_shelf_price(api)
    fixtures.close_cycle(api, bundle["cycle"]["id"])
    provisional_rows, _ = _ceilings_for_pair(api, bundle, CeilingStatus.PROVISIONAL.value)
    provisional_id = provisional_rows[0]["id"]

    fixtures.publish_cycle(api, bundle["cycle"]["id"])

    retired = validate_success(api.get_price_ceiling(provisional_id, SUPERVISOR_HEADERS))
    assert_price_ceiling(
        retired,
        status=CeilingStatus.SUPERSEDED.value,
        superseded_reason=SupersededReason.PROVISIONAL_REPLACED.value,
        mar_cents=351,  # the preview number is retained, not recomputed
    )
    assert _decimal_field(retired, "base_cents") == 334.5
    assert _decimal_field(retired, "cap_cents") == 375.0
    assert retired["version"] > provisional_rows[0]["version"], (
        "moving the row to SUPERSEDED is a mutation and must increment its version"
    )

    still_provisional, meta = _ceilings_for_pair(
        api, bundle, CeilingStatus.PROVISIONAL.value
    )
    assert meta["total_count"] == 0, (
        f"no provisional row of this cycle may survive publication, got {still_provisional}"
    )


# ---------------------------------------------------------------------------
# The statewide cap clamps the allowance-adjusted percentile base
# ---------------------------------------------------------------------------


def test_nearest_rank_percentile_base_is_the_top_of_three_peer_prices(api):
    """
    The nearest-rank seventy-fifth percentile of three prices is the highest one.

    "Under `PEER_PERCENTILE_75`, the base is the nearest-rank seventy-fifth
    percentile: multiply 0.75 by the number of candidates, round that product **up**
    to the next whole number, and take the element at that one-based position in the
    ascending list — so with four candidates the third-lowest price is taken, and
    with five candidates the fourth."
    "Otherwise the basis is decided by comparing the peer count against the peer
    group's own `min_submissions_for_ceiling`."
    "When the peer count is greater than or equal to that threshold, `basis` is
    `PEER_GROUP` and the candidate set is the peer list itself."
    "Either way, the size of the candidate set actually used is recorded as
    `contributing_submission_count`, while `peer_submission_count` continues to
    report the peer count even when the fallback was used."

    Design: Difficulty/combinatorial_formula/mar_statewide_cap_binds_over_percentile_75_allowance
    """
    bundle = fixtures.peer_group_with_three_accepted_prices(
        api,
        peer_group_overrides=_PERCENTILE_PEER_GROUP,
        prices=_PERCENTILE_PRICES,
        reported_volumes=_PERCENTILE_VOLUMES,
        store_type=StoreType.MEDIUM_GROCERY.value,
    )
    fixtures.close_cycle(api, bundle["cycle"]["id"])

    validate_success(
        api.publish_ceilings(bundle["cycle"]["id"], None, SUPERVISOR_HEADERS)
    )

    rows, meta = _ceilings_for_pair(api, bundle, CeilingStatus.ACTIVE.value)
    assert meta["total_count"] == 1, f"expected one active row, got {meta}"
    row = rows[0]
    assert_field_values(
        row,
        basis=CeilingBasis.PEER_GROUP.value,
        peer_submission_count=3,
        contributing_submission_count=3,
    )
    # ceil(0.75 x 3) = ceil(2.25) = 3, so the third of 200, 250, 400 ascending.
    assert _decimal_field(row, "base_cents") == 400.0


def test_statewide_cap_clamps_the_allowance_adjusted_percentile_base(api):
    """
    The allowance lifts the base first and the cap then clamps the lifted figure.

    "The step order from base price to final ceiling is pinned and must not be
    rearranged."
    "The allowance is applied first: the base is multiplied by one plus the peer
    group's `competitive_allowance_pct`, giving an allowance-adjusted figure."
    "The statewide cap is computed second, as 1.25 times the smallest price in the
    **same** candidate set that produced the base — not the smallest peer price when
    the fallback was used, and not a statewide minimum computed separately."
    "That unrounded cap is stored as `cap_cents`, and `cap_binding` is recorded as
    true exactly when the cap is strictly less than the allowance-adjusted figure."
    "Rounding happens once, at the very end: `mar_cents` is the lesser of the
    allowance-adjusted figure and the cap, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/mar_statewide_cap_binds_over_percentile_75_allowance
    """
    bundle = fixtures.peer_group_with_three_accepted_prices(
        api,
        peer_group_overrides=_PERCENTILE_PEER_GROUP,
        prices=_PERCENTILE_PRICES,
        reported_volumes=_PERCENTILE_VOLUMES,
        store_type=StoreType.MEDIUM_GROCERY.value,
    )
    fixtures.close_cycle(api, bundle["cycle"]["id"])

    validate_success(
        api.publish_ceilings(bundle["cycle"]["id"], None, SUPERVISOR_HEADERS)
    )

    rows, _ = _ceilings_for_pair(api, bundle, CeilingStatus.ACTIVE.value)
    row = rows[0]
    # 400 x 1.08 = 432.0 allowance-adjusted; cap 1.25 x 200 = 250.0 is strictly less.
    assert _decimal_field(row, "cap_cents") == 250.0
    assert_field_values(row, cap_binding=True, mar_cents=250)
    assert row["mar_cents"] != 432, "the cap must not be ignored after the allowance"
    assert row["mar_cents"] != 270, (
        "the cap must not be taken off the allowance-free base and then re-inflated"
    )
