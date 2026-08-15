from datetime import date as date_cls
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import store, current_date
from errors import ApiError
from helpers import (
    add_trace,
    base_fields,
    create_invoice,
    get_customer_or_404,
    get_lease_or_404,
    get_unit_or_404,
    list_response,
    pub,
    touch,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("lease", __name__, url_prefix="/mro")


@bp.route("/lease-agreements", methods=["POST"])
@require_roles("CustomerServiceRep")
def create_lease():
    body = validate_body(
        get_json_body(),
        {
            "customer_id": ("str", True),
            "unit_id": ("str", True),
            "start_date": ("date", True),
            "end_date": ("date", True),
            "daily_rate_cents": ("int", True),
            "expected_unit_version": ("int", True),
        },
    )
    cust = get_customer_or_404(body["customer_id"])
    unit = get_unit_or_404(body["unit_id"])
    # OCC fires after existence, before any business logic (PRD 2.7).
    if body["expected_unit_version"] != unit["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Unit version has advanced")
    start = date_cls.fromisoformat(body["start_date"])
    end = date_cls.fromisoformat(body["end_date"])
    # Temporal: day-closed interval must not share any day with an ACTIVE lease
    # on the same unit (a shared boundary day IS a conflict).
    for other in store.leases.values():
        if other["unit_id"] != unit["id"] or other["status"] != "ACTIVE":
            continue
        o_start = date_cls.fromisoformat(other["start_date"])
        o_end = date_cls.fromisoformat(other["end_date"])
        if start <= o_end and o_start <= end:
            raise ApiError(
                "ERR_LEASE_PERIOD_OVERLAP", 409, "Lease interval overlaps an ACTIVE lease"
            )
    # Constraint: leasability.
    if (
        unit["ownership"] != "SHOP"
        or unit["condition_status"] != "SERVICEABLE"
        or unit["custody_status"] not in ("IN_POOL", "ON_LEASE")
        or end < start
    ):
        raise ApiError("ERR_UNIT_NOT_LEASABLE", 422, "Unit is not leasable")
    ag = dict(base_fields())
    ag.update(
        {
            "customer_id": cust["id"],
            "unit_id": unit["id"],
            "daily_rate_cents": body["daily_rate_cents"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "returned_at": None,
            "status": "ACTIVE",
            "billed_days": None,
            "overage_days": None,
            "total_charge_cents": None,
        }
    )
    store.leases[ag["id"]] = ag
    unit["custody_status"] = "ON_LEASE"
    touch(unit)  # OCC anchor: increments ComponentUnit.version by 1
    add_trace(unit["id"], "LEASE_OUT", notes=ag["id"])
    return ok(pub(ag), 201)


@bp.route("/lease-agreements/<agreementId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_lease(agreementId):
    return ok(pub(get_lease_or_404(agreementId)))


@bp.route("/lease-agreements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_leases():
    return list_response(
        store.leases.values(),
        filters={"customer_id": "customer_id", "unit_id": "unit_id", "status": "status"},
    )


@bp.route("/lease-agreements/<agreementId>/return", methods=["POST"])
@require_roles("CustomerServiceRep")
def return_lease(agreementId):
    ag = get_lease_or_404(agreementId)
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_INVALID_STATE", 409, "Lease agreement not ACTIVE")
    cur = current_date()
    start = date_cls.fromisoformat(ag["start_date"])
    end = date_cls.fromisoformat(ag["end_date"])
    if cur < start:
        raise ApiError("ERR_LEASE_INVALID_STATE", 409, "Return before lease start_date")
    billed_end = min(cur, end)
    billed_days = (billed_end - start).days + 1
    overage_days = max(0, (cur - end).days)
    base_charge = billed_days * ag["daily_rate_cents"]
    overage_charge = int(
        (Decimal(overage_days) * Decimal(ag["daily_rate_cents"]) * Decimal("1.5")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    total_charge = base_charge + overage_charge
    ag["returned_at"] = cur.isoformat()
    ag["billed_days"] = billed_days
    ag["overage_days"] = overage_days
    ag["total_charge_cents"] = total_charge
    ag["status"] = "RETURNED"
    touch(ag)
    unit = store.units[ag["unit_id"]]
    unit["custody_status"] = "IN_POOL"
    touch(unit)
    add_trace(unit["id"], "LEASE_RETURN", notes=ag["id"])
    create_invoice(
        "LEASE",
        ag["customer_id"],
        lease_agreement_id=ag["id"],
        other_charge_cents=total_charge,
        total_cents=total_charge,
    )
    return ok(pub(ag))
