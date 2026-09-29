"""Disposition orders and owner claims."""

from flask import Blueprint

import calc
import domain
import serializers as ser
import validate as v
from auth import authorize, require_self
from envelope import created, listed, ok, paginate
from errors import ApiError
from store import db, mark, new_entity, now, sort_rows

bp = Blueprint("disposition", __name__)

PRM = ["PropertyRoomManager"]
ORDER_TYPES = ("RETURN_TO_OWNER", "AUCTION", "DESTRUCTION", "CONVERSION")
NOTICE_METHODS = ("CERTIFIED_MAIL", "PUBLICATION", "IN_PERSON")
ORDER_READERS = [
    "PropertyRoomManager",
    "EvidenceTechnician",
    "CourtClerk",
    "InternalAuditor",
]
CLAIM_READERS = ["PropertyRoomManager", "EvidenceTechnician", "InternalAuditor"]
ELIGIBLE_STATES = ("DISPOSAL_ELIGIBLE", "UNCLAIMED_ELIGIBLE")


# --------------------------------------------------------------------------
# disposition orders
# --------------------------------------------------------------------------

@bp.post("/disposition-orders")
def create_order():
    principal = authorize(["EvidenceTechnician", "PropertyRoomManager"])
    data = v.body()
    require_self(principal, data, "requested_by_custodian_id")

    item_id = v.req_str(data, "evidence_item_id")
    order_type = v.req_enum(data, "type", ORDER_TYPES)
    requester_id = v.req_str(data, "requested_by_custodian_id")
    if order_type == "RETURN_TO_OWNER":
        claim_id = v.req_str(data, "owner_claim_id")
    else:
        v.must_be_absent(data, "owner_claim_id", "unless type is RETURN_TO_OWNER")
        claim_id = None
    if order_type == "AUCTION":
        reserve_price = v.req_int(data, "reserve_price_cents", minimum=0)
    else:
        v.must_be_absent(data, "reserve_price_cents", "unless type is AUCTION")
        reserve_price = None

    item = domain.find(db.items, item_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")
    requester = domain.find(db.custodians, requester_id, "ERR_CUSTODIAN_NOT_FOUND")
    claim = None
    if claim_id is not None:
        claim = domain.find(db.claims, claim_id, "ERR_OWNER_CLAIM_NOT_FOUND")

    case = domain.case_of_item(item)
    statute = domain.statute_of_case(case)
    room = domain.room_of_case(case)
    domain.gate_locked_down(room)

    if item["disposition_state"] in ("ORDER_PENDING", "DISPOSED"):
        raise ApiError("ERR_ITEM_DISPOSITION_STATE_INVALID")

    domain.gate_active(requester)

    if order_type == "DESTRUCTION" and statute["preservation_class"] in (
        "BIOLOGICAL_INDEFINITE",
        "HOMICIDE_PERMANENT",
    ):
        raise ApiError("ERR_PRESERVATION_CLASS_FORBIDS_DESTRUCTION")

    found_property_exemption = (
        item["is_found_property"] is True and item["disposition_state"] == "UNCLAIMED_ELIGIBLE"
    )
    if case["status"] not in ("ADJUDICATED", "CLOSED") and not found_property_exemption:
        raise ApiError("ERR_CASE_NOT_DISPOSABLE")

    if item["disposition_state"] not in ELIGIBLE_STATES:
        raise ApiError("ERR_RETENTION_NOT_MATURED")

    order = new_entity(
        "DispositionOrder",
        {
            "evidence_item_id": item["id"],
            "type": order_type,
            "requested_by_custodian_id": requester["id"],
            "owner_claim_id": claim["id"] if claim else None,
            "reserve_price_cents": reserve_price,
            "status": "PENDING_COURT_AUTH",
            "auto_authorized": False,
            "court_order_number": None,
            "estimated_net_proceeds_cents": calc.estimated_net_proceeds(
                order_type, item["appraised_value_cents"]
            ),
            "gross_sale_cents": None,
            "commission_cents": None,
            "storage_recovery_cents": None,
            "settled_net_proceeds_cents": None,
            "settlement_status": "NONE",
            "executed_by_custodian_id": None,
            "witness_custodian_id": None,
            "authorized_at": None,
            "executed_at": None,
            "settlement_deadline_at": None,
            "settled_at": None,
            "payee_reference": None,
        },
    )
    db.orders[order["id"]] = order

    item["disposition_state"] = "ORDER_PENDING"
    mark(item)

    if calc.auto_authorized(order_type, statute, item):
        order["status"] = "AUTHORIZED"
        order["auto_authorized"] = True
        order["authorized_at"] = now()

    domain.refresh_room(room)
    return created(ser.order(order))


@bp.get("/disposition-orders/<order_id>")
def get_order(order_id):
    authorize(ORDER_READERS)
    order = domain.find(db.orders, order_id, "ERR_DISPOSITION_ORDER_NOT_FOUND")
    return ok(ser.order(order))


@bp.get("/disposition-orders")
def list_orders():
    authorize(ORDER_READERS)
    rows = v.filter_rows(
        sort_rows(db.orders.values()),
        {
            "evidence_item_id": ("evidence_item_id", "str"),
            "owner_claim_id": ("owner_claim_id", "str"),
            "requested_by_custodian_id": ("requested_by_custodian_id", "str"),
            "executed_by_custodian_id": ("executed_by_custodian_id", "str"),
            "witness_custodian_id": ("witness_custodian_id", "str"),
            "status": ("status", "str"),
            "type": ("type", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.order(r) for r in page], limit, offset, total)


@bp.post("/disposition-orders/<order_id>/authorize")
def authorize_order(order_id):
    authorize(["CourtClerk"])
    order = domain.find(db.orders, order_id, "ERR_DISPOSITION_ORDER_NOT_FOUND")
    data = v.body()
    court_order_number = v.req_str(data, "court_order_number", min_len=1)

    item = db.items.get(order["evidence_item_id"])
    domain.gate_locked_down(domain.room_of_item(item))

    if order["status"] != "PENDING_COURT_AUTH":
        raise ApiError("ERR_ORDER_STATE_INVALID")

    order["status"] = "AUTHORIZED"
    order["court_order_number"] = court_order_number
    order["authorized_at"] = now()
    mark(order)
    return ok(ser.order(order))


@bp.post("/disposition-orders/<order_id>/reject")
def reject_order(order_id):
    authorize(["CourtClerk"])
    order = domain.find(db.orders, order_id, "ERR_DISPOSITION_ORDER_NOT_FOUND")
    data = v.body()
    v.req_str(data, "reason", min_len=1)

    item = db.items.get(order["evidence_item_id"])
    room = domain.room_of_item(item)
    domain.gate_locked_down(room)

    if order["status"] != "PENDING_COURT_AUTH":
        raise ApiError("ERR_ORDER_STATE_INVALID")

    order["status"] = "REJECTED"
    mark(order)

    if item["disposition_state"] == "ORDER_PENDING":
        item["disposition_state"] = "RETAINED"
        mark(item)
    domain.refresh_room(room)
    return ok(ser.order(order))


@bp.post("/disposition-orders/<order_id>/execute")
def execute_order(order_id):
    principal = authorize(PRM)
    order = domain.find(db.orders, order_id, "ERR_DISPOSITION_ORDER_NOT_FOUND")
    data = v.body()
    executor_id = v.req_str(data, "executed_by_custodian_id")
    witness_id = v.req_str(data, "witness_custodian_id")

    executor = domain.find(db.custodians, executor_id, "ERR_CUSTODIAN_NOT_FOUND")
    witness = domain.find(db.custodians, witness_id, "ERR_CUSTODIAN_NOT_FOUND")

    item = db.items.get(order["evidence_item_id"])
    case = domain.case_of_item(item)
    room = domain.room_of_case(case)
    location = domain.location_of_item(item)
    claim = db.claims.get(order["owner_claim_id"]) if order["owner_claim_id"] else None

    domain.gate_locked_down(room)
    domain.gate_restricted(room)

    if order["status"] != "AUTHORIZED":
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if item["custody_state"] != "STORED":
        raise ApiError("ERR_ITEM_CUSTODY_STATE_INVALID")

    domain.gate_active(executor, witness)
    domain.gate_certified(executor, witness)

    if executor["id"] == order["requested_by_custodian_id"] or witness["id"] == executor["id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if order["type"] == "RETURN_TO_OWNER" and (claim is None or claim["status"] != "VERIFIED"):
        raise ApiError("ERR_CLAIM_NOT_VERIFIED")

    instant = now()
    order["status"] = "EXECUTED"
    order["executed_by_custodian_id"] = executor["id"]
    order["witness_custodian_id"] = witness["id"]
    order["executed_at"] = instant
    if order["type"] == "AUCTION":
        order["settlement_deadline_at"] = calc.add_days(instant, calc.SETTLEMENT_WINDOW_DAYS)
    mark(order)

    item["custody_state"] = "PURGED"
    item["disposition_state"] = "DISPOSED"
    item["current_holder_id"] = None
    mark(item)
    domain.refresh_location(location)

    if order["type"] == "RETURN_TO_OWNER" and claim is not None:
        claim["status"] = "RELEASED"
        mark(claim)

    domain.append_chain_event(
        item,
        "DISPOSITION_EXECUTED",
        principal.role,
        principal.custodian_id,
        None,
        "Disposition of type %s executed." % order["type"],
    )

    if order["type"] != "AUCTION":
        order["status"] = "SETTLED"
        order["settled_net_proceeds_cents"] = 0
        order["settlement_status"] = "NONE"
        order["settled_at"] = instant

    domain.refresh_case(case)
    mark(case)
    domain.refresh_room(room)
    return ok(ser.order(order))


@bp.post("/disposition-orders/<order_id>/settle")
def settle_order(order_id):
    authorize(PRM)
    order = domain.find(db.orders, order_id, "ERR_DISPOSITION_ORDER_NOT_FOUND")
    data = v.body()
    gross = v.req_int(data, "gross_sale_cents", minimum=0)

    item = db.items.get(order["evidence_item_id"])
    room = domain.room_of_item(item)
    domain.gate_locked_down(room)

    if order["type"] != "AUCTION" or order["status"] != "EXECUTED":
        raise ApiError("ERR_ORDER_STATE_INVALID")

    if gross < (order["reserve_price_cents"] or 0):
        raise ApiError("ERR_SALE_BELOW_RESERVE")

    if order["settlement_deadline_at"] is not None and now() > order["settlement_deadline_at"]:
        raise ApiError("ERR_SETTLEMENT_WINDOW_CLOSED")

    commission, recovery, net = calc.settled_proceeds(
        gross, item["intake_at"], order["executed_at"], item["required_storage_category"]
    )
    order["status"] = "SETTLED"
    order["gross_sale_cents"] = gross
    order["commission_cents"] = commission
    order["storage_recovery_cents"] = recovery
    order["settled_net_proceeds_cents"] = net
    order["settlement_status"] = "HELD"
    order["settled_at"] = now()
    mark(order)

    domain.refresh_room(room)
    return ok(ser.order(order))


@bp.post("/disposition-orders/<order_id>/disburse")
def disburse_order(order_id):
    authorize(PRM)
    order = domain.find(db.orders, order_id, "ERR_DISPOSITION_ORDER_NOT_FOUND")
    data = v.body()
    payee_reference = v.req_str(data, "payee_reference", min_len=1)

    item = db.items.get(order["evidence_item_id"])
    room = domain.room_of_item(item)
    domain.gate_locked_down(room)

    if order["status"] != "SETTLED":
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if order["settlement_status"] != "HELD":
        raise ApiError("ERR_NO_PROCEEDS_HELD")

    order["status"] = "DISBURSED"
    order["settlement_status"] = "DISBURSED"
    order["payee_reference"] = payee_reference
    mark(order)

    domain.refresh_room(room)
    return ok(ser.order(order))


# --------------------------------------------------------------------------
# owner claims
# --------------------------------------------------------------------------

@bp.post("/owner-claims")
def create_claim():
    principal = authorize(["EvidenceTechnician"])
    data = v.body()
    item_id = v.req_str(data, "evidence_item_id")
    claimant_name = v.req_str(data, "claimant_name", min_len=1)
    claimant_contact = v.req_str(data, "claimant_contact", min_len=1)
    notice_method = v.req_enum(data, "notice_method", NOTICE_METHODS)

    item = domain.find(db.items, item_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")
    domain.gate_locked_down(domain.room_of_item(item))

    notified_at = now()
    claim = new_entity(
        "OwnerClaim",
        {
            "evidence_item_id": item["id"],
            "claimant_name": claimant_name,
            "claimant_contact": claimant_contact,
            "notice_method": notice_method,
            "notified_at": notified_at,
            "claim_deadline_at": calc.owner_claim_deadline(
                notified_at, item["is_found_property"], notice_method
            ),
            "status": "NOTICE_SENT",
            "proof_document_ref": None,
            "verified_at": None,
        },
    )
    db.claims[claim["id"]] = claim
    domain.append_chain_event(
        item,
        "NOTICE_SENT",
        principal.role,
        principal.custodian_id,
        None,
        "Owner notice issued to %s by %s." % (claimant_name, notice_method),
    )
    return created(ser.claim(claim))


@bp.get("/owner-claims/<claim_id>")
def get_claim(claim_id):
    authorize(CLAIM_READERS)
    claim = domain.find(db.claims, claim_id, "ERR_OWNER_CLAIM_NOT_FOUND")
    return ok(ser.claim(claim))


@bp.get("/owner-claims")
def list_claims():
    authorize(CLAIM_READERS)
    rows = v.filter_rows(
        sort_rows(db.claims.values()),
        {
            "evidence_item_id": ("evidence_item_id", "str"),
            "status": ("status", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.claim(r) for r in page], limit, offset, total)


@bp.post("/owner-claims/<claim_id>/file")
def file_claim(claim_id):
    authorize(["EvidenceTechnician"])
    claim = domain.find(db.claims, claim_id, "ERR_OWNER_CLAIM_NOT_FOUND")
    data = v.body()
    proof = v.req_str(data, "proof_document_ref", min_len=1)

    item = db.items.get(claim["evidence_item_id"])
    domain.gate_locked_down(domain.room_of_item(item))

    if claim["status"] != "NOTICE_SENT" or now() > claim["claim_deadline_at"]:
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    claim["status"] = "CLAIM_FILED"
    claim["proof_document_ref"] = proof
    mark(claim)
    return ok(ser.claim(claim))


@bp.post("/owner-claims/<claim_id>/verify")
def verify_claim(claim_id):
    authorize(PRM)
    claim = domain.find(db.claims, claim_id, "ERR_OWNER_CLAIM_NOT_FOUND")

    item = db.items.get(claim["evidence_item_id"])
    domain.gate_locked_down(domain.room_of_item(item))

    if claim["status"] != "CLAIM_FILED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    claim["status"] = "VERIFIED"
    claim["verified_at"] = now()
    mark(claim)
    return ok(ser.claim(claim))
