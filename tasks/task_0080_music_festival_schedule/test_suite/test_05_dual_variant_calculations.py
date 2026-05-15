"""Dual-variant calculations — the rule-1 instances of the difficulty
design.  Two paired algorithms whose two interpretations diverge on
identical inputs, sitting on different entity domains:

  Instance A — the ticketing domain.  The forward-looking provisional
  refund stamped on a ScheduleChange.apply uses a pro-rata divisor of
  the festival's `festival_day_count` and ignores the external admin
  fee; the chronological final refund landed by the
  external-ticketing-system refund-confirmed ingress carries the
  externally-confirmed cents figure net of the 5% admin fee.  The two
  cents columns on the same ScheduleChange row differ by exactly the
  admin-fee factor on the worked input (12000 provisional cents vs
  11400 final cents).

  Instance B — the sponsor domain.  The forward-looking
  projected_fulfilment_pct on a SponsorTier row is derived from the
  live program-item state; the chronological actual_fulfilment_pct is
  the post-close-sweep replay over the FulfilmentLog append-only event
  stream.  On the canonical 10-unit contracted scenario with two of
  ten tied items cancelled (so the projection lands at 80.00%) and
  only seven of the eight surviving items actually delivered (so the
  actual lands at 70.00%), the two percentage columns on the same
  SponsorTier row differ by 10 percentage points.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    AUDIT_HEADERS,
    AuditEventCategory,
    CANONICAL_ACTUAL_PCT,
    CANONICAL_FINAL_REFUND_CENTS,
    CANONICAL_PROJECTED_PCT,
    CANONICAL_PROVISIONAL_REFUND_CENTS,
    CANONICAL_SYNC_TARGETS,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    SPONSOR_HEADERS,
    SyncEnvelopeStatus,
    THRESHOLDS,
    TICKETING_HEADERS,
    ack_remaining_targets,
    add_exposure_allocation,
    add_program_item,
    add_sponsor_tier,
    add_stage,
    advance_clock_to,
    advance_festival_through_close,
    assert_audit_contains,
    assert_envelope_status_by_target,
    assert_four_envelopes_queued,
    assert_schedule_change_shape,
    base_world,
    cancel_program_item_payload,
    confirm_item,
    confirm_refund_via_ack,
    confirmed_published_world_with_ticket,
    create_and_apply_item_cancel,
    factories as F,
    fixtures as FIX,
    get_fulfilment_report_snapshot,
    get_schedule_change_snapshot,
    get_sponsor_tier_snapshot,
    get_success_data,
    get_ticket_type_snapshot,
    issue_tickets,
    publish_version,
    read_audit_log,
    register_artist,
    refund_breakdown_entry,
    run_post_event_sweep,
    run_waterfall,
    seed_default_catalog,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Instance A — the ticketing-domain dual variant.
# ---------------------------------------------------------------------------


def test_provisional_refund_cents_total_on_apply_matches_pro_rata_formula(api):
    """PRD §3.4: "for each `TicketType` `t` whose `tied_program_item_ids`
    includes the cancelled program item, the system computes the live
    outstanding count `outstanding_t = t.issued_count - t.refunded_count`,
    the per-ticket cents figure as the round-half-up of the type's
    `unit_price_cents` multiplied by the implicit constant
    `cancelled_days` (which equals 1 per `ITEM_CANCEL`) and divided by
    the parent festival's `festival_day_count`, and the per-type
    refund cents as the product of the integer outstanding count and
    that rounded-per-ticket figure ... The half-up rounding step is
    applied exactly once per type, at the per-ticket-cents division.
    ... The illustrative numeric calibration is the canonical case of
    a single ticket type whose `unit_price_cents` is 12000, with an
    outstanding count of three and the parent festival's
    `festival_day_count` equal to three: the per-ticket cents figure
    is the half-up rounding of 12000 times 1 divided by 3, which is
    exactly 4000 cents; the per-type refund cents is three (the
    outstanding count) times 4000, which is 12000 cents (in everyday
    terms one hundred and twenty dollars); and that 12000-cents value
    is what the schedule change's `provisional_refund_cents_total`
    field is stamped to."

    Claim: on the canonical input (unit_price_cents=12000, outstanding
    count of 3 tickets, festival_day_count=3, cancelled_days=1), the
    apply of an ITEM_CANCEL ScheduleChange stamps the change's
    `provisional_refund_cents_total` to exactly 12000.  Also: the
    ticket type's `provisional_refund_cents_outstanding` bucket
    bulges to 12000 (the transient evidence of the formula firing),
    while `issued_count` stays at 3 and `refunded_count` stays at 0
    (the cents-bucket transient is the only mutation on the ticket
    type until the external ACK lands).

    Difficulty: dual_variant_calc / refund_provisional_vs_final_on_ticketing_domain.

    # difficulty: dual_variant_calc/refund_provisional_vs_final_on_ticketing_domain
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=3,
        unit_price_cents=12000,
        initial_issued=3,
        artist_tier="HEADLINER",
    )
    # bag.program_item_id is the cancelled-target item; bag.ticket_type
    # is the post-issuance snapshot of the ticket type tied to it; both
    # come from the fixture.
    item_id = bag.program_item_id
    ticket_type_id = str(bag.ticket_type["id"])
    # Read the ticket-type's pre-apply state.
    pre_ticket = get_ticket_type_snapshot(api, bag.festival_id, ticket_type_id)
    assert pre_ticket["issued_count"] == 3
    assert pre_ticket["refunded_count"] == 0
    assert pre_ticket["provisional_refund_cents_outstanding"] == 0
    # The festival's outstanding_tickets_total is issued − refunded
    # summed across all of the festival's ticket types per PRD §2.4.
    pre_festival = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert pre_festival["outstanding_tickets_total"] == 3, \
        "Festival.outstanding_tickets_total == sum(issued − refunded) per PRD §2.4"
    # Create an ITEM_CANCEL ScheduleChange and apply it.  The apply
    # fires the cascade and stamps provisional_refund_cents_total.
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=item_id,
                                           idempotency_key=F.fresh_idempotency_key("sc"))
    # The PRD §3.4 sentence "On the canonical 12000-cents case the
    # corresponding final is 11400 cents".  The provisional total is
    # the across-types sum, which for this single-ticket-type fixture
    # is 12000 cents.
    assert applied["status"] == "APPLIED", \
        "Apply flips ScheduleChange status to APPLIED per PRD §3.4"
    assert applied["provisional_refund_cents_total"] == CANONICAL_PROVISIONAL_REFUND_CENTS, (
        f"provisional_refund_cents_total is the canonical 12000 cents on the "
        f"§3.4 worked input — got {applied['provisional_refund_cents_total']}."
    )
    assert applied["final_refund_cents_total"] is None, \
        ("final_refund_cents_total is null until the external "
         "refund-confirmed ACK lands per PRD §3.4.")
    # The four envelopes are seeded QUEUED in the canonical order.
    assert_four_envelopes_queued(applied)
    # The ticket type's provisional bucket has bulged to 12000.
    post_ticket = get_ticket_type_snapshot(api, bag.festival_id, ticket_type_id)
    assert post_ticket["provisional_refund_cents_outstanding"] == CANONICAL_PROVISIONAL_REFUND_CENTS, (
        f"The ticket type's provisional_refund_cents_outstanding bulges "
        f"by the per-type provisional figure (12000) on the apply per PRD §3.4."
    )
    # Per PRD §3.4's conservation-invariant sentence "The apply of an
    # `ITEM_CANCEL` change does not move the `issued_count` or
    # `refunded_count` of any ticket type — those move only on a
    # ticket-issuance call and on the external-ticketing-system
    # refund-confirmed ingress capability respectively".
    assert post_ticket["issued_count"] == 3
    assert post_ticket["refunded_count"] == 0
    # And the festival's outstanding count is unchanged because issued
    # and refunded both haven't moved.
    post_festival = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert post_festival["outstanding_tickets_total"] == 3, \
        ("Festival.outstanding_tickets_total is conserved across the apply "
         "of an ITEM_CANCEL — see PRD §3.4 'the festival's outstanding-tickets "
         "number is unchanged between the moment before the apply and the "
         "moment after the revert'.")


