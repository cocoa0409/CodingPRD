"""Payload factories - one per writable endpoint, input fields only."""


def create_donor_payload(full_name="Test Donor", **overrides):
    payload = {"full_name": full_name}
    payload.update(overrides)
    return payload


def update_donor_payload(**fields):
    return dict(fields)


def create_batch_payload(donor_id, source="WALK_IN", receipt_requested=None):
    payload = {"donor_id": donor_id, "source": source}
    if receipt_requested is not None:
        payload["receipt_requested"] = receipt_requested
    return payload


def create_item_payload(category="CLOTHING", condition="GOOD", **overrides):
    payload = {"category": category, "condition": condition}
    payload.update(overrides)
    return payload


def triage_payload(decision="SALABLE", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def revalue_payload(expected_batch_version, adjustments):
    return {
        "expected_batch_version": expected_batch_version,
        "adjustments": adjustments,
    }


def create_guideline_payload(category, base_cents, demand_multiplier=None):
    payload = {"category": category, "base_cents": base_cents}
    if demand_multiplier is not None:
        payload["demand_multiplier"] = demand_multiplier
    return payload


def create_vendor_payload(name, rates):
    return {"name": name, "rates": rates}


def seal_bale_payload(vendor_id):
    return {"vendor_id": vendor_id}


def settle_bale_payload(actual_weight_lbs):
    return {"actual_weight_lbs": actual_weight_lbs}


def create_till_session_payload(opening_float_cents=5000):
    return {"opening_float_cents": opening_float_cents}


def count_session_payload(counted_cash_cents):
    return {"counted_cash_cents": counted_cash_cents}


def create_sale_payload(till_session_id, item_ids, payment_method="CASH"):
    return {
        "till_session_id": till_session_id,
        "item_ids": item_ids,
        "payment_method": payment_method,
    }


def void_sale_payload(reason=None):
    payload = {}
    if reason is not None:
        payload["reason"] = reason
    return payload


def create_route_payload(route_date, driver_worker_id, truck_capacity_cuft):
    return {
        "route_date": route_date,
        "driver_worker_id": driver_worker_id,
        "truck_capacity_cuft": truck_capacity_cuft,
    }


def create_stop_payload(donor_id, window_start, window_end, estimated_volume_cuft):
    return {
        "donor_id": donor_id,
        "window_start": window_start,
        "window_end": window_end,
        "estimated_volume_cuft": estimated_volume_cuft,
    }


def reschedule_stop_payload(target_route_id, window_start, window_end):
    return {
        "target_route_id": target_route_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def create_worker_payload(full_name, employment_type="STAFF", **overrides):
    payload = {"full_name": full_name, "employment_type": employment_type}
    payload.update(overrides)
    return payload


def update_worker_payload(**fields):
    return dict(fields)


def create_shift_payload(role_type, starts_at, ends_at, required_headcount=1):
    return {
        "role_type": role_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "required_headcount": required_headcount,
    }


def create_assignment_payload(worker_id):
    return {"worker_id": worker_id}


def create_transfer_payload(expected_cycle_version, allocations):
    return {
        "expected_cycle_version": expected_cycle_version,
        "allocations": allocations,
    }


def shrink_payload(reason="THEFT"):
    return {"reason": reason}


def clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}
