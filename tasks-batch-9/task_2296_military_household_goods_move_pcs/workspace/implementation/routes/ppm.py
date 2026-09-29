"""Personally procured moves (PRD §3.9)."""

from flask import Blueprint

from db import base_record, by_seq, db, mark_fresh, touch
from errors import ApiError
from middleware import (
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
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
    opt_decimal,
    opt_enum,
    opt_str,
    req_list,
    validate_trip_tickets,
)

bp = Blueprint("ppm", __name__)


def _ordered_tickets(tickets):
    return sorted(tickets, key=lambda t: t["trip_number"])


def _moved_weight(tickets):
    """Ladder step 52 — every ticket certified, sourced and showing a positive net."""
    if not tickets:
        raise ApiError(
            "ERR_WEIGHT_TICKET_PAIR_INCOMPLETE", "At least one certified weight ticket is required."
        )
    total = 0
    for ticket in _ordered_tickets(tickets):
        if not ticket["certified"] or not str(ticket["ticket_source"]).strip():
            raise ApiError(
                "ERR_WEIGHT_TICKET_PAIR_INCOMPLETE",
                "Every weight ticket must be certified and name its source.",
            )
        net = ticket["full_lbs"] - ticket["empty_lbs"]
        if net <= 0:
            raise ApiError(
                "ERR_WEIGHT_TICKET_PAIR_INCOMPLETE",
                "Every weight ticket must show a full weight above its empty weight.",
            )
        total += net
    return total


@bp.post("/shipments/<shipment_id>/ppm-submissions")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def submit_ppm(shipment_id):
    body = get_body()
    raw_tickets = req_list(body, "trip_tickets")
    tickets = validate_trip_tickets(raw_tickets)
    documented = opt_decimal(body, "documented_expenses_usd", default=calc.ZERO, minimum=0)
    advance = opt_decimal(body, "advance_paid_usd", default=calc.ZERO, minimum=0)
    elected_basis = opt_enum(body, "elected_basis", calc.PPM_ELECTED_BASES, default="AUTO")

    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))

    if shipment["shipment_method"] != "PPM":
        raise ApiError(
            "ERR_PPM_METHOD_REQUIRED", "A PPM packet only applies to a PPM shipment."
        )
    moved_weight = _moved_weight(tickets)

    record = base_record()
    record.update(
        {
            "shipment_id": shipment["id"],
            "trip_tickets": tickets,
            "moved_weight_lbs": moved_weight,
            "allowable_weight_lbs": 0,
            "gcc_usd": calc.ZERO,
            "incentive_usd": calc.ZERO,
            "documented_expenses_usd": calc.money(documented),
            "advance_paid_usd": calc.money(advance),
            "elected_basis": elected_basis,
            "applied_basis": "UNDETERMINED",
            "reimbursement_usd": calc.ZERO,
            "net_payable_usd": calc.ZERO,
            "debt_owed_usd": calc.ZERO,
            "taxable_amount_usd": calc.ZERO,
            "approved_by_user_id": None,
            "status": "SUBMITTED",
        }
    )
    mark_fresh(record)
    db.ppm_submissions[record["id"]] = record
    return created(serialize(record))


@bp.get("/shipments/<shipment_id>/ppm-submissions")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def list_shipment_ppm(shipment_id):
    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))
    records = by_seq(
        [p for p in db.ppm_submissions.values() if p["shipment_id"] == shipment["id"]]
    )
    return list_response(records)


@bp.get("/ppm-submissions/<submission_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def read_ppm(submission_id):
    submission = ledger.get_ppm(submission_id)
    shipment = db.shipments[submission["shipment_id"]]
    require_ownership(ledger.member_of_shipment(shipment))
    return ok(serialize(submission))


@bp.post("/ppm-submissions/<submission_id>/approve")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def approve_ppm(submission_id):
    body = get_body()
    opt_str(body, "approval_note")

    submission = ledger.get_ppm(submission_id)

    if submission["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PPM_STATE", "Only a submitted packet may be approved.")
    shipment = db.shipments[submission["shipment_id"]]
    if shipment["movement_status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE",
            "The shipment must be delivered before the packet is approved.",
        )
    moved_weight = _moved_weight(submission["trip_tickets"])

    entitlement = db.entitlements.get(shipment["entitlement_id"])
    order = db.orders.get(shipment["order_id"])
    others = 0
    if entitlement is not None:
        for sibling in ledger.contributing_shipments(entitlement["id"]):
            if sibling["id"] == shipment["id"]:
                continue
            others += sibling["billable_weight_lbs"]
        room = max(0, entitlement["total_billable_cap_lbs"] - others)
    else:
        room = 0
    allowable = min(moved_weight, room)

    distance = order["distance_miles"] if order is not None else 0
    gcc = calc.gcc_amount(allowable, distance)
    incentive = calc.money(gcc * calc.PPM_INCENTIVE_PCT)
    documented = calc.money(submission["documented_expenses_usd"])
    expense_figure = documented if documented < gcc else gcc

    elected = submission["elected_basis"]
    if elected == "AUTO":
        applied = "INCENTIVE_BASIS" if incentive >= expense_figure else "ACTUAL_EXPENSE_BASIS"
    else:
        applied = elected
    reimbursement = incentive if applied == "INCENTIVE_BASIS" else expense_figure

    advance = calc.money(submission["advance_paid_usd"])
    net_payable = calc.money(reimbursement - advance)
    if net_payable < calc.ZERO:
        net_payable = calc.ZERO
    debt = calc.money(advance - reimbursement)
    if debt < calc.ZERO:
        debt = calc.ZERO
    if applied == "INCENTIVE_BASIS":
        taxable = calc.money(reimbursement - documented)
        if taxable < calc.ZERO:
            taxable = calc.ZERO
    else:
        taxable = calc.ZERO

    submission["moved_weight_lbs"] = moved_weight
    submission["allowable_weight_lbs"] = allowable
    submission["gcc_usd"] = gcc
    submission["incentive_usd"] = incentive
    submission["applied_basis"] = applied
    submission["reimbursement_usd"] = reimbursement
    submission["net_payable_usd"] = net_payable
    submission["debt_owed_usd"] = debt
    submission["taxable_amount_usd"] = taxable
    submission["approved_by_user_id"] = acting_user_id()
    submission["status"] = "APPROVED"
    touch(submission)

    shipment["billable_weight_lbs"] = allowable
    shipment["billable_basis"] = "ACTUAL"
    shipment["weight_recon_status"] = "ACTUAL_RECORDED"
    touch(shipment)
    if shipment["capacity_block_id"]:
        block = db.capacity_blocks.get(shipment["capacity_block_id"])
        if block is not None:
            ledger.recompute_capacity_block(block, force_touch=False)
    if entitlement is not None:
        ledger.recompute_entitlement_ledger(entitlement, cascade=True)
    return ok(serialize(submission))
