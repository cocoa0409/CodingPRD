"""Escalations, lazy sweeps and the derived program report (PRD §3.10)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock, elapsed_days, is_strictly_after
from envelope import created, listing, ok
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_PATIENT_NOT_FOUND, ERR_SEGREGATION_OF_DUTIES,
)
from ladder import (
    ALL_ROLES, BILLING, CHW, Endpoint, PROGRAM_ADMIN, SUPERVISOR, run,
)
from serial import dump, dump_all

bp = Blueprint("ops", __name__)

EP_ESCALATION_CREATE = Endpoint("escalation.create", [CHW, SUPERVISOR], gated=True)
EP_ESCALATION_READ = Endpoint("escalation.read", ALL_ROLES,
                              path=[("escalation_id", "escalation")])
EP_ESCALATION_LIST = Endpoint("escalation.list", ALL_ROLES)
EP_ESCALATION_ACK = Endpoint("escalation.acknowledge", [SUPERVISOR, PROGRAM_ADMIN],
                             path=[("escalation_id", "escalation")])
EP_ESCALATION_RESOLVE = Endpoint("escalation.resolve", [SUPERVISOR, PROGRAM_ADMIN],
                                 path=[("escalation_id", "escalation")])
EP_SWEEP = Endpoint("ops.run_sweep", [PROGRAM_ADMIN])
EP_REPORT = Endpoint("reports.program_summary", [SUPERVISOR, PROGRAM_ADMIN, BILLING])

SWEEP_TYPES = ("REFERRAL_LAPSE", "OFFERING_HOLD_EXPIRY", "ESCALATION_PROMOTION")
DENOMINATOR_BASES = ("ENROLLED_ONLY", "EVER_ENROLLED")
SOURCE_FLAGS = ("CRITICAL_SDOH_FINDING", "RESOURCE_EXHAUSTED", "REFERRAL_UNFULFILLED",
                "GOAL_NOT_MET", "MANUAL")


# ------------------------------------------------------------- escalations
@bp.post("/chw/escalations")
def create_escalation():
    def payload(ctx):
        ctx.state["patient_id"] = v.req_str(ctx.body, "patient_id")
        ctx.state["note"] = v.opt_str(ctx.body, "note")

    def body_refs(ctx):
        patient = store.get("patient", ctx.state["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        ctx.state["patient"] = patient

    ctx = run(EP_ESCALATION_CREATE, steps={5: [payload], 6: [body_refs]})
    row = cascades.open_escalation(ctx.state["patient"]["id"], "MANUAL", ctx.user_id,
                                   note=ctx.state["note"])
    return created(dump(row))


@bp.get("/chw/escalations/<escalation_id>")
def read_escalation(escalation_id):
    ctx = run(EP_ESCALATION_READ, {"escalation_id": escalation_id})
    return ok(dump(ctx.row("escalation_id")))


@bp.get("/chw/escalations")
def list_escalations():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_ESCALATION_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("escalation")
    for key in ("patient_id", "source_flag", "status", "source_referral_id",
                "source_screening_id", "blocking_offering_id"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


@bp.post("/chw/escalations/<escalation_id>/acknowledge")
def acknowledge_escalation(escalation_id):
    def target_state(ctx):
        if ctx.row("escalation_id")["status"] not in cascades.OPEN_TIERS:
            raise ApiError(ERR_INVALID_STATE, "Only an open escalation may be acknowledged")

    def segregation(ctx):
        if ctx.user_id == ctx.row("escalation_id").get("opened_by_user_id"):
            raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                           "An operator may not acknowledge their own escalation")

    ctx = run(EP_ESCALATION_ACK, {"escalation_id": escalation_id},
              steps={8: [target_state], 10: [segregation]})
    escalation = ctx.row("escalation_id")
    escalation["status"] = "ACKNOWLEDGED"
    escalation["acknowledged_by_user_id"] = ctx.user_id
    store.touch(escalation)
    return ok(dump(escalation))


@bp.post("/chw/escalations/<escalation_id>/resolve")
def resolve_escalation(escalation_id):
    def target_state(ctx):
        if ctx.row("escalation_id")["status"] != "ACKNOWLEDGED":
            raise ApiError(ERR_INVALID_STATE,
                           "Only an ACKNOWLEDGED escalation may be resolved")

    ctx = run(EP_ESCALATION_RESOLVE, {"escalation_id": escalation_id},
              steps={8: [target_state]})
    escalation = ctx.row("escalation_id")
    escalation["status"] = "RESOLVED"
    escalation["resolution_reason"] = "MANUAL_RESOLUTION"
    store.touch(escalation)
    return ok(dump(escalation))


# ------------------------------------------------------------------ sweeps
@bp.post("/chw/ops/run-sweep")
def run_sweep():
    def payload(ctx):
        ctx.state["sweep_type"] = v.req_enum(ctx.body, "sweep_type", SWEEP_TYPES)

    ctx = run(EP_SWEEP, steps={5: [payload]})
    sweep_type = ctx.state["sweep_type"]
    now = clock.now_raw()
    referrals_lapsed = 0
    holds_expired = 0
    escalations_promoted = 0
    units_returned = 0

    if sweep_type == "REFERRAL_LAPSE":
        for referral in store.all_rows("referral"):
            if referral.get("status") != "SENT":
                continue
            if not is_strictly_after(now, referral.get("ack_deadline_at")):
                continue
            units_returned += cascades.lapse_referral(referral, "ACK_SLA_EXPIRED",
                                                      "released_units")
            referrals_lapsed += 1
    elif sweep_type == "OFFERING_HOLD_EXPIRY":
        for referral in store.all_rows("referral"):
            if referral.get("status") != "ACCEPTED":
                continue
            if not is_strictly_after(now, referral.get("hold_expires_at")):
                continue
            units_returned += cascades.lapse_referral(referral, "HOLD_EXPIRED",
                                                      "expired_units")
            holds_expired += 1
    else:
        for escalation in store.all_rows("escalation"):
            status = escalation.get("status")
            if status not in ("OPEN_TIER_1", "OPEN_TIER_2"):
                continue
            if not is_strictly_after(now, escalation.get("ack_deadline_at")):
                continue
            tier = 2 if status == "OPEN_TIER_1" else 3
            escalation["status"] = "OPEN_TIER_%d" % tier
            escalation["current_tier"] = tier
            escalation["tier_entered_at"] = now
            escalation["ack_deadline_at"] = cascades.tier_deadline(now, tier)
            escalation["promotion_count"] = escalation.get("promotion_count", 0) + 1
            store.touch(escalation)
            escalations_promoted += 1

    return ok({
        "sweep_type": sweep_type,
        "referrals_lapsed": referrals_lapsed,
        "holds_expired": holds_expired,
        "escalations_promoted": escalations_promoted,
        "units_returned": units_returned,
    })


# ------------------------------------------------------------------ report
@bp.get("/chw/reports/program-summary")
def program_summary():
    def payload(ctx):
        args = ctx.args
        month = args.get("service_month")
        if month is None or not v.MONTH_RE.match(month or ""):
            v.bad("service_month must be a YYYY-MM month")
        basis = args.get("denominator_basis")
        if basis is None:
            v.bad("denominator_basis is required")
        v.enum_value("denominator_basis", basis, DENOMINATOR_BASES)
        ctx.state["service_month"] = month
        ctx.state["denominator_basis"] = basis

    ctx = run(EP_REPORT, steps={5: [payload]})
    month = ctx.state["service_month"]
    basis = ctx.state["denominator_basis"]
    now = clock.now_raw()

    if basis == "ENROLLED_ONLY":
        wanted = ("ENROLLED",)
    else:
        wanted = ("ENROLLED", "DISENROLLED")
    denominator = [p for p in store.all_rows("patient")
                   if p.get("enrollment_status") in wanted]
    denominator_ids = set(p["id"] for p in denominator)
    denominator_count = len(denominator)

    covered = 0
    for patient in denominator:
        for screening in store.all_rows("screening"):
            if screening.get("patient_id") != patient["id"]:
                continue
            if screening.get("status") not in ("SUBMITTED", "AMENDED"):
                continue
            elapsed = elapsed_days(screening.get("anchor_screened_at"), now)
            if elapsed is not None and elapsed <= Decimal(calc.SCREENING_COVERAGE_WINDOW_DAYS):
                covered += 1
                break

    resolved = [r for r in store.all_rows("referral")
                if r.get("patient_id") in denominator_ids
                and r.get("status") in ("SERVICE_DELIVERED", "CLOSED", "DECLINED", "LAPSED")]
    closed_loops = [r for r in resolved
                    if r.get("status") == "CLOSED" and r.get("delivered_at") is not None]

    minutes = {"PAYER": 0, "GRANT": 0, "UNFUNDED": 0}
    total_miles = Decimal(0)
    for encounter in store.all_rows("encounter"):
        if encounter.get("patient_id") not in denominator_ids:
            continue
        if encounter.get("service_month") != month:
            continue
        if encounter.get("status") not in ("SUBMITTED", "LOCKED"):
            continue
        source = encounter.get("funding_source")
        if source in minutes:
            minutes[source] += encounter.get("billable_minutes", 0)
        total_miles += Decimal(str(encounter.get("travel_miles") or 0))

    open_escalations = 0
    for escalation in store.all_rows("escalation"):
        if escalation.get("patient_id") not in denominator_ids:
            continue
        if escalation.get("status") in cascades.OPEN_TIERS:
            open_escalations += 1

    return ok({
        "patient_denominator_count": denominator_count,
        "screening_coverage_pct": calc.pct(covered, denominator_count),
        "referral_loop_closure_pct": calc.pct(len(closed_loops), len(resolved)),
        "payer_minutes": minutes["PAYER"],
        "grant_minutes": minutes["GRANT"],
        "unfunded_minutes": minutes["UNFUNDED"],
        "travel_reimbursement_monthly_cents": calc.marginal_cents(total_miles),
        "open_escalation_count": open_escalations,
    })
