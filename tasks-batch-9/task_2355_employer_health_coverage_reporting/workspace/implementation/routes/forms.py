"""Furnishing consents, Form 1095-C generation / furnishing, coverage lines."""

from datetime import date

from flask import Blueprint

import calc
import lookups as lk
import sync
from auth import READ_ROLES, READ_ROLES_WITH_EMPLOYEE, require_roles
from db import clock_date, clock_iso, insert, touch
from envelope import created, ok
from errors import fail
from guards import (
    listing,
    require_group_ale,
    require_group_unlocked,
    require_season_open,
    single_read,
)
from shapes import body, bool_field, enum_field, int_field, string_field

bp = Blueprint("forms", __name__)

FURNISHED = ("FURNISHED_PAPER", "FURNISHED_ELECTRONIC")
FILED = ("FILED_ACCEPTED", "FILED_WITH_ERRORS")
PREFERENCES = ("W2", "RATE_OF_PAY", "FPL", "NONE")


# --------------------------------------------------------------------------- #
# FurnishingConsent
# --------------------------------------------------------------------------- #
@bp.post("/furnishing-consents")
def create_consent():
    require_roles("EmployeeSelfService", "BenefitsAdmin")
    data = body()
    employee_id = string_field(data, "employee_id")
    electronic_address = string_field(data, "electronic_address")

    lk.find("employees", employee_id)
    if lk.consent_of_employee(employee_id) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "That employee already has a furnishing consent.")

    record = insert(
        "furnishing_consents",
        {
            "employee_id": employee_id,
            "electronic_address": electronic_address,
            "consent_status": "PENDING",
            "granted_at": None,
            "withdrawn_at": None,
            "grant_count": 0,
        },
    )
    return created(record)


@bp.get("/furnishing-consents")
def list_consents():
    return listing(
        "furnishing_consents",
        {"employee_id": ("employee_id", "str"), "consent_status": ("consent_status", "str")},
        READ_ROLES_WITH_EMPLOYEE,
    )


@bp.get("/furnishing-consents/<identifier>")
def read_consent(identifier):
    return single_read("furnishing_consents", identifier, READ_ROLES_WITH_EMPLOYEE)


def _own_consent(consent_id):
    """Rung 2 for the entity-backed role: role, then existence, then identity."""
    user_id, _role = require_roles("EmployeeSelfService")
    consent = lk.find("furnishing_consents", consent_id)
    if consent["employee_id"] != user_id:
        fail("ERR_FORBIDDEN_ROLE", "This consent belongs to another employee.")
    return consent


@bp.post("/furnishing-consents/<consent_id>/grant")
def grant_consent(consent_id):
    consent = _own_consent(consent_id)
    body()
    if consent["consent_status"] not in ("PENDING", "WITHDRAWN"):
        fail("ERR_CONSENT_ALREADY_GRANTED", "This consent has already been granted.")
    sync.set_field(consent, "consent_status", "GRANTED")
    sync.set_field(consent, "granted_at", clock_iso())
    consent["grant_count"] = (consent["grant_count"] or 0) + 1
    touch(consent)
    return ok(consent)


@bp.post("/furnishing-consents/<consent_id>/withdraw")
def withdraw_consent(consent_id):
    consent = _own_consent(consent_id)
    body()
    if consent["consent_status"] != "GRANTED":
        fail("ERR_CONSENT_NOT_GRANTED", "This consent is not currently granted.")
    sync.set_field(consent, "consent_status", "WITHDRAWN")
    sync.set_field(consent, "withdrawn_at", clock_iso())
    touch(consent)
    employee = lk.get("employees", consent["employee_id"])
    if employee is not None:
        sync.consent_withdrawal_cascade(employee)
    return ok(consent)


# --------------------------------------------------------------------------- #
# Form1095C
# --------------------------------------------------------------------------- #
@bp.post("/forms-1095c")
def create_form():
    user_id, _role = require_roles("Preparer")
    data = body()
    employee_id = string_field(data, "employee_id")
    plan_start_month = int_field(data, "plan_start_month", minimum=0, maximum=12)
    preference = enum_field(
        data, "safe_harbor_preference", PREFERENCES, required=False, default="W2"
    )

    employee = lk.find("employees", employee_id)
    group = lk.group_of_employee(employee)
    season = lk.season_of_employee(employee)
    require_season_open(season)
    require_group_unlocked(group)
    require_group_ale(group)

    # rungs 25 / 26 outrank the duplicate-original check at rung 40.
    lines, rollups, full_time, sources, average = calc.compute_lines(employee, season, preference)

    for existing in lk.forms_of_employee(employee):
        if existing["form_type"] == "ORIGINAL" and existing["furnishing_status"] != "VOIDED":
            fail("ERR_DUPLICATE_FORM", "This employee already has an original statement.")

    record = insert(
        "forms_1095c",
        sync.new_form_record(employee, plan_start_month, preference, user_id),
    )
    sync.write_lines(record, lines)
    sync.apply_rollups(record, rollups)
    sync.write_employee_full_time(employee, full_time, sources, average)
    return created(record)


