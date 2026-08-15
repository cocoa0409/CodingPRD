"""Invoice endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_FUEL_ENTRY_MISSING,
    ERR_INVALID_STATE,
    ERR_INVOICE_PERIOD_INCOMPLETE,
    raise_err,
)
from middleware import (
    authenticate,
    district_ownership,
    get_or_404,
    read_scoping,
    require_roles,
)
from services.pricing import compute_invoice_lines, fuel_entry_for
from validation import (
    get_body,
    paginate,
    pagination_params,
    req_int,
    req_month,
    req_str,
)

bp = Blueprint("invoices", __name__)

READ_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FinanceClerk"}
TERMINAL = ("PAID", "WRITTEN_OFF")


def check_invoice_transition(inv, allowed_from):
    if inv["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Invoice is in a terminal state")
    if inv["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "Invoice in state %s cannot perform this transition" % inv["status"],
        )


@bp.route("/busops/invoices/generate", methods=["POST"])
def generate_invoice():
    body = get_body()
    contract_id = req_str(body, "contract_id")
    period = req_month(body, "period_month")
    actor = authenticate()
    require_roles(actor, {"FinanceClerk"})
    contract = get_or_404("contracts", contract_id, "Contract")
    # 13. referential: fuel entry must exist for (district, period)
    if fuel_entry_for(contract["district_id"], period) is None:
        raise_err(
            ERR_FUEL_ENTRY_MISSING,
            "No fuel price entry for the contract's district and period",
        )
    # 14. fiscal: at least one RECONCILED day in the period
    has_reconciled = any(
        d["contract_id"] == contract_id
        and d["service_date"][:7] == period
        and d["status"] == "RECONCILED"
        for d in db.all_of("service_days")
    )
    if not has_reconciled:
        raise_err(
            ERR_INVOICE_PERIOD_INCOMPLETE,
            "Period has no RECONCILED service day (nothing final to bill)",
        )

    lines = compute_invoice_lines(contract, period, "PROVISIONAL")
    rec = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "period_month": period,
        "status": "DRAFT",
        "bus_lines_cents": lines["bus_lines_cents"],
        "charter_lines_cents": lines["charter_lines_cents"],
        "shortage_credit_cents": lines["shortage_credit_cents"],
        "fuel_adjustment_cents": lines["fuel_adjustment_cents"],
        "provisional_total_cents": lines["total_cents"],
        "final_total_cents": None,
        "total_cents": lines["total_cents"],
        "issued_on": None,
        "dispute_count": 0,
        "dispute_reason": None,
        "paid_on": None,
        "_district_ref": contract["district_id"],
    }
    db.stamp_new(rec)
    db.STORES["invoices"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/invoices", methods=["GET"])
def list_invoices():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    items = list(db.all_of("invoices"))
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    period = request.args.get("period_month")
    if contract_id is not None:
        items = [i for i in items if i["contract_id"] == contract_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if period is not None:
        items = [i for i in items if i["period_month"] == period]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    rec = get_or_404("invoices", rid, "Invoice")
    err = read_scoping(actor, rec)
    if err:
        raise err
    return success_object(db.public(rec))


@bp.route("/busops/invoices/<rid>/issue", methods=["POST"])
def issue_invoice(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"FinanceClerk"})
    inv = get_or_404("invoices", rid, "Invoice")
    check_invoice_transition(inv, ("DRAFT",))
    contract = get_or_404("contracts", inv["contract_id"], "Contract")
    period = inv["period_month"]

    lines = compute_invoice_lines(contract, period, "FINAL")
    inv["bus_lines_cents"] = lines["bus_lines_cents"]
    inv["charter_lines_cents"] = lines["charter_lines_cents"]
    inv["shortage_credit_cents"] = lines["shortage_credit_cents"]
    inv["fuel_adjustment_cents"] = lines["fuel_adjustment_cents"]
    inv["final_total_cents"] = lines["total_cents"]
    inv["total_cents"] = lines["total_cents"]
    inv["issued_on"] = db.clock_date().isoformat()
    inv["status"] = "ISSUED"
    db.touch(inv)

    for day in db.all_of("service_days"):
        if (
            day["contract_id"] == contract["id"]
            and day["service_date"][:7] == period
            and day["status"] == "RECONCILED"
        ):
            day["status"] = "INVOICED"
            db.touch(day)
    for trip in db.all_of("charter_trips"):
        if (
            trip["contract_id"] == contract["id"]
            and trip["trip_date"][:7] == period
            and trip["status"] == "COMPLETED"
        ):
            trip["status"] = "INVOICED"
            db.touch(trip)
    return success_object(db.public(inv))


@bp.route("/busops/invoices/<rid>/dispute", methods=["POST"])
def dispute_invoice(rid):
    body = get_body()
    reason = req_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    inv = get_or_404("invoices", rid, "Invoice")
    contract = get_or_404("contracts", inv["contract_id"], "Contract")
    district_ownership(actor, contract["district_id"])
    check_invoice_transition(inv, ("ISSUED",))
    district = get_or_404("districts", contract["district_id"], "District")
    issued = db.parse_date(inv["issued_on"])
    deadline = issued + timedelta(days=district["billing_dispute_window_days"])
    if db.clock_date() > deadline:
        raise_err(
            ERR_DISPUTE_WINDOW_CLOSED,
            "Dispute attempted after the billing dispute window closed",
        )
    inv["status"] = "DISPUTED"
    inv["dispute_count"] += 1
    inv["dispute_reason"] = reason
    db.touch(inv)
    return success_object(db.public(inv))


@bp.route("/busops/invoices/<rid>/reissue", methods=["POST"])
def reissue_invoice(rid):
    body = get_body()
    delta = req_int(body, "adjustment_delta_cents")
    reason = req_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"FinanceClerk"})
    inv = get_or_404("invoices", rid, "Invoice")
    check_invoice_transition(inv, ("DISPUTED",))
    inv["total_cents"] += delta
    inv["final_total_cents"] = (inv["final_total_cents"] or 0) + delta
    inv["issued_on"] = db.clock_date().isoformat()
    inv["status"] = "ISSUED"
    db.touch(inv)
    return success_object(db.public(inv))


@bp.route("/busops/invoices/<rid>/pay", methods=["POST"])
def pay_invoice(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"FinanceClerk"})
    inv = get_or_404("invoices", rid, "Invoice")
    check_invoice_transition(inv, ("ISSUED",))
    inv["status"] = "PAID"
    inv["paid_on"] = db.clock_date().isoformat()
    db.touch(inv)
    return success_object(db.public(inv))


@bp.route("/busops/invoices/<rid>/write-off", methods=["POST"])
def write_off_invoice(rid):
    body = get_body()
    actor = authenticate()
    require_roles(actor, {"FinanceClerk"})
    inv = get_or_404("invoices", rid, "Invoice")
    check_invoice_transition(inv, ("ISSUED", "DISPUTED"))
    inv["status"] = "WRITTEN_OFF"
    db.touch(inv)
    return success_object(db.public(inv))