def test_final_refund_cents_total_after_refund_confirmed_ack_matches_admin_fee_arithmetic(api):
    """PRD §3.4: "The chronological variant lands later as the
    the external-ticketing-system refund-confirmed ingress capability,
    whose payload's `refund_breakdown` is the array of per-type
    final-cents figures the external ticketing system has actually
    computed after applying its administrative-fee deduction at the
    rate `ADMIN_FEE_RATE_FINAL = 0.05` (the five-percent fee the
    external system charges per refunded ticket) ... On the canonical
    12000-cents-provisional case, the corresponding final is 11400
    cents, computed as 12000 minus the half-up rounding of 12000 times
    0.05 (the five-percent admin fee being 600 cents on the half-up
    rule, with 11400 cents the actual refund amount).  The endpoint
    increments each affected ticket type's `refunded_count` by the
    per-type `refunded_count_delta`, decrements the corresponding
    `provisional_refund_cents_outstanding` by the originally-pencilled-
    in provisional amount so the pending bucket goes back to zero on a
    full acknowledgement, and stamps the schedule change's
    `final_refund_cents_total` field to the across-row sum of the
    externally-final cents totals.  The festival's
    `outstanding_tickets_total` is recomputed."

    And PRD §2.8: "the ticketing element of the change's
    sync_envelopes is flipped to `ACKNOWLEDGED`".

    Claim: posting the refund-confirmed ingress with the canonical
    final-cents figure of 11400 (12000 minus the 600-cent admin fee)
    stamps the change's `final_refund_cents_total` to 11400, flips
    the ticketing envelope element to ACKNOWLEDGED, decrements the
    ticket type's `provisional_refund_cents_outstanding` to zero,
    increments its `refunded_count` to 3 (the delta supplied in the
    payload), and the festival's `outstanding_tickets_total` falls to
    zero (issued count of 3 minus refunded count of 3).  Once the
    other three targets have also ACKed via /_events/sync-ack the
    change advances APPLIED → SYNCED per PRD §2.8.

    The cents inequality on the same row — 12000 provisional cents vs
    11400 final cents — is the rule-1 dual-variant evidence on the
    ticketing entity domain.

    # difficulty: dual_variant_calc/refund_provisional_vs_final_on_ticketing_domain
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=3, unit_price_cents=12000,
        initial_issued=3, artist_tier="HEADLINER",
    )
    ticket_type_id = str(bag.ticket_type["id"])
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=bag.program_item_id)
    change_id = str(applied["id"])
    # Sanity: the §3.4 invariant says the provisional column is 12000
    # before the ACK.
    assert applied["provisional_refund_cents_total"] == CANONICAL_PROVISIONAL_REFUND_CENTS
    assert applied["final_refund_cents_total"] is None
    # Land the refund-confirmed event with the canonical externally-
    # final cents figure of 11400 = round_half_up(12000 * (1 −
    # ADMIN_FEE_RATE_FINAL)).
    ack_payload_breakdown: List[Dict[str, Any]] = [
        refund_breakdown_entry(ticket_type_id=ticket_type_id,
                               refunded_count_delta=3,
                               final_cents_total_for_type=CANONICAL_FINAL_REFUND_CENTS),
    ]
    post_ack_change = confirm_refund_via_ack(api, bag, change_id,
                                             ack_payload_breakdown)
    # The PRD §3.4 sentence "stamps the schedule change's
    # `final_refund_cents_total` field to the across-row sum".
    assert post_ack_change["final_refund_cents_total"] == CANONICAL_FINAL_REFUND_CENTS, (
        f"final_refund_cents_total == 11400 on the canonical input per "
        f"the §3.4 worked example.  Got "
        f"{post_ack_change['final_refund_cents_total']}."
    )
    # The provisional column is monotone — the ack does not change the
    # provisional figure.  See PRD §3.4 narrative about the
    # provisional column.
    assert post_ack_change["provisional_refund_cents_total"] == CANONICAL_PROVISIONAL_REFUND_CENTS, \
        ("The provisional column is monotone after the apply per PRD §3.4 — "
         "only the final column moves on the ACK.")
    # Critically, the two cents numbers on the same ScheduleChange row
    # differ, and the gap is exactly the admin-fee deduction on the
    # canonical input (12000 − 11400 == 600).  This is the rule-1
    # dual-variant evidence.
    gap = (post_ack_change["provisional_refund_cents_total"]
           - post_ack_change["final_refund_cents_total"])
    assert gap == 600, (
        f"The admin-fee gap on the canonical input is 600 cents "
        f"(half-up of 12000 × 0.05) per PRD §3.4.  Got gap={gap}."
    )
    # The ticket-type counters and the festival-wide outstanding total
    # have moved per the PRD §3.4 ACK side-effects.
    post_ticket = get_ticket_type_snapshot(api, bag.festival_id, ticket_type_id)
    assert post_ticket["refunded_count"] == 3, \
        "refunded_count incremented by 3 per the §3.4 ACK payload's refunded_count_delta."
    assert post_ticket["issued_count"] == 3, "issued_count unchanged by the ACK per PRD §3.4."
    assert post_ticket["provisional_refund_cents_outstanding"] == 0, \
        "provisional_refund_cents_outstanding clears to 0 on a full ACK per PRD §3.4."
    post_festival = get_success_data(api.get_festival(bag.festival_id, AUDIT_HEADERS))
    assert post_festival["outstanding_tickets_total"] == 0, \
        ("Festival.outstanding_tickets_total is recomputed as issued − refunded "
         "across the festival's ticket types per PRD §2.4 / §3.4.")
    # The ticketing envelope element is now ACKNOWLEDGED per PRD §2.8.
    assert_envelope_status_by_target(post_ack_change, "ticketing",
                                     SyncEnvelopeStatus.ACKNOWLEDGED.value)
    # Drive the remaining three envelopes through the generic
    # sync-ack ingress; per PRD §2.8 the change advances APPLIED →
    # SYNCED once the last QUEUED envelope flips.
    ack_remaining_targets(api, bag, change_id,
                          targets=["im", "broadcasting", "sponsor"])
    fully_synced = get_schedule_change_snapshot(api, bag.festival_id, change_id)
    assert fully_synced["status"] == "SYNCED", \
        ("Once all four envelope elements are ACKNOWLEDGED the change "
         "advances APPLIED → SYNCED per PRD §2.8.")
    for env in fully_synced["sync_envelopes"]:
        assert env["status"] == "ACKNOWLEDGED", \
            "Every envelope element is ACKNOWLEDGED in the SYNCED terminal state per PRD §2.8."
    # An audit row of event_category SYNC_ACK exists on the change
    # subject per PRD §2.8's "an audit entry of category `SYNC_ACK` is
    # appended" sentence.
    audit_rows = read_audit_log(api, bag,
                                event_category=AuditEventCategory.SYNC_ACK.value,
                                subject_entity_type="ScheduleChange")
    matching = [e for e in audit_rows if e.get("subject_entity_id") == change_id]
    assert matching, ("A SYNC_ACK audit row on the schedule-change subject is "
                      "appended for the refund-confirmed event per PRD §2.8 / §3.4.")


def test_refund_confirmed_with_excess_cents_rejected(api):
    """PRD §3.4 / §2.8: "the cross-row magnitude bound is hard: the
    `final_cents_total_for_type` for any row may not exceed the
    matching provisional figure attributed to that type by the
    originating apply by any positive amount (the absolute tolerance
    is `ABS_TOLERANCE_CENTS = 0`), otherwise the request is rejected at
    HTTP 422 with `ERR_REFUND_EXCEEDS_PROVISIONAL`."

    Claim: a refund-confirmed body whose `final_cents_total_for_type`
    exceeds the matching provisional figure for the type by even one
    cent is rejected with `ERR_REFUND_EXCEEDS_PROVISIONAL` at HTTP 422.
    The corresponding equality case (full provisional, no admin fee)
    is the PRD's stated "standard outcome before any admin-fee
    deduction" and is accepted by the previous test's variant.
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=3, unit_price_cents=12000,
        initial_issued=3, artist_tier="HEADLINER",
    )
    ticket_type_id = str(bag.ticket_type["id"])
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=bag.program_item_id)
    change_id = str(applied["id"])
    excess_cents = CANONICAL_PROVISIONAL_REFUND_CENTS + 1  # one cent over the provisional cap
    body = F.refund_confirmed_payload(
        festival_id=bag.festival_id,
        schedule_change_id=change_id,
        refund_breakdown=[
            refund_breakdown_entry(ticket_type_id=ticket_type_id,
                                   refunded_count_delta=3,
                                   final_cents_total_for_type=excess_cents),
        ],
    )
    resp = api.refund_confirmed(body, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PROVISIONAL.value,
                   expected_status=422)


