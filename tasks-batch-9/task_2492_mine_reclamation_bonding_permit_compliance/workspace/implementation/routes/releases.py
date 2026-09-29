"""Incremental bond release: notice, comment, inspection and decision (PRD 3.5)."""

from flask import Blueprint

import calculations as calc
import constants as C
import engine
import serialization as ser
from db import D, ZERO, base_row, days, db, money, now
from engine import PHASE_ACRE_FIELD, bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    check_decision_reason,
    collection_filtered,
    precheck_denial_reason,
    require_permit_operator,
    require_permit_status,
    require_state,
)
from validation import (
    authorize,
    bool_field,
    enum_field,
    get_body,
    lookup,
    number_field,
    resolve,
    str_field,
)

bp = Blueprint("releases", __name__)

LIST_FILTERS = [
    ("permit_id", "permit_id", None),
    ("inspection_id", "inspection_id", None),
    ("status", "status", C.RELEASE_STATUSES),
    ("phase", "phase", C.RELEASE_PHASES),
]

COMPLIANT_POSTURES = ("COMPLIANT", "NOTICE_ACTIVE")


def _require_compliant(permit):
    if permit["compliance_posture"] not in COMPLIANT_POSTURES:
        raise ApiError(
            "ERR_PERMIT_NOT_COMPLIANT",
            "The permit's compliance posture does not admit this operation.",
        )


