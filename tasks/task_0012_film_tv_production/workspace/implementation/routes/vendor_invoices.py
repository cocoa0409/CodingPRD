"""Vendor invoice routes."""
from flask import Blueprint, g

import errors as E
from db import store, init_common, touch
from middleware import require_roles
from response import ok_object
from body import get_json_body, require_string, require_enum, require_int
from services.occ import check_version
from services.budget import find_category, recompute_posture, category_alert_state
from services.serializers import serialize_vendor_invoice


bp = Blueprint("vendor_invoices", __name__)


CATEGORY_CODES = {"CAST", "CREW", "EQUIPMENT", "LOCATION", "POST", "MISC"}


@bp.route("/vendor-invoices", methods=["POST"])
@require_roles("FinanceController")
def submit_invoice():
    body = get_json_body()
    with store.lock:
        production_id = require_string(body, "production_id")
        vendor_id = require_string(body, "vendor_id")
        category_code = require_enum(body, "category_code", CATEGORY_CODES)
        gross = require_int(body, "gross_cents", minv=0)
        prod = store.productions.get(production_id)
        if not prod:
            E.reference_mismatch("Production not found")
        if prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        rec = {
            "production_id": production_id,
            "vendor_id": vendor_id,
            "category_code": category_code,
            "gross_cents": gross,
            "deduction_cents": 0,
            "net_cents": 0,
            "status": "SUBMITTED",
        }
        init_common(rec)
        store.vendor_invoices[rec["id"]] = rec
        return ok_object(serialize_vendor_invoice(rec), http_status=201)


def _get_invoice(iid):
    v = store.vendor_invoices.get(iid)
    if not v:
        E.not_found(f"VendorInvoice {iid} not found")
    return v


@bp.route("/vendor-invoices/<iid>/reconcile", methods=["POST"])
@require_roles("FinanceController")
def reconcile_invoice(iid):
    body = get_json_body()
    with store.lock:
        v = _get_invoice(iid)
        check_version(v, body)
        prod = store.productions.get(v["production_id"])
        if not prod:
            E.not_found("Production not found")
        if v["status"] != "SUBMITTED":
            E.invalid_state("reconcile requires SUBMITTED")
        # Posture FROZEN blocks non-wrap operations; reconcile is not wrap-progression
        # but it's needed during normal ops & during WRAP_PENDING because wrap requires PAID/DISPUTED
        if prod.get("posture") == "FROZEN" and prod.get("status") != "WRAP_PENDING":
            E.posture_blocked("Production posture is FROZEN")
        # All linked equipment in DAMAGED/LOST for this vendor must have been RETURNED
        for eq in store.equipment.values():
            if eq.get("vendor_id") != v["vendor_id"]:
                continue
            if eq["status"] in {"DAMAGED", "LOST"}:
                E.invalid_state("Linked equipment still DAMAGED/LOST; reconcile blocked")
        v["net_cents"] = v["gross_cents"] - v.get("deduction_cents", 0)
        v["status"] = "RECONCILED"
        touch(v)
        # BudgetCategory(category_code) committed_cents -= net_cents; actual_cents += net_cents
        cat = find_category(v["production_id"], v["category_code"])
        if cat is not None:
            cat["committed_cents"] = cat.get("committed_cents", 0) - v["net_cents"]
            cat["actual_cents"] = cat.get("actual_cents", 0) + v["net_cents"]
            cat["alert_state"] = category_alert_state(cat)
            touch(cat)
        recompute_posture(prod, actor_user_id=g.user_id)
        return ok_object(serialize_vendor_invoice(v))


@bp.route("/vendor-invoices/<iid>/pay", methods=["POST"])
@require_roles("FinanceController")
def pay_invoice(iid):
    body = get_json_body()
    with store.lock:
        v = _get_invoice(iid)
        check_version(v, body)
        prod = store.productions.get(v["production_id"])
        if not prod:
            E.not_found("Production not found")
        if v["status"] != "RECONCILED":
            E.invalid_state("pay requires RECONCILED")
        if prod["status"] not in {"IN_PRODUCTION", "WRAP_PENDING"}:
            E.invalid_state("Production must be IN_PRODUCTION or WRAP_PENDING to pay")
        v["status"] = "PAID"
        touch(v)
        # Production.spent_cents += net_cents
        prod["spent_cents"] = prod.get("spent_cents", 0) + v.get("net_cents", 0)
        touch(prod)
        recompute_posture(prod, actor_user_id=g.user_id)
        return ok_object(serialize_vendor_invoice(v))


@bp.route("/vendor-invoices/<iid>/dispute", methods=["POST"])
@require_roles("FinanceController")
def dispute_invoice(iid):
    body = get_json_body()
    with store.lock:
        v = _get_invoice(iid)
        check_version(v, body)
        if v["status"] != "SUBMITTED":
            E.invalid_state("dispute requires SUBMITTED")
        v["status"] = "DISPUTED"
        touch(v)
        return ok_object(serialize_vendor_invoice(v))
