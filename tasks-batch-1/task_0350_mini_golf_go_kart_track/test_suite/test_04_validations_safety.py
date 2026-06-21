"""Validation rules: safety gates, temporal windows, fiscal sufficiency, slot
overlap semantics, and validation-precedence conflicts.

Covers Difficulty queue rules priority_pair_validation_conflict and
resource_temporal_overlap, plus corner-design validation claims.
"""
from test_helpers import (
    validate_success, validate_error,
    make_ops_manager_headers, make_cashier_headers,
    setup_open_heat_scenario,
    create_venue, create_attraction, create_heat, create_tee_session,
    create_pricing_plan, create_guest, make_signed_guest, sign_waiver,
    create_heat_hold_booking, create_tee_hold_booking, confirm_booking_heat,
    get_heat, get_booking, get_guest, get_wallet_for_guest, top_up,
    create_combo_pass,
    create_booking_payload, create_party_group_payload, create_waiver_payload,
)

OPS = make_ops_manager_headers()
CASHIER = make_cashier_headers()


# ───────────────── Difficulty: priority_pair_validation_conflict ──────────────

def test_invalid_state_beats_height_on_confirm(api):
    """PRD §3.12: "then that the target is in a legal state for the requested
    transition, covering terminal-state lockdown and repeated-trigger rejection
    (ERR_INVALID_STATE)."
    PRD §3.12: "Then the safety gates evaluate: the height requirement
    (ERR_HEIGHT_REQUIREMENT) before the waiver requirement (ERR_WAIVER_REQUIRED)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_height_on_confirm
    """
    # Both gates fail at once: the guest is too short (height 120 < min 150, pri 8)
    # AND the booking is in a terminal state because its SCHEDULED heat was
    # cancelled (cascade), so confirm hits the state check (pri 7) first.
    venue = create_venue(name="V", set_clock="2026-06-14T09:00:00Z")
    attraction = create_attraction(venue["id"], kind="GO_KART", min_height_cm=150, lane_count=5)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])  # SCHEDULED, not opened
    short = make_signed_guest(full_name="Short", height_cm=120)
    bk = create_heat_hold_booking(venue["id"], short["id"], heat["id"], plan["id"], party_size=1)
    validate_success(api.cancel_heat(heat["id"], OPS), 200)  # cascades booking -> CANCELLED
    assert get_booking(bk["id"])["status"] == "CANCELLED"

    # Cancelling the heat bumped its version; supply the CURRENT version so the
    # OCC check (§3.12 priority 6, ERR_STALE_SLOT_VERSION) passes and the
    # booking-state check (priority 7) is the gate that fires — proving state
    # (pri 7) precedes the height gate (pri 8) on this confirm.
    heat_v = get_heat(heat["id"])["version"]
    res = api.confirm_booking(bk["id"], {"expected_heat_version": heat_v}, OPS)
    validate_error(res, "ERR_INVALID_STATE")


def test_waiver_required_beats_combo_pass_invalid_on_confirm(api):
    """PRD §3.12: "Then the safety gates evaluate: the height requirement
    (ERR_HEIGHT_REQUIREMENT) before the waiver requirement (ERR_WAIVER_REQUIRED).
    Then slot-interval collision on slot creation (ERR_SLOT_OVERLAP), then the
    wristband unit cap (ERR_WRISTBAND_CAP_EXCEEDED), then combo-pass validity
    (ERR_COMBO_PASS_INVALID)".
    PRD §3.3: "A booking whose guest does not hold a SIGNED, unexpired waiver at
    confirm time is rejected with ERR_WAIVER_REQUIRED."

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_combo_pass_invalid_on_confirm
    """
    # Both gates fail at once: the booking guest has NO waiver (safety, pri 9) AND
    # cites a combo pass owned by a DIFFERENT guest (referential, pri 12). The
    # waiver requirement is reported because it is evaluated first.
    s = setup_open_heat_scenario(lane_count=5, min_height_cm=0)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    no_waiver = create_guest(full_name="NoWaiver", height_cm=180)
    other = make_signed_guest(full_name="Other", height_cm=180)
    other_pass = create_combo_pass(other["id"], total_credits=5)  # not owned by no_waiver
    bk = create_heat_hold_booking(venue_id, no_waiver["id"], heat_id, plan_id, party_size=1,
                                  units=1, combo_pass_id=other_pass["id"])
    res = api.confirm_booking(bk["id"], {"expected_heat_version": s["heat"]["version"]}, OPS)
    validate_error(res, "ERR_WAIVER_REQUIRED")
    assert get_booking(bk["id"])["status"] == "HOLD"


