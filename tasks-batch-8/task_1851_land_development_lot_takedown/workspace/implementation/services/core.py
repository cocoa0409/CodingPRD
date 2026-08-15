"""Record lifecycle, lookups, and parcel derived-field reconciliation (PRD 2.4, 2.9, 3.8)."""
from datetime import timedelta

from db import db
from services import calculations as calc
from util import CLOCK, new_id, now_ts, parse_dt


def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version by exactly one."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def phases_of_parcel(parcel_id):
    return [p for p in db["phases"].values() if p["parcel_id"] == parcel_id]


def lots_of_phase(phase_id):
    return [lot for lot in db["lots"].values() if lot["phase_id"] == phase_id]


def lots_of_parcel(parcel_id):
    phase_ids = {p["id"] for p in phases_of_parcel(parcel_id)}
    return [lot for lot in db["lots"].values() if lot["phase_id"] in phase_ids]


def hoas_of_parcel(parcel_id):
    return [h for h in db["hoas"].values() if h["parcel_id"] == parcel_id]


def active_loan_for(parcel_id):
    """loan_selector_for_parcel: at most one ACTIVE loan per parcel can exist
    (the uniqueness rule blocks a second open loan); empty -> None."""
    for loan in db["loans"].values():
        if loan["parcel_id"] == parcel_id and loan["status"] == "ACTIVE":
            return loan
    return None


# ---------------------------------------------------------------------------
# Parcel derived fields (PRD 3.8) — recomputed on plat recordation, closing
# finalize, lot-release cascades, lot reserve, and every clock set.
# ---------------------------------------------------------------------------

def _trailing_counts(parcel_id, now):
    phase_ids = {p["id"] for p in phases_of_parcel(parcel_id)}
    lot_ids = {lot["id"] for lot in db["lots"].values() if lot["phase_id"] in phase_ids}
    c1 = c2 = c3 = 0
    for closing in db["closings"].values():
        if closing["status"] != "CLOSED" or closing["lot_id"] not in lot_ids:
            continue
        fin = parse_dt(closing["finalized_at"])
        if now - timedelta(days=30) <= fin <= now:
            c1 += 1  # [now-30d, now] — both endpoints included
        elif now - timedelta(days=60) <= fin < now - timedelta(days=30):
            c2 += 1  # [now-60d, now-30d)
        elif now - timedelta(days=90) <= fin < now - timedelta(days=60):
            c3 += 1  # [now-90d, now-60d)
    return c1, c2, c3


def recompute_parcel(parcel, bump="always"):
    """Recompute the parcel's derived fields from current state.

    bump: "always" increments version unconditionally (scaffold-specified
    triggers: recordation, finalize, lot-release cascade, reserve);
    "change" increments only when a derived value actually moved (clock-set
    re-anchoring); "never" writes values without touching version.
    """
    lots = lots_of_parcel(parcel["id"])
    total = len(lots)
    closed = sum(1 for lot in lots if lot["sales_status"] == "CLOSED")
    available = sum(1 for lot in lots if lot["sales_status"] == "PLATTED")
    cpct = calc.closed_pct_calc(closed, total)
    slp = calc.straight_line_pace(total, parcel["planned_sellout_months"])
    c1, c2, c3 = _trailing_counts(parcel["id"], CLOCK.now())
    twp = calc.trailing_weighted_pace(c1, c2, c3)
    sel = slp if parcel["absorption_method"] == "STRAIGHT_LINE" else twp
    proj = calc.projection_calc(total - closed, sel)
    eligible = proj is not None and proj <= calc.PHASE_LEAD_MONTHS

    new_values = {
        "total_lots_planned": total,
        "lots_closed_count": closed,
        "lots_available_count": available,
        "closed_pct": float(cpct),
        "straight_line_pace_pm": float(slp),
        "trailing_weighted_pace_pm": float(twp),
        "selected_pace_pm": float(sel),
        "projected_months_to_sellout": (float(proj) if proj is not None else None),
        "next_phase_release_eligible": bool(eligible),
    }
    changed = any(parcel.get(k) != v for k, v in new_values.items())
    parcel.update(new_values)
    if bump == "always" or (bump == "change" and changed):
        touch(parcel)
