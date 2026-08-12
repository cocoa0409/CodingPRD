"""AttestationRecord endpoints: list, get, respond (ProviderRep)."""

from datetime import timedelta

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.cascades import recompute_cycle_counters

bp = Blueprint("records", __name__)

RECORD_STATUSES = {"PENDING", "ATTESTED", "CORRECTION_REQUESTED", "NON_RESPONSIVE", "CANCELLED"}

CORRECTION_SLA_HOURS = 72


@bp.route("/network/attestation-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_records(user_id, role):
    limit, offset = helpers.get_pagination()
    cycle_id = helpers.query_str("cycle_id")
    listing_id = helpers.query_str("listing_id")
    status = helpers.query_enum("status", RECORD_STATUSES)
    items = list(db.records.values())
    if cycle_id is not None:
        items = [r for r in items if r["cycle_id"] == cycle_id]
    if listing_id is not None:
        items = [r for r in items if r["listing_id"] == listing_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_record(r) for r in page], limit, offset, total)


@bp.route("/network/attestation-records/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_record(user_id, role, rid):
    rec = db.records.get(rid)
    if rec is None:
        raise errors.err_record_not_found()
    return success_object(helpers.ser_record(rec))


def _spawn_correction(listing_id, complaint_id, changes, submitted_by):
    sla = db.clock_now + timedelta(hours=CORRECTION_SLA_HOURS)
    corr = {
        "listing_id": listing_id, "complaint_id": complaint_id,
        "changes": changes, "submitted_by_user_id": submitted_by,
        "sla_due_at": helpers._dt_to_iso(sla), "is_late": False,
        "status": "SUBMITTED", "verified_at": None, "verified_by_user_id": None,
    }
    helpers.stamp_new(corr)
    db.corrections[corr["id"]] = corr
    return corr


@bp.route("/network/attestation-records/<rid>/respond", methods=["POST"])
@require_roles("ProviderRep")
def respond_record(user_id, role, rid):
    rec = db.records.get(rid)
    if rec is None:
        raise errors.err_record_not_found()
    # ownership: ProviderRep X-User-ID must equal the record's listing's provider_id
    listing = db.listings.get(rec["listing_id"])
    owner_provider_id = listing["provider_id"] if listing is not None else None
    if user_id != owner_provider_id:
        raise errors.err_not_owner()
    cycle = db.cycles.get(rec["cycle_id"])
    cycle_status = cycle["status"] if cycle is not None else None
    respondable = (
        (rec["status"] == "PENDING" and cycle_status in ("OPEN", "OUTREACH"))
        or (rec["status"] == "NON_RESPONSIVE" and cycle_status == "CLOSED")
    )
    if not respondable:
        raise errors.err_record_not_respondable()
    body = helpers.get_body()
    data_accurate = helpers.req_bool(body, "data_accurate")
    if data_accurate:
        rec["status"] = "ATTESTED"
    else:
        corrected = body.get("corrected_payload")
        if not isinstance(corrected, dict) or len(corrected) == 0:
            raise errors.err_invalid("corrected_payload must be present and non-empty")
        rec["status"] = "CORRECTION_REQUESTED"
        _spawn_correction(rec["listing_id"], None, corrected, user_id)
    rec["responded_at"] = helpers.now_iso()
    helpers.touch(rec)
    if cycle is not None:
        recompute_cycle_counters(cycle)
    return success_object(helpers.ser_record(rec))
