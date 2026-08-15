"""Provider site endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db
from errors import invalid_state, ApiError, ERR_OPEN_EXCURSION_EXISTS, ERR_OPEN_BORROW_TICKET_EXISTS, ERR_OPEN_AUDIT_EXISTS
from middleware import get_auth, ALL_ROLES, ROLE_COMPLIANCE_AUDITOR
from response import success_object, paginate
from services.validate import require_body, require_string, get_or_404

bp = Blueprint("provider_sites", __name__)


def serialize_site(site):
    return {
        "id": site["id"],
        "created_at": site["created_at"],
        "updated_at": site["updated_at"],
        "version": site["version"],
        "site_name": site["site_name"],
        "vfc_pin": site["vfc_pin"],
        "status": site["status"],
        "excursion_count_open": site["excursion_count_open"],
        "accountability_balance_doses": site["accountability_balance_doses"],
        "private_lending_balance": site["private_lending_balance"],
    }


@bp.route("/provider-sites", methods=["POST"])
def create_site():
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    body = require_body(request.get_json(silent=True))
    site_name = require_string(body, "site_name")
    vfc_pin = require_string(body, "vfc_pin")

    now = db.now_ts()
    site = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "site_name": site_name,
        "vfc_pin": vfc_pin,
        "status": "ACTIVE",
        "excursion_count_open": 0,
        "accountability_balance_doses": 0,
        "private_lending_balance": 0,
    }
    db.provider_sites[site["id"]] = site
    return success_object(serialize_site(site), 201)


@bp.route("/provider-sites", methods=["GET"])
def list_sites():
    get_auth(ALL_ROLES)
    status_filter = request.args.get("status")
    items = list(db.provider_sites.values())
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return paginate([serialize_site(s) for s in items], request.args)


@bp.route("/provider-sites/<site_id>", methods=["GET"])
def get_site(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    return success_object(serialize_site(site))


def _bump(site):
    site["updated_at"] = db.now_ts()
    site["version"] += 1


@bp.route("/provider-sites/<site_id>/suspend-ordering", methods=["POST"])
def suspend_ordering(site_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    if site["status"] != "ACTIVE":
        raise invalid_state("Site must be ACTIVE to suspend ordering")
    site["status"] = "SUSPENDED_ORDERING"
    _bump(site)
    return success_object(serialize_site(site))


@bp.route("/provider-sites/<site_id>/reinstate-ordering", methods=["POST"])
def reinstate_ordering(site_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    if site["status"] != "SUSPENDED_ORDERING":
        raise invalid_state("Site must be SUSPENDED_ORDERING to reinstate ordering")
    site["status"] = "ACTIVE"
    _bump(site)
    return success_object(serialize_site(site))


@bp.route("/provider-sites/<site_id>/terminate", methods=["POST"])
def terminate_site(site_id):
    get_auth([ROLE_COMPLIANCE_AUDITOR])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    if site["status"] not in ("ACTIVE", "SUSPENDED_ORDERING"):
        raise invalid_state("Site must be ACTIVE or SUSPENDED_ORDERING to terminate")

    # Blocking conditions evaluated in PRD §3.1 order: excursion, borrow ticket, audit.
    unit_ids = {u["id"] for u in db.storage_units.values() if u["provider_site_id"] == site_id}
    for e in db.temperature_excursions.values():
        if e["storage_unit_id"] in unit_ids and e["status"] in ("OPEN", "UNDER_REVIEW"):
            raise ApiError(ERR_OPEN_EXCURSION_EXISTS,
                           "An OPEN or UNDER_REVIEW TemperatureExcursion blocks termination", 409)
    for bt in db.borrow_tickets.values():
        if bt["provider_site_id"] == site_id and bt["status"] in ("OPEN", "PARTIALLY_REPAID"):
            raise ApiError(ERR_OPEN_BORROW_TICKET_EXISTS,
                           "An OPEN or PARTIALLY_REPAID BorrowTicket blocks termination", 409)
    for a in db.site_visit_audits.values():
        if a["provider_site_id"] == site_id and a["status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError(ERR_OPEN_AUDIT_EXISTS,
                           "A SCHEDULED or IN_PROGRESS SiteVisitAudit blocks termination", 409)

    # Cascade: all AVAILABLE lots -> WASTED_CLOSED, quantity zeroed.
    for lot in db.lots.values():
        if lot["provider_site_id"] == site_id and lot["status"] == "AVAILABLE":
            lot["status"] = "WASTED_CLOSED"
            lot["quantity_on_hand"] = 0
            lot["updated_at"] = db.now_ts()
            lot["version"] += 1

    site["status"] = "TERMINATED"
    _bump(site)
    return success_object(serialize_site(site))
