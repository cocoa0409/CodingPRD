"""ContaminationReport endpoints: file, list, adjudicate, dismiss."""
from flask import Blueprint

from db import store, new_record, touch, now_dt, now_iso
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import check_fields, get_body, paginate

bp = Blueprint("reports", __name__)


@bp.route("/weight-tickets/<tid>/contamination-reports", methods=["POST"])
@endpoint(["Inspector"])
def file_report(user_id, role, tid):
    ticket = store.tickets.get(tid)
    body = get_body()
    check_fields(body, {
        "severity": (("enum", ("MINOR", "MAJOR", "SEVERE")), True),
        "notes": ("str", False),
    })
    if ticket is None:
        fail("ERR_NOT_FOUND", "WeightTicket not found: %s" % tid)
    # at most one OPEN report per ticket (catalogued under ERR_INVALID_REQUEST)
    if domain.open_report_on_ticket(tid) is not None:
        fail("ERR_INVALID_REQUEST", "An OPEN report already exists for this ticket")
    # p8: report window — ticket CERTIFIED and no SETTLED credit
    if ticket["status"] != "CERTIFIED" or domain.settled_credit_on_ticket(tid) is not None:
        fail("ERR_REPORT_WINDOW_CLOSED", "Report window is closed for this ticket")
    rec = new_record()
    rec.update({
        "ticket_id": tid,
        "severity": body["severity"],
        "notes": body.get("notes", ""),
        "status": "OPEN",
        "outcome": None,
        "reported_by": user_id,
        "adjudicated_at": None,
        "_adjudicated_at": None,
    })
    store.reports[rec["id"]] = rec
    return success(domain.report_view(rec), code=201)


@bp.route("/weight-tickets/<tid>/contamination-reports", methods=["GET"])
@endpoint(["ZoneOperator", "Inspector"])
def list_reports(user_id, role, tid):
    domain.get_or_404(store.tickets, tid, "WeightTicket")
    items = [r for r in store.reports.values() if r["ticket_id"] == tid]
    page, meta = paginate(items)
    return success([domain.report_view(r) for r in page], response_type="array",
                   pagination=meta)


@bp.route("/contamination-reports/<rid>/adjudicate", methods=["POST"])
@endpoint(["ZoneOperator"])
def adjudicate_report(user_id, role, rid):
    report = store.reports.get(rid)
    body = get_body()
    check_fields(body, {"outcome": (("enum", ("UPHELD", "OVERTURNED")), True)})
    if report is None:
        fail("ERR_NOT_FOUND", "ContaminationReport not found: %s" % rid)
    if report["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Report must be OPEN to adjudicate")
    report["status"] = "ADJUDICATED"
    report["outcome"] = body["outcome"]
    report["adjudicated_at"] = now_iso()
    report["_adjudicated_at"] = now_dt()
    touch(report)
    if body["outcome"] == "UPHELD":
        now = now_dt()
        ticket = store.tickets.get(report["ticket_id"])
        severity = report["severity"]
        if ticket is not None:
            domain.recompute_ticket_severity(ticket)
            # SEVERE on a CERTIFIED ticket: quarantine cascade
            if severity == "SEVERE" and ticket["status"] == "CERTIFIED":
                domain.quarantine_ticket(ticket)
            if severity in ("MAJOR", "SEVERE"):
                # resident strike on pickup-sourced tickets
                if ticket["source_type"] == "PICKUP_REQUEST":
                    pickup = store.pickups.get(ticket["source_id"])
                    resident = store.residents.get(pickup["resident_id"]) if pickup else None
                    if resident is not None:
                        domain.apply_strike(resident)
                # score recompute for partners holding ACCEPTED/COMPLETED assignments
                partner_ids = {a["partner_id"] for a in store.assignments.values()
                               if a["ticket_id"] == ticket["id"]
                               and a["status"] in ("ACCEPTED", "COMPLETED")}
                for pid in partner_ids:
                    partner = store.partners.get(pid)
                    if partner is not None:
                        domain.apply_partner_score_transitions(partner, now)
    return success(domain.report_view(report))


@bp.route("/contamination-reports/<rid>/dismiss", methods=["POST"])
@endpoint(["ZoneOperator"])
def dismiss_report(user_id, role, rid):
    report = store.reports.get(rid)
    get_body()
    if report is None:
        fail("ERR_NOT_FOUND", "ContaminationReport not found: %s" % rid)
    if report["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Report must be OPEN to dismiss")
    report["status"] = "DISMISSED"
    touch(report)
    return success(domain.report_view(report))
