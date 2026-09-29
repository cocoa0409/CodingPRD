"""Recall campaigns: the quarantine cascade and the supplier trust score."""
import constants as C
import db
import validation as V
from db import store
from errors import ApiError
from flask import Blueprint
from middleware import authorize
from routes.common import insert, list_out, must_find, object_out
from services import cascade, derive

bp = Blueprint("recalls", __name__)

CAMPAIGN_STATUSES = ["DRAFT", "OPEN", "CLOSED"]


@bp.post("/recall-campaigns")
@authorize("RecallCoordinator")
def create_campaign():
    body = V.body_dict()
    supplier_id = V.field_string(body, "supplier_id", required=True, min_len=1)
    campaign_code = V.field_string(body, "campaign_code", required=True, min_len=1)
    part_number = V.field_string(body, "part_number", required=True, min_len=1)
    lot_codes = V.field_str_array(body, "lot_codes", required=True, allow_empty=False)
    severity = V.field_enum(body, "severity", C.SEVERITIES, required=True)
    V.unique_or_400(store.recall_campaigns, "campaign_code", campaign_code, "campaign_code")
    must_find("suppliers", supplier_id)
    row = db.new_row(
        {
            "supplier_id": supplier_id,
            "campaign_code": campaign_code,
            "part_number": part_number,
            "lot_codes": lot_codes,
            "severity": severity,
            "opened_at": None,
            "affected_installation_count": 0,
            "remedied_installation_count": 0,
            "quarantined_piece_count": 0,
            "ship_stop": severity == "SAFETY",
            "status": "DRAFT",
        }
    )
    insert("recall_campaigns", row)
    return object_out("recall_campaigns", row, 201)


@bp.get("/recall-campaigns/<row_id>")
@authorize("PlantAdmin", "RecallCoordinator")
def get_campaign(row_id):
    return object_out("recall_campaigns", must_find("recall_campaigns", row_id))


@bp.get("/recall-campaigns")
@authorize("PlantAdmin", "RecallCoordinator")
def list_campaigns():
    supplier_id = V.query_string("supplier_id")
    part_number = V.query_string("part_number")
    severity = V.query_enum("severity", C.SEVERITIES)
    status = V.query_enum("status", CAMPAIGN_STATUSES)
    rows = list(store.recall_campaigns.values())
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    if part_number is not None:
        rows = [r for r in rows if r["part_number"] == part_number]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_out("recall_campaigns", rows)


@bp.post("/recall-campaigns/<row_id>/open")
@authorize("RecallCoordinator")
def open_campaign(row_id):
    V.body_dict()
    row = must_find("recall_campaigns", row_id)
    if row["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Campaign status is {}; only a DRAFT campaign can be opened.".format(row["status"]),
        )
    row["opened_at"] = db.now()
    row["ship_stop"] = row["severity"] == "SAFETY"
    row["status"] = "OPEN"
    cascade.quarantine_cascade(row, row["lot_codes"])
    db.touch(row)

    supplier = store.suppliers.get(row["supplier_id"])
    if supplier is not None:
        supplier["open_recall_count"] = int(supplier["open_recall_count"]) + 1
        supplier["penalty_event_count"] = int(supplier["penalty_event_count"]) + 1
        derive.rescore_supplier(supplier)
        db.touch(supplier)
    return object_out("recall_campaigns", row)


@bp.post("/recall-campaigns/<row_id>/expand")
@authorize("RecallCoordinator")
def expand_campaign(row_id):
    body = V.body_dict()
    additional = V.field_str_array(body, "additional_lot_codes", required=True, allow_empty=False)
    expected = V.field_int(body, "expected_recall_campaign_version", required=True, minimum=0)
    row = must_find("recall_campaigns", row_id)
    if row["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Campaign status is {}; only an OPEN campaign can be expanded.".format(row["status"]),
        )
    if expected != int(row["version"]):
        raise ApiError(
            "ERR_STALE_RECALL_CAMPAIGN_VERSION",
            "Expected campaign version {} but the stored version is {}.".format(
                expected, row["version"]
            ),
        )
    existing = list(row["lot_codes"])
    new_codes = [code for code in additional if code not in existing]
    if not new_codes:
        raise ApiError(
            "ERR_INVALID_STATE",
            "additional_lot_codes brings no lot code that is not already in scope.",
        )
    row["lot_codes"] = existing + new_codes
    cascade.quarantine_cascade(row, new_codes)
    db.touch(row)

    supplier = store.suppliers.get(row["supplier_id"])
    if supplier is not None:
        # hop 4 does not run again: no counter moves, only a rescore
        derive.rescore_supplier(supplier)
    return object_out("recall_campaigns", row)


@bp.post("/recall-campaigns/<row_id>/close")
@authorize("RecallCoordinator")
def close_campaign(row_id):
    V.body_dict()
    row = must_find("recall_campaigns", row_id)
    if row["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Campaign status is {}; only an OPEN campaign can be closed.".format(row["status"]),
        )
    if int(row["remedied_installation_count"]) != int(row["affected_installation_count"]):
        raise ApiError(
            "ERR_CAMPAIGN_NOT_CLOSEABLE",
            "{} of {} affected installations have been remedied.".format(
                row["remedied_installation_count"], row["affected_installation_count"]
            ),
        )
    row["status"] = "CLOSED"
    db.touch(row)
    supplier = store.suppliers.get(row["supplier_id"])
    if supplier is not None:
        supplier["open_recall_count"] = max(0, int(supplier["open_recall_count"]) - 1)
        derive.rescore_supplier(supplier)
        db.touch(supplier)
    return object_out("recall_campaigns", row)
