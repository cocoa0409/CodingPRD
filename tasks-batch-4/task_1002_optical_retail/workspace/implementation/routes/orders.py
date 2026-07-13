"""Order building, the money waterfall, confirmation and cancellation (PRD 3.5, 3.6)."""
from flask import Blueprint, request

import calc
import schema
import services
import store
from auth import authenticate, require_owner
from envelope import array_response, object_response, paginate
from errors import err
from serializers import dump, dump_all

bp = Blueprint("orders", __name__)

CANCELLABLE_FULFILLMENT = ("DRAFT", "CONFIRMED", "IN_LAB")
CANCELLABLE_LAB_STATUSES = ("QUEUED", "IN_PRODUCTION", "REMAKE_QUEUED", "QC_PASSED")


@bp.post("/orders")
def create_order():
    actor = authenticate("Customer")
    b = schema.body()
    customer_id = schema.string_field(b, "customer_id")
    prescription_id = schema.string_field(b, "prescription_id")
    frame_id = schema.string_field(b, "frame_id")
    material_option_id = schema.string_field(b, "material_option_id")
    delivery_method = schema.enum_field(b, "delivery_method", ("SHIP", "BOPIS"))
    coating_option_ids = schema.string_list_field(
        b, "coating_option_ids", required=False, default=[]
    )
    store_id = schema.string_field(b, "store_id", required=False, default=None)
    exam_appointment_id = schema.string_field(
        b, "exam_appointment_id", required=False, default=None
    )

    # Priority 5 -- body reference existence, in payload order.
    customer = schema.get_customer(customer_id)
    rx = schema.get_prescription(prescription_id)
    frame = schema.get_frame(frame_id)
    material = schema.get_lens_option(material_option_id, "MATERIAL")
    coatings = [schema.get_lens_option(cid, "COATING") for cid in coating_option_ids]
    if store_id is not None:
        schema.get_store(store_id)
    if exam_appointment_id is not None:
        schema.get_appointment(exam_appointment_id)

    # Priority 6 -- ownership.
    require_owner(actor, customer_id)

    # Priority 13 -- the Rx PD must lie within the frame's geometry (inclusive).
    pd = calc.dec(rx["pd_mm"])
    if pd < calc.dec(frame["min_pd_mm"]) or pd > calc.dec(frame["max_pd_mm"]):
        raise err("ERR_PD_OUT_OF_RANGE")

    # Priority 14 -- the blank must be optically strong enough.
    power = calc.rx_power(rx)
    tier = calc.required_index_tier(power)
    index = material.get("material_index")
    if index is None or calc.dec(index) < tier:
        raise err("ERR_LENS_INCOMPATIBLE_WITH_RX")

    # Priority 15 -- coating compatibility, checked symmetrically.
    for i, a in enumerate(coatings):
        for bopt in coatings[i + 1:]:
            if bopt["code"] in (a.get("incompatible_with") or []) or a["code"] in (
                bopt.get("incompatible_with") or []
            ):
                raise err("ERR_COATING_INCOMPATIBLE")

    # Priority 16 -- the frame must be orderable.
    if frame["status"] != "ACTIVE":
        raise err("ERR_FRAME_DISCONTINUED")

    # Priority 17 -- the prescription must belong to the ordering customer.
    if rx["customer_id"] != customer_id:
        raise err("ERR_PRESCRIPTION_OWNER_MISMATCH")

    # Priority 26 -- delivery method and store must agree.
    if delivery_method == "BOPIS" and store_id is None:
        raise err("ERR_BOPIS_STORE_REQUIRED")
    if delivery_method == "SHIP" and store_id is not None:
        raise err("ERR_BOPIS_STORE_REQUIRED")

    upcharge = calc.lens_upcharge(rx, material, coatings)
    policy = services.order_policy({"customer_id": customer_id})
    quote = calc.order_price_quote(frame, upcharge, customer, policy, fsa_amount_cents=0)

    rec = store.new_record(
        customer_id=customer_id,
        prescription_id=prescription_id,
        frame_id=frame_id,
        material_option_id=material_option_id,
        coating_option_ids=list(coating_option_ids),
        store_id=store_id,
        exam_appointment_id=exam_appointment_id,
        active_claim_id=None,
        delivery_method=delivery_method,
        fulfillment_status="DRAFT",
        payment_status="UNPAID",
        lens_upcharge_cents=upcharge,
        quote_variant="ESTIMATED",
        **quote
    )
    store.orders[rec["id"]] = rec
    return object_response(dump("order", rec), 201)


@bp.get("/orders/<order_id>")
def read_order(order_id):
    actor = authenticate("Customer", "StoreAssociate", "BenefitsAdmin", "PlatformAdmin")
    rec = schema.get_order(order_id)
    require_owner(actor, rec["customer_id"])
    return object_response(dump("order", rec))


