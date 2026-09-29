"""Logical clock and programme endpoints."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import ops
import serializers
from auth import ALL_DMC_ROLES, ROLE_CONTROLLER, ROLE_PROGRAM_DIRECTOR, current_user_id, endpoint
from common import apply_filters, program_or_404, respond_list
from envelope import created, ok
from errors import fail
from store import clock_now, db, fmt_dt, new_row, set_clock, touch
from validation import (body, opt_num, opt_str, pagination, req_dt, req_int, req_str,
                        strictly_after)

bp = Blueprint("programs", __name__)

EXECUTION_STATUSES = ("DRAFT", "DESIGN_LOCKED", "CONFIRMED", "IN_EXECUTION",
                      "COMPLETED", "CANCELLED")
SETTLEMENT_STATUSES = ("NOT_STARTED", "RECONCILING", "CLIENT_INVOICED", "CREDITED", "SETTLED")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@endpoint(ALL_DMC_ROLES)
def set_current_utc():
    data = body()
    instant = req_dt(data, "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": fmt_dt(clock_now())})


# --------------------------------------------------------------------------
# programme CRUD
# --------------------------------------------------------------------------

@bp.post("/dmc/programs")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def create_program():
    data = body()
    client_name = req_str(data, "client_name", min_len=1, max_len=120)
    group_name = req_str(data, "group_name", min_len=1, max_len=120)
    arrival_date = req_dt(data, "arrival_date")
    departure_date = req_dt(data, "departure_date")
    strictly_after(departure_date, arrival_date, "departure_date", "arrival_date")
    guaranteed_count = req_int(data, "guaranteed_count", minimum=1)
    markup_pct = opt_num(data, "markup_pct", default=0.18)

    if not (calc.MARKUP_PCT_MIN <= calc.dec(markup_pct) <= calc.MARKUP_PCT_MAX):
        fail("ERR_MARKUP_PCT_OUT_OF_BAND",
             "markup_pct must be between 0.05 and 0.35 inclusive.")

    row = new_row(
        client_name=client_name,
        group_name=group_name,
        arrival_date=arrival_date,
        departure_date=departure_date,
        guaranteed_count=guaranteed_count,
        markup_pct=markup_pct,
        execution_status="DRAFT",
        settlement_status="NOT_STARTED",
        estimated_client_total_cents=0,
        management_fee_cents=0,
        final_client_total_cents=0,
        fee_pct_applied=0,
        credit_note_cents=0,
        staffing_gap_count=0,
        unseated_guest_count=0,
        invoice_issued_at=None,
    )
    db.programs[row["id"]] = row
    return created(serializers.program(row))


@bp.get("/dmc/programs/<program_id>")
@endpoint(ALL_DMC_ROLES)
def read_program(program_id):
    program = program_or_404(program_id)
    return ok(serializers.program(program))


@bp.get("/dmc/programs")
@endpoint(ALL_DMC_ROLES)
def list_programs():
    rows = apply_filters(list(db.programs.values()), [
        ("execution_status", "execution_status", EXECUTION_STATUSES),
        ("settlement_status", "settlement_status", SETTLEMENT_STATUSES),
    ])
    return respond_list(rows, serializers.program)


@bp.get("/dmc/programs/<program_id>/cost-summary")
@endpoint((ROLE_PROGRAM_DIRECTOR, ROLE_CONTROLLER))
def program_cost_summary(program_id):
    program = program_or_404(program_id)
    return ok(serializers.cost_summary(program))


# --------------------------------------------------------------------------
# execution dimension
# --------------------------------------------------------------------------

@bp.post("/dmc/programs/<program_id>/lock-design")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def lock_design(program_id):
    program = program_or_404(program_id)
    if program["execution_status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION",
             "lock-design requires execution_status DRAFT.")
    if derive.element_count(program_id) < 1:
        fail("ERR_PROGRAM_HAS_NO_ELEMENTS", "The programme has no elements to freeze.")
    if not (calc.MARKUP_PCT_MIN <= calc.dec(program["markup_pct"]) <= calc.MARKUP_PCT_MAX):
        fail("ERR_MARKUP_PCT_OUT_OF_BAND",
             "markup_pct must be between 0.05 and 0.35 inclusive.")
    program["execution_status"] = "DESIGN_LOCKED"
    touch(program)
    return ok(serializers.program(program))


@bp.post("/dmc/programs/<program_id>/unlock-design")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def unlock_design(program_id):
    program = program_or_404(program_id)
    if program["execution_status"] != "DESIGN_LOCKED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "unlock-design requires execution_status DESIGN_LOCKED.")
    if program["settlement_status"] != "NOT_STARTED":
        fail("ERR_PROGRAM_ALREADY_RECONCILING",
             "The settlement dimension has already left NOT_STARTED.")
    for assignment in derive.assignments_of_program(program_id):
        if assignment["status"] in ("CHECKED_IN", "COMPLETED"):
            fail("ERR_PROGRAM_ALREADY_STAFFED_ON_SITE",
                 "Staff have already worked this programme.")
    program["execution_status"] = "DRAFT"
    touch(program)
    return ok(serializers.program(program))


@bp.post("/dmc/programs/<program_id>/confirm")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def confirm_program(program_id):
    program = program_or_404(program_id)
    if program["execution_status"] != "DESIGN_LOCKED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "confirm requires execution_status DESIGN_LOCKED.")
    elements = derive.elements_of_program(program_id)
    for element in elements:
        if element["status"] == "PERMIT_BLOCKED":
            fail("ERR_PERMIT_NOT_APPROVED",
                 "An element of the programme is permit-blocked.")
    for element in elements:
        if element["status"] in ("PLANNED", "READY"):
            if derive.active_contract_for(program_id, element["supplier_id"]) is None:
                fail("ERR_NO_ACTIVE_SUPPLIER_CONTRACT",
                     "An element is not covered by an ACTIVE supplier contract.")
    program["execution_status"] = "CONFIRMED"
    _base, _fee_pct, _fee, total = ops.estimate_client_total(program)
    program["estimated_client_total_cents"] = total
    touch(program)
    return ok(serializers.program(program))


@bp.post("/dmc/programs/<program_id>/start-execution")
@endpoint(("OperationsCoordinator",))
def start_execution(program_id):
    program = program_or_404(program_id)
    if program["execution_status"] != "CONFIRMED":
        fail("ERR_PROGRAM_NOT_CONFIRMED",
             "start-execution requires execution_status CONFIRMED.")
    if clock_now() < program["arrival_date"]:
        fail("ERR_PROGRAM_WINDOW_NOT_OPEN",
             "The programme window has not opened yet.")
    program["execution_status"] = "IN_EXECUTION"
    touch(program)
    return ok(serializers.program(program))


@bp.post("/dmc/programs/<program_id>/cancel")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def cancel_program(program_id):
    program = program_or_404(program_id)
    body()
    if program["execution_status"] not in ("DRAFT", "DESIGN_LOCKED", "CONFIRMED",
                                           "IN_EXECUTION"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The programme can no longer be cancelled.")
    if program["settlement_status"] != "NOT_STARTED":
        fail("ERR_PROGRAM_ALREADY_RECONCILING",
             "The settlement dimension has already left NOT_STARTED.")

    # The programme leaves IN_EXECUTION first, so the COMPLETED bubble-up
    # cannot fire while the element cascade empties the open set.
    program["execution_status"] = "CANCELLED"
    for element in derive.elements_of_program(program_id):
        cascades.cancel_element(element, program, bubble=False)
    for segment in derive.segments_of_program(program_id):
        cascades.cancel_segment(segment, program)
    touch(program)
    return ok(serializers.program(program))


# --------------------------------------------------------------------------
# settlement dimension
# --------------------------------------------------------------------------

@bp.post("/dmc/programs/<program_id>/reconcile")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def reconcile_program(program_id):
    program = program_or_404(program_id)
    if program["settlement_status"] != "NOT_STARTED":
        fail("ERR_PROGRAM_ALREADY_RECONCILING",
             "Reconciliation has already been opened.")
    if program["execution_status"] not in ("COMPLETED", "CANCELLED"):
        fail("ERR_PROGRAM_NOT_EXECUTION_FINAL",
             "The execution dimension has not reached a final state.")
    reconcilable = [e for e in derive.elements_of_program(program_id)
                    if e["status"] in ("DELIVERED", "CANCELLED")]
    if not reconcilable:
        fail("ERR_NO_RECONCILABLE_ELEMENTS", "Nothing to reconcile on this programme.")

    program["settlement_status"] = "RECONCILING"
    ops.materialise_lines(program)
    touch(program)
    return ok(serializers.program(program))


@bp.post("/dmc/programs/<program_id>/issue-invoice")
@endpoint((ROLE_CONTROLLER,))
def issue_invoice(program_id):
    program = program_or_404(program_id)
    if program["settlement_status"] != "RECONCILING":
        fail("ERR_PROGRAM_NOT_RECONCILING",
             "issue-invoice requires settlement_status RECONCILING.")
    for line in derive.lines_of_program(program_id):
        if line["status"] != "APPROVED":
            fail("ERR_RECONCILIATION_LINES_PENDING",
                 "Every reconciliation line must be APPROVED first.")

    _base, fee_pct, fee, total = ops.final_client_total(program)
    program["settlement_status"] = "CLIENT_INVOICED"
    program["management_fee_cents"] = fee
    program["final_client_total_cents"] = total
    program["fee_pct_applied"] = float(fee_pct)
    program["invoice_issued_at"] = clock_now()
    touch(program)
    return ok(serializers.program(program))


@bp.post("/dmc/programs/<program_id>/credit-invoice")
@endpoint((ROLE_CONTROLLER,))
def credit_invoice(program_id):
    program = program_or_404(program_id)
    data = body()
    req_str(data, "credit_reason", min_len=1)
    if program["settlement_status"] != "CLIENT_INVOICED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "credit-invoice requires settlement_status CLIENT_INVOICED.")
    for payment in derive.payments_of_program(program_id):
        if payment["status"] == "PAID":
            fail("ERR_SETTLEMENT_ALREADY_PAID",
                 "A settlement payment of this programme has already been paid.")

    program["settlement_status"] = "CREDITED"
    program["credit_note_cents"] += int(program["final_client_total_cents"])
    for line in derive.lines_of_program(program_id):
        if line["status"] == "APPROVED":
            line["status"] = "DRAFT"
            touch(line)
    touch(program)

    # Server-driven follow-on transition inside the same request.
    if not any(l["status"] == "APPROVED" for l in derive.lines_of_program(program_id)):
        program["settlement_status"] = "RECONCILING"
        program["management_fee_cents"] = 0
        program["final_client_total_cents"] = 0
        program["fee_pct_applied"] = 0
        program["invoice_issued_at"] = None
        touch(program)

    return ok(serializers.program(program))
