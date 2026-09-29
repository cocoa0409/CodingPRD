"""DistrictOrder endpoints (PRD 3.9)."""

import calc
import domain
import serializers as S
import validation as V
from db import apply_changes, base_record, db
from errors import fail
from middleware import authorize
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("orders", __name__)

READ_ROLES = ("PlatformAdmin", "SalesRep", "PricingManager", "StateAdoptionOfficer")


@bp.post("/district-orders")
def create_order():
    user_id, _role = authorize(("SalesRep",))
    payload = V.body()

    district_ref = V.get_str(payload, "district_ref", min_len=1, max_len=60)
    state_id = V.get_str(payload, "state_id")
    title_id = V.get_str(payload, "title_id")
    pricing_proposal_id = V.get_str(
        payload, "pricing_proposal_id", required=False, default=None
    )
    print_units = V.get_int(payload, "print_units", minimum=0)
    digital_seats = V.get_int(payload, "digital_seats", minimum=0)

    state = domain.find_state(state_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")
    title = domain.find_title(title_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")
    proposal = None
    if pricing_proposal_id is not None:
        proposal = domain.find_proposal(
            pricing_proposal_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND"
        )

    if title["status"] == "SUNSET":
        fail("ERR_TITLE_SUNSET", "A SUNSET edition can no longer be ordered.")
    if title["status"] not in ("ACTIVE", "REVISION_PLANNED"):
        fail("ERR_TITLE_NOT_RELEASED", "The edition has not been released for sale.")

    quoted, freight = calc.order_total_value(
        "quoted", print_units, digital_seats, title, state, proposal
    )

    record = base_record()
    record.update(
        {
            "district_ref": district_ref,
            "state_id": state_id,
            "title_id": title_id,
            "pricing_proposal_id": pricing_proposal_id,
            "print_units": print_units,
            "digital_seats": digital_seats,
            "status": "QUOTED",
            "quoted_tcv_cents": quoted,
            "contracted_tcv_cents": None,
            "freight_surcharge_cents": freight,
            "allocated_units": 0,
            "created_by_user_id": user_id,
            "confirmed_by_user_id": None,
        }
    )
    db.district_orders[record["id"]] = record
    return respond(S.serialize(record, S.DISTRICT_ORDER_FIELDS), 201)


@bp.get("/district-orders/<order_id>")
def get_order(order_id):
    authorize(READ_ROLES)
    record = domain.find_order(order_id)
    return respond(S.serialize(record, S.DISTRICT_ORDER_FIELDS))


@bp.get("/district-orders")
def list_orders():
    authorize(READ_ROLES)
    limit, offset = V.pagination()
    state_id = V.query_str("state_id")
    title_id = V.query_str("title_id")
    pricing_proposal_id = V.query_str("pricing_proposal_id")
    district_ref = V.query_str("district_ref")
    status = V.query_enum("status", V.ORDER_STATUSES)

    items = domain.ordered(list(db.district_orders.values()))
    if state_id is not None:
        items = [i for i in items if i["state_id"] == state_id]
    if title_id is not None:
        items = [i for i in items if i["title_id"] == title_id]
    if pricing_proposal_id is not None:
        items = [
            i for i in items if i["pricing_proposal_id"] == pricing_proposal_id
        ]
    if district_ref is not None:
        items = [i for i in items if i["district_ref"] == district_ref]
    if status is not None:
        items = [i for i in items if i["status"] == status]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.DISTRICT_ORDER_FIELDS), total, limit, offset
    )


