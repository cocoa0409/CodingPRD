"""Read-only ledger entry logs (PRD 2.10): AFUDC, depreciation, amortization."""
from flask import Blueprint, request

from services.core import (
    serialize_afudc_entry, serialize_depreciation_entry, serialize_amortization_entry,
)
from routes.helpers import list_response, get_one

bp = Blueprint("entries", __name__)


@bp.route("/ucp/afudc-entries/<entry_id>", methods=["GET"])
def get_afudc_entry(entry_id):
    return get_one("afudc_entries", serialize_afudc_entry, entry_id)


@bp.route("/ucp/afudc-entries", methods=["GET"])
def list_afudc_entries():
    filters = {
        "work_order_id": request.args.get("work_order_id"),
        "accounting_period_id": request.args.get("accounting_period_id"),
        "status": request.args.get("status"),
    }
    return list_response("afudc_entries", serialize_afudc_entry, filters)


@bp.route("/ucp/depreciation-entries/<entry_id>", methods=["GET"])
def get_depreciation_entry(entry_id):
    return get_one("depreciation_entries", serialize_depreciation_entry, entry_id)


@bp.route("/ucp/depreciation-entries", methods=["GET"])
def list_depreciation_entries():
    filters = {
        "fixed_asset_unit_id": request.args.get("fixed_asset_unit_id"),
        "accounting_period_id": request.args.get("accounting_period_id"),
        "status": request.args.get("status"),
    }
    return list_response("depreciation_entries", serialize_depreciation_entry, filters)


@bp.route("/ucp/amortization-entries/<entry_id>", methods=["GET"])
def get_amortization_entry(entry_id):
    return get_one("amortization_entries", serialize_amortization_entry, entry_id)


@bp.route("/ucp/amortization-entries", methods=["GET"])
def list_amortization_entries():
    filters = {
        "regulatory_asset_id": request.args.get("regulatory_asset_id"),
        "accounting_period_id": request.args.get("accounting_period_id"),
        "status": request.args.get("status"),
    }
    return list_response("amortization_entries", serialize_amortization_entry, filters)
