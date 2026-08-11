"""Contractors, contracts, DBE reports, invoices."""
from decimal import Decimal

from flask import Blueprint, g, request

from auth import ALL_ROLES, require
from domain import (contract_invoices, ledger_recompute, retainage_split,
                    ser_contract, ser_contractor, ser_dbe_report, ser_invoice)
from errors import ApiError, err_forbidden, err_invalid_state, err_validation
from store import DB
from util import (as_number, as_str, body, get_or_404, need, new_entity, r2,
                  respond, respond_list, touch)

bp = Blueprint("contracts", __name__)


# ---------------------------------------------------------------------------
# Contractors
# ---------------------------------------------------------------------------

@bp.route("/aip/contractors", methods=["POST"])
@require("SponsorStaff")
def create_contractor():
    b = body()
    if "sponsor_id" not in b or b["sponsor_id"] is None:
        raise err_validation("Missing required field: sponsor_id")
    sponsor = get_or_404(DB.sponsors, b["sponsor_id"], "Sponsor")
    name = as_str(need(b, "contractor_name"), "contractor_name")
    dbe = b.get("dbe_certified", False)
    if not isinstance(dbe, bool):
        raise err_validation("dbe_certified must be a boolean")
    c = new_entity()
    c.update({"sponsor_id": sponsor["id"], "contractor_name": name,
              "dbe_certified": dbe, "status": "REGISTERED"})
    DB.contractors[c["id"]] = c
    return respond(ser_contractor(c), 201)


@bp.route("/aip/contractors", methods=["GET"])
@require(*ALL_ROLES)
def list_contractors():
    items = list(DB.contractors.values())
    sponsor_id = request.args.get("sponsor_id")
    if sponsor_id is not None:
        items = [c for c in items if c["sponsor_id"] == sponsor_id]
    return respond_list(items, ser_contractor)


@bp.route("/aip/contractors/<contractorId>", methods=["GET"])
@require(*ALL_ROLES)
def get_contractor(contractorId):
    return respond(ser_contractor(
        get_or_404(DB.contractors, contractorId, "Contractor")))


@bp.route("/aip/contractors/<contractorId>/suspend", methods=["POST"])
@require("SponsorStaff")
def suspend_contractor(contractorId):
    c = get_or_404(DB.contractors, contractorId, "Contractor")
    if c["status"] != "REGISTERED":
        raise err_invalid_state("Only a REGISTERED contractor can be "
                                "suspended")
    c["status"] = "SUSPENDED"
    touch(c)
    return respond(ser_contractor(c))


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@bp.route("/aip/contracts", methods=["POST"])
@require("SponsorStaff")
def create_contract():
    b = body()
    for fk, entity in (("grant_id", "Grant"), ("cip_project_id", "CIPProject"),
                       ("contractor_id", "Contractor")):
        if fk not in b or b[fk] is None:
            raise err_validation(f"Missing required field: {fk}")
    grant = get_or_404(DB.grants, b["grant_id"], "Grant")
    project = get_or_404(DB.projects, b["cip_project_id"], "CIPProject")
    contractor = get_or_404(DB.contractors, b["contractor_id"], "Contractor")
    awarded = as_number(need(b, "awarded_value"), "awarded_value")
    if awarded <= 0:
        raise err_validation("awarded_value must be > 0")
    dbe_goal = as_number(need(b, "dbe_goal_pct"), "dbe_goal_pct")
    if not (Decimal("0") <= dbe_goal <= Decimal("100")):
        raise err_validation("dbe_goal_pct must be within [0, 100]")
    retainage = as_number(need(b, "retainage_pct"), "retainage_pct")
    if not (Decimal("0") <= retainage <= Decimal("0.20")):
        raise err_validation("retainage_pct must be within [0, 0.20]")
    # Cross-sponsor integrity, then suspension (priority 15 before 16).
    app = DB.applications.get(grant["application_id"])
    program = DB.programs.get(project["program_id"])
    if (contractor["sponsor_id"] != grant["sponsor_id"]
            or program is None
            or program["sponsor_id"] != grant["sponsor_id"]
            or app is None
            or project["id"] not in app["project_ids"]):
        raise ApiError("ERR_CROSS_SPONSOR_REFERENCE", 422,
                       "Contractor/project must belong to the grant's sponsor "
                       "and the project must be in the application's "
                       "project_ids")
    if contractor["status"] != "REGISTERED":
        raise ApiError("ERR_CONTRACTOR_SUSPENDED", 422,
                       "Cannot award a contract to a SUSPENDED contractor")
    c = new_entity()
    c.update({"grant_id": grant["id"], "cip_project_id": project["id"],
              "contractor_id": contractor["id"], "awarded_value": awarded,
              "dbe_goal_pct": dbe_goal, "retainage_pct": retainage,
              "invoiced_total": Decimal("0"),
              "remaining_value": awarded,
              "retainage_held": Decimal("0"),
              "dbe_posture": "UNEVALUATED", "status": "AWARDED"})
    DB.contracts[c["id"]] = c
    return respond(ser_contract(c), 201)


