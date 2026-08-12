from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_DOCUMENT_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_DOCUMENT_INVALID_STATE, ERR_RESCISSION_WINDOW_LAPSED, ERR_LEASE_NOT_FOUND,
)
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.calc import compute_pricing
from services.common import touch
from timeutil import parse_date, clock_date, add_months

bp = Blueprint("documents", __name__)


def _serialize(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "offer_id": d["offer_id"],
        "lease_id": d["lease_id"],
        "status": d["status"],
        "executed_rent_cents": d.get("executed_rent_cents"),
        "countersigned_on_date": d.get("countersigned_on_date"),
        "rescind_deadline_date": d.get("rescind_deadline_date"),
        "prior_lease_status": d.get("prior_lease_status"),
        "prior_monthly_rent_cents": d.get("prior_monthly_rent_cents"),
        "prior_term_start_date": d.get("prior_term_start_date"),
        "prior_term_end_date": d.get("prior_term_end_date"),
        "prior_term_months": d.get("prior_term_months"),
    }


def _get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


@bp.route("/renewal-documents", methods=["GET"])
def list_documents():
    user_id, role = get_auth()
    if role not in ("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent", "Resident"):
        from errors import ERR_FORBIDDEN_ROLE
        raise_err(ERR_FORBIDDEN_ROLE, "forbidden")
    limit, offset = _get_pagination()
    offer_id = request.args.get("offer_id")
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    items = list(store.renewal_documents.values())
    if role == "Resident":
        items = [d for d in items
                 if store.leases.get(d["lease_id"]) and
                 store.leases[d["lease_id"]]["resident_id"] == user_id]
    if offer_id:
        items = [d for d in items if d["offer_id"] == offer_id]
    if lease_id:
        items = [d for d in items if d["lease_id"] == lease_id]
    if status:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(d) for d in page], limit, offset, total)


@bp.route("/renewal-documents/<did>", methods=["GET"])
def get_document(did):
    user_id, role = get_auth()
    if role not in ("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent", "Resident"):
        from errors import ERR_FORBIDDEN_ROLE
        raise_err(ERR_FORBIDDEN_ROLE, "forbidden")
    d = store.renewal_documents.get(did)
    if d is None:
        raise_err(ERR_DOCUMENT_NOT_FOUND, "document not found")
    if role == "Resident":
        lease = store.leases.get(d["lease_id"])
        if lease is None or lease["resident_id"] != user_id:
            raise_err(ERR_NOT_RESOURCE_OWNER, "not owner")
    return success_object(_serialize(d))


@bp.route("/renewal-documents/<did>/sign-resident", methods=["POST"])
def sign_resident(did):
    user_id, role = require_roles("Resident")
    d = store.renewal_documents.get(did)
    if d is None:
        raise_err(ERR_DOCUMENT_NOT_FOUND, "document not found")
    lease = store.leases.get(d["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")
    if lease["resident_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "not owner")
    if d["status"] != "GENERATED":
        raise_err(ERR_DOCUMENT_INVALID_STATE, "document not GENERATED")
    d["status"] = "RESIDENT_SIGNED"
    touch(d)
    return success_object(_serialize(d))


@bp.route("/renewal-documents/<did>/countersign", methods=["POST"])
def countersign(did):
    user_id, role = require_roles("PropertyManager", "RegionalDirector")
    d = store.renewal_documents.get(did)
    if d is None:
        raise_err(ERR_DOCUMENT_NOT_FOUND, "document not found")
    lease = store.leases.get(d["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")
    if d["status"] != "RESIDENT_SIGNED":
        raise_err(ERR_DOCUMENT_INVALID_STATE, "document not RESIDENT_SIGNED")
    if lease["status"] == "ENDED":
        raise_err(ERR_DOCUMENT_INVALID_STATE, "lease ENDED")

    offer = store.renewal_offers.get(d["offer_id"])
    prop = store.properties.get(lease["property_id"])
    policy = store.rent_cap_policies.get(prop["rent_cap_policy_id"]) if prop else None
    unit = store.units.get(lease["unit_id"])

    # Final-variant pricing recompute
    executed_rent, _ = compute_pricing(
        lease["monthly_rent_cents"],
        unit["current_market_rent_cents"],
        offer["offered_term_months"],
        offer["rate_strategy"],
        policy["effective_cap_bps"],
    )

    now = clock_date()

    # Capture snapshot BEFORE mutating lease
    prior_status = lease.get("status_before_offer") if lease.get("status_before_offer") else lease["status"]
    d["prior_lease_status"] = prior_status
    d["prior_monthly_rent_cents"] = lease["monthly_rent_cents"]
    d["prior_term_start_date"] = lease["term_start_date"]
    d["prior_term_end_date"] = lease["term_end_date"]
    d["prior_term_months"] = lease["term_months"]
    d["executed_rent_cents"] = executed_rent
    d["countersigned_on_date"] = now.strftime("%Y-%m-%d")
    d["rescind_deadline_date"] = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    d["status"] = "COUNTERSIGNED"
    touch(d)

    # Offer ACCEPTED -> EXECUTED
    if offer is not None and offer["status"] == "ACCEPTED":
        offer["status"] = "EXECUTED"
        offer["executed_rent_cents"] = executed_rent
        touch(offer)

    # Renew lease
    old_term_end = parse_date(lease["term_end_date"])
    new_start = max(old_term_end, now)
    new_months = offer["offered_term_months"] if offer else lease["term_months"]
    new_end = add_months(new_start, new_months)
    lease["monthly_rent_cents"] = executed_rent
    lease["term_start_date"] = new_start.strftime("%Y-%m-%d")
    lease["term_months"] = new_months
    lease["term_end_date"] = new_end.strftime("%Y-%m-%d")
    lease["status"] = "ACTIVE"
    lease["status_before_offer"] = None
    touch(lease)

    return success_object(_serialize(d))


@bp.route("/renewal-documents/<did>/rescind", methods=["POST"])
def rescind_document(did):
    user_id, role = require_roles("Resident")
    d = store.renewal_documents.get(did)
    if d is None:
        raise_err(ERR_DOCUMENT_NOT_FOUND, "document not found")
    lease = store.leases.get(d["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")
    if lease["resident_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "not owner")
    if d["status"] != "COUNTERSIGNED":
        raise_err(ERR_DOCUMENT_INVALID_STATE, "document not COUNTERSIGNED")
    now = clock_date()
    if now > parse_date(d["rescind_deadline_date"]):
        raise_err(ERR_RESCISSION_WINDOW_LAPSED, "rescission window lapsed")

    # Restore lease from snapshot
    lease["monthly_rent_cents"] = d["prior_monthly_rent_cents"]
    lease["term_start_date"] = d["prior_term_start_date"]
    lease["term_end_date"] = d["prior_term_end_date"]
    lease["term_months"] = d["prior_term_months"]
    lease["status"] = d["prior_lease_status"]
    lease["status_before_offer"] = None
    touch(lease)

    # Offer EXECUTED -> VOIDED
    offer = store.renewal_offers.get(d["offer_id"])
    if offer is not None and offer["status"] == "EXECUTED":
        offer["status"] = "VOIDED"
        touch(offer)

    d["status"] = "RESCINDED"
    touch(d)
    return success_object(_serialize(d))
