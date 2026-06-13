"""Shared entity helpers: common fields, timestamps/versioning, derived-count
reconciliation, audit, time arithmetic (PRD §2.4, §2.8, §3.6).
"""
from datetime import datetime, timedelta, timezone

from db import db, new_id, now_iso
from services.calc import GRACE_DAYS


# --------------------------------------------------------------------------- #
# common fields (PRD §2.4)
# --------------------------------------------------------------------------- #
def stamp_create(record, common_fields=True):
    """Attach id + creation provenance. common_fields=True adds updated_at and
    version (mutable resources); False keeps only id + created_at (immutable:
    VaccinationRecord, AuditEvent)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    if common_fields:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Mutation bump: refresh updated_at and increment version (PRD §2.4).

    Applies to every mutation, including derived-field changes.
    """
    if "version" in record:
        record["version"] = record["version"] + 1
        record["updated_at"] = now_iso()


# --------------------------------------------------------------------------- #
# time arithmetic (PRD §2.10, §3.4, §3.6)
# --------------------------------------------------------------------------- #
def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
    s = value
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, years):
    """Add whole calendar years (PRD §3.4: expires_on = issued_on + term_years).

    Calendar-year addition (e.g. 2026-01-01 + 1yr = 2027-01-01); Feb-29 falls
    back to Feb-28 in a non-leap target year.
    """
    year = dt.year + int(years)
    try:
        return dt.replace(year=year)
    except ValueError:
        # Feb 29 -> Feb 28
        return dt.replace(year=year, day=28)


def days_between_floored(later, earlier):
    """Whole days elapsed from earlier to later, floored (PRD §3.6)."""
    delta = later - earlier
    return delta.days if delta.total_seconds() >= 0 else 0


# --------------------------------------------------------------------------- #
# audit trail (PRD §3.9)
# --------------------------------------------------------------------------- #
def append_audit(subject_entity, subject_id, action, actor_role):
    ev = {
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
    }
    stamp_create(ev, common_fields=False)  # append-only: id + created_at only
    db.audit_events[ev["id"]] = ev
    return ev


# --------------------------------------------------------------------------- #
# derived-count reconciliation (PRD §2.8)
# --------------------------------------------------------------------------- #
def licenses_of_owner(owner_id):
    return [l for l in db.licenses.values() if l["owner_id"] == owner_id]


def licenses_of_kennel(kennel_id):
    return [l for l in db.licenses.values() if l.get("kennel_id") == kennel_id]


def licenses_of_pet(pet_id):
    return [l for l in db.licenses.values() if l["pet_id"] == pet_id]


def recompute_owner_active_license_count(owner_id):
    owner = db.owners.get(owner_id)
    if owner is None:
        return
    count = sum(1 for l in licenses_of_owner(owner_id) if l["status"] == "ACTIVE")
    if owner["active_license_count"] != count:
        owner["active_license_count"] = count
        touch(owner)


def recompute_owner_outstanding_penalty(owner_id):
    """NET reading (PRD §2.8): sum late_penalty_cents over the owner's licenses
    in {EXPIRED, GRACE} AND penalty_paid == false. Sets DELINQUENT iff > 0."""
    owner = db.owners.get(owner_id)
    if owner is None:
        return
    total = sum(
        l["late_penalty_cents"]
        for l in licenses_of_owner(owner_id)
        if l["status"] in ("EXPIRED", "GRACE") and l["penalty_paid"] is False
    )
    new_status = "DELINQUENT" if total > 0 else "ACTIVE"
    changed = owner["outstanding_penalty_cents"] != total or owner["status"] != new_status
    owner["outstanding_penalty_cents"] = total
    owner["status"] = new_status
    if changed:
        touch(owner)


def recompute_kennel_occupied_slots(kennel_id):
    kennel = db.kennels.get(kennel_id)
    if kennel is None:
        return
    count = sum(1 for l in licenses_of_kennel(kennel_id) if l["status"] in ("ACTIVE", "GRACE"))
    if kennel["occupied_slots"] != count:
        kennel["occupied_slots"] = count
        touch(kennel)


# --------------------------------------------------------------------------- #
# rabies-proof helper (PRD §3.3, §3.5)
# --------------------------------------------------------------------------- #
def pet_has_valid_rabies(pet_id):
    """True if the pet has any unexpired RABIES vaccination record vs current_utc."""
    now = db.current_utc
    for vr in db.vaccination_records.values():
        if vr["pet_id"] == pet_id and vr["vaccine_type"] == "RABIES":
            if parse_iso(vr["expires_on"]) > now:
                return True
    return False
