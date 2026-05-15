"""Qualification document upload + reviewer decision."""
from flask import Blueprint

from .. import store
from ..auth import require_auth
from ..errors import ApiError
from ..response import success
from ..validators import get_json_body, require_fields, require_enum, require_non_empty_string
from ..services.paths import resolve_advertiser, resolve_qualification
from ..services.qualification import (
    recompute_qualification_status,
    maybe_activate_advertiser,
    cascade_reject_creatives_on_qual_rejected,
)
from ..services.lifecycle import suspend_advertiser_cascade


bp = Blueprint("qualifications", __name__)


DOC_TYPES = ["BUSINESS_LICENSE", "MEDICAL_PERMIT", "FINANCIAL_LICENSE", "EDUCATION_PERMIT"]


@bp.post("/advertisers/<advertiser_id>/qualifications")
@require_auth(["AccountOwner", "PlatformAdmin"])
def upload_qualification(advertiser_id):
    adv = resolve_advertiser(advertiser_id)
    body = get_json_body()
    require_fields(body, ["doc_type", "doc_url", "expiry_date"])
    doc_type = require_enum(body, "doc_type", DOC_TYPES)

    rec = {
        "id": store.gen_uuid(),
        "advertiser_id": advertiser_id,
        "doc_type": doc_type,
        "doc_url": body["doc_url"],
        "expiry_date": body["expiry_date"],
        "review_status": "PENDING",
        "rejection_reason": None,
    }
    store.stamp_common(rec, with_version=False)
    store.insert("QualificationDoc", rec)

    if adv.get("qualification_status") in ("UNVERIFIED",):
        adv["qualification_status"] = "UNDER_REVIEW"
    else:
        recompute_qualification_status(adv)
    store.touch(adv)
    return success(rec, status=201)


@bp.post("/advertisers/<advertiser_id>/qualifications/<doc_id>/review")
@require_auth(["PlatformAdmin"])
def review_qualification(advertiser_id, doc_id):
    adv, doc = resolve_qualification(advertiser_id, doc_id)
    if doc.get("review_status") != "PENDING":
        raise ApiError("ERR_INVALID_REQUEST", "Document already decided.")

    body = get_json_body()
    outcome = require_enum(body, "outcome", ["APPROVE", "REJECT"])

    prev_qual = adv.get("qualification_status")
    # An advertiser in ACTIVE / SUSPENDED status was previously VERIFIED
    # (the only path to ACTIVE per PRD §3.1 is first-time qualification
    # VERIFIED with funded balance). This signals "prior VERIFIED" for
    # the cascade trigger, even if a new PENDING doc temporarily flipped
    # the qualification_status to UNDER_REVIEW prior to this review.
    was_ever_verified = (
        prev_qual == "VERIFIED"
        or adv.get("status") in ("ACTIVE", "SUSPENDED")
    )

    if outcome == "APPROVE":
        doc["review_status"] = "APPROVED"
    else:
        require_non_empty_string(body, "rejection_reason")
        doc["review_status"] = "REJECTED"
        doc["rejection_reason"] = body["rejection_reason"]

    new_qual = recompute_qualification_status(adv)
    store.touch(adv)

    # Side effects on transitions.
    if new_qual == "VERIFIED":
        maybe_activate_advertiser(adv)
    elif new_qual == "REJECTED" and was_ever_verified:
        cascade_reject_creatives_on_qual_rejected(adv)
        if adv.get("status") == "ACTIVE":
            suspend_advertiser_cascade(adv)

    return success(doc)
