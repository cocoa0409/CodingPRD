"""MaintenanceFiling endpoints (PRD 3.9)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_OUTSIDE_FILING_WINDOW,
    ERR_RECORD_NOT_REGISTERED, ERR_EVIDENCE_RECORD_MISMATCH,
    ERR_EVIDENCE_NOT_VERIFIED, ERR_EVIDENCE_STALE, ERR_INCOMPLETE_CLASS_COVERAGE,
    ERR_VALIDATION,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import (
    ser_maintenance_filing, maintenance_fees, evidence_staleness_cutoff,
)
from util import (
    get_payload, reject_unknown_fields, require_enum, require_array,
    stamp_new, touch, parse_dt, fmt_business, add_years,
)
from routes.common import do_list

bp = Blueprint("maintenance_filings", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
FILING_TYPES = ("SECTION_8", "RENEWAL")
DECISIONS = ("ACCEPTED", "REJECTED")


def _get_filing(filing_id):
    filing = db.maintenance_filings.get(filing_id)
    if filing is None:
        raise_error(ERR_NOT_FOUND, "MaintenanceFiling not found")
    return filing


# ---------------------------------------------------------------------------
# Nested create: POST /brand/trademark-records/{id}/maintenance-filings
# ---------------------------------------------------------------------------

@bp.route("/brand/trademark-records/<record_id>/maintenance-filings", methods=["POST"])
def create_filing(record_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"filing_type", "evidence_item_ids"})
    filing_type = require_enum(body, "filing_type", FILING_TYPES)
    evidence_item_ids = require_array(body, "evidence_item_ids")
    for eid in evidence_item_ids:
        if not isinstance(eid, str):
            raise_error(ERR_VALIDATION, "evidence_item_ids entries must be strings")
    record = db.trademark_records.get(record_id)
    if record is None:
        raise_error(ERR_NOT_FOUND, "TrademarkRecord not found")
    # Body-referenced FKs must exist (validation priority 4).
    for eid in evidence_item_ids:
        if eid not in db.evidence_items:
            raise_error(ERR_NOT_FOUND, "UseEvidenceItem not found: %s" % eid)
    # Fees are computed at PREPARED (no late fee until a grace-window submit).
    base, surcharge, late_fee, total = maintenance_fees(record, is_late=False)
    filing = {
        "trademark_record_id": record["id"],
        "filing_type": filing_type,
        "evidence_item_ids": list(evidence_item_ids),
        "fee_base_cents": base,
        "fee_surcharge_cents": surcharge,
        "late_fee_cents": late_fee,
        "fee_total_cents": total,
        "is_late": False,
        "status": "PREPARED",
    }
    stamp_new(filing)
    db.maintenance_filings[filing["id"]] = filing
    return success(ser_maintenance_filing(filing), 201)


@bp.route("/brand/maintenance-filings", methods=["GET"])
def list_filings():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.maintenance_filings.values(), ser_maintenance_filing,
                   [("trademark_record_id", "trademark_record_id", None),
                    ("status", "status", None)],
                   user_id, role, "maintenance_filing")


@bp.route("/brand/maintenance-filings/<filing_id>", methods=["GET"])
def get_filing(filing_id):
    user_id, role = require_roles(*READ_ROLES)
    filing = _get_filing(filing_id)
    enforce_client_scope(user_id, role,
                         domain.client_id_for_resource("maintenance_filing", filing))
    return success(ser_maintenance_filing(filing), 200)


@bp.route("/brand/maintenance-filings/<filing_id>/submit", methods=["POST"])
def submit_filing(filing_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, set())
    filing = _get_filing(filing_id)
    if filing["status"] not in ("PREPARED", "REJECTED_OFFICE"):
        raise_error(ERR_INVALID_STATE,
                    "submit is declared only from PREPARED / REJECTED_OFFICE")
    record = db.trademark_records.get(filing["trademark_record_id"])
    now = db.clock.now()
    # Temporal (priority 10): timely window [open, close] (closed interval) or
    # grace window (close, grace_close]. Evaluable only once windows exist.
    is_late = None
    if record["maintenance_window_open"] is not None:
        window_open = parse_dt(record["maintenance_window_open"])
        window_close = parse_dt(record["maintenance_window_close"])
        grace_close = parse_dt(record["maintenance_grace_close"])
        if window_open <= now <= window_close:
            is_late = False
        elif window_close < now <= grace_close:
            is_late = True
        else:
            raise_error(ERR_OUTSIDE_FILING_WINDOW,
                        "Submit is outside the timely and grace filing windows")
    # Referential (priority 20): the record must be REGISTERED or MAINTENANCE_DUE.
    if record["status"] not in ("REGISTERED", "MAINTENANCE_DUE"):
        raise_error(ERR_RECORD_NOT_REGISTERED,
                    "Maintenance submit requires a REGISTERED / MAINTENANCE_DUE record")
    # Evidence integrity family (priority 21), in declared order.
    cutoff = evidence_staleness_cutoff(record)
    covered_classes = set()
    for eid in filing["evidence_item_ids"]:
        item = db.evidence_items.get(eid)
        if item is None:
            raise_error(ERR_NOT_FOUND, "UseEvidenceItem not found: %s" % eid)
        if item["trademark_record_id"] != record["id"]:
            raise_error(ERR_EVIDENCE_RECORD_MISMATCH,
                        "Evidence item belongs to a different record")
        if item["status"] != "VERIFIED":
            raise_error(ERR_EVIDENCE_NOT_VERIFIED, "Evidence item is not VERIFIED")
        if parse_dt(item["specimen_date"]) < cutoff:
            raise_error(ERR_EVIDENCE_STALE,
                        "specimen_date is earlier than maintenance_window_close - 36 months")
        covered_classes.add(item["nice_class"])
    for nice_class in record["nice_classes"]:
        if nice_class not in covered_classes:
            raise_error(ERR_INCOMPLETE_CLASS_COVERAGE,
                        "Every record nice_class must be covered by a listed VERIFIED item")
    # Fees are re-finalized at submission with the pinned evaluation order.
    base, surcharge, late_fee, total = maintenance_fees(record, is_late=is_late)
    filing["fee_base_cents"] = base
    filing["fee_surcharge_cents"] = surcharge
    filing["late_fee_cents"] = late_fee
    filing["fee_total_cents"] = total
    filing["is_late"] = is_late
    filing["status"] = "LATE_FILED" if is_late else "SUBMITTED"
    touch(filing)
    return success(ser_maintenance_filing(filing), 200)


@bp.route("/brand/maintenance-filings/<filing_id>/office-decision", methods=["POST"])
def office_decision(filing_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"decision"})
    decision = require_enum(body, "decision", DECISIONS)
    filing = _get_filing(filing_id)
    if filing["status"] not in ("SUBMITTED", "LATE_FILED"):
        raise_error(ERR_INVALID_STATE,
                    "office-decision is declared only from SUBMITTED / LATE_FILED")
    if decision == "ACCEPTED":
        filing["status"] = "ACCEPTED"
        touch(filing)
        # Record cascade (PRD 3.2): MAINTENANCE_DUE returns to REGISTERED (an
        # already-REGISTERED record stays); all three horizons advance +10 years.
        record = db.trademark_records.get(filing["trademark_record_id"])
        if record is not None and record["maintenance_window_open"] is not None:
            record["maintenance_window_open"] = fmt_business(
                add_years(parse_dt(record["maintenance_window_open"]), 10))
            record["maintenance_window_close"] = fmt_business(
                add_years(parse_dt(record["maintenance_window_close"]), 10))
            record["maintenance_grace_close"] = fmt_business(
                add_years(parse_dt(record["maintenance_grace_close"]), 10))
            if record["status"] == "MAINTENANCE_DUE":
                record["status"] = "REGISTERED"
            touch(record)
    else:  # REJECTED
        filing["status"] = "REJECTED_OFFICE"
        touch(filing)
    return success(ser_maintenance_filing(filing), 200)
