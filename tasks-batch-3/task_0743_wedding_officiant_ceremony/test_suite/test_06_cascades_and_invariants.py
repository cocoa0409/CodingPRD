"""Cascading reconciliation and conserved-quantity invariants: the suspension
cascade (booking -> script -> rehearsal), the cancellation cascade (booking ->
hold -> officiant slot), and the hold-slot count invariant (PRD Sections 2.8, 3.3).
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
    make_coordinator_headers, make_couple_headers,
)

COORD = make_coordinator_headers()


def _confirmed_with_approved_script_and_confirmed_rehearsal(api):
    ctx = fx.setup_confirmed_booking(api)
    script = fx.create_approved_script(api, ctx.booking, ctx.couple, ctx.officiant)
    rehearsal = fx.create_rehearsal(
        api, ctx.booking, ctx.couple, ctx.venue,
        rehearsal_start="2026-08-31T18:00:00Z", rehearsal_end="2026-08-31T19:00:00Z",
    )
    fx.confirm_rehearsal(api, rehearsal, ctx.officiant)
    return ctx, script, rehearsal


def test_suspension_moves_confirmed_booking_to_backup_pending(api):
    """PRD §2.8: "For each booking in which the suspended officiant is the primary
    assignee (`officiant_id`) and whose status is `CONFIRMED` or `BACKUP_CONFIRMED`,
    that booking moves to `BACKUP_PENDING`".

    Design: Difficulty/transitive_cascade/suspend_cascade_officiant_booking_script_rehearsal_depth3
    """
    ctx, script, rehearsal = _confirmed_with_approved_script_and_confirmed_rehearsal(api)
    fx.suspend_officiant(api, ctx.officiant["id"])
    booking = fx.get_success_data(api.get_booking(ctx.booking["id"], COORD))
    assert booking["status"] == "BACKUP_PENDING"


def test_suspension_reverts_approved_script_and_confirmed_rehearsal(api):
    """PRD §2.8: "if the booking's ceremony script is `APPROVED`, it reverts to
    `CHANGES_REQUESTED` (the incoming officiant must re-approve it); and that script
    reversion in turn propagates: if the booking's rehearsal is `CONFIRMED`, it
    reverts to `SCHEDULED`, unlocking the timeline pending the new officiant's
    re-approval."

    Design: Difficulty/transitive_cascade/suspend_cascade_officiant_booking_script_rehearsal_depth3
    """
    ctx, script, rehearsal = _confirmed_with_approved_script_and_confirmed_rehearsal(api)
    fx.suspend_officiant(api, ctx.officiant["id"])
    script_after = fx.get_success_data(api.get_ceremony_script(script["id"], COORD))
    rehearsal_after = fx.get_success_data(api.get_rehearsal(rehearsal["id"], COORD))
    assert script_after["status"] == "CHANGES_REQUESTED"
    assert rehearsal_after["status"] == "SCHEDULED"


def test_cancel_confirmed_booking_releases_its_date_hold(api):
    """PRD §2.8: "When a booking is cancelled, its active date hold — one that is
    still `HELD` or `CONFIRMED` — is moved to `RELEASED`."

    Design: Difficulty/transitive_cascade/cancel_cascade_booking_hold_officiant_depth2
    """
    ctx = fx.setup_confirmed_booking(api)
    fx.cancel_booking(api, ctx.booking, ctx.couple)
    booking = fx.get_success_data(api.get_booking(ctx.booking["id"], COORD))
    hold = fx.get_success_data(api.get_date_hold(ctx.hold["id"], COORD))
    assert booking["status"] == "CANCELLED"
    assert hold["status"] == "RELEASED"


def test_cancel_confirmed_booking_decrements_officiant_hold_count(api):
    """PRD §2.8: "Releasing the hold decrements the officiant's `active_hold_count`
    by one and increments the officiant's `version`."

    Design: Difficulty/transitive_cascade/cancel_cascade_booking_hold_officiant_depth2
    """
    ctx = fx.setup_confirmed_booking(api)
    fx.cancel_booking(api, ctx.booking, ctx.couple)
    officiant = fx.get_officiant(api, ctx.officiant["id"])
    assert officiant["active_hold_count"] == 0


def test_release_on_cancel_restores_hold_slot_count(api):
    """PRD §3.3: "placing a hold adds one, and releasing or expiring a hold
    subtracts one, so placing and then releasing a hold returns the count to its
    prior value."

    Design: Difficulty/compensating_invariant/hold_slot_count_conserved_on_release
    """
    ctx = fx.setup_held_booking(api)
    fx.cancel_booking(api, ctx.booking, ctx.couple)  # HOLD -> CANCELLED releases the hold
    hold = fx.get_success_data(api.get_date_hold(ctx.hold["id"], COORD))
    officiant = fx.get_officiant(api, ctx.officiant["id"])
    assert hold["status"] == "RELEASED"
    assert officiant["active_hold_count"] == 0


def test_place_then_release_returns_count_to_prior_value(api):
    """PRD §3.3: "The officiant's `active_hold_count` is always kept equal to the
    number of that officiant's date holds in `HELD` or `CONFIRMED`; placing a hold
    adds one, and releasing or expiring a hold subtracts one".

    Design: Difficulty/compensating_invariant/hold_slot_count_conserved_on_release
    """
    ctx = fx.setup_held_booking(api)
    after_place = fx.get_officiant(api, ctx.officiant["id"])
    assert after_place["active_hold_count"] == 1
    fx.cancel_booking(api, ctx.booking, ctx.couple)
    after_release = fx.get_officiant(api, ctx.officiant["id"])
    assert after_release["active_hold_count"] == 0
