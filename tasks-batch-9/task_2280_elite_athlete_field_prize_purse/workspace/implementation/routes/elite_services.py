"""Elite services: fluid-station reservations and pacing arrangements (PRD 3.5)."""
from flask import Blueprint

from constants import (
    ALLOWED_STATION_KM,
    ASSISTANCE_RULES,
    MAX_PACING_KM,
    MAX_TABLE_POSITION,
)
from db import db, new_record
from errors import err, invalid
from middleware import authenticate
from response import object_response
from services import gates, lookup, serializers
from validators import get_body, oenum, rint, rnum, rstr

bp = Blueprint("elite_services", __name__)


def _station_mark(value):
    for mark in ALLOWED_STATION_KM:
        if abs(value - mark) < 1e-9:
            return mark
    raise invalid(
        "station_km must be one of %s"
        % ", ".join("%.1f" % mark for mark in ALLOWED_STATION_KM)
    )


@bp.post("/fluid-station-slots")
def create_slot():
    authenticate(("ElitesDirector",))
    body = get_body()
    invitation_id = rstr(body, "invitation_id")
    invitation = lookup.get_invitation(invitation_id)

    station_km = _station_mark(rnum(body, "station_km"))
    table_position = rint(body, "table_position", minimum=1, maximum=MAX_TABLE_POSITION)
    bottle_count = rint(body, "bottle_count", minimum=1, maximum=3)
    occupied_from = table_position
    occupied_to = table_position + bottle_count - 1
    if occupied_to > MAX_TABLE_POSITION:
        raise invalid(
            "table_position plus bottle_count minus one must not exceed %d"
            % MAX_TABLE_POSITION
        )

    edition = lookup.soft_get("race_editions", invitation["race_edition_id"])
    gates.gate_edition(edition, ("FIELD_OPEN", "FIELD_LOCKED"))

    for peer in lookup.rows("fluid_station_slots", status="RESERVED"):
        if abs(peer["station_km"] - station_km) >= 1e-9:
            continue
        owner = lookup.soft_get("invitations", peer["invitation_id"])
        if owner is None or owner["race_edition_id"] != invitation["race_edition_id"]:
            continue
        peer_from = peer["table_position"]
        peer_to = peer["table_position"] + peer["bottle_count"] - 1
        # At least one free position must separate the two reservations.
        separated = occupied_from > peer_to + 1 or peer_from > occupied_to + 1
        if not separated:
            raise err(
                "ERR_FLUID_SLOT_CONFLICT",
                "The requested table positions do not leave a free position",
            )

    slot = new_record(
        invitation_id=invitation_id,
        station_km=station_km,
        table_position=table_position,
        bottle_count=bottle_count,
        status="RESERVED",
    )
    db.fluid_station_slots[slot["id"]] = slot
    return object_response(serializers.ser_slot(slot), 201)


@bp.post("/pacer-assignments")
def create_pacer_assignment():
    authenticate(("ElitesDirector",))
    body = get_body()
    edition_id = rstr(body, "race_edition_id")
    edition = lookup.get_edition(edition_id)

    pacer_license_code = rstr(body, "pacer_license_code")
    pacer_name = rstr(body, "pacer_name")
    target_pace = rint(body, "target_pace_seconds_per_km", minimum=120, maximum=400)
    start_km = rnum(body, "start_km", minimum=0)
    end_km = rnum(body, "end_km")
    if end_km <= start_km:
        raise invalid("end_km must be strictly greater than start_km")
    assistance_rule = oenum(body, "assistance_rule", ASSISTANCE_RULES, "LEAD_ONLY")

    gates.gate_edition(edition, ("FIELD_OPEN", "FIELD_LOCKED"))

    if end_km > MAX_PACING_KM + 1e-9:
        raise err(
            "ERR_PACING_BEYOND_LIMIT",
            "Pacing on this course stops at %.1f kilometres" % MAX_PACING_KM,
        )

    for peer in lookup.rows(
        "pacer_assignments",
        race_edition_id=edition_id,
        pacer_license_code=pacer_license_code,
    ):
        if start_km < peer["end_km"] - 1e-9 and peer["start_km"] < end_km - 1e-9:
            raise err(
                "ERR_PACING_RANGE_CONFLICT",
                "The pacer already holds an overlapping range in this edition",
            )

    pacer = new_record(
        race_edition_id=edition_id,
        pacer_license_code=pacer_license_code,
        pacer_name=pacer_name,
        target_pace_seconds_per_km=target_pace,
        start_km=start_km,
        end_km=end_km,
        assistance_rule=assistance_rule,
    )
    db.pacer_assignments[pacer["id"]] = pacer
    return object_response(serializers.ser_pacer(pacer), 201)
