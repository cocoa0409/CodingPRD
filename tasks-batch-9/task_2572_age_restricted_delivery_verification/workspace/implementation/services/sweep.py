"""The epoch sweep triggered by POST /_clock/set_current_utc (PRD 2.5).

Three fixed steps, in this order:
  1. expire VALID identity checks, then re-derive each affected customer
  2. expire ACTIVE certifications, then re-derive each affected courier's gates
  3. rewrite both risk variants on every partner, then derive posture
"""
from db import db, sort_key, touch
from services.parties import (
    recompute_partner_scores,
    rederive_courier_gates,
    rederive_latest_identity_result,
    rederive_posture,
)
from util import parse_dt


def run_sweep():
    clock = db.clock

    # --- step 1: identity checks -----------------------------------------
    expired_checks = []
    for check in sorted(db.identity_checks.values(), key=sort_key):
        if check["status"] != "VALID":
            continue
        expires_at = parse_dt(check["expires_at"])
        if expires_at is not None and expires_at <= clock:
            check["status"] = "EXPIRED"
            touch(check)
            expired_checks.append(check)
    affected_customers = []
    seen = set()
    for check in expired_checks:
        if check["customer_id"] in seen:
            continue
        seen.add(check["customer_id"])
        customer = db.customers.get(check["customer_id"])
        if customer is not None:
            affected_customers.append(customer)
    for customer in affected_customers:
        rederive_latest_identity_result(customer)

    # --- step 2: courier certifications ----------------------------------
    expired_certifications = []
    for certification in sorted(db.certifications.values(), key=sort_key):
        if certification["state"] != "ACTIVE":
            continue
        expires_at = parse_dt(certification["expires_at"])
        if expires_at is not None and expires_at <= clock:
            certification["state"] = "EXPIRED"
            touch(certification)
            expired_certifications.append(certification)
    seen = set()
    for certification in expired_certifications:
        if certification["courier_id"] in seen:
            continue
        seen.add(certification["courier_id"])
        courier = db.couriers.get(certification["courier_id"])
        if courier is not None:
            rederive_courier_gates(courier)

    # --- step 3: partner re-scoring and reposturing ----------------------
    repostured = 0
    for partner in sorted(db.partners.values(), key=sort_key):
        recompute_partner_scores(partner)
        if rederive_posture(partner):
            repostured += 1

    return {
        "expired_identity_check_count": len(expired_checks),
        "expired_certification_count": len(expired_certifications),
        "repostured_partner_count": repostured,
    }
