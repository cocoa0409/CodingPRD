"""Cascades and facility posture: CRITICAL maintenance closes a lane, shifts posture,
cancels and refunds overlapping bookings; program withdrawal cascades count/status/wallet;
program cycles FULL->OPEN; CLOSED posture blocks confirm.

Covers Difficulty rules transitive_cascade, non_linear_state_machine (program cycle),
and cross_entity_state_dependency (facility-closed posture).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_member_headers,
    ApiErrorId,
    setup_member_ready,
    create_facility,
    create_lane,
    create_member,
    sign_waiver,
    top_up,
    request_booking,
    confirm_booking,
    create_confirmed_booking,
    setup_full_single_seat_program,
    open_maintenance,
    set_clock,
    lane_version,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}


# ─── transitive_cascade / critical_maintenance_cascades_lane_facility_and_booking ─

def test_critical_maintenance_closes_lane_and_shifts_posture(api):
    """PRD §3.3: "Opening a CRITICAL window moves the lane to CLOSED". PRD §3.3: "When
    that count is at least the close threshold of 2, the posture is CLOSED; when the count
    is at least 1 but below 2, the posture is RESTRICTED".

    Design: Difficulty/transitive_cascade/critical_maintenance_cascades_lane_facility_and_booking
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-05T18:00:00Z", end_utc="2026-04-05T19:00:00Z",
    )
    set_clock("2026-04-05T12:00:00Z")
    open_maintenance(
        facility, lane["id"], "2026-04-05T17:00:00Z", "2026-04-05T20:00:00Z", "CRITICAL"
    )
    lane_after = get_success_data(api.get_lane(lane["id"], MANAGER))
    facility_after = get_success_data(api.get_facility(facility["id"], MANAGER))
    assert lane_after["maint_status"] == "CLOSED"
    assert facility_after["posture"] == "RESTRICTED"


