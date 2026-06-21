"""Gate-out fulfilment: the depth-3 cascade (appointment -> container ->
slot+invoice), the customs-cleared cross-entity guard, the stacked-over
retrieval guard, and the invalid-state-beats-stacking precedence.

Difficulty instances: transitive_cascade (fulfill cascade),
cross_entity_state_dependency (gate-out blocked until cleared),
priority_pair_validation_conflict (invalid-state beats stacking). Corner
instance: retrieve-box-with-box-on-top stacking violation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["terminal_admin_headers"]
BERTH = TEST_USERS["berth_planner_headers"]
YARD = TEST_USERS["yard_planner_headers"]
GATE = TEST_USERS["gate_operator_headers"]
CUSTOMS = TEST_USERS["customs_officer_headers"]


def _setup_8day_arrived(code, imo, cnum, slot_block):
    """Provision a cleared, grounded container with an ARRIVED appointment where
    the clock sits 7d12h past free-time expiry (8 chargeable days). Returns
    (container, slot, appointment)."""
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code=code, length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number=imo, loa_m=300, draft_m=14.0, free_time_days=5)
    window = fx.create_scheduled_window(berth["id"], vessel["id"], etd="2026-02-25T00:00:00.000Z")
    fx.berth_window(window)
    container = fx.declare_container(vessel["id"], window["id"], container_number=cnum)
    slot = fx.create_yard_slot(block=slot_block)
    fx.ground_container(container["id"], slot["id"])
    fx.customs_clear(container["id"])
    fx.set_clock("2026-02-13T12:00:00.000Z")
    appt = fx.book_appointment(
        container["id"], window_start="2026-02-13T12:00:00.000Z", window_end="2026-02-13T13:00:00.000Z"
    )
    fx.get_success_data(fx.api_client.check_in_gate_appointment(appt["id"], GATE))
    return container, slot, appt


# --------------------------------------------------------------------------- #
# Depth-3 fulfill cascade — transitive_cascade
# --------------------------------------------------------------------------- #
def test_fulfill_cascade_frees_slot_and_mints_invoice(api):
    """PRD §3.4: "the system recomputes the container's `demurrage_due_cents` ...
    sets the container's `handling_status` to `GATED_OUT`, frees the vacated yard
    slot by clearing its `occupied_by_container_id` to null and returning its
    `status` to `EMPTY`, clears the container's `yard_slot_id` to null, sets the
    appointment's `status` to `FULFILLED`, ... and creates one demurrage invoice
    whose `amount_cents` is frozen from the container's just-computed
    `demurrage_due_cents`".

    Design: Difficulty/transitive_cascade/fulfill_gateout_invoice_slot_free_cascade
    """
    container, slot, appt = _setup_8day_arrived("B-7", "1000007", "CASC7000070", "A7")
    fx.get_success_data(api.fulfill_gate_appointment(appt["id"], {"condition": "SOUND"}, GATE))

    cont_after = validate_success(api.get_container(container["id"], YARD), 200)
    assert cont_after["handling_status"] == "GATED_OUT"
    assert cont_after["yard_slot_id"] is None

    slot_after = validate_success(api.get_yard_slot(slot["id"], YARD), 200)
    assert slot_after["status"] == "EMPTY"
    assert slot_after["occupied_by_container_id"] is None

    invoice = fx.get_only_invoice(container["id"])
    assert invoice["amount_cents"] == 59000


def test_fulfill_marks_appointment_fulfilled_and_invoice_issued(api):
    """PRD §3.4: "The climactic gate action is the **fulfilment** that drives a
    container out of the terminal, advancing the container's handling state from
    `GROUNDED` to the terminal `GATED_OUT` and the appointment from `ARRIVED` to
    `FULFILLED`."
    PRD §3.6: "the invoice names the `container_id` it bills, copies the computed
    `chargeable_days`, freezes the computed `amount_cents`, and opens in `ISSUED`
    status."

    Design: Difficulty/transitive_cascade/fulfill_gateout_invoice_slot_free_cascade
    """
    container, slot, appt = _setup_8day_arrived("B-7b", "1000077", "CASC7000077", "A7b")
    fulfilled = validate_success(
        api.fulfill_gate_appointment(appt["id"], {"condition": "SOUND"}, GATE), 200
    )
    assert fulfilled["status"] == "FULFILLED"
    invoice = fx.get_only_invoice(container["id"])
    assert invoice["status"] == "ISSUED"
    assert invoice["chargeable_days"] == 8
    assert invoice["amount_cents"] == 59000


# --------------------------------------------------------------------------- #
# Cross-entity guard — gate-out blocked until customs cleared
# --------------------------------------------------------------------------- #
def test_gateout_blocked_while_held(api):
    """PRD §3.4: "the container's `customs_status` must be `CLEARED`, because a
    `HELD` or `PENDING` container cannot leave the terminal — a non-cleared
    container is rejected with `ERR_CROSS_ENTITY_STATE`".

    Design: Difficulty/cross_entity_state_dependency/gateout_blocked_until_container_customs_cleared
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    container, slot, hold = fx.setup_held_container(free_time_days=60)
    appt = fx.book_appointment(
        container["id"], window_start="2026-02-02T10:00:00.000Z", window_end="2026-02-02T11:00:00.000Z"
    )
    fx.set_clock("2026-02-02T10:30:00.000Z")
    fx.get_success_data(api.check_in_gate_appointment(appt["id"], GATE))
    resp = api.fulfill_gate_appointment(appt["id"], {"condition": "SOUND"}, GATE)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE.value)
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["handling_status"] == "GROUNDED"


