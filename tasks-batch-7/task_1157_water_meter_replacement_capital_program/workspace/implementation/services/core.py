"""Shared business logic: derived fields, serializers, calculations, cascades.

Every rule here traces to PRD section 3 and the scaffold state machines /
calculations tables. Monetary math uses Decimal with ROUND_HALF_UP (PRD 2.6).
"""
import math
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db
from db import base_resource, clock_now, fmt_ts, touch
from errors import raise_err

OPEN_WO_STATES = ("CLOSED", "CANCELLED")  # membership means NOT open
OPEN_COMPLAINT_STATES = ("FILED", "UNDER_REVIEW", "BENCH_TEST_ORDERED")

# Calculation constants (scaffold 1.3)
KNOWN_LOW_CCF = 2
KNOWN_MID_CCF = 20
KNOWN_HIGH_CCF = 30
WEIGHTED_PASS_MIN = Decimal("98.5")
WEIGHTED_PASS_MAX = Decimal("101.5")
LOW_FLOW_MIN = Decimal("95.0")
LOW_FLOW_MAX = Decimal("105.0")
AUDIT_FAIL_PENALTY_BP = 400
SCORE_WINDOW_SIZE = 20
SUSPEND_BELOW_BP = 9200
BONUS_ELIGIBLE_BP = 9800
AMI_MIN_READS = 4
COMM_WINDOW_HOURS = 72
RSSI_MIN_DBM = -95
NO_ACCESS_STRIKE_THRESHOLD = 3
FACTORY_INITIAL_READ_MAX_CCF = 1
MANDATORY_BENCH_VARIANCE_PCT = Decimal("50")
COMPLAINT_MIN_VARIANCE_PCT = Decimal("25")


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def get_or_404(store, rid, label="Resource"):
    obj = store.get(rid)
    if obj is None:
        raise_err("ERR_NOT_FOUND", "%s not found: %s" % (label, rid))
    return obj


def dec(x):
    return Decimal(str(x))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def money_int(value):
    """Decimal -> integer cents, half-up."""
    return int(round_half_up(value, 0))


def pct_float(value):
    """Decimal percentage (2dp) -> JSON number."""
    return float(value)


def whole_days(later, earlier):
    """Whole days between two instants: floor(elapsed seconds / 86400)."""
    return math.floor((later - earlier).total_seconds() / 86400)


# ---------------------------------------------------------------------------
# Relationship traversal
# ---------------------------------------------------------------------------
def wave_of(wo):
    return db.waves.get(wo["wave_id"])


def program_of_work_order(wo):
    wave = wave_of(wo)
    return db.programs.get(wave["program_id"]) if wave else None


def work_orders_of_program(program_id):
    out = []
    for wo in db.work_orders.values():
        wave = db.waves.get(wo["wave_id"])
        if wave and wave["program_id"] == program_id:
            out.append(wo)
    return out


def wave_counts(wave):
    committed = 0
    completed = 0
    for wo in db.work_orders.values():
        if wo["wave_id"] != wave["id"]:
            continue
        if wo["lifecycle_status"] != "CANCELLED":
            committed += 1
        if wo["lifecycle_status"] == "CLOSED":
            completed += 1
    return committed, completed


def program_derived(p):
    """budget_position calculation (scaffold 1.3): integer cents, exact."""
    committed = 0
    completed = 0
    for wo in work_orders_of_program(p["id"]):
        if wo["lifecycle_status"] not in OPEN_WO_STATES:
            committed += wo["committed_amount_cents"]
        if wo["lifecycle_status"] == "CLOSED":
            completed += 1
    spent = sum(
        inv["net_amount_cents"]
        for inv in db.invoices.values()
        if inv["program_id"] == p["id"]
        and inv["status"] == "APPROVED"
        and inv["net_amount_cents"] is not None
    )
    available = p["budget_total_cents"] - committed - spent
    if committed + spent > p["budget_total_cents"]:
        posture = "OVERRUN"
    elif available < (p["budget_total_cents"] * 10) // 100:
        posture = "TIGHT"
    else:
        posture = "FUNDED"
    return committed, spent, available, posture, completed


def contractor_installs_completed(contractor_id):
    return sum(
        1
        for wo in db.work_orders.values()
        if wo["contractor_id"] == contractor_id and wo["lifecycle_status"] == "CLOSED"
    )


