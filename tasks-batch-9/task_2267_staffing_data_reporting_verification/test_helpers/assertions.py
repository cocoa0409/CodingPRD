"""Entity assertions and domain invariant checkers."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppealGrounds,
    AppealStatus,
    AuditStatus,
    CaseStatus,
    CaseTriggerReason,
    CensusDayStatus,
    DirectCareClass,
    EntryStatus,
    FacilityPosture,
    FindingCode,
    FindingSeverity,
    FindingStatus,
    HourEntrySource,
    MeasureVariant,
    NurseGroup,
    PublicationStatus,
    PublicationStatus as _PublicationStatus,
    ReportingPeriodStatus,
    SubmissionStatus,
    SupportType,
    VendorSubmissionStatus,
    VendorStatus,
    VerificationStatus,
    WorkerStatus,
    WorkerType,
)

HOUR_TOLERANCE = 0.005
RATIO_TOLERANCE = 0.00005
SCORE_TOLERANCE = 0.005


# ---------------------------------------------------------------------------
# Precision helpers
# ---------------------------------------------------------------------------


def assert_decimal_places(value: Any, places: int, field: str) -> None:
    """A numeric quantity must not carry more than `places` decimal places."""
    assert value is not None, f"{field} must not be null"
    quantised = Decimal(str(value)).normalize()
    exponent = -quantised.as_tuple().exponent
    assert exponent <= places, (
        f"{field} must carry at most {places} decimal places, got {value}"
    )


def assert_hour_precision(value: Any, field: str = "hour quantity") -> None:
    """Hour quantities carry exactly 2 decimal places."""
    assert_decimal_places(value, 2, field)


def assert_ratio_precision(value: Any, field: str = "ratio") -> None:
    """Ratios and per-resident-day rates carry exactly 4 decimal places."""
    assert_decimal_places(value, 4, field)


def assert_whole_cents(value: Any, field: str = "money field") -> None:
    """Money is held in whole cents as integers and is never fractional."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )


def approx_hours(expected: float):
    return pytest.approx(expected, abs=HOUR_TOLERANCE)


def approx_ratio(expected: float):
    return pytest.approx(expected, abs=RATIO_TOLERANCE)


def approx_score(expected: float):
    return pytest.approx(expected, abs=SCORE_TOLERANCE)


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------


