"""Entity assertions and domain invariant checkers for the Surety Bond Underwriting API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system fields present on every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increases on mutation"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["single_limit_cents"], int)
    assert isinstance(data["aggregate_limit_cents"], int)
    assert isinstance(data["referral_threshold_cents"], int)
    assert isinstance(data["loss_alert_threshold_cents"], int)
    assert isinstance(data["aggregate_committed_cents"], int)
    assert isinstance(data["aggregate_available_cents"], int)
    assert data["status"] in ("OPEN", "SUSPENDED")
    # aggregate_available = aggregate_limit - aggregate_committed (PRD §2.6)
    assert data["aggregate_available_cents"] == (
        data["aggregate_limit_cents"] - data["aggregate_committed_cents"]
    ), "aggregate_available_cents must equal aggregate_limit - aggregate_committed"


def assert_principal(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["credit_score"], int)
    assert isinstance(data["working_capital_cents"], int)
    assert data["credit_tier"] in ("PREFERRED", "STANDARD", "SUBSTANDARD")
    assert isinstance(data["indemnity_on_file"], bool)


def assert_indemnity_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["principal_id"])
    assert isinstance(data["indemnitor_count"], int)
    assert isinstance(data["required_signature_count"], int)
    assert isinstance(data["collected_signature_count"], int)
    assert data["status"] in ("PENDING", "EXECUTED", "VOIDED")


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["principal_id"])
    assert is_valid_uuid(data["program_id"])
    assert data["bond_type"] in ("BID", "PERFORMANCE", "PAYMENT", "LICENSE_PERMIT", "FIDELITY")
    assert isinstance(data["requested_penal_sum_cents"], int)
    assert isinstance(data["term_months"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "REFERRED", "APPROVED", "DECLINED", "BOUND"
    )


def assert_bond(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["principal_id"])
    assert is_valid_uuid(data["program_id"])
    assert data["bond_type"] in ("BID", "PERFORMANCE", "PAYMENT", "LICENSE_PERMIT", "FIDELITY")
    assert isinstance(data["penal_sum_cents"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["premium_rate_bps"], int)
    assert isinstance(data["written_premium_cents"], int)
    assert isinstance(data["earned_premium_cents"], int)
    assert isinstance(data["ceded_penal_sum_cents"], int)
    assert isinstance(data["net_retained_cents"], int)
    assert isinstance(data["incurred_loss_cents"], int)
    assert data["status"] in ("ISSUED", "ACTIVE", "RENEWED", "CANCELLED", "EXPIRED")
    # net_retained = penal_sum - ceded (PRD §2.6)
    assert data["net_retained_cents"] == (
        data["penal_sum_cents"] - data["ceded_penal_sum_cents"]
    ), "net_retained_cents must equal penal_sum - ceded_penal_sum"


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bond_id"])
    assert isinstance(data["claimant_name"], str)
    assert isinstance(data["demand_cents"], int)
    assert isinstance(data["reserve_cents"], int)
    assert data["status"] in ("FILED", "INVESTIGATING", "PAID", "DENIED")


def assert_rider(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bond_id"])
    assert data["rider_type"] in ("INCREASE", "DECREASE", "NAME_CHANGE")
    assert isinstance(data["penal_sum_delta_cents"], int)
    assert isinstance(data["additional_premium_cents"], int)
    assert data["status"] in ("DRAFT", "APPLIED", "REJECTED")


def assert_treaty(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["cession_pct_bps"], int)
    assert isinstance(data["treaty_capacity_cents"], int)
    assert isinstance(data["ceded_committed_cents"], int)
    assert isinstance(data["ceded_available_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED")
    # ceded_available = treaty_capacity - ceded_committed (PRD §2.8)
    assert data["ceded_available_cents"] == (
        data["treaty_capacity_cents"] - data["ceded_committed_cents"]
    ), "ceded_available_cents must equal treaty_capacity - ceded_committed"


def assert_cession(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["bond_id"])
    assert is_valid_uuid(data["treaty_id"])
    assert isinstance(data["ceded_penal_sum_cents"], int)
    assert data["status"] in ("ACTIVE", "RECAPTURED")
