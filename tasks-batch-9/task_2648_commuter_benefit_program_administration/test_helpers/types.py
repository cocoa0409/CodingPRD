"""TypedDict shapes for every resource the commuter benefit service returns.

Most resources carry the four common fields ``id``, ``created_at``,
``updated_at`` and ``version``.  Two are append-only audit records and carry
only ``id`` and ``created_at``: ``LedgerEntry`` and ``ComplianceAssessment``.
Those two TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class MutableResource(TypedDict):
    """The four common fields carried by every mutable resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """The two common fields carried by the append-only audit records."""

    id: str
    created_at: str


class Employer(MutableResource, total=False):
    legal_name: str
    region_code: str
    transit_group_limit_cents: int
    parking_group_limit_cents: int
    pretax_ratio_cap_pct: int
    spill_policy: str
    rollover_policy: str
    rollover_cap_cents: int
    forfeiture_grace_days: int
    program_cap_cents: int
    program_status: str
    ordinance_mandate_status: str
    total_pretax_committed_cents: int
    enrolled_employee_count: int


class BenefitCategory(MutableResource, total=False):
    employer_id: str
    category_type: str
    limit_group: str
    monthly_exclusion_limit_cents: int
    pretax_allowed: bool
    posttax_allowed: bool
    status: str
    active_election_count: int


class Employee(MutableResource, total=False):
    employer_id: str
    external_ref: str
    work_region_code: str
    payroll_cycle: str
    hire_date: str
    termination_date: Optional[str]
    status: str
    substantiation_hold: bool
    repayment_due_cents: int


class ElectionWindow(MutableResource, total=False):
    employer_id: str
    benefit_month: str
    opens_at: str
    cutoff_at: str
    fulfillment_lead_days: int
    mid_month_change_allowed: bool
    status: str
    election_count: int
    locked_at: Optional[str]


class BenefitAccount(MutableResource, total=False):
    employee_id: str
    benefit_category_id: str
    rollover_in_cents: int
    contributed_cents: int
    spent_cents: int
    forfeited_cents: int
    refunded_cents: int
    reversed_cents: int
    fee_charged_cents: int
    available_balance_cents: int
    ledger_entry_count: int


class LedgerEntry(AppendOnlyRecord, total=False):
    """Append-only: no ``updated_at`` and no ``version``."""

    benefit_account_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    source_entity: str
    source_id: str
    reason: Optional[str]


class Election(MutableResource, total=False):
    employee_id: str
    election_window_id: str
    benefit_category_id: str
    benefit_account_id: str
    transit_media_id: Optional[str]
    superseded_election_id: Optional[str]
    pretax_amount_cents: int
    posttax_amount_cents: int
    total_amount_cents: int
    excluded_amount_cents: int
    posttax_spill_cents: int
    posttax_effective_cents: int
    exclusion_basis: str
    entitled_media_units: int
    change_count: int
    funding_status: str
    fulfillment_status: str


class TransitMedia(MutableResource, total=False):
    sku: str
    media_type: str
    region_code: str
    eligible_category_type: str
    unit_price_cents: int
    lead_days: int
    replacement_fee_cents: int
    requires_physical_fulfillment: bool
    status: str


class OrderBatch(MutableResource, total=False):
    election_window_id: str
    region_code: str
    status: str
    line_count: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    sealed_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    sealed_at: Optional[str]


class MediaOrder(MutableResource, total=False):
    election_id: str
    transit_media_id: str
    order_batch_id: str
    superseded_media_order_id: Optional[str]
    quantity: int
    coverage_start_at: str
    coverage_end_at: str
    unit_price_cents_snapshot: int
    line_gross_cents: int
    line_surcharge_cents: int
    line_total_cents: int
    status: str
    tracking_ref: Optional[str]
    undelivered_reason: Optional[str]
    replacement_count: int
    replacement_fee_charged_cents: int


class CardTransaction(MutableResource, total=False):
    election_id: str
    benefit_account_id: str
    amount_cents: int
    merchant_category_code: int
    merchant_name: str
    transaction_at: str
    substantiation_status: str
    posted_spend_cents: int
    reopen_count: int
    approved_by_user_id: Optional[str]
    denied_by_user_id: Optional[str]


class SubstantiationClaim(MutableResource, total=False):
    card_transaction_id: str
    claimed_amount_cents: int
    doc_type: str
    status: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class PayrollFile(MutableResource, total=False):
    employer_id: str
    period_month: str
    status: str
    participant_count: int
    total_pretax_cents: int
    total_posttax_cents: int
    admin_fee_cents: int
    pre_waiver_charge_cents: int
    fee_waiver_cents: int
    employer_charge_cents: int
    transmitted_at: Optional[str]
    acknowledgement_code: Optional[str]


class ComplianceAssessment(AppendOnlyRecord, total=False):
    """Append-only: no ``updated_at`` and no ``version``."""

    employer_id: str
    assessment_month: str
    covered_employee_count: int
    qualifying_transit_offering_count: int
    assessed_transit_group_limit_cents: int
    mandate_status: str
    finding: str


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
