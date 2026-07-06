"""Business calculation rules."""
from helpers import round_half_up
import db

HAGUE_MEMBERS = ["FR", "DE", "JP", "MX", "IT", "ES", "GB", "NL"]
APOSTILLE_FEE_CENTS = 2000
CERTIFICATION_FEE_CENTS = 4000
MAX_CONCURRENT_SESSIONS = 3

STANDARD_WEIGHTS = {"kba": 0.5, "credential": 0.3, "biometric": 0.2, "threshold": 70}
ENHANCED_WEIGHTS = {"kba": 0.3, "credential": 0.4, "biometric": 0.3, "threshold": 75}


def request_fee(fs, ron, stamps, miles):
    """Compute a request fee in integer cents. miles already 0 if ron."""
    base = (stamps * fs["per_stamp_cents"]
            + fs["travel_base_cents"]
            + miles * fs["travel_per_mile_cents"]
            + (fs["ron_surcharge_cents"] if ron else 0))
    total = min(fs["state_cap_cents"], base)
    return total


def credential_trust(enhanced, kba, credential, biometric):
    """Return (variant, trust_score_float, outcome)."""
    if enhanced:
        score = 0.3 * kba + 0.4 * credential + 0.3 * biometric
        threshold = 75
        variant = "ENHANCED"
    else:
        score = 0.5 * kba + 0.3 * credential + 0.2 * biometric
        threshold = 70
        variant = "STANDARD"
    trust_score = round_half_up(score, 2)
    outcome = "PASS" if trust_score >= threshold else "FAIL"
    # Return trust_score as float-equivalent number (2 dp).
    return variant, float(trust_score), outcome


def loan_package_fee(docs, discount_pct):
    """Round each doc's discounted fee to whole cents, then sum."""
    total = 0
    for doc in docs:
        discounted = doc["signing_fee_cents"] * (1 - discount_pct)
        per_doc = int(round_half_up(discounted, 0))
        total += per_doc
    return total


def apostille_fee(destination_country):
    """Return (authentication_type, fee_cents)."""
    hague = destination_country in HAGUE_MEMBERS
    if hague:
        return "APOSTILLE", APOSTILLE_FEE_CENTS
    return "CERTIFICATION", CERTIFICATION_FEE_CENTS


def notary_active_session_count(notary_id):
    n = 0
    for s in db.ron_sessions.values():
        if s["notary_id"] == notary_id and s["session_status"] in ("SCHEDULED", "LIVE"):
            n += 1
    return n
