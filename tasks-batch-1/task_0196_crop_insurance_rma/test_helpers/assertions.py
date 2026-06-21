"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape against the PRD contract using
the framework's generic helpers. Identity entities (Producer, Agent) deliberately
do NOT carry updated_at / version and those are asserted absent.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_COMMON_SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_commodity_program(data: dict):
    _assert_common(data)
    assert isinstance(data["crop_code"], str) and data["crop_code"]
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert isinstance(data["crop_year"], int)
    assert isinstance(data["projected_price"], (int, float))
    assert isinstance(data["base_premium_rate"], (int, float))
    assert isinstance(data["pp_coverage_factor"], (int, float))
    assert isinstance(data["harvest_price_published"], bool)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("producer_id", "")), "producer_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert isinstance(data["crop_year"], int)
    for f in ("total_premium_cents", "producer_premium_cents", "subsidy_cents",
              "total_indemnity_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer (cents)"
    assert isinstance(data["total_insured_acres"], (int, float))
    assert data["status"] in ("DRAFT", "ACTIVE", "CANCELLED")


def assert_coverage_election(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("policy_id", ""))
    assert is_valid_uuid(data.get("commodity_program_id", ""))
    assert data["plan_type"] in ("YP", "RP", "RP_HPE")
    assert isinstance(data["aph_yield"], (int, float))
    assert data["coverage_level"] in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)
    assert isinstance(data["yield_guarantee_bu"], (int, float))
    for f in ("dollar_liability_per_acre_cents", "total_premium_cents",
              "subsidy_cents", "producer_premium_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer (cents)"
    assert isinstance(data["subsidy_factor"], (int, float))
    assert data["status"] in ("ELECTED", "REPORTED", "INDEMNIFIED", "VOID")


def assert_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("coverage_election_id", ""))
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["acres"], (int, float)) and data["acres"] > 0
    assert isinstance(data["share"], (int, float)) and 0 < data["share"] <= 1
    assert isinstance(data["planted_acres"], (int, float))
    assert isinstance(data["prevented_acres"], (int, float))
    assert data["status"] in ("PENDING", "REPORTED", "ACTIVE", "SETTLED", "VOID")


def assert_acreage_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["planted_acres"], (int, float))
    assert isinstance(data["prevented_acres"], (int, float))
    assert isinstance(data["late_planted"], bool)
    assert data["status"] in ("FILED", "ACCEPTED", "SUPERSEDED")


def assert_loss_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["production_to_count_bu"], (int, float))
    assert isinstance(data["indemnity_cents"], int)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "APPROVED", "DENIED", "PAID")


def assert_pp_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["claimed_prevented_acres"], (int, float))
    assert data["cause"] in ("EXCESS_MOISTURE", "DROUGHT", "FLOOD", "OTHER")
    assert isinstance(data["pp_indemnity_cents"], int)
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "APPROVED", "DENIED")


def assert_agent_commission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", ""))
    assert is_valid_uuid(data.get("coverage_election_id", ""))
    assert isinstance(data["commission_rate"], (int, float))
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["clawback_cents"], int)
    assert data["status"] in ("EARNED", "CLAWED_BACK")


def assert_identity_entity(data: dict):
    """Producer / Agent carry only id + created_at — no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "identity entity must not carry a version field"
    assert "updated_at" not in data, "identity entity must not carry an updated_at field"


# ─── Domain invariant checkers ────────────────────────────────────────────

def assert_premium_conserved(election: dict):
    """PRD §3.4: subsidy_cents + producer_premium_cents == total_premium_cents exactly."""
    assert election["subsidy_cents"] + election["producer_premium_cents"] == \
        election["total_premium_cents"], (
        "premium ledger must conserve: subsidy + producer == total"
    )
