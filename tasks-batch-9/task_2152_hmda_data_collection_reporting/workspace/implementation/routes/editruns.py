"""The edit battery: running, verifying, clearing (PRD 3.6)."""

from flask import Blueprint

import calc
import cascades
import constants as C
import serializers as S
import store
from auth import authenticate
from errors import fail
from response import array_response, object_response
from validate import (Field, check, enum_filter, json_body, lookup, paginate,
                      pagination)

bp = Blueprint("editruns", __name__)

BACK_OFFICE_READ_ROLES = ["SystemAdmin", "InstitutionAdmin", "ComplianceAnalyst",
                          "ComplianceOfficer", "Examiner"]

CREATE_FIELDS = [
    Field("institution_id", "string", required=True),
    Field("scope", "string", required=True, enum=C.EDIT_RUN_SCOPES),
    Field("window_start", "datetime", required=True),
    Field("window_end", "datetime", required=True),
]

VERIFY_FIELDS = [Field("verification_note", "string", required=True)]

ALLOWED_ULI_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

EDIT_MESSAGES = {
    "S300": "Universal Loan Identifier is shorter than the required length.",
    "S301": "Universal Loan Identifier contains a character outside A-Z and 0-9.",
    "V610": "Income relied on is required for this action taken.",
    "V620": "Rate spread must not be reported for this action taken.",
    "V631": "The property has not been resolved to a census tract.",
    "Q607": "Loan amount is implausibly high relative to reported income.",
    "Q615": "The lag between application date and action taken date is implausibly long.",
    "Q620": "Loan amount is implausibly small.",
    "Q800": "The share of withdrawn applications in the register is implausibly high.",
}
EDIT_SEVERITY = {
    "S300": "SYNTACTICAL", "S301": "SYNTACTICAL",
    "V610": "VALIDITY", "V620": "VALIDITY", "V631": "VALIDITY",
    "Q607": "QUALITY", "Q615": "QUALITY", "Q620": "QUALITY",
    "Q800": "MACRO",
}


def _new_exception(run, application_id, edit_code, field_name):
    row = store.new_row()
    row.update({
        "edit_run_id": run["id"],
        "application_id": application_id,
        "edit_code": edit_code,
        "severity": EDIT_SEVERITY[edit_code],
        "field_name": field_name,
        "message": EDIT_MESSAGES[edit_code],
        "verification_note": None,
        "verified_by_user_id": None,
        "verified_at": None,
        "status": "OPEN",
    })
    store.edit_exceptions[row["id"]] = row
    return row


def _record_edits(app, inst):
    """The eight record-level edits, in the pinned catalogue order."""
    fired = []
    uli = app["uli"] or ""
    if len(uli) < C.ULI_MIN_LENGTH:
        fired.append(("S300", "uli"))
    if any(ch not in ALLOWED_ULI_CHARS for ch in uli):
        fired.append(("S301", "uli"))
    if (app["income_thousands"] is None
            and inst["partial_exemption_eligible"] is False
            and app["action_taken"] in ("ORIGINATED", "APPROVED_NOT_ACCEPTED", "DENIED")):
        fired.append(("V610", "income_thousands"))
    if (app["rate_spread"] is not None
            and app["action_taken"] in ("WITHDRAWN", "FILE_CLOSED_INCOMPLETE")):
        fired.append(("V620", "rate_spread"))
    assignment = calc.current_assignment(app["id"])
    if assignment is None or assignment["status"] in ("AMBIGUOUS", "NOT_MATCHED", "PENDING"):
        fired.append(("V631", "census_tract_id"))
    if (app["income_thousands"] is not None
            and app["loan_amount_cents"] >
            app["income_thousands"] * 100000 * C.QUALITY_LTI_MULTIPLE):
        fired.append(("Q607", "loan_amount_cents"))
    if (app["action_taken_date"] is not None and app["application_date"] is not None
            and calc.whole_days_between(app["application_date"], app["action_taken_date"])
            > C.QUALITY_DECISION_LAG_DAYS):
        fired.append(("Q615", "action_taken_date"))
    if app["loan_amount_cents"] < C.QUALITY_MIN_LOAN_CENTS:
        fired.append(("Q620", "loan_amount_cents"))
    return fired


