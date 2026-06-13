"""CIP/KYC application logic: scoring, cip_status derivation, account opening.

PRD §3.1 (onboarding), §3.2 (KYC scoring), §3.3 (adjudication).
"""
import math
from db import db, clock_date_iso, parse_date
from models import stamp_new, touch

# KYC scoring constants (PRD §3.2 / SCAFFOLD kyc_risk_scoring).
SANCTIONED_LAST4 = {"6666", "9999"}
NON_US_WEIGHT = 40
UNDERAGE_WEIGHT = 60
SANCTIONS_WEIGHT = 50
PRIOR_REJECTION_WEIGHT = 10
PRIOR_REJECTION_CAP = 3
RISK_CEILING = 100
KYC_APPROVAL_GATE = 70


def compute_kyc_risk(customer):
    """Weighted KYC risk score 0..100 at submission time (PRD §3.2)."""
    score = 0

    if customer.get("country_of_residence", "US") != "US":
        score += NON_US_WEIGHT

    # Age in whole years: (submit_date - dob).days / 365.25, floored.
    dob = parse_date(customer["date_of_birth"])
    submit_date = db.clock_date()
    age_days = (submit_date - dob).days
    age_years = math.floor(age_days / 365.25)
    if age_years < 18:
        score += UNDERAGE_WEIGHT

    if customer.get("tax_id_last4") in SANCTIONED_LAST4:
        score += SANCTIONS_WEIGHT

    prior_rejections = sum(
        1 for a in db.applications.values()
        if a["customer_id"] == customer["id"] and a["status"] == "REJECTED"
    )
    score += min(prior_rejections, PRIOR_REJECTION_CAP) * PRIOR_REJECTION_WEIGHT

    return min(score, RISK_CEILING)


def recompute_cip_status(customer_id):
    """Derive cip_status from the latest adjudicated application (PRD §3.1).

    Latest = the APPROVED/REJECTED application with the greatest created_at.
    """
    adjudicated = [
        a for a in db.applications.values()
        if a["customer_id"] == customer_id and a["status"] in ("APPROVED", "REJECTED")
    ]
    customer = db.customers.get(customer_id)
    if customer is None:
        return
    if not adjudicated:
        customer["cip_status"] = "UNVERIFIED"
        return
    latest = max(adjudicated, key=lambda a: (a["created_at"], a["_seq"]))
    customer["cip_status"] = "VERIFIED" if latest["status"] == "APPROVED" else "REJECTED"


def open_account(application):
    """Create the Account + PRIMARY AccountOwner on approval (PRD §3.3)."""
    account = {
        "product_type": application["product_type"],
        "origin_application_id": application["id"],
        "apy_tier_code": application["requested_apy_tier_code"],
        "status": "ACTIVE",
        "courtesy_pay_opted_in": False,
        "courtesy_pay_limit_cents": 50000,
        "accrued_interest_cents": 0,
        "last_activity_date": clock_date_iso(),
        "dormancy_threshold_days": 365,
        "escheat_threshold_days": 1095,
    }
    stamp_new(account)
    db.accounts[account["id"]] = account

    owner = {
        "account_id": account["id"],
        "customer_id": application["customer_id"],
        "ownership_role": "PRIMARY",
        "is_active": True,
    }
    stamp_new(owner)
    db.account_owners[owner["id"]] = owner

    return account
