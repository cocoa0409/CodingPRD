"""Holder enrolment, physical-credential changes and address propagation."""

import re

from flask import Blueprint

import cascade
import derive
import lookup
import serialize
import validate as v
from auth import endpoint
from envelope import ok, ok_list
from store import base_row, db, sort_rows, touch

bp = Blueprint("holder", __name__, url_prefix="/mdl")

PHYSICAL_STATUSES = ("VALID", "EXPIRED", "SUSPENDED", "REVOKED", "CANCELLED")
DEVICE_STATES = ("REGISTERED", "ATTESTED", "BOUND", "LOST_REPORTED", "WIPED", "RETIRED")
PROOFING_STATES = (
    "COLLECTING", "SUBMITTED", "VERIFIED", "RETURNED", "DENIED", "EXPIRED", "CONSUMED",
)
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def _state_code(body, name, required=True):
    if required:
        value = v.req_str(body, name)
    else:
        value = v.opt_str(body, name)
        if value is None:
            return None
    if not STATE_CODE_RE.match(value):
        raise v.bad_request("Field '%s' must be exactly two uppercase letters." % name)
    return value


@endpoint(bp, "/holders", ["POST"], ["SystemAdmin"])
def create_holder():
    body = v.body()
    legal_name = v.req_str(body, "legal_name")
    date_of_birth = v.req_date(body, "date_of_birth")
    address_line1 = v.req_str(body, "address_line1")
    city = v.req_str(body, "city")
    state_code = _state_code(body, "state_code")
    postal_code = v.req_str(body, "postal_code")
    physical_number = v.req_str(body, "physical_credential_number")
    expires_on = v.req_date(body, "physical_credential_expires_on")
    status = v.opt_enum(body, "physical_credential_status", PHYSICAL_STATUSES, "VALID")
    restriction_codes = v.opt_array_str(body, "restriction_codes", [])

    for existing in db.holders.values():
        if existing["physical_credential_number"] == physical_number:
            raise v.bad_request(
                "physical_credential_number must be unique across all holders."
            )

    row = base_row("Holder")
    row["legal_name"] = legal_name
    row["date_of_birth"] = date_of_birth
    row["address_line1"] = address_line1
    row["city"] = city
    row["state_code"] = state_code
    row["postal_code"] = postal_code
    row["physical_credential_number"] = physical_number
    row["physical_credential_status"] = status
    row["physical_credential_expires_on"] = expires_on
    row["restriction_codes"] = restriction_codes
    row["address_version"] = 1
    db.holders[row["id"]] = row
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/holders/<holder_id>", ["GET"],
          ["SystemAdmin", "ProofingAgent", "CredentialAdjudicator", "Holder"])
def read_holder(holder_id):
    row = lookup.holder(holder_id)
    return ok(serialize.dump(row))


@endpoint(bp, "/holders/<holder_id>/physical-credential", ["PATCH"], ["SystemAdmin"])
def patch_physical_credential(holder_id):
    body = v.body()
    status = v.opt_enum(body, "physical_credential_status", PHYSICAL_STATUSES)
    expires_on = v.opt_date(body, "physical_credential_expires_on")
    restriction_codes = v.opt_array_str(body, "restriction_codes")

    holder = lookup.holder(holder_id)

    if expires_on is not None:
        holder["physical_credential_expires_on"] = expires_on

    if status is not None:
        holder["physical_credential_status"] = status
        credentials = sort_rows(derive.credentials_of_holder(holder["id"]))
        if status == "SUSPENDED":
            for credential in credentials:
                if credential["lifecycle_state"] == "ACTIVE":
                    cascade.suspend_credential(
                        credential, "PHYSICAL_CREDENTIAL_SUSPENDED",
                        "SUSPENDED", "ADMIN_HOLD",
                    )
        elif status == "VALID":
            for credential in credentials:
                if (credential["lifecycle_state"] == "SUSPENDED"
                        and credential.get("suspend_reason")
                        == "PHYSICAL_CREDENTIAL_SUSPENDED"):
                    cascade.reinstate_credential(credential)
        elif status == "REVOKED":
            for credential in credentials:
                if credential["lifecycle_state"] in ("ACTIVE", "SUSPENDED"):
                    cascade.revoke_credential(
                        credential, "PHYSICAL_CREDENTIAL_REVOKED"
                    )

    if restriction_codes is not None:
        holder["restriction_codes"] = restriction_codes

    touch(holder)

    if restriction_codes is not None:
        cascade.open_update_order(
            holder,
            "RESTRICTION_CHANGE",
            "Physical credential restriction codes updated to [%s]."
            % ", ".join(restriction_codes),
            holder["address_version"],
        )

    return ok(serialize.dump(holder))


@endpoint(bp, "/holders/<holder_id>/address-change", ["POST"], ["SystemAdmin"])
def address_change(holder_id):
    body = v.body()
    address_line1 = v.req_str(body, "address_line1")
    city = v.req_str(body, "city")
    state_code = _state_code(body, "state_code")
    postal_code = v.req_str(body, "postal_code")

    holder = lookup.holder(holder_id)
    holder["address_line1"] = address_line1
    holder["city"] = city
    holder["state_code"] = state_code
    holder["postal_code"] = postal_code
    holder["address_version"] += 1
    touch(holder)

    order = cascade.open_update_order(
        holder,
        "ADDRESS_CHANGE",
        "Address of record updated to %s, %s %s %s."
        % (address_line1, city, state_code, postal_code),
        holder["address_version"],
    )
    return ok(serialize.dump(order), 201)


@endpoint(bp, "/holders/<holder_id>/devices", ["GET"],
          ["SystemAdmin", "Holder", "PrivacyAuditor"])
def list_holder_devices(holder_id):
    limit, offset = v.pagination()
    state = v.q_enum("state", DEVICE_STATES)
    holder = lookup.holder(holder_id)
    rows = [d for d in db.devices.values() if d["holder_id"] == holder["id"]]
    if state is not None:
        rows = [d for d in rows if d["state"] == state]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)


@endpoint(bp, "/holders/<holder_id>/proofing-sessions", ["GET"],
          ["SystemAdmin", "ProofingAgent", "CredentialAdjudicator"])
def list_holder_proofing_sessions(holder_id):
    limit, offset = v.pagination()
    state = v.q_enum("state", PROOFING_STATES)
    holder = lookup.holder(holder_id)
    rows = [s for s in db.proofing_sessions.values()
            if s["holder_id"] == holder["id"]]
    if state is not None:
        rows = [s for s in rows if s["state"] == state]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)
