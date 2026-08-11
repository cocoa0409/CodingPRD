import uuid

from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_EMAIL_TAKEN, ERR_REFERRAL_CODE_INVALID, ERR_CUSTOMER_NOT_FOUND,
    ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS, ERR_CUSTOMER_NOT_SUSPENDED,
    ERR_SUBSCRIPTIONS_STILL_OPEN, ERR_FORBIDDEN_ROLE, ERR_OWNERSHIP_MISMATCH,
)
from middleware import get_body, authenticate, check_ownership
from response import ok
from serializers import ser_customer
from services import PROVISIONAL_REFERRAL_CENTS
from util import req_str, req_enum, fmt_dt3

bp = Blueprint("customers", __name__)

CLIMATE_ZONES = {"COOL", "TRANSITION", "WARM"}


def _mint_referral_code():
    while True:
        code = "REF-" + uuid.uuid4().hex[:6].upper()
        if not any(c.referral_code == code for c in store.customers.values()):
            return code


@bp.route("/api/customers/register", methods=["POST"])
def register():
    # The one unauthenticated endpoint: no header requirement (PRD 2.1).
    body = get_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    climate_zone = req_enum(body, "climate_zone", CLIMATE_ZONES)
    referred_by_code = body.get("referred_by_code")
    if referred_by_code is not None and not isinstance(referred_by_code, str):
        raise_err(ERR_REFERRAL_CODE_INVALID, "referred_by_code must be a string")

    # If a role header is presented, only Anonymous may register.
    role = request.headers.get("X-User-Role")
    if role is not None and role.strip() != "Anonymous":
        raise_err(ERR_FORBIDDEN_ROLE, "Only Anonymous may register a customer")

    if any(c.email.lower() == email.lower() for c in store.customers.values()):
        raise_err(ERR_EMAIL_TAKEN, "Email already registered")

    referrer = None
    if referred_by_code is not None:
        for c in store.customers.values():
            if c.referral_code == referred_by_code:
                referrer = c
                break
        if referrer is None:
            raise_err(ERR_REFERRAL_CODE_INVALID, "referred_by_code does not resolve to any customer")

    ts = now()
    cust = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        email=email, full_name=full_name, climate_zone=climate_zone,
        referral_code=_mint_referral_code(), credit_balance_cents=0, status="ACTIVE",
    )
    cust.raw["created_at"] = fmt_dt3(ts)
    cust.raw["updated_at"] = fmt_dt3(ts)
    store.customers[cust.id] = cust

    if referrer is not None:
        ref = Rec(
            id=new_id(), created_at=now(), updated_at=now(), version=1, seq=next_seq(),
            referrer_customer_id=referrer.id,
            referee_customer_id=cust.id,
            referral_code_used=referred_by_code,
            status="PENDING",
            provisional_credit_cents=PROVISIONAL_REFERRAL_CENTS,
            qualified_credit_cents=None,
            referee_first_invoice_id=None,
        )
        ref.raw["created_at"] = fmt_dt3(ref.created_at)
        ref.raw["updated_at"] = fmt_dt3(ref.updated_at)
        store.referrals[ref.id] = ref

    return ok(ser_customer(cust), 201)


@bp.route("/api/customers/<cid>", methods=["GET"])
def get_customer(cid):
    uid, role = authenticate(["Customer", "Agronomist", "PlatformAdmin"])
    if role == "Customer" and uid != cid:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Customers may only read their own record")
    cust = store.customers.get(cid)
    if cust is None:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    return ok(ser_customer(cust))


@bp.route("/api/customers/<cid>/status", methods=["POST"])
def set_status(cid):
    body = get_body()
    to_status = req_enum(body, "to_status", {"ACTIVE", "SUSPENDED", "CHURNED"})
    authenticate(["PlatformAdmin"])
    cust = store.customers.get(cid)
    if cust is None:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")

    if to_status == "SUSPENDED":
        if cust.status != "ACTIVE":
            raise_err(ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS, "Suspend requires customer ACTIVE")
        cust.status = "SUSPENDED"
    elif to_status == "ACTIVE":
        if cust.status != "SUSPENDED":
            raise_err(ERR_CUSTOMER_NOT_SUSPENDED, "Reinstate requires customer SUSPENDED")
        cust.status = "ACTIVE"
    else:  # CHURNED
        if cust.status != "ACTIVE":
            raise_err(ERR_CUSTOMER_NOT_ACTIVE_FOR_STATUS, "Churn requires customer ACTIVE")
        open_subs = [
            s for s in store.subscriptions.values()
            if s.customer_id == cid and s.status != "CANCELLED"
        ]
        if open_subs:
            raise_err(ERR_SUBSCRIPTIONS_STILL_OPEN, "Churn requires all subscriptions CANCELLED")
        cust.status = "CHURNED"
    touch(cust)
    return ok(ser_customer(cust))
