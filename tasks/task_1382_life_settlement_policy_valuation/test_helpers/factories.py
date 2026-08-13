"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "BROKER_NAME": "Broker One",
    "BROKER_LICENSE": "BR-1",
    "STATE": "TX",
    "INSURED_NAME": "Pat Doe",
    "DOB": "1960-01-01",
    "GENDER": "M",
    "SMOKER": "NON_TOBACCO",
    "SSN4": "1234",
    "CARRIER": "CarrierCo",
    "FACE": 10000000,
    "POLICY_TYPE": "WHOLE_LIFE",
    "ISSUE_DATE": "2023-01-01",
    "ANNUAL_PREMIUM": 600000,
    "LICENSE_NUMBER": "LIC-TX-1",
    "LICENSE_EFFECTIVE": "2026-01-01",
    "LICENSE_EXPIRY": "2027-12-31",
    "OFFER_AMOUNT": 6000000,
    "COMMISSION_BPS": 455,
    "LE_BASE": 120,
    "LE_DEBITS": [0.1, 0.2],
    "PORTFOLIO_NAME": "PRO",
    "DISCOUNT_RATE_BPS": 1200,
    "VALUATION_METHOD": "PROSPECTIVE",
}

# The five disclosure packet types required before any offer acceptance (PRD §3.2).
DISCLOSURE_PACKET_TYPES = ["COMPENSATION", "ALTERNATIVES", "TAX", "PRIVACY", "RESCISSION_RIGHTS"]

# Required closing-document checklist for a TX insured (no STATE_SUPPLEMENT) (PRD §3.4).
TX_REQUIRED_DOC_TYPES = [
    "CHANGE_OF_OWNERSHIP",
    "CHANGE_OF_BENEFICIARY",
    "COMPENSATION_DISCLOSURE",
    "ALTERNATIVES_DISCLOSURE",
    "TAX_DISCLOSURE",
    "PRIVACY_NOTICE",
    "RESCISSION_NOTICE",
]

# CA / NY insureds additionally require STATE_SUPPLEMENT (PRD §3.4).
CA_REQUIRED_DOC_TYPES = TX_REQUIRED_DOC_TYPES + ["STATE_SUPPLEMENT"]


def create_broker_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BROKER_NAME"],
        "license_number": DEFAULTS["BROKER_LICENSE"],
        "state_code": DEFAULTS["STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_investor_payload(**overrides) -> dict:
    defaults = {"name": "Inv One", "investor_type": "FUND"}
    defaults.update(overrides)
    return defaults


def create_insured_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["INSURED_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "state_code": DEFAULTS["STATE"],
        "gender": DEFAULTS["GENDER"],
        "smoker_status": DEFAULTS["SMOKER"],
        "ssn_last4": DEFAULTS["SSN4"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(insured_id, **overrides) -> dict:
    defaults = {
        "insured_id": insured_id,
        "carrier_name": DEFAULTS["CARRIER"],
        "policy_number": "P-1",
        "face_amount_cents": DEFAULTS["FACE"],
        "policy_type": DEFAULTS["POLICY_TYPE"],
        "issue_date": DEFAULTS["ISSUE_DATE"],
        "annual_premium_cents": DEFAULTS["ANNUAL_PREMIUM"],
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "effective_date": DEFAULTS["LICENSE_EFFECTIVE"],
        "expiry_date": DEFAULTS["LICENSE_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_le_report_order_payload(**overrides) -> dict:
    defaults = {"underwriter_tier": "A"}
    defaults.update(overrides)
    return defaults


def create_le_report_deliver_payload(**overrides) -> dict:
    defaults = {
        "base_le_months": DEFAULTS["LE_BASE"],
        "impairment_debits": list(DEFAULTS["LE_DEBITS"]),
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {"amount_cents": DEFAULTS["OFFER_AMOUNT"]}
    defaults.update(overrides)
    return defaults


def create_portfolio_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PORTFOLIO_NAME"],
        "discount_rate_bps": DEFAULTS["DISCOUNT_RATE_BPS"],
        "valuation_method": DEFAULTS["VALUATION_METHOD"],
        "allocations": [],
    }
    defaults.update(overrides)
    return defaults


def create_tracking_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "OBIT_SEARCH",
        "outcome": "DEATH_INDICATED",
        "source_channel": "OBIT",
        "event_date": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults
