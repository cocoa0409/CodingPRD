"""Investigations, meter test requests and repair proofs."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import domain
from core import (
    INVESTIGATION_STATUSES,
    LEAK_DETERMINATIONS,
    LEAK_TYPES,
    MAX_EVIDENCE_ROUNDS,
    METER_TEST_DEPOSIT_CENTS,
    METER_TEST_QUARANTINE_HOURS,
    PROOF_STATUSES,
    REQUESTED_BY_KINDS,
    TEST_STATUSES,
    TEST_TYPES,
    FIELD_RESULTS,
    Body,
    as_date,
    as_dt,
    base_record,
    clock_now,
    created_response,
    endpoint,
    err,
    get_or_404,
    insert,
    is_customer,
    iso,
    list_result,
    maybe,
    now_iso,
    object_response,
    parse_date,
    parse_dt,
    q_enum,
    q_str,
    register_new,
    require_own_account,
    rows,
    serialize,
    store,
    touch,
)

bp = Blueprint("routes_c", __name__)


def _advance_evidence_under_review(investigation):
    if investigation["status"] == "EVIDENCE_REQUESTED":
        investigation["status"] = "EVIDENCE_UNDER_REVIEW"
        domain.sync_investigation_hold(investigation)
        touch(investigation)


# ---------------------------------------------------------------------------
# HighBillInvestigation
# ---------------------------------------------------------------------------
@bp.route("/investigations", methods=["POST"])
@endpoint("CustomerServiceRep", "Customer")
def create_investigation():
    body = Body()
    bill_id = body.string("bill_id")
    reported_cause = body.string("reported_cause")

    bill = get_or_404("bills", bill_id)
    require_own_account(bill["account_id"])

    if bill["billing_status"] != "ISSUED":
        err(
            "ERR_INVESTIGATION_ALREADY_OPEN",
            "the bill is not in ISSUED status",
        )
    if domain.open_investigations_for_bill(bill["id"]):
        err(
            "ERR_INVESTIGATION_ALREADY_OPEN",
            "a non-terminal investigation already exists for this bill",
        )
    if bill["seasonal_baseline_gallons"] is None:
        err(
            "ERR_INSUFFICIENT_BASELINE_HISTORY",
            "the bill has no seasonal baseline",
        )

    rec = base_record()
    rec.update(
        {
            "bill_id": bill["id"],
            "account_id": bill["account_id"],
            "reported_cause": reported_cause,
            "status": "OPEN",
            "leak_determination": "UNDETERMINED",
            "determination_by_user_id": None,
            "determined_at": None,
            "evidence_round_count": 0,
            "remand_count": 0,
            "shutoff_hold_active": True,
            "opened_by_role": "CUSTOMER" if g.role == "Customer" else "CUSTOMER_SERVICE_REP",
            "opened_by_user_id": g.user_id,
        }
    )
    insert("investigations", register_new(rec))

    bill["billing_status"] = "UNDER_INVESTIGATION"
    touch(bill)
    account = maybe("service_accounts", bill["account_id"])
    domain.refresh_account(account)
    return created_response(serialize(rec))


@bp.route("/investigations", methods=["GET"])
@endpoint("CustomerServiceRep", "Customer", "BillingSupervisor", "SystemAdmin", "UtilityBoardClerk")
def list_investigations():
    bill_id = q_str("bill_id")
    account_id = q_str("account_id")
    status = q_enum("status", INVESTIGATION_STATUSES)
    leak_determination = q_enum("leak_determination", LEAK_DETERMINATIONS)
    if account_id is not None:
        require_own_account(account_id)
    if bill_id is not None:
        bill = maybe("bills", bill_id)
        if bill is not None:
            require_own_account(bill["account_id"])

    result = []
    for rec in rows("investigations"):
        if bill_id is not None and rec["bill_id"] != bill_id:
            continue
        if account_id is not None and rec["account_id"] != account_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if leak_determination is not None and rec["leak_determination"] != leak_determination:
            continue
        result.append(rec)
    if is_customer():
        result = [r for r in result if r["account_id"] == g.user_id]
    return list_result(result)


@bp.route("/investigations/<rid>", methods=["GET"])
@endpoint("CustomerServiceRep", "Customer", "BillingSupervisor", "SystemAdmin", "UtilityBoardClerk")
def get_investigation(rid):
    rec = get_or_404("investigations", rid)
    require_own_account(rec["account_id"])
    return object_response(serialize(rec))


@bp.route("/investigations/<rid>/request-evidence", methods=["POST"])
@endpoint("CustomerServiceRep")
def request_evidence(rid):
    Body().string("note", required=False)
    rec = get_or_404("investigations", rid)
    if rec["status"] not in ("OPEN", "EVIDENCE_REQUESTED"):
        err("ERR_INVALID_STATE_TRANSITION", "evidence may only be requested from OPEN or EVIDENCE_REQUESTED")
    if rec["evidence_round_count"] >= MAX_EVIDENCE_ROUNDS:
        err("ERR_EVIDENCE_ROUND_LIMIT", "the evidence round limit has been reached")
    rec["status"] = "EVIDENCE_REQUESTED"
    rec["evidence_round_count"] = rec["evidence_round_count"] + 1
    domain.sync_investigation_hold(rec)
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/investigations/<rid>/determine", methods=["POST"])
@endpoint("CustomerServiceRep")
def determine_investigation(rid):
    body = Body()
    leak_determination = body.enum("leak_determination", LEAK_DETERMINATIONS)
    rec = get_or_404("investigations", rid)
    if rec["status"] != "EVIDENCE_UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "status must be EVIDENCE_UNDER_REVIEW")
    bill = maybe("bills", rec["bill_id"])
    if bill is None or bill["seasonal_baseline_gallons"] is None:
        err("ERR_INVALID_STATE_TRANSITION", "the bill has no seasonal baseline")
    if leak_determination in ("CUSTOMER_SIDE_LEAK", "UTILITY_SIDE_LEAK"):
        if not domain.verified_proofs(rec["id"]):
            err("ERR_INVALID_STATE_TRANSITION", "a VERIFIED repair proof is required")
    if leak_determination == "METER_ERROR":
        closed = [
            t
            for t in rows("meter_test_requests")
            if t["investigation_id"] == rec["id"]
            and t["status"] in ("CLOSED_FAST", "CLOSED_SLOW")
        ]
        if not closed:
            err(
                "ERR_INVALID_STATE_TRANSITION",
                "a meter test closed FAST or SLOW is required",
            )

    rec["status"] = "DETERMINED"
    rec["leak_determination"] = leak_determination
    rec["determination_by_user_id"] = g.user_id
    rec["determined_at"] = now_iso()
    domain.sync_investigation_hold(rec)
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/investigations/<rid>/close-no-adjustment", methods=["POST"])
@endpoint("CustomerServiceRep")
def close_no_adjustment(rid):
    Body().string("note", required=False)
    rec = get_or_404("investigations", rid)
    if rec["status"] not in (
        "OPEN",
        "EVIDENCE_REQUESTED",
        "EVIDENCE_UNDER_REVIEW",
        "EVIDENCE_EXHAUSTED",
    ):
        err("ERR_INVALID_STATE_TRANSITION", "the investigation cannot be closed from this state")

    rec["status"] = "CLOSED_NO_ADJUSTMENT"
    domain.sync_investigation_hold(rec)
    rec["_closed_at"] = now_iso()
    touch(rec)

    bill = maybe("bills", rec["bill_id"])
    if bill is not None and bill["billing_status"] == "UNDER_INVESTIGATION":
        bill["billing_status"] = "UPHELD_AS_BILLED"
        domain.recompute_adjusted_total(bill)
        touch(bill)
    account = maybe("service_accounts", rec["account_id"])
    if account is not None:
        domain.refresh_account(account)
    return object_response(serialize(rec))


# ---------------------------------------------------------------------------
# MeterTestRequest
# ---------------------------------------------------------------------------
@bp.route("/meter-test-requests", methods=["POST"])
@endpoint("CustomerServiceRep", "MeterTechnician", "Customer")
def create_meter_test_request():
    body = Body()
    investigation_id = body.string("investigation_id")
    meter_id = body.string("meter_id")
    requested_test_type = body.enum("requested_test_type", TEST_TYPES)
    requested_by_kind = body.enum("requested_by_kind", REQUESTED_BY_KINDS)
    deposit_cents = body.integer("deposit_cents", minimum=0)

    investigation = get_or_404("investigations", investigation_id)
    meter = get_or_404("meters", meter_id)
    require_own_account(investigation["account_id"])

    if meter["account_id"] != investigation["account_id"]:
        err(
            "ERR_TEST_METER_ACCOUNT_MISMATCH",
            "the meter does not belong to the investigation's account",
        )
    if requested_by_kind == "CUSTOMER" and deposit_cents != METER_TEST_DEPOSIT_CENTS:
        err(
            "ERR_TEST_DEPOSIT_INVALID",
            "a customer-requested test requires a deposit of %d cents" % METER_TEST_DEPOSIT_CENTS,
        )
    if requested_by_kind == "UTILITY" and deposit_cents != 0:
        err("ERR_TEST_DEPOSIT_INVALID", "a utility-requested test carries no deposit")

    rec = base_record()
    rec.update(
        {
            "investigation_id": investigation["id"],
            "meter_id": meter["id"],
            "requested_test_type": requested_test_type,
            "requested_by_kind": requested_by_kind,
            "deposit_cents": deposit_cents,
            "status": "REQUESTED",
            "window_start": None,
            "window_end": None,
            "tested_at": None,
            "field_result": None,
            "low_flow_pct": None,
            "mid_flow_pct": None,
            "high_flow_pct": None,
            "accuracy_method": None,
            "accuracy_pct": None,
            "bench_result": None,
            "deposit_refunded": False,
        }
    )
    insert("meter_test_requests", register_new(rec))

    account = maybe("service_accounts", investigation["account_id"])
    if deposit_cents > 0:
        domain.add_ledger_entry(
            account,
            "CHARGE",
            "METER_TEST_DEPOSIT",
            deposit_cents,
            bill_id=None,
            source_id=rec["id"],
        )
        domain.refresh_account(account)
    if requested_test_type == "BENCH":
        rec["status"] = "BENCH_TEST_PENDING"
    return created_response(serialize(rec))


@bp.route("/meter-test-requests", methods=["GET"])
@endpoint("CustomerServiceRep", "MeterTechnician", "Customer", "BillingSupervisor", "SystemAdmin")
def list_meter_test_requests():
    investigation_id = q_str("investigation_id")
    meter_id = q_str("meter_id")
    status = q_enum("status", TEST_STATUSES)
    requested_test_type = q_enum("requested_test_type", TEST_TYPES)
    if investigation_id is not None:
        inv = maybe("investigations", investigation_id)
        if inv is not None:
            require_own_account(inv["account_id"])
    if meter_id is not None:
        meter = maybe("meters", meter_id)
        if meter is not None:
            require_own_account(meter["account_id"])

    result = []
    for rec in rows("meter_test_requests"):
        if investigation_id is not None and rec["investigation_id"] != investigation_id:
            continue
        if meter_id is not None and rec["meter_id"] != meter_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if requested_test_type is not None and rec["requested_test_type"] != requested_test_type:
            continue
        result.append(rec)
    if is_customer():
        owned = set(
            i["id"] for i in rows("investigations") if i["account_id"] == g.user_id
        )
        result = [r for r in result if r["investigation_id"] in owned]
    return list_result(result)


@bp.route("/meter-test-requests/<rid>", methods=["GET"])
@endpoint("CustomerServiceRep", "MeterTechnician", "Customer", "BillingSupervisor", "SystemAdmin")
def get_meter_test_request(rid):
    rec = get_or_404("meter_test_requests", rid)
    inv = maybe("investigations", rec["investigation_id"])
    if inv is not None:
        require_own_account(inv["account_id"])
    return object_response(serialize(rec))


@bp.route("/meter-test-requests/<rid>/schedule-field-test", methods=["POST"])
@endpoint("MeterTechnician")
def schedule_field_test(rid):
    body = Body()
    window_start = body.datetime("window_start")
    window_end = body.datetime("window_end")
    rec = get_or_404("meter_test_requests", rid)

    if rec["status"] != "REQUESTED" or rec["requested_test_type"] != "FIELD":
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "only a REQUESTED FIELD test may be scheduled",
        )
    start = parse_dt(window_start)
    end = parse_dt(window_end)
    if not end > start:
        err("ERR_INVALID_STATE_TRANSITION", "window_end must be after window_start")

    meter = maybe("meters", rec["meter_id"])
    last_test = as_dt(meter["last_test_completed_at"]) if meter else None
    if last_test is not None:
        if start < last_test + timedelta(hours=METER_TEST_QUARANTINE_HOURS):
            err(
                "ERR_METER_TEST_QUARANTINE",
                "the window starts inside the post-test quarantine buffer",
            )

    for other in rows("meter_test_requests"):
        if other["id"] == rec["id"]:
            continue
        if other["meter_id"] != rec["meter_id"]:
            continue
        if other["status"] not in ("FIELD_TEST_SCHEDULED", "BENCH_TEST_PENDING"):
            continue
        if other["window_start"] is None or other["window_end"] is None:
            continue
        other_start = as_dt(other["window_start"])
        other_end = as_dt(other["window_end"])
        if start < other_end and other_start < end:
            err(
                "ERR_METER_TEST_WINDOW_CONFLICT",
                "the window overlaps another reserved window on this meter",
            )

    rec["status"] = "FIELD_TEST_SCHEDULED"
    rec["window_start"] = window_start
    rec["window_end"] = window_end
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/meter-test-requests/<rid>/record-field-result", methods=["POST"])
@endpoint("MeterTechnician")
def record_field_result(rid):
    body = Body()
    tested_at = body.datetime("tested_at")
    field_result = body.enum("field_result", FIELD_RESULTS)
    rec = get_or_404("meter_test_requests", rid)

    if rec["status"] != "FIELD_TEST_SCHEDULED":
        err("ERR_INVALID_STATE_TRANSITION", "status must be FIELD_TEST_SCHEDULED")
    moment = parse_dt(tested_at)
    if not (as_dt(rec["window_start"]) <= moment < as_dt(rec["window_end"])):
        err(
            "ERR_TEST_RESULT_OUTSIDE_WINDOW",
            "tested_at must fall inside the reserved half-open window",
        )

    rec["tested_at"] = tested_at
    rec["field_result"] = field_result
    if field_result == "PASS":
        rec["status"] = "CLOSED_PASS"
        touch(rec)
        meter = maybe("meters", rec["meter_id"])
        if meter is not None:
            meter["accuracy_status"] = "VERIFIED_ACCURATE"
            meter["last_test_completed_at"] = tested_at
            touch(meter)
        investigation = maybe("investigations", rec["investigation_id"])
        if investigation is not None:
            _advance_evidence_under_review(investigation)
    else:
        rec["status"] = "BENCH_TEST_PENDING"
        rec["window_start"] = None
        rec["window_end"] = None
        touch(rec)
    return object_response(serialize(rec))


@bp.route("/meter-test-requests/<rid>/record-bench-result", methods=["POST"])
@endpoint("MeterTechnician")
def record_bench_result(rid):
    body = Body()
    tested_at = body.datetime("tested_at")
    low = body.number("low_flow_pct")
    mid = body.number("mid_flow_pct")
    high = body.number("high_flow_pct")
    rec = get_or_404("meter_test_requests", rid)

    if rec["status"] != "BENCH_TEST_PENDING":
        err("ERR_INVALID_STATE_TRANSITION", "status must be BENCH_TEST_PENDING")

    meter = maybe("meters", rec["meter_id"])
    method, accuracy, result, correction_factor = calc.bench_test_accuracy(
        meter["size_inches"], low, mid, high
    )

    rec["tested_at"] = tested_at
    rec["low_flow_pct"] = low
    rec["mid_flow_pct"] = mid
    rec["high_flow_pct"] = high
    rec["accuracy_method"] = method
    rec["accuracy_pct"] = accuracy
    rec["bench_result"] = result
    rec["status"] = {
        "PASS": "CLOSED_PASS",
        "FAST": "CLOSED_FAST",
        "SLOW": "CLOSED_SLOW",
    }[result]
    rec["window_start"] = None
    rec["window_end"] = None

    meter["accuracy_pct"] = accuracy
    meter["correction_factor"] = correction_factor
    meter["last_test_completed_at"] = tested_at
    meter["accuracy_status"] = {
        "PASS": "VERIFIED_ACCURATE",
        "FAST": "FAILED_FAST",
        "SLOW": "FAILED_SLOW",
    }[result]

    account = maybe("service_accounts", meter["account_id"])
    if result in ("FAST", "SLOW") and int(rec["deposit_cents"] or 0) > 0:
        rec["deposit_refunded"] = True
        domain.add_ledger_entry(
            account,
            "CREDIT",
            "METER_TEST_DEPOSIT_REFUND",
            -int(rec["deposit_cents"]),
            bill_id=None,
            source_id=rec["id"],
        )
    touch(rec)
    touch(meter)

    if result == "FAST":
        _apply_fast_correction(meter, correction_factor)

    if account is not None:
        domain.refresh_account(account)

    investigation = maybe("investigations", rec["investigation_id"])
    if investigation is not None:
        _advance_evidence_under_review(investigation)
    return object_response(serialize(rec))


def _apply_fast_correction(meter, correction_factor):
    live = domain.live_reads(meter["id"], types=None)
    if not live:
        return
    target = live[-1]
    prior_value = (
        int(live[-2]["reading_value"]) if len(live) >= 2 else int(meter["initial_register_value"])
    )
    segment = calc.corrected_segment(
        target["reading_value"], prior_value, correction_factor
    )

    rec = base_record()
    rec.update(
        {
            "meter_id": meter["id"],
            "read_date": target["read_date"],
            "read_type": "CORRECTED",
            "reading_value": prior_value + segment,
            "corrects_reading_id": target["id"],
            "superseded_by_reading_id": None,
            "consumption_since_prior_gallons": segment,
        }
    )
    insert("meter_readings", register_new(rec))
    target["superseded_by_reading_id"] = rec["id"]
    touch(target)
    domain.trigger_rebill_pending(meter, as_date(target["read_date"]))


# ---------------------------------------------------------------------------
# RepairProof
# ---------------------------------------------------------------------------
@bp.route("/repair-proofs", methods=["POST"])
@endpoint("Customer", "CustomerServiceRep")
def create_repair_proof():
    body = Body()
    investigation_id = body.string("investigation_id")
    plumber_license_no = body.string("plumber_license_no")
    repair_date = body.date("repair_date")
    leak_type = body.enum("leak_type", LEAK_TYPES)
    invoice_amount_cents = body.integer("invoice_amount_cents", minimum=0)
    description = body.string("description")

    investigation = get_or_404("investigations", investigation_id)
    require_own_account(investigation["account_id"])

    rec = base_record()
    rec.update(
        {
            "investigation_id": investigation["id"],
            "plumber_license_no": plumber_license_no,
            "repair_date": repair_date,
            "leak_type": leak_type,
            "invoice_amount_cents": invoice_amount_cents,
            "description": description,
            "status": "SUBMITTED",
            "verified_by_user_id": None,
            "rejection_reason": None,
        }
    )
    insert("repair_proofs", register_new(rec))
    _advance_evidence_under_review(investigation)
    return created_response(serialize(rec))


@bp.route("/repair-proofs", methods=["GET"])
@endpoint("Customer", "CustomerServiceRep", "BillingSupervisor", "SystemAdmin", "UtilityBoardClerk")
def list_repair_proofs():
    investigation_id = q_str("investigation_id")
    status = q_enum("status", PROOF_STATUSES)
    leak_type = q_enum("leak_type", LEAK_TYPES)
    if investigation_id is not None:
        inv = maybe("investigations", investigation_id)
        if inv is not None:
            require_own_account(inv["account_id"])

    result = []
    for rec in rows("repair_proofs"):
        if investigation_id is not None and rec["investigation_id"] != investigation_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if leak_type is not None and rec["leak_type"] != leak_type:
            continue
        result.append(rec)
    if is_customer():
        owned = set(
            i["id"] for i in rows("investigations") if i["account_id"] == g.user_id
        )
        result = [r for r in result if r["investigation_id"] in owned]
    return list_result(result)


@bp.route("/repair-proofs/<rid>", methods=["GET"])
@endpoint("Customer", "CustomerServiceRep", "BillingSupervisor", "SystemAdmin", "UtilityBoardClerk")
def get_repair_proof(rid):
    rec = get_or_404("repair_proofs", rid)
    inv = maybe("investigations", rec["investigation_id"])
    if inv is not None:
        require_own_account(inv["account_id"])
    return object_response(serialize(rec))


@bp.route("/repair-proofs/<rid>/verify", methods=["POST"])
@endpoint("CustomerServiceRep")
def verify_repair_proof(rid):
    rec = get_or_404("repair_proofs", rid)
    investigation = maybe("investigations", rec["investigation_id"])
    if rec["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "only a SUBMITTED proof may be verified")
    if investigation is None or investigation["status"] != "EVIDENCE_UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "the investigation is not under evidence review")
    bill = maybe("bills", investigation["bill_id"])
    period = domain.period_of_bill(bill) if bill else None
    if period is not None:
        if as_date(rec["repair_date"]) < as_date(period["start_date"]):
            err(
                "ERR_INVALID_STATE_TRANSITION",
                "repair_date precedes the billing period start_date",
            )
    rec["status"] = "VERIFIED"
    rec["verified_by_user_id"] = g.user_id
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/repair-proofs/<rid>/reject", methods=["POST"])
@endpoint("CustomerServiceRep")
def reject_repair_proof(rid):
    body = Body()
    rejection_reason = body.string("rejection_reason")
    rec = get_or_404("repair_proofs", rid)
    investigation = maybe("investigations", rec["investigation_id"])
    if rec["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "only a SUBMITTED proof may be rejected")
    if investigation is None or investigation["status"] != "EVIDENCE_UNDER_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", "the investigation is not under evidence review")

    rec["status"] = "REJECTED"
    rec["rejection_reason"] = rejection_reason
    touch(rec)

    if investigation["evidence_round_count"] < MAX_EVIDENCE_ROUNDS:
        investigation["status"] = "EVIDENCE_REQUESTED"
        investigation["evidence_round_count"] = investigation["evidence_round_count"] + 1
    else:
        investigation["status"] = "EVIDENCE_EXHAUSTED"
    domain.sync_investigation_hold(investigation)
    touch(investigation)
    return object_response(serialize(rec))
