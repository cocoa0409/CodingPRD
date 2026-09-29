"""Derived roll-ups and resource representations."""
from decimal import Decimal

import calc
import db
from util import dec, q1


# ===========================================================================
# tower roll-ups
# ===========================================================================
def tower_backhaul_accepted_mbps(tower_id):
    total = 0
    for circuit in db.backhaul_circuits.values():
        if circuit["tower_id"] == tower_id and circuit["state"] == "ACCEPTED":
            total += int(circuit["committed_mbps"])
    return total


def tower_active_sector_count(tower_id):
    return sum(1 for s in db.sectors.values()
               if s["tower_id"] == tower_id and s["status"] == "ACTIVE")


def tower_sectors(tower_id):
    return db.ordered([s for s in db.sectors.values() if s["tower_id"] == tower_id])


# ===========================================================================
# spectrum licence
# ===========================================================================
def license_status(license_record, clock_now=None):
    now = clock_now if clock_now is not None else db.now()
    if now < license_record["effective_from"]:
        return "PENDING"
    if now < license_record["effective_to"]:
        return "ACTIVE"
    return "EXPIRED"


def license_edges(license_record):
    return calc.channel_edges(license_record["channel_center_mhz"],
                              license_record["channel_width_mhz"])


# ===========================================================================
# sector ledger
# ===========================================================================
def sector_sold_mbps(sector_id):
    total = 0
    for subscriber in db.subscribers.values():
        if subscriber["sector_id"] != sector_id:
            continue
        if subscriber["service_status"] not in ("PENDING_INSTALL", "ACTIVE", "SUSPENDED"):
            continue
        plan = db.service_plans.get(subscriber["service_plan_id"])
        if plan is not None:
            total += int(plan["downstream_mbps"])
    return total


def sector_held_mbps(sector_id):
    total = 0
    for hold in db.capacity_holds.values():
        if hold["sector_id"] == sector_id and hold["status"] == "HELD":
            total += int(hold["held_mbps"])
    return total


def sector_ledger(sector):
    """The live capacity ledger of one sector (PRD 3.3)."""
    tower = db.towers.get(sector["tower_id"]) or {}
    sold = sector_sold_mbps(sector["id"])
    held = sector_held_mbps(sector["id"])
    committed = sold + held
    max_ratio = dec(sector["max_oversubscription_ratio"])
    ratio = calc.oversubscription_ratio(committed, sector["capacity_mbps"])
    backhaul = tower_backhaul_accepted_mbps(sector["tower_id"])
    posture = calc.capacity_posture(
        sector["status"], tower.get("status"), backhaul, ratio, max_ratio, committed)
    remaining = calc.remaining_allowance_mbps(sector["capacity_mbps"], max_ratio, committed)
    return {
        "sold_mbps": sold,
        "held_mbps": held,
        "committed_mbps": committed,
        "oversubscription_ratio": ratio,
        "remaining_allowance_mbps": remaining,
        "capacity_posture": posture,
    }


def sector_snapshot(sector):
    """Tuple of every derived sector field, used to detect ledger mutations."""
    ledger = sector_ledger(sector)
    return (
        ledger["sold_mbps"], ledger["held_mbps"], ledger["committed_mbps"],
        str(ledger["oversubscription_ratio"]), ledger["remaining_allowance_mbps"],
        ledger["capacity_posture"],
    )


def sector_edges(sector):
    return calc.channel_edges(sector["channel_center_mhz"], sector["channel_width_mhz"])


# ===========================================================================
# subscriber roll-ups
# ===========================================================================
def subscriber_usage_records(subscriber_id):
    return [r for r in db.usage_records.values() if r["subscriber_id"] == subscriber_id]


def subscriber_cycle_usage_gb(subscriber):
    start = subscriber.get("cycle_start_date")
    if start is None:
        return Decimal("0.0")
    inside = [r for r in subscriber_usage_records(subscriber["id"])
              if calc.in_window(r["usage_date"], start)]
    return calc.accumulate_cycle_usage(inside)


def subscriber_credit_balance_cents(subscriber_id):
    total = 0
    for credit in db.outage_credits.values():
        if credit["subscriber_id"] == subscriber_id and credit["status"] == "APPLIED":
            total += int(credit["credit_cents"])
    return total