@bp.route("/aip/contracts", methods=["GET"])
@require(*ALL_ROLES)
def list_contracts():
    items = list(DB.contracts.values())
    grant_id = request.args.get("grant_id")
    contractor_id = request.args.get("contractor_id")
    project_id = request.args.get("cip_project_id")
    if grant_id is not None:
        items = [c for c in items if c["grant_id"] == grant_id]
    if contractor_id is not None:
        items = [c for c in items if c["contractor_id"] == contractor_id]
    if project_id is not None:
        items = [c for c in items if c["cip_project_id"] == project_id]
    return respond_list(items, ser_contract)


@bp.route("/aip/contracts/<contractId>", methods=["GET"])
@require(*ALL_ROLES)
def get_contract(contractId):
    return respond(ser_contract(
        get_or_404(DB.contracts, contractId, "Contract")))


# ---------------------------------------------------------------------------
# DBE reports
# ---------------------------------------------------------------------------

@bp.route("/aip/dbe-reports", methods=["POST"])
@require("Contractor")
def create_dbe_report():
    b = body()
    if "contract_id" not in b or b["contract_id"] is None:
        raise err_validation("Missing required field: contract_id")
    contract = get_or_404(DB.contracts, b["contract_id"], "Contract")
    if contract["contractor_id"] != g.user_id:
        raise err_forbidden(
            "A contractor may only file DBE reports against its own "
            "contracts")
    period = as_str(need(b, "reporting_period"), "reporting_period")
    dbe_paid = as_number(need(b, "dbe_paid_amount"), "dbe_paid_amount")
    if dbe_paid < 0:
        raise err_validation("dbe_paid_amount must be >= 0")
    total_paid = as_number(need(b, "total_paid_amount"), "total_paid_amount")
    if total_paid <= 0:
        raise err_validation("total_paid_amount must be > 0")
    if total_paid < dbe_paid:
        raise err_validation(
            "total_paid_amount must be >= dbe_paid_amount")
    if any(r["contract_id"] == contract["id"]
           and r["reporting_period"] == period
           for r in DB.dbe_reports.values()):
        raise err_validation("reporting_period must be unique per contract")
    achieved = r2(dbe_paid / total_paid * Decimal(100))
    r = new_entity(common=False)
    r.update({"contract_id": contract["id"], "reporting_period": period,
              "dbe_paid_amount": dbe_paid, "total_paid_amount": total_paid,
              "achieved_dbe_pct": achieved, "status": "PENDING"})
    DB.dbe_reports[r["id"]] = r
    return respond(ser_dbe_report(r), 201)


@bp.route("/aip/contracts/<contractId>/dbe-reports", methods=["GET"])
@require(*ALL_ROLES)
def list_dbe_reports(contractId):
    contract = get_or_404(DB.contracts, contractId, "Contract")
    items = [r for r in DB.dbe_reports.values()
             if r["contract_id"] == contract["id"]]
    return respond_list(items, ser_dbe_report)


