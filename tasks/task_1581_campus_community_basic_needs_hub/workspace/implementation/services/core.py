"""Core shared services: record lifecycle, derived fields, serializers, cascades."""
from db import db, SEQ
from util import CLOCK, fmt_ts, new_id
from services import calculations as calc


def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = CLOCK.now_iso()
    rec["created_at"] = ts
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next(SEQ)
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """PRD 2.5: every mutation refreshes updated_at and increments version."""
    rec["updated_at"] = CLOCK.now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_records(collection):
    """Creation-timestamp ascending; insertion order breaks ties deterministically."""
    return sorted(db[collection].values(), key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Client derived fields (computed at read; mutation events bump version)
# ---------------------------------------------------------------------------

def verified_assessment(client_id):
    """At most one VERIFIED assessment exists per client (supersede rule)."""
    for a in db["assessments"].values():
        if a["client_id"] == client_id and a["status"] == "VERIFIED":
            return a
    return None


def serialize_client(c):
    out = public(c)
    va = verified_assessment(c["id"])
    hh = va["household_size"] if va else None
    out["risk_tier"] = calc.compute_risk_tier(va)
    out["household_size_effective"] = hh
    out["pantry_points_allotment"] = calc.compute_allotment(hh)
    out["pantry_points_spent_settled"] = calc.points_settled(c["id"])
    out["pantry_points_spent_reserved"] = calc.points_reserved(c["id"])
    out["pantry_week_start"] = fmt_ts(calc.current_week_start())
    out["lifetime_grant_cents"] = calc.lifetime_grant_cents(c["id"])
    noshows = calc.no_show_count_90d(c["id"])
    out["shelter_no_show_count_90d"] = noshows
    out["shelter_restricted"] = noshows >= 2
    return out


def serialize_assessment(a):
    out = public(a)
    ratio = a.get("_ratio")
    out["income_ratio"] = float(ratio) if ratio is not None else None
    return out


def serialize_fund(f):
    out = public(f)
    out["remaining_committed_basis"] = f["allocated_cents"] - f["committed_cents"] - f["disbursed_cents"]
    out["remaining_cash_basis"] = f["allocated_cents"] - f["disbursed_cents"]
    return out


def serialize_staff(s):
    out = public(s)
    out["active_case_load"] = calc.counselor_case_load(s["id"])
    return out


# ---------------------------------------------------------------------------
# Counter reconciliation (PRD 2.10): recompute from source rows, then bump
# ---------------------------------------------------------------------------

def recompute_fund(fund, bump=True):
    committed, disbursed = calc.fund_counters(fund["id"])
    fund["committed_cents"] = committed
    fund["disbursed_cents"] = disbursed
    if bump:
        touch(fund)


def fund_remaining_committed(fund) -> int:
    return fund["allocated_cents"] - fund["committed_cents"] - fund["disbursed_cents"]


def recompute_agency(agency, bump=True):
    count = sum(
        1 for r in db["referrals"].values()
        if r["agency_id"] == agency["id"] and r["status"] in ("SENT", "ACKNOWLEDGED", "APPOINTMENT_BOOKED")
    )
    agency["active_referral_count"] = count
    if bump:
        touch(agency)


def recompute_event(event, bump=True):
    registered = sum(
        1 for r in db["event_registrations"].values()
        if r["event_id"] == event["id"] and r["status"] == "REGISTERED"
    )
    attended = sum(
        1 for r in db["event_registrations"].values()
        if r["event_id"] == event["id"] and r["status"] == "ATTENDED"
    )
    event["registered_count"] = registered
    event["attended_count"] = attended
    # Automatic posture flips (OPEN<->FULL) only apply while the event is live
    if event["status"] == "OPEN" and registered >= event["capacity"]:
        event["status"] = "FULL"
    elif event["status"] == "FULL" and registered < event["capacity"]:
        event["status"] = "OPEN"
    if bump:
        touch(event)


def promote_queued_application(fund) -> bool:
    """fund_reopen_promotion: earliest-created QUEUED application -> SUBMITTED."""
    queued = [g for g in db["grant_applications"].values()
              if g["fund_id"] == fund["id"] and g["status"] == "QUEUED"]
    if not queued:
        return False
    oldest = min(queued, key=lambda g: g["_seq"])
    oldest["status"] = "SUBMITTED"
    touch(oldest)
    return True


def maybe_reopen_fund(fund) -> bool:
    """EXHAUSTED -> OPEN when committed-basis headroom returns; promotes one queued app."""
    if fund["status"] == "EXHAUSTED" and fund_remaining_committed(fund) > 0:
        fund["status"] = "OPEN"
        return True
    return False


def void_visit(visit):
    """Void a visit from CHECKED_IN or COMPLETED (PRD 3.3)."""
    was = visit["status"]
    if was == "CHECKED_IN":
        # Provisional lines discarded; no stock or points movement.
        for li in list(db["visit_line_items"].values()):
            if li["visit_id"] == visit["id"]:
                del db["visit_line_items"][li["id"]]
        visit["provisional_points"] = 0
    elif was == "COMPLETED":
        # Restore stock per line; each restore recomputes the item's restock_flag.
        for li in list(db["visit_line_items"].values()):
            if li["visit_id"] != visit["id"]:
                continue
            item = db["pantry_items"].get(li["item_id"])
            if item is not None:
                item["quantity_on_hand"] += li["quantity"]
                item["restock_flag"] = item["quantity_on_hand"] <= item["reorder_threshold"]
                touch(item)
        visit["points_spent"] = 0
    visit["status"] = "VOIDED"
    touch(visit)
