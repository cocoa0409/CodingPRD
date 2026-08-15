"""Resource resolution helpers — one 404 error id per resource type."""
from db import store
from errors import ApiError


def _get(table, rid, error_id, label):
    rec = table.get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "%s not found: %s" % (label, rid))
    return rec


def get_program_year(rid):
    return _get(store.program_years, rid, "ERR_PROGRAM_YEAR_NOT_FOUND", "ProgramYear")


def get_measure(rid):
    return _get(store.measures, rid, "ERR_MEASURE_NOT_FOUND", "Measure")


def get_trade_ally(rid):
    return _get(store.trade_allies, rid, "ERR_ALLY_NOT_FOUND", "TradeAlly")


def get_application(rid):
    return _get(store.applications, rid, "ERR_APPLICATION_NOT_FOUND", "RebateApplication")


def get_line_item(rid):
    return _get(store.line_items, rid, "ERR_LINE_ITEM_NOT_FOUND", "ApplicationLineItem")


def get_savings_claim(rid):
    return _get(store.savings_claims, rid, "ERR_SAVINGS_CLAIM_NOT_FOUND", "SavingsClaim")


def get_inspection(rid):
    return _get(store.inspections, rid, "ERR_INSPECTION_NOT_FOUND", "Inspection")


def get_adjustment(rid):
    return _get(store.adjustments, rid, "ERR_ADJUSTMENT_NOT_FOUND", "EvaluationAdjustment")


def get_fraud_flag(rid):
    return _get(store.fraud_flags, rid, "ERR_FRAUD_FLAG_NOT_FOUND", "FraudFlag")


def program_year_of_application(app):
    return store.program_years[app["program_year_id"]]


def ensure_program_open(py):
    """Program-open gate (PRD section 2.9, fifth check)."""
    if py["status"] != "OPEN":
        raise ApiError(
            "ERR_PROGRAM_NOT_OPEN",
            409,
            "ProgramYear.status is %s; operation requires OPEN" % py["status"],
        )


def lines_of(application_id):
    rows = [r for r in store.line_items.values() if r["application_id"] == application_id]
    return sorted(rows, key=lambda r: r["_seq"])


def claim_of_line(line_item_id):
    for c in store.savings_claims.values():
        if c["line_item_id"] == line_item_id:
            return c
    return None
