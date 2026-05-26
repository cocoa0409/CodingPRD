"""Entity assertions and domain invariant checkers (PRD §2.4)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_fields(data: dict) -> None:
    """Every persistent resource carries id (UUID) + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def _with_versioning(data: dict) -> None:
    """Entities with common_fields:true additionally carry updated_at + version (PRD §2.4)."""
    _common_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be integer >= 1, got {data.get('version')!r}"


def assert_department(data: dict) -> None:
    _with_versioning(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["cost_center_code"], str) and len(data["cost_center_code"]) > 0
    assert isinstance(data["hiring_budget_cents"], int) and data["hiring_budget_cents"] >= 0
    assert isinstance(data["committed_offer_cents"], int) and data["committed_offer_cents"] >= 0


def assert_requisition(data: dict) -> None:
    _with_versioning(data)
    assert data["status"] in {"DRAFT", "PENDING_APPROVAL", "APPROVED",
                              "REJECTED", "CLOSED", "CANCELLED"}
    assert data["target_level"] in {"JUNIOR", "MID", "SENIOR", "STAFF"}
    assert isinstance(data["openings"], int) and data["openings"] >= 1
    assert isinstance(data["base_salary_min_cents"], int) and data["base_salary_min_cents"] >= 0
    assert isinstance(data["base_salary_max_cents"], int)
    assert data["base_salary_max_cents"] > data["base_salary_min_cents"]
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0


def assert_candidate(data: dict) -> None:
    _with_versioning(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert data["source_channel"] in {"DIRECT", "REFERRAL", "AGENCY", "JOB_BOARD"}
    assert data["eeo_ethnicity"] in {"WHITE", "BLACK", "HISPANIC", "ASIAN",
                                     "NATIVE", "PACIFIC", "TWO_OR_MORE", "DECLINED"}
    assert data["eeo_gender"] in {"FEMALE", "MALE", "NONBINARY", "DECLINED"}
    assert isinstance(data["eeo_veteran"], bool)
    assert isinstance(data["eeo_disability"], bool)


def assert_application(data: dict) -> None:
    _with_versioning(data)
    assert data["status"] in {"APPLIED", "SCREENING", "INTERVIEWING", "OFFER_EXTENDED",
                              "HIRED", "REJECTED", "WITHDRAWN"}


def assert_interview(data: dict) -> None:
    _with_versioning(data)
    assert data["status"] in {"SCHEDULED", "COMPLETED", "CANCELLED"}
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 15
    assert isinstance(data["panel_user_ids"], list)


def assert_interview_feedback(data: dict) -> None:
    """InterviewFeedback is append-only: ONLY id + created_at (PRD §2.4)."""
    _common_fields(data)
    # No updated_at, no version per PRD §2.4: "The InterviewFeedback resource is a
    # write-once log row and carries only `id` and `created_at`; it has no `updated_at`
    # and no `version`."
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5


def assert_offer(data: dict) -> None:
    _with_versioning(data)
    assert data["status"] in {"PENDING_APPROVAL", "APPROVED", "EXTENDED",
                              "ACCEPTED", "DECLINED", "REJECTED", "REVOKED"}
    assert isinstance(data["base_salary_cents"], int) and data["base_salary_cents"] >= 0
    assert isinstance(data["signing_bonus_cents"], int) and data["signing_bonus_cents"] >= 0


def assert_background_check(data: dict) -> None:
    _with_versioning(data)
    assert data["status"] in {"INITIATED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELLED"}


def assert_referral_bonus(data: dict) -> None:
    _with_versioning(data)
    assert data["status"] in {"PENDING_BGC", "PAYABLE", "PAID", "VOID"}
    assert isinstance(data["estimated_amount_cents"], int) and data["estimated_amount_cents"] >= 0


def assert_diversity_goal(data: dict) -> None:
    _with_versioning(data)
    assert data["target_level"] in {"JUNIOR", "MID", "SENIOR", "STAFF"}
    assert isinstance(data["period_year"], int) and data["period_year"] >= 2000
    assert 0.0 <= float(data["target_underrepresented_pct"]) <= 1.0
    assert 0.0 <= float(data["pool_underrepresented_pct"]) <= 1.0
    assert 0.0 <= float(data["hire_underrepresented_pct"]) <= 1.0


# ---------------- Domain invariants ----------------

def assert_committed_offer_nonneg(department: dict) -> None:
    """PRD §3.1: committed_offer_cents starts at zero, and §2.9 sums of active offers' base
    salaries are non-negative integers."""
    assert isinstance(department["committed_offer_cents"], int)
    assert department["committed_offer_cents"] >= 0


def assert_filled_count_consistent(requisition: dict) -> None:
    """filled_count is bounded by openings (PRD §3.2)."""
    assert isinstance(requisition["filled_count"], int)
    assert requisition["filled_count"] >= 0
    # Hard upper bound for openings: filled_count == openings auto-CLOSES per §3.2,
    # so filled_count cannot legitimately exceed openings.
    assert requisition["filled_count"] <= requisition["openings"]
