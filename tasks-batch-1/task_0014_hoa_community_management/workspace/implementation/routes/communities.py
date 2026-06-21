"""Community endpoints."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import auth_required
from response import success
from .helpers import (
    fetch_or_404,
    get_json_body,
    optional_int,
    require_int,
    require_str,
)


bp = Blueprint("communities", __name__)

DEFAULTS = {
    "late_fee_grace_days": 15,
    "late_fee_flat_cents": 2500,
    "late_fee_pct_bps": 1000,
    "lien_threshold_cents": 250000,
    "election_quorum_pct": 33,
    "reserve_inflation_bps": 300,
}


def _serialize(c: dict) -> dict:
    return {
        "id": c["id"],
        "name": c["name"],
        "fiscal_year_start_month": c["fiscal_year_start_month"],
        "regular_assessment_cents": c["regular_assessment_cents"],
        "late_fee_grace_days": c["late_fee_grace_days"],
        "late_fee_flat_cents": c["late_fee_flat_cents"],
        "late_fee_pct_bps": c["late_fee_pct_bps"],
        "lien_threshold_cents": c["lien_threshold_cents"],
        "election_quorum_pct": c["election_quorum_pct"],
        "reserve_inflation_bps": c["reserve_inflation_bps"],
        "current_utc": db.fmt_iso(db.get_current_utc()),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/hoa/communities", methods=["POST"])
@auth_required({"PlatformAdmin"})
def create_community():
    body = get_json_body()
    name = require_str(body, "name")
    fiscal_year_start_month = require_int(body, "fiscal_year_start_month",
                                          min_value=1, max_value=12)
    regular_assessment_cents = require_int(body, "regular_assessment_cents",
                                           min_value=0)

    record = {
        **db.make_common_fields(),
        "name": name,
        "fiscal_year_start_month": fiscal_year_start_month,
        "regular_assessment_cents": regular_assessment_cents,
        "late_fee_grace_days": optional_int(body, "late_fee_grace_days",
                                            DEFAULTS["late_fee_grace_days"],
                                            min_value=0),
        "late_fee_flat_cents": optional_int(body, "late_fee_flat_cents",
                                            DEFAULTS["late_fee_flat_cents"],
                                            min_value=0),
        "late_fee_pct_bps": optional_int(body, "late_fee_pct_bps",
                                         DEFAULTS["late_fee_pct_bps"],
                                         min_value=0),
        "lien_threshold_cents": optional_int(body, "lien_threshold_cents",
                                             DEFAULTS["lien_threshold_cents"],
                                             min_value=0),
        "election_quorum_pct": optional_int(body, "election_quorum_pct",
                                            DEFAULTS["election_quorum_pct"],
                                            min_value=0, max_value=100),
        "reserve_inflation_bps": optional_int(body, "reserve_inflation_bps",
                                              DEFAULTS["reserve_inflation_bps"],
                                              min_value=0),
    }
    db.communities[record["id"]] = record
    return success(_serialize(record), status=201)


@bp.route("/hoa/communities/<cid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember", "HomeOwner"})
def fetch_community(cid):
    c = fetch_or_404(db.communities, cid, "Community")
    return success(_serialize(c))
