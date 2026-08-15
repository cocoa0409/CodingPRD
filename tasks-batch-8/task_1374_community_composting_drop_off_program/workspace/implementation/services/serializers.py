"""Entity serializers (response shapes)."""

import db


def site(s):
    return {
        "id": s["id"],
        "program_id": s["program_id"],
        "name": s["name"],
        "address": s["address"],
        "capacity_kg": s["capacity_kg"],
        "stored_kg": s["stored_kg"],
        "pending_pickup_kg": s["pending_pickup_kg"],
        "posture": s["posture"],
        "host_agreement_id": s["host_agreement_id"],
        "archived": s["archived"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def agreement(a):
    return {
        "id": a["id"],
        "program_id": a["program_id"],
        "site_id": a["site_id"],
        "host_name": a["host_name"],
        "term_start": db.fmt_ts(a["term_start"]),
        "term_end": db.fmt_ts(a["term_end"]),
        "cure_period_days": a["cure_period_days"],
        "status": a["status"],
        "breach_noticed_at": db.fmt_ts(a["breach_noticed_at"]) if a.get("breach_noticed_at") else None,
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def material(m):
    return {
        "id": m["id"],
        "program_id": m["program_id"],
        "code": m["code"],
        "description": m["description"],
        "accepted_start_month_day": m["accepted_start_month_day"],
        "accepted_end_month_day": m["accepted_end_month_day"],
        "contamination_sensitivity": m["contamination_sensitivity"],
        "active": m["active"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def participant(p):
    return {
        "id": p["id"],
        "program_id": p["program_id"],
        "email": p["email"],
        "full_name": p["full_name"],
        "household_size": p["household_size"],
        "status": p["status"],
        "verification_token": p.get("verification_token"),
        "bucket_credit_balance": p["bucket_credit_balance"],
        "bucket_credits_granted_total": p["bucket_credits_granted_total"],
        "bucket_credits_redeemed_total": p["bucket_credits_redeemed_total"],
        "bucket_credits_expired_total": p["bucket_credits_expired_total"],
        "suspension_count": p["suspension_count"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def grant(g):
    return {
        "id": g["id"],
        "participant_id": g["participant_id"],
        "site_id": g["site_id"],
        "access_code": g["access_code"],
        "bucket_quota": g["bucket_quota"],
        "buckets_checked_out": g["buckets_checked_out"],
        "status": g["status"],
        "expires_at": db.fmt_ts(g["expires_at"]),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def contamination_report(r):
    return {
        "id": r["id"],
        "site_id": r["site_id"],
        "drop_event_id": r["drop_event_id"],
        "auditor_id": r["auditor_id"],
        "severity": r["severity"],
        "finding_note": r["finding_note"],
        "feedback_sent_at": db.fmt_ts(r["feedback_sent_at"]) if r.get("feedback_sent_at") else None,
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def route(r):
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "route_code": r["route_code"],
        "vehicle_capacity_kg": r["vehicle_capacity_kg"],
        "processing_partner_id": r["processing_partner_id"],
        "status": r["status"],
        "scheduled_start": db.fmt_ts(r["scheduled_start"]),
        "scheduled_end": db.fmt_ts(r["scheduled_end"]),
        "assigned_load_kg": r["assigned_load_kg"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def partner(p):
    return {
        "id": p["id"],
        "program_id": p["program_id"],
        "name": p["name"],
        "intake_capacity_kg_per_day": p["intake_capacity_kg_per_day"],
        "yield_ratio": p["yield_ratio"],
        "contamination_reject_threshold_pct": p["contamination_reject_threshold_pct"],
        "active": p["active"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def stop(s):
    return {
        "id": s["id"],
        "route_id": s["route_id"],
        "site_id": s["site_id"],
        "planned_pickup_kg": s["planned_pickup_kg"],
        "actual_pickup_kg": s["actual_pickup_kg"],
        "stop_sequence": s["stop_sequence"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def batch(b):
    return {
        "id": b["id"],
        "partner_id": b["partner_id"],
        "route_id": b["route_id"],
        "input_gross_kg": b["input_gross_kg"],
        "measured_contamination_kg": b.get("measured_contamination_kg"),
        "measured_net_kg": b.get("measured_net_kg"),
        "contamination_pct": b.get("contamination_pct"),
        "finished_compost_kg": b.get("finished_compost_kg"),
        "status": b["status"],
        "closed_at": db.fmt_ts(b["closed_at"]) if b.get("closed_at") else None,
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def distribution(d):
    return {
        "id": d["id"],
        "program_id": d["program_id"],
        "batch_id": d["batch_id"],
        "total_pool_kg": d["total_pool_kg"],
        "allocated_kg": d["allocated_kg"],
        "status": d["status"],
        "opened_at": db.fmt_ts(d["opened_at"]),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def allocation(a):
    return {
        "id": a["id"],
        "distribution_id": a["distribution_id"],
        "participant_id": a["participant_id"],
        "requested_kg": a["requested_kg"],
        "credits_redeemed": a["credits_redeemed"],
        "allocation_kg": a["allocation_kg"],
        "status": a["status"],
        "created_at": a["created_at"],
    }


def complaint(c):
    return {
        "id": c["id"],
        "site_id": c["site_id"],
        "reporter_contact": c["reporter_contact"],
        "kind": c["kind"],
        "description": c["description"],
        "reported_at": db.fmt_ts(c["reported_at"]),
        "sla_due_at": db.fmt_ts(c["sla_due_at"]),
        "acknowledged_at": db.fmt_ts(c["acknowledged_at"]) if c.get("acknowledged_at") else None,
        "resolved_at": db.fmt_ts(c["resolved_at"]) if c.get("resolved_at") else None,
        "sla_breached": c["sla_breached"],
        "reopen_count": c["reopen_count"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def diversion_report(r):
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "period_start": db.fmt_ts(r["period_start"]),
        "period_end": db.fmt_ts(r["period_end"]),
        "method": r["method"],
        "gross_diverted_kg": r["gross_diverted_kg"],
        "net_diverted_kg": r["net_diverted_kg"],
        "contamination_kg": r["contamination_kg"],
        "diversion_rate_pct": r["diversion_rate_pct"],
        "certified_by": r.get("certified_by"),
        "status": r["status"],
        "created_at": r["created_at"],
    }
