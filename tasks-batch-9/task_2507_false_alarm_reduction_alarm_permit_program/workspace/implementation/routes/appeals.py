"""Appeals: filing, seating, decision and withdrawal."""

from flask import Blueprint

import engine
import rt
from core import (F, authenticate, check_owner, created, listing, ok, q,
                  validate)
from errors import ApiError
from store import add_days, base_row, now, store, touch

bp = Blueprint("appeals", __name__)

FILE_ROLES = ["AlarmUser", "ProgramAdministrator"]
SCHEDULE_ROLES = ["ProgramAdministrator", "HearingOfficer"]
READ_ROLES = ["ProgramAdministrator", "HearingOfficer",
              "FalseAlarmReviewOfficer", "PermitClerk", "BillingClerk",
              "AlarmUser"]

GROUNDS = ("WRONG_CAUSE_CODE", "EXEMPT_CAUSE", "NOT_MY_SYSTEM",
           "VERIFIED_RESPONSE_DEFECT", "COUNTING_ERROR",
           "FEE_CALCULATION_ERROR")
DECISIONS = ("GRANTED", "DENIED", "REMANDED")
MAX_REHEARING_DEPTH = 2

FILE_FIELDS = [
    F("false_alarm_incident_id", "uuid"),
    F("grounds", "enum", values=GROUNDS),
    F("narrative", "string"),
    F("expected_false_alarm_incident_version", "int"),
    F("prior_appeal_id", "uuid", required=False),
]

SCHEDULE_FIELDS = [
    F("hearing_docket_id", "uuid"),
    F("expected_hearing_docket_version", "int"),
]

DECIDE_FIELDS = [
    F("decision", "enum", values=DECISIONS),
    F("findings", "string"),
    F("exempt_cause_code", "string", required=False),
]

WITHDRAW_FIELDS = [F("withdrawal_reason", "string", required=False)]


def _resume_dunning(incident):
    """Nothing to unfreeze explicitly: the freeze is derived from the status."""
    invoice = engine.invoice_for_incident(incident["id"])
    if invoice is not None:
        engine.refresh_days_delinquent(invoice)


@bp.post("/appeals")
def file_appeal():
    ctx = authenticate(FILE_ROLES)
    data = validate(ctx.body, FILE_FIELDS)
    incident = rt.resolve("FalseAlarmIncident", data["false_alarm_incident_id"])
    prior = None
    if "prior_appeal_id" in data:
        prior = rt.resolve("Appeal", data["prior_appeal_id"])
    check_owner(ctx, site_id=incident.get("alarm_site_id"))
    if data["expected_false_alarm_incident_version"] != incident.get("version"):
        raise ApiError("ERR_STALE_FALSE_ALARM_INCIDENT_VERSION",
                       "The incident has been modified since it was read.")
    # Position 17.  `APPEALED` is a declared source for a further filing: the
    # window (position 30) and the pending-appeal check (position 36) are what
    # decide it, so it must not be short-circuited here (PRD 2.10 Collision C).
    if incident.get("status") not in ("COUNTED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a COUNTED incident may be appealed.")
    site = store.alarm_sites.get(incident.get("alarm_site_id"))
    sched = engine.governing_schedule(site) if site else None
    filing_days = int((sched or {}).get("appeal_filing_days") or 20)
    determined_at = incident.get("determined_at")
    if determined_at is not None \
            and now() > add_days(determined_at, filing_days):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED",
                       "The %d-day filing window has closed." % filing_days)
    if engine.live_appeal_for_incident(incident["id"]) is not None:
        raise ApiError("ERR_APPEAL_ALREADY_PENDING",
                       "A live appeal already contests this incident.")
    depth = 0
    if prior is not None:
        if prior.get("decision") != "DENIED" or prior.get("status") != "DENIED":
            raise ApiError("ERR_REHEARING_NOT_ELIGIBLE",
                           "Only a DENIED appeal may be reheard.")
        for other in rt.all_rows("Appeal"):
            if other.get("prior_appeal_id") == prior["id"]:
                raise ApiError("ERR_REHEARING_NOT_ELIGIBLE",
                               "A rehearing has already been filed against "
                               "that appeal.")
        depth = (prior.get("rehearing_depth") or 0) + 1
        if depth > MAX_REHEARING_DEPTH:
            raise ApiError("ERR_REHEARING_NOT_ELIGIBLE",
                           "The rehearing chain is exhausted.")

    row = base_row()
    row["false_alarm_incident_id"] = incident["id"]
    row["alarm_site_id"] = incident.get("alarm_site_id")
    row["hearing_docket_id"] = None
    row["prior_appeal_id"] = prior["id"] if prior is not None else None
    row["filed_by_user_id"] = ctx.user_id
    row["grounds"] = data["grounds"]
    row["narrative"] = data["narrative"]
    row["filed_at"] = now()
    row["status"] = "FILED"
    row["decision"] = None
    row["decided_at"] = None
    row["decided_by_user_id"] = None
    row["findings"] = None
    row["rehearing_depth"] = depth
    store.appeals[row["id"]] = row

    incident["status"] = "APPEALED"
    incident["appeal_count"] = (incident.get("appeal_count") or 0) + 1
    touch(incident)
    return created(row)


