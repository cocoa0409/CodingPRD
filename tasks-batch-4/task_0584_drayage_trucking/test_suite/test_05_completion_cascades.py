"""Leg completion branches (POD / empty return / street turn), the empty-return
and cancellation cascades, and per-diem provisional vs final accrual.

Covers Difficulty rules: non_linear_state_machine, transitive_cascade,
dual_variant_calc. Covers Corner sections: state_machines, calculations.
"""
from test_helpers import (
    validate_success, get_success_data,
    mk_booking,
    create_booking_payload, create_leg_payload,
    setup_delivered_booking, setup_empty_returned,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]

# Shared setup keywords placing the pickup dispatch at 2026-05-15.
_OUT_KW = dict(
    clock="2026-05-15T00:00:00Z", per_diem_rate_cents=8500, free_days=4,
    last_free_day="2026-06-30T00:00:00Z", appt_start="2026-05-15T06:00:00Z",
    appt_end="2026-05-30T23:59:59Z", leg_start="2026-05-15T08:00:00Z",
    leg_end="2026-05-15T12:00:00Z",
)


# --- non_linear_state_machine: leg completion forks by leg_type -----------

def test_pickup_completion_keeps_chassis_out_and_delivers_booking(api):
    """PRD §3.7: "**Pickup completion** captures proof of delivery. It requires the
    leg to be `DISPATCHED` and of `leg_type` `PICKUP`, and it advances the owning
    booking from `DISPATCHED` to `DELIVERED`, incrementing the booking's `version`."
    PRD §3.6: "the assigned chassis moves from `ASSIGNED` to `OUT` and its
    `assigned_out_at` is set to the current clock".

    Design: Difficulty/non_linear_state_machine/leg_completion_branch_divergent
    """
    ctx = setup_delivered_booking(api, container_number="MSCU6", **_OUT_KW)
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["status"] == "DELIVERED"
    chassis = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert chassis["status"] == "OUT", "pickup completion must not return the chassis"


def test_return_completion_releases_chassis_and_empties_booking(api):
    """PRD §3.7: "**Return completion** is the empty-return that closes the move. It
    requires the leg to be of `leg_type` `RETURN`, the owning booking to be
    `DELIVERED`, and the assigned chassis to be `OUT`. Completing it triggers the
    empty-return chain in full: the assigned chassis moves from `OUT` to `AVAILABLE`,
    its `returned_at` is set to the current clock, and its **final per-diem** is
    computed into `per_diem_final_cents`; that in turn stamps the owning booking's
    `per_diem_final_cents` from the chassis's finalized figure and advances the
    booking from `DELIVERED` to `EMPTY_RETURNED`."

    Design: Difficulty/non_linear_state_machine/leg_completion_branch_divergent
    """
    ctx = setup_empty_returned(api, container_number="MSCU6", return_clock="2026-05-16T00:00:00Z",
                               return_start="2026-05-16T08:00:00Z", return_end="2026-05-16T12:00:00Z",
                               **_OUT_KW)
    chassis = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert chassis["status"] == "AVAILABLE"
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["status"] == "EMPTY_RETURNED"


# --- transitive_cascade: empty return finalizes per-diem down the chain ----

def test_return_completion_finalizes_chassis_per_diem(api):
    """PRD §3.7: "the assigned chassis moves from `OUT` to `AVAILABLE`, its
    `returned_at` is set to the current clock, and its **final per-diem** is computed
    into `per_diem_final_cents`".
    PRD §3.7: "The per-diem calculation counts the whole UTC calendar days a chassis
    has been out — the UTC calendar date of the basis minus the UTC calendar date of
    `assigned_out_at`, floored at zero — then subtracts the chassis's `free_days`,
    flooring that result at zero as well, and multiplies the remaining chargeable days
    by the chassis's `per_diem_rate_cents`. For the final figure the basis is the
    chassis's `returned_at`."

    Design: Difficulty/transitive_cascade/empty_return_chassis_booking_cascade
    """
    ctx = setup_empty_returned(api, container_number="MSCU7", return_clock="2026-05-24T00:00:00Z",
                               return_start="2026-05-24T08:00:00Z", return_end="2026-05-24T12:00:00Z",
                               **_OUT_KW)
    ret_leg = validate_success(api.get_leg(ctx["return_leg_id"], DISPATCHER))
    assert ret_leg["status"] == "COMPLETED"
    chassis = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert chassis["status"] == "AVAILABLE"
    # OUT 2026-05-15 .. returned 2026-05-24 = 9 days; less free_days 4 = 5; * 8500.
    assert chassis["per_diem_final_cents"] == 42500


