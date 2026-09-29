"""Confirmation side effects, the deposit dimension and the pinned charge."""

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import ADJUDICATOR, PLATFORM_ADMIN


def test_confirming_a_deposit_booking_places_the_hold_on_the_guest(api):
    """The hold is a side effect of confirmation, not a separate request.

    The reservation's deposit dimension leaves NONE for HELD, and the same amount
    appears on the guest's standing exposure, which is the aggregate the platform
    later has to unwind.

    PRD: "A successful confirmation advances `stay_state` from `REQUESTED` to `CONFIRMED` and increases the reservation's `version` by 1."
    PRD: "On a listing whose `protection_product` is `DEPOSIT`, it additionally places the security hold: `deposit_state` moves from `NONE` to `HELD`, the guest's `deposit_held_cents` rises by the reservation's `deposit_hold_cents`, and the guest's `version` increases by 1."

    Design: Corner/state_machines/reservation_confirm_side_effect_places_deposit_hold
    """
    cast = fixtures.setup_deposit_listing(api)
    booked = fixtures.book_stay(api, cast, check_in="2026-08-10", check_out="2026-08-12")
    assertions.assert_fields(
        booked,
        "reservation",
        stay_state="REQUESTED",
        deposit_state="NONE",
        deposit_hold_cents=50000,
        screening_state="CLEARED",
        screening_reason_code="LOW_RISK_AUTO_CLEAR",
    )
    guest_before = fixtures.read_guest(api, cast)
    assertions.assert_fields(guest_before, "guest", deposit_held_cents=0)

    confirmed = fixtures.confirm_stay(api, cast, booked["id"])
    assertions.assert_fields(
        confirmed,
        "reservation",
        stay_state="CONFIRMED",
        deposit_state="HELD",
        deposit_hold_cents=50000,
        deposit_refunded_cents=0,
        deposit_applied_cents=0,
    )
    assertions.assert_version_advanced_by(booked, confirmed, 1, "reservation")

    guest_after = fixtures.read_guest(api, cast)
    assertions.assert_fields(guest_after, "guest", deposit_held_cents=50000)
    assertions.assert_version_advanced_by(guest_before, guest_after, 1, "guest")


def test_confirming_a_waiver_booking_touches_neither_hold_nor_guest(api):
    """On a waiver listing the deposit dimension never leaves NONE.

    The fee-bearing product replaces the refundable hold entirely: the guest's
    standing exposure stays at zero and the guest row is not even re-versioned by
    the confirmation, while the waiver fee itself was priced at booking.

    PRD: "On a `WAIVER` listing nothing happens to the deposit dimension at all — `deposit_state` remains `NONE` for the whole life of that booking, and the guest's `version` is untouched by the confirmation."
    PRD: "On a `WAIVER` listing, `deposit_hold_cents` is 0 and `waiver_fee_cents` is the listing's `waiver_nightly_fee_cents` multiplied by `nights` and again by a risk multiplier read from the pinned `risk_tier_at_booking` — 1.00 at `LOW`, 1.25 at `ELEVATED`, 1.60 at `HIGH` and 2.00 at `CRITICAL` — with the product rounded half up to a whole cent."

    Design: Corner/state_machines/waiver_listing_confirm_places_no_deposit_hold
    """
    cast = fixtures.setup_waiver_listing(api)
    booked = fixtures.book_stay(api, cast, check_in="2026-08-10", check_out="2026-08-13")
    assertions.assert_charge(
        booked,
        nights=3,
        accommodation_cents=90000,
        waiver_fee_cents=11250,
        pre_fee_subtotal_cents=101250,
        trust_fee_pct=0.025,
        trust_fee_cents=2531,
        total_charged_cents=103781,
        deposit_hold_cents=0,
    )
    guest_before = fixtures.read_guest(api, cast)

    confirmed = fixtures.confirm_stay(api, cast, booked["id"])
    assertions.assert_fields(
        confirmed,
        "reservation",
        stay_state="CONFIRMED",
        deposit_state="NONE",
        deposit_hold_cents=0,
        deposit_refunded_cents=0,
    )

    guest_after = fixtures.read_guest(api, cast)
    assertions.assert_fields(guest_after, "guest", deposit_held_cents=0)
    assertions.assert_version_unchanged(guest_before, guest_after, "guest")


