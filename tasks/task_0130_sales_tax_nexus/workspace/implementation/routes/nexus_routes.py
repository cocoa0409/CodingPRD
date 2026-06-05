"""NexusProfile endpoints (§3.2)."""
from flask import Blueprint, request

import db
from errors import APIError, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE
from middleware import require
from response import object_response, array_response
from services import common, serializers

bp = Blueprint("nexus", __name__)

READ_ROLES = ["Seller", "PlatformAdmin", "TaxPreparer", "TaxApprover", "Auditor"]


@bp.post("/nexus-profiles")
@require("Seller", "PlatformAdmin")
def create_profile():
    body = common.get_body()
    seller_id = common.require_str(body, "seller_id")
    jurisdiction_id = common.require_str(body, "jurisdiction_id")

    common.resolve_fk(db.sellers, seller_id, "seller_id")
    common.resolve_fk(db.tax_jurisdictions, jurisdiction_id, "jurisdiction_id")

    for p in db.nexus_profiles.values():
        if p["seller_id"] == seller_id and p["jurisdiction_id"] == jurisdiction_id:
            raise APIError(ERR_DUPLICATE_RESOURCE, "duplicate (seller_id, jurisdiction_id) nexus profile")

    rec = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "cumulative_taxable_sales": 0,
        "cumulative_txn_count": 0,
        "nexus_status": "NO_NEXUS",
        "registered_at": None,
    }
    common.stamp_create(rec)
    db.nexus_profiles[rec["id"]] = rec
    return object_response(serializers.nexus_profile(rec), 201)


@bp.get("/nexus-profiles/<rec_id>")
@require(*READ_ROLES)
def get_profile(rec_id):
    rec = common.get_or_404(db.nexus_profiles, rec_id, "nexus profile")
    return object_response(serializers.nexus_profile(rec))


@bp.get("/nexus-profiles")
@require(*READ_ROLES)
def list_profiles():
    records = list(db.nexus_profiles.values())
    sid = request.args.get("seller_id")
    jid = request.args.get("jurisdiction_id")
    if sid is not None:
        records = [r for r in records if r["seller_id"] == sid]
    if jid is not None:
        records = [r for r in records if r["jurisdiction_id"] == jid]
    items, limit, offset, total = common.paginate(records, serializers.nexus_profile)
    return array_response(items, limit, offset, total)


@bp.post("/nexus-profiles/<rec_id>/register")
@require("Seller")
def register_profile(rec_id):
    rec = common.get_or_404(db.nexus_profiles, rec_id, "nexus profile")
    if rec["nexus_status"] != "THRESHOLD_MET":
        raise APIError(ERR_INVALID_STATE, "nexus profile must be THRESHOLD_MET to register")
    rec["registered_at"] = db.now()
    rec["nexus_status"] = "REGISTERED"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "NexusProfile", rec["id"], "REGISTER_NEXUS")
    return object_response(serializers.nexus_profile(rec))
