"""Typed shapes for every resource the Rent-To-Own Store API exposes.

Every resource carries a server-minted ``id`` and a ``created_at`` timestamp.
Most resources additionally carry ``updated_at`` and ``version``; the two
append-only records -- a collection contact and a loyalty ledger entry -- carry
only ``id`` and ``created_at`` and are therefore modelled without them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Envelope shapes
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    """The ``meta`` object of a success or error envelope."""

    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorBody(TypedDict):
    """The ``data`` object of an error envelope."""

    error_id: str
    message: str


class Envelope(TypedDict, total=False):
    meta: ResponseMeta
    response_type: str
    data: Any


# ---------------------------------------------------------------------------
# Common field mixins
# ---------------------------------------------------------------------------


class Tracked(TypedDict):
    """Identity, timestamps and mutation bookkeeping."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnly(TypedDict):
    """An immutable record of something that happened."""

    id: str
    created_at: str


# ---------------------------------------------------------------------------
# Statutory configuration
# ---------------------------------------------------------------------------


class StateRtoRule(Tracked, total=False):
    state_code: str
    late_fee_grace_days: int
    late_fee_pct: float
    late_fee_max_cents: int
    reinstate_threshold_months: int
    reinstate_days_short: int
    reinstate_days_long: int
    reinstatement_fee_cents: int
    early_purchase_formula: str
    early_purchase_pct: float
    rent_credit_pct: float
    processing_fee_max_cents: int
    disclosure_requires_total_of_payments: bool
    max_collection_contacts_per_week: int
    quiet_hours_start_utc_hour: int
    quiet_hours_end_utc_hour: int
    repossession_paid_pct_limit: float
    credit_inquiry_prohibited: bool
    max_term_renewals: int


# ---------------------------------------------------------------------------
# Store, inventory, crews
# ---------------------------------------------------------------------------


class Store(Tracked, total=False):
    name: str
    state_code: str
    service_bay_capacity: int
    units_on_rent_count: int
    units_in_service_count: int
    service_intake_open: bool


class InventoryUnit(Tracked, total=False):
    store_id: str
    model_code: str
    serial_number: str
    category: str
    cash_price_cents: int
    condition_grade: str
    rent_cycle_count: int
    status: str
    accumulated_rent_received_cents: int
    residual_value_cents: int
    residual_valuation_basis: str
    replaced_unit_id: Optional[str]
    retired_reason: str


class DeliveryCrew(Tracked, total=False):
    store_id: str
    crew_name: str
    setup_certified: bool
    status: str


# ---------------------------------------------------------------------------
# Renter onboarding
# ---------------------------------------------------------------------------


class Customer(Tracked, total=False):
    full_name: str
    email: str
    phone: str
    state_code: str
    employer_name: str
    employer_verified: bool
    monthly_income_cents: int
    residence_months: int
    government_id_verified: bool
    in_person_contact_consent: bool
    verification_status: str
    verification_score: int
    verified_reference_count: int
    verified_by_user_id: str
    loyalty_points_balance: int
    loyalty_points_lifetime: int
    loyalty_tier: str
    credit_balance_cents: int
    account_flag: str
    adverse_agreement_count: int
    lifetime_delinquency_count: int


class CustomerReference(Tracked, total=False):
    customer_id: str
    reference_name: str
    relationship: str
    phone: str
    check_status: str
    checked_at: Optional[str]
    checked_by_user_id: str


# ---------------------------------------------------------------------------
# The agreement and its money
# ---------------------------------------------------------------------------


class Agreement(Tracked, total=False):
    customer_id: str
    unit_id: str
    store_id: str
    state_code_snapshot: str
    state_rule_version_snapshot: int
    created_by_user_id: str
    term_type: str
    renewal_count: int
    disclosure_acknowledged: bool
    adjusted_cash_price_cents: int
    renewal_rate_cents: int
    rent_subtotal_cents: int
    processing_fee_cents: int
    total_of_payments_cents: int
    monthly_equivalent_rate_cents: int
    payment_status: str
    possession_status: str
    collections_stage: str
    cycle_anchor_at: Optional[str]
    current_period_due_at: Optional[str]
    periods_paid: int
    rent_applied_cents: int
    partial_credit_cents: int
    customer_credit_contributed_cents: int
    late_fee_assessed_cents: int
    late_fee_paid_cents: int
    late_fee_balance_cents: int
    late_fee_period_index_last: int
    reinstatement_fee_assessed_cents: int
    reinstatement_fee_paid_cents: int
    reinstatement_fee_balance_cents: int
    early_purchase_paid_cents: int
    paid_pct: float
    swap_count: int
    service_credit_days: int
    collection_contact_count_7d: int


