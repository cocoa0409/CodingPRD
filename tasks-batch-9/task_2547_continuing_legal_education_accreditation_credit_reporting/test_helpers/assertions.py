"""Record assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .constants import CYCLE_SUMMARY_FIELDS


# --- Shared shape helpers -----------------------------------------------

def assert_identity_and_versioning(data: dict):
    """Records that carry the common fields expose id, created_at, updated_at
    and version, and version starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_identity(data: dict):
    """Append-only records expose only id and created_at — no updated_at and
    no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "an append-only record must not carry updated_at"
    assert "version" not in data, "an append-only record must not carry version"


def assert_utc_millisecond_timestamp(value: str):
    """Timestamps are rendered in UTC with exactly three fractional digits."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"timestamp must be UTC and end in Z, got {value!r}"
    )
    assert "." in value, f"timestamp must carry fractional seconds, got {value!r}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits, got {value!r}"
    )


def assert_no_uuid_prefix(record_id: str):
    assert is_valid_uuid(record_id), f"identifier must be a bare UUID, got {record_id!r}"
    assert ":" not in record_id and "_" not in record_id, (
        f"identifier must carry no prefix, got {record_id!r}"
    )


# --- Per-record assertions ------------------------------------------------

def assert_provider(data: dict):
    assert_identity_and_versioning(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 200
    assert data["provider_type"] in [
        "BAR_ASSOCIATION", "LAW_SCHOOL", "GOVERNMENT", "COMMERCIAL", "LAW_FIRM",
    ]
    assert data["accreditation_status"] in [
        "APPLIED", "ACCREDITED", "PROBATIONARY", "SUSPENDED", "LAPSED", "DENIED",
    ]
    assert isinstance(data["self_certification_enabled"], bool)
    for counter in (
        "courses_total_count", "courses_self_certified_count",
        "attendance_reports_total_count", "attendance_reports_late_count",
        "substantiated_complaint_count", "audit_findings_count",
        "courses_sampled_lifetime",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0
    assert data["risk_score_variant"] in [
        "REVIEWED_WEIGHTING", "SELF_CERTIFIED_WEIGHTING",
    ]
    assert_risk_score_in_range(data["risk_score"])


def assert_risk_score_in_range(score):
    assert isinstance(score, (int, float)), f"risk_score must be numeric, got {score!r}"
    assert 0.0 <= float(score) <= 1.0, f"risk_score must sit in 0.00..1.00, got {score!r}"
    assert round(float(score), 2) == float(score), (
        f"risk_score must be rounded to two decimal places, got {score!r}"
    )


def assert_provider_standing_invariants(data: dict):
    """Self-certification and the risk-score weighting variant are both true
    of exactly the accredited sponsors."""
    accredited = data["accreditation_status"] == "ACCREDITED"
    assert data["self_certification_enabled"] is accredited, (
        "self_certification_enabled must be true exactly when the sponsor is ACCREDITED, "
        f"got {data['self_certification_enabled']!r} at {data['accreditation_status']}"
    )
    expected_variant = "SELF_CERTIFIED_WEIGHTING" if accredited else "REVIEWED_WEIGHTING"
    assert data["risk_score_variant"] == expected_variant, (
        f"risk_score_variant must be {expected_variant} at "
        f"{data['accreditation_status']}, got {data['risk_score_variant']}"
    )


def assert_course(data: dict):
    assert_identity_and_versioning(data)
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert data["delivery_format"] in [
        "LIVE_IN_PERSON", "LIVE_WEBCAST", "ON_DEMAND", "SELF_STUDY",
    ]
    assert data["approval_pathway"] in ["PROVIDER_ACCREDITED", "INDIVIDUAL_APPROVAL"]
    assert data["status"] in [
        "PENDING_APPROVAL", "APPROVED", "DENIED",
        "SUSPENDED_PENDING_REVIEW", "EXPIRED", "REVOKED",
    ]
    assert data["attendance_verification_method"] in [
        "ATTENDANCE_CODE", "CERTIFICATE", "ROSTER", "AFFIRMATION_ONLY",
    ]
    assert isinstance(data["total_minutes"], int) and data["total_minutes"] >= 30
    assert data["total_minutes"] % 15 == 0, (
        f"total_minutes must be a whole multiple of 15, got {data['total_minutes']}"
    )
    assert is_iso8601_timestamp(data["presented_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["credited_minutes_total"] == data["total_minutes"], (
        "credited_minutes_total is the sum of the allocation minutes and must equal "
        f"total_minutes: {data['credited_minutes_total']} vs {data['total_minutes']}"
    )
    assert isinstance(data["verified_credit_record_count"], int)
    assert data["verified_credit_record_count"] >= 0


def assert_attendance_code_shape(course: dict):
    """A minted attendance code is six characters long."""
    code = course.get("attendance_code")
    assert isinstance(code, str) and len(code) == 6, (
        f"attendance_code must be a six-character string, got {code!r}"
    )


def assert_credit_allocation(data: dict):
    assert_append_only_identity(data)
    assert data["category"] in ["GENERAL", "ETHICS", "TECHNOLOGY", "BIAS_ELIMINATION"]
    assert isinstance(data["minutes"], int) and data["minutes"] > 0
    assert data["minutes"] % 15 == 0, (
        f"an allocation must be a positive whole multiple of 15, got {data['minutes']}"
    )


def assert_course_application(data: dict):
    assert_identity_and_versioning(data)
    assert data["status"] in [
        "SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED",
        "APPEALED", "APPEAL_GRANTED", "APPEAL_DENIED",
    ]
    assert isinstance(data["info_request_round"], int) and 0 <= data["info_request_round"] <= 2
    assert isinstance(data["remand_count"], int) and 0 <= data["remand_count"] <= 1
    assert isinstance(data["supplement_count"], int) and data["supplement_count"] >= 0
    assert data["applicant_role"] in ["ProviderAdmin", "Attorney"]


def assert_attorney(data: dict):
    assert_identity_and_versioning(data)
    assert isinstance(data["bar_number"], str) and len(data["bar_number"]) >= 1
    assert isinstance(data["full_name"], str) and len(data["full_name"]) >= 1
    assert data["compliance_group"] in ["GROUP_1", "GROUP_2", "GROUP_3"]
    assert data["status"] in ["ACTIVE", "EXEMPT", "ADMIN_SUSPENDED", "INACTIVE"]
    assert isinstance(data["outstanding_fee_cents"], int)
    assert data["outstanding_fee_cents"] >= 0, (
        "outstanding_fee_cents may never fall below zero, got "
        f"{data['outstanding_fee_cents']}"
    )
    assert isinstance(data["open_deficiency_count"], int)
    assert isinstance(data["pending_recertification_count"], int)
    assert is_iso8601_timestamp(data["admission_date"])


def assert_compliance_cycle(data: dict):
    assert_identity_and_versioning(data)
    assert data["credit_status"] in ["OPEN", "SATISFIED", "DEFICIENT", "CLOSED_COMITY"]
    assert data["administrative_status"] in [
        "GOOD_STANDING", "DELINQUENT", "ADMIN_SUSPENDED", "REINSTATED",
    ]
    assert data["carryover_election"] in ["CARRY_FORWARD", "WAIVE_CARRYOVER"]
    assert isinstance(data["prorated"], bool)
    for field in (
        "required_total_minutes", "required_ethics_minutes",
        "required_technology_minutes", "required_bias_minutes",
        "carryover_in_general_minutes", "carryover_in_ethics_minutes",
        "carryover_out_general_minutes", "carryover_out_ethics_minutes",
        "earned_countable_minutes", "earned_ethics_minutes",
        "earned_technology_minutes", "earned_bias_minutes", "earned_live_minutes",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative whole number of minutes, got {data[field]!r}"
        )
    assert data["period_start"] < data["period_end"], (
        "period_start must be strictly earlier than period_end"
    )
    assert is_iso8601_timestamp(data["filing_deadline"])


def assert_whole_hour_requirement(minutes: int):
    """The period requirement is rounded up to a whole credit hour."""
    assert minutes % 60 == 0, (
        f"a period requirement must be a whole number of credit hours, got {minutes}"
    )


def assert_affirmation(data: dict):
    assert_append_only_identity(data)
    assert data["affirmation_type"] in [
        "ATTENDANCE_AFFIRMATION", "SELF_STUDY_AFFIRMATION", "FINAL_COMPLIANCE_AFFIRMATION",
    ]
    assert isinstance(data["statement"], str) and 1 <= len(data["statement"]) <= 500


def assert_credit_record(data: dict):
    assert_identity_and_versioning(data)
    assert data["status"] in ["PENDING_VERIFICATION", "VERIFIED", "REJECTED", "VOIDED"]
    assert data["verification_method"] in [
        "ATTENDANCE_CODE", "CERTIFICATE", "ROSTER", "AFFIRMATION",
    ]
    assert data["source"] in ["IN_STATE", "RECIPROCITY", "COMITY"]
    assert data["effective_format"] in ["LIVE", "ON_DEMAND", "SELF_STUDY"]
    for field in (
        "credited_minutes", "credited_general_minutes", "credited_ethics_minutes",
        "credited_technology_minutes", "credited_bias_minutes", "countable_minutes",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative whole number of minutes, got {data[field]!r}"
        )
    assert data["credited_minutes"] == (
        data["credited_general_minutes"] + data["credited_ethics_minutes"]
        + data["credited_technology_minutes"] + data["credited_bias_minutes"]
    ), "the per-category credited minutes must sum to credited_minutes"
    assert data["countable_minutes"] <= data["credited_minutes"], (
        "countable_minutes may never exceed credited_minutes"
    )


def assert_minutes_on_quarter_hour(minutes: int, label="minutes"):
    assert minutes % 15 == 0, (
        f"{label} must land on a whole quarter hour, got {minutes}"
    )


def assert_attendance_report(data: dict):
    assert_identity_and_versioning(data)
    assert data["status"] in ["ACCEPTED", "ACCEPTED_LATE"]
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 1
    assert data["accepted_entry_count"] + data["rejected_entry_count"] == data["entry_count"], (
        "accepted_entry_count and rejected_entry_count must sum to entry_count: "
        f"{data['accepted_entry_count']} + {data['rejected_entry_count']} != "
        f"{data['entry_count']}"
    )
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert is_iso8601_timestamp(data["session_date"])
    assert is_iso8601_timestamp(data["session_end"])
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_reciprocity_claim(data: dict):
    assert_identity_and_versioning(data)
    assert data["basis"] in ["RECIPROCITY", "COMITY"]
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED"]
    assert data["converted_category"] in [
        "GENERAL", "ETHICS", "TECHNOLOGY", "BIAS_ELIMINATION",
    ]
    assert isinstance(data["converted_minutes"], int) and data["converted_minutes"] >= 0
    assert data["origin_category"] in [
        "GENERAL", "PROFESSIONALISM", "ETHICS", "TECHNOLOGY", "DIVERSITY_INCLUSION",
    ]


def assert_provider_audit(data: dict):
    assert_identity_and_versioning(data)
    assert data["status"] in [
        "OPENED", "SAMPLED", "FINDINGS_ISSUED", "CLEARED", "SANCTIONED",
    ]
    assert data["trigger_type"] in ["RISK_BASED", "COMPLAINT_ESCALATION", "RANDOM"]
    assert data["sanction_type"] in ["NONE", "PROBATION", "SUSPENSION"]
    assert isinstance(data["sampled_course_ids"], list)
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 0
    assert data["sample_size"] == len(data["sampled_course_ids"]), (
        "sample_size must equal the number of sampled course identifiers: "
        f"{data['sample_size']} vs {len(data['sampled_course_ids'])}"
    )
    assert isinstance(data["findings_count"], int) and data["findings_count"] >= 0
    assert data["findings_count"] <= data["sample_size"], (
        "findings_count may never exceed sample_size"
    )
    assert_risk_score_in_range(data["risk_score_at_open"])


def assert_complaint(data: dict):
    assert_identity_and_versioning(data)
    assert data["subject_type"] in ["PROVIDER", "COURSE"]
    assert data["status"] in ["RECEIVED", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED"]
    assert data["allegation_category"] in [
        "MISREPRESENTED_CREDIT", "NO_SHOW_FACULTY", "ATTENDANCE_FRAUD", "FEE_DISPUTE",
    ]
    assert data["complainant_role"] in ["ATTORNEY", "BOARD_ADMIN"]
    assert isinstance(data["escalated"], bool)
    assert isinstance(data["allegation"], str) and 1 <= len(data["allegation"]) <= 2000


def assert_fee_assessment(data: dict):
    assert_identity_and_versioning(data)
    assert data["fee_type"] in [
        "LATE_COMPLIANCE", "REINSTATEMENT", "AUDIT_SANCTION", "PROVIDER_ANNUAL",
    ]
    assert data["status"] in ["ASSESSED", "PAID", "WAIVED", "VOIDED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0, (
        f"amount_cents must be a whole number of cents, got {data['amount_cents']!r}"
    )
    assert is_iso8601_timestamp(data["assessed_at"])


def assert_reporting_sweep(data: dict):
    assert_append_only_identity(data)
    assert isinstance(data["sweep_number"], int) and data["sweep_number"] >= 1
    assert is_iso8601_timestamp(data["as_of"])
    for tally in (
        "cycles_examined", "delinquencies_issued", "suspensions_issued",
        "late_fees_assessed_cents", "courses_expired", "providers_lapsed",
    ):
        assert isinstance(data[tally], int) and data[tally] >= 0, (
            f"{tally} must be a non-negative integer, got {data[tally]!r}"
        )


def assert_cycle_summary_shape(data: dict):
    """The computed cycle read carries every field the PRD names."""
    missing = [field for field in CYCLE_SUMMARY_FIELDS if field not in data]
    assert not missing, f"the cycle summary is missing {missing}"


# --- Domain invariants ----------------------------------------------------

def assert_fee_ledger_reconciled(attorney: dict, assessments: list):
    """outstanding_fee_cents equals the sum of that attorney's assessments
    still in the assessed state."""
    expected = sum(
        item["amount_cents"] for item in assessments
        if item["status"] == "ASSESSED" and item.get("attorney_id") == attorney["id"]
    )
    assert attorney["outstanding_fee_cents"] == expected, (
        "outstanding_fee_cents must equal the sum of the attorney's ASSESSED "
        f"assessments: {attorney['outstanding_fee_cents']} vs {expected}"
    )


def assert_carryover_chain(predecessor: dict, successor: dict):
    """The successor's incoming carryover equals the predecessor's outgoing
    carryover, in both the general and the ethics dimension."""
    assert successor["carryover_in_general_minutes"] == predecessor["carryover_out_general_minutes"], (
        "carryover_in_general_minutes must equal the predecessor's "
        f"carryover_out_general_minutes: {successor['carryover_in_general_minutes']} vs "
        f"{predecessor['carryover_out_general_minutes']}"
    )
    assert successor["carryover_in_ethics_minutes"] == predecessor["carryover_out_ethics_minutes"], (
        "carryover_in_ethics_minutes must equal the predecessor's "
        f"carryover_out_ethics_minutes: {successor['carryover_in_ethics_minutes']} vs "
        f"{predecessor['carryover_out_ethics_minutes']}"
    )


def assert_version_unchanged(before: dict, after: dict):
    """A rejected write leaves the record's version where it was."""
    assert before["version"] == after["version"], (
        f"a rejected write must not bump version: {before['version']} -> {after['version']}"
    )


def assert_pagination_meta(meta: dict, limit, offset, total_count=None):
    assert meta["limit"] == limit, f"limit must be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset must be {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count must be {total_count}, got {meta['total_count']}"
        )
    assert isinstance(meta["has_more"], bool)


def assert_ordered_by(items: list, *fields):
    """Ascending order over the named fields, in the order given."""
    keys = [tuple(item[field] for field in fields) for item in items]
    assert keys == sorted(keys), f"items must be ordered ascending by {fields}, got {keys}"


def assert_ordered_desc_by(items: list, field: str):
    keys = [item[field] for item in items]
    assert keys == sorted(keys, reverse=True), (
        f"items must be ordered descending by {field}, got {keys}"
    )
