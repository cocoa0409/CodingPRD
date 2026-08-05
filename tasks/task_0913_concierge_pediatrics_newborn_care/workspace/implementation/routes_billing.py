"""Service lines and invoices."""
from flask import Blueprint, g

import calc
import constants as C
import serialize
import svc_invoice
import svc_line
import validate as V
from auth import begin, parent_family_scope, require_family_owner, require_membership_owner
from envelope import object_response
from errors import ApiError
from listing import paginated
from store import db, touch
from timeutil import add_days

bp = Blueprint("billing", __name__)

LINE_ROLES = [C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST, C.ROLE_PARENT]
LINE_WRITE_ROLES = [C.ROLE_BILLING_SPECIALIST, C.ROLE_PRACTICE_ADMIN]
INVOICE_READ_ROLES = [C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST, C.ROLE_PARENT]
INVOICE_WRITE_ROLES = [C.ROLE_BILLING_SPECIALIST, C.ROLE_PRACTICE_ADMIN]


def _membership_family(membership_id):
    membership = db.memberships.get(membership_id)
    return membership["family_id"] if membership else None


# =============================================================== ServiceLine
@bp.get("/peds/service-lines")
def list_service_lines():
    begin(LINE_ROLES)
    route = V.enum_filter("route", C.ROUTE_VALUES)                     # RUNG 4 p10
    status = V.enum_filter("status", C.SERVICE_LINE_STATUSES)
    limit, offset = V.pagination()                                     # RUNG 4 p11
    encounter_id = V.filter_value("encounter_id")
    consult_booking_id = V.filter_value("consult_booking_id")
    well_visit_id = V.filter_value("well_visit_id")
    membership_id = V.filter_value("membership_id")
    policy_id = V.filter_value("policy_id")
    scope = parent_family_scope()

    rows = []
    for line in db.service_lines.values():
        if encounter_id is not None and line["encounter_id"] != encounter_id:
            continue
        if consult_booking_id is not None and line["consult_booking_id"] != consult_booking_id:
            continue
        if well_visit_id is not None and line["well_visit_id"] != well_visit_id:
            continue
        if membership_id is not None and line["membership_id"] != membership_id:
            continue
        if policy_id is not None and line["policy_id"] != policy_id:
            continue
        if route is not None and line["route"] != route:
            continue
        if status is not None and line["status"] != status:
            continue
        if scope is not None and _membership_family(line["membership_id"]) != scope:
            continue
        rows.append(line)
    return paginated(rows, serialize.service_line_json, limit, offset)


@bp.get("/peds/service-lines/<service_line_id>")
def read_service_line(service_line_id):
    begin(LINE_ROLES)
    line = db.service_lines.get(service_line_id)                       # RUNG 3 p8
    if line is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_membership_owner(db.memberships.get(line["membership_id"]))  # RUNG 7 p19
    return object_response(serialize.service_line_json(line), 200)


@bp.post("/peds/service-lines/<service_line_id>/adjudicate")
def adjudicate_line(service_line_id):
    begin(LINE_WRITE_ROLES)
    line = db.service_lines.get(service_line_id)                       # RUNG 3 p8
    if line is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    body = V.json_body()
    allowed_amount_cents = V.req_int(body, "allowed_amount_cents")     # RUNG 4 p9
    expected_policy_version = V.req_int(body, "expected_policy_version")
    override = V.opt_int(body, "patient_responsibility_override_cents", None)
    V.check_range(                                                     # RUNG 4 p11
        0 <= allowed_amount_cents <= line["billed_amount_cents"],
        "allowed_amount_cents must be between 0 and the line's billed_amount_cents.",
    )

    if g.user_id == line["submitted_by_user_id"]:                      # RUNG 8 p20
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    policy = db.policies.get(line["policy_id"]) if line["policy_id"] else None
    if policy is not None and expected_policy_version != policy["version"]:
        raise ApiError("ERR_STALE_VERSION")                            # RUNG 9 p21

    # RUNG 12 p26 is evaluated ahead of the state rung for lines that can never
    # be adjudicated at all: a COVERED_BY_MEMBERSHIP or PATIENT_RESPONSIBILITY
    # line is born SETTLED, so PRD 3.7's "is refused with ERR_ROUTE_NOT_
    # ADJUDICABLE" would otherwise be unreachable.  Insurance-routed lines keep
    # the ladder order exactly: state (p22) then policy state (p25).
    if line["route"] != "BILLED_TO_INSURANCE":
        raise ApiError("ERR_ROUTE_NOT_ADJUDICABLE")

    if line["status"] != "ROUTED":                                     # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a ROUTED line can be adjudicated.")
    if policy is None or policy["status"] != "ACTIVE":                 # RUNG 11 p25
        raise ApiError("ERR_POLICY_INACTIVE")

    split = calc.insurance_split(line["billed_amount_cents"], allowed_amount_cents, policy)

    if override is not None:                                           # RUNG 17 p36
        ceiling = split["deductible_applied_cents"] + split["coinsurance_cents"]
        if override > ceiling:
            raise ApiError("ERR_BALANCE_BILLING_BLOCKED")

    line.update(split)
    line["status"] = "ADJUDICATED"
    line["adjudicated_by_user_id"] = g.user_id
    touch(line, g.touched)

    policy["deductible_met_cents"] += split["deductible_applied_cents"]
    touch(policy, g.touched)
    return object_response(serialize.service_line_json(line), 200)


