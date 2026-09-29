"""Suspension orders: proposal, service, reinstatement, lift and vacatur."""

from flask import Blueprint

import calc
import engine
import rt
from core import (F, authenticate, check_owner, created, listing, ok, q,
                  validate)
from errors import ApiError
from store import add_days, base_row, now, signed_whole_days, store, touch

bp = Blueprint("suspensions", __name__)

ADMIN = ["ProgramAdministrator"]
SERVE_ROLES = ["ProgramAdministrator", "PermitClerk"]
APPLY_ROLES = ["AlarmUser", "ProgramAdministrator"]
READ_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
              "FalseAlarmReviewOfficer", "HearingOfficer",
              "PoliceDispatchSupervisor", "AlarmUser"]

BASES = ("EXCESSIVE_FALSE_ALARMS", "UNPERMITTED_OPERATION", "NONPAYMENT")
PROPOSABLE = ("PROPOSED", "EFFECTIVE", "REINSTATEMENT_PENDING")
INSPECTION_VALID_DAYS = 30
PROBATION_DAYS_PER_STEP = 90

CREATE_FIELDS = [
    F("alarm_site_id", "uuid"),
    F("triggering_incident_id", "uuid"),
    F("basis", "enum", values=BASES),
    F("effective_from", "ts"),
    F("effective_through", "ts"),
    F("expected_alarm_site_version", "int"),
]

APPLY_FIELDS = [
    F("technician_inspection_date", "ts"),
    F("ecv_attestation", "bool"),
    F("corrective_action_summary", "string"),
]

VACATE_FIELDS = [F("vacated_reason", "string")]


def _basis_holds(site, sched):
    if sched is None:
        return False
    engine.rollup_site(site, bump=False)
    threshold = int(sched.get("suspension_threshold_count") or 0)
    return site.get("chargeable_count_window", 0) >= threshold


@bp.post("/suspension-orders")
def propose_order():
    ctx = authenticate(ADMIN)
    data = validate(ctx.body, CREATE_FIELDS)
    site = rt.resolve("AlarmSite", data["alarm_site_id"])
    incident = rt.resolve("FalseAlarmIncident", data["triggering_incident_id"])
    if data["expected_alarm_site_version"] != site.get("version"):
        raise ApiError("ERR_STALE_ALARM_SITE_VERSION",
                       "The premises has been modified since it was read.")
    effective_from = data["effective_from"]
    effective_through = data["effective_through"]
    occurred_at = incident.get("occurred_at")
    if effective_from < now() or effective_through <= effective_from \
            or (occurred_at is not None and effective_from < occurred_at):
        raise ApiError("ERR_SUSPENSION_EFFECTIVE_DATE_INVALID",
                       "The suspension interval is not coherent.")
    for order in engine.site_orders(site["id"]):
        if order.get("status") not in PROPOSABLE:
            continue
        if calc.suspension_periods_conflict(effective_from, effective_through,
                                            order.get("effective_from"),
                                            order.get("effective_through")):
            raise ApiError("ERR_SUSPENSION_PERIOD_OVERLAP",
                           "The premises is already under a live order across "
                           "those days.")
    sched = engine.governing_schedule(site)
    if not _basis_holds(site, sched):
        raise ApiError("ERR_SUSPENSION_BASIS_NO_LONGER_MET",
                       "The chargeable count no longer supports a suspension.")

    row = base_row()
    row["alarm_site_id"] = site["id"]
    row["triggering_incident_id"] = incident["id"]
    row["basis"] = data["basis"]
    row["status"] = "PROPOSED"
    row["effective_from"] = effective_from
    row["effective_through"] = effective_through
    row["suspension_sequence"] = (site.get("lifted_suspension_count") or 0) + 1
    row["reinstatement_fee_cents"] = None
    row["probation_days"] = None
    row["required_conditions"] = None
    row["served_at"] = None
    row["reinstatement_requested_at"] = None
    row["technician_inspection_date"] = None
    row["ecv_attestation"] = None
    row["lifted_at"] = None
    row["vacated_reason"] = None
    store.suspension_orders[row["id"]] = row
    engine.rollup_site(site)
    return created(row)


@bp.post("/suspension-orders/<order_id>/serve")
def serve_order(order_id):
    authenticate(SERVE_ROLES)
    order = rt.resolve("SuspensionOrder", order_id)
    if order.get("status") != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PROPOSED order may be served.")
    effective_from = order.get("effective_from")
    if effective_from is not None and now() > effective_from:
        raise ApiError("ERR_SUSPENSION_EFFECTIVE_DATE_INVALID",
                       "The order's effective date has already passed.")
    site = store.alarm_sites.get(order.get("alarm_site_id"))
    if site is None:
        raise ApiError("ERR_ALARM_SITE_NOT_FOUND", "The premises is missing.")
    sched = engine.governing_schedule(site)
    if not _basis_holds(site, sched):
        raise ApiError("ERR_SUSPENSION_BASIS_NO_LONGER_MET",
                       "The chargeable count no longer supports a suspension.")

    prior = len([o for o in engine.site_orders(site["id"])
                 if o.get("status") == "LIFTED"])
    order["status"] = "EFFECTIVE"
    order["served_at"] = now()
    order["reinstatement_fee_cents"] = calc.reinstatement_fee_cents(sched, prior)
    order["probation_days"] = PROBATION_DAYS_PER_STEP * (prior + 1)
    order["suspension_sequence"] = prior + 1
    order["required_conditions"] = {
        "inspection_required": True,
        "ecv_attestation_required": True,
        "min_ecv_contacts": 2 + prior,
        "invoices_paid_required": True,
    }
    touch(order)
    engine.new_invoice(site, sched, "REINSTATEMENT_FEE",
                       calc.reinstatement_lines(sched, prior),
                       "suspension_order_id", order["id"])
    engine.rollup_site(site)
    return ok(order)


