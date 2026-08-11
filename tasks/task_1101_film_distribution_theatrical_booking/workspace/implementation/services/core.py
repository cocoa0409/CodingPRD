"""Core entity helpers: creation, serialization, hierarchical resolution."""
from datetime import timedelta
from decimal import Decimal

from db import db
from util import new_id, utcnow_iso, parse_dt, iso_from_dt, dec_pct, dec_str
from errors import err_not_found, err_invalid_request


# ---------------- Serialization ----------------

def serialize_distributor(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "territory": d["territory"],
        "week_epoch": d["week_epoch"],
        "logical_clock_utc": d["logical_clock_utc"],
        "lifecycle_posture": compute_distributor_posture(d["id"]),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_film(f):
    return {
        "id": f["id"],
        "distributor_id": f["distributor_id"],
        "title": f["title"],
        "genre": f["genre"],
        "runtime_minutes": f["runtime_minutes"],
        "rating": f["rating"],
        "release_pattern": f["release_pattern"],
        "target_release_date": f["target_release_date"],
        "min_screens_for_wide": f["min_screens_for_wide"],
        "lifecycle_status": f["lifecycle_status"],
        "screens_committed": compute_screens_committed(f["id"]),
        "theatrical_window_end": f["theatrical_window_end"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_theatre(t):
    return {
        "id": t["id"],
        "distributor_id": t["distributor_id"],
        "name": t["name"],
        "circuit": t["circuit"],
        "market_code": t["market_code"],
        "house_allowance_cents": t["house_allowance_cents"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_screen(s):
    return {
        "id": s["id"],
        "theatre_id": s["theatre_id"],
        "auditorium_label": s["auditorium_label"],
        "seat_count": s["seat_count"],
        "projection_format": s["projection_format"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_market(m):
    return {
        "id": m["id"],
        "distributor_id": m["distributor_id"],
        "code": m["code"],
        "population_tier": m["population_tier"],
        "weekly_coop_budget_cents": m["weekly_coop_budget_cents"],
        "coop_committed_cents": compute_coop_committed(m["id"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_booking(b):
    return {
        "id": b["id"],
        "film_id": b["film_id"],
        "theatre_id": b["theatre_id"],
        "screen_id": b["screen_id"],
        "deal_status": b["deal_status"],
        "print_status": b["print_status"],
        "opening_date": b["opening_date"],
        "min_weeks_committed": b["min_weeks_committed"],
        "week_one_rental_pct": dec_str(b["week_one_rental_pct"]),
        "rental_decay_per_week": dec_str(b["rental_decay_per_week"]),
        "floor_pct": dec_str(b["floor_pct"]),
        "per_capita_floor_cents": b["per_capita_floor_cents"],
        "weeks_played": b["weeks_played"],
        "current_week_rental_pct": dec_str(compute_current_week_rental_pct(b)),
        "aggregate_deal_id": b["aggregate_deal_id"],
        "holdover_eligible": compute_holdover_eligible(b),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_aggregate_deal(a):
    return {
        "id": a["id"],
        "distributor_id": a["distributor_id"],
        "film_id": a["film_id"],
        "circuit": a["circuit"],
        "deal_status": a["deal_status"],
        "aggregate_rental_pct": dec_str(a["aggregate_rental_pct"]),
        "min_screens": a["min_screens"],
        "aggregate_house_allowance_cents": a["aggregate_house_allowance_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_dcp_shipment(s):
    return {
        "id": s["id"],
        "booking_agreement_id": s["booking_agreement_id"],
        "content_format": s["content_format"],
        "tracking_number": s["tracking_number"],
        "shipped_at": s["shipped_at"],
        "delivered_at": s["delivered_at"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_kdm_key(k):
    return {
        "id": k["id"],
        "booking_agreement_id": k["booking_agreement_id"],
        "valid_from_utc": k["valid_from_utc"],
        "valid_until_utc": k["valid_until_utc"],
        "screen_cert_fingerprint": k["screen_cert_fingerprint"],
        "status": k["status"],
        "created_at": k["created_at"],
        "updated_at": k["updated_at"],
        "version": k["version"],
    }


def serialize_box_office_report(r):
    return {
        "id": r["id"],
        "booking_agreement_id": r["booking_agreement_id"],
        "report_date": r["report_date"],
        "gross_cents": r["gross_cents"],
        "admissions": r["admissions"],
        "week_index": r["week_index"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_settlement(s):
    return {
        "id": s["id"],
        "booking_agreement_id": s["booking_agreement_id"],
        "week_index": s["week_index"],
        "gross_cents": s["gross_cents"],
        "house_allowance_cents": s["house_allowance_cents"],
        "net_cents": s["net_cents"],
        "rental_pct_applied": dec_str(s["rental_pct_applied"]),
        "distributor_share_cents": s["distributor_share_cents"],
        "exhibitor_share_cents": s["exhibitor_share_cents"],
        "marketing_offset_cents": s["marketing_offset_cents"],
        "final_distributor_payout_cents": s["final_distributor_payout_cents"],
        "variant": s["variant"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_holdover_decision(h):
    return {
        "id": h["id"],
        "booking_agreement_id": h["booking_agreement_id"],
        "week_index": h["week_index"],
        "prior_week_gross_cents": h["prior_week_gross_cents"],
        "decision": h["decision"],
        "rationale": h["rationale"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def serialize_marketing_commitment(m):
    return {
        "id": m["id"],
        "market_id": m["market_id"],
        "film_id": m["film_id"],
        "theatre_id": m["theatre_id"],
        "committed_cents": m["committed_cents"],
        "spent_cents": m["spent_cents"],
        "outstanding_cents": m["committed_cents"] - m["spent_cents"],
        "status": m["status"],
        "coop_share_pct": dec_str(m["coop_share_pct"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_zone_clearance(z):
    return {
        "id": z["id"],
        "market_id": z["market_id"],
        "film_id": z["film_id"],
        "theatre_id": z["theatre_id"],
        "clearance_radius_km": float(z["clearance_radius_km"]) if z["clearance_radius_km"] is not None else None,
        "effective_from_utc": z["effective_from_utc"],
        "effective_until_utc": z["effective_until_utc"],
        "parent_dispute_id": z["parent_dispute_id"],
        "status": z["status"],
        "created_at": z["created_at"],
        "updated_at": z["updated_at"],
        "version": z["version"],
    }


def serialize_ancillary_window(a):
    return {
        "id": a["id"],
        "film_id": a["film_id"],
        "window_kind": a["window_kind"],
        "scheduled_start_utc": a["scheduled_start_utc"],
        "actual_start_utc": a["actual_start_utc"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


# ---------------- Hierarchy resolution ----------------

def get_distributor(did):
    d = db.distributors.get(did)
    if not d:
        raise err_not_found("Distributor not found")
    return d


def get_film(did, fid):
    get_distributor(did)
    f = db.films.get(fid)
    if not f or f["distributor_id"] != did:
        raise err_not_found("Film not found")
    return f


def get_theatre(did, tid):
    get_distributor(did)
    t = db.theatres.get(tid)
    if not t or t["distributor_id"] != did:
        raise err_not_found("Theatre not found")
    return t


def get_screen(did, tid, sid):
    get_theatre(did, tid)
    s = db.screens.get(sid)
    if not s or s["theatre_id"] != tid:
        raise err_not_found("Screen not found")
    return s


def get_market(did, mid):
    get_distributor(did)
    m = db.markets.get(mid)
    if not m or m["distributor_id"] != did:
        raise err_not_found("Market not found")
    return m


def get_booking(did, baid):
    get_distributor(did)
    b = db.booking_agreements.get(baid)
    if not b:
        raise err_not_found("BookingAgreement not found")
    f = db.films.get(b["film_id"])
    if not f or f["distributor_id"] != did:
        raise err_not_found("BookingAgreement not found")
    return b


def get_aggregate_deal(did, aid):
    get_distributor(did)
    a = db.aggregate_deals.get(aid)
    if not a or a["distributor_id"] != did:
        raise err_not_found("AggregateDeal not found")
    return a


def get_dcp_shipment(did, baid, sid):
    get_booking(did, baid)
    s = db.dcp_shipments.get(sid)
    if not s or s["booking_agreement_id"] != baid:
        raise err_not_found("DCPShipment not found")
    return s


def get_kdm_key(did, baid, kid):
    get_booking(did, baid)
    k = db.kdm_keys.get(kid)
    if not k or k["booking_agreement_id"] != baid:
        raise err_not_found("KDMKey not found")
    return k


def get_box_office_report(did, baid, rid):
    get_booking(did, baid)
    r = db.box_office_reports.get(rid)
    if not r or r["booking_agreement_id"] != baid:
        raise err_not_found("BoxOfficeReport not found")
    return r


def get_settlement(did, baid, sid):
    get_booking(did, baid)
    s = db.settlements.get(sid)
    if not s or s["booking_agreement_id"] != baid:
        raise err_not_found("Settlement not found")
    return s


def get_marketing_commitment(did, mid, mcid):
    get_market(did, mid)
    mc = db.marketing_commitments.get(mcid)
    if not mc or mc["market_id"] != mid:
        raise err_not_found("MarketingCommitment not found")
    return mc


def get_zone_clearance(did, mid, zid):
    get_market(did, mid)
    z = db.zone_clearances.get(zid)
    if not z or z["market_id"] != mid:
        raise err_not_found("ZoneClearance not found")
    return z


def get_zone_clearance_by_id(did, zid):
    get_distributor(did)
    z = db.zone_clearances.get(zid)
    if not z:
        raise err_not_found("ZoneClearance not found")
    m = db.markets.get(z["market_id"])
    if not m or m["distributor_id"] != did:
        raise err_not_found("ZoneClearance not found")
    return z


def get_ancillary_window(did, fid, awid):
    get_film(did, fid)
    a = db.ancillary_windows.get(awid)
    if not a or a["film_id"] != fid:
        raise err_not_found("AncillaryWindow not found")
    return a


# ---------------- Computed fields ----------------

def compute_distributor_posture(did):
    """FROZEN if any DISPUTED settlement under this distributor, else ACTIVE."""
    for s in db.settlements.values():
        if s["status"] == "DISPUTED":
            b = db.booking_agreements.get(s["booking_agreement_id"])
            if b:
                f = db.films.get(b["film_id"])
                if f and f["distributor_id"] == did:
                    return "FROZEN"
    return "ACTIVE"


def compute_screens_committed(film_id):
    count = 0
    for b in db.booking_agreements.values():
        if b["film_id"] == film_id and b["deal_status"] in ("ACCEPTED", "IN_PLAY", "HELD_OVER"):
            count += 1
    return count


def compute_coop_committed(market_id):
    total = 0
    for m in db.marketing_commitments.values():
        if m["market_id"] == market_id and m["status"] in ("COMMITTED", "ACCRUING"):
            total += m["committed_cents"]
    return total


def compute_current_week_rental_pct(b):
    """Aggregate override -> flat pct; otherwise decay from week_one with floor."""
    ad_id = b.get("aggregate_deal_id")
    if ad_id:
        ad = db.aggregate_deals.get(ad_id)
        if ad and ad["deal_status"] == "ACTIVE":
            return dec_pct(ad["aggregate_rental_pct"])
    base = b["week_one_rental_pct"] - (b["rental_decay_per_week"] * b["weeks_played"])
    floor = b["floor_pct"]
    if base < floor:
        base = floor
    return dec_pct(base)


def compute_holdover_eligible(b):
    return b["weeks_played"] >= b["min_weeks_committed"] and b["deal_status"] == "IN_PLAY"


# ---------------- Mutation helper ----------------

def touch(entity):
    """Bump updated_at + version on mutation."""
    entity["updated_at"] = utcnow_iso()
    entity["version"] = entity.get("version", 1) + 1


def new_entity_common():
    ts = utcnow_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
