"""Status vocabularies and payload shapes for the clearinghouse entities.

The string constants mirror the enumerations the PRD defines. They exist so a
test asserts against a named state rather than a bare literal, and so a typo
in a state name fails at import time rather than as a puzzling comparison.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------

class ManufacturerStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RetailerStatus:
    ACTIVE = "ACTIVE"
    WATCHLIST = "WATCHLIST"
    SUSPENDED = "SUSPENDED"


class OfferStatus:
    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class IntakeStatus:
    RECEIVED = "RECEIVED"
    COUNT_VERIFIED = "COUNT_VERIFIED"
    SORTED = "SORTED"
    CLOSED = "CLOSED"


class SettlementStatus:
    PENDING = "PENDING"
    STATEMENT_ISSUED = "STATEMENT_ISSUED"
    PAID = "PAID"
    HELD = "HELD"


class LotStatus:
    SORTED = "SORTED"
    VALIDATED = "VALIDATED"
    LOT_REJECTED = "LOT_REJECTED"
    DISPUTED = "DISPUTED"
    REINSTATED = "REINSTATED"


class ItemStatus:
    CAPTURED = "CAPTURED"
    ACCEPTED = "ACCEPTED"
    REJECTED_COUNTERFEIT = "REJECTED_COUNTERFEIT"
    REJECTED_EXPIRED = "REJECTED_EXPIRED"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_MISREDEEMED = "REJECTED_MISREDEEMED"
    REINSTATED = "REINSTATED"


class RejectCode:
    BARCODE_MISMATCH = "BARCODE_MISMATCH"
    EXPIRED_AT_POS = "EXPIRED_AT_POS"
    DUPLICATE_SERIAL = "DUPLICATE_SERIAL"
    NO_PURCHASE_MATCH = "NO_PURCHASE_MATCH"
    INSUFFICIENT_QUALIFYING_UNITS = "INSUFFICIENT_QUALIFYING_UNITS"


class LotRejectReason:
    ALL_ITEMS_REJECTED = "ALL_ITEMS_REJECTED"
    OFFER_WITHDRAWN = "OFFER_WITHDRAWN"
    DISPUTE_UPHELD = "DISPUTE_UPHELD"


class StatementStatus:
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    PAID = "PAID"


class HoldReason:
    FRAUD_REVIEW = "FRAUD_REVIEW"
    DISPUTE_OPEN = "DISPUTE_OPEN"
    FUNDING_SHORTFALL = "FUNDING_SHORTFALL"


class InvoiceStatus:
    ISSUED = "ISSUED"
    SHORT_FUNDED = "SHORT_FUNDED"
    FUNDED = "FUNDED"
    RECONCILED = "RECONCILED"
    REVERSED = "REVERSED"


class DisputeStatus:
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class ClipStatus:
    CLIPPED = "CLIPPED"
    MATCHED = "MATCHED"
    EXPIRED_UNUSED = "EXPIRED_UNUSED"


class RedemptionEventStatus:
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"


class EventRejectCode:
    NO_ELIGIBLE_CLIP = "NO_ELIGIBLE_CLIP"


class ValuationVariant:
    FULL_COUNT = "FULL_COUNT"
    SAMPLED_EXTRAPOLATION = "SAMPLED_EXTRAPOLATION"


class BarcodeFamily:
    GS1_DATABAR = "GS1_DATABAR"
    UPC_A_WITH_EXT5 = "UPC_A_WITH_EXT5"


class Channel:
    MAIL = "MAIL"
    ELECTRONIC = "ELECTRONIC"


class ChannelCapability:
    MAIL_ONLY = "MAIL_ONLY"
    ELECTRONIC_ONLY = "ELECTRONIC_ONLY"
    BOTH = "BOTH"


class PaymentTerms:
    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_45 = "NET_45"


class FeeTier:
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    PROBATION = "PROBATION"


class HandlingFeePolicy:
    CONTRACT_RATE = "CONTRACT_RATE"
    TIERED_RATE = "TIERED_RATE"


class FraudScoringMode:
    ROLLING_WINDOW = "ROLLING_WINDOW"
    LIFETIME_WEIGHTED = "LIFETIME_WEIGHTED"


# ---------------------------------------------------------------------------
# Field groupings used by the shared assertions
# ---------------------------------------------------------------------------

# Most resources carry these four identity fields.
VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# A point-of-sale basket is immutable and carries only these two.
IMMUTABLE_COMMON_FIELDS = ("id", "created_at")

# The complete key set of a purchase-data record payload.
PURCHASE_RECORD_FIELDS = (
    "id",
    "created_at",
    "retailer_id",
    "offer_id",
    "pos_transaction_ref",
    "transaction_date",
    "qualifying_units",
)

# The response body of the computed valuation read.
VALUATION_FIELDS = (
    "submission_id",
    "valuation_method",
    "full_count_gross_face_value_cents",
    "sampled_gross_face_value_cents",
    "settled_gross_face_value_cents",
    "settled_handling_fee_cents",
    "lot_count",
)


class CapturedItemPayload(TypedDict, total=False):
    """One element of the bulk image-capture array."""
    scanned_barcode: str
    serial_number: Optional[str]
    image_uri: str
    redeemed_at: str
    pos_transaction_ref: Optional[str]
    claimed_units: int


class ChainState(TypedDict, total=False):
    """The ids a composite fixture threads through to the test body."""
    manufacturer_id: str
    retailer_id: str
    offer_id: str
    submission_id: str
    lot_ids: List[str]
    item_ids: List[str]
    record_ids: Dict[str, str]
    statement_ids: List[str]
    invoice_ids: List[str]
    dispute_id: str
    extra: Dict[str, Any]
