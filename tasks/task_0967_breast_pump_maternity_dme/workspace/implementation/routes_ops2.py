"""Prior authorizations, shipments, claims."""
from flask import Blueprint

from db import store, now_iso, today, next_seq
from errors import ApiError
from response import ok
from middleware import (
    authorize, check_ownership, body, get_or_404, req_str, opt_str, req_int,
    req_enum, parse_date, paginate, filter_query, scope_member_list, public,
)
from services import (
    create_entity, bump, adjudication_waterfall, compute_next_eligible,
    recompute_member_aggregates,
)
from routes_ops import (
    _check_fk, _check_polymorphic, PA_READ_ROLES, SHIPMENT_READ_ROLES,
    CLAIM_READ_ROLES, PA_DECISIONS, SHIPMENT_STATUSES, CLAIM_OUTCOMES,
)

bp = Blueprint("ops2", __name__, url_prefix="/dme")


# ----------------------------------------------------- prior authorizations ----

@bp.route("/prior-authorizations", methods=["POST"])
def create_prior_auth():
    uid, role = authorize(["InsuranceSpecialist"])
    b = body()
    _check_fk(b, "pump_order_id", store.pump_orders, "ERR_ORDER_NOT_FOUND")
    oid = req_str(b, "pump_order_id")
    order = store.pump_orders[oid]
    if order["fulfillment_status"] != "QUALIFIED" or not order["prior_auth_required"]:
        raise ApiError(
            "ERR_PRIOR_AUTH_NOT_REQUIRED",
            "Order is not QUALIFIED or does not require prior authorization",
            409,
        )
    item = store.catalog_items[order["pump_item_id"]]
    pa = create_entity(store.prior_auths, {
        "pump_order_id": order["id"],
        "member_id": order["member_id"],
        "policy_id": order["policy_id"],
        "requested_item_tier": item["insurance_tier"],
        "status": "SUBMITTED",
        "auth_number": None,
        "approved_until": None,
        "submission_count": 1,
        "submitted_by_user_id": uid,
        "decided_by_user_id": None,
        "payer_notes": None,
    })
    order["billing_status"] = "AUTH_PENDING"
    bump(order)
    return ok(public(pa), 201)


@bp.route("/prior-authorizations/<pid>", methods=["GET"])
def get_prior_auth(pid):
    uid, role = authorize(PA_READ_ROLES)
    pa = get_or_404(store.prior_auths, pid, "ERR_PRIOR_AUTH_NOT_FOUND")
    check_ownership(role, uid, pa["member_id"])
    return ok(public(pa))


@bp.route("/prior-authorizations", methods=["GET"])
def list_prior_auths():
    uid, role = authorize(PA_READ_ROLES)
    items = scope_member_list(store.prior_auths.values(), role, uid)
    items = filter_query(items, {
        "pump_order_id": "pump_order_id",
        "member_id": "member_id",
        "policy_id": "policy_id",
        "status": "status",
    })
    return paginate(items)


@bp.route("/prior-authorizations/<pid>/payer-decision", methods=["POST"])
def payer_decision(pid):
    uid, role = authorize(["PlatformAdmin"])
    pa = get_or_404(store.prior_auths, pid, "ERR_PRIOR_AUTH_NOT_FOUND")
    b = body()
    decision = req_enum(b, "decision", PA_DECISIONS)
    auth_number = opt_str(b, "auth_number")
    approved_until = None
    if b.get("approved_until") is not None:
        parse_date(b["approved_until"])
        approved_until = b["approved_until"]
    payer_notes = opt_str(b, "payer_notes")
    if pa["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE", "PA is not awaiting a payer decision", 409)
    if decision == "PENDED" and pa["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED PA may be pended", 409)
    if decision == "APPROVED" and approved_until is None:
        raise ApiError("ERR_VALIDATION", "approved_until is required for APPROVED", 400)
    order = store.pump_orders[pa["pump_order_id"]]
    if decision == "APPROVED":
        pa["status"] = "APPROVED"
        pa["auth_number"] = auth_number
        pa["approved_until"] = approved_until
        pa["decided_by_user_id"] = uid
        order["billing_status"] = "AUTH_APPROVED"
        bump(order)
    elif decision == "DENIED":
        pa["status"] = "DENIED" if pa["status"] == "SUBMITTED" else "DENIED_FINAL"
        pa["decided_by_user_id"] = uid
        order["billing_status"] = "DENIED"
        bump(order)
    else:  # PENDED
        pa["status"] = "PENDED"
        pa["payer_notes"] = payer_notes
    bump(pa)
    return ok(public(pa))


