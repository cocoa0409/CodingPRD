"""Routes: logical clock, school years, departments, fee catalog items,
optional purchase items, offerings, and the year operations sweep."""
from flask import Blueprint, jsonify

from core import (
    db, auth, body, req_field, req_int, opt_int, req_enum, opt_bool,
    envelope_obj, envelope_list, paginate, parse_datetime, parse_date,
    clock_now, clock_set, clock_date, fmt_ts, new_entity, touch,
    ApiError, err_invalid_request, err_invalid_state, err_not_found,
    err_ref_not_found, get_or_404, get_scoped, observe_offering,
    recompute_account, open_or_advance_case, case_bucket, spawn_refund,
    proration_refund_cents, assessment_outstanding, write_ledger,
    bump_dirty_departments,
)
from serializers import (
    ser_year, ser_department, ser_fee_item, ser_purchase_item, ser_offering,
)

bp = Blueprint("years", __name__)

BK = ("Bookkeeper",)
ANY = ("Bookkeeper", "FamilyMember", "Superintendent")


def ok(payload, code=200):
    resp = jsonify(payload)
    resp.status_code = code
    return resp


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(BK)
    data = body()
    raw = req_field(data, "to_iso8601")
    dt = parse_datetime(raw)
    if dt is None:
        raise err_invalid_request("to_iso8601 must be a valid ISO-8601 instant.")
    clock_set(dt)
    return ok(envelope_obj({"now_iso8601": fmt_ts(clock_now())}))


# ---------------------------------------------------------------------------
# School years
# ---------------------------------------------------------------------------

def validate_year_shape(data):
    label = req_field(data, "label")
    start = parse_date(req_field(data, "start_date"))
    end = parse_date(req_field(data, "end_date"))
    refund_full = req_int(data, "refund_full_days")
    refund_partial = req_int(data, "refund_partial_days")
    partial_bp = req_int(data, "partial_refund_pct_bp")
    plan_min = req_int(data, "payment_plan_min_cents")
    plan_max_inst = req_int(data, "payment_plan_max_installments")
    writeoff_max = req_int(data, "writeoff_max_cents")
    aging_interval = req_int(data, "aging_interval_days")
    grad_threshold = req_int(data, "graduation_hold_threshold_cents")
    if not isinstance(label, str):
        raise err_invalid_request("label must be a string.")
    if start is None or end is None:
        raise err_invalid_request("start_date and end_date must be ISO-8601 dates.")
    if end <= start:
        raise err_invalid_request("end_date must be strictly after start_date.")
    if refund_partial <= refund_full:
        raise err_invalid_request(
            "refund_partial_days must be strictly greater than refund_full_days.")
    if not (0 <= partial_bp <= 10000):
        raise err_invalid_request("partial_refund_pct_bp must be within 0..10000.")
    if plan_max_inst < 2:
        raise err_invalid_request("payment_plan_max_installments must be at least 2.")
    return (label, start, end, refund_full, refund_partial, partial_bp, plan_min,
            plan_max_inst, writeoff_max, aging_interval, grad_threshold)


@bp.post("/school-years")
def create_year():
    auth(BK)
    data = body()
    (label, start, end, refund_full, refund_partial, partial_bp, plan_min,
     plan_max_inst, writeoff_max, aging_interval, grad_threshold) = \
        validate_year_shape(data)
    # rung 12: closed-interval overlap against existing non-CLOSED years;
    # a shared endpoint date DOES collide
    for y in db.years.values():
        if y["status"] == "CLOSED":
            continue
        if start <= y["_end"] and y["_start"] <= end:
            raise ApiError("ERR_YEAR_OVERLAP", 409,
                           "The new year's date range intersects an existing "
                           "non-CLOSED school year.")
    year = new_entity("years", {
        "label": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "refund_full_days": refund_full,
        "refund_partial_days": refund_partial,
        "partial_refund_pct_bp": partial_bp,
        "payment_plan_min_cents": plan_min,
        "payment_plan_max_installments": plan_max_inst,
        "writeoff_max_cents": writeoff_max,
        "aging_interval_days": aging_interval,
        "graduation_hold_threshold_cents": grad_threshold,
        "status": "DRAFT",
        "_start": start,
        "_end": end,
    })
    return ok(envelope_obj(ser_year(year)), 201)


