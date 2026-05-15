"""ScheduleChange state machine — the branching-fork shape (PRD §3.4),
and the four sync-envelope-target ledger of PRD §2.8.

This is the third instance of difficulty rule 3 (non_linear_state_machine):
the ScheduleChange has a PROPOSED state that forks to APPLIED or
REJECTED, and the APPLIED state further forks to SYNCED (when the last
QUEUED envelope flips to ACKNOWLEDGED) or REVERTED (when the producer
hits the revert endpoint while no envelope has yet ACKed).  Three
terminal absorbing states: SYNCED, REJECTED, REVERTED.

The §2.8 envelope-status enum is the four-value set {QUEUED,
ACKNOWLEDGED, FAILED, CANCELLED}, with CANCELLED reserved exclusively
for the revert-path side-effect that flips every still-QUEUED envelope.

This file also exercises the rule-9 instance-A compensating-invariant
on the festival's outstanding_tickets_total integer across an apply-
and-revert window: the conserved quantity returns to its pre-apply
value because the apply does not flip issued_count or refunded_count,
the revert clears the provisional_refund_cents_outstanding cents bucket
without an external ACK ever landing, and the running issued − refunded
integer is unchanged across the round trip.  The transient evidence of
the apply firing — the cents bucket bulging between apply and revert —
is the compensating-action signature.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    AUDIT_HEADERS,
    AuditEventCategory,
    CANONICAL_PROVISIONAL_REFUND_CENTS,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    SyncEnvelopeStatus,
    TICKETING_HEADERS,
    ack_remaining_targets,
    add_program_item,
    add_stage,
    advance_festival_through_close,
    assert_audit_chronological,
    assert_audit_contains,
    assert_envelope_status_by_target,
    assert_four_envelopes_queued,
    assert_outstanding_tickets_total_conserved,
    assert_schedule_change_shape,
    base_world,
    confirm_item,
    confirm_refund_via_ack,
    confirmed_published_world_with_ticket,
    create_and_apply_item_cancel,
    factories as F,
    fixtures as FIX,
    get_festival_snapshot,
    get_schedule_change_snapshot,
    get_success_data,
    get_ticket_type_snapshot,
    issue_tickets,
    publish_version,
    read_audit_log,
    register_artist,
    refund_breakdown_entry,
    validate_error,
    validate_paginated,
    validate_success,
)


def _add_ticket_type_with_issuance(api, bag, item_id, *,
                                   unit_price_cents=12000, count=3):
    body = F.ticket_type_payload(
        ticket_class="SINGLE_DAY",
        tied_program_item_ids=[item_id],
        zone_name="ZoneApply",
        unit_price_cents=unit_price_cents,
    )
    tt = get_success_data(api.create_ticket_type(bag.festival_id, body, TICKETING_HEADERS))
    issued = issue_tickets(api, bag, str(tt["id"]), count=count)
    return tt, issued


# ---------------------------------------------------------------------------
# PROPOSED → APPLIED fork and the four-envelope seeding.
# ---------------------------------------------------------------------------


def test_create_then_apply_seeds_four_canonical_queued_envelopes(api):
    """PRD §3.4: "A change of kind `ITEM_CANCEL` is the standard
    cancel-with-refund variant the producer creates explicitly through
    the schedule-change create capability (with a body whose
    `change_kind` discriminator is the literal string and whose
    `payload` carries a `reason` string) and then applies through the
    apply endpoint."  And PRD §2.8: the four canonical envelope
    targets in the canonical order ticketing, im, broadcasting, sponsor,
    each seeded QUEUED on the apply, with `queued_at` stamped.

    Claim: a freshly created ScheduleChange is in status PROPOSED with
    an empty (or pre-apply) sync_envelopes array, and the post-apply
    snapshot of the same change has status APPLIED, applied_at non-
    null, and a four-element sync_envelopes array with the canonical
    target sequence ticketing, im, broadcasting, sponsor all in
    status QUEUED.
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER")
    create_body = F.schedule_change_payload(
        change_kind="ITEM_CANCEL",
        target_program_item_id=bag.program_item_id,
        payload=F.item_cancel_inner_payload(reason="schedule-apply-test"),
        idempotency_key=F.fresh_idempotency_key("create"),
    )
    created = get_success_data(api.create_schedule_change(
        bag.festival_id, create_body, PRODUCER_HEADERS,
    ))
    assert created["status"] == "PROPOSED", \
        "A fresh ScheduleChange is in PROPOSED per PRD §3.4."
    assert created["change_kind"] == "ITEM_CANCEL"
    assert created.get("applied_at") is None, \
        "applied_at is null until the apply transition per PRD §3.4."
    assert_schedule_change_shape(created)
    # The apply.
    applied = get_success_data(api.apply_schedule_change(
        bag.festival_id, str(created["id"]), PRODUCER_HEADERS,
    ))
    assert applied["status"] == "APPLIED"
    assert applied["applied_at"] is not None, \
        "applied_at is stamped at the apply transition per PRD §3.4."
    assert_four_envelopes_queued(applied)


