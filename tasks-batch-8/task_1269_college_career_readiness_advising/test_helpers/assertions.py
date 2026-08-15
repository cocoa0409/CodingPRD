"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
import re

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

# PRD §2.4: created_at/updated_at are ISO 8601 UTC with three fractional digits.
_THREE_FRACTION_RE = re.compile(r"\.\d{3}(Z|[+-]\d{2}:?\d{2})$")


def assert_common_fields(data: dict):
    """System-managed properties every entity carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_three_fraction_digits(timestamp: str):
    """Timestamps carry exactly three fractional digits (PRD §2.4)."""
    assert isinstance(timestamp, str) and _THREE_FRACTION_RE.search(timestamp), (
        f"expected ISO 8601 UTC with three fractional digits, got {timestamp!r}"
    )


def assert_pct(actual, expected):
    """Two-decimal rounded figure; tight tolerance so a different rounding
    order or a missed cap cannot pass (PRD §2.10)."""
    assert actual == pytest.approx(expected, abs=0.001), (
        f"expected {expected}, got {actual}"
    )


def assert_student(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_ref"], str) and data["student_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["grade_level"] in (9, 10, 11, 12)
    assert data["demographic_group"] in ("GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D")
    assert isinstance(data["first_generation"], bool)
    assert data["status"] in ("ENROLLED", "GRADUATED", "TRANSFERRED_OUT", "WITHDRAWN")
    assert data.get("assigned_advisor_id") is None or isinstance(
        data["assigned_advisor_id"], str)


def assert_advisor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] >= 1
    assert data["status"] in ("ACTIVE", "INACTIVE")
    # PRD §3.1: the three computed load views appear on the advisor record.
    assert isinstance(data["active_caseload_count"], int)
    assert isinstance(data["caseload_load_simple"], (int, float))
    assert isinstance(data["caseload_load_weighted"], (int, float))


def assert_teacher(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["department"], str)
    assert isinstance(data["max_active_letters"], int) and data["max_active_letters"] >= 1
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["open_request_count"], int)


def assert_pathway(data: dict):
    assert_common_fields(data)
    assert isinstance(data["pathway_code"], str) and data["pathway_code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["required_course_codes"], list)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_plan(data: dict):
    """A plan's full derived state is returned on single-plan reads (PRD §3.2)."""
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["pathway_id"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "REVISING", "SUPERSEDED")
    for field in ("alignment_provisional_pct", "alignment_official_pct",
                  "milestone_pct", "milestone_pct_lenient", "wbl_hours_pct",
                  "certification_points", "readiness_provisional",
                  "readiness_official"):
        assert isinstance(data.get(field), (int, float)), \
            f"plan derived field {field} missing or non-numeric: {data.get(field)!r}"


def assert_enrollment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["course_code"], str)
    assert isinstance(data["credits"], (int, float)) and data["credits"] > 0
    assert data["status"] in ("PLANNED", "ENROLLED", "COMPLETED", "FAILED", "DROPPED")
    assert isinstance(data["counts_toward_pathway"], bool)


def assert_application(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["college_name"], str)
    assert data["program_type"] in ("COLLEGE_4YR", "COLLEGE_2YR", "TRADE_PROGRAM")
    assert is_iso8601_timestamp(data["deadline_at"])
    assert data["submission_status"] in ("DRAFT", "READY", "SUBMITTED",
                                         "CONFIRMED", "WITHDRAWN")
    assert data["decision_status"] in ("NONE", "PENDING", "ACCEPTED",
                                       "WAITLISTED", "DENIED", "DEFERRED")


def assert_milestone(data: dict):
    assert_common_fields(data)
    assert isinstance(data["application_id"], str)
    assert data["kind"] in ("ESSAY", "TRANSCRIPT", "FEE_PAYMENT", "TEST_SCORES",
                            "REC_LETTERS", "FAFSA", "INTERVIEW", "OTHER")
    assert isinstance(data["required"], bool)
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("PENDING", "READY", "COMPLETED", "MISSED", "WAIVED")


def assert_rec_request(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["teacher_id"], str)
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("REQUESTED", "ACCEPTED", "DECLINED", "SUBMITTED",
                              "VERIFIED", "WITHDRAWN")
    assert isinstance(data["reroute_count"], int)


def assert_certification(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["cert_code"], str) and data["cert_code"]
    assert data["status"] in ("REGISTERED", "EXAM_SCHEDULED", "PASSED",
                              "FAILED", "CANCELLED")
    assert isinstance(data["retake_count"], int)


def assert_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["max_concurrent_placements"], int) \
        and data["max_concurrent_placements"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    # PRD §3.6: the site record carries confirmed_active_count.
    assert isinstance(data["confirmed_active_count"], int)


def assert_placement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["site_id"], str)
    assert is_iso8601_timestamp(data["term_start"])
    assert is_iso8601_timestamp(data["term_end"])
    assert isinstance(data["hours_per_week"], (int, float)) \
        and data["hours_per_week"] > 0
    assert data["status"] in ("OFFERED", "CONFIRMED", "ACTIVE", "COMPLETED",
                              "DECLINED", "TERMINATED")
    assert isinstance(data["hours_logged"], (int, float))


def assert_senior_audit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["auditor_advisor_id"], str)
    assert data["status"] in ("DRAFT", "IN_REVIEW", "FLAGGED", "CERTIFIED")
    # PRD §3.7: the audit snapshots required_credits at 24.
    assert data["required_credits"] == 24
    assert isinstance(data["credits_earned"], (int, float))
    for flag in ("pathway_requirements_met", "certification_requirement_met",
                 "work_hours_met"):
        assert isinstance(data.get(flag), bool), \
            f"audit computed flag {flag} missing or non-boolean"


def assert_outcome_record(data: dict):
    assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert data["outcome_type"] in ("ENROLLED_4YR", "ENROLLED_2YR",
                                    "APPRENTICESHIP", "EMPLOYED",
                                    "MILITARY", "OTHER")
    assert is_iso8601_timestamp(data["reported_at"])
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "DISPUTED")


def assert_ops_run(data: dict):
    assert_common_fields(data)
    # PRD §3.8: the run record is retrievable afterwards with all four counters.
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    assert is_iso8601_timestamp(data["executed_at"])
    for counter in ("milestones_marked_missed", "applications_regressed",
                    "reminders_queued", "plans_recomputed"):
        assert isinstance(data.get(counter), int), \
            f"ops-run counter {counter} missing or non-integer"


def assert_equity_report(data: dict):
    """The equity report returns all of these figures together (PRD §3.1)."""
    for field in ("advisor_id", "active_caseload_count", "caseload_load_simple",
                  "caseload_load_weighted", "equity_gap_index",
                  "target_caseload", "district_total_students",
                  "district_total_capacity"):
        assert field in data, f"equity report missing field {field}"
    assert isinstance(data["active_caseload_count"], int)
    assert isinstance(data["district_total_students"], int)
    assert isinstance(data["district_total_capacity"], int)


def assert_error_envelope(body: dict):
    """Error envelope shape (PRD §2.2)."""
    assert body.get("response_type") == "error"
    meta = body.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str)
    assert isinstance(meta.get("api_request_timestamp"), str)
    data = body.get("data", {})
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str) and data["message"]
