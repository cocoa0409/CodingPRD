"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional input fields (incoterm, tolerance_class,
scrap_allowance_pct, setup_fee_cents, buffer_min) are included with sensible
defaults but may be overridden or deleted by tests that exercise omission.
"""


def create_rfq_payload(**overrides) -> dict:
    defaults = {
        "customer_name": "Test Customer",
        "customer_id": "CUST-TEST",
        "requested_due_date": "2026-09-01T00:00:00Z",
        "incoterm": "EXW",
    }
    defaults.update(overrides)
    return defaults


def create_part_line_payload(**overrides) -> dict:
    defaults = {
        "part_number": "P-TEST",
        "drawing_rev": "A",
        "material_spec": "AL_6061",
        "quantity": 1,
        "tolerance_class": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(rfq_id: str, part_line_id: str, **overrides) -> dict:
    defaults = {
        "rfq_id": rfq_id,
        "part_line_id": part_line_id,
        "material_unit_cost_cents": 1000,
        "scrap_allowance_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_routing_op_payload(seq: int, machine_class: str, estimated_cycle_min, **overrides) -> dict:
    defaults = {
        "seq": seq,
        "machine_class": machine_class,
        "estimated_cycle_min": estimated_cycle_min,
        "setup_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(quote_id: str, part_line_id: str, qty_ordered: int,
                              qty_started: int, **overrides) -> dict:
    defaults = {
        "quote_id": quote_id,
        "part_line_id": part_line_id,
        "qty_ordered": qty_ordered,
        "qty_started": qty_started,
    }
    defaults.update(overrides)
    return defaults


def create_material_lot_payload(material_spec: str, qty_received: int,
                                unit_cost_cents: int, received_at: str, **overrides) -> dict:
    defaults = {
        "material_spec": material_spec,
        "heat_number": "H-TEST",
        "qty_received": qty_received,
        "unit_cost_cents": unit_cost_cents,
        "received_at": received_at,
    }
    defaults.update(overrides)
    return defaults


def create_machine_slot_payload(machine_class: str, machine_code: str, routing_op_id: str,
                                start_min: int, end_min: int, **overrides) -> dict:
    defaults = {
        "machine_class": machine_class,
        "machine_code": machine_code,
        "routing_op_id": routing_op_id,
        "start_min": start_min,
        "end_min": end_min,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_station_payload(name: str = "CMM-TEST",
                                      supports_mode: str = "ALL", **overrides) -> dict:
    defaults = {
        "name": name,
        "supports_mode": supports_mode,
        "buffer_min": 15,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(work_order_id: str, inspection_station_id: str, mode: str,
                              window_start_min: int, window_end_min: int, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "inspection_station_id": inspection_station_id,
        "mode": mode,
        "window_start_min": window_start_min,
        "window_end_min": window_end_min,
    }
    defaults.update(overrides)
    return defaults


def disposition_payload(qty_inspected: int, qty_accepted: int, qty_rework: int,
                        qty_scrap: int, **overrides) -> dict:
    defaults = {
        "qty_inspected": qty_inspected,
        "qty_accepted": qty_accepted,
        "qty_rework": qty_rework,
        "qty_scrap": qty_scrap,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(work_order_id: str, qty_shipped: int,
                            promised_date: str, actual_ship_date: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "qty_shipped": qty_shipped,
        "promised_date": promised_date,
        "actual_ship_date": actual_ship_date,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(shipment_id: str, **overrides) -> dict:
    defaults = {"shipment_id": shipment_id}
    defaults.update(overrides)
    return defaults
