"""Multi-link cascades: a recall hold downwards and a delivery confirmation upwards."""

from test_helpers import (
    AllocationStatus,
    AppointmentStatus,
    DrawPosture,
    HoldScope,
    LotStatus,
    OrderStatus,
    RecallClass,
    RecallStatus,
    assert_lot_ledger,
    assert_pounds,
    factories as f,
    fixtures as fx,
)

PEACH_CODE = "CANNED_PEACHES"


def _scheduled_peach_order(api, *, allocatable_cases):
    """One eligible agency with an approved 10-case peach order already booked."""
    env = fx.build_program(
        api,
        commodity_payloads=[f.canned_peaches_payload(entitlement_value_cents_per_case=1800)],
        lot_cases=100,
        allocatable_cases=allocatable_cases,
        admin_funds_pool_cents=5000000,
    )
    fx.build_scheduled_order(api, env, commodity_code=PEACH_CODE, cases_requested=10)
    return env


def test_01_raising_a_recall_puts_the_source_lot_on_hold(api):
    """PRD §3.8: "Each covered lot moves `AVAILABLE → HOLD` or `WATCH → HOLD` — a
    lot moved from `WATCH` keeps its existing `monitor_flag`, since the hold says
    nothing about staleness — has its `hold_recall_id` set to the recall's `id`,
    contributes one to the recall's `held_lot_count`, and has its `version`
    incremented."

    Design: Difficulty/transitive_cascade/recall_hold_propagates_lot_then_appointment_then_order
    """
    env = _scheduled_peach_order(api, allocatable_cases=1001)
    lot = env["lots"][PEACH_CODE]

    recall = fx.raise_recall(
        api,
        lot["id"],
        recall_class=RecallClass.CLASS_II,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Supplier reported a packaging integrity defect.",
    )

    held = fx.read_lot(api, lot["id"])
    assert held["status"] == LotStatus.HOLD, (
        f"the source lot expected HOLD but got {held['status']}"
    )
    assert held["hold_recall_id"] == recall["id"], (
        f"hold_recall_id expected {recall['id']} but got {held['hold_recall_id']}"
    )
    assert recall["status"] == RecallStatus.INITIATED, (
        f"recall status expected INITIATED but got {recall['status']}"
    )
    assert recall["held_lot_count"] == 1, (
        f"held_lot_count expected 1 but got {recall['held_lot_count']}"
    )
    assert recall["action_count"] == 0, (
        f"action_count expected 0 but got {recall['action_count']}"
    )


def test_02_the_hold_blocks_the_appointment_and_then_holds_the_order(api):
    """PRD §3.8: "**The cascade chain then runs three links deep: recall to lot
    hold, lot hold to appointment block, appointment block to order hold.**" PRD
    §3.8: "Every delivery appointment in `SCHEDULED` whose order reserves cases from
    a newly held lot — that is, whose order has a line whose `lot_assignments`
    reference that lot — moves `SCHEDULED → BLOCKED`."

    Design: Difficulty/transitive_cascade/recall_hold_propagates_lot_then_appointment_then_order
    """
    env = _scheduled_peach_order(api, allocatable_cases=1001)

    fx.raise_recall(
        api,
        env["lots"][PEACH_CODE]["id"],
        recall_class=RecallClass.CLASS_II,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Supplier reported a packaging integrity defect.",
    )

    appointment = fx.read_appointment(api, env["appointment"]["id"])
    assert appointment["status"] == AppointmentStatus.BLOCKED, (
        f"appointment status expected BLOCKED but got {appointment['status']}"
    )
    order = fx.read_order(api, env["order"]["id"])
    assert order["status"] == OrderStatus.HELD, (
        f"order status expected HELD but got {order['status']}"
    )


def test_03_a_held_order_keeps_every_commitment_in_place(api):
    """PRD §3.8: "In both cases the commitments stay exactly in place: a held order
    neither releases its reserved cases nor its entitlement headroom, and while it
    is `HELD` it can be neither scheduled nor delivered."

    Design: Difficulty/transitive_cascade/recall_hold_propagates_lot_then_appointment_then_order
    """
    env = _scheduled_peach_order(api, allocatable_cases=1001)

    fx.raise_recall(
        api,
        env["lots"][PEACH_CODE]["id"],
        recall_class=RecallClass.CLASS_II,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Supplier reported a packaging integrity defect.",
    )

    lot = fx.read_lot(api, env["lots"][PEACH_CODE]["id"])
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=10, cases_shipped_to_date=0)
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 10, (
        f"cases_committed expected 10 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_delivered"] == 0, (
        f"cases_delivered expected 0 but got {allocation['cases_delivered']}"
    )


