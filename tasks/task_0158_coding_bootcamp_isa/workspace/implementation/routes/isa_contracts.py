"""ISA contract reads, dual-view projection, and nested child lists (PRD §3.11)."""
from flask import Blueprint, request

from db import db
from middleware import require_role
from response import success
from services import serialize, calc
from services.common import parse_pagination, sort_by_created, paginate, lookup
from services.derive import recompute_isa_ledger, latest_income_report

bp = Blueprint("isa_contracts", __name__)


@bp.get("/isa-contracts/<cid>")
def get_isa_contract(cid):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    c = lookup(db.isa_contracts, cid)
    return success(serialize.isa_contract_view(c))


@bp.get("/isa-contracts")
def list_isa_contracts():
    require_role("ServicingOfficer", "ComplianceOfficer")
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    rows = list(db.isa_contracts.values())
    if enrollment_id is not None:
        rows = [c for c in rows if c["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.isa_contract_view(c) for c in window], pagination=pg)


@bp.get("/isa-contracts/<cid>/projection")
def projection(cid):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    c = lookup(db.isa_contracts, cid)
    recompute_isa_ledger(c)
    variant = request.args.get("variant")
    view = serialize.isa_contract_view(c)
    # default response carries both amount_paid_cents (chronological) and
    # projected_payoff_cents (forward-looking). The variant selector picks the
    # headline projected_payoff_cents value (PRD §3.11).
    if variant in ("CHRONOLOGICAL", "ACTUAL"):
        view["projected_payoff_cents"] = c["_amount_paid_cents"]
    elif variant == "PROJECTED" or variant is None:
        latest = latest_income_report(c["id"])
        view["projected_payoff_cents"] = calc.projected_payoff(c, latest)
    return success(view)


@bp.get("/isa-contracts/<cid>/payments")
def list_contract_payments(cid):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    limit, offset = parse_pagination()
    lookup(db.isa_contracts, cid)
    rows = [p for p in db.payments.values() if p["isa_contract_id"] == cid]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.payment_view(p) for p in window], pagination=pg)


@bp.get("/isa-contracts/<cid>/income-reports")
def list_contract_income_reports(cid):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    limit, offset = parse_pagination()
    lookup(db.isa_contracts, cid)
    rows = [r for r in db.income_reports.values() if r["isa_contract_id"] == cid]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.income_report_view(r) for r in window], pagination=pg)


@bp.get("/isa-contracts/<cid>/deferment-requests")
def list_contract_deferments(cid):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    limit, offset = parse_pagination()
    lookup(db.isa_contracts, cid)
    rows = [d for d in db.deferment_requests.values() if d["isa_contract_id"] == cid]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.deferment_view(d) for d in window], pagination=pg)