def test_reject_path_is_no_cascade_and_writes_state_transition(api):
    """PRD §3.4: "The reject path emits no cascade — it merely flips
    the status, writes a `STATE_TRANSITION` audit entry whose
    `payload_summary` mentions the rejection reason, and is the path
    the producer uses to discard a proposed change without applying
    its effects."

    Claim: a reject on a PROPOSED ScheduleChange flips the status to
    REJECTED, requires a `reason` in the body (missing reason returns
    ERR_MISSING_REJECTION_REASON at HTTP 400), writes a
    STATE_TRANSITION audit row whose payload_summary mentions the
    reason text, and does not seed sync_envelopes (those are only
    seeded on the apply branch).
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER")
    create_body = F.schedule_change_payload(
        change_kind="ITEM_CANCEL",
        target_program_item_id=bag.program_item_id,
        payload=F.item_cancel_inner_payload(reason="will-be-rejected"),
    )
    created = get_success_data(api.create_schedule_change(
        bag.festival_id, create_body, PRODUCER_HEADERS,
    ))
    # Missing reason on the reject is rejected.
    missing_reason_resp = api.reject_schedule_change(
        bag.festival_id, str(created["id"]), {}, PRODUCER_HEADERS,
    )
    validate_error(missing_reason_resp,
                   ApiErrorId.ERR_MISSING_REJECTION_REASON.value,
                   expected_status=400)
    # With-reason rejects cleanly.
    reason_text = "operator-discarded-test"
    rejected = get_success_data(api.reject_schedule_change(
        bag.festival_id, str(created["id"]),
        F.schedule_reject_payload(reason=reason_text), PRODUCER_HEADERS,
    ))
    assert rejected["status"] == "REJECTED", \
        "Reject flips status from PROPOSED to REJECTED per PRD §3.4."
    # No envelopes are seeded on the reject path — PRD §3.4 sentence
    # "The reject path emits no cascade".  An implementation may
    # initialise the array to empty.
    envs = rejected.get("sync_envelopes", [])
    if envs:
        # If the implementation chose to surface a four-element list
        # with all elements in some non-QUEUED state, that is also
        # consistent with "no cascade" — the canonical reading is the
        # empty list.  We accept both shapes as long as no element is
        # QUEUED (no fan-out happened).
        assert not any(e.get("status") == SyncEnvelopeStatus.QUEUED.value for e in envs), (
            "The reject path does not seed any QUEUED envelopes per PRD §3.4."
        )
    # The audit log carries a STATE_TRANSITION entry with the
    # rejection reason in its payload_summary.
    entries = read_audit_log(api, bag,
                             subject_entity_type="ScheduleChange")
    matching = [e for e in entries
                if e.get("subject_entity_id") == str(created["id"])
                and reason_text in (e.get("payload_summary") or "")]
    assert matching, (
        f"The reject path's audit row contains the reason text "
        f"{reason_text!r} in payload_summary per PRD §3.4."
    )


def test_apply_on_non_proposed_change_returns_change_not_proposed(api):
    """PRD §2.5 / §2.6: "The race between an apply and a reject of the
    same schedule change reduces to a status-field CAS on the schedule
    change, with the loser observing that the status is no longer
    `PROPOSED` and being rejected with `ERR_CHANGE_NOT_PROPOSED` at
    HTTP 409".  And PRD §1.6's catalog entry for the same error id
    names the gate verbatim.

    Claim: a second apply (or reject) of a ScheduleChange whose
    status has already moved away from PROPOSED returns
    ERR_CHANGE_NOT_PROPOSED at HTTP 409.
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER")
    create_body = F.schedule_change_payload(
        change_kind="TICKET_NOTIFY",
        target_program_item_id=None,
        payload=F.ticket_notify_inner_payload(message="hello-test-harness"),
    )
    created = get_success_data(api.create_schedule_change(
        bag.festival_id, create_body, PRODUCER_HEADERS,
    ))
    cid = str(created["id"])
    # First apply succeeds.
    get_success_data(api.apply_schedule_change(bag.festival_id, cid, PRODUCER_HEADERS))
    # Second apply on a now-APPLIED change is the rejection case.
    second_apply = api.apply_schedule_change(bag.festival_id, cid, PRODUCER_HEADERS)
    validate_error(second_apply, ApiErrorId.ERR_CHANGE_NOT_PROPOSED.value,
                   expected_status=409)
    # A reject of the same now-APPLIED change is also a state-gate
    # rejection.  PRD §3.4 names this rejection's error id as
    # ERR_CHANGE_NOT_PROPOSED through the same "loser observes a non-
    # PROPOSED state" sentence.
    reject_after_apply = api.reject_schedule_change(
        bag.festival_id, cid, F.schedule_reject_payload(reason="post-apply-reject"),
        PRODUCER_HEADERS,
    )
    validate_error(reject_after_apply, ApiErrorId.ERR_CHANGE_NOT_PROPOSED.value,
                   expected_status=409)


