"""Testimonials and revocable client consent (PRD §3.8).

Two independent dimensions: consent_status (PENDING -> CONSENTED | DECLINED;
CONSENTED -> REVOKED; REVOKED -> CONSENTED) and publish_status
(HIDDEN -> PUBLISHED, only while consent is CONSENTED and the enrollment's
lifecycle is COMPLETED or ACTIVE; revocation compensates by re-hiding).
"""
from flask import Blueprint, request

from auth import authenticate, require_role, require_ownership, body, get_str, get_int
from db import store
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_DUPLICATE_RESOURCE, not_found)
from serializers import testimonial as ser_testimonial, base_row, touch

bp = Blueprint("testimonials", __name__)


def _get_testimonial(tid):
    t = store.testimonials.get(tid)
    if t is None:
        raise not_found("Testimonial not found")
    return t


def _owning_enrollment(t):
    return store.enrollments.get(t["enrollment_id"])


@bp.post("/testimonials")
def create_testimonial():
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    b = body()
    eid = b.get("enrollment_id")
    e = store.enrollments.get(eid) if isinstance(eid, str) else None
    if e is None:
        raise not_found("enrollment_id does not reference an existing enrollment")
    require_ownership(e["client_id"], uid)
    # At most one testimonial per enrollment (priority 15, before shape).
    if any(t["enrollment_id"] == eid for t in store.testimonials.values()):
        raise ApiError(ERR_DUPLICATE_RESOURCE, 409,
                       "An enrollment carries at most one testimonial")
    rating = get_int(b, "outcome_rating")
    body_text = get_str(b, "body_text")
    if rating is None or rating < 1 or rating > 5 or body_text is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: enrollment_id, outcome_rating 1..5, body_text")
    t = base_row()
    t.update({
        "enrollment_id": eid,
        "outcome_rating": rating,
        "body_text": body_text,
        "consent_status": "PENDING",
        "publish_status": "HIDDEN",
    })
    store.testimonials[t["id"]] = t
    return success(ser_testimonial(t)), 201


@bp.get("/testimonials/<tid>")
def get_testimonial(tid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    return success(ser_testimonial(_get_testimonial(tid)))


@bp.get("/testimonials")
def list_testimonials():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.testimonials.values())
    for param in ("enrollment_id", "consent_status", "publish_status"):
        v = request.args.get(param)
        if v is not None:
            rows = [t for t in rows if t[param] == v]
    rows.sort(key=lambda t: (t["created_at"], t["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_testimonial(t) for t in page], meta)


@bp.post("/testimonials/<tid>/consent")
def consent(tid):
    """PENDING -> CONSENTED, and the cyclic edge REVOKED -> CONSENTED
    (publication stays HIDDEN; re-publishing is explicit) (PRD §3.8)."""
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    t = _get_testimonial(tid)
    e = _owning_enrollment(t)
    require_ownership(e["client_id"] if e is not None else None, uid)
    if t["consent_status"] not in ("PENDING", "REVOKED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Consent can only be granted from PENDING or REVOKED")
    t["consent_status"] = "CONSENTED"
    touch(t)
    return success(ser_testimonial(t))


@bp.post("/testimonials/<tid>/decline")
def decline(tid):
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    t = _get_testimonial(tid)
    e = _owning_enrollment(t)
    require_ownership(e["client_id"] if e is not None else None, uid)
    if t["consent_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING testimonial can be declined")
    t["consent_status"] = "DECLINED"
    touch(t)
    return success(ser_testimonial(t))


@bp.post("/testimonials/<tid>/publish")
def publish(tid):
    role, uid = authenticate()
    require_role(role, uid, ("PracticeManager",))
    t = _get_testimonial(tid)
    e = _owning_enrollment(t)
    if t["consent_status"] != "CONSENTED" or t["publish_status"] != "HIDDEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Publishing requires consent CONSENTED and publication HIDDEN")
    if e is None or e["lifecycle_status"] not in ("COMPLETED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only testimonials of COMPLETED or ACTIVE enrollments may be published")
    t["publish_status"] = "PUBLISHED"
    touch(t)
    return success(ser_testimonial(t))


@bp.post("/testimonials/<tid>/revoke-consent")
def revoke_consent(tid):
    """CONSENTED -> REVOKED; publication compensates to HIDDEN (PRD §3.8)."""
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    t = _get_testimonial(tid)
    e = _owning_enrollment(t)
    require_ownership(e["client_id"] if e is not None else None, uid)
    if t["consent_status"] != "CONSENTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a CONSENTED testimonial can be revoked")
    t["consent_status"] = "REVOKED"
    t["publish_status"] = "HIDDEN"
    touch(t)
    return success(ser_testimonial(t))