# ---------------------------------------------------------------------------
# Serializers (exactly the entity fields + common fields; internals hidden)
# ---------------------------------------------------------------------------
def dump(res, fields, common=True):
    out = {}
    for f in fields:
        v = res.get(f)
        if isinstance(v, datetime):
            v = fmt_ts(v)
        out[f] = v
    if common:
        out["id"] = res["id"]
        out["created_at"] = fmt_ts(res["created_at"])
        out["updated_at"] = fmt_ts(res["updated_at"])
        out["version"] = res["version"]
    return out


PROGRAM_FIELDS = [
    "name", "fiscal_year", "budget_total_cents", "target_meter_count",
    "rate_per_ccf_cents", "default_unit_allowance_cents", "notice_days", "status",
]


def ser_program(p):
    out = dump(p, PROGRAM_FIELDS)
    committed, spent, available, posture, completed = program_derived(p)
    out["budget_committed_cents"] = committed
    out["budget_spent_cents"] = spent
    out["budget_available_cents"] = available
    out["budget_posture"] = posture
    out["completed_meter_count"] = completed
    return out


CONTRACTOR_FIELDS = [
    "program_id", "name", "crew_capacity_per_window", "unit_price_cents",
    "quality_score_bp", "audits_failed_count", "status",
]


def ser_contractor(c):
    out = dump(c, CONTRACTOR_FIELDS)
    out["installs_completed_count"] = contractor_installs_completed(c["id"])
    return out


ACCOUNT_FIELDS = [
    "account_number", "service_address", "meter_location", "customer_name",
    "customer_phone", "priority_tier", "avg_daily_usage_ccf",
    "last_billed_read_value", "last_billed_read_at", "status",
]


def ser_account(a):
    return dump(a, ACCOUNT_FIELDS)


METER_FIELDS = [
    "serial_number", "size_code", "technology", "service_account_id",
    "installed_read_value", "status",
]


def ser_meter(m):
    return dump(m, METER_FIELDS)


WAVE_FIELDS = [
    "program_id", "wave_number", "window_start", "window_end", "capacity", "status",
]


def ser_wave(w):
    out = dump(w, WAVE_FIELDS)
    committed, completed = wave_counts(w)
    out["committed_count"] = committed
    out["completed_count"] = completed
    return out


WORK_ORDER_FIELDS = [
    "wave_id", "service_account_id", "contractor_id", "old_meter_id",
    "new_meter_id", "committed_amount_cents", "provisional_trueup_cents",
    "trueup_amount_cents", "trueup_delta_cents", "no_access_strikes",
    "closed_at", "lifecycle_status", "hold_status",
]


def ser_work_order(wo):
    return dump(wo, WORK_ORDER_FIELDS)


NOTIFICATION_FIELDS = [
    "work_order_id", "no_access_case_id", "channel", "sent_at", "delivered_at",
    "status",
]


def ser_notification(n):
    return dump(n, NOTIFICATION_FIELDS)


APPOINTMENT_FIELDS = [
    "work_order_id", "contractor_id", "slot_date", "window", "attempt_number",
    "status",
]


def ser_appointment(a):
    return dump(a, APPOINTMENT_FIELDS)


CASE_FIELDS = ["work_order_id", "stage", "strikes_at_open", "status", "resolution"]


def ser_case(c):
    return dump(c, CASE_FIELDS)


READING_FIELDS = ["work_order_id", "meter_id", "read_type", "value", "source", "read_at"]


def ser_reading(r):
    # Append-only event: id + created_at only; no updated_at / version (PRD 2.4).
    out = dump(r, READING_FIELDS, common=False)
    out["id"] = r["id"]
    out["created_at"] = fmt_ts(r["created_at"])
    return out


REGISTRATION_FIELDS = [
    "work_order_id", "meter_id", "endpoint_serial", "registered_at",
    "reads_received_count", "rssi_sum_dbm", "status",
]


def ser_registration(r):
    return dump(r, REGISTRATION_FIELDS)


BENCH_TEST_FIELDS = [
    "meter_id", "work_order_id", "complaint_id", "measured_low_ccf",
    "measured_mid_ccf", "measured_high_ccf", "accuracy_low_pct",
    "accuracy_mid_pct", "accuracy_high_pct", "weighted_accuracy_pct", "result",
    "tested_at",
]


