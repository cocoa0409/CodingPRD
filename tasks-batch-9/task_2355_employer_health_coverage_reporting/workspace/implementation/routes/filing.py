"""Transmittals (1094-C) and the agency error / correction cycle."""

from flask import Blueprint

import calc
import lookups as lk
import sync
from auth import READ_ROLES, require_roles
from db import clock_iso, insert, touch
from envelope import created, ok
from errors import fail
from guards import (
    group_of_transmittal,
    listing,
    require_group_ale,
    require_season_open,
    season_of_transmittal,
    single_read,
)
from shapes import body, bool_field, enum_field, id_list_field, int_field, string_field

bp = Blueprint("filing", __name__)

SEVERITIES = ("FATAL", "ERROR", "WARNING")
BUILDABLE = ("DRAFT", "REJECTED", "CORRECTION_REQUIRED")
ERRORED = ("ACCEPTED_WITH_ERRORS", "PARTIALLY_ACCEPTED")
ERROR_HOLDING = ("ACCEPTED_WITH_ERRORS", "PARTIALLY_ACCEPTED", "REJECTED")


def _live_form_count(transmittal):
    return sum(1 for f in lk.forms_of_transmittal(transmittal) if f["filing_status"] != "VOIDED")


def _open_error_count(transmittal):
    return sum(
        1 for e in lk.errors_of_transmittal(transmittal) if e["resolution_status"] == "OPEN"
    )


# --------------------------------------------------------------------------- #
# Transmittal
# --------------------------------------------------------------------------- #
@bp.post("/transmittals")
def create_transmittal():
    require_roles("Preparer")
    data = body()
    group_member_id = string_field(data, "group_member_id")
    transmission_type = enum_field(
        data, "transmission_type", ("ORIGINAL", "CORRECTION", "REPLACEMENT")
    )
    expected = int_field(data, "expected_group_member_version", minimum=0)
    authoritative = bool_field(data, "authoritative_indicator", required=False, default=True)

    member = lk.find("group_members", group_member_id)
    require_season_open(lk.season_of_member(member))
    if expected != member["version"]:
        fail("ERR_STALE_MEMBER_VERSION", "The group member has changed since it was read.")

    record = insert(
        "transmittals",
        {
            "group_member_id": group_member_id,
            "transmission_type": transmission_type,
            "authoritative_indicator": authoritative,
            "status": "DRAFT",
            "cycle_number": 1,
            "form_count": 0,
            "aggregate_return_count": 0,
            "required_channel": "ANY",
            "channel": None,
            "receipt_id": None,
            "monthly_ft_counts": [],
            "error_count": 0,
            "open_error_count": 0,
            "built_by_user_id": None,
            "transmitted_by_user_id": None,
            "built_at": None,
            "transmitted_at": None,
        },
    )
    touch(member)
    return created(record)


@bp.get("/transmittals")
def list_transmittals():
    return listing(
        "transmittals",
        {"group_member_id": ("group_member_id", "str"), "status": ("status", "str")},
        READ_ROLES,
    )


@bp.get("/transmittals/<identifier>")
def read_transmittal(identifier):
    return single_read("transmittals", identifier, READ_ROLES)


@bp.post("/transmittals/<transmittal_id>/attach-forms")
def attach_forms(transmittal_id):
    require_roles("Preparer")
    data = body()
    form_ids = id_list_field(data, "form_ids")

    transmittal = lk.find("transmittals", transmittal_id)
    forms = [lk.find("forms_1095c", form_id) for form_id in form_ids]
    for form in forms:
        employee = lk.get("employees", form["employee_id"])
        if employee is None or employee["group_member_id"] != transmittal["group_member_id"]:
            fail("ERR_SCOPE_MISMATCH", "That statement belongs to another member.")

    require_season_open(season_of_transmittal(transmittal))
    for form in forms:
        if form["filing_status"] != "NOT_FILED":
            fail("ERR_FORM_ALREADY_ATTACHED", "One of those statements is already attached.")
    if transmittal["status"] != "DRAFT":
        fail("ERR_TRANSMITTAL_STATE_INVALID", "Only a DRAFT transmittal accepts statements.")

    for form in forms:
        sync.set_field(form, "filing_status", "ATTACHED")
        sync.set_field(form, "transmittal_id", transmittal["id"])
        predecessor_id = form.get("corrected_from_form_id")
        if predecessor_id:
            predecessor = lk.get("forms_1095c", predecessor_id)
            if predecessor is not None and predecessor["filing_status"] == "CORRECTION_DRAFTED":
                sync.set_field(predecessor, "filing_status", "VOIDED")
    touch(lk.get("group_members", transmittal["group_member_id"]))
    return ok(transmittal)


