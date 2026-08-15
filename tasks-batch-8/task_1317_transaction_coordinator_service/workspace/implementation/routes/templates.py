"""Checklist templates."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, mint, touch, pub, pub_list
from response import ok_object, ok_list

bp = Blueprint("templates", __name__)


def _validate_milestone_defs(defs):
    for entry in defs:
        if not isinstance(entry, dict):
            E.raise_err(E.ERR_INVALID_REQUEST, "milestone_defs entries must be objects")
        if set(entry.keys()) - {"name", "offset_days", "mandatory"}:
            E.raise_err(E.ERR_INVALID_REQUEST, "Unknown field in milestone_defs entry")
        if "name" not in entry or not isinstance(entry["name"], str):
            E.raise_err(E.ERR_INVALID_REQUEST, "milestone_defs entry requires a string name")
        if "offset_days" not in entry or not isinstance(entry["offset_days"], int) \
                or isinstance(entry["offset_days"], bool):
            E.raise_err(E.ERR_INVALID_REQUEST, "milestone_defs entry requires integer offset_days")
        if "mandatory" not in entry or not isinstance(entry["mandatory"], bool):
            E.raise_err(E.ERR_INVALID_REQUEST, "milestone_defs entry requires boolean mandatory")


def _validate_doc_types(types):
    for t in types:
        if not isinstance(t, str) or t not in mw.DOC_TYPES:
            E.raise_err(E.ERR_INVALID_REQUEST, f"Invalid doc_type: {t}")


@bp.post("/tc/checklist-templates")
def create_template():
    uid, role = mw.auth()
    mw.require_roles(role, {"SystemAdmin"})
    data = mw.body()
    mw.validate_shape(data, [
        ("state_code", "string", True, mw.state_code_ok),
        ("contract_type", "enum", True, mw.CONTRACT_TYPES),
        ("milestone_defs", "array", True, _validate_milestone_defs),
        ("required_doc_types", "array", True, _validate_doc_types),
    ])
    rec = mint({
        "state_code": data["state_code"],
        "contract_type": data["contract_type"],
        "milestone_defs": data["milestone_defs"],
        "required_doc_types": data["required_doc_types"],
        "status": "DRAFT",
        "template_version": 1,
    })
    store.templates[rec["id"]] = rec
    return ok_object(pub("template", rec), 201)


@bp.get("/tc/checklist-templates/<templateId>")
def get_template(templateId):
    mw.auth()
    rec = mw.get_or_404("template", templateId)
    return ok_object(pub("template", rec))


@bp.get("/tc/checklist-templates")
def list_templates():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.templates.values())
    recs = mw.filter_eq(recs, "state_code", request.args.get("state_code"))
    recs = mw.filter_eq(recs, "contract_type", request.args.get("contract_type"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("template", page), limit, offset, total)


@bp.post("/tc/checklist-templates/<templateId>/publish")
def publish_template(templateId):
    uid, role = mw.auth()
    mw.require_roles(role, {"SystemAdmin"})
    rec = mw.get_or_404("template", templateId)
    if rec["status"] != "DRAFT":
        E.raise_err(E.ERR_TEMPLATE_INVALID_STATE, "Only a DRAFT template can be published")
    for t in store.templates.values():
        if t["id"] != rec["id"] and t["status"] == "ACTIVE" \
                and t["state_code"] == rec["state_code"] \
                and t["contract_type"] == rec["contract_type"]:
            E.raise_err(E.ERR_TEMPLATE_ALREADY_ACTIVE,
                        "Another ACTIVE template exists for this (state_code, contract_type)")
    if not rec["milestone_defs"]:
        E.raise_err(E.ERR_INVALID_REQUEST, "milestone_defs must be non-empty to publish")
    rec["status"] = "ACTIVE"
    rec["template_version"] += 1
    touch(rec)
    return ok_object(pub("template", rec))


@bp.post("/tc/checklist-templates/<templateId>/retire")
def retire_template(templateId):
    uid, role = mw.auth()
    mw.require_roles(role, {"SystemAdmin"})
    rec = mw.get_or_404("template", templateId)
    if rec["status"] != "ACTIVE":
        E.raise_err(E.ERR_TEMPLATE_INVALID_STATE, "Only an ACTIVE template can be retired")
    rec["status"] = "RETIRED"
    touch(rec)
    return ok_object(pub("template", rec))