def _order_at_its_delivery_window(api):
    """A booked 10-case order against a 10-case entitlement, clock at the window start."""
    env = _scheduled_peach_order(api, allocatable_cases=10)
    fx.set_clock(api, "2026-08-10T10:00:00Z")
    return env


def test_04_confirmation_delivers_the_appointment_and_its_order(api):
    """PRD §3.7: "The appointment moves `SCHEDULED → DELIVERED`, capturing
    `delivered_pounds` from the order's `total_pounds` and recording the confirming
    operator in `confirmed_by_user_id`." PRD §3.7: "The order moves `SCHEDULED →
    DELIVERED`."

    Design: Difficulty/transitive_cascade/delivery_confirmation_propagates_order_allocation_then_cycle_posture
    """
    env = _order_at_its_delivery_window(api)

    appointment = fx.confirm_delivery(
        api, env["appointment"]["id"], env["warehouse"]["id"]
    )

    assert appointment["status"] == AppointmentStatus.DELIVERED, (
        f"appointment status expected DELIVERED but got {appointment['status']}"
    )
    assert_pounds(appointment["delivered_pounds"], 243.75, "delivered_pounds")
    assert appointment["confirmed_by_user_id"] == env["warehouse"]["id"], (
        "confirmed_by_user_id expected the confirming warehouse operator "
        f"{env['warehouse']['id']} but got {appointment['confirmed_by_user_id']}"
    )
    order = fx.read_order(api, env["order"]["id"])
    assert order["status"] == OrderStatus.DELIVERED, (
        f"order status expected DELIVERED but got {order['status']}"
    )


def test_05_delivery_draws_the_entitlement_down_and_flips_the_cycle_posture(api):
    """PRD §3.7: "The entitlement then has `total_cases_approved` subtracted from its
    `cases_committed` and added to its `cases_delivered`, its `cases_remaining` is
    recomputed, and its `status` becomes `FULLY_DRAWN` when `cases_remaining`
    reaches zero and `PARTIALLY_DRAWN` otherwise." PRD §2.11: "it reads
    `NOT_STARTED` while every entitlement of the cycle is still `ENTITLED`,
    `FULLY_DRAWN` only when every entitlement of the cycle is `FULLY_DRAWN`, and
    `PARTIAL` in every other case."

    Design: Difficulty/transitive_cascade/delivery_confirmation_propagates_order_allocation_then_cycle_posture
    """
    env = _order_at_its_delivery_window(api)
    before = fx.read_cycle(api, env["cycle"]["id"])
    assert before["draw_posture"] == DrawPosture.PARTIAL, (
        f"draw_posture before delivery expected PARTIAL but got {before['draw_posture']}"
    )

    fx.confirm_delivery(api, env["appointment"]["id"], env["warehouse"]["id"])

    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_delivered"] == 10, (
        f"cases_delivered expected 10 but got {allocation['cases_delivered']}"
    )
    assert allocation["cases_remaining"] == 0, (
        f"cases_remaining expected 0 but got {allocation['cases_remaining']}"
    )
    assert allocation["status"] == AllocationStatus.FULLY_DRAWN, (
        f"entitlement status expected FULLY_DRAWN but got {allocation['status']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["draw_posture"] == DrawPosture.FULLY_DRAWN, (
        f"draw_posture expected FULLY_DRAWN but got {cycle['draw_posture']}"
    )


def test_06_delivery_settles_the_lot_ledger_and_the_agency_counters(api):
    """PRD §3.7: "Each reserved lot has the reserved cases subtracted from
    `cases_on_hand`, subtracted from `cases_committed`, and added to
    `cases_shipped_to_date`; a lot whose `cases_on_hand` reaches zero moves to
    `DEPLETED` with its `monitor_flag` reset to `NONE`." PRD §3.7: "Finally the
    receiving agency's `agency_cases_on_hand` and `delivered_cases_ytd` each grow by
    the order's `total_cases_approved` — the first is the live stock the agency may
    hand out or return, the second a cumulative year-to-date figure that never
    falls."

    Design: Difficulty/transitive_cascade/delivery_confirmation_propagates_order_allocation_then_cycle_posture
    """
    env = _order_at_its_delivery_window(api)

    fx.confirm_delivery(api, env["appointment"]["id"], env["warehouse"]["id"])

    lot = fx.read_lot(api, env["lots"][PEACH_CODE]["id"])
    assert_lot_ledger(lot, cases_on_hand=90, cases_committed=0, cases_shipped_to_date=10)
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"a lot with cases left expected AVAILABLE but got {lot['status']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 10, (
        f"agency_cases_on_hand expected 10 but got {agency['agency_cases_on_hand']}"
    )
    assert agency["delivered_cases_ytd"] == 10, (
        f"delivered_cases_ytd expected 10 but got {agency['delivered_cases_ytd']}"
    )