def test_critical_maintenance_cancels_and_refunds_overlapping_booking(api):
    """PRD §3.3: "every booking on that lane in CONFIRMED or CHECKED_IN status whose
    interval overlaps the window is cascade-cancelled to CANCELLED, and each such
    cancellation refunds the payer exactly as a normal cancel would, releasing tokens or
    restoring membership minutes". PRD §3.7: "if that is at least the refund cut-off of
    120 minutes, the full token_cost is refunded to the member's token_balance".

    Design: Difficulty/transitive_cascade/critical_maintenance_cascades_lane_facility_and_booking
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-05T18:00:00Z", end_utc="2026-04-05T19:00:00Z",
    )
    set_clock("2026-04-05T12:00:00Z")  # > 120 min before start -> full refund
    open_maintenance(
        facility, lane["id"], "2026-04-05T17:00:00Z", "2026-04-05T20:00:00Z", "CRITICAL"
    )
    cancelled = get_success_data(api.get_booking(booking["id"], MANAGER))
    member_after = get_success_data(api.get_member(member["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"
    assert member_after["token_balance"] == 100  # full refund restores wallet


# ─── transitive_cascade / program_withdraw_cascades_count_status_and_wallet ────

def test_program_withdraw_decrements_count_and_reopens(api):
    """PRD §3.8: "Withdrawal decreases the program's enrolled_count by one and, if the
    program was FULL, returns it from FULL to OPEN."

    Design: Difficulty/transitive_cascade/program_withdraw_cascades_count_status_and_wallet
    """
    facility, lane, member, program, enrollment = setup_full_single_seat_program(
        kind="CLINIC", price_cents=5000
    )
    assert program["status"] == "FULL"
    validate_success(
        api.withdraw_enrollment(enrollment["id"], make_member_headers(member["id"])), 200
    )
    after = get_success_data(api.get_program(program["id"], MANAGER))
    assert after["enrolled_count"] == 0
    assert after["status"] == "OPEN"


def test_program_withdraw_refunds_tokens_to_wallet(api):
    """PRD §3.8: "The member is refunded not in cents but in wallet tokens: the
    charged_cents is converted to tokens by dividing by the facility's token_price_cents
    and rounding down to the nearest whole token, and that many tokens are added to the
    member's token_balance."

    Design: Difficulty/transitive_cascade/program_withdraw_cascades_count_status_and_wallet
    """
    facility, lane, member, program, enrollment = setup_full_single_seat_program(
        kind="CLINIC", price_cents=5000
    )
    validate_success(
        api.withdraw_enrollment(enrollment["id"], make_member_headers(member["id"])), 200
    )
    member_after = get_success_data(api.get_member(member["id"], MANAGER))
    # floor(5000 / 500) = 10 tokens credited; member started at 0.
    assert member_after["token_balance"] == 10


# ─── non_linear_state_machine / program_cyclic_full_to_open_on_withdraw ────────

def test_program_cycles_full_then_open_on_withdraw(api):
    """PRD §3.8: "its status is FULL when the enrolled count equals capacity ... and OPEN
    otherwise". PRD §3.8: "Withdrawal decreases the program's enrolled_count by one and,
    if the program was FULL, returns it from FULL to OPEN."

    Design: Difficulty/non_linear_state_machine/program_cyclic_full_to_open_on_withdraw
    """
    facility, lane, member, program, enrollment = setup_full_single_seat_program(
        kind="LEAGUE", price_cents=5000
    )
    assert program["status"] == "FULL"
    withdrawn = validate_success(
        api.withdraw_enrollment(enrollment["id"], make_member_headers(member["id"])), 200
    )
    after = get_success_data(api.get_program(program["id"], MANAGER))
    assert after["status"] == "OPEN"
    assert after["enrolled_count"] == 0
    assert withdrawn["status"] == "WITHDRAWN"


def test_single_seat_program_full_on_only_enrollment(api):
    """PRD §3.8: "flips the program from OPEN to FULL if the new count reaches capacity".
    PRD §3.8: "When the enrolled count reaches capacity the program transitions OPEN → FULL".

    Design: Difficulty/non_linear_state_machine/program_cyclic_full_to_open_on_withdraw
    """
    facility, lane, member, program, enrollment = setup_full_single_seat_program(
        kind="LEAGUE", price_cents=5000
    )
    assert program["status"] == "FULL"
    assert program["enrolled_count"] == 1
    assert enrollment["status"] == "ENROLLED"


# ─── cross_entity_state_dependency / booking_confirm_blocked_by_facility_closed ─

def test_confirm_blocked_when_facility_closed_by_two_incidents(api):
    """PRD §3.3: "when that count is at least the close threshold of 2, the posture is
    CLOSED ... a CLOSED posture blocks confirmation of all booking kinds". PRD §3.5: "The
    facility posture must permit this booking kind ... CLOSED blocks every kind — or the
    confirm is rejected with ERR_FACILITY_POSTURE_BLOCK."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_blocked_by_facility_closed_posture
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    l1 = create_lane(facility["id"], kind="CAGE", buffer_minutes=0, label="L1")
    l2 = create_lane(facility["id"], kind="CAGE", buffer_minutes=0, label="L2")
    l3 = create_lane(facility["id"], kind="CAGE", buffer_minutes=0, label="L3")
    member = create_member(facility["id"], tier="NONE")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 100)

    booking = request_booking(
        facility, l3["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-08T09:00:00Z", "2026-04-08T10:00:00Z",
    )
    l3_ver = booking and lane_version(l3["id"])

    open_maintenance(facility, l1["id"], "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", "CRITICAL")
    open_maintenance(facility, l2["id"], "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", "CRITICAL")

    facility_after = get_success_data(api.get_facility(facility["id"], MANAGER))
    assert facility_after["posture"] == "CLOSED"

    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": l3_ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_FACILITY_POSTURE_BLOCK.value)


def test_restricted_posture_blocks_party_confirm(api):
    """PRD §3.3: "A RESTRICTED posture blocks the creation of large-footprint PARTY and
    TEAM_BLOCK bookings while still allowing OPEN_SLOT and LESSON bookings". PRD §3.5:
    "The facility posture must permit this booking kind — RESTRICTED blocks PARTY and
    TEAM_BLOCK ... or the confirm is rejected with ERR_FACILITY_POSTURE_BLOCK."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_blocked_by_facility_closed_posture
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    l1 = create_lane(facility["id"], kind="CAGE", buffer_minutes=0, label="L1")
    l2 = create_lane(facility["id"], kind="CAGE", buffer_minutes=0, label="L2")
    member = create_member(facility["id"], tier="NONE")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 200)

    party = request_booking(
        facility, l2["id"], member, "PARTY", "TOKEN",
        "2026-04-08T09:00:00Z", "2026-04-08T11:00:00Z", party_guests=5,
    )
    l2_ver = lane_version(l2["id"])
    # One CRITICAL incident -> facility RESTRICTED (1 closed lane, below threshold 2).
    open_maintenance(facility, l1["id"], "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", "CRITICAL")
    facility_after = get_success_data(api.get_facility(facility["id"], MANAGER))
    assert facility_after["posture"] == "RESTRICTED"

    res = api.confirm_booking(
        party["id"], {"expected_lane_version": l2_ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_FACILITY_POSTURE_BLOCK.value)
