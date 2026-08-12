"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "LANDLORD_NAME": "Landlord L",
    "CONTACT_EMAIL": "owner@example.com",
    "TENANT_NAME": "Tenant T",
    "YEARS_EXPERIENCE": 5,
    "FIELD_NAME": "Field F",
    "ACRES": 100,
    "SOIL_CSR2": 80,
    "TERM_YEARS": 1,
    "TERM_START": "2027-03-01T00:00:00Z",
    "TERM_END": "2028-03-01T00:00:00Z",
    "MIN_BID_PER_ACRE_CENTS": 20000,
    "REFERENCE_YIELD_BU_PER_ACRE": 200,
    "REFERENCE_PRICE_CENTS_PER_BU": 500,
    "BID_DEADLINE": "2026-06-15T00:00:00Z",
    "CASH_BID_PER_ACRE_CENTS": 25000,
    "FLEX_BASE_PER_ACRE_CENTS": 20000,
    "FLEX_BONUS_PCT": 0.2,
    "FLEX_CAP_CENTS": 500000,
    "REVENUE_TRIGGER_CENTS": 9000000,
    "FLEX_CE_BID_PER_ACRE": 22000,
    "SHARE_LANDLORD_SHARE_PCT": 0.4,
    "SHARE_INPUT_SHARE_PCT": 0.5,
    "SHARE_CE_BID_PER_ACRE": 25000,
    "PAYMENT_PATTERN": "MAR_NOV_50_50",
    "ESCALATION_TYPE": "NONE",
    "CROP_YEAR": 2027,
    "YIELD_BU_PER_ACRE": 200,
    "HARVEST_PRICE_CENTS_PER_BU": 500,
    "EXPENSE_CATEGORY": "SEED",
    "EXPENSE_TOTAL_COST_CENTS": 50000,
    "EXPENSE_INCURRED_DATE": "2027-04-10T00:00:00Z",
    "PROJECT_TYPE": "LIMING",
    "PROJECT_TOTAL_COST_CENTS": 500000,
    "REIMBURSEMENT_METHOD": "STRAIGHT_LINE",
    "AMORTIZATION_YEARS": 3,
    "REPORT_TYPE": "QUARTERLY",
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-03-31T00:00:00Z",
}


def create_landlord_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["LANDLORD_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_tenant_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TENANT_NAME"],
        "years_experience": DEFAULTS["YEARS_EXPERIENCE"],
    }
    payload.update(overrides)
    return payload


def create_field_payload(landlord_id: str, **overrides) -> dict:
    payload = {
        "landlord_id": landlord_id,
        "name": DEFAULTS["FIELD_NAME"],
        "acres": DEFAULTS["ACRES"],
        "soil_csr2": DEFAULTS["SOIL_CSR2"],
    }
    payload.update(overrides)
    return payload


def create_offering_payload(field_id: str, **overrides) -> dict:
    payload = {
        "field_id": field_id,
        "term_years": DEFAULTS["TERM_YEARS"],
        "term_start_date": DEFAULTS["TERM_START"],
        "min_bid_per_acre_cents": DEFAULTS["MIN_BID_PER_ACRE_CENTS"],
        "reference_yield_bu_per_acre": DEFAULTS["REFERENCE_YIELD_BU_PER_ACRE"],
        "reference_price_cents_per_bu": DEFAULTS["REFERENCE_PRICE_CENTS_PER_BU"],
        "bid_deadline": DEFAULTS["BID_DEADLINE"],
    }
    payload.update(overrides)
    return payload


def create_bid_payload(offering_id: str, lease_type: str = "CASH", **overrides) -> dict:
    """Bid payload with the conditional amount parameters the declared
    lease_type requires (PRD §3.2); cash_equivalent_bid_cents_per_acre is
    always required regardless of type."""
    payload = {
        "offering_id": offering_id,
        "lease_type": lease_type,
    }
    if lease_type == "CASH":
        payload["cash_bid_per_acre_cents"] = DEFAULTS["CASH_BID_PER_ACRE_CENTS"]
        payload["cash_equivalent_bid_cents_per_acre"] = DEFAULTS["CASH_BID_PER_ACRE_CENTS"]
    elif lease_type == "FLEX":
        payload["flex_base_per_acre_cents"] = DEFAULTS["FLEX_BASE_PER_ACRE_CENTS"]
        payload["flex_bonus_pct"] = DEFAULTS["FLEX_BONUS_PCT"]
        payload["flex_cap_cents"] = DEFAULTS["FLEX_CAP_CENTS"]
        payload["revenue_trigger_cents"] = DEFAULTS["REVENUE_TRIGGER_CENTS"]
        payload["cash_equivalent_bid_cents_per_acre"] = DEFAULTS["FLEX_CE_BID_PER_ACRE"]
    elif lease_type == "SHARE":
        payload["landlord_share_pct"] = DEFAULTS["SHARE_LANDLORD_SHARE_PCT"]
        payload["input_share_pct"] = DEFAULTS["SHARE_INPUT_SHARE_PCT"]
        payload["cash_equivalent_bid_cents_per_acre"] = DEFAULTS["SHARE_CE_BID_PER_ACRE"]
    payload.update(overrides)
    return payload


def create_lease_payload(bid_id: str, **overrides) -> dict:
    payload = {
        "bid_id": bid_id,
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
        "payment_pattern": DEFAULTS["PAYMENT_PATTERN"],
        "escalation_type": DEFAULTS["ESCALATION_TYPE"],
    }
    payload.update(overrides)
    return payload


def record_payment_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def waive_installment_payload(reason: str = "manager waiver", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def create_settlement_payload(lease_id: str, expected_lease_version: int, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "crop_year": DEFAULTS["CROP_YEAR"],
        "price_source": "ACTUAL",
        "yield_bu_per_acre": DEFAULTS["YIELD_BU_PER_ACRE"],
        "harvest_price_cents_per_bu": DEFAULTS["HARVEST_PRICE_CENTS_PER_BU"],
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def create_expense_payload(lease_id: str, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "category": DEFAULTS["EXPENSE_CATEGORY"],
        "total_cost_cents": DEFAULTS["EXPENSE_TOTAL_COST_CENTS"],
        "incurred_date": DEFAULTS["EXPENSE_INCURRED_DATE"],
        "crop_year": DEFAULTS["CROP_YEAR"],
    }
    payload.update(overrides)
    return payload


def evidence_payload(evidence_note: str = "practice completed and documented") -> dict:
    return {"evidence_note": evidence_note}


def reason_payload(reason: str = "reviewed by manager") -> dict:
    return {"reason": reason}


def create_improvement_payload(field_id: str, **overrides) -> dict:
    payload = {
        "field_id": field_id,
        "project_type": DEFAULTS["PROJECT_TYPE"],
        "total_cost_cents": DEFAULTS["PROJECT_TOTAL_COST_CENTS"],
        "landlord_share_pct": 0.5,
        "tenant_share_pct": 0.5,
        "reimbursement_method": DEFAULTS["REIMBURSEMENT_METHOD"],
        "amortization_years": DEFAULTS["AMORTIZATION_YEARS"],
    }
    payload.update(overrides)
    return payload


def create_notice_payload(lease_id: str, served_by: str = "LANDLORD") -> dict:
    return {"lease_id": lease_id, "served_by": served_by}


def create_report_payload(landlord_id: str, **overrides) -> dict:
    payload = {
        "landlord_id": landlord_id,
        "report_type": DEFAULTS["REPORT_TYPE"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    payload.update(overrides)
    return payload
