"""Resource serialisers.

Computed fields are derived here from live state, which is equivalent to
recomputing them at every trigger and immune to a missed recompute.
"""
from decimal import Decimal

import calc
import clock


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": clock.iso(row["created_at"]),
        "updated_at": clock.iso(row["updated_at"]),
        "version": row["version"],
    }


def host_site(row):
    data = _common(row)
    data.update({
        "site_code": row["site_code"],
        "host_org_name": row["host_org_name"],
        "agreement_status": row["agreement_status"],
        "power_upgrade_status": row["power_upgrade_status"],
        "access_hours_mode": row["access_hours_mode"],
        "access_open_minute": row["access_open_minute"],
        "access_close_minute": row["access_close_minute"],
        "parking_enforcement_mode": row["parking_enforcement_mode"],
        "committed_service_capacity_kw": _num(row["committed_service_capacity_kw"]),
        "station_count": calc.host_site_station_count(row["id"]),
    })
    return data


def station(row):
    gross, excluded, billable = calc.station_downtime_ledger(row["id"])
    data = _common(row)
    data.update({
        "host_site_id": row["host_site_id"],
        "station_code": row["station_code"],
        "power_class": row["power_class"],
        "declared_port_count": row["declared_port_count"],
        "corridor_designated": row["corridor_designated"],
        "status": row["status"],
        "suspension_source": row["suspension_source"],
        "commissioned_at": clock.iso(row["commissioned_at"]),
        "commissioned_port_count": calc.commissioned_port_count(row["id"]),
        "out_of_service_port_count": calc.out_of_service_port_count(row["id"]),
        "installed_power_kw": _num(calc.installed_power_kw(row["id"])),
        "payment_interop_score": _num(calc.payment_interoperability_score(row["id"])),
        "gross_downtime_minutes_lifetime": gross,
        "excluded_downtime_minutes_lifetime": excluded,
        "billable_downtime_minutes_lifetime": billable,
        "refund_liability_cents": calc.refund_liability_cents(row["id"]),
    })
    return data


def charging_port(row):
    data = _common(row)
    data.update({
        "station_id": row["station_id"],
        "connector_type": row["connector_type"],
        "rated_power_kw": _num(row["rated_power_kw"]),
        "dispenser_serial": row["dispenser_serial"],
        "terminal_model": row["terminal_model"],
        "contactless_enabled": row["contactless_enabled"],
        "plug_and_charge_enabled": row["plug_and_charge_enabled"],
        "price_display_verified": row["price_display_verified"],
        "roaming_ocpi_version": row["roaming_ocpi_version"],
        "terminal_certification_status": row["terminal_certification_status"],
        "service_state": row["service_state"],
        "maintenance_state": row["maintenance_state"],
        "retired_at": clock.iso(row["retired_at"]),
    })
    return data


def outage_event(row):
    data = _common(row)
    data.update({
        "port_id": row["port_id"],
        "fault_code": row["fault_code"],
        "fault_class": row["fault_class"],
        "detected_at": clock.iso(row["detected_at"]),
        "cleared_at": clock.iso(row["cleared_at"]),
        "excluded_cause_claim": row["excluded_cause_claim"],
        "state": row["state"],
        "pre_exclusion_state": row["pre_exclusion_state"],
        "excluded_at": clock.iso(row["excluded_at"]),
        "dispatch_created_by_user_id": row["dispatch_created_by_user_id"],
        "is_system_generated": row["is_system_generated"],
    })
    return data


def maintenance_dispatch(row):
    data = _common(row)
    data.update({
        "outage_event_id": row["outage_event_id"],
        "port_id": row["port_id"],
        "technician_user_id": row["technician_user_id"],
        "technician_certification_class": row["technician_certification_class"],
        "window_start_at": clock.iso(row["window_start_at"]),
        "window_end_at": clock.iso(row["window_end_at"]),
        "response_deadline_at": clock.iso(row["response_deadline_at"]),
        "arrived_at": clock.iso(row["arrived_at"]),
        "response_met": row["response_met"],
        "promised_repair_at": clock.iso(row["promised_repair_at"]),
        "total_hold_minutes": row["total_hold_minutes"],
        "created_by_user_id": row["created_by_user_id"],
        "state": row["state"],
    })
    return data


def spare_part(row):
    data = _common(row)
    data.update({
        "part_number": row["part_number"],
        "part_class": row["part_class"],
        "on_hand_qty": row["on_hand_qty"],
        "reserved_qty": calc.reserved_qty(row["id"]),
        "backordered_qty": calc.backordered_qty(row["id"]),
        "consumed_qty_lifetime": calc.consumed_qty_lifetime(row["id"]),
        "unencumbered_qty": calc.unencumbered_qty(row),
        "lead_time_days": row["lead_time_days"],
    })
    return data


def part_reservation(row):
    data = _common(row)
    data.update({
        "dispatch_id": row["dispatch_id"],
        "spare_part_id": row["spare_part_id"],
        "qty": row["qty"],
        "state": row["state"],
        "expected_available_at": clock.iso(row["expected_available_at"]),
    })
    return data


def uptime_report(row):
    data = _common(row)
    data.update({
        "station_id": row["station_id"],
        "period_start": clock.iso(row["period_start"]),
        "period_end": clock.iso(row["period_end"]),
        "methodology": row["methodology"],
        "eligible_port_count": row["eligible_port_count"],
        "total_port_minutes": row["total_port_minutes"],
        "excluded_minutes": row["excluded_minutes"],
        "billable_downtime_minutes": row["billable_downtime_minutes"],
        "uptime_pct": _num(row["uptime_pct"]),
        "state": row["state"],
        "finalized_by_user_id": row["finalized_by_user_id"],
        "claim_count": row["claim_count"],
        "returned_count": row["returned_count"],
    })
    return data


def reimbursement_claim(row):
    data = _common(row)
    data.update({
        "uptime_report_id": row["uptime_report_id"],
        "line_items": [
            {
                "port_id": item["port_id"],
                "category": item["category"],
                "amount_cents": item["amount_cents"],
            }
            for item in row["line_items"]
        ],
        "requested_amount_cents": row["requested_amount_cents"],
        "remediation_credit_pp": _num(row["remediation_credit_pp"]),
        "effective_uptime_pct": _num(row["effective_uptime_pct"]),
        "withhold_rate": _num(row["withhold_rate"]),
        "withheld_amount_cents": row["withheld_amount_cents"],
        "approved_amount_cents": row["approved_amount_cents"],
        "state": row["state"],
        "decided_by_user_id": row["decided_by_user_id"],
    })
    return data


def customer_complaint(row):
    data = _common(row)
    data.update({
        "station_id": row["station_id"],
        "port_id": row["port_id"],
        "linked_outage_event_id": row["linked_outage_event_id"],
        "complaint_type": row["complaint_type"],
        "session_started_at": clock.iso(row["session_started_at"]),
        "session_ended_at": clock.iso(row["session_ended_at"]),
        "session_energy_kwh": _num(row["session_energy_kwh"]),
        "session_price_per_kwh_cents": row["session_price_per_kwh_cents"],
        "session_idle_fee_cents": row["session_idle_fee_cents"],
        "session_charged_cents": row["session_charged_cents"],
        "state": row["state"],
        "refund_state": row["refund_state"],
        "refund_basis": row["refund_basis"],
        "refund_amount_cents": row["refund_amount_cents"],
        "retained_amount_cents": row["retained_amount_cents"],
        "refund_requested_by_user_id": row["refund_requested_by_user_id"],
        "refund_settled_at": clock.iso(row["refund_settled_at"]),
    })
    return data
