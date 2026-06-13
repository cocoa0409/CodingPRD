"""Booking lifecycle transitions, the two parallel state axes, the cyclic
reschedule negotiation, version-increment discipline, and invalid-state guards.

Translates difficulty rules `non_linear_state_machine` and the
`confirm_blocked_when_coordinator_unassigned` cross-entity instance, plus corner
`state_machines` and `cross_cutting` version instances.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_reschedule_payload,
    create_payment_payload,
    create_hold_payload,
    create_inventory,
    create_inquiry_booking,
    add_both_holds,
    place_soft_hold,
    pay_deposit,
    confirm,
    setup_confirmed_booking,
    setup_held_booking,
    get_holds,
)

FO = TEST_USERS["finance_officer_headers"]

# Convenient block-time tuples for reschedule rounds.
_R1 = ("2026-10-10", "2026-10-10T20:00:00Z", "2026-10-10T21:00:00Z",
       "2026-10-10T21:00:00Z", "2026-10-11T02:00:00Z")
_R2 = ("2026-10-17", "2026-10-17T20:00:00Z", "2026-10-17T21:00:00Z",
       "2026-10-17T21:00:00Z", "2026-10-18T02:00:00Z")
_R3 = ("2026-10-24", "2026-10-24T20:00:00Z", "2026-10-24T21:00:00Z",
       "2026-10-24T21:00:00Z", "2026-10-25T02:00:00Z")


# ───────────── Rule 3: cyclic reschedule negotiation ─────────────

def test_reschedule_supersede_withdraws_prior_and_reopens_proposed(api):
    """PRD §3.10: "The client may answer a counter by re-proposing a new round whose
    `supersedes_request_id` points at the countered request; doing so withdraws the
    superseded request (its `request_status` becomes `WITHDRAWN`) and opens a fresh
    `PROPOSED` round".

    Design: Difficulty/non_linear_state_machine/reschedule_request_negotiation_cycle
    """
    inv, booking = setup_confirmed_booking()
    client_h = inv["client_headers"]
    coord_h = inv["coord_headers"]
    req1 = get_success_data(api.create_reschedule_request(
        booking["id"], create_reschedule_payload("CLIENT_REQUEST", *_R1), client_h))
    get_success_data(api.counter_reschedule(
        req1["id"],
        {"proposed_event_date": _R2[0], "proposed_ceremony_start": _R2[1],
         "proposed_ceremony_end": _R2[2], "proposed_reception_start": _R2[3],
         "proposed_reception_end": _R2[4]},
        coord_h))
    payload = create_reschedule_payload("CLIENT_REQUEST", *_R3)
    payload["supersedes_request_id"] = req1["id"]
    req2 = get_success_data(api.create_reschedule_request(booking["id"], payload, client_h))

    req1_now = get_success_data(api.get_reschedule_request(req1["id"], coord_h))
    assert req1_now["request_status"] == "WITHDRAWN"
    assert req2["request_status"] == "PROPOSED"
    assert req2["supersedes_request_id"] == req1["id"]


def test_counter_moves_request_proposed_to_countered(api):
    """PRD §3.10: "A `Coordinator` counters a `PROPOSED` request — permitted only
    when the request is `PROPOSED` and the parent booking is `CONFIRMED` or
    `GUARANTEED` — by supplying alternate `proposed_event_date`,
    `proposed_ceremony_start`, `proposed_ceremony_end`, `proposed_reception_start`,
    and `proposed_reception_end`, moving `request_status` from `PROPOSED` to
    `COUNTERED` and recording those counter times on the request."

    Design: Difficulty/non_linear_state_machine/reschedule_request_negotiation_cycle
    """
    inv, booking = setup_confirmed_booking()
    req1 = get_success_data(api.create_reschedule_request(
        booking["id"], create_reschedule_payload("CLIENT_REQUEST", *_R1), inv["client_headers"]))
    countered = get_success_data(api.counter_reschedule(
        req1["id"],
        {"proposed_event_date": _R2[0], "proposed_ceremony_start": _R2[1],
         "proposed_ceremony_end": _R2[2], "proposed_reception_start": _R2[3],
         "proposed_reception_end": _R2[4]},
        inv["coord_headers"]))
    assert countered["request_status"] == "COUNTERED"


# ───────────── Rule 3: parallel booking axes evolve independently ─────────────

def test_two_axes_carry_independent_values_after_confirm(api):
    """PRD §2.7: "A `Booking` advances along two independent state axes that never
    share a field. The lifecycle axis is `booking_status` ... The settlement axis
    is `payment_status`".
    PRD §2.7: "These axes evolve independently: payment posting drives
    `payment_status` while lifecycle endpoints drive `booking_status`".

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_axes_evolve_independently
    """
    inv, booking = setup_confirmed_booking()
    # The lifecycle axis advanced to CONFIRMED; the settlement axis sits at
    # DEPOSIT_PAID — two distinct enum values on two distinct fields.
    assert booking["booking_status"] == "CONFIRMED"
    assert booking["payment_status"] == "DEPOSIT_PAID"
    assert booking["booking_status"] != booking["payment_status"]


def test_confirm_advances_booking_status_payment_status_stays_deposit_paid(api):
    """PRD §2.7: "payment posting drives `payment_status` while lifecycle endpoints
    drive `booking_status`, and `payment_status` only gates a lifecycle transition
    where a precondition explicitly says so (confirmation requires a settled
    deposit; completion requires paid-in-full)."

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_axes_evolve_independently
    """
    inv, booking = setup_confirmed_booking()
    assert booking["booking_status"] == "CONFIRMED"
    assert booking["payment_status"] == "DEPOSIT_PAID"


# ───────────── Rule 7: confirm blocked when coordinator unassigned ─────────────

def test_confirm_rejected_when_coordinator_unassigned(api):
    """PRD §3.4: "Confirmation is permitted only when the booking is `HELD`, the
    current clock is still before `hold_expires_at` (the hold has not lapsed), a
    coordinator is assigned (`coordinator_id` is not null), and the deposit has been
    settled".
    PRD §2.7: "Any attempt to drive a transition that is not defined from a
    resource's current state ... is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_coordinator_unassigned
    """
    inv = create_inventory()
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    booking, _, _ = add_both_holds(inv, booking)
    booking = place_soft_hold(inv, booking["id"])
    pay_deposit(inv, booking["id"])
    res = api.confirm_booking(booking["id"], inv["coord_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["booking_status"] == "HELD"


def test_confirm_unassigned_leaves_coordinator_id_null(api):
    """PRD §3.4: "a coordinator is assigned (`coordinator_id` is not null)".
    PRD §3.2: "On creation the booking lands at `booking_status` `INQUIRY` and
    `payment_status` `UNPAID`; its `coordinator_id` is null until assigned."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_coordinator_unassigned
    """
    inv = create_inventory()
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    booking, _, _ = add_both_holds(inv, booking)
    booking = place_soft_hold(inv, booking["id"])
    pay_deposit(inv, booking["id"])
    api.confirm_booking(booking["id"], inv["coord_headers"])
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["coordinator_id"] is None


# ───────────── Corner: state machine guards ─────────────

def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §2.7: "Any attempt to drive a transition that is not defined from a
    resource's current state — whether on `booking_status`, `hold_status`,
    `vendor_status`, or `request_status` — is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    inv, booking = setup_held_booking()
    get_success_data(api.cancel_booking(booking["id"], inv["client_headers"]))
    res = api.cancel_booking(booking["id"], inv["client_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["booking_status"] == "CANCELLED"


def test_place_hold_requires_both_block_holds_present(api):
    """PRD §3.3: "Once at least one `HELD` hold covering a `CEREMONY` block and at
    least one `HELD` hold covering a `RECEPTION` block both exist for the booking, a
    `Coordinator` may place the soft hold — the transition that advances
    `booking_status` from `INQUIRY` to `HELD`."

    Design: Corner/state_machines/place_hold_requires_both_block_holds_present
    """
    inv = create_inventory()
    booking = create_inquiry_booking(inv)
    coord = inv["coord_headers"]
    # Only a CEREMONY hold exists.
    get_success_data(api.create_hold(
        booking["id"], create_hold_payload(inv["space_id"], "CEREMONY", booking["version"]),
        coord))
    res = api.place_hold(booking["id"], coord)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_booking(booking["id"], coord))
    assert after["booking_status"] == "INQUIRY"


# ───────────── Corner: OCC version increments ─────────────

def test_booking_version_increments_one_per_mutation(api):
    """PRD §2.4: "an integer `version` that begins at its initial value and
    increments by one on every mutation of the resource."
    PRD §2.5: "Whenever a booking's own state, charge fields, or assignments change,
    the booking's `version` advances by one".

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write
    """
    inv = create_inventory()
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    assert booking["version"] == 1
    assigned = get_success_data(api.assign_coordinator(
        booking["id"], {"coordinator_id": inv["coordinator_id"]}, inv["coord_headers"]))
    assert assigned["version"] == 2
    hold = get_success_data(api.create_hold(
        booking["id"], create_hold_payload(inv["space_id"], "CEREMONY", assigned["version"]),
        inv["coord_headers"]))
    after = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert after["version"] == 3