def assert_common_fields(data: Dict[str, Any], entity_name: str) -> None:
    """Every persisted resource but a payroll document carries id, created_at,
    updated_at, and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 UTC instant"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 UTC instant"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an int"
    assert data["version"] >= 1, f"{entity_name}.version begins at 1"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_facility(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Facility")
    assert isinstance(data["ccn"], str) and len(data["ccn"]) == 6
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["certified_bed_count"], int)
    assert data["certified_bed_count"] >= 1
    assert data["posture"] in [p.value for p in FacilityPosture]
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert isinstance(data["substantiated_case_count"], int)
    assert data["substantiated_case_count"] >= 0
    assert_whole_cents(
        data["outstanding_surcharge_cents"], "Facility.outstanding_surcharge_cents"
    )
    rating = data["latest_staffing_rating"]
    assert rating is None or (isinstance(rating, int) and 1 <= rating <= 5)


def assert_reporting_period(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ReportingPeriod")
    assert isinstance(data["period_code"], str) and data["period_code"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["end_date"] >= data["start_date"]
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1
    assert data["correction_window_end"] > data["submission_deadline"]
    assert data["status"] in [s.value for s in ReportingPeriodStatus]


def assert_job_category(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "JobCategory")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["cms_job_code"], int)
    assert 1 <= data["cms_job_code"] <= 40
    assert data["direct_care_class"] in [c.value for c in DirectCareClass]
    assert data["nurse_group"] in [g.value for g in NurseGroup]
    assert 0.00 <= float(data["direct_care_credit_pct"]) <= 1.00
    assert_decimal_places(
        data["direct_care_credit_pct"], 2, "JobCategory.direct_care_credit_pct"
    )
    assert isinstance(data["weekend_countable"], bool)


def assert_worker(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Worker")
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["worker_type"] in [t.value for t in WorkerType]
    assert is_valid_uuid(data["primary_job_category_id"])
    assert isinstance(data["hire_date"], str)
    assert data["status"] in [s.value for s in WorkerStatus]
    assert isinstance(data["authorized_roles"], list)
    assert_hour_precision(data["reported_hours_total"], "Worker.reported_hours_total")
    if data["worker_type"] == WorkerType.AGENCY_CONTRACTOR.value:
        assert data["vendor_id"] is not None, (
            "vendor_id must be supplied exactly when worker_type is AGENCY_CONTRACTOR"
        )
    else:
        assert data["vendor_id"] is None, (
            "vendor_id must be absent for a non-agency worker"
        )


def assert_staffing_vendor(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "StaffingVendor")
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["attestation_contact"], str)
    assert data["status"] in [s.value for s in VendorStatus]
    assert_hour_precision(
        data["accepted_hours_total"], "StaffingVendor.accepted_hours_total"
    )


def assert_payroll_record(data: Dict[str, Any]) -> None:
    """A filed payroll document carries only `id` and `created_at`; both
    `updated_at` and `version` are absent from the payload entirely."""
    assert is_valid_uuid(data.get("id", "")), "PayrollRecord.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        "PayrollRecord must not carry updated_at"
    )
    assert "version" not in data, "PayrollRecord must not carry version"
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["worker_id"])
    assert data["pay_period_end"] >= data["pay_period_start"]
    assert float(data["paid_hours"]) > 0.00
    assert_hour_precision(data["paid_hours"], "PayrollRecord.paid_hours")
    assert data["support_type"] in [t.value for t in SupportType]
    assert isinstance(data["document_ref"], str) and data["document_ref"]


def assert_hour_entry(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "HourEntry")
    assert is_valid_uuid(data["submission_id"])
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["reporting_period_id"])
    assert is_valid_uuid(data["worker_id"])
    assert is_valid_uuid(data["job_category_id"])
    for field in (
        "raw_hours",
        "direct_care_hours",
        "excluded_hours",
        "rn_hours",
        "lpn_hours",
        "na_hours",
    ):
        assert_hour_precision(data[field], f"HourEntry.{field}")
    assert data["entry_status"] in [s.value for s in EntryStatus]
    assert data["verification_status"] in [s.value for s in VerificationStatus]
    assert data["source"] in [s.value for s in HourEntrySource]
    assert isinstance(data["is_weekend"], bool)
    assert isinstance(data["allocation_revision"], int)
    assert data["allocation_revision"] >= 0
    assert isinstance(data["submission_version"], int)
    assert_hours_conserved(data)


def assert_hours_conserved(entry: Dict[str, Any]) -> None:
    """`excluded_hours` is `raw_hours` less `direct_care_hours`, so the raw total
    is conserved across any allocation restatement."""
    assert float(entry["direct_care_hours"]) + float(
        entry["excluded_hours"]
    ) == approx_hours(float(entry["raw_hours"])), (
        "raw_hours must equal direct_care_hours + excluded_hours on "
        f"entry {entry.get('id')}"
    )


def assert_census_day(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CensusDay")
    assert is_valid_uuid(data["submission_id"])
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["reporting_period_id"])
    assert isinstance(data["census_date"], str)
    assert isinstance(data["resident_count"], int) and data["resident_count"] >= 0
    mds = data["mds_resident_count"]
    assert mds is None or (isinstance(mds, int) and mds >= 0)
    if data["variance_pct"] is not None:
        assert_ratio_precision(data["variance_pct"], "CensusDay.variance_pct")
    assert data["status"] in [s.value for s in CensusDayStatus]
    assert isinstance(data["is_weekend"], bool)
    assert isinstance(data["submission_version"], int)


def assert_quarterly_submission(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "QuarterlySubmission")
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["reporting_period_id"])
    assert data["status"] in [s.value for s in SubmissionStatus]
    for field in (
        "total_raw_hours",
        "total_direct_care_hours",
        "total_excluded_hours",
        "total_rn_direct_care_hours",
        "weekend_direct_care_hours",
        "vendor_sourced_hours",
    ):
        assert_hour_precision(data[field], f"QuarterlySubmission.{field}")
    assert isinstance(data["total_resident_days"], int)
    if data["hprd_reported"] is not None:
        assert_ratio_precision(
            data["hprd_reported"], "QuarterlySubmission.hprd_reported"
        )
    if data["weekend_hprd_reported"] is not None:
        assert_ratio_precision(
            data["weekend_hprd_reported"], "QuarterlySubmission.weekend_hprd_reported"
        )
    if data["audit_support_score"] is not None:
        assert_decimal_places(
            data["audit_support_score"], 2, "QuarterlySubmission.audit_support_score"
        )
    assert isinstance(data["open_fatal_finding_count"], int)
    assert isinstance(data["open_warning_finding_count"], int)
    assert isinstance(data["amendment_index"], int)
    assert_whole_cents(
        data["amendment_surcharge_cents"],
        "QuarterlySubmission.amendment_surcharge_cents",
    )
    assert_whole_cents(
        data["waived_surcharge_cents"], "QuarterlySubmission.waived_surcharge_cents"
    )
    assert isinstance(data["correction_deadline"], str)
    assert_submission_rollup_conserved(data)


def assert_submission_rollup_conserved(data: Dict[str, Any]) -> None:
    """The submission's direct-care and excluded rollups must sum to the raw
    rollup, because every entry's excluded hours are its raw less its direct."""
    assert float(data["total_direct_care_hours"]) + float(
        data["total_excluded_hours"]
    ) == approx_hours(float(data["total_raw_hours"])), (
        "total_raw_hours must equal total_direct_care_hours + total_excluded_hours"
    )


