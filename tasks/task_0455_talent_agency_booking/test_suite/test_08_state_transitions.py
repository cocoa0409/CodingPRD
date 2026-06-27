"""State-machine precondition and guarded-transition enforcement."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    create_audition_slot_payload,
    create_payment_payload,
    setup_rostered_talent,
    setup_open_call_with_submission,
    setup_pending_booking,
    setup_confirmed_booking,
    setup_completed_booking,
    setup_paid_booking,
    schedule_audition_slot,
    make_casting_director_headers,
    create_agency,
    create_talent,
)

AGENT = TEST_USERS["agent_headers"]


# ─── Precondition: roster requires a comp card ───────────────────────────────
def test_roster_talent_without_comp_card_rejected(api):
    """PRD §3.1: "Moving a talent from `PROSPECT` to `ROSTERED` requires that the
    talent have at least one comp card on file; with none, the activation is
    refused with `ERR_NO_COMP_CARD`."

    Design: Corner/state_machines/roster_without_comp_card_rejected
    """
    agency = create_agency()
    talent = create_talent(agency["id"])  # PROSPECT, no comp card
    resp = api.roster_talent(talent["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_NO_COMP_CARD.value, 409)


# ─── Precondition: complete slot before end_at ───────────────────────────────
def test_complete_audition_slot_before_end_at_rejected(api):
    """PRD §3.3: "A `SCHEDULED` slot can be completed only once the logical clock
    has reached or passed its `end_at`; an attempt before the slot has ended is
    refused with `ERR_SLOT_NOT_ENDED`."

    Design: Corner/state_machines/complete_audition_slot_before_end_rejected
    """
    base = setup_open_call_with_submission(media_type="DIGITAL", usage_term_months=6)
    cd_id = base["cd"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    # Slot ends 2026-04-10T10:30Z; clock left at startup default 2026-01-01.
    slot = schedule_audition_slot(cd_id, base["submission"]["id"])
    resp = api.complete_audition_slot(slot["id"], cd_headers)
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_ENDED.value, 409)


# ─── Guarded transition: callback requires completed audition ────────────────
def test_callback_slot_without_completed_audition_rejected(api):
    """PRD §3.3: "Creating a `CALLBACK`-kind slot advances the submission
    `AUDITION_SCHEDULED → CALLBACK_SCHEDULED`, but this is permitted only when an
    `AUDITION`-kind slot for that same submission has already reached
    `COMPLETED`; without a completed audition, the callback is refused with
    `ERR_AUDITION_NOT_COMPLETED`."

    Design: Corner/state_machines/callback_requires_completed_audition
    """
    base = setup_open_call_with_submission(media_type="DIGITAL", usage_term_months=6)
    cd_id = base["cd"]["id"]
    sub_id = base["submission"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    # AUDITION slot scheduled but left SCHEDULED (not completed).
    schedule_audition_slot(cd_id, sub_id, start_at="2026-04-10T10:00:00Z",
                           end_at="2026-04-10T10:30:00Z")
    resp = api.create_audition_slot(
        create_audition_slot_payload(
            sub_id, cd_id, slot_kind="CALLBACK",
            start_at="2026-04-12T10:00:00Z", end_at="2026-04-12T10:30:00Z",
        ),
        cd_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AUDITION_NOT_COMPLETED.value, 409)


# ─── Idempotency: double-cancel a PENDING-origin booking ─────────────────────
def test_double_cancel_booking_rejected(api):
    """PRD §3.7: "A `PENDING` booking cancels freely to the terminal `CANCELLED`
    state."
    PRD §2.9: "the target resource's own state is checked for transition
    legality, failing with `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/double_cancel_booking_invalid_state
    """
    base = setup_pending_booking(union_status="SAG", media_type="STREAMING")
    booking_id = base["booking"]["id"]
    get_success_data(api.cancel_booking(booking_id, AGENT))
    resp = api.cancel_booking(booking_id, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ─── Precondition: archive talent with open booking ──────────────────────────
def test_archive_talent_with_confirmed_booking_rejected(api):
    """PRD §3.1: "an agent may archive the talent, moving them to the terminal
    `ARCHIVED` state — but only if the talent has no booking in `booking_status`
    `PENDING` or `CONFIRMED`; an open booking blocks the archive with
    `ERR_TALENT_HAS_OPEN_BOOKINGS`."

    Design: Corner/state_machines/archive_talent_with_open_booking_rejected
    """
    base = setup_confirmed_booking(union_status="SAG", media_type="STREAMING")
    resp = api.archive_talent(base["talent"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_TALENT_HAS_OPEN_BOOKINGS.value, 409)
