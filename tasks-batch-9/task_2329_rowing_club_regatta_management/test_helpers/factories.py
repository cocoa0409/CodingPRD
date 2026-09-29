"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import (
    CURRENT_SWIM_TEST,
    FAR_FUTURE_CERT,
    REGATTA_ENTRY_DEADLINE,
    REGATTA_RACE_DATE,
    REGATTA_SCRATCH_DEADLINE,
    REGATTA_WEIGH_IN_CLOSES,
    REGATTA_WEIGH_IN_OPENS,
)


def create_member_payload(**overrides) -> dict:
    """Enrolment payload: full_name, tier and body_weight_kg are required."""
    payload = {
        "full_name": "Rita Rower",
        "tier": "RECREATIONAL",
        "body_weight_kg": 70.0,
    }
    payload.update(overrides)
    return payload


def athlete_payload(full_name="Row One", tier="COMPETITIVE", body_weight_kg=82.0, **overrides) -> dict:
    payload = create_member_payload(
        full_name=full_name,
        tier=tier,
        body_weight_kg=body_weight_kg,
        club_roles=["ATHLETE"],
        swim_test_passed_on=CURRENT_SWIM_TEST,
    )
    payload.update(overrides)
    return payload


def coach_payload(full_name="Cora Coach", **overrides) -> dict:
    payload = create_member_payload(
        full_name=full_name,
        tier="COMPETITIVE",
        body_weight_kg=78.0,
        club_roles=["COACH"],
        swim_test_passed_on=CURRENT_SWIM_TEST,
        coach_cert_expires_at=FAR_FUTURE_CERT,
    )
    payload.update(overrides)
    return payload


def coxswain_payload(full_name="Kip Cox", body_weight_kg=52.0, **overrides) -> dict:
    payload = create_member_payload(
        full_name=full_name,
        tier="COMPETITIVE",
        body_weight_kg=body_weight_kg,
        club_roles=["COXSWAIN"],
        swim_test_passed_on=CURRENT_SWIM_TEST,
        coxswain_cert_expires_at=FAR_FUTURE_CERT,
    )
    payload.update(overrides)
    return payload


def launch_driver_payload(full_name="Dave Driver", launch_supervision_limit=2, **overrides) -> dict:
    payload = create_member_payload(
        full_name=full_name,
        tier="RECREATIONAL",
        body_weight_kg=88.0,
        club_roles=["LAUNCH_DRIVER"],
        swim_test_passed_on=CURRENT_SWIM_TEST,
        safety_launch_cert_expires_at=FAR_FUTURE_CERT,
        launch_supervision_limit=launch_supervision_limit,
    )
    payload.update(overrides)
    return payload


def officer_payload(full_name="Sam Officer", **overrides) -> dict:
    """A plain member who acts in an officiating capacity (no credentials needed)."""
    payload = create_member_payload(
        full_name=full_name,
        tier="COMPETITIVE",
        body_weight_kg=80.0,
        club_roles=[],
        swim_test_passed_on=CURRENT_SWIM_TEST,
    )
    payload.update(overrides)
    return payload


def equipment_manager_payload(full_name="Enid Boatman", **overrides) -> dict:
    payload = create_member_payload(
        full_name=full_name,
        tier="RECREATIONAL",
        body_weight_kg=75.0,
        club_roles=["EQUIPMENT_MANAGER"],
    )
    payload.update(overrides)
    return payload


def jury_chair_payload(full_name="Jude Jury", **overrides) -> dict:
    payload = create_member_payload(
        full_name=full_name,
        tier="RECREATIONAL",
        body_weight_kg=72.0,
        club_roles=["JURY"],
    )
    payload.update(overrides)
    return payload


def create_dues_invoice_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "season_year": 2026,
        "billable_months": 12,
        "due_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_shell_payload(**overrides) -> dict:
    payload = {
        "hull_name": "Kingfisher",
        "boat_class": "1X",
        "hull_weight_kg": 14.0,
        "home_bay": "BAY-1",
    }
    payload.update(overrides)
    return payload


