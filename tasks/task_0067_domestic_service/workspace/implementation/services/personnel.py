"""Service personnel and skill certifications business logic."""
from decimal import Decimal

from db import store, iso_to_dt
from errors import (
    ERR_VALIDATION_ERROR, ERR_INVALID_STATE, ERR_HAS_ACTIVE_ASSIGNMENTS,
    ERR_CERT_REQUIREMENTS_NOT_MET, raise_error,
)
from services.utils import stamp_create, stamp_update


VALID_SKILL_TAGS = {"CLEANING", "COOKING", "CHILDCARE", "ELDERCARE"}
VALID_GENDERS = {"MALE", "FEMALE"}


# ---------- skill_tags refresh ----------
def refresh_skill_tags(personnel_id: str):
    """Recompute personnel.skill_tags from ACTIVE SkillCertification rows."""
    p = store.personnel.get(personnel_id)
    if not p:
        return
    active_tags = set()
    for cert in store.certifications.values():
        if cert["personnel_id"] == personnel_id and cert["status"] == "ACTIVE":
            active_tags.add(cert["skill_tag"])
    p["skill_tags"] = sorted(active_tags)


# ---------- tier recompute ----------
def recompute_tier(p: dict):
    rc = int(p.get("rating_count", 0))
    rs = Decimal(str(p.get("rating_score", 0)))
    if rc < 5:
        p["tier"] = "BRONZE"
    elif rs >= Decimal("4.8"):
        p["tier"] = "PLATINUM"
    elif rs >= Decimal("4.5"):
        p["tier"] = "GOLD"
    elif rs >= Decimal("4.0"):
        p["tier"] = "SILVER"
    else:
        p["tier"] = "BRONZE"


def has_active_assignment(personnel_id: str) -> bool:
    blocking = {"DISPATCHED", "ACCEPTED", "IN_PROGRESS"}
    for o in store.orders.values():
        if o.get("assigned_personnel_id") == personnel_id and o.get("status") in blocking:
            return True
    return False


def has_active_cert(personnel_id: str) -> bool:
    for cert in store.certifications.values():
        if cert["personnel_id"] == personnel_id and cert["status"] == "ACTIVE":
            return True
    return False


# ---------- personnel CRUD ----------
def create_personnel(body: dict) -> dict:
    required = ["full_name", "gender", "age", "languages",
                "service_lat", "service_lng", "health_cert_expires_at"]
    for f in required:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")

    gender = body["gender"]
    if gender not in VALID_GENDERS:
        raise_error(ERR_VALIDATION_ERROR, "gender must be MALE or FEMALE")

    try:
        age = int(body["age"])
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION_ERROR, "age must be an integer")
    if age < 18 or age > 70:
        raise_error(ERR_VALIDATION_ERROR, "age must be between 18 and 70 inclusive")

    if not isinstance(body["languages"], list):
        raise_error(ERR_VALIDATION_ERROR, "languages must be an array")

    service_radius = body.get("service_radius_km", 10)
    record = {
        "full_name": body["full_name"],
        "gender": gender,
        "age": age,
        "languages": list(body["languages"]),
        "skill_tags": [],
        "service_lat": float(body["service_lat"]),
        "service_lng": float(body["service_lng"]),
        "service_radius_km": float(service_radius),
        "identity_verified": False,
        "health_cert_expires_at": body["health_cert_expires_at"],
        "status": "PENDING_VERIFICATION",
        "rating_score": 0,
        "rating_count": 0,
        "workload_active_orders": 0,
        "tier": "BRONZE",
        "last_recert_at": None,
    }
    stamp_create(record)
    store.personnel[record["id"]] = record
    return record


def verify_identity(personnel_id: str) -> dict:
    p = store.personnel.get(personnel_id)
    if not p:
        from errors import ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    p["identity_verified"] = True
    stamp_update(p)
    return p


