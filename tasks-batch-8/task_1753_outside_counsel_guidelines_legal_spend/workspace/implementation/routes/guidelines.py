"""GuidelineVersion + GuidelineAcknowledgment endpoints."""

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER

bp = Blueprint("guidelines", __name__)


@bp.route("/legal-departments/<deptId>/guideline-versions", methods=["POST"])
def create_guideline_version(deptId):
    require_auth([ROLE_LEGAL_OPS])
    helpers.resolve_department(deptId)
    body = helpers.get_body()
    helpers.require_fields(body, ["version_label", "effective_date"])
    rec = db.base_resource({
        "legal_department_id": deptId,
        "version_label": body["version_label"],
        "effective_date": body["effective_date"],
        "status": "DRAFT",
        "published_at": None,
    })
    db.guideline_versions[rec["id"]] = rec
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/guideline-versions/<gvId>", methods=["GET"])
def get_guideline_version(deptId, gvId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, gv = helpers.resolve_guideline_version(deptId, gvId)
    return resp.success_object(resp.public(gv))


@bp.route("/legal-departments/<deptId>/guideline-versions", methods=["GET"])
def list_guideline_versions(deptId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_department(deptId)
    limit, offset = resp.parse_pagination(request.args)
    records = [g for g in db.guideline_versions.values() if g.get("legal_department_id") == deptId]
    records = helpers.apply_filters(records, request.args, ["status"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/guideline-versions/<gvId>/publish", methods=["POST"])
def publish_guideline_version(deptId, gvId):
    require_auth([ROLE_LEGAL_OPS])
    dept, gv = helpers.resolve_guideline_version(deptId, gvId)
    if gv.get("status") != "DRAFT":
        raise errors.invalid_state()

    effective = db.parse_iso(gv.get("effective_date"))
    # Temporal guard: effective_date must not lie in the past.
    if effective is not None and effective < db.get_clock():
        raise errors.invalid_temporal()

    prior_published = [
        g for g in db.guideline_versions.values()
        if g.get("legal_department_id") == deptId
        and g.get("status") == "PUBLISHED"
        and g.get("id") != gvId
    ]
    # Overlap guard: no other PUBLISHED version with effective_date >= this one.
    for other in prior_published:
        other_eff = db.parse_iso(other.get("effective_date"))
        if other_eff is not None and effective is not None and other_eff >= effective:
            raise errors.guideline_overlap()
    # Notice-gap guard against the currently-published version (if any).
    if prior_published:
        # The most recently effective published version is "the prior version".
        prior = max(prior_published, key=lambda g: db.parse_iso(g.get("effective_date")) or db.get_clock())
        prior_eff = db.parse_iso(prior.get("effective_date"))
        if prior_eff is not None and effective is not None:
            from datetime import timedelta
            gap_days = int(dept.get("guideline_notice_days", 0))
            if effective - prior_eff < timedelta(days=gap_days):
                raise errors.notice_gap()

    gv["status"] = "PUBLISHED"
    gv["published_at"] = db.now_iso()
    db.touch(gv)

    # Supersede the previously published version.
    for other in prior_published:
        other["status"] = "SUPERSEDED"
        db.touch(other)

    # Cascade-create PENDING acknowledgments for every ACTIVE firm.
    for firm in db.panel_firms.values():
        if firm.get("legal_department_id") == deptId and firm.get("status") == "ACTIVE":
            ack = db.base_resource({
                "panel_firm_id": firm["id"],
                "guideline_version_id": gvId,
                "status": "PENDING",
                "acknowledged_at": None,
            })
            db.guideline_acknowledgments[ack["id"]] = ack

    return resp.success_object(resp.public(gv))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/acknowledgments/<ackId>", methods=["GET"])
def get_acknowledgment(deptId, firmId, ackId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, ack = helpers.resolve_acknowledgment(deptId, firmId, ackId)
    return resp.success_object(resp.public(ack))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/acknowledgments", methods=["GET"])
def list_acknowledgments(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_firm(deptId, firmId)
    limit, offset = resp.parse_pagination(request.args)
    records = [a for a in db.guideline_acknowledgments.values() if a.get("panel_firm_id") == firmId]
    records = helpers.apply_filters(records, request.args, ["status", "guideline_version_id"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/acknowledgments/<ackId>/acknowledge", methods=["POST"])
def acknowledge(deptId, firmId, ackId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, _, ack = helpers.resolve_acknowledgment(deptId, firmId, ackId)
    if user_id != ack.get("panel_firm_id"):
        raise errors.firm_mismatch()
    if ack.get("status") not in ("PENDING", "OVERDUE"):
        raise errors.invalid_state()
    ack["status"] = "ACKNOWLEDGED"
    ack["acknowledged_at"] = db.now_iso()
    db.touch(ack)
    return resp.success_object(resp.public(ack))
