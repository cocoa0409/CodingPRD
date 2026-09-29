"""TypedDict shapes for every resource the Winery DTC API returns.

The system-managed properties follow PRD §2.5: eleven resources carry the full
set of ``id``, ``created_at``, ``updated_at`` and ``version``, while
``ProhibitedZip``, ``OrderLine`` and ``VolumeLedgerEntry`` are immutable and
therefore carry only ``id`` and ``created_at`` — for those two, ``updated_at``
and ``version`` are absent from the resource entirely.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


class VersionedResource(TypedDict):
    """The four system-managed properties of PRD §2.5."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableResource(TypedDict):
    """The two system-managed properties of an immutable row (PRD §2.5)."""

    id: str
    created_at: str


class Winery(VersionedResource, total=False):
    name: str
    ttb_permit_number: str
    home_state_code: str
    annual_production_gallons: int
    status: str
    suspension_reason: Optional[str]
    excise_accrued_cents: int
    excise_reversed_cents: int
    suspended_subscription_count: int
    open_exception_count: int


class StateRule(VersionedResource, total=False):
    state_code: str
    allows_dtc: bool
    per_consumer_limit_liters: float
    per_consumer_period: str
    per_winery_annual_limit_liters: float
    excise_rate_per_liter_cents: int
    large_format_surcharge_cents_per_liter: int
    excise_cap_cents_per_shipment: int
    sales_tax_rate_bps: int
    tax_on_shipping: bool
    excise_in_tax_base: bool
    adult_signature_required: bool
    requires_carrier_program: bool
    reporting_frequency: str
    zero_filing_required: bool
    min_purchaser_age: int
    renewal_lead_days: int


class ProhibitedZip(ImmutableResource, total=False):
    state_rule_id: str
    zip_code: str
    reason: str
    effective_from: str


class CarrierProgram(VersionedResource, total=False):
    carrier_code: str
    program_name: str
    states_served: List[str]
    requires_enrollment: bool
    adult_signature_service_code: Optional[str]


class CarrierEnrollment(VersionedResource, total=False):
    winery_id: str
    carrier_program_id: str
    account_number: str
    status: str
    approved_at: Optional[str]
    decided_by_user_id: Optional[str]


class Consumer(VersionedResource, total=False):
    full_name: str
    email: str
    birthdate: str
    address_line: str
    city: str
    state_code: str
    zip_code: str
    id_verification_method: str
    id_verified_at: Optional[str]
    rolling_liters_by_state: Dict[str, float]
    rolling_liters_settled_by_state: Dict[str, float]
    return_credit_count: int
    denied_exception_count: int
    risk_score_screening: int
    risk_score_audit: int
    screening_tier: str


class StatePermit(VersionedResource, total=False):
    winery_id: str
    state_code: str
    permit_number: str
    permit_type: str
    effective_date: str
    expiration_date: str
    status: str
    renewal_reference: Optional[str]
    renewal_filed_at: Optional[str]
    revocation_reason: Optional[str]
    renewal_cycle_count: int


class ClubSubscription(VersionedResource, total=False):
    consumer_id: str
    winery_id: str
    cadence: str
    sku: str
    bottles_per_shipment: int
    bottle_ml: int
    unit_price_cents: int
    next_run_date: Optional[str]
    status: str
    hold_start_date: Optional[str]
    hold_release_date: Optional[str]
    hold_reason: Optional[str]
    last_hold_release_date: Optional[str]
    missed_run_count: int
    annual_allotment: int
    consumed_shipments: int
    remaining_allotment: int


class Order(VersionedResource, total=False):
    winery_id: str
    consumer_id: str
    club_subscription_id: Optional[str]
    ship_to_address_line: str
    ship_to_state_code: str
    ship_to_zip: str
    compliance_status: str
    fulfillment_status: str
    rejection_error_id: Optional[str]
    override_applied: bool
    total_liters: float
    subtotal_cents: int
    shipping_gross_cents: int
    shipping_tiered_cents: int
    shipping_discount_cents: int
    shipping_cents: int
    excise_tax_cents: int
    sales_tax_cents: int
    pre_fee_total_cents: int
    compliance_handling_fee_cents: int
    total_cents: int
    excise_reversed_cents: int
    sales_tax_reversed_cents: int
    adult_signature_required: bool
    cleared_at: Optional[str]
    returned_at: Optional[str]


class OrderLine(ImmutableResource, total=False):
    order_id: str
    line_index: int
    sku: str
    bottle_ml: int
    bottles: int
    unit_price_cents: int
    line_liters: float
    line_subtotal_cents: int
    allocated_shipping_cents: int
    line_taxable_cents: int
    line_sales_tax_cents: int


class Shipment(VersionedResource, total=False):
    order_id: str
    carrier_enrollment_id: str
    replacement_of_shipment_id: Optional[str]
    tracking_number: str
    adult_signature_required: bool
    adult_signature_service_code: Optional[str]
    status: str
    exception_code: Optional[str]
    reroute_zip: Optional[str]
    reroute_count: int
    signed_by: Optional[str]
    signer_age_verified: Optional[bool]
    delivered_at: Optional[str]
    returned_at: Optional[str]


class ComplianceException(VersionedResource, total=False):
    order_id: str
    raised_rule: str
    justification: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]


class VolumeLedgerEntry(ImmutableResource, total=False):
    consumer_id: str
    winery_id: str
    order_id: Optional[str]
    shipment_id: Optional[str]
    state_code: str
    liters: float
    event_type: str
    occurred_at: str
    reason: Optional[str]


class TaxRemittance(VersionedResource, total=False):
    winery_id: str
    supersedes_remittance_id: Optional[str]
    state_code: str
    period_type: str
    period_start: str
    period_end: str
    basis: str
    status: str
    excise_accrued_cents: int
    excise_reversed_cents: int
    excise_due_cents: int
    sales_tax_accrued_cents: int
    sales_tax_reversed_cents: int
    sales_tax_due_cents: int
    liters_total: float
    shipment_count: int
    included_order_ids: List[str]
    filed_at: Optional[str]
    filed_by_user_id: Optional[str]
    remitted_at: Optional[str]
    remitted_by_user_id: Optional[str]
    payment_reference: Optional[str]


class VolumeSummary(TypedDict, total=False):
    """The computed read of PRD §3.4."""

    consumer_id: str
    as_of: str
    per_state: Dict[str, Any]
    risk_score_screening: int
    risk_score_audit: int
    screening_tier: str
    return_credit_count: int
    denied_exception_count: int


class ClubRunResult(TypedDict, total=False):
    """The club-run response of PRD §3.8."""

    winery_id: str
    run_date: str
    generated_count: int
    skipped_count: int
    generated_order_ids: List[str]
    skipped_subscription_ids: List[str]


class RenewalCalendar(TypedDict, total=False):
    """The computed read of PRD §3.9."""

    winery_id: str
    as_of: str
    horizon_days: int
    permits_expiring: List[Dict[str, Any]]
    reports_due: List[Dict[str, Any]]


VERSIONED_ENTITY_NAMES = [
    "Winery",
    "StateRule",
    "CarrierProgram",
    "CarrierEnrollment",
    "Consumer",
    "StatePermit",
    "ClubSubscription",
    "Order",
    "Shipment",
    "ComplianceException",
    "TaxRemittance",
]

IMMUTABLE_ENTITY_NAMES = ["ProhibitedZip", "OrderLine", "VolumeLedgerEntry"]
