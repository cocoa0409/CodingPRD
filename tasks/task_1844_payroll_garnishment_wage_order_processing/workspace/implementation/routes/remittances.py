"""Remittance creation, confirmation, and cancellation (PRD §3.7)."""

from flask import Blueprint, g

from db import logical_now, next_seq, store
from errors import (
    ERR_DUPLICATE_REMITTANCE,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE,
    ERR_NO_REMITTABLE_EVENTS,
    ERR_NOT_FOUND,
    ERR_REMITTANCE_EMPTY,
    fail,
)
from middleware import (
    ALL_ROLES,
    ROLE_MANAGER,
    ROLE_SPECIALIST,
    authorize,
    get_body,
    public,
    req_str,
)
from response import object_response
from routes.authorities import get_authority_or_404
from services import audit
from util import add_business_days, new_uuid, parse_date, render_date, render_instant

bp = Blueprint("remittances", __name__)

TIMING_OFFSETS = {"SAME_DAY": 0, "NEXT_BUSINESS_DAY": 1, "THREE_BUSINESS_DAYS": 3}

# Only events of orders in these processing states are remittance-assignable.
REMITTABLE_STATES = ("ACTIVE", "ANSWER_FILED")


def get_remittance_or_404(remittance_id):
    remittance = store.remittances.get(remittance_id)
    if remittance is None:
        fail(ERR_NOT_FOUND, 404, "Remittance '%s' does not exist." % remittance_id)
    return remittance


@bp.post("/remittances")
def create_remittance():
    authorize(ROLE_SPECIALIST)
    body = get_body()
    employer_id = req_str(body, "employer_id")
    authority_id = req_str(body, "authority_id")
    payroll_run_id = req_str(body, "payroll_run_id")

    employer = store.employers.get(employer_id)
    if employer is None:
        fail(ERR_NOT_FOUND, 404, "Employer '%s' does not exist." % employer_id)
    get_authority_or_404(authority_id)
    run = store.runs.get(payroll_run_id)
    if run is None or run["employer_id"] != employer_id:
        fail(ERR_NOT_FOUND, 404,
             "PayrollRun '%s' does not exist within the employer scope."
             % payroll_run_id)

    # One remittance per authority per run.
    if any(r["authority_id"] == authority_id and r["payroll_run_id"] == payroll_run_id
           for r in store.remittances.values()):
        fail(ERR_DUPLICATE_REMITTANCE, 409,
             "A remittance already exists for (authority_id, payroll_run_id) = "
             "(%s, %s)." % (authority_id, payroll_run_id))

    # Sweep still-unassigned WITHHOLD events posted against this run for
    # orders of this authority currently ACTIVE or ANSWER_FILED.
    swept = []
    for event in store.events.values():
        if event["event_type"] != "WITHHOLD":
            continue
        if event["payroll_run_id"] != payroll_run_id:
            continue
        if event["_remittance_id"] is not None:
            continue
        order = store.orders.get(event["garnishment_order_id"])
        if order is None:
            continue
        if order["issuing_authority_id"] != authority_id:
            continue
        if order["processing_status"] not in REMITTABLE_STATES:
            continue
        swept.append(event)
    swept.sort(key=lambda e: (e["created_at"], e["_seq"]))

    if not swept:
        fail(ERR_NO_REMITTABLE_EVENTS, 409,
             "No unassigned WITHHOLD events from ACTIVE/ANSWER_FILED orders "
             "exist for (authority, run) = (%s, %s)." % (authority_id, payroll_run_id))

    amount_due = sum(e["amount_cents"] for e in swept)

    # Due date fixed at creation: run.pay_date advanced by the timing offset
    # in business days (SAME_DAY pins due_date to pay_date itself). A later
    # employer config change never moves an existing remittance's deadline.
    offset = TIMING_OFFSETS[employer["remittance_timing"]]
    due_date = render_date(add_business_days(parse_date(run["pay_date"]), offset))

    now = render_instant(logical_now())
    remittance = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "employer_id": employer_id,
        "authority_id": authority_id,
        "payroll_run_id": payroll_run_id,
        "amount_due_cents": amount_due,
        "status": "PENDING",
        "due_date": due_date,
        "confirmed_at": None,
        "member_event_ids": [e["id"] for e in swept],
        "_seq": next_seq(),
    }
    store.remittances[remittance["id"]] = remittance
    for event in swept:
        event["_remittance_id"] = remittance["id"]

    audit.append_audit(employer_id, "Remittance", remittance["id"],
                       "remittance.create",
                       details={"authority_id": authority_id,
                                "payroll_run_id": payroll_run_id,
                                "amount_due_cents": amount_due,
                                "due_date": due_date,
                                "member_event_ids": remittance["member_event_ids"]})
    return object_response(public(remittance), 201)


@bp.get("/remittances/<remittanceId>")
def get_remittance(remittanceId):
    authorize(*ALL_ROLES)
    return object_response(public(get_remittance_or_404(remittanceId)))


@bp.post("/remittances/<remittanceId>/confirm")
def confirm_remittance(remittanceId):
    authorize(ROLE_MANAGER)
    remittance = get_remittance_or_404(remittanceId)

    # Segregation of duties (§2.10): the confirmer's X-User-ID must differ
    # from the X-User-ID that paid the run.
    payer = store.run_payers.get(remittance["payroll_run_id"])
    if payer is not None and payer == g.user_id:
        fail(ERR_FORBIDDEN_ROLE, 403,
             "Segregation of duties: the operator who paid the run may not "
             "confirm its remittances.")

    if remittance["status"] != "PENDING":
        fail(ERR_INVALID_STATE, 409,
             "Only a PENDING remittance can be confirmed; current state is %s."
             % remittance["status"])
    if remittance["amount_due_cents"] <= 0:
        fail(ERR_REMITTANCE_EMPTY, 409,
             "Remittance '%s' has an effective amount of 0." % remittance["id"])

    # On or before due_date -> CONFIRMED; after -> LATE_CONFIRMED.
    current_date = logical_now().date()
    if current_date > parse_date(remittance["due_date"]):
        remittance["status"] = "LATE_CONFIRMED"
    else:
        remittance["status"] = "CONFIRMED"
    remittance["confirmed_at"] = render_instant(logical_now())
    remittance["version"] += 1
    remittance["updated_at"] = render_instant(logical_now())
    audit.append_audit(remittance["employer_id"], "Remittance", remittance["id"],
                       "remittance.confirm",
                       details={"status": remittance["status"],
                                "due_date": remittance["due_date"],
                                "confirmed_at": remittance["confirmed_at"]})
    return object_response(public(remittance))


@bp.post("/remittances/<remittanceId>/cancel")
def cancel_remittance(remittanceId):
    authorize(ROLE_MANAGER)
    remittance = get_remittance_or_404(remittanceId)
    if remittance["status"] != "PENDING":
        fail(ERR_INVALID_STATE, 409,
             "Only a PENDING remittance can be cancelled; current state is %s."
             % remittance["status"])

    # Cancellation applies when every member withholding event carries a
    # compensating refund, i.e. the effective total has reached zero.
    if remittance["amount_due_cents"] > 0:
        fail(ERR_INVALID_STATE, 409,
             "Remittance '%s' still has unrefunded member events."
             % remittance["id"])

    remittance["status"] = "CANCELLED"
    remittance["version"] += 1
    remittance["updated_at"] = render_instant(logical_now())
    audit.append_audit(remittance["employer_id"], "Remittance", remittance["id"],
                       "remittance.cancel")
    return object_response(public(remittance))
