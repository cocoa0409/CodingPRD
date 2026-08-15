"""Planting contracts, crews, crew assignments."""
from datetime import timedelta

from server import (STORE, app, bad_request, body, calc_required_seedlings, ceil_div,
                 create_record, dec, err, get_path, invalid_state, order_allocated,
                 require_owner, require_role, ser_assignment, ser_contract, ser_crew,
                 success, success_list, today, touch, v_date, v_fk, v_int, v_num, v_str)
from server import request_arg

CO = "ContractOfficer"
FA = "FieldAuditor"
PA = "ProgramAdministrator"
LO = "Landowner"


# ---------------------------------------------------------------------------
# Planting contracts
# ---------------------------------------------------------------------------
@app.route("/reforestation/planting-contracts", methods=["POST"])
def create_contract():
    require_role([CO])
    d = body()
    landowner = v_fk(d, "landowner_id", "landowners")
    order = v_fk(d, "seedling_order_id", "seedling_orders")
    zone = v_fk(d, "site_zone_id", "seed_zones")
    acres = v_num(d, "acres")
    if not (acres > 0):
        bad_request("acres must be > 0")
    tpa = d.get("trees_per_acre")
    # Spacing spec (priority 16) precedes window sanity (priority 17).
    if tpa is not None:
        from server import is_int
        if not is_int(tpa):
            bad_request("trees_per_acre must be an integer")
        tpa = int(tpa)
        if not (200 <= tpa <= 800):
            err("ERR_SPACING_SPEC_INVALID", 422, "trees_per_acre outside [200, 800]")
    else:
        bad_request("missing required field: trees_per_acre")
    contingency = v_num(d, "contingency_pct")
    if not (0 <= contingency <= 0.25):
        bad_request("contingency_pct must be within [0, 0.25]")
    pw_start = v_date(d, "planting_window_start")
    pw_end = v_date(d, "planting_window_end")
    if pw_end < pw_start:
        err("ERR_WINDOW_INVERTED", 400, "planting_window_end must be >= planting_window_start")
    rec = create_record("planting_contracts", {
        "landowner_id": landowner["id"],
        "seedling_order_id": order["id"],
        "site_zone_id": zone["id"],
        "acres": acres,
        "trees_per_acre": tpa,
        "contingency_pct": contingency,
        "required_seedlings": calc_required_seedlings(acres, tpa, contingency),
        "planting_window_start": pw_start,
        "planting_window_end": pw_end,
        "herbicide_applied_on": None,
        "site_prep_status": "NONE",
        "last_planted_on": None,
        "planted_quantity": 0,
        "status": "DRAFT",
    })
    return success(ser_contract(rec), 201)


@app.route("/reforestation/planting-contracts/<rid>", methods=["GET"])
def get_contract(rid):
    uid, role = require_role([CO, FA, PA, LO])
    rec = get_path("planting_contracts", rid)
    if role == LO:
        require_owner(rec, uid)
    return success(ser_contract(rec))