def test_cancelling_an_already_cancelled_stay_is_refused_as_terminal(api):
    """CANCELLED is the end of the stay dimension, so the edge cannot be re-walked.

    The distinction matters: a stay that has run out of transitions altogether is
    refused as terminal rather than as an invalid state.

    PRD: "Because `COMPLETED` and `CANCELLED` are both terminal for the stay dimension, cancelling an already-completed or already-cancelled booking is refused with `ERR_ALREADY_TERMINAL`, and cancelling a stay already `IN_STAY` is refused with `ERR_INVALID_STATE`."
    PRD: "Cancelling from `REQUESTED` moves `stay_state` to `CANCELLED`, sets `cancel_reason_code` to `GUEST_WITHDREW` or `HOST_WITHDREW` according to the acting role, and leaves the deposit dimension untouched — `deposit_state` is still `NONE` because no hold had been placed."

    Design: Corner/state_machines/reservation_cancel_from_cancelled_returns_already_terminal
    """
    cast = fixtures.setup_waiver_listing(api)
    booked = fixtures.book_stay(api, cast, check_in="2026-08-10", check_out="2026-08-13")

    cancelled = validate_success(
        api.cancel_reservation(booked["id"], cast.guest_headers)
    )
    assertions.assert_fields(
        cancelled,
        "reservation",
        stay_state="CANCELLED",
        cancel_reason_code="GUEST_WITHDREW",
        deposit_state="NONE",
    )

    validate_error(
        api.cancel_reservation(booked["id"], cast.guest_headers),
        ApiErrorId.ERR_ALREADY_TERMINAL,
        expected_status=409,
    )

    unchanged = validate_success(
        api.get_reservation(booked["id"], cast.guest_headers)
    )
    assertions.assert_fields(
        unchanged, "reservation", stay_state="CANCELLED", cancel_reason_code="GUEST_WITHDREW"
    )
    assertions.assert_version_unchanged(cancelled, unchanged, "reservation")


def test_one_cancel_moves_two_dimensions_and_leaves_the_third_alone(api):
    """Three state dimensions run in parallel on a reservation, not in series.

    A single cancel request has to move the stay dimension to CANCELLED and the
    deposit dimension from HELD to RELEASED, while the screening dimension stays
    exactly where its own terminal verdict left it. The pinned charge and risk
    snapshot are not recomputed either.

    PRD: "Cancelling from `CONFIRMED` moves `stay_state` to `CANCELLED` and sets `cancel_reason_code` the same way, but it must also unwind the hold: when `deposit_state` reads `HELD`, it moves to `RELEASED`, `deposit_refunded_cents` is set to the full `deposit_hold_cents`, the guest's `deposit_held_cents` falls by that same `deposit_hold_cents`, and the guest's `version` increases by 1."
    PRD: "This is a compensating action in the strict sense — the guest's `deposit_held_cents` returns to exactly the value it had before the confirmation."
    PRD: "Once the calendar is clear, the charge is computed exactly once and never revisited; a later repricing of the listing has no effect on a booking already made."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_dimensions_move_independently_on_cancel
    """
    cast = fixtures.setup_deposit_listing(api)
    booked = fixtures.book_stay(api, cast, check_in="2026-08-10", check_out="2026-08-12")
    confirmed = fixtures.confirm_stay(api, cast, booked["id"])
    assertions.assert_fields(confirmed, "reservation", deposit_state="HELD")
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", deposit_held_cents=50000
    )

    cancelled = validate_success(
        api.cancel_reservation(booked["id"], cast.guest_headers)
    )

    assertions.assert_fields(
        cancelled,
        "reservation",
        stay_state="CANCELLED",
        cancel_reason_code="GUEST_WITHDREW",
        deposit_state="RELEASED",
        deposit_refunded_cents=50000,
        deposit_applied_cents=0,
        screening_state="CLEARED",
        screening_reason_code="LOW_RISK_AUTO_CLEAR",
        nights=2,
        total_charged_cents=41400,
    )
    assertions.assert_booking_snapshot(cancelled, 35, "ELEVATED")

    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", deposit_held_cents=0
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", open_reservation_count=0
    )