@bp.get("/school-years")
def list_years():
    auth(ANY)
    return ok(paginate(list(db.years.values()), ser_year))


@bp.get("/school-years/<id>")
def get_year(id):
    auth(ANY)
    return ok(envelope_obj(ser_year(get_or_404("years", id, "school year"))))


@bp.post("/school-years/<id>/open")
def open_year(id):
    auth(BK)
    year = get_or_404("years", id, "school year")
    if year["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT school year can be opened.")
    has_dept = any(d["school_year_id"] == id for d in db.departments.values())
    if not has_dept:
        raise ApiError("ERR_YEAR_NOT_CONFIGURABLE", 409,
                       "The year has no departments configured.")
    if year["_end"] <= year["_start"]:
        raise err_invalid_request("end_date must be strictly after start_date.")
    year["status"] = "OPEN"
    touch(year)
    return ok(envelope_obj(ser_year(year)))


@bp.post("/school-years/<id>/close")
def close_year(id):
    auth(BK)
    year = get_or_404("years", id, "school year")
    if year["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN school year can be closed.")
    data = body()
    expected = req_int(data, "expected_year_version")
    # business preconditions (collections terminal first, then active plans)
    acct_ids = {a["id"] for a in db.accounts.values() if a["school_year_id"] == id}
    for c in db.cases.values():
        if c["student_account_id"] in acct_ids and \
                c["status"] in ("OPEN", "PAYMENT_PROMISED"):
            raise ApiError("ERR_OPEN_COLLECTIONS_CASES", 409,
                           "Non-terminal collections cases exist under the year.")
    for p in db.plans.values():
        if p["student_account_id"] in acct_ids and p["status"] == "ACTIVE":
            raise ApiError("ERR_ACTIVE_PAYMENT_PLANS", 409,
                           "Active payment plans exist under the year.")
    # rung 23: OCC last
    if expected != year["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_year_version does not match the year's current "
                       "version.")
    year["status"] = "CLOSED"
    touch(year)
    return ok(envelope_obj(ser_year(year)))


