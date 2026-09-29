"""Logical clock, staff, consumers, plants, lines, products and production lots."""

from flask import Blueprint, request

import calc
import serializers as ser
import services as svc
from common import (
    ROLE_CARE_AGENT,
    ROLE_CARE_SUPERVISOR,
    ROLE_CONSUMER,
    ROLE_QUALITY_LEAD,
    ROLE_SYSTEM_ADMIN,
    authorize,
    authorize_clock,
    base_record,
    check_required,
    err,
    fmt_datetime,
    get_body,
    must_get,
    now,
    num2,
    pagination,
    paginated,
    q_bool,
    q_enum,
    q_str,
    sort_records,
    store,
    success,
    touch,
    unique_or_conflict,
    v_bool,
    v_datetime,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("reference", __name__)

STAFF_ROLES = ("CARE_AGENT", "CARE_SUPERVISOR", "QUALITY_LEAD", "REGULATORY_OFFICER")
TIERS = ("TIER_1", "TIER_2", "TIER_3")
REGIONS = ("MW", "NE", "SE", "WEST")
CATEGORIES = ("SNACK", "BEVERAGE", "DAIRY", "NON_FOOD")
POSTURES = ("NORMAL", "WATCH", "INVESTIGATION_HOLD")
RELEASE_STATES = ("RELEASED", "HOLD", "WITHDRAWN")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize_clock()
    body = get_body()
    check_required(body, ["current_utc"])
    current = v_datetime(body, "current_utc")
    previous = store.clock
    store.clock = current
    return success(
        {"current_utc": fmt_datetime(current), "previous_utc": fmt_datetime(previous)}
    )


# ---------------------------------------------------------------------------
# staff users
# ---------------------------------------------------------------------------
@bp.post("/staff-users")
def create_staff_user():
    authorize([ROLE_SYSTEM_ADMIN])
    body = get_body()
    check_required(body, ["staff_code", "full_name", "role"])
    staff_code = v_string(body, "staff_code", 1, 32)
    full_name = v_string(body, "full_name", 1)
    role = v_enum(body, "role", STAFF_ROLES)
    authority_tier = v_enum(body, "authority_tier", TIERS, "TIER_1")
    is_active = v_bool(body, "is_active", True)

    unique_or_conflict("staff_users", "staff_code", staff_code)

    rec = base_record()
    rec.update(
        {
            "staff_code": staff_code,
            "full_name": full_name,
            "role": role,
            "authority_tier": authority_tier,
            "is_active": is_active,
        }
    )
    store.staff_users[rec["id"]] = rec
    return success(ser.staff_user(rec), 201)


@bp.get("/staff-users")
def list_staff_users():
    authorize([ROLE_SYSTEM_ADMIN])
    limit, offset = pagination()
    role = q_str("role")
    tier = q_str("authority_tier")
    is_active = q_bool("is_active")
    items = []
    for rec in sort_records(list(store.staff_users.values())):
        if role is not None and rec["role"] != role:
            continue
        if tier is not None and rec["authority_tier"] != tier:
            continue
        if is_active is not None and rec["is_active"] != is_active:
            continue
        items.append(ser.staff_user(rec))
    return paginated(items, limit, offset)


@bp.get("/staff-users/<record_id>")
def get_staff_user(record_id):
    authorize([ROLE_SYSTEM_ADMIN])
    rec = must_get("staff_users", record_id)
    return success(ser.staff_user(rec))


# ---------------------------------------------------------------------------
# consumers
# ---------------------------------------------------------------------------
@bp.post("/consumers")
def create_consumer():
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    body = get_body()
    check_required(body, ["external_ref", "full_name"])
    external_ref = v_string(body, "external_ref", 1)
    full_name = v_string(body, "full_name", 1)
    email = v_string(body, "email", 0)
    phone = v_string(body, "phone", 0)
    postal_code = v_string(body, "postal_code", 0)
    is_vulnerable_flag = v_bool(body, "is_vulnerable_flag", False)

    unique_or_conflict("consumers", "external_ref", external_ref)

    rec = base_record()
    rec.update(
        {
            "external_ref": external_ref,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "postal_code": postal_code,
            "is_vulnerable_flag": is_vulnerable_flag,
            "goodwill_authorized_cents": 0,
            "goodwill_outstanding_cents": 0,
            "goodwill_paid_cents": 0,
            "goodwill_voided_cents": 0,
            "open_kit_count": 0,
            "complaint_count": 0,
        }
    )
    store.consumers[rec["id"]] = rec
    return success(ser.consumer(rec), 201)


@bp.get("/consumers")
def list_consumers():
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    limit, offset = pagination()
    external_ref = q_str("external_ref")
    vulnerable = q_bool("is_vulnerable_flag")
    items = []
    for rec in sort_records(list(store.consumers.values())):
        if external_ref is not None and rec["external_ref"] != external_ref:
            continue
        if vulnerable is not None and rec["is_vulnerable_flag"] != vulnerable:
            continue
        items.append(ser.consumer(rec))
    return paginated(items, limit, offset)


@bp.get("/consumers/<record_id>")
def get_consumer(record_id):
    actor = authorize(
        [ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD, ROLE_CONSUMER]
    )
    if actor.role == ROLE_CONSUMER and record_id != actor.user_id:
        raise err("ERR_UNAUTHORIZED", "a consumer may only read their own record")
    rec = must_get("consumers", record_id)
    return success(ser.consumer(rec))


@bp.patch("/consumers/<record_id>")
def update_consumer(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    rec = must_get("consumers", record_id)
    body = get_body()

    updates = {}
    for field in ("email", "phone", "postal_code"):
        if field in body:
            value = body[field]
            if value is None:
                updates[field] = None
            elif isinstance(value, str):
                updates[field] = value
            else:
                raise err("ERR_VALIDATION", "%s must be a string" % field)
    if "is_vulnerable_flag" in body and body["is_vulnerable_flag"] is not None:
        updates["is_vulnerable_flag"] = v_bool(body, "is_vulnerable_flag")

    rec.update(updates)
    touch(rec)
    return success(ser.consumer(rec))


@bp.get("/consumers/<record_id>/sentiment")
def consumer_sentiment(record_id):
    authorize([ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("consumers", record_id)
    view = "agent_view"
    if "view" in request.args:
        raw = request.args.get("view")
        if raw not in ("agent_view", "executive_view"):
            raise err("ERR_VALIDATION", "view must be agent_view or executive_view")
        view = raw
    figures = calc.consumer_sentiment(rec, view)
    return success(
        {
            "consumer_id": rec["id"],
            "view": view,
            "penalty_total": num2(figures["penalty_total"]),
            "credit_total": num2(figures["credit_total"]),
            "sentiment_index": num2(figures["sentiment_index"]),
            "complaint_count_in_window": figures["complaint_count_in_window"],
        }
    )


# ---------------------------------------------------------------------------
# plants
# ---------------------------------------------------------------------------
@bp.post("/plants")
def create_plant():
    authorize([ROLE_SYSTEM_ADMIN])
    body = get_body()
    check_required(body, ["plant_code", "name", "region"])
    plant_code = v_string(body, "plant_code", 1)
    name = v_string(body, "name", 1)
    region = v_enum(body, "region", REGIONS)

    unique_or_conflict("plants", "plant_code", plant_code)

    rec = base_record()
    rec.update(
        {
            "plant_code": plant_code,
            "name": name,
            "region": region,
            "oversight_posture": "NORMAL",
            "open_investigation_count": 0,
            "recall_initiated_count": 0,
        }
    )
    store.plants[rec["id"]] = rec
    return success(ser.plant(rec), 201)


@bp.get("/plants")
def list_plants():
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR])
    limit, offset = pagination()
    region = q_str("region")
    posture = q_str("oversight_posture")
    items = []
    for rec in sort_records(list(store.plants.values())):
        if region is not None and rec["region"] != region:
            continue
        if posture is not None and rec["oversight_posture"] != posture:
            continue
        items.append(ser.plant(rec))
    return paginated(items, limit, offset)


@bp.get("/plants/<record_id>")
def get_plant(record_id):
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR])
    rec = must_get("plants", record_id)
    return success(ser.plant(rec))


