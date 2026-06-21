"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Each assert_{entity}() validates the system-managed fields (id is a UUID,
created_at/updated_at are ISO 8601, version is a positive integer) plus the
entity-specific fields and enum membership.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CARE_LEVELS = {"INDEPENDENT", "ASSISTED", "SKILLED"}


def _assert_common(data: dict) -> None:
    """Common resource properties (PRD §2.4): id, created_at, updated_at,
    integer version that begins at 1 and increments on every mutation."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_community(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["current_period_index"], int)
    assert isinstance(data["actuarial_discount_rate_bps"], int)
    assert isinstance(data["target_funded_ratio_bps"], int)
    assert isinstance(data["reserve_assets_cents"], int)
    assert isinstance(data["is_admissions_frozen"], bool)


def assert_contract_plan(data: dict) -> None:
    _assert_common(data)
    assert data["contract_type"] in {"TYPE_A", "TYPE_B", "TYPE_C"}
    assert data["refund_plan"] in {
        "DECLINING", "FIFTY_REFUNDABLE", "NINETY_REFUNDABLE",
    }
    assert data["entrance_fee_cents"] > 0
    assert data["monthly_service_fee_cents"] > 0
    assert data["second_person_fee_cents"] >= 0


def assert_unit(data: dict) -> None:
    _assert_common(data)
    assert data["care_level"] in CARE_LEVELS
    assert data["status"] in {"AVAILABLE", "OCCUPIED"}
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 1


def assert_resident(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["priority_score"], int)


def assert_residency(data: dict) -> None:
    _assert_common(data)
    assert data["care_level"] in CARE_LEVELS
    assert data["status"] in {
        "DEPOSIT_HELD", "WAITLISTED", "RESERVED", "ACTIVE",
        "TERMINATED_VOLUNTARY", "TERMINATED_DEATH",
    }
    assert isinstance(data["entrance_fee_paid_cents"], int)
    assert isinstance(data["occupied_months"], int)
    assert isinstance(data["skilled_days_used"], int)
    assert isinstance(data["has_second_person"], bool)
    assert isinstance(data["refund_disbursed_cents"], int)


def assert_second_person(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in {"ACTIVE", "REMOVED"}
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_waitlist_entry(data: dict) -> None:
    _assert_common(data)
    assert data["target_care_level"] in CARE_LEVELS
    assert data["status"] in {"PENDING", "OFFERED", "PLACED", "WITHDRAWN"}
    assert isinstance(data["rank"], int)
    assert isinstance(data["enqueued_period_index"], int)
    assert isinstance(data["priority_score"], int)


def assert_care_transition(data: dict) -> None:
    _assert_common(data)
    assert data["from_level"] in CARE_LEVELS
    assert data["to_level"] in CARE_LEVELS
    assert data["status"] in {"PROPOSED", "APPLIED", "REVERTED"}
    assert isinstance(data["effective_period_index"], int)


def assert_bed_reservation(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in {"HELD", "OCCUPIED", "RELEASED", "EXPIRED"}
    assert isinstance(data["hold_start_period"], int)
    assert isinstance(data["hold_expiry_period"], int)
    assert isinstance(data["occupied_start_period"], int)


def assert_monthly_invoice(data: dict) -> None:
    _assert_common(data)
    assert data["status"] == "ISSUED"
    assert isinstance(data["base_service_fee_cents"], int)
    assert isinstance(data["second_person_fee_cents"], int)
    assert isinstance(data["care_surcharge_cents"], int)
    assert isinstance(data["total_cents"], int)
    # total is the sum of the three lines (PRD §3.6).
    assert data["total_cents"] == (
        data["base_service_fee_cents"]
        + data["second_person_fee_cents"]
        + data["care_surcharge_cents"]
    ), "total_cents must equal base + second_person + care_surcharge"


def assert_refund_disbursement(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in {"PENDING", "SETTLED"}
    assert data["termination_reason"] in {"VOLUNTARY", "DEATH"}
    assert isinstance(data["gross_entrance_fee_cents"], int)
    assert isinstance(data["refundable_cents"], int)
    assert data["refundable_cents"] >= 0


def assert_council(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["quorum_pct_bps"], int)


def assert_resolution(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in {"DRAFT", "OPEN", "PASSED", "FAILED"}
    assert isinstance(data["yes_votes"], int)
    assert isinstance(data["no_votes"], int)
    assert isinstance(data["eligible_voter_count"], int)