@bp.route("/hmda/edit-runs", methods=["POST"])
def create_edit_run():
    authenticate(["ComplianceAnalyst"])
    body = check(json_body(), CREATE_FIELDS)
    inst = lookup(store.institutions, body["institution_id"], "ERR_INSTITUTION_NOT_FOUND")

    # step 14 -- interval well-formedness
    if body["window_end"] <= body["window_start"]:
        fail("ERR_INVALID_WINDOW")

    # step 15 -- half-open review windows on one institution
    new_start, new_end = body["window_start"], body["window_end"]
    for existing in store.edit_runs.values():
        if existing["institution_id"] != inst["id"] or existing["status"] == "INVALIDATED":
            continue
        if new_start < existing["window_end"] and existing["window_start"] < new_end:
            fail("ERR_EDIT_RUN_WINDOW_OVERLAP")

    earlier_runs = [r for r in store.ordered(store.edit_runs.values())
                    if r["institution_id"] == inst["id"] and r["status"] != "INVALIDATED"]

    inst["_run_index"] += 1
    run = store.new_row()
    run.update({
        "institution_id": inst["id"],
        "run_index": inst["_run_index"],
        "scope": body["scope"],
        "window_start": new_start,
        "window_end": new_end,
        "snapshot_record_count": 0,
        "syntactical_count": 0,
        "validity_count": 0,
        "quality_count": 0,
        "macro_count": 0,
        "total_exception_count": 0,
        "open_exception_count": 0,
        "verified_exception_count": 0,
        "stale_exception_count": 0,
        "cleared_record_count": 0,
        "required_verified_quota": 0,
        "status": "RUNNING",
        "_snapshot_ids": [],
        "_cleared_ids": set(),
    })
    store.edit_runs[run["id"]] = run

    # --- the snapshot, ordered by created_at ascending -----------------------
    snapshot = [a for a in store.ordered(store.applications.values())
                if a["institution_id"] == inst["id"]
                and a["action_taken"] is not None
                and a["is_superseded"] is False
                and a["lar_status"] != "EXCLUDED"
                and a["stage"] in ("DECISIONED", "REGISTER_LOCKED")]
    run["_snapshot_ids"] = [a["id"] for a in snapshot]
    run["snapshot_record_count"] = len(snapshot)

    severity_counts = {"SYNTACTICAL": 0, "VALIDITY": 0, "QUALITY": 0, "MACRO": 0}
    flagged_ids = set()
    for app in snapshot:
        for edit_code, field_name in _record_edits(app, inst):
            _new_exception(run, app["id"], edit_code, field_name)
            severity_counts[EDIT_SEVERITY[edit_code]] += 1
            flagged_ids.add(app["id"])

    # --- the macro edit, evaluated once over the whole snapshot --------------
    n = run["snapshot_record_count"]
    if n >= 1:
        withdrawn = sum(1 for a in snapshot if a["action_taken"] == "WITHDRAWN")
        # strict >, exact rational arithmetic rather than a float approximation
        if withdrawn * 1000 > int(C.MACRO_WITHDRAWN_PCT * 10) * n:
            _new_exception(run, None, "Q800", "action_taken")
            severity_counts["MACRO"] += 1

    run["syntactical_count"] = severity_counts["SYNTACTICAL"]
    run["validity_count"] = severity_counts["VALIDITY"]
    run["quality_count"] = severity_counts["QUALITY"]
    run["macro_count"] = severity_counts["MACRO"]
    run["total_exception_count"] = sum(severity_counts.values())
    run["open_exception_count"] = run["total_exception_count"]
    run["verified_exception_count"] = 0
    run["stale_exception_count"] = 0

    cleared_ids = set(a["id"] for a in snapshot if a["id"] not in flagged_ids)
    run["_cleared_ids"] = cleared_ids
    run["cleared_record_count"] = len(cleared_ids)

    # --- register-quality side effects on the snapshot -----------------------
    for app in snapshot:
        target = "EXCEPTION_FLAGGED" if app["id"] in flagged_ids else "CLEARED"
        if app["lar_status"] != target:
            app["lar_status"] = target
            store.bump(app)

    # --- where the run lands -------------------------------------------------
    if run["open_exception_count"] >= 1:
        run["status"] = "COMPLETED"
        run["required_verified_quota"] = calc.certification_verification_quota(
            run["snapshot_record_count"], run["quality_count"], run["macro_count"])
    else:
        run["status"] = "CLEARED_ALL"
        run["cleared_record_count"] = run["snapshot_record_count"]
        run["_cleared_ids"] = set(run["_snapshot_ids"])
        run["required_verified_quota"] = 0

    # --- superseding earlier runs -------------------------------------------
    for earlier in earlier_runs:
        cascades.stale_run_exceptions(earlier)
        cascades.invalidate_run(earlier)

    calc.recompute_institution_counters(inst)
    store.bump(inst)
    return object_response(S.edit_run(run), 201)


