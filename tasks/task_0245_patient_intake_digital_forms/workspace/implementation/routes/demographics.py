"""DemographicsSyncJob routes (PRD §3.9). Idempotent by (session, idempotency_key)."""
from flask import Blueprint, request

import db
import serialize
from middleware import require_roles
from response import success, success_list
from services.common import touch, require_string
from services.lookups import get_session, get_sync_job
from services.pagination import paginate

bp = Blueprint("demographics", __name__)


@bp.route("/demographics-sync-jobs", methods=["POST"])
@require_roles("FrontDeskStaff")
def create_sync_job():
    body = request.get_json(silent=True) or {}
    intake_session_id = require_string(body, "intake_session_id")
    idempotency_key = require_string(body, "idempotency_key")
    synced_legal_name = require_string(body, "synced_legal_name")
    synced_phone = require_string(body, "synced_phone")
    session = get_session(intake_session_id)

    with db.LOCK:
        # Duplicate: same key already used on this session. No new job is
        # created and no patient mutation occurs; the original job is returned
        # instead of creating a new one, but with a SKIPPED_DUPLICATE status
        # (PRD §3.9). The stored original job is left untouched (still COMMITTED).
        for existing in db.demographics_sync_jobs.values():
            if existing["intake_session_id"] == intake_session_id and \
                    existing["idempotency_key"] == idempotency_key:
                view = serialize.demographics_sync_job(existing)
                view["status"] = "SKIPPED_DUPLICATE"
                return success(view, status=201)

        now = db.now_iso()
        job = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "intake_session_id": intake_session_id,
            "idempotency_key": idempotency_key,
            "synced_legal_name": synced_legal_name,
            "synced_phone": synced_phone,
            "status": "QUEUED",
        }
        db.demographics_sync_jobs[job["id"]] = job

        # Commit: overwrite patient demographics and bump demographics_revision.
        patient = db.patients[session["patient_id"]]
        patient["legal_name"] = synced_legal_name
        patient["phone"] = synced_phone
        patient["demographics_revision"] += 1
        touch(patient)
        job["status"] = "COMMITTED"
        touch(job)
    return success(serialize.demographics_sync_job(job), status=201)


@bp.route("/demographics-sync-jobs/<jid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_sync_job_route(jid):
    job = get_sync_job(jid)
    return success(serialize.demographics_sync_job(job), status=200)


@bp.route("/demographics-sync-jobs", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_sync_jobs():
    records = list(db.demographics_sync_jobs.values())
    val = request.args.get("intake_session_id")
    if val is not None:
        records = [r for r in records if r["intake_session_id"] == val]
    items, limit, offset, total = paginate(records, serialize.demographics_sync_job)
    return success_list(items, limit, offset, total)
