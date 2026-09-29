"""Attendance reporting and tuition invoice verification (PRD 3.5 / 3.6)."""
from decimal import Decimal

from flask import Blueprint, g

from calc import (
    BILLING_CYCLE_DAYS,
    MAX_AMENDMENT_ROUNDS,
    MAX_RESUBMISSION_ROUNDS,
    VARIANCE_TOLERANCE_PCT,
    active_transport_route,
    dec,
    price_invoice,
)
from cascades import approve_payment_cascade
from common import (
    ACCEPT_DECISIONS,
    VERIFICATION_BASES,
    attendance_or_404,
    collection,
    invoice_or_404,
    placement_or_404,
    single,
)
from errors import fail
from middleware import (
    ALL_ROLES,
    FISCAL_OFFICER,
    PLACEMENT_COORDINATOR,
    SCHOOL_BILLING_AGENT,
    check_scope,
    endpoint,
)
from response import created, ok
from store import add_days, db, new_row, parse_date, public, touch
from validation import (
    QUARTER,
    get_cents,
    get_date,
    get_enum,
    get_id,
    get_int,
    get_object_array,
    get_text,
    is_num,
    q_str,
    read_body,
)

bp = Blueprint("billing", __name__)

MAX_COUNT = BILLING_CYCLE_DAYS


# =========================================================================
# attendance record helpers
# =========================================================================

def _validate_lines(body, name, required=False, default=None):
    entries = get_object_array(body, name, required=required, default=default)
    if entries is None:
        return None
    for entry in entries:
        for key in entry.keys():
            if key not in ("service_addendum_id", "hours_delivered"):
                fail("ERR_INVALID_REQUEST",
                     "service delivery lines accept only 'service_addendum_id' and "
                     "'hours_delivered'.")
        addendum_id = entry.get("service_addendum_id")
        if not isinstance(addendum_id, str) or not addendum_id.strip():
            fail("ERR_INVALID_REQUEST", "service_addendum_id must be a non-empty string.")
        hours = entry.get("hours_delivered")
        if hours is None:
            fail("ERR_INVALID_REQUEST", "hours_delivered is required on each service line.")
        if not is_num(hours):
            fail("ERR_INVALID_REQUEST", "hours_delivered must be a number.")
        value = Decimal(str(hours))
        if value < 0:
            fail("ERR_INVALID_REQUEST", "hours_delivered must be at least 0.")
        if (value / QUARTER) % 1 != 0:
            fail("ERR_INVALID_REQUEST",
                 "hours_delivered must be an exact multiple of 0.25.")
    return entries


def _resolve_lines(entries):
    """Rung 5: every named addendum must exist. Returns the resolved rows."""
    resolved = []
    for entry in entries:
        addendum = db.addenda.get(entry["service_addendum_id"])
        if addendum is None:
            fail("ERR_ADDENDUM_NOT_FOUND")
        resolved.append(addendum)
    return resolved


def _check_line_linkage(resolved, placement_id):
    for addendum in resolved:
        if addendum["placement_id"] != placement_id or addendum["status"] != "ACTIVE":
            fail("ERR_ADDENDUM_PLACEMENT_MISMATCH",
                 "Every service line must name an ACTIVE addendum on this placement.")


