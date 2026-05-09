"""Project-related endpoints (incl. nested peer-reviews and budget-items)."""

from flask import Blueprint, g, request

from common import get_json_body, paginate_list, parse_pagination
from middleware import require_roles
from response import paginated, success
from services.budget_item import (
    create_budget_item,
    list_budget_items,
    serialize_item,
)
from services.peer_review import create_review, list_reviews, serialize_review
from services.project import (
    activate_project,
    approve_project,
    begin_closing,
    create_project,
    get_project_or_404,
    list_projects,
    reject_project,
    serialize_project,
    submit_project,
)


bp = Blueprint("projects", __name__)


@bp.route("/projects", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_project():
    body = get_json_body()
    p = create_project(body, g.user_id)
    return success(serialize_project(p), 201)


@bp.route("/projects", methods=["GET"])
@require_roles("Any")
def get_projects():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    funding_source = request.args.get("funding_source")
    items = list_projects(limit, offset, status=status, funding_source=funding_source)
    page, total = paginate_list(items, limit, offset)
    return paginated([serialize_project(p) for p in page], limit, offset, total)


@bp.route("/projects/<project_id>", methods=["GET"])
@require_roles("Any")
def get_project(project_id):
    p = get_project_or_404(project_id)
    return success(serialize_project(p), 200)


@bp.route("/projects/<project_id>/submit", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_submit_project(project_id):
    p = submit_project(project_id, g.user_id)
    return success(serialize_project(p), 200)


@bp.route("/projects/<project_id>/approve", methods=["POST"])
@require_roles("ResearchAdmin")
def post_approve_project(project_id):
    p = approve_project(project_id, g.user_id, g.user_role)
    return success(serialize_project(p), 200)


@bp.route("/projects/<project_id>/reject", methods=["POST"])
@require_roles("ResearchAdmin")
def post_reject_project(project_id):
    p = reject_project(project_id, g.user_id, g.user_role)
    return success(serialize_project(p), 200)


@bp.route("/projects/<project_id>/activate", methods=["POST"])
@require_roles("ResearchAdmin")
def post_activate_project(project_id):
    p = activate_project(project_id)
    return success(serialize_project(p), 200)


@bp.route("/projects/<project_id>/begin-closing", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_begin_closing(project_id):
    p = begin_closing(project_id, g.user_id)
    return success(serialize_project(p), 200)


# Peer reviews
@bp.route("/projects/<project_id>/peer-reviews", methods=["POST"])
@require_roles("PeerReviewer")
def post_peer_review(project_id):
    get_project_or_404(project_id)
    body = get_json_body()
    rec = create_review(project_id, body)
    return success(serialize_review(rec), 201)


@bp.route("/projects/<project_id>/peer-reviews", methods=["GET"])
@require_roles("Any")
def get_peer_reviews(project_id):
    get_project_or_404(project_id)
    limit, offset = parse_pagination()
    items = list_reviews(project_id)
    page, total = paginate_list(items, limit, offset)
    return paginated([serialize_review(r) for r in page], limit, offset, total)


# Budget items
@bp.route("/projects/<project_id>/budget-items", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_budget_item(project_id):
    project = get_project_or_404(project_id)
    body = get_json_body()
    bi = create_budget_item(project, g.user_id, body)
    return success(serialize_item(bi), 201)


@bp.route("/projects/<project_id>/budget-items", methods=["GET"])
@require_roles("Any")
def get_budget_items(project_id):
    get_project_or_404(project_id)
    limit, offset = parse_pagination()
    items = list_budget_items(project_id)
    page, total = paginate_list(items, limit, offset)
    return paginated([serialize_item(bi) for bi in page], limit, offset, total)
