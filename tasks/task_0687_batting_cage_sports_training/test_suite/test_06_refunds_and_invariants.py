"""Conserved quantities and refund waterfall: token wallet restored on confirm-then-cancel,
membership minutes restored, partial refund within cutoff, membership-minutes input
filtering, and the empty-team-lane cardinality boundary.

Covers Difficulty rules compensating_invariant and boundary_precision_check (empty team),
plus the refund and membership-minutes calculation corner instances.
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
    set_clock,
    lane_version,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}


# ─── compensating_invariant / token_wallet_conserved_on_confirm_then_cancel ────

def test_token_wallet_conserved_on_confirm_then_full_refund_cancel(api):
    """PRD §3.7: "if that is at least the refund cut-off of 120 minutes, the full
    token_cost is refunded to the member's token_balance". PRD §3.5: "and that many
    tokens are subtracted from the member's token_balance."

    Design: Difficulty/compensating_invariant/token_wallet_conserved_on_confirm_then_cancel_full_refund
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    set_clock("2026-04-05T00:00:00Z")
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-05T09:00:00Z", end_utc="2026-04-05T10:00:00Z",
    )
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200
    )
    member_after = get_success_data(api.get_member(member["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"
    assert member_after["token_balance"] == 100  # debit then full refund -> no drift


def test_token_full_refund_when_cancel_far_before_start(api):
    """PRD §3.7: "the system computes the whole minutes from the current clock to the
    booking's start_utc; if that is at least the refund cut-off of 120 minutes, the full
    token_cost is refunded to the member's token_balance".

    Design: Difficulty/compensating_invariant/token_wallet_conserved_on_confirm_then_cancel_full_refund
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    set_clock("2026-04-05T00:00:00Z")  # 9 hours before a 09:00 start
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-05T09:00:00Z", end_utc="2026-04-05T10:00:00Z",
    )
    before_cancel = get_success_data(api.get_member(member["id"], MANAGER))
    assert before_cancel["token_balance"] == 92  # 100 - 8 on confirm
    validate_success(
        api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200
    )
    after = get_success_data(api.get_member(member["id"], MANAGER))
    assert after["token_balance"] == 100  # full 8 restored


# ─── compensating_invariant / member_minutes_conserved_on_confirm_then_cancel ──

def test_membership_minutes_conserved_on_confirm_then_cancel(api):
    """PRD §3.7: "A booking cancelled from CONFIRMED under MEMBERSHIP pay mode restores
    the member's minutes fully — the booking's duration_minutes times lane_count is
    subtracted back from monthly_member_minutes_used, with no forfeit."

    Design: Difficulty/compensating_invariant/member_minutes_conserved_on_confirm_then_cancel
    """
    facility, lane, member = setup_member_ready(tier="GOLD", waiver=True, tokens=0)
    booking = create_confirmed_booking(
        facility, lane, member, pay_mode="MEMBERSHIP",
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    validate_success(
        api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200
    )
    after = get_success_data(api.get_member(member["id"], MANAGER))
    assert after["monthly_member_minutes_used"] == 0


def test_membership_minutes_added_on_confirm(api):
    """PRD §3.5: "When pay_mode is MEMBERSHIP, the member's monthly_member_minutes_used is
    increased by the booking's duration_minutes multiplied by its lane_count."

    Design: Difficulty/compensating_invariant/member_minutes_conserved_on_confirm_then_cancel
    """
    facility, lane, member = setup_member_ready(tier="GOLD", waiver=True, tokens=0)
    create_confirmed_booking(
        facility, lane, member, pay_mode="MEMBERSHIP",
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    after = get_success_data(api.get_member(member["id"], MANAGER))
    assert after["monthly_member_minutes_used"] == 60  # 60 min * lane_count 1


# ─── calculations corner: refund_partial_within_cutoff ─────────────────────────

def test_partial_refund_within_cutoff(api):
    """PRD §3.7: "otherwise the facility keeps a forfeit equal to the token_cost
    multiplied by one-half, rounded up to a whole token, and the member is refunded the
    token_cost minus that forfeit."

    Design: Corner/calculations/refund_partial_within_cutoff
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    set_clock("2026-04-05T00:00:00Z")
    # Peak booking 18:00-19:00: lane 4000*1.5=6000 -> ceil(6000/500)=12 tokens.
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-05T18:00:00Z", end_utc="2026-04-05T19:00:00Z",
    )
    confirmed = get_success_data(api.get_booking(booking["id"], MANAGER))
    assert confirmed["token_cost"] == 12
    set_clock("2026-04-05T17:30:00Z")  # 30 min before start (< 120 cutoff)
    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200
    )
    member_after = get_success_data(api.get_member(member["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"
    # 100 -> 88 (confirm debit 12) -> refund 12 - ceil(12*0.5)=6 -> 94.
    assert member_after["token_balance"] == 94


# ─── calculations corner: membership_minutes_input_filtering_excludes_cancelled ─

def test_membership_minutes_exclude_cancelled_booking(api):
    """PRD §3.5: "When pay_mode is MEMBERSHIP, the member's monthly_member_minutes_used
    is increased by the booking's duration_minutes multiplied by its lane_count." PRD §3.7:
    "A booking cancelled from CONFIRMED under MEMBERSHIP pay mode restores the member's
    minutes fully — the booking's duration_minutes times lane_count is subtracted back
    from monthly_member_minutes_used, with no forfeit."

    Design: Corner/calculations/membership_minutes_input_filtering_excludes_cancelled
    """
    facility, lane, member = setup_member_ready(tier="GOLD", waiver=True, tokens=0)
    # One kept MEMBERSHIP booking (60 min) -> 60 minutes.
    create_confirmed_booking(
        facility, lane, member, pay_mode="MEMBERSHIP",
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    # A second MEMBERSHIP booking confirmed then cancelled -> contributes 0.
    bk_cancel = create_confirmed_booking(
        facility, lane, member, pay_mode="MEMBERSHIP",
        start_utc="2026-04-02T11:00:00Z", end_utc="2026-04-02T12:00:00Z",
    )
    validate_success(
        api.cancel_booking(bk_cancel["id"], make_member_headers(member["id"])), 200
    )
    after = get_success_data(api.get_member(member["id"], MANAGER))
    assert after["monthly_member_minutes_used"] == 60


# ─── boundary_precision_check / empty_team_lane_ids_zero_extra_lanes_boundary ──

def test_team_block_lane_count_mismatch_rejected(api):
    """PRD §3.4: "The lane_count must equal one plus the number of entries in
    team_lane_ids." PRD §2.11: "a lane_count that does not equal one plus the number of
    entries in team_lane_ids — yields ERR_INVALID_REQUEST."

    Design: Difficulty/boundary_precision_check/empty_team_lane_ids_zero_extra_lanes_boundary
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "TEAM_BLOCK", "pay_mode": "HOURLY",
        "lane_count": 2, "team_lane_ids": [],
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_lane_count_one_with_empty_team_list_accepted(api):
    """PRD §3.4: "a lane_count (lanes occupied, defaulting to 1)". PRD §3.4: "The
    lane_count must equal one plus the number of entries in team_lane_ids."

    Design: Difficulty/boundary_precision_check/empty_team_lane_ids_zero_extra_lanes_boundary
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "OPEN_SLOT", "pay_mode": "HOURLY",
        "lane_count": 1, "team_lane_ids": [],
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    booking = validate_success(res, 201)
    assert booking["status"] == "REQUESTED"