@bp.post("/appeals/<appeal_id>/schedule")
def schedule_appeal(appeal_id):
    ctx = authenticate(SCHEDULE_ROLES)
    data = validate(ctx.body, SCHEDULE_FIELDS)
    appeal = rt.resolve("Appeal", appeal_id)
    docket = rt.resolve("HearingDocket", data["hearing_docket_id"])
    if data["expected_hearing_docket_version"] != docket.get("version"):
        raise ApiError("ERR_STALE_HEARING_DOCKET_VERSION",
                       "The docket has been modified since it was read.")
    if appeal.get("status") != "FILED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a FILED appeal may be scheduled.")
    if docket.get("status") != "OPEN":
        raise ApiError("ERR_DOCKET_NOT_OPEN",
                       "The docket is not open for scheduling.")
    capacity = int(docket.get("capacity") or 0)
    if (docket.get("scheduled_appeal_count") or 0) + 1 > capacity:
        raise ApiError("ERR_DOCKET_CAPACITY_EXCEEDED",
                       "The session has no free seat.")
    session_start = docket.get("session_start")
    if session_start is not None and now() >= session_start:
        raise ApiError("ERR_HEARING_SESSION_IN_PAST",
                       "The session has already begun.")
    appeal["status"] = "SCHEDULED"
    appeal["hearing_docket_id"] = docket["id"]
    touch(appeal)
    docket["scheduled_appeal_count"] = (docket.get("scheduled_appeal_count")
                                       or 0) + 1
    if docket["scheduled_appeal_count"] >= capacity:
        docket["status"] = "CLOSED_FOR_SCHEDULING"
    touch(docket)
    return ok(appeal)


