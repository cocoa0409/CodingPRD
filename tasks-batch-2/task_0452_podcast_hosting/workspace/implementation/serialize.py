"""Resource serialization.

Each entity stores its persisted + system fields in db. Computed fields are
recomputed synchronously on mutation (PRD §2.6) and stored on the entity, so
serialization simply projects stored values. Stored computed values are kept
in sync by recompute.py.
"""

import calc
import db


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }


def publisher(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "payout_email": p["payout_email"],
        "revenue_share_pct": p["revenue_share_pct"],
    })
    return out


def advertiser(a):
    out = _common(a)
    out.update({"name": a["name"], "billing_email": a["billing_email"]})
    return out


def listener(l):
    out = _common(l)
    out.update({"email": l["email"], "display_name": l["display_name"]})
    return out


def show(s):
    out = _common(s)
    out.update({
        "publisher_id": s["publisher_id"],
        "title": s["title"],
        "category": s["category"],
        "status": s["status"],
        "monetization_enabled": s["monetization_enabled"],
        "episode_count": s["episode_count"],
    })
    return out


def episode(e):
    out = _common(e)
    out.update({
        "show_id": e["show_id"],
        "title": e["title"],
        "duration_ms": e["duration_ms"],
        "total_ad_slots": e["total_ad_slots"],
        "offered_positions": e["offered_positions"],
        "media_status": e["media_status"],
        "publish_status": e["publish_status"],
        "scheduled_publish_at": e["scheduled_publish_at"],
        "filled_slots": e["filled_slots"],
        "available_slots": e["available_slots"],
        "fill_rate": e["fill_rate"],
    })
    return out


def media_asset(m):
    out = _common(m)
    out.update({
        "episode_id": m["episode_id"],
        "source_filename": m["source_filename"],
        "source_duration_ms": m["source_duration_ms"],
        "status": m["status"],
        "transcode_attempts": m["transcode_attempts"],
        "output_duration_ms": m["output_duration_ms"],
    })
    return out


def feed(f):
    out = _common(f)
    out.update({
        "show_id": f["show_id"],
        "visibility": f["visibility"],
        "status": f["status"],
        "token_required": f["token_required"],
    })
    return out


def subscription(s):
    out = _common(s)
    out.update({
        "listener_id": s["listener_id"],
        "show_id": s["show_id"],
        "price_cents": s["price_cents"],
        "status": s["status"],
        "period_start": s["period_start"],
        "period_end": s["period_end"],
        "access_token": s["access_token"],
    })
    return out


def distribution(d):
    out = _common(d)
    out.update({
        "show_id": d["show_id"],
        "channel": d["channel"],
        "status": d["status"],
        "external_ref": d["external_ref"],
    })
    return out


def ad_campaign(c):
    out = _common(c)
    out.update({
        "advertiser_id": c["advertiser_id"],
        "name": c["name"],
        "budget_cents": c["budget_cents"],
        "bid_cpm_cents": c["bid_cpm_cents"],
        "targeting_category": c["targeting_category"],
        "premium_targeting": c["premium_targeting"],
        "flight_start": c["flight_start"],
        "flight_end": c["flight_end"],
        "status": c["status"],
        "reserved_budget_cents": c["reserved_budget_cents"],
        "spent_budget_cents": c["spent_budget_cents"],
        "available_budget_cents": c["available_budget_cents"],
    })
    return out


def ad_placement(p):
    out = _common(p)
    out.update({
        "campaign_id": p["campaign_id"],
        "episode_id": p["episode_id"],
        "position": p["position"],
        "offset_ms": p["offset_ms"],
        "ad_duration_ms": p["ad_duration_ms"],
        "forecast_impressions": p["forecast_impressions"],
        "delivered_impressions": p["delivered_impressions"],
        "estimated_cost_cents": p["estimated_cost_cents"],
        "fill_tier_multiplier": p["fill_tier_multiplier"],
        "final_cost_cents": p["final_cost_cents"],
        "status": p["status"],
    })
    return out


def download_event(d):
    # PRD §2.4: only id + created_at; no updated_at, no version.
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "episode_id": d["episode_id"],
        "placement_id": d["placement_id"],
        "client_ip_hash": d["client_ip_hash"],
        "user_agent": d["user_agent"],
        "bytes_served": d["bytes_served"],
        "counted": d["counted"],
        "event_at": d["event_at"],
    }


def payout_statement(s):
    out = _common(s)
    out.update({
        "publisher_id": s["publisher_id"],
        "period_start": s["period_start"],
        "period_end": s["period_end"],
        "status": s["status"],
        "gross_revenue_cents": s["gross_revenue_cents"],
        "platform_fee_cents": s["platform_fee_cents"],
        "net_payable_cents": s["net_payable_cents"],
        "settled_revenue_cents": s["settled_revenue_cents"],
    })
    return out