@bp.get("/forms-1095c")
def list_forms():
    return listing(
        "forms_1095c",
        {
            "employee_id": ("employee_id", "str"),
            "transmittal_id": ("transmittal_id", "str"),
            "corrected_from_form_id": ("corrected_from_form_id", "str"),
            "furnishing_status": ("furnishing_status", "str"),
            "filing_status": ("filing_status", "str"),
            "form_type": ("form_type", "str"),
        },
        READ_ROLES,
    )


@bp.get("/forms-1095c/<identifier>")
def read_form(identifier):
    return single_read("forms_1095c", identifier, READ_ROLES_WITH_EMPLOYEE)


@bp.post("/forms-1095c/<form_id>/regenerate")
def regenerate_form(form_id):
    user_id, _role = require_roles("Preparer")
    data = body()
    reason = string_field(data, "correction_reason", required=False)

    form = lk.find("forms_1095c", form_id)
    employee = lk.get("employees", form["employee_id"])
    group = lk.group_of_employee(employee) if employee else None
    season = lk.season_of_employee(employee) if employee else None
    require_season_open(season)
    require_group_ale(group)
    if form["furnishing_status"] == "VOIDED" or form["filing_status"] == "VOIDED":
        fail("ERR_FORM_VOIDED", "A voided statement cannot be regenerated.")

    preference = form["safe_harbor_preference"]
    lines, rollups, full_time, sources, average = calc.compute_lines(employee, season, preference)

    delivered = form["furnishing_status"] in FURNISHED
    filed = form["filing_status"] in FILED
    if delivered or filed:
        sync.draft_correction(source_form=form, employee=employee, season=season, reason=reason, user_id=user_id)
        if delivered:
            sync.set_field(form, "furnishing_status", "VOIDED")
        if filed:
            sync.set_field(form, "filing_status", "CORRECTION_DRAFTED")
        sync.set_field(form, "correction_reason", reason)
        return ok(form)

    sync.write_lines(form, lines)
    sync.apply_rollups(form, rollups)
    sync.set_field(form, "generated_by_user_id", user_id)
    sync.write_employee_full_time(employee, full_time, sources, average)
    touch(form)
    return ok(form)


@bp.post("/forms-1095c/<form_id>/furnish")
def furnish_form(form_id):
    user_id, _role = require_roles("Preparer", "BenefitsAdmin")
    data = body()
    channel = enum_field(data, "delivery_channel", ("PAPER", "ELECTRONIC"))
    intentional = bool_field(data, "intentional_disregard", required=False, default=False)

    form = lk.find("forms_1095c", form_id)
    employee = lk.get("employees", form["employee_id"])
    season = lk.season_of_employee(employee) if employee else None
    require_season_open(season)

    if form["furnishing_status"] not in ("NOT_FURNISHED", "REDELIVERY_REQUIRED"):
        fail("ERR_FORM_ALREADY_FURNISHED", "This statement has already been furnished.")
    if user_id == form.get("generated_by_user_id"):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who generated a statement may not furnish it.",
        )
    if channel == "ELECTRONIC":
        consent = lk.consent_of_employee(form["employee_id"])
        if consent is None or consent["consent_status"] != "GRANTED":
            fail("ERR_CONSENT_NOT_GRANTED", "Electronic delivery requires a granted consent.")
    if season is None:
        fail("ERR_FILING_SEASON_NOT_FOUND", "No filing season governs this statement.")
    today = clock_date()
    if today <= date(season["tax_year"], 12, 31):
        fail("ERR_FURNISHING_WINDOW_NOT_OPEN", "The reporting year has not ended yet.")

    sync.set_field(
        form,
        "furnishing_status",
        "FURNISHED_ELECTRONIC" if channel == "ELECTRONIC" else "FURNISHED_PAPER",
    )
    sync.set_field(form, "furnished_at", clock_iso())
    sync.set_field(form, "furnished_by_user_id", user_id)
    sync.set_field(
        form,
        "late_furnishing_penalty_cents",
        calc.late_furnishing_penalty(season, today, intentional),
    )
    return ok(form)


# --------------------------------------------------------------------------- #
# MonthlyCoverageLine
# --------------------------------------------------------------------------- #
@bp.get("/monthly-coverage-lines")
def list_lines():
    return listing(
        "monthly_coverage_lines",
        {"form_1095c_id": ("form_1095c_id", "str"), "month": ("month", "int")},
        READ_ROLES_WITH_EMPLOYEE,
    )


@bp.get("/monthly-coverage-lines/<identifier>")
def read_line(identifier):
    return single_read("monthly_coverage_lines", identifier, READ_ROLES_WITH_EMPLOYEE)