# ---------------------------------------------------------------------------
# production lines
# ---------------------------------------------------------------------------
@bp.post("/production-lines")
def create_production_line():
    authorize([ROLE_SYSTEM_ADMIN])
    body = get_body()
    if "plant_id" in body and body["plant_id"] is not None:
        must_get("plants", body["plant_id"])
    check_required(body, ["plant_id", "line_code", "nominal_units_per_hour"])
    plant_id = v_string(body, "plant_id", 1)
    line_code = v_string(body, "line_code", 1)
    throughput = v_int(body, "nominal_units_per_hour", 1)

    unique_or_conflict("production_lines", "line_code", line_code, ("plant_id", plant_id))

    rec = base_record()
    rec.update(
        {
            "plant_id": plant_id,
            "line_code": line_code,
            "nominal_units_per_hour": throughput,
            "lot_count": 0,
        }
    )
    store.production_lines[rec["id"]] = rec
    return success(ser.production_line(rec), 201)


@bp.get("/plants/<record_id>/production-lines")
def list_plant_lines(record_id):
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR])
    must_get("plants", record_id)
    limit, offset = pagination()
    items = [
        ser.production_line(rec)
        for rec in sort_records(list(store.production_lines.values()))
        if rec["plant_id"] == record_id
    ]
    return paginated(items, limit, offset)


