"""Invoice endpoints (DRAFT -> ISSUED -> PAID; VOIDED from DRAFT/ISSUED)."""
from flask import Blueprint, request

import calc
from db import STORE, now_dt
from domain import (new_entity, bump, bump_program, regen_draft_invoices,
                    get_or_404, by_created, serialize_invoice)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_FORBIDDEN_OWNERSHIP, ERR_INVOICE_KIND_PHASE,
                    ERR_INVOICE_ALREADY_ISSUED)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("invoices", __name__)

KINDS = ("DEPOSIT", "PROGRESS", "FINAL")

# Kind-phase issuance gates (scaffold Invoice machine / PRD §3.12).
ISSUABLE_PHASES = {
    "DEPOSIT": ("BOOKED", "INDUCTED", "SURFACE_REVIEW", "IN_WORK",
                "IN_INSPECTION", "READY_FOR_DELIVERY"),
    "PROGRESS": ("IN_WORK", "IN_INSPECTION", "READY_FOR_DELIVERY"),
    "FINAL": ("READY_FOR_DELIVERY",),
}


def _kind_conflict(program_id, kind, exclude_id=None):
    for inv in calc.invoices_of(program_id):
        if inv["kind"] == kind and inv["status"] != "VOIDED" and inv["id"] != exclude_id:
            return True
    return False


@bp.post("/invoices")
def create_invoice():
    auth("FinanceClerk")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    kind = field(data, "kind", "str", enum=KINDS)
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] in ("DELIVERED", "CANCELLED"):
        raise invalid_state("Cannot draft an invoice for a terminal program")
    # PRD §3.12: drafting is permitted in any non-terminal phase; the
    # same-kind uniqueness rule is enforced at issuance, not at drafting.
    inv = new_entity()
    inv.update({
        "program_id": program_id,
        "kind": kind,
        "status": "DRAFT",
        "lines": None,       # DRAFT lines are computed at read time
        "total_cents": None,
        "issued_at": None,
    })
    STORE.invoices[inv["id"]] = inv
    return success(serialize_invoice(inv), status=201)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    auth()
    inv = get_or_404(STORE.invoices, iid, "Invoice")
    return success(serialize_invoice(inv))


@bp.get("/invoices")
def list_invoices():
    auth()
    items = by_created(list(STORE.invoices.values()))
    for key in ("program_id", "kind", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [i for i in items if i[key] == value]
    return paginate(items, serialize_invoice)


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    auth("FinanceClerk")
    inv = get_or_404(STORE.invoices, iid, "Invoice")
    if inv["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT invoice can be issued")
    prog = STORE.programs[inv["program_id"]]
    if prog["status"] not in ISSUABLE_PHASES[inv["kind"]]:
        raise ApiError(ERR_INVOICE_KIND_PHASE, 409,
                       f"{inv['kind']} invoices are not issuable while the "
                       f"program is {prog['status']}")
    if _kind_conflict(prog["id"], inv["kind"], exclude_id=inv["id"]):
        raise ApiError(ERR_INVOICE_ALREADY_ISSUED, 409,
                       f"Another non-VOIDED {inv['kind']} invoice exists")
    # FINAL issuance persists the settlement-variant penalty before freezing
    # lines (the penalty credit line reads penalty_final_cents).
    if inv["kind"] == "FINAL":
        prog["penalty_final_cents"] = calc.delivery_penalty(
            prog, "settlement", reference_date=now_dt().date())
        bump_program(prog)
    lines, total = calc.compute_invoice_lines(prog, inv["kind"])
    inv["lines"] = lines
    inv["total_cents"] = total
    inv["issued_at"] = now_dt()
    inv["status"] = "ISSUED"
    bump(inv)
    return success(serialize_invoice(inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    user_id, _ = auth("CustomerRep")
    inv = get_or_404(STORE.invoices, iid, "Invoice")
    prog = STORE.programs[inv["program_id"]]
    if user_id != prog["customer_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "X-User-ID does not match the program's customer_id")
    if inv["status"] != "ISSUED":
        raise invalid_state("Only an ISSUED invoice can be paid")
    inv["status"] = "PAID"
    bump(inv)
    # billed_total_cents (derived) now includes this invoice.
    bump_program(prog)
    regen_draft_invoices(prog["id"])
    return success(serialize_invoice(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    auth("FinanceClerk")
    inv = get_or_404(STORE.invoices, iid, "Invoice")
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise invalid_state("Only a DRAFT or ISSUED invoice can be voided")
    prog = STORE.programs[inv["program_id"]]
    if inv["status"] == "ISSUED":
        if prog["status"] == "DELIVERED":
            raise invalid_state("Cannot void an ISSUED invoice after delivery")
    was_issued = inv["status"] == "ISSUED"
    inv["status"] = "VOIDED"
    bump(inv)
    if was_issued:
        # Issue-then-void nets to zero in billed_total_cents (derived).
        bump_program(prog)
        regen_draft_invoices(prog["id"])
    return success(serialize_invoice(inv))
