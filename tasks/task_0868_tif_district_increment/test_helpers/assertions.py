"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_full(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_audit_light(data: dict):
    """Audit-light entities carry only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit-light entity must not carry updated_at"
    assert "version" not in data, "audit-light entity must not carry version"


def assert_district(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["municipality_name"], str)
    assert isinstance(data["base_tax_year"], int)
    assert isinstance(data["base_eav_cents"], int) and data["base_eav_cents"] > 0
    assert isinstance(data["term_years"], int)
    assert data["surplus_policy"] in ("GROSS", "NET")
    assert data["status"] in ("DRAFT", "CERTIFIED", "DECERTIFIED")
    assert isinstance(data["obligations_cleared"], bool)


def assert_taxing_body(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["district_id"], str)
    assert data["body_type"] in ("SCHOOL", "COUNTY", "MUNICIPAL", "PARK", "LIBRARY", "OTHER")
    assert isinstance(data["tax_rate"], (int, float)) and 0 < data["tax_rate"] < 1
    assert isinstance(data["total_surplus_received_cents"], int)
    assert data["total_surplus_received_cents"] >= 0


def assert_developer(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str)


def assert_project_fund(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED")
    for f in ("lifetime_increment_cents", "lifetime_disbursed_cents",
              "lifetime_surplus_cents", "lifetime_admin_fee_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_obligation(data: dict):
    _assert_audit_full(data)
    assert data["obligation_type"] in ("DEVELOPER_NOTE", "BOND")
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["interest_rate_bps"], int) and data["interest_rate_bps"] >= 0
    assert data["status"] in ("PROPOSED", "UNDER_REVIEW", "REGISTERED", "SATISFIED",
                              "DEFEASED", "DEFAULTED", "REJECTED")
    if data.get("seniority") is not None:
        assert data["seniority"] in ("SENIOR", "SUBORDINATE")


def assert_increment_record(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["current_eav_cents"], int)
    assert isinstance(data["incremental_eav_cents"], int)
    assert isinstance(data["gross_increment_cents"], int)
    assert isinstance(data["admin_fee_cents"], int)
    assert isinstance(data["captured_increment_cents"], int)
    assert data["variant_state"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("CERTIFIED", "FINALIZED")


def assert_disbursement(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["interest_portion_cents"], int)
    assert isinstance(data["principal_portion_cents"], int)
    assert data["status"] in ("PAID", "VOIDED")


def assert_annual_report(data: dict):
    _assert_audit_full(data)
    assert isinstance(data["report_tax_year"], int)
    assert data["status"] in ("DRAFT", "FILED", "ACCEPTED")


def assert_surplus_distribution(data: dict):
    _assert_audit_light(data)
    assert data["source"] in ("ANNUAL", "DECERTIFICATION")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["share_ppm"], int)


def assert_surplus_agreement(data: dict):
    _assert_audit_light(data)
    assert isinstance(data["surplus_share_ppm_override"], int)
    assert 0 <= data["surplus_share_ppm_override"] <= 1_000_000


def assert_eav_split_invariant(record: dict, base_eav_cents: int):
    """current_eav_cents == base_eav_cents + incremental_eav_cents whenever the
    current value is above the base (PRD 3.2 frozen base/increment split)."""
    if record["current_eav_cents"] >= base_eav_cents:
        assert record["incremental_eav_cents"] == record["current_eav_cents"] - base_eav_cents
    else:
        assert record["incremental_eav_cents"] == 0
