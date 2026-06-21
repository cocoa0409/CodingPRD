"""Loading stops, detention and lumper fees, window scheduling, and fee ledgers.

Translates difficulty instances (combinatorial_formula detention, boundary detention,
resource_temporal_overlap stop window, compensating_invariant detention ledger) and
corner calculation / validation instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    fixtures as fx,
    factories as F,
)


def test_detention_fee_tiered_ceil_nonlinear(api):
    """PRD §3.9: "Those billable minutes are converted to billable hours by rounding up to the next whole hour — any started hour is billed in full. The first 4 billable hours are tier-one hours billed at 5,000 cents each; every billable hour beyond the first 4 is a tier-two hour billed at 7,500 cents each. The stop's `detention_fee_cents` is the tier-one hours times 5,000 plus the tier-two hours times 7,500."

    Design: Difficulty/combinatorial_formula/detention_fee_tiered_ceil_nonlinear_mode_a
    """
    # dwell 500 - free 120 = 380 billable -> ceil(380/60)=7h. tier1=4*5000, tier2=3*7500
    # = 20000 + 22500 = 42500.
    ctx, stop = fx.setup_arrived_stop(arrived_min=0, appointment_min=0, kind="DELIVERY",
                                      lane_kind="CHILLED", carrier_op="carrier-op-3",
                                      shipper_op="shipper-op-3")
    resp = api.close_stop(ctx["shipment"]["id"], stop["id"], F.close_payload(500), fx.DRIVER)
    data = validate_success(resp)
    assert data["detention_fee_cents"] == 42500
    ship = validate_success(api.get_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    assert ship["total_detention_fee_cents"] == 42500


def test_detention_fee_tier1_only_no_tier2(api):
    """PRD §3.9: "The first 4 billable hours are tier-one hours billed at 5,000 cents each; every billable hour beyond the first 4 is a tier-two hour billed at 7,500 cents each."

    Design: Difficulty/combinatorial_formula/detention_fee_tiered_ceil_nonlinear_mode_a
    """
    # dwell 360 - free 120 = 240 billable -> ceil(240/60)=4h, all tier-one, no tier-two
    # -> 4*5000 = 20000.
    ctx, stop = fx.setup_arrived_stop(arrived_min=0, appointment_min=0, kind="DELIVERY",
                                      lane_kind="CHILLED", carrier_op="carrier-op-3b",
                                      shipper_op="shipper-op-3b")
    resp = api.close_stop(ctx["shipment"]["id"], stop["id"], F.close_payload(360), fx.DRIVER)
    data = validate_success(resp)
    assert data["detention_fee_cents"] == 20000, "4 billable hours are all tier-one: 4*5000"


def test_detention_free_time_boundary_exactly_120_is_zero(api):
    """PRD §3.9: "the billable minutes are the dwell minus a free allowance of 120 minutes (never less than 0)."

    Design: Difficulty/boundary_precision_check/detention_free_time_boundary_120_vs_121_on_stop_close
    """
    # dwell exactly 120 == FREE_TIME_MIN -> billable 0 -> fee 0.
    ctx, stop = fx.setup_arrived_stop(arrived_min=600, appointment_min=600, kind="DELIVERY",
                                      lane_kind="CHILLED", carrier_op="carrier-op-11",
                                      shipper_op="shipper-op-11")
    resp = api.close_stop(ctx["shipment"]["id"], stop["id"], F.close_payload(720), fx.DRIVER)
    data = validate_success(resp)
    assert data["detention_fee_cents"] == 0, "dwell exactly 120 == free time must bill 0"


def test_detention_free_time_boundary_121_bills_one_hour(api):
    """PRD §3.9: "Those billable minutes are converted to billable hours by rounding up to the next whole hour — any started hour is billed in full. The first 4 billable hours are tier-one hours billed at 5,000 cents each".

    Design: Difficulty/boundary_precision_check/detention_free_time_boundary_120_vs_121_on_stop_close
    """
    # dwell 121 -> billable 1 -> ceil = 1h -> tier1 1*5000 = 5000.
    ctx, stop = fx.setup_arrived_stop(arrived_min=600, appointment_min=600, kind="DELIVERY",
                                      lane_kind="CHILLED", carrier_op="carrier-op-11b",
                                      shipper_op="shipper-op-11b")
    resp = api.close_stop(ctx["shipment"]["id"], stop["id"], F.close_payload(721), fx.DRIVER)
    data = validate_success(resp)
    assert data["detention_fee_cents"] == 5000, "dwell 121 crosses to one started hour -> 5000"


def test_lumper_fee_multitemp_surcharge(api):
    """PRD §3.9: "The **lumper fee** is a base of 7,500 cents, plus 350 cents for each
    of the stop's `pallets_handled`, plus a multi-temp surcharge of 2,500 cents for each
    compartment beyond the first that was accessed — that is, the surcharge applies to
    `compartments_touched` minus 1 when that is positive, and contributes nothing when
    only a single compartment was touched."

    Design: Corner/calculations/lumper_fee_multitemp_surcharge_correct
    """
    # 7500 + 12*350 + (3-1)*2500 = 7500 + 4200 + 5000 = 16700. dwell 60 < free -> det 0.
    ctx, stop = fx.setup_arrived_stop(arrived_min=0, appointment_min=0, kind="DELIVERY",
                                      pallets_handled=12, compartments_touched=3,
                                      lane_kind="CHILLED", carrier_op="carrier-c14",
                                      shipper_op="shipper-c14")
    resp = api.close_stop(
        ctx["shipment"]["id"], stop["id"],
        F.close_payload(60, pallets_handled=12, compartments_touched=3), fx.DRIVER,
    )
    data = validate_success(resp)
    assert data["lumper_fee_cents"] == 16700
    assert data["detention_fee_cents"] == 0, "dwell 60 < free time 120 must bill no detention"
    ship = validate_success(api.get_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    assert ship["total_lumper_fee_cents"] == 16700


def test_close_stop_with_departed_before_arrived_returns_invalid_interval(api):
    """PRD §3.9: "Closing is recorded from `ARRIVED`, supplying a `departed_min` that must be at least the `arrived_min` (a `departed_min` earlier than `arrived_min` is rejected with `ERR_INVALID_INTERVAL`)".

    Design: Corner/validations/close_stop_with_departed_before_arrived_returns_invalid_interval
    """
    ctx, stop = fx.setup_arrived_stop(arrived_min=100, appointment_min=100, kind="DELIVERY",
                                      lane_kind="CHILLED", carrier_op="carrier-c18",
                                      shipper_op="shipper-c18")
    resp = api.close_stop(ctx["shipment"]["id"], stop["id"], F.close_payload(50), fx.DRIVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


def test_stop_window_buffered_overlap_rejected(api):
    """PRD §3.9: "The new window collides with an existing window unless they are cleanly separated by at least a 30-minute buffer — concretely, the candidate is allowed only when the candidate window's end plus 30 minutes is at most the existing window's start, or the existing window's end plus 30 minutes is at most the candidate window's start. Any closer spacing — including windows that merely touch, or that sit within the 30-minute buffer of each other — collides and is rejected with `ERR_STOP_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/stop_window_buffered_overlap_on_shipment
    """
    # Existing [100,160]; candidate [185,245]. gap = 185 - 160 = 25 < buffer 30 -> collide.
    carrier, ch = fx.create_carrier(legal_name="Window Carrier", op_id="carrier-op-15")
    lane = fx.create_lane()
    shipment = fx.tender_shipment(carrier["id"], cargo_class="FOOD", shipper_op="shipper-op-15")
    fx.add_compartment(shipment["id"], lane["id"], ordinal=1, shipper_op="shipper-op-15")
    fx.add_stop(shipment["id"], "PICKUP", 100, shipper_op="shipper-op-15")
    resp = api.create_stop(
        shipment["id"], F.create_stop_payload("DELIVERY", 185), fx.make_shipper_headers("shipper-op-15")
    )
    validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_OVERLAP.value)


def test_stop_window_exactly_buffer_apart_succeeds(api):
    """PRD §3.9: "the candidate is allowed only when the candidate window's end plus 30 minutes is at most the existing window's start, or the existing window's end plus 30 minutes is at most the candidate window's start."

    Design: Difficulty/resource_temporal_overlap/stop_window_buffered_overlap_on_shipment
    """
    # Existing [100,160]; candidate [190,250]. existing.end 160 + 30 = 190 <= 190 -> ok.
    carrier, ch = fx.create_carrier(legal_name="Window2 Carrier", op_id="carrier-op-15b")
    lane = fx.create_lane()
    shipment = fx.tender_shipment(carrier["id"], cargo_class="FOOD", shipper_op="shipper-op-15b")
    fx.add_compartment(shipment["id"], lane["id"], ordinal=1, shipper_op="shipper-op-15b")
    fx.add_stop(shipment["id"], "PICKUP", 100, shipper_op="shipper-op-15b")
    resp = api.create_stop(
        shipment["id"], F.create_stop_payload("DELIVERY", 190), fx.make_shipper_headers("shipper-op-15b")
    )
    validate_success(resp, expected_status=201)


def test_detention_ledger_equals_sum_over_closed_stops(api):
    """PRD §2.11: "When a `StopEvent` closes, the platform computes that stop's `detention_fee_cents` and `lumper_fee_cents` (Section 3.9), then recomputes the parent shipment's `total_detention_fee_cents` as the sum of `detention_fee_cents` over all of the shipment's closed stops".

    Design: Difficulty/compensating_invariant/detention_ledger_conservation_close_then_reopen_via_second_stop
    """
    # Two stops: A dwell 180 -> billable 60 -> 1h -> 5000; B dwell 181 -> billable 61
    # -> 2h -> 10000. Ledger total = 15000.
    fx.set_clock("2026-03-01T00:00:00Z")
    ctx = fx.setup_tendered_with_compartments(num_compartments=1, lane_kind="CHILLED",
                                              carrier_op="carrier-op-18", shipper_op="shipper-op-18")
    sid = ctx["shipment"]["id"]
    stopA = fx.add_stop(sid, "PICKUP", 0, shipper_op="shipper-op-18")
    stopB = fx.add_stop(sid, "DELIVERY", 300, shipper_op="shipper-op-18")
    fx.accept(sid, ctx["unit"]["id"], ctx["carrier_headers"])
    from test_helpers import get_success_data
    comp = ctx["compartments"][0]
    get_success_data(api.create_reading(comp["id"], F.create_reading_payload("PRECOOL", 0, temp_c=2), ctx["carrier_headers"]))
    get_success_data(api.precool_verify_shipment(sid, ctx["carrier_headers"]))
    get_success_data(api.dispatch_shipment(sid, ctx["carrier_headers"]))
    get_success_data(api.arrive_stop(sid, stopA["id"], F.arrive_payload(0), fx.DRIVER))
    feeA = validate_success(api.close_stop(sid, stopA["id"], F.close_payload(180), fx.DRIVER))
    assert feeA["detention_fee_cents"] == 5000
    get_success_data(api.arrive_stop(sid, stopB["id"], F.arrive_payload(300), fx.DRIVER))
    feeB = validate_success(api.close_stop(sid, stopB["id"], F.close_payload(481), fx.DRIVER))
    assert feeB["detention_fee_cents"] == 10000
    ship = validate_success(api.get_shipment(sid, ctx["carrier_headers"]))
    assert ship["total_detention_fee_cents"] == 15000, \
        "shipment ledger must equal the exact sum of detention over CLOSED stops"


def test_detention_ledger_equals_single_closed_stop_fee(api):
    """PRD §2.11: "the platform ... recomputes the parent shipment's `total_detention_fee_cents` as the sum of `detention_fee_cents` over all of the shipment's closed stops".
    PRD §2.11: "Both shipment totals default to 0 before any stop has closed."

    Design: Difficulty/compensating_invariant/detention_ledger_conservation_close_then_reopen_via_second_stop
    """
    # After one CLOSED stop (dwell 180 -> 5000) the ledger reads exactly that fee, and
    # was 0 before any close.
    ctx, stop = fx.setup_arrived_stop(arrived_min=0, appointment_min=0, kind="DELIVERY",
                                      lane_kind="CHILLED", carrier_op="carrier-op-18b",
                                      shipper_op="shipper-op-18b")
    before = validate_success(api.get_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    assert before["total_detention_fee_cents"] == 0, "ledger must be 0 before any stop closes"
    fee = validate_success(api.close_stop(ctx["shipment"]["id"], stop["id"], F.close_payload(180), fx.DRIVER))
    assert fee["detention_fee_cents"] == 5000
    after = validate_success(api.get_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    assert after["total_detention_fee_cents"] == 5000, \
        "ledger must equal the single CLOSED stop's detention fee with no drift"