def assert_validation_finding(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ValidationFinding")
    assert is_valid_uuid(data["submission_id"])
    assert data["code"] in [c.value for c in FindingCode]
    assert data["severity"] in [s.value for s in FindingSeverity]
    assert data["status"] in [s.value for s in FindingStatus]
    assert isinstance(data["subject_ref"], str)
    assert isinstance(data["detail"], str)


def assert_staffing_measure(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "StaffingMeasure")
    assert is_valid_uuid(data["submission_id"])
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["reporting_period_id"])
    assert data["measure_variant"] in [v.value for v in MeasureVariant]
    assert data["publication_status"] in [s.value for s in _PublicationStatus]
    assert data["audit_status"] in [s.value for s in AuditStatus]
    for field in ("total_nurse_hprd", "rn_hprd", "weekend_total_nurse_hprd"):
        if data[field] is not None:
            assert_ratio_precision(data[field], f"StaffingMeasure.{field}")
    assert data["total_nurse_points"] in (1, 2, 3, 4, 5)
    assert data["rn_points"] in (1, 2, 3, 4, 5)
    assert isinstance(data["days_with_zero_rn_hours"], int)
    assert data["staffing_rating"] in (1, 2, 3, 4, 5)
    assert isinstance(data["has_open_appeal"], bool)
    if data["publication_status"] == PublicationStatus.PROVISIONAL.value:
        assert data["published_at"] is None
        assert data["appeal_deadline"] is None


def assert_discrepancy_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "DiscrepancyCase")
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["submission_id"])
    assert data["trigger_reason"] in [r.value for r in CaseTriggerReason]
    assert data["status"] in [s.value for s in CaseStatus]
    assert isinstance(data["auto_opened"], bool)
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert isinstance(data["info_request_count"], int)
    assert isinstance(data["facility_response_count"], int)
    assert isinstance(data["detail"], str)


def assert_rating_appeal(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "RatingAppeal")
    assert is_valid_uuid(data["staffing_measure_id"])
    assert is_valid_uuid(data["facility_id"])
    assert data["grounds"] in [g.value for g in AppealGrounds]
    assert data["status"] in [s.value for s in AppealStatus]
    assert isinstance(data["narrative"], str)
    assert is_valid_uuid(data["filed_by_worker_id"])
    assert_whole_cents(
        data["surcharge_waived_cents"], "RatingAppeal.surcharge_waived_cents"
    )


