"""Speaker agreements: drafting fan-out, signature fork and execution (PRD §3.5)."""

from flask import Blueprint, g

import db
import errors
import validators as v
from errors import fail
from middleware import get_contract, own_contract, roles
from response import ok, paged
from services import calc, lifecycle
from store import public, touch
from timeutil import fmt_iso

bp = Blueprint("contracts", __name__)


@bp.get("/contracts")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def list_contracts():
    engagement_id = v.query_string("engagement_id")
    status = v.query_string("status")
    rows = []
    for row in db.contracts.values():
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/contracts/<contract_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def read_contract(contract_id):
    return ok(public(get_contract(contract_id)))


@bp.post("/contracts/<contract_id>/send")
@roles("BookingAgent")
def send_contract(contract_id):
    contract = get_contract(contract_id)
    own_contract(contract)

    if contract["status"] != "DRAFT":
        fail(errors.ERR_CONTRACT_STATE_INVALID)
    engagement = db.engagements[contract["engagement_id"]]
    if engagement["booking_status"] != "CONFIRMED":
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    contract["status"] = "SENT"
    touch(contract)
    return ok(public(contract))


@bp.post("/contracts/<contract_id>/sign")
@roles("Speaker", "Client")
def sign_contract(contract_id):
    contract = get_contract(contract_id)
    data = v.body()
    v.req_string(data, "signature_name")
    own_contract(contract)

    if contract["status"] not in ("SENT", "PARTIALLY_SIGNED"):
        fail(errors.ERR_CONTRACT_STATE_INVALID)

    engagement = db.engagements[contract["engagement_id"]]
    speaker = db.speakers[engagement["speaker_id"]]
    inquiry = db.inquiries[engagement["inquiry_id"]]
    client = db.clients[inquiry["client_id"]]
    now = db.now_utc()

    if g.role == "Speaker":
        if contract["speaker_signed_at_utc"] is not None:
            fail(errors.ERR_PARTY_ALREADY_SIGNED)
        if speaker["roster_status"] != "ACTIVE":
            fail(errors.ERR_SPEAKER_NOT_ACTIVE)
        contract["speaker_signed_at_utc"] = fmt_iso(now)
    else:
        if contract["client_signed_at_utc"] is not None:
            fail(errors.ERR_PARTY_ALREADY_SIGNED)
        if client["credit_status"] == "HOLD":
            fail(errors.ERR_CLIENT_CREDIT_HOLD)
        contract["client_signed_at_utc"] = fmt_iso(now)

    both_signed = (contract["speaker_signed_at_utc"] is not None
                   and contract["client_signed_at_utc"] is not None)
    if both_signed:
        contract["status"] = "EXECUTED"
        contract["executed_at_utc"] = fmt_iso(now)
    else:
        contract["status"] = "PARTIALLY_SIGNED"
    touch(contract)

    if both_signed:
        _execute(contract, engagement, speaker, client)
    return ok(public(contract))


def _execute(contract, engagement, speaker, client):
    """The execution fan-out of PRD §3.5."""
    engagement["booking_status"] = "CONTRACTED"
    engagement["recording_rights"] = contract["recording_rights"]
    engagement["recording_fee_cents"] = contract["recording_fee_cents"]
    engagement["technical_rider_code"] = contract["technical_rider_code"]
    snapshot = calc.dec(speaker["default_commission_pct"])
    engagement["commission_pct_snapshot"] = float(snapshot)
    engagement["provisional_commission_cents"] = calc.provisional_commission(
        engagement["quoted_fee_cents"], snapshot)
    touch(engagement)

    option = db.options.get(engagement["selected_option_id"])
    if option is not None:
        proposal = db.proposals.get(option["proposal_id"])
        if proposal is not None and proposal["status"] == "ACCEPTED":
            proposal["status"] = "CLOSED"
            touch(proposal)

    if contract["exclusivity_days"] > 0:
        lifecycle.create_grant(engagement, contract, client)