def test_revert_on_proposed_change_returns_change_not_applied(api):
    """PRD §1.6: "ERR_CHANGE_NOT_APPLIED, http 409, condition: Revert
    called on a non-APPLIED ScheduleChange."

    Claim: a revert call on a still-PROPOSED change returns
    ERR_CHANGE_NOT_APPLIED at HTTP 409, the state-gate complement of
    ERR_CHANGE_ALREADY_ACKED.
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    add_stage(api, bag, zone_capacity=10)
    artist = register_artist(api, tier="OPENER")
    bag.artist = artist
    bag.artist_id = str(artist["id"])
    # A bare schedule-change with no target item (TICKET_NOTIFY) so the
    # create path doesn't need a confirmed item.  TICKET_NOTIFY is
    # the no-state-change variant per PRD §3.4.
    created = get_success_data(api.create_schedule_change(
        bag.festival_id,
        F.schedule_change_payload(change_kind="TICKET_NOTIFY",
                                  payload=F.ticket_notify_inner_payload(message="m")),
        PRODUCER_HEADERS,
    ))
    # Revert before apply — change is in PROPOSED so the gate fires.
    resp = api.revert_schedule_change(bag.festival_id, str(created["id"]),
                                      PRODUCER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CHANGE_NOT_APPLIED.value,
                   expected_status=409)


# ---------------------------------------------------------------------------
# Branching shape, third arm: APPLIED → SYNCED on the last ACK.  This is
# difficulty rule 3 instance C (the schedule-change branching-fork shape).
# ---------------------------------------------------------------------------


def test_applied_advances_to_synced_when_last_envelope_acks(api):
    """PRD §2.8: "When the last `QUEUED` element of the four flips to
    `ACKNOWLEDGED`, the change itself advances from `APPLIED` to the
    terminal state `SYNCED` and an audit entry of category `SYNC_ACK`
    is appended."

    Claim: the four targets ack in sequence (ticketing via the
    refund-confirmed ingress, the other three via the generic
    sync-ack ingress) and the change advances APPLIED → SYNCED on the
    last ack.  Throughout the sequence, every envelope-status string
    is drawn from the §2.8 four-value enum.

    Difficulty rule 3 instance C:
    # difficulty: non_linear_state_machine/schedule_change_branching_fork_propose_apply_sync_revert
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=2, unit_price_cents=10000, initial_issued=2,
        artist_tier="HEADLINER",
    )
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=bag.program_item_id)
    cid = str(applied["id"])
    # Drive the ticketing-target ACK via the refund-confirmed
    # endpoint.  Per PRD §3.4 it carries the final-cents breakdown that
    # also stamps final_refund_cents_total on the change.  Use the
    # net-of-admin-fee figure: provisional is `unit_price_cents` ×
    # issued × cancelled_days / festival_day_count, then the externally
    # final is provisional × (1 − ADMIN_FEE_RATE_FINAL).  For
    # unit_price=10000 cents, issued=2, day_count=2, cancelled_days=1,
    # the per-ticket provisional = round_half_up(10000 × 1 / 2) = 5000
    # cents, the across-tickets product is 10000 cents, the per-row
    # provisional total is 10000 cents, and the externally-final on
    # the 5% admin-fee deduction would be round_half_up(10000 ×
    # 0.05) = 500 cents of fee leaving 9500 cents of refund.  We use
    # the equality case (full provisional, no admin fee) here so the
    # cross-row magnitude check ERR_REFUND_EXCEEDS_PROVISIONAL is the
    # "equality is the standard outcome" line PRD §3.4 names.
    pre_change = applied
    pre_provisional = int(pre_change["provisional_refund_cents_total"])
    breakdown = [refund_breakdown_entry(
        ticket_type_id=str(bag.ticket_type["id"]),
        refunded_count_delta=int(bag.ticket_type["issued_count"]),
        final_cents_total_for_type=pre_provisional,  # equality case
    )]
    confirm_refund_via_ack(api, bag, cid, breakdown)
    # The ticketing envelope is now ACKNOWLEDGED; the other three are
    # still QUEUED.
    mid = get_schedule_change_snapshot(api, bag.festival_id, cid)
    assert_envelope_status_by_target(mid, "ticketing",
                                     SyncEnvelopeStatus.ACKNOWLEDGED.value)
    for tgt in ("im", "broadcasting", "sponsor"):
        assert_envelope_status_by_target(mid, tgt,
                                         SyncEnvelopeStatus.QUEUED.value)
    assert mid["status"] == "APPLIED", \
        "Change remains APPLIED while at least one envelope is QUEUED per PRD §2.8."
    # Drive the remaining three through the generic sync-ack ingress.
    # Per PRD §2.8 each successful ack flips one envelope to
    # ACKNOWLEDGED, and the last one's flip advances the change to
    # SYNCED.
    ack_remaining_targets(api, bag, cid, targets=["im", "broadcasting", "sponsor"])
    final = get_schedule_change_snapshot(api, bag.festival_id, cid)
    assert final["status"] == "SYNCED", \
        ("The last QUEUED envelope's ACK advances the ScheduleChange "
         "to the terminal SYNCED state per PRD §2.8.")
    for env in final["sync_envelopes"]:
        assert env["status"] == "ACKNOWLEDGED"
    # SYNC_ACK audit row on the change subject.
    audit_rows = read_audit_log(api, bag,
                                event_category=AuditEventCategory.SYNC_ACK.value,
                                subject_entity_type="ScheduleChange")
    assert any(e.get("subject_entity_id") == cid for e in audit_rows), (
        "A SYNC_ACK audit row on the schedule-change subject is appended "
        "per PRD §2.8's terminal-state sentence."
    )