def assert_vendor_hour_submission(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "VendorHourSubmission")
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["reporting_period_id"])
    assert isinstance(data["attested_by"], str) and data["attested_by"]
    assert isinstance(data["line_count"], int) and data["line_count"] >= 1
    assert data["status"] in [s.value for s in VendorSubmissionStatus]
    assert_hour_precision(
        data["accepted_direct_care_hours"],
        "VendorHourSubmission.accepted_direct_care_hours",
    )
    assert isinstance(data["accepted_hour_entry_ids"], list)


# ---------------------------------------------------------------------------
# Computed-read assertions
# ---------------------------------------------------------------------------


def assert_hprd_read(data: Dict[str, Any], expected_variant: str) -> None:
    assert data["submission_id"]
    assert data["variant"] == expected_variant, (
        f"Expected the read to report variant {expected_variant}, "
        f"got {data['variant']}"
    )
    for field in (
        "total_direct_care_hours",
        "total_rn_hours",
        "weekend_direct_care_hours",
    ):
        assert_hour_precision(data[field], f"hprd read {field}")
    assert isinstance(data["resident_days"], int)
    assert isinstance(data["weekend_resident_days"], int)
    for field in ("total_nurse_hprd", "rn_hprd", "weekend_total_nurse_hprd"):
        if data[field] is not None:
            assert_ratio_precision(data[field], f"hprd read {field}")
    assert isinstance(data["implausible"], bool)


def assert_audit_readiness_read(data: Dict[str, Any], expected_variant: str) -> None:
    assert data["submission_id"]
    assert data["variant"] == expected_variant, (
        f"Expected the read to report variant {expected_variant}, "
        f"got {data['variant']}"
    )
    assert isinstance(data["considered_entry_count"], int)
    assert_hour_precision(data["considered_hours"], "considered_hours")
    assert_hour_precision(data["supported_hours"], "supported_hours")
    for field in (
        "support_ratio",
        "vendor_attestation_ratio",
        "census_reconciled_ratio",
    ):
        assert_ratio_precision(data[field], f"audit readiness {field}")
    assert_decimal_places(data["score"], 2, "audit readiness score")
    assert isinstance(data["at_risk"], bool)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_outstanding_surcharge_matches(
    facility: Dict[str, Any], submissions: list
) -> None:
    """`outstanding_surcharge_cents` is the sum, over every submission of the
    facility whose status is anything other than VOID, of that submission's
    `amendment_surcharge_cents` less its `waived_surcharge_cents`."""
    expected = sum(
        s["amendment_surcharge_cents"] - s["waived_surcharge_cents"]
        for s in submissions
        if s["status"] != SubmissionStatus.VOID.value
    )
    assert facility["outstanding_surcharge_cents"] == expected, (
        "Facility.outstanding_surcharge_cents must equal the sum over non-VOID "
        f"submissions of surcharge less waiver: expected {expected}, got "
        f"{facility['outstanding_surcharge_cents']}"
    )


def assert_instant_equals(
    value: Any, expected: str, field: str = "timestamp"
) -> None:
    """Two ISO 8601 UTC instants are compared by the instant they name.

    A stamped instant is written from the logical clock, and the number of
    fractional digits used to render it is not part of the instant, so
    `2026-08-01T00:00:00Z` and `2026-08-01T00:00:00.000Z` name the same moment.
    """
    assert value is not None, f"{field} must not be null"
    assert is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 UTC instant, got {value}"
    )
    actual = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    wanted = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert actual == wanted, f"{field} must be {expected}, got {value}"


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Every response carries a server-minted request id starting with `req_`
    and an ISO 8601 UTC timestamp with three fractional digits."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']}"
    )
    timestamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(timestamp), (
        f"api_request_timestamp must be an ISO 8601 UTC instant, got {timestamp}"
    )
    assert "." in timestamp, "api_request_timestamp must carry fractional digits"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"api_request_timestamp must carry three fractional digits, got {timestamp}"
    )


def find_finding(findings: list, code: str, subject_ref: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the first finding matching `code` (and `subject_ref` when given)."""
    for finding in findings:
        if finding["code"] != code:
            continue
        if subject_ref is not None and finding["subject_ref"] != subject_ref:
            continue
        return finding
    return None


def findings_with_code(findings: list, code: str) -> list:
    return [f for f in findings if f["code"] == code]
