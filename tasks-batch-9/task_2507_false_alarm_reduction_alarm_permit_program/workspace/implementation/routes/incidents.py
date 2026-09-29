"""False alarm incidents: reporting, determination and administrative void."""

from flask import Blueprint

import calc
import engine
import rt
from core import (F, authenticate, check_owner, created, listing, ok, q,
                  q_instant, validate)
from errors import ApiError
from store import base_row, now, store, touch

bp = Blueprint("incidents", __name__)

REPORT_ROLES = ["PoliceDispatchSupervisor", "FalseAlarmReviewOfficer",
                "AlarmCompanyOperator"]
RULE_ROLES = ["FalseAlarmReviewOfficer", "ProgramAdministrator"]
READ_ROLES = ["ProgramAdministrator", "FalseAlarmReviewOfficer",
              "HearingOfficer", "PoliceDispatchSupervisor", "PermitClerk",
              "BillingClerk", "AlarmCompanyOperator", "AlarmUser"]

CAUSE_CODES = ("OPERATOR_ERROR", "EQUIPMENT_MALFUNCTION", "UNKNOWN",
               "ANIMAL_MOVEMENT", "OPEN_DOOR_WINDOW", "SEVERE_WEATHER",
               "UTILITY_POWER_FAILURE", "TELEPHONE_LINE_FAILURE",
               "AUTHORIZED_TEST_WITH_NOTICE", "CRIMINAL_OFFENSE_CONFIRMED",
               "NEW_INSTALLATION_GRACE")

CREATE_FIELDS = [
    F("dispatch_request_id", "uuid"),
    F("cause_code", "enum", values=CAUSE_CODES),
    F("narrative", "string", required=False),
]

RULE_FIELDS = [
    F("determination", "enum", values=("COUNTED", "EXEMPT")),
    F("exempt_cause_code", "string", required=False),
    F("review_notes", "string", required=False),
]

VOID_FIELDS = [F("void_reason", "string")]


def _company_of(incident):
    system = store.alarm_systems.get(incident.get("alarm_system_id")) or {}
    return system.get("monitoring_company_id")


def _scope(ctx, rows):
    if ctx.role == "AlarmUser":
        return [r for r in rows if r.get("alarm_site_id") == ctx.user_id]
    if ctx.role == "AlarmCompanyOperator":
        return [r for r in rows if _company_of(r) == ctx.user_id]
    return rows


@bp.post("/false-alarm-incidents")
def create_incident():
    ctx = authenticate(REPORT_ROLES)
    data = validate(ctx.body, CREATE_FIELDS)
    req = rt.resolve("DispatchRequest", data["dispatch_request_id"])
    check_owner(ctx, company_id=req.get("monitoring_company_id"))
    if req.get("status") != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE",
                       "An incident may only be opened against a DISPATCHED "
                       "request.")
    if engine.incident_for_request(req["id"]) is not None:
        raise ApiError("ERR_INCIDENT_ALREADY_REPORTED",
                       "This dispatch request already has a live incident.")
    company = store.alarm_companies.get(req.get("monitoring_company_id"))
    if company is None or company.get("status") not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED",
                       "This company's dispatch privilege is withdrawn.")
    row = base_row()
    row["dispatch_request_id"] = req["id"]
    row["alarm_site_id"] = req.get("alarm_site_id")
    row["alarm_system_id"] = req.get("alarm_system_id")
    row["occurred_at"] = req.get("occurred_at")
    row["cause_code"] = data["cause_code"]
    row["status"] = "REPORTED"
    row["determination"] = None
    row["exempt_cause_code"] = None
    row["determined_at"] = None
    row["determined_by_user_id"] = None
    row["occurrence_index"] = None
    row["assessed_fee_cents"] = None
    row["fee_basis"] = None
    row["counted_window_mode"] = None
    row["appeal_count"] = 0
    row["narrative"] = data.get("narrative")
    store.false_alarm_incidents[row["id"]] = row
    touch(req)
    return created(row)


