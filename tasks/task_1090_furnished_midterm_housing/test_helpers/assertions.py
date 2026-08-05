"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a non-prefixed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_host(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["email"], str)
    assert data["payout_account_status"] in ("UNVERIFIED", "VERIFIED")
    assert data["status"] == "ACTIVE"
    assert isinstance(data["projected_payout_cents"], int)
    assert isinstance(data["payout_balance_cents"], int)


def assert_tenant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["tenant_type"] in ("TRAVEL_NURSE", "RELOCATION", "OTHER")
    assert data["verification_status"] in ("UNVERIFIED", "PENDING", "VERIFIED", "REJECTED")
    assert data["status"] == "ACTIVE"


def assert_verification(data: dict):
    _assert_common(data)
    assert data["doc_type"] in ("GOVERNMENT_ID", "EMPLOYMENT_LETTER", "ASSIGNMENT_CONTRACT")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] > 0
    assert data["status"] in ("DRAFT", "LISTED", "SUSPENDED", "DELISTED")
    assert isinstance(data["min_term_days"], int)
    assert isinstance(data["max_term_days"], int)
    assert isinstance(data["turnover_buffer_days"], int)


def assert_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["term_days"], int)
    assert isinstance(data["rent_cents"], int)
    assert isinstance(data["gross_rent_cents"], int)
    assert data["rent_basis"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("REQUESTED", "CONFIRMED", "ACTIVE", "COMPLETED", "CANCELLED", "DECLINED")
    assert data["gross_rent_cents"] == data["rent_cents"] + data["cleaning_charge_cents"], \
        "gross_rent_cents must equal rent_cents + cleaning_charge_cents"


def assert_deposit(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "REFUNDED", "PARTIALLY_REFUNDED", "FORFEITED")
    assert_deposit_conserved(data)


def assert_deposit_conserved(data: dict):
    """PRD §2.10: held, refunded, and forfeited buckets sum to amount_cents."""
    total = data["held_cents"] + data["refunded_cents"] + data["forfeited_cents"]
    assert total == data["amount_cents"], (
        f"deposit partition must conserve amount_cents: "
        f"{data['held_cents']} + {data['refunded_cents']} + {data['forfeited_cents']} "
        f"!= {data['amount_cents']}"
    )
    assert data["held_cents"] >= 0 and data["refunded_cents"] >= 0 and data["forfeited_cents"] >= 0


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "DISPUTED", "APPROVED", "REJECTED", "WITHDRAWN")
    assert isinstance(data["claimed_cents"], int)


def assert_coi_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data["coverage_cents"], int)


def assert_turnover(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "SKIPPED")


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "SCHEDULED", "PAID", "REVERSED", "VOIDED")
    assert data["payout_basis"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["net_cents"], int)
    assert data["net_cents"] == (
        data["gross_rent_cents"] - data["platform_fee_cents"] + data["deposit_adjustment_cents"]
    ), "net_cents must equal gross - fee + deposit_adjustment"


def assert_tax_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["taxable"], bool)
    assert data["exempt_reason"] in ("MID_TERM_30_DAY", "NONE")
    assert isinstance(data["occupancy_tax_cents"], int)
