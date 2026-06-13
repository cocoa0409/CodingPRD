"""Booking-time constraints on reservation create and confirm: stay-length cap,
date overlap (half-open), maintenance-hold buffered window, the fixed guard
ordering, boundary precision on the cap, and the cross-entity site-status gate
on confirm and add-on.

Covers difficulty queue priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, and resource_temporal_overlap.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_guest_headers,
    make_operator_headers,
    create_reservation_payload,
    create_add_on_payload,
    ApiErrorId,
    setup_base_scenario,
    create_reservation,
    create_deposit_paid_reservation,
    create_cancelled_reservation,
    put_site_in_maintenance,
    current_site_version,
    get_reservation,
)

OP = make_operator_headers()


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / cancel_checked_out_state_beats_refund_fiscal
# ===========================================================================
def test_cancel_checked_out_reservation_fails_state_check(api):
    """PRD §3.5: "A guest (or the system, during a site retirement) may cancel a
    reservation that is `REQUESTED` or `CONFIRMED`, moving it to the terminal
    `CANCELLED` state"
    PRD §3.5: "Any of these transitions attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/cancel_checked_out_state_beats_refund_fiscal
    """
    from test_helpers import create_checked_in_reservation, set_clock, check_out_reservation
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_checked_in_reservation(
        site, guest, "2026-08-01", "2026-08-11", checkin_clock="2026-08-01T12:00:00Z")
    set_clock("2026-08-11T12:00:00Z")
    check_out_reservation(res)
    resp = api.cancel_reservation(res["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_reservation(res["id"])["reservation_status"] == "CHECKED_OUT"


def test_cancel_checked_out_leaves_reservation_unchanged(api):
    """PRD §3.5: "An operator later checks the guest out, moving a `CHECKED_IN`
    reservation to the terminal `CHECKED_OUT` state"
    PRD §3.5: "Any of these transitions attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/cancel_checked_out_state_beats_refund_fiscal
    """
    from test_helpers import create_checked_in_reservation, set_clock, check_out_reservation
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_checked_in_reservation(
        site, guest, "2026-08-01", "2026-08-11", checkin_clock="2026-08-01T12:00:00Z")
    set_clock("2026-08-11T12:00:00Z")
    final = check_out_reservation(res)
    paid_after_checkout = final["payment_status"]
    api.cancel_reservation(res["id"], make_guest_headers(guest["id"]))
    after = get_reservation(res["id"])
    # Fiscal refund computation never ran: payment_status unchanged from checkout.
    assert after["reservation_status"] == "CHECKED_OUT"
    assert after["payment_status"] == paid_after_checkout


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / create_overlap_temporal_vs_max_stay_constraint
# ===========================================================================
def test_max_stay_check_precedes_date_overlap_check(api):
    """PRD §3.5: "Then the stay-length cap is enforced: `nights` must not exceed
    the site's `max_length_of_stay_nights`, where a stay whose `nights` exactly
    equals the cap is allowed and one night longer is rejected with
    `ERR_MAX_STAY_EXCEEDED` (422). ... Finally the date-overlap check runs"

    Design: Difficulty/priority_pair_validation_conflict/create_overlap_temporal_vs_max_stay_constraint
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 7})
    # R1 occupies 08-01..08-05.
    create_reservation(site, guest, "2026-08-01", "2026-08-05")
    v = current_site_version(site["id"])
    # Trigger: 8 nights (> cap 7) AND overlaps R1. Max-stay fires first.
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-03", "2026-08-11", v),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_MAX_STAY_EXCEEDED.value)


def test_overlap_within_cap_returns_date_overlap(api):
    """PRD §3.5: "the date-overlap check runs: the requested half-open interval
    must not overlap that of any other reservation on the site whose
    `reservation_status` is `REQUESTED`, `CONFIRMED`, or `CHECKED_IN`. ... a
    genuine overlap is rejected with `ERR_DATE_OVERLAP` (409)."

    Design: Difficulty/priority_pair_validation_conflict/create_overlap_temporal_vs_max_stay_constraint
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 7})
    create_reservation(site, guest, "2026-08-01", "2026-08-05")
    v = current_site_version(site["id"])
    # 4 nights (<= cap 7) but overlaps R1: only the date-overlap check can fire.
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-03", "2026-08-07", v),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_DATE_OVERLAP.value)


# ===========================================================================
# Difficulty: boundary_precision_check / max_stay_boundary_equal_allowed_plus_one_rejected
# ===========================================================================
def test_max_stay_at_cap_allowed(api):
    """PRD §3.5: "`nights` must not exceed the site's `max_length_of_stay_nights`,
    where a stay whose `nights` exactly equals the cap is allowed and one night
    longer is rejected with `ERR_MAX_STAY_EXCEEDED` (422)."

    Design: Difficulty/boundary_precision_check/max_stay_boundary_equal_allowed_plus_one_rejected
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 7})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-08")  # exactly 7 nights
    assert res["nights"] == 7
    assert res["reservation_status"] == "REQUESTED"