@bp.route("/hmda/edit-runs/<run_id>", methods=["GET"])
def get_edit_run(run_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    run = lookup(store.edit_runs, run_id, "ERR_EDIT_RUN_NOT_FOUND")
    return object_response(S.edit_run(run))


@bp.route("/hmda/edit-runs/<run_id>/exceptions", methods=["GET"])
def list_run_exceptions(run_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    lookup(store.edit_runs, run_id, "ERR_EDIT_RUN_NOT_FOUND")
    limit, offset = pagination()
    status = enum_filter("status", C.EDIT_EXCEPTION_STATUSES)
    severity = enum_filter("severity", C.EDIT_SEVERITIES)
    rows = [e for e in store.ordered(store.edit_exceptions.values())
            if e["edit_run_id"] == run_id
            and (status is None or e["status"] == status)
            and (severity is None or e["severity"] == severity)]
    items, total = paginate(rows, limit, offset, S.edit_exception)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/edit-runs/<run_id>/submissions", methods=["GET"])
def list_run_submissions(run_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    lookup(store.edit_runs, run_id, "ERR_EDIT_RUN_NOT_FOUND")
    limit, offset = pagination()
    rows = [s for s in store.ordered(store.filing_submissions.values())
            if s["edit_run_id"] == run_id]
    items, total = paginate(rows, limit, offset, S.filing_submission)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/edit-exceptions/<exception_id>/verify", methods=["POST"])
def verify_exception(exception_id):
    user_id, _role = authenticate(["ComplianceAnalyst"])
    exc = lookup(store.edit_exceptions, exception_id, "ERR_EDIT_EXCEPTION_NOT_FOUND")
    body = check(json_body(), VERIFY_FIELDS)

    # step 8 -- state preconditions
    if exc["status"] != "OPEN":
        fail("ERR_EXCEPTION_NOT_OPEN")
    app = None
    if exc["application_id"] is not None:
        app = store.applications.get(exc["application_id"])
        if app is not None and app["stage"] == "ARCHIVED":
            fail("ERR_APPLICATION_ARCHIVED")

    # step 15 -- only QUALITY and MACRO exceptions may be verified
    if exc["severity"] not in C.VERIFIABLE_SEVERITIES:
        fail("ERR_SEVERITY_NOT_VERIFIABLE")

    run = store.edit_runs[exc["edit_run_id"]]
    exc["status"] = "VERIFIED"
    exc["verification_note"] = body["verification_note"]
    exc["verified_by_user_id"] = user_id
    exc["verified_at"] = store.now()
    store.bump(exc)

    run["open_exception_count"] -= 1
    run["verified_exception_count"] += 1
    store.touch(run)

    # --- bubble-up in three hops --------------------------------------------
    if app is not None:
        remaining = cascades.open_exceptions_for_application(run["id"], app["id"])
        if not remaining and app["lar_status"] == "EXCEPTION_FLAGGED":
            app["lar_status"] = "CLEARED"
            store.bump(app)
            cascades.add_cleared_record(run, app["id"])
            inst = store.institutions.get(app["institution_id"])
            if inst is not None:
                calc.recompute_institution_counters(inst)
    if (run["status"] == "COMPLETED"
            and run["cleared_record_count"] == run["snapshot_record_count"]):
        run["status"] = "CLEARED_ALL"
        store.touch(run)

    return object_response(S.edit_exception(exc))
