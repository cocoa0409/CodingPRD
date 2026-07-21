"""Existence lookups (SCAFFOLD validations priority 4) and FK-chain traversal helpers."""
from db import db
from errors import err


def get_landlord(landlord_id):
    e = db.landlords.get(landlord_id)
    if not e:
        raise err("ERR_LANDLORD_NOT_FOUND", "Landlord not found.")
    return e


def get_property(property_id):
    e = db.properties.get(property_id)
    if not e:
        raise err("ERR_PROPERTY_NOT_FOUND", "Property not found.")
    return e


def get_renter(renter_id):
    e = db.renters.get(renter_id)
    if not e:
        raise err("ERR_RENTER_NOT_FOUND", "Renter not found.")
    return e


def get_enrollment(enrollment_id):
    e = db.renter_enrollments.get(enrollment_id)
    if not e:
        raise err("ERR_RENTER_ENROLLMENT_NOT_FOUND", "Renter enrollment not found.")
    return e


def get_policy(policy_id):
    e = db.policies.get(policy_id)
    if not e:
        raise err("ERR_POLICY_NOT_FOUND", "Policy not found.")
    return e


def get_invoice(invoice_id):
    e = db.invoices.get(invoice_id)
    if not e:
        raise err("ERR_INVOICE_NOT_FOUND", "Invoice not found.")
    return e


def get_claim(claim_id):
    e = db.claims.get(claim_id)
    if not e:
        raise err("ERR_CLAIM_NOT_FOUND", "Claim not found.")
    return e


def get_payout(payout_id):
    e = db.payouts.get(payout_id)
    if not e:
        raise err("ERR_PAYOUT_NOT_FOUND", "Payout not found.")
    return e


def get_subrogation_case(case_id):
    e = db.subrogation_cases.get(case_id)
    if not e:
        raise err("ERR_SUBROGATION_CASE_NOT_FOUND", "Subrogation case not found.")
    return e


def get_recovery_payment(payment_id):
    e = db.recovery_payments.get(payment_id)
    if not e:
        raise err("ERR_RECOVERY_PAYMENT_NOT_FOUND", "Recovery payment not found.")
    return e


# --- FK-chain traversal (for ownership checks + cascades) ---

def enrollment_for_policy(policy):
    return db.renter_enrollments[policy["renter_enrollment_id"]]


def property_for_policy(policy):
    enrollment = enrollment_for_policy(policy)
    return db.properties[enrollment["property_id"]]


def landlord_id_for_policy(policy):
    return property_for_policy(policy)["landlord_id"]


def renter_id_for_policy(policy):
    return enrollment_for_policy(policy)["renter_id"]


def policy_for_claim(claim):
    return db.policies[claim["policy_id"]]


def property_for_claim(claim):
    return property_for_policy(policy_for_claim(claim))


def landlord_id_for_claim(claim):
    return property_for_claim(claim)["landlord_id"]


def renter_id_for_claim(claim):
    return renter_id_for_policy(policy_for_claim(claim))


def claim_for_payout(payout):
    return db.claims[payout["claim_id"]]


def claim_for_subrogation_case(case):
    return db.claims[case["claim_id"]]


def subrogation_case_for_recovery_payment(payment):
    return db.subrogation_cases[payment["subrogation_case_id"]]


# --- Reverse-FK collections ---

def properties_for_landlord(landlord_id):
    return [p for p in db.properties.values() if p["landlord_id"] == landlord_id]


def enrollments_for_property(property_id):
    return [e for e in db.renter_enrollments.values() if e["property_id"] == property_id]


def enrollments_for_renter(renter_id):
    return [e for e in db.renter_enrollments.values() if e["renter_id"] == renter_id]


def policy_for_enrollment(enrollment_id):
    for p in db.policies.values():
        if p["renter_enrollment_id"] == enrollment_id:
            return p
    return None


def invoices_for_policy(policy_id):
    return [i for i in db.invoices.values() if i["policy_id"] == policy_id]


def claims_for_policy(policy_id):
    return [c for c in db.claims.values() if c["policy_id"] == policy_id]


def payouts_for_claim(claim_id):
    return [p for p in db.payouts.values() if p["claim_id"] == claim_id]


def payouts_for_policy(policy_id):
    claim_ids = {c["id"] for c in claims_for_policy(policy_id)}
    return [p for p in db.payouts.values() if p["claim_id"] in claim_ids]


def subrogation_cases_for_claim(claim_id):
    return [s for s in db.subrogation_cases.values() if s["claim_id"] == claim_id]


def recovery_payments_for_case(case_id):
    return [r for r in db.recovery_payments.values() if r["subrogation_case_id"] == case_id]


def claims_for_property(property_id):
    policy_ids = {
        p["id"] for p in db.policies.values()
        if enrollment_for_policy(p)["property_id"] == property_id
    }
    return [c for c in db.claims.values() if c["policy_id"] in policy_ids]


def payouts_for_property(property_id):
    claim_ids = {c["id"] for c in claims_for_property(property_id)}
    return [p for p in db.payouts.values() if p["claim_id"] in claim_ids]


def policies_for_property(property_id):
    enrollment_ids = {e["id"] for e in enrollments_for_property(property_id)}
    return [p for p in db.policies.values() if p["renter_enrollment_id"] in enrollment_ids]
