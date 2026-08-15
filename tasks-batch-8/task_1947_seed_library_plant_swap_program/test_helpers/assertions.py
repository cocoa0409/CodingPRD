"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["site_type"] in ("LIBRARY_BRANCH", "GARDEN")
    assert isinstance(data["region_zone"], str) and data["region_zone"]
    assert isinstance(data["label_stock_count"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("home_site_id", ""))
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    for counter in (
        "active_checkout_count",
        "overdue_checkout_count",
        "terminal_checkout_count",
        "verified_return_count",
        "credits_earned_total",
        "credits_redeemed_total",
        "credits_expired_total",
        "credits_revoked_total",
        "credits_balance",
        "effective_borrow_limit",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert isinstance(data["simple_return_rate"], (int, float))
    assert isinstance(data["decay_weighted_return_score"], (int, float))
    assert data["standing_tier"] in ("PROBATION", "STANDARD", "TRUSTED")


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("APPLIED", "ACTIVE", "INACTIVE")


def assert_seed_variety(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["variety_name"], str) and data["variety_name"]
    assert isinstance(data["species"], str) and data["species"]
    assert data["category"] in ("VEGETABLE", "HERB", "FLOWER", "NATIVE")
    assert isinstance(data["invasive_flag"], bool)
    assert isinstance(data["rarity_flag"], bool)
    assert isinstance(data["approved_zones"], list) and len(data["approved_zones"]) > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_seed_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("variety_id", ""))
    assert is_valid_uuid(data.get("home_site_id", ""))
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["harvest_year"], int)
    assert isinstance(data["seeds_received"], int) and data["seeds_received"] >= 1
    assert isinstance(data["provisional_viability_pct"], (int, float))
    assert data["status"] in (
        "DRAFT",
        "QUARANTINE",
        "ACTIVE",
        "DEPLETED",
        "REJECTED",
        "RETIRED",
    )
    assert data["final_viability_pct"] is None or isinstance(
        data["final_viability_pct"], (int, float)
    )
    for bucket in ("seeds_remaining", "seeds_in_packets", "seeds_discarded"):
        assert isinstance(data[bucket], int), f"{bucket} must be an integer"
    assert isinstance(data["packets_created_total"], int)
    assert isinstance(data["viable_seed_count"], int)


def assert_germination_test(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["seeds_tested"], int) and data["seeds_tested"] >= 1
    assert isinstance(data["sprouted_count"], int) and data["sprouted_count"] >= 0
    assert data["sprouted_count"] <= data["seeds_tested"]
    assert isinstance(data["result_pct"], (int, float))
    assert data["status"] in ("RECORDED", "CERTIFIED", "VOIDED")


def assert_seed_packet(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["packet_code"], str) and data["packet_code"]
    assert isinstance(data["seeds_count"], int) and data["seeds_count"] >= 1
    assert data["status"] in (
        "AVAILABLE",
        "CHECKED_OUT",
        "RETURNED",
        "RECALLED",
        "VOIDED",
        "DISCARDED",
    )


def assert_checkout(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("packet_id", ""))
    assert is_iso8601_timestamp(data.get("checked_out_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data.get("returned_at") is None or is_iso8601_timestamp(data["returned_at"])
    assert isinstance(data["recall_required"], bool)
    assert data["status"] in (
        "ACTIVE",
        "OVERDUE",
        "RETURNED",
        "DISPUTED",
        "VERIFIED",
        "WRITTEN_OFF",
    )


def assert_swap_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in (
        "DRAFT",
        "SCHEDULED",
        "INTAKE_OPEN",
        "INTAKE_CLOSED",
        "COMPLETED",
        "CANCELLED",
    )


def assert_intake_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("variety_id", ""))
    assert data["item_type"] in ("SEED_PACKET", "PLANT_START", "CUTTING")
    assert data["condition"] in ("EXCELLENT", "GOOD", "FAIR")
    assert isinstance(data["credit_value"], int)
    assert data["status"] in (
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED",
        "WITHDRAWN",
        "RETURNED_TO_OWNER",
        "SWAPPED",
    )


def assert_credit_entry(data: dict):
    """Append-only ledger row: id + created_at only — no updated_at/version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ledger rows carry no updated_at"
    assert "version" not in data, "ledger rows carry no version"
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("event_id", ""))
    assert data["entry_type"] in ("EARNED", "REDEEMED", "EXPIRED", "REVOKED")
    assert isinstance(data["credits"], int) and data["credits"] >= 1


def assert_packing_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_packing_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["status"] in ("SIGNUP", "ATTENDED", "NO_SHOW", "CANCELLED")


def assert_seed_count_conservation(lot: dict):
    """PRD §2.10: seeds received always equals loose + in live packets +
    discarded."""
    total = (
        lot["seeds_remaining"] + lot["seeds_in_packets"] + lot["seeds_discarded"]
    )
    assert lot["seeds_received"] == total, (
        f"seed conservation broken: received {lot['seeds_received']} != "
        f"remaining {lot['seeds_remaining']} + in_packets "
        f"{lot['seeds_in_packets']} + discarded {lot['seeds_discarded']}"
    )


def assert_credit_conservation(summary: dict):
    """PRD §2.10: earned always equals redeemed + expired + revoked +
    balance."""
    rhs = (
        summary["credits_redeemed_total"]
        + summary["credits_expired_total"]
        + summary["credits_revoked_total"]
        + summary["credits_balance"]
    )
    assert summary["credits_earned_total"] == rhs, (
        f"credit conservation broken: earned "
        f"{summary['credits_earned_total']} != redeemed "
        f"{summary['credits_redeemed_total']} + expired "
        f"{summary['credits_expired_total']} + revoked "
        f"{summary['credits_revoked_total']} + balance "
        f"{summary['credits_balance']}"
    )
