"""Composite setup builders.

Every test starts against an empty database, so all preconditions are built
here through the public API. Builders return plain dicts of the entities and
identifiers a test needs, and each accepts **overrides so a single field can be
pinned without rewriting the chain.

Identity matters: the OperatorBuyer's X-User-ID must be the Operator id and the
ManufacturerRep's X-User-ID must be the Manufacturer id, so every builder that
performs an ownership-gated call threads the entity id into its headers.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import AUG_05, SEP_START, TERM_START
from .test_users import (
    ACCOUNTANT_USER_ID,
    ANALYST_USER_ID,
    AUDITOR_USER_ID,
    NAM_USER_ID,
    make_contract_auditor_headers,
    make_manufacturer_rep_headers,
    make_national_account_manager_headers,
    make_operator_buyer_headers,
    make_pricing_analyst_headers,
    make_rebate_accountant_headers,
    make_system_admin_headers,
)

ADMIN = make_system_admin_headers()
NAM = make_national_account_manager_headers(NAM_USER_ID)
ANALYST = make_pricing_analyst_headers(ANALYST_USER_ID)
ACCOUNTANT = make_rebate_accountant_headers(ACCOUNTANT_USER_ID)
AUDITOR = make_contract_auditor_headers(AUDITOR_USER_ID)


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock and run the expiry sweep."""
    return get_success_data(api_client.set_clock(f.clock_payload(to_iso8601), ADMIN))


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

def create_operator(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_operator(f.operator_payload(**overrides), ADMIN)
    )


def create_manufacturer(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_manufacturer(f.manufacturer_payload(**overrides), ADMIN)
    )


def create_distribution_center(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_distribution_center(
            f.distribution_center_payload(**overrides), ADMIN
        )
    )


def create_product(manufacturer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_product(f.product_payload(manufacturer_id, **overrides), ADMIN)
    )


def set_availability(product_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_product_availability(
            product_id, f.availability_payload(**overrides), ADMIN
        )
    )


