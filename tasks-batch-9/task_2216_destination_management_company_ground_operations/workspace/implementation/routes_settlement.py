"""Reconciliation-line and settlement-payment endpoints."""

from flask import Blueprint

import calc
import cascades
import derive
import ops
import serializers
from auth import (ALL_DMC_ROLES, ROLE_CONTROLLER, ROLE_PROGRAM_DIRECTOR,
                  ROLE_SUPPLIER_MANAGER, current_user_id, endpoint)
from common import (apply_filters, contract_or_404, program_or_404, recon_line_or_404,
                    respond_list, settlement_or_404, supplier_or_404)
from envelope import created, ok
from errors import fail
from store import db, new_row, touch
from validation import body, opt_str, ref_id, req_int, req_str

bp = Blueprint("settlement", __name__)

LINE_KINDS = ("DELIVERY", "CANCELLATION_PENALTY")
LINE_STATUSES = ("DRAFT", "APPROVED")
PAYMENT_STATUSES = ("PENDING", "APPROVED", "PAID", "VOID")
PAYMENT_READ_ROLES = (ROLE_PROGRAM_DIRECTOR, ROLE_SUPPLIER_MANAGER, ROLE_CONTROLLER)

_LINE_KIND_RANK = {"CANCELLATION_PENALTY": 0, "DELIVERY": 1}


# --------------------------------------------------------------------------
# reconciliation lines
# --------------------------------------------------------------------------

@bp.get("/dmc/reconciliation-lines/<reconciliation_line_id>")
@endpoint(ALL_DMC_ROLES)
def read_line(reconciliation_line_id):
    return ok(serializers.reconciliation_line(recon_line_or_404(reconciliation_line_id)))


@bp.get("/dmc/reconciliation-lines")
@endpoint(ALL_DMC_ROLES)
def list_lines():
    rows = apply_filters(list(db.recon_lines.values()), [
        ("program_id", "program_id", None),
        ("element_id", "element_id", None),
        ("supplier_id", "supplier_id", None),
        ("status", "status", LINE_STATUSES),
    ])
    return respond_list(rows, serializers.reconciliation_line)


@bp.patch("/dmc/reconciliation-lines/<reconciliation_line_id>")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def patch_line(reconciliation_line_id):
    line = recon_line_or_404(reconciliation_line_id)
    data = body()
    variance_reason = None
    if "variance_reason" in data:
        variance_reason = opt_str(data, "variance_reason")
    actual_headcount = None
    if "actual_headcount" in data and data["actual_headcount"] is not None:
        actual_headcount = req_int(data, "actual_headcount", minimum=0)

    # A patch is not a state transition, so the reconciliation-window
    # requirement PRD section 3.8 names for patching is the gate that speaks
    # first; the DRAFT requirement is checked behind it.
    program = db.programs.get(line["program_id"])
    if program is None or program["settlement_status"] != "RECONCILING":
        fail("ERR_PROGRAM_NOT_RECONCILING",
             "The programme's settlement_status is not RECONCILING.")
    if line["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT line may be patched.")

    if "variance_reason" in data:
        line["variance_reason"] = variance_reason
    if actual_headcount is not None:
        line["actual_headcount"] = actual_headcount
        element = db.elements.get(line["element_id"])
        if element is not None:
            ops.recompute_line(line, element, program)
    touch(line)
    return ok(serializers.reconciliation_line(line))


