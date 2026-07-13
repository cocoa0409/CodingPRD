"""Resource serializers. Datetimes become ISO 8601 UTC with 3 fractional digits."""
from store import fmt_dt


def _common(r):
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def rate_card(r):
    d = _common(r)
    d.update({
        "name": r["name"],
        "per_stop_fee_cents": r["per_stop_fee_cents"],
        "per_mile_rate_cents": r["per_mile_rate_cents"],
        "stat_surcharge_pct": r["stat_surcharge_pct"],
        "stat_surcharge_cap_cents": r["stat_surcharge_cap_cents"],
        "temp_handling_fee_cents": r["temp_handling_fee_cents"],
    })
    return d


def lab_client(r):
    d = _common(r)
    d.update({
        "name": r["name"],
        "budget_cents": r["budget_cents"],
        "contact": r["contact"],
        "billed_balance_cents": r["billed_balance_cents"],
    })
    return d


def driver(r):
    d = _common(r)
    d.update({
        "name": r["name"],
        "credential_type": r["credential_type"],
        "credential_expiry": fmt_dt(r["credential_expiry"]),
        "status": r["status"],
    })
    return d


def vehicle(r):
    d = _common(r)
    d.update({
        "plate": r["plate"],
        "has_refrigeration": r["has_refrigeration"],
        "sanitation_buffer_minutes": r["sanitation_buffer_minutes"],
        "status": r["status"],
        "last_released_at": fmt_dt(r["last_released_at"]),
    })
    return d


def route_template(r):
    d = _common(r)
    d.update({
        "lab_client_id": r["lab_client_id"],
        "rate_card_id": r["rate_card_id"],
        "cadence": r["cadence"],
        "default_run_type": r["default_run_type"],
        "stop_specs": r["stop_specs"],
    })
    return d


def route(r):
    d = _common(r)
    d.update({
        "lab_client_id": r["lab_client_id"],
        "rate_card_id": r["rate_card_id"],
        "template_id": r["template_id"],
        "driver_id": r["driver_id"],
        "vehicle_id": r["vehicle_id"],
        "run_type": r["run_type"],
        "scheduled_start": fmt_dt(r["scheduled_start"]),
        "scheduled_end": fmt_dt(r["scheduled_end"]),
        "planned_total_miles": r["planned_total_miles"],
        "sla_deadline": fmt_dt(r["sla_deadline"]),
        "provisional_charge_cents": r["provisional_charge_cents"],
        "final_charge_cents": r["final_charge_cents"],
        "status": r["status"],
    })
    return d


def stop(r):
    d = _common(r)
    d.update({
        "route_id": r["route_id"],
        "sequence": r["sequence"],
        "address": r["address"],
        "stop_kind": r["stop_kind"],
        "planned_leg_miles": r["planned_leg_miles"],
        "actual_leg_miles": r["actual_leg_miles"],
        "leg_charge_cents": r["leg_charge_cents"],
        "arrived_at": fmt_dt(r["arrived_at"]),
        "completed_at": fmt_dt(r["completed_at"]),
        "status": r["status"],
    })
    return d


def specimen(r):
    d = _common(r)
    d.update({
        "route_id": r["route_id"],
        "pickup_stop_id": r["pickup_stop_id"],
        "dropoff_stop_id": r["dropoff_stop_id"],
        "specimen_type": r["specimen_type"],
        "temp_requirement": r["temp_requirement"],
        "required_temp_min_c": r["required_temp_min_c"],
        "required_temp_max_c": r["required_temp_max_c"],
        "custody_status": r["custody_status"],
        "integrity_status": r["integrity_status"],
        "excursion_count": r["excursion_count"],
        "picked_up_at": fmt_dt(r["picked_up_at"]),
        "delivered_at": fmt_dt(r["delivered_at"]),
        "estimated_risk_score": r["estimated_risk_score"],
        "final_risk_score": r["final_risk_score"],
    })
    return d


def scan_event(r):
    # Append-only chain-of-custody record: only id + created_at (PRD 2.4).
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "specimen_id": r["specimen_id"],
        "driver_id": r["driver_id"],
        "stop_id": r["stop_id"],
        "scan_type": r["scan_type"],
        "temp_reading_c": r["temp_reading_c"],
        "leg_miles": r["leg_miles"],
        "scanned_at": fmt_dt(r["scanned_at"]),
        "is_excursion": r["is_excursion"],
    }


def route_exception(r):
    d = _common(r)
    d.update({
        "route_id": r["route_id"],
        "stop_id": r["stop_id"],
        "specimen_id": r["specimen_id"],
        "exception_type": r["exception_type"],
        "detail": r["detail"],
        "resolution_note": r["resolution_note"],
        "status": r["status"],
    })
    return d


def run_billing(r):
    d = _common(r)
    d.update({
        "route_id": r["route_id"],
        "lab_client_id": r["lab_client_id"],
        "gross_charge_cents": r["gross_charge_cents"],
        "surcharge_cents": r["surcharge_cents"],
        "net_charge_cents": r["net_charge_cents"],
        "status": r["status"],
    })
    return d