def test_the_released_hold_is_conserved_exactly_across_the_cancel(api):
    """The deposit dimension returns the guest to its pre-confirmation exposure.

    Read as a conserved quantity: the refunded amount equals the full hold, the
    applied amount is still zero, and the guest's standing exposure lands back on
    the number it held before the confirmation rather than merely near it. The stay
    dimension is meanwhile terminal, so no later request can move the money again.

    PRD: "This is a compensating action in the strict sense — the guest's `deposit_held_cents` returns to exactly the value it had before the confirmation."
    PRD: "It moves to `RELEASED` when the booking is cancelled, or when the sweep finds the claim window closed with no live claim standing against the stay; either way `deposit_refunded_cents` becomes the full `deposit_hold_cents` and the guest's `deposit_held_cents` falls by that amount."
    PRD: "Because `COMPLETED` and `CANCELLED` are both terminal for the stay dimension, cancelling an already-completed or already-cancelled booking is refused with `ERR_ALREADY_TERMINAL`, and cancelling a stay already `IN_STAY` is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_dimensions_move_independently_on_cancel
    """
    cast = fixtures.setup_deposit_listing(api)
    exposure_before = fixtures.read_guest(api, cast)["deposit_held_cents"]

    booked = fixtures.book_stay(api, cast, check_in="2026-08-10", check_out="2026-08-12")
    fixtures.confirm_stay(api, cast, booked["id"])
    held = fixtures.read_guest(api, cast)
    assert held["deposit_held_cents"] == exposure_before + 50000, (
        "the confirmation must raise the guest's exposure by the whole hold, got "
        "{0}".format(held["deposit_held_cents"])
    )

    cancelled = validate_success(
        api.cancel_reservation(booked["id"], cast.guest_headers)
    )
    assert (
        cancelled["deposit_refunded_cents"] == cancelled["deposit_hold_cents"]
    ), "the refund must be the entire hold, got {0} of {1}".format(
        cancelled["deposit_refunded_cents"], cancelled["deposit_hold_cents"]
    )

    released = fixtures.read_guest(api, cast)
    assert released["deposit_held_cents"] == exposure_before, (
        "the guest's exposure must return to exactly {0}, got {1}".format(
            exposure_before, released["deposit_held_cents"]
        )
    )

    validate_error(
        api.cancel_reservation(booked["id"], cast.guest_headers),
        ApiErrorId.ERR_ALREADY_TERMINAL,
        expected_status=409,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", deposit_held_cents=exposure_before
    )