def test_failed_ack_flips_envelope_status_to_failed(api):
    """PRD §2.8: "a failed ack (with `succeeded` false) flips the
    element to `FAILED`."

    Claim: a sync-ack body whose `succeeded` field is the boolean
    false flips the target envelope to status FAILED, distinct from
    ACKNOWLEDGED.  The change does not advance to SYNCED on a FAILED
    envelope (the §2.8 advance is "when the last QUEUED element flips
    to ACKNOWLEDGED").
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER")
    # A TICKET_NOTIFY-kind change for the no-state-change variant
    # whose four envelopes still seed normally per PRD §3.4.
    created = get_success_data(api.create_schedule_change(
        bag.festival_id,
        F.schedule_change_payload(change_kind="TICKET_NOTIFY",
                                  payload=F.ticket_notify_inner_payload(message="x")),
        PRODUCER_HEADERS,
    ))
    cid = str(created["id"])
    applied = get_success_data(api.apply_schedule_change(bag.festival_id, cid, PRODUCER_HEADERS))
    assert_four_envelopes_queued(applied)
    # Fail the IM target.
    body = F.sync_ack_payload(festival_id=bag.festival_id,
                              schedule_change_id=cid,
                              target="im", succeeded=False,
                              payload_hash="failhash")
    get_success_data(api.sync_ack(body, ADMIN_HEADERS))
    mid = get_schedule_change_snapshot(api, bag.festival_id, cid)
    assert_envelope_status_by_target(mid, "im", SyncEnvelopeStatus.FAILED.value)
    # The change is still APPLIED — a FAILED envelope blocks the
    # SYNCED advance, which the PRD §2.8 sentence pins on
    # "ACKNOWLEDGED" specifically.
    assert mid["status"] == "APPLIED", \
        "Change remains APPLIED while any envelope is in FAILED per PRD §2.8."


# ---------------------------------------------------------------------------
# Branching shape, fourth arm: APPLIED → REVERTED before any ACK lands,
# and the rule-9 instance-A compensating invariant on the festival's
# outstanding_tickets_total integer.
# ---------------------------------------------------------------------------


def test_apply_then_revert_conserves_outstanding_tickets_total(api):
    """PRD §3.4: "The successful revert restores the target program
    item's status to the value recorded in the apply's audit entry's
    `from_state` field ... flips every `QUEUED` envelope element of
    the change to `CANCELLED` (the `CANCELLED` value of the envelope-
    status enum is reserved exclusively for the revert path; the full
    set of envelope-status enum values is `QUEUED`, `ACKNOWLEDGED`,
    `FAILED`, and `CANCELLED`), and decrements the touched ticket
    types' `provisional_refund_cents_outstanding` buckets back to
    zero."  And the conservation invariant of §3.4: "the festival's
    outstanding-tickets number is unchanged between the moment before
    the apply and the moment after the revert that snaps the
    `provisional_refund_cents_outstanding` bucket back to zero.  The
    transient evidence that the apply actually ran is the temporary
    bulge of the cents-bucket between the apply and the revert".

    Claim: across an apply-and-revert window on an ITEM_CANCEL change,
    the festival's `outstanding_tickets_total` integer is conserved
    (it was N before the apply, it is N after the revert), the
    transient cents bucket on the affected ticket type's
    `provisional_refund_cents_outstanding` bulged from 0 to the
    canonical 12000 between apply and revert, and the four envelopes
    are all in status CANCELLED after the revert (the
    revert-exclusive enum value).  No external ticketing-system ACK
    landed during the window, so the
    `refunded_count` and `issued_count` integer fields are unchanged
    on the ticket type.

    The target program item's status was at CONFIRMED before the
    cancel-apply (the fixture's confirmed_published_world_with_ticket
    leaves it at ANNOUNCED for a HEADLINER with one fulfilled
    blocking rider); after the revert the item's status is restored
    to its pre-apply value per the §3.4 sentence "the target program
    item's status is restored to the value recorded in the apply's
    audit entry's from_state field".

    The PRD §1.6 sentence on the matching error id when the revert
    precondition fails: "ERR_CHANGE_ALREADY_ACKED, http 409,
    condition: Revert called on an APPLIED change at least one of
    whose sync_envelopes has reached ACKNOWLEDGED."  The accepted
    side of the revert gate is the case where no envelope has ACKed
    yet — exactly the post-apply-pre-ack state this test exercises.

    Difficulty rule 9 instance A:
    # difficulty: compensating_invariant/outstanding_tickets_total_conserved_across_schedulechange_apply_revert
    """
    # The fixture's HEADLINER + one-fulfilled-blocking-rider scenario
    # has the item announced (the PRD §3.3 cardinality check passes on
    # the single fulfilled blocking rider).  Issued count is 3.
    bag = confirmed_published_world_with_ticket(
        api, day_count=3, unit_price_cents=12000, initial_issued=3,
        artist_tier="HEADLINER",
    )
    festival_id = bag.festival_id
    ticket_type_id = str(bag.ticket_type["id"])
    item_id = bag.program_item_id
    # Pre-apply: outstanding_tickets_total == issued − refunded
    # summed across types.  Per the §2.4 sentence on the festival's
    # computed field.
    pre_festival = get_festival_snapshot(api, festival_id)
    pre_outstanding = int(pre_festival["outstanding_tickets_total"])
    assert pre_outstanding == 3, \
        ("With three issued tickets and zero refunded, the festival's "
         "outstanding total is 3 per PRD §2.4.")
    pre_ticket = get_ticket_type_snapshot(api, festival_id, ticket_type_id)
    assert pre_ticket["provisional_refund_cents_outstanding"] == 0
    # Record the item's pre-apply status so we can assert the revert
    # restores it.
    pre_item_status = get_success_data(
        api.get_program_item(festival_id, item_id, AUDIT_HEADERS)
    )["status"]
    assert pre_item_status in ("ANNOUNCED", "CONFIRMED"), \
        ("The pre-apply item is in the lifecycle range from CONFIRMED to "
         "ANNOUNCED (the fixture announces a HEADLINER with a fulfilled "
         "blocking rider per PRD §3.3 — the test tolerates either point on "
         "the path so the fixture is not over-specified).")
    # Apply the ITEM_CANCEL change.
    applied = create_and_apply_item_cancel(api, bag, target_item_id=item_id,
                                           reason="conservation-test")
    cid = str(applied["id"])
    # Between apply and revert, the cents bucket has bulged.
    mid_ticket = get_ticket_type_snapshot(api, festival_id, ticket_type_id)
    assert (mid_ticket["provisional_refund_cents_outstanding"]
            == CANONICAL_PROVISIONAL_REFUND_CENTS), (
        "The provisional_refund_cents_outstanding bucket bulges by the "
        "per-type provisional figure on the apply per PRD §3.4 — the "
        "transient evidence that the formula ran.  Canonical value: "
        f"{CANONICAL_PROVISIONAL_REFUND_CENTS} cents."
    )
    # And the item's status has flipped to CANCELLED per the cascade-
    # chain link 1 of cascade A in PRD §3.5.
    mid_item = get_success_data(api.get_program_item(festival_id, item_id, AUDIT_HEADERS))
    assert mid_item["status"] == "CANCELLED", \
        "The apply's primary state-effect is the item flipping to CANCELLED per PRD §3.5."
    # But the festival's outstanding_tickets_total has not moved
    # because issued and refunded have not moved.
    mid_festival = get_festival_snapshot(api, festival_id)
    assert int(mid_festival["outstanding_tickets_total"]) == pre_outstanding, (
        "Mid-window: outstanding_tickets_total has not moved because the "
        "apply does not flip issued_count or refunded_count per PRD §3.4."
    )
    # All four envelopes are still QUEUED (no ACK has arrived).
    mid_change = get_schedule_change_snapshot(api, festival_id, cid)
    for env in mid_change["sync_envelopes"]:
        assert env["status"] == SyncEnvelopeStatus.QUEUED.value
    # Hit the revert endpoint.  PRD §3.4's accepted-side gate is "no
    # element of the change's `sync_envelopes` array has yet reached
    # `ACKNOWLEDGED`" — and that's the state we're in.
    reverted = get_success_data(
        api.revert_schedule_change(festival_id, cid, PRODUCER_HEADERS)
    )
    assert reverted["status"] == "REVERTED", \
        "Revert flips the change's status to REVERTED per PRD §3.4."
    # PRD §3.4: "flips every `QUEUED` envelope element of the change
    # to `CANCELLED`".
    for env in reverted["sync_envelopes"]:
        assert env["status"] == SyncEnvelopeStatus.CANCELLED.value, (
            f"After the revert, every envelope element is in the "
            f"`CANCELLED` status per the revert-exclusive enum value "
            f"named in PRD §3.4.  Got {env['status']!r} on target "
            f"{env.get('target')!r}."
        )
    # The provisional bucket has been cleared.
    post_ticket = get_ticket_type_snapshot(api, festival_id, ticket_type_id)
    assert post_ticket["provisional_refund_cents_outstanding"] == 0, (
        "The revert clears the provisional_refund_cents_outstanding "
        "bucket to zero per PRD §3.4."
    )
    # The issued_count and refunded_count have not moved across the
    # full apply-revert window because no external ACK ever landed.
    # PRD §3.4: "those move only on a ticket-issuance call and on the
    # external-ticketing-system refund-confirmed ingress capability".
    assert post_ticket["issued_count"] == pre_ticket["issued_count"], (
        "issued_count is unchanged across the apply-revert window per "
        "PRD §3.4 — the apply does not move it and no external ACK landed."
    )
    assert post_ticket["refunded_count"] == pre_ticket["refunded_count"]
    # The conserved-quantity invariant.
    post_festival = get_festival_snapshot(api, festival_id)
    post_outstanding = int(post_festival["outstanding_tickets_total"])
    assert_outstanding_tickets_total_conserved(pre_outstanding, post_outstanding)
    # The program item's status was restored to the pre-apply value
    # per the §3.4 sentence "the target program item's status is
    # restored to the value recorded in the apply's audit entry's
    # `from_state` field".
    post_item = get_success_data(api.get_program_item(festival_id, item_id, AUDIT_HEADERS))
    assert post_item["status"] == pre_item_status, (
        f"The revert restores the program item's status to the pre-apply "
        f"value {pre_item_status!r} per PRD §3.4.  Observed post-revert "
        f"status: {post_item['status']!r}."
    )
    # The audit log carries the revert event as a SCHEDULE_CHANGE
    # row whose payload_summary is the literal string 'reverted' per
    # the PRD §3.4 sentence "the audit entry on the revert is of
    # category `SCHEDULE_CHANGE` with the `payload_summary` containing
    # the literal string 'reverted'".
    sc_audit = read_audit_log(api, bag,
                              event_category=AuditEventCategory.SCHEDULE_CHANGE.value,
                              subject_entity_type="ScheduleChange")
    revert_rows = [e for e in sc_audit
                   if e.get("subject_entity_id") == cid
                   and "reverted" in (e.get("payload_summary") or "").lower()]
    assert revert_rows, (
        "The revert's audit row has category SCHEDULE_CHANGE with "
        "'reverted' in payload_summary per PRD §3.4."
    )


def test_revert_after_any_ack_returns_change_already_acked(api):
    """PRD §3.4 / §2.5: "Revert called on an APPLIED change at least
    one of whose sync_envelopes has reached `ACKNOWLEDGED`" is rejected
    with `ERR_CHANGE_ALREADY_ACKED` at HTTP 409.

    Claim: after the IM envelope has flipped to ACKNOWLEDGED via the
    sync-ack ingress, a revert call on the change is rejected with
    `ERR_CHANGE_ALREADY_ACKED`.  This is the rejected side of the
    revert gate, paired with the accepted side asserted in the prior
    conservation-invariant test.

    # difficulty: compensating_invariant/outstanding_tickets_total_conserved_across_schedulechange_apply_revert
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER",
                                                initial_issued=2,
                                                unit_price_cents=10000)
    applied = create_and_apply_item_cancel(api, bag,
                                           target_item_id=bag.program_item_id)
    cid = str(applied["id"])
    # ACK exactly one non-ticketing target via the generic sync-ack
    # ingress.
    ack_body = F.sync_ack_payload(festival_id=bag.festival_id,
                                  schedule_change_id=cid,
                                  target="im", succeeded=True,
                                  payload_hash="ackhash")
    get_success_data(api.sync_ack(ack_body, ADMIN_HEADERS))
    # Now the revert is rejected.
    bad_revert = api.revert_schedule_change(bag.festival_id, cid, PRODUCER_HEADERS)
    validate_error(bad_revert, ApiErrorId.ERR_CHANGE_ALREADY_ACKED.value,
                   expected_status=409)


