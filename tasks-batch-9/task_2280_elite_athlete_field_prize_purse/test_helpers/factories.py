"""Payload factories — one per entity, input fields only."""
from itertools import count

from .constants import TEST_DEFAULTS

_license_seq = count(1)
_sample_seq = count(1)
_athlete_seq = count(1)


def create_race_edition_payload(**overrides) -> dict:
    payload = {
        "name": "Harbor City Marathon 2026",
        "city": "Harbor City",
        "race_date": TEST_DEFAULTS["RACE_DATE"],
        "appearance_budget_cents": TEST_DEFAULTS["APPEARANCE_BUDGET_CENTS"],
        "total_purse_cents": TEST_DEFAULTS["TOTAL_PURSE_CENTS"],
        "bonus_pool_cap_cents": TEST_DEFAULTS["BONUS_POOL_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_purse_line_payload(race_edition_id, category="OVERALL", gender="MALE",
                              amount_cents=1_000_000, **overrides) -> dict:
    payload = {
        "race_edition_id": race_edition_id,
        "category": category,
        "gender": gender,
        "amount_cents": amount_cents,
    }
    if category in ("OVERALL", "DIVISION", "MASTERS"):
        payload["place"] = 1
    if category in ("DIVISION", "TIME_BONUS", "RECORD_BONUS"):
        payload["division"] = "ELITE"
    if category == "TIME_BONUS":
        payload["threshold_seconds"] = 7_800
    payload.update(overrides)
    return payload


def create_division_standard_payload(race_edition_id, division="ELITE", gender="MALE",
                                     **overrides) -> dict:
    payload = {
        "race_edition_id": race_edition_id,
        "division": division,
        "gender": gender,
        "max_qualifying_seconds": TEST_DEFAULTS["MAX_QUALIFYING_SECONDS"],
        "bib_range_start": TEST_DEFAULTS["BIB_RANGE_START"],
        "bib_range_end": TEST_DEFAULTS["BIB_RANGE_END"],
    }
    payload.update(overrides)
    return payload


def create_athlete_payload(**overrides) -> dict:
    n = next(_athlete_seq)
    payload = {
        "full_name": f"Test Runner {n}",
        "country_code": "KEN",
        "gender": "MALE",
        "birth_date": "1996-03-14",
    }
    payload.update(overrides)
    return payload


def create_rep_agent_payload(**overrides) -> dict:
    payload = {
        "agency_name": "Global Track Management",
        "license_code": f"LIC-{next(_license_seq):04d}",
    }
    payload.update(overrides)
    return payload


def create_performance_record_payload(athlete_id, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "race_name": "Lakeside Marathon",
        "performance_date": "2026-04-12",
        "performance_seconds": 7_900,
        "division": "ELITE",
        "sanctioning_ref": "SANC-REF-1",
        "chip_timed": True,
    }
    payload.update(overrides)
    return payload


def verify_performance_payload(official_seconds, **overrides) -> dict:
    payload = {"decision": "VERIFIED", "official_seconds": official_seconds}
    payload.update(overrides)
    return payload


def reject_performance_payload(rejection_reason, **overrides) -> dict:
    payload = {"decision": "REJECTED", "rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def create_invitation_payload(race_edition_id, athlete_id, agent_id,
                              qualifying_performance_id, division="ELITE",
                              **overrides) -> dict:
    payload = {
        "race_edition_id": race_edition_id,
        "athlete_id": athlete_id,
        "agent_id": agent_id,
        "qualifying_performance_id": qualifying_performance_id,
        "division": division,
    }
    payload.update(overrides)
    return payload


def offer_payload(appearance_fee_cents=500_000, air_class="ECONOMY", hotel_nights=2,
                  ground_transport=False, **overrides) -> dict:
    payload = {
        "appearance_fee_cents": appearance_fee_cents,
        "air_class": air_class,
        "hotel_nights": hotel_nights,
        "ground_transport": ground_transport,
    }
    payload.update(overrides)
    return payload


def negotiation_round_payload(expected_invitation_version, appearance_fee_cents=600_000,
                              air_class="ECONOMY", hotel_nights=2,
                              ground_transport=False, **overrides) -> dict:
    payload = {
        "appearance_fee_cents": appearance_fee_cents,
        "air_class": air_class,
        "hotel_nights": hotel_nights,
        "ground_transport": ground_transport,
        "expected_invitation_version": expected_invitation_version,
    }
    payload.update(overrides)
    return payload


def create_fluid_station_slot_payload(invitation_id, station_km=10.0,
                                      table_position=3, bottle_count=2,
                                      **overrides) -> dict:
    payload = {
        "invitation_id": invitation_id,
        "station_km": station_km,
        "table_position": table_position,
        "bottle_count": bottle_count,
    }
    payload.update(overrides)
    return payload


def create_pacer_assignment_payload(race_edition_id, pacer_license_code="PC-1",
                                    start_km=0.0, end_km=21.0, **overrides) -> dict:
    payload = {
        "race_edition_id": race_edition_id,
        "pacer_license_code": pacer_license_code,
        "pacer_name": "Lead Pacer",
        "target_pace_seconds_per_km": 180,
        "start_km": start_km,
        "end_km": end_km,
    }
    payload.update(overrides)
    return payload


def create_doping_test_payload(athlete_id, race_edition_id,
                               test_type="OUT_OF_COMPETITION",
                               window_start_at="2026-10-10T08:00:00Z",
                               window_end_at="2026-10-10T18:00:00Z",
                               sample_code=None, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "race_edition_id": race_edition_id,
        "test_type": test_type,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "sample_code": sample_code or f"SMPL-{next(_sample_seq):04d}",
    }
    payload.update(overrides)
    return payload


def create_race_result_payload(race_edition_id, invitation_id, gun_seconds=7_500,
                               net_seconds=None, **overrides) -> dict:
    payload = {
        "race_edition_id": race_edition_id,
        "invitation_id": invitation_id,
        "gun_seconds": gun_seconds,
        "net_seconds": net_seconds if net_seconds is not None else gun_seconds,
    }
    payload.update(overrides)
    return payload