@bp.post("/mining/bond-release-applications")
def create_release():
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    permit_id = str_field(body, "permit_id")
    phase = enum_field(body, "phase", C.RELEASE_PHASES)
    acres_requested = number_field(body, "acres_requested", gt=0)

    permit = resolve(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    require_permit_operator(role, user_id, permit)
    require_permit_status(permit, C.PERMIT_STATUSES_RELEASE)

    # Band 13 — the phase acreage sanity check.
    already = D(permit[PHASE_ACRE_FIELD[phase]])
    if D(acres_requested) + already > D(permit["disturbed_acres"]):
        raise ApiError(
            "ERR_ACRES_EXCEED_DISTURBED",
            "The acreage claimed for this phase exceeds the permit's disturbed acreage.",
        )

    row = base_row()
    row.update(
        {
            "permit_id": permit_id,
            "phase": phase,
            "acres_requested": acres_requested,
            "requested_amount": calc.release_requested_amount(permit, phase, acres_requested),
            "approved_amount": ZERO,
            "status": "SUBMITTED",
            "notice_start_date": None,
            "notice_end_date": None,
            "comment_count": 0,
            "objection_count": 0,
            "objections_resolved": False,
            "inspection_id": None,
            "decided_by_user_id": None,
            "approved_at": None,
            "denial_reason": None,
            "rescission_reason": None,
        }
    )
    db.release_apps[row["id"]] = row
    return created_response(ser.release_out(row))


@bp.get("/mining/bond-release-applications/<application_id>")
def get_release(application_id):
    authorize(C.ROLES_OP_STAFF_PUBLIC)
    row = lookup(db.release_apps, application_id, "ERR_RELEASE_APPLICATION_NOT_FOUND")
    return object_response(ser.release_out(row))


@bp.get("/mining/bond-release-applications")
def list_releases():
    authorize(C.ROLES_OP_STAFF_PUBLIC)
    return collection_filtered(db.release_apps.values(), LIST_FILTERS, ser.release_out)


@bp.post("/mining/bond-release-applications/<application_id>/publish-notice")
def publish_notice(application_id):
    authorize([C.ROLE_BOND_SPECIALIST])
    get_body()
    app_row = lookup(db.release_apps, application_id, "ERR_RELEASE_APPLICATION_NOT_FOUND")
    permit = db.permits[app_row["permit_id"]]

    # Band 9.
    require_state(app_row, "status", ["SUBMITTED"], "ERR_RELEASE_STATE_INVALID")
    # Band 11.
    _require_compliant(permit)
    # Band 15 — the fifteen-day temporal exclusion over the permit's windows.
    if engine.notice_window_conflict(permit, app_row):
        raise ApiError(
            "ERR_NOTICE_WINDOW_CONFLICT",
            "The new notice window opens within fifteen days of another window on this permit.",
        )

    start = now()
    app_row["status"] = "PUBLIC_NOTICE"
    app_row["notice_start_date"] = start
    app_row["notice_end_date"] = start + days(C.PUBLIC_NOTICE_DAYS)
    bump(app_row)

    before = permit["last_notice_end_date"]
    engine.recompute_last_notice_end_date(permit)
    if permit["last_notice_end_date"] != before:
        bump(permit)

    return object_response(ser.release_out(app_row))


@bp.post("/mining/bond-release-applications/<application_id>/comment")
def comment(application_id):
    authorize([C.ROLE_PUBLIC_PARTICIPANT])
    body = get_body()
    str_field(body, "comment_text")
    is_objection = bool_field(body, "is_objection")

    app_row = lookup(db.release_apps, application_id, "ERR_RELEASE_APPLICATION_NOT_FOUND")
    require_state(app_row, "status", ["PUBLIC_NOTICE"], "ERR_RELEASE_STATE_INVALID")

    app_row["comment_count"] = app_row["comment_count"] + 1
    if is_objection:
        app_row["objection_count"] = app_row["objection_count"] + 1
    bump(app_row)
    return object_response(ser.release_out(app_row))


@bp.post("/mining/bond-release-applications/<application_id>/resolve-objections")
def resolve_objections(application_id):
    authorize([C.ROLE_BOND_SPECIALIST])
    body = get_body()
    str_field(body, "resolution_note")

    app_row = lookup(db.release_apps, application_id, "ERR_RELEASE_APPLICATION_NOT_FOUND")
    require_state(app_row, "status", ["PUBLIC_NOTICE"], "ERR_RELEASE_STATE_INVALID")

    app_row["objections_resolved"] = True
    bump(app_row)
    return object_response(ser.release_out(app_row))


@bp.post("/mining/bond-release-applications/<application_id>/decide")
def decide_release(application_id):
    user_id, role = authorize([C.ROLE_BOND_SPECIALIST])
    body = get_body()
    decision = enum_field(body, "decision", C.DECISIONS_APPROVE)
    inspection_id = str_field(body, "inspection_id")
    precheck_denial_reason(body)

    app_row = lookup(db.release_apps, application_id, "ERR_RELEASE_APPLICATION_NOT_FOUND")
    permit = db.permits[app_row["permit_id"]]

    # Band 5.
    inspection = resolve(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")

    # Band 7 — segregation of duties over every ACCEPTED instrument on the permit.
    for instrument in db.instruments.values():
        if (
            instrument["permit_id"] == permit["id"]
            and instrument["status"] == "ACCEPTED"
            and instrument["accepted_by_user_id"] == user_id
        ):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "A specialist who accepted security on this permit may not decide its release.",
            )

    # Band 9.
    require_state(app_row, "status", ["PUBLIC_NOTICE"], "ERR_RELEASE_STATE_INVALID")

    # Band 10 — eligibility of the cited inspection.
    eligible = (
        inspection["permit_id"] == permit["id"]
        and inspection["inspection_type"] == "RELEASE"
        and inspection["status"] == "COMPLETED"
    )
    if eligible and decision == "APPROVE":
        eligible = inspection["result"] == "PASS"
    if not eligible:
        raise ApiError(
            "ERR_INSPECTION_NOT_ELIGIBLE",
            "The cited inspection does not support this release decision.",
        )

    # Band 11 — public money is not returned while a violation stands.
    if engine.has_notice_in(permit["id"], ("ISSUED", "CESSATION_ORDERED")):
        raise ApiError(
            "ERR_UNABATED_VIOLATION",
            "An unabated violation notice stands against this permit.",
        )

    # Band 12 — the notice period must have elapsed.
    end = app_row["notice_end_date"]
    if end is None or not now() > end:
        raise ApiError(
            "ERR_NOTICE_PERIOD_NOT_ELAPSED",
            "The public notice period for this application has not yet elapsed.",
        )

    # Band 13.
    denial_reason = check_decision_reason(decision, body)

    if decision == "APPROVE":
        # Band 14.
        if app_row["objection_count"] > 0 and not app_row["objections_resolved"]:
            raise ApiError(
                "ERR_OBJECTIONS_UNRESOLVED",
                "Public objections on this application have not been disposed of.",
            )
        # Band 15 — headroom recomputed at decision time.
        available = calc.available_headroom(permit, app_row["phase"])
        if D(app_row["requested_amount"]) > available:
            raise ApiError(
                "ERR_RELEASE_EXCEEDS_AVAILABLE",
                "The requested release exceeds the bond available above the retention floor.",
            )

        app_row["status"] = "APPROVED"
        app_row["approved_amount"] = money(app_row["requested_amount"])
        app_row["approved_at"] = now()
        app_row["inspection_id"] = inspection_id
        app_row["decided_by_user_id"] = user_id
        bump(app_row)

        permit["bond_released_to_date"] = money(
            D(permit["bond_released_to_date"]) + D(app_row["approved_amount"])
        )
        engine.refresh_bond_ledger(permit)
        field = PHASE_ACRE_FIELD[app_row["phase"]]
        permit[field] = money(D(permit[field]) + D(app_row["acres_requested"]))
        engine.evaluate_termination(permit, app_row)
        engine.recompute_posture(permit)
        bump(permit)
    else:
        app_row["status"] = "DENIED"
        app_row["denial_reason"] = denial_reason
        app_row["inspection_id"] = inspection_id
        app_row["decided_by_user_id"] = user_id
        bump(app_row)
        # The permit is deliberately untouched: its version does not move.

    return object_response(ser.release_out(app_row))


@bp.post("/mining/bond-release-applications/<application_id>/reinstate")
def reinstate(application_id):
    authorize([C.ROLE_BOND_SPECIALIST])
    get_body()
    app_row = lookup(db.release_apps, application_id, "ERR_RELEASE_APPLICATION_NOT_FOUND")
    permit = db.permits[app_row["permit_id"]]

    require_state(app_row, "status", ["SUSPENDED"], "ERR_RELEASE_STATE_INVALID")
    _require_compliant(permit)

    app_row["status"] = "SUBMITTED"
    app_row["requested_amount"] = calc.release_requested_amount(
        permit, app_row["phase"], app_row["acres_requested"]
    )
    bump(app_row)
    return object_response(ser.release_out(app_row))


@bp.post("/mining/bond-release-applications/<application_id>/rescind")
def rescind(application_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    rescission_reason = str_field(body, "rescission_reason")

    app_row = lookup(db.release_apps, application_id, "ERR_RELEASE_APPLICATION_NOT_FOUND")
    permit = db.permits[app_row["permit_id"]]

    # Band 9, then band 10.
    require_state(app_row, "status", ["APPROVED"], "ERR_RELEASE_STATE_INVALID")
    require_permit_status(permit, C.PERMIT_STATUSES_RELEASE)

    # Band 12 — the sixty-day compensating window.
    approved_at = app_row["approved_at"]
    if approved_at is None or now() > approved_at + days(C.RESCISSION_WINDOW_DAYS):
        raise ApiError(
            "ERR_RESCISSION_WINDOW_CLOSED",
            "The sixty-day window for rescinding this release has closed.",
        )

    approved_amount = D(app_row["approved_amount"])
    permit["bond_released_to_date"] = money(
        D(permit["bond_released_to_date"]) - approved_amount
    )
    field = PHASE_ACRE_FIELD[app_row["phase"]]
    permit[field] = money(D(permit[field]) - D(app_row["acres_requested"]))

    app_row["status"] = "RESCINDED"
    app_row["approved_amount"] = ZERO
    app_row["rescission_reason"] = rescission_reason
    bump(app_row)

    engine.refresh_bond_ledger(permit)
    engine.recompute_posture(permit)
    bump(permit)

    return object_response(ser.release_out(app_row))