def test_the_fee_tier_is_chosen_from_the_subtotal_even_when_the_total_crosses(api):
    """99000 picks the expensive rate, and adding the fee does not undo that choice.

    A verified guest prices at the LOW multiplier, so three nights come to 99000
    before the fee — just under the break. The 3.5% rate yields 3465 and a total of
    102465, which is above the break; re-selecting 2.5% at that point would give
    2562 and a total of 101562, and that number must not appear.

    PRD: "`pre_fee_subtotal_cents` is `accommodation_cents` plus `waiver_fee_cents`, and it is the **only** input to the trust-and-safety fee tier selection."
    PRD: "The tier selection is pinned to the pre-fee subtotal and is never re-selected from the total, even when adding the fee pushes the total across the break."
    PRD: "Since 99000 is below the break, `trust_fee_pct` is 0.035, `trust_fee_cents` is 3465, and `total_charged_cents` is 102465 — above the break, but re-selecting 0.025 at that point would give 2562 and a total of 101562, which is wrong."

    Design: Difficulty/combinatorial_formula/trust_fee_tier_pinned_to_pre_fee_subtotal_not_to_total
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Dana Reyes", guest_email="dana@guest.test"
    )
    verified, _, _ = fixtures.verify_guest(api, cast.guest_id)
    assertions.assert_guest_risk(verified, 20, "LOW")

    reservation = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )

    assertions.assert_booking_snapshot(reservation, 20, "LOW")
    assertions.assert_charge(
        reservation,
        nights=3,
        accommodation_cents=90000,
        waiver_fee_cents=9000,
        pre_fee_subtotal_cents=99000,
        trust_fee_pct=0.035,
        trust_fee_cents=3465,
        total_charged_cents=102465,
        deposit_hold_cents=0,
    )
    assert reservation["total_charged_cents"] != 101562, (
        "101562 is the total produced by re-selecting the cheaper tier from the "
        "post-fee total, which the contract forbids"
    )
    assertions.assert_fields(
        reservation,
        "reservation",
        deposit_state="NONE",
        screening_state="CLEARED",
        screening_reason_code="LOW_RISK_AUTO_CLEAR",
    )


def test_the_breakdown_read_reproduces_the_pinned_tier_rather_than_reselecting_it(api):
    """The computed read derives the fee afresh and must land on the same rate.

    This is the same 99000 subtotal, but read back through the endpoint that
    recomputes the whole derivation independently of the stored row. Because the
    total it reports sits above the break while the rate it reports is the
    below-break rate, the read cannot have chosen its tier from the total.

    PRD: "A computed read exposes the whole pricing derivation independently of the stored row, returning `nights`, `accommodation_cents`, `waiver_fee_cents`, `pre_fee_subtotal_cents`, `trust_fee_pct`, `trust_fee_cents`, `total_charged_cents` and `deposit_hold_cents`."
    PRD: "The tier selection is pinned to the pre-fee subtotal and is never re-selected from the total, even when adding the fee pushes the total across the break."
    PRD: "When `pre_fee_subtotal_cents` is below 100000 cents — that is, below 1,000.00 in major units — `trust_fee_pct` is 0.035; at 100000 cents or above it is 0.025."

    Design: Difficulty/combinatorial_formula/trust_fee_tier_pinned_to_pre_fee_subtotal_not_to_total
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Dana Reyes", guest_email="dana@guest.test"
    )
    fixtures.verify_guest(api, cast.guest_id)
    reservation = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )

    breakdown = validate_success(
        api.get_charge_breakdown(reservation["id"], cast.host_headers)
    )
    assertions.assert_charge(
        breakdown,
        nights=3,
        accommodation_cents=90000,
        waiver_fee_cents=9000,
        pre_fee_subtotal_cents=99000,
        trust_fee_pct=0.035,
        trust_fee_cents=3465,
        total_charged_cents=102465,
        deposit_hold_cents=0,
        label="charge_breakdown",
    )
    assert breakdown["pre_fee_subtotal_cents"] < constants.TRUST_FEE_TIER_BREAK_CENTS, (
        "the scenario requires a subtotal below the fee break, got {0}".format(
            breakdown["pre_fee_subtotal_cents"]
        )
    )
    assert breakdown["total_charged_cents"] > constants.TRUST_FEE_TIER_BREAK_CENTS, (
        "the scenario requires a total above the fee break, got {0}".format(
            breakdown["total_charged_cents"]
        )
    )
    assertions.assert_charge_internally_consistent(breakdown)


