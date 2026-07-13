"""All API route handlers for the Extended-Stay & Corporate Housing API."""
from flask import request

import core
from core import (
    db, err, auth, get, create, touch, all_of, serialize,
    get_body, require_fields, require_int, parse_dt, whole_days, paginate, ok,
    rate_subtotal_cents, occupancy_tax_cents, recompute_lease, recompute_stay_deposit,
    find_invoice_for_stay,
    TURNOVER_BUFFER_DAYS, MIN_LEASE_TERM_DAYS,
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def single(collection, entity, status=200):
    return ok(serialize(collection, entity), status=status, response_type="object")


def listing(collection, items):
    page, meta = paginate(items)
    data = [serialize(collection, e) for e in page]
    return ok(data, status=200, response_type="array", pagination=meta)


def must_exist(collection, entity_id):
    entity = get(collection, entity_id)
    if entity is None:
        raise err("ERR_NOT_FOUND", 404, "{} not found".format(collection))
    return entity


def stay_owner_account_id(stay):
    lease_id = stay.get("master_lease_id")
    if lease_id:
        lease = get("master_leases", lease_id)
        if lease:
            return lease["corporate_account_id"]
    return None


def filter_by(items, **filters):
    result = items
    for field, value in filters.items():
        if value is not None:
            result = [e for e in result if e.get(field) == value]
    return result


# ---------------------------------------------------------------------------
# Invoice lifecycle
# ---------------------------------------------------------------------------
def create_provisional_invoice(stay):
    rate_plan = get("rate_plans", stay["rate_plan_id"])
    nights = stay["planned_nights"]
    subtotal = rate_subtotal_cents(rate_plan, nights)
    tax = occupancy_tax_cents(rate_plan, nights, subtotal)
    cleaning = rate_plan["cleaning_fee_cents"]
    amount_due = subtotal + cleaning + tax
    fields = {
        "stay_id": stay["id"],
        "invoice_kind": "PROVISIONAL",
        "nights_billed": nights,
        "rate_subtotal_cents": subtotal,
        "cleaning_fee_cents": cleaning,
        "occupancy_tax_cents": tax,
        "amount_due_cents": amount_due,
        "damage_total_cents": 0,
        "total_settlement_cents": amount_due,
        "deposit_refund_cents": max(0, stay["deposit_held_cents"]),
        "status": "DRAFT",
    }
    return create("invoices", fields)


def finalize_invoice(stay):
    inv = find_invoice_for_stay(stay["id"])
    if inv is None:
        return
    rate_plan = get("rate_plans", stay["rate_plan_id"])
    nights = stay["billable_nights"]
    subtotal = rate_subtotal_cents(rate_plan, nights)
    tax = occupancy_tax_cents(rate_plan, nights, subtotal)
    cleaning = rate_plan["cleaning_fee_cents"]
    amount_due = subtotal + cleaning + tax
    damage_total = stay["deposit_charged_cents"]
    inv["invoice_kind"] = "FINAL"
    inv["nights_billed"] = nights
    inv["rate_subtotal_cents"] = subtotal
    inv["cleaning_fee_cents"] = cleaning
    inv["occupancy_tax_cents"] = tax
    inv["amount_due_cents"] = amount_due
    inv["damage_total_cents"] = damage_total
    inv["total_settlement_cents"] = amount_due + damage_total
    inv["deposit_refund_cents"] = max(0, stay["deposit_held_cents"] - damage_total)
    inv["status"] = "ISSUED"
    touch(inv)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register(app):

    # ----- Logical clock -----
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def clock_set():
        auth(["PropertyManager"])
        body = get_body()
        require_fields(body, ["to_iso8601"])
        try:
            db.clock = parse_dt(body["to_iso8601"])
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", 400, "to_iso8601 is not a valid ISO 8601 timestamp")
        return ok({}, status=200, response_type="object")

    # ----- CorporateAccount -----
    @app.route("/corporate-accounts", methods=["POST"])
    def corporate_account_create():
        auth(["PropertyManager"])
        body = get_body()
        require_fields(body, ["company_name", "billing_email"])
        entity = create("corporate_accounts", {
            "company_name": body["company_name"],
            "billing_email": body["billing_email"],
        })
        return single("corporate_accounts", entity, status=201)

    @app.route("/corporate-accounts/<cid>", methods=["GET"])
    def corporate_account_get(cid):
        auth(["PropertyManager", "CorporateAdmin"])
        entity = must_exist("corporate_accounts", cid)
        return single("corporate_accounts", entity)

    # ----- RatePlan -----
    @app.route("/rate-plans", methods=["POST"])
    def rate_plan_create():
        auth(["PropertyManager"])
        body = get_body()
        require_fields(body, ["name", "monthly_rate_cents", "utility_monthly_cents",
                              "cleaning_fee_cents", "occupancy_tax_rate_bps"])
        require_int(body, "monthly_rate_cents", minimum=0)
        require_int(body, "utility_monthly_cents", minimum=0)
        require_int(body, "cleaning_fee_cents", minimum=0)
        bps = require_int(body, "occupancy_tax_rate_bps", minimum=0)
        if bps > 10000:
            raise err("ERR_VALIDATION", 400, "occupancy_tax_rate_bps must be within [0,10000]")
        entity = create("rate_plans", {
            "name": body["name"],
            "monthly_rate_cents": body["monthly_rate_cents"],
            "utility_monthly_cents": body["utility_monthly_cents"],
            "cleaning_fee_cents": body["cleaning_fee_cents"],
            "occupancy_tax_rate_bps": body["occupancy_tax_rate_bps"],
        })
        return single("rate_plans", entity, status=201)

    @app.route("/rate-plans/<rid>", methods=["GET"])
    def rate_plan_get(rid):
        auth(["PropertyManager", "CorporateAdmin"])
        entity = must_exist("rate_plans", rid)
        return single("rate_plans", entity)

    # ----- Unit -----
    @app.route("/units", methods=["POST"])
    def unit_create():
        auth(["PropertyManager"])
        body = get_body()
        require_fields(body, ["name", "property_name", "bedrooms"])
        require_int(body, "bedrooms", minimum=0)
        entity = create("units", {
            "name": body["name"],
            "property_name": body["property_name"],
            "bedrooms": body["bedrooms"],
            "status": "AVAILABLE",
        })
        return single("units", entity, status=201)

    @app.route("/units/<uid>", methods=["GET"])
    def unit_get(uid):
        auth(["PropertyManager", "CorporateAdmin"])
        entity = must_exist("units", uid)
        return single("units", entity)

    # ----- MasterLease -----
    @app.route("/master-leases", methods=["POST"])
    def master_lease_create():
        auth(["PropertyManager"])
        body = get_body()
        require_fields(body, ["corporate_account_id", "committed_units",
                              "negotiated_monthly_rate_cents", "start_date", "end_date"])
        # existence of FK (present field)
        must_exist("corporate_accounts", body["corporate_account_id"])
        require_int(body, "committed_units", minimum=1)
        require_int(body, "negotiated_monthly_rate_cents", minimum=0)
        try:
            parse_dt(body["start_date"])
            parse_dt(body["end_date"])
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", 400, "start_date/end_date must be ISO 8601")
        entity = create("master_leases", {
            "corporate_account_id": body["corporate_account_id"],
            "committed_units": body["committed_units"],
            "negotiated_monthly_rate_cents": body["negotiated_monthly_rate_cents"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "status": "DRAFT",
            "units_consumed": 0,
            "units_free": body["committed_units"],
        })
        return single("master_leases", entity, status=201)

    @app.route("/master-leases/<lid>", methods=["GET"])
    def master_lease_get(lid):
        auth(["PropertyManager", "CorporateAdmin"])
        entity = must_exist("master_leases", lid)
        return single("master_leases", entity)

    @app.route("/master-leases", methods=["GET"])
    def master_lease_list():
        auth(["PropertyManager", "CorporateAdmin"])
        items = filter_by(all_of("master_leases"),
                          corporate_account_id=request.args.get("corporate_account_id"),
                          status=request.args.get("status"))
        return listing("master_leases", items)

    def _lease_transition(lid, from_status, to_status):
        auth(["PropertyManager"])
        lease = must_exist("master_leases", lid)
        if lease["status"] != from_status:
            raise err("ERR_INVALID_STATE", 409, "Master lease not in state {}".format(from_status))
        lease["status"] = to_status
        touch(lease)
        return single("master_leases", lease)

    @app.route("/master-leases/<lid>/activate", methods=["POST"])
    def master_lease_activate(lid):
        return _lease_transition(lid, "DRAFT", "ACTIVE")

    @app.route("/master-leases/<lid>/suspend", methods=["POST"])
    def master_lease_suspend(lid):
        return _lease_transition(lid, "ACTIVE", "SUSPENDED")

    @app.route("/master-leases/<lid>/resume", methods=["POST"])
    def master_lease_resume(lid):
        return _lease_transition(lid, "SUSPENDED", "ACTIVE")

    @app.route("/master-leases/<lid>/renegotiate", methods=["POST"])
    def master_lease_renegotiate(lid):
        uid, role = auth(["PropertyManager", "CorporateAdmin"])
        lease = must_exist("master_leases", lid)
        if role == "CorporateAdmin" and lease["corporate_account_id"] != uid:
            raise err("ERR_FORBIDDEN", 403, "CorporateAdmin does not own this master lease")
        body = get_body()
        require_fields(body, ["expected_master_lease_version", "negotiated_monthly_rate_cents"])
        require_int(body, "expected_master_lease_version")
        require_int(body, "negotiated_monthly_rate_cents", minimum=0)
        if body["expected_master_lease_version"] != lease["version"]:
            raise err("ERR_STALE_VERSION", 412, "expected_master_lease_version does not match current version")
        lease["negotiated_monthly_rate_cents"] = body["negotiated_monthly_rate_cents"]
        touch(lease)
        return single("master_leases", lease)

    # ----- Employee -----
    @app.route("/employees", methods=["POST"])
    def employee_create():
        uid, role = auth(["CorporateAdmin"])
        body = get_body()
        require_fields(body, ["corporate_account_id", "full_name", "email"])
        must_exist("corporate_accounts", body["corporate_account_id"])
        if body["corporate_account_id"] != uid:
            raise err("ERR_FORBIDDEN", 403, "CorporateAdmin does not own this corporate account")
        entity = create("employees", {
            "corporate_account_id": body["corporate_account_id"],
            "full_name": body["full_name"],
            "email": body["email"],
        })
        return single("employees", entity, status=201)

    @app.route("/employees/<eid>", methods=["GET"])
    def employee_get(eid):
        auth(["CorporateAdmin", "PropertyManager"])
        entity = must_exist("employees", eid)
        return single("employees", entity)

    @app.route("/employees", methods=["GET"])
    def employee_list():
        auth(["CorporateAdmin", "PropertyManager"])
        items = filter_by(all_of("employees"),
                          corporate_account_id=request.args.get("corporate_account_id"))
        return listing("employees", items)

    # ----- Stay -----
    @app.route("/stays", methods=["POST"])
    def stay_create():
        uid, role = auth(["PropertyManager", "CorporateAdmin"])
        body = get_body()

        # Existence (left-to-right on present FK fields)
        unit = get("units", body.get("unit_id")) if body.get("unit_id") is not None else None
        if body.get("unit_id") is not None and unit is None:
            raise err("ERR_NOT_FOUND", 404, "unit not found")
        rate_plan = get("rate_plans", body.get("rate_plan_id")) if body.get("rate_plan_id") is not None else None
        if body.get("rate_plan_id") is not None and rate_plan is None:
            raise err("ERR_NOT_FOUND", 404, "rate plan not found")
        lease = None
        if body.get("master_lease_id") is not None:
            lease = get("master_leases", body["master_lease_id"])
            if lease is None:
                raise err("ERR_NOT_FOUND", 404, "master lease not found")
        employee = None
        if body.get("employee_id") is not None:
            employee = get("employees", body["employee_id"])
            if employee is None:
                raise err("ERR_NOT_FOUND", 404, "employee not found")

        # Ownership (CorporateAdmin scoped write)
        if role == "CorporateAdmin":
            if lease is not None and lease["corporate_account_id"] != uid:
                raise err("ERR_FORBIDDEN", 403, "CorporateAdmin does not own this master lease")
            if employee is not None and employee["corporate_account_id"] != uid:
                raise err("ERR_FORBIDDEN", 403, "CorporateAdmin does not own this employee")

        # Body shape
        require_fields(body, ["unit_id", "rate_plan_id", "move_in", "planned_move_out", "deposit_held_cents"])
        require_int(body, "deposit_held_cents", minimum=0)
        try:
            move_in = parse_dt(body["move_in"])
            planned_move_out = parse_dt(body["planned_move_out"])
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", 400, "move_in/planned_move_out must be ISO 8601")

        # Business checks (order per PRD 2.8)
        # 1) master-lease active
        if lease is not None and lease["status"] != "ACTIVE":
            raise err("ERR_MASTER_LEASE_NOT_ACTIVE", 409, "Referenced master lease is not ACTIVE")
        # 2) unit occupancy separation (turnover buffer)
        _check_unit_conflict(body["unit_id"], move_in, planned_move_out)
        # 3) employee double-booking
        if employee is not None:
            _check_employee_double_booked(employee["id"], move_in, planned_move_out)
        # 4) date sanity
        if not (planned_move_out > move_in):
            raise err("ERR_INVALID_DATE_RANGE", 422, "planned_move_out must be after move_in")
        # 5) minimum term
        planned_nights = whole_days(move_in, planned_move_out)
        if planned_nights < MIN_LEASE_TERM_DAYS:
            raise err("ERR_MIN_TERM_NOT_MET", 422, "planned_nights below minimum lease term")
        # 6) capacity
        if lease is not None:
            consumed = sum(1 for s in db.data["stays"].values()
                           if s["master_lease_id"] == lease["id"] and s["status"] in ("RESERVED", "ACTIVE"))
            if consumed + 1 > lease["committed_units"]:
                raise err("ERR_MASTER_LEASE_CAP_EXCEEDED", 402, "Booking exceeds committed units")

        stay = create("stays", {
            "unit_id": body["unit_id"],
            "rate_plan_id": body["rate_plan_id"],
            "master_lease_id": body.get("master_lease_id"),
            "employee_id": body.get("employee_id"),
            "move_in": body["move_in"],
            "planned_move_out": body["planned_move_out"],
            "actual_move_out": None,
            "status": "RESERVED",
            "planned_nights": planned_nights,
            "billable_nights": None,
            "deposit_held_cents": body["deposit_held_cents"],
            "deposit_charged_cents": 0,
            "deposit_refundable_cents": body["deposit_held_cents"],
        })
        if lease is not None:
            recompute_lease(lease)
        return single("stays", stay, status=201)

    @app.route("/stays/<sid>", methods=["GET"])
    def stay_get(sid):
        auth(["PropertyManager", "CorporateAdmin", "Employee"])
        entity = must_exist("stays", sid)
        return single("stays", entity)

    @app.route("/stays", methods=["GET"])
    def stay_list():
        auth(["PropertyManager", "CorporateAdmin"])
        items = filter_by(all_of("stays"),
                          unit_id=request.args.get("unit_id"),
                          rate_plan_id=request.args.get("rate_plan_id"),
                          employee_id=request.args.get("employee_id"),
                          master_lease_id=request.args.get("master_lease_id"),
                          status=request.args.get("status"))
        return listing("stays", items)

    @app.route("/stays/<sid>/check-in", methods=["POST"])
    def stay_check_in(sid):
        auth(["PropertyManager"])
        stay = must_exist("stays", sid)
        if stay["status"] != "RESERVED":
            raise err("ERR_INVALID_STATE", 409, "Stay is not RESERVED")
        unit = get("units", stay["unit_id"])
        if unit is None or unit["status"] != "AVAILABLE":
            raise err("ERR_UNIT_NOT_AVAILABLE", 409, "Referenced unit is not AVAILABLE")
        lease = None
        if stay["master_lease_id"]:
            lease = get("master_leases", stay["master_lease_id"])
            if lease is None or lease["status"] != "ACTIVE":
                raise err("ERR_MASTER_LEASE_NOT_ACTIVE", 409, "Master lease is not ACTIVE")
        stay["status"] = "ACTIVE"
        touch(stay)
        unit["status"] = "OCCUPIED"
        touch(unit)
        create_provisional_invoice(stay)
        if lease is not None:
            recompute_lease(lease)
        return single("stays", stay)

    @app.route("/stays/<sid>/depart", methods=["POST"])
    def stay_depart(sid):
        uid, role = auth(["PropertyManager", "Employee"])
        stay = must_exist("stays", sid)
        if role == "Employee" and stay["employee_id"] != uid:
            raise err("ERR_FORBIDDEN", 403, "Employee does not own this stay")
        body = get_body()
        require_fields(body, ["actual_move_out"])
        try:
            actual_move_out = parse_dt(body["actual_move_out"])
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", 400, "actual_move_out must be ISO 8601")
        if stay["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", 409, "Stay is not ACTIVE")
        move_in = parse_dt(stay["move_in"])
        planned_move_out = parse_dt(stay["planned_move_out"])
        if actual_move_out < move_in:
            raise err("ERR_INVALID_DATE_RANGE", 422, "actual_move_out is before move_in")

        stay["actual_move_out"] = body["actual_move_out"]
        stay["billable_nights"] = whole_days(move_in, actual_move_out)
        if actual_move_out < planned_move_out:
            stay["status"] = "COMPLETED_EARLY"
        else:
            stay["status"] = "COMPLETED"
        touch(stay)

        finalize_invoice(stay)

        unit = get("units", stay["unit_id"])
        if unit is not None:
            unit["status"] = "TURNOVER"
            touch(unit)
            create("turnovers", {
                "unit_id": unit["id"],
                "stay_id": stay["id"],
                "scheduled_date": stay["actual_move_out"],
                "status": "SCHEDULED",
            })
        if stay["master_lease_id"]:
            lease = get("master_leases", stay["master_lease_id"])
            if lease is not None:
                recompute_lease(lease)
        return single("stays", stay)

    @app.route("/stays/<sid>/cancel", methods=["POST"])
    def stay_cancel(sid):
        uid, role = auth(["PropertyManager", "CorporateAdmin"])
        stay = must_exist("stays", sid)
        if role == "CorporateAdmin" and stay_owner_account_id(stay) != uid:
            raise err("ERR_FORBIDDEN", 403, "CorporateAdmin does not own this stay")
        if stay["status"] != "RESERVED":
            raise err("ERR_INVALID_STATE", 409, "Stay is not RESERVED")
        stay["status"] = "CANCELLED"
        touch(stay)
        if stay["master_lease_id"]:
            lease = get("master_leases", stay["master_lease_id"])
            if lease is not None:
                recompute_lease(lease)
        return single("stays", stay)

    # ----- HousekeepingVisit -----
    @app.route("/housekeeping-visits", methods=["POST"])
    def housekeeping_create():
        uid, role = auth(["PropertyManager", "Employee"])
        body = get_body()
        # existence
        stay = None
        if body.get("stay_id") is not None:
            stay = get("stays", body["stay_id"])
            if stay is None:
                raise err("ERR_NOT_FOUND", 404, "stay not found")
        # ownership
        if role == "Employee" and (stay is None or stay["employee_id"] != uid):
            raise err("ERR_FORBIDDEN", 403, "Employee does not own this stay")
        # body shape
        require_fields(body, ["stay_id", "scheduled_date"])
        try:
            parse_dt(body["scheduled_date"])
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", 400, "scheduled_date must be ISO 8601")
        visit_type = body.get("visit_type", "STANDARD")
        if visit_type is None:
            visit_type = "STANDARD"
        if visit_type not in ("STANDARD", "DEEP"):
            raise err("ERR_INVALID_ENUM", 422, "visit_type must be STANDARD or DEEP")
        # business: stay ACTIVE
        if stay["status"] != "ACTIVE":
            raise err("ERR_STAY_NOT_ACTIVE", 409, "Stay is not ACTIVE")
        entity = create("housekeeping_visits", {
            "stay_id": body["stay_id"],
            "scheduled_date": body["scheduled_date"],
            "visit_type": visit_type,
            "status": "SCHEDULED",
        })
        return single("housekeeping_visits", entity, status=201)

    @app.route("/housekeeping-visits/<hid>", methods=["GET"])
    def housekeeping_get(hid):
        auth(["PropertyManager", "Employee"])
        entity = must_exist("housekeeping_visits", hid)
        return single("housekeeping_visits", entity)

    @app.route("/housekeeping-visits", methods=["GET"])
    def housekeeping_list():
        auth(["PropertyManager", "Employee"])
        items = filter_by(all_of("housekeeping_visits"),
                          stay_id=request.args.get("stay_id"),
                          status=request.args.get("status"))
        return listing("housekeeping_visits", items)

    @app.route("/housekeeping-visits/<hid>/complete", methods=["POST"])
    def housekeeping_complete(hid):
        auth(["PropertyManager"])
        visit = must_exist("housekeeping_visits", hid)
        if visit["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", 409, "Visit is not SCHEDULED")
        visit["status"] = "COMPLETED"
        touch(visit)
        return single("housekeeping_visits", visit)

    @app.route("/housekeeping-visits/<hid>/cancel", methods=["POST"])
    def housekeeping_cancel(hid):
        uid, role = auth(["PropertyManager", "Employee"])
        visit = must_exist("housekeeping_visits", hid)
        if role == "Employee":
            stay = get("stays", visit["stay_id"])
            if stay is None or stay["employee_id"] != uid:
                raise err("ERR_FORBIDDEN", 403, "Employee does not own this visit")
        if visit["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", 409, "Visit is not SCHEDULED")
        visit["status"] = "CANCELLED"
        touch(visit)
        return single("housekeeping_visits", visit)

    # ----- DamageCharge -----
    @app.route("/damage-charges", methods=["POST"])
    def damage_create():
        auth(["PropertyManager"])
        body = get_body()
        if body.get("stay_id") is not None:
            if get("stays", body["stay_id"]) is None:
                raise err("ERR_NOT_FOUND", 404, "stay not found")
        require_fields(body, ["stay_id", "amount_cents", "description"])
        require_int(body, "amount_cents", gt=0)
        entity = create("damage_charges", {
            "stay_id": body["stay_id"],
            "amount_cents": body["amount_cents"],
            "description": body["description"],
            "status": "ASSESSED",
        })
        return single("damage_charges", entity, status=201)

    @app.route("/damage-charges/<did>", methods=["GET"])
    def damage_get(did):
        auth(["PropertyManager", "Employee"])
        entity = must_exist("damage_charges", did)
        return single("damage_charges", entity)

    @app.route("/damage-charges", methods=["GET"])
    def damage_list():
        auth(["PropertyManager", "Employee"])
        items = filter_by(all_of("damage_charges"),
                          stay_id=request.args.get("stay_id"),
                          status=request.args.get("status"))
        return listing("damage_charges", items)

    @app.route("/damage-charges/<did>/charge", methods=["POST"])
    def damage_charge(did):
        auth(["PropertyManager"])
        charge = must_exist("damage_charges", did)
        if charge["status"] not in ("ASSESSED", "DISPUTED"):
            raise err("ERR_INVALID_STATE", 409, "Damage charge not in a chargeable state")
        stay = get("stays", charge["stay_id"])
        _, refundable = core.stay_deposit(stay)
        if charge["amount_cents"] > refundable:
            raise err("ERR_DAMAGE_EXCEEDS_DEPOSIT", 402, "Damage charge would overdraw the deposit")
        charge["status"] = "CHARGED"
        touch(charge)
        recompute_stay_deposit(stay)
        return single("damage_charges", charge)

    @app.route("/damage-charges/<did>/dispute", methods=["POST"])
    def damage_dispute(did):
        uid, role = auth(["Employee"])
        charge = must_exist("damage_charges", did)
        stay = get("stays", charge["stay_id"])
        if stay is None or stay["employee_id"] != uid:
            raise err("ERR_FORBIDDEN", 403, "Employee does not own this stay")
        if charge["status"] != "ASSESSED":
            raise err("ERR_INVALID_STATE", 409, "Damage charge is not ASSESSED")
        charge["status"] = "DISPUTED"
        touch(charge)
        return single("damage_charges", charge)

    @app.route("/damage-charges/<did>/waive", methods=["POST"])
    def damage_waive(did):
        auth(["PropertyManager"])
        charge = must_exist("damage_charges", did)
        if charge["status"] not in ("DISPUTED", "CHARGED"):
            raise err("ERR_INVALID_STATE", 409, "Damage charge not in a waivable state")
        was_charged = charge["status"] == "CHARGED"
        charge["status"] = "WAIVED"
        touch(charge)
        if was_charged:
            stay = get("stays", charge["stay_id"])
            recompute_stay_deposit(stay)
        return single("damage_charges", charge)

    # ----- Invoice -----
    @app.route("/invoices/<iid>", methods=["GET"])
    def invoice_get(iid):
        auth(["PropertyManager", "CorporateAdmin"])
        entity = must_exist("invoices", iid)
        return single("invoices", entity)

    @app.route("/invoices", methods=["GET"])
    def invoice_list():
        auth(["PropertyManager", "CorporateAdmin"])
        items = filter_by(all_of("invoices"),
                          stay_id=request.args.get("stay_id"),
                          status=request.args.get("status"))
        return listing("invoices", items)

    @app.route("/invoices/<iid>/pay", methods=["POST"])
    def invoice_pay(iid):
        uid, role = auth(["PropertyManager", "CorporateAdmin"])
        invoice = must_exist("invoices", iid)
        if role == "CorporateAdmin":
            stay = get("stays", invoice["stay_id"])
            if stay is None or stay_owner_account_id(stay) != uid:
                raise err("ERR_FORBIDDEN", 403, "CorporateAdmin does not own this invoice")
        if invoice["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", 409, "Invoice is not ISSUED")
        invoice["status"] = "PAID"
        touch(invoice)
        return single("invoices", invoice)

    # ----- Turnover -----
    @app.route("/turnovers/<tid>", methods=["GET"])
    def turnover_get(tid):
        auth(["PropertyManager"])
        entity = must_exist("turnovers", tid)
        return single("turnovers", entity)

    @app.route("/turnovers", methods=["GET"])
    def turnover_list():
        auth(["PropertyManager"])
        items = filter_by(all_of("turnovers"),
                          unit_id=request.args.get("unit_id"),
                          stay_id=request.args.get("stay_id"),
                          status=request.args.get("status"))
        return listing("turnovers", items)

    @app.route("/turnovers/<tid>/complete", methods=["POST"])
    def turnover_complete(tid):
        auth(["PropertyManager"])
        turnover = must_exist("turnovers", tid)
        if turnover["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", 409, "Turnover is not SCHEDULED")
        turnover["status"] = "COMPLETED"
        touch(turnover)
        unit = get("units", turnover["unit_id"])
        if unit is not None:
            unit["status"] = "AVAILABLE"
            touch(unit)
        return single("turnovers", turnover)


# ---------------------------------------------------------------------------
# Temporal conflict helpers
# ---------------------------------------------------------------------------
def _check_unit_conflict(unit_id, move_in, planned_move_out):
    from datetime import timedelta
    buffer = timedelta(days=TURNOVER_BUFFER_DAYS)
    for s in db.data["stays"].values():
        if s["unit_id"] != unit_id or s["status"] == "CANCELLED":
            continue
        ex_in = parse_dt(s["move_in"])
        ex_out = parse_dt(s["planned_move_out"])
        separated = (move_in >= ex_out + buffer) or (ex_in >= planned_move_out + buffer)
        if not separated:
            raise err("ERR_UNIT_TIME_CONFLICT", 409, "Stay conflicts with another stay on the same unit")


def _check_employee_double_booked(employee_id, move_in, planned_move_out):
    for s in db.data["stays"].values():
        if s.get("employee_id") != employee_id or s["status"] == "CANCELLED":
            continue
        ex_in = parse_dt(s["move_in"])
        ex_out = parse_dt(s["planned_move_out"])
        # half-open overlap: [a,b) overlaps [c,d) iff a < d and c < b
        if move_in < ex_out and ex_in < planned_move_out:
            raise err("ERR_EMPLOYEE_DOUBLE_BOOKED", 409, "Employee already booked in an overlapping window")
