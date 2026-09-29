"""Domain vocabulary for the renewable-diesel plant API under test.

Plain string constants (not Enum) so they compare directly against JSON values.
"""

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_PLANT_OPERATOR = "PlantOperator"
ROLE_FEEDSTOCK_TRADER = "FeedstockTrader"
ROLE_QUALITY_ANALYST = "QualityAnalyst"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_INDEPENDENT_VERIFIER = "IndependentVerifier"
ROLE_SUPPLIER = "Supplier"

ALL_ROLES = [
    ROLE_PLANT_OPERATOR,
    ROLE_FEEDSTOCK_TRADER,
    ROLE_QUALITY_ANALYST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INDEPENDENT_VERIFIER,
    ROLE_SUPPLIER,
]

# ---------------------------------------------------------------------------
# Feedstock
# ---------------------------------------------------------------------------
FEEDSTOCK_UCO = "UCO"
FEEDSTOCK_TALLOW = "TALLOW"
FEEDSTOCK_DCO = "DCO"
FEEDSTOCK_SOYBEAN_OIL = "SOYBEAN_OIL"
FEEDSTOCK_CANOLA_OIL = "CANOLA_OIL"

FEEDSTOCK_TYPES = [
    FEEDSTOCK_UCO,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_DCO,
    FEEDSTOCK_SOYBEAN_OIL,
    FEEDSTOCK_CANOLA_OIL,
]
WASTE_FEEDSTOCK_TYPES = [FEEDSTOCK_UCO, FEEDSTOCK_TALLOW, FEEDSTOCK_DCO]

# ---------------------------------------------------------------------------
# Supplier due-diligence status
# ---------------------------------------------------------------------------
DD_PENDING = "PENDING"
DD_VERIFIED = "VERIFIED"
DD_SUSPENDED = "SUSPENDED"

# ---------------------------------------------------------------------------
# Traceability documents
# ---------------------------------------------------------------------------
DOC_ORIGIN_ATTESTATION = "ORIGIN_ATTESTATION"
DOC_CHAIN_OF_CUSTODY = "CHAIN_OF_CUSTODY"
DOC_MASS_BALANCE_STATEMENT = "MASS_BALANCE_STATEMENT"
DOC_THIRD_PARTY_AUDIT = "THIRD_PARTY_AUDIT"

DOC_TYPES = [
    DOC_ORIGIN_ATTESTATION,
    DOC_CHAIN_OF_CUSTODY,
    DOC_MASS_BALANCE_STATEMENT,
    DOC_THIRD_PARTY_AUDIT,
]

# ---------------------------------------------------------------------------
# Feedstock lot status
# ---------------------------------------------------------------------------
LOT_RECEIVED = "RECEIVED"
LOT_TESTED = "TESTED"
LOT_PRETREAT_REQUIRED = "PRETREAT_REQUIRED"
LOT_PRETREATED = "PRETREATED"
LOT_ACCEPTED = "ACCEPTED"
LOT_REJECTED = "REJECTED"
LOT_CHARGED = "CHARGED"
LOT_QUARANTINED = "QUARANTINED"

# ---------------------------------------------------------------------------
# Pretreatment tiers / quality-test dispositions
# ---------------------------------------------------------------------------
TIER_NONE = "NONE"
TIER_LIGHT = "LIGHT"
TIER_HEAVY = "HEAVY"

DISPOSITION_PASS = "PASS"
DISPOSITION_PRETREAT = "PRETREAT"
DISPOSITION_REJECT = "REJECT"

# ---------------------------------------------------------------------------
# Hydrotreating unit status
# ---------------------------------------------------------------------------
UNIT_IDLE = "IDLE"
UNIT_RUNNING = "RUNNING"
UNIT_DOWN_TURNAROUND = "DOWN_TURNAROUND"

# ---------------------------------------------------------------------------
# Catalyst charge status
# ---------------------------------------------------------------------------
CHARGE_ACTIVE = "ACTIVE"
CHARGE_DERATED = "DERATED"
CHARGE_SPENT = "SPENT"
CHARGE_REMOVED = "REMOVED"

# ---------------------------------------------------------------------------
# Turnaround windows
# ---------------------------------------------------------------------------
SCOPE_CATALYST_CHANGE = "CATALYST_CHANGE"
SCOPE_INSPECTION = "INSPECTION"
SCOPE_MAJOR = "MAJOR"

WINDOW_PLANNED = "PLANNED"
WINDOW_APPROVED = "APPROVED"
WINDOW_IN_PROGRESS = "IN_PROGRESS"
WINDOW_COMPLETED = "COMPLETED"
WINDOW_CANCELLED = "CANCELLED"