@bp.get("/production-lines/<record_id>")
def get_production_line(record_id):
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR])
    rec = must_get("production_lines", record_id)
    return success(ser.production_line(rec))


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------
@bp.post("/products")
def create_product():
    authorize([ROLE_SYSTEM_ADMIN])
    body = get_body()
    check_required(
        body,
        ["sku", "name", "category", "is_regulated_food", "unit_retail_price_cents", "units_per_case"],
    )
    sku = v_string(body, "sku", 1)
    name = v_string(body, "name", 1)
    category = v_enum(body, "category", CATEGORIES)
    is_regulated_food = v_bool(body, "is_regulated_food")
    price = v_int(body, "unit_retail_price_cents", 1)
    units_per_case = v_int(body, "units_per_case", 1)

    unique_or_conflict("products", "sku", sku)

    rec = base_record()
    rec.update(
        {
            "sku": sku,
            "name": name,
            "category": category,
            "is_regulated_food": is_regulated_food,
            "unit_retail_price_cents": price,
            "units_per_case": units_per_case,
        }
    )
    store.products[rec["id"]] = rec
    return success(ser.product(rec), 201)


@bp.get("/products")
def list_products():
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR, ROLE_CARE_AGENT])
    limit, offset = pagination()
    sku = q_str("sku")
    category = q_str("category")
    regulated = q_bool("is_regulated_food")
    items = []
    for rec in sort_records(list(store.products.values())):
        if sku is not None and rec["sku"] != sku:
            continue
        if category is not None and rec["category"] != category:
            continue
        if regulated is not None and rec["is_regulated_food"] != regulated:
            continue
        items.append(ser.product(rec))
    return paginated(items, limit, offset)


@bp.get("/products/<record_id>")
def get_product(record_id):
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR, ROLE_CARE_AGENT])
    rec = must_get("products", record_id)
    return success(ser.product(rec))