# ---------------------------------------------------------------------------
# Operations run (aging sweep)
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/ops-runs")
def ops_run(id):
    auth(BK)
    year = get_or_404("years", id, "school year")
    today = clock_date()
    k = year["aging_interval_days"]
    swept_cases = 0
    defaulted_plans = 0
    advanced_installments = 0
    opened_cases = 0

    accts = [a for a in db.accounts.values() if a["school_year_id"] == id]
    accts.sort(key=lambda a: (a["created_at"], a["_seq"]))
    acct_ids = {a["id"] for a in accts}

    # 0. clock-driven offering transitions
    for off in db.offerings.values():
        if off["school_year_id"] == id:
            observe_offering(off)

    # 1. installments: SCHEDULED->DUE at due date; DUE->PAST_DUE past due date
    year_plans = [p for p in db.plans.values()
                  if p["student_account_id"] in acct_ids]
    year_plans.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for plan in year_plans:
        if plan["status"] != "ACTIVE":
            continue
        insts = [i for i in db.installments.values()
                 if i["payment_plan_id"] == plan["id"]]
        insts.sort(key=lambda i: i["sequence"])
        for inst in insts:
            if inst["status"] == "SCHEDULED" and today >= inst["_due"]:
                inst["status"] = "DUE"
                touch(inst)
                advanced_installments += 1
            if inst["status"] == "DUE" and today > inst["_due"] and \
                    inst["paid_cents"] < inst["amount_cents"]:
                inst["status"] = "PAST_DUE"
                touch(inst)
                advanced_installments += 1

    # 2. plan defaults: any installment PAST_DUE for more than k days past due
    for plan in year_plans:
        if plan["status"] != "ACTIVE":
            continue
        insts = [i for i in db.installments.values()
                 if i["payment_plan_id"] == plan["id"]]
        default = any(i["status"] == "PAST_DUE" and
                      (today - i["_due"]).days > k for i in insts)
        if not default:
            continue
        plan["status"] = "DEFAULTED"
        touch(plan)
        defaulted_plans += 1
        for i in insts:
            if i["status"] in ("SCHEDULED", "DUE", "PAST_DUE"):
                i["status"] = "WAIVED_BY_DEFAULT"
                touch(i)
        account = db.accounts.get(plan["student_account_id"])
        for aid, _w in plan["_covered"]:
            a = db.assessments.get(aid)
            if a is not None and a["status"] == "PAYMENT_PLAN":
                a["status"] = "DELINQUENT"
                touch(a)
        if account is not None:
            _case, is_new = open_or_advance_case(account)
            if is_new:
                opened_cases += 1
            recompute_account(account)

    # 3. unpaid assessments older than k days -> DELINQUENT; open cases
    for account in accts:
        assess = [a for a in db.assessments.values()
                  if a["student_account_id"] == account["id"]
                  and a["status"] in ("ASSESSED", "PARTIALLY_PAID")
                  and assessment_outstanding(a) > 0]
        assess.sort(key=lambda a: (a["created_at"], a["_seq"]))
        became = False
        for a in assess:
            age = (clock_now() - a["_created_dt"]).days
            if age > k:
                a["status"] = "DELINQUENT"
                touch(a)
                became = True
        if became:
            _case, is_new = open_or_advance_case(account)
            if is_new:
                opened_cases += 1
            recompute_account(account)

    # sweep pass over non-terminal cases (bucket recompute is live; count here)
    year_cases = [c for c in db.cases.values()
                  if c["student_account_id"] in acct_ids]
    year_cases.sort(key=lambda c: (c["created_at"], c["_seq"]))

    # 4. broken-promise reversion
    for c in year_cases:
        if c["status"] != "PAYMENT_PROMISED":
            continue
        promised_at = c.get("_promised_at")
        paid_after = any(
            p["student_account_id"] == c["student_account_id"]
            and p["status"] == "SUCCEEDED"
            and promised_at is not None and p["created_at"] > promised_at
            for p in db.payments.values())
        if not paid_after:
            c["status"] = "OPEN"
            touch(c)

    swept_cases = sum(1 for c in year_cases
                      if c["status"] in ("OPEN", "PAYMENT_PROMISED"))

    bump_dirty_departments()
    return ok(envelope_obj({
        "swept_cases": swept_cases,
        "defaulted_plans": defaulted_plans,
        "advanced_installments": advanced_installments,
        "opened_cases": opened_cases,
    }))


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/departments")
def create_department(id):
    auth(BK)
    year = get_or_404("years", id, "school year")
    data = body()
    code = req_field(data, "code")
    name = req_field(data, "name")
    if not isinstance(code, str) or not isinstance(name, str):
        raise err_invalid_request("code and name must be strings.")
    for d in db.departments.values():
        if d["school_year_id"] == id and d["code"] == code:
            raise err_invalid_request(
                "A department with this code already exists in the school year.")
    dept = new_entity("departments", {
        "school_year_id": id, "code": code, "name": name,
        "reconciled_cents": 0,
    })
    return ok(envelope_obj(ser_department(dept)), 201)


@bp.get("/school-years/<id>/departments")
def list_departments(id):
    auth(ANY)
    get_or_404("years", id, "school year")
    rows = [d for d in db.departments.values() if d["school_year_id"] == id]
    f = _filter_args()
    if "department_id" in f:
        rows = [d for d in rows if d["id"] == f["department_id"]]
    return ok(paginate(rows, ser_department))


@bp.get("/school-years/<id>/departments/<departmentId>")
def get_department(id, departmentId):
    auth(ANY)
    get_or_404("years", id, "school year")
    dept = get_scoped("departments", departmentId, "school_year_id", id,
                      "department")
    return ok(envelope_obj(ser_department(dept)))


# ---------------------------------------------------------------------------
# Fee catalog items
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/fee-catalog-items")
def create_fee_item(id):
    auth(BK)
    get_or_404("years", id, "school year")
    data = body()
    name = req_field(data, "name")
    amount = req_int(data, "amount_cents")
    dept_id = req_field(data, "department_id")
    waiverable = opt_bool(data, "waiverable", True)
    refundable = opt_bool(data, "refundable", True)
    if not isinstance(name, str):
        raise err_invalid_request("name must be a string.")
    # rung 4: body reference must exist and belong to the same year
    dept = db.departments.get(dept_id)
    if dept is None or dept["school_year_id"] != id:
        raise err_ref_not_found("department")
    if amount <= 0:
        raise err_invalid_request("amount_cents must be greater than zero.")
    item = new_entity("fee_items", {
        "school_year_id": id, "name": name, "amount_cents": amount,
        "department_id": dept_id, "waiverable": waiverable,
        "refundable": refundable, "status": "ACTIVE",
    })
    return ok(envelope_obj(ser_fee_item(item)), 201)


