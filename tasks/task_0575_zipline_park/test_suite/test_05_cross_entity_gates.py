"""Cross-entity check-in gates and validation-priority precedence (PRD §2.9, §3.5)."""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_course_slot_guide, setup_open_slot, create_participant, sign_waiver,
    create_booking, get_booking,
)

OP = TEST_USERS["operator_headers"]


# ── Booking->TimeSlot dependency: check-in requires slot OPEN ──────────────
def test_checkin_on_scheduled_slot_rejected(api):
    """PRD §3.5: "the slot must currently be `OPEN`, else the request is refused with
    `ERR_SLOT_NOT_OPEN`".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_slot_open_booking_to_timeslot
    """
    course, ts, guide = setup_course_slot_guide(api)  # slot left SCHEDULED
    p = create_participant(api)
    sign_waiver(api, p["id"], signature_name="P A")
    booking = create_booking(api, ts["id"], p["id"])
    res = api.checkin_booking(booking["id"], OP)
    validate_error(res, "ERR_SLOT_NOT_OPEN", expected_status=409)


def test_checkin_succeeds_after_slot_opened(api):
    """PRD §3.5: "Checking a booking in advances it from `CONFIRMED` to `CHECKED_IN`, and
    is gated twice: the slot must currently be `OPEN`, else the request is refused with
    `ERR_SLOT_NOT_OPEN`".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_slot_open_booking_to_timeslot
    """
    course, ts, guide = setup_course_slot_guide(api)
    p = create_participant(api)
    sign_waiver(api, p["id"], signature_name="P A")
    booking = create_booking(api, ts["id"], p["id"])
    api.open_time_slot(ts["id"], OP)
    checked = validate_success(api.checkin_booking(booking["id"], OP), 200)
    assert checked["status"] == "CHECKED_IN"


# ── Booking->Participant dependency: check-in requires waiver SIGNED ────────
def test_checkin_without_waiver_rejected(api):
    """PRD §3.5: "the participant's `waiver_status` must be `SIGNED`, else it is refused
    with `ERR_WAIVER_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_waiver_signed_booking_to_participant
    """
    course, ts, guide = setup_open_slot(api)  # slot OPEN
    p = create_participant(api)  # no waiver
    booking = create_booking(api, ts["id"], p["id"])
    res = api.checkin_booking(booking["id"], OP)
    validate_error(res, "ERR_WAIVER_REQUIRED", expected_status=422)


def test_checkin_succeeds_after_waiver_signed(api):
    """PRD §3.5: "the participant's `waiver_status` must be `SIGNED`, else it is refused
    with `ERR_WAIVER_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_waiver_signed_booking_to_participant
    """
    course, ts, guide = setup_open_slot(api)
    p = create_participant(api)
    booking = create_booking(api, ts["id"], p["id"])
    sign_waiver(api, p["id"], signature_name="P A")
    checked = validate_success(api.checkin_booking(booking["id"], OP), 200)
    assert checked["status"] == "CHECKED_IN"


# ── Priority: Safety (weight, p7) beats Fiscal (slot-full, p9) on booking ───
def _overweight_on_full_slot(api):
    """Capacity-1 slot filled by a valid booking; second participant is over max weight."""
    course, ts, guide = setup_course_slot_guide(api, capacity=1)
    fill = create_participant(api, full_name="Fill", weight_kg=70)
    create_booking(api, ts["id"], fill["id"])  # remaining -> 0
    heavy = create_participant(api, full_name="Heavy", weight_kg=130)
    return ts, heavy


def test_weight_error_beats_slot_full(api):
    """PRD §2.9: "Requests are validated in a fixed priority order, and the first failing
    check determines the error returned".
    PRD §2.9: "7. **Safety** — weight, age, waiver, and guide-certification limits are
    enforced next, each with its own error."

    Design: Difficulty/priority_pair_validation_conflict/safety_weight_beats_fiscal_slotfull_on_booking
    """
    ts, heavy = _overweight_on_full_slot(api)
    res = api.create_booking(
        {"time_slot_id": ts["id"], "participant_id": heavy["id"]}, OP)
    validate_error(res, "ERR_WEIGHT_OUT_OF_RANGE", expected_status=422)


def test_slot_full_is_masked_by_weight_error(api):
    """PRD §2.9: "9. **Fiscal/capacity constraints** — seat availability and season-pass
    validity/exhaustion are enforced."
    PRD §2.9: "a state error surfaces before any safety or capacity error on the same
    request."

    Design: Difficulty/priority_pair_validation_conflict/safety_weight_beats_fiscal_slotfull_on_booking
    """
    ts, heavy = _overweight_on_full_slot(api)
    res = api.create_booking(
        {"time_slot_id": ts["id"], "participant_id": heavy["id"]}, OP)
    body = res.json()["data"]
    assert body["error_id"] != "ERR_SLOT_FULL"
    assert res.status_code == 422


# ── Priority: State (slot-not-open, p6) beats Safety (waiver, p7) on check-in ─
def _no_waiver_on_scheduled_slot(api):
    """SCHEDULED slot + booking whose participant has no waiver (both gates would fail)."""
    course, ts, guide = setup_course_slot_guide(api)  # slot SCHEDULED
    p = create_participant(api)  # no waiver
    booking = create_booking(api, ts["id"], p["id"])
    return booking


def test_slot_not_open_beats_waiver_required(api):
    """PRD §3.5: "Because state is checked before safety, a check-in against a non-open
    slot surfaces the slot error before the waiver error."

    Design: Difficulty/priority_pair_validation_conflict/state_slotnotopen_beats_safety_waiver_on_checkin
    """
    booking = _no_waiver_on_scheduled_slot(api)
    res = api.checkin_booking(booking["id"], OP)
    validate_error(res, "ERR_SLOT_NOT_OPEN", expected_status=409)


def test_waiver_error_is_masked_by_slot_state(api):
    """PRD §3.5: "Because state is checked before safety, a check-in against a non-open
    slot surfaces the slot error before the waiver error."

    Design: Difficulty/priority_pair_validation_conflict/state_slotnotopen_beats_safety_waiver_on_checkin
    """
    booking = _no_waiver_on_scheduled_slot(api)
    res = api.checkin_booking(booking["id"], OP)
    body = res.json()["data"]
    assert body["error_id"] != "ERR_WAIVER_REQUIRED"
    assert res.status_code == 409
