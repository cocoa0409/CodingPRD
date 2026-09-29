"""Payload factories.

Each factory returns a valid request body with domain-plausible defaults and
accepts keyword overrides. Money is always whole integer cents; percentages are
plain decimals between 0 and 1.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import DEFAULT_CLOCK

_apn_counter = itertools.count(1)
_license_counter = itertools.count(1)
_fund_code_counter = itertools.count(1)
_resolution_counter = itertools.count(1)
_instrument_counter = itertools.count(1)


def unique_apn(prefix: str = "APN") -> str:
    """A parcel number no other parcel in the store will hold."""
    return f"{prefix}-{next(_apn_counter):06d}"


def unique_license_number(prefix: str = "AG") -> str:
    """An appraiser licence number no other appraiser in the store will hold."""
    return f"{prefix}-{next(_license_counter):06d}"


def unique_fund_code(prefix: str = "F") -> str:
    """A fund code no other fund in the store will hold."""
    return f"{prefix}-{next(_fund_code_counter):06d}"


def unique_resolution_number() -> str:
    """A board resolution number for an adoption."""
    return f"RES-2026-{next(_resolution_counter):04d}"


def unique_instrument_number() -> str:
    """A recorder's instrument number for a recorded deed."""
    return f"2026-INST-{next(_instrument_counter):06d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key explicitly overridden with ``None``."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------


def agency_payload(**overrides: Any) -> Dict[str, Any]:
    """A custodian agency that is not a preference entity."""
    return _merge(
        {
            "name": "City of Riverbend",
            "agency_type": "MUNICIPAL",
            "contact_email": "realproperty@riverbend.gov",
        },
        overrides,
    )


def preference_agency_payload(
    preference_category: str = "AFFORDABLE_HOUSING", **overrides: Any
) -> Dict[str, Any]:
    """A registered preference entity in the given statutory category."""
    return _merge(
        {
            "name": "Riverbend Housing Authority",
            "agency_type": "HOUSING_AUTHORITY",
            "contact_email": "director@riverbendhousing.gov",
            "is_preference_entity": True,
            "preference_category": preference_category,
        },
        overrides,
    )


def transit_agency_payload(**overrides: Any) -> Dict[str, Any]:
    """A neighbouring transit district that is not a preference entity."""
    return _merge(
        {
            "name": "Riverbend Transit District",
            "agency_type": "TRANSIT",
            "contact_email": "clerk@rtd.gov",
        },
        overrides,
    )


def parcel_payload(custodian_agency_id: str, **overrides: Any) -> Dict[str, Any]:
    """A publicly owned parcel held by the given custodian agency."""
    return _merge(
        {
            "apn": unique_apn(),
            "address": "9 Canal Street",
            "acreage": 3.1,
            "zoning_code": "M-1",
            "book_value_cents": 70000000,
            "custodian_agency_id": custodian_agency_id,
        },
        overrides,
    )


def appraiser_payload(**overrides: Any) -> Dict[str, Any]:
    """A licensed appraiser whose licence runs well past the default clock."""
    return _merge(
        {
            "name": "Dana Kirkwood MAI",
            "license_number": unique_license_number(),
            "license_expires_on": "2028-01-01T00:00:00Z",
        },
        overrides,
    )


def bidder_payload(**overrides: Any) -> Dict[str, Any]:
    """A prospective bidder with a clear debarment record."""
    return _merge(
        {
            "legal_name": "Canal Yard Holdings LLC",
            "entity_type": "CORPORATION",
            "contact_email": "deals@canalyard.example",
        },
        overrides,
    )


def funding_payload(amount_cents: int = 10000000, **overrides: Any) -> Dict[str, Any]:
    """Verified funds credited to a bidder's account."""
    return _merge({"amount_cents": amount_cents}, overrides)


def debarment_payload(**overrides: Any) -> Dict[str, Any]:
    """A debarment for cause."""
    return _merge(
        {
            "debarment_reason": (
                "State contractor debarment list entry dated 2026-09-14"
            )
        },
        overrides,
    )


