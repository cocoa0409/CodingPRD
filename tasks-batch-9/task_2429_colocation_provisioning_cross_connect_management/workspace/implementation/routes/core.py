"""The logical clock, customers and the authorization list (PRD §3.1, §3.7)."""

from flask import Blueprint

import refs
from auth import authorize
from errors import ApiError
from response import created, ok, ok_list, paginate, pagination, serialize
from store import (
    ACCESS_LEVELS,
    AUTH_SCOPES,
    BIOMETRIC_STATES,
    base_row,
    now,
    store,
    touch,
)
from util import fmt_dt
from validate import json_body, qfilter, req_datetime, req_enum, req_id, req_string, req_string_list, opt_enum

bp = Blueprint("core", __name__)

ALL_ROLES = (
    "ProvisioningEngineer",
    "FacilityManager",
    "SecurityOfficer",
    "BillingOperator",
    "CustomerAdmin",
)


# --------------------------------------------------------------------------
# Logical clock — PRD §2.4
# --------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(*ALL_ROLES)
    body = json_body()
    current = req_datetime(body, "current_utc")
    store.clock = current
    return ok({"current_utc": fmt_dt(current)})


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------

@bp.route("/customers", methods=["POST"])
def create_customer():
    authorize("FacilityManager", "BillingOperator")
    body = json_body()
    legal_name = req_string(body, "legal_name")
    account_code = req_string(body, "account_code")
    for existing in store.customers.values():
        if existing["account_code"] == account_code:
            raise ApiError("ERR_INVALID_REQUEST", "account_code must be unique across customers")
    customer = base_row()
    customer.update(
        {
            "legal_name": legal_name,
            "account_code": account_code,
            "account_status": "ACTIVE",
        }
    )
    store.customers[customer["id"]] = customer
    return created(serialize(customer))


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    actor = authorize(*ALL_ROLES)
    customer = refs.path_row(refs.CUSTOMER, customer_id)
    actor.scope_customer_id(customer_id)
    return ok(serialize(customer))


# --------------------------------------------------------------------------
# Authorized contacts
# --------------------------------------------------------------------------

CONTACT_ROLES = ("CustomerAdmin", "SecurityOfficer", "ProvisioningEngineer", "FacilityManager")


@bp.route("/contacts", methods=["POST"])
def create_contact():
    actor = authorize("CustomerAdmin", "SecurityOfficer")
    body = json_body()
    customer = refs.body_fk(body, "customer_id", refs.CUSTOMER)
    if customer is not None:
        actor.scope_customer_id(customer["id"])
    else:
        actor.require_customer()
    customer_id = req_id(body, "customer_id")
    full_name = req_string(body, "full_name")
    scopes = req_string_list(body, "authorization_scopes", allowed=AUTH_SCOPES)
    access_level = opt_enum(body, "access_level", ACCESS_LEVELS, "ESCORTED_ONLY")

    contact = base_row()
    contact.update(
        {
            "customer_id": customer_id,
            "full_name": full_name,
            "access_level": access_level,
            "authorization_scopes": list(scopes),
            "biometric_state": "NOT_ENROLLED",
            "enrolled_at": None,
        }
    )
    store.contacts[contact["id"]] = contact
    return created(serialize(contact))


@bp.route("/contacts/<contact_id>/biometric-state", methods=["POST"])
def biometric_state(contact_id):
    authorize("SecurityOfficer")
    contact = refs.path_row(refs.CONTACT, contact_id)
    body = json_body()
    to_state = req_enum(body, "to_state", BIOMETRIC_STATES)

    current = contact["biometric_state"]
    if to_state == "NOT_ENROLLED" or to_state == current:
        raise ApiError(
            "ERR_INVALID_STATE",
            "biometric_state %s cannot transition to %s" % (current, to_state),
        )

    contact["biometric_state"] = to_state
    if to_state == "ENROLLED":
        contact["enrolled_at"] = now()
    touch(contact)

    if to_state == "REVOKED":
        _revoke_cascade(contact)
    return ok(serialize(contact))


def _revoke_cascade(contact):
    """PRD §3.7 — revocation forces authorization_state REVOKED on the
    contact's non-terminal tickets and CANCELLED on their SCHEDULED visits."""
    for ticket in store.tickets.values():
        if ticket["requested_by_contact_id"] != contact["id"]:
            continue
        if ticket["authorization_state"] not in ("PENDING_AUTHORIZATION", "AUTHORIZED"):
            continue
        if ticket["execution_state"] in ("COMPLETED", "CANCELLED"):
            continue
        ticket["authorization_state"] = "REVOKED"
        touch(ticket)
    for visit in store.visits.values():
        if visit["contact_id"] != contact["id"]:
            continue
        if visit["status"] != "SCHEDULED":
            continue
        visit["status"] = "CANCELLED"
        touch(visit)


@bp.route("/contacts/<contact_id>", methods=["GET"])
def get_contact(contact_id):
    actor = authorize(*CONTACT_ROLES)
    contact = refs.path_row(refs.CONTACT, contact_id)
    actor.scope_contact(contact)
    return ok(serialize(contact))


@bp.route("/contacts", methods=["GET"])
def list_contacts():
    actor = authorize(*CONTACT_ROLES)
    actor.require_customer()
    limit, offset = pagination()
    actor.scope_query(("customer", "customer_id"))
    rows = qfilter(list(store.contacts.values()), "customer_id", "access_level", "biometric_state")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)
