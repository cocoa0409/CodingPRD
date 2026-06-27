"""Validation precedence ordering, slot overlap, and OCC on booking create.

Covers the priority-pair conflicts (state-check vs cross-entity gate; payment
referential vs fiscal), the buffered audition-slot overlap rule, and the
stale-talent-version optimistic-concurrency rejection on booking create.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    create_payment_payload,
    create_booking_payload,
    confirm_payload,
    create_audition_slot_payload,
    setup_pending_booking,
    setup_completed_booking,
    setup_open_call_with_submission,
    setup_rostered_talent,
    make_casting_director_headers,
    make_talent_headers,
    create_casting_call,
    create_submission,
    create_availability_hold,
    create_deal_memo_payload,
    offer_payload,
    schedule_audition_slot,
    talent_version,
    create_talent,
)

AGENT = TEST_USERS["agent_headers"]


# ─── priority_pair: confirm state-check beats cross-entity gate ──────────────
def test_confirm_cancelled_booking_state_check_beats_deal_gate(api):
    """PRD §2.9: "Sixth, the target resource's own state is checked for
    transition legality, failing with `ERR_INVALID_STATE` (409). Seventh,
    cross-entity gates that require a referenced sibling to be in a particular
    state are evaluated"
    PRD §2.9: "A request that violates several rules surfaces the highest-priority
    (lowest-numbered) failure."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_cross_entity_gate
    """
    # Build a PENDING booking whose deal is still OFFERED (not accepted), then
    # cancel the booking. Confirming the CANCELLED booking would fail BOTH the
    # state check and the deal-accepted gate; the lower-numbered state check wins.
    base = setup_rostered_talent(union_status="SAG")
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    call = create_casting_call(cd_id, media_type="STREAMING")
    submission = create_submission(call["id"], talent_id, cc_id)
    # Advance submission to AUDITION_SCHEDULED so the deal memo open moves it to
    # OFFER_EXTENDED, making the first offer permitted (PRD §3.5).
    schedule_audition_slot(cd_id, submission["id"])
    dm = get_success_data(
        api.create_deal_memo(
            create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    get_success_data(api.offer_deal_memo(dm["id"], offer_payload(200000, 12), cd_headers))
    hold = create_availability_hold(talent_id)
    tv = talent_version(talent_id)
    booking = get_success_data(
        api.create_booking(
            create_booking_payload(dm["id"], talent_id, call["id"], hold["id"], tv),
            AGENT,
        )
    )
    get_success_data(api.cancel_booking(booking["id"], AGENT))

    resp = api.confirm_booking(booking["id"], confirm_payload(tv), AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_confirm_cancelled_booking_state_check_beats_rostered_gate(api):
    """PRD §2.9: "Sixth, the target resource's own state is checked for
    transition legality, failing with `ERR_INVALID_STATE` (409). Seventh,
    cross-entity gates that require a referenced sibling to be in a particular
    state are evaluated"
    PRD §2.9: "A request that violates several rules surfaces the highest-priority
    (lowest-numbered) failure."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_cross_entity_gate
    """
    # Build a PENDING booking (deal accepted), suspend the talent (would fail the
    # rostered gate), then cancel the booking. Confirming the CANCELLED booking
    # fails the state check (priority 6) ahead of the talent-rostered gate.
    base = setup_pending_booking(union_status="SAG", media_type="STREAMING")
    talent_id = base["talent"]["id"]
    booking_id = base["booking"]["id"]
    get_success_data(api.suspend_talent(talent_id, AGENT))
    get_success_data(api.cancel_booking(booking_id, AGENT))
    tv = talent_version(talent_id)
    resp = api.confirm_booking(booking_id, confirm_payload(tv), AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ─── priority_pair: payment referential beats fiscal ─────────────────────────
def test_payment_talent_mismatch_beats_escrow_insufficiency(api):
    """PRD §3.8: "The payment's `talent_id` must equal the booking's
    `talent_id`; a mismatch is refused with `ERR_TALENT_MISMATCH`. The agency's
    escrow must also be sufficient to release the booking's held commission
    entry ... otherwise the post is refused with `ERR_ESCROW_INSUFFICIENT`."
    PRD §2.9: "A request that violates several rules surfaces the highest-priority
    (lowest-numbered) failure."

    Design: Difficulty/priority_pair_validation_conflict/payment_referential_beats_fiscal
    """
    base = setup_completed_booking(union_status="SAG", media_type="STREAMING")
    agency_id = base["agency"]["id"]
    booking_id = base["booking"]["id"]
    # A second talent (different id) to drive the talent mismatch.
    talent_b = create_talent(agency_id, union_status="SAG", full_name="Bob B")

    # Mismatched payee AND an enormous gross that would also strain escrow.
    resp = api.create_payment(
        create_payment_payload(booking_id, talent_b["id"], 99999999), AGENT
    )
    validate_error(resp, ApiErrorId.ERR_TALENT_MISMATCH.value, 409)


def test_payment_talent_mismatch_rejected_in_isolation(api):
    """PRD §3.8: "The payment's `talent_id` must equal the booking's
    `talent_id`; a mismatch is refused with `ERR_TALENT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/payment_referential_beats_fiscal
    """
    # Mismatch with a small gross that escrow easily covers — only the referential
    # rule can fire, confirming it is the rule that fired in the conflict case.
    base = setup_completed_booking(union_status="SAG", media_type="STREAMING")
    talent_b = create_talent(base["agency"]["id"], union_status="SAG", full_name="Bob B")
    resp = api.create_payment(
        create_payment_payload(base["booking"]["id"], talent_b["id"], 1000), AGENT
    )
    validate_error(resp, ApiErrorId.ERR_TALENT_MISMATCH.value, 409)


# ─── resource_temporal_overlap: audition slot buffered overlap ──────────────
def test_audition_slot_within_buffer_gap_rejected(api):
    """PRD §3.3: "A new audition slot may not overlap another `SCHEDULED` slot
    belonging to the same `casting_director_id`, where overlap is measured as a
    closed interval extended by a buffer gap of `SLOT_BUFFER_MINUTES` minutes —
    fifteen minutes of turnaround between adjacent slots on one director's
    calendar. A slot that violates this buffered-overlap rule is rejected with
    `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/audition_slot_buffered_overlap_rejected
    """
    base = setup_open_call_with_submission(media_type="DIGITAL", usage_term_months=6)
    cd_id = base["cd"]["id"]
    sub1_id = base["submission"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    # Second submission on the same call for the second slot.
    sub2 = create_submission(base["call"]["id"], base["talent"]["id"], base["comp_card"]["id"])

    # First slot 10:00-10:30.
    schedule_audition_slot(cd_id, sub1_id, start_at="2026-04-10T10:00:00Z",
                           end_at="2026-04-10T10:30:00Z")
    # Second slot starts 10:40 — only 10 minutes after the first ends, inside the
    # 15-minute buffer.
    resp = api.create_audition_slot(
        create_audition_slot_payload(
            sub2["id"], cd_id, slot_kind="AUDITION",
            start_at="2026-04-10T10:40:00Z", end_at="2026-04-10T11:00:00Z",
        ),
        cd_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value, 409)


def test_audition_slot_directly_overlapping_existing_slot_rejected(api):
    """PRD §3.3: "A new audition slot may not overlap another `SCHEDULED` slot
    belonging to the same `casting_director_id`, where overlap is measured as a
    closed interval extended by a buffer gap of `SLOT_BUFFER_MINUTES` minutes"

    Design: Difficulty/resource_temporal_overlap/audition_slot_buffered_overlap_rejected
    """
    base = setup_open_call_with_submission(media_type="DIGITAL", usage_term_months=6)
    cd_id = base["cd"]["id"]
    sub1_id = base["submission"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    sub2 = create_submission(base["call"]["id"], base["talent"]["id"], base["comp_card"]["id"])

    # First slot 10:00-10:30; second slot directly overlapping at 10:15-10:45.
    schedule_audition_slot(cd_id, sub1_id, start_at="2026-04-10T10:00:00Z",
                           end_at="2026-04-10T10:30:00Z")
    resp = api.create_audition_slot(
        create_audition_slot_payload(
            sub2["id"], cd_id, slot_kind="AUDITION",
            start_at="2026-04-10T10:15:00Z", end_at="2026-04-10T10:45:00Z",
        ),
        cd_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value, 409)


# ─── cross_cutting: OCC stale talent version on booking create ──────────────
def test_create_booking_with_stale_talent_version_rejected(api):
    """PRD §2.8: "A create-booking request must carry `expected_talent_version`,
    which is not optional, holding the `version` of the target `Talent` that the
    client last observed. If that value does not equal the talent's current
    `version` at the moment the request is processed, the create is rejected with
    `ERR_STALE_TALENT_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_talent_version_on_booking_create
    """
    base = setup_rostered_talent(union_status="SAG")
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    talent_headers = make_talent_headers(talent_id)
    call = create_casting_call(cd_id, media_type="STREAMING")
    submission = create_submission(call["id"], talent_id, cc_id)
    # Advance submission to AUDITION_SCHEDULED so the deal memo open moves it to
    # OFFER_EXTENDED, making the first offer permitted (PRD §3.5).
    schedule_audition_slot(cd_id, submission["id"])
    dm = get_success_data(
        api.create_deal_memo(
            create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    get_success_data(api.offer_deal_memo(dm["id"], offer_payload(200000, 12), cd_headers))
    get_success_data(api.accept_deal_memo(dm["id"], talent_headers))
    hold = create_availability_hold(talent_id)

    tv_now = talent_version(talent_id)
    resp = api.create_booking(
        create_booking_payload(dm["id"], talent_id, call["id"], hold["id"], tv_now - 1),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_TALENT_VERSION.value, 412)
