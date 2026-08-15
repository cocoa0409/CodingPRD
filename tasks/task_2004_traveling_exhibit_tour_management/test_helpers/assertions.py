"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_tour(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["exhibit_code"], str) and data["exhibit_code"]
    assert isinstance(data["crate_count"], int) and data["crate_count"] >= 0
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data["refurbishment_gap_days"], int)
    assert data["status"] in ["DRAFT", "BOOKING", "ON_TOUR", "IN_REFURBISHMENT", "RETIRED"]
    for f in ("total_billed_cents", "total_collected_cents", "total_waived_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str)
    assert isinstance(data["climate_controlled"], bool)
    assert isinstance(data["max_gallery_sqm"], int)
    assert isinstance(data["local_sponsorship_cap_cents"], int)


def assert_tour_stop(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["venue_id"], str)
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    for f in ("install_start", "open_date", "close_date", "teardown_end"):
        assert is_iso8601_timestamp(data[f]), f"{f} must be ISO 8601"
    assert isinstance(data["projected_attendance"], int)
    assert data["status"] in [
        "TENTATIVE",
        "CONTRACTED",
        "INSTALLING",
        "OPEN",
        "TEARDOWN",
        "CLOSED",
        "CANCELLED",
    ]
    assert isinstance(data["supervision_required"], bool)


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_stop_id"], str)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["sponsorship_credit_cents"], int)
    assert data["status"] in ["DRAFT", "SENT", "SIGNED", "FINALIZED"]


def assert_crate(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["crate_label"], str) and data["crate_label"]
    assert isinstance(data["contents_value_cents"], int)
    assert data["location_status"] in [
        "AT_ORIGIN",
        "IN_TRANSIT",
        "AT_VENUE",
        "IN_REFURBISHMENT",
    ]


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["destination_stop_id"], str)
    assert is_iso8601_timestamp(data["depart_at"])
    assert is_iso8601_timestamp(data["arrive_at"])
    assert isinstance(data["carrier_name"], str)
    assert data["status"] in [
        "PLANNED",
        "DISPATCHED",
        "IN_TRANSIT",
        "RECEIVED",
        "DAMAGE_HOLD",
        "CLEARED",
    ]


def assert_condition_report(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["crate_id"], str)
    assert isinstance(data["inspector_name"], str)
    assert data["phase"] in ["UNPACK", "PACK"]
    assert 0 <= data["surface_score"] <= 100
    assert 0 <= data["structural_score"] <= 100
    assert isinstance(data["seal_intact"], bool)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "DISPUTED"]


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["condition_report_id"], str)
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["line_items"], list)
    assert data["status"] in ["FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "PAID"]


def assert_marketing_kit(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_stop_id"], str)
    assert isinstance(data["language_count"], int)
    assert isinstance(data["sponsor_logo_slots"], int)
    assert isinstance(data["press_release_sent"], bool)
    assert data["status"] in ["PLANNED", "PRODUCED", "DELIVERED", "RETIRED"]


def assert_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["tour_stop_id"], str)
    assert isinstance(data["insurer_name"], str)
    assert isinstance(data["coverage_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ["ISSUED", "ACTIVE", "EXPIRED", "VOID"]