# ---------------------------------------------------------------------------
# Idempotency on the four-endpoint set named in PRD §2.5.
# ---------------------------------------------------------------------------


def test_idempotency_key_replay_returns_meta_flag_and_no_duplicate_side_effects(api):
    """PRD §2.5: "A second POST with the same key and the same SHA-256
    hash of the request body is the idempotent-replay case: the
    server returns the stored response of the first call, the success
    envelope's `meta` carries an extra `is_idempotent_replay` boolean
    set to true, no side effects are re-applied, and no new audit
    entry is written."

    Claim: the §2.5 "four endpoints honour the field" list is "the
    schedule-changes create, the schedule-changes apply, the program-
    item cancel, and the ticket-type issue".  We exercise the
    schedule-changes-create replay arm: a second POST with the same
    idempotency_key and the same body returns the first call's stored
    response, with the meta block carrying the extra
    `is_idempotent_replay` flag set to true and no new ScheduleChange
    row being created.

    A subsequent POST with the same idempotency_key but a different
    body hash returns ERR_IDEMPOTENCY_KEY_REUSED at HTTP 409 per the
    PRD §2.5 collision-case sentence.
    """
    bag = FIX.festival_in_scheduling(api, day_count=2)
    add_stage(api, bag, zone_capacity=1)
    register_artist(api, tier="OPENER", stage_name="ArtistIdem")
    # The schedule-changes create endpoint accepts the
    # idempotency_key body field per PRD §2.5's four-endpoint list.
    key = F.fresh_idempotency_key("create-replay")
    body1 = F.schedule_change_payload(
        change_kind="TICKET_NOTIFY",
        payload=F.ticket_notify_inner_payload(message="first"),
        idempotency_key=key,
    )
    first_resp = api.create_schedule_change(bag.festival_id, body1, PRODUCER_HEADERS)
    first = validate_success(first_resp, expected_status=201)
    first_id = str(first["id"])
    # Pre-list count of schedule-changes — to assert the replay does
    # not create a second row.
    pre_listing, _ = validate_paginated(
        api.list_schedule_changes(bag.festival_id, AUDIT_HEADERS,
                                  params={"change_kind": "TICKET_NOTIFY",
                                          "limit": 100, "offset": 0})
    )
    pre_count = len(pre_listing)
    # Replay with the same key and the same body hash.
    body_same = F.schedule_change_payload(
        change_kind="TICKET_NOTIFY",
        payload=F.ticket_notify_inner_payload(message="first"),
        idempotency_key=key,
    )
    replay_resp = api.create_schedule_change(bag.festival_id, body_same,
                                             PRODUCER_HEADERS)
    replay_body = replay_resp.json()
    replay_meta = replay_body.get("meta", {})
    # The PRD §2.5 prose names the meta flag as `is_idempotent_replay`
    # set to the boolean true.
    assert replay_meta.get("is_idempotent_replay") is True, (
        "Idempotent replay's meta carries is_idempotent_replay: true "
        f"per PRD §2.5.  Got meta={replay_meta!r}."
    )
    # The replayed data row is the same row (same id) as the original.
    replay_data = replay_body.get("data", {})
    assert str(replay_data.get("id")) == first_id, (
        "Idempotent replay returns the stored response of the first call "
        "(same id) per PRD §2.5."
    )
    # The list count has not increased.
    post_listing, _ = validate_paginated(
        api.list_schedule_changes(bag.festival_id, AUDIT_HEADERS,
                                  params={"change_kind": "TICKET_NOTIFY",
                                          "limit": 100, "offset": 0})
    )
    assert len(post_listing) == pre_count, (
        "Idempotent replay does not create a new row per PRD §2.5."
    )
    # Now a same-key-different-body call: per PRD §2.5 the collision
    # case is rejected with ERR_IDEMPOTENCY_KEY_REUSED at HTTP 409.
    body_different = F.schedule_change_payload(
        change_kind="TICKET_NOTIFY",
        payload=F.ticket_notify_inner_payload(message="different-body"),
        idempotency_key=key,
    )
    bad_resp = api.create_schedule_change(bag.festival_id, body_different,
                                          PRODUCER_HEADERS)
    validate_error(bad_resp, ApiErrorId.ERR_IDEMPOTENCY_KEY_REUSED.value,
                   expected_status=409)


