from flask import Blueprint, request

from db import store, touch
from errors import raise_err, ERR_REFERRAL_NOT_FOUND, ERR_REFERRAL_NOT_REVOKABLE
from middleware import authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_referral
from services import post_ledger

bp = Blueprint("referrals", __name__)

READ_ROLES = ["Customer", "PlatformAdmin"]


def _get_referral_or_404(rid):
    rec = store.referrals.get(rid)
    if rec is None:
        raise_err(ERR_REFERRAL_NOT_FOUND, "Referral not found")
    return rec


def _check_referral_read_ownership(uid, role, ref):
    # a referral involves two customers; either side may read it
    if role == "Customer" and uid not in (ref.referrer_customer_id, ref.referee_customer_id):
        from errors import ERR_OWNERSHIP_MISMATCH
        raise_err(ERR_OWNERSHIP_MISMATCH, "Acting customer is not a party to this referral")


@bp.route("/api/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_referral_or_404(rid)
    _check_referral_read_ownership(uid, role, rec)
    return ok(ser_referral(rec))


@bp.route("/api/referrals", methods=["GET"])
def list_referrals():
    uid, role = authenticate(READ_ROLES)
    items = list(store.referrals.values())
    if role == "Customer":
        items = [r for r in items
                 if r.referrer_customer_id == uid or r.referee_customer_id == uid]
    for param in ("referrer_customer_id", "referee_customer_id",
                  "referee_first_invoice_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if getattr(r, param) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_referral(r) for r in page], total, limit, offset)


@bp.route("/api/referrals/<rid>/revoke", methods=["POST"])
def revoke_referral(rid):
    authenticate(["PlatformAdmin"])
    rec = _get_referral_or_404(rid)
    if rec.status not in ("PENDING", "QUALIFIED"):
        raise_err(ERR_REFERRAL_NOT_REVOKABLE, "revoke requires referral PENDING or QUALIFIED")
    was_qualified = rec.status == "QUALIFIED"
    rec.status = "REVOKED"
    touch(rec)
    if was_qualified and rec.qualified_credit_cents:
        # clawback compensation to the referrer
        post_ledger(rec.referrer_customer_id, "REVOKE_REFERRAL",
                    -rec.qualified_credit_cents, reference_id=rec.id)
    return ok(ser_referral(rec))
