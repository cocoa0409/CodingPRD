"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Client Co",
    "CONTACT_EMAIL": "client@example.com",
    "OPERATOR_NAME": "Ann Analyst",
    "COUNTY_NAME": "Test County",
    "STATE_CODE": "TX",
    "ASSET_TAG": "A-0001",
    "ACQUISITION_COST_CENTS": 100000,
    "ACQUISITION_DATE": "2026-01-05",
    "IN_SERVICE_DATE": "2026-01-10",
    "TAX_YEAR": 2027,
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["OPERATOR_NAME"],
        "operator_role": "TAX_ANALYST",
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "county_name": DEFAULTS["COUNTY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "base_deadline_mmdd": "04-15",
        "max_extension_days": 30,
        "late_penalty_pct_per_month": 2,
        "max_late_penalty_pct": 10,
        "penalty_base": "VALUE_BASE",
        "tax_rate": 0.02,
        "offered_exemption_types": ["FREEPORT"],
        "max_exemption_pct": 50,
    }
    defaults.update(overrides)
    return defaults


def create_class_rule_payload(jurisdiction_id: str, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "category": "MACHINERY",
        "is_taxable": True,
        "depreciation_convention": "FULL_YEAR",
        "percent_good_vector": [100, 100],
        "percent_good_floor_pct": 10,
        "de_minimis_line_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(client_id: str, jurisdiction_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "jurisdiction_id": jurisdiction_id,
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "category": "MACHINERY",
        "acquisition_cost_cents": DEFAULTS["ACQUISITION_COST_CENTS"],
        "acquisition_date": DEFAULTS["ACQUISITION_DATE"],
        "in_service_date": DEFAULTS["IN_SERVICE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_disposal_payload(**overrides) -> dict:
    defaults = {
        "disposal_date": "2026-06-01",
        "disposal_proceeds_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_rendition_payload(client_id: str, jurisdiction_id: str, tax_year: int,
                             **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "jurisdiction_id": jurisdiction_id,
        "tax_year": tax_year,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(action: str = "OPEN", **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_extension_payload(requested_extend_to_date: str,
                             expected_rendition_version, **overrides) -> dict:
    defaults = {
        "requested_extend_to_date": requested_extend_to_date,
        "expected_rendition_version": expected_rendition_version,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(**overrides) -> dict:
    defaults = {
        "notice_value_cents": 800000,
        "received_date": "2027-05-01",
        "protest_deadline_date": "2027-05-31",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {
        "claimed_value_cents": 700000,
        "grounds": "overvaluation",
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(**overrides) -> dict:
    defaults = {"hearing_date": "2027-06-10"}
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {
        "decision": "GRANTED_REDUCTION",
        "decided_value_cents": 700000,
    }
    defaults.update(overrides)
    return defaults


def create_resolve_payload(resolution: str = "ACCEPT", **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


def create_tax_bill_payload(**overrides) -> dict:
    defaults = {
        "billed_amount_cents": 20000,
        "tax_rate": 0.025,
        "due_date": "2027-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_payment_schedule_payload(**overrides) -> dict:
    defaults = {"installment_count": 2}
    defaults.update(overrides)
    return defaults


def create_pay_installment_payload(installment_no: int = 1, **overrides) -> dict:
    defaults = {"installment_no": installment_no}
    defaults.update(overrides)
    return defaults


def create_exemption_application_payload(**overrides) -> dict:
    defaults = {
        "exemption_type": "FREEPORT",
        "exemption_pct": 30,
        "effective_date": "2027-01-01",
        "expiration_date": "2028-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_compliance_payload(action: str = "SUSPEND", **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_abatement_payload(**overrides) -> dict:
    defaults = {
        "first_tax_year": 2027,
        "last_tax_year": 2031,
        "abatement_pct": 50,
    }
    defaults.update(overrides)
    return defaults


def create_recertify_payload(tax_year: int, **overrides) -> dict:
    defaults = {"tax_year": tax_year}
    defaults.update(overrides)
    return defaults


def create_forecast_payload(tax_year: int, variant: str, as_of_date: str,
                            expected_client_version, **overrides) -> dict:
    defaults = {
        "tax_year": tax_year,
        "variant": variant,
        "as_of_date": as_of_date,
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
