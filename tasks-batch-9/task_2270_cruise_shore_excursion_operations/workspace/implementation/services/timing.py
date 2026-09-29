"""Timing-risk projections (PRD 3.4)."""

from datetime import timedelta

from db import db
from util import minutes_between, round_half_up

TRANSFER_BUFFER_MINUTES = 30          # 15 minutes at each end
UNASSIGNED_WAVE_PENALTY_MINUTES = 20
BAND_RED_AT_OR_BELOW = 0
BAND_AMBER_AT_OR_BELOW = 45


def egress_minutes(port, departure):
    if port["docking_mode"] == "ALONGSIDE":
        return 0
    minutes = port["tender_egress_minutes"]
    if not departure.get("tender_wave_id"):
        minutes += UNASSIGNED_WAVE_PENALTY_MINUTES
    return minutes


def ashore_leg_minutes(excursion, port, departure):
    return excursion["duration_minutes"] + TRANSFER_BUFFER_MINUTES + egress_minutes(port, departure)


def band_for(slack_minutes):
    if slack_minutes <= BAND_RED_AT_OR_BELOW:
        return "RED"
    if slack_minutes <= BAND_AMBER_AT_OR_BELOW:
        return "AMBER"
    return "GREEN"


def recompute_projections(departure):
    """Recompute both projections, both slack figures and both bands in place."""
    call = db.port_calls.get(departure["port_call_id"])
    excursion = db.excursions.get(departure["excursion_id"])
    if call is None or excursion is None:
        return departure
    port = db.ports.get(call["port_id"])
    if port is None:
        return departure

    leg = ashore_leg_minutes(excursion, port, departure)
    meeting = departure["meeting_time_utc"]
    delay = call.get("delay_minutes", 0)

    scheduled_start = meeting
    projected_scheduled = scheduled_start + timedelta(minutes=leg)

    wave = db.tender_waves.get(departure.get("tender_wave_id")) if departure.get("tender_wave_id") else None
    if wave is not None:
        wave_landing = wave["window_end_utc"] + timedelta(minutes=delay)
        actual_start = wave_landing if wave_landing > meeting else meeting
    else:
        actual_start = meeting + timedelta(minutes=delay)
    projected_actual = actual_start + timedelta(minutes=leg)

    buffer_minutes = port["risk_buffer_minutes"]
    slack_scheduled = round_half_up(minutes_between(projected_scheduled, call["all_aboard_utc"])) - buffer_minutes
    slack_actual = round_half_up(minutes_between(projected_actual, call["all_aboard_utc"])) - buffer_minutes

    departure["projected_return_scheduled_utc"] = projected_scheduled
    departure["projected_return_actual_utc"] = projected_actual
    departure["slack_minutes_scheduled"] = slack_scheduled
    departure["slack_minutes_actual"] = slack_actual
    departure["timing_risk_band_scheduled"] = band_for(slack_scheduled)
    departure["timing_risk_band_actual"] = band_for(slack_actual)
    return departure
