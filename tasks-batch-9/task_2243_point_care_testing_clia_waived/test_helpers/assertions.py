"""Entity shape assertions and domain invariants for the oversight API."""

import re
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── Primitive helpers ──────────────────────────────────────────────


def assert_is_date(value, label="date"):
    """PRD 2.5: date-valued comparisons are performed on YYYY-MM-DD UTC dates."""
    assert isinstance(value, str) and DATE_RE.match(value), (
        f"{label} must be a YYYY-MM-DD date, got {value!r}"
    )


def assert_logical_instant(value, expected, label="instant"):
    """PRD 2.4: the stamp is the logical clock's instant.

    An ISO 8601 UTC instant may or may not be rendered with its three fractional
    digits, so `2026-08-01T00:00:00Z` and `2026-08-01T00:00:00.000Z` are the same
    instant; only the instant itself is asserted.
    """
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC instant, got {value!r}"
    )
    normalised = value.replace(".000Z", "Z")
    assert normalised == expected.replace(".000Z", "Z"), (
        f"{label} should be {expected}, got {value!r}"
    )


def assert_two_decimals(value, label="value"):
    """PRD 2.5: derived score-style numbers carry exactly 2 decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r}"
    )
    quantised = float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    assert abs(quantised - float(value)) < 1e-9, (
        f"{label} must carry at most 2 decimal places, got {value!r}"
    )


def round_half_up(value, places=2):
    """PRD 2.5 rounding discipline: round half up at the given scale."""
    exp = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(exp, rounding=ROUND_HALF_UP))


def assert_identity_fields(data, label="resource"):
    """PRD 2.4: every resource carries a UUID `id` and an ISO 8601 `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC instant"
    )


def assert_versioned_fields(data, label="resource"):
    """PRD 2.4: most resources also carry `updated_at` and an integer `version`."""
    assert_identity_fields(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC instant"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_append_only_record(data, label="record"):
    """PRD 2.4: a control run and a temperature reading expose only `id` and `created_at`."""
    assert_identity_fields(data, label)
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# ── Entity assertions ──────────────────────────────────────────────


def assert_certificate(data):
    assert_versioned_fields(data, "certificate")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert data["certificate_type"] in (
        "CERTIFICATE_OF_WAIVER",
        "CERTIFICATE_OF_COMPLIANCE",
        "CERTIFICATE_OF_ACCREDITATION",
    )
    assert data["permitted_complexity"] in ("WAIVED", "MODERATE")
    assert_is_date(data["effective_date"], "certificate.effective_date")
    assert_is_date(data["expiration_date"], "certificate.expiration_date")
    assert isinstance(data["covered_site_count"], int)
    assert data["covered_site_count"] >= 0


def assert_site(data):
    assert_versioned_fields(data, "site")
    assert data["oversight_posture"] in ("OPEN", "RESTRICTED", "SUSPENDED")
    assert data["complexity_scope"] in ("WAIVED", "MODERATE")
    assert isinstance(data["manual_entry_blocked"], bool)
    assert isinstance(data["scope_creep_flag"], bool)
    for counter in (
        "held_result_count",
        "total_operator_count",
        "locked_out_operator_count",
        "lapsed_or_locked_operator_count",
        "pt_unsuccessful_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"site.{counter} must be a non-negative integer"
        )
    assert_two_decimals(data["open_deficiency_weight"], "site.open_deficiency_weight")
    assert_two_decimals(
        data["site_qc_compliance_index"], "site.site_qc_compliance_index"
    )
    assert_two_decimals(
        data["inspection_readiness_score"], "site.inspection_readiness_score"
    )


def assert_site_invariants(data):
    """Invariants that must hold on any site read (PRD 2.10, 2.11, 3.9)."""
    assert_site(data)
    assert 0.0 <= data["inspection_readiness_score"] <= 100.0
    assert 0.0 <= data["site_qc_compliance_index"] <= 100.0
    assert data["open_deficiency_weight"] >= 0.0
    assert data["locked_out_operator_count"] <= data["total_operator_count"]
    assert data["manual_entry_blocked"] is (data["oversight_posture"] != "OPEN"), (
        "manual_entry_blocked is true exactly when the posture is not OPEN"
    )


def assert_posture_matches_inputs(data, has_in_window_active_coverage):
    """PRD 2.10: re-derive the posture from its four inputs plus coverage."""
    weight = data["open_deficiency_weight"]
    if not has_in_window_active_coverage or weight >= 16.0:
        expected = "SUSPENDED"
    elif (
        weight >= 6.0
        or data["held_result_count"] >= 3
        or 2 * data["locked_out_operator_count"] > data["total_operator_count"]
    ):
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert data["oversight_posture"] == expected, (
        f"posture should derive to {expected}, got {data['oversight_posture']}"
    )


def assert_coverage(data):
    assert_versioned_fields(data, "coverage")
    assert_is_date(data["coverage_start"], "coverage.coverage_start")
    assert_is_date(data["coverage_end"], "coverage.coverage_end")
    assert data["coverage_end"] >= data["coverage_start"]
    assert data["permitted_complexity_snapshot"] in ("WAIVED", "MODERATE")


def assert_operator(data):
    assert_versioned_fields(data, "operator")
    assert data["competency_status"] in (
        "PENDING",
        "PROVISIONAL",
        "COMPETENT",
        "LAPSED",
        "REVOKED",
    )
    assert data["access_status"] in ("LOCKED_OUT", "ACTIVE", "DEACTIVATED")
    assert data["role_title"] in (
        "PHYSICIAN",
        "DOCTORAL_SCIENTIST",
        "MIDLEVEL_PRACTITIONER",
        "MEDICAL_TECHNOLOGIST",
        "MEDICAL_ASSISTANT",
        "NURSE",
    )
    if data.get("lockout_reason") is not None:
        assert data["lockout_reason"] in (
            "NEVER_TRAINED",
            "COMPETENCY_LAPSED",
            "SITE_SUSPENDED",
            "COMPETENCY_REVOKED",
        )
    assert isinstance(data["current_grace_days"], int)
    assert data["current_grace_days"] >= 0
    assert isinstance(data["consecutive_rejection_count"], int)
    if data.get("lapse_deadline") is not None:
        assert_is_date(data["lapse_deadline"], "operator.lapse_deadline")


def assert_assessment(data):
    assert_versioned_fields(data, "assessment")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "VOIDED")
    assert data["assessment_type"] in (
        "INITIAL",
        "SEMIANNUAL_1",
        "SEMIANNUAL_2",
        "ANNUAL",
    )
    assert isinstance(data["methods_demonstrated"], int)
    assert 0 <= data["methods_demonstrated"] <= 6
    assert_is_date(data["effective_date"], "assessment.effective_date")
    assert_is_date(data["expires_at"], "assessment.expires_at")
    assert data["expires_at"] > data["effective_date"]


def assert_device(data):
    assert_versioned_fields(data, "device")
    assert data["status"] in ("ACTIVE", "QC_LOCKED", "RETIRED")
    assert data["complexity_class"] in ("WAIVED", "MODERATE")
    assert data["connectivity_mode"] in ("INTERFACED", "MANUAL_ENTRY", "OFFLINE")
    assert isinstance(data["qc_frequency_days"], int)
    assert data["qc_frequency_days"] >= 1
    assert isinstance(data["manual_entry_suspended"], bool)
    assert isinstance(data["use_day_count"], int) and data["use_day_count"] >= 0
    assert_two_decimals(
        data["qc_compliance_rate_calendar"], "device.qc_compliance_rate_calendar"
    )
    assert_two_decimals(
        data["qc_compliance_rate_day_of_use"], "device.qc_compliance_rate_day_of_use"
    )
    assert_is_date(data["qc_next_due_at"], "device.qc_next_due_at")
    if data.get("qc_lock_reason") is not None:
        assert data["qc_lock_reason"] in (
            "QC_FAILURE",
            "QC_OVERDUE",
            "LOT_QUARANTINE",
            "PT_UNSUCCESSFUL",
            "CERTIFICATE_SCOPE",
        )


def assert_storage_unit(data):
    assert_versioned_fields(data, "storage_unit")
    assert data["excursion_state"] in ("IN_RANGE", "EXCURSION_OPEN")
    assert data["max_temp_c"] > data["min_temp_c"]
    assert isinstance(data["quarantined_lot_count"], int)
    assert data["quarantined_lot_count"] >= 0


def assert_temperature_reading(data):
    assert_append_only_record(data, "temperature_reading")
    assert data["disposition"] in ("IN_RANGE", "OUT_OF_RANGE")
    assert isinstance(data["triggered_excursion"], bool)


def assert_reagent_lot(data):
    assert_versioned_fields(data, "reagent_lot")
    assert data["verification_status"] in (
        "UNVERIFIED",
        "VERIFIED",
        "REJECTED",
        "QUARANTINED",
        "DISCARDED",
        "EXPIRED",
    )
    assert_is_date(data["expiration_date"], "reagent_lot.expiration_date")
    assert data["control_max_level_1"] > data["control_min_level_1"]
    assert data["control_max_level_2"] > data["control_min_level_2"]


def assert_qc_run(data):
    assert_append_only_record(data, "qc_run")
    assert data["control_level"] in ("LEVEL_1", "LEVEL_2")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["locked_device"], bool)
    assert isinstance(data["expected_min"], (int, float))
    assert isinstance(data["expected_max"], (int, float))


def assert_qc_run_band(data, expected_min, expected_max):
    """PRD 3.4: the run snapshots the acceptance band it was judged against."""
    assert data["expected_min"] == expected_min
    assert data["expected_max"] == expected_max
    in_band = expected_min <= data["measured_value"] <= expected_max
    assert data["result"] == ("PASS" if in_band else "FAIL")


def assert_test_result(data):
    assert_versioned_fields(data, "test_result")
    assert data["posting_status"] in (
        "PENDING_REVIEW",
        "POSTED",
        "HELD",
        "REJECTED",
        "CORRECTION_PENDING",
    )
    assert data["entry_mode"] in ("INTERFACED", "MANUAL")
    assert isinstance(data["correction_count"], int)
    assert data["correction_count"] >= 0


def assert_pt_enrollment(data):
    assert_versioned_fields(data, "pt_enrollment")
    assert data["status"] in ("ENROLLED", "UNSUCCESSFUL_PARTICIPATION")
    assert isinstance(data["graded_event_count"], int)
    assert isinstance(data["fail_count_last_three"], int)
    assert 0 <= data["fail_count_last_three"] <= 3


def assert_pt_event(data):
    assert_versioned_fields(data, "pt_event")
    assert data["status"] in (
        "PENDING",
        "PASSED",
        "INVESTIGATION_OPEN",
        "UNSUCCESSFUL_LOCKED",
        "INVESTIGATION_SUBMITTED",
        "INVESTIGATION_ACCEPTED",
    )
    if data.get("outcome") is not None:
        assert data["outcome"] in ("PASS", "FAIL")
    assert isinstance(data["shipment_number"], int)
    assert 1 <= data["shipment_number"] <= 3
    assert isinstance(data["investigation_round"], int)


def assert_inspection(data):
    assert_versioned_fields(data, "inspection")
    assert data["status"] in (
        "IN_PROGRESS",
        "DEFICIENCIES_ISSUED",
        "CLOSED",
        "RESCINDED",
    )
    assert data["inspection_type"] in (
        "BIENNIAL_SURVEY",
        "COMPLAINT_SURVEY",
        "INTERNAL_READINESS",
    )
    assert_two_decimals(data["issued_weight_total"], "inspection.issued_weight_total")


def assert_deficiency(data):
    assert_versioned_fields(data, "deficiency")
    assert data["status"] in (
        "DRAFT",
        "OPEN",
        "CORRECTION_SUBMITTED",
        "CORRECTION_REJECTED",
        "CLOSED",
        "VOIDED",
    )
    assert data["severity"] in ("CONDITION_LEVEL", "STANDARD_LEVEL", "ADVISORY")
    assert data["category"] in (
        "PERSONNEL_COMPETENCY",
        "QUALITY_CONTROL",
        "PROFICIENCY_TESTING",
        "REAGENT_STORAGE",
        "RESULT_REPORTING",
        "CERTIFICATE_SCOPE",
    )
    assert_two_decimals(data["weight"], "deficiency.weight")
    assert isinstance(data["correction_round"], int)


def assert_readiness_breakdown(data):
    """PRD 3.9: the readiness read reports the basis, score, four penalties and inputs."""
    assert data["basis"] in ("AS_OF_ACTUAL", "PRE_SURVEY_PROJECTED")
    for term in (
        "score",
        "deficiency_penalty",
        "competency_penalty",
        "qc_penalty",
        "pt_penalty",
        "open_deficiency_weight",
        "site_qc_compliance_index",
    ):
        assert_two_decimals(data[term], f"readiness.{term}")
    assert isinstance(data["pt_unsuccessful_count"], int)
    assert is_iso8601_timestamp(data["computed_at"])
    assert data["deficiency_penalty"] <= 50.0
    assert data["competency_penalty"] <= 25.0
    assert data["qc_penalty"] <= 20.0
    assert data["pt_penalty"] <= 18.0
    assert 0.0 <= data["score"] <= 100.0


def assert_readiness_score_consistent(data):
    """PRD 3.9: subtract all four penalties from 100.0, floored at 0.0."""
    raw = 100.0 - (
        data["deficiency_penalty"]
        + data["competency_penalty"]
        + data["qc_penalty"]
        + data["pt_penalty"]
    )
    expected = max(round_half_up(raw, 2), 0.0)
    assert data["score"] == expected, (
        f"score should be {expected} from the four penalties, got {data['score']}"
    )
