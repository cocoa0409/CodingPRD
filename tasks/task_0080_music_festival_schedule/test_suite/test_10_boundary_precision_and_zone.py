"""Boundary-precision tests on three different metrics — rule-6 in the
difficulty design, on three different endpoints.

  Instance A — the artist travel-buffer-gap inclusive-≥ boundary in
  wall-clock seconds.  PRD §3.5: "The boundary is inclusive —
  equality on the gap is acceptable, strict less-than is the
  rejection at HTTP 409 with `ERR_ARTIST_TRAVEL_BUFFER_VIOLATION`."
  The acceptance side is gap == minimum_travel_buffer_seconds; the
  rejection side is gap == minimum_travel_buffer_seconds − 1.

  Instance B — the ticket-zone capacity strict-`>` boundary on the
  integer post-increment count.  PRD §3.4: "The boundary is strict-
  greater-than on the post-increment cumulative count: pre-increment
  cumulative equal to `zone_capacity − count` (the very-last-ticket
  case at the boundary) is accepted, and the next increment that
  would push the cumulative count above `zone_capacity` is rejected
  at HTTP 422 with `ERR_TICKET_ZONE_CAPACITY_EXCEEDED`."  And the
  zero-capacity degenerate case: `ERR_TICKET_ZONE_NO_STAGE` at HTTP
  422 when the zone group has no tied stage.

  Instance C — the headliner blocking-rider cardinality 0-vs-1
  boundary on a non-negative integer count.  PRD §3.3 / §3.5: "the
  boundary precisely at zero versus one — a HEADLINER announcing
  with zero blocking riders is rejected and a HEADLINER announcing
  with exactly one fulfilled blocking rider on file is accepted".
  The PRD §1.6 catalog pins the error id as
  `ERR_HEADLINER_MISSING_BLOCKING_RIDER` at HTTP 422.

The three metrics — wall-clock seconds, integer post-increment count,
non-negative-integer cardinality — are categorically different, on
three different endpoints, which satisfies the "different metrics on
different endpoints" clause the rule-6 difficulty entry calls out.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from test_helpers import (
    ApiErrorId,
    AUDIT_HEADERS,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    STAGE_HEADERS,
    THRESHOLDS,
    TICKETING_HEADERS,
    add_program_item,
    add_program_version,
    add_stage,
    add_ticket_type,
    base_world,
    confirm_item,
    confirmed_published_world_with_ticket,
    external_commitment,
    factories as F,
    fixtures as FIX,
    get_success_data,
    issue_tickets,
    publish_version,
    register_artist,
    rider_fulfil_payload,
    rider_payload,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Rule 6 instance A — the travel-buffer gap inclusive-≥ boundary in
# wall-clock seconds, on the program-item-confirm endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("delta_seconds, expect_accept", [
    (0,  True),   # gap == minimum_travel_buffer_seconds exactly — accepted.
    (-1, False),  # gap == minimum_travel_buffer_seconds − 1 — rejected.
])
def test_travel_buffer_inclusive_ge_boundary_on_confirm(api, delta_seconds, expect_accept):
    """PRD §3.5: "the artist's `minimum_travel_buffer_hours` (defaulting
    to the global `TRAVEL_HOURS_MIN = 4` of four hours when the
    per-artist override is null) converted to seconds by multiplying
    by 3600.  The boundary is inclusive — equality on the gap is
    acceptable, strict less-than is the rejection at HTTP 409 with
    `ERR_ARTIST_TRAVEL_BUFFER_VIOLATION`."

    Claim: the boundary precision pair is at `gap_seconds == buffer`
    on the accept side and `gap_seconds == buffer − 1` on the reject
    side, with all other inputs identical between the two cases.

    The "gap" is the integer-second difference from the artist's
    latest-preceding external_commitment.end_time to the candidate's
    start_time per PRD §3.5.  The "minimum_travel_buffer_seconds" is
    the artist's `minimum_travel_buffer_hours * 3600` (with the
    global default of 4 hours when the per-artist override is null).

    Difficulty rule 6 instance A:
    # difficulty: boundary_precision_check/artist_travel_buffer_seconds_inclusive_ge_on_confirm
    """
    # We need a candidate item whose artist has an external
    # commitment whose end_time is `target_gap` seconds before the
    # item's start_time.  Set the artist's
    # minimum_travel_buffer_hours to a small explicit value (1 hour
    # == 3600 seconds) so the boundary case is short enough to fit
    # comfortably inside a 3-day festival window.  The PRD §2.4
    # narrative says the per-artist override "overrides the global
    # `TRAVEL_HOURS_MIN` of four hours when the per-artist override
    # is not null" — and the §3.5 narrative says "The gate is 'the
    # gap in seconds from the latest preceding external commitment's
    # end_time to the candidate's start_time is at least the artist's
    # `minimum_travel_buffer_hours` (defaulting to the global
    # `TRAVEL_HOURS_MIN = 4` of four hours when the per-artist
    # override is null) converted to seconds by multiplying by 3600.'"
    # The per-artist override avoids the multi-festival-overlap rule
    # also firing because we keep the commitment's window strictly
    # before the candidate's window (a non-intersecting pair).
    buffer_hours = 1
    buffer_seconds = buffer_hours * 3600
    target_gap = buffer_seconds + delta_seconds  # gap exactly at the
                                                  # boundary (delta=0)
                                                  # or one second short
                                                  # (delta=-1).
    bag = FIX.festival_in_scheduling(api, day_count=3)
    add_stage(api, bag, zone_capacity=10)
    # The artist's external commitment ends `target_gap` seconds before
    # the candidate's start_time and starts well before that (so the
    # commitment's window is a fixed interval that ends strictly
    # before the candidate's window starts — no PRD §3.5 multi-
    # festival-temporal-overlap of intersecting windows fires).
    cand_start = bag.festival_start + 86400 + 12 * 3600
    cand_end = cand_start + 1800
    commitment_end = cand_start - target_gap
    commitment_start = commitment_end - 3600  # one-hour commitment.
    assert commitment_start < commitment_end <= cand_start, \
        "Test fixture sanity: the commitment ends at or before the candidate's start."
    ec = external_commitment(festival_external_id="Ext-A",
                              start_time=commitment_start,
                              end_time=commitment_end,
                              city="Other")
    artist = get_success_data(api.create_artist(
        F.artist_payload(stage_name="BoundaryArtist",
                         tier="OPENER",
                         home_city="Local",
                         external_commitments=[ec],
                         minimum_travel_buffer_hours=buffer_hours),
        LIAISON_HEADERS,
    ))
    add_program_version(api, bag, version_label="boundary-a") if bag.version_id is None else None
    # Create the item.  The PRD §3.3 note "the overlap, travel-buffer,
    # multi-festival-conflict ... checks all run at creation time as
    # advisory rejections — they reject the create when violated"
    # means the create call itself is the observation point on the
    # reject side.  The §3.5 sentence "the explicit gate that fires
    # on the program-item-create capability (advisorily, where the
    # create still succeeds but the item is then unable to confirm)
    # and authoritatively on the `confirm` transition" pins the
    # confirm endpoint as the authoritative observation point.  The
    # ambiguous "advisorily" wording leaves the create either as a
    # reject-on-bad or as an accept-with-confirm-rejection — both are
    # PRD-faithful readings, so we observe whichever happens.
    create_body = F.program_item_payload(
        program_version_id=bag.version_id,
        artist_id=str(artist["id"]),
        stage_id=bag.stage_id,
        start_time=cand_start, end_time=cand_end,
        genre="g", equipment_kit_codes=[],
    )
    create_resp = api.create_program_item(bag.festival_id, create_body,
                                          LIAISON_HEADERS)
    if expect_accept:
        # The accepted-boundary case must clear both the create and
        # the confirm.
        item = validate_success(create_resp, expected_status=201)
        confirmed = validate_success(api.confirm_program_item(
            bag.festival_id, str(item["id"]), LIAISON_HEADERS,
        ))
        assert confirmed["status"] == "CONFIRMED", (
            f"With gap_seconds == minimum_travel_buffer_seconds (== "
            f"{buffer_seconds}), the inclusive-≥ boundary of PRD §3.5 "
            f"accepts the confirm."
        )
    else:
        # The rejected-boundary case may fail on the create (if the
        # implementation reads the §3.3 sentence as the strict
        # create-time rejection) or on the confirm (the
        # authoritative-confirm-time interpretation).  Both are PRD-
        # consistent.  Either way, the observed error id is
        # ERR_ARTIST_TRAVEL_BUFFER_VIOLATION at HTTP 409.
        if create_resp.status_code >= 400:
            validate_error(
                create_resp,
                ApiErrorId.ERR_ARTIST_TRAVEL_BUFFER_VIOLATION.value,
                expected_status=409,
            )
        else:
            item = validate_success(create_resp, expected_status=201)
            confirm_resp = api.confirm_program_item(
                bag.festival_id, str(item["id"]), LIAISON_HEADERS,
            )
            validate_error(
                confirm_resp,
                ApiErrorId.ERR_ARTIST_TRAVEL_BUFFER_VIOLATION.value,
                expected_status=409,
            )


def test_travel_buffer_no_preceding_commitment_is_trivially_satisfied(api):
    """PRD §3.5: the travel-buffer check considers only "the latest
    preceding external_commitment's `end_time` to the candidate's
    `start_time`".  When there are no preceding commitments — the
    artist's external_commitments array is empty, or all of its
    entries' end_time fall after the candidate's start_time — the
    gate is trivially satisfied (no gap to enforce).

    Claim: an artist with an empty `external_commitments` array
    confirms an item with no rejection.  This is the empty-set
    boundary edge of the same metric, which the PRD §3.5 narrative
    handles implicitly through the "the latest preceding commitment"
    qualifier — no preceding commitment means no constraint.

    # difficulty: boundary_precision_check/artist_travel_buffer_seconds_inclusive_ge_on_confirm
    """
    bag = base_world(api, day_count=2,
                     artist_external_commitments=[],
                     artist_min_buffer_hours=None,
                     stage_zone_capacity=10)
    item = get_success_data(api.create_program_item(
        bag.festival_id,
        F.program_item_payload(program_version_id=bag.version_id,
                               artist_id=bag.artist_id,
                               stage_id=bag.stage_id,
                               start_time=bag.festival_start + 3600,
                               end_time=bag.festival_start + 7200,
                               genre="g", equipment_kit_codes=[]),
        LIAISON_HEADERS,
    ))
    confirmed = validate_success(api.confirm_program_item(
        bag.festival_id, str(item["id"]), LIAISON_HEADERS,
    ))
    assert confirmed["status"] == "CONFIRMED", \
        ("An artist with no external commitments trivially clears the "
         "travel-buffer rule per the PRD §3.5 'latest preceding "
         "commitment' qualifier — the empty-preceding-set case has no "
         "constraint.")


# ---------------------------------------------------------------------------
# Rule 6 instance B — the ticket-zone capacity strict-`>` boundary on the
# integer post-increment count, on the ticket-issue endpoint.
# ---------------------------------------------------------------------------


def test_ticket_zone_capacity_strict_post_increment_boundary(api):
    """PRD §3.4: "The boundary is strict-greater-than on the post-
    increment cumulative count: pre-increment cumulative equal to
    `zone_capacity − count` (the very-last-ticket case at the
    boundary) is accepted, and the next increment that would push
    the cumulative count above `zone_capacity` is rejected at HTTP
    422 with `ERR_TICKET_ZONE_CAPACITY_EXCEEDED`."

    Claim: with a zone whose capacity is `Z` and a fresh ticket type
    whose `tied_program_item_ids` references the program item on a
    stage with `zone_capacity == Z`, the cumulative-issued count can
    grow to exactly Z without rejection (the boundary is inclusive
    on the accept side of the strict-`>` rule), and the next
    one-unit issuance fails with `ERR_TICKET_ZONE_CAPACITY_EXCEEDED`
    at HTTP 422.

    A concrete arithmetic example with Z=5: a single issuance of 5
    is accepted (cumulative goes from 0 to 5, equality, the strict-
    `>` of "5 > 5" is false, so it's accepted), and the next
    issuance of 1 pushes cumulative to 6 which is `> 5`, the
    rejection case.  The PRD §1.6 catalog pins the error id at 422.

    Difficulty rule 6 instance B:
    # difficulty: boundary_precision_check/ticket_zone_capacity_strict_gt_post_increment_on_issue
    """
    Z = 5
    bag = base_world(api, day_count=2, stage_zone_capacity=Z)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    item_id = str(bag.program_item["id"])
    # Confirm the item so the §3.3 lifecycle gate is satisfied.
    confirm_item(api, bag, item_id)
    # Publish the version so the ticket-type's "tie set is non-empty"
    # and the festival is in PUBLISHED.  The fixture's
    # confirmed_published_world_with_ticket also goes through these
    # steps but with extra rider-and-announce machinery for HEADLINER
    # cases that we don't need here.
    publish_version(api, bag)
    tt = get_success_data(api.create_ticket_type(
        bag.festival_id,
        F.ticket_type_payload(ticket_class="SINGLE_DAY",
                              tied_program_item_ids=[item_id],
                              zone_name="ZoneCap",
                              unit_price_cents=1000),
        TICKETING_HEADERS,
    ))
    tt_id = str(tt["id"])
    # Issue Z tickets in a single call.  PRD §3.4's strict-`>` rule
    # accepts when the post-increment cumulative is no greater than
    # the zone capacity, so Z == Z is the inclusive-on-the-accept-
    # side boundary.
    accept_resp = api.issue_tickets(bag.festival_id, tt_id,
                                    F.ticket_issue_payload(count=Z),
                                    TICKETING_HEADERS)
    accept_data = validate_success(accept_resp)
    assert accept_data["issued_count"] == Z, \
        f"The boundary issuance of count={Z} on a zone of capacity Z=={Z} is accepted per PRD §3.4."
    # The next one-unit issuance pushes the cumulative above Z, the
    # strict-`>` rejection case.
    reject_resp = api.issue_tickets(bag.festival_id, tt_id,
                                    F.ticket_issue_payload(count=1),
                                    TICKETING_HEADERS)
    validate_error(reject_resp,
                   ApiErrorId.ERR_TICKET_ZONE_CAPACITY_EXCEEDED.value,
                   expected_status=422)
    # The ticket type's issued_count is still Z (the rejection didn't
    # increment).
    post = get_success_data(api.get_ticket_type(bag.festival_id, tt_id, AUDIT_HEADERS))
    assert post["issued_count"] == Z, \
        "A rejected issuance does not increment issued_count per the §3.4 'serialise the counter increment' rule."


def test_ticket_zone_no_stage_zero_capacity_degenerate_edge(api):
    """PRD §3.4: "The zero-capacity edge — when the zone group has no
    tied stage at all from which to derive a `zone_capacity`, so the
    implicit cap is zero — is rejected at the same priority with
    `ERR_TICKET_ZONE_NO_STAGE` at HTTP 422."

    Claim: a ticket-type whose `tied_program_item_ids` array is empty
    — so the zone group has no tied stage to derive a capacity from
    — rejects any issuance with the dedicated
    `ERR_TICKET_ZONE_NO_STAGE` error id at HTTP 422, distinct from
    the regular over-capacity `ERR_TICKET_ZONE_CAPACITY_EXCEEDED`.

    This is the zero-quantity degenerate edge of the same integer-
    count metric the prior test exercised at the cap-boundary.

    # difficulty: boundary_precision_check/ticket_zone_capacity_strict_gt_post_increment_on_issue
    """
    bag = base_world(api, day_count=2, stage_zone_capacity=100)
    # No program items at all so the ticket type's tied_program_item_ids
    # is the empty list.  The §3.4 sentence on the zero-capacity edge
    # — "the zone group has no tied stage at all from which to derive
    # a `zone_capacity`" — applies in this exact case.
    # We need the festival in PUBLISHED so the ticket-type create
    # itself isn't blocked by anything else; publish a version even
    # without items.  Wait, PRD §3.3's
    # ERR_EMPTY_PROGRAM_VERSION-on-submit-for-review prevents
    # publishing a version with zero items.  We have a fixture-side
    # workaround: add a single program item under V1 (which is on a
    # stage whose zone_capacity is large, so the regular zone-capacity
    # rule on that item's zone wouldn't fire on a separate ticket
    # type whose tied list does not include this item).  Then
    # publish V1.  The fresh ticket type under test has an empty
    # tied_program_item_ids list, so the zone-group's tied-stage set
    # is also empty — the zero-capacity-edge condition the PRD §3.4
    # narrative names.
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    # The empty-tied-list ticket type.
    tt = get_success_data(api.create_ticket_type(
        bag.festival_id,
        F.ticket_type_payload(ticket_class="SINGLE_DAY",
                              tied_program_item_ids=[],
                              zone_name="NoStageZone",
                              unit_price_cents=1500),
        TICKETING_HEADERS,
    ))
    tt_id = str(tt["id"])
    # Any positive-count issuance against an empty-tied-list type's
    # zone fires ERR_TICKET_ZONE_NO_STAGE per the PRD §3.4 sentence.
    bad_resp = api.issue_tickets(bag.festival_id, tt_id,
                                 F.ticket_issue_payload(count=1),
                                 TICKETING_HEADERS)
    validate_error(bad_resp, ApiErrorId.ERR_TICKET_ZONE_NO_STAGE.value,
                   expected_status=422)


# ---------------------------------------------------------------------------
# Rule 6 instance C — the HEADLINER blocking-rider cardinality 0-vs-1
# boundary on the program-item-announce endpoint.
# ---------------------------------------------------------------------------


def test_headliner_announce_with_zero_blocking_riders_rejected(api):
    """PRD §3.3 / §3.5: "the `blocking_rider_minimum_check`: when the
    artist's `tier` is `HEADLINER`, the total count of blocking
    riders on the item must be at least the constant
    `HEADLINER_MIN_BLOCKING_RIDERS = 1`, otherwise
    `ERR_HEADLINER_MISSING_BLOCKING_RIDER` at HTTP 422 fires, with
    the boundary precisely at zero versus one — a HEADLINER
    announcing with zero blocking riders is rejected and a
    HEADLINER announcing with exactly one fulfilled blocking rider
    on file is accepted."

    Claim: a HEADLINER program item with zero blocking riders is
    rejected on announce with `ERR_HEADLINER_MISSING_BLOCKING_RIDER`
    at HTTP 422 — the boundary's zero side, with the integer-
    cardinality count of `is_blocking=true` riders being zero.

    Difficulty rule 6 instance C (rejection side):
    # difficulty: boundary_precision_check/headliner_blocking_rider_cardinality_zero_vs_one_on_announce
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=2, unit_price_cents=1000, initial_issued=0,
        artist_tier="HEADLINER", headliner_blocking_rider=False,
    )
    # The fixture leaves the HEADLINER item in CONFIRMED (it skips
    # the announce step because headliner_blocking_rider=False — and
    # consequently the fixture itself does not append any blocking
    # rider).  The item therefore has zero blocking riders, the
    # cardinality-zero side of the boundary.
    item_id = bag.program_item_id
    resp = api.announce_program_item(bag.festival_id, item_id, LIAISON_HEADERS)
    validate_error(resp,
                   ApiErrorId.ERR_HEADLINER_MISSING_BLOCKING_RIDER.value,
                   expected_status=422)


