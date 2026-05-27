"""Lien endpoints."""
from __future__ import annotations

import datetime

from flask import Blueprint, request

import db
import recompute
from errors import (
    ERR_BALANCE_BELOW_THRESHOLD,
    ERR_BALANCE_NONZERO,
    ERR_INVALID_STATE,
    raise_err,
)
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    paginate,
    parse_pagination,
)


bp = Blueprint("liens", __name__)


def _serialize(l: dict) -> dict:
    return {
        "id": l["id"],
        "property_id": l["property_id"],
        "principal_at_filing_cents": int(l["principal_at_filing_cents"]),
        "status": l["status"],
        "filed_at": l["filed_at"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.route("/hoa/liens/<lid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "HomeOwner"})
def fetch_lien(lid):
    l = fetch_or_404(db.liens, lid, "Lien")
    return success(_serialize(l))


@bp.route("/hoa/liens", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "HomeOwner"})
def list_liens():
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    rows = list(db.liens.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize(r) for r in page], total, limit, offset)


@bp.route("/hoa/liens/<lid>/satisfy", methods=["POST"])
@auth_required({"BoardSecretary"})
def satisfy_lien(lid):
    l = fetch_or_404(db.liens, lid, "Lien")
    if l["status"] != "FILED":
        raise_err(ERR_INVALID_STATE,
                  f"Lien must be FILED to satisfy (currently {l['status']})")
    prop = fetch_or_404(db.properties, l["property_id"], "Property")
    if int(prop["account_balance_cents"]) != 0:
        raise_err(ERR_BALANCE_NONZERO,
                  "Property balance must be 0 to satisfy a lien")
    l["status"] = "SATISFIED"
    db.bump(l)
    recompute.recompute_property_compliance_posture(prop)
    return success(_serialize(l))


@bp.route("/hoa/liens/<lid>/initiate-foreclosure", methods=["POST"])
@auth_required({"BoardPresident"})
def initiate_foreclosure(lid):
    l = fetch_or_404(db.liens, lid, "Lien")
    if l["status"] != "FILED":
        raise_err(ERR_INVALID_STATE,
                  f"Lien must be FILED to initiate foreclosure "
                  f"(currently {l['status']})")
    prop = fetch_or_404(db.properties, l["property_id"], "Property")
    community = fetch_or_404(db.communities, prop["community_id"], "Community")

    # Validation priority: safety (priority 7, ERR_BALANCE_BELOW_THRESHOLD)
    # BEFORE temporal (180-day cool-off, which surfaces as ERR_INVALID_STATE)
    if int(prop["account_balance_cents"]) < int(community["lien_threshold_cents"]):
        raise_err(ERR_BALANCE_BELOW_THRESHOLD,
                  "Property balance has dropped below the lien threshold")

    # Temporal: 180-day cooling-off
    filed_at = db.parse_iso(l["filed_at"])
    now = db.get_current_utc()
    if now < filed_at + datetime.timedelta(days=180):
        raise_err(ERR_INVALID_STATE,
                  "180-day cooling-off period has not yet elapsed")

    l["status"] = "FORECLOSURE_INITIATED"
    db.bump(l)
    return success(_serialize(l))
