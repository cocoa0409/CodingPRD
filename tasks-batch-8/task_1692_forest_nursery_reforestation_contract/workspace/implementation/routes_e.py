"""Shipments, survival surveys, cost-share enrollments."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from server import (CLOCK, COST_SHARE_THRESHOLD, HANDLING_WINDOW_HOURS, COLD_STORAGE_MAX_DAYS,
                 REPEAT_FAILURE_FACTOR, ESCALATION_CAP_MULT, SPOILAGE_REASONS,
                 STANDARD_THRESHOLD, STORE, app, bad_request, body, calc_award,
                 check_batch_depleted, create_record, dec, err, fmt_dt, get_path,
                 invalid_state, order_shipped, release_payment_holds, require_owner,
                 require_role, seed_transfer_ok, ser_enrollment, ser_shipment,
                 ser_survey, success, success_list, today, touch, v_date, v_datetime,
                 v_enum, v_fk, v_int, v_num, v_str, contract_obligation_count)
from server import request_arg

NM = "NurseryManager"
CO = "ContractOfficer"
FA = "FieldAuditor"
PA = "ProgramAdministrator"
LO = "Landowner"


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------
@app.route("/reforestation/shipments", methods=["POST"])
def create_shipment():
    require_role([NM])
    d = body()
    contract = v_fk(d, "planting_contract_id", "planting_contracts")
    batch = v_fk(d, "crop_batch_id", "crop_batches")
    # Cross-entity state gate (priority 5).
    if contract["status"] not in ("READY_TO_PLANT", "PLANTING"):
        invalid_state("destination contract must be READY_TO_PLANT or PLANTING")
    lot = STORE["seed_lots"].get(batch["seed_lot_id"])
    if lot is not None and lot["status"] == "QUARANTINED":
        err("ERR_LOT_QUARANTINED", 422, "seed lot is quarantined")
    # Simulate oldest-first withdrawal to determine touched placements and
    # enforce the cold-storage stock-age rule (priority 12).
    qty_raw = d.get("quantity")
    qty_valid = isinstance(qty_raw, int) and not isinstance(qty_raw, bool) and qty_raw > 0
    if isinstance(qty_raw, float) and qty_raw.is_integer():
        qty_valid = qty_raw > 0
    dispatch_date = today()
    actives = sorted(
        (p for p in STORE["storage_placements"].values()
         if p["crop_batch_id"] == batch["id"] and p["status"] == "ACTIVE"
         and p["quantity"] - p["withdrawn_quantity"] > 0),
        key=lambda p: (p["placed_on"], p["_seq"]))
    touched = []
    if qty_valid:
        need = int(qty_raw)
        for p in actives:
            avail = p["quantity"] - p["withdrawn_quantity"]
            take = min(avail, need)
            touched.append((p, take))
            need -= take
            if need == 0:
                break
    for p, _take in touched:
        if (dispatch_date - p["placed_on"]).days > COLD_STORAGE_MAX_DAYS:
            err("ERR_STOCK_AGE_EXCEEDED", 422,
                "placement %s exceeds the 45-day cold-storage limit" % p["id"])
    # Seed-transfer rule (priority 14).
    order = STORE["seedling_orders"].get(contract["seedling_order_id"])
    dest_zone = STORE["seed_zones"].get(contract["site_zone_id"])
    if order is None or lot is None or dest_zone is None \
            or not seed_transfer_ok(batch, order, dest_zone):
        err("ERR_SPECIES_ZONE_MISMATCH", 422,
            "species mismatch or elevation midpoints more than 500 ft apart")
    # Request shape (priority 18).
    if not qty_valid:
        bad_request("quantity must be a positive integer")
    quantity = int(qty_raw)
    # Batch grading status (priority 19).
    if batch["status"] != "GRADED":
        err("ERR_BATCH_NOT_GRADED", 422, "shipment batch must be GRADED")
    # Sufficiency (priority 21.5/22).
    stored = sum(p["quantity"] - p["withdrawn_quantity"] for p in actives)
    allocated_here = sum(a["quantity"] for a in STORE["allocations"].values()
                         if a["crop_batch_id"] == batch["id"]
                         and a["seedling_order_id"] == order["id"]
                         and a["status"] == "ACTIVE")
    if stored < quantity or allocated_here < quantity:
        err("ERR_INSUFFICIENT_STORED_STOCK", 422,
            "insufficient stored stock or active allocations on this batch")
    # Apply the withdrawal oldest-first.
    need = quantity
    for p in actives:
        avail = p["quantity"] - p["withdrawn_quantity"]
        take = min(avail, need)
        if take > 0:
            p["withdrawn_quantity"] += take
            if p["withdrawn_quantity"] == p["quantity"]:
                p["status"] = "WITHDRAWN"
            touch(p)
            need -= take
        if need == 0:
            break
    dispatched = CLOCK["now"]
    rec = create_record("shipments", {
        "planting_contract_id": contract["id"],
        "crop_batch_id": batch["id"],
        "quantity": quantity,
        "dispatched_at": dispatched,
        "handling_deadline": dispatched + timedelta(hours=HANDLING_WINDOW_HOURS),
        "delivered_at": None,
        "planted_confirmed_at": None,
        "spoilage_reason": None,
        "status": "DISPATCHED",
    })
    # Order auto-fulfilment.
    if order["status"] == "ALLOCATED" and order_shipped(order["id"]) >= order["quantity"]:
        order["status"] = "FULFILLED"
        touch(order)
    check_batch_depleted(batch)
    return success(ser_shipment(rec), 201)


@app.route("/reforestation/shipments/<rid>", methods=["GET"])
def get_shipment(rid):
    require_role([NM, CO, FA])
    return success(ser_shipment(get_path("shipments", rid)))


@app.route("/reforestation/shipments", methods=["GET"])
def list_shipments():
    require_role([NM, CO, FA])
    items = list(STORE["shipments"].values())
    for f in ("planting_contract_id", "crop_batch_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_shipment)


@app.route("/reforestation/shipments/<rid>/deliver", methods=["POST"])
def deliver_shipment(rid):
    require_role([NM])
    shipment = get_path("shipments", rid)
    if shipment["status"] != "DISPATCHED":
        invalid_state("only a DISPATCHED shipment can be delivered")
    d = body()
    delivered_at = v_datetime(d, "delivered_at")
    if delivered_at < shipment["dispatched_at"]:
        bad_request("delivered_at may not precede dispatched_at")
    shipment["delivered_at"] = delivered_at
    shipment["status"] = "DELIVERED"
    touch(shipment)
    return success(ser_shipment(shipment))


@app.route("/reforestation/shipments/<rid>/confirm-planted", methods=["POST"])
def confirm_planted(rid):
    require_role([CO])
    shipment = get_path("shipments", rid)
    if shipment["status"] != "DELIVERED":
        invalid_state("only a DELIVERED shipment can be confirmed planted")
    contract = STORE["planting_contracts"].get(shipment["planting_contract_id"])
    if contract is None or contract["status"] != "PLANTING":
        invalid_state("destination contract must be PLANTING")
    d = body()
    confirmed_at = v_datetime(d, "planted_confirmed_at")
    if confirmed_at > shipment["handling_deadline"]:
        err("ERR_HANDLING_WINDOW_EXCEEDED", 422,
            "planted_confirmed_at later than dispatched_at + 72h")
    shipment["planted_confirmed_at"] = confirmed_at
    shipment["status"] = "PLANTED"
    touch(shipment)
    return success(ser_shipment(shipment))


@app.route("/reforestation/shipments/<rid>/report-spoilage", methods=["POST"])
def report_spoilage(rid):
    require_role([FA])
    shipment = get_path("shipments", rid)
    if shipment["status"] not in ("DISPATCHED", "DELIVERED"):
        invalid_state("only DISPATCHED or DELIVERED shipments can be spoiled")
    d = body()
    reason = v_enum(d, "reason", SPOILAGE_REASONS)
    shipment["spoilage_reason"] = reason
    shipment["status"] = "SPOILED"
    touch(shipment)
    return success(ser_shipment(shipment))


# ---------------------------------------------------------------------------
# Survival surveys
# ---------------------------------------------------------------------------
@app.route("/reforestation/survival-surveys", methods=["POST"])
def create_survey():
    require_role([FA])
    d = body()
    contract = v_fk(d, "planting_contract_id", "planting_contracts")
    if contract["status"] != "PLANTED":
        invalid_state("surveys may be recorded only for PLANTED contracts")
    surveyed_on = v_date(d, "surveyed_on")
    last = contract["last_planted_on"]
    if not (last + timedelta(days=300) <= surveyed_on <= last + timedelta(days=400)):
        err("ERR_SURVEY_WINDOW_INVALID", 422,
            "surveyed_on outside [last_planted_on + 300, last_planted_on + 400]")
    alive_count = v_int(d, "alive_count", minimum=0)
    snapshot = contract["planted_quantity"]
    if alive_count > snapshot:
        bad_request("alive_count may not exceed the planted count")
    # Threshold variant: cost-share landowner judged at 80.00.
    landowner_id = contract["landowner_id"]
    has_cost_share = any(
        e["landowner_id"] == landowner_id and e["status"] in ("APPROVED", "PAYMENT_HELD", "PAID")
        for e in STORE["cost_share_enrollments"].values())
    threshold = COST_SHARE_THRESHOLD if has_cost_share else STANDARD_THRESHOLD
    survival = (Decimal(alive_count) * 100 / Decimal(snapshot)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    below = survival < threshold
    prior_failures = contract_obligation_count(contract["id"])
    if below:
        required_surviving = int((Decimal(contract["required_seedlings"]) * threshold / 100)
                                 .to_integral_value(rounding=ROUND_CEILING))
        base = max(0, required_surviving - alive_count)
        if prior_failures >= 1:
            owed = int((Decimal(base) * REPEAT_FAILURE_FACTOR)
                       .to_integral_value(rounding=ROUND_CEILING))
        else:
            owed = base
        owed = min(ESCALATION_CAP_MULT * snapshot, min(snapshot, owed))
        obligation_status = "OPEN"
    else:
        owed = 0
        obligation_status = "NONE"
    rec = create_record("survival_surveys", {
        "planting_contract_id": contract["id"],
        "surveyed_on": surveyed_on,
        "planted_count_snapshot": snapshot,
        "alive_count": alive_count,
        "survival_pct": float(survival),
        "threshold_pct": float(threshold),
        "below_threshold": below,
        "owed_quantity": owed,
        "replant_date": None,
        "waiver_reason": None,
        "obligation_status": obligation_status,
    })
    # Contract PLANTED -> SURVEYED -> CLOSED or REPLANT_REQUIRED (one mutation).
    contract["status"] = "REPLANT_REQUIRED" if below else "CLOSED"
    touch(contract)
    if below:
        # CASCADE B: release pending crew work; hold approved cost-share money.
        for a in STORE["crew_assignments"].values():
            if a["planting_contract_id"] == contract["id"] \
                    and a["status"] in ("SCHEDULED", "CONFIRMED"):
                a["status"] = "RELEASED"
                touch(a)
        for e in STORE["cost_share_enrollments"].values():
            if e["landowner_id"] == landowner_id and e["status"] == "APPROVED":
                e["status"] = "PAYMENT_HELD"
                touch(e)
    return success(ser_survey(rec), 201)


@app.route("/reforestation/survival-surveys/<rid>", methods=["GET"])
def get_survey(rid):
    require_role([FA, CO, PA])
    return success(ser_survey(get_path("survival_surveys", rid)))


@app.route("/reforestation/survival-surveys", methods=["GET"])
def list_surveys():
    require_role([FA, CO, PA])
    items = list(STORE["survival_surveys"].values())
    val = request_arg("planting_contract_id")
    if val is not None:
        items = [r for r in items if r["planting_contract_id"] == val]
    return success_list(items, ser_survey)


@app.route("/reforestation/survival-surveys/<rid>/schedule-replant", methods=["POST"])
def schedule_replant(rid):
    require_role([CO])
    survey = get_path("survival_surveys", rid)
    if survey["obligation_status"] != "OPEN":
        invalid_state("only an OPEN obligation can be scheduled")
    d = body()
    replant_date = v_date(d, "replant_date")
    if replant_date < today():
        bad_request("replant_date may not precede the current date")
    survey["replant_date"] = replant_date
    survey["obligation_status"] = "SCHEDULED"
    touch(survey)
    return success(ser_survey(survey))


@app.route("/reforestation/survival-surveys/<rid>/reopen-replant", methods=["POST"])
def reopen_replant(rid):
    require_role([CO])
    survey = get_path("survival_surveys", rid)
    if survey["obligation_status"] != "SCHEDULED":
        invalid_state("only a SCHEDULED obligation can be reopened")
    survey["replant_date"] = None
    survey["obligation_status"] = "OPEN"
    touch(survey)
    return success(ser_survey(survey))


@app.route("/reforestation/survival-surveys/<rid>/fulfill-replant", methods=["POST"])
def fulfill_replant(rid):
    require_role([CO])
    survey = get_path("survival_surveys", rid)
    if survey["obligation_status"] != "SCHEDULED":
        invalid_state("only a SCHEDULED obligation can be fulfilled")
    contract = STORE["planting_contracts"].get(survey["planting_contract_id"])
    survey_created_date = parse_iso_date_part(survey["created_at"])
    if contract is None or contract["status"] not in ("PLANTED", "SURVEYED", "CLOSED") \
            or contract["last_planted_on"] is None \
            or not (contract["last_planted_on"] > survey_created_date):
        invalid_state("no replant cycle completed after this survey")
    survey["obligation_status"] = "FULFILLED"
    touch(survey)
    release_payment_holds(contract["landowner_id"])
    return success(ser_survey(survey))


def parse_iso_date_part(iso_ts):
    return datetime.strptime(iso_ts[:10], "%Y-%m-%d").date()


from datetime import datetime  # noqa: E402


@app.route("/reforestation/survival-surveys/<rid>/waive-replant", methods=["POST"])
def waive_replant(rid):
    require_role([PA])
    survey = get_path("survival_surveys", rid)
    if survey["obligation_status"] != "OPEN":
        invalid_state("only an OPEN obligation can be waived")
    d = body()
    reason = v_str(d, "waiver_reason")
    survey["waiver_reason"] = reason
    survey["obligation_status"] = "WAIVED"
    touch(survey)
    contract = STORE["planting_contracts"].get(survey["planting_contract_id"])
    if contract is not None:
        release_payment_holds(contract["landowner_id"])
    return success(ser_survey(survey))


# ---------------------------------------------------------------------------
# Cost-share enrollments
# ---------------------------------------------------------------------------
@app.route("/reforestation/cost-share-enrollments", methods=["POST"])
def create_enrollment():
    uid, role = require_role([LO])
    d = body()
    landowner_id = d.get("landowner_id")
    if landowner_id is None:
        bad_request("missing required field: landowner_id")
    if not isinstance(landowner_id, str):
        bad_request("landowner_id must be a string id")
    if landowner_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Landowner may enroll only its own account")
    program_code = v_str(d, "program_code")
    enrolled_acres = v_num(d, "enrolled_acres")
    if not (enrolled_acres > 0):
        bad_request("enrolled_acres must be > 0")
    rate = v_int(d, "rate_per_acre_cents", minimum=1)
    cap = v_int(d, "cap_cents", minimum=1)
    rec = create_record("cost_share_enrollments", {
        "landowner_id": landowner_id,
        "program_code": program_code,
        "enrolled_acres": enrolled_acres,
        "rate_per_acre_cents": rate,
        "cap_cents": cap,
        "documented_acres": None,
        "documented_cost_cents": None,
        "provisional_award_cents": calc_award(enrolled_acres, rate, cap),
        "final_award_cents": None,
        "paid_cents": 0,
        "status": "DRAFT",
    })
    return success(ser_enrollment(rec), 201)


@app.route("/reforestation/cost-share-enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    uid, role = require_role([LO, PA])
    rec = get_path("cost_share_enrollments", rid)
    if role == LO:
        require_owner(rec, uid)
    return success(ser_enrollment(rec))


@app.route("/reforestation/cost-share-enrollments", methods=["GET"])
def list_enrollments():
    uid, role = require_role([LO, PA])
    items = list(STORE["cost_share_enrollments"].values())
    if role == LO:
        items = [r for r in items if r["landowner_id"] == uid]
    for f in ("landowner_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_enrollment)


@app.route("/reforestation/cost-share-enrollments/<rid>/submit", methods=["POST"])
def submit_enrollment(rid):
    uid, role = require_role([LO])
    rec = get_path("cost_share_enrollments", rid)
    require_owner(rec, uid)
    if rec["status"] != "DRAFT":
        invalid_state("only a DRAFT enrollment can be submitted")
    d = body()
    documented_acres = v_num(d, "documented_acres")
    if not (documented_acres > 0):
        bad_request("documented_acres must be > 0")
    documented_cost = v_int(d, "documented_cost_cents", minimum=1)
    if documented_acres > rec["enrolled_acres"]:
        err("ERR_ENROLLMENT_ACRES_EXCEEDED", 422,
            "documented_acres exceeds enrolled_acres")
    rec["documented_acres"] = documented_acres
    rec["documented_cost_cents"] = documented_cost
    rec["provisional_award_cents"] = calc_award(
        documented_acres, rec["rate_per_acre_cents"], rec["cap_cents"])
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return success(ser_enrollment(rec))


@app.route("/reforestation/cost-share-enrollments/<rid>/approve", methods=["POST"])
def approve_enrollment(rid):
    require_role([PA])
    rec = get_path("cost_share_enrollments", rid)
    if rec["status"] != "UNDER_REVIEW":
        invalid_state("only an UNDER_REVIEW enrollment can be approved")
    rec["final_award_cents"] = calc_award(
        rec["documented_acres"], rec["rate_per_acre_cents"], rec["cap_cents"])
    rec["status"] = "APPROVED"
    touch(rec)
    return success(ser_enrollment(rec))


@app.route("/reforestation/cost-share-enrollments/<rid>/return-for-correction", methods=["POST"])
def return_enrollment(rid):
    require_role([PA])
    rec = get_path("cost_share_enrollments", rid)
    if rec["status"] != "UNDER_REVIEW":
        invalid_state("only an UNDER_REVIEW enrollment can be returned")
    d = body()
    v_str(d, "reason")
    rec["status"] = "DRAFT"
    touch(rec)
    return success(ser_enrollment(rec))


@app.route("/reforestation/cost-share-enrollments/<rid>/pay", methods=["POST"])
def pay_enrollment(rid):
    require_role([PA])
    rec = get_path("cost_share_enrollments", rid)
    if rec["status"] == "PAYMENT_HELD":
        err("ERR_PAYMENT_HELD", 422, "enrollment payment is held")
    if rec["status"] != "APPROVED":
        invalid_state("only an APPROVED enrollment can be paid")
    rec["paid_cents"] = rec["final_award_cents"]
    rec["status"] = "PAID"
    touch(rec)
    return success(ser_enrollment(rec))