class AgreementDisclosure(TypedDict, total=False):
    """The read-only total-of-payments rendering. It computes nothing new."""

    agreement_id: str
    term_type: str
    renewal_count: int
    adjusted_cash_price_cents: int
    renewal_rate_cents: int
    rent_subtotal_cents: int
    processing_fee_cents: int
    total_of_payments_cents: int
    monthly_equivalent_rate_cents: int
    early_purchase_formula: str
    state_code: str
    cost_of_rental_cents: int


class RenewalPayment(Tracked, total=False):
    agreement_id: str
    amount_cents: int
    payment_method: str
    status: str
    posted_at: str
    allocation_late_fee_cents: int
    allocation_reinstatement_fee_cents: int
    allocation_rent_cents: int
    allocation_partial_credit_cents: int
    allocation_customer_credit_cents: int
    partial_credit_before_cents: int
    periods_advanced: int
    days_late: int
    cured_delinquency: bool
    loyalty_points_awarded: int
    reversal_reason: str
    reversed_at: Optional[str]


class ReinstatementWindow(Tracked, total=False):
    agreement_id: str
    missed_period_index: int
    opened_at: str
    expires_at: str
    window_days: int
    status: str
    reinstatement_fee_cents: int


# ---------------------------------------------------------------------------
# Delivery and service
# ---------------------------------------------------------------------------


class DeliveryOrder(Tracked, total=False):
    agreement_id: str
    crew_id: str
    service_type: str
    window_start_at: str
    window_end_at: str
    status: str
    attempt_count: int
    setup_completed: bool
    completed_at: Optional[str]


class ServiceTicket(Tracked, total=False):
    agreement_id: str
    store_id: str
    unit_id: str
    issue_code: str
    window_start_at: str
    window_end_at: str
    status: str
    replacement_unit_id: Optional[str]
    resolution: Optional[str]
    rent_credit_days: int
    issued_by_user_id: str


class ReturnInspection(Tracked, total=False):
    agreement_id: str
    unit_id: str
    return_reason: str
    status: str
    assessed_grade: Optional[str]
    damage_deduction_cents: int
    missing_parts_count: int
    final_residual_value_cents: int
    re_rent_rate_cents: int
    depreciation_tier: str
    graded_by_user_id: str


# ---------------------------------------------------------------------------
# Ending the agreement, and collections
# ---------------------------------------------------------------------------


class EarlyPurchaseQuote(Tracked, total=False):
    agreement_id: str
    formula_applied: str
    rent_applied_snapshot_cents: int
    loyalty_tier_snapshot: str
    pre_discount_cents: int
    loyalty_discount_cents: int
    late_fee_component_cents: int
    payoff_amount_cents: int
    status: str
    issued_at: str
    expires_at: str


class CollectionContact(AppendOnly, total=False):
    """Append-only: no ``updated_at`` and no ``version``."""

    agreement_id: str
    channel: str
    outcome: str
    contacted_at: str
    rolling_7d_count_at_contact: int
    contacted_by_user_id: str


class LoyaltyLedgerEntry(AppendOnly, total=False):
    """Append-only: no ``updated_at`` and no ``version``."""

    customer_id: str
    agreement_id: Optional[str]
    source_payment_id: Optional[str]
    entry_type: str
    delta_points: int
    balance_after: int
    occurred_at: str


class DayCloseReport(TypedDict, total=False):
    """What the ops-run arrears checkpoint reports it did."""

    store_id: str
    closed_at: str
    agreements_scanned: int
    late_fees_assessed: int
    late_fee_total_cents: int
    windows_opened: int
    windows_expired: int
    agreements_defaulted: int
    agreements_marked_adverse: int


class ClockState(TypedDict, total=False):
    current_utc: str


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
