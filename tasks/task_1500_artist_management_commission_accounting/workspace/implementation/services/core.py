"""Core shared services: record lifecycle, artist aggregates, sunset windows, overlap math."""
from datetime import timedelta

from db import db
from util import new_id, now_ts, add_months, parse_date, parse_datetime


def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def get_artist(artist_id):
    return db["artists"].get(artist_id)


def recompute_artist(artist_id, bump=True):
    """Recompute the four standing-ledger aggregates; bump artist version (PRD 2.9)."""
    artist = db["artists"].get(artist_id)
    if artist is None:
        return
    unrecouped = sum(
        a["outstanding_cents"]
        for a in db["advances"].values()
        if a["artist_id"] == artist_id and a["status"] == "ACTIVE"
    )
    lifetime_gross = sum(
        e["gross_amount_cents"]
        for e in db["income_events"].values()
        if e["artist_id"] == artist_id and e["status"] != "VOIDED"
    )
    lifetime_commission = sum(
        e["commission_amount_cents"] or 0
        for e in db["income_events"].values()
        if e["artist_id"] == artist_id and e["status"] in ("VERIFIED", "SETTLED", "POSTED")
    )
    lifetime_disbursed = sum(
        s["disbursed_cents"]
        for s in db["statements"].values()
        if s["artist_id"] == artist_id and s["status"] == "FINALIZED"
    )
    changed = (
        artist["unrecouped_advance_balance_cents"] != unrecouped
        or artist["lifetime_gross_cents"] != lifetime_gross
        or artist["lifetime_commission_cents"] != lifetime_commission
        or artist["lifetime_disbursed_cents"] != lifetime_disbursed
    )
    artist["unrecouped_advance_balance_cents"] = unrecouped
    artist["lifetime_gross_cents"] = lifetime_gross
    artist["lifetime_commission_cents"] = lifetime_commission
    artist["lifetime_disbursed_cents"] = lifetime_disbursed
    if bump:
        # Workflows that recompute aggregates increment the artist version (PRD 2.9)
        touch(artist)
    return changed


def max_sunset_months(agreement_id):
    months = [
        s["sunset_months"]
        for s in db["rate_schedules"].values()
        if s["agreement_id"] == agreement_id
    ]
    return max(months) if months else 0


def compute_sunset_window(start_date_iso):
    """sunset_end = start + max(sunset_months) - 1 day; null when max == 0."""
    if start_date_iso is None:
        return None
    return None  # replaced by caller with agreement context; see below


def set_sunset_window(agreement, start_date):
    """Given an agreement and an ISO sunset start date, set sunset start/end fields."""
    agreement["sunset_start_date"] = start_date.isoformat() if hasattr(start_date, "isoformat") else start_date
    mm = max_sunset_months(agreement["id"])
    if mm == 0:
        agreement["sunset_end_date"] = None
    else:
        start = parse_date(agreement["sunset_start_date"])
        end = add_months(start, mm) - timedelta(days=1)
        agreement["sunset_end_date"] = end.isoformat()


def cancel_pending_approvals_for(target_type, target_id):
    for req in db["approval_requests"].values():
        if (
            req["target_type"] == target_type
            and req["target_id"] == target_id
            and req["status"] == "PENDING"
        ):
            req["status"] = "CANCELLED"
            touch(req)


# ---------------------------------------------------------------------------
# Engagement overlap (buffered) and cascades (PRD 3.4)
# ---------------------------------------------------------------------------

def _buffered_window(eng):
    start = parse_datetime(eng["start_datetime"]) - timedelta(hours=eng["travel_buffer_hours"])
    end = parse_datetime(eng["end_datetime"]) + timedelta(hours=eng["travel_buffer_hours"])
    return start, end


def windows_conflict(e1, e2):
    """Strict-intersection overlap over buffered windows; touching allowed."""
    s1, e1_ = _buffered_window(e1)
    s2, e2_ = _buffered_window(e2)
    return s1 < e2_ and s2 < e1_


def confirm_cascade(artist_id, confirmed_eng, exclude_id=None):
    """Check conflicts vs CONFIRMED; on success release overlapping HOLDs and
    withdraw their open opportunities.

    Returns None on success; raises ApiError(ERR_ENGAGEMENT_OVERLAP) on conflict.
    """
    from errors import raise_error, ERR_ENGAGEMENT_OVERLAP

    for other in db["engagements"].values():
        if other["artist_id"] != artist_id:
            continue
        if other["id"] == (exclude_id or confirmed_eng["id"]):
            continue
        if other["status"] == "CONFIRMED" and windows_conflict(confirmed_eng, other):
            raise_error(ERR_ENGAGEMENT_OVERLAP,
                        "buffered window collides with another CONFIRMED engagement")
    # Release overlapping HOLDs
    for other in list(db["engagements"].values()):
        if other["artist_id"] != artist_id:
            continue
        if other["id"] == confirmed_eng["id"]:
            continue
        if other["status"] == "HOLD" and windows_conflict(confirmed_eng, other):
            other["status"] = "RELEASED"
            touch(other)
            opp_id = other.get("opportunity_id")
            if opp_id:
                opp = db["opportunities"].get(opp_id)
                if opp is not None and opp["status"] in ("RECEIVED", "UNDER_EVALUATION", "NEGOTIATING"):
                    opp["status"] = "WITHDRAWN"
                    touch(opp)
                    cancel_pending_approvals_for("OPPORTUNITY", opp["id"])


def has_active_dispute(statement_id):
    for d in db["disputes"].values():
        if d["statement_id"] == statement_id and d["status"] in ("OPEN", "UNDER_REVIEW"):
            return True
    return False
