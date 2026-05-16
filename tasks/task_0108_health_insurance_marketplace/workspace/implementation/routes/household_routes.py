"""Household member and IncomeRecord routes."""

from datetime import date
from flask import Blueprint, request, g

from db import db, stamp_created, bump_version
from clock import clock
from errors import raise_error
from middleware import auth_required
from response import success_object
from services.constants import VALID_FILER_TYPES, VALID_INCOME_SOURCES
from services.calculations import (
    compute_household_size,
    compute_total_magi_cents,
    update_member_magi,
)
from services.dates import parse_iso_date, years_between
from services.serializers import (
    serialize_household_member,
    serialize_income_record,
)


bp = Blueprint("household", __name__)


def _find_app_or_404(app_id: str):
    app = db.applications.get(app_id)
    if app is None:
        raise_error("ERR_NOT_FOUND")
    return app


def _check_owner(app):
    if g.user_role == "Applicant" and app["applicant_id"] != g.user_id:
        raise_error("ERR_NOT_APPLICATION_OWNER")


def _find_member_or_404(member_id: str, app_id: str):
    member = db.household_members.get(member_id)
    if member is None or member["application_id"] != app_id:
        raise_error("ERR_NOT_FOUND")
    return member


def _refresh_app_rollups(app: dict) -> None:
    app["household_size"] = compute_household_size(app["id"])
    if app["status"] != "DRAFT":
        app["total_magi_cents"] = compute_total_magi_cents(app["id"])
    bump_version(app)


# ---- POST /applications/{id}/household-members ----

@bp.post("/applications/<app_id>/household-members")
@auth_required(allowed_roles={"Applicant"})
def add_household_member(app_id):
    app = _find_app_or_404(app_id)
    _check_owner(app)
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")

    body = request.get_json(silent=True) or {}
    filer_type = body.get("filer_type")
    dob_str = body.get("date_of_birth")
    if filer_type not in VALID_FILER_TYPES or not dob_str:
        raise_error("ERR_INVALID_STATE", "filer_type and date_of_birth are required")

    try:
        dob = parse_iso_date(dob_str)
    except Exception:
        raise_error("ERR_INVALID_STATE", "Invalid date_of_birth format")

    # ERR_DEPENDENT_AGE_INVALID: dependent age >= 26 at coverage_year start
    if filer_type == "DEPENDENT":
        coverage_year_start = date(app["coverage_year"], 1, 1)
        age = years_between(dob, coverage_year_start)
        if age >= 26:
            raise_error("ERR_DEPENDENT_AGE_INVALID")

    # At-most-one PRIMARY_FILER constraint on add
    if filer_type == "PRIMARY_FILER":
        for m in db.household_members.values():
            if m["application_id"] == app["id"] and m["filer_type"] == "PRIMARY_FILER":
                raise_error("ERR_INVALID_STATE", "Application already has a PRIMARY_FILER")

    include_in_household = body.get("include_in_household", True)
    include_in_magi = body.get("include_in_magi", True)
    is_tobacco_user = body.get("is_tobacco_user", False)

    member = {
        "application_id": app["id"],
        "filer_type": filer_type,
        "date_of_birth": dob_str,
        "include_in_household": bool(include_in_household),
        "include_in_magi": bool(include_in_magi),
        "is_tobacco_user": bool(is_tobacco_user),
        "medicaid_eligible": None,
        "member_magi_cents": 0,
    }
    stamp_created(member, versioned=True)
    db.household_members[member["id"]] = member

    _refresh_app_rollups(app)
    return success_object(serialize_household_member(member), status=201)


# ---- PATCH /applications/{id}/household-members/{member_id} ----

@bp.patch("/applications/<app_id>/household-members/<member_id>")
@auth_required(allowed_roles={"Applicant"})
def patch_household_member(app_id, member_id):
    app = _find_app_or_404(app_id)
    _check_owner(app)
    member = _find_member_or_404(member_id, app_id)
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")

    body = request.get_json(silent=True) or {}

    # OCC check
    if "version" in body and body["version"] is not None:
        if body["version"] != member["version"]:
            raise_error("ERR_STALE_VERSION")

    for field in ("include_in_household", "include_in_magi", "is_tobacco_user"):
        if field in body:
            member[field] = bool(body[field])

    bump_version(member)
    _refresh_app_rollups(app)
    return success_object(serialize_household_member(member))


# ---- DELETE /applications/{id}/household-members/{member_id} ----

@bp.delete("/applications/<app_id>/household-members/<member_id>")
@auth_required(allowed_roles={"Applicant"})
def delete_household_member(app_id, member_id):
    app = _find_app_or_404(app_id)
    _check_owner(app)
    member = _find_member_or_404(member_id, app_id)
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")
    if member["filer_type"] == "PRIMARY_FILER":
        raise_error("ERR_INVALID_STATE", "Cannot delete the PRIMARY_FILER member")

    # Also delete the member's IncomeRecord rows
    to_remove = [r["id"] for r in db.income_records.values() if r["member_id"] == member_id]
    for rid in to_remove:
        del db.income_records[rid]

    del db.household_members[member_id]
    _refresh_app_rollups(app)
    return "", 204


# ---- POST /applications/{id}/household-members/{member_id}/income-records ----

@bp.post("/applications/<app_id>/household-members/<member_id>/income-records")
@auth_required(allowed_roles={"Applicant"})
def add_income_record(app_id, member_id):
    app = _find_app_or_404(app_id)
    _check_owner(app)
    member = _find_member_or_404(member_id, app_id)

    body = request.get_json(silent=True) or {}
    source_type = body.get("source_type")
    amount_cents = body.get("amount_cents")
    effective_date = body.get("effective_date")
    supersedes_id = body.get("supersedes_id")

    if source_type not in VALID_INCOME_SOURCES or not isinstance(amount_cents, int) or not effective_date:
        raise_error("ERR_INVALID_STATE", "source_type, amount_cents, effective_date are required")

    try:
        parse_iso_date(effective_date)
    except Exception:
        raise_error("ERR_INVALID_STATE", "Invalid effective_date")

    record = {
        "member_id": member_id,
        "source_type": source_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "superseded_by_id": None,
    }
    stamp_created(record, versioned=False)
    db.income_records[record["id"]] = record

    if supersedes_id:
        prior = db.income_records.get(supersedes_id)
        if prior is None or prior["member_id"] != member_id:
            raise_error("ERR_NOT_FOUND")
        prior["superseded_by_id"] = record["id"]

    update_member_magi(member)
    # Bump member's version since member_magi_cents changed
    bump_version(member)

    # Update Application rollups (only if status != DRAFT, but harmless to recompute)
    if app["status"] != "DRAFT":
        app["total_magi_cents"] = compute_total_magi_cents(app["id"])
        bump_version(app)
    return success_object(serialize_income_record(record), status=201)
