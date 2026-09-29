"""Regulator filings and the five-phase compliance sweep (PRD 3.9)."""

from flask import Blueprint

import calc
import ledger
from auth import ADMIN, authorize
from envelope import created, ok
from errors import ApiError
from store import S, add_days, new_row, serialize, touch
from validation import body_fk, field, json_body, must_exist, validate

bp = Blueprint("reports", __name__)

METRIC_FIELDS = (
    "complaint_count",
    "disability_complaint_count",
    "late_answer_count",
    "tarmac_violation_count",
    "involuntary_denied_boarding_count",
    "refund_obligation_cents_total",
    "overdue_refund_count",
)

REPORT_SPEC = [
    field("policy_profile_id", "string", True),
    field("period_start_utc", "datetime", True),
    field("period_end_utc", "datetime", True),
    field("expected_policy_profile_version", "int", True, min=0),
]


def _scope_booking_ids(policy_profile_id):
    return set(
        b["id"] for b in S.bookings.values() if b["policy_profile_id"] == policy_profile_id
    )


def _by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


@bp.post("/compliance/regulator-reports")
def open_report():
    authorize([ADMIN])
    body = json_body()
    profile = body_fk(body, "policy_profile_id", "policy_profile")
    data = validate(body, REPORT_SPEC)

    if data["expected_policy_profile_version"] != profile["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION")

    start = data["period_start_utc"]
    end = data["period_end_utc"]
    if start >= end:
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")

    # Both ends are inclusive, so sharing a single boundary instant IS an overlap.
    for existing in S.regulator_reports.values():
        if existing["policy_profile_id"] != profile["id"]:
            continue
        if start <= existing["period_end_utc"] and existing["period_start_utc"] <= end:
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP")

    row = new_row(
        {
            "policy_profile_id": profile["id"],
            "period_start_utc": start,
            "period_end_utc": end,
            "status": "DRAFT",
            "complaint_count": 0,
            "disability_complaint_count": 0,
            "late_answer_count": 0,
            "tarmac_violation_count": 0,
            "involuntary_denied_boarding_count": 0,
            "refund_obligation_cents_total": 0,
            "overdue_refund_count": 0,
            "policy_version_pinned": 0,
            "submitted_at_utc": None,
            "amendment_count": 0,
            "amendment_reason": None,
            "submitted_by_user_id": None,
        }
    )
    S.regulator_reports[row["id"]] = row
    profile["report_count"] += 1
    touch(profile)
    return created(serialize(row))


SUBMIT_SPEC = [field("submitted_at_utc", "datetime", True)]


def _in_window(instant, start, end):
    return instant is not None and start <= instant <= end


def _compute_metrics(report):
    booking_ids = _scope_booking_ids(report["policy_profile_id"])
    start = report["period_start_utc"]
    end = report["period_end_utc"]

    complaints = [
        c
        for c in _by_seq(S.consumer_complaints.values())
        if c["booking_id"] in booking_ids and _in_window(c["received_at_utc"], start, end)
    ]
    segment_ids = set(
        s["id"] for s in S.flight_segments.values() if s["booking_id"] in booking_ids
    )
    events = [
        e
        for e in _by_seq(S.tarmac_delay_events.values())
        if e["flight_segment_id"] in segment_ids
        and _in_window(e["tarmac_start_utc"], start, end)
    ]
    records = [
        r
        for r in _by_seq(S.denied_boarding_records.values())
        if r["booking_id"] in booking_ids
        and r["status"] in ("FINALIZED", "RECATEGORIZED")
        and _in_window(r["finalized_at_utc"], start, end)
    ]
    obligations = [
        o
        for o in _by_seq(S.refund_obligations.values())
        if o["booking_id"] in booking_ids
        and _in_window(o["obligation_start_utc"], start, end)
    ]

    cents_total = 0
    for row in obligations:
        if row["settlement_status"] != "VOIDED":
            cents_total += row["amount_cents"]

    return {
        "complaint_count": len(complaints),
        "disability_complaint_count": sum(
            1 for c in complaints if c["category"] == "DISABILITY"
        ),
        "late_answer_count": sum(1 for c in complaints if c["answer_breached"]),
        "tarmac_violation_count": sum(1 for e in events if e["is_violation"]),
        "involuntary_denied_boarding_count": sum(
            1 for r in records if r["effective_category"] == "INVOLUNTARY"
        ),
        "refund_obligation_cents_total": cents_total,
        "overdue_refund_count": sum(1 for o in obligations if o["deadline_breached"]),
    }