@bp.post("/suspension-orders/<order_id>/reinstatement-requests")
def request_reinstatement(order_id):
    ctx = authenticate(APPLY_ROLES)
    data = validate(ctx.body, APPLY_FIELDS)
    order = rt.resolve("SuspensionOrder", order_id)
    check_owner(ctx, site_id=order.get("alarm_site_id"))
    if order.get("status") != "EFFECTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an EFFECTIVE order may receive a reinstatement "
                       "request.")
    inspected = data["technician_inspection_date"]
    age = signed_whole_days(now(), inspected)
    if age > INSPECTION_VALID_DAYS or age < 0:
        raise ApiError("ERR_INSPECTION_EVIDENCE_STALE",
                       "The technician inspection is stale or in the future.")
    summary = data["corrective_action_summary"]
    if not data["ecv_attestation"] or not str(summary).strip():
        raise ApiError("ERR_ECV_ATTESTATION_REQUIRED",
                       "An affirmative attestation with a corrective action "
                       "summary is required.")
    site = store.alarm_sites.get(order.get("alarm_site_id"))
    conditions = order.get("required_conditions") or {}
    minimum = int(conditions.get("min_ecv_contacts") or 2)
    if site is not None:
        engine.rollup_site(site, bump=False)
        if (site.get("ecv_callable_contact_count") or 0) < minimum:
            raise ApiError("ERR_INSUFFICIENT_ECV_CONTACTS",
                           "The premises needs at least %d live callable "
                           "contacts." % minimum)
    order["status"] = "REINSTATEMENT_PENDING"
    order["reinstatement_requested_at"] = now()
    order["technician_inspection_date"] = inspected
    order["ecv_attestation"] = data["ecv_attestation"]
    touch(order)
    return ok(order)


@bp.post("/suspension-orders/<order_id>/lift")
def lift_order(order_id):
    authenticate(ADMIN)
    order = rt.resolve("SuspensionOrder", order_id)
    if order.get("status") != "REINSTATEMENT_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an order awaiting reinstatement may be lifted.")
    site = store.alarm_sites.get(order.get("alarm_site_id"))
    if site is None:
        raise ApiError("ERR_ALARM_SITE_NOT_FOUND", "The premises is missing.")
    engine.rollup_site(site, bump=False)
    blocked = False
    for inv in engine.site_invoices(site["id"]):
        if inv.get("collections_stage") == "WRITTEN_OFF":
            continue
        if inv.get("payment_status") in ("PAID", "VOIDED"):
            continue
        blocked = True
        break
    net = (site.get("outstanding_balance_cents") or 0) \
        - (site.get("credit_balance_cents") or 0)
    if blocked or net > 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT",
                       "The premises still owes penalty money.")
    order["status"] = "LIFTED"
    order["lifted_at"] = now()
    touch(order)
    engine.rollup_site(site)
    return ok(order)


@bp.post("/suspension-orders/<order_id>/vacate")
def vacate_order(order_id):
    ctx = authenticate(ADMIN)
    data = validate(ctx.body, VACATE_FIELDS)
    order = rt.resolve("SuspensionOrder", order_id)
    if order.get("status") not in PROPOSABLE:
        raise ApiError("ERR_INVALID_STATE",
                       "A %s order may not be vacated." % order.get("status"))
    was_billed = order.get("status") in engine.LIVE_ORDER_STATUSES
    order["status"] = "VACATED"
    order["vacated_reason"] = data["vacated_reason"]
    touch(order)
    site = store.alarm_sites.get(order.get("alarm_site_id"))
    if site is not None:
        if was_billed:
            engine.void_invoice_cascade(engine.invoice_for_order(order["id"]),
                                        site)
        engine.rollup_site(site)
    return ok(order)


@bp.get("/suspension-orders/<order_id>")
def get_order(order_id):
    ctx = authenticate(READ_ROLES)
    order = rt.resolve("SuspensionOrder", order_id)
    check_owner(ctx, site_id=order.get("alarm_site_id"))
    return ok(order)


@bp.get("/suspension-orders")
def list_orders():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("SuspensionOrder"),
                          company_field=None)
    for field in ("alarm_site_id", "triggering_incident_id", "status", "basis"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, rt.fields("SuspensionOrder"))
