"""Routes: /fcra/orders*."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_role, current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_forbidden, err_validation_failed
from core.pagination import paginate, parse_pagination
from core.serializers import (
    serialize_audit_event,
    serialize_flow,
    serialize_order,
)
from core.store import store
from core.utils import lock
from services.audit_service import events_for_order
from services.order_service import (
    cancel_order,
    create_order,
    issue_final_adverse,
    issue_pre_adverse,
    request_rework,
    resume_verification,
    start_verification,
)
from services.validations import (
    get_candidate_or_404,
    get_order_or_404,
)


bp = Blueprint("orders", __name__)


# POST /fcra/orders
@bp.route("/fcra/orders", methods=["POST"])
@require_roles("Recruiter")
def post_order():
    body = get_json_body()
    candidate_id = body.get("candidate_id")
    if not isinstance(candidate_id, str) or candidate_id == "":
        raise err_validation_failed("candidate_id is required.")
    candidate = get_candidate_or_404(candidate_id)
    with lock():
        order = create_order(
            candidate=candidate,
            body=body,
            actor_role=current_role(),
            actor_user_id=current_user_id(),
        )
    return success_response(serialize_order(order), status=201)


# GET /fcra/orders/{orderId}
@bp.route("/fcra/orders/<order_id>", methods=["GET"])
@require_roles("Recruiter", "Adjudicator", "Candidate")
def get_order(order_id):
    order = get_order_or_404(order_id)
    if current_role() == "Candidate" and order["candidate_id"] != current_user_id():
        raise err_forbidden("Candidates may only read their own orders.")
    return success_response(serialize_order(order))


# GET /fcra/orders
@bp.route("/fcra/orders", methods=["GET"])
@require_roles("Recruiter", "Adjudicator")
def list_orders():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    cand_filter = request.args.get("candidate_id")
    rows = list(store.orders.values())
    if status_filter is not None:
        rows = [r for r in rows if r.get("status") == status_filter]
    if cand_filter is not None:
        rows = [r for r in rows if r.get("candidate_id") == cand_filter]
    rows.sort(key=lambda r: r["created_at"])
    sliced, pmeta = paginate(rows, limit, offset)
    return success_response(
        [serialize_order(r) for r in sliced],
        response_type="array",
        pagination=pmeta,
    )


# POST /fcra/orders/{orderId}/start-verification
@bp.route("/fcra/orders/<order_id>/start-verification", methods=["POST"])
@require_roles("Recruiter")
def post_start_verification(order_id):
    order = get_order_or_404(order_id)
    with lock():
        start_verification(
            order, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_order(order))


# POST /fcra/orders/{orderId}/cancel
@bp.route("/fcra/orders/<order_id>/cancel", methods=["POST"])
@require_roles("Recruiter")
def post_cancel_order(order_id):
    order = get_order_or_404(order_id)
    with lock():
        cancel_order(
            order, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_order(order))


# POST /fcra/orders/{orderId}/pre-adverse
@bp.route("/fcra/orders/<order_id>/pre-adverse", methods=["POST"])
@require_roles("Adjudicator")
def post_pre_adverse(order_id):
    order = get_order_or_404(order_id)
    with lock():
        flow = issue_pre_adverse(
            order, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_flow(flow))


# POST /fcra/orders/{orderId}/final-adverse
@bp.route("/fcra/orders/<order_id>/final-adverse", methods=["POST"])
@require_roles("Adjudicator")
def post_final_adverse(order_id):
    order = get_order_or_404(order_id)
    with lock():
        issue_final_adverse(
            order, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_order(order))


# POST /fcra/orders/{orderId}/request-rework
@bp.route("/fcra/orders/<order_id>/request-rework", methods=["POST"])
@require_roles("Adjudicator")
def post_request_rework(order_id):
    order = get_order_or_404(order_id)
    body = get_json_body()
    with lock():
        request_rework(
            order, body, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_order(order))


# POST /fcra/orders/{orderId}/resume-verification
@bp.route("/fcra/orders/<order_id>/resume-verification", methods=["POST"])
@require_roles("Adjudicator")
def post_resume_verification(order_id):
    order = get_order_or_404(order_id)
    with lock():
        resume_verification(
            order, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_order(order))


# GET /fcra/orders/{orderId}/audit-trail
@bp.route("/fcra/orders/<order_id>/audit-trail", methods=["GET"])
@require_roles("Recruiter", "Adjudicator")
def get_audit_trail(order_id):
    order = get_order_or_404(order_id)
    events = events_for_order(order["id"])
    events.sort(key=lambda e: e["created_at"])
    return success_response(
        [serialize_audit_event(e) for e in events], response_type="array"
    )
