"""Entity construction, common-field stamping, and serialization (PRD §2.4)."""
from datetime import timedelta

from clock import clock, to_iso_z
from db import new_id
import calc

# Entities that carry full common fields (id, created_at, updated_at, version).
# Waiver and Enrollment carry only id + created_at (PRD §2.4).
LIGHT_ENTITIES = {"Waiver", "Enrollment"}


def stamp_create(record, kind, versioned=True):
    """Add common fields at creation. version stored separately on the record itself
    when the entity owns a version field per scaffold; here common 'version' applies
    to the full-common-field entities except where the entity already manages it."""
    now = clock.now()
    record["id"] = new_id()
    record["_created_at"] = now
    if kind not in LIGHT_ENTITIES:
        record["_updated_at"] = now
    return record


def touch(record, kind):
    """Refresh updated_at on mutation for full-common-field entities."""
    if kind not in LIGHT_ENTITIES:
        record["_updated_at"] = clock.now()


# ---------------------------------------------------------------------------
# Serializers — each returns the public JSON dict for a stored record.
# ---------------------------------------------------------------------------

def _common(record, kind):
    out = {
        "id": record["id"],
        "created_at": to_iso_z(record["_created_at"]),
    }
    if kind not in LIGHT_ENTITIES:
        out["updated_at"] = to_iso_z(record["_updated_at"])
        # version is present only on entities whose scaffold field list declares it.
        if "version" in record:
            out["version"] = record["version"]
    return out


def serialize_member(m):
    # Member carries id/created_at/updated_at but no version field in the scaffold.
    out = _common(m, "Member")
    out.update({
        "full_name": m["full_name"],
        "email": m["email"],
        "date_of_birth": m["date_of_birth_raw"],
        "is_youth": m["is_youth"],
        "wallet_credit_cents": m["wallet_credit_cents"],
        "status": m["status"],
    })
    return out


def waiver_status(w):
    return "VALID" if clock.now() < w["expires_at"] else "EXPIRED"


def serialize_waiver(w):
    out = _common(w, "Waiver")
    out.update({
        "member_id": w["member_id"],
        "signed_at": to_iso_z(w["signed_at"]),
        "expires_at": to_iso_z(w["expires_at"]),
        "minor_guardian_name": w.get("minor_guardian_name"),
        "status": waiver_status(w),
    })
    return out


def serialize_membership(m):
    out = _common(m, "Membership")
    out.update({
        "member_id": m["member_id"],
        "plan_tier": m["plan_tier"],
        "monthly_fee_cents": m["monthly_fee_cents"],
        "cycle_start": to_iso_z(m["cycle_start"]),
        "cycle_end": to_iso_z(m["cycle_end"]),
        "billing_status": m["billing_status"],
        "access_status": m["access_status"],
        "past_due_since": to_iso_z(m["past_due_since"]) if m["past_due_since"] else None,
        "frozen_at": to_iso_z(m["frozen_at"]) if m["frozen_at"] else None,
    })
    return out


def serialize_certification(c):
    out = _common(c, "Certification")
    out.update({
        "member_id": c["member_id"],
        "discipline": c["discipline"],
        "status": c["status"],
        "weighted_score": c["weighted_score"],
        "min_station_score": c["min_station_score"],
        "passed_at": to_iso_z(c["passed_at"]) if c["passed_at"] else None,
        "expires_at": to_iso_z(c["expires_at"]) if c["expires_at"] else None,
        "examiner_user_id": c["examiner_user_id"],
    })
    return out


def serialize_facility(f):
    out = _common(f, "Facility")
    out.update({
        "name": f["name"],
        "floor_capacity": f["floor_capacity"],
        "occupancy": f["occupancy"],
        "requires_belay_cert": f["requires_belay_cert"],
    })
    return out


def serialize_route(r):
    out = _common(r, "Route")
    out.update({
        "facility_id": r["facility_id"],
        "setter_user_id": r["setter_user_id"],
        "grade": r["grade"],
        "style": r["style"],
        "difficulty_points": r["difficulty_points"],
        "status": r["status"],
        "set_on": to_iso_z(r["set_on"]),
    })
    return out


def serialize_check_in(c):
    out = _common(c, "CheckIn")
    out.update({
        "member_id": c["member_id"],
        "facility_id": c["facility_id"],
        "entry_kind": c["entry_kind"],
        "gear_bundle": c["gear_bundle"],
        "price_cents": c["price_cents"],
        "status": c["status"],
        "checked_in_at": to_iso_z(c["checked_in_at"]),
        "checked_out_at": to_iso_z(c["checked_out_at"]) if c["checked_out_at"] else None,
    })
    return out


def serialize_clinic(c):
    out = _common(c, "Clinic")
    out.update({
        "title": c["title"],
        "starts_at": to_iso_z(c["starts_at"]),
        "ends_at": to_iso_z(c["ends_at"]),
        "seat_capacity": c["seat_capacity"],
        "enrolled_count": c["enrolled_count"],
        "status": c["status"],
    })
    return out


def serialize_enrollment(e):
    out = _common(e, "Enrollment")
    out.update({
        "clinic_id": e["clinic_id"],
        "member_id": e["member_id"],
        "status": e["status"],
    })
    return out


def serialize_rental(r):
    out = _common(r, "Rental")
    out.update({
        "member_id": r["member_id"],
        "item_kind": r["item_kind"],
        "deposit_cents": r["deposit_cents"],
        "rented_at": to_iso_z(r["rented_at"]),
        "due_at": to_iso_z(r["due_at"]),
        "returned_at": to_iso_z(r["returned_at"]) if r["returned_at"] else None,
        "late_fee_cents": r["late_fee_cents"],
        "refund_cents": r["refund_cents"],
        "status": r["status"],
    })
    return out


def serialize_incident(i):
    out = _common(i, "Incident")
    out.update({
        "member_id": i["member_id"],
        "facility_id": i["facility_id"],
        "certification_id": i.get("certification_id"),
        "severity": i["severity"],
        "description": i["description"],
        "status": i["status"],
        "reported_at": to_iso_z(i["reported_at"]),
    })
    return out