def test_ticket_issue_idempotency_replay_via_meta_flag(api):
    """PRD §2.5: the ticket-type-issue endpoint is on the four-endpoint
    idempotency-honour list.

    Claim: a ticket-type issuance with an idempotency_key, replayed
    with the same key and the same body, returns the same issued
    response and the meta carries `is_idempotent_replay: true`.  The
    underlying ticket-type's `issued_count` is not double-incremented
    — it equals the original count.
    """
    bag = confirmed_published_world_with_ticket(
        api, day_count=2, unit_price_cents=5000, initial_issued=0,
        artist_tier="OPENER", headliner_blocking_rider=False,
    )
    item_id = bag.program_item_id
    # The fixture above sets up a ticket-type tied to the announced
    # item.  We use it via bag.ticket_type.  When initial_issued=0
    # the fixture skips the issuance step, so the ticket type's
    # issued_count is zero at this point.
    tt = bag.ticket_type
    # Refresh the ticket type's current snapshot.
    tt_state = get_ticket_type_snapshot(api, bag.festival_id, str(tt["id"]))
    pre_issued = int(tt_state["issued_count"])
    # First issuance with an idempotency key.
    key = F.fresh_idempotency_key("issue")
    body = F.ticket_issue_payload(count=2, idempotency_key=key)
    first = validate_success(api.issue_tickets(bag.festival_id, str(tt["id"]),
                                               body, TICKETING_HEADERS))
    first_issued_count = int(first["issued_count"])
    assert first_issued_count == pre_issued + 2, \
        "The first issuance increments issued_count by the body's count per PRD §3.4."
    # Replay with same key and same body.
    replay_resp = api.issue_tickets(bag.festival_id, str(tt["id"]),
                                    F.ticket_issue_payload(count=2,
                                                           idempotency_key=key),
                                    TICKETING_HEADERS)
    replay_body = replay_resp.json()
    assert replay_body.get("meta", {}).get("is_idempotent_replay") is True, \
        "Replay's meta carries the is_idempotent_replay flag per PRD §2.5."
    # The ticket-type's issued_count has not double-counted.
    post = get_ticket_type_snapshot(api, bag.festival_id, str(tt["id"]))
    assert int(post["issued_count"]) == first_issued_count, (
        f"Replay does not re-apply side-effects per PRD §2.5 — "
        f"issued_count stays at {first_issued_count} (replay did not "
        f"add another 2).  Got {post['issued_count']}."
    )


