"""Invoice routes. PRD 3.9, 3.10 + 2.9 OCC."""
from flask import Blueprint, request

from clock import clock
from db import store, iso, common_fields_on_create, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_EMPTY_INVOICE,
    ERR_STALE_VERSION,
)
from helpers import (
    get_body, require_str, require_datetime, opt_enum, require_int,
    parse_pagination, paginate, parse_datetime,
)
from middleware import get_principal, require_roles
from response import object_response, array_response
from domain import serialize_invoice, recompute_parent_ledger
from lookups import get_parent, get_invoice
from calculations import compute_window_count, prorated_line_cents, apply_sibling_discount

bp = Blueprint("invoices", __name__)


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    principal = get_principal()
    require_roles(principal, ["BillingAdmin"])
    body = get_body()
    parent_id = require_str(body, "parent_id")
    parent = get_parent(parent_id)
    cycle_start = require_datetime(body, "cycle_start")
    cycle_end = require_datetime(body, "cycle_end")
    if cycle_end <= cycle_start:
        err(ERR_INVALID_REQUEST, "cycle_end must be > cycle_start")
    due_at = require_datetime(body, "due_at")
    variant = opt_enum(body, "variant", ["FORWARD_LOOKING", "CHRONOLOGICAL"],
                       "FORWARD_LOOKING")

    current_utc = clock.now()
    # Billable enrollments: the parent's enrollments in ACTIVE or PAUSED status.
    billable = []
    for e in store.enrollments.values():
        student = store.students.get(e["student_id"])
        if student is None or student["parent_id"] != parent["id"]:
            continue
        if e["status"] in ("ACTIVE", "PAUSED"):
            billable.append(e)

    lines = []
    for e in billable:
        session = store.class_sessions.get(e["class_session_id"])
        if session is None:
            continue
        joined_at = parse_datetime(e["joined_at"], "joined_at") if e["joined_at"] else cycle_start
        window, occ_total = compute_window_count(
            joined_at, cycle_start, cycle_end, current_utc,
            session["day_of_week"], variant)
        prorated = prorated_line_cents(e["tuition_basis_cents"], window, occ_total)
        lines.append({
            "enrollment_id": e["id"],
            "student_id": e["student_id"],
            "basis_cents": e["tuition_basis_cents"],
            "prorated_cents": prorated,
            # discount_pct / line_total_cents / line_discount_amount filled below.
        })

    # Sibling discount + pinned totals.
    if lines:
        sids = set(l["student_id"] for l in lines)
        student_created_at = {
            sid: store.students[sid]["created_at"]
            for sid in sids if sid in store.students
        }
        student_seq = {
            sid: store.students[sid]["_seq"]
            for sid in sids if sid in store.students
        }
        subtotal, discount, total = apply_sibling_discount(
            lines, student_created_at, student_seq)
        # Emit only the public line fields (drop internal line_discount_amount).
        public_lines = [{
            "enrollment_id": l["enrollment_id"],
            "student_id": l["student_id"],
            "basis_cents": l["basis_cents"],
            "prorated_cents": l["prorated_cents"],
            "discount_pct": l["discount_pct"],
            "line_total_cents": l["line_total_cents"],
        } for l in lines]
    else:
        subtotal = discount = total = 0
        public_lines = []

    rec = common_fields_on_create()
    rec.update({
        "parent_id": parent["id"],
        "cycle_start": iso(cycle_start),
        "cycle_end": iso(cycle_end),
        "variant": variant,
        "line_items": public_lines,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": total,
        "due_at": iso(due_at),
        "status": "DRAFT",
    })
    store.invoices[rec["id"]] = rec
    return object_response(serialize_invoice(rec), 201)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin", "Parent"])
    limit, offset = parse_pagination()
    records = list(store.invoices.values())
    # Parent sees only their own invoices.
    if principal.role == "Parent":
        records = [r for r in records if r["parent_id"] == principal.user_id]
    for f in ("parent_id", "status"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_invoice(r) for r in window], limit, offset, total)


@bp.route("/invoices/<id>", methods=["GET"])
def get_invoice_route(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin", "Parent"])
    rec = get_invoice(id)
    if principal.role == "Parent" and principal.user_id != rec["parent_id"]:
        from errors import ERR_NOT_RESOURCE_OWNER
        err(ERR_NOT_RESOURCE_OWNER, "Parent may only view its own invoice")
    return object_response(serialize_invoice(rec), 200)


@bp.route("/invoices/<id>/issue", methods=["POST"])
def issue_invoice(id):
    principal = get_principal()
    require_roles(principal, ["BillingAdmin"])
    invoice = get_invoice(id)
    # State legality: only DRAFT -> ISSUED.
    if invoice["status"] != "DRAFT":
        err(ERR_INVALID_STATE, "Only a DRAFT invoice may be issued")
    # priority 14: non-empty line_items.
    if not invoice["line_items"]:
        err(ERR_EMPTY_INVOICE, "Cannot issue an invoice with no line items")
    invoice["status"] = "ISSUED"
    touch(invoice)
    parent = store.parents.get(invoice["parent_id"])
    if parent is not None:
        recompute_parent_ledger(parent)  # outstanding_balance reflects ISSUED set.
    return object_response(serialize_invoice(invoice), 200)


@bp.route("/invoices/<id>/pay", methods=["POST"])
def pay_invoice(id):
    principal = get_principal()
    require_roles(principal, ["BillingAdmin"])
    invoice = get_invoice(id)
    body = get_body()
    expected_version = require_int(body, "expected_invoice_version")
    # State legality: only ISSUED -> PAID.
    if invoice["status"] != "ISSUED":
        err(ERR_INVALID_STATE, "Only an ISSUED invoice may be paid")
    # priority 15: OCC.
    if expected_version != invoice["version"]:
        err(ERR_STALE_VERSION, "Stale invoice version")
    invoice["status"] = "PAID"
    touch(invoice)  # version++.
    parent = store.parents.get(invoice["parent_id"])
    if parent is not None:
        recompute_parent_ledger(parent)  # balance/standing recomputed.
    return object_response(serialize_invoice(invoice), 200)


@bp.route("/invoices/<id>/void", methods=["POST"])
def void_invoice(id):
    principal = get_principal()
    require_roles(principal, ["BillingAdmin"])
    invoice = get_invoice(id)
    # State legality: only ISSUED -> VOID.
    if invoice["status"] != "ISSUED":
        err(ERR_INVALID_STATE, "Only an ISSUED invoice may be voided")
    invoice["status"] = "VOID"
    touch(invoice)  # version++.
    parent = store.parents.get(invoice["parent_id"])
    if parent is not None:
        recompute_parent_ledger(parent)
    return object_response(serialize_invoice(invoice), 200)
