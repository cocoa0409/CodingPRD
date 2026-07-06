"""Invoice endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import db
from middleware import authenticate
from clock import clock
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PROJECT_WRONG_STAGE, ERR_ZERO_AMOUNT_MILESTONE, ERR_NOT_YET_DUE,
)
from helpers import (
    require_role, get_json_body, require_fields, as_string,
    parse_pagination, paginate, get_studio, require_client_owns_project,
)
from util import parse_iso8601, mul_round_half_up
from response import success, success_list
from serialize import view
from services.calc import late_fee
from services.ledger import already_credited_deposit

bp = Blueprint("invoices", __name__)


def _resolve_invoice(studio_id, invoice_id):
    get_studio(studio_id)
    iv = db.invoices.get(invoice_id)
    if iv is None:
        raise err(ERR_NOT_FOUND, "Invoice not found")
    proj = db.projects.get(iv["project_id"])
    if proj is None or proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Invoice not found in this studio")
    return proj, iv


@bp.route("/studios/<studio_id>/invoices", methods=["POST"])
def issue_invoice(studio_id):
    caller = authenticate()
    require_role(caller, "BillingOps")
    studio = get_studio(studio_id)
    body = get_json_body()
    require_fields(body, "milestone_id", "due_date")
    milestone_id = as_string(body["milestone_id"], "milestone_id")
    due_raw = as_string(body["due_date"], "due_date")
    due_date = parse_iso8601(due_raw)
    if due_date is None:
        raise err(ERR_INVALID_REQUEST, "due_date must be an ISO 8601 datetime")

    # Body-referenced existence (§2.9).
    ms = db.milestones.get(milestone_id)
    if ms is None:
        raise err(ERR_NOT_FOUND, "Milestone not found")
    proj = db.projects.get(ms["project_id"])
    if proj is None or proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Milestone not found in this studio")

    # Transition PENDING -> INVOICED must be defined (state, priority 6).
    if ms["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Milestone is not PENDING")
    # Stage gate (priority 7).
    if proj["status"] not in ("DELIVERY", "HANDOFF"):
        raise err(ERR_PROJECT_WRONG_STAGE, "Project is not in DELIVERY or HANDOFF")
    # Zero-amount milestone cannot be invoiced.
    if ms["amount_cents"] <= 0:
        raise err(ERR_ZERO_AMOUNT_MILESTONE, "Milestone amount is zero")

    # ---- Money fields computed in fixed order (PRD §3.6) ----
    gross = ms["amount_cents"]
    # Deposit credit = min(round_half_up(gross * deposit_pct), remaining deposit).
    pct_credit = mul_round_half_up(gross, proj["deposit_pct"])
    consumed = already_credited_deposit(proj["id"])
    remaining = proj["deposit_collected_cents"] - consumed
    if remaining < 0:
        remaining = 0
    deposit_credit = min(pct_credit, remaining)

    taxable = gross - deposit_credit
    tax = mul_round_half_up(taxable, studio["tax_rate"])
    net_before_fee = taxable + tax
    late = 0
    net_due = net_before_fee + late

    invoice = db.create(db.invoices, {
        "project_id": proj["id"],
        "milestone_id": milestone_id,
        "gross_cents": gross,
        "deposit_credit_cents": deposit_credit,
        "tax_cents": tax,
        "late_fee_cents": late,
        "net_due_cents": net_due,
        "due_date": due_raw,
        "status": "ISSUED",
    })

    # Milestone PENDING -> INVOICED.
    ms["status"] = "INVOICED"
    db.touch(ms)

    return success(view(invoice), status=201)


@bp.route("/studios/<studio_id>/invoices/<invoice_id>", methods=["GET"])
def get_invoice(studio_id, invoice_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    proj, iv = _resolve_invoice(studio_id, invoice_id)
    require_client_owns_project(caller, proj)
    return success(view(iv), status=200)


@bp.route("/studios/<studio_id>/invoices", methods=["GET"])
def list_invoices(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    get_studio(studio_id)
    limit, offset = parse_pagination()

    # Invoices scoped to this studio (via their project).
    studio_project_ids = {
        p["id"] for p in db.projects.values() if p["studio_id"] == studio_id
    }
    records = [iv for iv in db.invoices.values()
               if iv["project_id"] in studio_project_ids]

    filter_project = request.args.get("project_id")
    filter_milestone = request.args.get("milestone_id")
    if filter_project is not None:
        records = [iv for iv in records if iv["project_id"] == filter_project]
    if filter_milestone is not None:
        records = [iv for iv in records if iv["milestone_id"] == filter_milestone]
    if caller.role == "Client":
        owned = {p["id"] for p in db.projects.values()
                 if p["studio_id"] == studio_id and p["client_id"] == caller.user_id}
        records = [iv for iv in records if iv["project_id"] in owned]

    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/invoices/<invoice_id>/mark-overdue", methods=["POST"])
def mark_overdue(studio_id, invoice_id):
    caller = authenticate()
    require_role(caller, "BillingOps")
    proj, iv = _resolve_invoice(studio_id, invoice_id)
    # ISSUED -> OVERDUE.
    if iv["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Invoice is not ISSUED")
    # Clock must be strictly beyond due_date.
    due_date = parse_iso8601(iv["due_date"])
    if not (clock.now() > due_date):
        raise err(ERR_NOT_YET_DUE, "Invoice is not yet due")

    net_before_fee = iv["net_due_cents"] - iv["late_fee_cents"]
    fee = late_fee(net_before_fee, clock.now(), due_date)
    iv["late_fee_cents"] = fee
    iv["net_due_cents"] = net_before_fee + fee
    iv["status"] = "OVERDUE"
    db.touch(iv)
    return success(view(iv), status=200)


@bp.route("/studios/<studio_id>/invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(studio_id, invoice_id):
    caller = authenticate()
    require_role(caller, "BillingOps")
    proj, iv = _resolve_invoice(studio_id, invoice_id)
    # ISSUED/OVERDUE -> PAID.
    if iv["status"] not in ("ISSUED", "OVERDUE"):
        raise err(ERR_INVALID_STATE, "Invoice is not payable from current state")
    iv["status"] = "PAID"
    db.touch(iv)
    # Bubble milestone -> PAID.
    ms = db.milestones.get(iv["milestone_id"])
    if ms is not None and ms["status"] in ("PENDING", "INVOICED"):
        ms["status"] = "PAID"
        db.touch(ms)
    return success(view(iv), status=200)
