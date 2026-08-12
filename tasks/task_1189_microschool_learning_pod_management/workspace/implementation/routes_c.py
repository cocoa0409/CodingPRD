"""Routes: Seat, TuitionInvoice, Payment."""
from flask import Blueprint

from core import (
    DB, auth, ok, ok_list, body, err, bad_request, not_found, invalid_state, forbidden,
    req_str, req_int, req_enum, req_date,
    new_resource, new_ledger_entry, touch, get_or_404, sorted_items,
    logical_today, logical_now_iso, parse_date_val, pod_gate,
    recompute_enrolled_count, refresh_posture, recompute_compliance,
    recompute_invoice_paid, recompute_seat_paid, settle_invoice_after_payment,
    recompute_funding, recompute_voucher_accepted, compute_invoice_money,
    prorated_enrollment, earned_through, withdrawal_refund, grade_band_for,
    create_claim,
)
from routes_a import request_arg

bp = Blueprint("c", __name__)


def _seat_in_pod(pod_id, seat_id):
    s = DB["seats"].get(seat_id)
    if s is None or s["pod_id"] != pod_id:
        not_found("Seat '%s' does not exist for this pod" % seat_id)
    return s


def _invoice_in_seat(seat_id, invoice_id):
    inv = DB["invoices"].get(invoice_id)
    if inv is None or inv["seat_id"] != seat_id:
        not_found("TuitionInvoice '%s' does not exist for this seat" % invoice_id)
    return inv


def _family_owns_seat_or_403(uid, role, seat):
    if role != "Family":
        return
    stu = DB["students"].get(seat["student_id"])
    if stu is None or stu["family_id"] != uid:
        forbidden("Family callers may only act on their own seats")


# ---------------------------------------------------------------------------
# Seat
# ---------------------------------------------------------------------------

@bp.post("/pods/<id>/seats")
def create_seat(id):
    auth("Registrar")
    p = get_or_404("pods", id, "Pod")
    b = body()
    student_id = req_str(b, "student_id")
    enrolled_on = req_date(b, "enrolled_on")
    stu = DB["students"].get(student_id)
    if stu is None:
        not_found("Student '%s' does not exist" % student_id)
    # posture gate, then duplicate-seat uniqueness, then term window
    pod_gate(p, block_frozen=True, block_closed=True)
    for s in DB["seats"].values():
        if s["pod_id"] == id and s["student_id"] == student_id \
                and s["seat_status"] in ("RESERVED", "ENROLLED"):
            err("ERR_DUPLICATE_SEAT", 422,
                "A RESERVED or ENROLLED seat already exists for this student in this pod")
    ts = parse_date_val(p["term_start_date"])
    te = parse_date_val(p["term_end_date"])
    if not (ts <= enrolled_on <= te):
        err("ERR_ENROLLMENT_OUT_OF_TERM", 422,
            "enrolled_on lies outside the pod's term window")
    s = new_resource()
    s.update({
        "pod_id": id,
        "student_id": student_id,
        "reserved_at": logical_now_iso(),
        "enrolled_on": enrolled_on.isoformat(),
        "withdrawn_on": None,
        "seat_status": "RESERVED",
        "tuition_basis_cents": None,
        "prorated_due_cents": None,
        "paid_cents": 0,
        "refund_due_cents": 0,
    })
    DB["seats"][s["id"]] = s
    if stu.get("esa_account_id"):
        v = DB["vouchers"].get(stu["esa_account_id"])
        if v is not None:
            recompute_voucher_accepted(v)
    return ok(s, 201)


