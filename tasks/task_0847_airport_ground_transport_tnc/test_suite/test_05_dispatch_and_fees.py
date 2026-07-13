"""Dispatch guards and provisional/final trip-fee accounting."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_operator_headers,
    set_clock, create_operator, register_vehicle, issue_permit, create_lot,
    queue_vehicle, setup_queued_vehicle, setup_completed_trip,
    dispatch_trip, transition_trip,
)

AA = TEST_USERS["airport_authority_headers"]


# --- dual_variant_calc: provisional vs final divergence -------------------
def test_provisional_fee_keys_off_dispatch_hour(api):
    """PRD §3.5: "The provisional variant runs at dispatch and is stored in
    `provisional_fee_cents`, taking its reference instant from `dispatch_ts`; the
    final variant runs at completion and is stored in `final_fee_cents`, taking its
    reference instant from `pickup_ts`."
    PRD §3.5: "a base fare selected by the operator's `operator_type` — 350 cents
    for `TNC`, 300 cents for `TAXI`, 500 cents for `LIMO`, and 200 cents for
    `SHUTTLE`."

    Design: Difficulty/dual_variant_calc/trip_fee_provisional_vs_final_diverge
    """
    ctx = setup_queued_vehicle(api, operator_type="TNC", clock="2026-04-01T15:55:00Z", avi_tag="AVI-1")
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="PICKUP", is_wheelchair_trip=False)
    assert trip["provisional_fee_cents"] == 350, (
        f"TNC off-peak (hour 15) provisional should be 350, got {trip['provisional_fee_cents']}"
    )


def test_final_fee_keys_off_pickup_hour_and_diverges(api):
    """PRD §3.5: "Because the actual pickup hour can cross a peak boundary the
    dispatch hour did not, the final fee can differ from the provisional fee for
    otherwise identical trip inputs."
    PRD §3.5: "That base is multiplied by a peak multiplier of 1.5 when the
    whole-hour UTC hour of the reference instant is one of 07, 08, 09, 16, 17, or
    18, and by 1.0 in every other hour; the product of base and multiplier is
    rounded half-up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/trip_fee_provisional_vs_final_diverge
    """
    ctx = setup_queued_vehicle(api, operator_type="TNC", clock="2026-04-01T15:55:00Z", avi_tag="AVI-1")
    op_id = ctx["operator"]["id"]
    trip = dispatch_trip(api, op_id, ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="PICKUP", is_wheelchair_trip=False)
    assert trip["provisional_fee_cents"] == 350
    set_clock(api, "2026-04-01T16:10:00Z")  # pickup crosses into peak hour 16
    transition_trip(api, op_id, trip["id"], "PICKUP")
    completed = transition_trip(api, op_id, trip["id"], "COMPLETE")
    assert completed["final_fee_cents"] == 525, (
        f"TNC peak (hour 16) final should be 525, got {completed['final_fee_cents']}"
    )
    assert completed["final_fee_cents"] != completed["provisional_fee_cents"], (
        "final should diverge from provisional across the peak boundary"
    )


# --- combinatorial_formula: peak * WAV * floor ----------------------------
def test_final_fee_peak_wav_no_floor(api):
    """PRD §3.5: "If the trip served a wheelchair passenger (`is_wheelchair_trip`
    true), a wheelchair discount of 100 cents is then subtracted from that rounded
    gross; otherwise nothing is subtracted. The resulting fee is finally raised, if
    necessary, to a floor of 200 cents — the fee charged is the greater of 200 cents
    and the discounted gross."

    Design: Difficulty/combinatorial_formula/trip_fee_peak_wav_floor_mode_a
    """
    ctx = setup_queued_vehicle(api, operator_type="TNC", clock="2026-04-02T16:00:00Z",
                               wav_vehicle=True, avi_tag="AVI-2")
    op_id = ctx["operator"]["id"]
    trip = dispatch_trip(api, op_id, ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="PICKUP", is_wheelchair_trip=True)
    transition_trip(api, op_id, trip["id"], "PICKUP")
    completed = transition_trip(api, op_id, trip["id"], "COMPLETE")
    # round_half_up(350 * 1.5) = 525; 525 - 100 WAV = 425; max(200, 425) = 425
    assert completed["final_fee_cents"] == 425, (
        f"TNC peak WAV should be 425, got {completed['final_fee_cents']}"
    )


def test_provisional_fee_peak_wav_no_floor(api):
    """PRD §3.5: "If the trip served a wheelchair passenger (`is_wheelchair_trip`
    true), a wheelchair discount of 100 cents is then subtracted from that rounded
    gross; otherwise nothing is subtracted. The resulting fee is finally raised, if
    necessary, to a floor of 200 cents — the fee charged is the greater of 200 cents
    and the discounted gross."

    Design: Difficulty/combinatorial_formula/trip_fee_peak_wav_floor_mode_a
    """
    ctx = setup_queued_vehicle(api, operator_type="TNC", clock="2026-04-02T16:00:00Z",
                               wav_vehicle=True, avi_tag="AVI-2b")
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="PICKUP", is_wheelchair_trip=True)
    assert trip["provisional_fee_cents"] == 425, (
        f"TNC peak WAV provisional should be 425, got {trip['provisional_fee_cents']}"
    )


# --- deadhead / floor / immediate provisional (corner) --------------------
def test_deadhead_trip_flat_fee(api):
    """PRD §3.5: "A `DEADHEAD` trip is charged a flat 100 cents regardless of any
    other factor."

    Design: Corner/calculations/deadhead_trip_flat_fee
    """
    ctx = setup_queued_vehicle(api, operator_type="LIMO", clock="2026-04-09T16:00:00Z", avi_tag="AVI-DHV1")
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="DEADHEAD")
    assert trip["provisional_fee_cents"] == 100, (
        f"DEADHEAD flat fee should be 100, got {trip['provisional_fee_cents']}"
    )


def test_trip_fee_floor_engaged(api):
    """PRD §3.5: "The resulting fee is finally raised, if necessary, to a floor of
    200 cents — the fee charged is the greater of 200 cents and the discounted
    gross."

    Design: Corner/calculations/trip_fee_floor_engaged
    """
    ctx = setup_queued_vehicle(api, operator_type="SHUTTLE", clock="2026-04-11T12:00:00Z",
                               wav_vehicle=True, avi_tag="AVI-FLV1")
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="PICKUP", is_wheelchair_trip=True)
    # SHUTTLE off-peak 200 * 1.0 = 200; 200 - 100 WAV = 100; max(200, 100) = 200
    assert trip["provisional_fee_cents"] == 200, (
        f"SHUTTLE off-peak WAV floored should be 200, got {trip['provisional_fee_cents']}"
    )


def test_dispatch_returns_provisional_fee_immediately(api):
    """PRD §3.4: "Dispatch creates a trip in `DISPATCHED` status, copies the
    `operator_id` from the dispatched vehicle, stamps `dispatch_ts` from the logical
    clock, computes and stores the provisional fee in `provisional_fee_cents`, and
    releases the vehicle's head queue entry (`WAITING → RELEASED`) with the
    consequent FIFO renumber."

    Design: Corner/consistency_model/dispatch_returns_provisional_fee_immediately
    """
    ctx = setup_queued_vehicle(api, operator_type="TAXI", clock="2026-04-16T12:00:00Z", avi_tag="AVI-IMV1")
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="PICKUP")
    assert trip["provisional_fee_cents"] == 300, (
        f"TAXI off-peak provisional should be 300 on the create response, got {trip['provisional_fee_cents']}"
    )


# --- pickup on a completed trip (corner invalid transition) ---------------
def test_pickup_completed_trip_returns_invalid_state(api):
    """PRD §3.4: "any action requested from an incompatible trip state is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pickup_completed_trip_returns_invalid_state
    """
    ctx = setup_completed_trip(api, operator_type="TNC", clock="2026-04-03T12:00:00Z", avi_tag="AVI-IV1")
    resp = api.transition_trip(
        ctx["trip"]["id"], {"action": "PICKUP"}, make_operator_headers(ctx["operator"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# --- priority pair: permit-invalid beats not-queue-head -------------------
def _two_queued_vehicles(api, *, expire_b: bool, clock: str, tag_a: str, tag_b: str):
    set_clock(api, clock)
    op = create_operator(api, operator_type="TNC", legal_name="Head Co", activate=True)
    lot = create_lot(api)
    va = register_vehicle(api, op["id"], plate="A")
    issue_permit(api, va["id"], va["version"], avi_tag_id=tag_a, activate=True)
    vb = register_vehicle(api, op["id"], plate="B")
    pb = issue_permit(api, vb["id"], vb["version"], avi_tag_id=tag_b, activate=True)
    queue_vehicle(api, op["id"], lot["id"], va["id"])  # A -> position 1 (head)
    queue_vehicle(api, op["id"], lot["id"], vb["id"])  # B -> position 2
    if expire_b:
        validate_success(api.transition_permit(pb["id"], {"action": "EXPIRE"}, AA))
    return op, lot, vb


def test_dispatch_non_head_with_expired_permit_permit_error_wins(api):
    """PRD §3.4: "the vehicle must be `ACTIVE` (else `ERR_VEHICLE_NOT_ACTIVE`); then
    the owning operator must be `ACTIVE` (else `ERR_OPERATOR_NOT_ACTIVE`); then the
    vehicle must hold an `ACTIVE` permit (else `ERR_VEHICLE_PERMIT_INVALID`); and
    finally the vehicle's `WAITING` queue entry must be at `position` 1, the head of
    its lot (else `ERR_NOT_QUEUE_HEAD`)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_permit_invalid_beats_not_queue_head
    """
    op, lot, vb = _two_queued_vehicles(api, expire_b=True, clock="2026-04-10T10:00:00Z",
                                       tag_a="AVI-A", tag_b="AVI-B")
    resp = api.create_trip(
        {"vehicle_id": vb["id"], "staging_lot_id": lot["id"], "trip_kind": "PICKUP"},
        make_operator_headers(op["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_PERMIT_INVALID.value, 409)


def test_dispatch_non_head_with_valid_permit_returns_not_queue_head(api):
    """PRD §3.4: "the vehicle must be `ACTIVE` (else `ERR_VEHICLE_NOT_ACTIVE`); then
    the owning operator must be `ACTIVE` (else `ERR_OPERATOR_NOT_ACTIVE`); then the
    vehicle must hold an `ACTIVE` permit (else `ERR_VEHICLE_PERMIT_INVALID`); and
    finally the vehicle's `WAITING` queue entry must be at `position` 1, the head of
    its lot (else `ERR_NOT_QUEUE_HEAD`)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_permit_invalid_beats_not_queue_head
    """
    op, lot, vb = _two_queued_vehicles(api, expire_b=False, clock="2026-04-10T10:00:00Z",
                                       tag_a="AVI-A2", tag_b="AVI-B2")
    resp = api.create_trip(
        {"vehicle_id": vb["id"], "staging_lot_id": lot["id"], "trip_kind": "PICKUP"},
        make_operator_headers(op["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_QUEUE_HEAD.value, 409)


# --- cross-entity: dispatch requires operator ACTIVE ----------------------
def test_dispatch_pending_operator_returns_operator_not_active(api):
    """PRD §3.4: "the vehicle must be `ACTIVE` (else `ERR_VEHICLE_NOT_ACTIVE`); then
    the owning operator must be `ACTIVE` (else `ERR_OPERATOR_NOT_ACTIVE`); then the
    vehicle must hold an `ACTIVE` permit (else `ERR_VEHICLE_PERMIT_INVALID`); and
    finally the vehicle's `WAITING` queue entry must be at `position` 1, the head of
    its lot (else `ERR_NOT_QUEUE_HEAD`)."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_operator_active
    """
    set_clock(api, "2026-04-15T10:00:00Z")
    op = create_operator(api, operator_type="TNC", legal_name="Pend Co")  # left PENDING
    veh = register_vehicle(api, op["id"], plate="PV1")
    issue_permit(api, veh["id"], veh["version"], avi_tag_id="AVI-PV1", activate=True)
    lot = create_lot(api)
    queue_vehicle(api, op["id"], lot["id"], veh["id"])
    resp = api.create_trip(
        {"vehicle_id": veh["id"], "staging_lot_id": lot["id"], "trip_kind": "PICKUP"},
        make_operator_headers(op["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OPERATOR_NOT_ACTIVE.value, 409)


def test_dispatch_active_operator_succeeds(api):
    """PRD §3.4: "the vehicle must be `ACTIVE` (else `ERR_VEHICLE_NOT_ACTIVE`); then
    the owning operator must be `ACTIVE` (else `ERR_OPERATOR_NOT_ACTIVE`); then the
    vehicle must hold an `ACTIVE` permit (else `ERR_VEHICLE_PERMIT_INVALID`); and
    finally the vehicle's `WAITING` queue entry must be at `position` 1, the head of
    its lot (else `ERR_NOT_QUEUE_HEAD`)."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_operator_active
    """
    ctx = setup_queued_vehicle(api, operator_type="TNC", clock="2026-04-15T10:00:00Z", avi_tag="AVI-PV2")
    trip = dispatch_trip(api, ctx["operator"]["id"], ctx["vehicle"]["id"], ctx["lot"]["id"],
                         trip_kind="PICKUP")
    assert trip["status"] == "DISPATCHED", (
        f"an ACTIVE operator's head vehicle should dispatch, got {trip['status']}"
    )