def test_invalid_state_reported_when_confirming_cancelled_short_guest(api):
    """PRD §3.12: "then that the target is in a legal state for the requested
    transition, covering terminal-state lockdown and repeated-trigger rejection
    (ERR_INVALID_STATE)." PRD §3.8: "The terminal booking statuses COMPLETED,
    CANCELLED, and NO_SHOW admit no further transitions".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_height_on_confirm
    """
    # Same category pair (state pri-7 vs height pri-8): a CANCELLED booking whose
    # guest is also too short still reports the state error, not the height error.
    s = setup_open_heat_scenario(lane_count=5, min_height_cm=150)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    guest = make_signed_guest(full_name="Short", height_cm=120)
    bk = create_heat_hold_booking(venue_id, guest["id"], heat_id, plan_id, party_size=1)
    validate_success(api.cancel_booking(bk["id"], OPS), 200)  # now terminal CANCELLED
    res = api.confirm_booking(bk["id"], {"expected_heat_version": s["heat"]["version"]}, OPS)
    validate_error(res, "ERR_INVALID_STATE")


def test_waiver_required_when_unsigned_guest_uses_invalid_combo(api):
    """PRD §3.12: "Then the safety gates evaluate: the height requirement
    (ERR_HEIGHT_REQUIREMENT) before the waiver requirement (ERR_WAIVER_REQUIRED).
    Then slot-interval collision on slot creation (ERR_SLOT_OVERLAP), then the
    wristband unit cap (ERR_WRISTBAND_CAP_EXCEEDED), then combo-pass validity
    (ERR_COMBO_PASS_INVALID)".
    PRD §3.5: "A combo pass named on a booking must belong to that booking's guest,
    be ACTIVE, and have at least one credit remaining".

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_combo_pass_invalid_on_confirm
    """
    # Same category pair (safety pri-9 vs referential pri-12): unsigned guest cites
    # ANOTHER guest's pass (referentially invalid); waiver fires first.
    s = setup_open_heat_scenario(lane_count=5, min_height_cm=0)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    unsigned = create_guest(full_name="Unsigned", height_cm=180)
    other = make_signed_guest(full_name="Other", height_cm=180)
    other_pass = create_combo_pass(other["id"], total_credits=5)
    bk = create_heat_hold_booking(venue_id, unsigned["id"], heat_id, plan_id,
                                  party_size=1, units=1, combo_pass_id=other_pass["id"])
    res = api.confirm_booking(bk["id"], {"expected_heat_version": s["heat"]["version"]}, OPS)
    validate_error(res, "ERR_WAIVER_REQUIRED")


# ────────────────── Difficulty: resource_temporal_overlap ─────────────────────

