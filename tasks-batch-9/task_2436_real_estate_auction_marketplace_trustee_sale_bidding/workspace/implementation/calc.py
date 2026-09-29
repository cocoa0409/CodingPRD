"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

All money is integer cents; every rate multiplication goes through Decimal and
`rhu` (round half up).  Never float.
"""

from decimal import Decimal

from util import D, rhu

# --------------------------------------------------------------------------- #
# enumerations
# --------------------------------------------------------------------------- #

SELLER_TYPES = {"SERVICER", "BANK", "PRIVATE_SELLER", "GSE"}
OCCUPANCY = {"OWNER_OCCUPIED", "TENANT_OCCUPIED", "VACANT", "UNKNOWN"}
TITLE_CONDITION = {"CLEAR", "JUNIOR_LIENS", "CLOUDED", "UNKNOWN"}
EVICTION_TIERS = {"LOW", "MEDIUM", "HIGH"}
LISTING_STATUS = {
    "INTAKE", "DISCLOSURE_READY", "LISTED", "SOLD_PENDING_CONTRACT",
    "SOLD_CLOSED", "UNSOLD", "RELIST_PENDING",
}
TITLE_CLEARANCE_STATUS = {"PENDING", "CLEARED", "CLOUDED_DISCLOSED", "DEFECTIVE"}
CLEARANCE_OUTCOMES = {"CLEARED", "CLOUDED_DISCLOSED", "DEFECTIVE"}
TRUSTEE_SALE_STATUS = {"PENDING", "CONFIRMED", "POSTPONED", "CANCELLED", "HELD"}
EVENT_STATUS = {"SCHEDULED", "LIVE", "POSTPONED", "CANCELLED", "CLOSED"}
LOT_STATUS = {
    "PENDING", "OPEN", "EXTENDED", "SUSPENDED", "CLOSED_SOLD",
    "CLOSED_NO_SALE", "WITHDRAWN",
}
LOT_TERMINAL = {"CLOSED_SOLD", "CLOSED_NO_SALE", "WITHDRAWN"}
LOT_NON_TERMINAL = {"PENDING", "OPEN", "EXTENDED", "SUSPENDED"}
IDENTITY_STATUS = {"UNVERIFIED", "VERIFIED", "REJECTED"}
REGISTRATION_STATUS = {"PENDING_REVIEW", "REGISTERED", "SUSPENDED", "REJECTED", "BARRED"}
EXCLUSION_TYPES = {"SANCTIONS_LIST", "TRUSTEE_AFFILIATE", "STATE_INELIGIBLE", "PRIOR_FALLOUT"}
CLIENT_EXCLUSION_TYPES = {"SANCTIONS_LIST", "TRUSTEE_AFFILIATE", "STATE_INELIGIBLE"}
EXCLUSION_STATUS = {"ACTIVE", "LIFTED"}
HOLD_STATUS = {"HELD", "EXTENDED", "RELEASED", "CAPTURED"}
HOLD_ENCUMBERED = {"HELD", "EXTENDED"}
RELEASE_REASONS = {
    "OUTBID", "NO_SALE", "CONTRACT_CLOSED", "EVENT_CANCELLED",
    "EXTENSION_LIMIT", "FORFEITED",
}
BID_STATUS = {"ACTIVE", "OUTBID", "WINNING", "WITHDRAWN"}
CONTRACT_STATUS = {"EXECUTED", "CLOSED", "FALLOUT"}
SETTLEMENT_STATUS = {"DRAFT", "POSTED", "VOID"}
OFFER_STATUS = {"OUTSTANDING", "ACCEPTED", "DECLINED", "EXPIRED"}
ASSESSMENT_MODES = {"SCREEN", "AUDIT"}
VERIFY_DECISIONS = {"VERIFIED", "REJECTED"}
OFFER_DECISIONS = {"ACCEPTED", "DECLINED"}

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

DEPOSIT_PCT = D("0.05")
DEPOSIT_FLOOR_CENTS = 500000
OCCUPANCY_DEPOSIT_MULT = {
    "OWNER_OCCUPIED": D("1.50"),
    "TENANT_OCCUPIED": D("1.25"),
    "UNKNOWN": D("1.50"),
    "VACANT": D("1.00"),
}

MAX_HOLD_EXTENSIONS = 2
HOLD_EXTENSION_DAYS = 30
# HOLD_INITIAL_DAYS is not pinned numerically by the PRD or the scaffold; the
# platform's "initial hold period" is taken to be the same 30 days the
# postponement policy grants.
HOLD_INITIAL_DAYS = 30

EXTENSION_TRIGGER_SECONDS = 60
EXTENSION_SECONDS = 120
MAX_EXTENSIONS_PER_LOT = 3

PREMIUM_TIER_1_CEILING_CENTS = 10000000
PREMIUM_TIER_2_CEILING_CENTS = 50000000
OCCUPANCY_SURCHARGE_BPS = {
    "OWNER_OCCUPIED": 150,
    "TENANT_OCCUPIED": 100,
    "VACANT": 0,
    "UNKNOWN": 200,
}
TITLE_SURCHARGE_BPS = {
    "CLEAR": 0,
    "JUNIOR_LIENS": 75,
    "CLOUDED": 175,
    "UNKNOWN": 250,
}
MIN_PREMIUM_CENTS = 250000
MAX_PREMIUM_CENTS = 6000000

POSTPONE_CARRY_BPS = 25

BASE_DOC_FEE_CENTS = 95000
DOC_FEE_TIER_1_FLOOR_CENTS = 25000000
DOC_FEE_TIER_2_FLOOR_CENTS = 50000000

MARKETING_RECOVERY_BPS = 35
TITLE_SERVICE_FEE_CENTS = 45000

FORFEIT_SELLER_BPS = 6000

IDENTITY_PENALTY = 25
EXCLUSION_PENALTY = 20
FALLOUT_PENALTY = 15
DEPOSIT_PENALTY = 10
RISK_SCORE_CAP = 100
ELIGIBILITY_MAX_SCORE = 40
BARRING_FALLOUT_THRESHOLD = 2

COUNTY_BUFFER_MINUTES = 30
OFFER_WINDOW_DAYS = 3


# --------------------------------------------------------------------------- #
# eviction_risk_tier — first matching clause wins (PRD §3.1)
# --------------------------------------------------------------------------- #

def eviction_risk_tier(occupancy_status, title_condition):
    if occupancy_status == "TENANT_OCCUPIED" or title_condition in ("CLOUDED", "UNKNOWN"):
        return "HIGH"
    if occupancy_status == "OWNER_OCCUPIED" or title_condition == "JUNIOR_LIENS":
        return "MEDIUM"
    return "LOW"


# --------------------------------------------------------------------------- #
# required_deposit (PRD §3.3)
# --------------------------------------------------------------------------- #

def required_deposit(opening_bid_cents, occupancy_status):
    base = max(DEPOSIT_FLOOR_CENTS, rhu(D(opening_bid_cents) * DEPOSIT_PCT))
    mult = OCCUPANCY_DEPOSIT_MULT[occupancy_status]
    return rhu(D(base) * mult)


# --------------------------------------------------------------------------- #
# buyer_premium — shared rule, two variants (PRD §3.6 / §3.7)
# --------------------------------------------------------------------------- #

def tier_rate(price_cents):
    if price_cents < PREMIUM_TIER_1_CEILING_CENTS:
        return D("0.10")
    if price_cents < PREMIUM_TIER_2_CEILING_CENTS:
        return D("0.08")
    return D("0.06")


def buyer_premium(price_cents, occupancy_status, title_condition):
    """A lot with no price yet projects a premium of 0 (PRD §3.1/§3.6)."""
    if price_cents <= 0:
        return 0
    rate = (
        tier_rate(price_cents)
        + D(OCCUPANCY_SURCHARGE_BPS[occupancy_status]) / D(10000)
        + D(TITLE_SURCHARGE_BPS[title_condition]) / D(10000)
    )
    raw = rhu(D(price_cents) * rate)
    return max(MIN_PREMIUM_CENTS, min(MAX_PREMIUM_CENTS, raw))


# --------------------------------------------------------------------------- #
# contract_price — hammer plus postponement carry (PRD §3.7)
# --------------------------------------------------------------------------- #

def contract_price(hammer_price_cents, postponement_count):
    carry = rhu(
        D(hammer_price_cents) * D(POSTPONE_CARRY_BPS) * D(postponement_count) / D(10000)
    )
    return hammer_price_cents + carry


# --------------------------------------------------------------------------- #
# doc_fee_and_total_due — three pinned steps, no fixed-point (PRD §3.7)
# --------------------------------------------------------------------------- #

def doc_fee_and_total_due(contract_price_cents, final_buyer_premium_cents):
    provisional_total = contract_price_cents + final_buyer_premium_cents + BASE_DOC_FEE_CENTS
    if provisional_total >= DOC_FEE_TIER_2_FLOOR_CENTS:
        discount = D("0.40")
    elif provisional_total >= DOC_FEE_TIER_1_FLOOR_CENTS:
        discount = D("0.25")
    else:
        discount = D("0")
    doc_fee = rhu(D(BASE_DOC_FEE_CENTS) * (Decimal(1) - discount))
    total_due = contract_price_cents + final_buyer_premium_cents + doc_fee
    return doc_fee, total_due


# --------------------------------------------------------------------------- #
# settlement_split — rounded per component, then summed (PRD §2.8 / §3.7)
# --------------------------------------------------------------------------- #

def settlement_split(contract_price_cents, commission_bps, title_condition,
                     final_buyer_premium_cents):
    c1 = rhu(D(contract_price_cents) * D(commission_bps) / D(10000))
    c2 = rhu(D(contract_price_cents) * D(MARKETING_RECOVERY_BPS) / D(10000))
    c3 = TITLE_SERVICE_FEE_CENTS if title_condition != "CLEAR" else 0
    platform_fee = c1 + c2 + c3
    seller_net = contract_price_cents - platform_fee
    return {
        "platform_fee_cents": platform_fee,
        "seller_net_cents": seller_net,
        "buyer_premium_cents": final_buyer_premium_cents,
        "settlement_gross_cents": contract_price_cents + final_buyer_premium_cents,
    }


# --------------------------------------------------------------------------- #
# forfeiture_split — remainder to the platform (PRD §3.8)
# --------------------------------------------------------------------------- #

def forfeiture_split(forfeited_deposit_cents):
    seller = rhu(D(forfeited_deposit_cents) * D(FORFEIT_SELLER_BPS) / D(10000))
    platform = forfeited_deposit_cents - seller
    return seller, platform