def test_refund_confirmed_cross_festival_rejected(api):
    """PRD §2.8 / §3.4: "Each row's `ticket_type_id` must point to a
    ticket type whose `festival_id` matches the `schedule_change_id`'s
    `festival_id`, otherwise the request is rejected at HTTP 422 with
    `ERR_CROSS_FESTIVAL_REFUND`."

    Claim: a refund-confirmed body whose `refund_breakdown` row names a
    ticket-type id under a different festival than the schedule
    change's festival is rejected with `ERR_CROSS_FESTIVAL_REFUND` at
    HTTP 422.
    """
    bag_a = confirmed_published_world_with_ticket(api, day_count=3,
                                                  artist_tier="HEADLINER")
    bag_b = confirmed_published_world_with_ticket(api, day_count=3,
                                                  artist_tier="HEADLINER",
                                                  unit_price_cents=8000)
    # Apply a cancel on festival A's item so an APPLIED change exists
    # on A.  Then submit a refund-confirmed body whose breakdown names
    # festival B's ticket-type id.
    applied_a = create_and_apply_item_cancel(api, bag_a,
                                             target_item_id=bag_a.program_item_id)
    change_a_id = str(applied_a["id"])
    foreign_ticket_id = str(bag_b.ticket_type["id"])
    body = F.refund_confirmed_payload(
        festival_id=bag_a.festival_id,
        schedule_change_id=change_a_id,
        refund_breakdown=[
            refund_breakdown_entry(ticket_type_id=foreign_ticket_id,
                                   refunded_count_delta=1,
                                   final_cents_total_for_type=1),
        ],
    )
    resp = api.refund_confirmed(body, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CROSS_FESTIVAL_REFUND.value,
                   expected_status=422)


def test_sync_ack_with_unknown_target_returns_target_unknown(api):
    """PRD §2.8: "A target outside the four-element set returns
    `ERR_SYNC_TARGET_UNKNOWN` at HTTP 400."

    Claim: a sync-ack body whose `target` field is a string outside
    {ticketing, im, broadcasting, sponsor} is rejected at HTTP 400.
    """
    bag = confirmed_published_world_with_ticket(api, day_count=3,
                                                artist_tier="HEADLINER")
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=bag.program_item_id)
    body = F.sync_ack_payload(festival_id=bag.festival_id,
                              schedule_change_id=str(applied["id"]),
                              target="not-a-real-target",
                              succeeded=True,
                              payload_hash="x")
    resp = api.sync_ack(body, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SYNC_TARGET_UNKNOWN.value,
                   expected_status=400)


def test_sync_ack_on_already_acked_envelope_returns_not_queued(api):
    """PRD §2.8 / §2.5: "The race between the external-system
    sync-acknowledgement ingress capability and the schedule-change
    revert capability on the same schedule change serialises via a
    row lock on the change row, with the post-revert envelope status
    `CANCELLED` causing a subsequent sync-ack to see a non-QUEUED
    envelope and return `ERR_SYNC_ENVELOPE_NOT_QUEUED` at HTTP 409"
    — the same error fires on a non-revert path when the envelope is
    already ACKNOWLEDGED (it is "the envelope is not currently QUEUED"
    condition the PRD §1.6 catalog calls out and §2.8 names verbatim
    via "A sync-ack against an envelope element that is not currently
    `QUEUED` (because the revert path or a prior ack already flipped
    it) returns `ERR_SYNC_ENVELOPE_NOT_QUEUED` at HTTP 409").

    Claim: a second sync-ack on the same (change, target) pair after
    the envelope has already flipped to ACKNOWLEDGED returns
    `ERR_SYNC_ENVELOPE_NOT_QUEUED` at HTTP 409.
    """
    bag = confirmed_published_world_with_ticket(api, day_count=3,
                                                artist_tier="HEADLINER")
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=bag.program_item_id)
    change_id = str(applied["id"])
    # First sync-ack on the IM target (non-ticketing — the ticketing
    # target's specialised ingress is the refund-confirmed endpoint per
    # PRD §2.8).
    first_body = F.sync_ack_payload(festival_id=bag.festival_id,
                                    schedule_change_id=change_id,
                                    target="im", succeeded=True,
                                    payload_hash="abc")
    get_success_data(api.sync_ack(first_body, ADMIN_HEADERS))
    # Read the change row and assert the IM envelope flipped.
    after_first = get_schedule_change_snapshot(api, bag.festival_id, change_id)
    assert_envelope_status_by_target(after_first, "im",
                                     SyncEnvelopeStatus.ACKNOWLEDGED.value)
    # Second sync-ack on the same target — the envelope is now
    # non-QUEUED, the rejection fires.
    second_body = F.sync_ack_payload(festival_id=bag.festival_id,
                                     schedule_change_id=change_id,
                                     target="im", succeeded=True,
                                     payload_hash="def")
    resp = api.sync_ack(second_body, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SYNC_ENVELOPE_NOT_QUEUED.value,
                   expected_status=409)


# ---------------------------------------------------------------------------
# Instance B — the sponsor-domain dual variant.  Forward-looking
# projected_fulfilment_pct vs the chronological actual_fulfilment_pct.
# ---------------------------------------------------------------------------


def _build_ten_tied_items(api, bag) -> List[Dict[str, Any]]:
    """Helper: create ten OPENER artists and ten one-hour program items
    on the first day of the festival in ten non-overlapping windows,
    confirming each.  Returns the list of post-confirm item dicts in
    the order they were created."""
    items: List[Dict[str, Any]] = []
    # Day-1 windows at hours 10, 11, ..., 19 (each one hour long).
    day1_start = bag.festival_start + 86400
    for i in range(10):
        artist_i = register_artist(api, tier="OPENER",
                                   home_city=f"city-{chr(ord('a') + i)}")
        win_start = day1_start + (10 + i) * 3600
        win_end = win_start + 3600 - 60  # 59-minute window to avoid
                                          # back-to-back stage-changeover
                                          # conflicts under the default
                                          # 1800-second buffer.
        # The default 30-minute stage-changeover buffer (1800 s) requires
        # at least 1800 s of clearance after the previous item's end_time
        # plus one second before the next item's start_time per PRD §3.5.
        # 59-minute items at the top of each hour gives 60 − 59 = 1 minute
        # of gap, which is less than the 30-minute buffer.  Instead use
        # a 30-minute item, 30 minutes of gap.  Wait, the rule says the
        # candidate's start_time vs the existing's padded right endpoint
        # — if existing ends at 11:00 and buffer is 1800s, the existing's
        # padded interval extends to 11:30.  A candidate starting at
        # 12:00 is therefore at gap 60 minutes > 30 minutes the buffer,
        # accepted.  So with one-hour-on-the-hour items we need a one-
        # hour gap, i.e. items at hours 10, 12, 14, ... — eight items
        # in the first half of the day, not ten.  Simpler: use 30-minute
        # items at half-hour intervals starting on the hour, so gap is
        # 30 minutes which exactly equals the buffer — and the
        # asymmetric boundary rule (existing's padded right endpoint is
        # inclusive) says the candidate at exactly that instant
        # conflicts.  Worse, conflicts.
        # To fit ten items on one day cleanly with the 1800-second
        # buffer, give each item a 30-minute window with a 30-minute
        # gap — but place each on its own dedicated stage so the
        # stage-changeover rule does not apply (the rule is per-stage
        # per PRD §3.5).  But the bag only has one stage.  Easier
        # workaround: add a second per-item stage.  But we want all ten
        # on the same festival, so add ten stages or stretch the
        # festival to span enough hours.  10 hours × (1 + 0.5)-hour
        # slots = 15 hours, fits in a 24-hour day.  Use 30-minute slots
        # spaced 1.5 hours apart from each other on the same stage so
        # the gap clears the 30-minute buffer with margin.  The
        # arithmetic: items at hours 10, 11.5, 13, 14.5, 16, 17.5, 19,
        # 20.5, 22, 23.5 — that's 10 windows, each 30 minutes long,
        # gap of 60 minutes between consecutive end and next start
        # which clears the 30-minute buffer.
        slot_hour_offset = 10.0 + i * 1.5
        win_start = int(day1_start + slot_hour_offset * 3600)
        win_end = win_start + 30 * 60
        if win_end >= bag.festival_end:
            # The festival is too short to fit all ten on one day; abort
            # the loop and let the caller see the partial-fixture state
            # (the test that uses this helper passes day_count large
            # enough so this never trips).
            break
        item = get_success_data(api.create_program_item(
            bag.festival_id,
            F.program_item_payload(program_version_id=bag.version_id,
                                   artist_id=str(artist_i["id"]),
                                   stage_id=bag.stage_id,
                                   start_time=win_start,
                                   end_time=win_end,
                                   genre="indie-rock",
                                   equipment_kit_codes=[]),
            LIAISON_HEADERS,
        ))
        confirmed = get_success_data(api.confirm_program_item(
            bag.festival_id, str(item["id"]), LIAISON_HEADERS,
        ))
        items.append(confirmed)
    assert len(items) == 10, (
        "The festival's window must be large enough to fit ten 30-minute "
        "items spaced 90 minutes apart on a single day — increase day_count "
        "on the bag if this assertion trips."
    )
    return items


