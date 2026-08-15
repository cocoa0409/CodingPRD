"""Referral partners and voucher issuance (PRD 3.4)."""
import uuid

from flask import Blueprint, g

import db
import services as svc
from db import stamp_new, store, touch
from errors import ApiError, forbidden, invalid_state, not_found
from middleware import require_roles
from response import ok
from routes.clients import get_client_or_404
from util import get_body, month_key, v_bool, v_dt, v_int, v_str

bp = Blueprint("partners", __name__)


def get_partner_or_404(partner_id):
    p = store.partners.get(partner_id)
    if p is None:
        raise not_found("Referral partner not found")
    return p


@bp.post("/closet/referral-partners")
@require_roles("ProgramAdmin")
def create_partner():
    data = get_body()
    name = v_str(data, "name")
    quota = v_int(data, "base_voucher_quota", lo=0)
    p = stamp_new({
        "name": name,
        "base_voucher_quota": quota,
        "status": "ACTIVE",
        "activated_month_key": month_key(db.now()),
    })
    store.partners[p["id"]] = p
    return ok(svc.serialize_partner(p), 201)


@bp.get("/closet/referral-partners/<pid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer", "ReferralPartner")
def get_partner(pid):
    # Ownership scope: a partner may read only its own record.
    if g.user_role == "ReferralPartner" and g.user_id != pid:
        raise forbidden("Partners may only read their own record")
    return ok(svc.serialize_partner(get_partner_or_404(pid)))


@bp.post("/closet/referral-partners/<pid>/suspend")
@require_roles("ProgramAdmin")
def suspend_partner(pid):
    p = get_partner_or_404(pid)
    if p["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE partner can be suspended")
    p["status"] = "SUSPENDED"
    touch(p)
    return ok(svc.serialize_partner(p))


@bp.post("/closet/referral-partners/<pid>/vouchers")
@require_roles("ProgramAdmin", "ReferralPartner")
def issue_voucher(pid):
    # Ownership scope: a partner acts only under its own partner id.
    if g.user_role == "ReferralPartner" and g.user_id != pid:
        raise forbidden("Partners may only issue vouchers under their own id")
    partner = get_partner_or_404(pid)
    data = get_body()
    client_id = data.get("client_id")
    if client_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: client_id")
    if not isinstance(client_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "client_id must be a string")
    client = get_client_or_404(client_id)
    bonus = v_int(data, "bonus_items", lo=1, hi=10)
    waives = v_bool(data, "waives_frequency", required=False, default=False)
    expires_at = v_dt(data, "expires_at")
    if not expires_at > db.now():
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "expires_at must lie after the logical clock at issuance",
        )

    # Issuance check order (PRD 3.4): client ACTIVE, partner ACTIVE, quota.
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client is not ACTIVE")
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_SUSPENDED", 409, "Partner is suspended")
    cur_month = month_key(db.now())
    issued = svc.vouchers_issued_in_month(partner["id"], cur_month)
    if issued >= svc.partner_current_month_quota(partner):
        raise ApiError(
            "ERR_VOUCHER_QUOTA_EXHAUSTED", 409,
            "Partner monthly voucher quota (with carryover) is exhausted",
        )
    v = stamp_new({
        "code": uuid.uuid4().hex,
        "partner_id": partner["id"],
        "client_id": client["id"],
        "bonus_items": bonus,
        "waives_frequency": waives,
        "expires_at": expires_at,
        "status": "ISSUED",
        "issued_month_key": cur_month,
        "redeemed_at": None,
    })
    store.vouchers[v["id"]] = v
    return ok(svc.serialize_voucher(v), 201)
