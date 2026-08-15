"""Entity serializers — public shape only (internal "_" keys excluded)."""
from validate import render_datetime


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_theater(t):
    d = _common(t)
    d.update({"name": t["name"], "market_tier": t["market_tier"],
              "theater_status": t["theater_status"]})
    return d


def ser_screen(s):
    d = _common(s)
    d.update({"theater_id": s["theater_id"],
              "auditorium_label": s["auditorium_label"],
              "seat_count": s["seat_count"],
              "screen_status": s["screen_status"]})
    return d


def ser_feature(f):
    d = _common(f)
    d.update({"title": f["title"], "content_rating": f["content_rating"],
              "runtime_minutes": f["runtime_minutes"],
              "release_date": f["release_date"]})
    return d


def ser_showtime(st):
    d = _common(st)
    d.update({"screen_id": st["screen_id"], "feature_id": st["feature_id"],
              "starts_at": render_datetime(st["_starts_dt"]),
              "daypart": st["daypart"],
              "forecast_attendance": st["forecast_attendance"],
              "actual_attendance": st["actual_attendance"]})
    return d


def ser_advertiser(a):
    d = _common(a)
    d.update({"name": a["name"], "advertiser_type": a["advertiser_type"],
              "category": a["category"],
              "advertiser_status": a["advertiser_status"]})
    return d


def ser_campaign(c):
    d = _common(c)
    d.update({"advertiser_id": c["advertiser_id"], "name": c["name"],
              "flight_start_date": c["flight_start_date"],
              "flight_end_date": c["flight_end_date"],
              "contracted_impressions": c["contracted_impressions"],
              "cpm_cents": c["cpm_cents"], "budget_cents": c["budget_cents"],
              "partial_credit_mode": c["partial_credit_mode"],
              "campaign_status": c["campaign_status"],
              "created_by_user_id": c["created_by_user_id"],
              "approved_by_user_id": c["approved_by_user_id"],
              "reserved_estimated_cents": c["reserved_estimated_cents"],
              "delivered_impressions": c["delivered_impressions"]})
    return d


def ser_reel(r):
    d = _common(r)
    d.update({"showtime_id": r["showtime_id"], "reel_status": r["reel_status"],
              "capacity_seconds": r["capacity_seconds"],
              "national_pool_seconds": r["national_pool_seconds"],
              "local_pool_seconds": r["local_pool_seconds"],
              "national_used_seconds": r["national_used_seconds"],
              "local_used_seconds": r["local_used_seconds"]})
    return d


def ser_slot(s):
    d = _common(s)
    d.update({"reel_id": s["reel_id"], "campaign_id": s["campaign_id"],
              "start_offset_seconds": s["start_offset_seconds"],
              "duration_seconds": s["duration_seconds"],
              "slot_status": s["slot_status"],
              "estimated_cost_cents": s["estimated_cost_cents"],
              "play_factor": s["play_factor"],
              "attributed_impressions": s["attributed_impressions"]})
    return d


def ser_playlog(p):
    # PlayLog is append-only: id + created_at only, no updated_at/version.
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "slot_id": p["slot_id"],
        "outcome": p["outcome"],
        "played_at": p["played_at"],
        "reported_by_user_id": p["reported_by_user_id"],
        "reported_by_theater_id": p["reported_by_theater_id"],
    }


def ser_attendance_report(r):
    d = _common(r)
    d.update({"showtime_id": r["showtime_id"],
              "reported_attendance": r["reported_attendance"],
              "audited_attendance": r["audited_attendance"],
              "report_status": r["report_status"],
              "reported_by_user_id": r["reported_by_user_id"],
              "reviewed_by_user_id": r["reviewed_by_user_id"],
              "audited_by_user_id": r["audited_by_user_id"]})
    return d


def ser_invoice(inv):
    d = _common(inv)
    d.update({"campaign_id": inv["campaign_id"],
              "period_start_date": inv["period_start_date"],
              "period_end_date": inv["period_end_date"],
              "billing_status": inv["billing_status"],
              "audit_status": inv["audit_status"],
              "provisional_impressions": inv["provisional_impressions"],
              "provisional_amount_cents": inv["provisional_amount_cents"],
              "audited_impressions": inv["audited_impressions"],
              "audited_amount_cents": inv["audited_amount_cents"],
              "applied_credit_cents": inv["applied_credit_cents"],
              "final_amount_cents": inv["final_amount_cents"],
              "issued_by_user_id": inv["issued_by_user_id"],
              "certified_by_user_id": inv["certified_by_user_id"]})
    return d


def ser_make_good(mg):
    d = _common(mg)
    d.update({"invoice_id": mg["invoice_id"],
              "shortfall_impressions": mg["shortfall_impressions"],
              "under_delivery_pct": mg["under_delivery_pct"],
              "credit_cents": mg["credit_cents"],
              "credit_status": mg["credit_status"],
              "proposed_by_user_id": mg["proposed_by_user_id"],
              "reviewed_by_user_id": mg["reviewed_by_user_id"],
              "applied_by_user_id": mg["applied_by_user_id"]})
    return d
