"""Logical clock, developer and reviewer identities, and properties (PRD 3.1)."""

import re

from flask import Blueprint

from auth import caller_role, require
from clock import clock, parse_iso
from db import base_record, store
from errors import ApiError
from response import created_response, object_response
from services import property_out
from support import fetch, state_code
from validate import bad, body, req_enum, req_int, req_str

bp = Blueprint("identity", __name__)

_DIGITS4 = re.compile(r"^\d{4}$")

ENTITY_TYPES = ("C_CORP", "S_CORP", "PARTNERSHIP", "LLC")
AGENCIES = ("SHPO", "NPS")
CREDENTIAL_STATUSES = ("ACTIVE", "SUSPENDED")
LISTING_STATUSES = (
    "NOT_LISTED",
    "INDIVIDUAL_LISTED",
    "DISTRICT_CONTRIBUTING",
    "DISTRICT_NONCONTRIBUTING",
)

ALL_READ_ROLES = (
    "PlatformAdmin",
    "Developer",
    "ShpoReviewer",
    "NpsReviewer",
    "ComplianceMonitor",
    "InvestorAdmin",
)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    # The sole endpoint exempt from the X-User-ID requirement (PRD 2.4).
    role = caller_role()
    if role is not None and role != "PlatformAdmin":
        raise ApiError("ERR_UNAUTHORIZED")
    data = body()
    raw = req_str(data, "to_iso8601")
    moment = parse_iso(raw)
    if moment is None:
        raise bad("Field 'to_iso8601' must be an ISO 8601 UTC instant.")
    if moment < clock.now():
        raise bad("The logical clock only ever moves forward.")
    clock.set(moment)
    return object_response({"current_utc": clock.now_iso()})


# --------------------------------------------------------------------------
# developers
# --------------------------------------------------------------------------


@bp.post("/developers")
def create_developer():
    require("PlatformAdmin")
    data = body()
    legal_name = req_str(data, "legal_name", min_len=1, max_len=120)
    last4 = req_str(data, "taxpayer_id_last4")
    if not _DIGITS4.match(last4):
        raise bad("Field 'taxpayer_id_last4' must be exactly four digits.")
    entity_type = req_enum(data, "entity_type", ENTITY_TYPES)
    email = req_str(data, "contact_email", min_len=1, max_len=320, required=False)
    if email is not None and "@" not in email:
        raise bad("Field 'contact_email' must contain an at-sign.")

    record = base_record(with_mutation_fields=False)
    record.update(
        {
            "legal_name": legal_name,
            "taxpayer_id_last4": last4,
            "entity_type": entity_type,
            "contact_email": email,
        }
    )
    store.developers[record["id"]] = record
    return created_response(_public(record))


@bp.get("/developers/<dev_id>")
def read_developer(dev_id):
    require("PlatformAdmin", "Developer", "ComplianceMonitor", "InvestorAdmin")
    record = fetch(store.developers, dev_id, "ERR_DEVELOPER_NOT_FOUND")
    return object_response(_public(record))


# --------------------------------------------------------------------------
# reviewers
# --------------------------------------------------------------------------


@bp.post("/reviewers")
def create_reviewer():
    require("PlatformAdmin")
    data = body()
    full_name = req_str(data, "full_name", min_len=1, max_len=80)
    agency = req_enum(data, "agency", AGENCIES)
    code = state_code(data, "state_code")
    credential = req_enum(
        data, "credential_status", CREDENTIAL_STATUSES, required=False, default="ACTIVE"
    )

    record = base_record(with_mutation_fields=False)
    record.update(
        {
            "full_name": full_name,
            "agency": agency,
            "state_code": code,
            "credential_status": credential,
        }
    )
    store.reviewers[record["id"]] = record
    return created_response(_public(record))


@bp.get("/reviewers/<reviewer_id>")
def read_reviewer(reviewer_id):
    require("PlatformAdmin", "Developer", "ShpoReviewer", "NpsReviewer", "ComplianceMonitor")
    record = fetch(store.reviewers, reviewer_id, "ERR_REVIEWER_NOT_FOUND")
    return object_response(_public(record))


# --------------------------------------------------------------------------
# properties
# --------------------------------------------------------------------------


@bp.post("/properties")
def create_property():
    require("PlatformAdmin", "Developer")
    data = body()
    name = req_str(data, "name", min_len=1, max_len=120)
    street = req_str(data, "street_address", min_len=1, max_len=160)
    city = req_str(data, "city", min_len=1, max_len=80)
    code = state_code(data, "state_code")
    year_built = req_int(data, "year_built", min_v=1600, max_v=2010)
    listing = req_enum(data, "listing_status", LISTING_STATUSES, required=False, default="NOT_LISTED")

    record = base_record()
    record.update(
        {
            "name": name,
            "street_address": street,
            "city": city,
            "state_code": code,
            "year_built": year_built,
            "listing_status": listing,
            "evaluation_status": "UNEVALUATED",
            "certified_at": None,
            "open_project_count": 0,
        }
    )
    store.properties[record["id"]] = record
    return created_response(property_out(record))


@bp.get("/properties/<property_id>")
def read_property(property_id):
    require(*ALL_READ_ROLES)
    record = fetch(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    return object_response(property_out(record))


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}
