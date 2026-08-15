"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def _assert_append_only_fields(data: dict):
    """PRD §2.5: append-only records carry only id and created_at; both
    updated_at and version are absent from them entirely."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_authority(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["utility_territory_code"] in ["PGE", "SCE", "SDGE"]
    assert data["rate_setting_policy"] in [
        "COST_PLUS",
        "DISCOUNT_TO_INCUMBENT",
        "VALUE_BASED",
    ]
    assert data["status"] in ["FORMING", "ACTIVE", "SUSPENDED", "DISSOLVED"]
    assert isinstance(data["climate_reserve_balance_cents"], int)


def assert_service_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["utility_account_number"], str)
    assert data["service_class"] in [
        "RESIDENTIAL",
        "SMALL_COMMERCIAL",
        "LARGE_COMMERCIAL",
        "INDUSTRIAL",
        "AGRICULTURAL",
        "STREETLIGHT",
    ]
    assert data["enrollment_state"] in [
        "PROSPECT",
        "NOTICED",
        "ENROLLED",
        "OPTED_OUT",
        "OPTED_BACK_TO_BUNDLED",
        "CLOSED",
    ]
    assert data["product_election"] in ["DEFAULT", "OPT_UP_100", "OPT_DOWN_ECONOMY"]
    assert isinstance(data["cumulative_billed_cents"], int)
    assert isinstance(data["cumulative_remitted_cents"], int)
    assert isinstance(data["uncollectible_flag"], bool)


def assert_enrollment_notice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wave_label"], str)
    assert data["status"] in [
        "DRAFT",
        "ISSUED",
        "CLOSED",
        "ENROLLING",
        "SETTLED",
        "CANCELLED",
    ]
    assert isinstance(data["account_count_noticed"], int)
    assert isinstance(data["account_count_opted_out"], int)
    assert isinstance(data["account_count_enrolled"], int)


def assert_opt_out_request(data: dict):
    _assert_append_only_fields(data)
    assert data["election_type"] in ["OPT_OUT", "OPT_BACK_TO_BUNDLED"]
    assert data["channel"] in ["WEB", "PHONE", "MAIL"]


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_code"], str)
    assert data["election_key"] in ["DEFAULT", "OPT_UP_100", "OPT_DOWN_ECONOMY"]
    assert data["status"] in ["DRAFT", "ADOPTED", "RETIRED"]
    assert isinstance(data["is_default"], bool)


def assert_rate_schedule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert data["status"] in ["DRAFT", "PROPOSED", "ADOPTED", "SUPERSEDED", "REJECTED"]
    assert isinstance(data["comparison_margin_bps"], int)


def assert_supply_contract(data: dict):
    _assert_common_fields(data)
    assert data["contract_type"] in ["ENERGY_BLOCK", "RA_CAPACITY", "REC_ONLY", "PPA"]
    assert data["status"] in [
        "NEGOTIATING",
        "EXECUTED",
        "DELIVERING",
        "CLOSED",
        "TERMINATED",
    ]
    assert isinstance(data["termination_fee_cents"], int)


def assert_load_forecast(data: dict):
    _assert_append_only_fields(data)
    assert data["forecast_variant"] in ["ADOPTED_PLAN", "ACTUAL_TRUED"]
    assert isinstance(data["period_year"], int)
    assert isinstance(data["total_energy_mwh"], (int, float))
    assert isinstance(data["coincident_peak_mw"], (int, float))
    assert isinstance(data["ra_requirement_mw"], (int, float))
    assert isinstance(data["coverage_gap_mwh"], int)


def assert_billing_extract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED_BY_UTILITY",
        "SETTLED",
    ]
    assert isinstance(data["line_count"], int)
    assert isinstance(data["total_billed_cents"], int)
    assert isinstance(data["total_pcia_collected_cents"], int)


def assert_billing_line(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["billing_extract_id"], str)
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["usage_kwh"], int) and data["usage_kwh"] > 0
    assert isinstance(data["generation_charge_cents"], int)
    assert isinstance(data["pcia_charge_cents"], int)
    assert data["product_election_at_billing"] in [
        "DEFAULT",
        "OPT_UP_100",
        "OPT_DOWN_ECONOMY",
    ]


def assert_remittance_file(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["RECEIVED", "RECONCILED", "DISPUTED", "SETTLED"]
    assert isinstance(data["gross_remittance_cents"], int)
    assert isinstance(data["net_remittance_cents"], int)
    assert isinstance(data["applied_cents"], int)


def assert_bad_debt_pool(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACCRUING", "CLOSED", "TRUED_UP"]
    assert isinstance(data["written_off_cents"], int)
    assert isinstance(data["billed_generation_cents"], int)


def assert_compliance_filing(data: dict):
    _assert_common_fields(data)
    assert data["filing_type"] in ["RPS_ANNUAL", "ERRA_FORECAST", "PSD"]
    assert data["status"] in [
        "DRAFT",
        "PREPARED",
        "REVIEWED",
        "FILED",
        "ACCEPTED_BY_CPUC",
        "REJECTED_BY_CPUC",
        "WITHDRAWN",
    ]
    assert isinstance(data["revision_count"], int)


def assert_rec_retirement(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["retirement_serial"], str)
    assert data["retired_mwh"] > 0


def assert_reserve_never_negative(authority: dict):
    """PRD §2.7: the reserve balance can never be driven below zero."""
    assert authority["climate_reserve_balance_cents"] >= 0, (
        "climate_reserve_balance_cents must never go negative"
    )