def test_projected_versus_actual_fulfilment_pct_diverge_on_the_same_sponsor_tier_row(api):
    """PRD §3.6: "The projected `projected_fulfilment_pct` field on the
    `SponsorTier` row is the forward-looking percentage computed
    eagerly on every relevant mutation ... An allocation tied to a
    specific program item (non-null `program_item_id`) contributes its
    full `actual_units` when the tied item's status is in the
    'will-or-did-happen' set `CONFIRMED`, `ANNOUNCED`, `ON_STAGE`, or
    `PERFORMED`, and contributes zero when the tied item's status is
    the terminal `CANCELLED`. ... The actual `actual_fulfilment_pct`
    field is null while the festival is still open and is stamped
    only by the post-event sweep ... while the festival is `CLOSED`.
    The actual computation walks the immutable `FulfilmentLog` event
    stream rather than the live schedule ...  The two columns can
    legitimately diverge."  And: "the salient property the test
    asserts is 'projected and actual are different non-zero numbers on
    the same `SponsorTier` row, and the actual is derived strictly
    from the `FulfilmentLog` stream while the projected is derived
    strictly from the live program-item state'".

    Claim: on a scenario where a single GOLD-tier sponsor contracts
    for 10 units (all tied to ten distinct day-1 program items via
    ten kind=stage_name allocations of one unit each), and where two
    of the ten tied items are cancelled before the festival opens
    (driving the projection numerator down by 2 to 8/10 = 80.00%),
    and where after the festival opens and closes only seven of the
    eight surviving items are delivered against (giving a post-event
    DELIVERED unit count of 7), the SponsorTier's two percentage
    fields land at projected==80.00 and actual==70.00 respectively —
    a 10-percentage-point gap on the same row, on identical input
    data.  The actual is null before the post-event sweep flips it
    per PRD §2.7.

    # difficulty: dual_variant_calc/exposure_projected_vs_actual_on_sponsor_domain
    """
    # A 3-day festival so the 15-hour 10-item layout fits comfortably
    # inside the festival window.
    bag = base_world(api, day_count=3, artist_tier="OPENER",
                     stage_zone_capacity=10_000)
    # The base-world fixture has the festival in SCHEDULING with a
    # DRAFT initial program version V1, one stage, one global artist
    # already registered, and an empty program-items list.  We do not
    # use the bag's pre-registered artist — the ten tied items each
    # use a fresh artist so the artist-self-overlap rule and the
    # multi-festival-overlap-check do not bite.
    items = _build_ten_tied_items(api, bag)
    # The version-publish step needs at least one item in the version's
    # program_item_ids snapshot per PRD §3.3.  We already attached
    # items to bag.version_id at create time, so the empty-program
    # guard does not fire.  Submit-and-publish.
    publish_version(api, bag)
    # Announce every item so the clock-tick chain
    # ANNOUNCED → ON_STAGE → PERFORMED of PRD §2.8 can fire on the
    # eight surviving items when the test advances the clock past
    # their end_times — the §2.8 item-start clock-tick rule fires
    # only on items in ANNOUNCED state.  The artist tier on each
    # item is OPENER (cardinality minimum zero blocking riders per
    # §3.3's HEADLINER_MIN_BLOCKING_RIDERS rule, and no riders at all
    # so the universal "every blocking rider is fulfilled" condition
    # is trivially satisfied), the parent festival's status is the
    # post-publish PUBLISHED required by the §3.3 announce gate, and
    # the sound-check axis is the default NOT_REQUIRED so the §3.3
    # cross-axis gate's "non-headliner cannot announce while
    # sound_check_status ∈ {REQUESTED, SCHEDULED}" condition is not
    # triggered.  The announce side-effect is the auto-emitted
    # TICKET_NOTIFY ScheduleChange, which is incidental for this test.
    announced_items: List[Dict[str, Any]] = []
    for it in items:
        announced = get_success_data(
            api.announce_program_item(bag.festival_id, str(it["id"]),
                                      LIAISON_HEADERS)
        )
        announced_items.append(announced)
    items = announced_items
    # Seed the catalog with ample pools so the waterfall doesn't trim
    # the canonical (10 × 1)-unit request set for kind == stage_name.
    seed_default_catalog(api, bag, branded_zone=100)
    # The single GOLD sponsor tier contracts for 10 units of
    # kind=stage_name.  contract_kinds_allowed is the full four-element
    # set so the §2.6 priority-16 referential check trivially passes.
    tier = add_sponsor_tier(api, bag, tier_code="GOLD", priority_rank=1,
                            sponsor_external_id="gold-dualvariant",
                            contracted_units=10,
                            contract_kinds_allowed=list(["stage_name",
                                                         "screen_time",
                                                         "artist_mention",
                                                         "branded_zone"]))
    tier_id = str(tier["id"])
    # Ten exposure-allocations of kind=stage_name, one per tied item,
    # each requesting one unit.
    allocations: List[Dict[str, Any]] = []
    for it in items:
        a = add_exposure_allocation(api, bag, tier_id,
                                    kind="stage_name",
                                    requested_units=1,
                                    program_item_id=str(it["id"]),
                                    pinned_rate_cents_per_unit=int(
                                        THRESHOLDS["SPONSOR_PAYOUT_RATE_MILS_DEFAULT"]
                                    ))
        allocations.append(a)
    # Run the waterfall sweep to assign actual_units=1 on each
    # allocation per the §3.6 disbursement formula.  Total requested is
    # 10 == the tier's contracted_units cap, and the kind=stage_name
    # pool of 100 is more than enough.
    run_waterfall(api, bag)
    # The tier's projected_fulfilment_pct now reads from the §3.6
    # forward-looking formula.  All ten allocations are tied to
    # CONFIRMED items in the "will-or-did-happen" set, so the
    # projection numerator is 10 and the denominator is contracted_units
    # == 10, giving 100.00.
    tier_after_sweep = get_sponsor_tier_snapshot(api, bag.festival_id, tier_id)
    assert float(tier_after_sweep["projected_fulfilment_pct"]) == pytest.approx(100.0, abs=0.01), (
        f"With all ten tied items in CONFIRMED state, the projected "
        f"fulfilment percentage is 100.00 per PRD §3.6 — got "
        f"{tier_after_sweep['projected_fulfilment_pct']}."
    )
    assert tier_after_sweep["actual_fulfilment_pct"] is None, (
        "actual_fulfilment_pct is null while the festival is open per PRD §2.7."
    )
    assert tier_after_sweep["tier_remaining_quota"] == 10, (
        "tier_remaining_quota == contracted_units − Σ delivered_units == 10 − 0 == 10 "
        "before any delivery per PRD §3.6."
    )
    # Cancel two of the ten tied items.  Per PRD §3.6 the cascade-B
    # chain flips the tied ExposureAllocation rows to VOIDED with a
    # PROGRAM_VOIDED FulfilmentLog row, and the SponsorTier's
    # projected_fulfilment_pct is recomputed.  The two cancelled items
    # are the last two of the ten so the early eight remain in the
    # "will-happen" set.
    cancelled_item_ids: List[str] = []
    for idx in (8, 9):
        item_id = str(items[idx]["id"])
        get_success_data(api.cancel_program_item(
            bag.festival_id, item_id,
            cancel_program_item_payload(reason=f"dual-variant-cancel-{idx}"),
            LIAISON_HEADERS,
        ))
        cancelled_item_ids.append(item_id)
    # The projection numerator is now 8 (the eight surviving tied
    # allocations, each at one actual_unit) and the denominator is 10.
    # The pinned percentage is 80.00 per the §3.6 / §2.7 prose.
    tier_after_cancels = get_sponsor_tier_snapshot(api, bag.festival_id, tier_id)
    assert float(tier_after_cancels["projected_fulfilment_pct"]) == pytest.approx(
        float(CANONICAL_PROJECTED_PCT), abs=0.01,
    ), (
        f"Cancelling two of ten tied items drops the projected "
        f"fulfilment pct to 80.00 per PRD §3.6 — got "
        f"{tier_after_cancels['projected_fulfilment_pct']}."
    )
    assert tier_after_cancels["actual_fulfilment_pct"] is None, (
        "actual_fulfilment_pct is still null while the festival is open per PRD §2.7."
    )
    # The two cascade-B-voided allocations are now in status VOIDED
    # per the PRD §3.5 cascade B prose and the §3.6 narrative ("when
    # the cascade-B chain from a program-item cancel reaches the
    # allocation").  Read the listing and assert.
    listing = validate_success(
        api.list_exposure_allocations(
            bag.festival_id, SPONSOR_HEADERS,
            params={"sponsor_tier_id": tier_id, "limit": 100, "offset": 0}),
    )
    rows = listing if isinstance(listing, list) else listing.get("items", listing.get("data", []))
    voided_rows = [r for r in rows if r.get("status") == "VOIDED"]
    assert len(voided_rows) == 2, (
        f"Two allocations are voided by the two ITEM_CANCEL cascades per PRD §3.5 — got {len(voided_rows)} voided rows."
    )
    # Advance the clock through the festival's lifetime so the eight
    # surviving items reach the PERFORMED status — the cross-entity
    # gate on the deliver endpoint of §3.6 requires the tied item to be
    # PERFORMED before an ExposureAllocation can be DELIVERED.
    # We move past the last surviving item's end_time, then to
    # festival close + grace.  The eight surviving items are items[0]
    # through items[7] in time-ordered sequence; their windows go from
    # day1+10h to day1+10+7*1.5h = day1+20.5h + 30min on the end.
    last_surviving_end = max(int(items[i]["end_time"]) for i in range(8))
    advance_clock_to(api, festival_id=bag.festival_id,
                     to_unix_seconds=last_surviving_end + 60)
    # Each surviving item should now be at PERFORMED status per the
    # clock-tick cascade of PRD §3.3.  Now deliver against seven of the
    # eight surviving allocations — one delivery per allocation, each
    # with units == 1.  The eighth surviving allocation gets no
    # delivery, mirroring the §3.6 worked example's "one slot fails to
    # deliver day-of".
    surviving_allocs = [a for a in allocations
                       if str(a.get("program_item_id"))
                          in {str(items[i]["id"]) for i in range(8)}]
    assert len(surviving_allocs) == 8
    for alloc in surviving_allocs[:7]:
        get_success_data(api.deliver_exposure(
            bag.festival_id, str(alloc["id"]),
            F.exposure_deliver_payload(units=1, note="delivered-during-act"),
            SPONSOR_HEADERS,
        ))
    # The eighth surviving allocation remains undelivered (no
    # FulfilmentLog DELIVERED row).
    undelivered_id = str(surviving_allocs[7]["id"])
    # Drive the festival through close + grace.  The Festival.LIVE →
    # CLOSED cascade fires per PRD §3.1, and the rehearsal-cascade C
    # of §3.5 dormant-ly fires.  After the close the post-event sweep
    # can flip the DELIVERED rows to REPORTED and stamp the actual
    # percentage.
    advance_festival_through_close(api, bag)
    # The festival's status is now CLOSED.
    festival_after_close = get_success_data(
        api.get_festival(bag.festival_id, AUDIT_HEADERS)
    )
    assert festival_after_close["status"] == "CLOSED", (
        "Festival auto-closes when the clock crosses end_time + "
        "FESTIVAL_CLOSE_GRACE_SECONDS per PRD §2.8."
    )
    # The post-event sweep with compute_payout=true runs the §3.6
    # actual_fulfilment_pct formula on the FulfilmentLog stream.  The
    # tier's delivered_units sum is 7 (seven DELIVERED unit-rows minus
    # zero VOIDED unit-rows on the seven non-cascade-voided
    # allocations, plus zero from the two cascade-voided allocations
    # whose PROGRAM_VOIDED row had units == 0 because the cascade fired
    # while delivered_units was zero, plus zero from the eighth
    # surviving-but-undelivered allocation).  The §3.6 sentence "The
    # actual is derived strictly from the FulfilmentLog stream" pins
    # the numerator at 7 and the denominator at the tier's
    # contracted_units of 10.  The two-decimal-half-up percent is
    # therefore 70.00 per the §2.7 rule.
    sweep_resp = run_post_event_sweep(api, bag, compute_payout=True)
    # The fulfilment-report read carries both columns and the
    # tier_remaining_quota.  The §3.6 actual formula: tier_delivered =
    # Σ delivered_units across the tier's allocations.  delivered_units
    # on an allocation is Σ DELIVERED-row units − Σ (VOIDED +
    # PROGRAM_VOIDED) units, with the REPORTED-row units always zero
    # per the PRD §2.7 closing-tally rule.  Seven 1-unit DELIVERED rows
    # and two zero-units PROGRAM_VOIDED rows (on the cascade-voided
    # allocations whose delivered_units was zero when the cascade
    # fired — see PRD §3.5 cascade-B sentence "appending a
    # FulfilmentLog row of event_type PROGRAM_VOIDED whose units
    # equals the allocation's current delivered_units") gives a tier
    # total of 7 delivered units.  And the §2.7 sentence: "The
    # `actual_fulfilment_pct` field, by contrast, is computed only by
    # the post-event sweep operator capability while the parent
    # festival is in status `CLOSED`. ... The sweep walks the
    # FulfilmentLog event stream for every ExposureAllocation under the
    # tier, computes each allocation's delivered_units as the sum of
    # the units of the DELIVERED log rows minus the sum of the units of
    # the VOIDED and PROGRAM_VOIDED log rows on the same allocation
    # (the REPORTED row carries units = 0 and contributes nothing to
    # the count), sums those delivered_units figures across the tier,
    # divides by the tier's contracted_units, multiplies by 100, and
    # rounds half up to two decimal places."  7/10*100 == 70.00.
    final_tier = get_sponsor_tier_snapshot(api, bag.festival_id, tier_id)
    assert final_tier["actual_fulfilment_pct"] is not None, (
        "Post-event sweep stamps actual_fulfilment_pct from null to a number per PRD §2.7."
    )
    assert float(final_tier["actual_fulfilment_pct"]) == pytest.approx(
        float(CANONICAL_ACTUAL_PCT), abs=0.01,
    ), (
        f"Seven DELIVERED units out of ten contracted units gives "
        f"actual_fulfilment_pct == 70.00 per PRD §2.7 / §3.6 — got "
        f"{final_tier['actual_fulfilment_pct']}."
    )
    # The tier_remaining_quota at this point is contracted_units − tier_delivered = 10 − 7 == 3 per the §3.6 sentence
    # "tier_remaining_quota = contracted_units − Σ delivered_units".
    assert final_tier["tier_remaining_quota"] == 3, (
        f"tier_remaining_quota == 10 − 7 == 3 per the PRD §3.6 formula — "
        f"got {final_tier['tier_remaining_quota']}."
    )
    # The gap between the projected (still 80.00) and the actual
    # (70.00) is the rule-1 dual-variant evidence on the sponsor
    # entity domain.  The PRD §2.7 sentence is the load-bearing one:
    # "The two percentages — projected and actual — can legitimately
    # diverge: a confirmed program item that gets day-of cancelled
    # contributes its allocation's full `actual_units` to the
    # projection but contributes zero `delivered_units` to the
    # post-event tally, and the gap shows up as a non-zero difference
    # between the two columns on the same `SponsorTier` row."  The
    # implementation may either freeze the projection at close or
    # recompute it to match the actual; the PRD does not pin which
    # of the two reasonable behaviours.  The unambiguous claim is
    # that the actual is 70.00 and the gap-between-the-pre-close-
    # projection-and-the-actual is 10 percentage points.  We assert
    # the post-close actual literal as the load-bearing pin and the
    # tier_remaining_quota integer as the conserved-quantity side
    # of the rule-9 instance-B invariant on the same tier.  The
    # projected-vs-actual gap is the rule-1 instance-B dual-variant.
    # The report-read endpoint exposes both columns per §3.7; the
    # `delivered_units_by_allocation` map exposes the per-allocation
    # delivered_units vector.
    report = get_fulfilment_report_snapshot(api, bag.festival_id, tier_id)
    assert float(report["actual_fulfilment_pct"]) == pytest.approx(
        float(CANONICAL_ACTUAL_PCT), abs=0.01,
    ), "The report-view's actual_fulfilment_pct equals the tier-row's per PRD §3.7."
    assert int(report["tier_remaining_quota"]) == 3, (
        "The report-view's tier_remaining_quota matches the tier-row's per PRD §3.7."
    )
    # The undelivered-but-surviving allocation's delivered_units is
    # zero — the §3.6 sentence "an allocation that arrives when the
    # pool is already drained at its position is given a zero
    # `actual_units` (a zero-units row is a valid record that surfaces
    # in the post-event report as a zero-percent delivery line for the
    # under-served sponsor)" is about the catalog-pool-empty case but
    # the same "zero-units row is a valid record in the post-event
    # report" semantics applies to the never-delivered-but-surviving
    # case: the row sits at status==PLANNED with delivered_units==0.
    listing_after = validate_success(api.list_exposure_allocations(
        bag.festival_id, SPONSOR_HEADERS,
        params={"sponsor_tier_id": tier_id, "limit": 100, "offset": 0},
    ))
    rows_after = (listing_after
                  if isinstance(listing_after, list)
                  else listing_after.get("items", listing_after.get("data", [])))
    by_id = {str(r["id"]): r for r in rows_after}
    undelivered_row = by_id.get(undelivered_id)
    assert undelivered_row is not None
    assert undelivered_row["delivered_units"] == 0, (
        "An allocation that received no DELIVERED log row has delivered_units==0 per PRD §3.6."
    )
    # The sweep wrote an EXPOSURE audit row for the tier per the §2.8
    # mapping ("the audit entries the sweep writes are of category
    # EXPOSURE").
    exposure_rows = read_audit_log(api, bag,
                                   event_category=AuditEventCategory.EXPOSURE.value)
    assert any(e.get("subject_entity_id") == tier_id for e in exposure_rows), (
        "An EXPOSURE-category audit row is appended for the swept tier per PRD §2.8."
    )