def test_empty_return_stamps_booking_per_diem_final(api):
    """PRD §3.7: "that in turn stamps the owning booking's `per_diem_final_cents` from
    the chassis's finalized figure and advances the booking from `DELIVERED` to
    `EMPTY_RETURNED`."

    Design: Difficulty/transitive_cascade/empty_return_chassis_booking_cascade
    """
    ctx = setup_empty_returned(api, container_number="MSCU7", return_clock="2026-05-24T00:00:00Z",
                               return_start="2026-05-24T08:00:00Z", return_end="2026-05-24T12:00:00Z",
                               **_OUT_KW)
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["status"] == "EMPTY_RETURNED"
    assert booking["per_diem_final_cents"] == 42500


# --- transitive_cascade: booking cancel -> leg -> chassis ------------------

def test_cancel_booking_cascades_pickup_leg_to_canceled(api):
    """PRD §3.8: "Canceling a booking is a single request with a fan-out. The booking
    moves to `CANCELED`, and every non-terminal leg of that booking is canceled as
    well; each such leg then runs its own cancellation side-effects."

    Design: Difficulty/transitive_cascade/booking_cancel_leg_chassis_cascade
    """
    from test_helpers import setup_dispatched_pickup
    ctx = setup_dispatched_pickup(api, container_number="MSCU8", **_OUT_KW)
    get_success_data(api.cancel_booking(ctx["booking_id"], DISPATCHER))
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["status"] == "CANCELED"
    leg = validate_success(api.get_leg(ctx["leg_id"], DISPATCHER))
    assert leg["status"] == "CANCELED"


def test_cancel_booking_releases_out_chassis(api):
    """PRD §3.8: "a booking that has already dispatched its pickup — so its chassis is
    `OUT` — will, on cancellation, cancel that pickup leg, which releases the chassis
    from `OUT` back to `AVAILABLE`, stamps the chassis's `returned_at`, and finalizes
    the chassis's per-diem."

    Design: Difficulty/transitive_cascade/booking_cancel_leg_chassis_cascade
    """
    from test_helpers import setup_dispatched_pickup
    ctx = setup_dispatched_pickup(api, container_number="MSCU8", **_OUT_KW)
    get_success_data(api.cancel_booking(ctx["booking_id"], DISPATCHER))
    chassis = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert chassis["status"] == "AVAILABLE"


# --- dual_variant_calc: per-diem provisional vs final ---------------------

def test_per_diem_provisional_computed_while_chassis_out(api):
    """PRD §3.7: "While a chassis is `OUT`, reading it computes
    `per_diem_provisional_cents` on the fly using the same formula with the current
    logical clock as the basis; the provisional figure is zero whenever the chassis is
    not `OUT`, and the final figure stays zero until the chassis returns."

    Design: Difficulty/dual_variant_calc/per_diem_provisional_vs_final_on_chassis
    """
    ctx = setup_delivered_booking(api, container_number="MSCU2", **_OUT_KW)
    api.set_clock("2026-05-21T00:00:00Z", DISPATCHER)
    chassis = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    # OUT 2026-05-15 .. clock 2026-05-21 = 6 days; less free_days 4 = 2; * 8500.
    assert chassis["per_diem_provisional_cents"] == 17000


