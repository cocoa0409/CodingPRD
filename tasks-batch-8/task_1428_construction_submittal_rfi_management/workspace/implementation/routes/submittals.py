"""Submittal routes: GET/PATCH, deferral, release, void, close."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, PROJECT_ENGINEER, PROJECT_MANAGER, require_roles
from db import store
from errors import (
    deferral_not_pending,
    invalid_request,
    open_rfi_blocks_close,
    project_not_found,
    submittal_not_approved,
    submittal_not_distributed,
    submittal_not_found,
    submittal_terminal,
)
from respond import success
from serialize import ser_submittal
from services import (
    affected_subcontractor_ids,
    create_distribution_records,
    find_lli_for_submittal,
    recompute_lli_with_events,
    require_active,
)
from store_ops import (
    json_body,
    opt_date,
    opt_str,
    paginate,
    req_enum,
    req_field,
    sorted_by_creation,
    touch,
)

bp = Blueprint("submittals", __name__)


def get_submittal_or_404(submittal_id):
    s = store.submittals.get(submittal_id)
    if s is None:
        raise submittal_not_found()
    return s


@bp.route("/v1/projects/<projectId>/submittals", methods=["GET"])
def list_project_submittals(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [s for s in store.submittals.values() if s["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_submittal(s) for s in page], response_type="array", pagination=pagination)


@bp.route("/v1/submittals", methods=["GET"])
def list_submittals():
    require_roles(ALL_ROLES)
    items = list(store.submittals.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [s for s in items if s["project_id"] == project_id]
    spec_section_id = request.args.get("spec_section_id")
    if spec_section_id:
        items = [s for s in items if s["spec_section_id"] == spec_section_id]
    review_status = request.args.get("review_status")
    if review_status:
        items = [s for s in items if s["review_status"] == review_status]
    is_long_lead = request.args.get("is_long_lead")
    if is_long_lead is not None:
        target = is_long_lead.lower() == "true"
        items = [s for s in items if s["is_long_lead"] == target]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_submittal(s) for s in page], response_type="array", pagination=pagination)


@bp.route("/v1/submittals/<submittalId>", methods=["GET"])
def get_submittal(submittalId):
    require_roles(ALL_ROLES)
    sub = get_submittal_or_404(submittalId)
    return success(ser_submittal(sub))


@bp.route("/v1/submittals/<submittalId>", methods=["PATCH"])
def patch_submittal(submittalId):
    require_roles([PROJECT_ENGINEER])
    sub = get_submittal_or_404(submittalId)
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if sub["review_status"] in ("CLOSED", "VOID"):
        raise submittal_terminal()
    data = json_body()
    if "required_on_site_date" in data:
        new_date = opt_date(data, "required_on_site_date", None)
        sub["required_on_site_date"] = new_date
        section = store.spec_sections.get(sub["spec_section_id"])
        if section is not None:
            calc.recompute_submittal_dates(sub, section, project)
        # Mirror onto LLI and recompute
        lli = find_lli_for_submittal(sub["id"])
        if lli is not None:
            lli["required_on_site_date"] = new_date
            if lli["status"] not in ("DELIVERED", "CANCELLED"):
                recompute_lli_with_events(lli, sub)
            touch(lli)
    touch(sub)
    return success(ser_submittal(sub))


@bp.route("/v1/submittals/<submittalId>/request-deferral", methods=["POST"])
def request_deferral(submittalId):
    require_roles([PROJECT_ENGINEER])
    sub = get_submittal_or_404(submittalId)
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    data = json_body()
    req_field(data, "reason")
    if sub["deferral_status"] != "NONE":
        raise deferral_not_pending()
    if sub["review_status"] not in ("REGISTERED", "RETURNED_NEEDS_RESUBMIT"):
        raise submittal_not_approved("Submittal review_status does not permit deferral request")
    sub["deferral_status"] = "DEFERRAL_REQUESTED"
    touch(sub)
    return success(ser_submittal(sub))


@bp.route("/v1/submittals/<submittalId>/decide-deferral", methods=["POST"])
def decide_deferral(submittalId):
    require_roles([PROJECT_MANAGER])
    sub = get_submittal_or_404(submittalId)
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    data = json_body()
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    if sub["deferral_status"] != "DEFERRAL_REQUESTED":
        raise deferral_not_pending()
    if decision == "APPROVE":
        sub["deferral_status"] = "DEFERRED_APPROVED"
        # Halve the linked LLI priority score on next recompute.
        lli = find_lli_for_submittal(sub["id"])
        if lli is not None and lli["status"] not in ("DELIVERED", "CANCELLED"):
            calc.recompute_lli(lli, sub)
            touch(lli)
    else:
        sub["deferral_status"] = "NONE"
    touch(sub)
    return success(ser_submittal(sub))


@bp.route("/v1/submittals/<submittalId>/release-for-construction", methods=["POST"])
def release_for_construction(submittalId):
    require_roles([PROJECT_ENGINEER])
    sub = get_submittal_or_404(submittalId)
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if sub["review_status"] != "APPROVED":
        raise submittal_not_approved()
    section = store.spec_sections.get(sub["spec_section_id"])
    subs = affected_subcontractor_ids(project["id"], section, sub["id"])
    if not subs:
        # Vacuous all-acknowledged: straight to DISTRIBUTED
        sub["review_status"] = "DISTRIBUTED"
    else:
        create_distribution_records(project["id"], "SUBMITTAL", sub["id"], subs)
        sub["review_status"] = "RELEASED"
    touch(sub)
    return success(ser_submittal(sub))


@bp.route("/v1/submittals/<submittalId>/void", methods=["POST"])
def void_submittal(submittalId):
    require_roles([PROJECT_MANAGER])
    sub = get_submittal_or_404(submittalId)
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if sub["review_status"] in ("CLOSED", "VOID"):
        raise submittal_terminal()
    if sub["review_status"] in ("RELEASED", "DISTRIBUTED"):
        raise submittal_not_approved("Voiding a RELEASED/DISTRIBUTED submittal is not permitted")
    # Cascade: supersede open revisions; decrement reviewer counts for UNDER_REVIEW
    for rev in store.revisions.values():
        if rev["submittal_id"] != sub["id"]:
            continue
        if rev["status"] == "UNDER_REVIEW":
            reviewer = store.reviewers.get(rev.get("reviewer_id"))
            if reviewer is not None:
                reviewer["open_review_count"] = max(0, reviewer["open_review_count"] - 1)
                touch(reviewer)
            rev["status"] = "SUPERSEDED"
            touch(rev)
        elif rev["status"] == "SUBMITTED":
            rev["status"] = "SUPERSEDED"
            touch(rev)
    # Cancel the LLI if non-terminal
    lli = find_lli_for_submittal(sub["id"])
    if lli is not None and lli["status"] not in ("DELIVERED", "CANCELLED"):
        lli["status"] = "CANCELLED"
        touch(lli)
    sub["expediting_status"] = "NOT_REQUIRED"
    sub["review_status"] = "VOID"
    touch(sub)
    return success(ser_submittal(sub))


@bp.route("/v1/submittals/<submittalId>/close", methods=["POST"])
def close_submittal(submittalId):
    require_roles([PROJECT_ENGINEER])
    sub = get_submittal_or_404(submittalId)
    project = store.projects.get(sub["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if sub["review_status"] != "DISTRIBUTED":
        raise submittal_not_distributed()
    # Block on OPEN/ROUTED RFIs referencing this submittal
    for r in store.rfis.values():
        if r["project_id"] == project["id"] and r.get("submittal_id") == sub["id"]:
            if r["status"] in ("OPEN", "ROUTED"):
                raise open_rfi_blocks_close()
    sub["review_status"] = "CLOSED"
    touch(sub)
    return success(ser_submittal(sub))
