"""Bill endpoints."""

from flask import Blueprint, g

import calc
import domain
from core import (
    BILLING_STATUSES,
    BILL_DUE_DAYS,
    BILL_READ_TYPES,
    LEAK_TYPES,
    SOURCE_KINDS,
    Body,
    add_days,
    as_date,
    base_record,
    clock_date,
    created_response,
    date_str,
    endpoint,
    err,
    get_or_404,
    insert,
    is_customer,
    list_result,
    maybe,
    object_response,
    q_bool,
    q_enum,
    q_str,
    register_new,
    require_own_account,
    rows,
    serialize,
    touch,
)

bp = Blueprint("routes_b", __name__)


def _blank_bill():
    rec = base_record()
    rec.update(
        {
            "account_id": None,
            "period_id": None,
            "meter_id": None,
            "consumption_gallons": 0,
            "read_type": None,
            "estimated_flag": False,
            "seasonal_baseline_gallons": None,
            "baseline_sample_count": 0,
            "anomaly_ratio": None,
            "anomaly_flag": False,
            "water_charge_cents": 0,
            "submeter_credit_gallons": 0,
            "sewer_billable_gallons": 0,
            "sewer_charge_cents": 0,
            "total_charge_cents": 0,
            "adjusted_total_cents": 0,
            "due_date": None,
            "billing_status": "DRAFT",
            "rebill_of_bill_id": None,
        }
    )
    return rec


@bp.route("/bills", methods=["POST"])
@endpoint("BillingSupervisor", "SystemAdmin")
def create_bill():
    body = Body()
    account_id = body.string("account_id")
    period_id = body.string("period_id")
    meter_id = body.string("meter_id")
    read_type = body.enum("read_type", BILL_READ_TYPES)

    account = get_or_404("service_accounts", account_id)
    period = get_or_404("billing_periods", period_id)
    meter = get_or_404("meters", meter_id)

    if period["status"] != "OPEN":
        err("ERR_BILLING_PERIOD_CLOSED", "bills may only be created for an OPEN period")
    if not clock_date() > as_date(period["end_date"]):
        err("ERR_BILLING_PERIOD_NOT_ENDED", "the billing period has not ended yet")

    for existing in rows("bills"):
        if (
            existing["meter_id"] == meter_id
            and existing["period_id"] == period_id
            and existing["billing_status"] != "REBILLED"
        ):
            err(
                "ERR_DUPLICATE_BILL_FOR_PERIOD",
                "a bill for this meter and period already exists",
            )
    if meter["meter_type"] != "POTABLE_MASTER":
        err("ERR_METER_NOT_BILLABLE", "only a POTABLE_MASTER meter may be billed")
    if meter["account_id"] != account_id:
        err("ERR_BILL_METER_ACCOUNT_MISMATCH", "the meter belongs to another account")

    rec = _blank_bill()
    rec["account_id"] = account["id"]
    rec["period_id"] = period["id"]
    rec["meter_id"] = meter["id"]
    rec["read_type"] = read_type
    rec["estimated_flag"] = read_type == "ESTIMATED"
    insert("bills", register_new(rec))
    domain.compute_bill_charges(rec)
    domain.compute_bill_baseline(rec)
    return created_response(serialize(rec))


@bp.route("/bills", methods=["GET"])
@endpoint("BillingSupervisor", "SystemAdmin", "CustomerServiceRep", "Customer")
def list_bills():
    account_id = q_str("account_id")
    period_id = q_str("period_id")
    meter_id = q_str("meter_id")
    rebill_of_bill_id = q_str("rebill_of_bill_id")
    billing_status = q_enum("billing_status", BILLING_STATUSES)
    anomaly_flag = q_bool("anomaly_flag")
    if account_id is not None:
        require_own_account(account_id)
    if meter_id is not None:
        meter = maybe("meters", meter_id)
        if meter is not None:
            require_own_account(meter["account_id"])
    if rebill_of_bill_id is not None:
        other = maybe("bills", rebill_of_bill_id)
        if other is not None:
            require_own_account(other["account_id"])

    result = []
    for rec in rows("bills"):
        if account_id is not None and rec["account_id"] != account_id:
            continue
        if period_id is not None and rec["period_id"] != period_id:
            continue
        if meter_id is not None and rec["meter_id"] != meter_id:
            continue
        if rebill_of_bill_id is not None and rec.get("rebill_of_bill_id") != rebill_of_bill_id:
            continue
        if billing_status is not None and rec["billing_status"] != billing_status:
            continue
        if anomaly_flag is not None and bool(rec["anomaly_flag"]) != anomaly_flag:
            continue
        result.append(rec)
    if is_customer():
        result = [r for r in result if r["account_id"] == g.user_id]
    return list_result(result)


@bp.route("/bills/<rid>", methods=["GET"])
@endpoint("BillingSupervisor", "SystemAdmin", "CustomerServiceRep", "Customer")
def get_bill(rid):
    bill = get_or_404("bills", rid)
    require_own_account(bill["account_id"])
    return object_response(serialize(bill))


