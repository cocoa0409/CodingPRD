"""Dispatch eligibility gates, resource-overlap checks, and offer negotiation.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 (priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap, non_linear_state_machine)
and SCAFFOLD_CORNER_DESIGN.yaml §1.9 (validations).
"""
from test_helpers import (
    TEST_USERS,
    create_order_payload,
    dispatch_order_for_carrier,
    list_pending_offer_for_carrier,
    make_carrier_headers,
    make_shipper_headers,
    post_ledger,
    read_order,
    register_carrier,
    register_shipper,
    register_terminal,
    setup_listed_order,
    setup_pending_offer,
    setup_quoted_order,
    suspend_carrier,
    validate_error,
    validate_success,
)


# ─── priority_pair_validation_conflict / safety beats fiscal — 2 tests ──────

def test_dispatch_equipment_mismatch_beats_pay_exceeds_total(api):
    """PRD §3.5: "5. The carrier's equipment_type must equal the order's
    transport_type, else ERR_EQUIPMENT_MISMATCH."
    PRD §3.5: "a stack of eligibility gates is evaluated in the following order,
    the first failure determining the rejection".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_dispatch_returns_equipment_mismatch
    """
    ctx = setup_pending_offer(
        route_miles=1200, carrier_equipment_type="ENCLOSED", ask_pay_cents=999999,
    )
    resp = api.accept_offer(ctx["listing"]["id"], ctx["offer"]["id"], TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_EQUIPMENT_MISMATCH", expected_status=409)


def test_dispatch_equipment_mismatch_leaves_order_listed(api):
    """PRD §3.5: "5. The carrier's equipment_type must equal the order's
    transport_type, else ERR_EQUIPMENT_MISMATCH."
    PRD §2.8: "the system performs the cascade immediately and in full — there is
    no eventual reconciliation and no partial application."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_dispatch_returns_equipment_mismatch
    """
    ctx = setup_pending_offer(
        route_miles=1200, carrier_equipment_type="ENCLOSED", ask_pay_cents=999999,
    )
    api.accept_offer(ctx["listing"]["id"], ctx["offer"]["id"], TEST_USERS["broker_headers"])
    order = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    assert order["status"] == "LISTED"


# ─── cross_entity_state_dependency / suspended carrier — 2 tests ────────────

def test_dispatch_blocked_when_carrier_suspended(api):
    """PRD §3.5: "2. The carrier must not be SUSPENDED, else
    ERR_CARRIER_SUSPENDED."
    PRD §3.1: "An Admin may later suspend a carrier, flipping its status from
    ACTIVE to SUSPENDED; a suspended carrier can no longer be awarded a load."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_carrier
    """
    ctx = setup_pending_offer(route_miles=1200)
    suspend_carrier(ctx["carrier"]["id"])
    resp = api.accept_offer(ctx["listing"]["id"], ctx["offer"]["id"], TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_CARRIER_SUSPENDED", expected_status=409)


def test_dispatch_blocked_by_suspension_leaves_order_listed(api):
    """PRD §3.1: "a suspended carrier can no longer be awarded a load."
    PRD §2.8: "the system performs the cascade immediately and in full — there is
    no eventual reconciliation and no partial application."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_carrier
    """
    ctx = setup_pending_offer(route_miles=1200)
    suspend_carrier(ctx["carrier"]["id"])
    api.accept_offer(ctx["listing"]["id"], ctx["offer"]["id"], TEST_USERS["broker_headers"])
    order = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    assert order["status"] == "LISTED"


# ─── resource_temporal_overlap / carrier schedule (half-open) — 2 tests ─────

def _two_orders_one_carrier():
    """Carrier dispatched on order1 (Jun1-5); order2 (Jun3-7) LISTED with a
    PENDING offer from the same carrier. Windows' interiors overlap."""
    shipper = register_shipper()
    carrier = register_carrier(equipment_type="OPEN", cargo_insurance_limit_cents=3_000_000)
    order1 = dispatch_order_for_carrier(
        shipper["id"], carrier["id"],
        pickup_window_start="2026-06-01T08:00:00Z", pickup_window_end="2026-06-05T18:00:00Z",
        pickup_eta="2026-06-02T09:00:00Z",
    )
    order2 = list_pending_offer_for_carrier(
        shipper["id"], carrier["id"],
        pickup_window_start="2026-06-03T08:00:00Z", pickup_window_end="2026-06-07T18:00:00Z",
        pickup_eta="2026-06-04T09:00:00Z",
    )
    return shipper, carrier, order1, order2


def test_second_dispatch_with_overlapping_window_rejected(api):
    """PRD §3.5: "4. The carrier must have no scheduling collision. No other
    Assignment of this carrier in DISPATCHED or PICKED_UP status may have an order
    pickup window that overlaps this order's window, evaluated as a half-open
    interval [pickup_window_start, pickup_window_end) — windows that merely touch
    at an endpoint do not conflict. A collision is rejected with
    ERR_CARRIER_SCHEDULE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/carrier_schedule_halfopen_pickup_window_overlap
    """
    _shipper, _carrier, _order1, order2 = _two_orders_one_carrier()
    resp = api.accept_offer(order2["listing"]["id"], order2["offer"]["id"], TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_CARRIER_SCHEDULE_CONFLICT", expected_status=409)


def test_schedule_conflict_leaves_second_order_listed(api):
    """PRD §3.5: "A collision is rejected with ERR_CARRIER_SCHEDULE_CONFLICT."
    PRD §2.8: "the system performs the cascade immediately and in full — there is
    no eventual reconciliation and no partial application."

    Design: Difficulty/resource_temporal_overlap/carrier_schedule_halfopen_pickup_window_overlap
    """
    shipper, _carrier, _order1, order2 = _two_orders_one_carrier()
    api.accept_offer(order2["listing"]["id"], order2["offer"]["id"], TEST_USERS["broker_headers"])
    order = read_order(order2["order"]["id"], shipper["id"])
    assert order["status"] == "LISTED"


# ─── resource_temporal_overlap / terminal dock (buffered, closed) — 2 tests ─

def _terminal_and_first_order(api, dock_count=1):
    terminal = register_terminal(dock_count=dock_count, buffer_minutes=60)
    shipper = register_shipper()
    payload = create_order_payload(
        route_miles=1200, transport_type="OPEN", delivery_mode="TERMINAL",
        terminal_id=terminal["id"],
        terminal_slot_start="2026-06-01T10:00:00Z", terminal_slot_end="2026-06-01T12:00:00Z",
    )
    order1 = validate_success(
        api.create_order(payload, make_shipper_headers(shipper["id"])), expected_status=201
    )
    return terminal, shipper, order1


def test_terminal_slot_conflict_when_buffered_intervals_overlap(api):
    """PRD §3.2: "Each such order's reserved slot is expanded by the terminal's
    buffer_minutes on both sides, forming a buffered interval running from its
    terminal_slot_start minus the buffer to its terminal_slot_end plus the buffer.
    Treat this buffered interval as closed, so that merely touching endpoints
    count as intersecting."
    PRD §3.2: "If that count reaches the terminal's dock_count — that is, if
    admitting this reservation would leave no free dock — the creation is rejected
    with ERR_TERMINAL_SLOT_CONFLICT".

    Design: Difficulty/resource_temporal_overlap/terminal_dock_buffered_closed_interval_overlap
    """
    terminal, shipper, _order1 = _terminal_and_first_order(api, dock_count=1)
    payload = create_order_payload(
        route_miles=1200, transport_type="OPEN", delivery_mode="TERMINAL",
        terminal_id=terminal["id"],
        terminal_slot_start="2026-06-01T12:30:00Z", terminal_slot_end="2026-06-01T14:00:00Z",
    )
    resp = api.create_order(payload, make_shipper_headers(shipper["id"]))
    validate_error(resp, "ERR_TERMINAL_SLOT_CONFLICT", expected_status=409)


def test_terminal_non_overlapping_slot_is_admitted(api):
    """PRD §3.2: "the reservation is admitted only while the number of conflicting
    orders remains below dock_count."

    A far-apart second slot (next day) does not intersect the buffered first slot,
    so the count of conflicts stays at 0 (< dock_count 1) and creation succeeds.

    Design: Difficulty/resource_temporal_overlap/terminal_dock_buffered_closed_interval_overlap
    """
    terminal, shipper, _order1 = _terminal_and_first_order(api, dock_count=1)
    payload = create_order_payload(
        route_miles=1200, transport_type="OPEN", delivery_mode="TERMINAL",
        terminal_id=terminal["id"],
        terminal_slot_start="2026-06-02T10:00:00Z", terminal_slot_end="2026-06-02T12:00:00Z",
    )
    order2 = validate_success(
        api.create_order(payload, make_shipper_headers(shipper["id"])), expected_status=201
    )
    assert order2["status"] == "DRAFT"


# ─── non_linear_state_machine / counter ↔ reoffer cycle — 2 tests ───────────

def test_offer_after_counter_and_reoffer_is_pending_round_three(api):
    """PRD §3.5: "A Broker may counter a PENDING offer, which advances it from
    PENDING to COUNTERED and increments its round_no by 1".
    PRD §3.5: "The owning Carrier may then re-ask, moving the offer from COUNTERED
    back to PENDING, updating ask_pay_cents to the new ask (and optionally a new
    pickup_eta), incrementing round_no by 1, and recomputing the listing's
    best_offer_id."

    Design: Difficulty/non_linear_state_machine/dispatch_offer_counter_reoffer_cycle
    """
    ctx = setup_pending_offer(route_miles=1200, ask_pay_cents=60000, offered_carrier_pay_cents=70000)
    validate_success(
        api.counter_offer(ctx["listing"]["id"], ctx["offer"]["id"],
                          {"counter_pay_cents": 52000}, TEST_USERS["broker_headers"]),
        200,
    )
    reoffered = validate_success(
        api.reoffer_offer(ctx["listing"]["id"], ctx["offer"]["id"],
                          {"ask_pay_cents": 55000, "pickup_eta": "2026-06-02T10:00:00Z"},
                          make_carrier_headers(ctx["carrier"]["id"])),
        200,
    )
    assert reoffered["status"] == "PENDING"
    assert reoffered["round_no"] == 3
    assert reoffered["ask_pay_cents"] == 55000


def test_offer_after_single_counter_is_countered_round_two(api):
    """PRD §3.5: "A Broker may counter a PENDING offer, which advances it from
    PENDING to COUNTERED and increments its round_no by 1".

    Design: Difficulty/non_linear_state_machine/dispatch_offer_counter_reoffer_cycle
    """
    ctx = setup_pending_offer(route_miles=1200, ask_pay_cents=60000, offered_carrier_pay_cents=70000)
    countered = validate_success(
        api.counter_offer(ctx["listing"]["id"], ctx["offer"]["id"],
                          {"counter_pay_cents": 52000}, TEST_USERS["broker_headers"]),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_no"] == 2


# ─── Corner validations ────────────────────────────────────────────────────

def test_offer_pickup_eta_outside_window_rejected(api):
    """PRD §3.5: "The promised pickup time must fall within the order's requested
    window as a closed interval — at or after pickup_window_start and at or before
    pickup_window_end, with both endpoints inclusive — and an eta outside that
    window is rejected with ERR_PICKUP_ETA_OUT_OF_WINDOW."

    Design: Corner/validations/pickup_eta_out_of_window_returns_invalid_request
    """
    ctx = setup_listed_order(route_miles=1200)  # window Jun1-5
    carrier = register_carrier(equipment_type="OPEN")
    resp = api.create_offer(
        ctx["listing"]["id"], {"ask_pay_cents": 50000, "pickup_eta": "2026-07-01T09:00:00Z"},
        make_carrier_headers(carrier["id"]),
    )
    validate_error(resp, "ERR_PICKUP_ETA_OUT_OF_WINDOW", expected_status=422)


def test_listing_before_deposit_paid_rejected(api):
    """PRD §3.4: "First, the deposit must already be paid: the order's
    amount_paid_cents must be at least its deposit_cents, established by a POSTED
    DEPOSIT entry, and otherwise the request is rejected with ERR_DEPOSIT_NOT_PAID."

    Design: Corner/validations/listing_before_deposit_returns_deposit_not_paid
    """
    ctx = setup_quoted_order(route_miles=1200)  # QUOTED, no deposit
    resp = api.create_listing(ctx["order"]["id"], {"offered_carrier_pay_cents": 50000},
                              TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_DEPOSIT_NOT_PAID", expected_status=402)


def test_listing_pay_exceeding_quoted_total_rejected(api):
    """PRD §3.4: "Second, offered_carrier_pay_cents may not exceed the order's
    quoted_total_cents, else ERR_PAY_EXCEEDS_TOTAL."

    Design: Corner/validations/listing_pay_exceeds_total_returns_pay_exceeds_total
    """
    ctx = setup_quoted_order(route_miles=1200)  # total 100000
    post_ledger(ctx["order"]["id"], "DEPOSIT", 20000)
    resp = api.create_listing(ctx["order"]["id"], {"offered_carrier_pay_cents": 200000},
                              TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_PAY_EXCEEDS_TOTAL", expected_status=402)


def test_dispatch_with_inadequate_insurance_rejected(api):
    """PRD §3.5: "6. The carrier's cargo coverage must be adequate for this load:
    cargo_insurance_limit_cents must be at least the per-load exposure, the sum of
    declared_value_cents across the order's vehicles. Otherwise the award is
    rejected with ERR_INSURANCE_INADEQUATE."

    Design: Corner/validations/dispatch_insurance_inadequate_returns_error
    """
    ctx = setup_pending_offer(
        route_miles=1200, declared_value_cents=1_000_000, carrier_insurance_limit_cents=500_000,
    )
    resp = api.accept_offer(ctx["listing"]["id"], ctx["offer"]["id"], TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_INSURANCE_INADEQUATE", expected_status=409)


def test_dispatch_with_expired_insurance_rejected(api):
    """PRD §3.5: "3. The carrier's insurance certificate must be current — the
    logical clock at or before insurance_expiry_date — else ERR_INSURANCE_EXPIRED."
    PRD §2.6: "At startup the logical clock reads 2026-05-01T00:00:00Z".

    Design: Corner/validations/dispatch_insurance_expired_returns_error
    """
    ctx = setup_pending_offer(
        route_miles=1200, carrier_insurance_expiry="2026-04-01T00:00:00Z",
    )
    resp = api.accept_offer(ctx["listing"]["id"], ctx["offer"]["id"], TEST_USERS["broker_headers"])
    validate_error(resp, "ERR_INSURANCE_EXPIRED", expected_status=409)
