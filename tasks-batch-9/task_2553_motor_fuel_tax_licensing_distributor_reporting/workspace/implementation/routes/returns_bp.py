"""Monthly returns, schedules, lines, filing and amendments (PRD 3.4 / 3.5)."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, LICENSEE_AGENT, LICENSING_OFFICER,
                        RETURNS_EXAMINER, TAX_SUPERVISOR)
from services import calc, cascade, derive

bp = Blueprint("returns", __name__, url_prefix="/mft")

READ_ROLES = (LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR,
              AUDIT_MANAGER, LICENSEE_AGENT)
WRITE_ROLES = (LICENSEE_AGENT, RETURNS_EXAMINER)


@bp.post("/returns")
def open_return():
    user_id, role = middleware.require(*WRITE_ROLES)
    body = shape.body()
    candidate = body.get("licensee_id")
    if isinstance(candidate, str) and candidate:
        middleware.scope_guard(user_id, role, candidate)
    licensee_id = shape.req_id(body, "licensee_id")
    period_month = shape.req_month(body, "period_month")

    licensee = helpers.body_licensee(licensee_id)
    if licensee["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_REVOKED")

    for existing in db.returns.values():
        if (existing["licensee_id"] == licensee_id
                and existing["period_month"] == period_month
                and existing["filing_status"] != "SUPERSEDED"):
            raise ApiError("ERR_DUPLICATE_RETURN_PERIOD")

    row = new_return_row(licensee_id, period_month)
    db.returns[row["id"]] = row
    return response.object_response(derive.monthly_return_json(row), 201)


def new_return_row(licensee_id, period_month, amends_return_id=None,
                   amendment_sequence=0):
    row = db.base_row()
    row.update({
        "licensee_id": licensee_id,
        "period_month": period_month,
        "amends_return_id": amends_return_id,
        "amendment_sequence": amendment_sequence,
        "amendment_count": 0,
        "filing_status": "DRAFT",
        "match_status": "NOT_MATCHED",
        "attest_name": None,
        "filed_at": None,
        "due_at": db.period_due_at(period_month),
        "days_late": 0,
        "taxable_gallons_total": calc.ZERO,
        "tax_due_cents": 0,
        "interest_cents": 0,
        "penalty_cents": 0,
        "total_remittance_cents": 0,
        "amendment_delta_cents": 0,
    })
    return row


@bp.get("/returns/<return_id>")
def read_return(return_id):
    user_id, role = middleware.require(*READ_ROLES)
    row = helpers.ensure("return", helpers.peek(
        "return", return_id, user_id, role, helpers.owner_of_return))
    return response.object_response(derive.monthly_return_json(row))


@bp.get("/returns")
def list_returns():
    user_id, role = middleware.require(*READ_ROLES)
    rows = db.ordered(db.returns)
    rows = helpers.agent_narrow(rows, helpers.owner_of_return, user_id, role)
    rows = helpers.filter_by(rows, {
        "licensee_id": "licensee_id",
        "period_month": "period_month",
        "filing_status": "filing_status",
        "match_status": "match_status",
        "amends_return_id": "amends_return_id",
    })
    return response.list_response(rows, derive.monthly_return_json)


@bp.post("/returns/<return_id>/schedules")
def add_schedule(return_id):
    user_id, role = middleware.require(*WRITE_ROLES)
    peeked = helpers.peek("return", return_id, user_id, role,
                          helpers.owner_of_return)
    body = shape.body()
    schedule_code = shape.req_enum(body, "schedule_code", calc.SCHEDULE_CODES)
    product_code = shape.req_enum(body, "product_code", calc.PRODUCT_CODES)
    total_gallons = shape.req_gallons(body, "total_gallons", ge=calc.ZERO)
    parent = helpers.ensure("return", peeked)

    if parent["filing_status"] != "DRAFT":
        raise ApiError("ERR_RETURN_ALREADY_FILED")

    if schedule_code == "SCH_10_DYED_SALES":
        if product_code != "DYED_DIESEL":
            raise ApiError("ERR_SCHEDULE_PRODUCT_NOT_ALLOWED")
    elif product_code == "DYED_DIESEL":
        raise ApiError("ERR_SCHEDULE_PRODUCT_NOT_ALLOWED")

    for existing in derive.return_schedules(parent["id"]):
        if (existing["schedule_code"] == schedule_code
                and existing["product_code"] == product_code):
            raise ApiError("ERR_DUPLICATE_SCHEDULE")

    row = db.base_row()
    row.update({
        "return_id": parent["id"],
        "schedule_code": schedule_code,
        "product_code": product_code,
        "total_gallons": total_gallons,
        "line_count": 0,
    })
    db.schedules[row["id"]] = row
    return response.object_response(derive.schedule_json(row), 201)


@bp.get("/returns/<return_id>/schedules")
def list_return_schedules(return_id):
    user_id, role = middleware.require(*READ_ROLES)
    peeked = helpers.peek("return", return_id, user_id, role,
                          helpers.owner_of_return)
    response.pagination()
    parent = helpers.ensure("return", peeked)
    rows = derive.return_schedules(parent["id"])
    rows = helpers.filter_by(rows, {"schedule_code": "schedule_code"})
    return response.list_response(rows, derive.schedule_json)


@bp.get("/schedules/<schedule_id>")
def read_schedule(schedule_id):
    user_id, role = middleware.require(*READ_ROLES)
    row = helpers.ensure("schedule", helpers.peek(
        "schedule", schedule_id, user_id, role, helpers.owner_of_schedule))
    return response.object_response(derive.schedule_json(row))


@bp.post("/schedules/<schedule_id>/lines")
def add_line(schedule_id):
    user_id, role = middleware.require(*WRITE_ROLES)
    peeked = helpers.peek("schedule", schedule_id, user_id, role,
                          helpers.owner_of_schedule)
    body = shape.body()
    counterparty_id = shape.req_id(body, "counterparty_licensee_id")
    certificate_id = shape.opt_id(body, "exemption_certificate_id")
    transaction_type = shape.req_enum(body, "transaction_type",
                                      calc.TRANSACTION_TYPES)
    gallons = shape.req_gallons(body, "gallons", gt=calc.ZERO)
    document_date = shape.req_date(body, "document_date")
    bol = shape.req_str(body, "bill_of_lading_number")

    parent_return = None
    if peeked is not None:
        parent_return = db.returns.get(peeked["return_id"])
        if parent_return is not None and not db.date_in_month(
                document_date, parent_return["period_month"]):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "document_date must fall inside the return's period_month.")

    schedule = helpers.ensure("schedule", peeked)
    counterparty = helpers.body_licensee(counterparty_id)
    certificate = (helpers.body_ref("certificate", certificate_id)
                   if certificate_id else None)

    if parent_return["filing_status"] != "DRAFT":
        raise ApiError("ERR_RETURN_ALREADY_FILED")

    if certificate is not None:
        if certificate["purchaser_licensee_id"] != counterparty_id:
            raise ApiError("ERR_CERTIFICATE_HOLDER_MISMATCH")
        if not cascade.cert_active_on_date(certificate, document_date):
            raise ApiError("ERR_CERTIFICATE_NOT_VALID_ON_DATE")
        if (schedule["product_code"]
                not in calc.CERT_PRODUCT_SET[certificate["exemption_type"]]):
            raise ApiError("ERR_EXEMPTION_PRODUCT_MISMATCH")

    if (schedule["schedule_code"] == "SCH_10_DYED_SALES"
            and counterparty["retail_channel"] == "HIGHWAY"):
        raise ApiError("ERR_DYED_FUEL_ON_ROAD_PROHIBITED")
    if (schedule["product_code"] == "DYED_DIESEL"
            and schedule["schedule_code"] in ("SCH_2_RECEIVED_TAX_UNPAID",
                                              "SCH_5_DELIVERED_TAX_COLLECTED",
                                              "SCH_6_EXEMPT_SALES")):
        raise ApiError("ERR_DYED_FUEL_ON_ROAD_PROHIBITED")

    if schedule["schedule_code"] in ("SCH_1_RECEIVED_TAX_PAID",
                                    "SCH_2_RECEIVED_TAX_UNPAID"):
        if counterparty["license_type"] not in ("SUPPLIER", "DISTRIBUTOR"):
            raise ApiError("ERR_COUNTERPARTY_TYPE_INVALID")
    if schedule["schedule_code"] == "SCH_7_EXPORTS":
        if counterparty["mailing_state"] == calc.HOME_STATE_CODE:
            raise ApiError("ERR_COUNTERPARTY_TYPE_INVALID")

    for other in db.schedule_lines.values():
        if (other["counterparty_licensee_id"] == counterparty_id
                and other["bill_of_lading_number"] == bol
                and derive.line_return_id(other) == parent_return["id"]):
            raise ApiError("ERR_DUPLICATE_BOL")

    row = db.base_row(versioned=False)
    row.update({
        "schedule_id": schedule["id"],
        "counterparty_licensee_id": counterparty_id,
        "exemption_certificate_id": certificate_id,
        "transaction_type": transaction_type,
        "gallons": gallons,
        "document_date": document_date,
        "bill_of_lading_number": bol,
    })
    db.schedule_lines[row["id"]] = row
    schedule["line_count"] += 1
    db.touch(schedule)
    return response.object_response(derive.schedule_line_json(row), 201)


@bp.get("/schedules/<schedule_id>/lines")
def list_schedule_lines(schedule_id):
    user_id, role = middleware.require(*READ_ROLES)
    peeked = helpers.peek("schedule", schedule_id, user_id, role,
                          helpers.owner_of_schedule)
    response.pagination()
    schedule = helpers.ensure("schedule", peeked)
    rows = derive.schedule_lines_of(schedule["id"])
    return response.list_response(rows, derive.schedule_line_json)


@bp.get("/schedule-lines/<line_id>")
def read_line(line_id):
    user_id, role = middleware.require(*READ_ROLES)
    row = helpers.ensure("schedule_line", helpers.peek(
        "schedule_line", line_id, user_id, role, helpers.owner_of_line))
    return response.object_response(derive.schedule_line_json(row))


@bp.get("/schedule-lines")
def list_lines():
    user_id, role = middleware.require(*READ_ROLES)
    rows = db.ordered(db.schedule_lines)
    rows = helpers.agent_narrow(rows, helpers.owner_of_line, user_id, role)
    rows = helpers.filter_by(rows, {
        "schedule_id": "schedule_id",
        "counterparty_licensee_id": "counterparty_licensee_id",
        "exemption_certificate_id": "exemption_certificate_id",
        "transaction_type": "transaction_type",
    })
    return response.list_response(rows, derive.schedule_line_json)


def _compute_tax(return_row):
    """Per-product: SCH_2 minus SCH_6 minus SCH_7, floored at zero, one
    rounding per product (PRD 3.5)."""
    return_id = return_row["id"]
    taxable_total = calc.ZERO
    tax_due_cents = 0
    for product in calc.PRODUCT_CODES:
        received = helpers.product_schedule_gallons(
            return_id, "SCH_2_RECEIVED_TAX_UNPAID", product)
        exempt = helpers.product_schedule_gallons(
            return_id, "SCH_6_EXEMPT_SALES", product)
        exports = helpers.product_schedule_gallons(
            return_id, "SCH_7_EXPORTS", product)
        net = calc.g2(received - exempt - exports)
        if net < calc.ZERO:
            net = calc.ZERO
        taxable_total += net
        tax_due_cents += calc.rate_cents(net, product)
    return calc.g2(taxable_total), tax_due_cents


@bp.post("/returns/<return_id>/file")
def file_return(return_id):
    user_id, role = middleware.require(*WRITE_ROLES)
    peeked = helpers.peek("return", return_id, user_id, role,
                          helpers.owner_of_return)
    body = shape.body()
    attest_name = shape.req_str(body, "attest_name")
    row = helpers.ensure("return", peeked)
    licensee = db.licensees.get(row["licensee_id"])

    # Seven conditions, in this order.
    if licensee is not None and licensee["status"] == "REVOKED":
        raise ApiError("ERR_LICENSEE_REVOKED")
    if row["filing_status"] != "DRAFT":
        raise ApiError("ERR_RETURN_ALREADY_FILED")
    if not db.period_is_closed(row["period_month"]):
        raise ApiError("ERR_PERIOD_NOT_CLOSED")

    schedules = derive.return_schedules(row["id"])
    for schedule in schedules:
        if schedule["schedule_code"] not in ("SCH_6_EXEMPT_SALES",
                                             "SCH_7_EXPORTS"):
            continue
        for line in derive.schedule_lines_of(schedule["id"]):
            cert_id = line["exemption_certificate_id"]
            cert = db.certificates.get(cert_id) if cert_id else None
            if cert is None or not cascade.cert_active_on_date(
                    cert, line["document_date"]):
                raise ApiError("ERR_CERTIFICATE_NOT_VALID_ON_DATE")

    for schedule in schedules:
        lines = derive.schedule_lines_of(schedule["id"])
        if derive.schedule_gallons_sum(schedule["id"]) != calc.g2(
                schedule["total_gallons"]):
            raise ApiError("ERR_SCHEDULE_TOTALS_MISMATCH")
        if schedule["line_count"] != len(lines):
            raise ApiError("ERR_SCHEDULE_TOTALS_MISMATCH")

    if licensee is not None and licensee["license_type"] in (
            "DISTRIBUTOR", "BLENDER", "RETAILER"):
        for product in calc.PRODUCT_CODES:
            outbound = calc.ZERO
            inbound = calc.ZERO
            for schedule in schedules:
                if schedule["product_code"] != product:
                    continue
                if schedule["schedule_code"] in calc.OUTBOUND_SCHEDULES:
                    outbound += schedule["total_gallons"]
                elif schedule["schedule_code"] in calc.INBOUND_SCHEDULES:
                    inbound += schedule["total_gallons"]
            if calc.g2(outbound) > calc.g2(inbound):
                raise ApiError("ERR_SCHEDULE_TOTALS_MISMATCH")

    if not schedules:
        raise ApiError("ERR_MISSING_REQUIRED_SCHEDULE")
    if licensee is not None and licensee["license_type"] == "SUPPLIER":
        if not any(s["schedule_code"] == "SCH_5_DELIVERED_TAX_COLLECTED"
                   for s in schedules):
            raise ApiError("ERR_MISSING_REQUIRED_SCHEDULE")

    taxable_total, tax_due_cents = _compute_tax(row)
    filed_at = db.now()
    days_late = calc.days_late_for(filed_at, row["due_at"])

    amended = None
    if row["amends_return_id"]:
        amended = db.returns.get(row["amends_return_id"])
    if amended is not None and tax_due_cents <= int(amended["tax_due_cents"]):
        # A corrective amendment cannot manufacture new penalty.
        interest_cents = int(amended["interest_cents"])
        penalty_cents = int(amended["penalty_cents"])
    else:
        interest_cents = calc.interest_for(tax_due_cents, days_late)
        penalty_cents = calc.penalty_for(tax_due_cents, interest_cents, days_late)
    total_remittance = tax_due_cents + interest_cents + penalty_cents
    delta_cents = 0
    if amended is not None:
        delta_cents = total_remittance - int(amended["total_remittance_cents"])

    row["filing_status"] = "FILED"
    row["attest_name"] = attest_name
    row["filed_at"] = filed_at
    row["days_late"] = days_late
    row["taxable_gallons_total"] = taxable_total
    row["tax_due_cents"] = tax_due_cents
    row["interest_cents"] = interest_cents
    row["penalty_cents"] = penalty_cents
    row["total_remittance_cents"] = total_remittance
    row["amendment_delta_cents"] = delta_cents
    db.touch(row)

    if amended is None:
        cascade.post_ledger(row["licensee_id"], "RETURN_TAX", tax_due_cents,
                            "MonthlyReturn", row["id"],
                            "Tax due on return for %s" % row["period_month"])
        if interest_cents > 0:
            cascade.post_ledger(row["licensee_id"], "INTEREST", interest_cents,
                                "MonthlyReturn", row["id"],
                                "Interest on late return for %s"
                                % row["period_month"])
        if penalty_cents > 0:
            cascade.post_ledger(row["licensee_id"], "PENALTY", penalty_cents,
                                "MonthlyReturn", row["id"],
                                "Penalty on late return for %s"
                                % row["period_month"])
    else:
        cascade.post_ledger(row["licensee_id"], "RETURN_TAX_ADJUSTMENT",
                            delta_cents, "MonthlyReturn", row["id"],
                            "Amendment adjustment for %s" % row["period_month"])
        amended["filing_status"] = "SUPERSEDED"
        db.touch(amended)

    return response.object_response(derive.monthly_return_json(row))


@bp.post("/returns/<return_id>/amendments")
def open_amendment(return_id):
    user_id, role = middleware.require(*WRITE_ROLES)
    peeked = helpers.peek("return", return_id, user_id, role,
                          helpers.owner_of_return)
    body = shape.body()
    expected_version = shape.req_int(body, "expected_return_version")
    shape.req_str(body, "reason")
    target = helpers.ensure("return", peeked)

    if expected_version != target["version"]:
        raise ApiError("ERR_STALE_RETURN_VERSION")
    if target["filing_status"] != "FILED":
        raise ApiError("ERR_RETURN_NOT_FILED")

    for sibling in db.returns.values():
        if sibling["id"] == target["id"]:
            continue
        if (sibling["licensee_id"] != target["licensee_id"]
                or sibling["period_month"] != target["period_month"]):
            continue
        if sibling["amends_return_id"] == target["id"]:
            raise ApiError("ERR_AMENDMENT_TARGET_INVALID")
        if (sibling["filing_status"] != "SUPERSEDED"
                and sibling["amendment_sequence"] > target["amendment_sequence"]):
            raise ApiError("ERR_AMENDMENT_TARGET_INVALID")

    row = new_return_row(target["licensee_id"], target["period_month"],
                         amends_return_id=target["id"],
                         amendment_sequence=target["amendment_sequence"] + 1)
    db.returns[row["id"]] = row
    target["amendment_count"] += 1
    db.touch(target)
    return response.object_response(derive.monthly_return_json(row), 201)