def bootstrap_partners(
    operator: Optional[Dict[str, Any]] = None,
    manufacturer: Optional[Dict[str, Any]] = None,
    distribution_center: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Operator, manufacturer and distribution center, plus the two
    entity-backed header sets bound to their ids."""
    op = create_operator(**(operator or {}))
    mfg = create_manufacturer(**(manufacturer or {}))
    dc = create_distribution_center(**(distribution_center or {}))
    return {
        "operator": op,
        "operator_id": op["id"],
        "manufacturer": mfg,
        "manufacturer_id": mfg["id"],
        "dc": dc,
        "dc_id": dc["id"],
        "buyer": make_operator_buyer_headers(op["id"]),
        "rep": make_manufacturer_rep_headers(mfg["id"]),
    }


# --------------------------------------------------------------------------
# Contract construction
# --------------------------------------------------------------------------

def create_contract_draft(
    operator_id: str, manufacturer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_contract(
            f.contract_payload(operator_id, manufacturer_id, **overrides), NAM
        )
    )


def add_tier(contract_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_contract_tier(
            f.contract_tier_payload(contract_id, **overrides), NAM
        )
    )


def add_coverage(
    contract_id: str, distribution_center_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_dc_coverage(
            f.dc_coverage_payload(contract_id, distribution_center_id, **overrides), NAM
        )
    )


def add_substitution_rule(
    contract_id: str,
    primary_product_id: str,
    substitute_product_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_substitution_rule(
            f.substitution_rule_payload(
                contract_id, primary_product_id, substitute_product_id, **overrides
            ),
            NAM,
        )
    )


def sign_contract(contract_id: str, operator_id: str) -> Dict[str, Any]:
    """Submit a configured draft for signature and have its own operator sign."""
    get_success_data(api_client.submit_contract_for_signature(contract_id, NAM))
    return get_success_data(
        api_client.sign_contract(contract_id, make_operator_buyer_headers(operator_id))
    )


def build_signed_contract(
    operator_id: str,
    manufacturer_id: str,
    distribution_center_id: str,
    tiers: Optional[List[Dict[str, Any]]] = None,
    coverages: Optional[List[Dict[str, Any]]] = None,
    **contract_overrides: Any,
) -> Dict[str, Any]:
    """A contract with its markup tiers and coverage in place, walked through
    signature so it is ACTIVE. `tiers` and `coverages` are lists of field
    overrides; one PROTEIN tier and one in-market coverage are used by default.
    """
    contract = create_contract_draft(operator_id, manufacturer_id, **contract_overrides)
    contract_id = contract["id"]

    tier_specs = tiers if tiers is not None else [{}]
    created_tiers = [add_tier(contract_id, **spec) for spec in tier_specs]

    coverage_specs = coverages if coverages is not None else [{}]
    created_coverages = [
        add_coverage(contract_id, distribution_center_id, **spec)
        for spec in coverage_specs
    ]

    signed = sign_contract(contract_id, operator_id)
    return {
        "contract": signed,
        "contract_id": contract_id,
        "contract_version": signed["version"],
        "tiers": created_tiers,
        "tier_ids": [tier["id"] for tier in created_tiers],
        "coverages": created_coverages,
        "coverage_ids": [cov["id"] for cov in created_coverages],
    }


def read_contract_version(contract_id: str) -> int:
    """The current contract version, re-read so an optimistic-concurrency guard
    on a create is satisfied."""
    return get_success_data(api_client.get_contract(contract_id, NAM))["version"]


# --------------------------------------------------------------------------
# Rebate periods
# --------------------------------------------------------------------------

def open_rebate_period(
    contract_id: str,
    period_start: str = TERM_START,
    period_end: str = SEP_START,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_rebate_period(
            f.rebate_period_payload(contract_id, period_start, period_end, **overrides),
            ACCOUNTANT,
        )
    )


def close_rebate_period(rebate_period_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_rebate_period(rebate_period_id, ACCOUNTANT)
    )


def settle_rebate_period(
    rebate_period_id: str, settlement_reference: str = "ACH-HLG-2026-08"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.settle_rebate_period(
            rebate_period_id, {"settlement_reference": settlement_reference}, ACCOUNTANT
        )
    )


# --------------------------------------------------------------------------
# Order lines
# --------------------------------------------------------------------------

def create_order_line(
    contract_id: str,
    product_id: str,
    distribution_center_id: str,
    operator_id: str,
    quantity_cases: int = 300,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_order_line(
            f.order_line_payload(
                contract_id,
                product_id,
                distribution_center_id,
                quantity_cases,
                **overrides,
            ),
            make_operator_buyer_headers(operator_id),
        )
    )


def substitute_order_line(
    order_line_id: str, operator_id: str, **payload: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.substitute_order_line(
            order_line_id, make_operator_buyer_headers(operator_id), payload or None
        )
    )


def invoice_order_line(order_line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.invoice_order_line(order_line_id, NAM))


def reprice_order_line(order_line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reprice_order_line(order_line_id, NAM))


def create_invoiced_line(
    contract_id: str,
    product_id: str,
    distribution_center_id: str,
    operator_id: str,
    quantity_cases: int = 300,
    order_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """Price a line at an optional clock instant and invoice it, which opens the
    bill-back dimension."""
    if order_clock is not None:
        set_clock(order_clock)
    line = create_order_line(
        contract_id, product_id, distribution_center_id, operator_id, quantity_cases
    )
    return invoice_order_line(line["id"])


# --------------------------------------------------------------------------
# Deviated pricing
# --------------------------------------------------------------------------

def create_deviation(
    contract_id: str,
    product_id: str,
    manufacturer_id: str,
    max_operator_price_cents: int,
    effective_from: str = TERM_START,
    effective_to: str = SEP_START,
    expected_contract_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a deviated price. The contract version is re-read unless the caller
    pins one, so the concurrency guard is satisfied."""
    version = (
        expected_contract_version
        if expected_contract_version is not None
        else read_contract_version(contract_id)
    )
    return get_success_data(
        api_client.create_deviation_agreement(
            f.deviation_agreement_payload(
                contract_id,
                product_id,
                manufacturer_id,
                version,
                max_operator_price_cents,
                effective_from,
                effective_to,
                **overrides,
            ),
            ANALYST,
        )
    )


def submit_deviation(deviation_agreement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_deviation_agreement(deviation_agreement_id, ANALYST)
    )


def decide_deviation(
    deviation_agreement_id: str,
    manufacturer_id: str,
    decision: str = "APPROVE",
    decision_note: str = "Approved per national program",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_deviation_agreement(
            deviation_agreement_id,
            f.manufacturer_decision_payload(decision, decision_note),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def activate_deviation(deviation_agreement_id: str) -> Dict[str, Any]:
    """Activation is performed by a manager who is not the submitting analyst."""
    return get_success_data(
        api_client.activate_deviation_agreement(deviation_agreement_id, NAM)
    )


def build_active_deviation(
    contract_id: str,
    product_id: str,
    manufacturer_id: str,
    max_operator_price_cents: int,
    effective_from: str = TERM_START,
    effective_to: str = SEP_START,
    stage: str = "ACTIVE",
    **overrides: Any,
) -> Dict[str, Any]:
    """Walk a deviation agreement up to `stage`: DRAFT, SUBMITTED,
    MANUFACTURER_APPROVED or ACTIVE."""
    agreement = create_deviation(
        contract_id,
        product_id,
        manufacturer_id,
        max_operator_price_cents,
        effective_from,
        effective_to,
        **overrides,
    )
    if stage == "DRAFT":
        return agreement
    agreement = submit_deviation(agreement["id"])
    if stage == "SUBMITTED":
        return agreement
    agreement = decide_deviation(agreement["id"], manufacturer_id)
    if stage == "MANUFACTURER_APPROVED":
        return agreement
    return activate_deviation(agreement["id"])


def read_deviation_version(deviation_agreement_id: str) -> int:
    return get_success_data(
        api_client.get_deviation_agreement(deviation_agreement_id, ANALYST)
    )["version"]


# --------------------------------------------------------------------------
# Cost change notices
# --------------------------------------------------------------------------

def create_notice(
    contract_id: str, product_id: str, effective_at: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_price_change_notice(
            f.price_change_notice_payload(
                contract_id, product_id, effective_at, **overrides
            ),
            ANALYST,
        )
    )


def acknowledge_notice(price_change_notice_id: str, operator_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.acknowledge_price_change_notice(
            price_change_notice_id, make_operator_buyer_headers(operator_id)
        )
    )


def activate_notice(price_change_notice_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.activate_price_change_notice(price_change_notice_id, ANALYST)
    )


def withdraw_notice(price_change_notice_id: str, reason: str = "Superseded") -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_price_change_notice(
            price_change_notice_id, ANALYST, {"reason": reason}
        )
    )


# --------------------------------------------------------------------------
# Bill-back claims, remittances
# --------------------------------------------------------------------------

def create_claim(
    deviation_agreement_id: str,
    claim_period_start: str = TERM_START,
    claim_period_end: str = SEP_START,
    expected_deviation_agreement_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_deviation_agreement_version
        if expected_deviation_agreement_version is not None
        else read_deviation_version(deviation_agreement_id)
    )
    return get_success_data(
        api_client.create_bill_back_claim(
            f.bill_back_claim_payload(
                deviation_agreement_id,
                claim_period_start,
                claim_period_end,
                version,
                **overrides,
            ),
            ACCOUNTANT,
        )
    )


def submit_claim(bill_back_claim_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_bill_back_claim(bill_back_claim_id, ACCOUNTANT)
    )


def build_submitted_claim(
    deviation_agreement_id: str,
    claim_period_start: str = TERM_START,
    claim_period_end: str = SEP_START,
    **overrides: Any,
) -> Dict[str, Any]:
    claim = create_claim(
        deviation_agreement_id, claim_period_start, claim_period_end, **overrides
    )
    return submit_claim(claim["id"])


def create_remittance(
    manufacturer_id: str,
    remitted_amount_cents: int,
    remittance_reference: str = "CPC-WIRE-0001",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_bill_back_remittance(
            f.bill_back_remittance_payload(
                manufacturer_id, remitted_amount_cents, remittance_reference
            ),
            ACCOUNTANT,
        )
    )


def reverse_remittance(
    bill_back_remittance_id: str, reason: str = "Wire recalled by manufacturer treasury"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.reverse_bill_back_remittance(
            bill_back_remittance_id, {"reason": reason}, ACCOUNTANT
        )
    )


# --------------------------------------------------------------------------
# Pricing disputes
# --------------------------------------------------------------------------

def create_dispute(
    order_line_id: str,
    operator_id: str,
    claimed_correct_unit_price_cents: int,
    dispute_reason: str = "TIER_MISAPPLIED",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pricing_dispute(
            f.pricing_dispute_payload(
                order_line_id, claimed_correct_unit_price_cents, dispute_reason
            ),
            make_operator_buyer_headers(operator_id),
        )
    )


def start_audit(pricing_dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_dispute_audit(pricing_dispute_id, AUDITOR))


def resolve_dispute(
    pricing_dispute_id: str, resolution: str = "UPHELD", note: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_pricing_dispute(
            pricing_dispute_id, f.dispute_resolution_payload(resolution, note), AUDITOR
        )
    )


def issue_credit(pricing_dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.issue_dispute_credit(pricing_dispute_id, AUDITOR))


# --------------------------------------------------------------------------
# Whole-scenario compositions
# --------------------------------------------------------------------------

def build_priced_world(
    tiers: Optional[List[Dict[str, Any]]] = None,
    coverages: Optional[List[Dict[str, Any]]] = None,
    product: Optional[Dict[str, Any]] = None,
    contract: Optional[Dict[str, Any]] = None,
    period_start: str = TERM_START,
    period_end: str = SEP_START,
    order_clock: str = AUG_05,
) -> Dict[str, Any]:
    """Partners, a product, an ACTIVE contract with tiers and coverage, an open
    rebate period, and the clock parked inside that period. No order lines yet.
    """
    world = bootstrap_partners()
    prod = create_product(world["manufacturer_id"], **(product or {}))
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=tiers,
        coverages=coverages,
        **(contract or {}),
    )
    period = open_rebate_period(signed["contract_id"], period_start, period_end)
    set_clock(order_clock)

    world.update(signed)
    world["product"] = prod
    world["product_id"] = prod["id"]
    world["rebate_period"] = period
    world["rebate_period_id"] = period["id"]
    return world


def build_invoiced_line_world(
    quantity_cases: int = 300,
    tiers: Optional[List[Dict[str, Any]]] = None,
    coverages: Optional[List[Dict[str, Any]]] = None,
    product: Optional[Dict[str, Any]] = None,
    contract: Optional[Dict[str, Any]] = None,
    period_start: str = TERM_START,
    period_end: str = SEP_START,
    order_clock: str = AUG_05,
) -> Dict[str, Any]:
    """`build_priced_world` plus one invoiced order line."""
    world = build_priced_world(
        tiers=tiers,
        coverages=coverages,
        product=product,
        contract=contract,
        period_start=period_start,
        period_end=period_end,
        order_clock=order_clock,
    )
    line = create_order_line(
        world["contract_id"],
        world["product_id"],
        world["dc_id"],
        world["operator_id"],
        quantity_cases,
    )
    world["order_line"] = invoice_order_line(line["id"])
    world["order_line_id"] = line["id"]
    return world


def build_closed_period_world(
    quantity_cases: int = 300,
    tiers: Optional[List[Dict[str, Any]]] = None,
    coverages: Optional[List[Dict[str, Any]]] = None,
    product: Optional[Dict[str, Any]] = None,
    contract: Optional[Dict[str, Any]] = None,
    period_start: str = TERM_START,
    period_end: str = SEP_START,
    order_clock: str = AUG_05,
    close_clock: str = SEP_START,
) -> Dict[str, Any]:
    """`build_invoiced_line_world` walked past the period end and closed, so the
    period carries its compliance and rebate figures."""
    world = build_invoiced_line_world(
        quantity_cases=quantity_cases,
        tiers=tiers,
        coverages=coverages,
        product=product,
        contract=contract,
        period_start=period_start,
        period_end=period_end,
        order_clock=order_clock,
    )
    set_clock(close_clock)
    world["rebate_period"] = close_rebate_period(world["rebate_period_id"])
    return world


def build_two_band_pricing_world(
    period_start: str = TERM_START,
    period_end: str = SEP_START,
    first_order_clock: str = AUG_05,
    second_order_clock: str = "2026-08-10T00:00:00Z",
    close_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """A PROTEIN contract carrying two markup bands — 12.50 percent on
    [0, 500) and 9.00 percent on [500, unbounded) — with two invoiced 300-case
    lines placed on different days, so the class volume crosses the band edge
    only after both lines exist. Closes the period when `close_clock` is given.
    """
    world = bootstrap_partners()
    product = create_product(world["manufacturer_id"])
    signed = build_signed_contract(
        world["operator_id"],
        world["manufacturer_id"],
        world["dc_id"],
        tiers=[
            {"markup_value": 12.50, "min_case_volume": 0, "max_case_volume": 500},
            {"markup_value": 9.00, "min_case_volume": 500},
        ],
    )
    world.update(signed)
    world["product"] = product
    world["product_id"] = product["id"]
    world["tier_low_id"] = signed["tier_ids"][0]
    world["tier_high_id"] = signed["tier_ids"][1]

    period = open_rebate_period(signed["contract_id"], period_start, period_end)
    world["rebate_period"] = period
    world["rebate_period_id"] = period["id"]

    set_clock(first_order_clock)
    line_a = create_order_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        300,
    )
    world["line_a"] = invoice_order_line(line_a["id"])
    world["line_a_id"] = line_a["id"]

    set_clock(second_order_clock)
    line_b = create_order_line(
        signed["contract_id"],
        product["id"],
        world["dc_id"],
        world["operator_id"],
        300,
    )
    world["line_b"] = invoice_order_line(line_b["id"])
    world["line_b_id"] = line_b["id"]

    if close_clock is not None:
        set_clock(close_clock)
        world["rebate_period"] = close_rebate_period(period["id"])
    return world


def build_deviated_line_world(
    deviation_max_operator_price_cents: int = 4500,
    deviation_overrides: Optional[Dict[str, Any]] = None,
    quantity_cases: int = 300,
    tiers: Optional[List[Dict[str, Any]]] = None,
    coverages: Optional[List[Dict[str, Any]]] = None,
    product: Optional[Dict[str, Any]] = None,
    contract: Optional[Dict[str, Any]] = None,
    period_start: str = TERM_START,
    period_end: str = SEP_START,
    deviation_from: str = TERM_START,
    deviation_to: str = SEP_START,
    order_clock: str = AUG_05,
) -> Dict[str, Any]:
    """An ACTIVE deviation on the contracted product plus one order line priced
    against it and invoiced, so the bill-back dimension is accrued."""
    world = build_priced_world(
        tiers=tiers,
        coverages=coverages,
        product=product,
        contract=contract,
        period_start=period_start,
        period_end=period_end,
        order_clock=order_clock,
    )
    agreement = build_active_deviation(
        world["contract_id"],
        world["product_id"],
        world["manufacturer_id"],
        deviation_max_operator_price_cents,
        deviation_from,
        deviation_to,
        **(deviation_overrides or {}),
    )
    line = create_order_line(
        world["contract_id"],
        world["product_id"],
        world["dc_id"],
        world["operator_id"],
        quantity_cases,
    )
    world["deviation"] = agreement
    world["deviation_id"] = agreement["id"]
    world["order_line"] = invoice_order_line(line["id"])
    world["order_line_id"] = line["id"]
    return world