def test_gateout_blocked_while_held_appointment_stays_arrived(api):
    """PRD §3.4: "the container's `customs_status` must be `CLEARED`, because a
    `HELD` or `PENDING` container cannot leave the terminal — a non-cleared
    container is rejected with `ERR_CROSS_ENTITY_STATE`".

    Design: Difficulty/cross_entity_state_dependency/gateout_blocked_until_container_customs_cleared
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    container, slot, hold = fx.setup_held_container(free_time_days=60)
    appt = fx.book_appointment(
        container["id"], window_start="2026-02-02T10:00:00.000Z", window_end="2026-02-02T11:00:00.000Z"
    )
    fx.set_clock("2026-02-02T10:30:00.000Z")
    fx.get_success_data(api.check_in_gate_appointment(appt["id"], GATE))
    validate_error(
        api.fulfill_gate_appointment(appt["id"], {"condition": "SOUND"}, GATE),
        ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
    )
    appt_after = validate_success(api.get_gate_appointment(appt["id"], GATE), 200)
    assert appt_after["status"] == "ARRIVED"


# --------------------------------------------------------------------------- #
# Stacked-over retrieval guard + invalid-state precedence
# --------------------------------------------------------------------------- #
def _setup_stacked_pair(code, imo, bottom_num, top_num, block, with_arrived):
    """Bottom container grounded tier 1, top container grounded tier 2 above it.
    Bottom is cleared. If with_arrived, an ARRIVED appointment exists for the
    bottom container; otherwise a BOOKED (un-arrived) one. Returns (bottom, appt)."""
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code=code, length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number=imo, loa_m=300, draft_m=14.0, free_time_days=60)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    fx.berth_window(window)
    bottom = fx.declare_container(vessel["id"], window["id"], container_number=bottom_num)
    top = fx.declare_container(vessel["id"], window["id"], container_number=top_num)
    slot1 = fx.create_yard_slot(block=block, bay=1, row=1, tier=1)
    slot2 = fx.create_yard_slot(block=block, bay=1, row=1, tier=2, below_slot_id=slot1["id"])
    fx.ground_container(bottom["id"], slot1["id"])
    fx.ground_container(top["id"], slot2["id"])
    fx.customs_clear(bottom["id"])
    appt = fx.book_appointment(
        bottom["id"], window_start="2026-02-02T10:00:00.000Z", window_end="2026-02-02T11:00:00.000Z"
    )
    if with_arrived:
        fx.set_clock("2026-02-02T10:30:00.000Z")
        fx.get_success_data(fx.api_client.check_in_gate_appointment(appt["id"], GATE))
    return bottom, appt


def test_retrieve_box_with_box_on_top_stacking_violation(api):
    """PRD §3.4: "no other slot whose `below_slot_id` names this container's
    `yard_slot_id` may be `OCCUPIED`, because a box cannot be retrieved while
    another box is stacked directly on top of it — a stacked-over retrieval is
    rejected with `ERR_STACKING_VIOLATION`."

    Design: Corner/validations/retrieve_box_with_box_on_top_stacking_violation
    """
    bottom, appt = _setup_stacked_pair("B-520", "2000320", "BTM2520520", "TOP2520521", "R", with_arrived=True)
    resp = api.fulfill_gate_appointment(appt["id"], {"condition": "SOUND"}, GATE)
    validate_error(resp, ApiErrorId.ERR_STACKING_VIOLATION.value)


def test_invalid_state_beats_stacking_on_gateout(api):
    """PRD §3.4: "the appointment must be `ARRIVED` and the container must be
    `GROUNDED`, failing which the relevant `ERR_INVALID_STATE` applies; ... and no
    other slot whose `below_slot_id` names this container's `yard_slot_id` may be
    `OCCUPIED` ... rejected with `ERR_STACKING_VIOLATION`."
    PRD §2.8: "Only then are state-machine preconditions and the deeper business
    rules of §3 evaluated."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_stacking_on_gateout
    """
    # Appointment left BOOKED (not ARRIVED) AND a box stacked above the bottom.
    bottom, appt = _setup_stacked_pair("B-9", "1000009", "BTM9000090", "TOP9000091", "B", with_arrived=False)
    resp = api.fulfill_gate_appointment(appt["id"], {"condition": "SOUND"}, GATE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_beats_stacking_container_unchanged(api):
    """PRD §3.4: "the appointment must be `ARRIVED` and the container must be
    `GROUNDED`, failing which the relevant `ERR_INVALID_STATE` applies".
    PRD §2.8: "Only then are state-machine preconditions and the deeper business
    rules of §3 evaluated."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_stacking_on_gateout
    """
    bottom, appt = _setup_stacked_pair("B-9c", "1000099", "BTM9000099", "TOP9000098", "Bc", with_arrived=False)
    validate_error(
        api.fulfill_gate_appointment(appt["id"], {"condition": "SOUND"}, GATE),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    after = validate_success(api.get_container(bottom["id"], YARD), 200)
    assert after["handling_status"] == "GROUNDED"
