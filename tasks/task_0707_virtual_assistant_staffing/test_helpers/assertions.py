"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape the PRD promises; the
invariant checkers encode arithmetic relationships that must hold after any
mutation (e.g. a cycle's available/overage hours derive from consumed_hours).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Immutable reference records (id + created_at only) ─────────────────────
def assert_skill_tag(data: dict):
    assert is_valid_uuid(data.get("id", "")), "skill tag id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["is_specialized"], bool)
    # Immutable reference record: no version field.
    assert "version" not in data, "SkillTag must not carry a version field"
    assert "updated_at" not in data, "SkillTag must not carry an updated_at field"


def assert_sla_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "sla policy id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in ("STANDARD", "PRIORITY", "URGENT")
    assert isinstance(data["response_minutes"], int) and data["response_minutes"] >= 1
    assert isinstance(data["resolution_hours"], int) and data["resolution_hours"] >= 1
    assert 0.0 <= data["breach_penalty_pct"] <= 1.0
    assert "version" not in data, "SlaPolicy must not carry a version field"


# ─── Full-lifecycle entities (id + created_at + updated_at + version) ───────
def _assert_full_lifecycle_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1


def assert_client(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert data["status"] in ("PENDING", "SCOPED", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["open_task_count"], int) and data["open_task_count"] >= 0


def assert_virtual_assistant(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["status"] in ("AVAILABLE", "ENGAGED", "BENCHED")
    assert 0.0 <= data["rating"] <= 5.0
    assert data["weekly_capacity_hours"] >= 1.0
    assert isinstance(data["active_engagement_count"], int) and data["active_engagement_count"] >= 0


def assert_engagement(data: dict):
    _assert_full_lifecycle_common(data)
    assert data["status"] in ("PROPOSED", "ONBOARDING", "ACTIVE", "ENDED", "REJECTED")
    assert is_valid_uuid(data.get("client_id", "")), "engagement client_id must be a UUID"


def assert_retainer_cycle(data: dict):
    _assert_full_lifecycle_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert_cycle_invariants(data)


def assert_task(data: dict):
    _assert_full_lifecycle_common(data)
    assert data["status"] in (
        "QUEUED", "ASSIGNED", "IN_PROGRESS", "BLOCKED", "DONE", "CANCELLED")
    assert data["priority"] in ("STANDARD", "PRIORITY", "URGENT")
    assert data["sla_state"] in ("ON_TRACK", "RESPONSE_BREACHED", "RESOLUTION_BREACHED")
    assert is_valid_uuid(data.get("client_id", "")), "task client_id must be a UUID"


def assert_time_entry(data: dict):
    _assert_full_lifecycle_common(data)
    assert data["status"] in ("LOGGED", "APPROVED", "REJECTED")
    assert isinstance(data["raw_minutes"], int) and data["raw_minutes"] >= 1
    # billable_hours is always an exact multiple of 0.25 h.
    assert_quarter_hour_grid(data["billable_hours"])


def assert_addon(data: dict):
    _assert_full_lifecycle_common(data)
    assert data["status"] in ("REQUESTED", "ACTIVE", "REVOKED")
    assert data["surcharge_rate_cents"] >= 0


def assert_escalation(data: dict):
    _assert_full_lifecycle_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "REPLACED")
    assert data["reason"] in ("SLA_BREACH", "QUALITY", "AVAILABILITY", "OTHER")


def assert_invoice(data: dict):
    _assert_full_lifecycle_common(data)
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("ISSUED", "VOID")
    assert_invoice_invariants(data)


# ─── Domain invariant checkers ──────────────────────────────────────────────
def assert_quarter_hour_grid(hours: float):
    """billable_hours and cycle hour figures sit on the 0.25 h grid."""
    quarters = round(hours / 0.25)
    assert abs(quarters * 0.25 - hours) < 1e-9, f"{hours} is not a multiple of 0.25 h"


def assert_cycle_invariants(data: dict):
    """available_hours and overage_hours derive from the bank vs consumed_hours
    (PRD §3.5): available = max(0, bank - consumed); overage = max(0, consumed - bank)."""
    bank = data["granted_hours"] + data["rolled_in_hours"]
    consumed = data["consumed_hours"]
    assert consumed >= 0
    assert abs(data["available_hours"] - max(0.0, bank - consumed)) < 0.01, \
        "available_hours must equal max(0, bank - consumed_hours)"
    assert abs(data["overage_hours"] - max(0.0, consumed - bank)) < 0.01, \
        "overage_hours must equal max(0, consumed_hours - bank)"


def assert_invoice_invariants(data: dict):
    """total_cents = max(0, base + overage + surcharge - sla_credit), in cents (PRD §3.8)."""
    expected_total = max(
        0,
        data["base_charge_cents"] + data["overage_charge_cents"]
        + data["surcharge_cents"] - data["sla_credit_cents"],
    )
    assert data["total_cents"] == expected_total, (
        f"total_cents {data['total_cents']} must equal "
        f"max(0, base+overage+surcharge-credit)={expected_total}"
    )
    for k in ("base_charge_cents", "overage_charge_cents", "surcharge_cents",
              "sla_credit_cents", "total_cents"):
        assert isinstance(data[k], int), f"{k} must be integer cents"
