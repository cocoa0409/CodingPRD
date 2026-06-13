"""Slot-permit lifecycle: confirm, redeem (compliance window), forfeit branch,
slot uniqueness, and invalid-state lockdown.

Queue A: dual_variant_calc (slot ARRIVAL variant at upper boundary),
non_linear_state_machine (CONFIRMED -> FORFEITED branch),
boundary_precision_check (clock one past upper bound).
Queue B: confirm_slot_from_used_returns_invalid_state, slot_double_booked_on_confirm.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures

SLOT = TEST_USERS["slot_coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: ARRIVAL window, clock at inclusive upper boundary
# ---------------------------------------------------------------------------
def test_redeem_arrival_slot_at_upper_boundary_succeeds(api):
    """PRD §3.7: "The redemption is compliant when current_utc is at or after the
    lower edge and at or before the upper edge — both boundaries are inclusive, so
    a clock sitting exactly on either edge passes. When compliant, the permit moves
    to USED."

    Design: Difficulty/dual_variant_calc/slot_compliance_arrival_vs_departure_variant_on_slotpermit
    """
    flight, permit = fixtures.setup_confirmed_slot_permit(
        flight_kwargs={"flight_no": "DL11", "aircraft_wingspan_m": 50,
                       "sched_arrival_utc": "2026-06-10T12:00:00Z",
                       "sched_departure_utc": "2026-06-10T13:00:00Z"},
        movement_type="ARRIVAL", slot_time_utc="2026-06-10T12:00:00Z", tolerance_minutes=15)
    fixtures.set_clock("2026-06-10T12:15:00Z")  # inclusive upper boundary of [11:45,12:15]
    data = validate_success(api.redeem_slot_permit(permit["id"], SLOT), 200)
    assert data["status"] == "USED"


def test_redeem_arrival_slot_at_lower_boundary_succeeds(api):
    """PRD §3.7: "The redemption is compliant when current_utc is at or after the
    lower edge and at or before the upper edge — both boundaries are inclusive, so
    a clock sitting exactly on either edge passes. When compliant, the permit moves
    to USED."

    Design: Difficulty/dual_variant_calc/slot_compliance_arrival_vs_departure_variant_on_slotpermit
    """
    flight, permit = fixtures.setup_confirmed_slot_permit(
        flight_kwargs={"flight_no": "DL12", "aircraft_wingspan_m": 50,
                       "sched_arrival_utc": "2026-06-10T12:00:00Z",
                       "sched_departure_utc": "2026-06-10T13:00:00Z"},
        movement_type="ARRIVAL", slot_time_utc="2026-06-10T12:00:00Z", tolerance_minutes=15)
    fixtures.set_clock("2026-06-10T11:45:00Z")  # inclusive lower boundary of [11:45,12:15]
    data = validate_success(api.redeem_slot_permit(permit["id"], SLOT), 200)
    assert data["status"] == "USED"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check: clock one minute past upper bound -> miss
# ---------------------------------------------------------------------------
def test_redeem_one_minute_past_upper_bound_rejected(api):
    """PRD §3.7: "When the clock lies outside that closed window, the redemption is
    rejected with ERR_SLOT_WINDOW_MISSED (HTTP 422) and the permit remains
    CONFIRMED, from which it may subsequently be forfeited."

    Design: Difficulty/boundary_precision_check/slot_window_upper_boundary_inclusive_vs_one_past
    """
    flight, permit = fixtures.setup_confirmed_slot_permit(
        flight_kwargs={"flight_no": "SQ6", "aircraft_wingspan_m": 50,
                       "sched_arrival_utc": "2026-06-10T12:00:00Z",
                       "sched_departure_utc": "2026-06-10T13:00:00Z"},
        movement_type="ARRIVAL", slot_time_utc="2026-06-10T12:00:00Z", tolerance_minutes=15)
    fixtures.set_clock("2026-06-10T12:16:00Z")  # one minute past 12:15 upper bound
    resp = api.redeem_slot_permit(permit["id"], SLOT)
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_MISSED.value, 422)
    after = validate_success(api.get_slot_permit(permit["id"], SLOT), 200)
    assert after["status"] == "CONFIRMED"


def test_missed_window_permit_can_still_be_forfeited(api):
    """PRD §3.7: "When the clock lies outside that closed window, the redemption is
    rejected with ERR_SLOT_WINDOW_MISSED (HTTP 422) and the permit remains
    CONFIRMED, from which it may subsequently be forfeited."

    Design: Difficulty/boundary_precision_check/slot_window_upper_boundary_inclusive_vs_one_past
    """
    flight, permit = fixtures.setup_confirmed_slot_permit(
        flight_kwargs={"flight_no": "SQ7", "aircraft_wingspan_m": 50,
                       "sched_arrival_utc": "2026-06-10T12:00:00Z",
                       "sched_departure_utc": "2026-06-10T13:00:00Z"},
        movement_type="ARRIVAL", slot_time_utc="2026-06-10T12:00:00Z", tolerance_minutes=15)
    fixtures.set_clock("2026-06-10T12:16:00Z")  # one minute past 12:15 upper bound
    resp = api.redeem_slot_permit(permit["id"], SLOT)
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_MISSED.value, 422)
    # permit still CONFIRMED -> forfeit is allowed from this state.
    data = validate_success(api.forfeit_slot_permit(permit["id"], SLOT), 200)
    assert data["status"] == "FORFEITED"


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: CONFIRMED -> FORFEITED branch
# ---------------------------------------------------------------------------
def test_forfeit_confirmed_slot_lands_forfeited(api):
    """PRD §3.6: "Forfeiting the permit moves it from CONFIRMED to FORFEITED, which
    is the explicit relinquishment branch: it is permitted whenever the permit is
    CONFIRMED, and it frees the slot for re-coordination rather than consuming it."

    Design: Difficulty/non_linear_state_machine/slotpermit_branch_confirmed_to_forfeited
    """
    flight, permit = fixtures.setup_confirmed_slot_permit(
        flight_kwargs={"flight_no": "LH3", "aircraft_wingspan_m": 50,
                       "sched_arrival_utc": "2026-06-10T09:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z"},
        movement_type="DEPARTURE", slot_time_utc="2026-06-10T10:00:00Z", tolerance_minutes=10)
    data = validate_success(api.forfeit_slot_permit(permit["id"], SLOT), 200)
    assert data["status"] == "FORFEITED"


def test_forfeit_branch_diverges_from_used(api):
    """PRD §3.6: "From CONFIRMED the permit branches two ways with deliberately
    divergent outcomes."
    PRD §3.6: "Forfeiting the permit moves it from CONFIRMED to FORFEITED."

    Design: Difficulty/non_linear_state_machine/slotpermit_branch_confirmed_to_forfeited
    """
    flight, permit = fixtures.setup_confirmed_slot_permit(
        flight_kwargs={"flight_no": "LH4", "aircraft_wingspan_m": 50,
                       "sched_arrival_utc": "2026-06-10T09:00:00Z",
                       "sched_departure_utc": "2026-06-10T10:00:00Z"},
        movement_type="DEPARTURE", slot_time_utc="2026-06-10T10:00:00Z", tolerance_minutes=10)
    data = validate_success(api.forfeit_slot_permit(permit["id"], SLOT), 200)
    assert data["status"] == "FORFEITED"
    assert data["status"] != "USED"


# ---------------------------------------------------------------------------
# Queue B — confirm a USED permit -> ERR_INVALID_STATE
# ---------------------------------------------------------------------------
def test_confirm_slot_from_used_returns_invalid_state(api):
    """PRD §3.6: "Confirming a permit moves it from REQUESTED to CONFIRMED and is
    permitted only when the permit is currently REQUESTED."
    PRD §3.6: "Each of confirm, redeem, forfeit, and cancel requires its specific
    from-state; an attempt from any other state is an ERR_INVALID_STATE rejection."

    Design: Corner/state_machines/confirm_slot_from_used_returns_invalid_state
    """
    flight, permit = fixtures.setup_confirmed_slot_permit(
        flight_kwargs={"flight_no": "SM1", "aircraft_wingspan_m": 50,
                       "sched_arrival_utc": "2026-06-10T12:00:00Z",
                       "sched_departure_utc": "2026-06-10T13:00:00Z"},
        movement_type="ARRIVAL", slot_time_utc="2026-06-10T12:00:00Z", tolerance_minutes=15)
    fixtures.set_clock("2026-06-10T12:00:00Z")
    used = validate_success(api.redeem_slot_permit(permit["id"], SLOT), 200)
    assert used["status"] == "USED"
    resp = api.confirm_slot_permit(permit["id"], SLOT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Queue B — slot uniqueness on confirm -> ERR_SLOT_DOUBLE_BOOKED
# ---------------------------------------------------------------------------
def test_slot_double_booked_on_confirm(api):
    """PRD §3.6: "Confirmation additionally enforces slot uniqueness: no other slot
    permit governing the same movement_type at the same slot_time_utc minute may
    already hold CONFIRMED or USED status. A confirmation that would collide with
    such a permit is rejected with ERR_SLOT_DOUBLE_BOOKED (HTTP 409)."

    Design: Corner/validations/slot_double_booked_on_confirm
    """
    f1 = fixtures.create_flight(
        flight_no="SD1", aircraft_wingspan_m=50,
        sched_arrival_utc="2026-06-10T12:00:00Z",
        sched_departure_utc="2026-06-10T13:00:00Z")
    f2 = fixtures.create_flight(
        flight_no="SD2", aircraft_wingspan_m=50,
        sched_arrival_utc="2026-06-10T12:00:00Z",
        sched_departure_utc="2026-06-10T13:00:00Z")
    p1 = fixtures.create_slot_permit(f1["id"], "ARRIVAL", "2026-06-10T12:00:00Z", 15)
    validate_success(api.confirm_slot_permit(p1["id"], SLOT), 200)
    p2 = fixtures.create_slot_permit(f2["id"], "ARRIVAL", "2026-06-10T12:00:00Z", 15)
    resp = api.confirm_slot_permit(p2["id"], SLOT)
    validate_error(resp, ApiErrorId.ERR_SLOT_DOUBLE_BOOKED.value, 409)
