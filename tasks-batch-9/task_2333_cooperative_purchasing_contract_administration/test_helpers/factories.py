"""Payload factories. Every factory returns a valid payload and accepts **overrides."""

from typing import Any

from .constants import (
    BASE_TERM_END,
    BASE_TERM_START,
    CART_BASE_PRICE_CENTS,
    CART_FLOOR_CENTS,
    DEFAULT_ADMIN_FEE_RATE_BPS,
    DISPENSER_BASE_PRICE_CENTS,
    DISPENSER_FLOOR_CENTS,
    LINER_BASE_PRICE_CENTS,
    LINER_FLOOR_CENTS,
    RESPONSE_DUE_AT,
    SEP_PERIOD_END,
    SEP_PERIOD_START,
    SKU_ADJUSTMENT,
    SKU_CART,
    SKU_DISPENSER,
    SKU_LINER,
)


def _merge(base: dict, overrides: dict) -> dict:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


_OMIT = object()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# State law configuration
# ---------------------------------------------------------------------------
def state_law_rule_payload(**overrides) -> dict:
    return _merge(
        {
            "state_code": "TX",
            "piggyback_doctrine": "STATUTORY_STRICT",
            "min_notice_days": 14,
            "requires_lead_agency_in_state": False,
            "allows_nonprofit_participation": True,
            "max_contract_term_months": 60,
            "requires_local_solicitation_waiver": False,
            "reciprocity_state_codes": [],
        },
        overrides,
    )


TX_RULE = dict(
    state_code="TX",
    piggyback_doctrine="STATUTORY_STRICT",
    min_notice_days=14,
    requires_lead_agency_in_state=False,
    allows_nonprofit_participation=True,
    max_contract_term_months=60,
    requires_local_solicitation_waiver=False,
    reciprocity_state_codes=[],
)

CA_RULE = dict(
    state_code="CA",
    piggyback_doctrine="STATUTORY_STRICT",
    min_notice_days=21,
    requires_lead_agency_in_state=True,
    allows_nonprofit_participation=True,
    max_contract_term_months=60,
    requires_local_solicitation_waiver=False,
    reciprocity_state_codes=[],
)

OR_RULE = dict(
    state_code="OR",
    piggyback_doctrine="RECIPROCITY_LIBERAL",
    min_notice_days=21,
    requires_lead_agency_in_state=False,
    allows_nonprofit_participation=True,
    max_contract_term_months=60,
    requires_local_solicitation_waiver=False,
    reciprocity_state_codes=["WA", "ID"],
)

ID_RULE = dict(
    state_code="ID",
    piggyback_doctrine="STATUTORY_STRICT",
    min_notice_days=23,
    requires_lead_agency_in_state=True,
    allows_nonprofit_participation=True,
    max_contract_term_months=60,
    requires_local_solicitation_waiver=False,
    reciprocity_state_codes=[],
)

OK_RULE = dict(
    state_code="OK",
    piggyback_doctrine="STATUTORY_STRICT",
    min_notice_days=30,
    requires_lead_agency_in_state=True,
    allows_nonprofit_participation=True,
    max_contract_term_months=36,
    requires_local_solicitation_waiver=False,
    reciprocity_state_codes=[],
)

NV_RULE = dict(
    state_code="NV",
    piggyback_doctrine="RECIPROCITY_LIBERAL",
    min_notice_days=30,
    requires_lead_agency_in_state=False,
    allows_nonprofit_participation=False,
    max_contract_term_months=60,
    requires_local_solicitation_waiver=True,
    reciprocity_state_codes=["CA"],
)


# ---------------------------------------------------------------------------
# Suppliers and solicitations
# ---------------------------------------------------------------------------
def supplier_payload(**overrides) -> dict:
    return _merge({"legal_name": "Acme Facility Supply LLC", "home_state_code": "TX"}, overrides)


def solicitation_payload(**overrides) -> dict:
    return _merge(
        {
            "title": "Janitorial Supplies and Equipment",
            "solicitation_number": "COOP-2026-001",
            "lead_agency_name": "Travis County Purchasing",
            "lead_agency_state_code": "TX",
            "response_due_at": RESPONSE_DUE_AT,
            "technical_weight_pct": 60.00,
            "price_weight_pct": 40.00,
            "specification_document_ref": "SPEC-COOP-2026-001",
            "method_justification_ref": "METH-COOP-2026-001",
        },
        overrides,
    )