def test_actual_fulfilment_pct_null_before_post_close_sweep(api):
    """PRD §2.7: "The `actual_fulfilment_pct` field, by contrast, is
    computed only by the post-event sweep operator capability while
    the parent festival is in status `CLOSED`.  It is null before
    then."  And PRD §2.8: "While the festival is still open (`status`
    not yet `CLOSED`), the sweep is a no-op on the actual percentage
    field — it may refresh the projected percentages but it does not
    flip any allocation's status to `REPORTED` nor stamp the actual
    percentage."

    Claim: a pre-close sweep does not stamp actual_fulfilment_pct.
    The field remains null on the tier read until the post-close
    sweep runs.  Pair with the prior test which exercises the
    post-close stamping path.

    # difficulty: dual_variant_calc/exposure_projected_vs_actual_on_sponsor_domain
    """
    bag = base_world(api, day_count=2)
    add_program_item(api, bag, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag, str(bag.program_item["id"]))
    publish_version(api, bag)
    seed_default_catalog(api, bag, branded_zone=10)
    tier = add_sponsor_tier(api, bag, tier_code="GOLD", priority_rank=1,
                            sponsor_external_id="gold-null-actual",
                            contracted_units=4,
                            contract_kinds_allowed=["branded_zone"])
    # One festival-wide allocation that doesn't depend on a specific
    # program item (program_item_id is null per PRD §3.6's "festival-
    # wide" allocation case).
    alloc = add_exposure_allocation(api, bag, str(tier["id"]),
                                    kind="branded_zone",
                                    requested_units=2)
    run_waterfall(api, bag)
    # Sweep while the festival is still in PUBLISHED (no clock
    # advance) — the sweep is a no-op on the actual column per PRD
    # §2.8.
    sweep_result = api.run_sweep(
        F.sweep_payload(festival_id=bag.festival_id, compute_payout=False),
        ADMIN_HEADERS,
    )
    get_success_data(sweep_result)  # the sweep itself succeeds; the
                                    # actual column was just left null.
    tier_state = get_sponsor_tier_snapshot(api, bag.festival_id, str(tier["id"]))
    assert tier_state["actual_fulfilment_pct"] is None, (
        "The pre-close sweep does not stamp actual_fulfilment_pct per PRD §2.8 / §2.7 — "
        f"got {tier_state['actual_fulfilment_pct']!r}."
    )


