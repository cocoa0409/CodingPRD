"""Domain assertions for the mammography accreditation service.

These wrap the repeated shape and invariant checks so that the individual tests
read as statements about the contract.  Every helper only asserts what the PRD
states; nothing here infers behaviour.
"""

from typing import Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AUDIT_METRIC_FIELDS,
    COMPLIANCE_RUN_FIELDS,
    FDA_LAY_SUMMARY_CODE,
    TIER_1_CEILING_CENTS,
    TIER_2_CEILING_CENTS,
)
from .factories import parse_utc, same_instant
from .types import COMMON_FIELDS, CREDIT_ONLY_FIELDS

PCT_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Identity, timestamps and versions
# ---------------------------------------------------------------------------


def assert_common_fields(entity: dict, expected_version: Optional[int] = None) -> None:
    """Every entity but a credit row carries id, created_at, updated_at, version."""
    for field in COMMON_FIELDS:
        assert field in entity, f"Missing common field '{field}': {entity}"
    assert is_valid_uuid(entity["id"]), f"id must be a UUID with no prefix: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_credit_shape(credit: dict) -> None:
    """A `QualificationCredit` carries only `id` and `created_at`."""
    for field in CREDIT_ONLY_FIELDS:
        assert field in credit, f"Missing credit field '{field}': {credit}"
    assert is_valid_uuid(credit["id"]), credit["id"]
    assert is_iso8601_timestamp(credit["created_at"]), credit["created_at"]
    assert "updated_at" not in credit, "A credit row carries no updated_at"
    assert "version" not in credit, "A credit row carries no version"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two timestamps by instant, tolerating fractional-second rendering."""
    assert same_instant(actual, expected), f"{label}: expected {expected}, got {actual}"


def assert_created_at_is_clock(entity: dict, clock_utc: str) -> None:
    assert_instant_equals(entity["created_at"], clock_utc, "created_at")


def assert_version_unchanged(before: int, after: int, label: str = "version") -> None:
    assert after == before, f"{label} should not have moved: {before} -> {after}"


def assert_no_pagination_fields(meta: dict) -> None:
    """A single-resource response carries no pagination fields."""
    for field in ("total_count", "has_more", "limit", "offset"):
        assert field not in meta, f"Single-resource meta must not carry '{field}': {meta}"


def assert_all_distinct(values: Sequence) -> None:
    assert len(set(values)) == len(values), f"Values are not pairwise distinct: {values}"


def assert_ordered_by_created_at(rows: Sequence[dict]) -> None:
    """Listings are ordered by `created_at` ascending."""
    stamps = [parse_utc(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"Rows are not in ascending created_at order: {stamps}"


# ---------------------------------------------------------------------------
# Percentages and money
# ---------------------------------------------------------------------------


def assert_pct(actual, expected, label: str = "percentage") -> None:
    """Compare a two-decimal percentage, or assert both sides are null."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual}"
        return
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual, expected, label: str = "cents") -> None:
    """Money is an integer number of cents, never a float."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual}"
        return
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_facility_ledger(
    facility: dict,
    total_funded_cents: Optional[int] = None,
    prepaid_credit_cents: Optional[int] = None,
    fee_held_cents: Optional[int] = None,
    fee_consumed_cents: Optional[int] = None,
) -> None:
    """Assert the four ledger fields and the conservation identity between them."""
    if total_funded_cents is not None:
        assert_cents(facility["total_funded_cents"], total_funded_cents, "total_funded_cents")
    if prepaid_credit_cents is not None:
        assert_cents(facility["prepaid_credit_cents"], prepaid_credit_cents, "prepaid_credit_cents")
    if fee_held_cents is not None:
        assert_cents(facility["fee_held_cents"], fee_held_cents, "fee_held_cents")
    if fee_consumed_cents is not None:
        assert_cents(facility["fee_consumed_cents"], fee_consumed_cents, "fee_consumed_cents")
    assert_ledger_identity(facility)


def assert_ledger_identity(facility: dict) -> None:
    """`total_funded_cents` == prepaid + held + consumed, at all times."""
    assert facility["total_funded_cents"] == (
        facility["prepaid_credit_cents"]
        + facility["fee_held_cents"]
        + facility["fee_consumed_cents"]
    ), (
        "Fee ledger identity broken: "
        f"total_funded={facility['total_funded_cents']} "
        f"prepaid={facility['prepaid_credit_cents']} "
        f"held={facility['fee_held_cents']} "
        f"consumed={facility['fee_consumed_cents']}"
    )


def assert_coverage_sums_to_allowed(order: dict) -> None:
    """The covered and residual shares always sum back to the allowed amount."""
    if order["allowed_amount_cents"] is None:
        return
    assert (
        order["covered_amount_cents"] + order["patient_responsibility_cents"]
        == order["allowed_amount_cents"]
    ), (
        "Coverage split does not sum back to the allowed amount: "
        f"{order['covered_amount_cents']} + {order['patient_responsibility_cents']} "
        f"!= {order['allowed_amount_cents']}"
    )


def assert_tier_for_allowed_amount(order: dict) -> None:
    """Both tier ceilings are inclusive: 31500 is TIER_1 and 63000 is TIER_2."""
    allowed = order["allowed_amount_cents"]
    tier = order["coverage_tier"]
    if tier is None:
        return
    if allowed <= TIER_1_CEILING_CENTS:
        expected = "TIER_1"
    elif allowed <= TIER_2_CEILING_CENTS:
        expected = "TIER_2"
    else:
        expected = "TIER_3"
    assert tier == expected, f"allowed {allowed} should be {expected}, got {tier}"



_UNSET = object()


def assert_coverage(
    order: dict,
    coverage_outcome=_UNSET,
    allowed_amount_cents=_UNSET,
    covered_amount_cents=_UNSET,
    patient_responsibility_cents=_UNSET,
    coverage_tier=_UNSET,
    governing_state_code=_UNSET,
) -> None:
    """Assert a coverage determination, including the sum-back invariant."""
    if coverage_outcome is not _UNSET:
        assert order["coverage_outcome"] == coverage_outcome, (
            f"coverage_outcome: expected {coverage_outcome}, got {order['coverage_outcome']}"
        )
    if allowed_amount_cents is not _UNSET:
        assert_cents(order["allowed_amount_cents"], allowed_amount_cents, "allowed_amount_cents")
    if covered_amount_cents is not _UNSET:
        assert_cents(order["covered_amount_cents"], covered_amount_cents, "covered_amount_cents")
    if patient_responsibility_cents is not _UNSET:
        assert_cents(
            order["patient_responsibility_cents"],
            patient_responsibility_cents,
            "patient_responsibility_cents",
        )
    if coverage_tier is not _UNSET:
        assert order["coverage_tier"] == coverage_tier, (
            f"coverage_tier: expected {coverage_tier}, got {order['coverage_tier']}"
        )
    if governing_state_code is not _UNSET:
        assert order["governing_state_code"] == governing_state_code, (
            f"governing_state_code: expected {governing_state_code}, "
            f"got {order['governing_state_code']}"
        )
    assert_coverage_sums_to_allowed(order)
    assert_tier_for_allowed_amount(order)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def assert_unit_state(
    unit: dict,
    accreditation_status=_UNSET,
    operational_state=_UNSET,
    survey_compliance=_UNSET,
    reaccreditation_attempts_remaining=_UNSET,
) -> None:
    """Accreditation, service and survey currency evolve independently."""
    if accreditation_status is not _UNSET:
        assert unit["accreditation_status"] == accreditation_status, (
            f"accreditation_status: expected {accreditation_status}, "
            f"got {unit['accreditation_status']}"
        )
    if operational_state is not _UNSET:
        assert unit["operational_state"] == operational_state, (
            f"operational_state: expected {operational_state}, got {unit['operational_state']}"
        )
    if survey_compliance is not _UNSET:
        assert unit["survey_compliance"] == survey_compliance, (
            f"survey_compliance: expected {survey_compliance}, got {unit['survey_compliance']}"
        )
    if reaccreditation_attempts_remaining is not _UNSET:
        assert unit["reaccreditation_attempts_remaining"] == reaccreditation_attempts_remaining, (
            "reaccreditation_attempts_remaining: expected "
            f"{reaccreditation_attempts_remaining}, "
            f"got {unit['reaccreditation_attempts_remaining']}"
        )


def assert_unit_image_ledger(
    unit: dict,
    total_images_acquired=_UNSET,
    repeat_images_acquired=_UNSET,
    image_based_repeat_rate_pct=_UNSET,
    patient_based_repeat_rate_pct=_UNSET,
    repeat_rate_flag=_UNSET,
) -> None:
    """Both repeat-rate variants are always computed and always exposed."""
    if total_images_acquired is not _UNSET:
        assert unit["total_images_acquired"] == total_images_acquired, (
            f"total_images_acquired: expected {total_images_acquired}, "
            f"got {unit['total_images_acquired']}"
        )
    if repeat_images_acquired is not _UNSET:
        assert unit["repeat_images_acquired"] == repeat_images_acquired, (
            f"repeat_images_acquired: expected {repeat_images_acquired}, "
            f"got {unit['repeat_images_acquired']}"
        )
    if image_based_repeat_rate_pct is not _UNSET:
        assert_pct(
            unit["image_based_repeat_rate_pct"],
            image_based_repeat_rate_pct,
            "image_based_repeat_rate_pct",
        )
    if patient_based_repeat_rate_pct is not _UNSET:
        assert_pct(
            unit["patient_based_repeat_rate_pct"],
            patient_based_repeat_rate_pct,
            "patient_based_repeat_rate_pct",
        )
    if repeat_rate_flag is not _UNSET:
        assert unit["repeat_rate_flag"] is repeat_rate_flag, (
            f"repeat_rate_flag: expected {repeat_rate_flag}, got {unit['repeat_rate_flag']}"
        )


# ---------------------------------------------------------------------------
# Personnel
# ---------------------------------------------------------------------------


def assert_personnel_state(
    person: dict,
    qualification_status=_UNSET,
    ce_status=_UNSET,
    ce_hours_36mo=_UNSET,
    volume_credit_24mo=_UNSET,
    ce_deadline_at=_UNSET,
) -> None:
    """`qualification_status` and `ce_status` are parallel dimensions."""
    if qualification_status is not _UNSET:
        assert person["qualification_status"] == qualification_status, (
            f"qualification_status: expected {qualification_status}, "
            f"got {person['qualification_status']}"
        )
    if ce_status is not _UNSET:
        assert person["ce_status"] == ce_status, (
            f"ce_status: expected {ce_status}, got {person['ce_status']}"
        )
    if ce_hours_36mo is not _UNSET:
        assert person["ce_hours_36mo"] == pytest.approx(ce_hours_36mo, abs=PCT_TOLERANCE), (
            f"ce_hours_36mo: expected {ce_hours_36mo}, got {person['ce_hours_36mo']}"
        )
    if volume_credit_24mo is not _UNSET:
        assert person["volume_credit_24mo"] == volume_credit_24mo, (
            f"volume_credit_24mo: expected {volume_credit_24mo}, "
            f"got {person['volume_credit_24mo']}"
        )
    if ce_deadline_at is not _UNSET:
        assert_instant_equals(person["ce_deadline_at"], ce_deadline_at, "ce_deadline_at")


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------


def assert_exam_dimensions(
    exam: dict,
    report_status=_UNSET,
    notification_status=_UNSET,
    follow_up_status=_UNSET,
) -> None:
    """The three exam dimensions can hold three unrelated values at once."""
    if report_status is not _UNSET:
        assert exam["report_status"] == report_status, (
            f"report_status: expected {report_status}, got {exam['report_status']}"
        )
    if notification_status is not _UNSET:
        assert exam["notification_status"] == notification_status, (
            f"notification_status: expected {notification_status}, "
            f"got {exam['notification_status']}"
        )
    if follow_up_status is not _UNSET:
        assert exam["follow_up_status"] == follow_up_status, (
            f"follow_up_status: expected {follow_up_status}, got {exam['follow_up_status']}"
        )


def assert_fresh_exam_defaults(exam: dict) -> None:
    """The declared landing state of a newly acquired exam."""
    assert_exam_dimensions(
        exam,
        report_status="AWAITING_INTERPRETATION",
        notification_status="NOT_REQUIRED",
        follow_up_status="NOT_REQUIRED",
    )
    assert exam["recall_flag"] is False
    assert exam["biopsy_performed"] is False
    assert exam["pathology_result"] is None
    assert exam["repeat_image_count"] == 0
    assert exam["amendment_count"] == 0
    assert exam["interpreted_late"] is False
    for field in (
        "interpreting_physician_id",
        "birads_assessment",
        "density_category",
        "interpreted_at",
        "outcome_recorded_at",
        "notification_deadline_at",
    ):
        assert exam[field] is None, f"A fresh exam must carry a null {field}, got {exam[field]}"


# ---------------------------------------------------------------------------
# Letters
# ---------------------------------------------------------------------------


def assert_letter_notice_codes(letter: dict, expected: List[str]) -> None:
    """The code list is ordered, de-duplicated, and always opens with the federal code."""
    actual = letter["required_notice_codes"]
    assert actual == expected, f"required_notice_codes: expected {expected}, got {actual}"
    assert actual[0] == FDA_LAY_SUMMARY_CODE, (
        f"The first element is always {FDA_LAY_SUMMARY_CODE}, got {actual[0]}"
    )
    assert len(set(actual)) == len(actual), f"required_notice_codes carries a duplicate: {actual}"


# ---------------------------------------------------------------------------
# Metrics and compliance runs
# ---------------------------------------------------------------------------


def assert_metrics_shape(metrics: dict) -> None:
    """The preview returns exactly the nine declared fields."""
    for field in AUDIT_METRIC_FIELDS:
        assert field in metrics, f"Metrics preview missing '{field}': {metrics}"


def assert_metrics(
    metrics: dict,
    variant=_UNSET,
    screening_exam_count=_UNSET,
    recall_count=_UNSET,
    biopsy_count=_UNSET,
    cancer_count=_UNSET,
    excluded_exam_count=_UNSET,
    recall_rate_pct=_UNSET,
    ppv_pct=_UNSET,
    abnormal_interpretation_flag=_UNSET,
) -> None:
    if variant is not _UNSET:
        assert metrics["variant"] == variant, f"variant: got {metrics['variant']}"
    for name, expected in (
        ("screening_exam_count", screening_exam_count),
        ("recall_count", recall_count),
        ("biopsy_count", biopsy_count),
        ("cancer_count", cancer_count),
        ("excluded_exam_count", excluded_exam_count),
    ):
        if expected is not _UNSET:
            assert metrics[name] == expected, (
                f"{name}: expected {expected}, got {metrics[name]}"
            )
    if recall_rate_pct is not _UNSET:
        assert_pct(metrics["recall_rate_pct"], recall_rate_pct, "recall_rate_pct")
    if ppv_pct is not _UNSET:
        assert_pct(metrics["ppv_pct"], ppv_pct, "ppv_pct")
    if abnormal_interpretation_flag is not _UNSET:
        assert metrics["abnormal_interpretation_flag"] is abnormal_interpretation_flag, (
            "abnormal_interpretation_flag: expected "
            f"{abnormal_interpretation_flag}, got {metrics['abnormal_interpretation_flag']}"
        )


def assert_compliance_run_shape(result: dict) -> None:
    """A run returns nine fields."""
    for field in COMPLIANCE_RUN_FIELDS:
        assert field in result, f"Compliance run missing '{field}': {result}"


def assert_compliance_run(
    result: dict,
    ran_at=_UNSET,
    units_marked_reaccreditation_due=_UNSET,
    units_survey_overdue=_UNSET,
    exams_marked_delayed=_UNSET,
    letters_marked_delivered=_UNSET,
    orders_marked_lost=_UNSET,
    personnel_moved_to_grace=_UNSET,
    personnel_moved_to_deficient=_UNSET,
    compliance_posture=_UNSET,
) -> None:
    assert_compliance_run_shape(result)
    if ran_at is not _UNSET:
        assert_instant_equals(result["ran_at"], ran_at, "ran_at")
    for name, expected in (
        ("units_marked_reaccreditation_due", units_marked_reaccreditation_due),
        ("units_survey_overdue", units_survey_overdue),
        ("exams_marked_delayed", exams_marked_delayed),
        ("letters_marked_delivered", letters_marked_delivered),
        ("orders_marked_lost", orders_marked_lost),
        ("personnel_moved_to_grace", personnel_moved_to_grace),
        ("personnel_moved_to_deficient", personnel_moved_to_deficient),
    ):
        if expected is not _UNSET:
            assert result[name] == expected, f"{name}: expected {expected}, got {result[name]}"
    if compliance_posture is not _UNSET:
        assert result["compliance_posture"] == compliance_posture, (
            f"compliance_posture: expected {compliance_posture}, "
            f"got {result['compliance_posture']}"
        )


def assert_all_counters_zero(result: dict) -> None:
    """A replayed checkpoint reports zeros across all seven movement counters."""
    for field in COMPLIANCE_RUN_FIELDS:
        if field in ("ran_at", "compliance_posture"):
            continue
        assert result[field] == 0, f"{field} should be 0 on a replayed run, got {result[field]}"


def ids_of(rows: Iterable[dict]) -> List[str]:
    return [row["id"] for row in rows]
