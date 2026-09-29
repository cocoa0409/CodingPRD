"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import STATION_KM_MARKS


def assert_common_fields(data: dict, entity_label: str = "resource"):
    """PRD §2.5 full set: id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID with no type prefix"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 UTC instant"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 UTC instant"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1"
    )


def assert_timestamp_has_three_fractional_digits(value: str, label: str):
    """PRD §2.5: timestamps carry three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    assert isinstance(value, str), f"{label} must be a string timestamp"
    assert value.endswith("Z"), f"{label} must be a UTC instant ending in Z, got {value}"
    assert "." in value, f"{label} must carry fractional digits, got {value}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value}"
    )


def assert_race_edition(data: dict):
    assert_common_fields(data, "race_edition")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["race_date"], str) and len(data["race_date"]) == 10
    assert data["status"] in (
        "PLANNING", "FIELD_OPEN", "FIELD_LOCKED", "RACED", "RESULTS_CERTIFIED",
        "PURSE_SETTLED",
    ), f"unexpected edition status {data['status']}"
    for field in (
        "appearance_budget_cents", "appearance_committed_cents",
        "appearance_uncommitted_cents", "total_purse_cents", "purse_allocated_cents",
        "purse_unallocated_cents", "bonus_pool_cap_cents", "bonus_pool_consumed_cents",
        "expired_offer_count", "offer_response_days", "max_negotiation_rounds",
        "masters_min_age",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert_edition_ledger_invariants(data)


def assert_edition_ledger_invariants(edition: dict):
    """The two conserved-pool invariants of PRD §2.9."""
    assert (
        edition["appearance_budget_cents"]
        == edition["appearance_committed_cents"] + edition["appearance_uncommitted_cents"]
    ), (
        "appearance_budget_cents must equal appearance_committed_cents plus "
        f"appearance_uncommitted_cents, got {edition['appearance_budget_cents']} vs "
        f"{edition['appearance_committed_cents']} + "
        f"{edition['appearance_uncommitted_cents']}"
    )
    assert (
        edition["total_purse_cents"]
        == edition["purse_allocated_cents"] + edition["purse_unallocated_cents"]
    ), (
        "total_purse_cents must equal purse_allocated_cents plus "
        f"purse_unallocated_cents, got {edition['total_purse_cents']} vs "
        f"{edition['purse_allocated_cents']} + {edition['purse_unallocated_cents']}"
    )


def assert_purse_line(data: dict):
    assert_common_fields(data, "purse_line")
    assert data["category"] in ("OVERALL", "DIVISION", "MASTERS", "TIME_BONUS",
                               "RECORD_BONUS")
    assert data["gender"] in ("MALE", "FEMALE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    if data["category"] in ("OVERALL", "MASTERS"):
        assert data["division"] is None, "division must be null on OVERALL/MASTERS lines"
    else:
        assert data["division"] in ("ELITE", "SUB_ELITE", "WHEELCHAIR")
    if data["category"] in ("OVERALL", "DIVISION", "MASTERS"):
        assert isinstance(data["place"], int) and 1 <= data["place"] <= 20
        assert data["threshold_seconds"] is None
    else:
        assert data["place"] is None, "place must be null on bonus lines"
    if data["category"] == "TIME_BONUS":
        assert isinstance(data["threshold_seconds"], int)


def assert_division_standard(data: dict):
    assert_common_fields(data, "division_standard")
    assert data["division"] in ("ELITE", "SUB_ELITE", "WHEELCHAIR")
    assert data["gender"] in ("MALE", "FEMALE")
    assert isinstance(data["max_qualifying_seconds"], int)
    assert data["max_qualifying_seconds"] > 0
    assert isinstance(data["window_months"], int) and 1 <= data["window_months"] <= 60
    assert isinstance(data["requires_chip_timing"], bool)
    assert 1 <= data["bib_range_start"] <= 9999
    assert data["bib_range_end"] >= data["bib_range_start"]


def assert_athlete(data: dict):
    assert_common_fields(data, "athlete")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 3
    assert data["gender"] in ("MALE", "FEMALE")
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) == 10
    assert isinstance(data["tax_residency_country"], str)
    assert isinstance(data["w8ben_on_file"], bool)
    assert isinstance(data["treaty_withholding_bps"], int)
    assert 0 <= data["treaty_withholding_bps"] <= 3000
    assert isinstance(data["whereabouts_filed"], bool)
    assert isinstance(data["missed_test_count"], int) and data["missed_test_count"] >= 0


def assert_rep_agent(data: dict):
    assert_common_fields(data, "rep_agent")
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["license_code"], str) and data["license_code"]
    assert isinstance(data["commission_bps"], int) and 0 <= data["commission_bps"] <= 3000
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_performance_record(data: dict):
    assert_common_fields(data, "performance_record")
    assert is_valid_uuid(data["athlete_id"])
    assert isinstance(data["race_name"], str) and data["race_name"]
    assert isinstance(data["performance_date"], str)
    assert isinstance(data["performance_seconds"], int)
    assert data["performance_seconds"] > 0
    assert data["division"] in ("ELITE", "SUB_ELITE", "WHEELCHAIR")
    assert isinstance(data["chip_timed"], bool)
    assert isinstance(data["sanctioning_ref"], str)
    assert data["verification_status"] in ("SUBMITTED", "VERIFIED", "REJECTED")