# ---------------------------------------------------------------------------
# Hydrogen
# ---------------------------------------------------------------------------
CONTRACT_ACTIVE = "ACTIVE"
CONTRACT_CLOSED = "CLOSED"

NOMINATION_CONFIRMED = "CONFIRMED"
NOMINATION_CANCELLED = "CANCELLED"

# ---------------------------------------------------------------------------
# Processing runs (campaigns)
# ---------------------------------------------------------------------------
RUN_PLANNED = "PLANNED"
RUN_HYDROGEN_SECURED = "HYDROGEN_SECURED"
RUN_RUNNING = "RUNNING"
RUN_COMPLETED = "COMPLETED"
RUN_RECONCILED = "RECONCILED"
RUN_ABORTED = "ABORTED"

# ---------------------------------------------------------------------------
# Feedstock allocations
# ---------------------------------------------------------------------------
ALLOC_RESERVED = "RESERVED"
ALLOC_CONSUMED = "CONSUMED"
ALLOC_RELEASED = "RELEASED"

RELEASE_MANUAL = "MANUAL"
RELEASE_SUPPLIER_SUSPENDED = "SUPPLIER_SUSPENDED"
RELEASE_RUN_ABORTED = "RUN_ABORTED"

# ---------------------------------------------------------------------------
# Product batches
# ---------------------------------------------------------------------------
PRODUCT_RENEWABLE_DIESEL = "RENEWABLE_DIESEL"
PRODUCT_SAF = "SAF"

CERT_UNCERTIFIED = "UNCERTIFIED"
CERT_PENDING = "CERT_PENDING"
CERT_CERTIFIED = "CERTIFIED"
CERT_REJECTED = "CERT_REJECTED"

DIST_IN_TANK = "IN_TANK"
DIST_RESERVED = "RESERVED"
DIST_SHIPPED = "SHIPPED"

ANNEX_A2_HEFA = "A2_HEFA"
ANNEX_A5_HC_HEFA = "A5_HC_HEFA"

# ---------------------------------------------------------------------------
# Pathway registrations
# ---------------------------------------------------------------------------
PROGRAM_RFS = "RFS"
PROGRAM_LCFS = "LCFS"

PATHWAY_DRAFT = "DRAFT"
PATHWAY_SUBMITTED = "SUBMITTED"
PATHWAY_UNDER_REVIEW = "UNDER_REVIEW"
PATHWAY_RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
PATHWAY_REGISTERED = "REGISTERED"
PATHWAY_DENIED = "DENIED"
PATHWAY_SUSPENDED = "SUSPENDED"

REVIEW_REGISTER = "REGISTER"
REVIEW_RETURN = "RETURN"
REVIEW_DENY = "DENY"

# ---------------------------------------------------------------------------
# Credit blocks
# ---------------------------------------------------------------------------
BLOCK_DRAFT = "DRAFT"
BLOCK_INTERNAL_SIGNED_OFF = "INTERNAL_SIGNED_OFF"
BLOCK_SUBMITTED_FOR_VERIFICATION = "SUBMITTED_FOR_VERIFICATION"
BLOCK_VERIFIED = "VERIFIED"
BLOCK_ADJUSTED = "ADJUSTED"
BLOCK_VERIFICATION_REJECTED = "VERIFICATION_REJECTED"
BLOCK_RETIRED = "RETIRED"
BLOCK_BLOCKED = "BLOCKED"

VERIFICATION_VERIFY = "VERIFY"
VERIFICATION_REJECT = "REJECT"

OUTCOME_NONE = "NONE"
OUTCOME_VERIFIED = "VERIFIED"
OUTCOME_ADJUSTED = "ADJUSTED"
OUTCOME_REJECTED = "REJECTED"

# ---------------------------------------------------------------------------
# Hedge positions
# ---------------------------------------------------------------------------
INSTRUMENT_FEEDSTOCK_SWAP = "FEEDSTOCK_SWAP"
INSTRUMENT_RIN_FORWARD = "RIN_FORWARD"
INSTRUMENT_LCFS_FORWARD = "LCFS_FORWARD"

TIER_T1 = "T1"
TIER_T2 = "T2"
TIER_T3 = "T3"

HEDGE_OPEN = "OPEN"
HEDGE_UNWOUND = "UNWOUND"

# ---------------------------------------------------------------------------
# Certification / batch decisions
# ---------------------------------------------------------------------------
CERT_DECISION_CERTIFY = "CERTIFY"
CERT_DECISION_REJECT = "REJECT"