@bp.get("/school-years/<id>/fee-catalog-items")
def list_fee_items(id):
    auth(ANY)
    get_or_404("years", id, "school year")
    rows = [i for i in db.fee_items.values() if i["school_year_id"] == id]
    f = _filter_args()
    if "department_id" in f:
        rows = [i for i in rows if i["department_id"] == f["department_id"]]
    return ok(paginate(rows, ser_fee_item))


@bp.get("/school-years/<id>/fee-catalog-items/<itemId>")
def get_fee_item(id, itemId):
    auth(ANY)
    get_or_404("years", id, "school year")
    item = get_scoped("fee_items", itemId, "school_year_id", id,
                      "fee catalog item")
    return ok(envelope_obj(ser_fee_item(item)))


@bp.post("/school-years/<id>/fee-catalog-items/<itemId>/retire")
def retire_fee_item(id, itemId):
    auth(BK)
    get_or_404("years", id, "school year")
    item = get_scoped("fee_items", itemId, "school_year_id", id,
                      "fee catalog item")
    if item["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE fee item can be retired.")
    for a in db.assessments.values():
        if a["fee_item_id"] == itemId and a["status"] in (
                "ASSESSED", "PARTIALLY_PAID", "PAYMENT_PLAN", "DELINQUENT"):
            raise ApiError("ERR_FEE_ITEM_IN_USE", 409,
                           "Non-terminal assessments reference this fee item.")
    item["status"] = "RETIRED"
    touch(item)
    return ok(envelope_obj(ser_fee_item(item)))


# ---------------------------------------------------------------------------
# Optional purchase items
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/optional-purchase-items")
def create_purchase_item(id):
    auth(BK)
    get_or_404("years", id, "school year")
    data = body()
    name = req_field(data, "name")
    amount = req_int(data, "amount_cents")
    dept_id = req_field(data, "department_id")
    refundable = opt_bool(data, "refundable", True)
    cap = req_int(data, "inventory_cap")
    if not isinstance(name, str):
        raise err_invalid_request("name must be a string.")
    dept = db.departments.get(dept_id)
    if dept is None or dept["school_year_id"] != id:
        raise err_ref_not_found("department")
    if amount <= 0:
        raise err_invalid_request("amount_cents must be greater than zero.")
    if cap < 1:
        raise err_invalid_request("inventory_cap must be at least 1.")
    item = new_entity("purchase_items", {
        "school_year_id": id, "name": name, "amount_cents": amount,
        "department_id": dept_id, "refundable": refundable,
        "inventory_cap": cap, "sold_count": 0,
    })
    return ok(envelope_obj(ser_purchase_item(item)), 201)


@bp.get("/school-years/<id>/optional-purchase-items")
def list_purchase_items(id):
    auth(ANY)
    get_or_404("years", id, "school year")
    rows = [i for i in db.purchase_items.values() if i["school_year_id"] == id]
    f = _filter_args()
    if "department_id" in f:
        rows = [i for i in rows if i["department_id"] == f["department_id"]]
    return ok(paginate(rows, ser_purchase_item))


@bp.get("/school-years/<id>/optional-purchase-items/<itemId>")
def get_purchase_item(id, itemId):
    auth(ANY)
    get_or_404("years", id, "school year")
    item = get_scoped("purchase_items", itemId, "school_year_id", id,
                      "optional purchase item")
    return ok(envelope_obj(ser_purchase_item(item)))


# ---------------------------------------------------------------------------
# Offerings
# ---------------------------------------------------------------------------

