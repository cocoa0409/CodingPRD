"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_service_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["charity_splits"], list)


def assert_resident(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a UUID"
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["strikes"], int) and data["strikes"] >= 0
    assert isinstance(data["credit_balance_cents"], int)


def assert_bag_kit(data: dict):
    _assert_common_fields(data)
    assert data["kit_type"] in ("BAG", "BIN")
    assert data["status"] in ("REQUESTED", "DISPATCHED", "DELIVERED", "RETIRED")


def assert_pickup_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED", "ROUTED", "COLLECTED", "WEIGHED", "SETTLED", "NO_SHOW", "CANCELLED",
    )
    assert isinstance(data["bags_claimed"], int) and data["bags_claimed"] >= 1
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert isinstance(data["rebook_count"], int) and data["rebook_count"] >= 0
    assert isinstance(data["est_weight_kg"], (int, float))


def assert_partner(data: dict):
    _assert_common_fields(data)
    assert data["partner_type"] in ("BRAND", "THRIFT")
    assert data["status"] in ("ELIGIBLE", "SUSPENDED", "QUARANTINED")
    assert isinstance(data["accepted_grades"], list) and data["accepted_grades"]
    assert isinstance(data["capacity_kg"], int) and data["capacity_kg"] > 0


def assert_routing_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "ACCEPTED", "DECLINED", "COMPLETED")
    assert isinstance(data["assigned_weight_kg"], (int, float))


def assert_dropbox(data: dict):
    _assert_common_fields(data)
    assert data["posture"] in ("OK", "FILLING", "FULL_PENDING_COLLECTION")
    assert isinstance(data["fill_pct"], (int, float))


def assert_fill_reading(data: dict):
    """Append-only event (PRD §2.4): id + created_at only; never updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "fill readings never carry updated_at"
    assert "version" not in data, "fill readings never carry version"
    assert 0 <= data["fill_pct"] <= 100


def assert_weight_ticket(data: dict):
    _assert_common_fields(data)
    assert data["source_type"] in ("PICKUP_REQUEST", "DROPBOX")
    assert data["status"] in ("PROVISIONAL", "CERTIFIED", "QUARANTINED", "VOIDED")
    assert isinstance(data["provisional_weight_kg"], (int, float))
    assert data["highest_upheld_severity"] in ("NONE", "MINOR", "MAJOR", "SEVERE")


def assert_diversion_credit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "DISPUTED", "SETTLED", "VOIDED")
    assert isinstance(data["projected_cents"], int)
    assert data["applied_severity"] in ("NONE", "MINOR", "MAJOR", "SEVERE")
    assert isinstance(data["has_hold"], bool)


def assert_sponsor_fund(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "CLOSED")
    for field in ("initial_cents", "funded_total_cents", "held_cents", "paid_cents", "available_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_charity(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["total_received_cents"], int)


def assert_contamination_report(data: dict):
    _assert_common_fields(data)
    assert data["severity"] in ("MINOR", "MAJOR", "SEVERE")
    assert data["status"] in ("OPEN", "ADJUDICATED", "DISMISSED")


def assert_reporting_period(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_fund_ledger_invariant(fund: dict):
    """PRD §2.8: held + paid + available == funded_total at all times."""
    total = fund["held_cents"] + fund["paid_cents"] + fund["available_cents"]
    assert total == fund["funded_total_cents"], (
        f"fund ledger drift: held {fund['held_cents']} + paid {fund['paid_cents']} "
        f"+ available {fund['available_cents']} != funded_total {fund['funded_total_cents']}"
    )


def assert_partner_capacity_partition(partner: dict):
    """PRD §3.7: remaining_kg == capacity_kg - committed_kg - completed_kg."""
    expected = partner["capacity_kg"] - partner["committed_kg"] - partner["completed_kg"]
    assert abs(partner["remaining_kg"] - expected) < 1e-6, (
        f"capacity partition drift: remaining {partner['remaining_kg']} != {expected}"
    )
