"""Fee schedules — the ordinance rows every price and deadline is read from."""

from flask import Blueprint

import engine
import rt
from core import F, authenticate, created, listing, ok, q, validate
from errors import ApiError
from store import base_row, now, store, touch

bp = Blueprint("fee_schedules", __name__)

READ_ONE_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
                  "FalseAlarmReviewOfficer", "HearingOfficer",
                  "PoliceDispatchSupervisor", "AlarmCompanyOperator", "AlarmUser"]
READ_MANY_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
                   "FalseAlarmReviewOfficer", "HearingOfficer"]

CREATE_FIELDS = [
    F("schedule_code", "string"),
    F("effective_from", "ts"),
    F("counting_window_mode", "enum", values=("ROLLING_365", "PERMIT_YEAR")),
    F("free_alarm_allowance", "int"),
    F("fee_tiers", "array", nonempty=True),
    F("occupancy_multipliers", "object"),
    F("non_ecv_surcharge_pct", "pct"),
    F("unpermitted_multiplier", "number"),
    F("suspension_period_aggravation_cents", "int"),
    F("per_incident_fee_cap_cents", "int"),
    F("probation_threshold_count", "int"),
    F("suspension_threshold_count", "int"),
    F("appeal_filing_days", "int"),
    F("permit_term_days", "int"),
    F("renewal_grace_days", "int"),
    F("new_installation_grace_days", "int"),
    F("permit_issue_fee_cents", "int"),
    F("permit_renewal_fee_cents", "int"),
    F("late_renewal_tiers", "array", nonempty=True),
    F("unpermitted_operation_penalty_cents", "int"),
    F("reinstatement_base_fee_cents", "int"),
    F("reinstatement_escalation_pct", "pct"),
    F("admin_fee_pct", "pct"),
    F("admin_fee_min_cents", "int"),
    F("admin_fee_max_cents", "int"),
    F("invoice_due_days", "int"),
    F("late_penalty_pct", "pct"),
    F("delinquency_days", "int"),
    F("collections_referral_threshold_cents", "int"),
    F("delinquent_balance_block_cents", "int"),
    F("exempt_cause_codes", "array"),
    F("company_probation_score_threshold", "pct"),
    F("company_suspension_score_threshold", "pct"),
]


@bp.post("/fee-schedules")
def create_fee_schedule():
    ctx = authenticate(["ProgramAdministrator"])
    data = validate(ctx.body, CREATE_FIELDS)
    for existing in store.fee_schedules.values():
        if existing.get("schedule_code") == data["schedule_code"]:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "schedule_code must be unique across all schedules.")
    row = base_row()
    row["schedule_code"] = data["schedule_code"]
    row["status"] = "DRAFT"
    for spec in CREATE_FIELDS[1:]:
        row[spec.name] = ctx.body.get(spec.name) if spec.kind != "ts" \
            else data[spec.name]
    row["effective_from"] = data["effective_from"]
    row["superseded_at"] = None
    store.fee_schedules[row["id"]] = row
    return created(row)


@bp.post("/fee-schedules/<schedule_id>/activate")
def activate_fee_schedule(schedule_id):
    ctx = authenticate(["ProgramAdministrator"])
    sched = rt.resolve("FeeSchedule", schedule_id)
    if sched.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT schedule may be activated.")
    # Supersession is status-based: any row already in `ACTIVE` is pushed out,
    # even one whose `effective_from` has not been reached yet (PRD 2.9 allows
    # at most one `ACTIVE` row program-wide).
    outgoing = engine.active_status_schedule()
    if outgoing is not None and outgoing["id"] != sched["id"]:
        outgoing["status"] = "SUPERSEDED"
        outgoing["superseded_at"] = now()
        touch(outgoing)
    sched["status"] = "ACTIVE"
    touch(sched)
    return ok(sched)


@bp.get("/fee-schedules/<schedule_id>")
def get_fee_schedule(schedule_id):
    authenticate(READ_ONE_ROLES)
    return ok(rt.resolve("FeeSchedule", schedule_id))


@bp.get("/fee-schedules")
def list_fee_schedules():
    authenticate(READ_MANY_ROLES)
    rows = rt.all_rows("FeeSchedule")
    status = q("status")
    code = q("schedule_code")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if code is not None:
        rows = [r for r in rows if r.get("schedule_code") == code]
    return listing(rows, rt.fields("FeeSchedule"))
