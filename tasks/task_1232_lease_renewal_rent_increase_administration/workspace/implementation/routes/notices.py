from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_LEASE_NOT_FOUND, ERR_NOTICE_NOT_FOUND,
    ERR_NOTICE_NOT_DRAFT, ERR_NOTICE_NOT_SERVED, ERR_LEASE_NOT_ISSUABLE,
    ERR_INVALID_EFFECTIVE_DATE, ERR_INSUFFICIENT_NOTICE_LEAD,
    ERR_SEGREGATION_OF_DUTIES, ERR_REPOSITIONING_QUOTA_EXCEEDED,
)
from middleware import require_roles
from response import success_object, success_list
from services.common import new_entity, touch
from services.lifecycle import withdraw_offer_cascade
from timeutil import parse_date, clock_date, quarter_key

bp = Blueprint("notices", __name__)

CAUSE_TYPES = {"LEASE_VIOLATION", "REPEATED_LATE_PAYMENT", "PROPERTY_REPOSITIONING", "OWNER_OCCUPANCY"}


def _serialize(n):
    return {
        "id": n["id"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
        "lease_id": n["lease_id"],
        "cause_type": n["cause_type"],
        "evidence_ref": n.get("evidence_ref"),
        "effective_date": n["effective_date"],
        "served_on_date": n.get("served_on_date"),
        "cure_deadline_date": n.get("cure_deadline_date"),
        "prior_lease_status": n.get("prior_lease_status"),
        "created_by_user_id": n["created_by_user_id"],
        "served_by_user_id": n.get("served_by_user_id"),
        "status": n["status"],
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


@bp.route("/leases/<lease_id>/non-renewal-notices", methods=["POST"])
def create_notice(lease_id):
    user_id, role = require_roles("LeasingAgent", "PropertyManager", "RegionalDirector")
    body = request.get_json(silent=True) or {}
    cause_type = body.get("cause_type")
    effective_date = body.get("effective_date")
    evidence_ref = body.get("evidence_ref")

    if cause_type not in CAUSE_TYPES:
        raise_err(ERR_INVALID_REQUEST, "cause_type invalid")
    if not effective_date or not isinstance(effective_date, str):
        raise_err(ERR_INVALID_REQUEST, "effective_date required")
    try:
        parse_date(effective_date)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "effective_date malformed")
    if cause_type == "LEASE_VIOLATION":
        if not evidence_ref or not isinstance(evidence_ref, str):
            raise_err(ERR_INVALID_REQUEST, "evidence_ref required for LEASE_VIOLATION")
    elif evidence_ref is not None and not isinstance(evidence_ref, str):
        raise_err(ERR_INVALID_REQUEST, "evidence_ref must be string")

    lease = store.leases.get(lease_id)
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")

    rec = new_entity()
    rec.update({
        "lease_id": lease_id,
        "cause_type": cause_type,
        "evidence_ref": evidence_ref,
        "effective_date": effective_date,
        "served_on_date": None,
        "cure_deadline_date": None,
        "prior_lease_status": None,
        "created_by_user_id": user_id,
        "served_by_user_id": None,
        "status": "DRAFT",
    })
    store.non_renewal_notices[rec["id"]] = rec
    return success_object(_serialize(rec), status_code=201)


@bp.route("/non-renewal-notices", methods=["GET"])
def list_notices():
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    limit, offset = _get_pagination()
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")
    items = list(store.non_renewal_notices.values())
    if lease_id:
        items = [n for n in items if n["lease_id"] == lease_id]
    if status:
        items = [n for n in items if n["status"] == status]
    items.sort(key=lambda n: n["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(n) for n in page], limit, offset, total)


@bp.route("/non-renewal-notices/<nid>", methods=["GET"])
def get_notice(nid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    n = store.non_renewal_notices.get(nid)
    if n is None:
        raise_err(ERR_NOTICE_NOT_FOUND, "notice not found")
    return success_object(_serialize(n))


@bp.route("/non-renewal-notices/<nid>/serve", methods=["POST"])
def serve_notice(nid):
    user_id, role = require_roles("PropertyManager", "RegionalDirector")
    n = store.non_renewal_notices.get(nid)
    if n is None:
        raise_err(ERR_NOTICE_NOT_FOUND, "notice not found")

    # State
    if n["status"] != "DRAFT":
        raise_err(ERR_NOTICE_NOT_DRAFT, "notice not DRAFT")

    lease = store.leases.get(n["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")
    prop = store.properties.get(lease["property_id"])
    policy = store.rent_cap_policies.get(prop["rent_cap_policy_id"]) if prop else None

    # Lease must be in {ACTIVE, MTM, RENEWAL_PENDING}
    if lease["status"] not in ("ACTIVE", "MTM", "RENEWAL_PENDING"):
        raise_err(ERR_LEASE_NOT_ISSUABLE, "lease not issuable")

    # effective_date >= lease.term_end_date
    eff = parse_date(n["effective_date"])
    term_end = parse_date(lease["term_end_date"])
    if eff < term_end:
        raise_err(ERR_INVALID_EFFECTIVE_DATE, "effective_date earlier than term_end_date")

    # clock date <= effective_date - non_renewal_notice_days
    now = clock_date()
    lead_deadline = eff - timedelta(days=int(policy["non_renewal_notice_days"]))
    if now > lead_deadline:
        raise_err(ERR_INSUFFICIENT_NOTICE_LEAD, "insufficient notice lead")

    # PRD §2.9 stage 10(e) — segregation of duties
    if user_id == n["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "server must differ from creator")

    # PRD §2.9 stage 10(g) — repositioning quota
    if n["cause_type"] == "PROPERTY_REPOSITIONING":
        eff_q = quarter_key(eff)
        count = 0
        for other in store.non_renewal_notices.values():
            if other["id"] == n["id"]:
                continue
            if other["cause_type"] != "PROPERTY_REPOSITIONING":
                continue
            if other["status"] not in ("SERVED", "CONFIRMED", "ENFORCED"):
                continue
            other_lease = store.leases.get(other["lease_id"])
            if other_lease is None or other_lease["property_id"] != lease["property_id"]:
                continue
            other_eff = parse_date(other["effective_date"])
            if quarter_key(other_eff) == eff_q:
                count += 1
        if count >= 2:
            raise_err(ERR_REPOSITIONING_QUOTA_EXCEEDED, "repositioning quota exceeded")

    # Apply: stamp notice
    n["served_on_date"] = now.strftime("%Y-%m-%d")
    n["cure_deadline_date"] = (now + timedelta(days=10)).strftime("%Y-%m-%d")
    n["served_by_user_id"] = user_id
    n["prior_lease_status"] = lease["status"]
    n["status"] = "SERVED"
    touch(n)

    # Lease -> NON_RENEWAL_NOTICED
    lease["status"] = "NON_RENEWAL_NOTICED"
    touch(lease)

    # Withdraw open offers
    for o in list(store.renewal_offers.values()):
        if o["lease_id"] == lease["id"] and o["status"] in ("DRAFT", "ISSUED", "COUNTERED"):
            withdraw_offer_cascade(o)

    return success_object(_serialize(n))


@bp.route("/non-renewal-notices/<nid>/rescind", methods=["POST"])
def rescind_notice(nid):
    user_id, role = require_roles("PropertyManager", "RegionalDirector")
    n = store.non_renewal_notices.get(nid)
    if n is None:
        raise_err(ERR_NOTICE_NOT_FOUND, "notice not found")
    if n["status"] != "SERVED":
        raise_err(ERR_NOTICE_NOT_SERVED, "notice not SERVED")
    # Cure window check
    now = clock_date()
    cure = parse_date(n["cure_deadline_date"])
    if now > cure:
        # already past cure — sweep should have confirmed; respond as not served
        raise_err(ERR_NOTICE_NOT_SERVED, "cure window lapsed")

    lease = store.leases.get(n["lease_id"])
    if lease is None:
        raise_err(ERR_LEASE_NOT_FOUND, "lease not found")

    n["status"] = "RESCINDED"
    touch(n)

    # Restore lease status verbatim
    prior = n.get("prior_lease_status")
    if prior in ("ACTIVE", "MTM", "RENEWAL_PENDING"):
        lease["status"] = prior
        touch(lease)

    return success_object(_serialize(n))
