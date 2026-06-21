"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Generic envelope-side assertions (PRD §2.4) ─────────────────


def assert_common_fields(data: dict):
    """Every persisted resource entity carries id, created_at, updated_at,
    version per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict):
    """Append-only entities (Form1099R, AuditEvent) carry only id + created_at
    per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ─── Per-entity assertions ───────────────────────────────────────


def assert_account_owner(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["tax_id_last4"], str) and len(data["tax_id_last4"]) == 4
    assert data["filing_status"] in {
        "SINGLE",
        "MARRIED_JOINT",
        "MARRIED_SEPARATE",
        "HEAD_OF_HOUSEHOLD",
    }
    assert isinstance(data["modified_agi_cents"], int)
    assert data["rmd_posture"] in {
        "NOT_REQUIRED",
        "REQUIRED_PENDING",
        "REQUIRED_MET",
        "REQUIRED_DELINQUENT",
    }


def assert_ira_account(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["owner_id"])
    assert data["account_type"] in {"TRADITIONAL", "ROTH"}
    assert data["status"] in {
        "ACTIVE",
        "FROZEN",
        "CONVERSION_IN_PROGRESS",
        "INHERITED",
        "CLOSED",
    }
    assert isinstance(data["cash_balance_cents"], int)
    assert isinstance(data["pretax_basis_cents"], int)
    assert isinstance(data["aftertax_basis_cents"], int)
    assert isinstance(data["ytd_contribution_cents"], int)
    assert isinstance(data["tax_year_marker"], int)


def assert_contribution(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["contribution_kind"] in {"PRETAX", "AFTERTAX", "ROTH"}
    assert data["status"] in {"PENDING", "CONFIRMED", "REJECTED", "REVERSED"}


def assert_distribution(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["distribution_reason"] in {
        "NORMAL",
        "EARLY",
        "RMD",
        "INHERITED",
        "ROLLOVER",
        "RETURN_OF_CONTRIBUTION",
    }
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["federal_withholding_cents"], int)
    assert data["status"] in {"PENDING", "CONFIRMED", "REVERSED"}


def assert_conversion(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["source_account_id"])
    assert is_valid_uuid(data["target_account_id"])
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] > 0
    assert isinstance(data["taxable_amount_cents"], int)
    assert isinstance(data["nontaxable_amount_cents"], int)
    assert data["status"] in {"INITIATED", "COMPLETED", "REVERSED"}


def assert_beneficiary_designation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["beneficiary_full_name"], str)
    assert data["relationship"] in {
        "SPOUSE",
        "MINOR_CHILD",
        "DISABLED",
        "CHRONIC_ILL",
        "ELIGIBLE_TRUST",
        "NON_ELIGIBLE_INDIVIDUAL",
    }
    assert isinstance(data["percentage_bps"], int)
    assert 0 < data["percentage_bps"] <= 10000
    assert data["status"] in {"PENDING", "ACTIVE", "REVOKED", "INHERITED"}


def assert_rmd_schedule(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["owner_id"])
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["required_amount_cents"], int)
    assert isinstance(data["satisfied_amount_cents"], int)
    assert data["satisfied_amount_cents"] >= 0
    assert data["status"] in {"OPEN", "SATISFIED", "DELINQUENT"}


def assert_form_1099r(data: dict):
    assert_append_only_fields(data)
    # Either distribution_id or conversion_id is non-null but not both (PRD §3.9).
    has_dist = data.get("distribution_id") is not None
    has_conv = data.get("conversion_id") is not None
    assert has_dist or has_conv, (
        "Form1099R must reference either a distribution or a conversion"
    )
    assert not (has_dist and has_conv), (
        "Form1099R cannot reference both distribution and conversion"
    )
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["gross_distribution_cents"], int)
    assert isinstance(data["taxable_amount_cents"], int)
    assert isinstance(data["federal_withholding_cents"], int)
    assert data["distribution_code"] in {"1", "2", "4", "7", "G", "B", "J", "T"}
    assert isinstance(data["ira_sep_simple_flag"], bool)


def assert_audit_event(data: dict):
    assert_append_only_fields(data)
    assert is_valid_uuid(data["owner_id"])
    assert data["event_kind"] in {
        "CONTRIBUTION_CONFIRMED",
        "DISTRIBUTION_CONFIRMED",
        "CONVERSION_COMPLETED",
        "RMD_DEADLINE_BREACHED",
        "BENEFICIARY_INHERITED",
        "OWNER_DECEASED",
        "YEAR_ROLLED_OVER",
    }
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["amount_cents"], int)
