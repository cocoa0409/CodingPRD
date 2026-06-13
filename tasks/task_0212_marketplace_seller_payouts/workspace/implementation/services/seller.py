"""Seller onboarding, posture transitions, account_status recompute.

PRD §3.1 (onboarding), §3.2 (suspend/reinstate/close), §3.10 (risk).
"""
from common import (
    err,
    require_fields,
    require_str,
    require_enum,
)
from errors import ERR_INVALID_REQUEST
from db import db
from services.entity import stamp_create, touch
from services.ledger import reconcile_balances, recompute_risk, recompute_ytd

COUNTRY_CODES = {"US", "CA", "GB", "DE", "AU"}
TAX_CLASSES = {"INDIVIDUAL", "SOLE_PROP", "C_CORP", "S_CORP", "LLC", "PARTNERSHIP"}


def create_seller(body):
    require_fields(body, ["legal_name", "email", "country_code",
                          "tax_classification", "tin_last4"])
    legal_name = require_str(body["legal_name"], "legal_name")
    email = require_str(body["email"], "email")
    country_code = body["country_code"]
    tax_classification = body["tax_classification"]
    tin_last4 = body["tin_last4"]

    require_enum(country_code, COUNTRY_CODES, "country_code")
    require_enum(tax_classification, TAX_CLASSES, "tax_classification")
    if not (isinstance(tin_last4, str) and tin_last4.isdigit() and len(tin_last4) == 4):
        raise err(ERR_INVALID_REQUEST, "tin_last4 must be exactly 4 digits.")

    # email unique across sellers (PRD §3.1)
    for s in db.sellers.values():
        if s["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email must be unique across sellers.")

    seller = {
        "legal_name": legal_name,
        "email": email,
        "country_code": country_code,
        "tax_classification": tax_classification,
        "tin_last4": tin_last4,
        "kyc_status": "PENDING",
        "w9_status": "NOT_SUBMITTED",
        "account_status": "ONBOARDING",
        "risk_tier": "STANDARD",
        "seller_risk_score": 0,
        "available_balance_cents": 0,
        "pending_balance_cents": 0,
        "reserve_held_cents": 0,
        "ytd_gross_cents": 0,
        "ytd_transaction_count": 0,
        "kyc_reviewer_id": None,
    }
    stamp_create(seller)
    db.sellers[seller["id"]] = seller
    return seller


def has_verified_method(seller_id):
    return any(
        m["seller_id"] == seller_id and m["verification_status"] == "VERIFIED"
        for m in db.payout_methods.values()
    )


def recompute_account_status(seller):
    """ONBOARDING until all three gates met (kyc APPROVED, w9 APPROVED, a
    VERIFIED payout method), then ACTIVE.

    Only transitions ONBOARDING->ACTIVE here. SUSPENDED and CLOSED are explicit
    operator states and are NOT auto-flipped by this recompute (PRD §3.1).

    Returns True if the seller was just activated (ONBOARDING->ACTIVE)."""
    if seller["account_status"] != "ONBOARDING":
        return False
    if (seller["kyc_status"] == "APPROVED"
            and seller["w9_status"] == "APPROVED"
            and has_verified_method(seller["id"])):
        seller["account_status"] = "ACTIVE"
        return True
    return False


def open_initial_reserve(seller):
    """Open the seller's initial reserve on activation, pinning
    reserve_pct_applied from current risk_tier (PRD §3.1).

    No funds are withheld yet (held_amount_cents starts 0); the reserve is the
    container that payout release later withholds into."""
    from services.reserve import reserve_pct_for_tier
    pct = reserve_pct_for_tier(seller)
    reserve = {
        "seller_id": seller["id"],
        "reserve_status": "OPEN",
        "held_amount_cents": 0,
        "reserve_pct_applied": pct,
        "release_due_at": None,
        "released_at": None,
    }
    stamp_create(reserve)
    db.reserves[reserve["id"]] = reserve
    reconcile_balances(seller)


def refresh_seller_derived(seller):
    """Recompute all derived balances / risk / ytd for a seller."""
    recompute_risk(seller)
    reconcile_balances(seller)
    recompute_ytd(seller)


def serialize_seller(seller):
    """Refresh derived fields then return the full record (read path)."""
    refresh_seller_derived(seller)
    return seller