@bp.get("/pods/<id>/seats")
def list_pod_seats(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Registrar", "Guide", "Family")
    get_or_404("pods", id, "Pod")
    items = [s for s in sorted_items(DB["seats"]) if s["pod_id"] == id]
    st = request_arg("seat_status")
    if st is not None:
        items = [s for s in items if s["seat_status"] == st]
    sid = request_arg("student_id")
    if sid is not None:
        items = [s for s in items if s["student_id"] == sid]
    return ok_list(items)


@bp.get("/seats/<id>")
def get_seat(id):
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Registrar", "Family")
    return ok(get_or_404("seats", id, "Seat"))


@bp.get("/seats")
def list_seats():
    auth("PlatformAdmin", "PodOperator", "ComplianceOfficer", "Registrar")
    items = sorted_items(DB["seats"])
    pid = request_arg("pod_id")
    if pid is not None:
        items = [s for s in items if s["pod_id"] == pid]
    sid = request_arg("student_id")
    if sid is not None:
        items = [s for s in items if s["student_id"] == sid]
    st = request_arg("seat_status")
    if st is not None:
        items = [s for s in items if s["seat_status"] == st]
    return ok_list(items)


@bp.post("/pods/<id>/seats/<seat_id>/enroll")
def enroll_seat(id, seat_id):
    uid, role = auth("Family")
    p = get_or_404("pods", id, "Pod")
    s = _seat_in_pod(id, seat_id)
    b = body()
    expected = req_int(b, "expected_pod_version")
    _family_owns_seat_or_403(uid, role, s)

    # state-level preconditions
    if s["seat_status"] != "RESERVED":
        invalid_state("Seat must be RESERVED to enroll")
    # posture gate (PRD 2.8: a FROZEN pod refuses enrolling a reserved seat
    # with ERR_POD_FROZEN; a SUSPENDED pod's posture is FROZEN per PRD 3.4)
    if p["posture"] not in ("OPEN", "RESTRICTED"):
        err("ERR_POD_FROZEN", 409, "Pod posture %s blocks enrollment" % p["posture"])
    if p["status"] != "ACTIVE":
        invalid_state("Pod must be ACTIVE to enroll a seat")
    stu = DB["students"].get(s["student_id"])
    if stu is None:
        not_found("Student does not exist")
    if stu["student_status"] != "APPLICANT":
        invalid_state("Student must be an APPLICANT to enroll")
    # optimistic concurrency on the pod
    if expected != p["version"]:
        err("ERR_STALE_VERSION", 412, "expected_pod_version does not match the pod's current version")
    # capacity, then term window
    if p["enrolled_count"] + 1 > p["seat_capacity"]:
        err("ERR_CAPACITY_FULL", 422, "Enrolling would exceed the pod's seat capacity")
    eon = parse_date_val(s["enrolled_on"])
    ts = parse_date_val(p["term_start_date"])
    te = parse_date_val(p["term_end_date"])
    if not (ts <= eon <= te):
        err("ERR_ENROLLMENT_OUT_OF_TERM", 422,
            "enrolled_on lies outside the pod's term window")
    # voucher acceptance
    if stu.get("esa_account_id"):
        v = DB["vouchers"].get(stu["esa_account_id"])
        if v is None or not v.get("accepted_by_pod"):
            err("ERR_INSUFFICIENT_VOUCHER_FUNDS", 422,
                "Linked voucher account is not accepted by the pod")
    # guide coverage on the enrollment date
    covered = any(
        a["pod_id"] == id and a["assignment_status"] in ("SCHEDULED", "ACTIVE")
        and parse_date_val(a["window_start_date"]) <= eon <= parse_date_val(a["window_end_date"])
        for a in DB["assignments"].values()
    )
    if not covered:
        invalid_state("Pod has no SCHEDULED/ACTIVE guide assignment covering enrolled_on")

    # effects
    s["seat_status"] = "ENROLLED"
    s["tuition_basis_cents"] = p["tuition_full_year_cents"]
    s["prorated_due_cents"] = prorated_enrollment(p, eon)
    touch(s)
    stu["student_status"] = "ENROLLED"
    stu["grade_band"] = grade_band_for(parse_date_val(stu["date_of_birth"]), ts)
    touch(stu)
    fam = DB["families"].get(stu["family_id"])
    if fam is not None and fam["family_status"] != "ACTIVE":
        fam["family_status"] = "ACTIVE"
        touch(fam)
    recompute_enrolled_count(p)
    refresh_posture(p)
    touch(p)
    recompute_compliance(p)
    refresh_posture(p)
    if stu.get("esa_account_id"):
        v = DB["vouchers"].get(stu["esa_account_id"])
        if v is not None:
            recompute_voucher_accepted(v)
    return ok(s)


@bp.post("/pods/<id>/seats/<seat_id>/withdraw")
def withdraw_seat(id, seat_id):
    uid, role = auth("Family")
    p = get_or_404("pods", id, "Pod")
    s = _seat_in_pod(id, seat_id)
    b = body()
    won = req_date(b, "withdrawn_on")
    _family_owns_seat_or_403(uid, role, s)

    if s["seat_status"] != "ENROLLED":
        invalid_state("Seat must be ENROLLED to withdraw")
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        invalid_state("Pod status %s does not permit withdrawal" % p["status"])
    pod_gate(p, block_frozen=True, block_closed=True)
    if won < logical_today():
        bad_request("withdrawn_on must not precede the current date")

    s["seat_status"] = "WITHDRAWN"
    s["withdrawn_on"] = won.isoformat()
    s["prorated_due_cents"] = earned_through(p, s, won)
    touch(s)
    stu = DB["students"].get(s["student_id"])
    if stu is not None and stu["student_status"] != "WITHDRAWN":
        stu["student_status"] = "WITHDRAWN"
        touch(stu)
    recompute_enrolled_count(p)
    refresh_posture(p)
    touch(p)
    recompute_compliance(p)
    refresh_posture(p)
    # refund claim priced by the sliding-scale rule
    create_claim(p, s, "WITHDRAWAL", withdrawal_refund(p, s), uid)
    # reconcile open invoices
    for inv in DB["invoices"].values():
        if inv["seat_id"] != seat_id or inv["invoice_status"] not in ("DRAFT", "ISSUED"):
            continue
        if inv["total_cents"] > s["prorated_due_cents"]:
            inv["invoice_status"] = "WRITTEN_OFF"
            touch(inv)
        else:
            new_st = None
            if inv["paid_cents"] >= inv["total_cents"]:
                new_st = "PAID"
            elif inv["paid_cents"] > 0:
                new_st = "PARTIALLY_PAID"
            if new_st and new_st != inv["invoice_status"]:
                inv["invoice_status"] = new_st
                touch(inv)
    return ok(s)


# ---------------------------------------------------------------------------
# TuitionInvoice
# ---------------------------------------------------------------------------

def _validate_line_items(raw):
    if not isinstance(raw, list):
        bad_request("line_items must be an array")
    items = []
    for i, li in enumerate(raw):
        if not isinstance(li, dict):
            bad_request("line_items[%d] must be an object" % i)
        desc = li.get("description")
        if not isinstance(desc, str) or desc == "":
            bad_request("line_items[%d].description must be a non-empty string" % i)
        qty = li.get("quantity")
        if not (isinstance(qty, (int, float)) and not isinstance(qty, bool)):
            bad_request("line_items[%d].quantity must be a number" % i)
        amt = li.get("unit_amount_cents")
        if not (isinstance(amt, int) and not isinstance(amt, bool)):
            bad_request("line_items[%d].unit_amount_cents must be an integer" % i)
        kind = li.get("kind")
        if kind not in ("TUITION", "FEE", "CREDIT"):
            bad_request("line_items[%d].kind must be one of TUITION, FEE, CREDIT" % i)
        items.append({"description": desc, "quantity": qty,
                      "unit_amount_cents": amt, "kind": kind})
    return items


@bp.post("/pods/<id>/seats/<seat_id>/invoices")
def create_invoice(id, seat_id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    s = _seat_in_pod(id, seat_id)
    b = body()
    pod_gate(p, block_frozen=False, block_closed=True)
    bps = req_date(b, "billing_period_start")
    bpe = req_date(b, "billing_period_end")
    due = req_date(b, "due_date")
    items = _validate_line_items(b.get("line_items"))
    if bps > bpe or due < bpe:
        err("ERR_INVALID_INVOICE_PERIOD", 422,
            "billing_period_start must not exceed billing_period_end and due_date must not precede billing_period_end")
    inv = new_resource()
    inv.update({
        "seat_id": seat_id,
        "billing_period_start": bps.isoformat(),
        "billing_period_end": bpe.isoformat(),
        "line_items": items,
        "subtotal_cents": 0,
        "admin_fee_cents": 0,
        "total_cents": 0,
        "paid_cents": 0,
        "invoice_status": "DRAFT",
        "due_date": due.isoformat(),
        "_pod_id": id,
    })
    compute_invoice_money(p, inv)
    DB["invoices"][inv["id"]] = inv
    return ok(inv, 201)


@bp.get("/pods/<id>/seats/<seat_id>/invoices")
def list_seat_invoices(id, seat_id):
    auth("PlatformAdmin", "PodOperator", "Registrar", "Family")
    get_or_404("pods", id, "Pod")
    _seat_in_pod(id, seat_id)
    items = [i for i in sorted_items(DB["invoices"]) if i["seat_id"] == seat_id]
    st = request_arg("invoice_status")
    if st is not None:
        items = [i for i in items if i["invoice_status"] == st]
    return ok_list(items)


@bp.get("/invoices/<id>")
def get_invoice(id):
    auth("PlatformAdmin", "PodOperator", "Registrar", "Family")
    return ok(get_or_404("invoices", id, "TuitionInvoice"))


@bp.get("/invoices")
def list_invoices():
    auth("PlatformAdmin", "PodOperator", "Registrar")
    items = sorted_items(DB["invoices"])
    sid = request_arg("seat_id")
    if sid is not None:
        items = [i for i in items if i["seat_id"] == sid]
    st = request_arg("invoice_status")
    if st is not None:
        items = [i for i in items if i["invoice_status"] == st]
    return ok_list(items)


@bp.post("/pods/<id>/seats/<seat_id>/invoices/<invoice_id>/issue")
def issue_invoice(id, seat_id, invoice_id):
    auth("PodOperator")
    p = get_or_404("pods", id, "Pod")
    s = _seat_in_pod(id, seat_id)
    inv = _invoice_in_seat(seat_id, invoice_id)
    if inv["invoice_status"] != "DRAFT":
        invalid_state("Only a DRAFT invoice can be issued")
    if s["seat_status"] != "ENROLLED":
        invalid_state("Seat must be ENROLLED to issue an invoice")
    compute_invoice_money(p, inv)
    inv["invoice_status"] = "ISSUED"
    touch(inv)
    return ok(inv)


@bp.post("/pods/<id>/seats/<seat_id>/invoices/<invoice_id>/write-off")
def write_off_invoice(id, seat_id, invoice_id):
    auth("PodOperator")
    get_or_404("pods", id, "Pod")
    s = _seat_in_pod(id, seat_id)
    inv = _invoice_in_seat(seat_id, invoice_id)
    if inv["invoice_status"] not in ("ISSUED", "OVERDUE"):
        invalid_state("Only an ISSUED or OVERDUE invoice can be written off")
    if s["seat_status"] != "WITHDRAWN":
        invalid_state("Seat must be WITHDRAWN to write off an invoice")
    if inv["paid_cents"] != 0:
        err("ERR_INVOICE_HAS_PAYMENTS", 422,
            "Invoice carries cleared payments and must be refunded rather than written off")
    inv["invoice_status"] = "WRITTEN_OFF"
    touch(inv)
    return ok(inv)


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

@bp.post("/pods/<id>/seats/<seat_id>/invoices/<invoice_id>/payments")
def create_payment(id, seat_id, invoice_id):
    uid, role = auth("Family", "Registrar")
    p = get_or_404("pods", id, "Pod")
    s = _seat_in_pod(id, seat_id)
    inv = _invoice_in_seat(seat_id, invoice_id)
    b = body()
    _family_owns_seat_or_403(uid, role, s)
    pod_gate(p, block_frozen=False, block_closed=True)
    source = req_enum(b, "source_kind", ("FAMILY", "VOUCHER", "SCHOLARSHIP", "REFUND_REVERSAL"))
    amount = req_int(b, "amount_cents", min_v=1)
    voucher_id = b.get("voucher_account_id")
    if source == "VOUCHER":
        if voucher_id is None:
            bad_request("voucher_account_id is required when source_kind is VOUCHER")
        if not isinstance(voucher_id, str):
            bad_request("voucher_account_id must be a string")
    elif voucher_id is not None:
        bad_request("voucher_account_id is only allowed when source_kind is VOUCHER")
    if inv["invoice_status"] in ("PAID", "WRITTEN_OFF"):
        invalid_state("Invoice in status %s cannot accept payments" % inv["invoice_status"])
    voucher = None
    if source == "VOUCHER":
        voucher = DB["vouchers"].get(voucher_id)
        if voucher is None:
            not_found("VoucherAccount '%s' does not exist" % voucher_id)
        _voucher_funds_check(voucher, amount)
    # PRD 3.7 overpayment ceiling is defined over "cumulative cleared
    # payments" — a freshly posted payment is PENDING and counts only when
    # cleared, so the ceiling is enforced at clear time (see clear_payment).
    pay = new_ledger_entry()
    pay.update({
        "invoice_id": invoice_id,
        "seat_id": seat_id,
        "source_kind": source,
        "voucher_account_id": voucher_id if source == "VOUCHER" else None,
        "amount_cents": amount,
        "paid_at": logical_now_iso(),
        "payment_status": "PENDING",
        "_pod_id": id,
    })
    DB["payments"][pay["id"]] = pay
    return ok(pay, 201)


def _voucher_funds_check(voucher, amount):
    if voucher["verification_status"] != "VERIFIED" \
            or voucher["funding_status"] == "FROZEN" \
            or voucher["disbursable_balance_cents"] < amount:
        err("ERR_INSUFFICIENT_VOUCHER_FUNDS", 422,
            "Voucher is not VERIFIED, is FROZEN, or lacks sufficient disbursable balance")


@bp.get("/payments/<id>")
def get_payment(id):
    auth("PlatformAdmin", "PodOperator", "Registrar", "Family")
    return ok(get_or_404("payments", id, "Payment"))


@bp.get("/payments")
def list_payments():
    auth("PlatformAdmin", "PodOperator", "Registrar")
    items = sorted_items(DB["payments"])
    for param, field in (("invoice_id", "invoice_id"), ("seat_id", "seat_id"),
                         ("voucher_account_id", "voucher_account_id"),
                         ("payment_status", "payment_status"), ("source_kind", "source_kind")):
        v = request_arg(param)
        if v is not None:
            items = [p for p in items if p.get(field) == v]
    return ok_list(items)


@bp.get("/pods/<id>/seats/<seat_id>/invoices/<invoice_id>/payments")
def list_invoice_payments(id, seat_id, invoice_id):
    auth("PlatformAdmin", "PodOperator", "Registrar", "Family")
    get_or_404("pods", id, "Pod")
    _seat_in_pod(id, seat_id)
    _invoice_in_seat(seat_id, invoice_id)
    items = [p for p in sorted_items(DB["payments"]) if p["invoice_id"] == invoice_id]
    st = request_arg("payment_status")
    if st is not None:
        items = [p for p in items if p["payment_status"] == st]
    sk = request_arg("source_kind")
    if sk is not None:
        items = [p for p in items if p["source_kind"] == sk]
    return ok_list(items)


@bp.post("/payments/<id>/clear")
def clear_payment(id):
    auth("PodOperator")
    pay = get_or_404("payments", id, "Payment")
    if pay["payment_status"] != "PENDING":
        invalid_state("Only a PENDING payment can be cleared")
    inv = DB["invoices"].get(pay["invoice_id"])
    voucher = None
    if pay["source_kind"] == "VOUCHER":
        voucher = DB["vouchers"].get(pay["voucher_account_id"])
        if voucher is None:
            not_found("VoucherAccount does not exist")
        _voucher_funds_check(voucher, pay["amount_cents"])
    if pay["source_kind"] in ("FAMILY", "SCHOLARSHIP") and inv is not None:
        if inv["paid_cents"] + pay["amount_cents"] > inv["total_cents"]:
            err("ERR_OVERPAYMENT", 422,
                "Cleared payments against the invoice may not exceed its total_cents")
    pay["payment_status"] = "CLEARED"
    if voucher is not None:
        voucher["disbursable_balance_cents"] -= pay["amount_cents"]
        recompute_funding(voucher)
        touch(voucher)
        recompute_voucher_accepted(voucher)
    if inv is not None:
        recompute_invoice_paid(inv)
        settle_invoice_after_payment(inv)
        touch(inv)
    seat = DB["seats"].get(pay["seat_id"])
    if seat is not None:
        recompute_seat_paid(seat)
        touch(seat)
    return ok(pay)


@bp.post("/payments/<id>/fail")
def fail_payment(id):
    auth("PodOperator")
    pay = get_or_404("payments", id, "Payment")
    if pay["payment_status"] != "PENDING":
        invalid_state("Only a PENDING payment can be failed")
    pay["payment_status"] = "FAILED"
    return ok(pay)


@bp.post("/payments/<id>/reverse")
def reverse_payment(id):
    auth("PlatformAdmin")
    pay = get_or_404("payments", id, "Payment")
    if pay["payment_status"] != "CLEARED":
        invalid_state("Only a CLEARED payment can be reversed")
    seat = DB["seats"].get(pay["seat_id"])
    seat_withdrawn = seat is not None and seat["seat_status"] == "WITHDRAWN"
    claim_exists = any(
        c["seat_id"] == pay["seat_id"] and c["claim_status"] in ("APPROVED", "PAID")
        for c in DB["claims"].values()
    )
    if not (seat_withdrawn or claim_exists):
        invalid_state("Payment reversal requires a WITHDRAWN seat or an APPROVED/PAID refund claim")
    pay["payment_status"] = "REVERSED"
    inv = DB["invoices"].get(pay["invoice_id"])
    if inv is not None:
        recompute_invoice_paid(inv)
        touch(inv)
    if seat is not None:
        recompute_seat_paid(seat)
        touch(seat)
    if pay["source_kind"] == "VOUCHER":
        voucher = DB["vouchers"].get(pay["voucher_account_id"])
        if voucher is not None:
            voucher["disbursable_balance_cents"] += pay["amount_cents"]
            recompute_funding(voucher)
            touch(voucher)
            recompute_voucher_accepted(voucher)
    return ok(pay)