@bp.route("/aip/dbe-reports/<reportId>/adjudicate", methods=["POST"])
@require("ComplianceOfficer")
def adjudicate_dbe_report(reportId):
    r = get_or_404(DB.dbe_reports, reportId, "DBEReport")
    if r["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING DBE report can be "
                                "adjudicated")
    contract = DB.contracts[r["contract_id"]]
    if contract["status"] != "AWARDED":
        raise ApiError("ERR_CONTRACT_CLOSED", 409,
                       "Adjudication requires an AWARDED contract")
    if r["achieved_dbe_pct"] >= contract["dbe_goal_pct"]:
        # Attainment (inclusive boundary): release withheld invoices.
        r["status"] = "COMPLIANT"
        contract["dbe_posture"] = "COMPLIANT"
        for inv in contract_invoices(contract["id"]):
            if inv["status"] == "WITHHELD":
                inv["status"] = "VERIFIED"
                touch(inv)
    else:
        # Shortfall: withhold every VERIFIED invoice.
        r["status"] = "SHORTFALL"
        contract["dbe_posture"] = "NON_COMPLIANT"
        for inv in contract_invoices(contract["id"]):
            if inv["status"] == "VERIFIED":
                inv["status"] = "WITHHELD"
                touch(inv)
    ledger_recompute(contract)
    touch(contract)
    return respond(ser_dbe_report(r))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.route("/aip/invoices", methods=["POST"])
@require("Contractor")
def create_invoice():
    b = body()
    if "contract_id" not in b or b["contract_id"] is None:
        raise err_validation("Missing required field: contract_id")
    contract = get_or_404(DB.contracts, b["contract_id"], "Contract")
    if contract["contractor_id"] != g.user_id:
        raise err_forbidden(
            "A contractor may only file invoices against its own contracts")
    number = as_str(need(b, "invoice_number"), "invoice_number")
    period = as_str(need(b, "period"), "period")
    gross = as_number(need(b, "gross_amount"), "gross_amount")
    if gross <= 0:
        raise err_validation("gross_amount must be > 0")
    if any(i["contract_id"] == contract["id"]
           and i["invoice_number"] == number for i in DB.invoices.values()):
        raise err_validation("invoice_number must be unique per contract")
    withheld, net = retainage_split(gross, contract["retainage_pct"])
    inv = new_entity()
    inv.update({"contract_id": contract["id"], "invoice_number": number,
                "period": period, "gross_amount": gross,
                "retainage_withheld": withheld, "net_payable": net,
                "drawdown_id": None, "status": "SUBMITTED"})
    DB.invoices[inv["id"]] = inv
    return respond(ser_invoice(inv), 201)


@bp.route("/aip/invoices", methods=["GET"])
@require(*ALL_ROLES)
def list_invoices():
    items = list(DB.invoices.values())
    contract_id = request.args.get("contract_id")
    drawdown_id = request.args.get("drawdown_id")
    status = request.args.get("status")
    if contract_id is not None:
        items = [i for i in items if i["contract_id"] == contract_id]
    if drawdown_id is not None:
        items = [i for i in items if i["drawdown_id"] == drawdown_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return respond_list(items, ser_invoice)


@bp.route("/aip/invoices/<invoiceId>", methods=["GET"])
@require(*ALL_ROLES)
def get_invoice(invoiceId):
    return respond(ser_invoice(
        get_or_404(DB.invoices, invoiceId, "Invoice")))


@bp.route("/aip/invoices/<invoiceId>/verify", methods=["POST"])
@require("SponsorStaff")
def verify_invoice(invoiceId):
    inv = get_or_404(DB.invoices, invoiceId, "Invoice")
    if inv["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED invoice can be verified")
    contract = DB.contracts[inv["contract_id"]]
    if contract["status"] != "AWARDED":
        raise ApiError("ERR_CONTRACT_CLOSED", 409,
                       "Invoice verification requires an AWARDED contract")
    grant = DB.grants[contract["grant_id"]]
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE", 409,
                       "Invoice verification requires an ACTIVE grant")
    if contract["invoiced_total"] + inv["gross_amount"] > \
            contract["awarded_value"]:
        raise ApiError("ERR_INVOICE_EXCEEDS_CONTRACT_VALUE", 402,
                       "Verification would push invoiced_total beyond "
                       "awarded_value")
    inv["status"] = "VERIFIED"
    touch(inv)
    ledger_recompute(contract)
    touch(contract)
    return respond(ser_invoice(inv))


@bp.route("/aip/invoices/<invoiceId>/reject", methods=["POST"])
@require("SponsorStaff")
def reject_invoice(invoiceId):
    inv = get_or_404(DB.invoices, invoiceId, "Invoice")
    if inv["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED invoice can be rejected")
    inv["status"] = "REJECTED"
    touch(inv)
    return respond(ser_invoice(inv))
