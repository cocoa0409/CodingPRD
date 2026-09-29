"""Checklist templates and their inspection points (PRD 3.1)."""
from flask import Blueprint

import enums
import helpers as h
import serializers as ser
from db import db, new_id
from errors import ApiError

bp = Blueprint("catalog", __name__)

READ_ROLES = (
    "ProgramAdministrator",
    "ProgramAuditor",
    "DealerPrincipal",
    "InspectionTechnician",
)


def template_or_404(template_id):
    row = db.templates.get(template_id)
    if row is None:
        raise ApiError("ERR_TEMPLATE_NOT_FOUND", "No checklist template with that id.")
    return row


def template_items(template_id):
    return [i for i in db.checklist_items.values() if i["template_id"] == template_id]


@bp.route("/checklist-templates", methods=["POST"])
def create_template():
    h.authorize(("ProgramAdministrator",))
    body = h.body_dict()
    code = h.f_string(body, "code")
    effective_from = h.f_date(body, "effective_from")
    for existing in db.templates.values():
        if existing["code"] == code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", "A checklist template already uses that code."
            )
    row = h.new_common(
        {
            "id": new_id(),
            "code": code,
            "effective_from": effective_from,
            "status": "DRAFT",
            "published_at": None,
        }
    )
    db.templates[row["id"]] = row
    return h.object_response(ser.checklist_template(row), 201)


@bp.route("/checklist-templates/<template_id>", methods=["GET"])
def read_template(template_id):
    h.authorize(READ_ROLES)
    return h.object_response(ser.checklist_template(template_or_404(template_id)))


@bp.route("/checklist-templates/<template_id>/items", methods=["POST"])
def add_item(template_id):
    h.authorize(("ProgramAdministrator",))
    body = h.body_dict()
    item_code = h.f_string(body, "item_code")
    category = h.f_enum(body, "category", enums.ITEM_CATEGORIES)
    severity = h.f_enum(body, "severity", enums.SEVERITIES)
    pass_criteria = h.f_string(body, "pass_criteria")
    min_measure = h.f_number(body, "min_measure", required=False)
    max_measure = h.f_number(body, "max_measure", required=False)
    reconditioning_allowed = h.f_bool(
        body, "reconditioning_allowed", required=False, default=True
    )
    max_cost = h.f_int(
        body, "max_reconditioning_cost_cents", required=False, default=100000, minimum=0
    )

    template = template_or_404(template_id)
    if template["status"] != "DRAFT":
        raise ApiError(
            "ERR_TEMPLATE_NOT_DRAFT", "Inspection points may only be added to a DRAFT template."
        )
    for existing in template_items(template_id):
        if existing["item_code"] == item_code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                "That item_code already exists on this template.",
            )

    row = h.new_evidence(
        {
            "id": new_id(),
            "template_id": template_id,
            "item_code": item_code,
            "category": category,
            "severity": severity,
            "pass_criteria": pass_criteria,
            "min_measure": min_measure,
            "max_measure": max_measure,
            "reconditioning_allowed": reconditioning_allowed,
            "max_reconditioning_cost_cents": max_cost,
        }
    )
    db.checklist_items[row["id"]] = row
    h.touch(template)
    return h.object_response(ser.checklist_item(row), 201)


@bp.route("/checklist-templates/<template_id>/items", methods=["GET"])
def list_items(template_id):
    h.authorize(READ_ROLES)
    category = h.q_enum("category", enums.ITEM_CATEGORIES)
    severity = h.q_enum("severity", enums.SEVERITIES)
    limit, offset = h.pagination()
    template_or_404(template_id)
    rows = template_items(template_id)
    if category:
        rows = [r for r in rows if r["category"] == category]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    return h.paged(rows, limit, offset, ser.checklist_item)


@bp.route("/checklist-templates/<template_id>/publish", methods=["POST"])
def publish_template(template_id):
    h.authorize(("ProgramAdministrator",))
    template = template_or_404(template_id)
    if template["status"] != "DRAFT":
        raise ApiError("ERR_TEMPLATE_NOT_DRAFT", "Only a DRAFT template may be published.")
    items = template_items(template_id)
    if len(items) < 1 or not any(i["severity"] == "CRITICAL" for i in items):
        raise ApiError(
            "ERR_TEMPLATE_NOT_PUBLISHABLE",
            "A template needs at least one point and at least one CRITICAL point.",
        )

    superseded = [
        t
        for t in db.templates.values()
        if t["id"] != template_id
        and t["status"] == "PUBLISHED"
        and t["effective_from"] <= template["effective_from"]
    ]
    template["status"] = "PUBLISHED"
    template["published_at"] = db.clock
    h.touch(template)
    for other in superseded:
        other["status"] = "RETIRED"
        h.touch(other)
    return h.object_response(ser.checklist_template(template))