def solicitation_response_payload(solicitation_id, supplier_id, **overrides) -> dict:
    return _merge(
        {
            "solicitation_id": solicitation_id,
            "supplier_id": supplier_id,
            "proposed_annual_value_cents": 1000000,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Master contracts and price-sheet lines
# ---------------------------------------------------------------------------
DEFAULT_DISCOUNT_TIERS: list[dict[str, Any]] = [
    {"tier_index": 0, "min_annual_spend_cents": 0, "discount_pct": 0.0000},
    {"tier_index": 1, "min_annual_spend_cents": 5000000, "discount_pct": 0.0500},
    {"tier_index": 2, "min_annual_spend_cents": 20000000, "discount_pct": 0.1800},
]

DEFAULT_PERMITTED_ADD_ONS: list[dict[str, Any]] = [
    {"code": "FREIGHT", "rate_pct": 0.0600, "cap_cents": 50000},
    {"code": "INSIDE_DELIVERY", "rate_pct": 0.0400, "cap_cents": 15000},
    {"code": "TRAINING", "rate_pct": 0.1000, "cap_cents": 100000},
]


def master_contract_payload(solicitation_id, supplier_id, **overrides) -> dict:
    return _merge(
        {
            "solicitation_id": solicitation_id,
            "supplier_id": supplier_id,
            "contract_number": "COOP-MC-2026-001",
            "admin_fee_rate_bps": DEFAULT_ADMIN_FEE_RATE_BPS,
            "base_term_start": BASE_TERM_START,
            "base_term_end": BASE_TERM_END,
            "max_renewals": 2,
            "price_escalation_cap_pct": 0.0500,
            "discount_tiers": [dict(t) for t in DEFAULT_DISCOUNT_TIERS],
            "permitted_add_ons": [dict(a) for a in DEFAULT_PERMITTED_ADD_ONS],
            "nationwide_pricing_flag": True,
        },
        overrides,
    )


def line_item_payload(**overrides) -> dict:
    return _merge(
        {
            "sku": SKU_DISPENSER,
            "item_description": "Wall dispenser, 500 sheet",
            "unit_of_measure": "EACH",
            "base_unit_price_cents": DISPENSER_BASE_PRICE_CENTS,
            "price_floor_cents": DISPENSER_FLOOR_CENTS,
        },
        overrides,
    )


DISPENSER_LINE = dict(
    sku=SKU_DISPENSER,
    item_description="Wall dispenser, 500 sheet",
    unit_of_measure="EACH",
    base_unit_price_cents=DISPENSER_BASE_PRICE_CENTS,
    price_floor_cents=DISPENSER_FLOOR_CENTS,
)

LINER_LINE = dict(
    sku=SKU_LINER,
    item_description="Can liner, 45 gallon, case of 100",
    unit_of_measure="CASE",
    base_unit_price_cents=LINER_BASE_PRICE_CENTS,
    price_floor_cents=LINER_FLOOR_CENTS,
)

CART_LINE = dict(
    sku=SKU_CART,
    item_description="Utility cart, 100 lb capacity",
    unit_of_measure="EACH",
    base_unit_price_cents=CART_BASE_PRICE_CENTS,
    price_floor_cents=CART_FLOOR_CENTS,
)

ADJUSTMENT_LINE = dict(
    sku=SKU_ADJUSTMENT,
    item_description="Administrative catalog adjustment unit, one cent per unit",
    unit_of_measure="EACH",
    base_unit_price_cents=1,
    price_floor_cents=1,
)


# ---------------------------------------------------------------------------
# Members, analyses, usage
# ---------------------------------------------------------------------------
def member_agency_payload(**overrides) -> dict:
    return _merge(
        {
            "legal_name": "Riverside Unified School District",
            "state_code": "CA",
            "member_category": "K12_DISTRICT",
            "annual_spend_ceiling_cents": 10000000,
            "governing_body_resolution_number": "RES-2026-114",
        },
        overrides,
    )


def piggyback_analysis_payload(member_agency_id, contract_id, expected_version, **overrides) -> dict:
    return _merge(
        {
            "member_agency_id": member_agency_id,
            "contract_id": contract_id,
            "expected_member_agency_version": expected_version,
        },
        overrides,
    )


def contract_usage_payload(contract_id, member_agency_id, line_item_id, analysis_id, **overrides):
    return _merge(
        {
            "contract_id": contract_id,
            "member_agency_id": member_agency_id,
            "line_item_id": line_item_id,
            "piggyback_analysis_id": analysis_id,
            "quantity": 1,
        },
        overrides,
    )


def price_quote_params(line_item_id, member_agency_id, quantity=1, **overrides) -> dict:
    return _merge(
        {
            "line_item_id": line_item_id,
            "member_agency_id": member_agency_id,
            "quantity": quantity,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Reports, amendments, complaints
# ---------------------------------------------------------------------------
def usage_report_payload(contract_id, **overrides) -> dict:
    return _merge(
        {
            "contract_id": contract_id,
            "period_start": SEP_PERIOD_START,
            "period_end": SEP_PERIOD_END,
        },
        overrides,
    )


def renewal_amendment_payload(contract_id, expected_version, requested_term_end, **overrides):
    return _merge(
        {
            "contract_id": contract_id,
            "amendment_type": "RENEWAL",
            "expected_contract_version": expected_version,
            "requested_term_end": requested_term_end,
        },
        overrides,
    )


def price_adjustment_amendment_payload(
    contract_id,
    expected_version,
    target_line_item_id,
    new_unit_price_cents,
    price_index="CPI_U",
    index_change_pct=0.0400,
    **overrides,
):
    return _merge(
        {
            "contract_id": contract_id,
            "amendment_type": "PRICE_ADJUSTMENT",
            "expected_contract_version": expected_version,
            "target_line_item_id": target_line_item_id,
            "new_unit_price_cents": new_unit_price_cents,
            "price_index": price_index,
            "index_change_pct": index_change_pct,
        },
        overrides,
    )


def expansion_amendment_payload(
    contract_id, expected_version, new_line_items, expansion_scope_overlap_pct=0.8000, **overrides
):
    return _merge(
        {
            "contract_id": contract_id,
            "amendment_type": "PRODUCT_LINE_EXPANSION",
            "expected_contract_version": expected_version,
            "new_line_items": new_line_items,
            "expansion_scope_overlap_pct": expansion_scope_overlap_pct,
        },
        overrides,
    )


def complaint_payload(contract_id, member_agency_id, **overrides) -> dict:
    return _merge(
        {
            "contract_id": contract_id,
            "member_agency_id": member_agency_id,
            "severity": "MAJOR",
            "category": "DELIVERY",
            "narrative": "Repeated late deliveries against the cooperative price sheet.",
        },
        overrides,
    )