@bp.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    ctx = authenticate(["HearingOfficer"])
    data = validate(ctx.body, DECIDE_FIELDS)
    appeal = rt.resolve("Appeal", appeal_id)
    incident = store.false_alarm_incidents.get(
        appeal.get("false_alarm_incident_id")) or {}
    if ctx.user_id == incident.get("determined_by_user_id") \
            or ctx.user_id == appeal.get("filed_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Nobody may review their own work.")
    docket = store.hearing_dockets.get(appeal.get("hearing_docket_id"))
    if docket is None or docket.get("hearing_officer_user_id") != ctx.user_id:
        raise ApiError("ERR_NOT_DOCKET_OFFICER",
                       "Only the officer who heard the appeal may decide it.")
    if appeal.get("status") != "HEARD":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a HEARD appeal may be decided.")
    site = store.alarm_sites.get(appeal.get("alarm_site_id"))
    sched = engine.governing_schedule(site) if site else None
    decision = data["decision"]
    supplied = data.get("exempt_cause_code")
    if decision == "GRANTED":
        exempt_codes = list((sched or engine.active_status_schedule() or {}).get(
            "exempt_cause_codes") or [])
        if supplied is None or supplied not in exempt_codes:
            raise ApiError("ERR_EXEMPT_CAUSE_NOT_RECOGNIZED",
                           "A grant must name a recognized exempt cause.")

    appeal["status"] = decision
    appeal["decision"] = decision
    appeal["decided_at"] = now()
    appeal["decided_by_user_id"] = ctx.user_id
    appeal["findings"] = data["findings"]
    touch(appeal)

    if decision == "DENIED":
        if incident:
            incident["status"] = "COUNTED"
            touch(incident)
            _resume_dunning(incident)
        return ok(appeal)

    if decision == "REMANDED":
        if incident:
            incident["status"] = "UNDER_REVIEW"
            incident["determination"] = None
            incident["determined_at"] = None
            incident["determined_by_user_id"] = None
            incident["occurrence_index"] = None
            # PRD 3.6: a remand *clears* `assessed_fee_cents`.
            incident["assessed_fee_cents"] = None
            incident["fee_basis"] = None
            incident["counted_window_mode"] = None
            touch(incident)
            if site is not None:
                invoice = engine.invoice_for_incident(incident["id"])
                if invoice is not None:
                    engine.void_invoice_cascade(invoice, site)
                engine.renumber_and_reprice(site)
                engine.rollup_site(site)
        return ok(appeal)

    # GRANTED — the four ordered hops of PRD 3.6.
    incident["status"] = "EXEMPT_BY_APPEAL"
    incident["determination"] = "EXEMPT"
    incident["exempt_cause_code"] = supplied
    incident["occurrence_index"] = None
    incident["assessed_fee_cents"] = 0
    incident["fee_basis"] = None
    touch(incident)
    if site is not None:
        invoice = engine.invoice_for_incident(incident["id"])
        if invoice is not None:
            engine.void_invoice_cascade(invoice, site)
        engine.renumber_and_reprice(site)
        engine.rollup_site(site, bump=False)
        threshold = int((sched or {}).get("suspension_threshold_count") or 0)
        if site.get("chargeable_count_window", 0) < threshold:
            for order in engine.site_orders(site["id"]):
                if order.get("status") in ("PROPOSED", "EFFECTIVE",
                                           "REINSTATEMENT_PENDING"):
                    was_billed = order.get("status") in ("EFFECTIVE",
                                                         "REINSTATEMENT_PENDING")
                    order["status"] = "VACATED"
                    order["vacated_reason"] = "APPEAL_GRANTED"
                    touch(order)
                    if was_billed:
                        engine.void_invoice_cascade(
                            engine.invoice_for_order(order["id"]), site)
        engine.rollup_site(site)
    return ok(appeal)


@bp.post("/appeals/<appeal_id>/withdraw")
def withdraw_appeal(appeal_id):
    ctx = authenticate(FILE_ROLES)
    validate(ctx.body, WITHDRAW_FIELDS)
    appeal = rt.resolve("Appeal", appeal_id)
    if ctx.user_id != appeal.get("alarm_site_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appellant premises may withdraw the appeal.")
    if appeal.get("status") not in ("FILED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a FILED or SCHEDULED appeal may be withdrawn.")
    was_scheduled = appeal.get("status") == "SCHEDULED"
    docket = store.hearing_dockets.get(appeal.get("hearing_docket_id"))
    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    if was_scheduled and docket is not None:
        docket["scheduled_appeal_count"] = max(
            0, (docket.get("scheduled_appeal_count") or 0) - 1)
        if docket.get("status") == "CLOSED_FOR_SCHEDULING":
            docket["status"] = "OPEN"
        touch(docket)
    incident = store.false_alarm_incidents.get(
        appeal.get("false_alarm_incident_id"))
    if incident is not None and incident.get("status") == "APPEALED":
        incident["status"] = "COUNTED"
        touch(incident)
        _resume_dunning(incident)
    return ok(appeal)


@bp.get("/appeals/<appeal_id>")
def get_appeal(appeal_id):
    ctx = authenticate(READ_ROLES)
    appeal = rt.resolve("Appeal", appeal_id)
    check_owner(ctx, site_id=appeal.get("alarm_site_id"))
    return ok(appeal)


@bp.get("/appeals")
def list_appeals():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("Appeal"), company_field=None)
    for field in ("false_alarm_incident_id", "alarm_site_id",
                  "hearing_docket_id", "prior_appeal_id", "status", "decision"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, rt.fields("Appeal"))
