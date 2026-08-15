"""Routes: enrollments, fee assessments, purchases, payments, payment plans."""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from core import (
    db, auth, body, req_field, req_int, req_enum, envelope_obj, paginate,
    clock_now, clock_date, fmt_ts, fmt_date, new_entity, touch, ApiError,
    err_invalid_request, err_invalid_state, err_ref_not_found, get_or_404,
    get_scoped, observe_offering, observe_account, recompute_account,
    require_year_open, year_of_account, run_stacking, assessment_outstanding,
    proration_refund_cents, spawn_refund, settle_waterfall,
    allocatable_ceiling, bump_dirty_departments,
)
from serializers import (
    ser_enrollment, ser_assessment, ser_purchase, ser_payment, ser_plan,
    ser_installment, ser_allocation,
)

bp = Blueprint("money", __name__)
BK = ("Bookkeeper",)
FM = ("FamilyMember",)
ANY = ("Bookkeeper", "FamilyMember", "Superintendent")


def ok(payload, code=200):
    resp = jsonify(payload)
    resp.status_code = code
    return resp


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------

@bp.post("/student-accounts/<id>/enrollments")
def create_enrollment(id):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    data = body()
    # rung 4: body reference (offering) exists and shares the account's year
    offering = None
    if "offering_id" in data and data["offering_id"] is not None:
        offering = db.offerings.get(data["offering_id"])
        if offering is None or offering["school_year_id"] != account["school_year_id"]:
            raise err_ref_not_found("offering")
    # rung 5: year must be OPEN
    year = year_of_account(account)
    require_year_open(year)
    # rung 7: shape
    req_field(data, "offering_id")
    observe_offering(offering)
    # rung 8: uniqueness — no second ACTIVE enrollment for (account, offering)
    for e in db.enrollments.values():
        if e["student_account_id"] == id and e["offering_id"] == offering["id"] \
                and e["status"] == "ACTIVE":
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", 409,
                           "An ACTIVE enrollment already exists for this "
                           "account and offering.")
    # rung 9: capacity — ACTIVE count must be below capacity
    active_count = sum(1 for e in db.enrollments.values()
                       if e["offering_id"] == offering["id"]
                       and e["status"] == "ACTIVE")
    if active_count >= offering["capacity"]:
        raise ApiError("ERR_OFFERING_FULL", 409,
                       "The offering is at capacity.")
    # rung 10: window — offering must still be SCHEDULED
    if offering["status"] != "SCHEDULED":
        raise ApiError("ERR_ENROLLMENT_WINDOW_CLOSED", 409,
                       "The offering is not SCHEDULED.")
    # fee item must still allow new assessments
    item = db.fee_items.get(offering["fee_item_id"])
    if item is not None and item["status"] == "RETIRED":
        raise err_invalid_state(
            "The offering's fee item is RETIRED; new assessments are blocked.")
    # rung 11: half-open schedule conflict; touching boundaries do not collide
    for e in db.enrollments.values():
        if e["student_account_id"] != id or e["status"] != "ACTIVE":
            continue
        other = db.offerings.get(e["offering_id"])
        if other is None:
            continue
        if offering["_start"] < other["_end"] and other["_start"] < offering["_end"]:
            raise ApiError("ERR_SCHEDULE_CONFLICT", 409,
                           "The offering window conflicts with an ACTIVE "
                           "enrollment on this account.")
    enrollment = new_entity("enrollments", {
        "student_account_id": id,
        "offering_id": offering["id"],
        "enrolled_at": fmt_ts(clock_now()),
        "withdrawn_at": None,
        "status": "ACTIVE",
    })
    # auto-create the fee assessment, pinning the catalog amount; offering-level
    # department attribution wins over the fee item's default
    assessment = new_entity("assessments", {
        "student_account_id": id,
        "enrollment_id": enrollment["id"],
        "fee_item_id": offering["fee_item_id"],
        "department_id": offering["department_id"],
        "assessed_amount_cents": item["amount_cents"] if item else 0,
        "waived_amount_cents": 0,
        "allocated_cents": 0,
        "refunded_cents": 0,
        "payment_plan_id": None,
        "status": "ASSESSED",
        "_waiver_by_program": {},
    })
    # provisional waiver stacking against the full assessed amount
    run_stacking(account, only_assessment=assessment["id"])
    recompute_account(account)
    return ok(envelope_obj(ser_enrollment(enrollment)), 201)