@bp.post("/transmittals/<transmittal_id>/detach-form")
def detach_form(transmittal_id):
    require_roles("Preparer")
    data = body()
    form_id = string_field(data, "form_id")

    transmittal = lk.find("transmittals", transmittal_id)
    form = lk.find("forms_1095c", form_id)
    require_season_open(season_of_transmittal(transmittal))
    if form["filing_status"] != "ATTACHED" or form.get("transmittal_id") != transmittal["id"]:
        fail("ERR_FORM_NOT_ATTACHED", "That statement is not attached to this transmittal.")
    if transmittal["status"] not in ("DRAFT", "BUILT"):
        fail("ERR_TRANSMITTAL_STATE_INVALID", "This transmittal no longer accepts changes.")

    sync.set_field(form, "filing_status", "NOT_FILED")
    sync.set_field(form, "transmittal_id", None)
    if transmittal["status"] == "BUILT":
        sync.set_field(transmittal, "status", "DRAFT")
        sync.set_field(transmittal, "aggregate_return_count", 0)
        sync.set_field(transmittal, "required_channel", "ANY")
        sync.set_field(transmittal, "monthly_ft_counts", [])
        sync.set_field(transmittal, "built_at", None)
    touch(lk.get("group_members", transmittal["group_member_id"]))
    return ok(transmittal)


@bp.post("/transmittals/<transmittal_id>/build")
def build_transmittal(transmittal_id):
    user_id, _role = require_roles("Preparer")
    body()
    transmittal = lk.find("transmittals", transmittal_id)
    member = lk.get("group_members", transmittal["group_member_id"])
    group = group_of_transmittal(transmittal)
    season = season_of_transmittal(transmittal)
    require_season_open(season)
    require_group_ale(group)

    status = transmittal["status"]
    if status not in BUILDABLE:
        fail("ERR_TRANSMITTAL_STATE_INVALID", "A %s transmittal cannot be built." % status)
    if _live_form_count(transmittal) < 1:
        fail("ERR_NO_FORMS_ATTACHED", "An empty transmittal cannot be built.")
    if status == "CORRECTION_REQUIRED" and _open_error_count(transmittal) != 0:
        fail("ERR_OPEN_TRANSMITTAL_ERRORS", "Every agency error must be resolved first.")
    if status in ("REJECTED", "CORRECTION_REQUIRED"):
        if transmittal["cycle_number"] >= calc.CORRECTION_CYCLE_LIMIT:
            fail("ERR_CORRECTION_CYCLE_LIMIT", "The correction cycle limit has been reached.")

    aggregate, channel = calc.transmission_channel(transmittal, member, season)
    if status in ("REJECTED", "CORRECTION_REQUIRED"):
        transmittal["cycle_number"] = transmittal["cycle_number"] + 1
        touch(transmittal)
    sync.set_field(transmittal, "aggregate_return_count", aggregate)
    sync.set_field(transmittal, "required_channel", channel)
    sync.set_field(
        transmittal, "monthly_ft_counts", calc.reporting_year_monthly_ft_counts(member)
    )
    sync.set_field(transmittal, "built_by_user_id", user_id)
    sync.set_field(transmittal, "built_at", clock_iso())
    sync.set_field(transmittal, "status", "BUILT")

    for sibling in lk.transmittals_of_member(member):
        if sibling["id"] != transmittal["id"] and sibling["status"] == "BUILT":
            sync.set_field(sibling, "status", "SUPERSEDED")
    return ok(transmittal)


