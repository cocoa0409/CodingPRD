"""Monogram program licenses, quality-system audits and the finding register (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import calcs
import domain
from auth import ANY, require_action_role, require_roles
from db import clock_iso, clock_now, db, iso_ms, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    SEVERITIES,
    VALVE_TYPES,
    filter_value,
    get_body,
    get_datetime,
    get_enum,
    get_enum_array,
    get_string,
    invalid,
    paginate,
    parse_pagination,
)

bp = Blueprint("monogram_licenses", __name__)

ACTION_ROLES = {
    "SCHEDULE_AUDIT": ["MonogramAuditor"],
    "START_AUDIT": ["MonogramAuditor"],
    "CLOSE_AUDIT": ["MonogramAuditor"],
    "GRANT": ["MonogramAuditor"],
    "GRANT_CONDITIONAL": ["MonogramAuditor"],
    "DENY": ["MonogramAuditor"],
    "SUSPEND": ["MonogramAuditor"],
    "REINSTATE": ["MonogramAuditor"],
}
ACTIONS = list(ACTION_ROLES.keys())

ENTRY_ROLES = {
    "RAISE": ["MonogramAuditor"],
    "CLOSE": ["MonogramAuditor"],
    "WAIVE": ["MonogramAuditor"],
}
ENTRY_ACTIONS = list(ENTRY_ROLES.keys())


@bp.post("/valve-mfg/monogram-licenses")
def create_license():
    require_roles(["QualityManager"])
    body = get_body()
    license_code = get_string(body, "license_code")
    facility_code = get_string(body, "facility_code")
    scope_valve_types = get_enum_array(body, "scope_valve_types", VALVE_TYPES)
    lead_auditor_user_id = get_string(body, "lead_auditor_user_id")
    start_raw, start_dt = get_datetime(body, "audit_window_start")
    end_raw, end_dt = get_datetime(body, "audit_window_end")
    if start_dt >= end_dt:
        raise invalid("audit_window_start must be strictly before audit_window_end")

    for row in db.licenses.values():
        if row["license_code"] == license_code:
            raise api_error(
                "ERR_DUPLICATE_CODE",
                "license_code '%s' is already in use" % license_code,
            )

    row = new_row(
        {
            "license_code": license_code,
            "facility_code": facility_code,
            "scope_valve_types": scope_valve_types,
            "lead_auditor_user_id": lead_auditor_user_id,
            "audit_window_start": start_raw,
            "audit_window_end": end_raw,
            "_audit_window_start_dt": start_dt,
            "_audit_window_end_dt": end_dt,
            "license_status": "APPLIED",
            "audit_state": "SCHEDULED",
            "total_major_raised": 0,
            "total_minor_raised": 0,
            "closed_major_finding_count": 0,
            "waived_major_finding_count": 0,
            "_closed_minor_count": 0,
            "last_audit_closed_at": None,
            "_last_audit_closed_dt": None,
            "granted_at": None,
            "conditional_expires_at": None,
            "_conditional_expires_dt": None,
        }
    )
    db.licenses[row["id"]] = row
    return object_response(domain.serialize_license(row), 201)


@bp.get("/valve-mfg/monogram-licenses")
def list_licenses():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.licenses.values()))
    serialized = [domain.serialize_license(r) for r in rows]
    for param in ("license_status", "audit_state", "compliance_posture"):
        value = filter_value(param)
        if value is not None:
            serialized = [r for r in serialized if r[param] == value]
    page, total = paginate(serialized, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/valve-mfg/monogram-licenses/<license_id>")
def get_license(license_id):
    require_roles(ANY)
    row = domain.find_license(license_id)
    return object_response(domain.serialize_license(row))


def _resume_orders_after_reinstate():
    for order in sort_rows(list(db.orders.values())):
        if order.get("status") != "HELD":
            continue
        if order.get("held_reason") != "UNIT_DECERTIFIED":
            continue
        remaining = False
        for unit in domain.units_of_order(order["id"]):
            domain.refresh_unit(unit)
            if unit.get("cert_status") == "DECERTIFIED":
                remaining = True
                break
        if remaining:
            continue
        order["status"] = "IN_PRODUCTION"
        order["held_reason"] = None
        touch(order)


def _suspend(lic):
    lic["license_status"] = "SUSPENDED"
    touch(lic)
    domain.decertify_units_of_license(lic, "LICENSE_SUSPENDED")


@bp.post("/valve-mfg/monogram-licenses/<license_id>/actions")
def license_actions(license_id):
    _user_id, role = require_roles(["MonogramAuditor"])
    body = get_body()
    action = get_enum(body, "action", ACTIONS)
    require_action_role(role, action, ACTION_ROLES)

    start_raw = start_dt = end_raw = end_dt = None
    if action == "SCHEDULE_AUDIT":
        start_raw, start_dt = get_datetime(body, "audit_window_start")
        end_raw, end_dt = get_datetime(body, "audit_window_end")
        if start_dt >= end_dt:
            raise invalid("audit_window_start must be strictly before audit_window_end")

    lic = domain.find_license(license_id)
    domain.refresh_license(lic)

    if action == "SCHEDULE_AUDIT":
        if lic["audit_state"] != "CLOSED":
            raise api_error(
                "ERR_STATE_INVALID",
                "SCHEDULE_AUDIT requires audit_state CLOSED (current: %s)"
                % lic["audit_state"],
            )
        closed_dt = lic.get("_last_audit_closed_dt")
        if closed_dt is not None:
            earliest = closed_dt + timedelta(days=calcs.AUDIT_COOLING_OFF_DAYS)
            if start_dt < earliest:
                raise api_error(
                    "ERR_AUDIT_COOLING_OFF_ACTIVE",
                    "the next audit window may not start before %s" % iso_ms(earliest),
                )
        lic["audit_window_start"] = start_raw
        lic["audit_window_end"] = end_raw
        lic["_audit_window_start_dt"] = start_dt
        lic["_audit_window_end_dt"] = end_dt
        lic["audit_state"] = "SCHEDULED"
        touch(lic)

    elif action == "START_AUDIT":
        if lic["audit_state"] != "SCHEDULED":
            raise api_error(
                "ERR_STATE_INVALID",
                "START_AUDIT requires audit_state SCHEDULED (current: %s)"
                % lic["audit_state"],
            )
        if clock_now() < lic["_audit_window_start_dt"]:
            raise api_error(
                "ERR_STATE_INVALID", "the audit window has not opened yet"
            )
        lic["audit_state"] = "IN_PROGRESS"
        touch(lic)

    elif action == "CLOSE_AUDIT":
        if lic["audit_state"] != "IN_PROGRESS":
            raise api_error(
                "ERR_STATE_INVALID",
                "CLOSE_AUDIT requires audit_state IN_PROGRESS (current: %s)"
                % lic["audit_state"],
            )
        lic["audit_state"] = "CLOSED"
        lic["last_audit_closed_at"] = clock_iso()
        lic["_last_audit_closed_dt"] = clock_now()
        touch(lic)

    elif action in ("GRANT", "GRANT_CONDITIONAL", "DENY"):
        allowed_from = ("APPLIED", "CONDITIONAL") if action == "GRANT" else ("APPLIED",)
        if lic["license_status"] not in allowed_from:
            raise api_error(
                "ERR_STATE_INVALID",
                "%s is not available from license_status %s"
                % (action, lic["license_status"]),
            )
        if lic["audit_state"] != "CLOSED":
            raise api_error(
                "ERR_STATE_INVALID",
                "the audit must be CLOSED before a closeout decision (current: %s)"
                % lic["audit_state"],
            )
        open_major, open_minor = domain.license_counts(lic)
        if action == "GRANT":
            if open_major != 0:
                raise api_error(
                    "ERR_OPEN_MAJOR_FINDINGS",
                    "GRANT requires zero open major findings (open: %s)" % open_major,
                )
            if open_minor > calcs.MINOR_FINDING_CONDITIONAL_THRESHOLD - 1:
                raise api_error(
                    "ERR_MINOR_FINDING_THRESHOLD",
                    "GRANT requires 4 or fewer open minor findings (open: %s)"
                    % open_minor,
                )
            lic["license_status"] = "GRANTED"
            lic["granted_at"] = clock_iso()
            lic["conditional_expires_at"] = None
            lic["_conditional_expires_dt"] = None
            touch(lic)
        elif action == "GRANT_CONDITIONAL":
            if open_major != 0:
                raise api_error(
                    "ERR_OPEN_MAJOR_FINDINGS",
                    "GRANT_CONDITIONAL requires zero open major findings (open: %s)"
                    % open_major,
                )
            if open_minor < calcs.MINOR_FINDING_CONDITIONAL_THRESHOLD:
                raise api_error(
                    "ERR_MINOR_FINDING_THRESHOLD",
                    "GRANT_CONDITIONAL requires 5 or more open minor findings (open: %s)"
                    % open_minor,
                )
            granted = clock_now()
            expires = granted + timedelta(days=calcs.CONDITIONAL_VALIDITY_DAYS)
            lic["license_status"] = "CONDITIONAL"
            lic["granted_at"] = iso_ms(granted)
            lic["conditional_expires_at"] = iso_ms(expires)
            lic["_conditional_expires_dt"] = expires
            touch(lic)
        else:  # DENY
            if open_major < 1:
                raise api_error(
                    "ERR_OPEN_MAJOR_FINDINGS",
                    "DENY requires at least one open major finding",
                )
            lic["license_status"] = "DENIED"
            touch(lic)
            domain.decertify_units_of_license(lic, "LICENSE_DENIED")

    elif action == "SUSPEND":
        if lic["license_status"] not in ("GRANTED", "CONDITIONAL"):
            raise api_error(
                "ERR_STATE_INVALID",
                "SUSPEND requires license_status GRANTED or CONDITIONAL (current: %s)"
                % lic["license_status"],
            )
        _suspend(lic)

    else:  # REINSTATE
        if lic["license_status"] != "SUSPENDED":
            raise api_error(
                "ERR_STATE_INVALID",
                "REINSTATE requires license_status SUSPENDED (current: %s)"
                % lic["license_status"],
            )
        open_major, _open_minor = domain.license_counts(lic)
        if open_major != 0:
            raise api_error(
                "ERR_OPEN_MAJOR_FINDINGS",
                "REINSTATE requires zero open major findings (open: %s)" % open_major,
            )
        lic["license_status"] = "GRANTED"
        touch(lic)
        _resume_orders_after_reinstate()

    return object_response(domain.serialize_license(lic))


@bp.post("/valve-mfg/monogram-licenses/<license_id>/finding-entries")
def finding_entries(license_id):
    user_id, role = require_roles(["MonogramAuditor"])
    body = get_body()
    entry_action = get_enum(body, "entry_action", ENTRY_ACTIONS)
    require_action_role(role, entry_action, ENTRY_ROLES)
    severity = get_enum(body, "severity", SEVERITIES)
    if entry_action == "WAIVE" and severity == "MINOR":
        raise invalid("only a MAJOR finding may be waived")

    lic = domain.find_license(license_id)
    domain.refresh_license(lic)

    if entry_action == "RAISE":
        if severity == "MAJOR":
            lic["total_major_raised"] = lic.get("total_major_raised", 0) + 1
        else:
            lic["total_minor_raised"] = lic.get("total_minor_raised", 0) + 1
        touch(lic)
        open_major, _open_minor = domain.license_counts(lic)
        if open_major >= calcs.MAJOR_FINDING_FREEZE_THRESHOLD and lic[
            "license_status"
        ] in ("GRANTED", "CONDITIONAL"):
            _suspend(lic)

    elif entry_action == "CLOSE":
        open_major, open_minor = domain.license_counts(lic)
        if severity == "MAJOR":
            if open_major < 1:
                raise api_error(
                    "ERR_STATE_INVALID", "there is no open MAJOR finding to close"
                )
            lic["closed_major_finding_count"] = (
                lic.get("closed_major_finding_count", 0) + 1
            )
        else:
            if open_minor < 1:
                raise api_error(
                    "ERR_STATE_INVALID", "there is no open MINOR finding to close"
                )
            lic["_closed_minor_count"] = lic.get("_closed_minor_count", 0) + 1
        touch(lic)

    else:  # WAIVE
        if user_id == lic["lead_auditor_user_id"]:
            raise api_error(
                "ERR_SOD_AUDIT_WAIVER_CONFLICT",
                "the lead auditor of this license may not waive its findings",
            )
        open_major, _open_minor = domain.license_counts(lic)
        if open_major < 1:
            raise api_error(
                "ERR_STATE_INVALID", "there is no open MAJOR finding to waive"
            )
        lic["waived_major_finding_count"] = lic.get("waived_major_finding_count", 0) + 1
        touch(lic)

    return object_response(domain.serialize_license(lic))
