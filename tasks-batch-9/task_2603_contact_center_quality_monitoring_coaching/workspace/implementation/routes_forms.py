"""Evaluation forms and their weighted behaviours (PRD 3.1)."""
import re
from decimal import Decimal

from flask import Blueprint

import shape
from authz import endpoint
from calc import form_behaviors
from common import (DB, body, created, fail, new_row, now_iso, ok, ok_list, q2,
                    require, rows, sorted_rows, touch)
from listing import page
from serial import view, views

bp = Blueprint("forms", __name__)

CODE_RE = re.compile(r"^[A-Z_]{2,24}$")
AUTO_FAIL_POLICIES = ("ZERO_TOTAL", "COMPLIANCE_SECTION_ZERO")
FORM_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")
READ_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor", "ComplianceAuditor")


@bp.post("/evaluation-forms")
@endpoint("QualityManager")
def create_form():
    payload = body()
    name = shape.want_string(payload, "name", min_len=1, max_len=120)
    version_label = shape.want_string(payload, "version_label", min_len=1, max_len=20)
    auto_fail_policy = shape.want_enum(payload, "auto_fail_policy", AUTO_FAIL_POLICIES)
    min_compliance = shape.want_int(payload, "min_compliance_item_score",
                                    required=False, default=3, minimum=1)

    if "behaviors" not in payload or payload["behaviors"] is None:
        shape.bad("field 'behaviors' is required and may not be null")
    raw_behaviors = payload["behaviors"]
    if not isinstance(raw_behaviors, list):
        shape.bad("field 'behaviors' must be an array")

    parsed = []
    for element in raw_behaviors:
        if not isinstance(element, dict):
            shape.bad("every entry of 'behaviors' must be an object")
        code = shape.want_string(element, "code")
        if not CODE_RE.match(code):
            shape.bad("behaviour 'code' must match ^[A-Z_]{2,24}$")
        parsed.append({
            "code": code,
            "label": shape.want_string(element, "label"),
            "weight_pct": q2(shape.want_decimal(element, "weight_pct",
                                                exclusive_min=Decimal("0.00"),
                                                maximum=Decimal("100.00"))),
            "compliance_critical": shape.want_bool(element, "compliance_critical",
                                                   default=False),
            "auto_fail_on_violation": shape.want_bool(element, "auto_fail_on_violation",
                                                      default=False),
            "max_points": shape.want_int(element, "max_points", required=False,
                                         default=5, choices=(3, 4, 5)),
            "allows_not_applicable": shape.want_bool(element, "allows_not_applicable",
                                                     default=False),
            "guidance_text": shape.want_string(element, "guidance_text"),
        })

    # version_label is unique among forms sharing the same name (PRD 3.1).
    for form in rows("forms"):
        if form["name"] == name and form["version_label"] == version_label:
            shape.bad("version_label must be unique among forms sharing the same name")

    total = q2(sum((b["weight_pct"] for b in parsed), Decimal(0)))
    if total != Decimal("100.00"):
        fail("ERR_WEIGHTS_NOT_100",
             "behaviour weight_pct values must sum to exactly 100.00")
    compliance_count = sum(1 for b in parsed if b["compliance_critical"])
    if compliance_count < 1:
        fail("ERR_NO_COMPLIANCE_BEHAVIOR",
             "at least one behaviour must be compliance_critical")
    codes = [b["code"] for b in parsed]
    if len(set(codes)) != len(codes):
        fail("ERR_DUPLICATE_BEHAVIOR_CODE",
             "behaviour codes must be unique within the form")

    form = new_row("forms", {
        "name": name,
        "version_label": version_label,
        "status": "DRAFT",
        "min_compliance_item_score": min_compliance,
        "auto_fail_policy": auto_fail_policy,
        "behavior_weight_total": total,
        "compliance_behavior_count": compliance_count,
        "guidance_version": 1,
        "activated_at": None,
        "retired_at": None,
    })
    for entry in parsed:
        fields = dict(entry)
        fields["form_id"] = form["id"]
        fields["guidance_version"] = 1
        new_row("behaviors", fields)
    return created(view(form))


@bp.post("/evaluation-forms/<form_id>/activate")
@endpoint("QualityManager")
def activate_form(form_id):
    form = require("forms", form_id, "ERR_FORM_NOT_FOUND")
    if form["status"] != "DRAFT":
        fail("ERR_FORM_NOT_DRAFT", "only a DRAFT form may be activated")
    if form["behavior_weight_total"] != Decimal("100.00"):
        fail("ERR_WEIGHTS_NOT_100", "behavior_weight_total must equal exactly 100.00")
    if form["compliance_behavior_count"] < 1:
        fail("ERR_NO_COMPLIANCE_BEHAVIOR",
             "the form carries no compliance_critical behaviour")
    critical = [b for b in form_behaviors(form["id"]) if b["compliance_critical"]]
    if critical:
        smallest = min(b["max_points"] for b in critical)
        if form["min_compliance_item_score"] > smallest:
            shape.bad("min_compliance_item_score exceeds the smallest max_points "
                      "among the compliance-critical behaviours")
    form["status"] = "ACTIVE"
    form["activated_at"] = now_iso()
    touch(form)
    return ok(view(form))


@bp.post("/evaluation-forms/<form_id>/retire")
@endpoint("QualityManager")
def retire_form(form_id):
    form = require("forms", form_id, "ERR_FORM_NOT_FOUND")
    if form["status"] != "ACTIVE":
        fail("ERR_FORM_NOT_ACTIVE", "only an ACTIVE form may be retired")
    form["status"] = "RETIRED"
    form["retired_at"] = now_iso()
    touch(form)
    return ok(view(form))


@bp.get("/evaluation-forms/<form_id>")
@endpoint(*READ_ROLES)
def read_form(form_id):
    return ok(view(require("forms", form_id, "ERR_FORM_NOT_FOUND")))


@bp.get("/evaluation-forms/<form_id>/behaviors")
@endpoint(*READ_ROLES)
def list_behaviors(form_id):
    limit, offset = shape.pagination()
    form = require("forms", form_id, "ERR_FORM_NOT_FOUND")
    items = form_behaviors(form["id"])
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)


@bp.get("/evaluation-forms")
@endpoint(*READ_ROLES)
def list_forms():
    limit, offset = shape.pagination()
    status = shape.query_enum("status", FORM_STATUSES)
    items = sorted_rows(rows("forms"))
    if status is not None:
        items = [f for f in items if f["status"] == status]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
