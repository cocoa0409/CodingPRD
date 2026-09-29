"""Buyer-side contacts and consent."""
from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from validate import (CONSENT_INPUT, CONSENT_STATUS, INCENTIVE_ELIGIBILITY,
                      TITLE_BAND, body, fk_from_query, opt_enum, paginate,
                      pagination, query_enum, query_str, req_enum, req_str,
                      resolve)

from services import serialize
from services.listing import by_created_at

bp = Blueprint("buyer_contacts", __name__)


def _get_deal(deal_id):
    return resolve(db.deals, deal_id, "ERR_DEAL_NOT_FOUND")


def _get_contact_of_deal(deal, contact_id):
    contact = db.buyer_contacts.get(contact_id)
    if contact is None or contact["deal_id"] != deal["id"]:
        fail("ERR_BUYER_CONTACT_NOT_FOUND")
    return contact


@bp.post("/deals/<deal_id>/buyer-contacts")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def add_buyer_contact(deal_id):
    deal = _get_deal(deal_id)
    payload = body()
    email = req_str(payload, "email")
    full_name = req_str(payload, "full_name")
    title_band = req_enum(payload, "title_band", TITLE_BAND)
    eligibility = opt_enum(payload, "incentive_eligibility", INCENTIVE_ELIGIBILITY,
                           "ELIGIBLE")
    lowered = email.strip().lower()
    for existing in db.buyer_contacts.values():
        if existing["deal_id"] == deal["id"] and existing["email"] == lowered:
            fail("ERR_DUPLICATE_RESOURCE_KEY",
                 "That email is already recorded on this deal.")
    contact = new_row({
        "deal_id": deal["id"],
        "email": lowered,
        "full_name": full_name,
        "title_band": title_band,
        "consent_status": "NOT_REQUESTED",
        "incentive_eligibility": eligibility,
    })
    db.buyer_contacts[contact["id"]] = contact
    return object_response(serialize.buyer_contact(contact), 201)


@bp.get("/deals/<deal_id>/buyer-contacts")
@endpoint(ANY_ROLE)
def list_deal_contacts(deal_id):
    deal = _get_deal(deal_id)
    consent_status = query_enum("consent_status", CONSENT_STATUS)
    limit, offset = pagination()
    rows = [c for c in db.buyer_contacts.values() if c["deal_id"] == deal["id"]]
    if consent_status:
        rows = [c for c in rows if c["consent_status"] == consent_status]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.buyer_contact(r) for r in page],
                         limit, offset, total)


@bp.get("/buyer-contacts/<contact_id>")
@endpoint(ANY_ROLE)
def read_buyer_contact(contact_id):
    contact = resolve(db.buyer_contacts, contact_id, "ERR_BUYER_CONTACT_NOT_FOUND")
    return object_response(serialize.buyer_contact(contact))


@bp.post("/deals/<deal_id>/buyer-contacts/<contact_id>/consent")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def record_consent(deal_id, contact_id):
    deal = _get_deal(deal_id)
    contact = _get_contact_of_deal(deal, contact_id)
    payload = body()
    consent_status = req_enum(payload, "consent_status", CONSENT_INPUT)
    contact["consent_status"] = consent_status
    touch(contact)
    return object_response(serialize.buyer_contact(contact))


@bp.get("/buyer-contacts")
@endpoint(ANY_ROLE)
def list_buyer_contacts():
    deal_id = fk_from_query("deal_id", db.deals, "ERR_DEAL_NOT_FOUND")
    email = query_str("email")
    consent_status = query_enum("consent_status", CONSENT_STATUS)
    eligibility = query_enum("incentive_eligibility", INCENTIVE_ELIGIBILITY)
    limit, offset = pagination()
    rows = list(db.buyer_contacts.values())
    if deal_id:
        rows = [c for c in rows if c["deal_id"] == deal_id]
    if email:
        lowered = email.strip().lower()
        rows = [c for c in rows if c["email"] == lowered]
    if consent_status:
        rows = [c for c in rows if c["consent_status"] == consent_status]
    if eligibility:
        rows = [c for c in rows if c["incentive_eligibility"] == eligibility]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.buyer_contact(r) for r in page],
                         limit, offset, total)
