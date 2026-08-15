"""Wire serializers for every entity (PRD 2.4 common fields; ZoneAccessEvent reduced set)."""
from decimal import Decimal

from util import fmt_dt


def _rate(value) -> float:
    return float(value)


def zone_view(z):
    return {
        "id": z["id"],
        "name": z["name"],
        "zone_code": z["zone_code"],
        "bond_coverage_cents": z["bond_coverage_cents"],
        "status": z["status"],
        "compliance_posture": z["compliance_posture"],
        "deferred_duty_exposure_cents": z["deferred_duty_exposure_cents"],
        "active_lot_count": z["active_lot_count"],
        "created_at": fmt_dt(z["created_at"]),
        "updated_at": fmt_dt(z["updated_at"]),
        "version": z["version"],
    }


def admission_view(a):
    return {
        "id": a["id"],
        "zone_id": a["zone_id"],
        "importer_ref": a["importer_ref"],
        "description": a["description"],
        "hts_code": a["hts_code"],
        "quantity": a["quantity"],
        "unit_value_cents": a["unit_value_cents"],
        "zone_status": a["zone_status"],
        "admission_date": fmt_dt(a["admission_date"]) if a["admission_date"] is not None else None,
        "status": a["status"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def lot_view(lot):
    return {
        "id": lot["id"],
        "zone_id": lot["zone_id"],
        "admission_id": lot["admission_id"],
        "source_manipulation_id": lot["source_manipulation_id"],
        "importer_ref": lot["importer_ref"],
        "hts_code": lot["hts_code"],
        "zone_status": lot["zone_status"],
        "admitted_quantity": lot["admitted_quantity"],
        "quantity_on_hand": lot["quantity_on_hand"],
        "reserved_quantity": lot["reserved_quantity"],
        "cumulative_withdrawn": lot["cumulative_withdrawn"],
        "cumulative_consumed": lot["cumulative_consumed"],
        "unit_value_cents": lot["unit_value_cents"],
        "duty_rate": _rate(lot["duty_rate"]),
        "status": lot["status"],
        "created_at": fmt_dt(lot["created_at"]),
        "updated_at": fmt_dt(lot["updated_at"]),
        "version": lot["version"],
    }


def order_view(o):
    return {
        "id": o["id"],
        "zone_id": o["zone_id"],
        "importer_ref": o["importer_ref"],
        "source_lot_id": o["source_lot_id"],
        "input_quantity": o["input_quantity"],
        "output_hts_code": o["output_hts_code"],
        "output_quantity": o["output_quantity"],
        "value_added_cents": o["value_added_cents"],
        "output_description": o["output_description"],
        "output_lot_id": o["output_lot_id"],
        "status": o["status"],
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def withdrawal_view(w):
    return {
        "id": w["id"],
        "zone_id": w["zone_id"],
        "importer_ref": w["importer_ref"],
        "lot_id": w["lot_id"],
        "weekly_entry_id": w["weekly_entry_id"],
        "withdrawal_type": w["withdrawal_type"],
        "quantity": w["quantity"],
        "estimated_duty_cents": w["estimated_duty_cents"],
        "assessed_duty_cents": w["assessed_duty_cents"],
        "withdrawal_date": fmt_dt(w["withdrawal_date"]) if w["withdrawal_date"] is not None else None,
        "duty_outcome": w["duty_outcome"],
        "status": w["status"],
        "created_at": fmt_dt(w["created_at"]),
        "updated_at": fmt_dt(w["updated_at"]),
        "version": w["version"],
    }


def entry_view(e):
    return {
        "id": e["id"],
        "zone_id": e["zone_id"],
        "importer_ref": e["importer_ref"],
        "week_start_date": fmt_dt(e["week_start_date"]),
        "week_end_date": fmt_dt(e["week_end_date"]),
        "entered_value_cents": e["entered_value_cents"],
        "duty_total_cents": e["duty_total_cents"],
        "mpf_uncapped_cents": e["mpf_uncapped_cents"],
        "mpf_cents": e["mpf_cents"],
        "per_shipment_mpf_cents": e["per_shipment_mpf_cents"],
        "mpf_savings_cents": e["mpf_savings_cents"],
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def recon_view(r):
    return {
        "id": r["id"],
        "zone_id": r["zone_id"],
        "zone_year": r["zone_year"],
        "beginning_value_cents": r["beginning_value_cents"],
        "physical_ending_value_cents": r["physical_ending_value_cents"],
        "book_receipts_value_cents": r["book_receipts_value_cents"],
        "book_withdrawals_value_cents": r["book_withdrawals_value_cents"],
        "book_ending_value_cents": r["book_ending_value_cents"],
        "discrepancy_cents": r["discrepancy_cents"],
        "discrepancy_pct": (float(r["discrepancy_pct"]) if r["discrepancy_pct"] is not None else None),
        "audit_flagged": r["audit_flagged"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def badge_view(b):
    return {
        "id": b["id"],
        "zone_id": b["zone_id"],
        "holder_name": b["holder_name"],
        "employer_ref": b["employer_ref"],
        "valid_from": fmt_dt(b["valid_from"]),
        "valid_until": fmt_dt(b["valid_until"]),
        "status": b["status"],
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def event_view(ev):
    return {
        "id": ev["id"],
        "zone_id": ev["zone_id"],
        "badge_id": ev["badge_id"],
        "direction": ev["direction"],
        "occurred_at": fmt_dt(ev["occurred_at"]),
        "created_at": fmt_dt(ev["created_at"]),
    }
