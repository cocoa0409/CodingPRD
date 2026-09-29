"""Providers, GME residents and rotation assignments (PRD 3.1 / 3.6)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import errors
import services.calc as calc
from common import (READ_ROLES, body, check_scope, endpoint, find, gme_refresh, ok_list_of,
                    pagination, public, reference, require_editable)
from db import db, new_row, ordered, residents_of, touch
from response import ok
from validators import query_enum, query_string

bp = Blueprint("providers", __name__)

TEACHING_STATUSES = ("TEACHING", "NON_TEACHING")
IRP_STATUSES = ("WITHIN_IRP", "BEYOND_IRP")
ROTATION_STATUSES = ("ACTIVE", "VOID")


# ------------------------------------------------------------------ Provider
@bp.post("/providers")
@endpoint(roles=["SystemAdmin"])
def create_provider():
    payload = body()
    ccn = payload.string("ccn", length=6, digits=True)
    name = payload.string("name", min_len=1, max_len=200)
    cbsa_code = payload.string("cbsa_code", length=5, digits=True)
    teaching_status = payload.enum("teaching_status", TEACHING_STATUSES, required=False,
                                   default="NON_TEACHING")
    fte_cap = payload.number("fte_cap", required=False, default=Decimal("0.00"), places=2,
                             minimum=0)
    interim_rate = payload.integer("current_interim_rate_cents", required=False, default=0,
                                   minimum=0)

    for existing in db.providers.values():
        if existing["ccn"] == ccn:
            raise errors.business("ERR_FISCAL_PERIOD_INVALID",
                                 "A provider with this certification number already exists.")

    provider = new_row(
        ccn=ccn,
        name=name,
        cbsa_code=cbsa_code,
        teaching_status=teaching_status,
        fte_cap=fte_cap,
        current_interim_rate_cents=interim_rate,
        approved_interim_period_count=0,
    )
    db.providers[provider["id"]] = provider
    return ok(public(provider), 201)


@bp.get("/providers/<provider_id>")
@endpoint(roles=list(READ_ROLES))
def read_provider(provider_id):
    provider = find("Provider", provider_id)
    check_scope(provider["id"])
    return ok(public(provider))


@bp.get("/providers")
@endpoint(roles=list(READ_ROLES))
def list_providers():
    limit, offset = pagination()
    ccn = query_string(request.args, "ccn")
    cbsa_code = query_string(request.args, "cbsa_code")
    teaching_status = query_enum(request.args, "teaching_status", TEACHING_STATUSES)
    rows = ordered(list(db.providers.values()))
    if ccn is not None:
        rows = [r for r in rows if r["ccn"] == ccn]
    if cbsa_code is not None:
        rows = [r for r in rows if r["cbsa_code"] == cbsa_code]
    if teaching_status is not None:
        rows = [r for r in rows if r["teaching_status"] == teaching_status]
    return ok_list_of(rows, limit, offset)


# ------------------------------------------------------------------ Resident
@bp.post("/providers/<provider_id>/residents")
@endpoint(roles=["ReimbursementAnalyst"])
def create_resident(provider_id):
    payload = body()
    full_name = payload.string("full_name")
    program = payload.string("program")
    irp_status = payload.enum("irp_status", IRP_STATUSES, required=False, default="WITHIN_IRP")

    provider = find("Provider", provider_id)
    check_scope(provider["id"])

    resident = new_row(
        provider_id=provider["id"],
        full_name=full_name,
        program=program,
        irp_status=irp_status,
        assigned_fte_days=Decimal("0.0000"),
    )
    db.residents[resident["id"]] = resident
    return ok(public(resident), 201)


@bp.get("/providers/<provider_id>/residents")
@endpoint(roles=list(READ_ROLES))
def list_residents(provider_id):
    limit, offset = pagination()
    irp_status = query_enum(request.args, "irp_status", IRP_STATUSES)
    provider = find("Provider", provider_id)
    rows = residents_of(provider["id"])
    if irp_status is not None:
        rows = [r for r in rows if r["irp_status"] == irp_status]
    return ok_list_of(rows, limit, offset)


@bp.get("/residents/<resident_id>")
@endpoint(roles=list(READ_ROLES))
def read_resident(resident_id):
    return ok(public(find("Resident", resident_id)))


# --------------------------------------------------------- RotationAssignment
@bp.post("/residents/<resident_id>/rotation-assignments")
@endpoint(roles=["ReimbursementAnalyst"])
def create_rotation(resident_id):
    payload = body()
    cost_center_id = payload.string("cost_center_id")
    start_date = payload.date("start_date")
    end_date = payload.date("end_date")
    fte_fraction = payload.number("fte_fraction", places=4, exclusive_minimum=0, maximum=1)
    if end_date <= start_date:
        raise errors.invalid_request("end_date must be strictly later than start_date.")

    resident = find("Resident", resident_id)
    center = reference("CostCenter", cost_center_id)
    check_scope(resident["provider_id"])
    report = db.cost_reports[center["cost_report_id"]]
    require_editable(report)

    if report["provider_id"] != resident["provider_id"]:
        raise errors.business("ERR_COST_CENTER_FOREIGN_TO_PROVIDER",
                             "The rotation site does not belong to the resident's provider.")

    if calc.daily_fte_exceeded(resident["id"], start_date, end_date, fte_fraction):
        raise errors.business("ERR_RESIDENT_DAILY_FTE_EXCEEDED",
                             "The resident would exceed 1.0000 FTE on at least one day.",
                             status=409)

    probe = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
    period_begin = calc.as_date(report["fiscal_year_begin"])
    period_end = calc.as_date(report["fiscal_year_end"]) + timedelta(days=1)
    if calc.overlap_days(probe, period_begin, period_end) <= 0:
        raise errors.business("ERR_ROTATION_OUTSIDE_FISCAL_YEAR",
                             "The rotation does not intersect the report's fiscal year.",
                             status=409)

    rotation = new_row(
        resident_id=resident["id"],
        cost_center_id=center["id"],
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        fte_fraction=fte_fraction,
        status="ACTIVE",
        overlap_days=0,
        fte_days=Decimal("0.0000"),
    )
    db.rotation_assignments[rotation["id"]] = rotation
    gme_refresh(report)
    rotation["version"] = 1
    rotation["updated_at"] = rotation["created_at"]
    return ok(public(rotation), 201)


@bp.get("/rotation-assignments/<rotation_id>")
@endpoint(roles=list(READ_ROLES))
def read_rotation(rotation_id):
    return ok(public(find("RotationAssignment", rotation_id)))


@bp.get("/rotation-assignments")
@endpoint(roles=list(READ_ROLES))
def list_rotations():
    limit, offset = pagination()
    resident_id = query_string(request.args, "resident_id")
    cost_center_id = query_string(request.args, "cost_center_id")
    status = query_enum(request.args, "status", ROTATION_STATUSES)
    rows = ordered(list(db.rotation_assignments.values()))
    if resident_id is not None:
        rows = [r for r in rows if r["resident_id"] == resident_id]
    if cost_center_id is not None:
        rows = [r for r in rows if r["cost_center_id"] == cost_center_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list_of(rows, limit, offset)


@bp.post("/rotation-assignments/<rotation_id>/void")
@endpoint(roles=["ReimbursementAnalyst"])
def void_rotation(rotation_id):
    rotation = find("RotationAssignment", rotation_id)
    resident = db.residents[rotation["resident_id"]]
    check_scope(resident["provider_id"])
    report = db.cost_reports[db.cost_centers[rotation["cost_center_id"]]["cost_report_id"]]
    require_editable(report)
    if rotation["status"] != "ACTIVE":
        raise errors.invalid_state("The rotation assignment is already VOID.")

    rotation["status"] = "VOID"
    rotation["fte_days"] = Decimal("0.0000")
    touch(rotation)
    gme_refresh(report)
    return ok(public(rotation))
