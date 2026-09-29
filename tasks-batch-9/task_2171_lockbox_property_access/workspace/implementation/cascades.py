"""Shared cascades and compensations (PRD §2.9)."""
from core import db, iso, new_common, now, ordered, parse_dt, touch
import calc


# --- charges ---------------------------------------------------------------
def create_charge(member_id, charge_type, amount_cents, variant_applied, basis,
                  lockbox_id=None, placement_id=None):
    rec = new_common()
    rec.update({
        "member_id": member_id,
        "lockbox_id": lockbox_id,
        "placement_id": placement_id,
        "charge_type": charge_type,
        "amount_cents": int(amount_cents),
        "variant_applied": variant_applied,
        "basis": basis,
        "status": "PENDING",
    })
    db.charges[rec["id"]] = rec
    return rec


# --- hop 1 variants --------------------------------------------------------
def suspend_active_credentials(member_id):
    """Member SUSPEND / EXPIRE cascade hop 1."""
    touched = 0
    for cred in ordered(db.credentials, calc.member_credentials(member_id)):
        if cred["status"] == "ACTIVE":
            cred["status"] = "SUSPENDED"
            cred["suspended_by_cascade"] = True
            touch(cred)
            touched += 1
    return touched


def restore_cascade_credentials(member_id):
    """Member REINSTATE / RENEW compensation."""
    clock = now()
    restored = 0
    for cred in ordered(db.credentials, calc.member_credentials(member_id)):
        if cred["status"] != "SUSPENDED" or not cred.get("suspended_by_cascade"):
            continue
        expires = parse_dt(cred["expires_at"])
        if expires is None or expires <= clock:
            continue
        cred["status"] = "ACTIVE"
        cred["suspended_by_cascade"] = False
        touch(cred)
        restored += 1
    return restored


def revoke_all_credentials(member_id):
    """Member TERMINATE cascade."""
    for cred in ordered(db.credentials, calc.member_credentials(member_id)):
        if cred["status"] != "REVOKED":
            cred["status"] = "REVOKED"
            touch(cred)


# --- hop 2 / hop 3 ---------------------------------------------------------
def revoke_grants(predicate):
    """Cascade hop 2 — no listing version bump on the cascade path."""
    revoked = []
    for grant in ordered(db.grants):
        if grant["status"] in ("REQUESTED", "APPROVED") and predicate(grant):
            grant["status"] = "REVOKED"
            touch(grant)
            revoked.append(grant)
    return revoked


def cancel_future_showings(predicate):
    """Cascade hop 3 — only showings whose window_start is strictly future."""
    clock = now()
    cancelled = []
    for appt in ordered(db.appointments):
        if appt["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if not predicate(appt):
            continue
        start = parse_dt(appt["window_start"])
        if start is None or not (start > clock):
            continue
        appt["status"] = "CANCELLED"
        appt["cancel_reason"] = "ACCESS_LOST"
        touch(appt)
        cancelled.append(appt)
    return cancelled


# --- composite cascades ----------------------------------------------------
def member_suspend_cascade(member):
    member_id = member["id"]
    suspend_active_credentials(member_id)
    revoke_grants(lambda g: g.get("issued_by_member_id") == member_id)
    cancel_future_showings(lambda a: a["showing_member_id"] == member_id)


def lockbox_missing_cascade(lockbox):
    """Lockbox PLACED -> MISSING: placement -> grant -> appointment."""
    lockbox_id = lockbox["id"]
    listing_ids = set()
    for placement in ordered(db.placements):
        if placement["lockbox_id"] != lockbox_id:
            continue
        if placement["placement_status"] in ("PLACED", "REMOVAL_DUE"):
            placement["placement_status"] = "DELINQUENT"
            touch(placement)
            listing_ids.add(placement["listing_id"])
    revoke_grants(lambda g: g["lockbox_id"] == lockbox_id)
    cancel_future_showings(lambda a: a["listing_id"] in listing_ids)


def listing_close_cascade(listing, deadline_dt):
    """Listing CLOSE / WITHDRAW: placement -> grant -> appointment."""
    listing_id = listing["id"]
    for placement in ordered(db.placements):
        if placement["listing_id"] != listing_id:
            continue
        if placement["placement_status"] == "PLACED":
            placement["placement_status"] = "REMOVAL_DUE"
            placement["removal_deadline"] = iso(deadline_dt)
            touch(placement)
    revoke_grants(lambda g: g["listing_id"] == listing_id)
    cancel_future_showings(lambda a: a["listing_id"] == listing_id)
