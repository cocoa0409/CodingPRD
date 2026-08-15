"""Collections referral endpoints (PRD 3.9): the PENDING -> REFERRED ->
SETTLED | RECALLED lifecycle with the re-referral cycle, gated on open
disputes and the property's collections threshold."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V
from services import calc

bp = Blueprint("referrals", __name__)


@bp.post("/collections-referrals/<referral_id>/transition")
def transition_referral(referral_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, middleware.PM)
    ref = db.referrals.get(referral_id)
    if ref is None:
        errors.fail(
            errors.ERR_NOT_FOUND,
            "Collections referral %s does not exist." % referral_id,
        )
    data = V.json_body()
    V.check_unknown(data, {"action", "agency_name", "recall_reason"})
    action = V.req_enum(data, "action", {"REFER", "SETTLE", "RECALL"})
    lease = db.leases[ref["lease_id"]]
    prop = calc.property_of(lease)

    if action == "REFER":
        # Tier 7: REFER is legal from PENDING or RECALLED (re-referral cycle).
        if ref["status"] not in ("PENDING", "RECALLED"):
            errors.fail(
                errors.ERR_REFERRAL_INVALID_TRANSITION,
                "REFER requires a referral in PENDING or RECALLED status.",
            )
        # Tier 14: no dispute on the lease may be OPEN or REOPENED.
        for d in db.disputes.values():
            if d["lease_id"] == lease["id"] and d["status"] in ("OPEN", "REOPENED"):
                errors.fail(
                    errors.ERR_BLOCKING_DISPUTE,
                    "An open dispute on this lease blocks collections referral.",
                )
        # Tier 17: the balance must meet the threshold; equality qualifies.
        if ref["referred_balance_cents"] < prop["collections_threshold_cents"]:
            errors.fail(
                errors.ERR_REFERRAL_THRESHOLD_NOT_MET,
                "Referred balance %d is below the collections threshold %d."
                % (ref["referred_balance_cents"], prop["collections_threshold_cents"]),
            )
        ref["status"] = "REFERRED"
        ref["agency_name"] = V.opt_str(data, "agency_name")
        ref["referred_date"] = db.today_str()
        db.touch(ref)
        return response.success_object(serializers.referral_view(ref))

    if action == "SETTLE":
        if ref["status"] != "REFERRED":
            errors.fail(
                errors.ERR_REFERRAL_INVALID_TRANSITION,
                "SETTLE requires a referral in REFERRED status.",
            )
        ref["status"] = "SETTLED"
        db.touch(ref)
        return response.success_object(serializers.referral_view(ref))

    # RECALL
    if ref["status"] != "REFERRED":
        errors.fail(
            errors.ERR_REFERRAL_INVALID_TRANSITION,
            "RECALL requires a referral in REFERRED status.",
        )
    ref["status"] = "RECALLED"
    ref["recall_reason"] = V.opt_str(data, "recall_reason")
    db.touch(ref)
    return response.success_object(serializers.referral_view(ref))


@bp.get("/leases/<lease_id>/collections-referrals")
def list_referrals(lease_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    if role == "Tenant":
        middleware.require_owns_lease(uid, lease)
    rows = [r for r in db.referrals.values() if r["lease_id"] == lease["id"]]
    page, limit, offset, total = V.sorted_page(rows, [
        ("status", V.query_filter("status")),
    ])
    return response.success_list(
        [serializers.referral_view(r) for r in page], limit, offset, total
    )
