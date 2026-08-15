"""Domain logic: serializers, rollups, cascades, lazy time transitions,
duplicate hashing, age bands, thank-you template selection."""

import hashlib
from datetime import datetime, timezone, timedelta

import clock
import db
from util import format_ts, age_years_at, age_band_for

PLEDGE_WINDOW = timedelta(hours=72)
FAMILY_TERMINAL = {"REJECTED", "CLOSED", "WITHDRAWN"}
ADOPTION_ACTIVE = {"PLEDGED", "CONFIRMED", "PARTIALLY_RECEIVED"}
GIFT_RECEIVED_PLUS = {"RECEIVED", "SORTED", "STAGED", "DELIVERED"}
PII_FIELDS = ("primary_caregiver_name", "caregiver_dob", "address_text", "phone_last4")


# ---------------------------------------------------------------------------
# generic row helpers
# ---------------------------------------------------------------------------

def make_row():
    now = clock.now()
    return {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def audit(family_id, actor_role, actor_id, event_type, payload=None):
    now = clock.now()
    ev = {
        "id": db.new_id(),
        "created_at": now,
        "occurred_at": now,
        "_seq": db.next_seq(),
        "family_id": family_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "event_type": event_type,
        "payload_json": payload or {},
    }
    db.family_audit_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------------------
# settings singleton
# ---------------------------------------------------------------------------

def get_settings():
    row = db.season_settings.get("GLOBAL")
    if row is None:
        row = make_row()
        row.update(
            singleton_key="GLOBAL",
            duplicate_auto_detect_enabled=True,
            duplicate_hash_salt="",
            late_donor_grace_hours=0,
            major_donor_threshold_cents=50000,
        )
        db.season_settings["GLOBAL"] = row
    return row


# ---------------------------------------------------------------------------
# computed fields
# ---------------------------------------------------------------------------

def agency_referral_used_count(agency_id):
    return sum(
        1
        for f in db.families.values()
        if f["agency_id"] == agency_id and f["status"] not in FAMILY_TERMINAL
    )


def slot_gifts_staged_count(slot_id):
    return sum(
        1 for g in db.gifts.values() if g.get("slot_id") == slot_id and g["status"] == "STAGED"
    )


def recompute_child_estimate(child):
    child["gift_estimate_cents"] = sum(
        w["estimated_price_cents"]
        for w in db.wish_items.values()
        if w["child_id"] == child["id"] and w["status"] in ("REQUESTED", "APPROVED")
    )
    touch(child)


def family_rollup(family, adjust_status=True):
    """Recompute fulfilled/total counts and (optionally) drive family status
    per PRD §3.10. Fires on child status transitions."""
    kids = [c for c in db.children.values() if c["family_id"] == family["id"]]
    fulfilled = sum(1 for c in kids if c["status"] in ("DELIVERED", "BACKFILL_PURCHASED"))
    total = sum(1 for c in kids if c["status"] != "CLOSED")
    family["fulfilled_children_count"] = fulfilled
    family["total_children_count"] = total
    if adjust_status and family["status"] in ("MATCHED", "PARTIALLY_FULFILLED"):
        if fulfilled == 0:
            family["status"] = "MATCHED"
        elif fulfilled < total:
            family["status"] = "PARTIALLY_FULFILLED"
        elif total > 0:
            any_backfill = any(c["status"] == "BACKFILL_PURCHASED" for c in kids)
            family["status"] = "BACKFILLED" if any_backfill else "FULFILLED"
    touch(family)


def adoption_covered_children(adoption):
    return [
        db.children[cid]
        for cid in adoption.get("_covered_child_ids", [])
        if cid in db.children
    ]


def recompute_adoptions_for_family(family):
    """Flip adoptions to FULFILLED when every covered child is terminal-done."""
    for a in db.adoptions.values():
        if a["family_id"] != family["id"]:
            continue
        if a["status"] not in ("CONFIRMED", "PARTIALLY_RECEIVED"):
            continue
        covered = adoption_covered_children(a)
        if covered and all(
            c["status"] in ("DELIVERED", "BACKFILL_PURCHASED", "CLOSED") for c in covered
        ):
            a["status"] = "FULFILLED"
            touch(a)


def donor_concurrent_count(donor_id, campaign_id, exclude_adoption_id=None):
    n = 0
    for a in db.adoptions.values():
        if a["donor_id"] == donor_id and a["campaign_id"] == campaign_id:
            if a["status"] in ADOPTION_ACTIVE and a["id"] != exclude_adoption_id:
                n += 1
    return n


# ---------------------------------------------------------------------------
# lazy time-based transitions (PRD §2.5)
# ---------------------------------------------------------------------------

def _expire_adoption(a):
    a["status"] = "EXPIRED"
    touch(a)


def lazy_time_sweep():
    """Adoption pledge expiry + slot no-show, evaluated on reads/writes."""
    now = clock.now()
    for a in db.adoptions.values():
        if a["status"] == "PLEDGED" and now > a["pledged_at"] + PLEDGE_WINDOW:
            _expire_adoption(a)
    for s in db.distribution_slots.values():
        if s["status"] == "RESERVED" and now > s["window_end"]:
            s["status"] = "NO_SHOW"
            touch(s)
            for g in db.gifts.values():
                if g.get("slot_id") == s["id"] and g["status"] == "STAGED":
                    g["status"] = "SORTED"
                    g["slot_id"] = None
                    touch(g)


# ---------------------------------------------------------------------------
# duplicate hashing (PRD §3.3)
# ---------------------------------------------------------------------------

def compute_duplicate_hash(caregiver_dob, phone_last4, address_text):
    settings = get_settings()
    normalized = "%s|%s|%s" % (
        str(caregiver_dob).strip().lower(),
        phone_last4,
        "".join(ch for ch in str(address_text) if ch.isdigit()),
    )
    digest = hashlib.sha256(
        (settings["duplicate_hash_salt"] + ":" + normalized).encode("utf-8")
    ).hexdigest()
    return digest


def raise_auto_flags(new_family):
    settings = get_settings()
    if not settings["duplicate_auto_detect_enabled"]:
        return
    for other in sort_rows(list(db.families.values())):
        if other["id"] == new_family["id"]:
            continue
        if other["campaign_id"] != new_family["campaign_id"]:
            continue
        if other["status"] in FAMILY_TERMINAL:
            continue
        if other["duplicate_hash"] != new_family["duplicate_hash"]:
            continue
        flag = make_row()
        flag.update(
            family_id=new_family["id"],
            other_family_id=other["id"],
            detected_by="AUTO_HASH",
            status="OPEN",
            resolution_note="",
        )
        db.duplicate_flags[flag["id"]] = flag


def family_has_open_flag(family_id):
    for f in db.duplicate_flags.values():
        if f["status"] == "OPEN" and (
            f["family_id"] == family_id or f["other_family_id"] == family_id
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# age bands
# ---------------------------------------------------------------------------

def compute_child_age_band(dob_date, campaign):
    years = age_years_at(dob_date, campaign["distribution_date"])
    return years, age_band_for(years)


def recheck_age_bands_on_distribution_shift(campaign, actor):
    """PRD §3.1: children keep their old band but an audit event is written
    for any child whose band would change."""
    for child in db.children.values():
        fam = db.families.get(child["family_id"])
        if fam is None or fam["campaign_id"] != campaign["id"]:
            continue
        years = age_years_at(child["_dob"], campaign["distribution_date"])
        new_band = age_band_for(years)
        if new_band != child["age_band"]:
            audit(
                fam["id"],
                actor.role,
                actor.user_id,
                "STATUS_CHANGE",
                {
                    "field": "age_band",
                    "child_id": child["id"],
                    "old_band": child["age_band"],
                    "new_band": new_band,
                },
            )


# ---------------------------------------------------------------------------
# cascades shared by several transitions
# ---------------------------------------------------------------------------

def cascade_family_rejected(family, actor, reason):
    """Family -> REJECTED: children -> CLOSED, their wish items -> REJECTED."""
    family["status"] = "REJECTED"
    touch(family)
    for child in db.children.values():
        if child["family_id"] != family["id"]:
            continue
        if child["status"] != "CLOSED":
            child["status"] = "CLOSED"
            touch(child)
        for w in db.wish_items.values():
            if w["child_id"] == child["id"] and w["status"] != "REJECTED":
                w["status"] = "REJECTED"
                touch(w)
        recompute_child_estimate(child)
    family_rollup(family, adjust_status=False)


def cascade_children_closed(family):
    for child in db.children.values():
        if child["family_id"] == family["id"] and child["status"] != "CLOSED":
            child["status"] = "CLOSED"
            touch(child)
    family_rollup(family, adjust_status=False)


def expire_adoption_cascade(adoption, actor=None):
    """Shared cascade for EXPIRED / DONOR_CANCELLED / LATE_CANCELLED /
    ADMIN_CANCELLED per §1.2 Adoption."""
    for g in db.gifts.values():
        if g["adoption_id"] == adoption["id"] and g["status"] in ("COMMITTED", "IN_TRANSIT"):
            g["status"] = "RETURNED_TO_DONOR"
            touch(g)
    covered = adoption_covered_children(adoption)
    family = db.families.get(adoption["family_id"])
    for child in covered:
        if child["status"] == "ADOPTED":
            child["status"] = "BACKFILL_ELIGIBLE"
            touch(child)
        for w in db.wish_items.values():
            if w["child_id"] == child["id"] and w["status"] == "COMMITTED":
                w["status"] = "APPROVED"
                touch(w)
        recompute_child_estimate(child)
    if family is not None:
        family_rollup(family, adjust_status=True)


def family_revert_after_cancel(adoption, actor):
    """Donor-cancel rule: family MATCHED -> VERIFIED when no other confirmed
    adoption covers it; otherwise leave the rollup result."""
    family = db.families.get(adoption["family_id"])
    if family is None or family["status"] != "MATCHED":
        return
    other_active = any(
        a["id"] != adoption["id"]
        and a["family_id"] == family["id"]
        and a["status"] in ("CONFIRMED", "PARTIALLY_RECEIVED")
        for a in db.adoptions.values()
    )
    if not other_active:
        family["status"] = "VERIFIED"
        touch(family)
        audit(
            family["id"],
            actor.role,
            actor.user_id,
            "STATUS_CHANGE",
            {"from": "MATCHED", "to": "VERIFIED", "reason": "ADOPTION_CANCELLED"},
        )


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def ser_campaign(c):
    return {
        "id": c["id"],
        "season_year": c["season_year"],
        "status": c["status"],
        "intake_open_at": format_ts(c["intake_open_at"]),
        "intake_close_at": format_ts(c["intake_close_at"]),
        "gift_return_deadline": format_ts(c["gift_return_deadline"]),
        "distribution_date": format_ts(c["distribution_date"]),
        "max_children_per_family": c["max_children_per_family"],
        "max_gift_value_cents": c["max_gift_value_cents"],
        "min_gift_value_cents": c["min_gift_value_cents"],
        "backfill_budget_cents": c["backfill_budget_cents"],
        "backfill_spent_cents": c["backfill_spent_cents"],
        "privacy_mode": c["privacy_mode"],
        "version": c["version"],
        "created_at": format_ts(c["created_at"]),
        "updated_at": format_ts(c["updated_at"]),
    }


def ser_agency(a):
    return {
        "id": a["id"],
        "agency_code": a["agency_code"],
        "legal_name": a["legal_name"],
        "status": a["status"],
        "referral_quota": a["referral_quota"],
        "referral_used_count": agency_referral_used_count(a["id"]),
        "contact_email": a["contact_email"],
        "version": a["version"],
        "created_at": format_ts(a["created_at"]),
        "updated_at": format_ts(a["updated_at"]),
    }


def ser_family(f, actor=None):
    out = {
        "id": f["id"],
        "agency_id": f["agency_id"],
        "campaign_id": f["campaign_id"],
        "primary_caregiver_name": f["primary_caregiver_name"],
        "caregiver_dob": f["caregiver_dob"],
        "household_size": f["household_size"],
        "address_text": f["address_text"],
        "phone_last4": f["phone_last4"],
        "duplicate_hash": f["duplicate_hash"],
        "status": f["status"],
        "verification_note": f["verification_note"],
        "verified_at": format_ts(f["verified_at"]) if f["verified_at"] else None,
        "fulfilled_children_count": f["fulfilled_children_count"],
        "total_children_count": f["total_children_count"],
        "duplicate_of_family_id": f["duplicate_of_family_id"],
        "version": f["version"],
        "created_at": format_ts(f["created_at"]),
        "updated_at": format_ts(f["updated_at"]),
    }
    if actor is not None and actor.role == "Donor":
        for k in PII_FIELDS:
            out.pop(k, None)
    return out


def ser_child(c, actor=None):
    if actor is not None and actor.role == "Donor":
        fam = db.families.get(c["family_id"])
        campaign = db.campaigns.get(fam["campaign_id"]) if fam else None
        out = {
            "id": c["id"],
            "family_id": c["family_id"],
            "first_name": c["first_name"],
            "age_band": c["age_band"],
            "status": c["status"],
            "version": c["version"],
            "created_at": format_ts(c["created_at"]),
            "updated_at": format_ts(c["updated_at"]),
        }
        if campaign is not None and campaign["privacy_mode"] == "STANDARD":
            out["interest_tags"] = list(c["interest_tags"])
            out["clothing_size"] = c["clothing_size"]
        return out
    return {
        "id": c["id"],
        "family_id": c["family_id"],
        "first_name": c["first_name"],
        "dob": c["dob"],
        "gender": c["gender"],
        "age_band": c["age_band"],
        "clothing_size": c["clothing_size"],
        "interest_tags": list(c["interest_tags"]),
        "status": c["status"],
        "gift_estimate_cents": c["gift_estimate_cents"],
        "version": c["version"],
        "created_at": format_ts(c["created_at"]),
        "updated_at": format_ts(c["updated_at"]),
    }


def ser_wish_item(w):
    return {
        "id": w["id"],
        "child_id": w["child_id"],
        "description": w["description"],
        "category": w["category"],
        "estimated_price_cents": w["estimated_price_cents"],
        "priority_rank": w["priority_rank"],
        "status": w["status"],
        "version": w["version"],
        "created_at": format_ts(w["created_at"]),
        "updated_at": format_ts(w["updated_at"]),
    }


def ser_donor(d):
    return {
        "id": d["id"],
        "email": d["email"],
        "display_name": d["display_name"],
        "status": d["status"],
        "max_adoptions_per_season": d["max_adoptions_per_season"],
        "preferred_age_bands": list(d["preferred_age_bands"]),
        "giving_history_cents": d["giving_history_cents"],
        "thank_you_opt_in": d["thank_you_opt_in"],
        "version": d["version"],
        "created_at": format_ts(d["created_at"]),
        "updated_at": format_ts(d["updated_at"]),
    }


def ser_adoption(a):
    return {
        "id": a["id"],
        "campaign_id": a["campaign_id"],
        "donor_id": a["donor_id"],
        "family_id": a["family_id"],
        "scope": a["scope"],
        "child_ids": list(a["child_ids"]),
        "commitment_cents": a["commitment_cents"],
        "status": a["status"],
        "pledged_at": format_ts(a["pledged_at"]),
        "confirmed_at": format_ts(a["confirmed_at"]) if a["confirmed_at"] else None,
        "return_deadline": format_ts(a["return_deadline"]) if a["return_deadline"] else None,
        "version": a["version"],
        "created_at": format_ts(a["created_at"]),
        "updated_at": format_ts(a["updated_at"]),
    }


def ser_gift(g):
    return {
        "id": g["id"],
        "adoption_id": g["adoption_id"],
        "child_id": g["child_id"],
        "wish_item_id": g["wish_item_id"],
        "description": g["description"],
        "declared_value_cents": g["declared_value_cents"],
        "status": g["status"],
        "received_at": format_ts(g["received_at"]) if g["received_at"] else None,
        "sorted_at": format_ts(g["sorted_at"]) if g["sorted_at"] else None,
        "slot_id": g["slot_id"],
        "version": g["version"],
        "created_at": format_ts(g["created_at"]),
        "updated_at": format_ts(g["updated_at"]),
    }


def ser_backfill(p):
    return {
        "id": p["id"],
        "campaign_id": p["campaign_id"],
        "child_id": p["child_id"],
        "wish_item_id": p["wish_item_id"],
        "quoted_cost_cents": p["quoted_cost_cents"],
        "final_cost_cents": p["final_cost_cents"],
        "status": p["status"],
        "purchased_at": format_ts(p["purchased_at"]) if p["purchased_at"] else None,
        "version": p["version"],
        "created_at": format_ts(p["created_at"]),
        "updated_at": format_ts(p["updated_at"]),
    }


def ser_event(e):
    return {
        "id": e["id"],
        "campaign_id": e["campaign_id"],
        "site_name": e["site_name"],
        "start_at": format_ts(e["start_at"]),
        "end_at": format_ts(e["end_at"]),
        "status": e["status"],
        "capacity_slots": e["capacity_slots"],
        "version": e["version"],
        "created_at": format_ts(e["created_at"]),
        "updated_at": format_ts(e["updated_at"]),
    }


def ser_slot(s):
    return {
        "id": s["id"],
        "event_id": s["event_id"],
        "family_id": s["family_id"],
        "window_start": format_ts(s["window_start"]),
        "window_end": format_ts(s["window_end"]),
        "lane": s["lane"],
        "status": s["status"],
        "gifts_staged_count": slot_gifts_staged_count(s["id"]),
        "version": s["version"],
        "created_at": format_ts(s["created_at"]),
        "updated_at": format_ts(s["updated_at"]),
    }


def ser_flag(f):
    return {
        "id": f["id"],
        "family_id": f["family_id"],
        "other_family_id": f["other_family_id"],
        "detected_by": f["detected_by"],
        "status": f["status"],
        "resolution_note": f["resolution_note"],
        "version": f["version"],
        "created_at": format_ts(f["created_at"]),
        "updated_at": format_ts(f["updated_at"]),
    }


def ser_note(n):
    return {
        "id": n["id"],
        "campaign_id": n["campaign_id"],
        "donor_id": n["donor_id"],
        "template": n["template"],
        "status": n["status"],
        "sent_at": format_ts(n["sent_at"]) if n["sent_at"] else None,
        "personalization_token": n["personalization_token"],
        "version": n["version"],
        "created_at": format_ts(n["created_at"]),
        "updated_at": format_ts(n["updated_at"]),
    }


def ser_audit(e):
    return {
        "id": e["id"],
        "family_id": e["family_id"],
        "actor_role": e["actor_role"],
        "actor_id": e["actor_id"],
        "event_type": e["event_type"],
        "payload_json": e["payload_json"],
        "occurred_at": format_ts(e["occurred_at"]),
        "created_at": format_ts(e["created_at"]),
    }


def ser_settings(s):
    return {
        "id": s["id"],
        "singleton_key": s["singleton_key"],
        "duplicate_auto_detect_enabled": s["duplicate_auto_detect_enabled"],
        "duplicate_hash_salt": s["duplicate_hash_salt"],
        "late_donor_grace_hours": s["late_donor_grace_hours"],
        "major_donor_threshold_cents": s["major_donor_threshold_cents"],
        "version": s["version"],
        "created_at": format_ts(s["created_at"]),
        "updated_at": format_ts(s["updated_at"]),
    }
