"""Routes: APA expenses and damage claims (PRD §3.7)."""

from flask import Blueprint, g, request

from httpkit import (api_err, as_enum, as_pos_int, as_str, body_json,
                     get_or_404, req_field, require_roles, respond_object,
                     respond_paginated, sort_created)
from serializers import ser_expense
from services import escrow_of, expenses_of
from store import db, mutate, new_record

bp = Blueprint("expenses", __name__)

EXPENSE_BUCKETS = ("APA", "DAMAGE_CLAIM")
EXPENSE_ACTIVE_AGREEMENT_STATES = ("IN_PREP", "UNDERWAY")


def _agreement_of(expense):
    return db["charter_agreements"][expense["charter_agreement_id"]]


def _client_side_or_403(agr):
    if g.role == "Client":
        if g.user_id != agr["client_id"]:
            raise api_err("ERR_FORBIDDEN", "Caller is not the agreement's client")
    elif g.role == "RetailBroker":
        if g.user_id != agr["retail_broker_id"]:
            raise api_err(
                "ERR_FORBIDDEN", "Caller is not the agreement's retail broker"
            )
    else:
        raise api_err("ERR_FORBIDDEN", "Role not authorized for this endpoint")


def _cap_check(agr, expense):
    """Bucket caps: approving must not push the APPROVED total above the held
    bucket (ERR_ESCROW_INSUFFICIENT for APA, ERR_DEPOSIT_CLAIM_EXCEEDS_HELD for
    DAMAGE_CLAIM)."""
    esc = escrow_of(agr["id"])
    expenses = expenses_of(agr["id"])
    if expense["bucket"] == "APA":
        approved = sum(
            e["amount_cents"] for e in expenses
            if e["bucket"] == "APA" and e["status"] == "APPROVED"
            and e["id"] != expense["id"]
        )
        held = esc["held_apa_cents"] if esc is not None else 0
        if approved + expense["amount_cents"] > held:
            raise api_err(
                "ERR_ESCROW_INSUFFICIENT",
                "Approved APA total would exceed held APA",
            )
    else:
        approved = sum(
            e["amount_cents"] for e in expenses
            if e["bucket"] == "DAMAGE_CLAIM" and e["status"] == "APPROVED"
            and e["id"] != expense["id"]
        )
        held = esc["held_deposit_cents"] if esc is not None else 0
        if approved + expense["amount_cents"] > held:
            raise api_err(
                "ERR_DEPOSIT_CLAIM_EXCEEDS_HELD",
                "Approved damage claims would exceed held deposit",
            )


@bp.route("/charter-agreements/<aid>/expenses", methods=["POST"])
def create_expense(aid):
    require_roles("Operator")
    agr = get_or_404("charter_agreements", aid, "CharterAgreement")
    if agr["operator_id"] != g.user_id:
        raise api_err("ERR_FORBIDDEN", "Caller does not own the yacht")
    if agr["status"] not in EXPENSE_ACTIVE_AGREEMENT_STATES:
        raise api_err(
            "ERR_INVALID_STATE", "Expenses require agreement IN_PREP or UNDERWAY"
        )
    body = body_json()
    bucket = as_enum(req_field(body, "bucket"), EXPENSE_BUCKETS, "bucket")
    description = as_str(req_field(body, "description"), "description")
    amount = as_pos_int(req_field(body, "amount_cents"), "amount_cents")
    e = new_record()
    e.update({
        "charter_agreement_id": agr["id"],
        "bucket": bucket,
        "description": description,
        "amount_cents": amount,
        "status": "PENDING",
    })
    db["expenses"][e["id"]] = e
    return respond_object(ser_expense(e), 201)


@bp.route("/charter-agreements/<aid>/expenses", methods=["GET"])
def list_expenses(aid):
    agr = get_or_404("charter_agreements", aid, "CharterAgreement")
    items = expenses_of(agr["id"])
    for f in ("bucket", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e[f] == v]
    return respond_paginated([ser_expense(e) for e in sort_created(items)])


@bp.route("/expenses/<eid>/review", methods=["POST"])
def review_expense(eid):
    require_roles("Client", "RetailBroker")
    e = get_or_404("expenses", eid, "ExpenseEntry")
    agr = _agreement_of(e)
    _client_side_or_403(agr)
    if e["status"] != "PENDING":
        raise api_err("ERR_INVALID_STATE", "ExpenseEntry is not PENDING")
    body = body_json()
    outcome = as_enum(req_field(body, "outcome"), ("APPROVED", "REJECTED"), "outcome")
    if outcome == "APPROVED":
        if agr["status"] not in EXPENSE_ACTIVE_AGREEMENT_STATES:
            raise api_err(
                "ERR_INVALID_STATE",
                "Approval requires agreement IN_PREP or UNDERWAY",
            )
        _cap_check(agr, e)
    e["status"] = outcome
    mutate(e)
    return respond_object(ser_expense(e))


@bp.route("/expenses/<eid>/dispute", methods=["POST"])
def dispute_expense(eid):
    require_roles("Client", "RetailBroker")
    e = get_or_404("expenses", eid, "ExpenseEntry")
    agr = _agreement_of(e)
    _client_side_or_403(agr)
    if e["status"] != "APPROVED":
        raise api_err("ERR_INVALID_STATE", "ExpenseEntry is not APPROVED")
    if agr["status"] not in EXPENSE_ACTIVE_AGREEMENT_STATES:
        raise api_err(
            "ERR_INVALID_STATE", "Dispute requires agreement IN_PREP or UNDERWAY"
        )
    e["status"] = "DISPUTED"
    mutate(e)
    return respond_object(ser_expense(e))


@bp.route("/expenses/<eid>/resolve", methods=["POST"])
def resolve_expense(eid):
    require_roles("CentralAgent")
    e = get_or_404("expenses", eid, "ExpenseEntry")
    agr = _agreement_of(e)
    if g.user_id != agr["central_agent_id"]:
        raise api_err(
            "ERR_FORBIDDEN", "Caller is not the agreement's central agent"
        )
    if e["status"] != "DISPUTED":
        raise api_err("ERR_INVALID_STATE", "ExpenseEntry is not DISPUTED")
    body = body_json()
    outcome = as_enum(req_field(body, "outcome"), ("APPROVED", "REJECTED"), "outcome")
    if outcome == "APPROVED":
        _cap_check(agr, e)
    e["status"] = outcome
    mutate(e)
    return respond_object(ser_expense(e))
