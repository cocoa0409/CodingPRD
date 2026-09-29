"""Advertising disclosure review and publication (PRD 3.8)."""
from flask import Blueprint, g

import serializers
from db import create, db, touch
from errors import ApiError
from middleware import (ALL_ROLES, endpoint, identity_from_body, require_identity)
from response import created, ok, paginated
from routes.common import filters, gate, get_or_404, get_referenced, listing, matches
from services import audit, authority
from validators import Body, STATE_RE, body_fk, raw_body

bp = Blueprint("ads", __name__)

MEDIA = ("WEB", "PRINT", "SOCIAL", "DIRECT_MAIL", "RADIO")
DECISIONS = ("APPROVE", "REJECT")


@bp.route("/advertisements", methods=["POST"])
@endpoint("Originator")
def draft_ad():
    raw = raw_body()
    identity_from_body(raw, "originator_id")
    originator_ref = body_fk(raw, "originator_id")
    originator = None
    if originator_ref is not None:
        originator = get_referenced(db.originators, originator_ref)
    body = Body(raw)
    body.string("originator_id")
    medium = body.enum("medium", MEDIA)
    content_text = body.string("content_text", min_len=10, max_len=4000)
    target_state_codes = body.str_array("target_state_codes", min_items=1, max_items=10,
                                        pattern=STATE_RE)
    disclosed_nmls_ids = body.str_array("disclosed_nmls_ids", required=False, default=[])
    disclosed_license_numbers = body.str_array("disclosed_license_numbers", required=False,
                                               default=[])
    row = create(db.advertisements, {
        "originator_id": originator["id"],
        "medium": medium,
        "content_text": content_text,
        "disclosed_nmls_ids": list(disclosed_nmls_ids),
        "disclosed_license_numbers": list(disclosed_license_numbers),
        "target_state_codes": list(target_state_codes),
        "status": "DRAFT",
        "disclosure_findings": [],
        "reviewed_by_user_id": None,
        "published_at": None,
    })
    return created(serializers.advertisement(row))


@bp.route("/advertisements", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_ads():
    active = filters("originator_id", "status")
    rows = listing(db.advertisements, lambda r: matches(r, active))
    return paginated(rows, serializers.advertisement)


@bp.route("/advertisements/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_ad(row_id):
    row = get_or_404(db.advertisements, row_id)
    return ok(serializers.advertisement(row))


@bp.route("/advertisements/<row_id>/submissions", methods=["POST"])
@endpoint("Originator")
def submit_ad(row_id):
    ad = get_or_404(db.advertisements, row_id)
    require_identity(ad["originator_id"])
    gate("Advertisement", ad, ("DRAFT",))
    ad["status"] = "SUBMITTED"
    ad["disclosure_findings"] = authority.disclosure_findings(ad)
    touch(ad)
    return ok(serializers.advertisement(ad))


@bp.route("/advertisements/<row_id>/reviews", methods=["POST"])
@endpoint("ComplianceOfficer")
def review_ad(row_id):
    ad = get_or_404(db.advertisements, row_id)
    body = Body(raw_body())
    decision = body.enum("decision", DECISIONS)
    note = body.string("note", required=False, default=None, max_len=2000)
    gate("Advertisement", ad, ("SUBMITTED",))

    # The inspection is re-run as part of the review either way.
    ad["disclosure_findings"] = authority.disclosure_findings(ad)
    if decision == "APPROVE" and ad["disclosure_findings"]:
        raise ApiError("ERR_AD_DISCLOSURE_INCOMPLETE")
    ad["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    ad["reviewed_by_user_id"] = g.user_id
    touch(ad)
    detail = {"decision": decision, "status": ad["status"],
              "disclosure_findings": list(ad["disclosure_findings"])}
    if note is not None:
        detail["note"] = note
    audit.append("Advertisement", ad["id"], "AD_DECIDED", detail)
    return ok(serializers.advertisement(ad))


@bp.route("/advertisements/<row_id>/revisions", methods=["POST"])
@endpoint("Originator")
def revise_ad(row_id):
    ad = get_or_404(db.advertisements, row_id)
    require_identity(ad["originator_id"])
    body = Body(raw_body())
    content_text = body.string("content_text", min_len=10, max_len=4000)
    disclosed_nmls_ids = body.str_array("disclosed_nmls_ids", required=False, default=None)
    disclosed_license_numbers = body.str_array("disclosed_license_numbers", required=False,
                                               default=None)
    gate("Advertisement", ad, ("REJECTED",))
    ad["status"] = "DRAFT"
    ad["content_text"] = content_text
    if disclosed_nmls_ids is not None:
        ad["disclosed_nmls_ids"] = list(disclosed_nmls_ids)
    if disclosed_license_numbers is not None:
        ad["disclosed_license_numbers"] = list(disclosed_license_numbers)
    # The inspection will run again at the next submission.
    ad["disclosure_findings"] = []
    ad["reviewed_by_user_id"] = None
    touch(ad)
    return ok(serializers.advertisement(ad))


@bp.route("/advertisements/<row_id>/publish", methods=["POST"])
@endpoint("Originator")
def publish_ad(row_id):
    ad = get_or_404(db.advertisements, row_id)
    require_identity(ad["originator_id"])
    gate("Advertisement", ad, ("APPROVED",))
    # Priority 14 is evaluated ahead of priority 22.
    failure = authority.publish_authority_probe(ad)
    if failure is not None:
        raise ApiError(failure)
    ad["disclosure_findings"] = authority.disclosure_findings(ad)
    if ad["disclosure_findings"]:
        raise ApiError("ERR_AD_DISCLOSURE_INCOMPLETE")
    ad["status"] = "PUBLISHED"
    ad["published_at"] = db.clock
    touch(ad)
    return ok(serializers.advertisement(ad))


@bp.route("/advertisements/<row_id>/withdraw", methods=["POST"])
@endpoint("ComplianceOfficer")
def withdraw_ad(row_id):
    ad = get_or_404(db.advertisements, row_id)
    body = Body(raw_body(required=False))
    reason = body.string("reason", required=False, default=None, max_len=2000)
    gate("Advertisement", ad, ("SUBMITTED", "APPROVED", "PUBLISHED"))
    ad["status"] = "WITHDRAWN"
    touch(ad)
    detail = {"status": "WITHDRAWN"}
    if reason is not None:
        detail["reason"] = reason
    audit.append("Advertisement", ad["id"], "AD_DECIDED", detail)
    return ok(serializers.advertisement(ad))