def test_max_stay_one_over_cap_rejected(api):
    """PRD §3.5: "a stay whose `nights` exactly equals the cap is allowed and one
    night longer is rejected with `ERR_MAX_STAY_EXCEEDED` (422)."

    Design: Difficulty/boundary_precision_check/max_stay_boundary_equal_allowed_plus_one_rejected
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 7})
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-01", "2026-08-09", site["version"]),  # 8 nights
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_MAX_STAY_EXCEEDED.value)


# ===========================================================================
# Difficulty: boundary_precision_check / cancellation_window_boundary_exactly_half_refund_day
# (The 50%-tier boundary; full-tier and zero-tier live in test_05.)
# ===========================================================================
def test_cancel_exactly_at_half_refund_boundary_yields_half_refund(api):
    """PRD §3.8: "else if `days_before` is at least `half_refund_min_days`, the
    refund is `amount_paid_cents` multiplied by 0.50, rounded half up to whole
    cents (50 percent)"
    PRD §3.8: "The day thresholds use an at-or-above comparison on `days_before`."

    Design: Difficulty/boundary_precision_check/cancellation_window_boundary_exactly_half_refund_day
    """
    from test_helpers import create_confirmed_reservation, validate_paginated
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-25T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    # check_in 2026-08-01 is exactly 7 days after the clock (half_refund_min_days=7).
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    cancelled = validate_success(
        api.cancel_reservation(confirmed["id"], make_guest_headers(guest["id"])),
        expected_status=200)
    assert cancelled["reservation_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    payments, _ = validate_paginated(api.list_payments(confirmed["id"], OP))
    refunds = [p for p in payments if p["type"] == "REFUND"]
    assert len(refunds) == 1
    # 50% of deposit 14580 = round_half_up(7290.0) = 7290.
    assert refunds[0]["amount_cents"] == 7290


def test_cancel_one_day_below_half_refund_boundary_yields_zero(api):
    """PRD §3.8: "a cancellation closer in than `half_refund_min_days` earns
    nothing."
    PRD §3.8: "otherwise the refund is 0."

    Design: Difficulty/boundary_precision_check/cancellation_window_boundary_exactly_half_refund_day
    """
    from test_helpers import create_confirmed_reservation, validate_paginated
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-26T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    # check_in 2026-08-01 is 6 days after the clock — below half_refund_min_days=7.
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    cancelled = validate_success(
        api.cancel_reservation(confirmed["id"], make_guest_headers(guest["id"])),
        expected_status=200)
    assert cancelled["reservation_status"] == "CANCELLED"
    payments, _ = validate_paginated(api.list_payments(confirmed["id"], OP))
    refunds = [p for p in payments if p["type"] == "REFUND"]
    assert len(refunds) == 0


# ===========================================================================
# Difficulty: cross_entity_state_dependency / confirm_requires_site_active
# ===========================================================================
def test_confirm_blocked_when_site_in_maintenance(api):
    """PRD §3.5: "Confirmation is permitted only when the reservation is
    `REQUESTED`, when its deposit has already been collected (its `payment_status`
    is `DEPOSIT_PAID` or `PAID_IN_FULL`), and when the host site is `ACTIVE`"
    PRD §3.5: "site availability is checked: the site must be neither `RETIRED`
    nor `MAINTENANCE`, or the request is rejected with `ERR_SITE_UNAVAILABLE`
    (409)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_site_active
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_deposit_paid_reservation(site, guest, "2026-08-01", "2026-08-11")
    put_site_in_maintenance(site["id"])
    resp = api.confirm_reservation(res["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_SITE_UNAVAILABLE.value)
    assert get_reservation(res["id"])["reservation_status"] == "REQUESTED"


def test_confirm_succeeds_when_site_active(api):
    """PRD §3.5: "A guest confirms a `REQUESTED` reservation, moving it to
    `CONFIRMED`. Confirmation is permitted only when the reservation is
    `REQUESTED`, when its deposit has already been collected ... and when the
    host site is `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_site_active
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_deposit_paid_reservation(site, guest, "2026-08-01", "2026-08-11")
    confirmed = validate_success(
        api.confirm_reservation(res["id"], make_guest_headers(guest["id"])),
        expected_status=200)
    assert confirmed["reservation_status"] == "CONFIRMED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / addon_add_requires_reservation_not_terminal
# ===========================================================================
def test_add_on_to_cancelled_reservation_rejected(api):
    """PRD §3.9: "Add-ons may only be added or removed while the parent
    reservation is non-terminal — neither `CHECKED_OUT` nor `CANCELLED`; an
    attempt to add to or remove from a terminal reservation is rejected with
    `ERR_ADDON_LOCKED` (409)."

    Design: Difficulty/cross_entity_state_dependency/addon_add_requires_reservation_not_terminal
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    cancelled = create_cancelled_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.create_add_on(
        cancelled["id"], create_add_on_payload("FIREWOOD", 1500),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_ADDON_LOCKED.value)


def test_add_on_to_active_reservation_allowed(api):
    """PRD §3.9: "A guest enriches their own reservation with an **Add-On** ...
    Each add-on records its `reservation_id`, begins with `status` `ACTIVE` and
    `version` 1"

    Design: Difficulty/cross_entity_state_dependency/addon_add_requires_reservation_not_terminal
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    addon = validate_success(
        api.create_add_on(res["id"], create_add_on_payload("FIREWOOD", 1500),
                          make_guest_headers(guest["id"])),
        expected_status=201)
    assert addon["status"] == "ACTIVE"


# ===========================================================================
# Difficulty: resource_temporal_overlap / reservation_half_open_overlap_on_site
# ===========================================================================
def test_interior_overlap_rejected(api):
    """PRD §3.5: "the date-overlap check runs: the requested half-open interval
    must not overlap that of any other reservation on the site whose
    `reservation_status` is `REQUESTED`, `CONFIRMED`, or `CHECKED_IN`. ... a
    genuine overlap is rejected with `ERR_DATE_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/reservation_half_open_overlap_on_site
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30, "turnover_buffer_days": 0})
    create_reservation(site, guest, "2026-08-01", "2026-08-05")  # R1
    v = current_site_version(site["id"])
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-04", "2026-08-09", v),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_DATE_OVERLAP.value)


def test_back_to_back_booking_allowed(api):
    """PRD §3.5: "Because the interval is half-open, a back-to-back booking where
    one reservation's `check_out_date` equals the next reservation's
    `check_in_date` is allowed"

    Design: Difficulty/resource_temporal_overlap/reservation_half_open_overlap_on_site
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30, "turnover_buffer_days": 0})
    create_reservation(site, guest, "2026-08-01", "2026-08-05")  # R1
    v = current_site_version(site["id"])
    # R3 starts exactly when R1 ends: adjacency, not overlap.
    res = create_reservation(site, guest, "2026-08-05", "2026-08-09", expected_site_version=v)
    assert res["reservation_status"] == "REQUESTED"


# ===========================================================================
# Difficulty: resource_temporal_overlap /
#   maintenance_hold_buffered_window_blocks_adjacent_reservation
# ===========================================================================
def test_maintenance_buffered_window_blocks_adjacent_reservation(api):
    """PRD §3.5: "the maintenance-buffer check runs: the requested half-open
    interval from `check_in_date` up to `check_out_date` must not overlap the
    buffered window of any `ACTIVE` maintenance hold on the site, where the
    buffered window runs as a closed interval from the hold's `start_date` minus
    `turnover_buffer_days` through the hold's `end_date` plus
    `turnover_buffer_days`; an overlap is rejected with `ERR_MAINTENANCE_CONFLICT`
    (409)."

    Design: Difficulty/resource_temporal_overlap/maintenance_hold_buffered_window_blocks_adjacent_reservation
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30, "turnover_buffer_days": 1})
    validate_success(
        api.create_maintenance_hold(
            site["id"],
            {"start_date": "2026-08-10", "end_date": "2026-08-12",
             "reason": "deck repair", "expected_site_version": site["version"]},
            OP),
        expected_status=201)
    v = current_site_version(site["id"])
    # Hold 08-10..08-12 with buffer 1 -> buffered window [08-09, 08-13].
    # Reservation 08-08..08-10 (nights 08-08, 08-09) touches 08-09 -> conflict.
    resp = api.create_reservation(
        site["id"],
        create_reservation_payload(guest["id"], "2026-08-08", "2026-08-10", v),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_CONFLICT.value)


def test_reservation_clear_of_buffered_window_allowed(api):
    """PRD §3.5: "the requested half-open interval from `check_in_date` up to
    `check_out_date` must not overlap the buffered window of any `ACTIVE`
    maintenance hold on the site, where the buffered window runs as a closed
    interval from the hold's `start_date` minus `turnover_buffer_days` through
    the hold's `end_date` plus `turnover_buffer_days`"

    Design: Difficulty/resource_temporal_overlap/maintenance_hold_buffered_window_blocks_adjacent_reservation
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30, "turnover_buffer_days": 1})
    validate_success(
        api.create_maintenance_hold(
            site["id"],
            {"start_date": "2026-08-10", "end_date": "2026-08-12",
             "reason": "deck repair", "expected_site_version": site["version"]},
            OP),
        expected_status=201)
    v = current_site_version(site["id"])
    # Buffered window [08-09, 08-13]; reservation 08-05..08-09 (nights up to 08-08)
    # ends exactly at the buffer edge without touching it -> allowed.
    res = create_reservation(site, guest, "2026-08-05", "2026-08-09", expected_site_version=v)
    assert res["reservation_status"] == "REQUESTED"
