"""Billing claims lifecycle and the compensation ledger reads."""

from flask import Blueprint, request

import clock
import db
import services
import util
from errors import (
    ApiError,
    ERR_CLAIM_ALREADY_EXISTS,
    ERR_CLAIM_INVALID_STATE,
    ERR_CONSULT_NOT_ANSWERED,
    ERR_CONSULT_NOT_CHARGEABLE,
    ERR_TRACK_BILLING_CAP_EXCEEDED,
)
from middleware import require_roles, ANY_ROLE
from response import ok, ok_list
from util import serialize, serialize_list

bp = Blueprint("claims", __name__)

LEDGER_ROLES = ("ProgramCoordinator", "Specialist", "BillingClerk")


# --- billing claims --------------------------------------------------------------

@bp.route("/econsult/consult-requests/<rid>/billing-claims", methods=["POST"])
def create_claim(rid):
    require_roles("BillingClerk")
    util.json_body()
    consult = services.get_consult(rid)
    if consult["status"] != "ANSWERED":
        raise ApiError(ERR_CONSULT_NOT_ANSWERED, 409, "Consult is not ANSWERED")
    for existing in db.store["billing_claims"].values():
        if existing["consult_id"] == consult["id"]:
            raise ApiError(
                ERR_CLAIM_ALREADY_EXISTS, 409,
                "Consult already has a billing claim",
            )

    track = db.store["specialty_tracks"][consult["specialty_track_id"]]
    resp = services.response_for_consult(consult["id"])
    amount, code = services.claim_amount_and_code(consult, track, resp)

    rec = services.base_record()
    rec.update({
        "consult_id": consult["id"],
        "claim_code": code,
        "amount_cents": amount,
        "period_key": clock.now().strftime("%Y-%m"),
        "status": "DRAFT",
    })
    db.store["billing_claims"][rec["id"]] = rec
    return ok(serialize("billing_claim", rec), 201)


@bp.route("/econsult/consult-requests/<rid>/billing-claims", methods=["GET"])
def list_consult_claims(rid):
    require_roles(*ANY_ROLE)
    consult = services.get_consult(rid)
    records = [
        claim for claim in db.store["billing_claims"].values()
        if claim["consult_id"] == consult["id"]
    ]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("billing_claim", page), total, limit, offset)


@bp.route("/econsult/billing-claims/<rid>", methods=["GET"])
def get_claim(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("billing_claim", services.get_claim(rid)), 200)


@bp.route("/econsult/billing-claims/<rid>/submit", methods=["POST"])
def submit_claim(rid):
    require_roles("BillingClerk")
    claim = services.get_claim(rid)
    if claim["status"] != "DRAFT":
        raise ApiError(ERR_CLAIM_INVALID_STATE, 409, "Claim is not DRAFT")
    consult = db.store["consult_requests"][claim["consult_id"]]
    if consult["billing_status"] != "CHARGEABLE":
        raise ApiError(
            ERR_CONSULT_NOT_CHARGEABLE, 409,
            "Claim submit requires consult billing_status CHARGEABLE",
        )
    track = db.store["specialty_tracks"][consult["specialty_track_id"]]
    consumed = 0
    for other in db.store["billing_claims"].values():
        if other["status"] not in ("SUBMITTED", "PAID"):
            continue
        if other["period_key"] != claim["period_key"]:
            continue
        other_consult = db.store["consult_requests"].get(other["consult_id"])
        if other_consult is None:
            continue
        if other_consult["specialty_track_id"] != track["id"]:
            continue
        consumed += other["amount_cents"]
    if consumed + claim["amount_cents"] > track["monthly_billing_cap_cents"]:
        raise ApiError(
            ERR_TRACK_BILLING_CAP_EXCEEDED, 402,
            "Submit would exceed the track's monthly billing cap",
        )
    claim["status"] = "SUBMITTED"
    services.touch(claim)
    consult["billing_status"] = "CLAIMED"
    services.touch(consult)
    return ok(serialize("billing_claim", claim), 200)


@bp.route("/econsult/billing-claims/<rid>/mark-paid", methods=["POST"])
def mark_paid_claim(rid):
    require_roles("BillingClerk")
    claim = services.get_claim(rid)
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, 409, "Claim is not SUBMITTED")
    claim["status"] = "PAID"
    services.touch(claim)
    return ok(serialize("billing_claim", claim), 200)


@bp.route("/econsult/billing-claims/<rid>/deny", methods=["POST"])
def deny_claim(rid):
    require_roles("BillingClerk")
    claim = services.get_claim(rid)
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, 409, "Claim is not SUBMITTED")
    claim["status"] = "DENIED"
    services.touch(claim)
    return ok(serialize("billing_claim", claim), 200)


@bp.route("/econsult/billing-claims/<rid>/write-off", methods=["POST"])
def write_off_claim(rid):
    require_roles("BillingClerk")
    claim = services.get_claim(rid)
    if claim["status"] != "DENIED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, 409, "Claim is not DENIED")
    claim["status"] = "VOID"
    services.touch(claim)
    consult = db.store["consult_requests"][claim["consult_id"]]
    consult["billing_status"] = "VOID"
    services.touch(consult)
    return ok(serialize("billing_claim", claim), 200)


# --- compensation ledger -----------------------------------------------------------

@bp.route("/econsult/compensation-entries", methods=["GET"])
def list_entries():
    require_roles(*LEDGER_ROLES)
    records = list(db.store["compensation_entries"].values())
    for param, field in (
        ("membership_id", "membership_id"),
        ("consult_id", "consult_id"),
        ("posture", "posture"),
    ):
        value = request.args.get(param)
        if value is not None:
            records = [e for e in records if e[field] == value]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("compensation_entry", page), total, limit, offset)


@bp.route("/econsult/compensation-entries/<rid>", methods=["GET"])
def get_entry(rid):
    require_roles(*LEDGER_ROLES)
    return ok(serialize("compensation_entry", services.get_entry(rid)), 200)