def test_per_diem_final_at_empty_return_differs_from_provisional(api):
    """PRD §3.7: "For the final figure the basis is the chassis's `returned_at`."
    PRD §3.7: "that in turn stamps the owning booking's `per_diem_final_cents` from
    the chassis's finalized figure and advances the booking from `DELIVERED` to
    `EMPTY_RETURNED`."

    Design: Difficulty/dual_variant_calc/per_diem_provisional_vs_final_on_chassis
    """
    ctx = setup_empty_returned(api, container_number="MSCU2", return_clock="2026-05-24T00:00:00Z",
                               return_start="2026-05-24T08:00:00Z", return_end="2026-05-24T12:00:00Z",
                               **_OUT_KW)
    chassis = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert chassis["per_diem_final_cents"] == 42500
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["per_diem_final_cents"] == 42500
    # final (42500) diverges from the provisional read at 2026-05-21 (17000).
    assert chassis["per_diem_final_cents"] != 17000


# --- Corner: street-turn transfers chassis to the export booking ----------

def test_street_turn_transfers_chassis_to_export_booking(api):
    """PRD §3.7: "On completion the import booking advances from `DELIVERED` to
    `EMPTY_RETURNED` without the chassis ever being returned to the terminal; the
    chassis stays `OUT` and is reassigned to the export booking — the export booking's
    `chassis_id` is set to this chassis and the export booking advances from
    `CONFIRMED` to `CHASSIS_ASSIGNED`."

    Design: Corner/state_machines/street_turn_transfers_chassis_to_export_booking
    """
    ctx = setup_delivered_booking(api, container_number="IMP1", **_OUT_KW)
    export = mk_booking(api, ctx["terminal_id"], container_number="EXP1",
                        direction="EXPORT", linehaul_base_cents=40000)
    get_success_data(api.confirm_booking(export["id"], DISPATCHER))
    st_leg = get_success_data(api.create_leg(
        create_leg_payload(ctx["booking_id"], ctx["driver_id"], "STREET_TURN",
                           "2026-05-16T08:00:00Z", "2026-05-16T12:00:00Z",
                           linked_export_booking_id=export["id"]),
        DISPATCHER))
    get_success_data(api.dispatch_leg(st_leg["id"], DISPATCHER))
    get_success_data(api.complete_leg(st_leg["id"], DISPATCHER))
    import_booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert import_booking["status"] == "EMPTY_RETURNED"
    chassis = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert chassis["status"] == "OUT", "street turn must NOT return the chassis"
    export_after = validate_success(api.get_booking(export["id"], DISPATCHER))
    assert export_after["chassis_id"] == ctx["chassis_id"]
    assert export_after["status"] == "CHASSIS_ASSIGNED"


# --- Corner: per-diem free-day boundary -----------------------------------

def test_per_diem_zero_at_free_day_then_charges_after(api):
    """PRD §3.7: "The per-diem calculation counts the whole UTC calendar days a chassis
    has been out — the UTC calendar date of the basis minus the UTC calendar date of
    `assigned_out_at`, floored at zero — then subtracts the chassis's `free_days`,
    flooring that result at zero as well, and multiplies the remaining chargeable days
    by the chassis's `per_diem_rate_cents`."

    Design: Corner/calculations/per_diem_free_day_boundary
    """
    ctx = setup_delivered_booking(api, container_number="MSCU14", **_OUT_KW)
    # 2026-05-19 is exactly 4 days out (== free_days) -> 0 chargeable days.
    api.set_clock("2026-05-19T00:00:00Z", DISPATCHER)
    at_free = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert at_free["per_diem_provisional_cents"] == 0
    # 2026-05-20 is 5 days out -> 1 chargeable day * 8500.
    api.set_clock("2026-05-20T00:00:00Z", DISPATCHER)
    after_free = validate_success(api.get_chassis(ctx["chassis_id"], DISPATCHER))
    assert after_free["per_diem_provisional_cents"] == 8500
