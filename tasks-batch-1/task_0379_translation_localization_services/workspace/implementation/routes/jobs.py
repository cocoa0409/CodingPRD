"""ProjectJob action routes: get, submit-translation, deliver, certificate,
and job sub-lists (assignments, qa-reports). PRD §3.6, §3.7, §3.12."""
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import job_out, assignment_out, qa_report_out, certificate_out
from services import calc
from services.helpers import get_json_body, require_fields, paginate_and_respond, append_ledger_entry
from services.lookups import (get_job, get_project, assignments_of_job,
                              active_translator_assignment, active_reviewer_assignment,
                              jobs_of_project)
from services.workflow import maybe_bubble_project_to_delivered

bp = Blueprint("jobs", __name__)


def _job_owner_visible(uid, role, job):
    """Ownership for entity-backed roles reading a job."""
    project = db.projects.get(job["project_id"])
    if role == "Client":
        if project is None or uid != project["client_id"]:
            raise err("ERR_FORBIDDEN_FOR_ROLE", "Client may only read its own jobs")
    elif role in ("Translator", "Reviewer"):
        # visible if the linguist holds any assignment on this job
        held = any(a["linguist_id"] == uid for a in assignments_of_job(job["id"]))
        if not held:
            raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own jobs")


@bp.route("/jobs/<jid>", methods=["GET"])
def get_job_route(jid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Translator", "Reviewer", "Client"})
    j = get_job(jid)
    _job_owner_visible(uid, role, j)
    return success_object(job_out(j), 200)


# ---------------------------------------------------------------------------
# submit-translation (TRANSLATING/REVISION -> IN_QA) PRD §3.6
# ---------------------------------------------------------------------------
@bp.route("/jobs/<jid>/submit-translation", methods=["POST"])
def submit_translation(jid):
    uid, role = get_user_context()
    require_role(role, {"Translator"})
    j = get_job(jid)

    if j["status"] not in ("TRANSLATING", "REVISION"):
        raise err("ERR_INVALID_STATE", "Job must be TRANSLATING or REVISION to submit")

    translator = active_translator_assignment(jid)
    if (translator is None or translator["linguist_id"] != uid
            or translator["status"] not in ("ACCEPTED", "IN_PROGRESS")):
        raise err("ERR_NOT_ASSIGNED_TRANSLATOR", "Acting linguist is not the job's active translator")

    from_revision = (j["status"] == "REVISION")

    # A reviewer must be lined up (IN_PROGRESS) — required on first submission.
    if not from_revision:
        reviewer = active_reviewer_assignment(jid)
        if reviewer is None or reviewer["status"] != "IN_PROGRESS":
            raise err("ERR_NO_REVIEWER_ASSIGNED", "No IN_PROGRESS reviewer assignment on this job")

    if from_revision:
        j["revision_rounds"] = j["revision_rounds"] + 1
    j["status"] = "IN_QA"
    touch(j)  # increments version
    return success_object(job_out(j), 200)


# ---------------------------------------------------------------------------
# deliver (QA_PASSED -> DELIVERED) PRD §3.7
# ---------------------------------------------------------------------------
@bp.route("/jobs/<jid>/deliver", methods=["POST"])
def deliver_job(jid):
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    j = get_job(jid)
    body = get_json_body()
    # body well-formedness (priority 4) checked before state? Per PRD §2.6 state is
    # priority 5 (after body). But deliver's required-fields are body validation.
    required = ["actual_no_match_words", "actual_fuzzy_words",
                "actual_reps_words", "actual_context_words"]
    require_fields(body, required)
    actuals = {}
    for f in required:
        v = body[f]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise err("ERR_INVALID_REQUEST", "%s must be a non-negative integer" % f)
        actuals[f] = v

    if j["status"] != "QA_PASSED":
        raise err("ERR_INVALID_STATE", "Job must be QA_PASSED to deliver")

    if sum(actuals.values()) <= 0:
        raise err("ERR_EMPTY_ANALYSIS", "Actual band words sum to zero")

    project = db.projects.get(j["project_id"])

    # record actuals
    j["actual_no_match_words"] = actuals["actual_no_match_words"]
    j["actual_fuzzy_words"] = actuals["actual_fuzzy_words"]
    j["actual_reps_words"] = actuals["actual_reps_words"]
    j["actual_context_words"] = actuals["actual_context_words"]
    j["weighted_source_words"] = float(calc.job_weighted_words(j, "actual"))

    # finalize the TRANSLATOR assignment payout
    translator = active_translator_assignment(jid)
    if translator is not None:
        provisional = translator["payout_cents"]
        final_payout = calc.linguist_payout_final(
            j, project["pinned_linguist_rate_cents_per_word"], j["latest_qa_score"])
        translator["payout_cents"] = final_payout
        translator["payout_finalized"] = True
        translator["status"] = "DELIVERED"
        touch(translator)
        delta = final_payout - provisional
        linguist = db.linguists.get(translator["linguist_id"])
        if linguist is not None:
            append_ledger_entry(linguist, translator["id"], "FINAL_ADJUST", delta,
                                "final payout delta at delivery")

    # mint a DeliveryCertificate if certification_mode != NONE
    if project["certification_mode"] != "NONE":
        _mint_certificate(project, j)

    j["status"] = "DELIVERED"
    touch(j)  # increments version

    # bubble up project to DELIVERED
    maybe_bubble_project_to_delivered(project)

    return success_object(job_out(j), 200)


def _mint_certificate(project, job):
    """Mint a DeliveryCertificate. certificate_number is sequential per project
    in job created_at ASC order among the project's certified deliveries."""
    total_source_words = calc.job_total_source_words(job, "actual")
    pages = calc.page_count(total_source_words)

    cert = common_fields()
    cert.update({
        "job_id": job["id"],
        "certification_mode": project["certification_mode"],
        "page_count": pages,
        "certificate_number": None,  # assigned below
    })
    db.certificates[cert["id"]] = cert

    # (Re)assign certificate_number for every certificate of this project in
    # job created_at ASC order among the project's certified deliveries.
    project_certs = [c for c in db.certificates.values()
                     if db.jobs.get(c["job_id"], {}).get("project_id") == project["id"]]

    def _job_created_at(c):
        jrec = db.jobs.get(c["job_id"], {})
        return (jrec.get("created_at", ""), c["job_id"])

    project_certs.sort(key=_job_created_at)
    for idx, c in enumerate(project_certs, start=1):
        c["certificate_number"] = idx
    return cert


@bp.route("/jobs/<jid>/certificate", methods=["GET"])
def list_job_certificate(jid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Client"})
    j = get_job(jid)
    if role == "Client":
        project = db.projects.get(j["project_id"])
        if project is None or uid != project["client_id"]:
            raise err("ERR_FORBIDDEN_FOR_ROLE", "Client may only read its own job certificate")
    items = [c for c in db.certificates.values() if c["job_id"] == jid]
    return paginate_and_respond(items, certificate_out)


# ---------------------------------------------------------------------------
# Job sub-lists
# ---------------------------------------------------------------------------
@bp.route("/jobs/<jid>/assignments", methods=["GET"])
def list_job_assignments(jid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Translator", "Reviewer"})
    j = get_job(jid)
    items = assignments_of_job(jid)
    if role in ("Translator", "Reviewer"):
        items = [a for a in items if a["linguist_id"] == uid]
    role_f = request.args.get("role")
    status_f = request.args.get("status")
    if role_f is not None:
        items = [a for a in items if a["role"] == role_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    return paginate_and_respond(items, assignment_out)


@bp.route("/jobs/<jid>/qa-reports", methods=["GET"])
def list_job_qa_reports(jid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Reviewer", "Translator"})
    j = get_job(jid)
    if role in ("Translator", "Reviewer"):
        held = any(a["linguist_id"] == uid for a in assignments_of_job(jid))
        if not held:
            raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own job QA reports")
    items = [q for q in db.qa_reports.values() if q["job_id"] == jid]
    outcome_f = request.args.get("outcome")
    if outcome_f is not None:
        items = [q for q in items if q["outcome"] == outcome_f]
    return paginate_and_respond(items, qa_report_out)