@bp.post("/transmittals/<transmittal_id>/transmit")
def transmit_transmittal(transmittal_id):
    user_id, _role = require_roles("FilingAgent")
    data = body()
    channel = enum_field(data, "channel", ("ELECTRONIC", "PAPER"))

    transmittal = lk.find("transmittals", transmittal_id)
    require_season_open(season_of_transmittal(transmittal))
    if transmittal["status"] != "BUILT":
        fail("ERR_TRANSMITTAL_NOT_BUILT", "Only a BUILT transmittal can be transmitted.")
    if user_id == transmittal.get("built_by_user_id"):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who built a submission may not transmit it.",
        )
    if channel == "PAPER" and transmittal["required_channel"] == "ELECTRONIC":
        fail("ERR_ELECTRONIC_FILING_REQUIRED", "This submission must be filed electronically.")

    sync.set_field(transmittal, "status", "TRANSMITTED")
    sync.set_field(transmittal, "channel", channel)
    sync.set_field(transmittal, "transmitted_by_user_id", user_id)
    sync.set_field(transmittal, "transmitted_at", clock_iso())
    for form in lk.forms_of_transmittal(transmittal):
        if form["filing_status"] == "ATTACHED":
            sync.set_field(form, "filing_status", "PENDING_FILING")
    return ok(transmittal)


@bp.post("/transmittals/<transmittal_id>/agency-response")
def agency_response(transmittal_id):
    require_roles("FilingAgent")
    data = body()
    response_status = enum_field(
        data,
        "response_status",
        ("ACCEPTED", "ACCEPTED_WITH_ERRORS", "PARTIALLY_ACCEPTED", "REJECTED"),
    )
    receipt_id = string_field(data, "receipt_id", required=False)
    raw_errors = data.get("errors")
    if raw_errors is None:
        raw_errors = []
    if not isinstance(raw_errors, list):
        fail("ERR_INVALID_REQUEST", "errors must be an array.")
    entries = []
    for entry in raw_errors:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "each errors entry must be an object.")
        entries.append(
            {
                "form_1095c_id": string_field(entry, "form_1095c_id", required=False),
                "error_code": string_field(entry, "error_code"),
                "error_field": string_field(entry, "error_field"),
                "severity": enum_field(entry, "severity", SEVERITIES),
            }
        )
    if response_status == "ACCEPTED" and entries:
        fail("ERR_INVALID_REQUEST", "An ACCEPTED response carries no errors.")
    if response_status in ERRORED and not entries:
        fail("ERR_INVALID_REQUEST", "%s requires at least one errors entry." % response_status)
    if response_status == "PARTIALLY_ACCEPTED" and not any(
        e["severity"] == "FATAL" for e in entries
    ):
        fail("ERR_INVALID_REQUEST", "PARTIALLY_ACCEPTED requires a FATAL errors entry.")

    transmittal = lk.find("transmittals", transmittal_id)
    for entry in entries:
        if entry["form_1095c_id"]:
            lk.find("forms_1095c", entry["form_1095c_id"])
    if transmittal["status"] != "TRANSMITTED":
        fail("ERR_TRANSMITTAL_STATE_INVALID", "Only a TRANSMITTED submission has a response.")

    if receipt_id is not None:
        sync.set_field(transmittal, "receipt_id", receipt_id)

    blocking = "FATAL" if response_status == "PARTIALLY_ACCEPTED" else None
    errored_form_ids = set()
    for entry in entries:
        insert(
            "transmittal_errors",
            {
                "transmittal_id": transmittal["id"],
                "form_1095c_id": entry["form_1095c_id"],
                "error_code": entry["error_code"],
                "error_field": entry["error_field"],
                "severity": entry["severity"],
                "resolution_status": "OPEN",
                "resolution_note": None,
                "corrected_form_id": None,
                "resolved_by_user_id": None,
            },
        )
        if not entry["form_1095c_id"]:
            continue
        if blocking is None:
            if entry["severity"] in ("FATAL", "ERROR"):
                errored_form_ids.add(entry["form_1095c_id"])
        elif entry["severity"] == blocking:
            errored_form_ids.add(entry["form_1095c_id"])

    sync.set_field(transmittal, "status", response_status)
    for form in lk.forms_of_transmittal(transmittal):
        if form["filing_status"] != "PENDING_FILING":
            continue
        if response_status == "REJECTED":
            sync.set_field(form, "filing_status", "ATTACHED")
        elif form["id"] in errored_form_ids:
            sync.set_field(form, "filing_status", "FILED_WITH_ERRORS")
            if form["furnishing_status"] in sync.FURNISHED:
                sync.set_field(form, "furnishing_status", "REDELIVERY_REQUIRED")
        else:
            sync.set_field(form, "filing_status", "FILED_ACCEPTED")
    return ok(transmittal)


