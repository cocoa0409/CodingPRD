"""CounterfeitReport routes and the seizure cascade / compensating reversal."""

from flask import Blueprint

import calc
from core import (
    REPORT_STATUSES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_VAULT_MANAGER,
    authorize,
    body_json,
    clock_now,
    db,
    fail,
    fmt_dt,
    get_lot,
    get_pagination,
    get_report,
    make_row,
    ordered,
    paginate,
    query_enum,
    query_str,
    req_int,
    req_str,
    respond,
    touch,
)
from serializers import report_out

bp = Blueprint("counterfeit", __name__)


@bp.post("/counterfeit-reports")
def create_report():
    authorize(ROLE_COMPLIANCE_OFFICER)
    body = body_json()
    fitness_lot_id = req_str(body, "fitness_lot_id")
    serial_number = req_str(body, "serial_number")
    denomination_cents = req_int(body, "denomination_cents", minimum=0)
    note_count = req_int(body, "note_count", minimum=0)

    get_lot(fitness_lot_id)

    row = make_row()
    row.update({
        "fitness_lot_id": fitness_lot_id,
        "serial_number": serial_number,
        "denomination_cents": denomination_cents,
        "note_count": note_count,
        "status": "DRAFT",
        "seized_face_value_cents": denomination_cents * note_count,
        "submitted_at": None,
        "case_number": None,
        "correction_note": None,
    })
    db.reports[row["id"]] = row
    return respond(report_out(row), 201)


@bp.get("/counterfeit-reports/<report_id>")
def read_report(report_id):
    authorize(ROLE_COMPLIANCE_OFFICER, ROLE_VAULT_MANAGER)
    return respond(report_out(get_report(report_id)))


@bp.get("/counterfeit-reports")
def list_reports():
    authorize(ROLE_COMPLIANCE_OFFICER, ROLE_VAULT_MANAGER)
    limit, offset = get_pagination()
    fitness_lot_id = query_str("fitness_lot_id")
    status = query_enum("status", REPORT_STATUSES)

    rows = ordered(db.reports.values())
    if fitness_lot_id is not None:
        rows = [r for r in rows if r["fitness_lot_id"] == fitness_lot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, report_out)


def _propagate_seizure(lot, signed_amount, incident_delta):
    """Shared by submit (+) and return-for-correction (-)."""
    session = db.sessions.get(lot["count_session_id"])
    bag = None
    if session is not None:
        session["seized_face_value_cents"] += signed_amount
        touch(session)
        bag = db.bags.get(session["sealed_bag_id"])
    if bag is not None:
        bag["seized_amount_cents"] += signed_amount
        calc.recompute_bag_settlement(bag)
        touch(bag)
        ticket = db.tickets.get(bag["deposit_ticket_id"])
        if ticket is not None:
            calc.recompute_ticket_counted_total(ticket)
            touch(ticket)
            account = db.customers.get(ticket["customer_account_id"])
            if account is not None:
                account["counterfeit_incident_count"] += incident_delta
                calc.apply_settled_only_risk(account)
                touch(account)


@bp.post("/counterfeit-reports/<report_id>/submit")
def submit_report(report_id):
    authorize(ROLE_COMPLIANCE_OFFICER)
    report = get_report(report_id)

    if report["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Report is not in DRAFT.")

    lot = db.lots.get(report["fitness_lot_id"])
    if lot is None or lot["status"] != "PENDING_REVIEW":
        fail("ERR_INVALID_STATE", "The referenced lot is not in PENDING_REVIEW.")

    # ladder 20 - the filer's assertions must match the lot exactly
    if (report["denomination_cents"] != lot["denomination_cents"]
            or report["note_count"] != lot["note_count"]):
        fail("ERR_REPORT_LOT_MISMATCH", "The report does not agree with its fitness lot.")

    report["status"] = "SUBMITTED"
    report["submitted_at"] = fmt_dt(clock_now())
    touch(report)

    lot["status"] = "SEIZED"
    touch(lot)

    _propagate_seizure(lot, lot["face_value_cents"], 1)
    return respond(report_out(report))


@bp.post("/counterfeit-reports/<report_id>/return-for-correction")
def return_report(report_id):
    authorize(ROLE_COMPLIANCE_OFFICER)
    body = body_json()
    correction_note = req_str(body, "correction_note")
    report = get_report(report_id)

    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Report is not in SUBMITTED.")

    report["status"] = "DRAFT"
    report["correction_note"] = correction_note
    report["submitted_at"] = None
    touch(report)

    lot = db.lots.get(report["fitness_lot_id"])
    if lot is not None:
        lot["status"] = "PENDING_REVIEW"
        touch(lot)
        _propagate_seizure(lot, -lot["face_value_cents"], -1)
    return respond(report_out(report))


@bp.post("/counterfeit-reports/<report_id>/acknowledge")
def acknowledge_report(report_id):
    authorize(ROLE_COMPLIANCE_OFFICER)
    body = body_json()
    case_number = req_str(body, "case_number")
    report = get_report(report_id)

    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Report is not in SUBMITTED.")

    report["case_number"] = case_number
    report["status"] = "ACKNOWLEDGED"
    touch(report)
    return respond(report_out(report))
