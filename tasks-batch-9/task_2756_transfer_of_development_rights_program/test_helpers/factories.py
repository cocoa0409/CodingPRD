"""Payload factories — one per creatable record, input fields only.

Every money field is emitted as a JSON integer number of cents, never as a
string.  Unique-constrained values (area `code`, parcel `apn`) draw from a
process-wide counter so a single test can create several of the same record
without colliding.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):04d}"


def unique_area_code(prefix: str = "AR") -> str:
    """A 3..16 character designation code unique within this process."""
    return f"{prefix}-{unique_suffix()}"


def unique_apn(prefix: str = "APN") -> str:
    """A 4..24 character assessor parcel number unique within this process."""
    return f"{prefix}-{unique_suffix()}"


def create_party_payload(kind: str = "LANDOWNER", **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "kind": kind,
        "legal_name": f"{kind.title()} Party {suffix}",
        "contact_email": f"party{suffix}@example.org",
        "neighborhood_code": "NB-EAST",
    }
    payload.update(overrides)
    return payload


def account_action_payload(action: str, expected_party_version: int, **overrides) -> dict:
    payload = {"action": action, "expected_party_version": expected_party_version}
    if action in ("CREDIT", "DEBIT"):
        payload["amount_cents"] = overrides.pop("amount_cents", 1_000_000)
    payload.update(overrides)
    return payload


def create_sending_area_payload(**overrides) -> dict:
    payload = {
        "code": unique_area_code("SND"),
        "name": "Test Sending Area",
        "neighborhood_code": "NB-EAST",
        "allocation_formula_version": "V1_NET_ACRE",
        "base_rate_units_per_acre": TEST_DEFAULTS["BASE_RATE_UNITS_PER_ACRE"],
        "gross_discount_factor": TEST_DEFAULTS["GROSS_DISCOUNT_FACTOR"],
        "equity_tier": "MODERATE",
        "sending_cap_units": TEST_DEFAULTS["SENDING_CAP_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_receiving_area_payload(**overrides) -> dict:
    payload = {
        "code": unique_area_code("RCV"),
        "name": "Test Receiving Area",
        "neighborhood_code": "NB-CORE",
        "base_density_units_per_acre": TEST_DEFAULTS["BASE_DENSITY_UNITS_PER_ACRE"],
        "max_bonus_pct": TEST_DEFAULTS["MAX_BONUS_PCT"],
        "absorption_cap_units": TEST_DEFAULTS["ABSORPTION_CAP_UNITS"],
        "design_review_required": False,
        "eligible_sending_area_codes": [],
    }
    payload.update(overrides)
    return payload


def create_appraisal_schedule_payload(**overrides) -> dict:
    payload = {
        "neighborhood_code": "NB-EAST",
        "per_unit_value_cents": TEST_DEFAULTS["PER_UNIT_VALUE_CENTS"],
        "equity_adjustment_bps": 0,
        "effective_from": "2026-01-01",
        "effective_to": "2027-01-01",
    }
    payload.update(overrides)
    return payload


def create_sending_parcel_payload(owner_party_id: str, sending_area_id: str, **overrides) -> dict:
    payload = {
        "owner_party_id": owner_party_id,
        "sending_area_id": sending_area_id,
        "apn": unique_apn(),
        "gross_acres": TEST_DEFAULTS["GROSS_ACRES"],
        "constrained_acres": TEST_DEFAULTS["CONSTRAINED_ACRES"],
        "soil_class": TEST_DEFAULTS["SOIL_CLASS"],
        "existing_dwelling_units": TEST_DEFAULTS["EXISTING_DWELLING_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_severance_application_payload(
    sending_parcel_id: str, applicant_party_id: str, requested_units: int, **overrides
) -> dict:
    payload = {
        "sending_parcel_id": sending_parcel_id,
        "applicant_party_id": applicant_party_id,
        "requested_units": requested_units,
    }
    payload.update(overrides)
    return payload


def review_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_inspection_payload(
    inspection_date: str, finding: str = "COMPLIANT", affected_acres: float = 0.00, **overrides
) -> dict:
    payload = {
        "inspection_date": inspection_date,
        "finding": finding,
        "affected_acres": affected_acres,
    }
    payload.update(overrides)
    return payload


def cure_verification_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def split_certificate_payload(units: int, expected_certificate_version: int, **overrides) -> dict:
    payload = {"units": units, "expected_certificate_version": expected_certificate_version}
    payload.update(overrides)
    return payload


def retire_certificate_payload(units: int, **overrides) -> dict:
    payload = {"units": units}
    payload.update(overrides)
    return payload


def create_market_transaction_payload(
    certificate_id: str,
    seller_party_id: str,
    buyer_party_id: str,
    units: int,
    channel: str = "PRIVATE",
    conveyance_mode: str = "WHOLE",
    **overrides,
) -> dict:
    payload = {
        "certificate_id": certificate_id,
        "seller_party_id": seller_party_id,
        "buyer_party_id": buyer_party_id,
        "channel": channel,
        "units": units,
        "conveyance_mode": conveyance_mode,
    }
    if channel == "PRIVATE":
        payload["agreed_price_cents"] = overrides.pop("agreed_price_cents", 1_000_000 * units)
    payload.update(overrides)
    return payload


def create_receiving_site_application_payload(
    developer_party_id: str, receiving_area_id: str,
    site_acres: float = 12.00, requested_bonus_units: int = 10, **overrides
) -> dict:
    payload = {
        "developer_party_id": developer_party_id,
        "receiving_area_id": receiving_area_id,
        "site_acres": site_acres,
        "requested_bonus_units": requested_bonus_units,
    }
    payload.update(overrides)
    return payload


def allocate_redemption_payload(
    certificate_id: str, units: int, expected_receiving_site_application_version: int, **overrides
) -> dict:
    payload = {
        "certificate_id": certificate_id,
        "units": units,
        "expected_receiving_site_application_version": expected_receiving_site_application_version,
    }
    payload.update(overrides)
    return payload


def design_review_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resubmit_design_payload(requested_bonus_units: int, **overrides) -> dict:
    payload = {"requested_bonus_units": requested_bonus_units}
    payload.update(overrides)
    return payload


def create_evaluation_payload(
    period_start: str, period_end: str, equity_weighting: str = "ACREAGE_WEIGHTED", **overrides
) -> dict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "equity_weighting": equity_weighting,
    }
    payload.update(overrides)
    return payload