def _check_period_rules(placement, record_id, period_start, period_end, enrolled, absent):
    # rung 10 - shape
    if period_end != add_days(period_start, BILLING_CYCLE_DAYS - 1):
        fail("ERR_BILLING_PERIOD_SHAPE",
             "The billing cycle must span exactly twenty-eight days.")
    if enrolled + absent > BILLING_CYCLE_DAYS:
        fail("ERR_BILLING_PERIOD_SHAPE",
             "days_enrolled plus days_absent_unexcused may not exceed twenty-eight.")

    # rung 10 - inside the placement window
    if placement is None:
        fail("ERR_PLACEMENT_NOT_FOUND")
    placement_start = parse_date(placement["start_date"])
    placement_end = parse_date(placement["end_date"])
    if (placement_start is None or placement_end is None
            or period_start < placement_start or period_end > placement_end):
        fail("ERR_PERIOD_OUTSIDE_PLACEMENT",
             "The billing cycle is not entirely inside the placement's contracted window.")

    # rung 10 - duplicate or overlapping cycle
    for other in db.attendance.values():
        if other["id"] == record_id:
            continue
        if other["placement_id"] != placement["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "VERIFIED", "DISPUTED"):
            continue
        other_start = parse_date(other["period_start"])
        other_end = parse_date(other["period_end"])
        if other_start is None or other_end is None:
            continue
        if other_start == period_start:
            fail("ERR_DUPLICATE_BILLING_PERIOD",
                 "Another live record already shares this period_start.")
        if period_start <= other_end and other_start <= period_end:
            fail("ERR_DUPLICATE_BILLING_PERIOD",
                 "The cycle overlaps another live record for this placement.")


def _check_counts(enrolled, attended, absent):
    if attended > enrolled:
        fail("ERR_INVALID_REQUEST", "days_attended may not exceed days_enrolled.")
    if attended + absent > enrolled:
        fail("ERR_INVALID_REQUEST",
             "days_attended plus days_absent_unexcused may not exceed days_enrolled.")


# =========================================================================
# attendance records
# =========================================================================

@endpoint(bp, "GET", "/attendance-records", ALL_ROLES)
def list_attendance_records():
    return collection(db.attendance.values(), [
        ("placement_id", q_str("placement_id")),
        ("status", q_str("status")),
    ])


@endpoint(bp, "GET", "/attendance-records/<record_id>", ALL_ROLES)
def get_attendance_record(record_id):
    return single(attendance_or_404(record_id))


@endpoint(bp, "POST", "/attendance-records", (SCHOOL_BILLING_AGENT, PLACEMENT_COORDINATOR))
def create_attendance_record():
    body = read_body((
        "placement_id", "period_start", "period_end", "days_enrolled", "days_attended",
        "days_absent_unexcused", "residential_nights", "service_delivery_lines",
    ))
    placement_id = get_id(body, "placement_id")
    period_start = get_date(body, "period_start")
    period_end = get_date(body, "period_end")
    enrolled = get_int(body, "days_enrolled", minimum=0, maximum=MAX_COUNT)
    attended = get_int(body, "days_attended", minimum=0, maximum=MAX_COUNT)
    absent = get_int(body, "days_absent_unexcused", minimum=0, maximum=MAX_COUNT)
    nights = get_int(body, "residential_nights", required=False, default=0,
                     minimum=0, maximum=MAX_COUNT)
    lines = _validate_lines(body, "service_delivery_lines", required=False, default=[])
    _check_counts(enrolled, attended, absent)

    placement = placement_or_404(placement_id)
    resolved = _resolve_lines(lines)

    if placement["placement_type"] == "DAY" and nights != 0:
        fail("ERR_INVALID_REQUEST",
             "residential_nights must be exactly 0 on a DAY placement.")

    check_scope(placement)
    _check_line_linkage(resolved, placement_id)
    _check_period_rules(placement, None, period_start, period_end, enrolled, absent)

    row = new_row("attendance", {
        "placement_id": placement_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "days_enrolled": enrolled,
        "days_attended": attended,
        "days_absent_unexcused": absent,
        "residential_nights": nights,
        "service_delivery_lines": lines,
        "status": "SUBMITTED",
        "verified_by_user_id": None,
        "amendment_round": 0,
    })
    db.attendance[row["id"]] = row
    return created(public(row))


@endpoint(bp, "POST", "/attendance-records/<record_id>/verify", (PLACEMENT_COORDINATOR,))
def verify_attendance_record(record_id):
    record = attendance_or_404(record_id)
    body = read_body(("decision", "dispute_reason"))
    decision = get_enum(body, "decision", ACCEPT_DECISIONS)
    get_text(body, "dispute_reason", required=False, default=None)

    if record["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a SUBMITTED attendance record may be disposed of.")

    placement = db.placements.get(record["placement_id"])
    if decision == "ACCEPT":
        if placement is None or placement["status"] not in (
                "ACTIVE", "TERMINATED", "RETURNED_TO_DISTRICT"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Attendance may only be accepted on an active or closed placement.")
        record["status"] = "VERIFIED"
        record["verified_by_user_id"] = g.user_id
        touch(record)
        for entry in record["service_delivery_lines"] or []:
            addendum = db.addenda.get(entry.get("service_addendum_id"))
            if addendum is None:
                continue
            addendum["delivered_hours_ytd"] = (
                dec(addendum["delivered_hours_ytd"]) + dec(entry.get("hours_delivered", 0))
            )
            touch(addendum)
    else:
        record["status"] = "DISPUTED"
        record["verified_by_user_id"] = g.user_id
        touch(record)
    return ok(public(record))


@endpoint(bp, "POST", "/attendance-records/<record_id>/amend", (SCHOOL_BILLING_AGENT,))
def amend_attendance_record(record_id):
    record = attendance_or_404(record_id)
    body = read_body((
        "days_enrolled", "days_attended", "days_absent_unexcused", "residential_nights",
        "service_delivery_lines",
    ))
    enrolled = get_int(body, "days_enrolled", minimum=0, maximum=MAX_COUNT)
    attended = get_int(body, "days_attended", minimum=0, maximum=MAX_COUNT)
    absent = get_int(body, "days_absent_unexcused", minimum=0, maximum=MAX_COUNT)
    nights = get_int(body, "residential_nights", required=False,
                     default=record["residential_nights"], minimum=0, maximum=MAX_COUNT)
    lines = _validate_lines(body, "service_delivery_lines", required=False,
                            default=record["service_delivery_lines"])
    _check_counts(enrolled, attended, absent)

    placement = db.placements.get(record["placement_id"])
    resolved = _resolve_lines(lines)

    if placement is not None and placement["placement_type"] == "DAY" and nights != 0:
        fail("ERR_INVALID_REQUEST",
             "residential_nights must be exactly 0 on a DAY placement.")

    if placement is not None:
        check_scope(placement)

    if record["status"] != "DISPUTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a DISPUTED attendance record may be amended.")

    _check_line_linkage(resolved, record["placement_id"])
    period_start = parse_date(record["period_start"])
    period_end = parse_date(record["period_end"])
    _check_period_rules(placement, record["id"], period_start, period_end, enrolled, absent)

    if record["amendment_round"] >= MAX_AMENDMENT_ROUNDS:
        fail("ERR_MAX_ROUNDS_EXCEEDED",
             "The amendment cycle is bounded at two rounds.")

    record["days_enrolled"] = enrolled
    record["days_attended"] = attended
    record["days_absent_unexcused"] = absent
    record["residential_nights"] = nights
    record["service_delivery_lines"] = lines
    record["status"] = "SUBMITTED"
    record["amendment_round"] += 1
    record["verified_by_user_id"] = None
    touch(record)
    return ok(public(record))


# =========================================================================
# tuition invoices
# =========================================================================

@endpoint(bp, "GET", "/tuition-invoices", ALL_ROLES)
def list_invoices():
    return collection(db.invoices.values(), [
        ("placement_id", q_str("placement_id")),
        ("attendance_record_id", q_str("attendance_record_id")),
        ("verification_status", q_str("verification_status")),
        ("payment_status", q_str("payment_status")),
    ])


@endpoint(bp, "GET", "/tuition-invoices/<invoice_id>", ALL_ROLES)
def get_invoice(invoice_id):
    return single(invoice_or_404(invoice_id))


@endpoint(bp, "POST", "/tuition-invoices", (SCHOOL_BILLING_AGENT, FISCAL_OFFICER))
def create_invoice():
    body = read_body((
        "placement_id", "attendance_record_id", "billing_period_start",
        "billing_period_end", "submitted_amount_cents", "transport_days_billed",
        "expected_placement_version",
    ))
    placement_id = get_id(body, "placement_id")
    record_id = get_id(body, "attendance_record_id")
    period_start = get_date(body, "billing_period_start")
    period_end = get_date(body, "billing_period_end")
    submitted = get_cents(body, "submitted_amount_cents", minimum=0)
    transport_days = get_int(body, "transport_days_billed", required=False, default=0,
                             minimum=0, maximum=MAX_COUNT)
    expected_version = get_int(body, "expected_placement_version", minimum=0)

    placement = placement_or_404(placement_id)
    record = attendance_or_404(record_id)

    if (period_start.isoformat() != record["period_start"]
            or period_end.isoformat() != record["period_end"]):
        fail("ERR_INVALID_REQUEST",
             "billing_period_start and billing_period_end must restate the record's cycle.")

    check_scope(placement)

    if expected_version != placement["version"]:
        fail("ERR_STALE_PLACEMENT_VERSION")

    if record["placement_id"] != placement_id:
        fail("ERR_ATTENDANCE_PLACEMENT_MISMATCH",
             "The attendance record belongs to a different placement.")

    for existing in db.invoices.values():
        if existing["attendance_record_id"] != record_id:
            continue
        if (existing["verification_status"] in ("SUBMITTED", "VERIFIED")
                and existing["payment_status"] != "VOIDED"):
            fail("ERR_DUPLICATE_RESOURCE",
                 "A live invoice already exists for this attendance record.")

    row = new_row("invoice", {
        "placement_id": placement_id,
        "attendance_record_id": record_id,
        "billing_period_start": period_start.isoformat(),
        "billing_period_end": period_end.isoformat(),
        "submitted_amount_cents": submitted,
        "transport_days_billed": transport_days,
        "verification_basis": None,
        "tuition_line_cents": 0,
        "residential_line_cents": 0,
        "service_lines_total_cents": 0,
        "transport_line_cents": 0,
        "gross_billable_cents": 0,
        "volume_credit_cents": 0,
        "admin_fee_cents": 0,
        "provisional_amount_cents": 0,
        "final_amount_cents": 0,
        "verified_amount_cents": 0,
        "variance_pct": 0,
        "settled_amount_cents": 0,
        "verification_status": "SUBMITTED",
        "payment_status": "UNPAID",
        "verified_by_user_id": None,
        "approved_by_user_id": None,
        "resubmission_round": 0,
    })
    db.invoices[row["id"]] = row
    return created(public(row))


@endpoint(bp, "POST", "/tuition-invoices/<invoice_id>/verify",
          (PLACEMENT_COORDINATOR, FISCAL_OFFICER))
def verify_invoice(invoice_id):
    invoice = invoice_or_404(invoice_id)
    body = read_body(("basis",))
    basis = get_enum(body, "basis", VERIFICATION_BASES)

    if invoice["verification_status"] != "SUBMITTED" or invoice["payment_status"] != "UNPAID":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a SUBMITTED, UNPAID invoice may be verified.")

    record = db.attendance.get(invoice["attendance_record_id"])
    if record is None or record["status"] != "VERIFIED":
        fail("ERR_ATTENDANCE_NOT_VERIFIED",
             "The linked attendance record has not been verified by the district.")

    placement = db.placements.get(invoice["placement_id"])
    route = active_transport_route(invoice["placement_id"])
    if invoice["transport_days_billed"] > 0 and route is None:
        fail("ERR_TRANSPORT_NOT_ASSIGNED",
             "Transport days were billed but the placement has no ACTIVE assignment.")

    schedule = db.rate_schedules.get(placement["rate_schedule_id"]) if placement else None
    if schedule is None:
        fail("ERR_RATE_SCHEDULE_NOT_FOUND")

    computed = price_invoice(invoice, placement, schedule, record, basis, route)
    invoice.update(computed)
    invoice["verified_by_user_id"] = g.user_id
    if computed["variance_pct"] > VARIANCE_TOLERANCE_PCT:
        invoice["verification_status"] = "DISPUTED"
    else:
        invoice["verification_status"] = "VERIFIED"
    touch(invoice)
    return ok(public(invoice))


@endpoint(bp, "POST", "/tuition-invoices/<invoice_id>/resubmit", (SCHOOL_BILLING_AGENT,))
def resubmit_invoice(invoice_id):
    invoice = invoice_or_404(invoice_id)
    body = read_body(("submitted_amount_cents", "transport_days_billed"))
    submitted = get_cents(body, "submitted_amount_cents", minimum=0)
    transport_days = get_int(body, "transport_days_billed", required=False,
                             default=invoice["transport_days_billed"],
                             minimum=0, maximum=MAX_COUNT)

    placement = db.placements.get(invoice["placement_id"])
    if placement is not None:
        check_scope(placement)

    if invoice["verification_status"] != "DISPUTED" or invoice["payment_status"] != "UNPAID":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a DISPUTED, UNPAID invoice may be resubmitted.")
    if invoice["resubmission_round"] >= MAX_RESUBMISSION_ROUNDS:
        fail("ERR_MAX_ROUNDS_EXCEEDED",
             "The resubmission cycle is bounded at two rounds.")

    invoice["submitted_amount_cents"] = submitted
    invoice["transport_days_billed"] = transport_days
    invoice["verification_status"] = "SUBMITTED"
    invoice["resubmission_round"] += 1
    invoice["verification_basis"] = None
    invoice["verified_by_user_id"] = None
    invoice["verified_amount_cents"] = 0
    invoice["variance_pct"] = 0
    touch(invoice)
    return ok(public(invoice))


@endpoint(bp, "POST", "/tuition-invoices/<invoice_id>/approve-payment", (FISCAL_OFFICER,))
def approve_invoice_payment(invoice_id):
    invoice = invoice_or_404(invoice_id)
    read_body(())

    if invoice["verification_status"] != "VERIFIED" or invoice["payment_status"] != "UNPAID":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a VERIFIED, UNPAID invoice may be approved for payment.")

    if g.user_id == invoice["verified_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The payment approver must differ from the invoice's verifier.")

    record = db.attendance.get(invoice["attendance_record_id"])
    if record is None or record["status"] != "VERIFIED":
        fail("ERR_ATTENDANCE_NOT_VERIFIED",
             "The linked attendance record is no longer VERIFIED.")

    placement = db.placements.get(invoice["placement_id"])
    if placement is None:
        fail("ERR_PLACEMENT_NOT_FOUND")
    remaining = placement["contract_encumbrance_cents"] - placement["paid_total_ytd_cents"]
    if remaining < invoice["verified_amount_cents"]:
        fail("ERR_ENCUMBRANCE_EXCEEDED",
             "The placement's remaining contract commitment cannot cover this invoice.")

    approve_payment_cascade(invoice, placement, g.user_id)
    return ok(public(invoice))
