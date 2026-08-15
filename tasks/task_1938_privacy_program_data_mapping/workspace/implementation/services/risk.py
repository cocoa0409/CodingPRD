"""Calculation rules (scaffold table 3 / PRD sections 2.6, 2.10, 3.x)."""
from decimal import Decimal

import db
from utils import round_half_up_int

# --- Enum vocabularies -------------------------------------------------------
DATA_CATEGORIES = (
    "BASIC_CONTACT", "IDENTIFIER", "FINANCIAL", "HEALTH",
    "BIOMETRIC", "PRECISE_LOCATION", "MINOR_DATA",
)
CLASSIFICATIONS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
DISPOSAL_ACTIONS = ("ANONYMIZE", "DELETE", "ARCHIVE")
REGIONS = ("US", "EU", "UK", "BR", "APAC")
NOTICE_SCOPES = ("WEBSITE", "MOBILE_APP", "EMPLOYEE", "LOYALTY_PROGRAM")
CLAUSE_CODES = ("DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT",
                "SUBPROCESSOR_CONSENT", "AUDIT_RIGHTS")
PURPOSE_TYPES = ("MARKETING", "ANALYTICS", "SERVICE_DELIVERY", "EMPLOYMENT",
                 "LEGAL_COMPLIANCE", "RESEARCH")
LEGAL_BASES = ("CONSENT", "CONTRACT", "LEGAL_OBLIGATION", "LEGITIMATE_INTEREST",
               "VITAL_INTEREST", "PUBLIC_TASK")
REQUEST_TYPES = ("ACCESS", "DELETION", "CORRECTION", "PORTABILITY", "OPT_OUT")
MECHANISMS = ("SCC_2021", "ADEQUACY", "BCR", "DEROGATION")

# --- Risk score constants ----------------------------------------------------
CATEGORY_WEIGHT = {
    "BASIC_CONTACT": 50, "IDENTIFIER": 100, "FINANCIAL": 200, "HEALTH": 300,
    "BIOMETRIC": 400, "PRECISE_LOCATION": 250, "MINOR_DATA": 350,
}
CLASSIFICATION_MULTIPLIER = {
    "PUBLIC": Decimal("0.5"), "INTERNAL": Decimal("1.0"),
    "CONFIDENTIAL": Decimal("1.5"), "RESTRICTED": Decimal("2.0"),
}
VENDOR_EXPOSURE = {"LOW": 0, "STANDARD": 75, "HIGH": 150}
PER_EXTRA_ELEMENT = 25
CONSENT_LEGAL_BASIS_ADJUSTMENT = 50
RISK_CAP = 1000
PIA_RISK_THRESHOLD = 500

DEFAULT_DEADLINE_DAYS = 45
DEFAULT_EXTENSION_DAYS = 30

REQUIRED_BY_TIER = {
    "LOW": ["DPA"],
    "STANDARD": ["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT"],
    "HIGH": ["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT",
             "SUBPROCESSOR_CONSENT", "AUDIT_RIGHTS"],
}


def element_value(element):
    return (Decimal(CATEGORY_WEIGHT[element["category"]])
            * CLASSIFICATION_MULTIPLIER[element["classification"]])


def _linked_elements(activity):
    return [db.data_elements[i] for i in activity["data_element_ids"]
            if i in db.data_elements]


def _vendor_exposure(activity):
    vid = activity.get("vendor_id")
    if not vid:
        return 0
    vendor = db.vendors.get(vid)
    if vendor is None:
        return 0
    return VENDOR_EXPOSURE[vendor["risk_tier"]]


def screening_score(activity):
    """Screening variant: round_half_up(max(element_value)) + 25*(n-1)
    + vendor exposure, capped at 1000. Governs pia_required."""
    elements = _linked_elements(activity)
    values = [element_value(e) for e in elements]
    max_value = max(values) if values else Decimal(0)
    base = round_half_up_int(max_value)
    extra = PER_EXTRA_ELEMENT * max(0, len(elements) - 1)
    return min(RISK_CAP, base + extra + _vendor_exposure(activity))


def comprehensive_score(activity):
    """Comprehensive variant: round_half_up(sum(element_value)) + vendor
    exposure + consent adjustment, capped at 1000. Written only to
    PrivacyImpactAssessment.final_score at approval."""
    elements = _linked_elements(activity)
    total = Decimal(0)
    for e in elements:
        total += element_value(e)
    base = round_half_up_int(total)
    has_documented_consent = any(
        p["activity_id"] == activity["id"]
        and p["status"] == "DOCUMENTED"
        and p["legal_basis"] == "CONSENT"
        for p in db.purposes.values()
    )
    score = base + _vendor_exposure(activity)
    if has_documented_consent:
        score += CONSENT_LEGAL_BASIS_ADJUSTMENT
    return min(RISK_CAP, score)


def vendor_risk_tier(categories):
    cats = set(categories)
    if cats & {"HEALTH", "BIOMETRIC", "MINOR_DATA"}:
        return "HIGH"
    if cats & {"FINANCIAL", "PRECISE_LOCATION", "IDENTIFIER"}:
        return "STANDARD"
    return "LOW"


def clause_gap(risk_tier, provided_clauses):
    required = list(REQUIRED_BY_TIER[risk_tier])
    missing = sorted(set(required) - set(provided_clauses))
    return required, missing