def activate_personnel(personnel_id: str) -> dict:
    p = store.personnel[personnel_id]
    if p["status"] != "PENDING_VERIFICATION":
        raise_error(ERR_INVALID_STATE, "Personnel must be PENDING_VERIFICATION to activate")
    # Preconditions
    if not p.get("identity_verified"):
        raise_error(ERR_INVALID_STATE, "Personnel identity not verified")
    health_dt = iso_to_dt(p.get("health_cert_expires_at"))
    if health_dt is None or health_dt <= store.now():
        raise_error(ERR_INVALID_STATE, "Health certificate not in date")
    if not has_active_cert(personnel_id):
        raise_error(ERR_INVALID_STATE, "No active skill certification")
    p["status"] = "ACTIVE"
    recompute_tier(p)
    stamp_update(p)
    return p


def suspend_personnel(personnel_id: str) -> dict:
    p = store.personnel[personnel_id]
    if p["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Personnel must be ACTIVE to suspend")
    if has_active_assignment(personnel_id):
        raise_error(ERR_HAS_ACTIVE_ASSIGNMENTS, "Personnel has active assignments")
    p["status"] = "SUSPENDED"
    stamp_update(p)
    return p


def reinstate_personnel(personnel_id: str) -> dict:
    p = store.personnel[personnel_id]
    if p["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Personnel must be SUSPENDED to reinstate")
    health_dt = iso_to_dt(p.get("health_cert_expires_at"))
    if health_dt is None or health_dt <= store.now():
        raise_error(ERR_INVALID_STATE, "Health certificate not in date")
    if not has_active_cert(personnel_id):
        raise_error(ERR_INVALID_STATE, "No active skill certification")
    p["status"] = "ACTIVE"
    recompute_tier(p)
    stamp_update(p)
    return p


def disqualify_personnel(personnel_id: str) -> dict:
    p = store.personnel[personnel_id]
    if p["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Personnel must be ACTIVE to disqualify")
    if has_active_assignment(personnel_id):
        raise_error(ERR_HAS_ACTIVE_ASSIGNMENTS, "Personnel has active assignments")
    p["status"] = "DISQUALIFIED"
    # Revoke all linked ACTIVE certifications
    for cert in store.certifications.values():
        if cert["personnel_id"] == personnel_id and cert["status"] == "ACTIVE":
            cert["status"] = "REVOKED"
            stamp_update(cert)
    refresh_skill_tags(personnel_id)
    stamp_update(p)
    return p


# ---------- certifications ----------
def create_certification(body: dict) -> dict:
    required = ["personnel_id", "skill_tag", "training_hours", "expires_at"]
    for f in required:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")
    if body["personnel_id"] not in store.personnel:
        from errors import ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    if body["skill_tag"] not in VALID_SKILL_TAGS:
        raise_error(ERR_VALIDATION_ERROR, "Invalid skill_tag")
    record = {
        "personnel_id": body["personnel_id"],
        "skill_tag": body["skill_tag"],
        "training_hours": float(body["training_hours"]),
        "certified_at": None,
        "expires_at": body["expires_at"],
        "status": "PENDING",
    }
    stamp_create(record)
    store.certifications[record["id"]] = record
    return record


def approve_certification(cert_id: str) -> dict:
    cert = store.certifications[cert_id]
    if cert["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "Certification must be PENDING to approve")
    # Preconditions
    if float(cert.get("training_hours", 0)) < 8:
        raise_error(ERR_CERT_REQUIREMENTS_NOT_MET, "training_hours must be at least 8")
    exp_dt = iso_to_dt(cert.get("expires_at"))
    if exp_dt is None or exp_dt <= store.now():
        raise_error(ERR_CERT_REQUIREMENTS_NOT_MET, "expires_at must be strictly in the future")
    cert["status"] = "ACTIVE"
    cert["certified_at"] = store.now_iso()
    stamp_update(cert)
    refresh_skill_tags(cert["personnel_id"])
    return cert


def revoke_certification(cert_id: str) -> dict:
    cert = store.certifications[cert_id]
    if cert["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Certification must be ACTIVE to revoke")
    cert["status"] = "REVOKED"
    stamp_update(cert)
    refresh_skill_tags(cert["personnel_id"])
    return cert
