"""Site visit audits (PRD §3.9)."""

from flask import Blueprint, request

import db
from errors import (
    invalid_state, ApiError,
    ERR_ACCOUNTABILITY_GAP_UNRESOLVED, ERR_OPEN_EXCURSION_EXISTS,
    ERR_OPEN_BORROW_TICKET_EXISTS,
)
from middleware import get_auth, ALL_ROLES, ROLE_COMPLIANCE_AUDITOR
from response import success_object, paginate
from services.ledger import compute_audit_snapshot, compute_wastage_rate
from services.validate import require_body, require_date, get_or_404

bp = Blueprint("audits", __name__)


def serialize_audit(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "provider_site_id": a["provider_site_id"],
        "visit_date": a["visit_date"],
        "conducted_by_user_id": a["conducted_by_user_id"],
        "status": a["status"],
        "public_doses_received": a["public_doses_received"],
        "public_doses_administered": a["public_doses_administered"],
        "public_doses_wasted": a["public_doses_wasted"],
        "public_doses_transferred_out": a["public_doses_transferred_out"],
        "accountability_gap": a["accountability_gap"],
        "on_hand_public_total": a["on_hand_public_total"],
        "wastage_rate": a["wastage_rate"],
        "wastage_tier": a["wastage_tier"],
    }


@bp.route("/provider-sites/<site_id>/site-visit-audits", methods=["POST"])
def create_audit(site_id):
    user_id = get_auth([ROLE_COMPLIANCE_AUDITOR])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    visit_date_raw, _ = require_date(body, "visit_date")

    now = db.now_ts()
    audit = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "visit_date": visit_date_raw,
        "conducted_by_user_id": user_id,
        "status": "SCHEDULED",
        "public_doses_received": None,
        "public_doses_administered": None,
        "public_doses_wasted": None,
        "public_doses_transferred_out": None,
        "accountability_gap": None,
        "on_hand_public_total": None,
        "wastage_rate": None,
        "wastage_tier": None,
    }
    db.site_visit_audits[audit["id"]] = audit
    return success_object(serialize_audit(audit), 201)


def _filter_audits(items, args):
    f_site = args.get("provider_site_id")
    f_status = args.get("status")
    if f_site is not None:
        items = [a for a in items if a["provider_site_id"] == f_site]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return items