@bp.post("/school-years/<id>/offerings")
def create_offering(id):
    auth(BK)
    get_or_404("years", id, "school year")
    data = body()
    kind = req_enum(data, "kind", ("COURSE", "ACTIVITY"))
    title = req_field(data, "title")
    dept_id = req_field(data, "department_id")
    fee_item_id = req_field(data, "fee_item_id")
    start = parse_date(req_field(data, "start_date"))
    end = parse_date(req_field(data, "end_date"))
    capacity = req_int(data, "capacity")
    if not isinstance(title, str):
        raise err_invalid_request("title must be a string.")
    dept = db.departments.get(dept_id)
    if dept is None or dept["school_year_id"] != id:
        raise err_ref_not_found("department")
    item = db.fee_items.get(fee_item_id)
    if item is None or item["school_year_id"] != id:
        raise err_ref_not_found("fee catalog item")
    if start is None or end is None:
        raise err_invalid_request("start_date and end_date must be ISO-8601 dates.")
    if end < start:
        raise err_invalid_request("end_date must be at or after start_date.")
    if capacity < 1:
        raise err_invalid_request("capacity must be at least 1.")
    off = new_entity("offerings", {
        "school_year_id": id, "kind": kind, "title": title,
        "department_id": dept_id, "fee_item_id": fee_item_id,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "capacity": capacity, "status": "SCHEDULED",
        "_start": start, "_end": end,
    })
    return ok(envelope_obj(ser_offering(off)), 201)


@bp.get("/school-years/<id>/offerings")
def list_offerings(id):
    auth(ANY)
    get_or_404("years", id, "school year")
    rows = [o for o in db.offerings.values() if o["school_year_id"] == id]
    for o in rows:
        observe_offering(o)
    f = _filter_args()
    if "department_id" in f:
        rows = [o for o in rows if o["department_id"] == f["department_id"]]
    if "status" in f:
        rows = [o for o in rows if o["status"] == f["status"]]
    return ok(paginate(rows, ser_offering))


@bp.get("/school-years/<id>/offerings/<offeringId>")
def get_offering(id, offeringId):
    auth(ANY)
    get_or_404("years", id, "school year")
    off = get_scoped("offerings", offeringId, "school_year_id", id, "offering")
    observe_offering(off)
    return ok(envelope_obj(ser_offering(off)))


@bp.post("/school-years/<id>/offerings/<offeringId>/complete")
def complete_offering(id, offeringId):
    auth(BK)
    get_or_404("years", id, "school year")
    off = get_scoped("offerings", offeringId, "school_year_id", id, "offering")
    observe_offering(off)
    if off["status"] != "IN_SESSION":
        raise err_invalid_state("Only an IN_SESSION offering can be completed.")
    for e in db.enrollments.values():
        if e["offering_id"] == offeringId and e["status"] == "ACTIVE":
            e["status"] = "COMPLETED"
            touch(e)
    off["status"] = "COMPLETED"
    touch(off)
    return ok(envelope_obj(ser_offering(off)))


@bp.post("/school-years/<id>/offerings/<offeringId>/cancel")
def cancel_offering(id, offeringId):
    auth(BK)
    year = get_or_404("years", id, "school year")
    off = get_scoped("offerings", offeringId, "school_year_id", id, "offering")
    observe_offering(off)
    if off["status"] not in ("SCHEDULED", "IN_SESSION"):
        raise err_invalid_state(
            "Only a SCHEDULED or IN_SESSION offering can be cancelled.")
    force_full = off["status"] == "SCHEDULED"  # cancelled before start
    affected_accounts = set()
    for e in db.enrollments.values():
        if e["offering_id"] != offeringId or e["status"] != "ACTIVE":
            continue
        e["status"] = "DROPPED_BY_CANCELLATION"
        e["withdrawn_at"] = fmt_ts(clock_now())
        touch(e)
        account = db.accounts.get(e["student_account_id"])
        if account is None:
            continue
        # one PENDING refund per dropped enrollment (0 when non-refundable)
        assessment = next(
            (a for a in db.assessments.values()
             if a.get("enrollment_id") == e["id"]), None)
        if assessment is not None:
            cents = proration_refund_cents(year, off, assessment,
                                           force_full=force_full)
            spawn_refund(account, "ACTIVITY_CANCELLATION", cents,
                         fee_assessment_id=assessment["id"])
        affected_accounts.add(account["id"])
    for aid in affected_accounts:
        recompute_account(db.accounts[aid])
    off["status"] = "CANCELLED"
    touch(off)
    return ok(envelope_obj(ser_offering(off)))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _filter_args():
    from flask import request
    return request.args
