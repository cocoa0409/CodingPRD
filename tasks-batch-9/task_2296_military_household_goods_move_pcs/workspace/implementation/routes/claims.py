"""Loss and damage claims, adjudication, settlement and provider performance (PRD §3.10)."""

from datetime import timedelta

from flask import Blueprint

from db import base_record, by_seq, clock, db, mark_fresh, touch
from errors import ApiError
from middleware import (
    ROLE_CLAIMS_EXAMINER,
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
    ROLE_TSP_COORDINATOR,
    acting_user_id,
    endpoint,
    require_ownership,
)
from paging import list_response
from response import created, ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import (
    get_body,
    opt_bool,
    opt_str,
    req_decimal,
    req_dt,
    req_enum,
    req_str,
)

bp = Blueprint("claims", __name__)


def _shipment_of(claim):
    return db.shipments[claim["shipment_id"]]


@bp.post("/shipments/<shipment_id>/claims")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def open_claim(shipment_id):
    body = get_body()
    claim_type = req_enum(body, "claim_type", calc.CLAIM_TYPES)
    notice_date = req_dt(body, "notice_date")
    incident_description = req_str(body, "incident_description")

    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))

    if shipment["movement_status"] != "DELIVERED":
        raise ApiError(
            "ERR_SHIPMENT_NOT_DELIVERED", "A claim is only opened against a delivered shipment."
        )
    deadline = shipment["delivery_date"] + timedelta(days=calc.LOSS_NOTICE_WINDOW_DAYS)
    if notice_date > deadline:
        raise ApiError(
            "ERR_LOSS_NOTICE_WINDOW_EXPIRED", "The 180-day notice window has closed."
        )

    record = base_record()
    record.update(
        {
            "shipment_id": shipment["id"],
            "claim_type": claim_type,
            "notice_date": notice_date,
            "incident_description": incident_description,
            "filed_date": None,
            "filing_window_days": None,
            "settlement_basis": "UNDETERMINED",
            "claimed_total_usd": calc.ZERO,
            "settlement_total_usd": calc.ZERO,
            "item_count": 0,
            "info_request_count": 0,
            "reviewed_by_user_id": None,
            "settled_by_user_id": None,
            "denial_reason": None,
            "status": "DRAFT",
        }
    )
    mark_fresh(record)
    db.claims[record["id"]] = record
    return created(serialize(record))


@bp.get("/shipments/<shipment_id>/claims")
@endpoint(
    [
        ROLE_SERVICE_MEMBER,
        ROLE_MOVE_COUNSELOR,
        ROLE_TSP_COORDINATOR,
        ROLE_CLAIMS_EXAMINER,
        ROLE_PROGRAM_ADMIN,
    ]
)
def list_shipment_claims(shipment_id):
    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))
    records = by_seq([c for c in db.claims.values() if c["shipment_id"] == shipment["id"]])
    return list_response(records)


@bp.get("/claims/<claim_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_CLAIMS_EXAMINER, ROLE_PROGRAM_ADMIN])
def read_claim(claim_id):
    claim = ledger.get_claim(claim_id)
    require_ownership(ledger.member_of_claim(claim))
    return ok(serialize(claim))


# ------------------------------------------------------------------ claim items


@bp.post("/claims/<claim_id>/claim-items")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def add_claim_item(claim_id):
    body = get_body()
    item_description = req_str(body, "item_description")
    inventory_item_number = req_str(body, "inventory_item_number")
    category = req_enum(body, "category", calc.ITEM_CATEGORIES)
    replacement_cost = req_decimal(body, "replacement_cost_usd", minimum=0)
    age_years = req_decimal(body, "age_years", minimum=0, maximum=60)
    documented = opt_bool(body, "high_value_inventory_documented", default=False)
    if replacement_cost <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'replacement_cost_usd' must be greater than zero."
        )

    claim = ledger.get_claim(claim_id)
    require_ownership(ledger.member_of_claim(claim))

    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Items are only added while the claim is a draft.")

    record = base_record()
    record.update(
        {
            "claim_id": claim["id"],
            "item_description": item_description,
            "inventory_item_number": inventory_item_number,
            "category": category,
            "replacement_cost_usd": calc.money(replacement_cost),
            "age_years": age_years,
            "high_value_inventory_documented": documented,
            "depreciation_rate_pct_per_year": calc.CATEGORY_DEPRECIATION_PCT[category],
            "item_settlement_usd": calc.ZERO,
            "adjudication_note": None,
            "disposition": "PENDING",
        }
    )
    mark_fresh(record)
    db.claim_items[record["id"]] = record
    ledger.recompute_claim_totals(claim)
    return created(serialize(record))


@bp.get("/claims/<claim_id>/claim-items")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_CLAIMS_EXAMINER, ROLE_PROGRAM_ADMIN])
def list_claim_items(claim_id):
    claim = ledger.get_claim(claim_id)
    require_ownership(ledger.member_of_claim(claim))
    return list_response(ledger.claim_items_of(claim))


@bp.get("/claim-items/<item_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_CLAIMS_EXAMINER, ROLE_PROGRAM_ADMIN])
def read_claim_item(item_id):
    item = ledger.get_claim_item(item_id)
    claim = db.claims[item["claim_id"]]
    require_ownership(ledger.member_of_claim(claim))
    return ok(serialize(item))


@bp.post("/claim-items/<item_id>/disposition")
@endpoint([ROLE_CLAIMS_EXAMINER])
def set_item_disposition(item_id):
    body = get_body()
    disposition = req_enum(body, "disposition", ("ALLOWED", "DENIED"))
    adjudication_note = opt_str(body, "adjudication_note")

    item = ledger.get_claim_item(item_id)
    claim = db.claims[item["claim_id"]]

    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE", "Items are only adjudicated while the claim is under review."
        )

    item["disposition"] = disposition
    item["adjudication_note"] = adjudication_note
    touch(item)
    return ok(serialize(item))


