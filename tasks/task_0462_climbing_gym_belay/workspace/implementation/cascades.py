"""Cascading side effects (PRD §3.2, §3.3, §3.8, §3.9)."""
from clock import clock
from db import db
from helpers import recompute_facility_occupancy, recompute_clinic_count
import models


def auto_check_out_member(member_id):
    """Check out every ON_FLOOR check-in for this member; bump affected facilities."""
    affected_facilities = set()
    for c in db.check_ins.values():
        if c["member_id"] == member_id and c["status"] == "ON_FLOOR":
            c["status"] = "CHECKED_OUT"
            c["checked_out_at"] = clock.now()
            models.touch(c, "CheckIn")
            affected_facilities.add(c["facility_id"])
    for fid in affected_facilities:
        recompute_facility_occupancy(fid)
        f = db.facilities.get(fid)
        if f is not None:
            f["version"] += 1
            models.touch(f, "Facility")


def withdraw_member_enrollments(member_id):
    """Withdraw active (ENROLLED) enrollments for this member; bump affected clinics."""
    affected_clinics = set()
    for e in db.enrollments.values():
        if e["member_id"] == member_id and e["status"] == "ENROLLED":
            e["status"] = "WITHDRAWN"
            affected_clinics.add(e["clinic_id"])
    for cid in affected_clinics:
        recompute_clinic_count(cid)
        c = db.clinics.get(cid)
        if c is not None:
            c["version"] += 1
            models.touch(c, "Clinic")


def serious_incident_cascade(member_id, certification_id):
    """3-hop cascade fired at SERIOUS incident creation (PRD §3.9).

    1. referenced cert (PASSED/EXPIRED) -> REVOKED, version+1
    2. member's ACTIVE/FROZEN membership -> access_status SUSPENDED, version+1
    3. member's ON_FLOOR check-ins -> CHECKED_OUT (occupancy/version recompute)
    """
    # Hop 1: certification revoke (only if a cert was supplied)
    if certification_id:
        cert = db.certifications.get(certification_id)
        if cert is not None and cert["status"] in ("PASSED", "EXPIRED"):
            cert["status"] = "REVOKED"
            cert["version"] += 1
            models.touch(cert, "Certification")

    # Hop 2: membership suspend (ACTIVE or FROZEN -> SUSPENDED)
    for m in db.memberships.values():
        if m["member_id"] == member_id and m["access_status"] in ("ACTIVE", "FROZEN"):
            m["access_status"] = "SUSPENDED"
            m["version"] += 1
            models.touch(m, "Membership")

    # Hop 3: auto check-out
    auto_check_out_member(member_id)
