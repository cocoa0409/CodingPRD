"""Weigh-in and net-weight calculation: tare aggregation, the zero floor, and
the append-only system fields of a weight ticket.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_onsite_order_en_route,
)
from test_helpers import factories as f

CO = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# boundary_precision_check / net_weight_zero_floor_on_weigh_in
# ===========================================================================
def test_net_weight_floored_at_zero_when_gross_below_tare(api):
    """PRD §3.5: "then sets net_weight_kg to the gross weight minus that tare
    total, with the result held to three decimal places of a kilogram and floored
    at zero so it can never go negative."

    Two CONSOLE containers (tare 8.0 + 5.0 = 13.0); gross 5.0 < tare 13.0 yields
    net 0.0, not -8.0.

    Design: Difficulty/boundary_precision_check/net_weight_zero_floor_on_weigh_in
    """
    state = setup_onsite_order_en_route(
        tech_id="tech-1",
        container_specs=[
            {"container_type": "CONSOLE", "capacity_kg": 50, "tare_weight_kg": 8.0},
            {"container_type": "CONSOLE", "capacity_kg": 30, "tare_weight_kg": 5.0},
        ],
        weigh_in=False,
    )
    data = validate_success(
        api.weigh_in_order(state["order"]["id"], f.weigh_in_payload(5.0), state["tech_headers"]),
        201,
    )
    assert data["net_weight_kg"] == 0.0, f"net floored at 0, got {data['net_weight_kg']}"
    assert data["tare_total_kg"] == 13.0, f"tare total, got {data['tare_total_kg']}"


def test_net_weight_tare_total_sums_container_tares(api):
    """PRD §3.5: "The net-weight calculation sums the tare_weight_kg of every
    container listed in the parent order's container_ids - regardless of each
    container's current status - to obtain tare_total_kg."

    Two CONSOLE containers with tares 8.0 and 5.0 produce tare_total_kg 13.0.

    Design: Difficulty/boundary_precision_check/net_weight_zero_floor_on_weigh_in
    """
    state = setup_onsite_order_en_route(
        tech_id="tech-1",
        container_specs=[
            {"container_type": "CONSOLE", "capacity_kg": 50, "tare_weight_kg": 8.0},
            {"container_type": "CONSOLE", "capacity_kg": 30, "tare_weight_kg": 5.0},
        ],
        weigh_in=False,
    )
    data = validate_success(
        api.weigh_in_order(state["order"]["id"], f.weigh_in_payload(5.0), state["tech_headers"]),
        201,
    )
    assert data["tare_total_kg"] == 13.0


# ===========================================================================
# Corner: entities / weight_ticket_default_fields_only
# ===========================================================================
def test_weight_ticket_computed_and_system_fields(api):
    """PRD §3.5: "producing a weight ticket - an append-only record carrying the
    order's order_id, the scale's gross_weight_kg (which must be at least 0), the
    computed tare_total_kg, the computed net_weight_kg, and the captured_by
    identifier of the operator who recorded it."

    One CONSOLE (tare 8.0); gross 30.0 -> tare_total 8.0, net 22.0, and
    captured_by is the recording operator's X-User-ID (tech-1).

    Design: Corner/entities/weight_ticket_default_fields_only
    """
    state = setup_onsite_order_en_route(tech_id="tech-1", weigh_in=False)
    data = validate_success(
        api.weigh_in_order(state["order"]["id"], f.weigh_in_payload(30.0), state["tech_headers"]),
        201,
    )
    assert data["tare_total_kg"] == 8.0, f"got {data['tare_total_kg']}"
    assert data["net_weight_kg"] == 22.0, f"got {data['net_weight_kg']}"
    assert data["captured_by"] == "tech-1", f"got {data['captured_by']}"