@bp.get("/student-accounts/<id>/enrollments")
def list_enrollments(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [e for e in db.enrollments.values() if e["student_account_id"] == id]
    if "offering_id" in request.args:
        rows = [e for e in rows if e["offering_id"] == request.args["offering_id"]]
    if "status" in request.args:
        rows = [e for e in rows if e["status"] == request.args["status"]]
    return ok(paginate(rows, ser_enrollment))


@bp.get("/student-accounts/<id>/enrollments/<enrollmentId>")
def get_enrollment(id, enrollmentId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    enr = get_scoped("enrollments", enrollmentId, "student_account_id", id,
                     "enrollment")
    return ok(envelope_obj(ser_enrollment(enr)))


@bp.post("/student-accounts/<id>/enrollments/<enrollmentId>/withdraw")
def withdraw_enrollment(id, enrollmentId):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    enr = get_scoped("enrollments", enrollmentId, "student_account_id", id,
                     "enrollment")
    year = year_of_account(account)
    require_year_open(year)
    if enr["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE enrollment can be withdrawn.")
    enr["status"] = "WITHDRAWN"
    enr["withdrawn_at"] = fmt_ts(clock_now())
    touch(enr)
    offering = db.offerings.get(enr["offering_id"])
    assessment = next((a for a in db.assessments.values()
                       if a.get("enrollment_id") == enr["id"]), None)
    if offering is not None and assessment is not None:
        item = db.fee_items.get(assessment["fee_item_id"])
        if item is not None and item.get("refundable", True):
            cents = proration_refund_cents(year, offering, assessment)
            spawn_refund(account, "WITHDRAWAL", cents,
                         fee_assessment_id=assessment["id"])
    recompute_account(account)
    return ok(envelope_obj(ser_enrollment(enr)))


# ---------------------------------------------------------------------------
# Fee assessments
# ---------------------------------------------------------------------------

@bp.post("/student-accounts/<id>/fee-assessments")
def create_assessment(id):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    data = body()
    item = None
    if "fee_item_id" in data and data["fee_item_id"] is not None:
        item = db.fee_items.get(data["fee_item_id"])
        if item is None or item["school_year_id"] != account["school_year_id"]:
            raise err_ref_not_found("fee catalog item")
    year = year_of_account(account)
    require_year_open(year)
    req_field(data, "fee_item_id")
    amount = req_int(data, "assessed_amount_cents")
    if amount <= 0:
        raise err_invalid_request("assessed_amount_cents must be greater than zero.")
    if item["status"] == "RETIRED":
        raise err_invalid_state(
            "The fee item is RETIRED; new assessments are blocked.")
    assessment = new_entity("assessments", {
        "student_account_id": id,
        "enrollment_id": None,
        "fee_item_id": item["id"],
        "department_id": item["department_id"],  # catalog default department
        "assessed_amount_cents": amount,
        "waived_amount_cents": 0,
        "allocated_cents": 0,
        "refunded_cents": 0,
        "payment_plan_id": None,
        "status": "ASSESSED",
        "_waiver_by_program": {},
    })
    run_stacking(account, only_assessment=assessment["id"])
    recompute_account(account)
    return ok(envelope_obj(ser_assessment(assessment)), 201)


@bp.get("/student-accounts/<id>/fee-assessments")
def list_assessments(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [a for a in db.assessments.values() if a["student_account_id"] == id]
    if "status" in request.args:
        rows = [a for a in rows if a["status"] == request.args["status"]]
    if "department_id" in request.args:
        rows = [a for a in rows if a["department_id"] == request.args["department_id"]]
    return ok(paginate(rows, ser_assessment))


@bp.get("/student-accounts/<id>/fee-assessments/<assessmentId>")
def get_assessment(id, assessmentId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    a = get_scoped("assessments", assessmentId, "student_account_id", id,
                   "fee assessment")
    return ok(envelope_obj(ser_assessment(a)))


@bp.post("/student-accounts/<id>/fee-assessments/<assessmentId>/void")
def void_assessment(id, assessmentId):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    a = get_scoped("assessments", assessmentId, "student_account_id", id,
                   "fee assessment")
    year = year_of_account(account)
    require_year_open(year)
    # PRD §3.5: void requires the assessment to be "still ASSESSED and
    # completely untouched: allocated_cents and refunded_cents must both be
    # zero, otherwise ERR_ASSESSMENT_HAS_ACTIVITY" — one compound precondition
    # with a single named error (an ASSESSED row is untouched by construction,
    # so a from-state-only gate would make the named error unreachable).
    if a["status"] != "ASSESSED" or a["allocated_cents"] != 0 \
            or a["refunded_cents"] != 0:
        raise ApiError("ERR_ASSESSMENT_HAS_ACTIVITY", 409,
                       "Only an ASSESSED assessment with no allocations or "
                       "refunds can be voided.")
    a["status"] = "VOID"
    touch(a)
    recompute_account(account)
    return ok(envelope_obj(ser_assessment(a)))


# ---------------------------------------------------------------------------
# Purchases (disjoint purchase ledger)
# ---------------------------------------------------------------------------

@bp.post("/student-accounts/<id>/purchases")
def create_purchase(id):
    auth(FM)
    account = get_or_404("accounts", id, "student account")
    data = body()
    item = None
    if "item_id" in data and data["item_id"] is not None:
        item = db.purchase_items.get(data["item_id"])
        if item is None or item["school_year_id"] != account["school_year_id"]:
            raise err_ref_not_found("optional purchase item")
    year = year_of_account(account)
    require_year_open(year)
    req_field(data, "item_id")
    req_enum(data, "method", ("CARD", "ACH", "CASH", "CHECK"))
    # rung 18: inventory
    if item["sold_count"] >= item["inventory_cap"]:
        raise ApiError("ERR_ITEM_SOLD_OUT", 409, "The item is sold out.")
    # atomic charge: created directly in COMPLETED with ledger credit
    purchase = new_entity("purchases", {
        "student_account_id": id,
        "item_id": item["id"],
        "amount_cents": item["amount_cents"],
        "refunded_cents": 0,
        "status": "COMPLETED",
    })
    from core import write_ledger
    write_ledger(id, item["department_id"], "DISTRIBUTION_CREDIT",
                 purchase["amount_cents"], source_payment_id=None)
    item["sold_count"] += 1
    touch(item)
    bump_dirty_departments()
    return ok(envelope_obj(ser_purchase(purchase)), 201)


@bp.get("/student-accounts/<id>/purchases")
def list_purchases(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [p for p in db.purchases.values() if p["student_account_id"] == id]
    if "item_id" in request.args:
        rows = [p for p in rows if p["item_id"] == request.args["item_id"]]
    if "status" in request.args:
        rows = [p for p in rows if p["status"] == request.args["status"]]
    return ok(paginate(rows, ser_purchase))


@bp.get("/student-accounts/<id>/purchases/<purchaseId>")
def get_purchase(id, purchaseId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    p = get_scoped("purchases", purchaseId, "student_account_id", id, "purchase")
    return ok(envelope_obj(ser_purchase(p)))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@bp.post("/student-accounts/<id>/payments")
def create_payment(id):
    auth(FM)
    account = get_or_404("accounts", id, "student account")
    data = body()
    year = year_of_account(account)
    require_year_open(year)
    amount = req_int(data, "amount_cents")
    method = req_enum(data, "method", ("CARD", "ACH", "CASH", "CHECK"))
    key = req_field(data, "idempotency_key")
    policy = data.get("overpayment_policy", "CREDIT_BALANCE")
    if policy not in ("CREDIT_BALANCE", "REJECT"):
        raise err_invalid_request(
            "overpayment_policy must be CREDIT_BALANCE or REJECT.")
    if not isinstance(key, str):
        raise err_invalid_request("idempotency_key must be a string.")
    if amount <= 0:
        raise err_invalid_request("amount_cents must be greater than zero.")
    # rung 15: key unique per account among non-FAILED payments
    for p in db.payments.values():
        if p["student_account_id"] == id and p["idempotency_key"] == key \
                and p["status"] != "FAILED":
            raise ApiError("ERR_DUPLICATE_PAYMENT", 409,
                           "idempotency_key already used on this account.")
    payment = new_entity("payments", {
        "student_account_id": id,
        "amount_cents": amount,
        "method": method,
        "idempotency_key": key,
        "overpayment_policy": policy,
        "allocated_cents": 0,
        "status": "PENDING",
        "_settled_by": None,
    })
    return ok(envelope_obj(ser_payment(payment)), 201)


@bp.get("/student-accounts/<id>/payments")
def list_payments(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [p for p in db.payments.values() if p["student_account_id"] == id]
    if "status" in request.args:
        rows = [p for p in rows if p["status"] == request.args["status"]]
    return ok(paginate(rows, ser_payment))


@bp.get("/student-accounts/<id>/payments/<paymentId>")
def get_payment(id, paymentId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    p = get_scoped("payments", paymentId, "student_account_id", id, "payment")
    return ok(envelope_obj(ser_payment(p)))


@bp.post("/student-accounts/<id>/payments/<paymentId>/settle")
def settle_payment(id, paymentId):
    uid, _role = auth(FM)
    account = get_or_404("accounts", id, "student account")
    payment = get_scoped("payments", paymentId, "student_account_id", id,
                         "payment")
    year = year_of_account(account)
    require_year_open(year)
    if payment["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING payment can be settled.")
    observe_account(account)
    if account["posture"] == "WRITTEN_OFF":
        raise ApiError("ERR_ACCOUNT_WRITTEN_OFF", 409,
                       "The account is in WRITTEN_OFF posture.")
    data = body()
    outcome = req_enum(data, "outcome", ("SUCCEEDED", "FAILED"))
    if outcome == "FAILED":
        payment["status"] = "FAILED"
        touch(payment)
        return ok(envelope_obj(ser_payment(payment)))
    # rung 16: REJECT pre-check with atomicity (before any allocation row)
    if payment["overpayment_policy"] == "REJECT":
        ceiling = allocatable_ceiling(account)
        if payment["amount_cents"] > ceiling:
            raise ApiError("ERR_OVERPAYMENT_REJECTED", 402,
                           "The settle amount exceeds the allocatable capacity.")
    settle_waterfall(account, payment)
    payment["status"] = "SUCCEEDED"
    payment["_settled_by"] = uid
    touch(payment)
    # case resolution: balance driven to zero or below resolves open cases
    recompute_account(account, bump=False)
    if account["balance_cents"] <= 0:
        for c in db.cases.values():
            if c["student_account_id"] == id and \
                    c["status"] in ("OPEN", "PAYMENT_PROMISED"):
                c["status"] = "RESOLVED"
                touch(c)
    recompute_account(account)
    bump_dirty_departments()
    return ok(envelope_obj(ser_payment(payment)))


@bp.post("/student-accounts/<id>/payments/<paymentId>/void")
def void_payment(id, paymentId):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    payment = get_scoped("payments", paymentId, "student_account_id", id,
                         "payment")
    year = year_of_account(account)
    require_year_open(year)
    if payment["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING payment can be voided.")
    payment["status"] = "VOIDED"
    touch(payment)
    return ok(envelope_obj(ser_payment(payment)))


@bp.get("/student-accounts/<id>/payments/<paymentId>/allocations")
def list_payment_allocations(id, paymentId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    get_scoped("payments", paymentId, "student_account_id", id, "payment")
    rows = [a for a in db.allocations.values() if a["payment_id"] == paymentId]
    return ok(paginate(rows, ser_allocation))


# ---------------------------------------------------------------------------
# Payment plans
# ---------------------------------------------------------------------------

@bp.post("/student-accounts/<id>/payment-plans")
def create_plan(id):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    data = body()
    year = year_of_account(account)
    require_year_open(year)
    # rung 7: shape
    count = req_int(data, "installment_count")
    first_due_raw = req_field(data, "first_due_date")
    from core import parse_date
    first_due = parse_date(first_due_raw)
    interval = req_int(data, "interval_days")
    expected = req_int(data, "expected_account_version")
    if first_due is None:
        raise err_invalid_request("first_due_date must be an ISO-8601 date.")
    if first_due < clock_date():
        raise err_invalid_request(
            "first_due_date must not precede the current logical date.")
    if interval <= 0:
        raise err_invalid_request("interval_days must be greater than zero.")
    # rung 17: plan terms
    observe_account(account)
    covered = [a for a in db.assessments.values()
               if a["student_account_id"] == id
               and a["status"] in ("ASSESSED", "PARTIALLY_PAID")
               and assessment_outstanding(a) > 0]
    covered.sort(key=lambda a: (a["created_at"], a["_seq"]))
    covered_amount = sum(assessment_outstanding(a) for a in covered)
    if not covered or covered_amount <= 0:
        raise ApiError("ERR_PLAN_TERMS_VIOLATION", 422,
                       "There is no outstanding balance to cover.")
    if covered_amount < year["payment_plan_min_cents"]:
        raise ApiError("ERR_PLAN_TERMS_VIOLATION", 422,
                       "Covered outstanding is below the plan minimum.")
    if count < 2 or count > year["payment_plan_max_installments"]:
        raise ApiError("ERR_PLAN_TERMS_VIOLATION", 422,
                       "installment_count is outside the allowed range.")
    # rung 23: OCC last
    if expected != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_account_version does not match the account's "
                       "current version.")
    # installment schedule: floor base, remainder pinned to the LAST installment
    base = covered_amount // count
    remainder = covered_amount - base * count
    plan = new_entity("plans", {
        "student_account_id": id,
        "installment_count": count,
        "first_due_date": first_due.isoformat(),
        "interval_days": interval,
        "covered_amount_cents": covered_amount,
        "installment_amount_cents": base,
        "status": "ACTIVE",
        "_covered": [(a["id"], assessment_outstanding(a)) for a in covered],
    })
    for i in range(1, count + 1):
        amount = base + (remainder if i == count else 0)
        due = first_due + timedelta(days=interval * (i - 1))
        new_entity("installments", {
            "payment_plan_id": plan["id"],
            "sequence": i,
            "due_date": due.isoformat(),
            "amount_cents": amount,
            "paid_cents": 0,
            "status": "SCHEDULED",
            "_due": due,
        })
    for a in covered:
        a["status"] = "PAYMENT_PLAN"
        a["payment_plan_id"] = plan["id"]
        touch(a)
    recompute_account(account)
    return ok(envelope_obj(ser_plan(plan)), 201)


@bp.get("/student-accounts/<id>/payment-plans")
def list_plans(id):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    rows = [p for p in db.plans.values() if p["student_account_id"] == id]
    if "status" in request.args:
        rows = [p for p in rows if p["status"] == request.args["status"]]
    return ok(paginate(rows, ser_plan))


@bp.get("/student-accounts/<id>/payment-plans/<planId>")
def get_plan(id, planId):
    auth(ANY)
    get_or_404("accounts", id, "student account")
    p = get_scoped("plans", planId, "student_account_id", id, "payment plan")
    return ok(envelope_obj(ser_plan(p)))


@bp.get("/student-accounts/<id>/payment-plans/<planId>/installments")
def list_plan_installments(id, planId):
    auth(ANY)
    account = get_or_404("accounts", id, "student account")
    plan = get_scoped("plans", planId, "student_account_id", id, "payment plan")
    observe_account(account)
    rows = [i for i in db.installments.values()
            if i["payment_plan_id"] == plan["id"]]
    if "status" in request.args:
        rows = [i for i in rows if i["status"] == request.args["status"]]
    return ok(paginate(rows, ser_installment))


@bp.post("/student-accounts/<id>/payment-plans/<planId>/cancel")
def cancel_plan(id, planId):
    auth(BK)
    account = get_or_404("accounts", id, "student account")
    plan = get_scoped("plans", planId, "student_account_id", id, "payment plan")
    year = year_of_account(account)
    require_year_open(year)
    if plan["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE plan can be cancelled.")
    for i in db.installments.values():
        if i["payment_plan_id"] == planId and i["status"] == "PAID":
            raise ApiError("ERR_PLAN_HAS_PAYMENTS", 409,
                           "The plan has at least one PAID installment.")
    plan["status"] = "CANCELLED"
    touch(plan)
    for i in db.installments.values():
        if i["payment_plan_id"] == planId and \
                i["status"] in ("SCHEDULED", "DUE", "PAST_DUE"):
            i["status"] = "WAIVED_BY_DEFAULT"
            touch(i)
    for aid, _w in plan["_covered"]:
        a = db.assessments.get(aid)
        if a is not None and a["status"] == "PAYMENT_PLAN":
            a["status"] = "PARTIALLY_PAID" if a["allocated_cents"] > 0 \
                else "ASSESSED"
            touch(a)
    recompute_account(account)
    return ok(envelope_obj(ser_plan(plan)))
