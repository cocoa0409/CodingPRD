"""Public JSON views of each entity.

Versioned entities expose id, created_at, updated_at, version plus domain fields.
Append-only telemetry (AudienceSnapshot, ConversionEvent) expose only id and
created_at — no updated_at / version (PRD 2.4).
"""


def _base(rec, versioned=True):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }
    if versioned:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def brand_view(b):
    out = _base(b)
    out.update({
        "legal_name": b["legal_name"],
        "contact_email": b["contact_email"],
        "budget_cents": b["budget_cents"],
        "committed_cents": b["committed_cents"],
        "available_budget_cents": b["available_budget_cents"],
    })
    return out


def creator_view(c):
    out = _base(c)
    out.update({
        "handle": c["handle"],
        "primary_platform": c["primary_platform"],
        "payout_method": c["payout_method"],
        "tax_id_on_file": c["tax_id_on_file"],
        "discovery_status": c["discovery_status"],
        "brand_safety_status": c["brand_safety_status"],
        "ytd_paid_cents": c["ytd_paid_cents"],
    })
    return out


def audience_snapshot_view(s):
    out = _base(s, versioned=False)
    out.update({
        "creator_id": s["creator_id"],
        "follower_count": s["follower_count"],
        "avg_engagement_rate": s["avg_engagement_rate"],
        "estimated_reach": s["estimated_reach"],
        "fake_follower_pct": s["fake_follower_pct"],
        "fraud_score": s["fraud_score"],
        "captured_at": s["captured_at"],
    })
    return out


def campaign_view(c):
    out = _base(c)
    out.update({
        "brand_id": c["brand_id"],
        "title": c["title"],
        "campaign_budget_cents": c["campaign_budget_cents"],
        "requires_ftc_disclosure": c["requires_ftc_disclosure"],
        "starts_at": c["starts_at"],
        "ends_at": c["ends_at"],
        "status": c["status"],
        "committed_cents": c["committed_cents"],
        "actual_spend_cents": c["actual_spend_cents"],
    })
    return out


def deliverable_view(d):
    out = _base(d)
    out.update({
        "campaign_id": d["campaign_id"],
        "content_type": d["content_type"],
        "quantity": d["quantity"],
        "due_at": d["due_at"],
        "base_rate_cents": d["base_rate_cents"],
    })
    return out


def offer_view(o):
    out = _base(o)
    out.update({
        "campaign_id": o["campaign_id"],
        "creator_id": o["creator_id"],
        "initiated_by": o["initiated_by"],
        "current_amount_cents": o["current_amount_cents"],
        "last_actor": o["last_actor"],
        "round_count": o["round_count"],
        "exclusivity_days": o["exclusivity_days"],
        "status": o["status"],
    })
    return out


def contract_view(c):
    out = _base(c)
    out.update({
        "offer_id": c["offer_id"],
        "campaign_id": c["campaign_id"],
        "creator_id": c["creator_id"],
        "contracted_rate_cents": c["contracted_rate_cents"],
        "pinned_offer_version": c["pinned_offer_version"],
        "exclusivity_start": c["exclusivity_start"],
        "exclusivity_end": c["exclusivity_end"],
        "status": c["status"],
    })
    return out


def content_submission_view(s):
    out = _base(s)
    out.update({
        "deliverable_id": s["deliverable_id"],
        "contract_id": s["contract_id"],
        "media_url": s["media_url"],
        "caption": s["caption"],
        "has_ftc_disclosure": s["has_ftc_disclosure"],
        "revision_count": s["revision_count"],
        "status": s["status"],
    })
    return out


def attribution_asset_view(a):
    out = _base(a)
    out.update({
        "contract_id": a["contract_id"],
        "asset_type": a["asset_type"],
        "code_or_slug": a["code_or_slug"],
        "status": a["status"],
    })
    return out


def conversion_event_view(e):
    out = _base(e, versioned=False)
    out.update({
        "attribution_asset_id": e["attribution_asset_id"],
        "event_type": e["event_type"],
        "count": e["count"],
        "revenue_cents": e["revenue_cents"],
        "occurred_at": e["occurred_at"],
    })
    return out


def payout_view(p):
    out = _base(p)
    out.update({
        "contract_id": p["contract_id"],
        "gross_amount_cents": p["gross_amount_cents"],
        "platform_fee_cents": p["platform_fee_cents"],
        "tax_withholding_cents": p["tax_withholding_cents"],
        "net_amount_cents": p["net_amount_cents"],
        "expected_contract_version": p["expected_contract_version"],
        "status": p["status"],
    })
    return out


def tax_form_view(t):
    out = _base(t)
    out.update({
        "creator_id": t["creator_id"],
        "tax_year": t["tax_year"],
        "total_reported_cents": t["total_reported_cents"],
        "status": t["status"],
    })
    return out


def brand_safety_flag_view(f):
    out = _base(f)
    out.update({
        "creator_id": f["creator_id"],
        "severity": f["severity"],
        "reason_code": f["reason_code"],
        "note": f["note"],
        "status": f["status"],
    })
    return out
