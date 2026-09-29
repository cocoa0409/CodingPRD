"""Pinned literals shared by the whole suite: jurisdictions, clock instants and enums.

Nothing here is derived at run time. The statutory profiles below are the exact
rule rows the tests seed, so every expected fee, window length, payoff figure and
equity ceiling in the suite is traceable to one of them.
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------

#: A logical clock, readable as ``current_utc``, begins at this instant on a
#: fresh server and never advances on its own.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Instants the suite moves the clock to, spelled out rather than computed.
DAY_02 = "2026-08-02T00:00:00Z"
DAY_05 = "2026-08-05T00:00:00Z"
DAY_08 = "2026-08-08T00:00:00Z"
DAY_08_PLUS_ONE_SECOND = "2026-08-08T00:00:01Z"
DAY_09 = "2026-08-09T00:00:00Z"
DAY_12 = "2026-08-12T00:00:00Z"
DAY_12_1500 = "2026-08-12T15:00:00Z"
DAY_13_1500 = "2026-08-13T15:00:00Z"
DAY_14_1500 = "2026-08-14T15:00:00Z"
DAY_14_1600 = "2026-08-14T16:00:00Z"
DAY_14_2200 = "2026-08-14T22:00:00Z"
DAY_15 = "2026-08-15T00:00:00Z"
DAY_15_1500 = "2026-08-15T15:00:00Z"
DAY_17 = "2026-08-17T00:00:00Z"
DAY_18 = "2026-08-18T00:00:00Z"
DAY_18_1500 = "2026-08-18T15:00:00Z"
DAY_19_1500 = "2026-08-19T15:00:00Z"
DAY_22 = "2026-08-22T00:00:00Z"
SEPT_12 = "2026-09-12T00:00:00Z"
NOV_06 = "2026-11-06T00:00:00Z"
NOV_27 = "2026-11-27T00:00:00Z"
NOV_28 = "2026-11-28T00:00:00Z"
NOV_28_1500 = "2026-11-28T15:00:00Z"

# ---------------------------------------------------------------------------
# Statutory rule profiles
# ---------------------------------------------------------------------------

TX_RULE: Dict[str, Any] = {
    "state_code": "TX",
    "late_fee_grace_days": 3,
    "late_fee_pct": 0.10,
    "late_fee_max_cents": 1000,
    "reinstate_threshold_months": 2,
    "reinstate_days_short": 5,
    "reinstate_days_long": 15,
    "reinstatement_fee_cents": 500,
    "early_purchase_formula": "PCT_OF_REMAINING",
    "early_purchase_pct": 0.55,
    "rent_credit_pct": 0.50,
    "processing_fee_max_cents": 5000,
    "disclosure_requires_total_of_payments": True,
    "max_collection_contacts_per_week": 3,
    "quiet_hours_start_utc_hour": 20,
    "quiet_hours_end_utc_hour": 8,
    "repossession_paid_pct_limit": 0.60,
    "credit_inquiry_prohibited": True,
    "max_term_renewals": 78,
}

MN_RULE: Dict[str, Any] = {
    "state_code": "MN",
    "late_fee_grace_days": 5,
    "late_fee_pct": 0.05,
    "late_fee_max_cents": 600,
    "reinstate_threshold_months": 2,
    "reinstate_days_short": 7,
    "reinstate_days_long": 21,
    "reinstatement_fee_cents": 0,
    "early_purchase_formula": "CASH_PRICE_MINUS_CREDIT",
    "early_purchase_pct": 0.55,
    "rent_credit_pct": 0.55,
    "processing_fee_max_cents": 0,
    "disclosure_requires_total_of_payments": True,
    "max_collection_contacts_per_week": 2,
    "quiet_hours_start_utc_hour": 21,
    "quiet_hours_end_utc_hour": 9,
    "repossession_paid_pct_limit": 0.50,
    "credit_inquiry_prohibited": False,
    "max_term_renewals": 78,
}

#: Texas economics with a lower processing-fee cap, used to prove the fee cap is
#: read from the store's jurisdiction and not the customer's.
NV_RULE: Dict[str, Any] = dict(
    TX_RULE,
    state_code="NV",
    processing_fee_max_cents=4000,
    credit_inquiry_prohibited=False,
)

# ---------------------------------------------------------------------------
# Stores, units and crews
# ---------------------------------------------------------------------------

AUSTIN_MAIN = "Austin Main"
DULUTH_MAIN = "Duluth Main"
ST_PAUL_MAIN = "St Paul Main"
RENO_MAIN = "Reno Main"
TULSA_MAIN = "Tulsa Main"
DALLAS_NORTH = "Dallas North"

SOFA_MODEL = "SOFA-3S-GRY"
WASHER_MODEL = "WASH-TL-WHT"
LAMP_MODEL = "LAMP-SM-BRN"

#: The disclosed cash price of a brand-new example of the canonical sofa.
SOFA_CASH_PRICE_CENTS = 120000
#: The disclosed cash price of the canonical washer.
WASHER_CASH_PRICE_CENTS = 30000

TX_CREW_A = "TX Crew A"
TX_CREW_B = "TX Crew B"
TX_CREW_C = "TX Crew C"
MN_CREW_A = "MN Crew A"

# ---------------------------------------------------------------------------
# Canonical WEEKLY x 52 pricing on a NEW 120000-cent furniture unit under TX
# ---------------------------------------------------------------------------

W52_ADJUSTED_CASH_PRICE_CENTS = 120000
W52_RENEWAL_RATE_CENTS = 5077
W52_RENT_SUBTOTAL_CENTS = 264004
W52_PROCESSING_FEE_CENTS = 5000
W52_TOTAL_OF_PAYMENTS_CENTS = 269004
W52_MONTHLY_EQUIVALENT_CENTS = 22000
W52_COST_OF_RENTAL_CENTS = 149004

#: The same term priced under Nevada's 4000-cent processing-fee cap.
W52_NV_PROCESSING_FEE_CENTS = 4000
W52_NV_TOTAL_OF_PAYMENTS_CENTS = 268004
W52_NV_COST_OF_RENTAL_CENTS = 148004

#: MONTHLY x 12 on the 30000-cent washer under TX.
M12_RENEWAL_RATE_CENTS = 4875
M12_RENT_SUBTOTAL_CENTS = 58500
M12_PROCESSING_FEE_CENTS = 2925
M12_TOTAL_OF_PAYMENTS_CENTS = 61425

#: A late fee under TX on the canonical weekly rate: 10 percent of 5077, capped
#: at 1000 cents, rounded half up.
TX_LATE_FEE_CENTS = 508
TX_REINSTATEMENT_FEE_CENTS = 500

#: A late fee under MN on a WEEKLY x 24 term: 5 percent of 11000, capped at 600.
MN_LATE_FEE_CENTS = 550

# ---------------------------------------------------------------------------
# Identifiers that do not resolve
# ---------------------------------------------------------------------------

MISSING_UNIT_ID = "00000000-0000-4000-8000-000000000006"
MISSING_CUSTOMER_ID = "00000000-0000-4000-8000-000000000007"
MISSING_STATE_RULE_ID = "00000000-0000-4000-8000-000000000008"
MISSING_AGREEMENT_ID = "00000000-0000-4000-8000-000000000009"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Role:
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STORE_MANAGER = "StoreManager"
    SALES_ASSOCIATE = "SalesAssociate"
    COLLECTIONS_AGENT = "CollectionsAgent"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    CUSTOMER = "Customer"


class VerificationStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CheckStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    UNREACHABLE = "UNREACHABLE"
    REFUSED = "REFUSED"


class Relationship:
    FAMILY = "FAMILY"
    EMPLOYER = "EMPLOYER"
    LANDLORD = "LANDLORD"
    PERSONAL = "PERSONAL"


class LoyaltyTier:
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AccountFlag:
    NORMAL = "NORMAL"
    ADVERSE = "ADVERSE"


class UnitStatus:
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ON_RENT = "ON_RENT"
    IN_SERVICE = "IN_SERVICE"
    RETURNED_PENDING_GRADE = "RETURNED_PENDING_GRADE"
    RETIRED = "RETIRED"
    SOLD = "SOLD"


class ConditionGrade:
    NEW = "NEW"
    GRADE_A = "GRADE_A"
    GRADE_B = "GRADE_B"
    GRADE_C = "GRADE_C"
    UNRENTABLE = "UNRENTABLE"


class ResidualBasis:
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class RetiredReason:
    NONE = "NONE"
    UNRENTABLE_ON_GRADING = "UNRENTABLE_ON_GRADING"


class Category:
    FURNITURE = "FURNITURE"
    APPLIANCE = "APPLIANCE"


class CrewStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TermType:
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class PaymentStatus:
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    CLOSED = "CLOSED"


class PossessionStatus:
    PENDING_DELIVERY = "PENDING_DELIVERY"
    DELIVERED = "DELIVERED"
    SERVICE_SWAP_PENDING = "SERVICE_SWAP_PENDING"
    RETURN_PENDING_INSPECTION = "RETURN_PENDING_INSPECTION"
    RETURNED = "RETURNED"
    REPOSSESSED = "REPOSSESSED"
    OWNED = "OWNED"


class CollectionsStage:
    NONE = "NONE"
    ADVERSE = "ADVERSE"


class PaymentMethod:
    CASH = "CASH"
    CARD = "CARD"
    ACH = "ACH"
    MONEY_ORDER = "MONEY_ORDER"


class PaymentRowStatus:
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ReversalReason:
    NONE = "NONE"
    CHARGEBACK = "CHARGEBACK"
    NSF = "NSF"
    POSTING_ERROR = "POSTING_ERROR"


class WindowStatus:
    OPEN = "OPEN"
    USED = "USED"
    EXPIRED = "EXPIRED"


class ServiceType:
    DELIVERY_ONLY = "DELIVERY_ONLY"
    DELIVERY_SETUP = "DELIVERY_SETUP"


class DeliveryOrderStatus:
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED_ATTEMPT = "FAILED_ATTEMPT"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class FailureReason:
    CUSTOMER_ABSENT = "CUSTOMER_ABSENT"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    VEHICLE_ISSUE = "VEHICLE_ISSUE"


class IssueCode:
    MECHANICAL = "MECHANICAL"
    COSMETIC = "COSMETIC"
    MISSING_PART = "MISSING_PART"
    ELECTRICAL = "ELECTRICAL"
    INFESTATION = "INFESTATION"


class TicketStatus:
    SCHEDULED = "SCHEDULED"
    SWAP_ISSUED = "SWAP_ISSUED"
    RESOLVED = "RESOLVED"
    VOIDED = "VOIDED"


class Resolution:
    REPAIRED = "REPAIRED"
    SWAPPED = "SWAPPED"


class ReturnReason:
    VOLUNTARY_RETURN = "VOLUNTARY_RETURN"
    REPOSSESSION_RECOVERY = "REPOSSESSION_RECOVERY"


class InspectionStatus:
    PENDING = "PENDING"
    GRADED = "GRADED"


class DepreciationTier:
    WRITE_OFF = "WRITE_OFF"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class QuoteStatus:
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class PayoffFormula:
    PCT_OF_REMAINING = "PCT_OF_REMAINING"
    CASH_PRICE_MINUS_CREDIT = "CASH_PRICE_MINUS_CREDIT"


class Channel:
    PHONE = "PHONE"
    SMS = "SMS"
    EMAIL = "EMAIL"
    IN_PERSON = "IN_PERSON"


class Outcome:
    NO_ANSWER = "NO_ANSWER"
    LEFT_MESSAGE = "LEFT_MESSAGE"
    SPOKE_TO_CUSTOMER = "SPOKE_TO_CUSTOMER"
    PROMISE_TO_PAY = "PROMISE_TO_PAY"


class EntryType:
    PAYMENT_ACCRUAL = "PAYMENT_ACCRUAL"
    PAYMENT_REVERSAL = "PAYMENT_REVERSAL"
    EARLY_PAYOFF_BONUS = "EARLY_PAYOFF_BONUS"


class Decision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"
