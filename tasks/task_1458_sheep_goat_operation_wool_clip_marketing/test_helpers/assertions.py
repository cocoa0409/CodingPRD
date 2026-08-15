"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly (PRD §3 entity narratives and §2.4 common
fields). BirthRecord assertions deliberately require the ABSENCE of
updated_at/version (PRD §2.4: "both updated_at and version are absent").
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"{entity}.updated_at must be an ISO 8601 timestamp"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"{entity}.version must be a positive integer"
        )


def assert_flock(data: dict):
    _assert_common(data, "Flock")
    assert isinstance(data["flock_name"], str) and data["flock_name"]
    assert data["species"] in ("SHEEP", "GOAT")
    assert data["flock_status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["baseline_headcount"], int) and data["baseline_headcount"] >= 1
    assert isinstance(data["guardian_dog_count"], int) and data["guardian_dog_count"] >= 0
    assert isinstance(data["current_headcount"], int)
    assert data.get("withdrawal_until") is None or is_iso8601_timestamp(data["withdrawal_until"])


def assert_breeding_season(data: dict):
    _assert_common(data, "BreedingSeason")
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert isinstance(data["ewes_bred"], int) and data["ewes_bred"] >= 1
    assert data["season_status"] in (
        "PLANNED", "BREEDING", "GESTATION", "LAMBING", "WEANING", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["total_born"], int)
    assert isinstance(data["total_born_alive"], int)


def assert_birth_record(data: dict):
    """PRD §2.4: birth records carry only id and created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "BirthRecord.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "BirthRecord.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "BirthRecord must not carry updated_at"
    assert "version" not in data, "BirthRecord must not carry version"
    assert isinstance(data["births_reported"], int) and data["births_reported"] >= 1
    assert isinstance(data["born_alive"], int) and data["born_alive"] >= 0
    assert isinstance(data["born_dead"], int) and data["born_dead"] >= 0


def assert_pasture(data: dict):
    _assert_common(data, "Pasture")
    assert isinstance(data["pasture_name"], str) and data["pasture_name"]
    assert data["acres"] > 0
    assert isinstance(data["carrying_capacity_head"], int) and data["carrying_capacity_head"] >= 1
    assert isinstance(data["rest_days"], int) and data["rest_days"] >= 0
    assert isinstance(data["occupied_head_count"], int)
    assert data["pasture_status"] in ("OCCUPIED", "RESTING", "AVAILABLE")


def assert_grazing_move(data: dict):
    _assert_common(data, "GrazingMove")
    assert (data.get("pasture_id") is None) != (data.get("contract_id") is None), (
        "exactly one of pasture_id / contract_id must be set"
    )
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert data["move_status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_parasite_treatment(data: dict):
    _assert_common(data, "ParasiteTreatment")
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert isinstance(data["withdrawal_days"], int) and data["withdrawal_days"] >= 0
    assert isinstance(data["fecal_egg_count_before"], int) and data["fecal_egg_count_before"] >= 0
    assert data.get("fecal_egg_count_after") is None or data["fecal_egg_count_after"] >= 0
    assert data.get("efficacy_pct") is None or isinstance(data["efficacy_pct"], (int, float))
    assert isinstance(data["resistance_flag"], bool)


def assert_shearing_crew(data: dict):
    _assert_common(data, "ShearingCrew")
    assert isinstance(data["crew_name"], str) and data["crew_name"]
    assert data["crew_status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["head_per_day_capacity"], int) and data["head_per_day_capacity"] >= 1
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0


def assert_shearing_event(data: dict):
    _assert_common(data, "ShearingEvent")
    assert isinstance(data["expected_head"], int) and data["expected_head"] >= 1
    assert data["shearing_status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data.get("shorn_head_count") is None or data["shorn_head_count"] >= 1


def assert_wool_clip(data: dict):
    _assert_common(data, "WoolClip")
    assert data["greasy_weight_lbs"] > 0
    assert 0 <= data["skirtings_weight_lbs"] < data["greasy_weight_lbs"]
    assert data["marketing_posture"] in ("UNGRADED", "GRADING", "MARKETING", "SETTLED_OUT")
    assert_clip_weight_conservation(data)


def assert_wool_lot(data: dict):
    _assert_common(data, "WoolLot")
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["weight_lbs"] > 0
    assert data["lot_status"] in (
        "DRAFT", "GRADED", "REGRADING", "CONSIGNED", "SOLD", "SETTLED", "WITHDRAWN",
    )


def assert_core_test(data: dict):
    _assert_common(data, "CoreTest")
    assert isinstance(data["lab_ref"], str) and data["lab_ref"]
    assert data["test_status"] in ("SUBMITTED", "RESULTED", "LOCKED", "REJECTED")
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


def assert_consignment(data: dict):
    _assert_common(data, "Consignment")
    assert isinstance(data["pool_ref"], str) and data["pool_ref"]
    assert data["consignment_status"] in (
        "TENDERED", "ACCEPTED", "REJECTED", "ADVANCED", "SOLD", "SETTLED", "WITHDRAWN",
    )
    assert isinstance(data["advance_cents"], int)
    assert isinstance(data["pending_clawback_cents"], int)
    assert isinstance(data["clawback_cents"], int)


def assert_holiday_window(data: dict):
    _assert_common(data, "HolidayWindow")
    assert isinstance(data["holiday_name"], str) and data["holiday_name"]
    assert 0 <= data["premium_pct"] <= 100
    assert isinstance(data["min_head"], int) and data["min_head"] >= 1


def assert_livestock_sale(data: dict):
    _assert_common(data, "LivestockSale")
    assert data["sale_type"] in ("MEAT", "BREEDING")
    assert data["channel"] in ("AUCTION", "DIRECT", "ETHNIC_MARKET")
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["delivery_status"] in ("PENDING", "LOADED", "DELIVERED", "CANCELLED")
    assert isinstance(data["booked_price_cents"], int)


def assert_loss_report(data: dict):
    _assert_common(data, "LossReport")
    assert isinstance(data["head_lost"], int) and data["head_lost"] >= 1
    assert data["predator_type"] in (
        "COYOTE", "MOUNTAIN_LION", "BEAR", "DOG", "EAGLE", "UNKNOWN",
    )
    assert isinstance(data["guardian_on_duty"], bool)
    assert data["report_status"] in ("REPORTED", "UNDER_REVIEW", "VERIFIED", "DISMISSED")


def assert_grazing_contract(data: dict):
    _assert_common(data, "GrazingContract")
    assert isinstance(data["client_org_name"], str) and data["client_org_name"]
    assert data["rate_per_head_day_cents"] > 0
    assert isinstance(data["min_head"], int) and data["min_head"] >= 1
    assert data["max_head"] >= data["min_head"]
    assert 0 <= data["target_cover_reduction_pct"] <= 100
    assert isinstance(data["terms_version"], int) and data["terms_version"] >= 1
    assert data["contract_status"] in (
        "DRAFT", "PROPOSED", "COUNTERED", "ACCEPTED", "ACTIVE", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["breach_flag"], bool)


def assert_pool_statement(data: dict):
    assert isinstance(data["pool_ref"], str) and data["pool_ref"]
    assert isinstance(data["consignment_count"], int) and data["consignment_count"] >= 0
    for field in (
        "total_sale_gross_cents",
        "total_pool_fee_cents",
        "total_advance_cents",
        "total_settlement_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_clip_weight_conservation(clip: dict):
    """PRD §3.3 weight-conservation invariant:
    unallocated = greasy - skirtings - allocated."""
    expected = clip["greasy_weight_lbs"] - clip["skirtings_weight_lbs"] - clip["allocated_weight_lbs"]
    assert clip["unallocated_weight_lbs"] == round(expected, 2), (
        f"weight conservation violated: unallocated {clip['unallocated_weight_lbs']} "
        f"!= greasy {clip['greasy_weight_lbs']} - skirtings {clip['skirtings_weight_lbs']} "
        f"- allocated {clip['allocated_weight_lbs']}"
    )
