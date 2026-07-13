"""Booking and reference-data lifecycle: creation, defaults, existence, and
simple state-machine lockdowns.

Covers Corner queue instances from sections: entities, state_machines,
consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_terminal, assert_booking,
    create_terminal_payload, create_booking_payload,
    mk_terminal, mk_confirmed_booking, mk_chassis, mk_chassis_assigned_booking,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_terminal_echoes_inputs_and_defaults_slot_capacity(api):
    """PRD §3.1: "an optional `slot_capacity_per_window`, which is the maximum
    number of booked appointments allowed to overlap the same window at that
    terminal and defaults to 1 when omitted (and must be at least 1)."

    Design: Corner/entities/create_terminal_returns_all_fields
    """
    resp = api.create_terminal(
        create_terminal_payload(name="Berth 55", code="B55", demurrage_daily_rate_cents=12500),
        DISPATCHER,
    )
    data = validate_success(resp, expected_status=201)
    assert_terminal(data)
    assert data["demurrage_daily_rate_cents"] == 12500
    assert data["slot_capacity_per_window"] == 1, "omitted slot_capacity_per_window must default to 1"


def test_create_booking_missing_linehaul_rejected(api):
    """PRD §2.6 (priority 4): "on any write, required fields are present, enum
    fields hold legal values, integer amounts are at least zero, and any supplied
    `window_start` is strictly before its `window_end`." "Any violation returns
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/booking_missing_required_linehaul_returns_invalid_request
    """
    terminal = mk_terminal(api, name="Berth 56", code="B56")
    payload = create_booking_payload(terminal["id"], container_number="MSCUX")
    payload.pop("linehaul_base_cents")
    resp = api.create_booking(payload, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_get_unknown_booking_returns_not_found(api):
    """PRD §2.6 (priority 3): "every resource named in the path and every foreign
    key in the body is resolved left to right; the first unresolved reference
    returns the matching not-found error (404). These are ... `ERR_BOOKING_NOT_FOUND` ..."

    Design: Corner/entities/booking_not_found_returns_404
    """
    resp = api.get_booking(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND, expected_status=404)


def test_create_booking_container_size_defaults_to_d40(api):
    """PRD §3.2: "A dispatcher creates it with a `container_number`, a `direction`
    of either `IMPORT` or `EXPORT`, an `origin_terminal_id` referencing the
    pickup/return terminal, a `last_free_day` (an ISO 8601 UTC instant), a
    `linehaul_base_cents` (the base trucking rate for the move, never negative),
    and an optional `container_size` of `D20`, `D40`, or `HC40` that defaults to `D40`."

    Design: Corner/entities/booking_container_size_default_applied
    """
    terminal = mk_terminal(api, name="Berth 57", code="B57")
    payload = create_booking_payload(terminal["id"], container_number="MSCUY")
    payload.pop("container_size", None)
    data = validate_success(api.create_booking(payload, DISPATCHER), expected_status=201)
    assert data["container_size"] == "D40"
    assert data["status"] == "DRAFT"


def test_created_booking_has_system_fields_and_zero_demurrage(api):
    """PRD §3.2: "A new booking begins in `DRAFT`."
    PRD §3.2: "The computed accrual fields `demurrage_estimate_cents`,
    `demurrage_actual_cents`, and `per_diem_final_cents` all start at zero and are
    populated at the moments described below."

    Design: Corner/entities/booking_system_fields_generated_input_ignored
    """
    terminal = mk_terminal(api, name="Berth 58", code="B58")
    payload = create_booking_payload(terminal["id"], container_number="MSCUZ")
    # A client-supplied status must be ignored — the server sets DRAFT.
    payload["status"] = "DELIVERED"
    data = validate_success(api.create_booking(payload, DISPATCHER), expected_status=201)
    assert_booking(data)
    assert data["status"] == "DRAFT"
    assert data["demurrage_actual_cents"] == 0


def test_confirm_twice_second_call_rejected(api):
    """PRD §3.2: "Confirming a booking advances it from `DRAFT` to `CONFIRMED`;
    the booking must be in `DRAFT` for this, and the transition increments the
    booking's `version`."
    PRD §2.6 (priority 6): "the target resource is in a legal state for the
    requested transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/confirm_twice_second_rejected
    """
    terminal = mk_terminal(api, name="Berth 59", code="B59")
    _, confirmed = mk_confirmed_booking(api, terminal["id"], container_number="MSCU10")
    resp = api.confirm_booking(confirmed["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_booking(confirmed["id"], DISPATCHER))
    assert after["status"] == "CONFIRMED"


def test_cancel_already_canceled_booking_rejected(api):
    """PRD §3.2: "A booking may be canceled from any non-terminal state (`DRAFT`,
    `CONFIRMED`, `CHASSIS_ASSIGNED`, `APPOINTED`, `DISPATCHED`, or `DELIVERED`),
    moving it to `CANCELED`; the two terminal states are `EMPTY_RETURNED` and
    `CANCELED`, and an already-terminal booking cannot be canceled again."

    Design: Corner/state_machines/cancel_already_canceled_booking_rejected
    """
    terminal = mk_terminal(api, name="Berth 60", code="B60")
    booking = get_success_data(api.create_booking(
        create_booking_payload(terminal["id"], container_number="MSCU11"), DISPATCHER))
    get_success_data(api.cancel_booking(booking["id"], DISPATCHER))
    resp = api.cancel_booking(booking["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_booking(booking["id"], DISPATCHER))
    assert after["status"] == "CANCELED"


def test_assigned_chassis_is_immediately_visible_on_read(api):
    """PRD §3.3: "On success, the booking's `chassis_id` is set to the target
    chassis, that chassis moves from `AVAILABLE` to `ASSIGNED`, and the booking's
    `version` increments."

    Design: Corner/consistency_model/immediate_visibility_of_assigned_chassis
    """
    terminal = mk_terminal(api, name="Berth 76", code="B76")
    chassis = mk_chassis(api, chassis_number="CHXR")
    assigned = mk_chassis_assigned_booking(api, terminal["id"], chassis["id"], container_number="MSCU27")
    assert assigned["chassis_id"] == chassis["id"]
    assert assigned["status"] == "CHASSIS_ASSIGNED"
    # Immediate consistency: a fresh GET in the same cycle shows the same state.
    fetched = validate_success(api.get_booking(assigned["id"], DISPATCHER))
    assert fetched["chassis_id"] == chassis["id"]
    assert fetched["status"] == "CHASSIS_ASSIGNED"