def ser_bench_test(b):
    out = dump(b, BENCH_TEST_FIELDS)
    for f in ("accuracy_low_pct", "accuracy_mid_pct", "accuracy_high_pct",
              "weighted_accuracy_pct"):
        out[f] = pct_float(b[f])
    return out


COMPLAINT_FIELDS = [
    "service_account_id", "work_order_id", "claimed_bill_cents",
    "baseline_bill_cents", "billing_period_start", "billing_period_end",
    "variance_pct", "bench_test_id", "adjustment_cents", "adjudication_variant",
    "status",
]


def ser_complaint(c):
    out = dump(c, COMPLAINT_FIELDS)
    out["variance_pct"] = pct_float(c["variance_pct"])
    return out


AUDIT_FIELDS = [
    "work_order_id", "contractor_id", "audit_type", "checks_total",
    "checks_passed", "defects_found", "recorded_at", "result_status",
]


def ser_audit(a):
    return dump(a, AUDIT_FIELDS)


INVOICE_FIELDS = [
    "contractor_id", "program_id", "period_start", "period_end",
    "units_completed", "gross_amount_cents", "bonus_cents", "penalty_cents",
    "retainage_cents", "net_amount_cents", "dispute_reason", "status",
]


def ser_invoice(i):
    return dump(i, INVOICE_FIELDS)