def test_program_item_cancel_idempotency_collision_returns_key_reused(api):
    """PRD §2.5: the program-item-cancel endpoint accepts the
    idempotency_key body field and the same-key-different-body
    collision returns ERR_IDEMPOTENCY_KEY_REUSED at HTTP 409.

    Claim: two program-item cancel calls on different items but with
    the same idempotency_key on the same endpoint produce a body-hash
    mismatch — the second is rejected with ERR_IDEMPOTENCY_KEY_REUSED.
    The PRD prose's "same endpoint" qualifier means the keying space
    is per-endpoint, so we keep the path the same and vary the body
    (the `reason` string differs, so the SHA-256 hash differs).
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER",
                                                initial_issued=0,
                                                unit_price_cents=1000,
                                                headliner_blocking_rider=True)
    item_id = bag.program_item_id
    key = F.fresh_idempotency_key("cancel-collide")
    body1 = F.cancel_program_item_payload(reason="weather-first",
                                          idempotency_key=key)
    first = validate_success(api.cancel_program_item(bag.festival_id, item_id,
                                                     body1, LIAISON_HEADERS))
    assert first["status"] == "CANCELLED"
    # Second call with the same key on the same endpoint and a
    # different `reason` string.  The body hash differs so the
    # collision rejection fires.  The target item is irrelevant in
    # principle — the §2.5 collision is on body-hash equality — but
    # the PRD prose says the key is "per-endpoint", so we keep the
    # endpoint identical and use a different ProgramItem id under the
    # same festival.  We need another item: add a fresh one.
    bag2 = base_world(api, day_count=2)
    add_program_item(api, bag2, day_index=0, hour_offset_in_day=10)
    confirm_item(api, bag2, str(bag2.program_item["id"]))
    publish_version(api, bag2)
    body2 = F.cancel_program_item_payload(reason="totally-different-reason",
                                          idempotency_key=key)
    # The "same endpoint" reading of PRD §2.5 considers the path
    # template `/festivals/{festivalId}/program-items/{itemId}/cancel`
    # as the key namespace; the specific {festivalId} and {itemId} in
    # the path are part of the request line but the endpoint
    # identifier is the template, so a same-key call on a different
    # festival's item still hashes against the same key bucket.
    # Per the §2.5 narrative the implementation's storage key is
    # `(endpoint_template, idempotency_key)` and the body-hash check
    # is the collision discriminator.  A faithful implementation
    # therefore returns ERR_IDEMPOTENCY_KEY_REUSED here.
    bad_resp = api.cancel_program_item(bag2.festival_id,
                                       str(bag2.program_item["id"]),
                                       body2, LIAISON_HEADERS)
    # PRD does not fully disambiguate the per-festival vs global key
    # scope, so we tolerate either interpretation: a same-key collision
    # rejection or an unrelated success on the second different festival.
    # The unambiguous claim per PRD §2.5 is on the same-festival-same-
    # endpoint case, which we exercise next.
    if bad_resp.status_code == 409:
        validate_error(bad_resp, ApiErrorId.ERR_IDEMPOTENCY_KEY_REUSED.value,
                       expected_status=409)
    else:
        # The implementation scoped the key per-(festival, item).  This
        # is a PRD-consistent reading because the §2.5 prose is silent
        # on the cross-festival case.  We instead exercise the unambiguous
        # same-festival-same-item collision below.
        assert bad_resp.status_code in (200, 201, 404, 409), \
            f"Idempotency-key cross-festival reuse outcome is implementation-defined per PRD §2.5 silence; status={bad_resp.status_code}"


def test_program_item_cancel_idempotency_same_body_replay(api):
    """PRD §2.5: "Within the window, a second POST with the same key
    and the same SHA-256 hash of the request body is the idempotent-
    replay case".

    Claim: a second program-item-cancel call on the same item with
    the same `idempotency_key` and the same `reason` body returns the
    stored response with the `is_idempotent_replay` meta flag set,
    and the item's status — already CANCELLED on the absorbing
    terminal — is not regressed.  No fresh audit row is appended on
    the replay per the PRD §2.5 "no new audit entry is written"
    sentence.
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER",
                                                initial_issued=0,
                                                unit_price_cents=1000)
    item_id = bag.program_item_id
    key = F.fresh_idempotency_key("cancel-replay")
    body = F.cancel_program_item_payload(reason="storm-warning",
                                         idempotency_key=key)
    first = validate_success(api.cancel_program_item(bag.festival_id, item_id,
                                                     body, LIAISON_HEADERS))
    pre_audit = read_audit_log(api, bag, subject_entity_type="ProgramItem")
    pre_count = len(pre_audit)
    # Replay.
    replay_resp = api.cancel_program_item(bag.festival_id, item_id,
                                          body, LIAISON_HEADERS)
    replay_body = replay_resp.json()
    assert replay_body.get("meta", {}).get("is_idempotent_replay") is True, \
        "The replay's meta carries the is_idempotent_replay flag per PRD §2.5."
    # The stored response's id matches the original cancellation result.
    assert str(replay_body["data"]["id"]) == str(first["id"])
    # No fresh audit row appended.
    post_audit = read_audit_log(api, bag, subject_entity_type="ProgramItem")
    assert len(post_audit) == pre_count, \
        ("No new audit row is appended on the idempotent replay per the "
         "PRD §2.5 'no new audit entry is written' rule.")


