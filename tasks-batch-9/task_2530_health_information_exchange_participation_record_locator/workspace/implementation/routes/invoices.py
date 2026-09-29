"""Participation invoice endpoints (PRD 3.10)."""
from flask import Blueprint, request

from db import clock, create, db, parse_iso, touch
from errors import ApiError
from middleware import (
    HIE_ADMIN,
    PARTICIPANT_ADMIN,
    authenticate,
    require_action_role,
    require_scope,
)
from response import entity, entity_created, paginate, pagination
from services import fees, repo
from services.counters import recompute_outstanding_balance
from validate import body, before, req_dt, req_enum, req_int, req_str
from routes.participants import DATA_CARRYING_STATUSES

bp = Blueprint("invoices", __name__)

BASIS_VARIANTS = ("PROVISIONAL", "RECONCILED")
INVOICE_STATUSES = ("ISSUED", "PAID", "DELINQUENT", "WRITTEN_OFF", "VOID")
TERMINAL_INVOICE_STATES = ("PAID", "WRITTEN_OFF", "VOID")
PERIOD_BLOCKING_STATUSES = ("ISSUED", "PAID", "DELINQUENT", "WRITTEN_OFF")
ADMIN_ACTIONS = ("DECLARE_DELINQUENT", "WRITE_OFF", "VOID")
ADMIN_ACTION_ROLES = {
    "DECLARE_DELINQUENT": (HIE_ADMIN,),
    "WRITE_OFF": (HIE_ADMIN,),
    "VOID": (HIE_ADMIN,),
}


@bp.route("/hie/participants/<pid>/participation-invoices", methods=["POST"])
def issue_invoice(pid):
    authenticate((HIE_ADMIN,))
    payload = body()
    start_raw, start_dt = req_dt(payload, "billing_period_start")
    end_raw, end_dt = req_dt(payload, "billing_period_end")
    before(
        start_dt,
        end_dt,
        "billing_period_end must be strictly after billing_period_start.",
    )
    basis_variant = req_enum(payload, "basis_variant", BASIS_VARIANTS)
    due_raw, due_dt = req_dt(payload, "due_date")

    participant = repo.must("participants", pid)

    if participant["onboarding_status"] not in DATA_CARRYING_STATUSES:
        raise ApiError("ERR_PARTICIPANT_NOT_ONBOARDED_FOR_DATA")

    for existing in repo.participant_invoices(pid):
        if existing["status"] not in PERIOD_BLOCKING_STATUSES:
            continue
        other_start = parse_iso(existing["billing_period_start"])
        other_end = parse_iso(existing["billing_period_end"])
        if other_start is None or other_end is None:
            continue
        if start_dt < other_end and other_start < end_dt:
            raise ApiError("ERR_INVOICE_PERIOD_OVERLAP")

    if end_dt > clock():
        raise ApiError("ERR_INVOICE_PERIOD_NOT_ELAPSED")

    if basis_variant == "PROVISIONAL":
        assessment = fees.provisional(participant)
    else:
        assessment = fees.reconciled(participant, start_dt, end_dt)

    row = create(
        db.invoices,
        "ParticipationInvoice",
        {
            "participant_id": pid,
            "billing_period_start": start_raw,
            "billing_period_end": end_raw,
            "basis_variant": basis_variant,
            "due_date": due_raw,
            "billable_volume_units": assessment["billable_volume_units"],
            "tier_charge_breakdown": assessment["tier_charge_breakdown"],
            "volume_fee_cents": assessment["volume_fee_cents"],
            "base_platform_fee_cents": assessment["base_platform_fee_cents"],
            "quality_grade_snapshot": assessment["quality_grade_snapshot"],
            "quality_multiplier": assessment["quality_multiplier"],
            "total_cents": assessment["total_cents"],
            "amount_paid_cents": 0,
            "status": "ISSUED",
            "status_reason": None,
        },
    )
    recompute_outstanding_balance(participant)
    touch(participant)
    return entity_created(row)


@bp.route("/hie/participation-invoices/<invoice_id>/payment", methods=["POST"])
def pay_invoice(invoice_id):
    actor = authenticate((PARTICIPANT_ADMIN, HIE_ADMIN))
    invoice = repo.get("invoices", invoice_id)
    if invoice is not None:
        require_scope(actor, invoice["participant_id"])
    payload = body()
    tendered = req_int(payload, "amount_paid_cents", minimum=0)

    invoice = repo.must("invoices", invoice_id)
    if invoice["status"] in TERMINAL_INVOICE_STATES:
        raise ApiError("ERR_TERMINAL_STATE")
    if invoice["status"] not in ("ISSUED", "DELINQUENT"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    outstanding = int(invoice["total_cents"]) - int(invoice["amount_paid_cents"] or 0)
    if tendered != outstanding:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    invoice["amount_paid_cents"] = int(invoice["amount_paid_cents"] or 0) + tendered
    invoice["status"] = "PAID"
    touch(invoice)

    participant = repo.must("participants", invoice["participant_id"])
    recompute_outstanding_balance(participant)
    touch(participant)
    return entity(invoice)


@bp.route(
    "/hie/participation-invoices/<invoice_id>/administrative-transitions",
    methods=["POST"],
)
def administrative_transition(invoice_id):
    actor = authenticate((HIE_ADMIN,))
    payload = body()
    require_action_role(actor, payload.get("action"), ADMIN_ACTION_ROLES)
    action = req_enum(payload, "action", ADMIN_ACTIONS)
    reason = req_str(payload, "reason")

    invoice = repo.must("invoices", invoice_id)
    if invoice["status"] in TERMINAL_INVOICE_STATES:
        raise ApiError("ERR_TERMINAL_STATE")

    if action == "DECLARE_DELINQUENT":
        if invoice["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        due = parse_iso(invoice["due_date"])
        if due is None or clock() <= due:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        invoice["status"] = "DELINQUENT"
    elif action == "WRITE_OFF":
        if invoice["status"] != "DELINQUENT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        invoice["status"] = "WRITTEN_OFF"
    else:
        if invoice["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        invoice["status"] = "VOID"
    invoice["status_reason"] = reason
    touch(invoice)

    if action in ("WRITE_OFF", "VOID"):
        participant = repo.must("participants", invoice["participant_id"])
        recompute_outstanding_balance(participant)
        touch(participant)
    return entity(invoice)


@bp.route("/hie/participation-invoices/<invoice_id>", methods=["GET"])
def read_invoice(invoice_id):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    return entity(repo.must("invoices", invoice_id))


@bp.route("/hie/participants/<pid>/participation-invoices", methods=["GET"])
def list_invoices(pid):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    limit, offset = pagination()
    repo.must("participants", pid)
    rows = repo.participant_invoices(pid)
    status = request.args.get("status")
    basis_variant = request.args.get("basis_variant")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if basis_variant:
        rows = [r for r in rows if r["basis_variant"] == basis_variant]
    return paginate(rows, limit, offset)
