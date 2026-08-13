"""Shared state-transition helpers and serialization for every resource."""

from db import store, touch
from services.calc import compute_live_period, derive_standing, derive_tier

# Computed scorecard fields frozen at close.
PERIOD_COMPUTED_FIELDS = [
    "total_waste_lbs_validated",
    "diverted_lbs_validated",
    "diversion_rate_certified_pct",
    "total_waste_lbs_provisional",
    "diverted_lbs_provisional",
    "diversion_rate_provisional_pct",
    "rebate_estimate_cents",
    "rebate_settled_cents",
    "cost_avoided_cents",
    "contamination_event_count",
]


def open_period_containing(site_id, date_str):
    """The site's OPEN ScorecardPeriod whose [start, end) contains date_str."""
    for p in store.periods.values():
        if (p["site_id"] == site_id and p["status"] == "OPEN"
                and p["period_start"] <= date_str < p["period_end"]):
            return p
    return None


def bump_period_for(site_id, date_str):
    """Ticket activity mutates the containing OPEN period's computed fields."""
    p = open_period_containing(site_id, date_str)
    if p is not None:
        touch(p)


def reject_ticket(t, reason):
    """PENDING -> REJECTED with the transition's standard side effects."""
    t["validation_status"] = "REJECTED"
    t["rejection_reason"] = reason
    touch(t)
    bump_period_for(t["site_id"], t["ticket_date"])


def void_ticket(t):
    """VALIDATED -> VOIDED; live computation compensates totals/rebate exactly."""
    t["validation_status"] = "VOIDED"
    touch(t)
    bump_period_for(t["site_id"], t["ticket_date"])


def rederive_standing(site_id):
    site = store.sites.get(site_id)
    if site is None:
        return
    new = derive_standing(store, site_id)
    if site["program_standing"] != new:
        site["program_standing"] = new
        touch(site)


def rederive_tier(site_id):
    site = store.sites.get(site_id)
    if site is None:
        return
    new = derive_tier(store, site_id)
    if site["certification_tier"] != new:
        site["certification_tier"] = new
        touch(site)


# --------------------------------------------------------------------------
# Serializers (public representations; internal _seq stripped)
# --------------------------------------------------------------------------

def pub_site(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "landfill_tip_fee_per_ton_cents": s["landfill_tip_fee_per_ton_cents"],
        "max_rebate_rate_per_ton_cents": s["max_rebate_rate_per_ton_cents"],
        "certification_tier": s["certification_tier"],
        "program_standing": s["program_standing"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def pub_vendor(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "vendor_type": v["vendor_type"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def pub_contract(c):
    return {
        "id": c["id"],
        "site_id": c["site_id"],
        "vendor_id": c["vendor_id"],
        "material_stream": c["material_stream"],
        "rebate_per_ton_cents": c["rebate_per_ton_cents"],
        "contamination_penalty_per_ton_cents": c["contamination_penalty_per_ton_cents"],
        "window_start": c["window_start"],
        "window_end": c["window_end"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def pub_ticket(t):
    return {
        "id": t["id"],
        "site_id": t["site_id"],
        "vendor_id": t["vendor_id"],
        "contract_id": t["contract_id"],
        "material_stream": t["material_stream"],
        "disposal_route": t["disposal_route"],
        "gross_weight_lbs": t["gross_weight_lbs"],
        "tare_weight_lbs": t["tare_weight_lbs"],
        "net_weight_lbs": t["net_weight_lbs"],
        "contamination_pct": t.get("contamination_pct"),
        "ticket_date": t["ticket_date"],
        "external_ticket_ref": t["external_ticket_ref"],
        "validation_status": t["validation_status"],
        "rejection_reason": t.get("rejection_reason"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def pub_audit(a):
    # Immutable measurement log: id + created_at only; no updated_at/version.
    return {
        "id": a["id"],
        "site_id": a["site_id"],
        "audit_date": a["audit_date"],
        "auditor_name": a["auditor_name"],
        "stream_findings": a["stream_findings"],
        "created_at": a["created_at"],
    }


def pub_event(e):
    return {
        "id": e["id"],
        "site_id": e["site_id"],
        "ticket_id": e.get("ticket_id"),
        "audit_id": e.get("audit_id"),
        "event_date": e["event_date"],
        "material_stream": e["material_stream"],
        "contamination_pct": e["contamination_pct"],
        "severity": e["severity"],
        "status": e["status"],
        "trainee_name": e.get("trainee_name"),
        "training_due_date": e.get("training_due_date"),
        "dismiss_reason": e.get("dismiss_reason"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def pub_goal(g):
    return {
        "id": g["id"],
        "site_id": g["site_id"],
        "metric": g["metric"],
        "target_value": g["target_value"],
        "window_start": g["window_start"],
        "window_end": g["window_end"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def pub_period(p):
    out = {
        "id": p["id"],
        "site_id": p["site_id"],
        "period_start": p["period_start"],
        "period_end": p["period_end"],
        "status": p["status"],
    }
    if p["status"] == "OPEN":
        live = compute_live_period(store, p)
        live["rebate_settled_cents"] = None
        live["cost_avoided_cents"] = None
        out.update(live)
    else:
        for k in PERIOD_COMPUTED_FIELDS:
            out[k] = p[k]
    out["created_at"] = p["created_at"]
    out["updated_at"] = p["updated_at"]
    out["version"] = p["version"]
    return out


def pub_application(a):
    return {
        "id": a["id"],
        "site_id": a["site_id"],
        "reporting_period_id": a["reporting_period_id"],
        "level_requested": a["level_requested"],
        "status": a["status"],
        "submitted_by": a.get("submitted_by"),
        "decided_by": a.get("decided_by"),
        "decided_at": a.get("decided_at"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }
