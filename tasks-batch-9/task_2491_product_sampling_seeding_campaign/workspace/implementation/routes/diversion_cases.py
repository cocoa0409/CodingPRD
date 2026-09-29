"""Diversion monitoring cases and the substantiation cascade."""

from flask import Blueprint

import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import acting_user_id, endpoint
from response import collection, single
from services import calculations as calc
from services.cascades import substantiate_diversion
from services.gates import must_exist, require_segregation
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("diversion_cases", __name__)

CASE_STATUSES = ("OPEN", "INVESTIGATING", "SUBSTANTIATED", "DISMISSED")
SIGNAL_TYPES = ("RESALE_LISTING", "ADDRESS_CLUSTER", "BULK_REDEMPTION")
LIVE_STATUSES = ("INVESTIGATING", "SUBSTANTIATED")

CREATE_FIELDS = [
    field("panelist_id", "id", required=True),
    field("sample_shipment_id", "id", required=True),
    field("signal_type", "enum", required=True, values=SIGNAL_TYPES),
    field("evidence_note", "string", required=True),
]

LIST_FILTERS = [
    field("panelist_id", "string"),
    field("sample_shipment_id", "string"),
    field("status", "enum", values=CASE_STATUSES),
]


def _require_status(case, expected):
    if case["status"] != expected:
        raise ApiError("ERR_INVALID_DIVERSION_CASE_STATE",
                       "Case status is '%s', not %s" % (case["status"], expected))


@bp.post("/diversion-cases")
@endpoint(["ComplianceModerator"])
def open_case():
    body, _ = parse_body(CREATE_FIELDS)
    panelist = must_exist("panelists", body["panelist_id"], "Panelist")
    shipment = must_exist("sample_shipments", body["sample_shipment_id"],
                          "Sample shipment")

    row = new_row()
    row.update({
        "panelist_id": panelist["id"],
        "sample_shipment_id": shipment["id"],
        "signal_type": body["signal_type"],
        "evidence_note": body["evidence_note"],
        "status": "OPEN",
        "opened_by_user_id": acting_user_id(),
        "substantiated_at": None,
        "reopen_count": 0,
    })
    db.diversion_cases[row["id"]] = row
    return single(serializers.diversion_case(row), 201)


@bp.get("/diversion-cases/<diversion_case_id>")
@endpoint(["ComplianceModerator", "CampaignManager", "PlatformAdmin"])
def get_case(diversion_case_id):
    parse_body([])
    row = must_exist("diversion_cases", diversion_case_id, "Diversion case")
    return single(serializers.diversion_case(row))


@bp.get("/diversion-cases")
@endpoint(["ComplianceModerator", "CampaignManager", "PlatformAdmin"])
def list_cases():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.diversion_cases.values())
    if query["panelist_id"] is not None:
        rows = [r for r in rows if r["panelist_id"] == query["panelist_id"]]
    if query["sample_shipment_id"] is not None:
        rows = [r for r in rows
                if r["sample_shipment_id"] == query["sample_shipment_id"]]
    if query["status"] is not None:
        rows = [r for r in rows if r["status"] == query["status"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.diversion_case(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/diversion-cases/<diversion_case_id>/investigate")
@endpoint(["ComplianceModerator"])
def investigate_case(diversion_case_id):
    parse_body([])
    case = must_exist("diversion_cases", diversion_case_id, "Diversion case")
    _require_status(case, "OPEN")

    # the status write precedes the rescore, so this very case counts itself
    case["status"] = "INVESTIGATING"
    touch(case)

    panelist = db.panelists.get(case["panelist_id"])
    if panelist is not None:
        calc.rescore_panelist(panelist, "AUDIT")
    return single(serializers.diversion_case(case))


@bp.post("/diversion-cases/<diversion_case_id>/reopen")
@endpoint(["ComplianceModerator"])
def reopen_case(diversion_case_id):
    parse_body([])
    case = must_exist("diversion_cases", diversion_case_id, "Diversion case")
    _require_status(case, "INVESTIGATING")
    case["status"] = "OPEN"
    case["reopen_count"] += 1
    touch(case)
    return single(serializers.diversion_case(case))


@bp.post("/diversion-cases/<diversion_case_id>/dismiss")
@endpoint(["ComplianceModerator"])
def dismiss_case(diversion_case_id):
    parse_body([])
    case = must_exist("diversion_cases", diversion_case_id, "Diversion case")
    _require_status(case, "INVESTIGATING")
    case["status"] = "DISMISSED"
    touch(case)

    panelist = db.panelists.get(case["panelist_id"])
    if panelist is not None and panelist["integrity_status"] == "FLAGGED":
        others_live = any(other["id"] != case["id"] and other["status"] in LIVE_STATUSES
                          for other in store.panelist_diversion_cases(panelist["id"]))
        if not others_live:
            panelist["integrity_status"] = "CLEAR"
            touch(panelist)
    return single(serializers.diversion_case(case))


@bp.post("/diversion-cases/<diversion_case_id>/substantiate")
@endpoint(["ComplianceModerator"])
def substantiate_case(diversion_case_id):
    parse_body([])
    case = must_exist("diversion_cases", diversion_case_id, "Diversion case")
    _require_status(case, "INVESTIGATING")
    require_segregation(case["opened_by_user_id"],
                        "The moderator who opened this case may not substantiate it")
    substantiate_diversion(case)
    return single(serializers.diversion_case(case))