# ---------------------------------------------------------------------------
# production lots
# ---------------------------------------------------------------------------
@bp.post("/production-lots")
def create_production_lot():
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD])
    body = get_body()
    if "product_id" in body and body["product_id"] is not None:
        must_get("products", body["product_id"])
    if "production_line_id" in body and body["production_line_id"] is not None:
        must_get("production_lines", body["production_line_id"])
    check_required(
        body, ["product_id", "production_line_id", "batch_code", "code_date", "units_produced"]
    )
    product_id = v_string(body, "product_id", 1)
    line_id = v_string(body, "production_line_id", 1)
    batch_code = v_string(body, "batch_code", 1)
    code_date = v_datetime(body, "code_date")
    units_produced = v_int(body, "units_produced", 0)

    line = store.production_lines[line_id]
    plant = store.plants.get(line["plant_id"])
    if plant is not None and plant["oversight_posture"] == "INVESTIGATION_HOLD":
        raise err(
            "ERR_PLANT_UNDER_INVESTIGATION_HOLD",
            "the owning plant is under an investigation hold",
        )

    rec = base_record()
    rec.update(
        {
            "product_id": product_id,
            "production_line_id": line_id,
            "batch_code": batch_code,
            "normalized_batch_code": calc.normalize_batch_code(batch_code),
            "code_date": code_date,
            "units_produced": units_produced,
            "release_status": "RELEASED",
            "linked_complaint_count": 0,
            "provisional_complaint_count": 0,
            "adjudicated_complaint_count": 0,
            "duplicate_complaint_count": 0,
            "goodwill_charged_cents": 0,
            "_hold_sources": set(),
        }
    )
    store.production_lots[rec["id"]] = rec
    ser.sync_line(line)
    return success(ser.production_lot(rec), 201)


@bp.get("/production-lots")
def list_production_lots():
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR, ROLE_CARE_AGENT])
    limit, offset = pagination()
    product_id = q_str("product_id")
    line_id = q_str("production_line_id")
    normalized = q_str("normalized_batch_code")
    release_status = q_str("release_status")
    items = []
    for rec in sort_records(list(store.production_lots.values())):
        if product_id is not None and rec["product_id"] != product_id:
            continue
        if line_id is not None and rec["production_line_id"] != line_id:
            continue
        if normalized is not None and rec["normalized_batch_code"] != normalized:
            continue
        if release_status is not None and rec["release_status"] != release_status:
            continue
        items.append(ser.production_lot(rec))
    return paginated(items, limit, offset)


@bp.get("/production-lots/<record_id>")
def get_production_lot(record_id):
    authorize([ROLE_SYSTEM_ADMIN, ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR, ROLE_CARE_AGENT])
    rec = must_get("production_lots", record_id)
    return success(ser.production_lot(rec))


@bp.get("/production-lots/<record_id>/complaint-rate")
def lot_complaint_rate(record_id):
    authorize([ROLE_QUALITY_LEAD, ROLE_CARE_SUPERVISOR])
    rec = must_get("production_lots", record_id)
    variant = "provisional"
    if "variant" in request.args:
        raw = request.args.get("variant")
        if raw not in ("provisional", "adjudicated"):
            raise err("ERR_VALIDATION", "variant must be provisional or adjudicated")
        variant = raw
    numerator, units, rate, undefined = calc.lot_complaint_rate(rec, variant)
    return success(
        {
            "production_lot_id": rec["id"],
            "variant": variant,
            "numerator": numerator,
            "units_produced": units,
            "rate_ppm": num2(rate),
            "rate_undefined": undefined,
        }
    )


@bp.post("/production-lots/<record_id>/hold")
def hold_production_lot(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("production_lots", record_id)
    get_body()
    if rec["release_status"] != "RELEASED":
        raise err("ERR_LOT_STATE_INVALID", "only a RELEASED lot may be placed on hold")
    svc.hold_lot(rec, "MANUAL")
    return success(ser.production_lot(rec))


@bp.post("/production-lots/<record_id>/release")
def release_production_lot(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("production_lots", record_id)
    get_body()
    if rec["release_status"] != "HOLD":
        raise err("ERR_LOT_STATE_INVALID", "only a lot on HOLD may be released")
    for signal in svc.signals_covering_lot(rec):
        if signal["status"] in ("INVESTIGATION_OPEN", "RECALL_EVALUATION"):
            raise err(
                "ERR_SIGNAL_INVESTIGATION_ACTIVE",
                "a trend signal covering this lot is still under investigation",
            )
    svc.release_lot(rec, clear_all=True)
    return success(ser.production_lot(rec))


@bp.post("/production-lots/<record_id>/withdraw")
def withdraw_production_lot(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("production_lots", record_id)
    get_body()
    if rec["release_status"] != "HOLD":
        raise err("ERR_LOT_STATE_INVALID", "only a lot on HOLD may be withdrawn")
    rec["release_status"] = "WITHDRAWN"
    touch(rec)
    return success(ser.production_lot(rec))
