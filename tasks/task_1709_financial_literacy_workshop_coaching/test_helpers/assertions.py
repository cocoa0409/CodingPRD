"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_mutable_common_fields(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_curriculum_module(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["module_code"], str) and data["module_code"]
    assert isinstance(data["title"], str)
    assert isinstance(data["session_count"], int) and data["session_count"] >= 1
    assert isinstance(data["incentive_cents_per_hour"], int) and data["incentive_cents_per_hour"] >= 0
    assert isinstance(data["completion_bonus_cents"], int) and data["completion_bonus_cents"] >= 0
    assert isinstance(data["completion_threshold"], int) and data["completion_threshold"] >= 1
    assert data["completion_threshold"] <= data["session_count"]
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_coach(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] >= 1
    assert data["status"] in ("CANDIDATE", "CERTIFIED", "SUSPENDED", "LAPSED")
    assert data.get("certification_expires_at") is None or is_iso8601_timestamp(
        data["certification_expires_at"]
    )
    assert isinstance(data.get("active_caseload"), int) and data["active_caseload"] >= 0


def assert_participant(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RESTRICTED", "EXITED")
    assert isinstance(data.get("no_show_count"), int) and data["no_show_count"] >= 0


def assert_workshop(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["module_id"], str)
    assert isinstance(data["coach_id"], str)
    assert isinstance(data["location"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data.get("confirmed_count"), int)
    assert 0 <= data["confirmed_count"] <= data["capacity"]
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_registration(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["workshop_id"], str)
    assert isinstance(data["participant_id"], str)
    assert data["status"] in ("REGISTERED", "WAITLISTED", "ATTENDED", "NO_SHOW", "CANCELLED")
    assert "waitlist_position" in data
    assert data["waitlist_position"] is None or isinstance(data["waitlist_position"], int)
    assert isinstance(data.get("incentive_earned_cents"), int) and data["incentive_earned_cents"] >= 0


def assert_coaching_case(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["coach_id"], str)
    assert isinstance(data["intake_date"], str)
    assert data["status"] in (
        "INTAKE", "PLAN_DRAFT", "PLAN_ACTIVE", "ON_HOLD",
        "PLAN_STALLED", "COMPLETED", "EXITED",
    )


def assert_goal_plan(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["monthly_savings_goal_cents"], int) and data["monthly_savings_goal_cents"] > 0
    assert isinstance(data["credit_score_target"], int) and 300 <= data["credit_score_target"] <= 850
    assert data["status"] in ("DRAFT", "ACTIVE", "FROZEN", "SUPERSEDED", "ACHIEVED")
    assert isinstance(data.get("plan_sequence"), int) and data["plan_sequence"] >= 1


def assert_outcome_snapshot(data: dict):
    # Append-only log entry: id + created_at only — no updated_at, no version.
    _assert_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert is_iso8601_timestamp(data["recorded_at"])
    assert "updated_at" not in data, "append-only snapshot must not carry updated_at"
    assert "version" not in data, "append-only snapshot must not carry version"
    if data.get("credit_score") is not None:
        assert 300 <= data["credit_score"] <= 850
    if data.get("savings_balance_cents") is not None:
        assert data["savings_balance_cents"] >= 0


def assert_match_pool(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["total_funded_cents"], int) and data["total_funded_cents"] > 0
    assert isinstance(data["income_threshold_cents"], int)
    assert isinstance(data["per_participant_cap_cents"], int) and data["per_participant_cap_cents"] > 0
    assert isinstance(data.get("uncommitted_cents"), int)
    assert isinstance(data.get("paid_out_cents"), int) and data["paid_out_cents"] >= 0
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_match_enrollment(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["pool_id"], str)
    assert isinstance(data["goal_plan_id"], str)
    assert isinstance(data["savings_goal_cents"], int) and data["savings_goal_cents"] > 0
    assert data["status"] in ("ACTIVE", "MATCH_PAUSED", "GOAL_MET", "PAID_OUT", "FORFEITED")
    assert isinstance(data.get("total_deposited_cents"), int) and data["total_deposited_cents"] >= 0
    assert isinstance(data.get("accrued_unpaid_cents"), int) and data["accrued_unpaid_cents"] >= 0


def assert_referral(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["coach_id"], str)
    assert isinstance(data["partner_name"], str)
    assert data["partner_type"] in ("LENDER", "ASSISTANCE_PROGRAM")
    assert data["status"] in ("SENT", "ACCEPTED", "DECLINED", "COMPLETED", "EXPIRED")
    assert is_iso8601_timestamp(data["sent_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_funder_report(data: dict):
    # Frozen at creation: id + created_at only — no updated_at, no version.
    _assert_common_fields(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["variant"] in ("COHORT", "ROLLING")
    assert isinstance(data.get("participants_measured"), int) and data["participants_measured"] >= 0
    assert data.get("avg_credit_delta_points") is None or isinstance(
        data["avg_credit_delta_points"], (int, float)
    )
    assert data.get("avg_savings_delta_cents") is None or isinstance(
        data["avg_savings_delta_cents"], int
    )
    assert isinstance(data.get("completions_count"), int) and data["completions_count"] >= 0
    assert "updated_at" not in data, "frozen report must not carry updated_at"
    assert "version" not in data, "frozen report must not carry version"


def assert_pool_conservation(pool: dict, enrollments: list):
    """Pool fund conservation identity (PRD §2.9):
    total_funded_cents == uncommitted_cents
        + sum(accrued_unpaid_cents over non-terminal enrollments)
        + paid_out_cents.
    """
    non_terminal_statuses = ("ACTIVE", "MATCH_PAUSED", "GOAL_MET")
    accrued_outstanding = sum(
        e["accrued_unpaid_cents"] for e in enrollments if e["status"] in non_terminal_statuses
    )
    lhs = pool["total_funded_cents"]
    rhs = pool["uncommitted_cents"] + accrued_outstanding + pool["paid_out_cents"]
    assert lhs == rhs, (
        f"pool conservation violated: total_funded_cents {lhs} != "
        f"uncommitted {pool['uncommitted_cents']} + accrued {accrued_outstanding} "
        f"+ paid_out {pool['paid_out_cents']}"
    )