def fund_payload(
    priority_rank: int = 1,
    allocation_pct: float = 1.0,
    fixed_reserve_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """A designated fund with its statutory rank, share and fixed reserve."""
    return _merge(
        {
            "name": "General Fund",
            "fund_code": unique_fund_code(),
            "priority_rank": priority_rank,
            "allocation_pct": allocation_pct,
            "fixed_reserve_cents": fixed_reserve_cents,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Title curative items
# ---------------------------------------------------------------------------


def title_item_payload(**overrides: Any) -> Dict[str, Any]:
    """A recorded lien opened against a parcel."""
    return _merge(
        {
            "item_type": "LIEN",
            "description": "Recorded mechanics lien from 2019 sidewalk work",
            "cure_cost_estimate_cents": 400000,
        },
        overrides,
    )


def cure_resolution_payload(
    actual_cure_cost_cents: Optional[int] = 250000, **overrides: Any
) -> Dict[str, Any]:
    """Resolve a title item by curing it at the given actual cost."""
    body: Dict[str, Any] = {"resolution": "CURED"}
    if actual_cure_cost_cents is not None:
        body["actual_cure_cost_cents"] = actual_cure_cost_cents
    return _merge(body, overrides)


def waiver_resolution_payload(**overrides: Any) -> Dict[str, Any]:
    """Resolve a title item by waiving it with a title endorsement."""
    return _merge({"resolution": "WAIVED_WITH_ENDORSEMENT"}, overrides)


def easement_resolution_payload(**overrides: Any) -> Dict[str, Any]:
    """Resolve a title item by reserving the burden as an agency easement."""
    return _merge(
        {
            "resolution": "RESERVED_AS_EASEMENT",
            "easement_purpose": "Storm drain maintenance access",
            "easement_area_sqft": 1200.0,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Appraisal
# ---------------------------------------------------------------------------


def appraisal_order_payload(
    parcel_id: str,
    appraiser_id: str,
    expected_parcel_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Order an appraisal over a closed engagement interval, carrying the OCC token."""
    return _merge(
        {
            "parcel_id": parcel_id,
            "appraiser_id": appraiser_id,
            "method": "SALES_COMPARISON",
            "engagement_start_on": "2026-08-02T00:00:00Z",
            "engagement_end_on": "2026-08-20T00:00:00Z",
            "expected_parcel_version": expected_parcel_version,
        },
        overrides,
    )


def appraisal_report_payload(
    appraised_value_cents: int = 100000000,
    effective_date: str = DEFAULT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    """The engaged appraiser's valuation report."""
    return _merge(
        {
            "appraised_value_cents": appraised_value_cents,
            "effective_date": effective_date,
            "narrative": "Sales comparison of four infill sales.",
        },
        overrides,
    )


def challenge_payload(
    asserted_value_cents: int = 90000000,
    deposit_paid_cents: int = 1000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A preference entity's challenge to the reported value, with its deposit."""
    return _merge(
        {
            "asserted_value_cents": asserted_value_cents,
            "grounds": "Comparable sales ignore the flood overlay on the rear third.",
            "deposit_paid_cents": deposit_paid_cents,
        },
        overrides,
    )


def sustain_determination_payload(
    revised_value_cents: int = 92000000, **overrides: Any
) -> Dict[str, Any]:
    """A board determination sustaining a challenge at the revised value."""
    return _merge(
        {"determination": "SUSTAINED", "revised_value_cents": revised_value_cents},
        overrides,
    )


def deny_determination_payload(**overrides: Any) -> Dict[str, Any]:
    """A board determination denying a challenge, forfeiting the deposit."""
    return _merge({"determination": "DENIED"}, overrides)


# ---------------------------------------------------------------------------
# Declaration, notices and preference negotiation
# ---------------------------------------------------------------------------


def declaration_payload(parcel_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft a declaration of surplus against one parcel."""
    return _merge(
        {
            "parcel_id": parcel_id,
            "justification": (
                "Canal Street yard is surplus after depot consolidation."
            ),
        },
        overrides,
    )


def adopt_payload(**overrides: Any) -> Dict[str, Any]:
    """Board adoption of the surplus resolution."""
    return _merge({"resolution_number": unique_resolution_number()}, overrides)


def issue_notices_payload(
    recipient_agency_ids: list, response_window_days: Optional[int] = 60, **overrides: Any
) -> Dict[str, Any]:
    """Serve the statutory notice of availability on the named agencies."""
    body: Dict[str, Any] = {"recipient_agency_ids": list(recipient_agency_ids)}
    if response_window_days is not None:
        body["response_window_days"] = response_window_days
    return _merge(body, overrides)


def decline_response_payload(**overrides: Any) -> Dict[str, Any]:
    """A noticed agency declining the statutory offer."""
    return _merge({"response_type": "DECLINE"}, overrides)


def express_interest_payload(
    claimed_preference_category: str = "AFFORDABLE_HOUSING", **overrides: Any
) -> Dict[str, Any]:
    """A noticed preference entity expressing statutory interest."""
    return _merge(
        {
            "response_type": "EXPRESS_INTEREST",
            "claimed_preference_category": claimed_preference_category,
        },
        overrides,
    )


def round_payload(
    party: str,
    price_offered_cents: int,
    responded_to_round_number: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Append one negotiation round to the good-faith record."""
    body: Dict[str, Any] = {
        "party": party,
        "price_offered_cents": price_offered_cents,
        "terms_summary": "Price and closing terms exchanged at the negotiation table.",
    }
    if responded_to_round_number is not None:
        body["responded_to_round_number"] = responded_to_round_number
    return _merge(body, overrides)


def officer_round_payload(
    price_offered_cents: int, **overrides: Any
) -> Dict[str, Any]:
    """A round written by the custodian agency."""
    return round_payload("CUSTODIAN_AGENCY", price_offered_cents, **overrides)


def entity_round_payload(
    price_offered_cents: int, **overrides: Any
) -> Dict[str, Any]:
    """A round written by the preference entity."""
    return round_payload("PREFERENCE_ENTITY", price_offered_cents, **overrides)


def conclude_agreed_payload(agreed_price_cents: int, **overrides: Any) -> Dict[str, Any]:
    """Conclude the negotiation as agreed at the given price."""
    return _merge(
        {"outcome": "AGREED", "agreed_price_cents": agreed_price_cents}, overrides
    )


def conclude_impasse_payload(**overrides: Any) -> Dict[str, Any]:
    """Conclude the negotiation as an impasse."""
    return _merge({"outcome": "IMPASSE"}, overrides)


# ---------------------------------------------------------------------------
# Environmental review
# ---------------------------------------------------------------------------


def exempt_review_payload(**overrides: Any) -> Dict[str, Any]:
    """An exempt determination, which is certified on creation."""
    return _merge({"determination_class": "EXEMPT"}, overrides)


def circulating_review_payload(
    determination_class: str = "NEGATIVE_DECLARATION",
    circulation_start_on: str = "2026-09-01T00:00:00Z",
    circulation_end_on: str = "2026-10-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A determination that must circulate for the statutory minimum."""
    return _merge(
        {
            "determination_class": determination_class,
            "circulation_start_on": circulation_start_on,
            "circulation_end_on": circulation_end_on,
        },
        overrides,
    )


def recirculate_payload(
    circulation_start_on: str,
    circulation_end_on: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Send the environmental document out for a further circulation round."""
    return _merge(
        {
            "recirculation_reason": (
                "Substantial new information on the groundwater plume."
            ),
            "circulation_start_on": circulation_start_on,
            "circulation_end_on": circulation_end_on,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Authorization, offering and bids
# ---------------------------------------------------------------------------


def authorize_payload(
    disposition_type: str = "COMPETITIVE_SALE", **overrides: Any
) -> Dict[str, Any]:
    """The board finding that fixes the disposition authority."""
    return _merge({"disposition_type": disposition_type}, overrides)


def offering_payload(
    declaration_id: str,
    expected_declaration_version: int,
    offering_type: str = "COMPETITIVE_SALE",
    bid_open_at: str = DEFAULT_CLOCK,
    bid_close_at: str = "2026-12-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create the disposition offering, carrying the OCC token on the declaration."""
    return _merge(
        {
            "declaration_id": declaration_id,
            "offering_type": offering_type,
            "bid_open_at": bid_open_at,
            "bid_close_at": bid_close_at,
            "expected_declaration_version": expected_declaration_version,
        },
        overrides,
    )


def bid_payload(
    amount_cents: int = 108000000,
    deposit_amount_cents: int = 5000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A sealed bid with its deposit."""
    return _merge(
        {
            "amount_cents": amount_cents,
            "deposit_amount_cents": deposit_amount_cents,
            "intended_use": "Light industrial redevelopment",
        },
        overrides,
    )


def rescind_payload(**overrides: Any) -> Dict[str, Any]:
    """Rescind an award."""
    return _merge(
        {"cancellation_reason": "Winning bidder failed to post the balance."},
        overrides,
    )


def withdraw_declaration_payload(**overrides: Any) -> Dict[str, Any]:
    """Withdraw the declaration of surplus."""
    return _merge(
        {"withdrawn_reason": "Council reversed the surplus finding on appeal."},
        overrides,
    )


# ---------------------------------------------------------------------------
# Conveyance and compliance
# ---------------------------------------------------------------------------


def conveyance_payload(
    closing_costs_cents: int = 1249999,
    broker_fee_cents: int = 1500000,
    deed_restrictions: Optional[list] = None,
    reverter_cure_period_days: Optional[int] = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open the conveyance file on an awarded offering."""
    body: Dict[str, Any] = {
        "closing_costs_cents": closing_costs_cents,
        "broker_fee_cents": broker_fee_cents,
        "deed_restrictions": (
            list(deed_restrictions)
            if deed_restrictions is not None
            else ["No residential use for 20 years"]
        ),
        "reverter_condition": (
            "Redevelopment permit within 24 months of recording"
        ),
    }
    if reverter_cure_period_days is not None:
        body["reverter_cure_period_days"] = reverter_cure_period_days
    return _merge(body, overrides)


def record_payload(**overrides: Any) -> Dict[str, Any]:
    """Record the deed under a recorder's instrument number."""
    return _merge(
        {"recorded_instrument_number": unique_instrument_number()}, overrides
    )


def violation_notice_payload(**overrides: Any) -> Dict[str, Any]:
    """Notice a breach of a recorded deed restriction."""
    return _merge(
        {
            "violation_description": (
                "Residential framing permit pulled in breach of the recorded "
                "restriction"
            )
        },
        overrides,
    )


def accept_cure_payload(**overrides: Any) -> Dict[str, Any]:
    """Accept the grantee's cure inside the cure period."""
    return _merge(
        {"cure_note": "Framing removed and the permit withdrawn on 2027-02-01."},
        overrides,
    )
