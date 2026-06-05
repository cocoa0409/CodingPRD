"""Payload factories — one per entity, input fields only (MES PRD §3)."""

DEFAULTS = {
    "PLANNED_PRODUCTION_SECS": 28800,
    "WORK_CENTER": "WC1",
    "IDEAL_CYCLE_TIME_SECS": 100,
}


def create_product_payload(sku="FGTEST", name="Test Product",
                           product_type="FINISHED_GOOD", **overrides) -> dict:
    """POST /products. unit_cost_cents and lot_controlled are optional (defaults 0/false)."""
    payload = {
        "sku": sku,
        "name": name,
        "product_type": product_type,
    }
    payload.update(overrides)
    return payload


def create_bom_line_payload(parent_product_id, component_product_id,
                            quantity_per=1, **overrides) -> dict:
    """POST /bom-lines. scrap_factor_pct optional (default 0)."""
    payload = {
        "parent_product_id": parent_product_id,
        "component_product_id": component_product_id,
        "quantity_per": quantity_per,
    }
    payload.update(overrides)
    return payload


def create_routing_payload(product_id, routing_code="RT-TEST", **overrides) -> dict:
    """POST /routings."""
    payload = {
        "product_id": product_id,
        "routing_code": routing_code,
    }
    payload.update(overrides)
    return payload


def create_operation_payload(machine_id, sequence_no=10,
                             ideal_cycle_time_secs=100, **overrides) -> dict:
    """POST /routings/{id}/operations. setup_buffer_secs optional (default 0)."""
    payload = {
        "machine_id": machine_id,
        "sequence_no": sequence_no,
        "ideal_cycle_time_secs": ideal_cycle_time_secs,
    }
    payload.update(overrides)
    return payload


def create_machine_payload(machine_code="M-TEST", work_center="WC1",
                           planned_production_secs=28800, **overrides) -> dict:
    """POST /machines."""
    payload = {
        "machine_code": machine_code,
        "work_center": work_center,
        "planned_production_secs": planned_production_secs,
    }
    payload.update(overrides)
    return payload


def create_run_log_payload(window_start, window_end, run_time_secs,
                           total_units, good_units, **overrides) -> dict:
    """POST /machines/{id}/run-logs."""
    payload = {
        "window_start": window_start,
        "window_end": window_end,
        "run_time_secs": run_time_secs,
        "total_units": total_units,
        "good_units": good_units,
    }
    payload.update(overrides)
    return payload


def create_lot_payload(product_id, lot_code="L-TEST", received_qty=5, **overrides) -> dict:
    """POST /lots."""
    payload = {
        "product_id": product_id,
        "lot_code": lot_code,
        "received_qty": received_qty,
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(product_id, routing_id, order_qty=1, **overrides) -> dict:
    """POST /work-orders."""
    payload = {
        "product_id": product_id,
        "routing_id": routing_id,
        "order_qty": order_qty,
    }
    payload.update(overrides)
    return payload


def release_work_order_payload(expected_work_order_version, **overrides) -> dict:
    """POST /work-orders/{id}/release. expected_work_order_version is required (§2.8)."""
    payload = {
        "expected_work_order_version": expected_work_order_version,
    }
    payload.update(overrides)
    return payload


def create_lot_issue_payload(component_demand_id, lot_id, work_order_operation_id,
                             issued_qty, **overrides) -> dict:
    """POST /lot-issues."""
    payload = {
        "component_demand_id": component_demand_id,
        "lot_id": lot_id,
        "work_order_operation_id": work_order_operation_id,
        "issued_qty": issued_qty,
    }
    payload.update(overrides)
    return payload


def create_signoff_payload(result="PASS", **overrides) -> dict:
    """POST /work-order-operations/{id}/signoffs."""
    payload = {"result": result}
    payload.update(overrides)
    return payload


def create_scrap_disposition_payload(quantity, defect_code="DEF", **overrides) -> dict:
    """POST /work-order-operations/{id}/scrap-dispositions."""
    payload = {
        "quantity": quantity,
        "defect_code": defect_code,
    }
    payload.update(overrides)
    return payload


def disposition_payload(decision, **overrides) -> dict:
    """POST /scrap-dispositions/{id}/disposition. decision is SCRAP or REWORK."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def set_machine_status_payload(status, **overrides) -> dict:
    """POST /machines/{id}/status."""
    payload = {"status": status}
    payload.update(overrides)
    return payload
