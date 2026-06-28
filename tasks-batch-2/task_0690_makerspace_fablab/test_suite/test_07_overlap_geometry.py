"""Machine reservation overlap geometry: cooldown-dilated intervals on the LASER
versus bare half-open adjacency on the cooldown-free 3D printer.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_member_machine_cert,
    create_held_reservation,
    make_member_headers,
)

MAKER_TIER = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
LASER_COOLDOWN_15 = {
    "machine_class": "LASER", "hourly_rate_cents": 4800, "setup_fee_cents": 500,
    "min_billing_minutes": 30, "cooldown_minutes": 15, "requires_certification": True,
}
PRINTER_COOLDOWN_0 = {
    "machine_class": "PRINTER_3D", "hourly_rate_cents": 1200, "setup_fee_cents": 0,
    "min_billing_minutes": 0, "cooldown_minutes": 0, "requires_certification": True,
}


# ===========================================================================
# resource_temporal_overlap / laser_cooldown_buffer_overlap_rejected
# ===========================================================================
def test_confirm_within_cooldown_buffer_rejected(api):
    """PRD §3.5: "when `cooldown_minutes` is positive, each existing window is dilated
    by that many minutes of mandatory post-session cooldown before the comparison, so
    a new booking must leave at least that buffer after any neighbor."
    PRD §3.6: "the window still does not overlap another non-terminal reservation on
    the machine, or else `ERR_RESERVATION_OVERLAP` (HTTP 409)."

    LASER cooldown 15: reservation A 10:00-11:00 dilates to [10:00,11:15); confirming
    B 11:10-12:00 (inside the buffer) is rejected.

    Design: Difficulty/resource_temporal_overlap/laser_cooldown_buffer_overlap_rejected
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_COOLDOWN_15,
        topup_cents=20000,
    )
    mh = make_member_headers(member["id"])
    # The cooldown buffer is one-sided (PRD §3.5: a new booking must leave the buffer
    # AFTER any neighbor). B 11:10-12:00 must be HELD first so it can later be confirmed
    # and rejected; creating A 10:00-11:00 afterward does not collide with B because B
    # starts after A's bare window ends, while confirming B later collides with A's
    # dilated window [10:00,11:15).
    res_b = create_held_reservation(
        member, machine, cert, "2026-04-30T11:10:00Z", "2026-04-30T12:00:00Z"
    )
    res_a = create_held_reservation(
        member, machine, cert, "2026-04-30T10:00:00Z", "2026-04-30T11:00:00Z"
    )
    v0 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_success(api.confirm_reservation(res_a["id"], v0, mh))
    v1 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(
        api.confirm_reservation(res_b["id"], v1, mh), ApiErrorId.ERR_RESERVATION_OVERLAP.value
    )


def test_cooldown_overlap_leaves_second_reservation_held(api):
    """PRD §3.5: "when `cooldown_minutes` is positive, each existing window is dilated
    by that many minutes of mandatory post-session cooldown before the comparison."
    PRD §3.5: "A new reservation begins `HELD` on its occupancy dimension."

    After the rejected confirm, reservation B remains HELD (unchanged).

    Design: Difficulty/resource_temporal_overlap/laser_cooldown_buffer_overlap_rejected
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_COOLDOWN_15,
        topup_cents=20000,
    )
    mh = make_member_headers(member["id"])
    # See test_confirm_within_cooldown_buffer_rejected: B is created first (HELD) so it
    # can be confirmed-and-rejected against A's dilated window. The rejected confirm
    # must leave B in HELD (no state change on a refused transition).
    res_b = create_held_reservation(
        member, machine, cert, "2026-04-30T11:10:00Z", "2026-04-30T12:00:00Z"
    )
    res_a = create_held_reservation(
        member, machine, cert, "2026-04-30T10:00:00Z", "2026-04-30T11:00:00Z"
    )
    v0 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_success(api.confirm_reservation(res_a["id"], v0, mh))
    v1 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(api.confirm_reservation(res_b["id"], v1, mh), ApiErrorId.ERR_RESERVATION_OVERLAP.value)
    b_after = validate_success(api.get_reservation(res_b["id"], mh))
    assert b_after["occupancy_status"] == "HELD", b_after["occupancy_status"]


# ===========================================================================
# resource_temporal_overlap / printer_bare_halfopen_adjacency_allowed
# ===========================================================================
def test_bare_halfopen_adjacency_both_confirm(api):
    """PRD §3.5: "when `cooldown_minutes` is 0, the windows are compared as bare
    half-open intervals (so a reservation ending exactly when another begins does not
    collide)."

    PRINTER_3D cooldown 0: A 10:00-11:00 and B 11:00-12:00 are exactly adjacent and
    both confirm — no collision.

    Design: Difficulty/resource_temporal_overlap/printer_bare_halfopen_adjacency_allowed
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="PRINTER_3D", tier_overrides=MAKER_TIER,
        machine_overrides=PRINTER_COOLDOWN_0, topup_cents=20000,
    )
    mh = make_member_headers(member["id"])
    res_p = create_held_reservation(
        member, machine, cert, "2026-04-30T10:00:00Z", "2026-04-30T11:00:00Z"
    )
    v0 = validate_success(api.get_member(member["id"], mh))["version"]
    confirmed_p = validate_success(api.confirm_reservation(res_p["id"], v0, mh))
    assert confirmed_p["occupancy_status"] == "CONFIRMED"
    res_q = create_held_reservation(
        member, machine, cert, "2026-04-30T11:00:00Z", "2026-04-30T12:00:00Z"
    )
    v1 = validate_success(api.get_member(member["id"], mh))["version"]
    confirmed_q = validate_success(api.confirm_reservation(res_q["id"], v1, mh))
    assert confirmed_q["occupancy_status"] == "CONFIRMED", confirmed_q["occupancy_status"]


def test_bare_adjacency_first_reservation_still_confirmed(api):
    """PRD §3.5: "when `cooldown_minutes` is 0, the windows are compared as bare
    half-open intervals (so a reservation ending exactly when another begins does not
    collide)."

    Confirming the exactly-adjacent second reservation does not disturb the first,
    which stays CONFIRMED.

    Design: Difficulty/resource_temporal_overlap/printer_bare_halfopen_adjacency_allowed
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="PRINTER_3D", tier_overrides=MAKER_TIER,
        machine_overrides=PRINTER_COOLDOWN_0, topup_cents=20000,
    )
    mh = make_member_headers(member["id"])
    res_p = create_held_reservation(
        member, machine, cert, "2026-04-30T10:00:00Z", "2026-04-30T11:00:00Z"
    )
    v0 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_success(api.confirm_reservation(res_p["id"], v0, mh))
    res_q = create_held_reservation(
        member, machine, cert, "2026-04-30T11:00:00Z", "2026-04-30T12:00:00Z"
    )
    v1 = validate_success(api.get_member(member["id"], mh))["version"]
    validate_success(api.confirm_reservation(res_q["id"], v1, mh))
    p_after = validate_success(api.get_reservation(res_p["id"], mh))
    assert p_after["occupancy_status"] == "CONFIRMED", p_after["occupancy_status"]