def list_page(values, filters, serializer):
    """Filter (exact match), sort by created_at ascending (PRD 2.3), paginate."""
    from validate import pagination
    from response import ok_list

    items = [
        v for v in values
        if all(str(v.get(k)) == str(val) for k, val in filters.items())
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = pagination()
    page = items[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def swap_trueup_prorated(account, program, swap_clock):
    """PRORATED_ESTIMATE variant (scaffold 1.3 swap_trueup)."""
    days = whole_days(swap_clock, account["last_billed_read_at"])
    usage = round_half_up(dec(account["avg_daily_usage_ccf"]) * days, 2)
    return money_int(usage * program["rate_per_ccf_cents"])


def swap_trueup_measured(final_read_value, account, program):
    """MEASURED variant: (final - last_billed) * rate, half-up whole cents."""
    usage = final_read_value - account["last_billed_read_value"]
    return money_int(dec(usage) * program["rate_per_ccf_cents"])


def bench_weighted_accuracy(low, mid, high):
    """Per-flow accuracies rounded to 2dp FIRST, then weighted (pinned order)."""
    acc_low = round_half_up(dec(low) / KNOWN_LOW_CCF * 100, 2)
    acc_mid = round_half_up(dec(mid) / KNOWN_MID_CCF * 100, 2)
    acc_high = round_half_up(dec(high) / KNOWN_HIGH_CCF * 100, 2)
    weighted = round_half_up(
        Decimal("0.20") * acc_low + Decimal("0.30") * acc_mid
        + Decimal("0.50") * acc_high,
        2,
    )
    result = (
        "PASS"
        if WEIGHTED_PASS_MIN <= weighted <= WEIGHTED_PASS_MAX
        and LOW_FLOW_MIN <= acc_low <= LOW_FLOW_MAX
        else "FAIL"
    )
    return acc_low, acc_mid, acc_high, weighted, result


def recompute_contractor_score(contractor):
    """quality_score_recompute (scaffold 1.3): latest 20 recorded audits,
    recorded_at DESC with created_at (insertion seq) ASC tie-break."""
    recorded = [
        a for a in db.quality_audits.values()
        if a["contractor_id"] == contractor["id"] and a["result_status"] in ("PASS", "FAIL")
    ]
    recorded.sort(key=lambda a: a["_seq"])
    recorded.sort(key=lambda a: a["recorded_at"], reverse=True)
    window = recorded[:SCORE_WINDOW_SIZE]
    fails = sum(1 for a in window if a["result_status"] == "FAIL")
    contractor["quality_score_bp"] = max(0, 10000 - AUDIT_FAIL_PENALTY_BP * fails)
    contractor["audits_failed_count"] = sum(
        1 for a in recorded if a["result_status"] == "FAIL"
    )
    if contractor["quality_score_bp"] < SUSPEND_BELOW_BP and contractor["status"] == "ACTIVE":
        contractor["status"] = "SUSPENDED"
        touch(contractor)


def complaint_variance_pct(claimed, baseline):
    return round_half_up(dec(claimed - baseline) / dec(baseline) * 100, 2)


def complaint_adjustment(complaint):
    """complaint_adjustment (scaffold 1.3), pinned evaluation order:
    FAIL bench test linked -> REGISTRATION_ERROR; else GOODWILL_TIERED."""
    fail_test = None
    for bt in db.bench_tests.values():
        if bt.get("complaint_id") == complaint["id"] and bt["result"] == "FAIL":
            fail_test = bt
            break
    if fail_test is None and complaint.get("bench_test_id"):
        bt = db.bench_tests.get(complaint["bench_test_id"])
        if bt and bt["result"] == "FAIL":
            fail_test = bt
    claimed = complaint["claimed_bill_cents"]
    if fail_test is not None:
        accuracy = fail_test["weighted_accuracy_pct"]
        recovered = money_int(dec(claimed) * 100 / accuracy)
        return claimed - recovered, "REGISTRATION_ERROR"
    excess = claimed - complaint["baseline_bill_cents"]
    variance = complaint["variance_pct"]
    if COMPLAINT_MIN_VARIANCE_PCT <= variance < Decimal("50"):
        rate = Decimal("0.10")
    elif Decimal("50") <= variance < Decimal("100"):
        rate = Decimal("0.20")
    else:
        rate = Decimal("0.30")
    return money_int(dec(excess) * rate), "GOODWILL_TIERED"


def linked_fail_bench_test_exists(complaint):
    for bt in db.bench_tests.values():
        if bt.get("complaint_id") == complaint["id"] and bt["result"] == "FAIL":
            return True
    bt_id = complaint.get("bench_test_id")
    if bt_id:
        bt = db.bench_tests.get(bt_id)
        if bt and bt["result"] == "FAIL":
            return True
    return False


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def wo_cancel_cascade(wo):
    """Shared cancel side effects (PRD 3.3). Caller handles the account
    transition when the driver is an ACCOUNT_EXEMPTED resolution."""
    wo["lifecycle_status"] = "CANCELLED"
    wo["committed_amount_cents"] = 0
    for appt in db.appointments.values():
        if appt["work_order_id"] == wo["id"] and appt["status"] in ("BOOKED", "CONFIRMED"):
            appt["status"] = "SUPERSEDED"
            touch(appt)
    touch(wo)


def account_return_to_eligible_if_clear(account, exclude_wo_id=None):
    for other in db.work_orders.values():
        if (
            other["service_account_id"] == account["id"]
            and other["id"] != exclude_wo_id
            and other["lifecycle_status"] not in OPEN_WO_STATES
        ):
            return
    if account["status"] == "IN_PROGRAM":
        account["status"] = "ELIGIBLE"
        touch(account)


def maybe_release_hold(wo):
    """Hold releases when the work order's last open complaint reaches a
    terminal state (PRD 3.8)."""
    if wo["hold_status"] != "ON_HOLD":
        return
    for c in db.complaints.values():
        if c["work_order_id"] == wo["id"] and c["status"] in OPEN_COMPLAINT_STATES:
            return
    wo["hold_status"] = "CLEAR"
    touch(wo)


def enter_qa_review(wo):
    """RECONCILED -> AMI_VERIFIED -> QA_REVIEW chain (two transitions, two
    version bumps), with 1-in-5 SAMPLED audit creation (PRD 3.6)."""
    wo["lifecycle_status"] = "AMI_VERIFIED"
    touch(wo)
    wo["lifecycle_status"] = "QA_REVIEW"
    touch(wo)
    contractor = db.contractors.get(wo["contractor_id"])
    if contractor is None:
        return
    entered = contractor.setdefault("_qa_review_entered", set())
    if wo["id"] in entered:
        return
    entered.add(wo["id"])
    if len(entered) % 5 == 0:
        audit = base_resource()
        audit.update({
            "work_order_id": wo["id"],
            "contractor_id": wo["contractor_id"],
            "audit_type": "SAMPLED",
            "checks_total": None,
            "checks_passed": None,
            "defects_found": None,
            "recorded_at": None,
            "result_status": "PENDING",
        })
        db.quality_audits[audit["id"]] = audit
