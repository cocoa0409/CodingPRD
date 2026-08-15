"""MaintenanceObligation: read, list, report/confirm/dismiss violation."""
from flask import Blueprint

import serializers
from db import STORE
from errors import ApiError
from helpers import (
    apply_filters, get_obligation, paginate, sorted_created, touch,
)
from middleware import ANY_ROLE, require_roles
from response import ok, ok_list
from services import ledger

bp = Blueprint("obligations", __name__)


@bp.get("/eqip/maintenance-obligations/<oid>")
@require_roles(*ANY_ROLE)
def get_one_obligation(oid, _uid, _role):
    return ok(serializers.obligation(get_obligation(oid)))


@bp.get("/eqip/maintenance-obligations")
@require_roles(*ANY_ROLE)
def list_obligations(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.obligations.values()),
        [("contract_id", "contract_id"), ("practice_item_id", "practice_item_id"),
         ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.obligation(o) for o in page], meta)


@bp.post("/eqip/maintenance-obligations/<oid>/report-violation")
@require_roles("ConservationPlanner")
def report_violation(oid, _uid, _role):
    ob = get_obligation(oid)
    if ob["status"] != "ACTIVE":
        raise ApiError("ERR_OBLIGATION_NOT_ACTIVE", 409, "report-violation requires ACTIVE")
    ob["status"] = "VIOLATION_REVIEW"
    ob["reported_by_user_id"] = _uid
    touch(ob)
    return ok(serializers.obligation(ob))


@bp.post("/eqip/maintenance-obligations/<oid>/confirm-violation")
@require_roles("QualityAssuranceOfficer")
def confirm_violation(oid, _uid, _role):
    ob = get_obligation(oid)
    if ob["status"] != "VIOLATION_REVIEW":
        raise ApiError(
            "ERR_OBLIGATION_NOT_IN_REVIEW", 409,
            "confirm-violation requires VIOLATION_REVIEW",
        )
    if ob["reported_by_user_id"] == _uid:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403,
            "the confirmer must differ from the reporter",
        )
    ob["status"] = "VIOLATION_CONFIRMED"
    touch(ob)
    item = STORE.items.get(ob["practice_item_id"])
    if item is not None and item["paid_amount_cents"] > 0:
        ledger.create_demand(
            contract_id=ob["contract_id"],
            amount_cents=item["paid_amount_cents"],
            maintenance_obligation_id=ob["id"],
        )
    if item is not None and item["payment_status"] == "PAID":
        item["payment_status"] = "RECOUPMENT_PENDING"
        touch(item)
    return ok(serializers.obligation(ob))


@bp.post("/eqip/maintenance-obligations/<oid>/dismiss-violation")
@require_roles("QualityAssuranceOfficer")
def dismiss_violation(oid, _uid, _role):
    ob = get_obligation(oid)
    if ob["status"] != "VIOLATION_REVIEW":
        raise ApiError(
            "ERR_OBLIGATION_NOT_IN_REVIEW", 409,
            "dismiss-violation requires VIOLATION_REVIEW",
        )
    ob["status"] = "ACTIVE"
    touch(ob)
    return ok(serializers.obligation(ob))
