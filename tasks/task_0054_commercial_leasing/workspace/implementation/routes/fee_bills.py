"""FeeBill routes."""
from flask import Blueprint, request, g

import db
from errors import err
from clock import parse_iso, iso
from middleware import require_auth
from response import success
from services.lookups import get_fee_bill, get_lease, get_unit
from services.validation import (
    require_body, get_body, require_str, require_int, require_iso,
    require_enum, require_bool,
)
from services.occ import check_version
from services.fee_calc import compute_property_fee, compute_energy_fee
from services.audit import record as audit_record


bp = Blueprint("fee_bills", __name__)

BILL_KINDS = {"PROPERTY_FEE", "ENERGY_FEE"}
PROPERTY_FEE_MODES = {"BY_AREA", "FIXED_RATE"}
ENERGY_MODES = {"SUB_METER", "ALLOCATED"}


def _check_tenant_ownership_bill(b: dict) -> None:
    if g.user_role == "Tenant" and b.get("tenant_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "Tenants can only access their own fee bills")


@bp.post("/fee-bills")
@require_auth(roles={"FinanceOfficer"})
def create_fee_bill():
    body = require_body(request)
    lease_id = require_str(body, "lease_id")
    le = get_lease(lease_id)
    bill_kind = require_enum(body, "bill_kind", BILL_KINDS)
    period_start = require_iso(body, "period_start")
    period_end = require_iso(body, "period_end")
    if period_end <= period_start:
        raise err("ERR_INVALID_DATE_RANGE", "period_end must be > period_start")

    if le["status"] not in {"ACTIVE", "AMENDMENT_PENDING", "TERMINATING"}:
        raise err("ERR_LEASE_NOT_BILLABLE",
                  f"Lease must be ACTIVE/AMENDMENT_PENDING/TERMINATING (current: {le['status']})")

    unit = get_unit(le["unit_id"])

    if bill_kind == "PROPERTY_FEE":
        property_fee_mode = require_enum(body, "property_fee_mode", PROPERTY_FEE_MODES)
        rate_by_area = body.get("rate_per_sqm_per_month_cents")
        fixed_rate = body.get("fixed_rate_cents_per_month")
        if property_fee_mode == "BY_AREA":
            if rate_by_area is None or isinstance(rate_by_area, bool) or not isinstance(rate_by_area, int) or rate_by_area < 0:
                raise err("ERR_VALIDATION", "rate_per_sqm_per_month_cents required for BY_AREA")
        if property_fee_mode == "FIXED_RATE":
            if fixed_rate is None or isinstance(fixed_rate, bool) or not isinstance(fixed_rate, int) or fixed_rate < 0:
                raise err("ERR_VALIDATION", "fixed_rate_cents_per_month required for FIXED_RATE")
        amount = compute_property_fee(
            unit=unit, period_start=period_start, period_end=period_end,
            property_fee_mode=property_fee_mode,
            rate_per_sqm_per_month_cents=rate_by_area,
            fixed_rate_cents_per_month=fixed_rate,
        )
        bill = {
            "lease_id": lease_id,
            "unit_id": le["unit_id"],
            "tenant_id": le["tenant_id"],
            "bill_kind": bill_kind,
            "period_start": iso(period_start),
            "period_end": iso(period_end),
            "property_fee_mode": property_fee_mode,
            "rate_per_sqm_per_month_cents": rate_by_area,
            "fixed_rate_cents_per_month": fixed_rate,
            "energy_mode": None,
            "sub_meter_kwh": None,
            "shared_total_kwh": None,
            "shared_meter_group_unit_ids": None,
            "tariff_per_kwh_cents": None,
            "amount_cents": amount,
            "status": "ISSUED",
            "dispute_reason": None,
        }
    else:  # ENERGY_FEE
        energy_mode = require_enum(body, "energy_mode", ENERGY_MODES)
        tariff = body.get("tariff_per_kwh_cents")
        if tariff is None or isinstance(tariff, bool) or not isinstance(tariff, int) or tariff <= 0:
            raise err("ERR_VALIDATION", "tariff_per_kwh_cents must be a positive integer")
        sub_meter_kwh = body.get("sub_meter_kwh")
        shared_total_kwh = body.get("shared_total_kwh")
        shared_group = body.get("shared_meter_group_unit_ids")

        if energy_mode == "SUB_METER":
            if sub_meter_kwh is None or isinstance(sub_meter_kwh, bool) or not isinstance(sub_meter_kwh, (int, float)) or sub_meter_kwh < 0:
                raise err("ERR_VALIDATION", "sub_meter_kwh must be a number >= 0")
        else:  # ALLOCATED
            if shared_total_kwh is None or isinstance(shared_total_kwh, bool) or not isinstance(shared_total_kwh, (int, float)) or shared_total_kwh < 0:
                raise err("ERR_VALIDATION", "shared_total_kwh must be a number >= 0")
            if not isinstance(shared_group, list) or len(shared_group) < 2:
                raise err("ERR_VALIDATION", "shared_meter_group_unit_ids must have >= 2 entries")
            if le["unit_id"] not in shared_group:
                raise err("ERR_VALIDATION", "shared_meter_group_unit_ids must include this bill's unit_id")

        amount = compute_energy_fee(
            this_unit=unit, period_start=period_start, period_end=period_end,
            energy_mode=energy_mode, tariff_per_kwh_cents=tariff,
            sub_meter_kwh=sub_meter_kwh,
            shared_total_kwh=shared_total_kwh,
            shared_meter_group_unit_ids=shared_group,
        )
        bill = {
            "lease_id": lease_id,
            "unit_id": le["unit_id"],
            "tenant_id": le["tenant_id"],
            "bill_kind": bill_kind,
            "period_start": iso(period_start),
            "period_end": iso(period_end),
            "property_fee_mode": None,
            "rate_per_sqm_per_month_cents": None,
            "fixed_rate_cents_per_month": None,
            "energy_mode": energy_mode,
            "sub_meter_kwh": sub_meter_kwh,
            "shared_total_kwh": shared_total_kwh,
            "shared_meter_group_unit_ids": shared_group,
            "tariff_per_kwh_cents": tariff,
            "amount_cents": amount,
            "status": "ISSUED",
            "dispute_reason": None,
        }

    db.stamp_create(bill)
    db.fee_bills[bill["id"]] = bill
    return success(db.public(bill), status=201)


@bp.get("/fee-bills/<bill_id>")
@require_auth(roles={"PropertyManager", "FinanceOfficer", "Tenant"})
def get_fee_bill_route(bill_id):
    b = get_fee_bill(bill_id)
    _check_tenant_ownership_bill(b)
    return success(db.public(b))


@bp.post("/fee-bills/<bill_id>/pay")
@require_auth(roles={"Tenant"})
def pay_bill(bill_id):
    b = get_fee_bill(bill_id)
    _check_tenant_ownership_bill(b)
    body = get_body(request)
    check_version(body, b)
    if b["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", f"Bill must be ISSUED to pay (current: {b['status']})")
    le = db.leases.get(b["lease_id"])
    if le is None or le["status"] not in {"ACTIVE", "AMENDMENT_PENDING", "TERMINATING", "TERMINATED"}:
        cur = le["status"] if le else "None"
        raise err("ERR_LEASE_NOT_BILLABLE",
                  f"Lease not in billable state for payment (current: {cur})")
    b["status"] = "PAID"
    db.stamp_update(b)
    return success(db.public(b))


@bp.post("/fee-bills/<bill_id>/dispute")
@require_auth(roles={"Tenant"})
def dispute_bill(bill_id):
    b = get_fee_bill(bill_id)
    _check_tenant_ownership_bill(b)
    body = require_body(request)
    check_version(body, b)
    if b["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", f"Bill must be ISSUED to dispute (current: {b['status']})")
    reason = require_str(body, "dispute_reason")
    b["status"] = "DISPUTED"
    b["dispute_reason"] = reason
    db.stamp_update(b)
    return success(db.public(b))


@bp.post("/fee-bills/<bill_id>/resolve-dispute")
@require_auth(roles={"FinanceOfficer"})
def resolve_dispute(bill_id):
    b = get_fee_bill(bill_id)
    body = require_body(request)
    check_version(body, b)
    if b["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", f"Bill must be DISPUTED (current: {b['status']})")
    keep = require_bool(body, "resolution_keeps_bill")
    if keep:
        b["status"] = "ISSUED"
        db.stamp_update(b)
        audit_record(
            subject_kind="FEE_BILL", subject_id=b["id"], action="FEE_DISPUTED",
            actor_role=g.user_role, actor_id=g.user_id,
            payload={"bill_id": b["id"], "resolution_keeps_bill": True},
        )
    else:
        b["status"] = "VOIDED"
        db.stamp_update(b)
        audit_record(
            subject_kind="FEE_BILL", subject_id=b["id"], action="FEE_ADJUSTED",
            actor_role=g.user_role, actor_id=g.user_id,
            payload={"bill_id": b["id"], "resolution_keeps_bill": False},
        )
    return success(db.public(b))


@bp.post("/fee-bills/<bill_id>/void")
@require_auth(roles={"FinanceOfficer"})
def void_bill(bill_id):
    b = get_fee_bill(bill_id)
    body = get_body(request)
    check_version(body, b)
    if b["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", f"Bill must be ISSUED (current: {b['status']})")
    b["status"] = "VOIDED"
    db.stamp_update(b)
    audit_record(
        subject_kind="FEE_BILL", subject_id=b["id"], action="FEE_ADJUSTED",
        actor_role=g.user_role, actor_id=g.user_id,
        payload={"bill_id": b["id"]},
    )
    return success(db.public(b))