@bp.post("/district-orders/<order_id>/confirm")
def confirm_order(order_id):
    user_id, _role = authorize(("SalesRep",))
    V.body()

    order = domain.find_order(order_id)
    title = db.titles[order["title_id"]]
    state = db.state_profiles[order["state_id"]]
    proposal = (
        db.pricing_proposals.get(order["pricing_proposal_id"])
        if order["pricing_proposal_id"] is not None
        else None
    )

    if title["status"] == "SUNSET":
        fail("ERR_TITLE_SUNSET", "A SUNSET edition can no longer be contracted.")
    if proposal is not None and proposal["status"] != "APPROVED":
        fail(
            "ERR_PRICING_PROPOSAL_STATE_INVALID",
            "The named price filing is not APPROVED.",
        )
    if order["status"] != "QUOTED":
        fail(
            "ERR_DISTRICT_ORDER_STATE_INVALID",
            "Only a QUOTED order may be confirmed.",
        )
    if user_id == order["created_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The confirming rep must differ from the rep who entered the order.",
        )

    if state["adoption_model"] == "ADOPTION_LIST":
        if proposal is None:
            fail(
                "ERR_PRICING_PROPOSAL_REQUIRED",
                "An adoption-list state requires an approved price filing.",
            )
        if state["state_code"] not in title["adopted_state_codes"]:
            fail(
                "ERR_TITLE_NOT_ON_ADOPTED_LIST",
                "The edition is not on this state's adopted list.",
            )

    if title["on_hand_units"] < order["print_units"]:
        fail(
            "ERR_INSUFFICIENT_PRINT_INVENTORY",
            "on_hand_units does not cover the order's print units.",
        )

    contracted, freight = calc.order_total_value(
        "contracted",
        order["print_units"],
        order["digital_seats"],
        title,
        state,
        proposal,
    )

    apply_changes(
        order,
        {
            "status": "CONFIRMED",
            "contracted_tcv_cents": contracted,
            "freight_surcharge_cents": freight,
            "allocated_units": order["print_units"],
            "confirmed_by_user_id": user_id,
        },
    )
    apply_changes(
        title,
        {
            "on_hand_units": title["on_hand_units"] - order["print_units"],
            "committed_units": title["committed_units"] + order["print_units"],
        },
    )
    if proposal is not None and proposal["status"] == "APPROVED":
        apply_changes(proposal, {"contract_locked": True})

    return respond(S.serialize(order, S.DISTRICT_ORDER_FIELDS))


@bp.post("/district-orders/<order_id>/fulfill")
def fulfill_order(order_id):
    authorize(("SalesRep",))
    V.body()

    order = domain.find_order(order_id)
    if order["status"] != "CONFIRMED":
        fail(
            "ERR_DISTRICT_ORDER_STATE_INVALID",
            "Only a CONFIRMED order may be fulfilled.",
        )

    title = db.titles[order["title_id"]]
    allocated = order["allocated_units"]
    apply_changes(order, {"status": "FULFILLED"})
    apply_changes(
        title,
        {
            "committed_units": title["committed_units"] - allocated,
            "fulfilled_units": title["fulfilled_units"] + allocated,
        },
    )
    return respond(S.serialize(order, S.DISTRICT_ORDER_FIELDS))


@bp.post("/district-orders/<order_id>/cancel")
def cancel_order(order_id):
    authorize(("SalesRep",))
    payload = V.body()
    V.get_str(payload, "reason", min_len=1, max_len=500)

    order = domain.find_order(order_id)
    if order["status"] not in ("QUOTED", "CONFIRMED"):
        fail(
            "ERR_DISTRICT_ORDER_STATE_INVALID",
            "Only a QUOTED or CONFIRMED order may be cancelled.",
        )

    was_confirmed = order["status"] == "CONFIRMED"
    allocated = order["allocated_units"]

    changes = {"status": "CANCELLED"}
    if was_confirmed:
        # From QUOTED there is nothing to unwind: allocated_units is already 0 and
        # the quoted figures stand as the district last saw them.
        changes["allocated_units"] = 0
        changes["contracted_tcv_cents"] = None
        changes["freight_surcharge_cents"] = 0
    apply_changes(order, changes)

    if was_confirmed:
        title = db.titles[order["title_id"]]
        apply_changes(
            title,
            {
                "committed_units": title["committed_units"] - allocated,
                "on_hand_units": title["on_hand_units"] + allocated,
            },
        )

    return respond(S.serialize(order, S.DISTRICT_ORDER_FIELDS))
