"""Disposition records: retrieval, finalization, retention-gated purge (PRD §2.11)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_DISPOSITION_NOT_FOUND,
    ERR_DISPOSITION_INVALID_STATE,
    ERR_RETENTION_PERIOD_ACTIVE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services import domain
from util import fmt_dt

bp = Blueprint("dispositions", __name__)

ANY = ALL_ROLES


def get_disposition_or_404(record_id: str) -> dict:
    record = db["dispositions"].get(record_id)
    if record is None:
        raise_error(ERR_DISPOSITION_NOT_FOUND, f"disposition record {record_id} does not exist")
    return record


@bp.route("/tissue-bank/disposition-records/<record_id>", methods=["GET"])
def get_disposition(record_id):
    require_roles(ANY)
    return success_object(domain.disposition_json(get_disposition_or_404(record_id)))


@bp.route("/tissue-bank/disposition-records/<record_id>/finalize", methods=["POST"])
def finalize_disposition(record_id):
    caller = require_roles({"ComplianceOfficer"})
    record = get_disposition_or_404(record_id)
    if record["status"] != "DRAFT":
        raise_error(ERR_DISPOSITION_INVALID_STATE, f"record status is {record['status']}, not DRAFT")
    now = domain.CLOCK.now()
    record["status"] = "FINALIZED"
    record["_finalized_dt"] = now
    record["finalized_at"] = fmt_dt(now)
    record["finalized_by_user_id"] = caller.user_id
    domain.touch(record)
    return success_object(domain.disposition_json(record))


@bp.route("/tissue-bank/disposition-records/<record_id>", methods=["DELETE"])
def purge_disposition(record_id):
    require_roles({"ComplianceOfficer"})
    record = get_disposition_or_404(record_id)
    if record["status"] == "DRAFT":
        raise_error(ERR_DISPOSITION_INVALID_STATE, "a DRAFT record cannot be purged")
    # retention floor: deletion permitted only when clock >= finalized_at + 3650 days
    threshold = record["_finalized_dt"] + timedelta(days=domain.RETENTION_DAYS)
    if domain.CLOCK.now() < threshold:
        raise_error(ERR_RETENTION_PERIOD_ACTIVE, "the ten-year retention period is still active")
    del db["dispositions"][record_id]
    return "", 204
