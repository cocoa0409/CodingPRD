"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS as D


def create_network_payload(**overrides) -> dict:
    defaults = {"name": D["NETWORK_NAME"], "line_of_business": D["NETWORK_LOB"]}
    defaults.update(overrides)
    return defaults


def create_benchmark_payload(**overrides) -> dict:
    defaults = {
        "benchmark_year": D["BENCHMARK_YEAR"],
        "locality_code": D["LOCALITY_CODE"],
        "hcpcs_code": D["HCPCS_CODE"],
        "benchmark_amount_cents": D["BENCHMARK_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_parity_rule_payload(**overrides) -> dict:
    defaults = {
        "line_of_business_a": "COMMERCIAL_PPO",
        "line_of_business_b": "MEDICARE_ADVANTAGE",
        "band_bps": 11000,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "legal_name": D["PROVIDER_NAME"],
        "tin": D["PROVIDER_TIN"],
        "npi": D["PROVIDER_NPI"],
        "locality_code": D["LOCALITY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "base_effective_date": D["BASE_EFFECTIVE_DATE"],
        "term_months": D["TERM_MONTHS"],
        "escalator_bps": D["ESCALATOR_BPS"],
        "escalator_mode": D["ESCALATOR_MODE"],
        "auto_renew": False,
    }
    defaults.update(overrides)
    return defaults


def create_contract_version_payload(**overrides) -> dict:
    defaults = {
        "version_number": 1,
        "effective_date": D["VERSION_EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_entry_payload(**overrides) -> dict:
    defaults = {
        "hcpcs_code": D["HCPCS_CODE"],
        "service_category": D["SERVICE_CATEGORY"],
        "rate_type": "PERCENT_OF_MEDICARE",
        "pct_of_medicare_bps": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_carve_out_payload(**overrides) -> dict:
    defaults = {
        "service_category": D["SERVICE_CATEGORY"],
        "override_type": "FLAT_RATE",
        "start_date": "2026-07-01",
        "end_date": "2026-12-31",
        "priority_rank": 1,
    }
    explicit = set(overrides)
    defaults.update(overrides)
    # PRD 3.5: the override payload matches the override_type — a flat-rate
    # override carries override_flat_cents, a percent-of-Medicare override
    # carries override_pct_bps, and an exclusion carries neither. Keys the
    # caller passed explicitly are always preserved verbatim.
    override_type = defaults["override_type"]
    if override_type == "FLAT_RATE":
        defaults.setdefault("override_flat_cents", 7777)
        if "override_pct_bps" not in explicit:
            defaults.pop("override_pct_bps", None)
    elif override_type == "PCT_OF_MEDICARE":
        defaults.setdefault("override_pct_bps", 10000)
        if "override_flat_cents" not in explicit:
            defaults.pop("override_flat_cents", None)
    else:  # EXCLUDE carries neither override field
        if "override_flat_cents" not in explicit:
            defaults.pop("override_flat_cents", None)
        if "override_pct_bps" not in explicit:
            defaults.pop("override_pct_bps", None)
    return defaults


def create_simulation_batch_payload(**overrides) -> dict:
    defaults = {"label": "B1"}
    defaults.update(overrides)
    return defaults


def create_simulation_claim_payload(**overrides) -> dict:
    defaults = {
        "hcpcs_code": D["HCPCS_CODE"],
        "service_category": D["SERVICE_CATEGORY"],
        "service_date": "2026-07-15",
        "billed_cents": 15000,
        "expected_allowed_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_paid_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_number": "CLM-1",
        "hcpcs_code": D["HCPCS_CODE"],
        "service_category": D["SERVICE_CATEGORY"],
        "service_date": "2026-08-10",
        "billed_cents": 15000,
        "paid_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_termination_notice_payload(**overrides) -> dict:
    defaults = {
        "notice_date": "2026-05-01",
        "termination_date": "2026-08-15",
        "reason": "WITHOUT_CAUSE",
    }
    defaults.update(overrides)
    return defaults


def create_continuity_case_payload(**overrides) -> dict:
    defaults = {
        "member_ref": "M1",
        "condition_category": "PREGNANCY",
        "treatment_end_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults
