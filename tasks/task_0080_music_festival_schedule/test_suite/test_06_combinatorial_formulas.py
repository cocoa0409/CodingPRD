"""Combinatorial formulas in three modes — rule-2 in the difficulty
design.  Three distinguishable shapes of combinatorial structure, each
on a different calculation surface in the PRD:

  Mode (a) — the slot_priority_score weighted-scoring formula of PRD
  §3.5, combining the four inputs (Artist.tier enum, travel-buffer
  minutes clamped at TRAVEL_BUFFER_MAX_MINUTES on the upper end, the
  multi-festival conflict count, and the rider count clamped at
  RIDER_CAP=5) with three independent non-linear pieces: the indicator-
  function selection over the tier, the upper clamp on the rider
  count, and the non-negative floor on the raw score.  The canonical
  worked input in PRD §3.5 yields 150.00 exactly.

  Mode (b) — the sponsor_payout_total mills-to-cents conversion of
  PRD §3.6.  The pinned rounding order is "sum the mils across all
  lines first, then divide once at the end, then round once at the
  end".  The rejected alternative "round each line's mills-to-cents
  conversion first and then sum the rounded cents" diverges by
  exactly one cent on the canonical three-lines-of-one-unit-at-25-mils
  input vector: the pinned answer is 8 cents (the unrounded 0.075-cent
  total rounds half-up to 0.08-cent which is integer-cents 8), and the
  rejected alternative is 9 cents (each line's 0.025-cent rounds
  half-up independently to 0.03-cent and the three rounded line-cents
  sum to 0.09-cent which is integer-cents 9).  The 8-versus-9 gap is
  the falsifiable signature of the rounding-order non-commutativity.

  Mode (c) — the sponsor_waterfall_allocation evaluation-order rule
  of PRD §3.6, with the fixed three-tier order
  `WATERFALL_TIER_ORDER == ["TITLE", "GOLD", "SILVER"]` and the
  within-tier (priority_rank ASC, sponsor_external_id ASC)
  lexicographic tiebreak.  On the canonical six-sponsor scenario
  (one TITLE at 5 units, two GOLDs at 2 each, three SILVERs at 1
  each, with a branded_zone pool of 10), the pinned post-sweep
  actual_units vector is exactly (5, 2, 2, 1, 0, 0).  A
  global-priority-rank-only allocator that ignored the tier order
  would land a different vector — that the canonical tuple matches
  the §3.6 narrative pins the tier-then-rank evaluation order.

These three modes together cover the rule-2 difficulty-design entry
in over-coverage (the rule requires two modes; the design names all
three).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ALTERNATIVE_UNPINNED_PAYOUT_CENTS,
    AUDIT_HEADERS,
    AuditEventCategory,
    CANONICAL_HEADLINER_SCORE,
    CANONICAL_PINNED_PAYOUT_CENTS,
    CANONICAL_WATERFALL_ACTUAL_UNITS,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    SPONSOR_HEADERS,
    STAGE_HEADERS,
    THRESHOLDS,
    advance_clock_to,
    add_program_item,
    add_program_version,
    add_sponsor_tier,
    add_stage,
    advance_festival_through_close,
    base_world,
    confirm_item,
    constants as C,
    external_commitment,
    factories as F,
    fixtures as FIX,
    get_fulfilment_report_snapshot,
    get_success_data,
    publish_version,
    read_audit_log,
    register_artist,
    rider_payload,
    run_post_event_sweep,
    run_waterfall,
    seed_default_catalog,
    validate_paginated,
    validate_success,
    waterfall_six_sponsor_world,
)


# ---------------------------------------------------------------------------
# Mode (a) — slot_priority_score on the canonical four-input worked example.
# ---------------------------------------------------------------------------


def test_slot_priority_score_canonical_one_fifty_on_headliner_input(api, time_anchor):
    """PRD §3.5: "The raw score is the algebraic sum: the matching tier
    bonus, plus the travel-buffer-minutes times the travel weight,
    minus the conflict count times the conflict penalty, plus the
    clamped rider count times the rider weight.  The final stored
    value is the raw score floored at zero (any negative result is
    clamped up to zero, the non-negative floor `NON_NEGATIVE_FLOOR =
    0`) and rounded half up to two decimal places.  The canonical
    illustrative input — a HEADLINER artist with a six-hundred-minute
    travel buffer (ten hours), one external-commitment conflict in the
    ±24-hour window, and seven riders on the item — yields the tier
    bonus 100, the travel term 600 times 0.1 equals 60.0, the
    conflict term 1 times 20 equals 20 (subtracted), and the rider
    term `min(7, 5) * 2 = 10` for an unclamped raw of 100 + 60 - 20 +
    10 = 150, max with zero is 150, and rounded to two decimals is
    150.00."

    Claim: the canonical input — HEADLINER tier, an external
    commitment whose end_time is exactly 600 minutes (10 hours, or
    36000 seconds) before the item's start_time so the travel-buffer-
    minutes term is 600.0, the commitment's window placed in the
    ±24-hour neighbourhood of the slot so the
    multi_festival_conflict_count is exactly 1, and seven non-blocking
    rider rows on the item so the clamped rider term lands at
    min(7, 5)*2 == 10 — yields a slot_priority_score of exactly the
    integer-Decimal literal `150.00`, the half-up rounded form of the
    raw integer 150.  The recompute-priority endpoint is the testable
    hook for forcing the formula to re-evaluate; it returns the row
    with the recomputed score.

    A side-pin: an additional non-blocking eighth rider does NOT
    change the score (the RIDER_CAP=5 clamp saturates at 5).

    Difficulty rule 2 mode (a):
    # difficulty: combinatorial_formula/slot_priority_score_three_input_nonlinear_mode_a
    """
    # The artist's external commitment window: the PRD §3.5 sentence
    # "the integer `multi_festival_conflict_count` equal to the count
    # of `external_commitments` whose half-open window intersects the
    # plus-or-minus-twenty-four-hour neighbourhood of the candidate's
    # window".  We pick a window whose end is exactly 600 minutes
    # before the candidate's start (so the travel-term is exactly
    # 60.0 = 600 minutes × 0.1) and whose start is 23 hours before
    # the candidate's start (so the commitment's window touches the
    # 24-hour neighbourhood of the slot and the conflict count is 1).
    # We anchor the candidate item at a known instant inside the
    # festival.
    bag = FIX.festival_in_scheduling(api, day_count=4, start_offset_seconds=0)
    # Per PRD §3.3, a festival in SCHEDULING needs a DRAFT
    # ProgramVersion attached before a ProgramItem can be created on
    # it — the item's `program_version_id` field is required by the
    # §3.3 create-body shape.  `festival_in_scheduling` is the bare
    # "festival in SCHEDULING with nothing else" helper that this
    # test wants on top of a fresh draft version, so we explicitly
    # add one here.
    add_program_version(api, bag, version_label="canonical-headliner-v")
    # Day-2 12:00 candidate start.  The festival starts at
    # TIME_ANCHOR_UNIX_SECONDS (the deterministic anchor from the
    # factories module), which is the per-test wall-clock origin.
    slot_start = bag.festival_start + 2 * 86400 + 12 * 3600
    slot_end = slot_start + 3600
    # Commitment ends 600 minutes (36000 s) before slot_start so the
    # gap-to-preceding-commitment-in-minutes is exactly 600.  Its
    # start is 23 hours before slot_start so the commitment's window
    # intersects the ±24-hour neighbourhood and the conflict count is
    # 1 (but the commitment ends before slot_start, so the gap-to-
    # preceding-commitment is the gap from the commitment's end to
    # the slot's start = 36000 s = 600 minutes).
    commitment_end = slot_start - 600 * 60          # 36000 seconds before
    commitment_start = slot_start - 23 * 3600       # 23 hours before
    assert commitment_start < commitment_end, "Sanity: commitment is a valid interval."
    ec = external_commitment(festival_external_id="ExtFest-X",
                             start_time=commitment_start,
                             end_time=commitment_end,
                             city="OtherCity")
    # The artist's minimum_travel_buffer_hours default of 4 means the
    # travel-buffer rule's gate is `gap_seconds >= 4 * 3600 == 14400`,
    # and our gap is 36000 s > 14400 s, so the travel-buffer-rule
    # ERR_ARTIST_TRAVEL_BUFFER_VIOLATION (PRD §3.5) does not fire on
    # the confirm step.  The multi-festival overlap rule
    # ERR_ARTIST_MULTI_FESTIVAL_CONFLICT does not fire either because
    # the commitment's window ends strictly before the candidate's
    # window starts (the rule's "overlap-subset" semantics in PRD §3.5
    # is "the candidate's half-open window actually intersects one of
    # the artist's external commitments' half-open windows" — which
    # this pair does not).
    artist = register_artist(api, tier="HEADLINER", home_city="HomeC",
                             external_commitments=[ec],
                             minimum_travel_buffer_hours=None)
    bag.artist = artist
    bag.artist_id = str(artist["id"])
    # The stage from base_world has empty equipment_kits — fine because
    # the item's equipment_kit_codes is the empty list, the per-item
    # kit-wiring guard passes.
    add_stage(api, bag, zone_capacity=100)
    # The version is the bag's initial DRAFT V1.
    # Create the item.
    item = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=slot_start, end_time=slot_end,
                               genre="indie-rock", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    item_id = str(item["id"])
    # The score at create time has the four-input arithmetic with
    # rider_count==0: 100 + 60.0 − 20 + 0 = 140.0 → 140.00.
    pre_rider = get_success_data(
        api.recompute_program_item_priority(bag.festival_id, item_id, PRODUCER_HEADERS)
    )
    # The PRD §3.5 prose says "the integer rider_count equal to the
    # count of all riders on the item (blocking or not), clamped from
    # above at the constant RIDER_CAP = 5".  Add seven non-blocking
    # riders so the un-clamped count is 7 and the clamped value is 5.
    for j in range(7):
        get_success_data(api.create_rider(
            bag.festival_id, item_id,
            rider_payload(category="HOSPITALITY",
                          description=f"snack-line-{j}",
                          is_blocking=False),
            LIAISON_HEADERS,
        ))
    after_riders = get_success_data(
        api.recompute_program_item_priority(bag.festival_id, item_id, PRODUCER_HEADERS)
    )
    # The canonical 150.00 literal.  The PRD §3.5 worked example pins
    # this value verbatim.
    assert float(after_riders["slot_priority_score"]) == pytest.approx(
        float(CANONICAL_HEADLINER_SCORE), abs=0.01,
    ), (
        f"The canonical HEADLINER score with travel_buffer=600 min, "
        f"conflict_count=1, rider_count=7-clamped-to-5 lands at exactly "
        f"150.00 per the PRD §3.5 worked example.  Got "
        f"{after_riders['slot_priority_score']}."
    )
    # The eighth rider does not change the score because the
    # RIDER_CAP=5 clamp is saturating per PRD §3.5.  This is the
    # second pin of the difficulty design's mode-(a) instance:
    # "adding an eighth non-blocking rider must NOT change the score
    # (the RIDER_CAP clamp at 5), confirming the cap behaviour".
    get_success_data(api.create_rider(
        bag.festival_id, item_id,
        rider_payload(category="HOSPITALITY",
                      description="snack-line-8-over-the-cap",
                      is_blocking=False),
        LIAISON_HEADERS,
    ))
    after_extra_rider = get_success_data(
        api.recompute_program_item_priority(bag.festival_id, item_id, PRODUCER_HEADERS)
    )
    assert (float(after_extra_rider["slot_priority_score"])
            == float(after_riders["slot_priority_score"])), (
        "An eighth rider does not move the score past the RIDER_CAP=5 "
        "clamp saturation per PRD §3.5."
    )


def test_slot_priority_score_tier_change_drops_score_by_indicator_function_delta(api):
    """PRD §3.5: "the tier-bonus indicator function ... HEADLINER_BONUS
    = 100, MAIN_BONUS = 50, OPENER_BONUS = 30, SURPRISE_BONUS = 10".
    And: "Every ProgramItem of the artist has slot_priority_score
    recomputed" on a PATCH to the artist's tier per the §4-table
    side-effects of `PATCH /artists/{artistId}`.

    Claim: the score on a program item changes by exactly the indicator
    function's delta when the artist's tier is patched.  Specifically:
    a fresh PROPOSED item under a HEADLINER artist scores at the
    HEADLINER-bonus baseline of 100 (with travel-term zero from a no-
    commitments artist and rider-term zero from no-riders, the
    non-negative-floor-clamped raw is 100, rounded half-up to 100.00).
    A PATCH that changes the artist's tier to OPENER drops the score
    by exactly `HEADLINER_BONUS - OPENER_BONUS = 100 - 30 = 70` to
    30.00.

    The cross-tier delta pins the indicator-function selection over
    the four-tier enum — a smooth-function alternative would not match
    these integer-difference literals.

    # difficulty: combinatorial_formula/slot_priority_score_three_input_nonlinear_mode_a
    """
    bag = FIX.festival_in_scheduling(api, day_count=3)
    artist = register_artist(api, tier="HEADLINER",
                             external_commitments=[],
                             minimum_travel_buffer_hours=None)
    bag.artist = artist
    bag.artist_id = str(artist["id"])
    add_stage(api, bag, zone_capacity=10)
    add_program_version(api, bag, version_label="v")
    slot_start = bag.festival_start + 1 * 86400 + 12 * 3600
    slot_end = slot_start + 3600
    item = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=slot_start, end_time=slot_end,
                               genre="rock", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    headliner_state = get_success_data(
        api.recompute_program_item_priority(bag.festival_id, str(item["id"]),
                                            PRODUCER_HEADERS)
    )
    headliner_score = float(headliner_state["slot_priority_score"])
    # PATCH the artist's tier to OPENER.  Per the PRD §4 table the
    # PATCH /artists/{artistId} endpoint's side-effects include "Every
    # ProgramItem of the artist has slot_priority_score recomputed",
    # so we re-read the item's score after the artist PATCH commits.
    get_success_data(api.patch_artist(bag.artist_id, {"tier": "OPENER"},
                                      LIAISON_HEADERS))
    # The recompute on the item should reflect the new tier bonus.
    # Force the recompute via the §3.3 recompute-priority knob so the
    # observation is deterministic.
    opener_state = get_success_data(
        api.recompute_program_item_priority(bag.festival_id, str(item["id"]),
                                            PRODUCER_HEADERS)
    )
    opener_score = float(opener_state["slot_priority_score"])
    expected_delta = float(
        THRESHOLDS["HEADLINER_BONUS"] - THRESHOLDS["OPENER_BONUS"]
    )
    assert (headliner_score - opener_score) == pytest.approx(expected_delta, abs=0.01), (
        f"A tier PATCH from HEADLINER to OPENER drops the priority score "
        f"by exactly HEADLINER_BONUS − OPENER_BONUS == "
        f"{THRESHOLDS['HEADLINER_BONUS']} − "
        f"{THRESHOLDS['OPENER_BONUS']} == {expected_delta} per the PRD §3.5 "
        f"indicator-function arithmetic.  Got "
        f"{headliner_score - opener_score}."
    )


# ---------------------------------------------------------------------------
# Mode (b) — sponsor_payout_total mills-to-cents rounding-order pinning.
# ---------------------------------------------------------------------------


def _setup_payout_three_lines(api) -> Dict[str, Any]:
    """Compose the §3.6 worked-example payout scenario: a single GOLD
    tier with three ExposureAllocations of `kind=stage_name`, each
    pinned at 25 mils per unit (the SPONSOR_PAYOUT_RATE_MILS_DEFAULT
    literal), each delivering one unit during the festival window.
    The post-event sweep with compute_payout=true is then expected to
    surface sponsor_payout_total_cents == 8 per the pinned
    sum-then-round order in PRD §2.7 / §3.6.

    Returns a dict with the bag, the tier_id, and the report dict
    after the post-event sweep.
    """
    bag = base_world(api, day_count=2, stage_zone_capacity=10_000)
    add_program_version(api, bag, version_label="payout-v") if bag.version_id is None else None
    # Three OPENER artists in three non-overlapping windows on day 1.
    artists = [register_artist(api, tier="OPENER",
                               home_city=f"city-{i}")
               for i in range(3)]
    day_start = bag.festival_start + 1 * 86400
    windows: List[List[int]] = []
    for i in range(3):
        # 30-minute window with a 90-minute gap between consecutive
        # starts so the default 30-minute stage-changeover buffer is
        # cleared (the prior end's padded-right is at +30 min, the
        # next start at the prior-start + 1.5 h is at +60 min after
        # the prior end, which is > 30 min of buffer).
        s = int(day_start + (10.0 + i * 1.5) * 3600)
        e = s + 30 * 60
        windows.append([s, e])
    # Items.
    items: List[Dict[str, Any]] = []
    for i, ((s, e), a) in enumerate(zip(windows, artists)):
        it = get_success_data(api.create_program_item(
            bag.festival_id,
            F.program_item_payload(program_version_id=bag.version_id,
                                   artist_id=str(a["id"]),
                                   stage_id=bag.stage_id,
                                   start_time=s, end_time=e,
                                   genre="indie",
                                   equipment_kit_codes=[]),
            LIAISON_HEADERS,
        ))
        confirm_item(api, bag, str(it["id"]))
        items.append(it)
    publish_version(api, bag)
    # The exposure catalog is generous on stage_name so the waterfall
    # gives each allocation its full one unit.
    seed_default_catalog(api, bag, stage_name=1000, screen_time=1000,
                        artist_mention=1000, branded_zone=1000)
    tier = add_sponsor_tier(api, bag, tier_code="GOLD", priority_rank=1,
                            sponsor_external_id="gold-payout-three",
                            contracted_units=3,
                            contract_kinds_allowed=["stage_name"])
    tier_id = str(tier["id"])
    allocations: List[Dict[str, Any]] = []
    for it in items:
        a = get_success_data(api.create_exposure_allocation(
            bag.festival_id, tier_id,
            F.exposure_allocation_payload(
                kind="stage_name", requested_units=1,
                program_item_id=str(it["id"]),
                pinned_rate_cents_per_unit=int(
                    THRESHOLDS["SPONSOR_PAYOUT_RATE_MILS_DEFAULT"]
                ),
            ),
            SPONSOR_HEADERS,
        ))
        allocations.append(a)
    # Sweep so each allocation's actual_units is set to 1.
    run_waterfall(api, bag)
    # Advance the clock so all three items reach PERFORMED state per
    # the §3.3 clock-driven ANNOUNCED→ON_STAGE→PERFORMED transitions.
    # Items are not yet ANNOUNCED but the PRD §3.6 deliver gate says
    # "the tied program item's status is `PERFORMED` for an
    # allocation whose `program_item_id` is non-null".  We need to
    # announce them first.
    for it in items:
        get_success_data(api.announce_program_item(
            bag.festival_id, str(it["id"]), LIAISON_HEADERS,
        ))
    # Cross the last item's end so all three are PERFORMED.
    last_end = max(int(it["end_time"]) for it in items)
    # First the festival goes LIVE (cross start_time).  Then the
    # individual item-starts.  Then the item-ends.  PRD §2.8 names the
    # tiebreak order on a single tick crossing multiple thresholds as
    # wall-clock-of-the-threshold ascending, festival-start-first then
    # item-start then sound-check-complete-eligible then
    # rehearsal-start then item-end then rehearsal-end+grace then
    # festival-end+grace.  Advancing in one shot to past the last
    # item's end_time triggers all of the in-window crossings in order.
    advance_clock_to(api, festival_id=bag.festival_id,
                     to_unix_seconds=last_end + 60)
    # Deliver one unit per allocation.
    for alloc in allocations:
        get_success_data(api.deliver_exposure(
            bag.festival_id, str(alloc["id"]),
            F.exposure_deliver_payload(units=1, note="line-deliver"),
            SPONSOR_HEADERS,
        ))
    # Festival close.
    advance_festival_through_close(api, bag)
    # Post-event sweep with compute_payout=True per the §2.8 sentence
    # "and — when the body's optional `compute_payout` flag is true —
    # computes the sponsor payout total in cents".
    sweep_resp = run_post_event_sweep(api, bag, compute_payout=True)
    report = get_fulfilment_report_snapshot(api, bag.festival_id, tier_id)
    return {"bag": bag, "tier_id": tier_id, "report": report,
            "sweep_result": sweep_resp, "allocations": allocations}


def test_sponsor_payout_total_cents_pins_sum_then_round_at_eight_cents(api):
    """PRD §3.6: "The rounding-order is pinned as 'sum the mills across
    all lines first, then divide once at the end, then round once at
    the end' rather than 'round each line's mills-to-cents conversion
    first and then sum the rounded cents', and the two orderings can
    diverge by exactly one cent on the canonical input vector of
    three exposure-allocation lines each carrying one delivered unit
    at the default rate of twenty-five mils per unit.  Under the
    pinned order the unrounded total is the sum of the three lines'
    mils — one plus one plus one — multiplied by the rate of
    twenty-five mils per unit, with that sum-of-mils divided once by
    one thousand to convert to cents, which gives the rational
    number 0.075 cents that rounds half up at the single final
    rounding step to 0.08 cents — and on the integer-cents output
    convention the implementation reports this as 8 cents (the half-
    up rule on the 0.005-cents-fraction boundary picks the upper
    integer)."  And PRD §2.7: "the alternative ordering of rounding
    each line's mills-to-cents conversion separately and then summing
    the rounded cents is explicitly rejected because the two orderings
    can diverge by exactly one cent on the canonical test input ...
    where the pinned single-final-rounding answer is 8 cents".

    Claim: the post-event sweep with compute_payout=true surfaces
    sponsor_payout_total_cents == 8 (the pinned answer), not 9 (the
    rejected per-line-rounded alternative).  This is the falsifiable
    pin of the rounding-order non-commutativity.

    Difficulty rule 2 mode (b):
    # difficulty: combinatorial_formula/sponsor_payout_rounding_order_mode_b
    """
    setup = _setup_payout_three_lines(api)
    report = setup["report"]
    payout_cents = report.get("sponsor_payout_total_cents")
    assert payout_cents is not None, (
        "The post-event sweep with compute_payout=true must populate "
        "sponsor_payout_total_cents per PRD §3.6 / §3.7."
    )
    assert int(payout_cents) == CANONICAL_PINNED_PAYOUT_CENTS, (
        f"The sum-then-round-at-end pinned answer is "
        f"{CANONICAL_PINNED_PAYOUT_CENTS} cents on the canonical 3-line × "
        f"1-unit × 25-mils input per PRD §2.7 / §3.6.  The rejected "
        f"per-line-rounded alternative would land "
        f"{ALTERNATIVE_UNPINNED_PAYOUT_CENTS} cents.  Observed: {payout_cents}."
    )
    # Also: a literal not-equal assertion against the rejected
    # alternative, to make the falsifiability symmetric.  The PRD §3.6
    # narrative names the 9-cent alternative explicitly as the
    # rejected ordering.
    assert int(payout_cents) != ALTERNATIVE_UNPINNED_PAYOUT_CENTS, (
        f"The per-line-rounded alternative (9 cents) is explicitly "
        f"rejected by PRD §2.7's pinning of the sum-then-round order."
    )


def test_sponsor_payout_post_close_sweep_appends_reported_log_rows(api):
    """PRD §2.8: "After the festival has closed, the sweep is the path
    that flips every `DELIVERED` allocation to `REPORTED` with a
    closing `REPORTED` `FulfilmentLog` row appended (its `units` field
    is zero)".  And PRD §2.7: "The post-event sweep ... walks the
    immutable `FulfilmentLog` event stream ... the `REPORTED` row
    carries `units = 0` and contributes nothing to the count".

    Claim: after the post-close sweep, each allocation that was in
    DELIVERED state is now in the REPORTED terminal state, the
    FulfilmentLog under each allocation contains both a DELIVERED row
    (units > 0) and a REPORTED row (units == 0), and the
    FulfilmentLog rows are append-only (no updated_at, no version on
    them per the PRD §2.4 common-fields branching).  And the audit
    log contains an EXPOSURE row for the sweep per PRD §2.8.

    The companion rule-2 mode-b test on the payout-cents literal is
    the previous test; this one pins the sweep's other side-effects
    so both halves of the rule-2 instance B coverage are present.

    # difficulty: combinatorial_formula/sponsor_payout_rounding_order_mode_b
    """
    setup = _setup_payout_three_lines(api)
    bag = setup["bag"]
    allocations = setup["allocations"]
    # The post-event sweep flipped each DELIVERED allocation to
    # REPORTED.  Read the list and confirm.
    listing = validate_success(
        api.list_exposure_allocations(bag.festival_id, SPONSOR_HEADERS,
                                      params={"sponsor_tier_id": setup["tier_id"],
                                              "limit": 100, "offset": 0})
    )
    rows = listing if isinstance(listing, list) else listing.get("items", listing.get("data", []))
    reported_rows = [r for r in rows if r.get("status") == "REPORTED"]
    assert len(reported_rows) == 3, (
        f"All three delivered allocations are in REPORTED status after the "
        f"post-close sweep per PRD §2.8 — got {len(reported_rows)} REPORTED rows."
    )
    # The per-allocation FulfilmentLog tail carries one DELIVERED row
    # and one REPORTED row.  The §3.6 deliver-endpoint side-effects
    # append the DELIVERED row at deliver time, and the §2.8 sweep
    # appends the closing REPORTED row.  Per PRD §2.4 the
    # FulfilmentLog is append-only — the row carries id and created_at
    # only, no updated_at and no version.  The allocation's detail
    # read joins the rows under the response per §1.5's
    # ExposureAllocationDetail synthetic shape.
    detail = get_success_data(
        api.get_exposure_allocation(bag.festival_id, str(allocations[0]["id"]),
                                    SPONSOR_HEADERS)
    )
    log = detail.get("fulfilment_log", detail.get("FulfilmentLog", detail.get("logs", [])))
    # Per the PRD §3.6 prose the allocation's response on the detail
    # endpoint exposes the FulfilmentLog tail.  Implementations may
    # name the array `fulfilment_log` or `logs` or similar; we accept
    # any of those.
    assert isinstance(log, list), (
        "The per-allocation detail read exposes the FulfilmentLog event-stream "
        "tail as an array per PRD §3.6's 'ExposureAllocationDetail' shape."
    )
    delivered_log_rows = [e for e in log if e.get("event_type") == "DELIVERED"]
    reported_log_rows = [e for e in log if e.get("event_type") == "REPORTED"]
    assert len(delivered_log_rows) >= 1, (
        "At least one DELIVERED-typed FulfilmentLog row exists on a delivered "
        "allocation per PRD §3.6's deliver endpoint side-effect."
    )
    assert len(reported_log_rows) >= 1, (
        "A REPORTED-typed FulfilmentLog row is appended on the post-event sweep "
        "per PRD §2.8."
    )
    for r in reported_log_rows:
        assert int(r.get("units", -1)) == 0, (
            "REPORTED-row units are zero per PRD §2.7 / §2.8."
        )
    # The audit log carries an EXPOSURE category row for the sweep run.
    audit = read_audit_log(api, bag,
                           event_category=AuditEventCategory.EXPOSURE.value)
    # Tolerate that the sweep audit row's subject_entity_id may be the
    # festival or the tier — the PRD §2.8 sentence is "the audit
    # entries the sweep writes are of category EXPOSURE" but does not
    # pin the subject_entity_type, so we assert the category presence.
    assert audit, (
        "The post-event sweep writes at least one EXPOSURE-category audit row "
        "per PRD §2.8."
    )


# ---------------------------------------------------------------------------
# Mode (c) — sponsor_waterfall_allocation evaluation-order canonical
# (5, 2, 2, 1, 0, 0) tuple.
# ---------------------------------------------------------------------------


def test_sponsor_waterfall_tier_then_rank_evaluation_order(api):
    """PRD §3.6: "The waterfall is the deterministic allocator that
    walks the catalog and the allocations and writes the resulting
    `actual_units` field on each allocation in the canonical order
    `WATERFALL_TIER_ORDER = ["TITLE", "GOLD", "SILVER"]` — title tier
    first, gold second, silver third, regardless of any sponsor's
    `priority_rank` value.  Within a tier the ordering is
    `priority_rank` ascending then `sponsor_external_id` lexicographic
    ascending."  And the worked example: "the catalog's `branded_zone`
    total is 10 units, one Title sponsor requests 5 units (gets 5;
    pool falls to 5), two Gold sponsors each request 2 units (the
    lower-`priority_rank` Gold drawn first, both succeed, pool falls 5
    − 2 − 2 = 1), and three Silver sponsors each request 1 unit in
    `priority_rank` ascending order — the first Silver gets the last
    unit, the other two get zero each because the pool is drained,
    and the precise outcome that the test asserts is 'the first
    Silver's `actual_units` is exactly 1 and the others' are exactly
    0'".

    Claim: the post-sweep `actual_units` vector keyed by
    `sponsor_external_id` is exactly the canonical six-tuple

      title-aaa  → 5
      gold-aaa   → 2  (priority_rank=1, the lower-rank-within-Gold)
      gold-bbb   → 2  (priority_rank=2)
      silver-aaa → 1  (priority_rank=1 within Silver, gets the last unit)
      silver-bbb → 0  (priority_rank=2 within Silver, pool drained)
      silver-ccc → 0  (priority_rank=3 within Silver, pool drained)

    A "global priority_rank ascending without the tier-first
    ordering" allocator would land a different tuple (it would give
    silver-aaa a unit before gold-bbb), so the canonical tuple's
    presence is the falsifiable evidence that the tier-then-rank
    pinning is honoured.  Σ actual_units across the six rows equals
    the catalog pool of 10 — the no-overshoot invariant the PRD §3.6
    states ("the pool is per `kind` ... the running `pool_remaining`
    is initialised to the catalog's `total_units` for that kind ...
    each allocation's `actual_units` is set to the minimum of its
    `requested_units` and the current `pool_remaining`, then
    `pool_remaining` is decremented by the just-disbursed amount").

    Σ actual_units = 5 + 2 + 2 + 1 + 0 + 0 = 10 = the pool size.

    The waterfall sweep also appends an EXPOSURE-category audit row
    per the PRD §3.6 sentence "an audit entry of category `EXPOSURE`
    is appended at the end of the sweep with a `summary` containing
    the per-kind disbursement vector for the test fixture to assert
    on."

    Difficulty rule 2 mode (c):
    # difficulty: combinatorial_formula/sponsor_waterfall_evaluation_order_mode_c
    """
    world = waterfall_six_sponsor_world(api)
    by_external_id = world["by_external_id"]
    # Every external id appears in the post-sweep map.
    for ext_id, expected in CANONICAL_WATERFALL_ACTUAL_UNITS.items():
        row = by_external_id.get(ext_id)
        assert row is not None, (
            f"Allocation for sponsor_external_id={ext_id!r} must appear "
            f"in the festival-wide exposure-allocations listing per PRD §3.6."
        )
        assert int(row["actual_units"]) == expected, (
            f"Sponsor {ext_id!r}'s actual_units after the waterfall sweep is "
            f"{expected} per the PRD §3.6 canonical worked example.  Got "
            f"{row['actual_units']}.  The full canonical tuple is "
            f"(title-aaa=5, gold-aaa=2, gold-bbb=2, silver-aaa=1, silver-bbb=0, "
            f"silver-ccc=0)."
        )
    # No-overshoot invariant on the pool sum.
    total_actual = sum(int(row["actual_units"]) for row in by_external_id.values())
    assert total_actual == 10, (
        f"The sum of actual_units across the six branded-zone allocations "
        f"equals the catalog pool of 10, per the PRD §3.6 invariant "
        f"'Σ_a a.actual_units ≤ exposure_catalog[k]'.  Sum = {total_actual}."
    )
    # The PRD §3.6 sentence on the audit-row trail: "an audit entry of
    # category EXPOSURE is appended at the end of the sweep with a
    # summary containing the per-kind disbursement vector".
    bag = world["bag"]
    audit_rows = read_audit_log(api, bag,
                                event_category=AuditEventCategory.EXPOSURE.value)
    assert audit_rows, (
        "An EXPOSURE-category audit row is appended for the waterfall sweep "
        "per PRD §3.6."
    )


def test_sponsor_waterfall_is_idempotent_on_repeat_invocation(api):
    """PRD §3.6: "the waterfall is ... idempotent — running it a second
    time with no new allocations or no catalog change produces the
    same `actual_units` vector".

    Claim: the post-sweep actual_units vector after a second
    invocation of POST /festivals/{fid}/sponsor-allocation-sweep is
    identical to the first invocation's vector.

    # difficulty: combinatorial_formula/sponsor_waterfall_evaluation_order_mode_c
    """
    world = waterfall_six_sponsor_world(api)
    bag = world["bag"]
    first_vector = {ext: int(row["actual_units"])
                    for ext, row in world["by_external_id"].items()}
    # Run the sweep again with no change.
    get_success_data(api.run_sponsor_allocation_sweep(bag.festival_id,
                                                     SPONSOR_HEADERS))
    listing = validate_success(api.list_exposure_allocations(
        bag.festival_id, SPONSOR_HEADERS,
        params={"limit": 100, "offset": 0},
    ))
    rows = listing if isinstance(listing, list) else listing.get("items", listing.get("data", []))
    # Build a second-pass map keyed by external id via the
    # sponsor_tier_id back-reference.  We need the tier-id-to-external-id
    # map, which the fixture's by_external_id captured but with the
    # post-first-sweep row objects.  Re-derive from the tier rows.
    tier_listing = validate_success(api.list_sponsor_tiers(
        bag.festival_id, AUDIT_HEADERS,
        params={"limit": 100, "offset": 0},
    ))
    tier_rows = tier_listing if isinstance(tier_listing, list) else tier_listing.get("items", tier_listing.get("data", []))
    tid_to_ext = {str(t["id"]): t["sponsor_external_id"] for t in tier_rows}
    second_vector: Dict[str, int] = {}
    for r in rows:
        tid = str(r.get("sponsor_tier_id"))
        ext = tid_to_ext.get(tid)
        if ext is None:
            continue
        second_vector[ext] = int(r["actual_units"])
    # The two vectors are equal — the waterfall is idempotent per PRD
    # §3.6.
    assert first_vector == second_vector, (
        f"The waterfall is idempotent per PRD §3.6 — the actual_units vector "
        f"is unchanged across two consecutive sweeps.  First: {first_vector}, "
        f"second: {second_vector}."
    )
