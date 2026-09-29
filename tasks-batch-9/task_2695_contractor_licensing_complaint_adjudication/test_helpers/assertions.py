"""Entity-shape assertions and domain invariant checkers.

The ``assert_<entity>`` helpers check the common-field contract and any
field-set expectations the caller passes as keyword arguments. The invariant
helpers below them express the conservation and ordering rules the PRD states
in prose, so a test can assert the rule rather than a pile of scalars.
"""

from typing import Any, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

Json = dict[str, Any]

ISO_DATE_LENGTH = 10


# --------------------------------------------------------- common fields -----
def assert_identity_fields(resource: Json) -> None:
    """Server-generated id and creation timestamp are present and well formed."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at is not ISO 8601: {resource['created_at']!r}"


def assert_common_fields(resource: Json) -> None:
    """Mutable resources also carry an update timestamp and a version counter."""
    assert_identity_fields(resource)
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"updated_at is not ISO 8601: {resource['updated_at']!r}"
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, f"version must start at 1, got {resource['version']}"


def assert_iso_date(value: Any, field: str) -> None:
    assert isinstance(value, str) and len(value) == ISO_DATE_LENGTH, (
        f"{field} must be an ISO calendar date (YYYY-MM-DD), got {value!r}"
    )


def assert_fields(resource: Json, expected: Json) -> None:
    """Every named field equals the expected value, reported one field at a time."""
    for field, want in expected.items():
        assert field in resource, f"missing field {field!r} in {sorted(resource)}"
        assert resource[field] == want, (
            f"{field}: expected {want!r}, got {resource[field]!r}"
        )


def assert_money_is_integer(resource: Json, *fields: str) -> None:
    """Monetary amounts travel as JSON integers of cents, never as strings."""
    for field in fields:
        value = resource[field]
        if value is None:
            continue
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {type(value).__name__}"
        )


# ------------------------------------------------------ per-entity shapes ----
def assert_trade_classification(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(
        resource,
        "min_net_worth_cents",
        "required_bond_amount_cents",
        "renewal_base_fee_cents",
    )
    assert resource["hazard_tier"] in (1, 2, 3), "hazard_tier must be 1, 2 or 3"
    assert_fields(resource, expected)


def assert_recovery_fund_account(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(
        resource,
        "initial_balance_cents",
        "per_claim_cap_cents",
        "per_license_aggregate_cap_cents",
        "balance_cents",
    )
    assert_fields(resource, expected)


def assert_licensee(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(
        resource, "unpaid_penalty_cents", "outstanding_recovery_payout_cents"
    )
    assert_fields(resource, expected)


def assert_qualifying_individual(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert resource["active_qualification_count"] >= 0
    assert_fields(resource, expected)


def assert_exam_result(resource: Json, **expected: Any) -> None:
    """The exam record is immutable, so it carries only id and created_at."""
    assert_identity_fields(resource)
    assert "updated_at" not in resource, "an immutable exam record carries no updated_at"
    assert "version" not in resource, "an immutable exam record carries no version"
    assert_iso_date(resource["taken_on"], "taken_on")
    assert_iso_date(resource["expires_on"], "expires_on")
    assert isinstance(resource["passed"], bool), "passed must be a boolean"
    assert_fields(resource, expected)


def assert_license_application(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(resource, "declared_net_worth_cents")
    assert resource["deficiency_round_count"] >= 0
    assert_fields(resource, expected)


def assert_license(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(
        resource,
        "outstanding_recovery_repayment_cents",
        "recovery_paid_to_date_cents",
        "recovery_encumbered_cents",
        "last_renewal_fee_cents",
    )
    assert_iso_date(resource["issued_on"], "issued_on")
    assert_iso_date(resource["expires_on"], "expires_on")
    assert resource["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED")
    assert resource["compliance_posture"] in (
        "COMPLIANT",
        "CONDITIONAL",
        "NON_COMPLIANT",
    )
    assert_fields(resource, expected)


def assert_coverage_record(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(resource, "amount_cents")
    assert_iso_date(resource["effective_date"], "effective_date")
    assert_iso_date(resource["expiration_date"], "expiration_date")
    assert resource["effective_date"] < resource["expiration_date"], (
        "the coverage period must open before it closes"
    )
    assert_fields(resource, expected)


def assert_qualifier_assignment(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_iso_date(resource["effective_from"], "effective_from")
    if resource["effective_to"] is not None:
        assert_iso_date(resource["effective_to"], "effective_to")
    assert_fields(resource, expected)


def assert_consumer(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_fields(resource, expected)


def assert_complaint(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(
        resource, "alleged_loss_cents", "settlement_amount_cents"
    )
    assert_iso_date(resource["contract_date"], "contract_date")
    assert resource["mediation_round_count"] >= 0
    assert_fields(resource, expected)


def assert_investigation(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_iso_date(resource["opened_on"], "opened_on")
    assert resource["origin"] in ("COMPLAINT", "STING")
    assert_fields(resource, expected)


def assert_citation(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(
        resource, "civil_penalty_cents", "penalty_paid_cents"
    )
    assert_iso_date(resource["issued_on"], "issued_on")
    assert_iso_date(resource["appeal_deadline"], "appeal_deadline")
    assert_iso_date(resource["correction_due_date"], "correction_due_date")
    assert resource["prior_final_citation_count"] >= 0
    assert_fields(resource, expected)


def assert_disciplinary_hearing(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert is_iso8601_timestamp(resource["scheduled_start_utc"])
    assert is_iso8601_timestamp(resource["scheduled_end_utc"])
    assert resource["scheduled_start_utc"] < resource["scheduled_end_utc"], (
        "the hearing block must start before it ends"
    )
    assert_fields(resource, expected)


def assert_recovery_fund_claim(resource: Json, **expected: Any) -> None:
    assert_common_fields(resource)
    assert_money_is_integer(
        resource,
        "claimed_amount_cents",
        "judgment_amount_cents",
        "estimated_award_cents",
        "awarded_amount_cents",
        "paid_amount_cents",
        "repaid_amount_cents",
    )
    assert_fields(resource, expected)


# ------------------------------------------------------ domain invariants ----
def assert_posture(license_resource: Json, expected_posture: str) -> None:
    """The compliance dimension reads exactly as expected."""
    assert license_resource["compliance_posture"] == expected_posture, (
        "compliance_posture: expected "
        f"{expected_posture}, got {license_resource['compliance_posture']}"
    )


def assert_dual_dimension(
    license_resource: Json, expected_status: str, expected_posture: str
) -> None:
    """Both halves of the parallel state machine read as expected at once."""
    assert (license_resource["status"], license_resource["compliance_posture"]) == (
        expected_status,
        expected_posture,
    ), (
        "expected licensure/compliance "
        f"{expected_status}/{expected_posture}, got "
        f"{license_resource['status']}/{license_resource['compliance_posture']}"
    )


def assert_suspension(
    license_resource: Json,
    expected_reason: Optional[str],
    expected_until: Optional[str],
) -> None:
    assert_fields(
        license_resource,
        {"suspension_reason": expected_reason, "suspension_until": expected_until},
    )


def assert_fund_cash_conserved(
    fund_account: Json, licenses: list[Json], expected_total: int
) -> None:
    """Cash left in the pool plus money still owed back to it is the appropriation."""
    outstanding = sum(
        lic["outstanding_recovery_repayment_cents"] for lic in licenses
    )
    total = fund_account["balance_cents"] + outstanding
    assert total == expected_total, (
        f"pool balance {fund_account['balance_cents']} plus outstanding debt "
        f"{outstanding} must equal {expected_total}, got {total}"
    )


def assert_qualification_count(individual: Json, expected_count: int) -> None:
    assert individual["active_qualification_count"] == expected_count, (
        "active_qualification_count: expected "
        f"{expected_count}, got {individual['active_qualification_count']}"
    )


def assert_penalty_within_statutory_maximum(citation: Json, maximum: int) -> None:
    assert citation["civil_penalty_cents"] <= maximum, (
        f"civil_penalty_cents {citation['civil_penalty_cents']} exceeds the "
        f"statutory maximum {maximum}"
    )


def assert_award_never_exceeds_estimate(claim: Json) -> None:
    """The final award may fall below the preliminary estimate but never above it."""
    if claim["awarded_amount_cents"] is not None:
        assert claim["awarded_amount_cents"] <= claim["estimated_award_cents"], (
            f"awarded {claim['awarded_amount_cents']} exceeds the stamped estimate "
            f"{claim['estimated_award_cents']}"
        )


def assert_coverage_period_half_open(coverage: Json, effective: str, expiration: str) -> None:
    """The coverage period is ``[effective_date, expiration_date)``."""
    assert_fields(
        coverage, {"effective_date": effective, "expiration_date": expiration}
    )


def assert_unchanged_version(before: Json, after: Json) -> None:
    """A rejected write leaves the resource's version untouched."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} on a "
        "request that should have changed nothing"
    )


def ids_of(rows: list[Json]) -> list[str]:
    return [row["id"] for row in rows]
