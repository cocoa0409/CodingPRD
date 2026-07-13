"""Catalog, store network, customer book and the logical clock (PRD 3.1, 2.5)."""
from flask import Blueprint

import calc
import schema
import store
from auth import authenticate, require_owner
from envelope import array_response, object_response, paginate
from serializers import dump, dump_all

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------- policies
@bp.post("/insurance-policies")
def create_policy():
    authenticate("PlatformAdmin")
    b = schema.body()
    member_id = schema.string_field(b, "member_id")
    network = schema.enum_field(b, "network", ("IN_NETWORK", "OUT_OF_NETWORK"))
    frame_allowance = schema.int_field(b, "frame_allowance_cents", minimum=0)
    lens_copay = schema.int_field(b, "lens_copay_cents", minimum=0)
    annual_max = schema.int_field(b, "annual_max_cents", minimum=0)
    plan_year_start_raw, _ = schema.datetime_field(b, "plan_year_start")
    oon_pct = schema.number_field(
        b, "oon_reimburse_pct", required=False, default=0.75, minimum=0, maximum=1
    )
    fee_schedule = schema.fee_schedule_field(b, "oon_fee_schedule")

    rec = store.new_record(
        member_id=member_id,
        network=network,
        frame_allowance_cents=frame_allowance,
        frame_allowance_remaining_cents=frame_allowance,
        lens_copay_cents=lens_copay,
        annual_max_cents=annual_max,
        annual_reimbursed_cents=0,
        oon_reimburse_pct=oon_pct,
        oon_fee_schedule=fee_schedule,
        plan_year_start=plan_year_start_raw,
    )
    store.policies[rec["id"]] = rec
    return object_response(dump("policy", rec), 201)


@bp.get("/insurance-policies/<policy_id>")
def read_policy(policy_id):
    authenticate("PlatformAdmin", "BenefitsAdmin", "Customer")
    rec = schema.get_policy(policy_id)
    return object_response(dump("policy", rec))


# ------------------------------------------------------------------ stores
@bp.post("/stores")
def create_store():
    authenticate("PlatformAdmin")
    b = schema.body()
    name = schema.string_field(b, "name")
    exam_chairs = schema.int_field(b, "exam_chairs", minimum=1)
    status = schema.enum_field(b, "status", ("OPEN", "CLOSED"), required=False, default="OPEN")
    buffer_minutes = schema.int_field(b, "buffer_minutes", required=False, default=10, minimum=0)
    pickup_capacity = schema.int_field(
        b, "pickup_capacity_per_day", required=False, default=50, minimum=0
    )

    rec = store.new_record(
        name=name,
        status=status,
        exam_chairs=exam_chairs,
        buffer_minutes=buffer_minutes,
        pickup_capacity_per_day=pickup_capacity,
    )
    store.stores[rec["id"]] = rec
    return object_response(dump("store", rec), 201)


# ------------------------------------------------------------------ frames
@bp.post("/frames")
def create_frame():
    authenticate("PlatformAdmin")
    b = schema.body()
    sku = schema.string_field(b, "sku")
    name = schema.string_field(b, "name")
    brand = schema.string_field(b, "brand")
    price_cents = schema.int_field(b, "price_cents", minimum=0)
    tryon_stock = schema.int_field(b, "tryon_stock", minimum=0)
    min_pd = schema.number_field(b, "min_pd_mm")
    max_pd = schema.number_field(b, "max_pd_mm")
    status = schema.enum_field(
        b, "status", ("ACTIVE", "DISCONTINUED"), required=False, default="ACTIVE"
    )

    rec = store.new_record(
        sku=sku,
        name=name,
        brand=brand,
        price_cents=price_cents,
        status=status,
        tryon_stock=tryon_stock,
        tryon_available=tryon_stock,
        min_pd_mm=min_pd,
        max_pd_mm=max_pd,
    )
    store.frames[rec["id"]] = rec
    return object_response(dump("frame", rec), 201)


@bp.get("/frames/<frame_id>")
def read_frame(frame_id):
    authenticate(
        "PlatformAdmin",
        "StoreAssociate",
        "Customer",
        "OpticianVerifier",
        "LabTechnician",
        "BenefitsAdmin",
    )
    rec = schema.get_frame(frame_id)
    return object_response(dump("frame", rec))


