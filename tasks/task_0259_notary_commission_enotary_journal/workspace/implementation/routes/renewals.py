"""Renewal lifecycle routes (PRD §2.7 OCC, §3.10)."""
from flask import Blueprint, request

from clock import parse_iso8601
from db import store, new_common_fields, touch
from domain import (
    find_renewal, find_notary, find_bond, audit, recompute_enotary_authorized,
    compute_filed_within_grace, extend_expiry,
)
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import get_body, require_str, require_int, parse_pagination, paginate

bp = Blueprint("renewals", __name__)


@bp.post("/renewals")
@endpoint(("CommissionAuthority", "Notary"))
def create_renewal():
    body = get_body()
    notary_id = require_str(body, "notary_id")
    expected_version = require_int(body, "expected_notary_version")
    new_bond_id = require_str(body, "new_bond_id")

    # Existence (404) before OCC (PRD §2.8/§2.9): notary + new_bond.
    notary = find_notary(notary_id)
    find_bond(new_bond_id)
    # OCC (PRD §2.7): expected_notary_version must match current Notary.version.
    if expected_version != notary["version"]:
        raise err("ERR_STALE_VERSION", "expected_notary_version does not match")

    juris = store.jurisdictions.get(notary["jurisdiction_id"])
    now = store.clock.now()
    within_grace = compute_filed_within_grace(notary, juris, now)

    rec = dict(new_common_fields())
    rec.update({
        "notary_id": notary_id,
        "expected_notary_version": expected_version,
        "new_bond_id": new_bond_id,
        "status": "SUBMITTED",
        "filed_within_grace": within_grace,
    })
    store.renewals[rec["id"]] = rec
    # Submitting a renewal increments Notary.version by one (PRD §3.10).
    touch(notary)
    return success(view(rec), status=201)


@bp.get("/renewals/<renewal_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_renewal(renewal_id):
    return success(view(find_renewal(renewal_id)))


@bp.get("/renewals")
@endpoint(("CommissionAuthority", "Notary"))
def list_renewals():
    limit, offset = parse_pagination()
    recs = list(store.renewals.values())
    nid = request.args.get("notary_id")
    bid = request.args.get("new_bond_id")
    status = request.args.get("status")
    if nid is not None:
        recs = [r for r in recs if r["notary_id"] == nid]
    if bid is not None:
        recs = [r for r in recs if r["new_bond_id"] == bid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.post("/renewals/<renewal_id>/approve")
@endpoint(("CommissionAuthority",))
def approve_renewal(renewal_id):
    renewal = find_renewal(renewal_id)
    if renewal["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Renewal is not SUBMITTED")
    if not renewal["filed_within_grace"]:
        raise err("ERR_RENEWAL_OUT_OF_GRACE", "Renewal filed outside grace window")
    bond = store.bonds.get(renewal["new_bond_id"])
    if bond is None or bond["status"] != "ACTIVE":
        raise err("ERR_BOND_NOT_ACTIVE", "new_bond is not ACTIVE")
    notary = store.notaries.get(renewal["notary_id"])
    if notary is None or notary["status"] not in ("ACTIVE", "EXPIRED"):
        raise err("ERR_INVALID_STATE", "Subject notary not ACTIVE or EXPIRED")

    renewal["status"] = "APPROVED"
    touch(renewal)

    was_expired = notary["status"] == "EXPIRED"
    notary["bond_id"] = renewal["new_bond_id"]
    juris = store.jurisdictions.get(notary["jurisdiction_id"])
    # PRD §3.10: commission_expires_at is extended by commission_term_months,
    # uniformly for ACTIVE and EXPIRED subjects (extend from current expiry).
    base = (parse_iso8601(notary["commission_expires_at"])
            if notary.get("commission_expires_at") else store.clock.now())
    extend_expiry(notary, juris, base)
    if was_expired:
        notary["status"] = "ACTIVE"
    recompute_enotary_authorized(notary)
    touch(notary)
    audit(notary["id"], "NOTARY", notary["id"], "NOTARY_RENEWED", "COMMISSION_AUTHORITY",
          "Commission renewed")
    return success(view(renewal))


@bp.post("/renewals/<renewal_id>/deny")
@endpoint(("CommissionAuthority",))
def deny_renewal(renewal_id):
    renewal = find_renewal(renewal_id)
    if renewal["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Renewal is not SUBMITTED")
    renewal["status"] = "DENIED"
    touch(renewal)
    audit(renewal["notary_id"], "RENEWAL", renewal["id"], "RENEWAL_DENIED",
          "COMMISSION_AUTHORITY", "Renewal denied")
    return success(view(renewal))