# ------------------------------------------------------------------ lifecycle


@bp.post("/claims/<claim_id>/submit")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def submit_claim(claim_id):
    body = get_body()
    opt_str(body, "filing_note")

    claim = ledger.get_claim(claim_id)
    require_ownership(ledger.member_of_claim(claim))

    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a draft claim may be filed.")
    shipment = _shipment_of(claim)
    if shipment["movement_status"] != "DELIVERED":
        raise ApiError(
            "ERR_SHIPMENT_NOT_DELIVERED", "A claim is only filed against a delivered shipment."
        )
    notice_deadline = shipment["delivery_date"] + timedelta(days=calc.LOSS_NOTICE_WINDOW_DAYS)
    if claim["notice_date"] > notice_deadline:
        raise ApiError("ERR_LOSS_NOTICE_WINDOW_EXPIRED", "The 180-day notice window has closed.")

    filed_date = clock()
    filing_deadline = shipment["delivery_date"] + timedelta(days=calc.CLAIM_WINDOW_DAYS)
    if filed_date > filing_deadline:
        raise ApiError(
            "ERR_CLAIM_FILING_WINDOW_EXPIRED", "The two-year filing window has closed."
        )
    items = ledger.claim_items_of(claim)
    if not items:
        raise ApiError("ERR_CLAIM_ITEM_REQUIRED", "A claim must hold at least one item.")

    window_days = calc.whole_days(shipment["delivery_date"], filed_date)
    claim["filed_date"] = filed_date
    claim["filing_window_days"] = window_days
    claim["settlement_basis"] = (
        "FULL_REPLACEMENT_VALUE" if window_days <= calc.FRV_WINDOW_DAYS else "DEPRECIATED_VALUE"
    )
    claim["status"] = "SUBMITTED"
    touch(claim)
    ledger.recompute_claim_totals(claim)
    ledger.create_notification(shipment["id"], "CLAIM_ACK")
    return ok(serialize(claim))


@bp.post("/claims/<claim_id>/review")
@endpoint([ROLE_CLAIMS_EXAMINER])
def review_claim(claim_id):
    body = get_body()
    opt_str(body, "review_note")

    claim = ledger.get_claim(claim_id)

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a filed claim may be taken under review.")

    claim["reviewed_by_user_id"] = acting_user_id()
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok(serialize(claim))


@bp.post("/claims/<claim_id>/request-info")
@endpoint([ROLE_CLAIMS_EXAMINER])
def request_claim_info(claim_id):
    body = get_body()
    req_str(body, "info_request_note")

    claim = ledger.get_claim(claim_id)

    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE", "Information is only requested while the claim is under review."
        )
    if claim["info_request_count"] >= calc.CLAIM_INFO_REQUEST_LIMIT:
        raise ApiError(
            "ERR_CLAIM_INFO_REQUEST_LIMIT", "Three information requests have already been issued."
        )

    claim["info_request_count"] += 1
    claim["status"] = "INFO_REQUESTED"
    touch(claim)
    return ok(serialize(claim))


@bp.post("/claims/<claim_id>/provide-info")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def provide_claim_info(claim_id):
    body = get_body()
    req_str(body, "response_note")

    claim = ledger.get_claim(claim_id)
    require_ownership(ledger.member_of_claim(claim))

    if claim["status"] != "INFO_REQUESTED":
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE", "No information request is outstanding on this claim."
        )

    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok(serialize(claim))


@bp.post("/claims/<claim_id>/settle")
@endpoint([ROLE_CLAIMS_EXAMINER, ROLE_PROGRAM_ADMIN])
def settle_claim(claim_id):
    body = get_body()
    opt_str(body, "settlement_note")

    claim = ledger.get_claim(claim_id)

    if (
        claim["reviewed_by_user_id"] is not None
        and claim["reviewed_by_user_id"] == acting_user_id()
    ):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewing examiner may not settle the same claim.",
        )
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a claim under review may be settled.")
    items = ledger.claim_items_of(claim)
    for item in items:
        if item["disposition"] == "PENDING":
            raise ApiError("ERR_CLAIM_ITEM_PENDING", "Every item must be decided before settlement.")

    amounts = []
    for item in items:
        amount = calc.item_settlement(item, claim["settlement_basis"])
        item["item_settlement_usd"] = amount
        touch(item)
        amounts.append(amount)
    claim["settlement_total_usd"] = calc.settlement_total(amounts)
    claim["settled_by_user_id"] = acting_user_id()
    claim["status"] = "SETTLED"
    touch(claim)

    shipment = _shipment_of(claim)
    tsp = db.tsps.get(shipment["tsp_id"])
    if tsp is not None:
        ledger.recompute_tsp_performance(tsp)
    return ok(serialize(claim))


@bp.post("/claims/<claim_id>/deny")
@endpoint([ROLE_CLAIMS_EXAMINER])
def deny_claim(claim_id):
    body = get_body()
    denial_reason = req_str(body, "denial_reason")

    claim = ledger.get_claim(claim_id)

    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a claim under review may be denied.")

    claim["denial_reason"] = denial_reason
    claim["settlement_total_usd"] = calc.ZERO
    claim["status"] = "DENIED"
    touch(claim)
    return ok(serialize(claim))