def create_damage_report_payload(shell_id, reported_by_member_id, **overrides) -> dict:
    payload = {
        "shell_id": shell_id,
        "reported_by_member_id": reported_by_member_id,
        "severity": "MAJOR",
        "narrative": "cracked rib at seat 1",
    }
    payload.update(overrides)
    return payload


def create_reading_payload(**overrides) -> dict:
    """An OPEN-posture observation unless overridden."""
    payload = {
        "observed_at": "2026-08-01T05:00:00Z",
        "air_temp_c": 20.0,
        "water_temp_c": 18.0,
        "wind_speed_kt": 5.0,
        "visibility_m": 3000,
        "traffic_pattern": "STANDARD_COUNTERCLOCKWISE",
    }
    payload.update(overrides)
    return payload


def create_water_session_payload(shell_id, **overrides) -> dict:
    payload = {
        "shell_id": shell_id,
        "session_kind": "PRACTICE",
        "planned_start_at": "2026-08-01T06:00:00Z",
        "planned_end_at": "2026-08-01T07:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_regatta_payload(**overrides) -> dict:
    payload = {
        "name": "Club Championship",
        "host_club": "Boathouse RC",
        "venue_kind": "HOME",
        "race_date_at": REGATTA_RACE_DATE,
        "entry_deadline_at": REGATTA_ENTRY_DEADLINE,
        "scratch_deadline_at": REGATTA_SCRATCH_DEADLINE,
        "weigh_in_opens_at": REGATTA_WEIGH_IN_OPENS,
        "weigh_in_closes_at": REGATTA_WEIGH_IN_CLOSES,
    }
    payload.update(overrides)
    return payload


def create_regatta_entry_payload(regatta_id, shell_id, **overrides) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "shell_id": shell_id,
        "event_code": "M1X_OPEN",
        "boat_class": "1X",
        "seed_time_seconds": 380.0,
    }
    payload.update(overrides)
    return payload


def seat(member_id, seat_number, seat_role="ROWER") -> dict:
    return {"member_id": member_id, "seat_number": seat_number, "seat_role": seat_role}


def lineup_payload(expected_version, seats, **overrides) -> dict:
    payload = {"expected_regatta_entry_version": expected_version, "seats": seats}
    payload.update(overrides)
    return payload


def coxed_four_seats(cox_id, rower_ids) -> list:
    """Five seats: the coxswain at seat 0 plus four rowers at seats 1-4."""
    seats = [seat(cox_id, 0, "COXSWAIN")]
    for index, member_id in enumerate(rower_ids, start=1):
        seats.append(seat(member_id, index, "ROWER"))
    return seats


def create_heat_payload(regatta_id, **overrides) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "event_code": "M1X_OPEN",
        "round_kind": "FINAL",
        "scheduled_start_at": "2026-08-12T09:00:00Z",
        "lane_count": 4,
        "advance_count": 0,
    }
    payload.update(overrides)
    return payload


def lane_results_payload(pairs) -> dict:
    """pairs is an iterable of (race_lane_id, elapsed_seconds)."""
    return {
        "lane_results": [
            {"race_lane_id": lane_id, "elapsed_seconds": elapsed}
            for lane_id, elapsed in pairs
        ]
    }


def create_protest_payload(heat_id, filed_by_member_id, against_race_lane_id, **overrides) -> dict:
    payload = {
        "heat_id": heat_id,
        "filed_by_member_id": filed_by_member_id,
        "against_race_lane_id": against_race_lane_id,
        "ground_code": "INTERFERENCE",
        "narrative": "the crew alongside crossed into our water at the 500",
    }
    payload.update(overrides)
    return payload


def create_trailer_load_payload(regatta_id, driver_member_id, **overrides) -> dict:
    payload = {
        "regatta_id": regatta_id,
        "driver_member_id": driver_member_id,
        "tow_vehicle_code": "TOW-1",
        "depart_at": "2026-08-11T05:00:00Z",
        "return_at": "2026-08-12T20:00:00Z",
    }
    payload.update(overrides)
    return payload
