"""Claim adjustment endpoints (PRD 3.6): read-only append-only repricing log."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_PROVIDER_SCOPE_VIOLATION
from response import success_object
from routes.helpers import (
    apply_filters, get_or_404, list_response, public, read_all,
)

bp = Blueprint("adjustments", __name__)


def _adjustment_provider_id(adj):
    claim = db["claims"].get(adj["claim_id"])
    return claim["provider_account_id"] if claim is not None else None


@bp.get("/api/claim-adjustments")
def list_adjustments():
    caller = read_all()
    items = list(db["claim_adjustments"].values())
    if caller.role == "ProviderRep":
        cfilter = request.args.get("claim_id")
        if cfilter is not None:
            claim = db["claims"].get(cfilter)
            if claim is not None and claim["provider_account_id"] != caller.user_id:
                raise_error(ERR_PROVIDER_SCOPE_VIOLATION, "claim_id filter is foreign")
        # scope resolved through the owning claim
        items = [a for a in items if _adjustment_provider_id(a) == caller.user_id]
    items = apply_filters(items, ["claim_id", "asp_schedule_id"])
    return list_response(items)


@bp.get("/api/claim-adjustments/<adjustmentId>")
def get_adjustment(adjustmentId):
    # single-adjustment reads are not scope-guarded (PRD 2.1 lists only the collection)
    read_all()
    adj = get_or_404("claim_adjustments", adjustmentId)
    return success_object(public(adj))
