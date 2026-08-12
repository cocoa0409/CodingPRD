"""Entity -> JSON dict serialization (datetime fields rendered as ISO8601 3-digit ms Z)."""
import db


def _dt(v):
    return db.fmt_ts(v) if v is not None else None


def title_out(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "author": t["author"],
        "title_kind": t["title_kind"],
        "royalty_basis": t["royalty_basis"],
        "base_flat_fee_cents": t["base_flat_fee_cents"],
        "gross_percent_bp": t["gross_percent_bp"],
        "restricted_material": t["restricted_material"],
        "perusal_fee_cents": t["perusal_fee_cents"],
        "rental_deposit_cents": t["rental_deposit_cents"],
        "late_fee_per_day_cents": t["late_fee_per_day_cents"],
        "restricted_late_fee_per_day_cents": t["restricted_late_fee_per_day_cents"],
        "recording_royalty_flat_cents": t["recording_royalty_flat_cents"],
        "status": t["status"],
        "created_at": _dt(t["created_at"]),
        "updated_at": _dt(t["updated_at"]),
        "version": t["version"],
    }


def restriction_out(r):
    return {
        "id": r["id"],
        "title_id": r["title_id"],
        "territory_code": r["territory_code"],
        "restriction_kind": r["restriction_kind"],
        "window_start": _dt(r["window_start"]),
        "window_end": _dt(r["window_end"]),
        "blocks_classification": r["blocks_classification"],
        "active": r["active"],
        "created_at": _dt(r["created_at"]),
        "updated_at": _dt(r["updated_at"]),
        "version": r["version"],
    }


def organization_out(o):
    return {
        "id": o["id"],
        "legal_name": o["legal_name"],
        "org_kind": o["org_kind"],
        "home_territory_code": o["home_territory_code"],
        "standing": o["standing"],
        "created_at": _dt(o["created_at"]),
        "updated_at": _dt(o["updated_at"]),
        "version": o["version"],
    }


def application_out(a):
    return {
        "id": a["id"],
        "title_id": a["title_id"],
        "organization_id": a["organization_id"],
        "requested_territory_code": a["requested_territory_code"],
        "requested_classification": a["requested_classification"],
        "venue_seating_capacity": a["venue_seating_capacity"],
        "ticket_top_price_cents": a["ticket_top_price_cents"],
        "performers_compensated": a["performers_compensated"],
        "admission_charged": a["admission_charged"],
        "projected_gross_cents": a["projected_gross_cents"],
        "performance_count": a["performance_count"],
        "first_performance_date": _dt(a["first_performance_date"]),
        "last_performance_date": _dt(a["last_performance_date"]),
        "determined_classification": a["determined_classification"],
        "status": a["status"],
        "submitted_at": _dt(a["submitted_at"]),
        "review_round": a["review_round"],
        "created_at": _dt(a["created_at"]),
        "updated_at": _dt(a["updated_at"]),
        "version": a["version"],
    }


def agreement_out(g):
    return {
        "id": g["id"],
        "application_id": g["application_id"],
        "title_id": g["title_id"],
        "organization_id": g["organization_id"],
        "territory_code": g["territory_code"],
        "classification": g["classification"],
        "house_seating_capacity": g["house_seating_capacity"],
        "contracted_performance_count": g["contracted_performance_count"],
        "window_start": _dt(g["window_start"]),
        "window_end": _dt(g["window_end"]),
        "royalty_mode": g["royalty_mode"],
        "quoted_royalty_total_cents": g["quoted_royalty_total_cents"],
        "settled_royalty_total_cents": g["settled_royalty_total_cents"],
        "royalty_balance_cents": g["royalty_balance_cents"],
        "license_status": g["license_status"],
        "payment_status": g["payment_status"],
        "amendment_seq": g["amendment_seq"],
        "supersedes_agreement_id": g["supersedes_agreement_id"],
        "has_exclusive_run": g["has_exclusive_run"],
        "created_at": _dt(g["created_at"]),
        "updated_at": _dt(g["updated_at"]),
        "version": g["version"],
    }


def performance_out(p):
    return {
        "id": p["id"],
        "agreement_id": p["agreement_id"],
        "performance_at": _dt(p["performance_at"]),
        "reported_attendance": p["reported_attendance"],
        "reported_gross_cents": p["reported_gross_cents"],
        "gross_reported": p["gross_reported"],
        "royalty_cents": p["royalty_cents"],
        "status": p["status"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
    }


def rental_out(r):
    return {
        "id": r["id"],
        "agreement_id": r["agreement_id"],
        "scripts_qty": r["scripts_qty"],
        "scores_qty": r["scores_qty"],
        "deposit_cents": r["deposit_cents"],
        "deposit_status": r["deposit_status"],
        "due_date": _dt(r["due_date"]),
        "returned_at": _dt(r["returned_at"]),
        "accrued_late_fee_cents": r["accrued_late_fee_cents"],
        "status": r["status"],
        "created_at": _dt(r["created_at"]),
        "updated_at": _dt(r["updated_at"]),
        "version": r["version"],
    }


def alteration_request_out(a):
    return {
        "id": a["id"],
        "agreement_id": a["agreement_id"],
        "alteration_kind": a["alteration_kind"],
        "description": a["description"],
        "status": a["status"],
        "decided_by_user_id": a["decided_by_user_id"],
        "created_at": _dt(a["created_at"]),
        "updated_at": _dt(a["updated_at"]),
        "version": a["version"],
    }


def recording_grant_out(g):
    return {
        "id": g["id"],
        "agreement_id": g["agreement_id"],
        "grant_kind": g["grant_kind"],
        "distribution_scope": g["distribution_scope"],
        "recording_royalty_cents": g["recording_royalty_cents"],
        "status": g["status"],
        "created_at": _dt(g["created_at"]),
        "updated_at": _dt(g["updated_at"]),
        "version": g["version"],
    }


def payment_out(p):
    return {
        "id": p["id"],
        "agreement_id": p["agreement_id"],
        "amount_cents": p["amount_cents"],
        "paid_at": _dt(p["paid_at"]),
        "refunded_cents": p.get("refunded_cents", 0),
        "created_at": _dt(p["created_at"]),
    }


def fine_out(f):
    return {
        "id": f["id"],
        "organization_id": f["organization_id"],
        "rental_id": f["rental_id"],
        "agreement_id": f["agreement_id"],
        "fine_kind": f["fine_kind"],
        "amount_cents": f["amount_cents"],
        "status": f["status"],
        "created_at": _dt(f["created_at"]),
        "updated_at": _dt(f["updated_at"]),
        "version": f["version"],
    }


def snapshot_out(s):
    return {
        "id": s["id"],
        "title_id": s["title_id"],
        "territory_code": s["territory_code"],
        "classification": s["classification"],
        "window_start": _dt(s["window_start"]),
        "window_end": _dt(s["window_end"]),
        "available": s["available"],
        "blocking_restriction_ids": list(s["blocking_restriction_ids"]),
        "blocking_agreement_ids": list(s["blocking_agreement_ids"]),
        "computed_at": _dt(s["computed_at"]),
        "created_at": _dt(s["created_at"]),
    }