@bp.post("/peds/service-lines/<service_line_id>/settle")
def settle_line(service_line_id):
    begin(LINE_WRITE_ROLES)
    line = db.service_lines.get(service_line_id)                       # RUNG 3 p8
    if line is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    body = V.json_body()
    payment_received_cents = V.req_int(body, "payment_received_cents")  # RUNG 4 p9

    if line["status"] != "ADJUDICATED":                                # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only an ADJUDICATED line can be settled.")
    if payment_received_cents != line["patient_responsibility_cents"]:  # RUNG 17 p38
        raise ApiError("ERR_VALIDATION", "Settlement must be exact.")

    line["status"] = "SETTLED"
    line["payment_received_cents"] = payment_received_cents
    touch(line, g.touched)

    encounter = db.encounters.get(line["encounter_id"]) if line["encounter_id"] else None
    if encounter is not None and svc_line.bubble_billing_axis(encounter):
        touch(encounter, g.touched)
    return object_response(serialize.service_line_json(line), 200)


# =================================================================== Invoice
@bp.post("/peds/invoices")
def create_invoice():
    begin(INVOICE_WRITE_ROLES)
    body = V.json_body()
    family_id = V.req_string(body, "family_id")                        # RUNG 4 p9
    V.req_string(body, "cycle_start_date")
    cycle_start_date = V.req_date(body, "cycle_start_date")            # RUNG 5 p12
    V.date_range(                                                      # RUNG 5 p13
        cycle_start_date.day == 1,
        "cycle_start_date must be the 1st day of a calendar month.",
    )

    family = db.families.get(family_id)                                # RUNG 6 p14
    if family is None:
        raise ApiError("ERR_FAMILY_NOT_FOUND")

    if svc_invoice.find_invoice(family_id, cycle_start_date) is not None:  # RUNG 15 p33
        raise ApiError(
            "ERR_DUPLICATE_WAITLIST_ENTRY",
            "An invoice already exists for this household and cycle.",
        )

    invoice = svc_invoice.create_invoice(family, cycle_start_date)
    return object_response(serialize.invoice_json(invoice), 201)


@bp.get("/peds/invoices")
def list_invoices():
    begin(INVOICE_READ_ROLES)
    status = V.enum_filter("status", C.INVOICE_STATUSES)               # RUNG 4 p10
    limit, offset = V.pagination()                                     # RUNG 4 p11
    family_id = V.filter_value("family_id")
    cycle_start_date = V.filter_value("cycle_start_date")
    scope = parent_family_scope()

    rows = []
    for invoice in db.invoices.values():
        if family_id is not None and invoice["family_id"] != family_id:
            continue
        if status is not None and invoice["status"] != status:
            continue
        if cycle_start_date is not None:
            from timeutil import fmt_date

            if fmt_date(invoice["cycle_start_date"]) != cycle_start_date:
                continue
        if scope is not None and invoice["family_id"] != scope:
            continue
        rows.append(invoice)
    return paginated(rows, serialize.invoice_json, limit, offset)


@bp.get("/peds/invoices/<invoice_id>")
def read_invoice(invoice_id):
    begin(INVOICE_READ_ROLES)
    invoice = db.invoices.get(invoice_id)                              # RUNG 3 p8
    if invoice is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_family_owner(invoice["family_id"])                         # RUNG 7 p19
    return object_response(serialize.invoice_json(invoice), 200)


@bp.post("/peds/invoices/<invoice_id>/issue")
def issue_invoice(invoice_id):
    begin(INVOICE_WRITE_ROLES)
    invoice = db.invoices.get(invoice_id)                              # RUNG 3 p8
    if invoice is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    if invoice["status"] != "DRAFT":                                   # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT invoice can be issued.")
    if not invoice["lines"]:
        raise ApiError("ERR_INVALID_STATE", "An invoice with no lines cannot be issued.")

    invoice["status"] = "ISSUED"
    invoice["issued_date"] = db.today()
    invoice["due_date"] = add_days(invoice["issued_date"], C.INVOICE_DUE_DAYS)
    touch(invoice, g.touched)
    return object_response(serialize.invoice_json(invoice), 200)


@bp.post("/peds/invoices/<invoice_id>/pay")
def pay_invoice(invoice_id):
    begin(INVOICE_WRITE_ROLES)
    invoice = db.invoices.get(invoice_id)                              # RUNG 3 p8
    if invoice is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    body = V.json_body()
    amount_paid_cents = V.req_int(body, "amount_paid_cents")           # RUNG 4 p9

    if invoice["status"] != "ISSUED":                                  # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED invoice can be paid.")
    if amount_paid_cents != invoice["total_cents"]:                    # RUNG 17 p38
        raise ApiError("ERR_VALIDATION", "Settlement must be exact.")

    invoice["status"] = "PAID"
    invoice["amount_paid_cents"] = amount_paid_cents
    invoice["paid_date"] = db.today()
    touch(invoice, g.touched)

    # Payment is the activation gate for the whole practice.
    for membership in db.memberships.values():
        if membership["family_id"] != invoice["family_id"]:
            continue
        if membership["status"] != "PENDING_ACTIVATION":
            continue
        if (
            invoice["cycle_start_date"]
            <= membership["start_date"]
            <= invoice["cycle_end_date"]
        ):
            membership["status"] = "ACTIVE"
            touch(membership, g.touched)

    return object_response(serialize.invoice_json(invoice), 200)
