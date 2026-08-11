"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_name"), str) and data["program_name"]
    assert isinstance(data.get("owner_organization"), str) and data["owner_organization"]
    assert data.get("status") in ("CHARTERING", "ACTIVE", "CLOSING", "CLOSED")
    assert isinstance(data.get("contingency_total_cents"), int)
    assert isinstance(data.get("contingency_reserved_cents"), int)
    assert isinstance(data.get("contingency_committed_cents"), int)
    assert isinstance(data.get("contingency_drawn_cents"), int)
    assert isinstance(data.get("contingency_available_cents"), int)
    assert data.get("contingency_posture") in ("NORMAL", "WATCH", "CRITICAL")


def assert_charter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("version_no"), int) and data["version_no"] >= 1
    assert isinstance(data.get("objectives"), str)
    assert isinstance(data.get("scope_statement"), str)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "SUPERSEDED")


def assert_baseline(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("version_no"), int) and data["version_no"] >= 1
    assert isinstance(data.get("total_budget_cents"), int) and data["total_budget_cents"] > 0
    assert isinstance(data.get("contingency_total_cents"), int) and data["contingency_total_cents"] >= 0
    assert isinstance(data.get("target_finish_date"), str)
    assert isinstance(data.get("lines"), list)
    for line in data["lines"]:
        assert isinstance(line.get("cost_code"), str) and line["cost_code"]
        assert isinstance(line.get("amount_cents"), int) and line["amount_cents"] > 0
    assert data.get("status") in ("DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "SUPERSEDED")


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("vendor_name"), str) and data["vendor_name"]
    assert data.get("contract_type") in ("CONSULTANT", "CONTRACTOR")
    assert isinstance(data.get("solicitation_estimate_cents"), int) and data["solicitation_estimate_cents"] > 0
    assert data.get("status") in ("SOLICITED", "UNDER_NEGOTIATION", "COUNTERED", "EXECUTED", "COMPLETED")
    assert isinstance(data.get("negotiation_rounds"), int) and data["negotiation_rounds"] >= 0


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("reason"), str)
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("status") in ("DRAFT", "UNDER_REVIEW", "RECOMMEND_APPROVAL",
                                   "RECOMMEND_REJECTION", "APPROVED", "REJECTED", "VOID")


def assert_risk_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("title"), str)
    assert data.get("category") in ("SCHEDULE", "COST", "SCOPE", "STAKEHOLDER", "SITE")
    assert isinstance(data.get("probability_pct"), int) and 1 <= data["probability_pct"] <= 100
    assert isinstance(data.get("impact_cents"), int) and data["impact_cents"] >= 0
    assert isinstance(data.get("exposure_cents"), int) and data["exposure_cents"] >= 0
    assert data.get("status") in ("IDENTIFIED", "ASSESSED", "MITIGATING", "MONITORING",
                                   "ESCALATED", "REALIZED", "CLOSED")


def assert_drawdown(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert data.get("source") in ("MANUAL_RESERVE", "RISK_REALIZATION", "CHANGE_ORDER")
    assert isinstance(data.get("purpose"), str)
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("status") in ("RESERVED", "COMMITTED", "DRAWN", "RELEASED")


def assert_owner_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("period"), str)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
    assert isinstance(data.get("eac_commitment_based_cents"), int)
    assert isinstance(data.get("eac_trend_based_cents"), int)
    assert isinstance(data.get("budget_variance_commitment_cents"), int)
    assert isinstance(data.get("budget_variance_trend_cents"), int)
    assert data.get("contingency_posture_snapshot") in ("NORMAL", "WATCH", "CRITICAL")


def assert_stakeholder_group(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("group_name"), str) and data["group_name"]
    assert data.get("group_type") in ("USER_GROUP", "AUTHORITIES", "COMMUNITY", "OPERATIONS")
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]


def assert_engagement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("stakeholder_group_id"), str)
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("scheduled_start"), str)
    assert isinstance(data.get("scheduled_end"), str)
    assert isinstance(data.get("duration_minutes"), int) and data["duration_minutes"] > 0
    assert data.get("status") in ("PROPOSED", "SCHEDULED", "HELD", "CANCELLED")


def assert_occupancy_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("plan_name"), str)
    assert isinstance(data.get("target_move_month"), str)
    assert data.get("status") in ("PLANNING", "COORDINATING", "READY", "EXECUTING", "COMPLETE")


def assert_move_in_wave(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("occupancy_plan_id"), str)
    assert isinstance(data.get("stakeholder_group_id"), str)
    assert isinstance(data.get("wave_name"), str)
    assert data.get("dock_resource") in ("DOCK_A", "DOCK_B", "DOCK_C")
    assert isinstance(data.get("move_start"), str)
    assert isinstance(data.get("move_end"), str)
    assert isinstance(data.get("criticality_weight"), int) and data["criticality_weight"] >= 1
    assert data.get("status") in ("SCHEDULED", "CONFIRMED", "COMPLETE", "CANCELLED")


def assert_closeout_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("program_id"), str)
    assert data.get("item_type") in ("PUNCH_LIST", "WARRANTY", "AS_BUILT", "FINAL_ACCOUNT", "TRAINING")
    assert isinstance(data.get("title"), str)
    assert data.get("status") in ("OPEN", "SUBMITTED", "VERIFIED")


def assert_lesson_entry(data: dict):
    """Append-only (PRD §2.4): only id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "LessonEntry must NOT carry updated_at"
    assert "version" not in data, "LessonEntry must NOT carry version"
    assert isinstance(data.get("program_id"), str)
    assert data.get("category") in ("SCHEDULE", "COST", "SCOPE", "STAKEHOLDER", "SITE", "PROCUREMENT")
    assert isinstance(data.get("lesson_text"), str)
    assert isinstance(data.get("recommendation"), str)


def assert_pool_conservation(program: dict):
    """PRD §2.7 conservation invariant: total == reserved + committed + drawn + available."""
    total = program["contingency_total_cents"]
    s = (program["contingency_reserved_cents"] + program["contingency_committed_cents"]
         + program["contingency_drawn_cents"] + program["contingency_available_cents"])
    assert total == s, (
        f"Pool conservation violated: total={total} but "
        f"reserved+committed+drawn+available={s}"
    )
