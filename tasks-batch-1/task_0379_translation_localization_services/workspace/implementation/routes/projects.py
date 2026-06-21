"""Project + ProjectJob routes (PRD §3.2-§3.4, §3.7, §3.11, §3.12)."""
from decimal import Decimal
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import project_out, job_out, invoice_out, certificate_out
from services import calc
from services.helpers import get_json_body, require_fields, paginate_and_respond
from services.lookups import (get_project, get_client, get_rate_card, get_job,
                              jobs_of_project, invoices_of_project)
from services.workflow import cascade_cancel_project_jobs

bp = Blueprint("projects", __name__)

RUSH_TIERS = {"STANDARD", "EXPRESS", "SAME_DAY"}
CERT_MODES = {"NONE", "CERTIFIED", "NOTARIZED"}


def _owns_project(uid, role, project):
    if role == "Client" and uid != project["client_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Client may only access its own project")


# ---------------------------------------------------------------------------
# Project create / read / list
# ---------------------------------------------------------------------------
@bp.route("/projects", methods=["POST"])
def create_project():
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    body = get_json_body()
    require_fields(body, ["client_id", "rate_card_id", "name"])

    rush_tier = body.get("rush_tier", "STANDARD")
    cert_mode = body.get("certification_mode", "NONE")
    if rush_tier not in RUSH_TIERS:
        raise err("ERR_INVALID_REQUEST", "invalid rush_tier")
    if cert_mode not in CERT_MODES:
        raise err("ERR_INVALID_REQUEST", "invalid certification_mode")

    client = get_client(body["client_id"])
    rate_card = get_rate_card(body["rate_card_id"])

    if client["status"] != "ACTIVE":
        raise err("ERR_CLIENT_SUSPENDED", "Cannot create a project for a suspended client")

    p = common_fields()
    p.update({
        "client_id": body["client_id"],
        "rate_card_id": body["rate_card_id"],
        "name": body["name"],
        "rush_tier": rush_tier,
        "certification_mode": cert_mode,
        "pinned_base_rate_cents_per_word": rate_card["base_rate_cents_per_word"],
        "pinned_linguist_rate_cents_per_word": rate_card["linguist_rate_cents_per_word"],
        "source_locale": rate_card["source_locale"],
        "target_locale": rate_card["target_locale"],
        "quoted_total_cents": None,
        "status": "DRAFT",
    })
    db.projects[p["id"]] = p
    return success_object(project_out(p), 201)


