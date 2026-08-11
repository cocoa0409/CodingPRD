"""Custody trail query and the logical clock (PRD §2.9, §2.10)."""

from flask import Blueprint, request

import clocktime
import db
import serialize
import utils
from errors import ApiError, ERR_VALIDATION
from middleware import require_roles, check_owns_account
from response import ok_object, paginate, sort_created

bp = Blueprint("misc", __name__)

SUBJECT_TYPES = {"MANIFEST", "ITEM", "BATCH"}


def _subject_account_id(subject_type, subject_id):
    """Resolve a custody subject to its owning account id when possible;
    None when the subject kind has no account linkage or does not resolve."""
    if subject_type == "MANIFEST":
        manifest = db.manifests.get(subject_id)
        return manifest["account_id"] if manifest else None
    if subject_type == "ITEM":
        item = db.items.get(subject_id)
        if item is None:
            return None
        manifest = db.manifests.get(item["manifest_id"])
        return manifest["account_id"] if manifest else None
    return None  # BATCH spans accounts


@bp.get("/itad/custody-events")
def query_custody_events():
    uid, role = require_roles("PlatformAdmin", "ComplianceOfficer", "IntakeOperator",
                              "LogisticsCoordinator", "AccountManager")
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    if subject_type is None or subject_type not in SUBJECT_TYPES:
        raise ApiError(ERR_VALIDATION, 400,
                       "subject_type query parameter must be MANIFEST, ITEM, or BATCH")
    if subject_id is None or not isinstance(subject_id, str):
        raise ApiError(ERR_VALIDATION, 400, "subject_id query parameter is required")
    if role == "AccountManager" and subject_type != "BATCH":
        account_id = _subject_account_id(subject_type, subject_id)
        if account_id is not None:
            check_owns_account(uid, role, account_id)
    records = [e for e in db.custody_events.values()
               if e["subject_type"] == subject_type and e["subject_id"] == subject_id]
    records = sort_created(records)
    return paginate([serialize.custody_event(e) for e in records])


@bp.post("/itad/_clock/set_current_utc")
def set_clock():
    uid, role = require_roles("PlatformAdmin")
    data = utils.body_json()
    target = utils.req_datetime(data, "to_iso8601")
    clocktime.set_now(target)
    return ok_object({"current_utc": clocktime.fmt_dt(clocktime.now())})
