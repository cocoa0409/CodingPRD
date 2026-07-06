"""Logical clock helpers — PRD §2.9. Also drives time-gated auto-transitions."""

from datetime import timedelta

import db
from utils import iso_now_from_clock, parse_iso, dt_to_iso


def get_now():
    """Return the current logical clock as an aware datetime (UTC)."""
    return iso_now_from_clock(db.current_utc_iso)


def get_now_iso():
    return db.current_utc_iso


def set_now(dt_or_iso):
    """Advance the logical clock. Accepts an aware datetime or ISO string."""
    if isinstance(dt_or_iso, str):
        # Normalize to our canonical formatting.
        dt = parse_iso(dt_or_iso)
    else:
        dt = dt_or_iso
    db.current_utc_iso = dt_to_iso(dt)


# ---------------- Time-gated auto-transitions ---------------- #

def sweep_time_transitions():
    """Run every time-gated auto-transition described in PRD §3.2/§3.5/§3.6/§3.7.

    Executed after every call to set_now (§2.9) — the PRD explicitly says the
    transitions fire "as part of the same request". Also called on-demand from
    endpoint handlers before evaluating state preconditions so a request that
    doesn't touch the clock still observes an up-to-date state.
    """
    # Local imports to avoid circular imports at module load time.
    from services import assessment as assessment_svc
    from services import violation as violation_svc
    from services import reservation as reservation_svc
    from services import homeowner as homeowner_svc

    now_dt = get_now()
    now_iso = get_now_iso()

    # 1) Assessments: OPEN|PARTIALLY_PAID -> OVERDUE when now >= due_date;
    #    OVERDUE -> DELINQUENT when now >= due_date + 60 days.
    assessments_needing_homeowner_recompute = set()
    for a in list(db.assessments.values()):
        due_dt = parse_iso(a["due_date"])
        if a["status"] in ("OPEN", "PARTIALLY_PAID") and now_dt >= due_dt:
            assessment_svc.transition_to_overdue(a, now_iso)
            prop = db.properties.get(a["property_id"])
            if prop:
                assessments_needing_homeowner_recompute.add(prop["homeowner_id"])
        if a["status"] == "OVERDUE" and now_dt >= (due_dt + timedelta(days=60)):
            a["status"] = "DELINQUENT"
            a["updated_at"] = now_iso
            a["version"] = a.get("version", 1) + 1
            prop = db.properties.get(a["property_id"])
            if prop:
                assessments_needing_homeowner_recompute.add(prop["homeowner_id"])

    # 2) Violations: FINED for > 14 days without appeal -> UPHELD.
    for v in list(db.violations.values()):
        if v["status"] == "FINED" and v.get("fined_at"):
            fined_dt = parse_iso(v["fined_at"])
            if now_dt > (fined_dt + timedelta(days=14)):
                v["status"] = "UPHELD"
                v["updated_at"] = now_iso
                v["version"] = v.get("version", 1) + 1
                # fine_balance_cents stays at fine_amount_cents (UPHELD keeps the fine).

    # 3) AmenityReservations: BOOKED past end_ts -> NO_SHOW; CHECKED_IN past end_ts -> COMPLETED.
    for r in list(db.amenity_reservations.values()):
        end_dt = parse_iso(r["end_ts"])
        if now_dt >= end_dt:
            if r["status"] == "BOOKED":
                r["status"] = "NO_SHOW"
                r["updated_at"] = now_iso
                r["version"] = r.get("version", 1) + 1
            elif r["status"] == "CHECKED_IN":
                r["status"] = "COMPLETED"
                r["updated_at"] = now_iso
                r["version"] = r.get("version", 1) + 1

    # 4) Property/Homeowner recompute for every homeowner touched by the assessment sweep.
    #    Assessment overdue/delinquent transitions change property.total_outstanding_cents
    #    and downstream delinquency_score/standing/booking_privilege.
    property_ids_touched = set()
    for a in db.assessments.values():
        prop = db.properties.get(a["property_id"])
        if prop:
            property_ids_touched.add(prop["id"])
    for pid in property_ids_touched:
        prop = db.properties.get(pid)
        if prop:
            from services import property as property_svc
            property_svc.recompute(prop, now_iso)
    for hid in assessments_needing_homeowner_recompute:
        home = db.homeowners.get(hid)
        if home:
            homeowner_svc.recompute(home, now_iso)
