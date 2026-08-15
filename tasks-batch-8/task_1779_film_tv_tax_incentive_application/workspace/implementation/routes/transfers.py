"""CreditTransfer endpoints: propose (OCC), counter, accept, settle, cancel."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AMOUNT_EXCEEDS_REMAINING,
    ERR_CERTIFICATE_EXPIRED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_OWNER,
    ERR_STALE_CERTIFICATE_VERSION,
    ERR_TRANSFER_EXPIRED,
    ERR_TRANSFER_PRICE_BELOW_FLOOR,
)
from helpers import (
    check_producer_owns,
    company_id_of_certificate,
    get_one,
    list_query,
    public,
)
from middleware import authorized
from response import success_object
from services.core import (
    new_record,
    settle_transfer,
    touch,
    transfer_price_floor_cents,
)
from util import CLOCK, fmt_dt, parse_dt
from validate import (
    get_body,
    reject_unknown_fields,
    req_int,
    req_str,
    require_body_ref,
    require_path_resource,
    version_field,
)

bp = Blueprint("transfers", __name__)


def _program_of_certificate(cert):
    app = db["applications"].get(cert["application_id"])
    return db["jurisdiction_programs"].get(app["jurisdiction_program_id"])


@bp.post("/transfers")
def create_transfer():
    caller = authorized(["Producer"])
    body = get_body()
    reject_unknown_fields(body, {
        "certificate_id", "buyer_id", "amount_cents", "price_cents",
        "expected_certificate_version",
    })
    certificate_id = req_str(body, "certificate_id")
    buyer_id = req_str(body, "buyer_id")
    amount_cents = req_int(body, "amount_cents", positive=True)
    price_cents = req_int(body, "price_cents", non_negative=True)
    expected = version_field(body, "expected_certificate_version")

    # Existence (3): body FKs left to right.
    cert = require_body_ref("certificates", certificate_id, "certificate_id")
    require_body_ref("credit_buyers", buyer_id, "buyer_id")

    # Ownership (4): the seller is the certificate's production company.
    seller_company_id = company_id_of_certificate(cert)
    check_producer_owns(caller, seller_company_id)

    # State (5): certificate must be ISSUED or PARTIALLY_TRANSFERRED.
    if cert["status"] not in ("ISSUED", "PARTIALLY_TRANSFERRED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"cannot propose a transfer against a {cert['status']} certificate")

    # OCC (7): expected_certificate_version guards the create.
    if expected != int(cert["version"]):
        raise_error(ERR_STALE_CERTIFICATE_VERSION,
                    "expected_certificate_version does not match the certificate's current version")

    # Temporal (9): the certificate must be unexpired.
    if CLOCK.now() > parse_dt(cert["expires_at"]):
        raise_error(ERR_CERTIFICATE_EXPIRED, "the certificate has expired")

    # Fiscal (12): amount against remaining, then price against the floor.
    if amount_cents > int(cert["remaining_amount_cents"]):
        raise_error(ERR_AMOUNT_EXCEEDS_REMAINING,
                    "amount_cents exceeds the certificate's remaining balance")
    program = _program_of_certificate(cert)
    if price_cents < transfer_price_floor_cents(program, amount_cents):
        raise_error(ERR_TRANSFER_PRICE_BELOW_FLOOR,
                    "price_cents is below the program's transfer price floor")

    now = CLOCK.now()
    rec = new_record("transfers", {
        "certificate_id": certificate_id,
        "buyer_id": buyer_id,
        "seller_production_company_id": seller_company_id,
        "amount_cents": amount_cents,
        "price_cents": price_cents,
        "current_price_cents": price_cents,
        "round_count": 0,
        "status": "PROPOSED",
        "proposed_at": CLOCK.now_iso(),
        "expires_at": fmt_dt(now + timedelta(days=int(program["transfer_proposal_validity_days"]))),
        "settled_at": None,
        "cancellation_reason": None,
    })
    # Creating a proposal increments the certificate's version (arms the OCC
    # guard for the next proposer).
    touch(cert)
    return success_object(public(rec), status=201)


@bp.get("/transfers")
def list_transfers():
    return list_query("transfers", {
        "certificate_id": request.args.get("certificate_id"),
        "buyer_id": request.args.get("buyer_id"),
        "status": request.args.get("status"),
    })


@bp.get("/transfers/<transferId>")
def get_transfer(transferId):
    return get_one("transfers", transferId)


def _check_acting_party(caller, transfer, party):
    """Priority 4: the actor side is pinned by the transfer's state.

    party == "buyer": caller must be the transfer's buyer.
    party == "seller": caller must own the seller production company.
    """
    if party == "buyer":
        if caller.user_id != transfer["buyer_id"]:
            raise_error(ERR_NOT_OWNER, "the buyer holds the acting side of this transfer")
    else:
        if caller.user_id != transfer["seller_production_company_id"]:
            raise_error(ERR_NOT_OWNER, "the seller production company holds the acting side of this transfer")


def _check_transfer_not_expired(transfer):
    if CLOCK.now() > parse_dt(transfer["expires_at"]):
        raise_error(ERR_TRANSFER_EXPIRED, "the transfer proposal has expired")


@bp.post("/transfers/<transferId>/counter")
def counter_transfer(transferId):
    caller = authorized(["Producer", "CreditBuyer"])
    transfer = require_path_resource("transfers", transferId)
    body = get_body()
    reject_unknown_fields(body, {"new_price_cents"})
    new_price_cents = req_int(body, "new_price_cents", non_negative=True)

    # State (5) + acting-party ownership (4): the party NOT holding the
    # standing offer counters — the buyer while PROPOSED, the seller while
    # COUNTERED.
    if transfer["status"] == "PROPOSED":
        _check_acting_party(caller, transfer, "buyer")
    elif transfer["status"] == "COUNTERED":
        _check_acting_party(caller, transfer, "seller")
    else:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"counter is not declared from status {transfer['status']}")
    # Temporal (9).
    _check_transfer_not_expired(transfer)
    # Fiscal (12): the new price re-clears the floor against the face amount.
    cert = db["certificates"].get(transfer["certificate_id"])
    program = _program_of_certificate(cert)
    if new_price_cents < transfer_price_floor_cents(program, int(transfer["amount_cents"])):
        raise_error(ERR_TRANSFER_PRICE_BELOW_FLOOR,
                    "new_price_cents is below the program's transfer price floor")
    transfer["current_price_cents"] = new_price_cents
    transfer["round_count"] = int(transfer["round_count"]) + 1
    transfer["status"] = "COUNTERED" if transfer["status"] == "PROPOSED" else "PROPOSED"
    touch(transfer)
    return success_object(public(transfer))


@bp.post("/transfers/<transferId>/accept")
def accept_transfer(transferId):
    caller = authorized(["Producer", "CreditBuyer"])
    transfer = require_path_resource("transfers", transferId)
    body = get_body()
    reject_unknown_fields(body, set())

    # Acceptance mirrors the counter split: the buyer accepts a PROPOSED
    # offer; the seller accepts a COUNTERED one.
    if transfer["status"] == "PROPOSED":
        _check_acting_party(caller, transfer, "buyer")
    elif transfer["status"] == "COUNTERED":
        _check_acting_party(caller, transfer, "seller")
    else:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"accept is not declared from status {transfer['status']}")
    _check_transfer_not_expired(transfer)
    transfer["status"] = "ACCEPTED"
    touch(transfer)
    return success_object(public(transfer))


@bp.post("/transfers/<transferId>/settle")
def settle(transferId):
    authorized(["FilmOfficeAdmin"])
    transfer = require_path_resource("transfers", transferId)
    body = get_body()
    reject_unknown_fields(body, set())
    # State (5): settle is declared only from ACCEPTED.
    if transfer["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"settle is not declared from status {transfer['status']}")
    cert = db["certificates"].get(transfer["certificate_id"])
    # State (5): the certificate must still be settleable.
    if cert["status"] not in ("ISSUED", "PARTIALLY_TRANSFERRED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"cannot settle against a {cert['status']} certificate")
    # Temporal (9): certificate expiry, then transfer expiry.
    if CLOCK.now() > parse_dt(cert["expires_at"]):
        raise_error(ERR_CERTIFICATE_EXPIRED, "the certificate has expired")
    _check_transfer_not_expired(transfer)
    # Fiscal (12): the face amount must fit the remaining balance at settle.
    if int(transfer["amount_cents"]) > int(cert["remaining_amount_cents"]):
        raise_error(ERR_AMOUNT_EXCEEDS_REMAINING,
                    "amount_cents exceeds the certificate's remaining balance")
    settle_transfer(transfer, cert)
    return success_object(public(transfer))


@bp.post("/transfers/<transferId>/cancel")
def cancel_transfer(transferId):
    caller = authorized(["Producer", "CreditBuyer"])
    transfer = require_path_resource("transfers", transferId)
    body = get_body()
    reject_unknown_fields(body, {"cancel_reason"})
    # State (5).
    if transfer["status"] not in ("PROPOSED", "COUNTERED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"cancel is not declared from status {transfer['status']}")
    # Ownership (4): the seller cancels in either state; the buyer may only
    # withdraw a counter-offer it placed (i.e. while COUNTERED).
    is_seller = caller.user_id == transfer["seller_production_company_id"]
    is_buyer_with_counter = (
        caller.user_id == transfer["buyer_id"] and transfer["status"] == "COUNTERED"
    )
    if not (is_seller or is_buyer_with_counter):
        raise_error(ERR_NOT_OWNER, "caller is not in a position to cancel this transfer")
    transfer["status"] = "CANCELLED"
    transfer["cancellation_reason"] = "MANUAL"
    touch(transfer)
    return success_object(public(transfer))
