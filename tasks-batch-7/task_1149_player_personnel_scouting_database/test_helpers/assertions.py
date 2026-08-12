"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, *, with_version: bool = True):
    """PRD §2.4: id/created_at/updated_at/version on primary resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_version:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(
            data.get("version"), int
        ), f"version must be an int, got {data.get('version')!r}"


def assert_scout(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["level"] in ("AREA", "DIRECTOR")


def assert_prospect(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["position"], str) and data["position"]
    assert data["evaluation_status"] in (
        "NEW",
        "SCOUTING",
        "EVALUATED",
        "BOARD_READY",
        "DRAFTED",
        "ARCHIVED",
    )
    assert data["flag_status"] in ("CLEAR", "UNDER_REVIEW", "CLEARED", "EXCLUDED")
    if data.get("composite_grade") is not None:
        assert isinstance(data["composite_grade"], (int, float))
    if data.get("tier") is not None:
        assert data["tier"] in ("T1", "T2", "T3", "T4")


def assert_report(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "LOCKED")
    assert isinstance(data["raw_grade"], (int, float))
    assert isinstance(data["scheme_fit"], (int, float))
    if data["status"] == "LOCKED":
        assert data["normalized_grade"] is not None


def assert_video_tag(data: dict):
    """VideoTag carries id and created_at only — no updated_at, no version (PRD §2.4)."""
    assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "VideoTag must not carry updated_at"
    assert "version" not in data, "VideoTag must not carry version"
    assert isinstance(data["start_sec"], int)
    assert isinstance(data["end_sec"], int)
    assert data["end_sec"] > data["start_sec"]
    assert data["tag"] in ("SCHEME", "ATHLETICISM", "TECHNIQUE", "CHARACTER")


def assert_flag(data: dict):
    assert_common_fields(data)
    assert data["flag_type"] in ("MEDICAL", "CHARACTER")
    assert data["severity"] in ("LOW", "HIGH")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "ESCALATED")


def assert_draft_board(data: dict):
    assert_common_fields(data)
    assert isinstance(data["season_year"], int)
    assert data["status"] in ("OPEN", "FROZEN", "FINALIZED")
    assert isinstance(data["active_entry_count"], int)


def assert_board_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert isinstance(data["fit_score"], (int, float))
    assert isinstance(data["active"], bool)


def assert_roster_need(data: dict):
    assert_common_fields(data)
    assert data["priority_tier"] in ("P1", "P2", "P3", "P4")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_free_agent_target(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "IDENTIFIED",
        "EVALUATING",
        "APPROVED",
        "OFFERED",
        "SIGNED",
        "RELEASED",
        "PASSED",
    )
    assert isinstance(data["annual_cap_hit_cents"], int)
    assert isinstance(data["base_salary_cents"], int)
    assert isinstance(data["signing_bonus_cents"], int)
    assert isinstance(data["contract_years"], int)


def assert_budget(data: dict):
    assert_common_fields(data)
    assert isinstance(data["base_cap_cents"], int)
    assert isinstance(data["rollover_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["posture"] in ("HEALTHY", "TIGHT")
    # Invariant: available = base_cap + rollover - committed
    assert (
        data["available_cents"]
        == data["base_cap_cents"] + data["rollover_cents"] - data["committed_cents"]
    ), (
        f"available_cents invariant broken: {data['available_cents']} != "
        f"{data['base_cap_cents']} + {data['rollover_cents']} - {data['committed_cents']}"
    )


def assert_interview(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_facility(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_booking(data: dict):
    assert_common_fields(data)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_outcome(data: dict):
    assert_common_fields(data)
    assert isinstance(data["season_year"], int)
    assert isinstance(data["games_started"], int) and data["games_started"] >= 0
    assert isinstance(data["pro_bowl"], bool)
    assert isinstance(data["outcome_percentile"], int)
    assert 0 <= data["outcome_percentile"] <= 100
