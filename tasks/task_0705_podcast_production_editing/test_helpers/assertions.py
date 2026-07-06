"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every primary resource carries id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_show(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["format"] in ("INTERVIEW", "SOLO", "PANEL", "NARRATIVE")
    assert data["billing_model"] in ("PER_EPISODE", "RETAINER")
    assert data["production_posture"] in ("ACTIVE", "ON_HOLD", "SUSPENDED")
    assert isinstance(data["lifetime_billed_cents"], int)
    assert isinstance(data["open_episode_count"], int)
    assert isinstance(data["target_loudness_lufs"], (int, float))


def assert_contract(data: dict):
    _assert_common(data)
    assert data["tier"] in ("STANDARD", "PRIORITY", "RUSH")
    assert data["engagement_type"] in ("PER_EPISODE", "RETAINER")
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
    assert isinstance(data["show_id"], str)


def assert_retainer_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["included_consumed"], int)
    assert isinstance(data["overage_episode_count"], int)
    assert isinstance(data["contract_id"], str)


def assert_episode(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["contract_id"], str)
    assert data["status"] in (
        "INTAKE", "RECORDING", "EDITING", "REVIEW",
        "MASTERED", "SCHEDULED", "PUBLISHED", "ARCHIVED", "CANCELLED",
    )
    assert isinstance(data["planned_track_count"], int)
    assert isinstance(data["revision_count"], int)


def assert_session(data: dict):
    _assert_common(data)
    assert isinstance(data["episode_id"], str)
    assert isinstance(data["engineer_id"], str)
    assert data["capture_mode"] in ("STUDIO", "REMOTE")
    assert data["status"] in ("BOOKED", "LIVE", "COMPLETED", "CANCELLED")


def assert_engineer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["remote_buffer_minutes"], int)
    assert isinstance(data["active"], bool)


def assert_deliverable(data: dict):
    _assert_common(data)
    assert data["kind"] in ("MASTER_AUDIO", "SHOW_NOTES", "TRANSCRIPT")
    assert data["status"] in ("PENDING", "READY", "DELIVERED")
    assert isinstance(data["current_version_no"], int)


def assert_asset_version(data: dict):
    _assert_common(data)
    assert isinstance(data["deliverable_id"], str)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["version_no"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert data["kind"] in ("PER_EPISODE", "RETAINER_OVERAGE")
    assert data["status"] in ("ISSUED", "PAID", "OVERDUE", "DISPUTED", "VOID")
    for f in ("subtotal_cents", "discount_cents", "late_fee_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_ad_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert data["status"] in ("DRAFT", "APPROVED", "RECONCILED", "CANCELLED")
    assert isinstance(data["show_payout_cents"], int)
    assert isinstance(data["platform_take_cents"], int)


def assert_ad_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["episode_id"], str)
    assert data["placement"] in ("PRE_ROLL", "MID_ROLL", "POST_ROLL")
    assert isinstance(data["gross_cents"], int)


def assert_invoice_total_consistent(data: dict):
    """total_cents == subtotal_cents - discount_cents + late_fee_cents (PRD §3.5)."""
    expected = data["subtotal_cents"] - data["discount_cents"] + data["late_fee_cents"]
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"- discount {data['discount_cents']} + late_fee {data['late_fee_cents']}"
    )


def assert_revenue_split_conserves_gross(data: dict, gross_total: int):
    """show_payout_cents + platform_take_cents == gross total (PRD §3.10)."""
    total = data["show_payout_cents"] + data["platform_take_cents"]
    assert total == gross_total, (
        f"split sum {total} != gross_total {gross_total} "
        f"(payout {data['show_payout_cents']} + take {data['platform_take_cents']})"
    )
