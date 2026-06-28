"""RecordedDocument routes (PRD §3.5, §4). Get by id and same-day void
correction (compensating cascade)."""
from flask import Blueprint

import errors
from auth import require_auth, RECORDER, ALL_READERS
from db import db, touch, touch_no_version
from helpers import get_or_404, out
from response import ok

bp = Blueprint("recorded_documents", __name__)


def _charged_assessment_total(package_id):
    """The total_due_cents that fed the office daily ledger at record time.
    The FINALIZED assessment persists FINALIZED through PAID and RECORDED, so
    the same FINALIZED assessment that was charged is the one we reverse against
    (PRD §3.5 'that package's total_due_cents')."""
    for a in db.assessments.values():
        if a["package_id"] == package_id and a["status"] == "FINALIZED":
            return a["total_due_cents"]
    return 0


@bp.route("/recorded-documents/<did>", methods=["GET"])
def get_recorded_document(did):
    require_auth(ALL_READERS)
    doc = get_or_404(db.recorded_documents, did)
    return ok(out(doc))


@bp.route("/recorded-documents/<did>/void-correction", methods=["POST"])
def void_correction(did):
    require_auth([RECORDER])
    doc = get_or_404(db.recorded_documents, did)

    # State (priority 5)
    if doc["status"] != "RECORDED":
        raise errors.err(errors.ERR_INVALID_STATE, "Document is not RECORDED")

    package = db.packages[doc["package_id"]]
    office = db.offices[package["office_id"]]

    # Temporal (priority 9): same recording-day only.
    if doc["recorded_on"] != office["recording_date"]:
        raise errors.err(errors.ERR_CORRECTION_WINDOW_CLOSED,
                         "Void-correction only allowed on the recording day")

    doc["status"] = "CORRECTED_VOID"
    touch(doc)

    # Compensating reversal of the recording cascade.
    office["documents_in_current_book"] -= 1
    office["daily_collected_cents"] -= _charged_assessment_total(package["id"])

    indexed_count = 0
    for pe in db.party_entries.values():
        if pe["package_id"] == package["id"] and pe["status"] == "INDEXED":
            pe["status"] = "VOIDED"
            touch(pe)
            indexed_count += 1
    office["total_indexed_entries"] -= indexed_count
    touch(office)

    # instrument_number is deliberately NOT reclaimed; next_instrument_number
    # left unchanged (tamper-evident sequence, PRD §3.5).
    return ok(out(doc))