@app.route("/reforestation/planting-contracts", methods=["GET"])
def list_contracts():
    uid, role = require_role([CO, FA, PA, LO])
    items = list(STORE["planting_contracts"].values())
    if role == LO:
        items = [r for r in items if r["landowner_id"] == uid]
    for f in ("landowner_id", "site_zone_id", "seedling_order_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_contract)


@app.route("/reforestation/planting-contracts/<rid>/record-site-prep", methods=["POST"])
def record_site_prep(rid):
    require_role([CO])
    contract = get_path("planting_contracts", rid)
    if contract["status"] not in ("DRAFT", "REPLANT_REQUIRED"):
        invalid_state("site prep can be recorded only from DRAFT or REPLANT_REQUIRED")
    d = body()
    applied_on = v_date(d, "herbicide_applied_on")
    if applied_on > today():
        bad_request("herbicide_applied_on may not lie in the future")
    contract["herbicide_applied_on"] = applied_on
    contract["site_prep_status"] = "RECORDED"
    contract["status"] = "SITE_PREP"
    touch(contract)
    return success(ser_contract(contract))


@app.route("/reforestation/planting-contracts/<rid>/verify-site-prep", methods=["POST"])
def verify_site_prep(rid):
    require_role([FA])
    contract = get_path("planting_contracts", rid)
    if contract["site_prep_status"] != "RECORDED":
        err("ERR_SITE_PREP_NOT_VERIFIED", 422,
            "site prep must be RECORDED before a FieldAuditor can verify it")
    contract["site_prep_status"] = "VERIFIED"
    touch(contract)
    return success(ser_contract(contract))


@app.route("/reforestation/planting-contracts/<rid>/mark-ready", methods=["POST"])
def mark_ready(rid):
    require_role([CO])
    contract = get_path("planting_contracts", rid)
    if contract["status"] not in ("SITE_PREP", "BLOCKED"):
        invalid_state("only SITE_PREP or BLOCKED contracts can be marked ready")
    if contract["site_prep_status"] != "VERIFIED":
        err("ERR_SITE_PREP_NOT_VERIFIED", 422, "site prep is not VERIFIED")
    order = STORE["seedling_orders"].get(contract["seedling_order_id"])
    if order is None or order_allocated(order["id"]) < contract["required_seedlings"]:
        err("ERR_ORDER_UNDER_ALLOCATED", 422,
            "order allocated_quantity below required_seedlings")
    contract["status"] = "READY_TO_PLANT"
    touch(contract)
    return success(ser_contract(contract))


@app.route("/reforestation/planting-contracts/<rid>/start-planting", methods=["POST"])
def start_planting(rid):
    require_role([CO])
    contract = get_path("planting_contracts", rid)
    if contract["status"] != "READY_TO_PLANT":
        invalid_state("only a READY_TO_PLANT contract can start planting")
    # Transition preconditions without a dedicated §2.6 rule fall under rule 5
    # (state legality, ERR_INVALID_STATE) and precede the rule-9 herbicide gate.
    covering = any(
        a["planting_contract_id"] == contract["id"] and a["status"] == "CONFIRMED"
        and a["start_date"] <= today() < a["end_date"]
        for a in STORE["crew_assignments"].values())
    if not covering:
        invalid_state("no CONFIRMED crew assignment covers the current date")
    if not (contract["planting_window_start"] <= today() <= contract["planting_window_end"]):
        invalid_state("current date outside the planting window")
    age = (today() - contract["herbicide_applied_on"]).days
    if not (14 <= age <= 120):
        err("ERR_SITE_PREP_WINDOW_INVALID", 422,
            "herbicide age outside [14, 120] days")
    contract["status"] = "PLANTING"
    touch(contract)
    return success(ser_contract(contract))


@app.route("/reforestation/planting-contracts/<rid>/complete-planting", methods=["POST"])
def complete_planting(rid):
    require_role([CO])
    contract = get_path("planting_contracts", rid)
    if contract["status"] != "PLANTING":
        invalid_state("only a PLANTING contract can complete planting")
    d = body()
    planted_qty = v_int(d, "planted_qty", minimum=1)
    from server import contract_obligation_count
    if contract_obligation_count(contract["id"]) == 0:
        floor = dec(contract["acres"]) * contract["trees_per_acre"]
        if dec(planted_qty) < floor:
            err("ERR_PLANTING_QUANTITY_SHORT", 422,
                "planted_qty below acres * trees_per_acre")
    else:
        open_surveys = [s for s in STORE["survival_surveys"].values()
                        if s["planting_contract_id"] == contract["id"]
                        and s["obligation_status"] in ("OPEN", "SCHEDULED")]
        if open_surveys:
            driving = max(open_surveys, key=lambda s: s["_seq"])
            floor = driving["owed_quantity"]
        else:
            floor = dec(contract["acres"]) * contract["trees_per_acre"]
        if planted_qty < floor:
            err("ERR_PLANTING_QUANTITY_SHORT", 422,
                "planted_qty below the driving obligation's owed_quantity")
    contract["planted_quantity"] += planted_qty
    contract["last_planted_on"] = today()
    contract["status"] = "PLANTED"
    touch(contract)
    for a in STORE["crew_assignments"].values():
        if a["planting_contract_id"] == contract["id"] and a["status"] == "CONFIRMED":
            a["status"] = "COMPLETED"
            touch(a)
    return success(ser_contract(contract))


@app.route("/reforestation/planting-contracts/<rid>/cancel", methods=["POST"])
def cancel_contract(rid):
    require_role([CO])
    contract = get_path("planting_contracts", rid)
    if contract["status"] not in ("DRAFT", "SITE_PREP", "READY_TO_PLANT", "BLOCKED"):
        invalid_state("contract cannot be cancelled from its current state")
    blocking = any(s["planting_contract_id"] == contract["id"]
                   and s["status"] in ("DISPATCHED", "DELIVERED", "PLANTED")
                   for s in STORE["shipments"].values())
    if blocking:
        err("ERR_NOT_CANCELLABLE", 409, "contract has shipments")
    for a in STORE["crew_assignments"].values():
        if a["planting_contract_id"] == contract["id"] and a["status"] in ("SCHEDULED", "CONFIRMED"):
            a["status"] = "RELEASED"
            touch(a)
    contract["status"] = "CANCELLED"
    touch(contract)
    return success(ser_contract(contract))


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------
@app.route("/reforestation/crews", methods=["POST"])
def create_crew():
    require_role([CO])
    d = body()
    crew_code = v_str(d, "crew_code")
    capacity = v_int(d, "capacity_per_day", minimum=1)
    from server import v_bool
    active = v_bool(d, "active", True)
    if any(c["crew_code"] == crew_code for c in STORE["crews"].values()):
        bad_request("crew_code must be unique")
    rec = create_record("crews", {
        "crew_code": crew_code, "capacity_per_day": capacity, "active": active,
    })
    return success(ser_crew(rec), 201)


@app.route("/reforestation/crews/<rid>", methods=["GET"])
def get_crew(rid):
    require_role([CO])
    return success(ser_crew(get_path("crews", rid)))


# ---------------------------------------------------------------------------
# Crew assignments
# ---------------------------------------------------------------------------
def assignment_days(a):
    return (a["end_date"] - a["start_date"]).days


def daily_load(a):
    return ceil_div(a["planned_seedlings"], assignment_days(a))


def overlaps(s1, e1, s2, e2):
    """Half-open interval intersection."""
    return s1 < e2 and s2 < e1


@app.route("/reforestation/crew-assignments", methods=["POST"])
def create_assignment():
    require_role([CO])
    d = body()
    crew = v_fk(d, "crew_id", "crews")
    contract = v_fk(d, "planting_contract_id", "planting_contracts")
    start = v_date(d, "start_date")
    end = v_date(d, "end_date")
    # Crew overlap (priority 15) precedes window sanity (priority 17).
    for x in STORE["crew_assignments"].values():
        if x["crew_id"] != crew["id"] or x["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        if x["planting_contract_id"] == contract["id"]:
            # Same contract: exact adjacency allowed, intersection forbidden.
            if overlaps(start, end, x["start_date"], x["end_date"]):
                err("ERR_CREW_OVERLAP", 409, "crew interval intersects an existing assignment")
        else:
            # Different contracts: require a full day of buffer.
            allowed = (start >= x["end_date"] + timedelta(days=1)
                       or end <= x["start_date"] - timedelta(days=1))
            if not allowed:
                err("ERR_CREW_OVERLAP", 409,
                    "cross-contract assignments require a one-day buffer")
    if end <= start:
        err("ERR_WINDOW_INVERTED", 400, "end_date must be strictly after start_date")
    planned = v_int(d, "planned_seedlings", minimum=1)
    # Capacity: per-date free capacity over the new interval.
    new_daily = ceil_div(planned, (end - start).days)
    day = start
    while day < end:
        used = sum(daily_load(x) for x in STORE["crew_assignments"].values()
                   if x["crew_id"] == crew["id"] and x["status"] in ("SCHEDULED", "CONFIRMED")
                   and x["start_date"] <= day < x["end_date"])
        if new_daily > crew["capacity_per_day"] - used:
            err("ERR_CREW_CAPACITY_EXCEEDED", 422,
                "crew free capacity exceeded on %s" % day.isoformat())
        day += timedelta(days=1)
    rec = create_record("crew_assignments", {
        "crew_id": crew["id"],
        "planting_contract_id": contract["id"],
        "start_date": start,
        "end_date": end,
        "planned_seedlings": planned,
        "status": "SCHEDULED",
    })
    return success(ser_assignment(rec), 201)


@app.route("/reforestation/crew-assignments/<rid>", methods=["GET"])
def get_assignment(rid):
    require_role([CO])
    return success(ser_assignment(get_path("crew_assignments", rid)))


@app.route("/reforestation/crew-assignments", methods=["GET"])
def list_assignments():
    require_role([CO])
    items = list(STORE["crew_assignments"].values())
    for f in ("crew_id", "planting_contract_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_assignment)


@app.route("/reforestation/crew-assignments/<rid>/confirm", methods=["POST"])
def confirm_assignment(rid):
    require_role([CO])
    a = get_path("crew_assignments", rid)
    if a["status"] != "SCHEDULED":
        invalid_state("only a SCHEDULED assignment can be confirmed")
    contract = STORE["planting_contracts"].get(a["planting_contract_id"])
    if contract is None or contract["status"] not in ("SITE_PREP", "READY_TO_PLANT", "BLOCKED"):
        invalid_state("contract state forbids confirming the assignment")
    a["status"] = "CONFIRMED"
    touch(a)
    return success(ser_assignment(a))


@app.route("/reforestation/crew-assignments/<rid>/release", methods=["POST"])
def release_assignment(rid):
    require_role([CO])
    a = get_path("crew_assignments", rid)
    if a["status"] not in ("SCHEDULED", "CONFIRMED"):
        invalid_state("only SCHEDULED or CONFIRMED assignments can be released")
    a["status"] = "RELEASED"
    touch(a)
    return success(ser_assignment(a))
