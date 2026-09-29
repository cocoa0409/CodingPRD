"""Entity-shape and domain-invariant assertions for the gluten-free certification API."""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import (
    CERT_BASE_FEE_CENTS,
    CERT_FEE_PER_INGREDIENT_CENTS,
    CERT_SHARED_EQUIPMENT_FEE_CENTS,
    FEE_RATE_TIER_1,
    FEE_RATE_TIER_1_MAX_CENTS,
    FEE_RATE_TIER_2,
    FEE_RATE_TIER_2_MAX_CENTS,
    FEE_RATE_TIER_3,
    NC_PENALTY_POINTS,
    POSTURE_GOOD_STANDING_FLOOR,
    POSTURE_WATCH_FLOOR,
    SWEEP_COUNTER_KEYS,
)
from .types import CompliancePosture


# ---------------------------------------------------------------------------
# generic shape helpers
# ---------------------------------------------------------------------------
def assert_identity_and_timestamps(row: Dict[str, Any], *, versioned: bool = True) -> None:
    """Every stored row carries a server-minted id, a creation stamp and, unless it
    is an immutable link row, an update stamp and an integer version."""
    assert is_valid_uuid(str(row.get("id"))), f"id must be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be ISO-8601, got {row.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(row["updated_at"]), (
            f"updated_at must be ISO-8601, got {row.get('updated_at')!r}"
        )
        assert isinstance(row.get("version"), int), "version must be an integer"
    else:
        assert "updated_at" not in row, "immutable link rows carry no updated_at"
        assert "version" not in row, "immutable link rows carry no version"


def assert_fields(row: Dict[str, Any], **expected: Any) -> None:
    """Assert a set of field values on a row, reporting the field name on failure."""
    for field, value in expected.items():
        assert field in row, f"expected field {field!r} on {sorted(row)}"
        assert row[field] == value, (
            f"{field}: expected {value!r}, got {row[field]!r}"
        )


# ---------------------------------------------------------------------------
# per-entity assertions
# ---------------------------------------------------------------------------
def assert_applicant(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "legal_name",
        "contact_email",
        "country_code",
        "compliance_posture",
        "posture_score_cycle",
        "posture_score_rolling_12m",
        "open_nc_penalty_points",
        "active_certified_product_count",
        "suspended_certificate_count",
        "revoked_certificate_count",
        "substantiated_complaint_count_rolling",
        "substantiated_complaint_count_cycle",
        "fee_balance_cents",
    ):
        assert field in row, f"applicant read must expose {field!r}"
    assert_fields(row, **expected)


def assert_facility(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "applicant_id",
        "site_name",
        "air_handling_class",
        "shared_equipment_present",
        "gluten_containing_operations",
        "sanitation_validation_status",
        "last_closed_audit_outcome",
        "last_closed_audit_closed_on",
    ):
        assert field in row, f"facility read must expose {field!r}"
    assert_fields(row, **expected)