@bp.route("/provider-sites/<site_id>/site-visit-audits", methods=["GET"])
def list_audits(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [a for a in db.site_visit_audits.values() if a["provider_site_id"] == site["id"]]
    items = _filter_audits(items, request.args)
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return paginate([serialize_audit(a) for a in items], request.args)


@bp.route("/site-visit-audits", methods=["GET"])
def list_audits_global():
    get_auth(ALL_ROLES)
    items = list(db.site_visit_audits.values())
    items = _filter_audits(items, request.args)
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return paginate([serialize_audit(a) for a in items], request.args)


@bp.route("/site-visit-audits/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    get_auth(ALL_ROLES)
    audit = get_or_404(db.site_visit_audits, audit_id, "site visit audit")
    return success_object(serialize_audit(audit))


def _get_site_audit(site_id, audit_id):
    site = get_or_404(db.provider_sites, site_id, "provider site")
    audit = get_or_404(db.site_visit_audits, audit_id, "site visit audit")
    if audit["provider_site_id"] != site["id"]:
        from errors import not_found
        raise not_found("site visit audit")
    return site, audit


def _bump(entity):
    entity["updated_at"] = db.now_ts()
    entity["version"] += 1


@bp.route("/provider-sites/<site_id>/site-visit-audits/<audit_id>/begin", methods=["POST"])
def begin_audit(site_id, audit_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    _, audit = _get_site_audit(site_id, audit_id)
    if audit["status"] != "SCHEDULED":
        raise invalid_state("Audit must be SCHEDULED to begin")
    audit["status"] = "IN_PROGRESS"
    _bump(audit)
    return success_object(serialize_audit(audit))


@bp.route("/provider-sites/<site_id>/site-visit-audits/<audit_id>/issue-findings", methods=["POST"])
def issue_findings(site_id, audit_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    site, audit = _get_site_audit(site_id, audit_id)
    if audit["status"] != "IN_PROGRESS":
        raise invalid_state("Audit must be IN_PROGRESS to issue findings")

    snapshot = compute_audit_snapshot(site["id"])
    audit["public_doses_received"] = snapshot["public_doses_received"]
    audit["public_doses_administered"] = snapshot["public_doses_administered"]
    audit["public_doses_wasted"] = snapshot["public_doses_wasted"]
    audit["public_doses_transferred_out"] = snapshot["public_doses_transferred_out"]
    audit["accountability_gap"] = snapshot["accountability_gap"]
    audit["on_hand_public_total"] = snapshot["on_hand_public_total"]

    rounded_rate, tier = compute_wastage_rate(
        snapshot["public_doses_wasted"], snapshot["public_doses_received"]
    )
    audit["wastage_rate"] = float(rounded_rate)
    audit["wastage_tier"] = tier

    audit["status"] = "FINDINGS_ISSUED"
    _bump(audit)
    return success_object(serialize_audit(audit))


@bp.route("/provider-sites/<site_id>/site-visit-audits/<audit_id>/close-pass", methods=["POST"])
def close_pass(site_id, audit_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    site, audit = _get_site_audit(site_id, audit_id)
    if audit["status"] != "FINDINGS_ISSUED":
        raise invalid_state("Audit must be FINDINGS_ISSUED to close pass")

    # Three conditions in PRD §3.9 order.
    if audit["accountability_gap"] != audit["on_hand_public_total"]:
        raise ApiError(ERR_ACCOUNTABILITY_GAP_UNRESOLVED,
                       "audit accountability_gap != on_hand_public_total at close-pass", 422)

    unit_ids = {u["id"] for u in db.storage_units.values() if u["provider_site_id"] == site_id}
    for e in db.temperature_excursions.values():
        if e["storage_unit_id"] in unit_ids and e["status"] in ("OPEN", "UNDER_REVIEW"):
            raise ApiError(ERR_OPEN_EXCURSION_EXISTS,
                           "An OPEN or UNDER_REVIEW TemperatureExcursion blocks close-pass", 409)

    for bt in db.borrow_tickets.values():
        if bt["provider_site_id"] == site_id and bt["status"] in ("OPEN", "PARTIALLY_REPAID"):
            raise ApiError(ERR_OPEN_BORROW_TICKET_EXISTS,
                           "An OPEN or PARTIALLY_REPAID BorrowTicket blocks close-pass", 409)

    audit["status"] = "CLOSED_PASS"
    _bump(audit)
    return success_object(serialize_audit(audit))


@bp.route("/provider-sites/<site_id>/site-visit-audits/<audit_id>/close-fail", methods=["POST"])
def close_fail(site_id, audit_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    site, audit = _get_site_audit(site_id, audit_id)
    if audit["status"] != "FINDINGS_ISSUED":
        raise invalid_state("Audit must be FINDINGS_ISSUED to close fail")
    audit["status"] = "CLOSED_FAIL"
    _bump(audit)
    # Cascade: site ordering is suspended
    site["status"] = "SUSPENDED_ORDERING"
    _bump(site)
    return success_object(serialize_audit(audit))


@bp.route("/provider-sites/<site_id>/site-visit-audits/<audit_id>/cancel", methods=["POST"])
def cancel_audit(site_id, audit_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    _, audit = _get_site_audit(site_id, audit_id)
    if audit["status"] != "SCHEDULED":
        raise invalid_state("Audit must be SCHEDULED to cancel")
    audit["status"] = "CANCELLED"
    _bump(audit)
    return success_object(serialize_audit(audit))
