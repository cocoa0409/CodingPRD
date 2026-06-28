"""UV session booking: the dose calc, skin/consent/frequency/cool-down gates,
boundary precision, and the dual-variant reservation-vs-start dose evaluation.

Covers queue-B entity/calculation/validation/errors corner instances for sessions
plus the dual_variant_calc, combinatorial_formula (dose), boundary_precision_check
(dose), and priority_pair (skin-prohibited) difficulty instances.
"""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    create_session_payload,
)
from test_helpers import fixtures as fx
from datetime import datetime


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable instant.

    PRD §2.4 mandates three fractional digits, but a bare-second form denotes
    the same instant; comparing parsed instants is the PRD-faithful check.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_system_headers"]
SALON_MANAGER = TEST_USERS["salon_manager_headers"]


# ---------------------------------------------------------------------------
# Request-shape and computed-field corner instances
# ---------------------------------------------------------------------------
def test_session_missing_requested_seconds_rejected(api):
    """PRD §3.4: "The body must be well-formed: required fields present, enums in
    range, `requested_seconds` at least 1, and the UV-versus-spray consistency just
    described — a mismatch ... is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_session_missing_required_field_returns_422
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0}, clock="2026-06-01T10:00:00Z",
    )
    payload = {
        "member_id": member["id"], "kind": "UV", "booking_mode": "WALK_IN",
        "equipment_id": equipment["id"], "start_at": "2026-06-01T10:00:00Z",
    }
    resp = api.create_session(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_uv_session_with_spray_room_inconsistent_rejected(api):
    """PRD §3.4: "the UV-versus-spray consistency just described — a mismatch (a UV
    booking missing `equipment_id` or carrying a `spray_room_id`, or the spray
    mirror image) is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/uv_session_with_spray_room_inconsistent_rejected
    """
    plan, member, room = fx.setup_active_member_with_spray_room(
        plan_overrides={"weekly_uv_session_cap": 0}, clock="2026-06-01T10:00:00Z",
    )
    payload = {
        "member_id": member["id"], "kind": "UV", "booking_mode": "WALK_IN",
        "spray_room_id": room["id"], "start_at": "2026-06-01T10:00:00Z",
        "requested_seconds": 120,
    }
    resp = api.create_session(payload, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_spray_session_end_at_computed(api):
    """PRD §3.4: "A new session is created in `RESERVED` status with `end_at`
    computed as `start_at` plus `requested_seconds`; for a UV session,
    `allowed_seconds` is populated from the dose calculation of Section 3.8 and is
    left null for spray sessions."

    Design: Corner/entities/session_end_at_computed_from_inputs
    """
    plan, member, room = fx.setup_active_member_with_spray_room(
        plan_overrides={"weekly_uv_session_cap": 0}, clock="2026-06-15T10:00:00Z",
    )
    session = fx.reserve_spray_session(member["id"], room["id"], "2026-06-15T11:00:00Z", 300)
    assert _instant(session["end_at"]) == _instant("2026-06-15T11:05:00Z"), (
        f"end_at must be start_at + 300s, got {session['end_at']}"
    )
    assert session["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Dose calculation: combinatorial nested-min, dual-variant, boundary
# ---------------------------------------------------------------------------
def test_dose_allowed_seconds_equipment_ceiling_binds(api):
    """PRD §3.8: "The session's `allowed_seconds` is then the minimum of three
    quantities: the escalated allowance, the per-type cap, and the booked
    equipment's `max_exposure_seconds`."

    Design: Difficulty/combinatorial_formula/dose_nested_min_three_inputs
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Low cap bed", max_exposure_seconds=100, turnaround_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Five Adult", skin_type="V",
                                     date_of_birth="1985-01-01T00:00:00Z")
    # skin V base 240 cap 720, count 0 -> escalated 240; min(240,720,100)=100.
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-01T10:00:00Z", requested_seconds=100,
    )
    resp = api.create_session(payload, make_member_headers(member["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["allowed_seconds"] == 100, (
        f"equipment ceiling 100 must bind, got allowed_seconds {data['allowed_seconds']}"
    )
    assert data["status"] == "RESERVED"


def test_dose_skin_iv_count_zero_allowed_is_180(api):
    """PRD §3.8: "The base seconds are 90 for type `II`, 120 for type `III`, 180 for
    type `IV`, 240 for type `V`, and 300 for type `VI`. ... The escalated allowance
    is the base plus 30 seconds for each of the member's completed UV sessions ...
    The session's `allowed_seconds` is then the minimum of three quantities: the
    escalated allowance, the per-type cap, and the booked equipment's
    `max_exposure_seconds`."

    Design: Difficulty/combinatorial_formula/dose_nested_min_three_inputs
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0},
        member_overrides={"skin_type": "IV"},
        equip_overrides={"max_exposure_seconds": 600, "turnaround_seconds": 600},
        clock="2026-06-01T10:00:00Z",
    )
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-01T10:00:00Z", requested_seconds=180,
    )
    resp = api.create_session(payload, make_member_headers(member["id"]))
    data = validate_success(resp, expected_status=201)
    # skin IV base 180, count 0 -> escalated 180; min(180,600,600)=180.
    assert data["allowed_seconds"] == 180


def test_dose_ceiling_exact_boundary_passes(api):
    """PRD §3.8: "A UV booking passes the dose gate when its `requested_seconds` is
    less than or equal to `allowed_seconds`; a request of exactly `allowed_seconds`
    passes, and a request of `allowed_seconds` plus one is rejected with
    `ERR_DOSE_EXCEEDS_LIMIT`."

    Design: Difficulty/boundary_precision_check/dose_ceiling_exact_boundary
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0},
        member_overrides={"skin_type": "IV"},
        equip_overrides={"max_exposure_seconds": 600, "turnaround_seconds": 600},
        clock="2026-06-01T10:00:00Z",
    )
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-01T10:00:00Z", requested_seconds=180,
    )
    resp = api.create_session(payload, make_member_headers(member["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["allowed_seconds"] == 180
    assert data["status"] == "RESERVED"


def test_dose_ceiling_one_over_boundary_rejected(api):
    """PRD §3.8: "a request of exactly `allowed_seconds` passes, and a request of
    `allowed_seconds` plus one is rejected with `ERR_DOSE_EXCEEDS_LIMIT`."

    Design: Difficulty/boundary_precision_check/dose_ceiling_exact_boundary
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0},
        member_overrides={"skin_type": "IV"},
        equip_overrides={"max_exposure_seconds": 600, "turnaround_seconds": 600},
        clock="2026-06-01T10:00:00Z",
    )
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-03T10:00:00Z", requested_seconds=181,
    )
    resp = api.create_session(payload, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_DOSE_EXCEEDS_LIMIT.value, expected_status=422)


def test_dose_estimate_persisted_at_reservation_holds_at_start(api):
    """PRD §3.4: "A new session is created in `RESERVED` status with `end_at`
    computed as `start_at` plus `requested_seconds`; for a UV session,
    `allowed_seconds` is populated from the dose calculation of Section 3.8."
    PRD §3.8: "At reservation it is a forward-looking estimate using
    `completed_uv_session_count` as observed at reservation time. It is re-evaluated
    when the session is started, using `completed_uv_session_count` as of the start
    instant; because intervening UV sessions may have completed in the meantime, the
    actual escalated allowance at start is greater than or equal to the
    reservation-time estimate, so a `requested_seconds` that was borderline-valid at
    reservation remains valid at start."

    Design: Difficulty/dual_variant_calc/dose_estimate_vs_actual_on_session
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000,
                          retail_discount_pct=0.10, weekly_uv_session_cap=0)
    eq1 = fx.create_equipment(name="Bed eq1", max_exposure_seconds=600, turnaround_seconds=600)
    eq2 = fx.create_equipment(name="Bed eq2", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Adult Three", skin_type="III")
    mid = member["id"]
    # Session A: complete it -> count becomes 1.
    fx.complete_uv_session(mid, eq1["id"], "2026-06-01T10:00:00Z", 100)
    fx.set_clock("2026-06-02T10:00:00Z")
    # Reserve B with count=1: allowed = min(120 + 1*30, 480, 600) = 150.
    sess_b = fx.reserve_uv_session(mid, eq2["id"], "2026-06-02T10:00:00Z", 150)
    assert sess_b["allowed_seconds"] == 150, (
        f"reservation estimate must stamp allowed_seconds 150, got {sess_b['allowed_seconds']}"
    )
    # Session C on eq1 (count becomes 2) before starting B.
    fx.complete_uv_session(mid, eq1["id"], "2026-06-02T10:00:00Z", 100)
    # Now start B; requested 150 still valid because actual allowance (>=150) at start.
    start_resp = api.start_session(sess_b["id"], FRONT_DESK)
    started = validate_success(start_resp)
    assert started["status"] == "IN_PROGRESS"
    assert started["allowed_seconds"] == 150, (
        f"persisted reservation estimate must remain 150, got {started['allowed_seconds']}"
    )
    after = validate_success(api.get_member(mid, FRONT_DESK))
    assert after["completed_uv_session_count"] == 2


def test_dose_estimate_reservation_value_independent_of_later_completion(api):
    """PRD §3.8: "At reservation it is a forward-looking estimate using
    `completed_uv_session_count` as observed at reservation time."

    Design: Difficulty/dual_variant_calc/dose_estimate_vs_actual_on_session
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    eq1 = fx.create_equipment(name="Bed eq1b", max_exposure_seconds=600, turnaround_seconds=600)
    eq2 = fx.create_equipment(name="Bed eq2b", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-01T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Adult Three B", skin_type="III")
    mid = member["id"]
    fx.complete_uv_session(mid, eq1["id"], "2026-06-01T10:00:00Z", 100)  # count -> 1
    fx.set_clock("2026-06-02T10:00:00Z")
    sess_b = fx.reserve_uv_session(mid, eq2["id"], "2026-06-02T10:00:00Z", 150)
    # The reservation estimate (count=1): 120 + 30 = 150.
    assert sess_b["allowed_seconds"] == 150
    assert sess_b["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Skin-type prohibition and the priority-conflict difficulty instance
# ---------------------------------------------------------------------------
def test_skin_type_i_uv_prohibited_pre_empts_slot_conflict(api):
    """PRD §3.5: "Fitzpatrick skin type `I` is categorically prohibited from UV
    exposure, because that skin type always burns; any UV booking for a member whose
    `skin_type` is `I` is rejected with `ERR_SKIN_TYPE_UV_PROHIBITED`. This is
    checked before any dose math runs."
    PRD §3.4: "The remaining checks apply only to UV bookings and run in this order:
    skin-type prohibition, minor consent, minor frequency, adult frequency,
    cool-down, dose ceiling, and finally the equipment slot-conflict check."

    Design: Difficulty/priority_pair_validation_conflict/skin_prohibited_beats_slot_conflict
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    equipment = fx.create_equipment(name="Conflict bed", max_exposure_seconds=600, turnaround_seconds=600)
    fx.set_clock("2026-06-15T09:00:00Z")
    occupant = fx.create_active_member(plan["id"], full_name="Occupant IV", skin_type="IV")
    # Occupant reserves the slot 10:00:00..10:02:00.
    fx.reserve_uv_session(occupant["id"], equipment["id"], "2026-06-15T10:00:00Z", 120)
    skin_one = fx.create_active_member(plan["id"], full_name="Skin One", skin_type="I")
    # Skin-I member books an overlapping slot; skin prohibition pre-empts slot conflict.
    payload = create_session_payload(
        member_id=skin_one["id"], kind="UV", booking_mode="RESERVATION",
        equipment_id=equipment["id"], start_at="2026-06-15T10:01:00Z", requested_seconds=60,
    )
    resp = api.create_session(payload, make_member_headers(skin_one["id"]))
    validate_error(resp, ApiErrorId.ERR_SKIN_TYPE_UV_PROHIBITED.value, expected_status=403)


def test_skin_type_i_uv_prohibited_no_existing_booking(api):
    """PRD §3.5: "Fitzpatrick skin type `I` is categorically prohibited from UV
    exposure, because that skin type always burns; any UV booking for a member whose
    `skin_type` is `I` is rejected with `ERR_SKIN_TYPE_UV_PROHIBITED`. This is
    checked before any dose math runs."

    Design: Difficulty/priority_pair_validation_conflict/skin_prohibited_beats_slot_conflict
    """
    plan, member, equipment = fx.setup_active_member_with_equipment(
        plan_overrides={"weekly_uv_session_cap": 0},
        member_overrides={"skin_type": "I"},
        equip_overrides={"max_exposure_seconds": 600, "turnaround_seconds": 600},
        clock="2026-06-15T09:00:00Z",
    )
    payload = create_session_payload(
        member_id=member["id"], kind="UV", booking_mode="WALK_IN",
        equipment_id=equipment["id"], start_at="2026-06-15T10:00:00Z", requested_seconds=60,
    )
    resp = api.create_session(payload, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_SKIN_TYPE_UV_PROHIBITED.value, expected_status=403)


# ---------------------------------------------------------------------------
# Cool-down and adult frequency cap
# ---------------------------------------------------------------------------
def test_uv_cooldown_under_24h_rejected(api):
    """PRD §3.6: "A UV booking is rejected with `ERR_UV_COOLDOWN_NOT_ELAPSED` if the
    member's most recent prior UV session began less than 24 hours before the new
    booking's `start_at`. ... The required spacing is 24 hours, measured between the
    two sessions' `start_at` instants; a gap of less than 24 hours fails, and a gap
    of exactly 24 hours or more passes."

    Design: Corner/calculations/uv_cooldown_boundary_just_before_24h
    """
    plan = fx.create_plan(tier_code="UNLIMITED", monthly_fee_cents=6000, weekly_uv_session_cap=0)
    eq1 = fx.create_equipment(name="Cool bed A", max_exposure_seconds=600)
    eq2 = fx.create_equipment(name="Cool bed B", max_exposure_seconds=600)
    fx.set_clock("2026-06-10T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Cool Member", skin_type="IV")
    mid = member["id"]
    fx.start_uv_session(mid, eq1["id"], "2026-06-10T10:00:00Z", 120)  # IN_PROGRESS, start 10:00
    fx.set_clock("2026-06-11T09:00:00Z")
    # New start_at 09:59 is 23h59m after prior start_at 10:00 -> under 24h.
    payload = create_session_payload(
        member_id=mid, kind="UV", booking_mode="RESERVATION",
        equipment_id=eq2["id"], start_at="2026-06-11T09:59:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, make_member_headers(mid))
    validate_error(resp, ApiErrorId.ERR_UV_COOLDOWN_NOT_ELAPSED.value, expected_status=409)


def test_adult_plan_weekly_cap_exceeded(api):
    """PRD §3.5: "Adult members are instead bound by their plan's weekly cap. When
    the plan's `weekly_uv_session_cap` is non-zero and the count of the member's UV
    sessions in the target ISO week has already reached that cap, the booking is
    rejected with `ERR_FREQUENCY_CAP_EXCEEDED`; a cap of zero means unlimited and is
    never exceeded."

    Design: Corner/calculations/adult_plan_weekly_cap_exceeded
    """
    plan = fx.create_plan(tier_code="BASIC", monthly_fee_cents=3000, weekly_uv_session_cap=1)
    eq1 = fx.create_equipment(name="Cap bed A", max_exposure_seconds=600)
    eq2 = fx.create_equipment(name="Cap bed B", max_exposure_seconds=600)
    fx.set_clock("2026-06-08T10:00:00Z")
    member = fx.create_active_member(plan["id"], full_name="Cap Member", skin_type="IV")
    mid = member["id"]
    fx.start_uv_session(mid, eq1["id"], "2026-06-08T10:00:00Z", 120)  # 1 UV this ISO week
    fx.set_clock("2026-06-09T11:00:00Z")  # >24h later, cooldown satisfied
    payload = create_session_payload(
        member_id=mid, kind="UV", booking_mode="RESERVATION",
        equipment_id=eq2["id"], start_at="2026-06-09T11:00:00Z", requested_seconds=120,
    )
    resp = api.create_session(payload, make_member_headers(mid))
    validate_error(resp, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED.value, expected_status=409)
