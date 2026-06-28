"""FinancingPlan + Installment endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import clock, format_iso8601_ms, parse_iso8601
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize, touch
from response import object_response, array_response
from services.calculations import (amortization, delinquency_state, GRACE_DAYS)
from services.dates import add_months
from services.listing import paginate
from services.store import (get_financing_plan, get_case, fk_case,
                            installments_for_plan)
from validation import (get_body, require_str, require_int, parse_pagination)

bp = Blueprint("financing", __name__)

TERMS = {12, 24, 36}


@bp.route("/financing-plans", methods=["POST"])
def create_financing():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    body = get_body()
    case_id = require_str(body, "case_id")
    term_months = require_int(body, "term_months")
    down_payment_cents = require_int(body, "down_payment_cents")
    apr_bps = require_int(body, "apr_bps")
    if term_months not in TERMS:
        raise err("ERR_INVALID_REQUEST", "term_months must be one of 12, 24, 36.")
    if down_payment_cents < 0:
        raise err("ERR_INVALID_REQUEST", "down_payment_cents must be >= 0.")
    if apr_bps < 0:
        raise err("ERR_INVALID_REQUEST", "apr_bps must be >= 0.")
    fk_case(case_id)

    rec = base_record(common_fields=True)
    rec.update({
        "case_id": case_id,
        "term_months": term_months,
        "down_payment_cents": down_payment_cents,
        "apr_bps": apr_bps,
        "billing_state": "PENDING_ACTIVATION",
        "delinquency_state": "CURRENT",
        "financed_principal_cents": 0,
        "outstanding_principal_cents": 0,
    })
    db.financing_plans[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/financing-plans/<fid>", methods=["GET"])
def fetch_financing(fid):
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    rec = get_financing_plan(fid)
    return object_response(serialize(rec), status=200)


@bp.route("/financing-plans", methods=["GET"])
def list_financing():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    billing_state = request.args.get("billing_state")
    records = list(db.financing_plans.values())
    if case_id is not None:
        records = [f for f in records if f["case_id"] == case_id]
    if billing_state is not None:
        records = [f for f in records if f["billing_state"] == billing_state]
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/financing-plans/<fid>/activate", methods=["POST"])
def activate_financing(fid):
    _, role = get_auth()
    require_roles(role, {"BillingAdmin"})
    plan = get_financing_plan(fid)
    body = get_body()
    expected_version = require_int(body, "expected_financing_plan_version")
    # state precondition
    if plan["billing_state"] != "PENDING_ACTIVATION":
        raise err("ERR_INVALID_STATE",
                  "FinancingPlan must be PENDING_ACTIVATION to activate.")
    # OCC check (priority 6)
    if expected_version != plan["version"]:
        raise err("ERR_STALE_FINANCING_VERSION",
                  "expected_financing_plan_version does not match current version.")
    case = get_case(plan["case_id"])
    # case must be PLAN_APPROVED
    if case["status"] != "PLAN_APPROVED":
        raise err("ERR_INVALID_STATE",
                  "The plan's case must be PLAN_APPROVED to activate financing.")
    # down payment must not exceed contracted total (priority 17)
    if plan["down_payment_cents"] > case["total_contracted_cents"]:
        raise err("ERR_DOWN_PAYMENT_EXCEEDS_TOTAL",
                  "down_payment_cents exceeds case.total_contracted_cents.")

    financed_principal = case["total_contracted_cents"] - plan["down_payment_cents"]
    plan["financed_principal_cents"] = financed_principal
    plan["outstanding_principal_cents"] = financed_principal

    activation_dt = clock.now()
    schedule = amortization(financed_principal, plan["term_months"], plan["apr_bps"])
    for row in schedule:
        due_dt = add_months(activation_dt, row["sequence_no"])
        inst = base_record(common_fields=True)
        inst.update({
            "financing_plan_id": plan["id"],
            "sequence_no": row["sequence_no"],
            "due_at": format_iso8601_ms(due_dt),
            "amount_cents": row["amount_cents"],
            "principal_portion_cents": row["principal_portion_cents"],
            "status": "SCHEDULED",
        })
        db.installments[inst["id"]] = inst

    # post the down payment to the case ledger
    case["amount_collected_cents"] += plan["down_payment_cents"]
    touch(case)

    plan["billing_state"] = "ACTIVE"
    touch(plan)  # increments version by 1
    return object_response(serialize(plan), status=200)


@bp.route("/financing-plans/<fid>/installments", methods=["GET"])
def list_installments(fid):
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    get_financing_plan(fid)
    limit, offset = parse_pagination()
    records = installments_for_plan(fid)
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


def _installment_by_seq(plan_id, seq):
    for i in db.installments.values():
        if i["financing_plan_id"] == plan_id and i["sequence_no"] == seq:
            return i
    return None


def _recompute_delinquency(plan):
    late_count = sum(
        1 for i in installments_for_plan(plan["id"]) if i["status"] == "LATE"
    )
    plan["delinquency_state"] = delinquency_state(late_count)


@bp.route("/financing-plans/<fid>/installments/<seq>/post-payment", methods=["POST"])
def post_payment(fid, seq):
    _, role = get_auth()
    require_roles(role, {"BillingAdmin"})
    plan = get_financing_plan(fid)
    try:
        seq_no = int(seq)
    except (ValueError, TypeError):
        raise err("ERR_NOT_FOUND", "Installment not found.")
    inst = _installment_by_seq(fid, seq_no)
    if inst is None:
        raise err("ERR_NOT_FOUND", "Installment not found.")
    # state precondition
    if inst["status"] not in ("SCHEDULED", "LATE"):
        raise err("ERR_INVALID_STATE",
                  "Installment must be SCHEDULED or LATE to post.")
    if plan["billing_state"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan must be ACTIVE to post a payment.")
    # in-order posting (priority 18)
    for other in installments_for_plan(fid):
        if (other["sequence_no"] < inst["sequence_no"]
                and other["status"] in ("SCHEDULED", "LATE")):
            raise err("ERR_INSTALLMENT_OUT_OF_ORDER",
                      "A lower-sequence installment is still unpaid.")

    inst["status"] = "POSTED"
    touch(inst)
    case = db.cases.get(plan["case_id"])
    if case is not None:
        case["amount_collected_cents"] += inst["amount_cents"]
        touch(case)
    plan["outstanding_principal_cents"] -= inst["principal_portion_cents"]

    paid_off = False
    if plan["outstanding_principal_cents"] == 0:
        plan["billing_state"] = "PAID_OFF"
        plan["delinquency_state"] = "CURRENT"
        paid_off = True
    if not paid_off:
        _recompute_delinquency(plan)
    touch(plan)
    return object_response(serialize(inst), status=200)


@bp.route("/financing-plans/<fid>/run-delinquency-sweep", methods=["POST"])
def run_delinquency_sweep(fid):
    _, role = get_auth()
    require_roles(role, {"BillingAdmin"})
    plan = get_financing_plan(fid)
    now = clock.now()
    grace = timedelta(days=GRACE_DAYS)
    for inst in installments_for_plan(fid):
        if inst["status"] != "SCHEDULED":
            continue
        due = parse_iso8601(inst["due_at"])
        if due is None:
            continue
        if due + grace <= now:
            inst["status"] = "LATE"
            touch(inst)
    _recompute_delinquency(plan)
    touch(plan)
    return object_response(serialize(plan), status=200)