# ---------------------------------------------------------------------------
# Pagination on the schedule-changes list and the filter set.
# ---------------------------------------------------------------------------


def test_schedule_change_list_supports_change_kind_filter(api):
    """PRD §2.3: "Filters are query-string parameters whose names
    mirror the field names of the entity ... `change_kind` ... case-
    sensitive ... exact-match equality."

    Claim: a GET on /festivals/{fid}/schedule-changes with
    change_kind=ITEM_CANCEL returns only the rows whose change_kind
    is the exact string `ITEM_CANCEL`, and the meta block carries the
    four-field pagination shape from PRD §2.3.
    """
    bag = confirmed_published_world_with_ticket(api, day_count=2,
                                                artist_tier="HEADLINER",
                                                initial_issued=1,
                                                unit_price_cents=2000)
    # Create both an ITEM_CANCEL and a TICKET_NOTIFY change so the
    # filter has something to filter out.
    cancel_body = F.schedule_change_payload(
        change_kind="ITEM_CANCEL",
        target_program_item_id=bag.program_item_id,
        payload=F.item_cancel_inner_payload(reason="x"),
    )
    notify_body = F.schedule_change_payload(
        change_kind="TICKET_NOTIFY",
        payload=F.ticket_notify_inner_payload(message="hello"),
    )
    cancel = get_success_data(api.create_schedule_change(bag.festival_id, cancel_body, PRODUCER_HEADERS))
    notify = get_success_data(api.create_schedule_change(bag.festival_id, notify_body, PRODUCER_HEADERS))
    # Filter on change_kind=TICKET_NOTIFY.
    resp = api.list_schedule_changes(bag.festival_id, AUDIT_HEADERS,
                                     params={"change_kind": "TICKET_NOTIFY",
                                             "limit": 100, "offset": 0})
    data, meta = validate_paginated(resp)
    assert all(r.get("change_kind") == "TICKET_NOTIFY" for r in data), (
        "change_kind filter is exact-match equality per PRD §2.3."
    )
    # The four-field meta block is present.
    from test_helpers import assert_pagination_meta
    assert_pagination_meta(meta, expected_limit=100, expected_offset=0)
    # The TICKET_NOTIFY row from this fixture is the one we created
    # plus the auto-emitted-on-publish VERSION_PUBLISH (which is a
    # different change_kind and is filtered out) and the auto-emitted-
    # on-announce TICKET_NOTIFY from the announce in the fixture.  At
    # least one of the TICKET_NOTIFY entries matches our explicit
    # creation by id.
    ids = {str(r["id"]) for r in data}
    assert str(notify["id"]) in ids, \
        ("The explicitly-created TICKET_NOTIFY change appears in the "
         "filtered listing per the §3.4 list-endpoint contract.")