@bp.post("/transmittals/<transmittal_id>/start-correction-cycle")
def start_correction_cycle(transmittal_id):
    require_roles("Preparer")
    body()
    transmittal = lk.find("transmittals", transmittal_id)
    if transmittal["status"] not in ERRORED:
        fail("ERR_TRANSMITTAL_STATE_INVALID", "This submission has no reported errors.")
    if _open_error_count(transmittal) < 1:
        fail("ERR_TRANSMITTAL_STATE_INVALID", "Every reported error is already resolved.")
    if transmittal["cycle_number"] >= calc.CORRECTION_CYCLE_LIMIT:
        fail("ERR_CORRECTION_CYCLE_LIMIT", "The correction cycle limit has been reached.")
    sync.set_field(transmittal, "status", "CORRECTION_REQUIRED")
    return ok(transmittal)


# --------------------------------------------------------------------------- #
# TransmittalError
# --------------------------------------------------------------------------- #
@bp.post("/transmittal-errors")
def create_error():
    require_roles("FilingAgent")
    data = body()
    transmittal_id = string_field(data, "transmittal_id")
    form_1095c_id = string_field(data, "form_1095c_id")
    error_code = string_field(data, "error_code")
    error_field = string_field(data, "error_field")
    severity = enum_field(data, "severity", SEVERITIES)

    transmittal = lk.find("transmittals", transmittal_id)
    form = lk.find("forms_1095c", form_1095c_id)
    if form.get("transmittal_id") != transmittal["id"]:
        fail("ERR_SCOPE_MISMATCH", "That statement is not part of this submission.")
    if transmittal["status"] not in ERROR_HOLDING:
        fail(
            "ERR_TRANSMITTAL_STATE_INVALID",
            "Additional errors may only be recorded on an errored submission.",
        )

    record = insert(
        "transmittal_errors",
        {
            "transmittal_id": transmittal_id,
            "form_1095c_id": form_1095c_id,
            "error_code": error_code,
            "error_field": error_field,
            "severity": severity,
            "resolution_status": "OPEN",
            "resolution_note": None,
            "corrected_form_id": None,
            "resolved_by_user_id": None,
        },
    )
    return created(record)


@bp.get("/transmittal-errors")
def list_errors():
    return listing(
        "transmittal_errors",
        {
            "transmittal_id": ("transmittal_id", "str"),
            "form_1095c_id": ("form_1095c_id", "str"),
            "corrected_form_id": ("corrected_form_id", "str"),
            "resolution_status": ("resolution_status", "str"),
        },
        READ_ROLES,
    )


@bp.get("/transmittal-errors/<identifier>")
def read_error(identifier):
    return single_read("transmittal_errors", identifier, READ_ROLES)


@bp.post("/transmittal-errors/<error_id>/resolve")
def resolve_error(error_id):
    user_id, _role = require_roles("Preparer")
    data = body()
    resolution = enum_field(data, "resolution", ("CORRECT_FORM", "ACCEPT_AS_FILED"))
    note = string_field(data, "resolution_note", required=False)

    record = lk.find("transmittal_errors", error_id)
    if record["resolution_status"] != "OPEN":
        fail("ERR_ERROR_ALREADY_RESOLVED", "This agency error is already resolved.")
    if resolution == "ACCEPT_AS_FILED" and record["severity"] != "WARNING":
        fail(
            "ERR_ERROR_ALREADY_RESOLVED",
            "Only a WARNING may be accepted as filed.",
        )

    if resolution == "CORRECT_FORM":
        if not record.get("form_1095c_id"):
            fail("ERR_INVALID_REQUEST", "This error does not name a statement to correct.")
        form = lk.find("forms_1095c", record["form_1095c_id"])
        employee = lk.get("employees", form["employee_id"])
        season = lk.season_of_employee(employee) if employee else None
        correction = sync.draft_correction(form, employee, season, note, user_id)
        sync.set_field(record, "corrected_form_id", correction["id"])
        sync.set_field(record, "resolution_status", "CORRECTED")
        if form["filing_status"] == "FILED_WITH_ERRORS":
            sync.set_field(form, "filing_status", "CORRECTION_DRAFTED")
    else:
        sync.set_field(record, "resolution_status", "ACCEPTED_AS_FILED")

    sync.set_field(record, "resolution_note", note)
    sync.set_field(record, "resolved_by_user_id", user_id)
    touch(record)
    return ok(record)