@bp.get("/frames/<frame_id>/try-on-kit-items")
def list_frame_items(frame_id):
    from flask import request

    authenticate("PlatformAdmin", "StoreAssociate")
    schema.get_frame(frame_id)
    items = [i for i in store.ordered(store.kit_items) if i["frame_id"] == frame_id]
    outcome = request.args.get("outcome")
    if outcome:
        items = [i for i in items if i["outcome"] == outcome]
    window, meta = paginate(items)
    return array_response(dump_all("kit_item", window), meta)


# ------------------------------------------------------------- lens options
@bp.post("/lens-options")
def create_lens_option():
    authenticate("PlatformAdmin")
    b = schema.body()
    code = schema.string_field(b, "code")
    category = schema.enum_field(b, "category", ("MATERIAL", "COATING"))
    base_price = schema.int_field(b, "base_price_cents", minimum=0)
    material_index = schema.number_field(b, "material_index", required=False, default=None)
    incompatible_with = schema.string_list_field(
        b, "incompatible_with", required=False, default=[]
    )
    status = schema.enum_field(
        b, "status", ("ACTIVE", "RETIRED"), required=False, default="ACTIVE"
    )

    rec = store.new_record(
        code=code,
        category=category,
        base_price_cents=base_price,
        material_index=material_index,
        incompatible_with=incompatible_with,
        status=status,
    )
    store.lens_options[rec["id"]] = rec
    return object_response(dump("lens_option", rec), 201)


# --------------------------------------------------------------- customers
@bp.post("/customers")
def create_customer():
    authenticate("PlatformAdmin")
    b = schema.body()
    full_name = schema.string_field(b, "full_name")
    email = schema.string_field(b, "email")
    dob_raw, _ = schema.datetime_field(b, "dob")
    policy_id = schema.string_field(b, "insurance_policy_id", required=False, default=None)
    fsa_balance = schema.int_field(b, "fsa_balance_cents", required=False, default=0, minimum=0)

    if policy_id is not None:
        schema.get_policy(policy_id)

    rec = store.new_record(
        full_name=full_name,
        email=email,
        dob=dob_raw,
        insurance_policy_id=policy_id,
        fsa_balance_cents=fsa_balance,
        lifetime_kit_count=0,
        return_risk_score=0,
    )
    store.customers[rec["id"]] = rec
    return object_response(dump("customer", rec), 201)


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    actor = authenticate("PlatformAdmin", "StoreAssociate", "Customer")
    rec = schema.get_customer(customer_id)
    require_owner(actor, rec["id"])
    return object_response(dump("customer", rec))


@bp.get("/customers")
def list_customers():
    from flask import request

    authenticate("PlatformAdmin", "StoreAssociate")
    items = store.ordered(store.customers)
    policy_id = request.args.get("insurance_policy_id")
    if policy_id:
        items = [c for c in items if c["insurance_policy_id"] == policy_id]
    window, meta = paginate(items)
    return array_response(dump_all("customer", window), meta)


# ------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate("PlatformAdmin")
    b = schema.body()
    _, new_now = schema.datetime_field(b, "to_iso8601")
    store.set_clock(new_now)

    expired_ids = []
    for rx in store.ordered(store.prescriptions):
        if rx["status"] == "VERIFIED" and rx["_expires_at_dt"] <= new_now:
            rx["status"] = "EXPIRED"
            store.touch(rx)
            expired_ids.append(rx["id"])

    overdue_ids = []
    for kit in store.ordered(store.kits):
        if kit["status"] == "SHIPPED" and kit["_due_date_dt"] < new_now:
            kit["status"] = "OVERDUE"
            kit["was_overdue"] = True
            store.touch(kit)
            overdue_ids.append(kit["id"])
            customer = store.customers.get(kit["customer_id"])
            if customer is not None:
                calc.recompute_return_risk(customer)

    return object_response(
        {
            "current_utc": store.iso_ms(new_now),
            "expired_prescription_ids": expired_ids,
            "overdue_kit_ids": overdue_ids,
        }
    )
