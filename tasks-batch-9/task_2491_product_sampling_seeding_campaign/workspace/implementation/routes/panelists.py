"""Panel recruitment and fraud risk rescoring."""

from decimal import Decimal

from flask import Blueprint

import serializers
from db import db, new_row, ordered
from middleware import endpoint
from response import collection, single
from services import calculations as calc
from services.gates import must_exist
from validation import field, invalid, paginate, parse_body, parse_query

bp = Blueprint("panelists", __name__)

INTEGRITY_STATUSES = ("CLEAR", "FLAGGED", "BANNED")

CREATE_FIELDS = [
    field("email", "string", required=True),
    field("display_name", "string", required=True),
    field("address_hash", "string", required=True),
    field("account_opened_at", "datetime", required=True),
    field("segment_code", "string", required=True),
    field("referred_by_panelist_id", "id"),
]

RESCORE_FIELDS = [
    field("variant", "enum", required=True, values=("SCREENING", "AUDIT")),
]

LIST_FILTERS = [
    field("referred_by_panelist_id", "string"),
    field("integrity_status", "enum", values=INTEGRITY_STATUSES),
    field("segment_code", "string"),
]


@bp.post("/panelists")
@endpoint(["Anonymous", "PlatformAdmin"], anonymous_ok=True)
def create_panelist():
    body, _ = parse_body(CREATE_FIELDS)
    for existing in db.panelists.values():
        if existing["email"] == body["email"]:
            raise invalid("email '%s' is already registered" % body["email"])
    if body["referred_by_panelist_id"] is not None:
        must_exist("panelists", body["referred_by_panelist_id"], "Panelist")

    row = new_row()
    row.update({
        "email": body["email"],
        "display_name": body["display_name"],
        "address_hash": body["address_hash"],
        "account_opened_at": body["account_opened_at"],
        "segment_code": body["segment_code"],
        "referred_by_panelist_id": body["referred_by_panelist_id"],
        "integrity_status": "CLEAR",
        "diversion_strikes": 0,
        "fraud_risk_score_screening": Decimal("0.0"),
        "fraud_risk_score_audit": None,
        "last_risk_scored_at": None,
    })
    db.panelists[row["id"]] = row
    return single(serializers.panelist(row), 201)


@bp.get("/panelists/<panelist_id>")
@endpoint(["ComplianceModerator", "CampaignManager", "PlatformAdmin"])
def get_panelist(panelist_id):
    parse_body([])
    row = must_exist("panelists", panelist_id, "Panelist")
    return single(serializers.panelist(row))


@bp.get("/panelists")
@endpoint(["ComplianceModerator", "CampaignManager", "PlatformAdmin"])
def list_panelists():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.panelists.values())
    if query["referred_by_panelist_id"] is not None:
        rows = [r for r in rows
                if r["referred_by_panelist_id"] == query["referred_by_panelist_id"]]
    if query["integrity_status"] is not None:
        rows = [r for r in rows if r["integrity_status"] == query["integrity_status"]]
    if query["segment_code"] is not None:
        rows = [r for r in rows if r["segment_code"] == query["segment_code"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.panelist(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/panelists/<panelist_id>/risk-rescore")
@endpoint(["ComplianceModerator"])
def risk_rescore(panelist_id):
    body, _ = parse_body(RESCORE_FIELDS)
    panelist = must_exist("panelists", panelist_id, "Panelist")
    calc.rescore_panelist(panelist, body["variant"])
    return single(serializers.panelist(panelist))
