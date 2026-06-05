"""Non-linear state-machine shapes: the Gallery cyclic proofing/revision loop and
the Booking CONFIRMED branch (SHOT vs CANCELLED), plus baseline valid/invalid
transitions on the workflow track.

Queue A (difficulty) instances exercised here:
  non_linear_state_machine / gallery_cyclic_proofing_revision_loop
  non_linear_state_machine / booking_branching_confirmed_to_shot_or_cancelled
Queue B (corner) instances exercised here:
  state_machines / cancel_already_cancelled_booking_returns_invalid_state
  state_machines / confirm_draft_booking_initial_state_and_computed_total
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client, TEST_USERS,
    ApiErrorId, make_client_headers, make_photographer_headers,
    # fixtures
    setup_draft_booking, setup_confirmed_booking, setup_deposit_paid_booking,
    setup_proofing_gallery, create_signed_contract, create_schedule, set_clock,
    # factories
    upload_gallery_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# non_linear_state_machine / gallery_cyclic_proofing_revision_loop
# ===========================================================================
def test_gallery_revision_loop_returns_to_proofing_bumps_round(api):
    """PRD §3.7: "The photographer answers a revision by uploading again, which moves the
    gallery REVISION_REQUESTED -> PROOFING, sets the new delivered_image_count, and
    increments revision_round by one, closing one turn of the loop."

    PROOFING gallery -> request-revision (REVISION_REQUESTED) -> upload (back to PROOFING,
    revision_round 0 -> 1).

    Design: Difficulty/non_linear_state_machine/gallery_cyclic_proofing_revision_loop
    """
    ctx = setup_proofing_gallery(delivered_image_count=30, included_edited_images=30)
    gallery, client, photographer = ctx["gallery"], ctx["client"], ctx["photographer"]
    assert gallery["status"] == "PROOFING"
    assert gallery["revision_round"] == 0
    requested = validate_success(
        api.request_gallery_revision(gallery["id"], make_client_headers(client["id"]))
    )
    assert requested["status"] == "REVISION_REQUESTED"
    re_uploaded = validate_success(
        api.upload_gallery(
            gallery["id"], upload_gallery_payload(32),
            make_photographer_headers(photographer["id"]),
        )
    )
    assert re_uploaded["status"] == "PROOFING"
    assert re_uploaded["revision_round"] == 1


def test_gallery_two_revision_loops_bump_round_twice(api):
    """PRD §3.7: "The photographer answers a revision by uploading again, which moves the
    gallery REVISION_REQUESTED -> PROOFING, sets the new delivered_image_count, and
    increments revision_round by one, closing one turn of the loop."

    Two full PROOFING -> REVISION_REQUESTED -> PROOFING cycles drive revision_round to 2.

    Design: Difficulty/non_linear_state_machine/gallery_cyclic_proofing_revision_loop
    """
    ctx = setup_proofing_gallery(delivered_image_count=30, included_edited_images=30)
    gallery, client, photographer = ctx["gallery"], ctx["client"], ctx["photographer"]
    client_h = make_client_headers(client["id"])
    photog_h = make_photographer_headers(photographer["id"])
    validate_success(api.request_gallery_revision(gallery["id"], client_h))
    first = validate_success(api.upload_gallery(gallery["id"], upload_gallery_payload(31), photog_h))
    assert first["revision_round"] == 1
    validate_success(api.request_gallery_revision(gallery["id"], client_h))
    second = validate_success(api.upload_gallery(gallery["id"], upload_gallery_payload(33), photog_h))
    assert second["status"] == "PROOFING"
    assert second["revision_round"] == 2


# ===========================================================================
# non_linear_state_machine / booking_branching_confirmed_to_shot_or_cancelled
# ===========================================================================
def test_confirmed_booking_branches_to_shot_on_complete(api):
    """PRD §3.7: "On success the schedule moves to COMPLETED, the booking's
    workflow_status advances CONFIRMED -> SHOT, and the relevant versions bump."

    A CONFIRMED + DEPOSIT_PAID booking whose shoot is completed branches to SHOT.

    Design: Difficulty/non_linear_state_machine/booking_branching_confirmed_to_shot_or_cancelled
    """
    ctx = setup_deposit_paid_booking(
        start_utc="2026-07-05T10:00:00Z", end_utc="2026-07-05T12:00:00Z",
    )
    booking, schedule, photographer = ctx["booking"], ctx["schedule"], ctx["photographer"]
    set_clock("2026-07-05T12:30:00Z")
    completed = validate_success(
        api.complete_shoot_schedule(schedule["id"], make_photographer_headers(photographer["id"]))
    )
    assert completed["status"] == "COMPLETED"
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["workflow_status"] == "SHOT"


def test_confirmed_booking_branches_to_cancelled_on_cancel(api):
    """PRD §3.8: "Cancelling a CONFIRMED booking moves it CONFIRMED -> CANCELLED and
    triggers a deeper cascade."

    The alternate branch from CONFIRMED: cancel takes the booking to CANCELLED (a
    divergent side-effect path from the SHOT branch).

    Design: Difficulty/non_linear_state_machine/booking_branching_confirmed_to_shot_or_cancelled
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-05T10:00:00Z", end_utc="2026-07-05T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    set_clock("2026-06-20T00:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert cancelled["workflow_status"] == "CANCELLED"


# ===========================================================================
# state_machines / cancel_already_cancelled_booking_returns_invalid_state
# ===========================================================================
def test_cancel_already_cancelled_booking_rejected(api):
    """PRD §3.8: "CLOSED and CANCELLED are the two terminal resting points of the
    workflow track." PRD §3.4: "The booking must currently be in DRAFT; otherwise the
    transition is illegal and yields ERR_INVALID_STATE."

    A DRAFT booking cancelled, then cancelled again -> ERR_INVALID_STATE (CANCELLED is
    terminal; no transition is legal from it).

    Design: Corner/state_machines/cancel_already_cancelled_booking_returns_invalid_state
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    client_h = make_client_headers(client["id"])
    validate_success(api.cancel_booking(booking["id"], client_h))
    validate_error(
        api.cancel_booking(booking["id"], client_h),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


# ===========================================================================
# state_machines / confirm_draft_booking_initial_state_and_computed_total
# ===========================================================================
def test_confirm_draft_booking_computes_total_and_deposit(api):
    """PRD §3.4: "Confirmation by the owning Client (or a StudioAdmin) advances the
    booking DRAFT -> CONFIRMED and is the moment the financials crystallize ... When all
    hold, confirmation recomputes total_fee_cents, pins deposit_due_cents, recomputes
    balance_due_cents, and bumps the booking's version."

    PORTRAIT BASIC, no overage: total 100000, deposit 0.30*100000 = 30000.

    Design: Corner/state_machines/confirm_draft_booking_initial_state_and_computed_total
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    client_h = make_client_headers(client["id"])
    create_signed_contract(booking["id"], client["id"], includes_model_release=False)
    create_schedule(booking["id"], "2026-07-12T10:00:00Z", "2026-07-12T12:00:00Z")
    confirmed = validate_success(api.confirm_booking(booking["id"], client_h))
    assert confirmed["workflow_status"] == "CONFIRMED"
    assert confirmed["total_fee_cents"] == 100000
    assert confirmed["deposit_due_cents"] == 30000