@bp.post("/false-alarm-incidents/<incident_id>/determination")
def determine_incident(incident_id):
    ctx = authenticate(RULE_ROLES)
    data = validate(ctx.body, RULE_FIELDS)
    incident = rt.resolve("FalseAlarmIncident", incident_id)
    req = store.dispatch_requests.get(incident.get("dispatch_request_id")) or {}
    if req.get("validated_by_user_id") is not None \
            and req.get("validated_by_user_id") == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The supervisor who released the patrol may not rule on "
                       "the alarm.")
    if incident.get("status") not in ("REPORTED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE",
                       "A %s incident may not be determined."
                       % incident.get("status"))
    site = store.alarm_sites.get(incident.get("alarm_site_id"))
    sched = engine.governing_schedule(site) if site else None
    # Recognizing an exempt cause code is a constant lookup (position 22/23),
    # not the money gate, so an unpinned premises may fall back to the
    # published ordinance row itself.
    reference = sched or engine.active_status_schedule()
    exempt_codes = list((reference or {}).get("exempt_cause_codes") or [])
    supplied = data.get("exempt_cause_code")
    grace_through = None
    for permit in engine.site_permits(incident.get("alarm_site_id")):
        if permit.get("new_installation_grace_through") is not None:
            grace_through = permit["new_installation_grace_through"]
            break
    if supplied is not None and supplied not in exempt_codes:
        if not (supplied == "NEW_INSTALLATION_GRACE" and grace_through is not None
                and incident.get("occurred_at") is not None
                and incident["occurred_at"] <= grace_through):
            raise ApiError("ERR_EXEMPT_CAUSE_NOT_RECOGNIZED",
                           "'%s' is not an exempt cause on the governing "
                           "schedule." % supplied)
    determination = data["determination"]
    if determination == "EXEMPT" and supplied is None:
        raise ApiError("ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT",
                       "An EXEMPT ruling must supply an exempt cause.")
    if determination == "COUNTED" and supplied is not None:
        raise ApiError("ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT",
                       "A COUNTED ruling must not supply an exempt cause.")

    # Every rejection is raised before any mutation, so a refused ruling leaves
    # the incident exactly where it was (PRD 2.10: rejection precedes effect).
    if determination == "COUNTED":
        if incident.get("cause_code") in exempt_codes:
            raise ApiError("ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT",
                           "This cause code forces an exempt determination.")
        if grace_through is not None \
                and incident.get("occurred_at") is not None \
                and incident["occurred_at"] <= grace_through:
            raise ApiError("ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT",
                           "The incident falls inside the new-installation "
                           "grace.")
        if site is None or sched is None:
            raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE",
                           "The premises is not pinned to a governing schedule.")

    # REPORTED -> UNDER_REVIEW happens inside this same request.
    incident["status"] = "UNDER_REVIEW"
    incident["determination"] = None
    incident["exempt_cause_code"] = None
    incident["determined_at"] = None
    incident["determined_by_user_id"] = None

    if determination == "EXEMPT":
        incident["status"] = "EXEMPT"
        incident["determination"] = "EXEMPT"
        incident["exempt_cause_code"] = supplied
        incident["determined_at"] = now()
        incident["determined_by_user_id"] = ctx.user_id
        # PRD 3.5: the exempt branch "leaves `occurrence_index` null and
        # `assessed_fee_cents` at 0".
        incident["occurrence_index"] = None
        incident["assessed_fee_cents"] = 0
        touch(incident)
        return ok(incident)

    incident["status"] = "COUNTED"
    incident["determination"] = "COUNTED"
    incident["determined_at"] = now()
    incident["determined_by_user_id"] = ctx.user_id
    incident["occurrence_index"] = engine.occurrence_index_for(site, sched,
                                                               incident)
    incident["counted_window_mode"] = sched.get("counting_window_mode")
    assessed, basis, detail = engine.price_incident(site, sched, incident)
    incident["assessed_fee_cents"] = assessed
    incident["fee_basis"] = basis
    touch(incident)
    if assessed > 0:
        engine.new_invoice(site, sched, "FALSE_ALARM_FEE",
                           calc.false_alarm_lines(sched, detail),
                           "false_alarm_incident_id", incident["id"])
    engine.rollup_site(site)
    engine.auto_propose_suspension(site, sched, incident)
    engine.rollup_site(site, bump=False)
    return ok(incident)


@bp.post("/false-alarm-incidents/<incident_id>/void")
def void_incident(incident_id):
    ctx = authenticate(["ProgramAdministrator"])
    validate(ctx.body, VOID_FIELDS)
    incident = rt.resolve("FalseAlarmIncident", incident_id)
    if incident.get("status") not in ("REPORTED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REPORTED or UNDER_REVIEW incident may be voided.")
    incident["status"] = "VOIDED"
    incident["occurrence_index"] = None
    touch(incident)
    site = store.alarm_sites.get(incident.get("alarm_site_id"))
    if site is not None:
        invoice = engine.invoice_for_incident(incident["id"])
        if invoice is not None:
            engine.void_invoice_cascade(invoice, site)
        engine.renumber_and_reprice(site)
        engine.rollup_site(site)
    return ok(incident)


@bp.get("/false-alarm-incidents/<incident_id>")
def get_incident(incident_id):
    ctx = authenticate(READ_ROLES)
    incident = rt.resolve("FalseAlarmIncident", incident_id)
    check_owner(ctx, site_id=incident.get("alarm_site_id"),
                company_id=_company_of(incident))
    return ok(incident)


@bp.get("/false-alarm-incidents")
def list_incidents():
    ctx = authenticate(READ_ROLES)
    rows = _scope(ctx, rt.all_rows("FalseAlarmIncident"))
    for field in ("dispatch_request_id", "alarm_site_id", "alarm_system_id",
                  "status", "determination"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    occurred_from = q_instant("occurred_from")
    occurred_to = q_instant("occurred_to")
    if occurred_from is not None:
        rows = [r for r in rows if r.get("occurred_at") is not None
                and r["occurred_at"] >= occurred_from]
    if occurred_to is not None:
        rows = [r for r in rows if r.get("occurred_at") is not None
                and r["occurred_at"] <= occurred_to]
    return listing(rows, rt.fields("FalseAlarmIncident"))