@bp.post("/compliance/regulator-reports/<report_id>/submit")
def submit_report(report_id):
    user_id, role = authorize([ADMIN])
    report = must_exist("regulator_report", report_id)
    data = validate(json_body(), SUBMIT_SPEC)

    if report["status"] not in ("DRAFT", "AMENDING"):
        raise ApiError("ERR_REPORT_STATE_INVALID")

    booking_ids = _scope_booking_ids(report["policy_profile_id"])
    for complaint in _by_seq(S.consumer_complaints.values()):
        if complaint["booking_id"] not in booking_ids:
            continue
        if not _in_window(
            complaint["received_at_utc"], report["period_start_utc"], report["period_end_utc"]
        ):
            continue
        if complaint["status"] not in ("ANSWERED", "CLOSED"):
            raise ApiError("ERR_OPEN_COMPLAINT_IN_PERIOD")

    if data["submitted_at_utc"] < report["period_end_utc"]:
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")

    metrics = _compute_metrics(report)
    for name in METRIC_FIELDS:
        report[name] = metrics[name]
    profile = S.policy_profiles.get(report["policy_profile_id"])
    report["policy_version_pinned"] = profile["version"] if profile else 0
    report["status"] = "SUBMITTED"
    report["submitted_at_utc"] = data["submitted_at_utc"]
    report["submitted_by_user_id"] = user_id
    touch(report)
    return ok(serialize(report))


AMEND_SPEC = [
    field("amendment_reason", "string", True, min_len=1, max_len=500),
    field("amended_at_utc", "datetime", True),
]


@bp.post("/compliance/regulator-reports/<report_id>/amend")
def amend_report(report_id):
    authorize([ADMIN])
    report = must_exist("regulator_report", report_id)
    data = validate(json_body(), AMEND_SPEC)

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_STATE_INVALID")
    if report["submitted_at_utc"] is not None and (
        data["amended_at_utc"] < report["submitted_at_utc"]
    ):
        raise ApiError("ERR_PERIOD_BOUNDS_INVALID")

    # The frozen metrics and policy_version_pinned are retained, not cleared.
    report["status"] = "AMENDING"
    report["amendment_count"] += 1
    report["amendment_reason"] = data["amendment_reason"]
    touch(report)
    return ok(serialize(report))


SWEEP_SPEC = [field("policy_profile_id", "string", True)]


@bp.post("/compliance/compliance-sweeps")
def run_sweep():
    authorize([ADMIN])
    body = json_body()
    profile = body_fk(body, "policy_profile_id", "policy_profile")
    validate(body, SWEEP_SPEC)

    now = S.now()
    booking_ids = _scope_booking_ids(profile["id"])
    obligations = [
        o for o in _by_seq(S.refund_obligations.values()) if o["booking_id"] in booking_ids
    ]
    complaints = [
        c for c in _by_seq(S.consumer_complaints.values()) if c["booking_id"] in booking_ids
    ]

    dirty_obligations = []
    dirty_complaints = []
    dirty_passengers = []

    def mark(collection, row):
        if row not in collection:
            collection.append(row)

    deadline_breach_flagged = 0
    election_auto_defaulted = 0
    ack_breach_flagged = 0
    answer_breach_flagged = 0
    auto_closed = 0

    # Phase one -- refund deadline flags.
    for row in obligations:
        if row["deadline_breached"]:
            continue
        if row["settlement_status"] in ("SETTLED", "VOIDED"):
            continue
        if row["deadline_utc"] is not None and now > row["deadline_utc"]:
            row["deadline_breached"] = True
            deadline_breach_flagged += 1
            mark(dirty_obligations, row)

    # Phase two -- election auto-default. Never ELECTED_CREDIT.
    for row in obligations:
        if row["election_status"] != "PENDING_ELECTION":
            continue
        if row["election_deadline_utc"] is None or now <= row["election_deadline_utc"]:
            continue
        booking = S.bookings.get(row["booking_id"])
        row["election_status"] = "ELECTED_CASH"
        row["election_source"] = "AUTO_DEFAULT"
        row["credit_bonus_cents"] = 0
        row["payable_total_cents"] = row["amount_cents"]
        if booking is not None:
            row["settlement_method"] = calc.settlement_method_for("CASH", booking)
        election_auto_defaulted += 1
        mark(dirty_obligations, row)

    # Phase three -- complaint deadline flags.
    for row in complaints:
        flagged = []
        if (
            not row["ack_breached"]
            and row["acknowledged_at_utc"] is None
            and row["ack_due_utc"] is not None
            and now > row["ack_due_utc"]
        ):
            row["ack_breached"] = True
            ack_breach_flagged += 1
            flagged.append("ack_due_utc")
        if (
            not row["answer_breached"]
            and row["status"] not in ("ANSWERED", "CLOSED")
            and row["answer_due_utc"] is not None
            and now > row["answer_due_utc"]
        ):
            row["answer_breached"] = True
            answer_breach_flagged += 1
            flagged.append("answer_due_utc")
        for field_name in flagged:
            ledger.append_activity(
                row["id"], "DEADLINE_BREACH_FLAGGED", now, "system", None, field_name
            )
        if flagged:
            mark(dirty_complaints, row)

    # Phase four -- complaint auto-close, in received_at_utc order.
    for row in sorted(complaints, key=lambda c: (c["received_at_utc"], c["_seq"])):
        if row["status"] != "ANSWERED" or row["answered_at_utc"] is None:
            continue
        if now <= add_days(row["answered_at_utc"], calc.AUTO_CLOSE_DAYS):
            continue
        row["status"] = "CLOSED"
        auto_closed += 1
        mark(dirty_complaints, row)
        ledger.append_activity(row["id"], "AUTO_CLOSED", now, "system", None, "AUTO_CLOSED")
        booking = S.bookings.get(row["booking_id"])
        passenger = ledger.passenger_of(booking) if booking is not None else None
        if passenger is not None:
            ledger.recompute_open_complaints(passenger)
            mark(dirty_passengers, passenger)

    for row in dirty_obligations:
        touch(row)
    for row in dirty_complaints:
        touch(row)
    for row in dirty_passengers:
        touch(row)

    # Phase five -- profile rollup over the flags phases one and three just set.
    segment_ids = set(
        s["id"] for s in S.flight_segments.values() if s["booking_id"] in booking_ids
    )
    violations = sum(
        1
        for e in S.tarmac_delay_events.values()
        if e["flight_segment_id"] in segment_ids and e["is_violation"]
    )
    violations += sum(1 for o in obligations if o["deadline_breached"])
    violations += sum(
        1 for c in complaints if c["ack_breached"] or c["answer_breached"]
    )
    if profile["open_violation_count"] != violations:
        profile["open_violation_count"] = violations
        touch(profile)

    return ok(
        {
            "policy_profile_id": profile["id"],
            "deadline_breach_flagged_count": deadline_breach_flagged,
            "election_auto_defaulted_count": election_auto_defaulted,
            "complaint_ack_breach_flagged_count": ack_breach_flagged,
            "complaint_answer_breach_flagged_count": answer_breach_flagged,
            "complaint_auto_closed_count": auto_closed,
            "open_violation_count": profile["open_violation_count"],
            "policy_profile_version": profile["version"],
        }
    )
