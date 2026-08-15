"""UseEvidenceItem endpoints (PRD 3.9)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
    ERR_CLASS_NOT_ON_RECORD,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import ser_evidence_item
from util import (
    get_payload, reject_unknown_fields, require_enum, require_int,
    require_string, require_datetime, stamp_new, touch, fmt_business,
)
from routes.common import do_list

bp = Blueprint("evidence_items", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
SPECIMEN_TYPES = ("LABEL", "SCREENSHOT", "PACKAGING", "ADVERTISING")


def _get_item(item_id):
    item = db.evidence_items.get(item_id)
    if item is None:
        raise_error(ERR_NOT_FOUND, "UseEvidenceItem not found")
    return item


def _touch_record(item):
    record = db.trademark_records.get(item["trademark_record_id"])
    if record is not None:
        touch(record)  # verified_evidence_count derivation changed


# ---------------------------------------------------------------------------
# Nested create: POST /brand/trademark-records/{id}/evidence-items
# ---------------------------------------------------------------------------

@bp.route("/brand/trademark-records/<record_id>/evidence-items", methods=["POST"])
def collect_evidence(record_id):
    user_id, role = require_roles("Paralegal", "AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"nice_class", "specimen_type", "specimen_date"})
    nice_class = require_int(body, "nice_class", minimum=1, maximum=45)
    specimen_type = require_enum(body, "specimen_type", SPECIMEN_TYPES)
    specimen_date = require_datetime(body, "specimen_date")
    record = db.trademark_records.get(record_id)
    if record is None:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    # The specimen's Nice class must be one of the record's own classes.
    if nice_class not in record["nice_classes"]:
        raise_error(ERR_CLASS_NOT_ON_RECORD, "nice_class is not in the record's nice_classes")
    item = {
        "trademark_record_id": record["id"],
        "nice_class": nice_class,
        "specimen_type": specimen_type,
        "specimen_date": fmt_business(specimen_date),
        "collected_by_user_id": user_id,
        "verified_by_user_id": None,
        "status": "COLLECTED",
    }
    stamp_new(item)
    db.evidence_items[item["id"]] = item
    return success(ser_evidence_item(item), 201)


@bp.route("/brand/evidence-items", methods=["GET"])
def list_evidence():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.evidence_items.values(), ser_evidence_item,
                   [("trademark_record_id", "trademark_record_id", None),
                    ("status", "status", None)],
                   user_id, role, "evidence_item")


@bp.route("/brand/evidence-items/<item_id>", methods=["GET"])
def get_evidence(item_id):
    user_id, role = require_roles(*READ_ROLES)
    item = _get_item(item_id)
    enforce_client_scope(user_id, role, domain.client_id_for_resource("evidence_item", item))
    return success(ser_evidence_item(item), 200)


@bp.route("/brand/evidence-items/<item_id>/verify", methods=["POST"])
def verify_evidence(item_id):
    user_id, role = require_roles("AssociateAttorney", "PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    item = _get_item(item_id)
    if item["status"] != "COLLECTED":
        raise_error(ERR_INVALID_STATE, "verify is declared only from COLLECTED")
    # Segregation of duties: the verifier must differ from the collector.
    if user_id == item["collected_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "Evidence verifier must differ from collected_by_user_id")
    item["verified_by_user_id"] = user_id
    item["status"] = "VERIFIED"
    touch(item)
    _touch_record(item)
    return success(ser_evidence_item(item), 200)


@bp.route("/brand/evidence-items/<item_id>/reject", methods=["POST"])
def reject_evidence(item_id):
    user_id, role = require_roles("AssociateAttorney", "PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"reason"})
    require_string(body, "reason")
    item = _get_item(item_id)
    if item["status"] not in ("COLLECTED", "VERIFIED"):
        raise_error(ERR_INVALID_STATE, "reject is declared only from COLLECTED / VERIFIED")
    item["status"] = "REJECTED"
    touch(item)
    _touch_record(item)  # a VERIFIED -> REJECTED reject decrements the count
    return success(ser_evidence_item(item), 200)