@bp.route("/projects/<pid>", methods=["GET"])
def get_project_route(pid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Client"})
    p = get_project(pid)
    _owns_project(uid, role, p)
    return success_object(project_out(p), 200)


@bp.route("/projects", methods=["GET"])
def list_projects():
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable"})
    items = list(db.projects.values())
    client_f = request.args.get("client_id")
    rate_card_f = request.args.get("rate_card_id")
    status_f = request.args.get("status")
    if client_f is not None:
        items = [p for p in items if p["client_id"] == client_f]
    if rate_card_f is not None:
        items = [p for p in items if p["rate_card_id"] == rate_card_f]
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    return paginate_and_respond(items, project_out)


# ---------------------------------------------------------------------------
# Quote (DRAFT -> QUOTED) PRD §3.3
# ---------------------------------------------------------------------------
@bp.route("/projects/<pid>/quote", methods=["POST"])
def quote_project(pid):
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    p = get_project(pid)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Project must be DRAFT to quote")
    jobs = jobs_of_project(pid)
    if len(jobs) < 1:
        raise err("ERR_NO_JOBS", "Project has no jobs")
    total_words = 0
    for j in jobs:
        total_words += calc.job_total_source_words(j, "quoted")
    if total_words <= 0:
        raise err("ERR_EMPTY_ANALYSIS", "Quoted band words sum to zero")

    p["quoted_total_cents"] = calc.quote_estimate(
        jobs, p["pinned_base_rate_cents_per_word"], p["rush_tier"], p["certification_mode"])
    # each job's weighted_source_words computed from quoted bands
    for j in jobs:
        j["weighted_source_words"] = float(calc.job_weighted_words(j, "quoted"))
        touch(j)
    p["status"] = "QUOTED"
    touch(p)
    return success_object(project_out(p), 200)


# ---------------------------------------------------------------------------
# Approve (QUOTED -> APPROVED) PRD §3.4
# ---------------------------------------------------------------------------
@bp.route("/projects/<pid>/approve", methods=["POST"])
def approve_project(pid):
    uid, role = get_user_context()
    require_role(role, {"Client"})
    p = get_project(pid)
    # ownership check (priority 2)
    if uid != p["client_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Client may only approve its own project")
    if p["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Project must be QUOTED to approve")
    if p["quoted_total_cents"] is None:
        raise err("ERR_INVALID_STATE", "Project has no current quote")
    p["status"] = "APPROVED"
    touch(p)
    return success_object(project_out(p), 200)


# ---------------------------------------------------------------------------
# Cancel PRD §3.11
# ---------------------------------------------------------------------------
@bp.route("/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    p = get_project(pid)
    status = p["status"]
    if status not in ("DRAFT", "QUOTED", "APPROVED", "IN_PRODUCTION"):
        raise err("ERR_INVALID_STATE", "Project cannot be cancelled from %s" % status)
    if status in ("APPROVED", "IN_PRODUCTION"):
        for inv in invoices_of_project(pid):
            if inv["status"] in ("ISSUED", "PAID"):
                raise err("ERR_PROJECT_HAS_INVOICE",
                          "Project has an issued/paid invoice")
    cascade_cancel_project_jobs(p, "project cancelled")
    p["status"] = "CANCELLED"
    touch(p)
    return success_object(project_out(p), 200)


# ---------------------------------------------------------------------------
# ProjectJob create / list (PRD §3.2)
# ---------------------------------------------------------------------------
def _check_count(body, field):
    if field in body and body[field] is not None:
        v = body[field]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise err("ERR_INVALID_REQUEST", "%s must be a non-negative integer" % field)
        return v
    return 0


@bp.route("/projects/<pid>/jobs", methods=["POST"])
def create_job(pid):
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    p = get_project(pid)
    body = get_json_body()
    require_fields(body, ["filename"])
    if not isinstance(body["filename"], str):
        raise err("ERR_INVALID_REQUEST", "filename must be a string")
    nm = _check_count(body, "quoted_no_match_words")
    fz = _check_count(body, "quoted_fuzzy_words")
    rp = _check_count(body, "quoted_reps_words")
    cx = _check_count(body, "quoted_context_words")

    j = common_fields()
    j.update({
        "project_id": pid,
        "filename": body["filename"],
        "quoted_no_match_words": nm,
        "quoted_fuzzy_words": fz,
        "quoted_reps_words": rp,
        "quoted_context_words": cx,
        "actual_no_match_words": None,
        "actual_fuzzy_words": None,
        "actual_reps_words": None,
        "actual_context_words": None,
        "weighted_source_words": None,
        "revision_rounds": 0,
        "latest_qa_score": None,
        "status": "PENDING",
    })
    db.jobs[j["id"]] = j

    # Adding a job to a QUOTED project re-opens the estimate
    if p["status"] == "QUOTED":
        p["quoted_total_cents"] = None
        p["status"] = "DRAFT"
        touch(p)

    return success_object(job_out(j), 201)


@bp.route("/projects/<pid>/jobs", methods=["GET"])
def list_project_jobs(pid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Client"})
    p = get_project(pid)
    _owns_project(uid, role, p)
    items = jobs_of_project(pid)
    status_f = request.args.get("status")
    if status_f is not None:
        items = [j for j in items if j["status"] == status_f]
    return paginate_and_respond(items, job_out)


# ---------------------------------------------------------------------------
# Project invoices list (PRD §3.12)
# ---------------------------------------------------------------------------
@bp.route("/projects/<pid>/invoices", methods=["GET"])
def list_project_invoices(pid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Client"})
    p = get_project(pid)
    _owns_project(uid, role, p)
    items = invoices_of_project(pid)
    status_f = request.args.get("status")
    if status_f is not None:
        items = [i for i in items if i["status"] == status_f]
    return paginate_and_respond(items, invoice_out)
