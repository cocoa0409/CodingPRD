"""Supplier endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import (require_roles, get_json_body, require_string,
                        require_enum, parse_pagination, paginate)
from response import success_object, success_list
from services.calculations import stamp_new, touch, serialize, serialize_list

bp = Blueprint("suppliers", __name__)

RISK_TIERS = {"LOW", "MEDIUM", "HIGH"}


@bp.route("/suppliers", methods=["POST"])
def create_supplier():
    require_roles("PlatformAdmin")
    body = get_json_body()
    supplier_name = require_string(body, "supplier_name", max_len=200)
    fsma_facility_id = require_string(body, "fsma_facility_id")
    country_code = require_string(body, "country_code")
    risk_tier = require_enum(body, "risk_tier", RISK_TIERS)

    for s in store.suppliers.values():
        if s["fsma_facility_id"] == fsma_facility_id:
            raise errors.duplicate_key("fsma_facility_id already registered")

    sup = {
        "supplier_name": supplier_name,
        "fsma_facility_id": fsma_facility_id,
        "country_code": country_code,
        "risk_tier": risk_tier,
        "approval_state": "PROVISIONAL",
        "approved_ingredient_count": 0,
    }
    stamp_new(sup)
    store.suppliers[sup["id"]] = sup
    return success_object(serialize(sup), 201)


@bp.route("/suppliers/<id>/approve", methods=["POST"])
def approve_supplier(id):
    require_roles("QAApprover")
    sup = store.suppliers.get(id)
    if sup is None:
        raise errors.not_found("Supplier not found")
    if sup["approval_state"] == "APPROVED":
        raise errors.invalid_state("Supplier already APPROVED")
    if sup["approval_state"] != "PROVISIONAL":
        raise errors.invalid_state("Only PROVISIONAL suppliers can be approved")
    sup["approval_state"] = "APPROVED"
    touch(sup, status_changed=True)
    return success_object(serialize(sup), 200)


@bp.route("/suppliers/<id>/suspend", methods=["POST"])
def suspend_supplier(id):
    require_roles("QAApprover")
    sup = store.suppliers.get(id)
    if sup is None:
        raise errors.not_found("Supplier not found")
    if sup["approval_state"] != "APPROVED":
        raise errors.invalid_state("Only APPROVED suppliers can be suspended")
    sup["approval_state"] = "SUSPENDED"
    touch(sup, status_changed=True)
    return success_object(serialize(sup), 200)


@bp.route("/suppliers/<id>", methods=["GET"])
def get_supplier(id):
    require_roles("PlatformAdmin", "QAApprover", "QualityAnalyst",
                  "FormulationScientist", "ProductionPlanner")
    sup = store.suppliers.get(id)
    if sup is None:
        raise errors.not_found("Supplier not found")
    return success_object(serialize(sup), 200)


@bp.route("/suppliers/<id>/ingredient-approvals", methods=["GET"])
def list_supplier_ingredient_approvals(id):
    require_roles("PlatformAdmin", "QAApprover", "QualityAnalyst")
    sup = store.suppliers.get(id)
    if sup is None:
        raise errors.not_found("Supplier not found")
    limit, offset = parse_pagination()
    state_filter = request.args.get("approval_state")
    items = [a for a in store.supplier_ingredient_approvals.values()
             if a["supplier_id"] == id]
    items.sort(key=lambda e: (e["_created_at_dt"], e["id"]))
    if state_filter is not None:
        items = [a for a in items if a["approval_state"] == state_filter]
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total, 200)


def recompute_supplier_approved_count(supplier_id):
    sup = store.suppliers.get(supplier_id)
    if sup is None:
        return
    count = sum(1 for a in store.supplier_ingredient_approvals.values()
                if a["supplier_id"] == supplier_id and a["approval_state"] == "APPROVED")
    sup["approved_ingredient_count"] = count
