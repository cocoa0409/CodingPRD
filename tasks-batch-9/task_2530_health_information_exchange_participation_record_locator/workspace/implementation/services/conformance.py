"""Conformance test evaluation (PRD 3.2)."""
from decimal import Decimal

from services.precision import out, rhu4

CONFORMANCE_PASS_RATE_FLOOR = Decimal("0.9500")
CRITICAL_FAILURE_CATEGORIES = ("SECURITY", "PATIENT_ID_INTEGRITY")
CONSECUTIVE_FAILURE_LIMIT = 3
REQUIRED_CERTIFICATION_PROFILES = (
    "ADT_PUBLISHER",
    "DOCUMENT_SOURCE",
    "QUERY_RESPONDER",
)
PROFILES = (
    "QUERY_RESPONDER",
    "ADT_PUBLISHER",
    "DOCUMENT_SOURCE",
    "ADT_SUBSCRIBER",
    "PUBLIC_HEALTH_CONDUIT",
)
FAILURE_CATEGORIES = (
    "SECURITY",
    "PATIENT_ID_INTEGRITY",
    "VOCABULARY",
    "TRANSPORT",
    "PAYLOAD_STRUCTURE",
)


def evaluate(assertions_total, assertions_passed, failure_categories):
    pass_rate = rhu4(Decimal(assertions_passed) / Decimal(assertions_total))
    critical = any(c in CRITICAL_FAILURE_CATEGORIES for c in (failure_categories or []))
    passed = pass_rate >= CONFORMANCE_PASS_RATE_FLOOR and not critical
    return out(pass_rate), critical, "PASSED" if passed else "FAILED"


def profiles_complete(passed_profiles):
    have = set(passed_profiles or [])
    return all(p in have for p in REQUIRED_CERTIFICATION_PROFILES)
