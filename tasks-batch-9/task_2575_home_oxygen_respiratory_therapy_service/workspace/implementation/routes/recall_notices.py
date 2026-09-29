"""Recall notice endpoints.

A CLASS_I notice fires the second four-hop cascade of the system: notice ->
fleet units -> placements -> contracts. The notice's affected and
auto-quarantined counts are frozen snapshots taken BEFORE the cascade runs;
only remediated_unit_count is a live recount (see serial.recall_notice_out).
"""
from flask import Blueprint

from calc import recall_deadline, remediated_unit_count
from core import (
    RECALL_READERS,
    ROLE_AUDITOR,
    ROLE_MANAGER,
    ApiError,
    authenticate,
    base_row,
    db,
    enum_filter,
    now,
    paginate,
    pagination,
    respond,
    sorted_rows,
    str_filter,
    touch,
)
from domain import get_recall_notice, recompute_allowable
from serial import recall_notice_out
from validate import Field, validate

bp = Blueprint("recall_notices", __name__)

SEVERITIES = ("CLASS_I", "CLASS_II", "CLASS_III")
NOTICE_STATUSES = ("OPEN", "IN_REMEDIATION", "CLOSED")
EXPOSED_STATUSES = ("IN_STOCK", "RESERVED", "DEPLOYED", "IN_QUARANTINE")
PULLED_STATUSES = ("IN_STOCK", "RESERVED", "DEPLOYED")

CREATE_FIELDS = [
    Field("model_code", "string", required=True, min_len=1, max_len=40),
    Field("severity", "enum", required=True, enum=SEVERITIES),
]


def _matching_units(model_code):
    return [
        unit
        for unit in sorted_rows(db.equipment_units.values())
        if unit["model_code"] == model_code
    ]


@bp.post("/recall-notices")
def create_notice():
    """Publish a recall; CLASS_I pulls the matching fleet out of service."""
    authenticate((ROLE_AUDITOR,))
    data = validate(CREATE_FIELDS)
    model_code = data["model_code"]
    severity = data["severity"]
    units = _matching_units(model_code)
    # HOP 2 snapshots, evaluated before hop 1 mutates anything.
    affected = [u for u in units if u["status"] in EXPOSED_STATUSES]
    pulled = [u for u in units if u["status"] in PULLED_STATUSES]
    issued_at = now()
    row = base_row()
    row.update(
        {
            "model_code": model_code,
            "severity": severity,
            "issued_at": issued_at,
            "remediation_deadline_utc": recall_deadline(issued_at, severity),
            "status": "OPEN",
            "affected_unit_count": len(affected),
            "auto_quarantined_unit_count": len(pulled) if severity == "CLASS_I" else 0,
        }
    )
    db.recall_notices[row["id"]] = row
    if severity == "CLASS_I":
        _class_one_cascade(pulled)
    return respond(recall_notice_out(row), 201)


def _class_one_cascade(pulled):
    """HOP 1: quarantine; HOP 3: recall placements; HOP 4: suspend contracts."""
    pulled_ids = set()
    for unit in pulled:
        unit["status"] = "IN_QUARANTINE"
        unit["quarantine_reason"] = "RECALL"
        touch(unit)
        pulled_ids.add(unit["id"])
    contract_ids = []
    for placement in sorted_rows(db.placements.values()):
        if placement["status"] != "PLACED":
            continue
        if placement["equipment_unit_id"] not in pulled_ids:
            continue
        placement["status"] = "RECALLED_OUT_OF_SERVICE"
        placement["removal_reason"] = "RECALL"
        placement["removed_at"] = now()
        touch(placement)
        if placement["contract_id"] not in contract_ids:
            contract_ids.append(placement["contract_id"])
    for contract_id in contract_ids:
        contract = db.contracts.get(contract_id)
        if contract is None or contract["billing_status"] == "CLOSED":
            continue
        if contract["billing_status"] in ("ACCRUING", "CAP_REACHED"):
            contract["billing_status"] = "SUSPENDED"
            contract["suspension_reason"] = "RECALL"
        recompute_allowable(contract)
        touch(contract)


@bp.get("/recall-notices")
def list_notices():
    authenticate(RECALL_READERS)
    model_code = str_filter("model_code")
    severity = enum_filter("severity", SEVERITIES)
    status = enum_filter("status", NOTICE_STATUSES)
    limit, offset = pagination()
    rows = sorted_rows(db.recall_notices.values())
    if model_code is not None:
        rows = [r for r in rows if r["model_code"] == model_code]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, recall_notice_out)


@bp.get("/recall-notices/<recall_notice_id>")
def read_notice(recall_notice_id):
    authenticate(RECALL_READERS)
    return respond(recall_notice_out(get_recall_notice(recall_notice_id)))


@bp.post("/recall-notices/<recall_notice_id>/start-remediation")
def start_remediation(recall_notice_id):
    authenticate((ROLE_MANAGER,))
    notice = get_recall_notice(recall_notice_id)
    if notice["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    notice["status"] = "IN_REMEDIATION"
    touch(notice)
    return respond(recall_notice_out(notice))


@bp.post("/recall-notices/<recall_notice_id>/close")
def close_notice(recall_notice_id):
    """Closure needs the live remediated count to catch the frozen snapshot."""
    authenticate((ROLE_MANAGER,))
    notice = get_recall_notice(recall_notice_id)
    if notice["status"] != "IN_REMEDIATION":
        raise ApiError("ERR_INVALID_STATE")
    if remediated_unit_count(notice) < notice["affected_unit_count"]:
        raise ApiError("ERR_RECALL_NOT_REMEDIATED")
    notice["status"] = "CLOSED"
    touch(notice)
    return respond(recall_notice_out(notice))
