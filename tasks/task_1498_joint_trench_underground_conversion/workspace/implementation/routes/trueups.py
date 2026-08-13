"""TrueUpRun endpoints: create (OCC on project version; supersedes the prior
PUBLISHED run; computes the final allocation waterfall) and transition
(publish with segregation of duties + invoice issuance; settle)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_TRUEUP_PREREQUISITES,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import trueup_run_view
from util import (
    get_json_body,
    get_or_404,
    parse_pagination,
    paginate,
    query_arg,
    require_field,
    require_int,
    require_string,
    sort_created,
)

bp = Blueprint("trueup_runs", __name__, url_prefix="/api/true-up-runs")

PM = "ProgramManager"
FA = "FinanceAnalyst"

TRANSITION_TARGETS = {"PUBLISHED", "SETTLED"}
TRUEUP_PARTICIPATION_STATUSES = {"INSTALLED", "BILLED", "SETTLED"}


@bp.route("", methods=["POST"])
@require_roles(FA)
def create_trueup_run(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    project_id = require_string(body, "project_id")
    project = db.projects[project_id]
    expected = require_int(body, "expected_project_version")
    if expected != project["version"]:
        raise_err(ERR_STALE_VERSION,
                  f"expected_project_version {expected} != current {project['version']}")

    if project["status"] != "RECONCILIATION":
        raise_err(ERR_TRUEUP_PREREQUISITES,
                  "true-up requires the project in RECONCILIATION")
    for s in domain.project_segments(project_id):
        if s["status"] != "CLOSED":
            raise_err(ERR_TRUEUP_PREREQUISITES,
                      "true-up requires every trench segment CLOSED")
    for p in domain.project_participations(project_id):
        if p["status"] != "WITHDRAWN" and p["status"] not in TRUEUP_PARTICIPATION_STATUSES:
            raise_err(ERR_TRUEUP_PREREQUISITES,
                      "every non-withdrawn participation must be "
                      "INSTALLED|BILLED|SETTLED")

    # Supersede cascade: the previously PUBLISHED run flips to SUPERSEDED and
    # its still-open invoices are voided.
    for run in domain.project_trueup_runs(project_id):
        if run["status"] == "PUBLISHED":
            run["status"] = "SUPERSEDED"
            touch(run)
            for inv in db.invoices.values():
                if inv["true_up_run_id"] == run["id"] and inv["status"] in {"ISSUED", "DISPUTED"}:
                    inv["status"] = "VOID"
                    touch(inv)

    lines, total_actual, credit_applied = domain.compute_trueup_lines(project)

    run = stamp_new({
        "project_id": project_id,
        "status": "DRAFT",
        "created_by_user_id": _user_id,
        "published_by_user_id": None,
        "total_actual_cost_cents": total_actual,
        "rule20_credit_applied_cents": credit_applied,
        "lines": lines,
    })
    db.trueup_runs[run["id"]] = run

    # Write the computed final share back onto each participation.
    for line in lines:
        part = db.participations.get(line["participation_id"])
        if part is not None and part.get("final_share_cents") != line["final_share_cents"]:
            part["final_share_cents"] = line["final_share_cents"]
            touch(part)

    project["latest_true_up_run_id"] = run["id"]
    touch(project)  # project version +1 (the OCC invalidation)
    return success_object(trueup_run_view(run), 201)


@bp.route("", methods=["GET"])
@require_roles(PM, FA)
def list_trueup_runs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.trueup_runs.values())
    project_id = query_arg("project_id")
    status = query_arg("status")
    if project_id:
        items = [r for r in items if r["project_id"] == project_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([trueup_run_view(r) for r in page], limit, offset, total)


@bp.route("/<rid>", methods=["GET"])
@require_roles(PM, FA)
def get_trueup_run(rid: str, _user_id: str, _role: str):
    return success_object(trueup_run_view(get_or_404(db.trueup_runs, rid, "TrueUpRun")))


@bp.route("/<rid>/transition", methods=["POST"])
@require_roles(PM)
def transition_trueup_run(rid: str, _user_id: str, _role: str):
    run = get_or_404(db.trueup_runs, rid, "TrueUpRun")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        from errors import ERR_VALIDATION
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    current = run["status"]
    if current in {"SETTLED", "SUPERSEDED"}:
        raise_err(ERR_INVALID_STATE, f"true-up run is terminal ({current})")

    if to == "PUBLISHED":
        if current != "DRAFT":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> PUBLISHED")
        # Segregation of duties: the publisher is neither the run creator nor
        # a submitter of any actual cost entry included in the run.
        if _user_id == run["created_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "publisher may not be the run creator")
        submitters = {e["submitted_by_user_id"]
                      for e in domain.project_cost_entries(run["project_id"])}
        if _user_id in submitters:
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "publisher submitted an actual cost entry included in the run")

        run["published_by_user_id"] = _user_id
        run["status"] = "PUBLISHED"
        touch(run)

        # Issue invoices in participation pinned order to every non-withdrawn
        # participation whose delta is positive.
        pid_to_part = db.participations
        ordered_lines = sorted(
            run["lines"],
            key=lambda l: (pid_to_part[l["participation_id"]]["sequence_order"],
                           pid_to_part[l["participation_id"]]["created_at"],
                           pid_to_part[l["participation_id"]].get("_seq", 0)),
        )
        for line in ordered_lines:
            if line["delta_cents"] <= 0:
                continue
            part = pid_to_part[line["participation_id"]]
            invoice = stamp_new({
                "true_up_run_id": run["id"],
                "participation_id": part["id"],
                "principal_cents": line["delta_cents"],
                "issued_on": domain.clock_str(),
                "due_on": domain.clock_plus_days(domain.INVOICE_DUE_DAYS),
                "status": "ISSUED",
                "paid_on": None,
            })
            db.invoices[invoice["id"]] = invoice
            if part["status"] == "INSTALLED":
                part["status"] = "BILLED"
                touch(part)

        project = db.projects[run["project_id"]]
        if project.get("latest_true_up_run_id") != run["id"]:
            project["latest_true_up_run_id"] = run["id"]
            touch(project)

    elif to == "SETTLED":
        if current != "PUBLISHED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> SETTLED")
        for inv in db.invoices.values():
            if inv["true_up_run_id"] == run["id"] and inv["status"] not in {"PAID", "VOID"}:
                raise_err(ERR_INVALID_STATE,
                          "every invoice of the run must be PAID|VOID")
        run["status"] = "SETTLED"
        touch(run)

    return success_object(trueup_run_view(run))
