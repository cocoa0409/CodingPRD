"""Sponsors, permit holders, escrow deposits and the review-team roster (PRD 3.1)."""
from decimal import Decimal

import auth
import ledger
import lookup
import serialize
import store
from errors import ApiError
from flask import Blueprint
from response import list_response, object_response
from validation import (PERMIT_RE, json_body, pagination, paginate, v_enum, v_huc8,
                        v_int, v_decimal, v_string)

bp = Blueprint("parties", __name__)

LEGAL_ENTITY_TYPES = ("PRIVATE_ENTREPRENEURIAL", "PUBLIC_AGENCY", "NGO")
AGENCIES = ("USACE", "EPA", "USFWS", "STATE_DEQ", "TRIBAL")
ROSTER_STATUSES = ("SEATED", "RECUSED")


@bp.get("/mitigation/sponsors/<row_id>")
def read_sponsor(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    return object_response(serialize.sponsor(lookup.sponsor(row_id)))


@bp.post("/mitigation/sponsors")
def create_sponsor():
    auth.authenticate("ProgramAdmin")
    body = json_body()
    row = store.new_row({
        "legal_name": v_string(body, "legal_name", max_len=160),
        "legal_entity_type": v_enum(body, "legal_entity_type", LEGAL_ENTITY_TYPES),
        "performance_bond_cents": v_int(body, "performance_bond_cents", required=False,
                                        minimum=0, default=0),
    })
    store.sponsors[row["id"]] = row
    return object_response(serialize.sponsor(row), 201)


@bp.get("/mitigation/permittees/<row_id>")
def read_permittee(row_id):
    auth.authenticate("ProgramAdmin", "Permittee", "Sponsor", "IRTChair")
    return object_response(serialize.permittee(lookup.permittee(row_id)))


@bp.post("/mitigation/permittees")
def create_permittee():
    auth.authenticate("ProgramAdmin")
    body = json_body()
    fields = {
        "organization_name": v_string(body, "organization_name", max_len=160),
        "permit_number": v_string(body, "permit_number", pattern=PERMIT_RE),
        "impact_huc8_code": v_huc8(body, "impact_huc8_code"),
        "required_credits": v_decimal(body, "required_credits", places=2, min_exclusive=0),
        "deposited_cents": 0,
    }
    for existing in store.permittees.values():
        if existing["permit_number"] == fields["permit_number"]:
            raise ApiError("ERR_DUPLICATE_PERMIT_NUMBER",
                           "Permit number %s is already registered." % fields["permit_number"])
    row = store.new_row(fields)
    store.permittees[row["id"]] = row
    return object_response(serialize.permittee(row), 201)


@bp.post("/mitigation/permittees/<row_id>/deposits")
def create_deposit(row_id):
    actor = auth.authenticate("ProgramAdmin", "Permittee")
    body = json_body()
    amount = v_int(body, "amount_cents", minimum=0)
    permittee = lookup.permittee(row_id)
    auth.require_sale_permittee(actor, permittee["id"])
    permittee["deposited_cents"] += amount
    store.touch(permittee)
    return object_response(serialize.permittee(permittee))


@bp.get("/mitigation/irt-members/<row_id>")
def read_member(row_id):
    auth.authenticate("ProgramAdmin", "IRTChair", "IRTMember")
    return object_response(serialize.irt_member(lookup.irt_member(row_id)))


@bp.post("/mitigation/irt-members")
def create_member():
    auth.authenticate("ProgramAdmin")
    body = json_body()
    row = store.new_row({
        "member_name": v_string(body, "member_name", max_len=120),
        "agency": v_enum(body, "agency", AGENCIES),
        "roster_status": v_enum(body, "roster_status", ROSTER_STATUSES, required=False,
                                default="SEATED"),
    })
    store.irt_members[row["id"]] = row
    return object_response(serialize.irt_member(row), 201)


@bp.get("/mitigation/irt-members/<row_id>/votes")
def list_member_votes(row_id):
    auth.authenticate("ProgramAdmin", "IRTChair", "IRTMember")
    limit, offset = pagination()
    member = lookup.irt_member(row_id)
    rows = store.ordered([v for v in store.prospectus_votes.values()
                          if v["irt_member_id"] == member["id"]])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.prospectus_vote(v) for v in page], limit, offset, total)