def test_an_acknowledged_incident_moves_the_guest_but_not_the_booking_snapshot(api):
    """Two readings of the same arithmetic, one live and one frozen.

    The stay was booked while the guest read 20 in LOW. Acknowledging an incident
    adds nine points to the live score and rebands the guest to ELEVATED, and the
    reservation's snapshot must not follow: it is written once at creation and never
    recomputed for any reason.

    PRD: "The **booking snapshot** reading uses identical arithmetic but its result is frozen onto the reservation at creation as `risk_score_at_booking` and `risk_tier_at_booking`, is never recomputed for any reason, and fires no cascade."
    PRD: "Acknowledgement moves `incident_state` from `OPEN` to `ACKNOWLEDGED` and sets `substantiated` to true, and from there a four-link cascade unrolls."
    PRD: "The changed count re-runs the risk score, adding 9 points for the new substantiation, subject to the joint 40-point cap it shares with escalations."

    Design: Difficulty/dual_variant_calc/guest_risk_snapshot_frozen_while_live_score_rebands
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Dana Reyes", guest_email="dana@guest.test"
    )
    fixtures.verify_guest(api, cast.guest_id)
    reservation = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )
    assertions.assert_booking_snapshot(reservation, 20, "LOW")
    fixtures.confirm_stay(api, cast, reservation["id"])
    fixtures.check_in_stay(api, cast, reservation["id"], clock=constants.IN_STAY_CLOCK_UTC)
    incident = fixtures.file_incident(
        api,
        cast,
        reservation["id"],
        acknowledge=False,
        detected_at="2026-08-11T01:30:00Z",
        description="Cracked glass cooktop found during a mid-stay check.",
    )

    acknowledged = validate_success(api.acknowledge_incident(incident["id"], ADJUDICATOR))
    assertions.assert_fields(
        acknowledged, "incident", incident_state="ACKNOWLEDGED", substantiated=True
    )

    guest = validate_success(api.get_guest(cast.guest_id, PLATFORM_ADMIN))
    assertions.assert_fields(guest, "guest", substantiated_incident_count=1)
    assertions.assert_guest_risk(guest, 29, "ELEVATED")

    frozen = validate_success(api.get_reservation(reservation["id"], cast.host_headers))
    assertions.assert_booking_snapshot(frozen, 20, "LOW")


def test_the_frozen_snapshot_keeps_pricing_the_stay_at_the_low_multiplier(api):
    """The re-banded guest does not make the standing booking more expensive.

    The waiver fee on this stay was multiplied by 1.00 because the snapshot said
    LOW. After the guest rebands to ELEVATED, the stay must still read 9000 rather
    than the 11250 an ELEVATED booking would have cost, and the computed read — which
    derives the charge again from scratch — must agree.

    PRD: "The divergence shows up on unchanged data: a stay booked while the guest read 20 in `LOW` still reports `risk_score_at_booking` of 20 and `risk_tier_at_booking` of `LOW` after an acknowledged incident has pushed the guest's live `risk_score` to 29 in `ELEVATED`, and any waiver fee on that booking stays priced at the `LOW` multiplier."
    PRD: "The **live** reading is what `risk_score` and `risk_tier` on the guest row always report; it reflects the aggregates as they stand at the moment of the read, is recomputed on every cascade that touches one of the seven inputs, and it is the only mode that fires the critical-tier ban cascade."
    PRD: "A dedicated computed read exposes the live position term by term, so a change can be attributed to a specific cascade."

    Design: Difficulty/dual_variant_calc/guest_risk_snapshot_frozen_while_live_score_rebands
    """
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Dana Reyes", guest_email="dana@guest.test"
    )
    fixtures.verify_guest(api, cast.guest_id)
    reservation = fixtures.book_stay(
        api, cast, check_in="2026-08-10", check_out="2026-08-13"
    )
    fixtures.confirm_stay(api, cast, reservation["id"])
    fixtures.check_in_stay(api, cast, reservation["id"], clock=constants.IN_STAY_CLOCK_UTC)
    fixtures.file_incident(
        api,
        cast,
        reservation["id"],
        detected_at="2026-08-11T01:30:00Z",
        description="Cracked glass cooktop found during a mid-stay check.",
    )

    profile = validate_success(api.get_guest_risk_profile(cast.guest_id, ADJUDICATOR))
    assertions.assert_fields(
        profile,
        "risk_profile",
        risk_score=29,
        risk_tier="ELEVATED",
        substantiated_incident_count=1,
    )

    stored = validate_success(api.get_reservation(reservation["id"], cast.host_headers))
    assertions.assert_booking_snapshot(stored, 20, "LOW")
    assertions.assert_charge(
        stored,
        waiver_fee_cents=9000,
        pre_fee_subtotal_cents=99000,
        total_charged_cents=102465,
    )
    assert stored["waiver_fee_cents"] != 11250, (
        "11250 is the ELEVATED price for this stay; the pinned snapshot must keep "
        "it at the LOW multiplier"
    )

    breakdown = validate_success(
        api.get_charge_breakdown(reservation["id"], cast.host_headers)
    )
    assertions.assert_charge(
        breakdown,
        waiver_fee_cents=9000,
        pre_fee_subtotal_cents=99000,
        trust_fee_cents=3465,
        total_charged_cents=102465,
        label="charge_breakdown",
    )