@bp.get("/orders")
def list_orders():
    authenticate("StoreAssociate", "BenefitsAdmin", "PlatformAdmin")
    items = store.ordered(store.orders)
    for field in (
        "customer_id",
        "prescription_id",
        "frame_id",
        "store_id",
        "exam_appointment_id",
        "material_option_id",
        "active_claim_id",
        "fulfillment_status",
    ):
        value = request.args.get(field)
        if value:
            items = [o for o in items if o[field] == value]
    window, meta = paginate(items)
    return array_response(dump_all("order", window), meta)


@bp.post("/orders/<order_id>/confirm")
def confirm_order(order_id):
    actor = authenticate("Customer")
    b = schema.body()
    fsa_amount = schema.int_field(b, "fsa_amount_cents", required=False, default=0, minimum=0)

    order = schema.get_order(order_id)
    require_owner(actor, order["customer_id"])

    # Priority 9 -- from-state.
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")

    rx = store.prescriptions.get(order["prescription_id"])
    customer = store.customers.get(order["customer_id"])
    frame = store.frames.get(order["frame_id"])
    policy = services.order_policy(order)

    # Priority 10 -- the prescription must be VERIFIED.
    if rx is None or rx["status"] != "VERIFIED":
        raise err("ERR_PRESCRIPTION_NOT_VERIFIED")

    # Priority 12 -- a BOPIS order needs an OPEN destination store.
    if order["delivery_method"] == "BOPIS":
        shop = store.stores.get(order["store_id"])
        if shop is None or shop["status"] != "OPEN":
            raise err("ERR_STORE_CLOSED")

    # Priority 18 -- the prescription must not have lapsed.
    if not (rx["_expires_at_dt"] > store.clock_now()):
        raise err("ERR_PRESCRIPTION_EXPIRED")

    # Priority 28 -- the reservation may not over-draw the allowance.
    if policy is not None and order["benefit_frame_cents"] > policy["frame_allowance_remaining_cents"]:
        raise err("ERR_INSUFFICIENT_BENEFIT")

    # Priority 29 -- FSA sufficiency.
    if fsa_amount > customer["fsa_balance_cents"]:
        raise err("ERR_INSUFFICIENT_FSA")

    # --- CASCADE L1: re-quote (ESTIMATED) and authorize -------------------
    quote = calc.order_price_quote(frame, order["lens_upcharge_cents"], customer, policy, fsa_amount)
    order.update(quote)
    order["quote_variant"] = "ESTIMATED"
    order["fulfillment_status"] = "CONFIRMED"
    order["payment_status"] = "AUTHORIZED"
    store.touch(order)

    services.customer_fsa_move(customer, -order["fsa_applied_cents"])

    # --- CASCADE L2: the lab order ---------------------------------------
    lab = store.new_record(
        order_id=order["id"],
        shipped_to_store_id=None,
        active_warranty_claim_id=None,
        status="QUEUED",
        remake_count=0,
        qc_failure_reason=None,
        is_remake=False,
        delivered_at=None,
    )
    store.lab_orders[lab["id"]] = lab

    # --- CASCADE L3/L4: the reserving insurance claim and the policy debit --
    if customer.get("insurance_policy_id"):
        claim = store.new_record(
            order_id=order["id"],
            policy_id=customer["insurance_policy_id"],
            service_lines=[],
            status="SUBMITTED",
            reserved_frame_benefit_cents=order["benefit_frame_cents"],
            allowed_amount_cents=None,
            approved_amount_cents=0,
            reimbursed_amount_cents=0,
            denial_reason=None,
        )
        store.claims[claim["id"]] = claim
        order["active_claim_id"] = claim["id"]
        services.policy_move(store.policies.get(claim["policy_id"]), -claim["reserved_frame_benefit_cents"])

    return object_response(dump("order", order))


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    actor = authenticate("Customer", "PlatformAdmin")
    b = schema.body()
    schema.string_field(b, "reason", required=False, default=None)

    order = schema.get_order(order_id)
    require_owner(actor, order["customer_id"])

    if order["fulfillment_status"] not in CANCELLABLE_FULFILLMENT:
        raise err("ERR_INVALID_STATE")

    customer = store.customers.get(order["customer_id"])

    # --- CASCADE L1: the order itself; the payment dimension moves on its own axis.
    order["fulfillment_status"] = "CANCELLED"
    if order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "REFUNDED"
        if customer is not None:
            services.customer_fsa_move(customer, order["fsa_applied_cents"])
    store.touch(order)

    # --- CASCADE L2: the lab order.
    for lab in services.lab_orders_for(order["id"]):
        if lab["status"] in CANCELLABLE_LAB_STATUSES:
            lab["status"] = "CANCELLED"
            store.touch(lab)

    # --- CASCADE L3/L4: the active claim goes VOID and credits its policy back.
    claim_id = order["active_claim_id"]
    if claim_id:
        claim = store.claims.get(claim_id)
        if claim is not None and claim["status"] != "VOID":
            services.void_claim(claim)
        order["active_claim_id"] = None

    return object_response(dump("order", order))
