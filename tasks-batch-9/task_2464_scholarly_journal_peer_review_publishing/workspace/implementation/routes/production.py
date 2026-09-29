"""Production workflow: typesetting slot, content dimension, deposit, publication."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
import validate as v
from auth import authorise
from db import now_iso, ordered, store, touch
from errors import ApiError
from response import list_response, object_response
from routes.manuscripts import find_manuscript

bp = Blueprint("production", __name__)

CONTENT_STAGES = ("COPYEDITING", "TYPESETTING", "PROOF_SENT", "PROOF_APPROVED", "TERMINATED")
REPOSITORIES = ("CLOCKSS", "PORTICO", "LOCKSS")
JOB_READ_ROLES = ("SystemAdmin", "EditorInChief", "ProductionStaff", "Author")
MANUSCRIPT_JOB_READ_ROLES = (
    "SystemAdmin",
    "EditorInChief",
    "HandlingEditor",
    "ProductionStaff",
    "Author",
)
# declared content-dimension steps
CONTENT_ADVANCE = {"COPYEDITING": ("TYPESETTING",), "TYPESETTING": ("PROOF_SENT",)}


def find_job(jid):
    job = store.production_jobs.get(jid)
    if job is None:
        raise ApiError("ERR_PRODUCTION_JOB_NOT_FOUND")
    return job


@bp.post("/production-jobs/<jid>/typeset-slot")
def book_slot(jid):
    authorise("ProductionStaff")
    job = find_job(jid)
    data = v.body()
    slot_start_text = v.req_date(data, "slot_start")
    slot_end_text = v.req_date(data, "slot_end")
    expected = v.req_int(data, "expected_production_job_version")

    slot_start = v.parse_date(slot_start_text)
    slot_end = v.parse_date(slot_end_text)
    if slot_end < slot_start:
        raise ApiError("ERR_INVALID_INTERVAL")

    if expected != int(job["version"]):
        raise ApiError("ERR_STALE_PRODUCTION_JOB_VERSION")

    svc.guard_job_terminal(job)
    if job["content_stage"] not in ("COPYEDITING", "TYPESETTING"):
        raise ApiError("ERR_INVALID_PRODUCTION_STAGE")

    manuscript = store.manuscripts.get(job["manuscript_id"])
    journal = calc.journal_of(manuscript)
    if calc.typeset_slot_blockers(job, manuscript, journal, slot_start, slot_end):
        raise ApiError("ERR_TYPESET_SLOT_CONFLICT")

    job["slot_start"] = slot_start_text
    job["slot_end"] = slot_end_text
    touch(job)
    return object_response(ser.production_job_out(job), 200)


@bp.post("/production-jobs/<jid>/content-advance")
def content_advance(jid):
    authorise("ProductionStaff")
    job = find_job(jid)
    data = v.body()
    to_stage = v.req_enum(data, "to_stage", CONTENT_STAGES)

    svc.guard_job_terminal(job)
    if to_stage not in CONTENT_ADVANCE.get(job["content_stage"], ()):
        raise ApiError("ERR_INVALID_PRODUCTION_STAGE")
    if to_stage == "TYPESETTING" and not job.get("slot_start"):
        raise ApiError("ERR_SLOT_NOT_BOOKED")

    manuscript = store.manuscripts.get(job["manuscript_id"])
    if manuscript is None or manuscript["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")

    job["content_stage"] = to_stage
    if to_stage == "PROOF_SENT":
        job["proof_round"] = int(job["proof_round"]) + 1
    touch(job)
    return object_response(ser.production_job_out(job), 200)


@bp.post("/production-jobs/<jid>/proof-approval")
def proof_approval(jid):
    actor = authorise("Author")
    job = find_job(jid)
    data = v.body()
    approved = v.req_bool(data, "approved")
    v.opt_string(data, "proof_comments")

    manuscript = store.manuscripts.get(job["manuscript_id"])
    if manuscript is None or manuscript["corresponding_author_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    svc.guard_job_terminal(job)
    if job["content_stage"] != "PROOF_SENT":
        raise ApiError("ERR_INVALID_PRODUCTION_STAGE")
    if manuscript["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")

    if approved:
        job["content_stage"] = "PROOF_APPROVED"
    else:
        journal = calc.journal_of(manuscript)
        if int(job["proof_round"]) >= int(journal["max_proof_rounds"]):
            raise ApiError("ERR_PROOF_ROUND_LIMIT_REACHED")
        job["content_stage"] = "TYPESETTING"
    touch(job)
    return object_response(ser.production_job_out(job), 200)


@bp.post("/production-jobs/<jid>/archival-deposit")
def archival_deposit(jid):
    authorise("ProductionStaff")
    job = find_job(jid)
    data = v.body()
    repository = v.req_enum(data, "archival_repository", REPOSITORIES)
    reference = v.req_string(data, "deposit_reference")

    svc.guard_job_terminal(job)
    if job["clearance_stage"] == "DEPOSIT_CONFIRMED":
        raise ApiError("ERR_INVALID_PRODUCTION_STAGE")
    if job["clearance_stage"] != "FEE_CLEARED":
        raise ApiError("ERR_DEPOSIT_NOT_READY")

    manuscript = store.manuscripts.get(job["manuscript_id"])
    if manuscript is None or manuscript["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_DEPOSIT_NOT_READY")

    job["clearance_stage"] = "DEPOSIT_CONFIRMED"
    job["archival_repository"] = repository
    job["deposit_reference"] = reference
    touch(job)
    return object_response(ser.production_job_out(job), 200)


@bp.post("/production-jobs/<jid>/publication")
def publication(jid):
    authorise("ProductionStaff")
    job = find_job(jid)
    data = v.body()
    publication_date = v.req_date(data, "publication_date")
    issue_label = v.opt_string(data, "issue_label")

    svc.guard_job_terminal(job)
    if job["content_stage"] != "PROOF_APPROVED" or job["clearance_stage"] != "DEPOSIT_CONFIRMED":
        raise ApiError("ERR_PRODUCTION_STAGE_NOT_READY")

    manuscript = store.manuscripts.get(job["manuscript_id"])
    if manuscript is None or manuscript["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")
    if calc.has_unresolved_case(manuscript["id"]):
        raise ApiError("ERR_ETHICS_HOLD")
    if calc.has_issued_invoice(manuscript["id"]):
        raise ApiError("ERR_UNPAID_APC_INVOICE")

    journal = calc.journal_of(manuscript)
    if issue_label is not None:
        job["issue_label"] = issue_label
    label = job.get("issue_label") or ""

    manuscript["status"] = "PUBLISHED"
    manuscript["publication_date"] = publication_date
    manuscript["embargo_end_date"] = calc.embargo_end_date(
        manuscript["oa_license"], publication_date, int(journal["embargo_months"])
    )
    manuscript["doi"] = "%s/%s.%04d" % (
        journal["doi_prefix"],
        label,
        int(manuscript["journal_sequence_number"]),
    )
    touch(manuscript)

    job["indexing_status"] = "INDEXED"
    job["published_at"] = now_iso()
    touch(job)

    journal["published_article_count"] = int(journal["published_article_count"]) + 1
    touch(journal)
    return object_response(ser.production_job_out(job), 200)


# ==========================================================================
# reads
# ==========================================================================
@bp.get("/production-jobs/<jid>")
def get_job(jid):
    authorise(*JOB_READ_ROLES)
    return object_response(ser.production_job_out(find_job(jid)), 200)


@bp.get("/manuscripts/<mid>/production-jobs")
def list_manuscript_jobs(mid):
    authorise(*MANUSCRIPT_JOB_READ_ROLES)
    find_manuscript(mid)
    limit, offset = v.pagination()
    rows = ordered(
        [j for j in store.production_jobs.values() if j["manuscript_id"] == mid]
    )
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.production_job_out), limit, offset, len(rows))