def assert_supplier(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in ("name", "country_code", "status", "verified_document_count"):
        assert field in row, f"supplier read must expose {field!r}"
    assert_fields(row, **expected)


def assert_supplier_document(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "supplier_id",
        "ingredient_id",
        "doc_type",
        "issued_on",
        "expires_on",
        "status",
    ):
        assert field in row, f"supplier document read must expose {field!r}"
    assert_fields(row, **expected)


def assert_ingredient(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "applicant_id",
        "supplier_id",
        "name",
        "risk_class",
        "status",
        "verified_doc_types",
        "review_cycle_count",
    ):
        assert field in row, f"ingredient read must expose {field!r}"
    assert isinstance(row["verified_doc_types"], list)
    assert_fields(row, **expected)


def assert_product(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "applicant_id",
        "facility_id",
        "name",
        "sku",
        "requested_mark_tier",
        "mark_tier_granted",
        "formula_status",
        "label_status",
        "testing_plan_status",
        "linked_ingredient_count",
    ):
        assert field in row, f"product read must expose {field!r}"
    assert_fields(row, **expected)


def assert_product_ingredient(row: Dict[str, Any], **expected: Any) -> None:
    """The formula line is an immutable link row: only id and created_at accompany
    its own fields."""
    assert_identity_and_timestamps(row, versioned=False)
    for field in ("product_id", "ingredient_id", "inclusion_pct", "is_risk_carrier"):
        assert field in row, f"formula line read must expose {field!r}"
    assert_fields(row, **expected)


def assert_lot_test(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "product_id",
        "lot_code",
        "test_type",
        "sample_collected_on",
        "ppm_result",
        "lab_method",
        "threshold_applied_ppm",
        "verdict",
        "status",
    ):
        assert field in row, f"lot test read must expose {field!r}"
    assert_fields(row, **expected)


def assert_audit(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "facility_id",
        "audit_type",
        "onsite_start_at",
        "onsite_end_at",
        "status",
        "finding_count",
        "critical_finding_count",
    ):
        assert field in row, f"audit read must expose {field!r}"
    assert_fields(row, **expected)


def assert_certificate(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "product_id",
        "applicant_id",
        "status",
        "mark_tier_granted",
        "certified_threshold_ppm",
        "issued_on",
        "expires_on",
        "surveillance_due_on",
        "surveillance_status",
        "suspension_count",
        "mark_usage_locked",
        "base_fee_cents",
        "surveillance_surcharge_cents",
        "total_fee_cents",
        "fee_charged",
        "fee_refunded",
    ):
        assert field in row, f"certificate read must expose {field!r}"
    assert_fields(row, **expected)


def assert_nonconformance(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "applicant_id",
        "source_type",
        "category",
        "severity",
        "status",
        "penalty_points",
        "ca_due_on",
        "ca_revision_count",
        "ca_verified",
    ):
        assert field in row, f"nonconformance read must expose {field!r}"
    assert_fields(row, **expected)


def assert_change_notification(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "certificate_id",
        "change_type",
        "effective_on",
        "status",
        "notified_days_before_effective",
        "late_notification",
        "required_retest",
    ):
        assert field in row, f"change notification read must expose {field!r}"
    assert_fields(row, **expected)


def assert_consumer_complaint(row: Dict[str, Any], **expected: Any) -> None:
    assert_identity_and_timestamps(row)
    for field in (
        "certificate_id",
        "exposure_date",
        "symptom_severity",
        "status",
        "recall_scope_lot_codes",
    ):
        assert field in row, f"complaint read must expose {field!r}"
    assert isinstance(row["recall_scope_lot_codes"], list)
    assert_fields(row, **expected)


# ---------------------------------------------------------------------------
# domain invariants
# ---------------------------------------------------------------------------
def expected_posture_band(score: int) -> str:
    """The band the PRD assigns to a posture score."""
    if score >= POSTURE_GOOD_STANDING_FLOOR:
        return CompliancePosture.GOOD_STANDING
    if score >= POSTURE_WATCH_FLOOR:
        return CompliancePosture.WATCH
    return CompliancePosture.PROBATION


def assert_posture(
    applicant: Dict[str, Any],
    *,
    score_cycle: Optional[int] = None,
    score_rolling: Optional[int] = None,
    band: Optional[str] = None,
    open_nc_penalty_points: Optional[int] = None,
) -> None:
    """Check the posture aggregate and that the band agrees with the cycle score."""
    if score_cycle is not None:
        assert applicant["posture_score_cycle"] == score_cycle, (
            f"posture_score_cycle: expected {score_cycle}, "
            f"got {applicant['posture_score_cycle']}"
        )
    if score_rolling is not None:
        assert applicant["posture_score_rolling_12m"] == score_rolling, (
            f"posture_score_rolling_12m: expected {score_rolling}, "
            f"got {applicant['posture_score_rolling_12m']}"
        )
    if open_nc_penalty_points is not None:
        assert applicant["open_nc_penalty_points"] == open_nc_penalty_points, (
            f"open_nc_penalty_points: expected {open_nc_penalty_points}, "
            f"got {applicant['open_nc_penalty_points']}"
        )
    if band is not None:
        assert applicant["compliance_posture"] == band, (
            f"compliance_posture: expected {band}, got {applicant['compliance_posture']}"
        )


def expected_penalty_points(*severities: str) -> int:
    """Total penalty points for a set of nonconformance severities."""
    return sum(NC_PENALTY_POINTS[s] for s in severities)


def expected_base_fee_cents(linked_ingredient_count: int, shared_equipment: bool) -> int:
    """The base fee the PRD derives from formula size and equipment sharing."""
    base = CERT_BASE_FEE_CENTS + CERT_FEE_PER_INGREDIENT_CENTS * linked_ingredient_count
    if shared_equipment:
        base += CERT_SHARED_EQUIPMENT_FEE_CENTS
    return base


def expected_fee_rate(base_fee_cents: int) -> float:
    """The surcharge rate band selected by the base fee."""
    if base_fee_cents < FEE_RATE_TIER_1_MAX_CENTS:
        return FEE_RATE_TIER_1
    if base_fee_cents < FEE_RATE_TIER_2_MAX_CENTS:
        return FEE_RATE_TIER_2
    return FEE_RATE_TIER_3


def assert_fee_breakdown(
    certificate: Dict[str, Any],
    *,
    base_fee_cents: int,
    surveillance_surcharge_cents: int,
    total_fee_cents: int,
) -> None:
    """Fees are whole cents and the total is exactly base plus surcharge."""
    assert certificate["base_fee_cents"] == base_fee_cents, (
        f"base_fee_cents: expected {base_fee_cents}, got {certificate['base_fee_cents']}"
    )
    assert certificate["surveillance_surcharge_cents"] == surveillance_surcharge_cents, (
        f"surveillance_surcharge_cents: expected {surveillance_surcharge_cents}, "
        f"got {certificate['surveillance_surcharge_cents']}"
    )
    assert certificate["total_fee_cents"] == total_fee_cents, (
        f"total_fee_cents: expected {total_fee_cents}, "
        f"got {certificate['total_fee_cents']}"
    )
    assert isinstance(certificate["total_fee_cents"], int), "fees are integer cents"
    assert (
        certificate["base_fee_cents"] + certificate["surveillance_surcharge_cents"]
        == certificate["total_fee_cents"]
    ), "total_fee_cents must equal base_fee_cents + surveillance_surcharge_cents"


def assert_sweep_shape(sweep: Dict[str, Any]) -> None:
    """Every sweep response reports the full counter set."""
    for key in SWEEP_COUNTER_KEYS:
        assert key in sweep, f"surveillance sweep must report {key!r}"


def assert_sweep_counters(sweep: Dict[str, Any], **expected: Any) -> None:
    assert_sweep_shape(sweep)
    assert_fields(sweep, **expected)


def assert_list_total(response, expected_total: int) -> list:
    """Assert a collection read reports ``expected_total`` rows and return them."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"total_count: expected {expected_total}, got {meta['total_count']}"
    )
    return rows


def assert_no_rows(response) -> None:
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == 0, f"expected no rows, got {meta['total_count']}"
    assert rows == [], f"expected an empty page, got {rows}"


def assert_fee_balance_matches_certificates(
    api, applicant_id: str, headers: Dict[str, str]
) -> None:
    """The applicant's outstanding balance equals the sum of total_fee_cents over
    certificates that were charged and not refunded."""
    rows, _ = validate_paginated(
        api.list_certificates(headers, applicant_id=applicant_id, limit=100)
    )
    expected = sum(
        row["total_fee_cents"]
        for row in rows
        if row.get("fee_charged") and not row.get("fee_refunded")
    )
    applicant = validate_success(api.get_applicant(applicant_id, headers))
    assert applicant["fee_balance_cents"] == expected, (
        f"fee_balance_cents {applicant['fee_balance_cents']} does not match the "
        f"unrefunded charged certificate total {expected}"
    )


def assert_ordered_ids(rows: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"expected order {list(expected_ids)}, got {actual}"