@bp.post("/dmc/reconciliation-lines/<reconciliation_line_id>/approve")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def approve_line(reconciliation_line_id):
    line = recon_line_or_404(reconciliation_line_id)
    if line["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "approve requires status DRAFT.")
    program = db.programs.get(line["program_id"])
    if program is None or program["settlement_status"] != "RECONCILING":
        fail("ERR_PROGRAM_NOT_RECONCILING",
             "The programme's settlement_status is not RECONCILING.")
    if calc.dec(line["variance_pct"]) > calc.VARIANCE_TOLERANCE_PCT:
        reason = line.get("variance_reason")
        if not isinstance(reason, str) or not reason.strip():
            fail("ERR_VARIANCE_REASON_REQUIRED",
                 "A line above the variance tolerance needs a variance_reason.")

    line["status"] = "APPROVED"
    touch(line)
    return ok(serializers.reconciliation_line(line))


# --------------------------------------------------------------------------
# settlement payments
# --------------------------------------------------------------------------

def _approved_lines_for(program_id, supplier_id):
    return [l for l in derive.lines_of_program(program_id)
            if l["supplier_id"] == supplier_id and l["status"] == "APPROVED"]


def _waterfall_order(lines):
    def key(line):
        element = db.elements.get(line["element_id"])
        starts_at = element["starts_at"] if element else line["created_at"]
        return (_LINE_KIND_RANK.get(line["line_kind"], 9), starts_at,
                line["created_at"], line["_seq"])

    return sorted(lines, key=key)


@bp.post("/dmc/settlement-payments")
@endpoint((ROLE_CONTROLLER,))
def create_payment():
    data = body()
    program_ref = ref_id(data, "program_id")
    if program_ref is not None:
        program_or_404(program_ref)
    supplier_ref = ref_id(data, "supplier_id")
    if supplier_ref is not None:
        supplier_or_404(supplier_ref)
    contract = None
    contract_ref = ref_id(data, "contract_id")
    if contract_ref is not None:
        contract = contract_or_404(contract_ref)

    program_id = req_str(data, "program_id", min_len=1)
    supplier_id = req_str(data, "supplier_id", min_len=1)
    contract_id = req_str(data, "contract_id", min_len=1)
    expected_contract_version = req_int(data, "expected_contract_version")

    if expected_contract_version != contract["version"]:
        fail("ERR_STALE_CONTRACT_VERSION",
             "expected_contract_version does not match the contract's current version.")

    lines = _approved_lines_for(program_id, supplier_id)
    gross_cents = sum(int(l["supplier_cost_cents"]) for l in lines)
    deposit_applied, net_payable, overpayment_credit = calc.settlement_waterfall(
        _waterfall_order(lines), contract["deposit_paid_cents"], gross_cents)

    row = new_row(
        program_id=program_id,
        supplier_id=supplier_id,
        contract_id=contract_id,
        gross_cents=gross_cents,
        deposit_applied_cents=deposit_applied,
        net_payable_cents=net_payable,
        overpayment_credit_cents=overpayment_credit,
        status="PENDING",
        approved_by_user_id=None,
        released_by_user_id=None,
    )
    db.settlements[row["id"]] = row
    touch(contract)
    return created(serializers.settlement_payment(row))


@bp.get("/dmc/settlement-payments/<settlement_payment_id>")
@endpoint(PAYMENT_READ_ROLES)
def read_payment(settlement_payment_id):
    return ok(serializers.settlement_payment(settlement_or_404(settlement_payment_id)))


@bp.get("/dmc/settlement-payments")
@endpoint(PAYMENT_READ_ROLES)
def list_payments():
    rows = apply_filters(list(db.settlements.values()), [
        ("program_id", "program_id", None),
        ("supplier_id", "supplier_id", None),
        ("contract_id", "contract_id", None),
        ("status", "status", PAYMENT_STATUSES),
    ])
    return respond_list(rows, serializers.settlement_payment)


@bp.post("/dmc/settlement-payments/<settlement_payment_id>/approve")
@endpoint((ROLE_CONTROLLER,))
def approve_payment(settlement_payment_id):
    payment = settlement_or_404(settlement_payment_id)
    if payment["status"] != "PENDING":
        fail("ERR_INVALID_STATE_TRANSITION", "approve requires status PENDING.")
    program = db.programs.get(payment["program_id"])
    if program is None or program["settlement_status"] not in ("RECONCILING",
                                                              "CLIENT_INVOICED"):
        fail("ERR_PROGRAM_NOT_RECONCILING",
             "The programme must be RECONCILING or CLIENT_INVOICED.")
    contract = db.contracts.get(payment["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The contract is no longer ACTIVE.")
    if int(payment["net_payable_cents"]) > derive.supplier_open_payable_cents(
            payment["program_id"]):
        fail("ERR_SETTLEMENT_EXCEEDS_OPEN_PAYABLE",
             "The settlement exceeds the programme's open payable.")

    payment["status"] = "APPROVED"
    payment["approved_by_user_id"] = current_user_id()
    touch(payment)
    return ok(serializers.settlement_payment(payment))


@bp.post("/dmc/settlement-payments/<settlement_payment_id>/release")
@endpoint((ROLE_CONTROLLER,))
def release_payment(settlement_payment_id):
    payment = settlement_or_404(settlement_payment_id)
    if payment["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION", "release requires status APPROVED.")
    if current_user_id() == payment["approved_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The releasing Controller must differ from the approver.")

    payment["status"] = "PAID"
    payment["released_by_user_id"] = current_user_id()
    touch(payment)
    program = db.programs.get(payment["program_id"])
    if program is not None:
        cascades.bubble_program_settled(program)
    return ok(serializers.settlement_payment(payment))


@bp.post("/dmc/settlement-payments/<settlement_payment_id>/void")
@endpoint((ROLE_CONTROLLER,))
def void_payment(settlement_payment_id):
    payment = settlement_or_404(settlement_payment_id)
    data = body()
    opt_str(data, "void_reason")
    if payment["status"] not in ("PENDING", "APPROVED"):
        fail("ERR_SETTLEMENT_ALREADY_PAID",
             "A paid or voided settlement can no longer be voided.")

    payment["status"] = "VOID"
    touch(payment)
    return ok(serializers.settlement_payment(payment))