def test_headliner_announce_with_one_fulfilled_blocking_rider_accepted(api):
    """The accept-side counter-test of the same boundary: a HEADLINER
    item with exactly one blocking rider on file whose `fulfilled_at`
    is non-null clears both halves of the announce-time
    blocking-rider check per PRD §3.3 (the cardinality-≥-1 minimum
    and the universal "every blocking rider is fulfilled" condition).
    The fixture's HEADLINER + headliner_blocking_rider=True path
    creates the exact-one-fulfilled-blocking-rider scenario and the
    announce step succeeds.

    Pair this with the zero-rider rejection test above: the two
    tests together pin the 0-vs-1 boundary precision per the PRD
    §3.5 sentence "the boundary precisely at zero versus one — a
    HEADLINER announcing with zero blocking riders is rejected and a
    HEADLINER announcing with exactly one fulfilled blocking rider
    on file is accepted".

    # difficulty: boundary_precision_check/headliner_blocking_rider_cardinality_zero_vs_one_on_announce
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=2, unit_price_cents=1000, initial_issued=0,
        artist_tier="HEADLINER", headliner_blocking_rider=True,
    )
    # With headliner_blocking_rider=True, the fixture has already
    # appended one blocking rider, fulfilled it, and called announce.
    # The fixture's bag.program_item is therefore the post-announce
    # snapshot of the item.  Re-read to confirm.
    item_id = bag.program_item_id
    item_state = get_success_data(api.get_program_item(
        bag.festival_id, item_id, AUDIT_HEADERS,
    ))
    assert item_state["status"] == "ANNOUNCED", (
        "A HEADLINER with exactly one fulfilled blocking rider can "
        "announce per the PRD §3.5 cardinality-1 accept-side of the "
        "0-vs-1 boundary."
    )


def test_non_headliner_with_zero_blocking_riders_announces_cleanly(api):
    """PRD §3.3: "Non-headliner tiers (`MAIN`, `OPENER`, `SURPRISE`)
    have a required-blocking minimum of 0 and so trivially pass the
    cardinality step".

    Claim: a non-headliner program item (OPENER) with zero blocking
    riders announces cleanly — the cardinality-minimum-of-0 case
    applies, so the `ERR_HEADLINER_MISSING_BLOCKING_RIDER` gate does
    not fire.  The empty-set boundary edge on the non-HEADLINER side
    of the indicator function.

    # difficulty: boundary_precision_check/headliner_blocking_rider_cardinality_zero_vs_one_on_announce
    """
    # OPENER tier so the cardinality minimum is zero.  The fixture's
    # publish_the_version=True path drives the festival into
    # PUBLISHED, the §3.3 announce-precondition.  The OPENER's
    # sound_check_status is NOT_REQUIRED at create time, so the
    # cross-axis sound-check gate of §3.3 is satisfied as well.
    bag = FIX.confirmed_item_world(api, artist_tier="OPENER",
                                   publish_the_version=True)
    item_id = bag.program_item_id
    announced = validate_success(api.announce_program_item(
        bag.festival_id, item_id, LIAISON_HEADERS,
    ))
    assert announced["status"] == "ANNOUNCED", (
        "A non-HEADLINER's announce with zero blocking riders is "
        "accepted per the PRD §3.3 cardinality-0-on-non-HEADLINER rule."
    )
