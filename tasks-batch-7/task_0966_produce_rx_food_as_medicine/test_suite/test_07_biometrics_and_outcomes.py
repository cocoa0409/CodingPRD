"""Biometric readings: immutability, A1c plausibility, and the dual-variant
outcome delta (PRD §2.4, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_biometric_reading,
    TEST_USERS, make_clinic_staff_headers,
    create_biometric_reading_payload,
    setup_enrollment, record_a1c,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


def test_biometric_reading_is_append_only(api):
    """PRD §2.4: "Two record types are deliberately thinner. An education
    completion and a biometric reading are append-only, immutable
    observations; each carries only `id` and `created_at` alongside its domain
    fields, and both `updated_at` and `version` are absent from these two
    resources."

    Design: Corner/entities/c_biometric_reading_immutability
    """
    ctx = setup_enrollment()
    reading = record_a1c(ctx, 8.0, "2026-05-10T00:00:00Z", source="LAB_VERIFIED")
    assert_biometric_reading(reading)
    assert reading["value"] == 8.0

    fetched = validate_success(api.get_biometric_reading(
        reading["id"], make_clinic_staff_headers(ctx["clinic"]["id"])), 200)
    assert fetched["value"] == 8.0
    assert "version" not in fetched
    assert "updated_at" not in fetched


def test_a1c_out_of_range_rejected(api):
    """PRD §3.7: "an A1C `value` must be clinically plausible — within the
    range 3.0 to 20.0 inclusive — with anything outside rejected as
    `ERR_A1C_OUT_OF_RANGE`."

    Design: Corner/errors/c_a1c_out_of_range_rejected
    """
    ctx = setup_enrollment()
    res = api.create_biometric_reading(
        ctx["enrollment_id"],
        create_biometric_reading_payload(kind="A1C", value=25.0,
                                         measured_at="2026-05-10T00:00:00Z",
                                         source="CLINIC"),
        make_clinic_staff_headers(ctx["clinic"]["id"]))
    validate_error(res, "ERR_A1C_OUT_OF_RANGE")


def test_a1c_baseline_uses_earliest_measured_at(api):
    """PRD §3.7: "the baseline is the `value` of the A1C reading with the
    earliest `measured_at`, ties broken by `created_at` ascending, and the
    latest reading is selected symmetrically by the latest `measured_at` with
    the same tie-break." and "the enrollment counts as improved exactly when
    the delta is less than or equal to the negative of the program's
    `outcome_improvement_threshold`, compared at one decimal place."

    Design: Corner/calculations/c_a1c_baseline_uses_earliest_measured_at
    """
    ctx = setup_enrollment()
    # Created out of chronological order; the earliest measured_at (8.4 on
    # 2026-05-05) is the baseline, not the first-created reading (8.0).
    record_a1c(ctx, 8.0, "2026-05-20T00:00:00Z", source="CLINIC")
    record_a1c(ctx, 8.4, "2026-05-05T00:00:00Z", source="CLINIC")
    record_a1c(ctx, 7.9, "2026-06-01T00:00:00Z", source="CLINIC")

    summary = validate_success(
        api.get_program_summary(ctx["program"]["id"], ADMIN), 200)
    # Baseline 8.4, latest 7.9 -> delta -0.5 <= -0.5 -> improved.
    assert summary["a1c_improved_inclusive_count"] == 1


# ---------------------------------------------------------------------------
# Depth instance: inclusive vs verified A1c outcome variants
# ---------------------------------------------------------------------------

def _mixed_source_a1c_context():
    """One ACTIVE enrollment with A1C readings LAB_VERIFIED 8.0 measured
    2026-05-10 and SELF_REPORT 6.9 measured 2026-06-01."""
    ctx = setup_enrollment()
    record_a1c(ctx, 8.0, "2026-05-10T00:00:00Z", source="LAB_VERIFIED")
    record_a1c(ctx, 6.9, "2026-06-01T00:00:00Z", source="SELF_REPORT")
    return ctx


def test_a1c_inclusive_variant_counts_any_source(api):
    """PRD §3.7: "The inclusive variant considers readings of every source:
    with at least two readings, the delta is the latest value minus the
    baseline value, and the enrollment counts as improved exactly when the
    delta is less than or equal to the negative of the program's
    `outcome_improvement_threshold`, compared at one decimal place."

    Design: Difficulty/dual_variant_calc/a1c_delta_inclusive_vs_verified
    """
    ctx = _mixed_source_a1c_context()
    summary = validate_success(
        api.get_program_summary(ctx["program"]["id"], ADMIN), 200)
    # Inclusive: baseline 8.0, latest 6.9 -> delta -1.1 <= -0.5 -> improved.
    assert summary["a1c_improved_inclusive_count"] == 1


def test_a1c_verified_variant_requires_two_lab_verified_readings(api):
    """PRD §3.7: "The verified variant restricts both endpoints to readings
    whose `source` is LAB_VERIFIED and applies the same delta and threshold;
    an enrollment with fewer than two lab-verified readings is never counted
    as improved under this variant, so the same raw data can yield a different
    improved set."

    Design: Difficulty/dual_variant_calc/a1c_delta_inclusive_vs_verified
    """
    ctx = _mixed_source_a1c_context()
    summary = validate_success(
        api.get_program_summary(ctx["program"]["id"], ADMIN), 200)
    # Verified: only one LAB_VERIFIED reading exists -> never improved.
    assert summary["a1c_improved_verified_count"] == 0
