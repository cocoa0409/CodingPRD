"""Hydrogen supply contracts and the daily nomination book (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint

import domain
import response
import store
import validate
from errors import (
    ERR_HYDROGEN_CAPACITY_EXCEEDED,
    ERR_INVALID_NOMINATION_STATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_RUN_STATE,
    ERR_NOMINATION_OUTSIDE_CONTRACT_WINDOW,
    fail,
)
from routes.helpers import body_ref, find, listing
from store import bump, q

bp = Blueprint("hydrogen", __name__)
ZERO = Decimal("0")


@bp.post("/hydrogen-contracts")
def create_contract():
    validate.auth("FeedstockTrader")
    data = validate.body()
    vendor_name = validate.get_str(data, "vendor_name", 1, 120)
    daily_capacity = validate.get_num(data, "daily_capacity_kg", 0, 500000, 1,
                                      exclusive_min=True)
    price = validate.get_num(data, "price_usd_per_kg", 0, 50, 2, exclusive_min=True)
    window_start = validate.get_dt(data, "window_start")
    window_end = validate.get_dt(data, "window_end")
    hydrogen_ci = validate.get_num(data, "hydrogen_ci_gco2e_per_mj", 0, 200, 2)
    if window_end < window_start:
        fail(ERR_INVALID_REQUEST, "Field 'window_end' must be at or after 'window_start'.")

    row = store.new_row()
    row.update({
        "vendor_name": vendor_name,
        "daily_capacity_kg": q(daily_capacity, 1),
        "price_usd_per_kg": q(price, 2),
        "window_start": window_start,
        "window_end": window_end,
        "hydrogen_ci_gco2e_per_mj": q(hydrogen_ci, 2),
        "peak_committed_kg_per_day": q(ZERO, 1),
    })
    store.contracts[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/hydrogen-contracts/<contract_id>")
def read_contract(contract_id):
    validate.auth("FeedstockTrader", "PlantOperator", "ComplianceOfficer")
    return response.ok(find("contract", contract_id))


@bp.post("/hydrogen-contracts/<contract_id>/nominations")
def create_nomination(contract_id):
    validate.auth("PlantOperator")
    contract = find("contract", contract_id)
    data = validate.body()
    run = body_ref("run", data, "run_id")
    start_at = validate.get_dt(data, "start_at")
    end_at = validate.get_dt(data, "end_at")
    kg_per_day = validate.get_num(data, "kg_per_day", 0, 500000, 1, exclusive_min=True)

    if (end_at < start_at
            or start_at < contract["window_start"]
            or end_at > contract["window_end"]):
        fail(ERR_NOMINATION_OUTSIDE_CONTRACT_WINDOW,
             "Nomination [%s, %s] falls outside contract window [%s, %s]."
             % (store.iso(start_at), store.iso(end_at),
                store.iso(contract["window_start"]), store.iso(contract["window_end"])))

    kg_per_day = q(kg_per_day, 1)
    for day in store.date_range(start_at.date(), end_at.date()):
        committed = domain.committed_on_day(contract["id"], day)
        if committed + kg_per_day > contract["daily_capacity_kg"]:
            fail(ERR_HYDROGEN_CAPACITY_EXCEEDED,
                 "Day %s committed %s kg plus %s kg exceeds capacity %s."
                 % (day.isoformat(), committed, kg_per_day, contract["daily_capacity_kg"]))

    row = store.new_row()
    row.update({
        "contract_id": contract["id"],
        "run_id": run["id"],
        "start_at": start_at,
        "end_at": end_at,
        "kg_per_day": kg_per_day,
        "status": "CONFIRMED",
    })
    store.nominations[row["id"]] = row

    domain.recompute_contract_peak(contract)
    bump(contract)
    return response.ok(row, 201)


@bp.get("/hydrogen-contracts/<contract_id>/nominations")
def list_contract_nominations(contract_id):
    validate.auth("PlantOperator", "ComplianceOfficer")
    contract = find("contract", contract_id)
    rows, limit, offset = listing(domain.contract_nominations(contract["id"]),
                                  {"status": "status"})
    return response.page(rows, limit, offset)


@bp.get("/processing-runs/<run_id>/hydrogen-nominations")
def list_run_nominations(run_id):
    validate.auth("PlantOperator", "ComplianceOfficer")
    run = find("run", run_id)
    rows, limit, offset = listing(domain.run_nominations(run["id"]), {"status": "status"})
    return response.page(rows, limit, offset)


@bp.post("/hydrogen-nominations/<nomination_id>/cancellations")
def cancel_nomination(nomination_id):
    validate.auth("PlantOperator")
    nomination = find("nomination", nomination_id)
    if nomination["status"] != "CONFIRMED":
        fail(ERR_INVALID_NOMINATION_STATE,
             "Only a CONFIRMED nomination may be cancelled; this one is %s."
             % nomination["status"])
    run = store.runs.get(nomination["run_id"])
    if run is not None and run["status"] not in ("PLANNED", "HYDROGEN_SECURED"):
        fail(ERR_INVALID_RUN_STATE,
             "The supplied campaign is %s and its nominations are frozen." % run["status"])

    nomination["status"] = "CANCELLED"
    bump(nomination)
    contract = store.contracts.get(nomination["contract_id"])
    if contract is not None:
        domain.recompute_contract_peak(contract)
        bump(contract)

    if run is not None and run["status"] == "HYDROGEN_SECURED":
        if not domain.hydrogen_coverage_ok(run):
            domain.downgrade_run(run, cancel_nominations=False)
    return response.ok(nomination)
