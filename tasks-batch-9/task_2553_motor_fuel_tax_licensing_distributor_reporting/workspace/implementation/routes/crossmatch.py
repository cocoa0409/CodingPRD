"""Cross-match runs, discrepancies, the inquiry cycle and disposition (PRD 3.6)."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, LICENSEE_AGENT, RETURNS_EXAMINER,
                        TAX_SUPERVISOR)
from services import calc, cascade, derive

bp = Blueprint("crossmatch", __name__, url_prefix="/mft")

RUN_WRITE_ROLES = (RETURNS_EXAMINER, TAX_SUPERVISOR)
RUN_READ_ROLES = (RETURNS_EXAMINER, TAX_SUPERVISOR, AUDIT_MANAGER)
DISCREPANCY_READ_ROLES = (RETURNS_EXAMINER, TAX_SUPERVISOR, AUDIT_MANAGER,
                          LICENSEE_AGENT)

TAX_COLLECTED = "SCH_5_DELIVERED_TAX_COLLECTED"
TAX_PAID = "SCH_1_RECEIVED_TAX_PAID"


def _supplier_cells(supplier_return):
    """Distinct (counterparty, product) cells of a supplier's SCH_5 block.

    Ordered by the counterparty's ascending created_at and then by product in
    the declared product order -- never by row identifier (PRD 3.6).
    """
    cells = {}
    for schedule in derive.return_schedules(supplier_return["id"]):
        if schedule["schedule_code"] != TAX_COLLECTED:
            continue
        product = schedule["product_code"]
        for line in derive.schedule_lines_of(schedule["id"]):
            key = (line["counterparty_licensee_id"], product)
            cells[key] = cells.get(key, calc.ZERO) + line["gallons"]

    def cell_key(key):
        counterparty = db.licensees.get(key[0])
        if counterparty is None:
            rank = ("", 0)
        else:
            rank = (counterparty["created_at"], counterparty["_seq"])
        return (rank, calc.PRODUCT_CODES.index(key[1]))

    return [(key, calc.g2(cells[key])) for key in sorted(cells, key=cell_key)]


def _distributor_gallons(purchaser_return, supplier_id, product):
    total = calc.ZERO
    for schedule in derive.return_schedules(purchaser_return["id"]):
        if (schedule["schedule_code"] != TAX_PAID
                or schedule["product_code"] != product):
            continue
        for line in derive.schedule_lines_of(schedule["id"]):
            if line["counterparty_licensee_id"] == supplier_id:
                total += line["gallons"]
    return calc.g2(total)


def _execute_run(run, user_id):
    period = run["period_month"]
    filed = [r for r in db.ordered(db.returns)
             if r["filing_status"] == "FILED" and r["period_month"] == period]
    filed_by_licensee = {}
    for row in filed:
        filed_by_licensee[row["licensee_id"]] = row

    supplier_rows = []
    for row in filed:
        has_sales = any(s["schedule_code"] == TAX_COLLECTED
                        for s in derive.return_schedules(row["id"]))
        licensee = db.licensees.get(row["licensee_id"])
        if has_sales and licensee is not None:
            supplier_rows.append(licensee)
    supplier_rows = db.sort_rows(supplier_rows)

    involved = set()
    for supplier in supplier_rows:
        supplier_return = filed_by_licensee[supplier["id"]]
        for (counterparty_id, product), supplier_gallons in _supplier_cells(
                supplier_return):
            run["matched_cells_count"] += 1
            purchaser_return = filed_by_licensee.get(counterparty_id)
            if purchaser_return is None:
                distributor_gallons = calc.ZERO
                direction = "MISSING_COUNTERPARTY_RETURN"
                distributor_return_id = None
            else:
                distributor_gallons = _distributor_gallons(
                    purchaser_return, supplier["id"], product)
                direction = None
                distributor_return_id = purchaser_return["id"]
            variance = calc.g2(supplier_gallons - distributor_gallons)
            if abs(variance) <= run["tolerance_gallons"]:
                continue
            if direction is None:
                direction = ("UNREPORTED_BY_PURCHASER" if variance > calc.ZERO
                             else "OVERSTATED_BY_PURCHASER")

            row = db.base_row()
            row.update({
                "run_id": run["id"],
                "supplier_licensee_id": supplier["id"],
                "distributor_licensee_id": counterparty_id,
                "supplier_return_id": supplier_return["id"],
                "distributor_return_id": distributor_return_id,
                "product_code": product,
                "supplier_gallons": supplier_gallons,
                "distributor_gallons": distributor_gallons,
                "variance_gallons": variance,
                "direction": direction,
                "status": "OPEN",
                "inquiry_round": 0,
                "last_question": None,
                "last_explanation": None,
                "response_due_date": None,
            })
            db.discrepancies[row["id"]] = row
            run["discrepancy_count"] += 1
            involved.add(supplier["id"])
            involved.add(counterparty_id)
            if direction == "UNREPORTED_BY_PURCHASER":
                run["gross_unreported_gallons_total"] = calc.g2(
                    run["gross_unreported_gallons_total"] + variance)
                if variance >= calc.AUTO_ESCALATION_GALLONS:
                    _auto_escalate(run, row, period, user_id)

    # Every filed return of the period is stamped once the cells are walked.
    for row in filed:
        row["match_status"] = ("MATCH_VARIANCE" if row["licensee_id"] in involved
                               else "MATCH_CLEAN")
        db.touch(row)


def _auto_escalate(run, discrepancy, period, user_id):
    """A batch run survives an overlap and keeps going (PRD 3.6)."""
    subject_id = cascade.escalation_subject_id(discrepancy)
    if cascade.overlapping_open_case(subject_id, period, period) is not None:
        run["escalation_skipped_count"] += 1
        return
    discrepancy["status"] = "ESCALATED_TO_AUDIT"
    run["escalated_count"] += 1
    cascade.create_audit_case(subject_id, "CROSS_MATCH_ESCALATION",
                              "VARIANCE_WEIGHTED", 0, period, period, user_id,
                              source_discrepancy_id=discrepancy["id"])


@bp.post("/cross-match-runs")
def create_run():
    user_id, role = middleware.require(*RUN_WRITE_ROLES)
    body = shape.body()
    period_month = shape.req_month(body, "period_month")
    tolerance = shape.opt_gallons(body, "tolerance_gallons", ge=calc.ZERO,
                                 default=calc.DEFAULT_TOLERANCE_GALLONS)

    if not db.period_is_closed(period_month):
        raise ApiError("ERR_PERIOD_NOT_CLOSED")
    for existing in db.cross_match_runs.values():
        if existing["period_month"] == period_month:
            raise ApiError("ERR_DUPLICATE_MATCH_RUN")

    run = db.base_row()
    run.update({
        "period_month": period_month,
        "run_status": "COMPLETED",
        "tolerance_gallons": tolerance,
        "matched_cells_count": 0,
        "discrepancy_count": 0,
        "gross_unreported_gallons_total": calc.ZERO,
        "escalated_count": 0,
        "escalation_skipped_count": 0,
    })
    db.cross_match_runs[run["id"]] = run
    _execute_run(run, user_id)
    return response.object_response(derive.cross_match_run_json(run), 201)


@bp.get("/cross-match-runs/<run_id>")
def read_run(run_id):
    middleware.require(*RUN_READ_ROLES)
    row = helpers.find("cross_match_run", run_id)
    return response.object_response(derive.cross_match_run_json(row))


@bp.get("/cross-match-runs")
def list_runs():
    middleware.require(*RUN_READ_ROLES)
    rows = db.ordered(db.cross_match_runs)
    rows = helpers.filter_by(rows, {
        "period_month": "period_month",
        "run_status": "run_status",
    })
    return response.list_response(rows, derive.cross_match_run_json)


@bp.get("/discrepancies/<discrepancy_id>")
def read_discrepancy(discrepancy_id):
    user_id, role = middleware.require(*DISCREPANCY_READ_ROLES)
    row = helpers.ensure("discrepancy", helpers.peek(
        "discrepancy", discrepancy_id, user_id, role,
        helpers.owner_of_discrepancy))
    return response.object_response(derive.discrepancy_json(row))


@bp.get("/discrepancies")
def list_discrepancies():
    user_id, role = middleware.require(*DISCREPANCY_READ_ROLES)
    rows = db.ordered(db.discrepancies)
    rows = helpers.agent_narrow(rows, helpers.owner_of_discrepancy, user_id, role)
    rows = helpers.filter_by(rows, {
        "run_id": "run_id",
        "supplier_licensee_id": "supplier_licensee_id",
        "distributor_licensee_id": "distributor_licensee_id",
        "supplier_return_id": "supplier_return_id",
        "distributor_return_id": "distributor_return_id",
        "product_code": "product_code",
        "status": "status",
        "direction": "direction",
    })
    return response.list_response(rows, derive.discrepancy_json)


@bp.post("/discrepancies/<discrepancy_id>/inquiries")
def send_inquiry(discrepancy_id):
    user_id, role = middleware.require(RETURNS_EXAMINER)
    peeked = helpers.peek("discrepancy", discrepancy_id, user_id, role,
                          helpers.owner_of_discrepancy)
    body = shape.body()
    question = shape.req_str(body, "question")
    due_date = shape.req_date(body, "response_due_date")
    row = helpers.ensure("discrepancy", peeked)

    if row["status"] not in ("OPEN", "RESPONSE_RECEIVED"):
        raise ApiError("ERR_DISCREPANCY_STATE_INVALID")
    if row["inquiry_round"] >= calc.MAX_INQUIRY_ROUNDS:
        raise ApiError("ERR_INQUIRY_ROUND_LIMIT")

    row["status"] = "INQUIRY_SENT"
    row["inquiry_round"] += 1
    row["last_question"] = question
    row["response_due_date"] = due_date
    db.touch(row)
    return response.object_response(derive.discrepancy_json(row))


@bp.post("/discrepancies/<discrepancy_id>/responses")
def send_response(discrepancy_id):
    user_id, role = middleware.require(LICENSEE_AGENT)
    peeked = helpers.peek("discrepancy", discrepancy_id, user_id, role,
                          helpers.owner_of_discrepancy)
    body = shape.body()
    explanation = shape.req_str(body, "explanation")
    referenced_id = shape.opt_id(body, "referenced_return_id")
    row = helpers.ensure("discrepancy", peeked)
    referenced = (helpers.body_ref("return", referenced_id)
                  if referenced_id else None)

    if row["status"] != "INQUIRY_SENT":
        raise ApiError("ERR_DISCREPANCY_STATE_INVALID")
    if (referenced is not None
            and referenced["licensee_id"] != row["distributor_licensee_id"]):
        raise ApiError("ERR_RESPONSE_RETURN_MISMATCH")

    row["status"] = "RESPONSE_RECEIVED"
    row["last_explanation"] = explanation
    db.touch(row)
    return response.object_response(derive.discrepancy_json(row))


RESOLUTIONS = ["EXPLAINED", "WRITTEN_OFF", "ESCALATE_TO_AUDIT"]


@bp.post("/discrepancies/<discrepancy_id>/resolve")
def resolve_discrepancy(discrepancy_id):
    user_id, role = middleware.require(RETURNS_EXAMINER)
    peeked = helpers.peek("discrepancy", discrepancy_id, user_id, role,
                          helpers.owner_of_discrepancy)
    body = shape.body()
    resolution = shape.req_enum(body, "resolution", RESOLUTIONS)
    write_off_reason = shape.opt_str(body, "write_off_reason")
    row = helpers.ensure("discrepancy", peeked)

    if row["status"] not in calc.OPEN_DISCREPANCY_STATUSES:
        raise ApiError("ERR_DISCREPANCY_STATE_INVALID")

    if resolution == "EXPLAINED":
        # The gallons stay in the run's live unreported pool deliberately.
        row["status"] = "RESOLVED_EXPLAINED"
    elif resolution == "WRITTEN_OFF":
        if not write_off_reason:
            raise ApiError("ERR_WRITE_OFF_NOT_PERMITTED")
        if abs(row["variance_gallons"]) >= calc.AUTO_ESCALATION_GALLONS:
            raise ApiError("ERR_WRITE_OFF_NOT_PERMITTED")
        row["status"] = "WRITTEN_OFF"
        row["write_off_reason"] = write_off_reason
    else:
        run = db.cross_match_runs.get(row["run_id"])
        period = run["period_month"] if run is not None else None
        subject_id = cascade.escalation_subject_id(row)
        # A hand-driven escalation must tell the examiner why it cannot proceed.
        if cascade.overlapping_open_case(subject_id, period, period) is not None:
            raise ApiError("ERR_AUDIT_PERIOD_OVERLAP")
        row["status"] = "ESCALATED_TO_AUDIT"
        cascade.create_audit_case(subject_id, "CROSS_MATCH_ESCALATION",
                                 "VARIANCE_WEIGHTED", 0, period, period,
                                 user_id, source_discrepancy_id=row["id"])

    db.touch(row)

    # All three branches then look at the purchaser's return.
    return_id = row["distributor_return_id"]
    if return_id:
        purchaser_return = db.returns.get(return_id)
        still_open = any(
            other["distributor_return_id"] == return_id
            and other["status"] in calc.OPEN_DISCREPANCY_STATUSES
            for other in db.discrepancies.values())
        if (purchaser_return is not None and not still_open
                and purchaser_return["match_status"] == "MATCH_VARIANCE"):
            purchaser_return["match_status"] = "MATCH_RESOLVED"
            db.touch(purchaser_return)

    return response.object_response(derive.discrepancy_json(row))