def subscriber_settlement_balance_cents(subscriber_id):
    total = 0
    for assignment in db.equipment_assignments.values():
        if assignment["subscriber_id"] != subscriber_id:
            continue
        if assignment["status"] in ("RETURNED", "UNRETURNED_BILLED", "VOIDED"):
            total += int(assignment["settlement_cents"])
    return total


def subscriber_equipment_monthly_charge_cents(subscriber_id):
    total = 0
    for assignment in db.equipment_assignments.values():
        if assignment["subscriber_id"] != subscriber_id:
            continue
        if assignment["status"] == "DEPLOYED":
            total += int(assignment["monthly_rental_cents"])
    return total


def subscriber_assignments(subscriber_id):
    return db.ordered([a for a in db.equipment_assignments.values()
                       if a["subscriber_id"] == subscriber_id])


def subscriber_work_orders(subscriber_id):
    return db.ordered([w for w in db.install_work_orders.values()
                       if w["subscriber_id"] == subscriber_id])


def outage_total_credited_cents(outage_event_id):
    total = 0
    for credit in db.outage_credits.values():
        if credit["outage_event_id"] == outage_event_id and credit["status"] == "APPLIED":
            total += int(credit["credit_cents"])
    return total


# ===========================================================================
# representations
# ===========================================================================
def _common(record):
    return {
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def tower_view(tower):
    out = {
        "id": tower["id"],
        "site_code": tower["site_code"],
        "latitude": tower["latitude"],
        "longitude": tower["longitude"],
        "ground_elevation_m": tower["ground_elevation_m"],
        "antenna_agl_m": tower["antenna_agl_m"],
        "status": tower["status"],
        "lease_landowner_name": tower["lease_landowner_name"],
        "lease_monthly_base_rent_cents": tower["lease_monthly_base_rent_cents"],
        "lease_escalator_pct": tower["lease_escalator_pct"],
        "lease_start_date": tower["lease_start_date"],
        "lease_term_months": tower["lease_term_months"],
        "current_monthly_rent_cents": calc.current_monthly_rent_cents(tower, db.now()),
        "active_sector_count": tower_active_sector_count(tower["id"]),
        "backhaul_accepted_mbps": tower_backhaul_accepted_mbps(tower["id"]),
    }
    out.update(_common(tower))
    return out


def circuit_view(circuit):
    out = {
        "id": circuit["id"],
        "tower_id": circuit["tower_id"],
        "carrier_name": circuit["carrier_name"],
        "circuit_ref": circuit["circuit_ref"],
        "committed_mbps": circuit["committed_mbps"],
        "monthly_cost_cents": circuit["monthly_cost_cents"],
        "state": circuit["state"],
        "measured_mbps": circuit["measured_mbps"],
        "accepted_at": circuit["accepted_at"],
        "degraded_since": circuit["degraded_since"],
    }
    out.update(_common(circuit))
    return out


def license_view(record):
    lower, upper = license_edges(record)
    out = {
        "id": record["id"],
        "license_ref": record["license_ref"],
        "band": record["band"],
        "channel_center_mhz": record["channel_center_mhz"],
        "channel_width_mhz": record["channel_width_mhz"],
        "max_eirp_dbm": record["max_eirp_dbm"],
        "license_area_code": record["license_area_code"],
        "effective_from": record["effective_from"],
        "effective_to": record["effective_to"],
        "lower_edge_mhz": lower,
        "upper_edge_mhz": upper,
        "status": license_status(record),
    }
    out.update(_common(record))
    return out


def sector_view(sector):
    lower, upper = sector_edges(sector)
    ledger = sector_ledger(sector)
    out = {
        "id": sector["id"],
        "tower_id": sector["tower_id"],
        "spectrum_license_id": sector["spectrum_license_id"],
        "azimuth_deg": sector["azimuth_deg"],
        "beamwidth_deg": sector["beamwidth_deg"],
        "channel_center_mhz": sector["channel_center_mhz"],
        "channel_width_mhz": sector["channel_width_mhz"],
        "tx_power_dbm": sector["tx_power_dbm"],
        "antenna_gain_dbi": sector["antenna_gain_dbi"],
        "eirp_dbm": q1(dec(sector["tx_power_dbm"]) + dec(sector["antenna_gain_dbi"])),
        "lower_edge_mhz": lower,
        "upper_edge_mhz": upper,
        "capacity_mbps": sector["capacity_mbps"],
        "max_oversubscription_ratio": sector["max_oversubscription_ratio"],
        "status": sector["status"],
        "sold_mbps": ledger["sold_mbps"],
        "held_mbps": ledger["held_mbps"],
        "committed_mbps": ledger["committed_mbps"],
        "oversubscription_ratio": ledger["oversubscription_ratio"],
        "remaining_allowance_mbps": ledger["remaining_allowance_mbps"],
        "capacity_posture": ledger["capacity_posture"],
        "capacity_policy_note": sector["capacity_policy_note"],
    }
    out.update(_common(sector))
    return out


def coordination_view(record):
    out = {
        "id": record["id"],
        "requesting_sector_id": record["requesting_sector_id"],
        "neighbor_sector_id": record["neighbor_sector_id"],
        "proposed_channel_center_mhz": record["proposed_channel_center_mhz"],
        "proposed_channel_width_mhz": record["proposed_channel_width_mhz"],
        "proposed_eirp_dbm": record["proposed_eirp_dbm"],
        "guard_band_mhz": record["guard_band_mhz"],
        "effective_from": record["effective_from"],
        "round_number": record["round_number"],
        "status": record["status"],
        "decision_note": record["decision_note"],
        "decided_by_user_id": record["decided_by_user_id"],
        "last_response_at": record["last_response_at"],
    }
    out.update(_common(record))
    return out


def plan_view(plan):
    out = {
        "id": plan["id"],
        "tier_code": plan["tier_code"],
        "downstream_mbps": plan["downstream_mbps"],
        "upstream_mbps": plan["upstream_mbps"],
        "monthly_price_cents": plan["monthly_price_cents"],
        "soft_cap_gb": plan["soft_cap_gb"],
        "deprioritization_factor": plan["deprioritization_factor"],
        "sla_uptime_pct": plan["sla_uptime_pct"],
        "sla_credit_method": plan["sla_credit_method"],
        "equipment_policy": plan["equipment_policy"],
    }
    out.update(_common(plan))
    return out


def request_view(record):
    out = {
        "id": record["id"],
        "candidate_tower_id": record["candidate_tower_id"],
        "requested_plan_id": record["requested_plan_id"],
        "contact_name": record["contact_name"],
        "premise_latitude": record["premise_latitude"],
        "premise_longitude": record["premise_longitude"],
        "premise_ground_elevation_m": record["premise_ground_elevation_m"],
        "roof_height_m": record["roof_height_m"],
        "declared_tree_line_height_m": record["declared_tree_line_height_m"],
        "obstruction_class": record["obstruction_class"],
        "path_distance_km": record["path_distance_km"],
        "intake_sequence": record["intake_sequence"],
        "qualified_sector_id": record["qualified_sector_id"],
        "desktop_los_margin_m": record["desktop_los_margin_m"],
        "desktop_required_mast_height_m": record["desktop_required_mast_height_m"],
        "desktop_mounting_type": record["desktop_mounting_type"],
        "status": record["status"],
        "denial_reason": record["denial_reason"],
        "qualification_expires_at": record["qualification_expires_at"],
    }
    out.update(_common(record))
    return out


def hold_view(record):
    out = {
        "id": record["id"],
        "serviceability_request_id": record["serviceability_request_id"],
        "sector_id": record["sector_id"],
        "held_mbps": record["held_mbps"],
        "hold_days": record["hold_days"],
        "expires_at": record["expires_at"],
        "status": record["status"],
        "release_reason": record["release_reason"],
        "origin": record["origin"],
    }
    out.update(_common(record))
    return out


def subscriber_view(subscriber):
    plan = db.service_plans.get(subscriber["service_plan_id"]) or {}
    priority = subscriber["usage_priority"]
    effective = (calc.effective_downstream(plan, priority) if plan else None)
    out = {
        "id": subscriber["id"],
        "serviceability_request_id": subscriber["serviceability_request_id"],
        "service_plan_id": subscriber["service_plan_id"],
        "sector_id": subscriber["sector_id"],
        "account_number": subscriber["account_number"],
        "billing_email": subscriber["billing_email"],
        "equipment_mode": subscriber["equipment_mode"],
        "service_status": subscriber["service_status"],
        "usage_priority": priority,
        "cycle_start_date": subscriber["cycle_start_date"],
        "cycle_usage_gb": subscriber_cycle_usage_gb(subscriber),
        "effective_downstream_mbps": effective,
        "consecutive_breach_cycles": subscriber["consecutive_breach_cycles"],
        "sticky_deprioritization_active": subscriber["sticky_deprioritization_active"],
        "deprioritized_at": subscriber["deprioritized_at"],
        "service_start_date": subscriber["service_start_date"],
        "cancelled_at": subscriber["cancelled_at"],
        "credit_balance_cents": subscriber_credit_balance_cents(subscriber["id"]),
        "settlement_balance_cents": subscriber_settlement_balance_cents(subscriber["id"]),
        "equipment_monthly_charge_cents":
            subscriber_equipment_monthly_charge_cents(subscriber["id"]),
    }
    out.update(_common(subscriber))
    return out


def work_order_view(record):
    out = {
        "id": record["id"],
        "subscriber_id": record["subscriber_id"],
        "scheduled_at": record["scheduled_at"],
        "status": record["status"],
        "measured_tree_line_height_m": record["measured_tree_line_height_m"],
        "measured_roof_height_m": record["measured_roof_height_m"],
        "structure_penetration_allowed": record["structure_penetration_allowed"],
        "field_los_margin_m": record["field_los_margin_m"],
        "recommended_mast_height_m": record["recommended_mast_height_m"],
        "recommended_mounting_type": record["recommended_mounting_type"],
        "approved_mounting_type": record["approved_mounting_type"],
        "surveyed_by_user_id": record["surveyed_by_user_id"],
        "exception_approved_by_user_id": record["exception_approved_by_user_id"],
        "resurvey_count": record["resurvey_count"],
        "installed_mast_height_m": record["installed_mast_height_m"],
        "radio_serial": record["radio_serial"],
        "install_invoice_total_cents": record["install_invoice_total_cents"],
        "installed_at": record["installed_at"],
    }
    out.update(_common(record))
    return out


def assignment_view(record):
    out = {
        "id": record["id"],
        "subscriber_id": record["subscriber_id"],
        "acquisition_mode": record["acquisition_mode"],
        "radio_serial": record["radio_serial"],
        "status": record["status"],
        "monthly_rental_cents": record["monthly_rental_cents"],
        "purchase_price_cents": record["purchase_price_cents"],
        "replacement_cost_cents": record["replacement_cost_cents"],
        "deployed_at": record["deployed_at"],
        "return_due_at": record["return_due_at"],
        "returned_at": record["returned_at"],
        "return_condition": record["return_condition"],
        "months_in_service": record["months_in_service"],
        "settlement_cents": record["settlement_cents"],
        "settlement_basis": record["settlement_basis"],
    }
    out.update(_common(record))
    return out


def usage_record_view(record):
    subscriber = db.subscribers.get(record["subscriber_id"]) or {}
    return {
        "id": record["id"],
        "subscriber_id": record["subscriber_id"],
        "usage_date": record["usage_date"],
        "downstream_gb": record["downstream_gb"],
        "upstream_gb": record["upstream_gb"],
        "total_gb": record["total_gb"],
        "ingest_sequence": record["ingest_sequence"],
        "in_current_cycle": calc.in_window(record["usage_date"],
                                           subscriber.get("cycle_start_date")),
        "created_at": record["created_at"],
    }


def outage_view(record):
    out = {
        "id": record["id"],
        "tower_id": record["tower_id"],
        "cause": record["cause"],
        "started_at": record["started_at"],
        "ended_at": record["ended_at"],
        "peak_wind_mph": record["peak_wind_mph"],
        "planned_notice_days": record["planned_notice_days"],
        "status": record["status"],
        "duration_minutes": record["duration_minutes"],
        "sla_excluded": record["sla_excluded"],
        "total_credited_cents": outage_total_credited_cents(record["id"]),
    }
    out.update(_common(record))
    return out


def credit_view(record):
    out = {
        "id": record["id"],
        "outage_event_id": record["outage_event_id"],
        "subscriber_id": record["subscriber_id"],
        "method": record["method"],
        "cycle_outage_minutes": record["cycle_outage_minutes"],
        "measured_uptime_pct": record["measured_uptime_pct"],
        "shortfall_pct": record["shortfall_pct"],
        "prior_cycle_credited_cents": record["prior_cycle_credited_cents"],
        "credit_cents": record["credit_cents"],
        "status": record["status"],
        "denial_reason": record["denial_reason"],
        "prepared_by_user_id": record["prepared_by_user_id"],
        "approved_by_user_id": record["approved_by_user_id"],
        "reversal_reason": record["reversal_reason"],
    }
    out.update(_common(record))
    return out
