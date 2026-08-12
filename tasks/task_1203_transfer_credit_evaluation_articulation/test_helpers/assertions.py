"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import GRADE_SCALE


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_partner_institution(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["institution_code"], str) and data["institution_code"]
    assert data["credit_system"] in ("SEMESTER", "QUARTER")


def assert_internal_course(data: dict):
    _assert_common(data)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["title"], str) and data["title"]
    hours = data["credit_hours"]
    assert isinstance(hours, (int, float))
    assert 0.5 <= hours <= 6.0 and (hours * 2) == int(hours * 2)
    assert data["level"] in ("LOWER", "UPPER", "GRADUATE")
    assert isinstance(data["department"], str) and data["department"]
    assert isinstance(data["gened_tags"], list)
    assert isinstance(data["is_active"], bool)


def assert_articulation_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["partner_institution_id"])
    assert isinstance(data["program_scope"], str) and data["program_scope"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "SUPERSEDED")
    assert "effective_start" in data and "effective_end" in data


def assert_course_equivalency(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["internal_course_id"])
    assert isinstance(data["external_course_code"], str) and data["external_course_code"]
    assert isinstance(data["external_credit_hours"], (int, float)) and data["external_credit_hours"] > 0
    assert data["equivalency_type"] in ("DIRECT", "GENED_ONLY", "ELECTIVE")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_transfer_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["declared_major"], str) and data["declared_major"]
    assert isinstance(data["catalog_year"], int)
    assert isinstance(data["total_posted_transfer_credits"], (int, float))
    assert isinstance(data["total_posted_pla_credits"], (int, float))


def assert_transcript(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["partner_institution_id"])
    assert data["status"] in ("RECEIVED", "VERIFIED", "EXTRACTED", "REJECTED")
    assert isinstance(data["courses"], list)
    for c in data["courses"]:
        assert c["grade"] in GRADE_SCALE, f"grade {c.get('grade')} must be on the grade scale"


def assert_transfer_credit_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["transcript_id"])
    assert data["status"] in ("DRAFT", "IN_REVIEW", "EVALUATED", "POSTED")
    assert isinstance(data["provisional_credits_total"], (int, float))
    assert isinstance(data["awarded_credits_total"], (int, float))
    assert isinstance(data["applied_credits_total"], (int, float))
    assert isinstance(data["open_line_count"], int)


def assert_evaluation_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["evaluation_id"])
    assert isinstance(data["external_course_code"], str)
    assert data["status"] in (
        "PENDING", "AUTO_MATCHED", "PETITION_REQUIRED", "ADOPTED", "DENIED", "POSTED",
    )
    if data.get("resolution") is not None:
        assert data["resolution"] in ("AUTO_EQUIVALENCY", "MANUAL_OVERRIDE", "PETITION", "AUTO_GRADE")


def assert_petition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["line_item_id"])
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["proposed_internal_course_id"])
    assert isinstance(data["syllabus_ref"], str) and data["syllabus_ref"]
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["petition_id"])
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["grounds"], str) and len(data["grounds"]) >= 20
    assert data["status"] in ("FILED", "UNDER_REVIEW", "UPHELD", "OVERTURNED")


def assert_prior_learning_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert data["source_type"] in ("MILITARY_JST", "CLEP", "AP", "IB", "PORTFOLIO")
    assert isinstance(data["claimed_credits"], (int, float)) and data["claimed_credits"] > 0
    assert data["status"] in ("SUBMITTED", "VERIFIED", "CREDITED", "REJECTED")


def assert_requirement_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    # Exactly one of line_item_id / pla_id is set (polymorphic source).
    assert (data.get("line_item_id") is None) != (data.get("pla_id") is None)
    assert data["slot"] in (
        "MAJOR_CORE", "MAJOR_ELECTIVE", "GENED_COMMS", "GENED_MATH",
        "GENED_SCIENCE", "GENED_HUMANITIES", "GENED_SOCIAL", "FREE_ELECTIVE",
    )
    assert isinstance(data["applied_credits"], (int, float))
    assert data["status"] in ("APPLIED", "PARTIAL", "UNAPPLIED")


def assert_transfer_guide(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["partner_institution_id"])
    assert isinstance(data["catalog_year"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "ARCHIVED")
    assert isinstance(data["is_stale"], bool)


def assert_posted_credit_ledger_invariant(student: dict, posted_lines: list):
    """The student's total_posted_transfer_credits equals the sum of
    applied_credits over lines currently in POSTED."""
    expected = sum(line.get("applied_credits") or 0.0 for line in posted_lines)
    actual = student["total_posted_transfer_credits"]
    assert actual == expected, (
        f"posted ledger invariant violated: student total {actual} != "
        f"sum of POSTED applied_credits {expected}"
    )