@bp.route("/prior-authorizations/<pid>/resubmit", methods=["POST"])
def resubmit_prior_auth(pid):
    authorize(["InsuranceSpecialist"])
    pa = get_or_404(store.prior_auths, pid, "ERR_PRIOR_AUTH_NOT_FOUND")
    if pa["status"] != "PENDED":
        raise ApiError("ERR_INVALID_STATE", "PA is not PENDED", 409)
    pa["status"] = "SUBMITTED"
    pa["submission_count"] += 1
    bump(pa)
    return ok(public(pa))


@bp.route("/prior-authorizations/<pid>/appeal", methods=["POST"])
def appeal_prior_auth(pid):
    authorize(["InsuranceSpecialist"])
    pa = get_or_404(store.prior_auths, pid, "ERR_PRIOR_AUTH_NOT_FOUND")
    if pa["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "PA is not DENIED", 409)
    pa["status"] = "APPEALED"
    order = store.pump_orders[pa["pump_order_id"]]
    order["billing_status"] = "AUTH_PENDING"
    bump(order)
    bump(pa)
    return ok(public(pa))


# --------------------------------------------------------------- shipments ----

def _shipment_member_id(s):
    if s["pump_order_id"] is not None:
        return store.pump_orders[s["pump_order_id"]]["member_id"]
    return store.resupply_orders[s["resupply_order_id"]]["member_id"]


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    authorize(["WarehouseOperator"])
    b = body()
    _check_fk(b, "pump_order_id", store.pump_orders, "ERR_ORDER_NOT_FOUND")
    _check_fk(b, "resupply_order_id", store.resupply_orders, "ERR_RESUPPLY_ORDER_NOT_FOUND")
    _check_polymorphic(b, "pump_order_id", "resupply_order_id")
    carrier = req_str(b, "carrier")
    tracking_number = req_str(b, "tracking_number")
    order = None
    rorder = None
    if b.get("pump_order_id") is not None:
        order = store.pump_orders[b["pump_order_id"]]
        if order["fulfillment_status"] != "QUALIFIED":
            raise ApiError("ERR_INVALID_STATE", "Pump order is not QUALIFIED", 409)
        if order["prior_auth_required"]:
            approved = [
                pa for pa in store.prior_auths.values()
                if pa["pump_order_id"] == order["id"] and pa["status"] == "APPROVED"
            ]
            valid = [pa for pa in approved if today() <= parse_date(pa["approved_until"])]
            if valid:
                pass
            elif approved:
                latest = max(approved, key=lambda p: p["_seq"])
                latest["status"] = "EXPIRED"
                bump(latest)
                order["billing_status"] = "AUTH_PENDING"
                bump(order)
                raise ApiError("ERR_PRIOR_AUTH_EXPIRED", "Prior authorization has expired", 422)
            else:
                raise ApiError("ERR_PRIOR_AUTH_REQUIRED", "An APPROVED prior authorization is required", 409)
    else:
        rorder = store.resupply_orders[b["resupply_order_id"]]
        if rorder["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Resupply order is not APPROVED", 409)
    s = create_entity(store.shipments, {
        "pump_order_id": b.get("pump_order_id"),
        "resupply_order_id": b.get("resupply_order_id"),
        "carrier": carrier,
        "tracking_number": tracking_number,
        "status": "LABEL_CREATED",
        "is_warranty_replacement": False,
        "shipped_at": now_iso(),
        "delivered_at": None,
    })
    if order is not None:
        order["fulfillment_status"] = "SHIPPED"
        bump(order)
    else:
        rorder["status"] = "SHIPPED"
        bump(rorder)
    return ok(public(s), 201)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    uid, role = authorize(SHIPMENT_READ_ROLES)
    s = get_or_404(store.shipments, sid, "ERR_SHIPMENT_NOT_FOUND")
    check_ownership(role, uid, _shipment_member_id(s))
    return ok(public(s))


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    uid, role = authorize(SHIPMENT_READ_ROLES)
    items = list(store.shipments.values())
    if role == "Member":
        items = [s for s in items if _shipment_member_id(s) == uid]
    items = filter_query(items, {
        "pump_order_id": "pump_order_id",
        "resupply_order_id": "resupply_order_id",
        "status": "status",
    })
    return paginate(items)


_ADVANCE_ALLOWED = {
    "LABEL_CREATED": {"IN_TRANSIT", "LOST"},
    "IN_TRANSIT": {"OUT_FOR_DELIVERY", "LOST"},
    "OUT_FOR_DELIVERY": {"DELIVERED", "RETURNED"},
}


@bp.route("/shipments/<sid>/advance", methods=["POST"])
def advance_shipment(sid):
    authorize(["WarehouseOperator"])
    s = get_or_404(store.shipments, sid, "ERR_SHIPMENT_NOT_FOUND")
    b = body()
    to_status = req_enum(b, "to_status", SHIPMENT_STATUSES)
    if to_status not in _ADVANCE_ALLOWED.get(s["status"], set()):
        raise ApiError("ERR_INVALID_STATE", "Invalid shipment status transition", 409)
    s["status"] = to_status
    if to_status == "DELIVERED":
        s["delivered_at"] = now_iso()
    bump(s)
    if to_status == "DELIVERED":
        if s["pump_order_id"] is not None and not s["is_warranty_replacement"]:
            order = store.pump_orders[s["pump_order_id"]]
            if order["fulfillment_status"] == "SHIPPED":
                order["fulfillment_status"] = "DELIVERED"
                order["delivery_date"] = today().isoformat()
                bump(order)
                policy = store.policies[order["policy_id"]]
                member = store.members[order["member_id"]]
                for item in store.catalog_items.values():
                    if item["item_type"] == "PART" and item["covered_under_resupply"]:
                        sched = create_entity(store.schedules, {
                            "member_id": order["member_id"],
                            "pump_order_id": order["id"],
                            "catalog_item_id": item["id"],
                            "frequency_days": policy["resupply_frequency_days"],
                            "schedule_mode": policy["schedule_mode"],
                            "anchor_date": order["delivery_date"],
                            "last_fulfilled_date": None,
                            "next_eligible_date": None,
                            "status": "ACTIVE",
                        })
                        sched["next_eligible_date"] = compute_next_eligible(sched)
                recompute_member_aggregates(member)
        elif s["resupply_order_id"] is not None:
            rorder = store.resupply_orders[s["resupply_order_id"]]
            if rorder["status"] == "SHIPPED":
                rorder["status"] = "DELIVERED"
                bump(rorder)
    return ok(public(s))


# ------------------------------------------------------------------ claims ----

@bp.route("/claims", methods=["POST"])
def create_claim():
    uid, role = authorize(["InsuranceSpecialist"])
    b = body()
    _check_fk(b, "pump_order_id", store.pump_orders, "ERR_ORDER_NOT_FOUND")
    _check_fk(b, "resupply_order_id", store.resupply_orders, "ERR_RESUPPLY_ORDER_NOT_FOUND")
    _check_polymorphic(b, "pump_order_id", "resupply_order_id")
    order = None
    if b.get("pump_order_id") is not None:
        order = store.pump_orders[b["pump_order_id"]]
        if order["fulfillment_status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE", "Pump order is not DELIVERED", 409)
        dup = [
            c for c in store.claims.values()
            if c["pump_order_id"] == order["id"] and c["status"] != "VOID"
        ]
        if dup:
            raise ApiError("ERR_DUPLICATE_CLAIM", "A claim already exists for this order", 409)
        if order["prior_auth_required"]:
            # CLAIM_FILED is reachable after a void, leaving the order claimable once more
            if order["billing_status"] not in ("AUTH_APPROVED", "CLAIM_FILED"):
                raise ApiError("ERR_INVALID_STATE", "Order billing does not permit claim filing", 409)
        elif order["billing_status"] not in ("UNBILLED", "CLAIM_FILED"):
            raise ApiError("ERR_INVALID_STATE", "Order billing does not permit claim filing", 409)
        member_id = order["member_id"]
        policy_id = order["policy_id"]
        provisional = order["provisional_allowed_cents"]
    else:
        rorder = store.resupply_orders[b["resupply_order_id"]]
        if rorder["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE", "Resupply order is not DELIVERED", 409)
        dup = [
            c for c in store.claims.values()
            if c["resupply_order_id"] == rorder["id"] and c["status"] != "VOID"
        ]
        if dup:
            raise ApiError("ERR_DUPLICATE_CLAIM", "A claim already exists for this order", 409)
        sched = store.schedules[rorder["schedule_id"]]
        src_order = store.pump_orders[sched["pump_order_id"]]
        member_id = rorder["member_id"]
        policy_id = src_order["policy_id"]
        provisional = rorder["total_cents"]
    claim = create_entity(store.claims, {
        "pump_order_id": b.get("pump_order_id"),
        "resupply_order_id": b.get("resupply_order_id"),
        "member_id": member_id,
        "policy_id": policy_id,
        "claim_number": "CLM-%06d" % next_seq(),
        "status": "SUBMITTED",
        "provisional_allowed_cents": provisional,
        "adjudicated_allowed_cents": None,
        "deductible_applied_cents": 0,
        "patient_responsibility_cents": None,
        "insurance_paid_cents": None,
        "submitted_by_user_id": uid,
        "remitted_by_user_id": None,
        "remittance_reference": None,
        "remitted_at": None,
    })
    if order is not None:
        order["billing_status"] = "CLAIM_FILED"
        bump(order)
    return ok(public(claim), 201)


@bp.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    uid, role = authorize(CLAIM_READ_ROLES)
    claim = get_or_404(store.claims, cid, "ERR_CLAIM_NOT_FOUND")
    check_ownership(role, uid, claim["member_id"])
    return ok(public(claim))


@bp.route("/claims", methods=["GET"])
def list_claims():
    uid, role = authorize(CLAIM_READ_ROLES)
    items = scope_member_list(store.claims.values(), role, uid)
    items = filter_query(items, {
        "member_id": "member_id",
        "policy_id": "policy_id",
        "pump_order_id": "pump_order_id",
        "resupply_order_id": "resupply_order_id",
        "status": "status",
    })
    return paginate(items)


def _source_pump_order(claim):
    if claim["pump_order_id"] is not None:
        return store.pump_orders[claim["pump_order_id"]]
    return None


@bp.route("/claims/<cid>/remit", methods=["POST"])
def remit_claim(cid):
    uid, role = authorize(["BillingSpecialist", "PlatformAdmin"])
    claim = get_or_404(store.claims, cid, "ERR_CLAIM_NOT_FOUND")
    b = body()
    outcome = req_enum(b, "outcome", CLAIM_OUTCOMES)
    allowed = req_int(b, "adjudicated_allowed_cents")
    paid = req_int(b, "insurance_paid_cents")
    ref = opt_str(b, "remittance_reference")
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE", "Claim is not remittable", 409)
    if uid == claim["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "Remittance poster must differ from the claim submitter",
            422,
        )
    policy = store.policies[claim["policy_id"]]
    member = store.members[claim["member_id"]]
    order = _source_pump_order(claim)
    if outcome == "APPROVED":
        ded_applied, patient = adjudication_waterfall(policy, member, allowed)
        if paid != allowed - patient:
            raise ApiError(
                "ERR_REMITTANCE_IMBALANCE",
                "insurance_paid_cents + patient_responsibility_cents must equal adjudicated_allowed_cents",
                422,
            )
        claim["adjudicated_allowed_cents"] = allowed
        claim["deductible_applied_cents"] = ded_applied
        claim["patient_responsibility_cents"] = patient
        claim["insurance_paid_cents"] = paid
        claim["remittance_reference"] = ref
        claim["status"] = "ADJUDICATED"
        claim["remitted_by_user_id"] = uid
        claim["remitted_at"] = now_iso()
        policy["deductible_met_cents"] += ded_applied
        bump(policy)
        member["oop_accumulated_cents"] += patient
        member["out_of_pocket_balance_cents"] += patient
        bump(member)
        if order is not None:
            order["billing_status"] = "ADJUDICATED"
            bump(order)
        bump(claim)
    else:  # DENIED
        claim["status"] = "DENIED"
        claim["remitted_by_user_id"] = uid
        claim["remitted_at"] = now_iso()
        if order is not None:
            order["billing_status"] = "DENIED"
            bump(order)
        bump(claim)
    return ok(public(claim))


@bp.route("/claims/<cid>/appeal", methods=["POST"])
def appeal_claim(cid):
    authorize(["InsuranceSpecialist"])
    claim = get_or_404(store.claims, cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not DENIED", 409)
    claim["status"] = "APPEALED"
    order = _source_pump_order(claim)
    if order is not None:
        order["billing_status"] = "CLAIM_FILED"
        bump(order)
    bump(claim)
    return ok(public(claim))


@bp.route("/claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    authorize(["BillingSpecialist"])
    claim = get_or_404(store.claims, cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "ADJUDICATED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not ADJUDICATED", 409)
    policy = store.policies[claim["policy_id"]]
    member = store.members[claim["member_id"]]
    policy["deductible_met_cents"] -= claim["deductible_applied_cents"]
    bump(policy)
    member["oop_accumulated_cents"] -= claim["patient_responsibility_cents"]
    member["out_of_pocket_balance_cents"] -= claim["patient_responsibility_cents"]
    bump(member)
    order = _source_pump_order(claim)
    if order is not None:
        order["billing_status"] = "CLAIM_FILED"
        bump(order)
    claim["status"] = "VOID"
    bump(claim)
    return ok(public(claim))
