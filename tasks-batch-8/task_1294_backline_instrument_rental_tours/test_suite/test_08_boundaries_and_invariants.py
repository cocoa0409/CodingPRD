"""Boundary precision (maintenance day-30 gate, charge-vs-hold equality) and
the shipment weight conservation invariant."""
from test_helpers import (
    validate_success, ApiErrorId,
    get_unit, get_reservation, find_ticket_for_unit,
    setup_maintenance_gate_boundary_pair, setup_overage_pair, setup_weight_scene,
    api_client, TEST_USERS,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]
LC = TEST_USERS["logistics_headers"]
WT = TEST_USERS["warehouse_tech_headers"]


def test_gate_29_days_returns_available(api, warehouse_tech_headers):
    """PRD §3.6: "the gate projects the unit's `rental_days_since_service` plus
    the days of the returning reservation, and when that projection reaches 30 —
    exactly 30 included — or the unit's `condition_score` has fallen below 40,
    the unit moves from `OUT_ON_RENTAL` (or `IN_TRANSIT`, if a claim or a leg
    left it there) to `MAINTENANCE` instead of back to the pool".
    PRD §3.6: "A clean return moves the unit from `OUT_ON_RENTAL` to
    `AVAILABLE`, adds the reservation's rental days to its
    `rental_days_since_service`, and clears its `active_reservation_id`."
    Projected 0 + 29 = 29 stays below the threshold.

    Design: Difficulty/boundary_precision_check/maintenance_gate_day30_exact_boundary
    """
    ctx = setup_maintenance_gate_boundary_pair()
    assert ctx["u29"] != ctx["u30"]

    returned = validate_success(api.check_in_reservation(
        ctx["r29"]["id"], {"checked_in_at": "2026-08-30T09:00:00Z"}, warehouse_tech_headers))
    assert returned["status"] == "RETURNED"
    unit = get_unit(ctx["u29"])
    assert unit["status"] == "AVAILABLE"
    assert unit["rental_days_since_service"] == 29


def test_gate_30_days_exactly_forces_maintenance(api, warehouse_tech_headers):
    """PRD §3.6: "the gate projects the unit's `rental_days_since_service` plus
    the days of the returning reservation, and when that projection reaches 30 —
    exactly 30 included — or the unit's `condition_score` has fallen below 40,
    the unit moves from `OUT_ON_RENTAL` (or `IN_TRANSIT`, if a claim or a leg
    left it there) to `MAINTENANCE` instead of back to the pool, and a
    maintenance ticket is opened with `opened_reason` `SCHEDULED_CYCLE` when the
    day threshold tripped or `CONDITION_THRESHOLD` when the condition did."
    Projected 0 + 30 = 30 — exactly 30 included — routes the unit to
    MAINTENANCE and opens a SCHEDULED_CYCLE ticket.

    Design: Difficulty/boundary_precision_check/maintenance_gate_day30_exact_boundary
    """
    ctx = setup_maintenance_gate_boundary_pair()
    validate_success(api.check_in_reservation(
        ctx["r30"]["id"], {"checked_in_at": "2026-08-31T09:00:00Z"}, warehouse_tech_headers))

    unit = get_unit(ctx["u30"])
    assert unit["status"] == "MAINTENANCE"
    ticket = find_ticket_for_unit(ctx["u30"])
    assert ticket["opened_reason"] == "SCHEDULED_CYCLE"


def test_damage_charge_exactly_equal_to_hold(api, tour_manager_headers):
    """PRD §3.7: "The `charge_cents` figure is the repair estimate for ordinary
    severities, or the model's full `replacement_value_cents` for `TOTAL_LOSS`."
    PRD §3.7: "The charge draws first against the linked reservation's
    `deposit_held_cents`; only the portion strictly exceeding the hold is billed
    directly as an overage, so a charge exactly equal to the hold leaves no
    overage at all."
    Repair estimate 55000 equals the 55000 hold: charge lands exactly at the
    hold with nothing left over.

    Design: Difficulty/boundary_precision_check/damage_charge_deposit_exact_overage_boundary
    """
    ctx = setup_overage_pair()
    assert ctx["r1"]["deposit_held_cents"] == 55_000

    charged = validate_success(api.charge_damage_claim(ctx["dc1"]["id"],
                                                       tour_manager_headers))
    assert charged["status"] == "CHARGED"
    assert charged["charge_cents"] == 55_000


def test_damage_charge_one_cent_over_hold(api, tour_manager_headers):
    """PRD §3.7: "The `charge_cents` figure is the repair estimate for ordinary
    severities, or the model's full `replacement_value_cents` for `TOTAL_LOSS`."
    PRD §3.7: "only the portion strictly exceeding the hold is billed directly
    as an overage, so a charge exactly equal to the hold leaves no overage at
    all."
    Repair estimate 55001 exceeds the 55000 hold by one cent, so the charge is
    55001 with the single-cent remainder billed directly.

    Design: Difficulty/boundary_precision_check/damage_charge_deposit_exact_overage_boundary
    """
    ctx = setup_overage_pair()
    assert ctx["r2"]["deposit_held_cents"] == 55_000

    charged = validate_success(api.charge_damage_claim(ctx["dc2"]["id"],
                                                       tour_manager_headers))
    assert charged["status"] == "CHARGED"
    assert charged["charge_cents"] == 55_001


def test_shipment_weight_conserved_under_line_cancel(api, logistics_headers):
    """PRD §3.5: "Both aggregates reconcile on every line mutation:
    `booked_weight_kg` sums the `weight_kg` of non-cancelled lines, and
    `tech_labor_minutes` sums their `labor_minutes`."
    PRD §3.5: "A single line can also be cancelled from `BOOKED` on its own,
    which recomputes the leg's booked weight."
    Booking 30 + 40 yields 70; cancelling the 30kg line leaves exactly 40 and
    labor 20 - 10 = 10, drift-free.

    Design: Difficulty/compensating_invariant/shipment_weight_conserved_under_load_then_cancel
    """
    ctx = setup_weight_scene()
    shipment = validate_success(api.get_shipment(ctx["shipment"]["id"], logistics_headers))
    assert shipment["booked_weight_kg"] == 70
    assert shipment["tech_labor_minutes"] == 20

    validate_success(api.cancel_shipment_line(ctx["sl1"]["id"], logistics_headers))
    after = validate_success(api.get_shipment(ctx["shipment"]["id"], logistics_headers))
    assert after["booked_weight_kg"] == 40
    assert after["tech_labor_minutes"] == 10


def test_shipment_cancel_zeroes_aggregates(api, logistics_headers):
    """PRD §3.5: "Cancellation is possible from `PLANNED` or `LOADING` so long
    as no line has reached `LOADED`: each `BOOKED` line is cancelled, each
    assigned case is released back to `AVAILABLE`, and the aggregates
    reconcile."
    PRD §3.5: "`booked_weight_kg` sums the `weight_kg` of non-cancelled lines".

    Design: Difficulty/compensating_invariant/shipment_weight_conserved_under_load_then_cancel
    """
    ctx = setup_weight_scene()
    cancelled = validate_success(api.cancel_shipment(ctx["shipment"]["id"], logistics_headers))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["booked_weight_kg"] == 0

    line = validate_success(api.get_shipment(ctx["shipment"]["id"], logistics_headers))
    assert line["booked_weight_kg"] == 0
    assert line["tech_labor_minutes"] == 0
