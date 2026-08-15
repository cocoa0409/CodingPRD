"""Voucher reads (with lazy expiry) and revocation (PRD 3.4)."""
from flask import Blueprint, g, request

import services as svc
from db import store, touch
from errors import forbidden, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from util import opt_enum_filter, page_params, paginate

bp = Blueprint("vouchers", __name__)

VOUCHER_STATUSES = {"ISSUED", "REDEEMED", "REVOKED", "EXPIRED"}


def get_voucher_or_404(voucher_id):
    v = store.vouchers.get(voucher_id)
    if v is None:
        raise not_found("Voucher not found")
    svc.refresh_voucher(v)
    return v


@bp.get("/closet/vouchers/<vid>")
@require_roles(
    "ProgramAdmin", "VolunteerLead", "Volunteer", "Client", "ReferralPartner"
)
def get_voucher(vid):
    v = get_voucher_or_404(vid)
    if g.user_role == "Client" and v["client_id"] != g.user_id:
        raise forbidden("Clients may only read their own vouchers")
    if g.user_role == "ReferralPartner" and v["partner_id"] != g.user_id:
        raise forbidden("Partners may only read their own vouchers")
    return ok(svc.serialize_voucher(v))


@bp.get("/closet/vouchers")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_vouchers():
    # Lazy expiry evaluation applies to listed rows before filtering.
    for v in store.vouchers.values():
        svc.refresh_voucher(v)
    status = opt_enum_filter("status", VOUCHER_STATUSES)
    partner_id = request.args.get("partner_id")
    client_id = request.args.get("client_id")
    code = request.args.get("code")
    limit, offset = page_params()
    rows = list(store.vouchers.values())
    if partner_id is not None:
        rows = [v for v in rows if v["partner_id"] == partner_id]
    if client_id is not None:
        rows = [v for v in rows if v["client_id"] == client_id]
    if code is not None:
        rows = [v for v in rows if v["code"] == code]
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_voucher(v) for v in page], total, limit, offset)


@bp.post("/closet/vouchers/<vid>/revoke")
@require_roles("ProgramAdmin", "ReferralPartner")
def revoke_voucher(vid):
    v = get_voucher_or_404(vid)
    if g.user_role == "ReferralPartner" and v["partner_id"] != g.user_id:
        raise forbidden("Partners may only revoke their own vouchers")
    if v["status"] != "ISSUED":
        raise invalid_state("Only an ISSUED voucher can be revoked")
    # Revocation does not refund the consumed issuance quota.
    v["status"] = "REVOKED"
    touch(v)
    return ok(svc.serialize_voucher(v))