def assert_invitation(data: dict):
    assert_common_fields(data, "invitation")
    for fk in ("race_edition_id", "athlete_id", "agent_id",
               "qualifying_performance_id"):
        assert is_valid_uuid(data[fk]), f"invitation.{fk} must be a UUID"
    assert data["division"] in ("ELITE", "SUB_ELITE", "WHEELCHAIR")
    assert data["status"] in ("DRAFT", "OFFERED", "COUNTERED", "ACCEPTED", "DECLINED",
                             "WITHDRAWN", "EXPIRED", "BREACHED")
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert isinstance(data["guaranteed_commitment_cents"], int)
    assert isinstance(data["full_exposure_cents"], int)
    if data["status"] != "ACCEPTED":
        assert data["guaranteed_commitment_cents"] == 0, (
            "in every status other than ACCEPTED, guaranteed_commitment_cents "
            "reads as zero"
        )


def assert_negotiation_round(data: dict):
    """PRD §2.5: a round carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "negotiation_round.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "negotiation_round.created_at must be an ISO 8601 UTC instant"
    )
    assert "updated_at" not in data, (
        "a negotiation round has no updated_at field and the key must not appear"
    )
    assert "version" not in data, (
        "a negotiation round has no version field and the key must not appear"
    )
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["side"] in ("COMMITTEE", "AGENT")
    assert isinstance(data["appearance_fee_cents"], int)
    assert data["air_class"] in ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS")
    assert isinstance(data["hotel_nights"], int)
    assert isinstance(data["ground_transport"], bool)


def assert_pacer_assignment(data: dict):
    assert_common_fields(data, "pacer_assignment")
    assert isinstance(data["pacer_license_code"], str) and data["pacer_license_code"]
    assert isinstance(data["pacer_name"], str)
    assert 120 <= data["target_pace_seconds_per_km"] <= 400
    assert float(data["start_km"]) >= 0
    assert float(data["end_km"]) > float(data["start_km"])
    assert data["assistance_rule"] in ("LEAD_ONLY", "FLUIDS_ALLOWED")


def assert_fluid_station_slot(data: dict):
    assert_common_fields(data, "fluid_station_slot")
    assert is_valid_uuid(data["invitation_id"])
    assert float(data["station_km"]) in STATION_KM_MARKS
    assert 1 <= data["table_position"] <= 40
    assert 1 <= data["bottle_count"] <= 3
    assert data["occupied_from"] == data["table_position"], (
        "occupied_from is the first table position"
    )
    assert data["occupied_to"] == data["table_position"] + data["bottle_count"] - 1, (
        "occupied_to is the first position plus the bottle count less one"
    )
    assert data["status"] in ("RESERVED", "RELEASED")


def assert_doping_test(data: dict):
    assert_common_fields(data, "doping_test")
    assert is_valid_uuid(data["athlete_id"])
    assert is_valid_uuid(data["race_edition_id"])
    assert data["test_type"] in ("IN_COMPETITION", "OUT_OF_COMPETITION")
    assert isinstance(data["window_start_at"], str)
    assert isinstance(data["window_end_at"], str)
    assert data["window_start_at"] < data["window_end_at"]
    assert isinstance(data["sample_code"], str) and data["sample_code"]
    assert data["status"] in ("SCHEDULED", "COLLECTED", "CLEARED", "ADVERSE", "MISSED")


def assert_race_result(data: dict):
    assert_common_fields(data, "race_result")
    assert is_valid_uuid(data["race_edition_id"])
    assert is_valid_uuid(data["invitation_id"])
    assert is_valid_uuid(data["athlete_id"])
    assert data["division"] in ("ELITE", "SUB_ELITE", "WHEELCHAIR")
    assert data["gun_seconds"] > 0 and data["net_seconds"] > 0
    assert data["net_seconds"] <= data["gun_seconds"]
    expected_official = (
        data["net_seconds"] if data["division"] == "WHEELCHAIR" else data["gun_seconds"]
    )
    assert data["official_seconds"] == expected_official, (
        "official_seconds is the gun time for ELITE and SUB_ELITE results and the "
        f"net time for WHEELCHAIR results, expected {expected_official}, got "
        f"{data['official_seconds']}"
    )
    assert data["certification_status"] in ("PROVISIONAL", "CERTIFIED", "DISQUALIFIED")
    assert data["record_claim_status"] in ("NONE", "CLAIMED", "SUBMITTED", "RATIFIED",
                                           "REJECTED")
    assert isinstance(data["tie_group_size"], int) and data["tie_group_size"] >= 1
    assert isinstance(data["is_masters"], bool)


def assert_prize_award(data: dict):
    assert_common_fields(data, "prize_award")
    assert is_valid_uuid(data["race_edition_id"])
    assert is_valid_uuid(data["race_result_id"])
    assert is_valid_uuid(data["athlete_id"])
    assert data["category"] in ("OVERALL", "DIVISION", "MASTERS", "TIME_BONUS",
                               "RECORD_BONUS")
    assert isinstance(data["tie_share_count"], int) and data["tie_share_count"] >= 1
    for field in ("gross_amount_cents", "withholding_bps", "withholding_cents",
                  "net_amount_cents"):
        assert isinstance(data[field], int), (
            f"{field} must be integer cents — no decimal money anywhere in the API"
        )
    assert data["withholding_variant"] in ("NONE", "PER_AWARD", "AGGREGATED")
    assert data["net_amount_cents"] == (
        data["gross_amount_cents"] - data["withholding_cents"]
    ), "net_amount_cents is gross_amount_cents less withholding_cents"
    assert data["status"] in ("COMPUTED", "APPROVED", "PAID", "VOID",
                             "CLAWBACK_PENDING")
    if data["category"] in ("TIME_BONUS", "RECORD_BONUS"):
        assert data["place"] is None, "a bonus award carries a null place"
        assert data["tie_share_count"] == 1, "a bonus award carries a tie_share_count of 1"


def assert_purse_ledger(edition: dict, allocated_cents: int, unallocated_cents: int):
    """Convenience checker for the purse pool projections of PRD §2.9."""
    assert edition["purse_allocated_cents"] == allocated_cents, (
        f"expected purse_allocated_cents {allocated_cents}, got "
        f"{edition['purse_allocated_cents']}"
    )
    assert edition["purse_unallocated_cents"] == unallocated_cents, (
        f"expected purse_unallocated_cents {unallocated_cents}, got "
        f"{edition['purse_unallocated_cents']}"
    )
    assert_edition_ledger_invariants(edition)


def assert_appearance_ledger(edition: dict, committed_cents: int,
                             uncommitted_cents: int):
    """Convenience checker for the appearance pool projections of PRD §2.9."""
    assert edition["appearance_committed_cents"] == committed_cents, (
        f"expected appearance_committed_cents {committed_cents}, got "
        f"{edition['appearance_committed_cents']}"
    )
    assert edition["appearance_uncommitted_cents"] == uncommitted_cents, (
        f"expected appearance_uncommitted_cents {uncommitted_cents}, got "
        f"{edition['appearance_uncommitted_cents']}"
    )
    assert_edition_ledger_invariants(edition)
