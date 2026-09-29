"""Household (Client) endpoints and the receivable ledger (PRD 3.1, 3.7)."""

from flask import Blueprint, request

import db
from db import CLIENT_STATUSES, NDA_STATUSES, REGION_CODES, serialize, sort_by_sequence, store, touch
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    BILLING_ADMINISTRATOR,
    CANDIDATE,
    CLIENT,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    VETTING_SPECIALIST,
    authenticate,
)
from response import created_response, list_response, object_response
from services import domain
from validation import (
    apply_filters,
    body_of,
    check_enum,
    check_int,
    list_params,
    require_email,
    require_present,
    require_string,
)

bp = Blueprint("clients", __name__)


def _new_client(household_name, primary_contact_email, region_code):
    row = {
        "household_name": household_name,
        "primary_contact_email": primary_contact_email,
        "region_code": region_code,
        "status": "PROSPECT",
        "confidentiality_agreement_status": "UNSIGNED",
        "signatory_name": None,
        "countersigned_at": None,
        "outstanding_balance_cents": 0,
        "placement_count": 0,
        "non_solicitation_expires_on": None,
    }
    db.stamp_new(row)
    store.clients[row["id"]] = row
    return row


@bp.post("/clients")
def create_client():
    authenticate({AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT})
    body = body_of(request)
    household_name = require_string(body, "household_name", 1, 120)
    primary_contact_email = require_email(body, "primary_contact_email")
    require_present(body, "region_code")
    region_code = check_enum(body, "region_code", REGION_CODES)
    row = _new_client(household_name, primary_contact_email, region_code)
    return created_response(serialize(row))


@bp.get("/clients/<client_id>")
def get_client(client_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT, CANDIDATE,
    })
    row = domain.resolve("clients", client_id)
    return object_response(serialize(row))


@bp.get("/clients")
def list_clients():
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={
            "status": CLIENT_STATUSES,
            "region_code": REGION_CODES,
            "confidentiality_agreement_status": NDA_STATUSES,
        },
    )
    rows = apply_filters(list(store.clients.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.post("/clients/<client_id>/confidentiality-agreement")
def confidentiality_agreement(client_id):
    user_id, role = authenticate({AGENCY_PRINCIPAL, CLIENT})
    body = body_of(request)

    # PRD 2.1: authorisation is partitioned by the supplied action value, and the
    # 403 precedes request-shape validation whenever the action is determinable.
    raw_action = body.get("action")
    if raw_action == "SIGN" and role != CLIENT:
        fail("ERR_UNAUTHORIZED")
    if raw_action == "COUNTERSIGN" and role != AGENCY_PRINCIPAL:
        fail("ERR_UNAUTHORIZED")

    require_present(body, "action")
    signatory_name = require_string(body, "signatory_name", 1, 120, required=False)
    action = check_enum(body, "action", ["SIGN", "COUNTERSIGN"])

    client = domain.resolve("clients", client_id)

    if action == "SIGN":
        if client["confidentiality_agreement_status"] != "UNSIGNED":
            fail("ERR_INVALID_STATE_TRANSITION")
        client["confidentiality_agreement_status"] = "SIGNED"
        if signatory_name is not None:
            client["signatory_name"] = signatory_name
        touch(client)
    else:
        if client["confidentiality_agreement_status"] != "SIGNED":
            fail("ERR_INVALID_STATE_TRANSITION")
        client["confidentiality_agreement_status"] = "COUNTERSIGNED"
        client["countersigned_at"] = store.now_str()
        if client["status"] == "PROSPECT":
            client["status"] = "ONBOARDED"
        touch(client)

    return object_response(serialize(client))


@bp.post("/clients/<client_id>/ledger-adjustments")
def create_ledger_adjustment(client_id):
    authenticate({BILLING_ADMINISTRATOR})
    body = body_of(request)

    require_present(body, "entry_type", "signed_amount_cents")
    memo = require_string(body, "memo", 1, 200, required=False)
    # MANUAL_ADJUSTMENT is the only entry_type a caller may nominate directly.
    check_enum(body, "entry_type", ["MANUAL_ADJUSTMENT"])
    signed_amount_cents = check_int(body, "signed_amount_cents")
    if signed_amount_cents == 0:
        fail("ERR_INVALID_LEDGER_AMOUNT")

    client = domain.resolve("clients", client_id)

    entry = domain.append_ledger_entry(
        client, "MANUAL_ADJUSTMENT", signed_amount_cents, memo,
        related_ref_type="NONE", related_ref_id=None,
    )
    client["outstanding_balance_cents"] = entry["balance_after_cents"]
    touch(client)
    return created_response(serialize(entry))


@bp.get("/clients/<client_id>/ledger-entries")
def list_ledger_entries(client_id):
    authenticate({AGENCY_PRINCIPAL, BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT})
    limit, offset, filters = list_params(
        request,
        enum_filters={
            "entry_type": db.LEDGER_ENTRY_TYPES,
            "related_ref_type": db.LEDGER_REF_TYPES,
        },
    )
    client = domain.resolve("clients", client_id)
    rows = apply_filters(domain.ledger_of(client["id"]), filters)
    # The ledger is pinned to sequence_no ascending (PRD 2.3).
    data, total = domain.page(rows, limit, offset, ordered=sort_by_sequence(rows))
    return list_response(data, limit, offset, total)
