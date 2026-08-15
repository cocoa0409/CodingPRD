"""TranslationJob endpoints (PRD §3.4): queue, assign, submit, review, cancel."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CONFIDENTIALITY_NOT_CURRENT,
    ERR_CONTRACT_CEILING_EXCEEDED,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DEPARTMENT_NONCOMPLIANT,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_DOCUMENT_RETIRED,
    ERR_FORBIDDEN_ROLE,
    ERR_INTERPRETER_NOT_FOUND,
    ERR_INTERPRETER_SUSPENDED,
    ERR_INVALID_TRANSITION,
    ERR_JOB_NOT_FOUND,
    ERR_REVIEWER_TIER_INSUFFICIENT,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_TRANSLATOR_TIER_INSUFFICIENT,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_endpoint
from services.core import (
    JOB_COMMITTED_STATES,
    confidentiality_current,
    contract_committed,
    contract_spent,
    department_posture,
    maybe_exhaust_contract,
    touch,
    translation_final_cost_cents,
)
from services.serializers import serialize_job
from util import CLOCK, new_id, next_seq
from validate import (
    get_body,
    reject_unknown_fields,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("translation_jobs", __name__)


@bp.post("/translation-jobs")
def create_job():
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(
        body, {"document_id", "vendor_contract_id", "target_language_code", "word_count", "rush"})
    document_id = req_str(body, "document_id")
    vendor_contract_id = req_str(body, "vendor_contract_id")
    target_language_code = req_str(body, "target_language_code")
    word_count = req_int(body, "word_count", positive=True)
    rush = body.get("rush", False)
    if not isinstance(rush, bool):
        raise_error(ERR_VALIDATION, "rush must be a boolean")

    # Priority 4: body FKs in declared order (document before contract).
    doc = require_path("vital_documents", document_id, ERR_DOCUMENT_NOT_FOUND)
    contract = require_path("vendor_contracts", vendor_contract_id, ERR_CONTRACT_NOT_FOUND)

    # Priority 5: document ACTIVE, then contract ACTIVE.
    if doc["status"] != "ACTIVE":
        raise_error(ERR_DOCUMENT_RETIRED, "document is RETIRED")
    if contract["status"] != "ACTIVE":
        raise_error(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE")

    # Priority 6: owning department must not be NONCOMPLIANT.
    if department_posture(doc["department_id"]) == "NONCOMPLIANT":
        raise_error(ERR_DEPARTMENT_NONCOMPLIANT, "department posture is NONCOMPLIANT")

    # Priority 9 (fiscal, last): provisional must fit the ceiling, equality allowed.
    provisional = word_count * contract["translation_per_word_cents"]
    if contract_committed(contract["id"]) + contract_spent(contract["id"]) + provisional > contract["ceiling_cents"]:
        raise_error(ERR_CONTRACT_CEILING_EXCEEDED, "provisional commitment would exceed the contract ceiling")

    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "document_id": document_id,
        "vendor_contract_id": vendor_contract_id,
        "target_language_code": target_language_code,
        "word_count": word_count,
        "rush": rush,
        "provisional_cost_cents": provisional,
        "translator_id": None,
        "reviewer_id": None,
        "submitted_word_count": None,
        "revision_count": 0,
        "final_cost_cents": None,
        "superseded_by_job_id": None,
        "status": "QUEUED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["translation_jobs"][rec["id"]] = rec
    touch(contract)  # committed_cents rose derivationally
    return success_object(serialize_job(rec), status=201)


@bp.get("/translation-jobs")
def list_jobs():
    filters = {
        "document_id": request.args.get("document_id"),
        "vendor_contract_id": request.args.get("vendor_contract_id"),
        "translator_id": request.args.get("translator_id"),
        "reviewer_id": request.args.get("reviewer_id"),
        "superseded_by_job_id": request.args.get("superseded_by_job_id"),
        "status": request.args.get("status"),
    }
    return list_endpoint("translation_jobs", serialize_job, filters)


@bp.get("/translation-jobs/<rid>")
def get_job(rid):
    return get_one("translation_jobs", rid, ERR_JOB_NOT_FOUND, serialize_job)


@bp.post("/translation-jobs/<rid>/assign")
def assign_job(rid):
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"translator_id"})
    translator_id = req_str(body, "translator_id")

    job = require_path("translation_jobs", rid, ERR_JOB_NOT_FOUND)
    interp = require_path("interpreters", translator_id, ERR_INTERPRETER_NOT_FOUND)

    if job["status"] != "QUEUED":
        raise_error(ERR_INVALID_TRANSITION, "only a QUEUED job may be assigned")
    # Fixed assign check order (PRD §3.4).
    if interp["status"] != "ACTIVE":
        raise_error(ERR_INTERPRETER_SUSPENDED, "interpreter is not ACTIVE")
    if not confidentiality_current(interp):
        raise_error(ERR_CONFIDENTIALITY_NOT_CURRENT, "interpreter confidentiality agreement is not current")
    if job["target_language_code"] not in interp["language_codes"]:
        raise_error(ERR_VALIDATION, "interpreter does not cover the job's target_language_code")
    if interp["tier"] not in ("REGISTERED", "CERTIFIED"):
        raise_error(ERR_TRANSLATOR_TIER_INSUFFICIENT, "translation requires tier REGISTERED or CERTIFIED")

    job["translator_id"] = translator_id
    job["status"] = "IN_TRANSLATION"
    touch(job)
    return success_object(serialize_job(job))


@bp.post("/translation-jobs/<rid>/submit-translation")
def submit_translation(rid):
    caller = authorized(["Interpreter"])
    body = get_body()
    reject_unknown_fields(body, {"submitted_word_count"})
    submitted_word_count = req_int(body, "submitted_word_count", positive=True)

    job = require_path("translation_jobs", rid, ERR_JOB_NOT_FOUND)
    if job["status"] != "IN_TRANSLATION":
        raise_error(ERR_INVALID_TRANSITION, "only an IN_TRANSLATION job accepts submitted work")
    if caller.user_id != job["translator_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the assigned translator may submit this job's work")

    job["submitted_word_count"] = submitted_word_count
    job["status"] = "QUALITY_REVIEW"
    touch(job)
    return success_object(serialize_job(job))


@bp.post("/translation-jobs/<rid>/review")
def review_job(rid):
    caller = authorized(["QualityReviewer"])
    body = get_body()
    reject_unknown_fields(body, {"decision"})
    decision = req_str(body, "decision")
    if decision not in ("APPROVE", "REQUEST_REVISION"):
        raise_error(ERR_VALIDATION, "decision must be APPROVE or REQUEST_REVISION")

    job = require_path("translation_jobs", rid, ERR_JOB_NOT_FOUND)
    # Entity-backed caller resolution (priority 4).
    reviewer = require_path("interpreters", caller.user_id, ERR_INTERPRETER_NOT_FOUND)

    if job["status"] != "QUALITY_REVIEW":
        raise_error(ERR_INVALID_TRANSITION, "only a QUALITY_REVIEW job may be reviewed")
    if reviewer["tier"] != "CERTIFIED":
        raise_error(ERR_REVIEWER_TIER_INSUFFICIENT, "quality review requires a CERTIFIED reviewer")
    if reviewer["id"] == job["translator_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES_VIOLATION, "the translator may not review their own job")

    if decision == "REQUEST_REVISION":
        job["revision_count"] += 1
        job["status"] = "IN_TRANSLATION"
        touch(job)
        return success_object(serialize_job(job))

    # APPROVE: price the final variant, settle ledgers, then cascades.
    contract = db["vendor_contracts"][job["vendor_contract_id"]]
    doc = db["vital_documents"].get(job["document_id"])
    codes_before = set()
    if doc is not None:
        from services.core import document_translated_language_codes
        codes_before = set(document_translated_language_codes(doc["id"]))

    job["reviewer_id"] = reviewer["id"]
    job["final_cost_cents"] = translation_final_cost_cents(
        job["submitted_word_count"], job["revision_count"], job["rush"],
        contract["translation_per_word_cents"])
    job["status"] = "APPROVED"
    touch(job)
    # Contract exhaustion (>= 90% spent) with its QUEUED-job cancellation cascade.
    maybe_exhaust_contract(contract)
    # Ledger moved (committed -> spent, possibly EXHAUSTED): one bump.
    touch(contract)
    # Department spend rose derivationally.
    if doc is not None:
        dept = db["departments"].get(doc["department_id"])
        if dept is not None:
            touch(dept)
    # Supersede the previously APPROVED job for the same (document, language).
    for other in db["translation_jobs"].values():
        if (other["id"] != job["id"] and other["document_id"] == job["document_id"]
                and other["target_language_code"] == job["target_language_code"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            other["superseded_by_job_id"] = job["id"]
            touch(other)
    # Document coverage list is derivational; bump when its content changed.
    if doc is not None:
        if set(document_translated_language_codes(doc["id"])) != codes_before:
            touch(doc)
    return success_object(serialize_job(job))


@bp.post("/translation-jobs/<rid>/cancel")
def cancel_job(rid):
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    job = require_path("translation_jobs", rid, ERR_JOB_NOT_FOUND)
    if job["status"] not in JOB_COMMITTED_STATES:
        raise_error(ERR_INVALID_TRANSITION, "only a non-terminal job may be cancelled")

    job["status"] = "CANCELLED"
    touch(job)
    contract = db["vendor_contracts"].get(job["vendor_contract_id"])
    if contract is not None:
        touch(contract)  # provisional commitment released derivationally
    return success_object(serialize_job(job))