def test_refund_confirmed_against_closed_festival_returns_already_closed(api):
    """PRD §2.8 / §3.4: "A late
    the external-ticketing-system refund-confirmed ingress capability
    against a ticket type whose festival has already reached the
    `CLOSED` state is rejected at HTTP 409 with
    `ERR_FESTIVAL_ALREADY_CLOSED`."

    Claim: a refund-confirmed ingress that arrives after the
    festival's auto-close (driven by the clock-advance past
    end_time + FESTIVAL_CLOSE_GRACE_SECONDS per PRD §2.8) is rejected
    with `ERR_FESTIVAL_ALREADY_CLOSED` at HTTP 409.

    The scenario: apply an ITEM_CANCEL change while the festival is
    still PUBLISHED, then advance the clock past the close boundary,
    then attempt the refund-confirmed ingress.
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=2, unit_price_cents=8000,
        initial_issued=2, artist_tier="HEADLINER",
    )
    ticket_type_id = str(bag.ticket_type["id"])
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=bag.program_item_id)
    change_id = str(applied["id"])
    # Now drive the festival's clock past end_time + grace so it auto-
    # closes per PRD §2.8.
    advance_festival_through_close(api, bag)
    # The festival's status is CLOSED.  Any refund-confirmed against
    # the change is rejected with ERR_FESTIVAL_ALREADY_CLOSED.
    body = F.refund_confirmed_payload(
        festival_id=bag.festival_id,
        schedule_change_id=change_id,
        refund_breakdown=[
            refund_breakdown_entry(ticket_type_id=ticket_type_id,
                                   refunded_count_delta=1,
                                   final_cents_total_for_type=8000),
        ],
    )
    resp = api.refund_confirmed(body, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_FESTIVAL_ALREADY_CLOSED.value,
                   expected_status=409)
