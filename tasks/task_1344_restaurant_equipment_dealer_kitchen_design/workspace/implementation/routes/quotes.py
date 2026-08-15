"""Quote endpoints (PRD 3.3): create (PROVISIONAL), list/get, present,
accept (OCC + credit guard + acceptance cascade), reject."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_CUSTOMER_SUSPENDED,
    ERR_INVALID_REQUEST,
    ERR_LAYOUT_NOT_APPROVED,
    ERR_LAYOUT_NOT_FOUND,
    ERR_PROJECT_NOT_IN_DESIGN,
    ERR_PROJECT_NOT_QUOTED,
    ERR_QUOTE_NOT_DRAFT,
    ERR_QUOTE_NOT_OPEN,
    ERR_QUOTE_NOT_PRESENTED,
    ERR_STALE_PROJECT_VERSION,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import (
    check_project_ownership,
    paginate,
    resolve_customer,
    resolve_project,
    resolve_quote,
    serialize,
)
from services import pricing, workflow
from services.validate import json_body, req_str

bp = Blueprint("quotes", __name__)

QUOTE_READ_ROLES = ("PlatformAdmin", "ProjectManager", "SalesRep", "Customer")


@bp.route("/design-build-projects/<id>/quotes", methods=["POST"])
@require_roles("SalesRep")
def create_quote(id, _user_id=None, _role=None):
    project = resolve_project(id)
    body = json_body(required=True)
    layout_id = req_str(body, "layout_id")
    # Body FK must resolve within this project.
    layout = db.layouts.get(layout_id)
    if layout is None or layout["project_id"] != project["id"]:
        raise ApiError(
            ERR_LAYOUT_NOT_FOUND, HTTP_STATUS[ERR_LAYOUT_NOT_FOUND],
            "KitchenLayout not found",
        )
    if layout["status"] != "APPROVED":
        raise ApiError(
            ERR_LAYOUT_NOT_APPROVED, HTTP_STATUS[ERR_LAYOUT_NOT_APPROVED],
            "Quote create requires an APPROVED layout",
        )
    # PROVISIONAL variant: read the layout snapshot once and freeze it.
    snapshot = pricing.snapshot_lines(layout["id"])
    amounts = pricing.compute_quote_pricing(snapshot, project["health_jurisdiction"])
    siblings = [q for q in db.quotes.values() if q["project_id"] == project["id"]]
    revision_no = max([int(q["revision_no"]) for q in siblings], default=0) + 1
    quote = db.stamp_new({
        "project_id": project["id"],
        "layout_id": layout["id"],
        "equipment_subtotal_cents": amounts["equipment_subtotal_cents"],
        "freight_cents": amounts["freight_cents"],
        "installation_cents": amounts["installation_cents"],
        "startup_cents": amounts["startup_cents"],
        "grand_total_cents": amounts["grand_total_cents"],
        "variant": "PROVISIONAL",
        "revision_no": revision_no,
        "status": "DRAFT",
        "_snapshot": snapshot,
    })
    db.quotes[quote["id"]] = quote
    return success_object(serialize(quote), 201)


@bp.route("/design-build-projects/<id>/quotes", methods=["GET"])
@require_roles(*QUOTE_READ_ROLES)
def list_quotes(id, _user_id=None, _role=None):
    project = resolve_project(id)
    check_project_ownership(_user_id, _role, project)
    status = request.args.get("status")
    variant = request.args.get("variant")
    records = [q for q in db.quotes.values() if q["project_id"] == project["id"]]
    if status is not None:
        records = [q for q in records if q["status"] == status]
    if variant is not None:
        records = [q for q in records if q["variant"] == variant]
    return paginate(records)


@bp.route("/design-build-projects/<id>/quotes/<quoteId>", methods=["GET"])
@require_roles(*QUOTE_READ_ROLES)
def get_quote(id, quoteId, _user_id=None, _role=None):
    project = resolve_project(id)
    quote = resolve_quote(project, quoteId)
    check_project_ownership(_user_id, _role, project)
    return success_object(serialize(quote), 200)


@bp.route("/design-build-projects/<id>/quotes/<quoteId>/present", methods=["POST"])
@require_roles("SalesRep")
def present_quote(id, quoteId, _user_id=None, _role=None):
    project = resolve_project(id)
    quote = resolve_quote(project, quoteId)
    # Fixed order (PRD 3.3): quote DRAFT, layout APPROVED, project DESIGN.
    if quote["status"] != "DRAFT":
        raise ApiError(
            ERR_QUOTE_NOT_DRAFT, HTTP_STATUS[ERR_QUOTE_NOT_DRAFT],
            "Present requires Quote in DRAFT",
        )
    layout = db.layouts.get(quote["layout_id"])
    if layout is None or layout["status"] != "APPROVED":
        raise ApiError(
            ERR_LAYOUT_NOT_APPROVED, HTTP_STATUS[ERR_LAYOUT_NOT_APPROVED],
            "Present requires the referenced layout to be APPROVED",
        )
    if project["status"] != "DESIGN":
        raise ApiError(
            ERR_PROJECT_NOT_IN_DESIGN, HTTP_STATUS[ERR_PROJECT_NOT_IN_DESIGN],
            "Quote present requires Project in DESIGN",
        )
    # PROVISIONAL recompute reads the creation-time snapshot, not current items.
    amounts = pricing.compute_quote_pricing(quote["_snapshot"], project["health_jurisdiction"])
    quote.update(amounts)
    quote["status"] = "PRESENTED"
    db.touch(quote)
    project["status"] = "QUOTED"
    db.touch(project)
    return success_object(serialize(quote), 200)


@bp.route("/design-build-projects/<id>/quotes/<quoteId>/accept", methods=["POST"])
@require_roles("Customer")
def accept_quote(id, quoteId, _user_id=None, _role=None):
    project = resolve_project(id)
    quote = resolve_quote(project, quoteId)
    # Customer callers act on their own projects only.
    check_project_ownership(_user_id, _role, project)
    body = json_body(required=True)
    expected = body.get("expected_project_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "expected_project_version is required and must be an integer",
        )
    # State guards (PRD 3.3 order): quote PRESENTED, then project QUOTED.
    if quote["status"] != "PRESENTED":
        raise ApiError(
            ERR_QUOTE_NOT_PRESENTED, HTTP_STATUS[ERR_QUOTE_NOT_PRESENTED],
            "Accept requires Quote in PRESENTED",
        )
    if project["status"] != "QUOTED":
        raise ApiError(
            ERR_PROJECT_NOT_QUOTED, HTTP_STATUS[ERR_PROJECT_NOT_QUOTED],
            "Quote accept requires Project in QUOTED",
        )
    # Fiscal guardrails outrank the OCC version check (PRD 2.8).
    customer = resolve_customer(project["customer_id"])
    if customer["status"] != "ACTIVE":
        raise ApiError(
            ERR_CUSTOMER_SUSPENDED, HTTP_STATUS[ERR_CUSTOMER_SUSPENDED],
            "Quote accept requires Customer.status == ACTIVE",
        )
    if (
        int(customer["outstanding_exposure_cents"]) + int(quote["grand_total_cents"])
        > int(customer["credit_limit_cents"])
    ):
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED, HTTP_STATUS[ERR_CREDIT_LIMIT_EXCEEDED],
            "outstanding_exposure_cents + grand_total_cents would exceed credit_limit_cents",
        )
    if expected != project["version"]:
        raise ApiError(
            ERR_STALE_PROJECT_VERSION, HTTP_STATUS[ERR_STALE_PROJECT_VERSION],
            "expected_project_version does not match Project.version",
        )
    workflow.accept_quote(project, quote, customer)
    return success_object(serialize(quote), 200)


@bp.route("/design-build-projects/<id>/quotes/<quoteId>/reject", methods=["POST"])
@require_roles("Customer")
def reject_quote(id, quoteId, _user_id=None, _role=None):
    project = resolve_project(id)
    quote = resolve_quote(project, quoteId)
    check_project_ownership(_user_id, _role, project)
    if quote["status"] not in ("DRAFT", "PRESENTED"):
        raise ApiError(
            ERR_QUOTE_NOT_OPEN, HTTP_STATUS[ERR_QUOTE_NOT_OPEN],
            "Reject requires Quote in DRAFT or PRESENTED",
        )
    quote["status"] = "REJECTED"
    db.touch(quote)
    return success_object(serialize(quote), 200)