def test_heat_half_open_adjacency_allowed_inner_overlap_rejected(api):
    """PRD §3.2: "Because the interval is half-open, exact adjacency — where one
    heat's end_utc equals the next heat's start_utc — does not collide and is
    permitted. Any inner overlap is rejected with ERR_SLOT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/heat_half_open_adjacency_allowed_inner_overlap_rejected
    """
    venue = create_venue(name="Track M", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    create_heat(venue["id"], attraction["id"],
                start_utc="2026-06-14T10:00:00Z", end_utc="2026-06-14T10:15:00Z")
    # Abutting [10:15,10:30): adjacency allowed -> 201 SCHEDULED.
    abut = validate_success(api.create_heat({
        "venue_id": venue["id"], "attraction_id": attraction["id"],
        "start_utc": "2026-06-14T10:15:00Z", "end_utc": "2026-06-14T10:30:00Z",
    }, OPS), 201)
    assert abut["status"] == "SCHEDULED"
    # Inner overlap [10:10,10:25): rejected.
    res = api.create_heat({
        "venue_id": venue["id"], "attraction_id": attraction["id"],
        "start_utc": "2026-06-14T10:10:00Z", "end_utc": "2026-06-14T10:25:00Z",
    }, OPS)
    validate_error(res, "ERR_SLOT_OVERLAP")


def test_tee_session_turnover_buffer_rejects_abutting(api):
    """PRD §3.2: "A consequence worth stating plainly: two sessions that merely
    abut, leaving a gap of exactly zero minutes, are rejected, because a zero gap
    is below the ten-minute buffer". PRD §3.2: "When that gap is less than ten
    minutes the creation is rejected with ERR_SLOT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/tee_session_turnover_buffer_rejects_abutting
    """
    venue = create_venue(name="Track N", set_clock=None)
    attraction = create_attraction(venue["id"], kind="MINI_GOLF")
    create_tee_session(venue["id"], attraction["id"],
                       start_utc="2026-06-14T10:00:00Z", end_utc="2026-06-14T11:00:00Z",
                       party_slot_capacity=10)
    # Abutting [11:00,12:00] gap 0 -> rejected.
    res = api.create_tee_session({
        "venue_id": venue["id"], "attraction_id": attraction["id"],
        "start_utc": "2026-06-14T11:00:00Z", "end_utc": "2026-06-14T12:00:00Z",
        "party_slot_capacity": 10,
    }, OPS)
    validate_error(res, "ERR_SLOT_OVERLAP")
    # Gap-10 [11:10,12:10] -> accepted.
    ok = validate_success(api.create_tee_session({
        "venue_id": venue["id"], "attraction_id": attraction["id"],
        "start_utc": "2026-06-14T11:10:00Z", "end_utc": "2026-06-14T12:10:00Z",
        "party_slot_capacity": 10,
    }, OPS), 201)
    assert ok["status"] == "SCHEDULED"


def test_heat_strict_inner_overlap_rejected(api):
    """PRD §3.2: "Heats use half-open interval semantics on the same attraction: a
    new heat's interval is [start_utc, end_utc), and it collides with an existing
    non-terminal heat (one in SCHEDULED, OPEN, or CLOSED; cancelled heats are
    ignored) when the new start is before the existing end and the existing start
    is before the new end."

    Design: Difficulty/resource_temporal_overlap/heat_half_open_adjacency_allowed_inner_overlap_rejected
    """
    # A second inner-overlap shape: a candidate fully containing the existing heat.
    venue = create_venue(name="Track M2", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    create_heat(venue["id"], attraction["id"],
                start_utc="2026-06-14T10:05:00Z", end_utc="2026-06-14T10:10:00Z")
    # Candidate [10:00,10:15) strictly contains [10:05,10:10) -> overlap rejected.
    res = api.create_heat({
        "venue_id": venue["id"], "attraction_id": attraction["id"],
        "start_utc": "2026-06-14T10:00:00Z", "end_utc": "2026-06-14T10:15:00Z",
    }, OPS)
    validate_error(res, "ERR_SLOT_OVERLAP")


def test_tee_session_interpenetrating_overlap_rejected(api):
    """PRD §3.2: "for a candidate session and each existing non-terminal session on
    the attraction, the system measures the gap ... and if the two intervals
    interpenetrate, there is no gap at all. When that gap is less than ten minutes
    the creation is rejected with ERR_SLOT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/tee_session_turnover_buffer_rejects_abutting
    """
    # A second buffer shape: two interpenetrating sessions (gap < 0) are rejected.
    venue = create_venue(name="Track N2", set_clock=None)
    attraction = create_attraction(venue["id"], kind="MINI_GOLF")
    create_tee_session(venue["id"], attraction["id"],
                       start_utc="2026-06-14T10:00:00Z", end_utc="2026-06-14T11:00:00Z",
                       party_slot_capacity=10)
    # Candidate [10:30,11:30] interpenetrates [10:00,11:00] -> rejected.
    res = api.create_tee_session({
        "venue_id": venue["id"], "attraction_id": attraction["id"],
        "start_utc": "2026-06-14T10:30:00Z", "end_utc": "2026-06-14T11:30:00Z",
        "party_slot_capacity": 10,
    }, OPS)
    validate_error(res, "ERR_SLOT_OVERLAP")


# ───────────────────────── Corner: validations ───────────────────────────────

def test_wristband_units_over_cap_rejected_on_create(api):
    """PRD §3.6: "If the booking names a wristband plan that caps units and the
    requested units exceeds that cap, creation is rejected with
    ERR_WRISTBAND_CAP_EXCEEDED."

    Design: Corner/validations/wristband_units_over_cap_rejected_on_create
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="MINI_GOLF")
    plan = create_pricing_plan(venue["id"], mode="WRISTBAND", base_price_cents=4000,
                               wristband_unit_cap=3)
    tee = create_tee_session(venue["id"], attraction["id"], party_slot_capacity=10)
    guest = create_guest(full_name="G", height_cm=170)
    res = api.create_booking(create_booking_payload(
        venue["id"], guest["id"], plan["id"],
        slot_kind="TEE_SESSION", tee_session_id=tee["id"], party_size=1, units=5,
    ), OPS)
    validate_error(res, "ERR_WRISTBAND_CAP_EXCEEDED")


def test_height_requirement_blocks_confirm(api):
    """PRD §3.3: "The height gate compares the guest's height_cm against the owning
    attraction's min_height_cm; a guest whose height is below the attraction's
    minimum is turned away from confirming with ERR_HEIGHT_REQUIREMENT."

    Design: Corner/validations/height_requirement_blocks_confirm
    """
    s = setup_open_heat_scenario(lane_count=5, min_height_cm=150)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    guest = make_signed_guest(full_name="ShortAdult", height_cm=120)
    bk = create_heat_hold_booking(venue_id, guest["id"], heat_id, plan_id, party_size=1)
    res = api.confirm_booking(bk["id"], {"expected_heat_version": s["heat"]["version"]}, OPS)
    validate_error(res, "ERR_HEIGHT_REQUIREMENT")
    assert get_booking(bk["id"])["status"] == "HOLD"


def test_minor_waiver_without_guardian_rejected(api):
    """PRD §3.3: "A guest is treated as a minor when their age at the time of
    signing — derived from birthdate against signed_at — is under 18 years; a
    minor's waiver must carry a guardian_name, and an attempt to sign a minor's
    waiver without one is rejected with ERR_WAIVER_REQUIRED."

    Design: Corner/validations/minor_waiver_without_guardian_rejected
    """
    venue = create_venue(name="V", set_clock="2026-06-14T09:00:00Z")
    guest = create_guest(full_name="Kid", height_cm=130, birthdate="2015-01-01")
    res = api.create_waiver(create_waiver_payload(guest["id"]), OPS)
    validate_error(res, "ERR_WAIVER_REQUIRED")
    assert get_guest(guest["id"])["waiver_status"] == "NONE"


def test_combo_pass_other_guest_rejected_on_confirm(api):
    """PRD §3.5: "A combo pass named on a booking must belong to that booking's
    guest, be ACTIVE, and have at least one credit remaining; a pass that fails any
    of these is rejected at confirm with ERR_COMBO_PASS_INVALID."

    Design: Corner/validations/combo_pass_other_guest_rejected_on_confirm
    """
    s = setup_open_heat_scenario(lane_count=5, min_height_cm=0)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    ga = make_signed_guest(full_name="A", height_cm=180)
    gb = create_guest(full_name="B", height_cm=180)
    pass_b = create_combo_pass(gb["id"], total_credits=5)
    bk = create_heat_hold_booking(venue_id, ga["id"], heat_id, plan_id, party_size=1,
                                  units=1, combo_pass_id=pass_b["id"])
    res = api.confirm_booking(bk["id"], {"expected_heat_version": s["heat"]["version"]}, OPS)
    validate_error(res, "ERR_COMBO_PASS_INVALID")
    assert get_booking(bk["id"])["status"] == "HOLD"


def test_arcade_redemption_over_balance_rejected(api):
    """PRD §3.4: "a redemption or deposit whose amount exceeds the current balance
    is rejected outright with ERR_INSUFFICIENT_CARD_BALANCE, never partially
    applied."

    Design: Corner/validations/arcade_redemption_over_balance_rejected
    """
    guest = create_guest(full_name="G", height_cm=175, as_role="cashier")
    wallet = get_wallet_for_guest(guest["id"])
    top_up(wallet["id"], 4000)
    res = api.redeem_wallet(wallet["id"], {"amount_cents": 6000}, CASHIER)
    validate_error(res, "ERR_INSUFFICIENT_CARD_BALANCE")
    refreshed = validate_success(api.get_wallet(wallet["id"], CASHIER), 200)
    assert refreshed["arcade_card_balance_cents"] == 4000, "balance unchanged after rejected redemption"


def test_party_deposit_over_wallet_balance_rejected(api):
    """PRD §3.10: "Creation opens the group in DRAFT status with units_consumed at
    zero and debits deposit_cents from the host's wallet arcade_card_balance_cents;
    if the host's balance cannot cover the deposit, creation is rejected with
    ERR_INSUFFICIENT_CARD_BALANCE."

    Design: Corner/validations/party_deposit_over_wallet_balance_rejected
    """
    venue = create_venue(name="V", set_clock=None)
    host = create_guest(full_name="Host", height_cm=175)
    wallet = get_wallet_for_guest(host["id"])
    top_up(wallet["id"], 1000)
    res = api.create_party_group(create_party_group_payload(
        venue["id"], host["id"], package_name="Big", included_unit_count=10, deposit_cents=3000), OPS)
    validate_error(res, "ERR_INSUFFICIENT_CARD_BALANCE")
    refreshed = validate_success(api.get_wallet(wallet["id"], OPS), 200)
    assert refreshed["arcade_card_balance_cents"] == 1000


def test_check_in_outside_window_rejected(api):
    """PRD §3.8: "Check-in is permitted only while the owning slot is OPEN and only
    when the venue's current_utc falls inside the slot's active window — within
    [start_utc, end_utc) for a heat (start inclusive, end exclusive) ... A check-in
    attempted outside that window is rejected with ERR_CHECK_IN_WINDOW."

    Design: Corner/validations/check_in_outside_window_rejected
    """
    # Heat [10:00,10:15) but clock at 09:00 (before the window).
    s = setup_open_heat_scenario(lane_count=5, set_clock="2026-06-14T09:00:00Z")
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(venue_id, guest["id"], heat_id, plan_id, party_size=1)
    bk = confirm_booking_heat(bk["id"], s["heat"]["version"])
    res = api.check_in_booking(bk["id"], CASHIER)
    validate_error(res, "ERR_CHECK_IN_WINDOW")
    assert get_booking(bk["id"])["status"] == "CONFIRMED"


def test_no_show_before_window_end_rejected(api):
    """PRD §3.8: "A confirmed booking that never showed can be marked a no-show by a
    Cashier or OpsManager ... but only after the slot's window has fully passed —
    that is, only when the venue's current_utc is at or after the slot's end_utc. A
    no-show attempted before the window has passed is rejected with
    ERR_NO_SHOW_WINDOW."

    Design: Corner/validations/no_show_before_window_end_rejected
    """
    # Heat [10:00,10:15); clock 10:05 (before end).
    s = setup_open_heat_scenario(lane_count=5, set_clock="2026-06-14T10:05:00Z")
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(venue_id, guest["id"], heat_id, plan_id, party_size=1)
    bk = confirm_booking_heat(bk["id"], s["heat"]["version"])
    res = api.no_show_booking(bk["id"], CASHIER)
    validate_error(res, "ERR_NO_SHOW_WINDOW")
    assert get_booking(bk["id"])["status"] == "CONFIRMED"


def test_slot_kind_mismatch_on_booking_create_rejected(api):
    """PRD §3.6: "The supplied slot_kind must agree with which of heat_id /
    tee_session_id was provided, and a mismatch is part of the malformed-request
    family rejected with ERR_INVALID_REQUEST".

    Design: Corner/validations/slot_kind_mismatch_on_booking_create_rejected
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="MINI_GOLF")
    plan = create_pricing_plan(venue["id"], mode="PER_ROUND", base_price_cents=1000)
    tee = create_tee_session(venue["id"], attraction["id"], party_slot_capacity=10)
    guest = create_guest(full_name="G", height_cm=170)
    # slot_kind=HEAT but only tee_session_id supplied.
    res = api.create_booking(create_booking_payload(
        venue["id"], guest["id"], plan["id"],
        slot_kind="HEAT", tee_session_id=tee["id"], party_size=1,
    ), OPS)
    validate_error(res, "ERR_INVALID_REQUEST")