@bp.route("/bills/<rid>/ledger-entries", methods=["GET"])
@endpoint("BillingSupervisor", "SystemAdmin", "CustomerServiceRep", "Customer")
def list_bill_ledger(rid):
    bill = get_or_404("bills", rid)
    require_own_account(bill["account_id"])
    source_kind = q_enum("source_kind", SOURCE_KINDS)
    result = []
    for entry in rows("ledger_entries"):
        if entry["bill_id"] != bill["id"]:
            continue
        if source_kind is not None and entry["source_kind"] != source_kind:
            continue
        result.append(entry)
    return list_result(result)


@bp.route("/bills/<rid>/adjustment-preview", methods=["GET"])
@endpoint("CustomerServiceRep", "BillingSupervisor")
def adjustment_preview(rid):
    assumed_leak_type = q_str("assumed_leak_type")
    if assumed_leak_type is None:
        err("ERR_INVALID_REQUEST", "assumed_leak_type is required")
    assumed_leak_type = q_enum("assumed_leak_type", LEAK_TYPES)
    bill = get_or_404("bills", rid)
    period = domain.period_of_bill(bill)
    schedule = domain.schedule_of_bill(bill)
    baseline = bill["seasonal_baseline_gallons"]

    reprice = calc.leak_adjustment_credit(
        bill, schedule, period["season"], assumed_leak_type, baseline,
        forced_variant="EXCESS_REPRICE",
    )
    rebill = calc.leak_adjustment_credit(
        bill, schedule, period["season"], assumed_leak_type, baseline,
        forced_variant="BASELINE_REBILL",
    )
    return object_response(
        {
            "bill_id": bill["id"],
            "assumed_leak_type": assumed_leak_type,
            "recommended_variant": calc.select_variant(assumed_leak_type, False),
            "excess_gallons": reprice["excess_gallons"],
            "excess_reprice_net_cents": reprice["net_credit_cents"],
            "baseline_rebill_net_cents": rebill["net_credit_cents"],
            "variant_delta_cents": rebill["net_credit_cents"] - reprice["net_credit_cents"],
        }
    )


def _issue(bill, account, source_kind):
    period = domain.period_of_bill(bill)
    bill["billing_status"] = "ISSUED"
    bill["due_date"] = date_str(add_days(as_date(period["end_date"]), BILL_DUE_DAYS))
    touch(bill)
    domain.add_ledger_entry(
        account,
        "CHARGE",
        source_kind,
        int(bill["total_charge_cents"]),
        bill_id=bill["id"],
        source_id=bill["id"],
    )


@bp.route("/bills/<rid>/issue", methods=["POST"])
@endpoint("BillingSupervisor")
def issue_bill(rid):
    bill = get_or_404("bills", rid)
    period = domain.period_of_bill(bill)
    if bill["billing_status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", "only a DRAFT bill may be issued")
    if period["status"] not in ("OPEN", "CLOSED"):
        err("ERR_INVALID_STATE_TRANSITION", "the billing period is LOCKED")
    account = maybe("service_accounts", bill["account_id"])
    _issue(bill, account, "BILL_CHARGE")
    domain.refresh_account(account)
    return object_response(serialize(bill))


@bp.route("/bills/<rid>/rebill", methods=["POST"])
@endpoint("BillingSupervisor")
def rebill_bill(rid):
    bill = get_or_404("bills", rid)
    period = domain.period_of_bill(bill)
    if bill["billing_status"] != "REBILL_PENDING":
        err("ERR_INVALID_STATE_TRANSITION", "only a REBILL_PENDING bill may be rebilled")
    if period["status"] == "LOCKED":
        err("ERR_BILLING_PERIOD_LOCKED", "the billing period is LOCKED")
    if clock_date() > as_date(period["rebilling_deadline_date"]):
        err("ERR_REBILL_WINDOW_EXPIRED", "the rebilling deadline has passed")

    account = maybe("service_accounts", bill["account_id"])
    original_charge_total = domain.bill_charge_total(bill["id"])

    bill["billing_status"] = "REBILLED"
    touch(bill)

    domain.add_ledger_entry(
        account,
        "REVERSAL",
        "REBILL_REVERSAL",
        -original_charge_total,
        bill_id=bill["id"],
        source_id=bill["id"],
    )

    replacement = _blank_bill()
    replacement["account_id"] = bill["account_id"]
    replacement["period_id"] = bill["period_id"]
    replacement["meter_id"] = bill["meter_id"]
    replacement["read_type"] = bill["read_type"]
    replacement["estimated_flag"] = bill["estimated_flag"]
    replacement["rebill_of_bill_id"] = bill["id"]
    insert("bills", register_new(replacement))
    domain.compute_bill_charges(replacement)
    domain.compute_bill_baseline(replacement)

    _issue(replacement, account, "REBILL_CHARGE")
    domain.refresh_account(account)
    return object_response(serialize(replacement))
