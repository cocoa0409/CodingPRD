"""Animal incidents: reporting, investigation, disclosure and close-out."""
from datetime import timedelta

from db import base_row, format_instant, parse_iso, sorted_rows, store, touch
from middleware import (ALL_ROLES, ROLE_ACCEPTANCE_AGENT, ROLE_COMPLIANCE_OFFICER,
                        register, resolve_fk)
from response import created_response, object_response
from services import calc, domain, serialize
from routes.helpers import INCIDENT_TYPES, VETERINARY_FINDINGS, listing

REPORTERS = [ROLE_ACCEPTANCE_AGENT, ROLE_COMPLIANCE_OFFICER]
COMPLIANCE = [ROLE_COMPLIANCE_OFFICER]

INCIDENT_SCHEMA = {
    "animal_record_id": {"type": "string", "required": True},
    "segment_assignment_id": {"type": "string", "nullable": True},
    "incident_type": {"type": "enum", "required": True, "values": INCIDENT_TYPES},
    "discovered_at_utc": {"type": "datetime", "required": True},
}

DISCLOSE_SCHEMA = {"regulator_reference": {"type": "string", "nullable": True}}

CLOSE_SCHEMA = {"veterinary_finding": {"type": "enum", "required": True,
                                       "values": VETERINARY_FINDINGS}}


def _itinerary_is_international(animal):
    for segment in domain.segments_of_animal(animal):
        if segment["status"] == "RELEASED":
            continue
        leg = domain.leg_of_segment(segment)
        origin = store.stations[leg["origin_station_id"]]
        destination = store.stations[leg["destination_station_id"]]
        if origin["country_code"] != destination["country_code"]:
            return True
    return False


def _raw_severity(incident):
    segment = None
    if incident["segment_assignment_id"] is not None:
        segment = store.segments.get(incident["segment_assignment_id"])
    required = segment["required_welfare_check_count"] if segment else 0
    completed = segment["completed_welfare_check_count"] if segment else 0
    return calc.raw_severity(incident["incident_type"],
                             incident["segment_assignment_id"] is not None,
                             required, completed)


def init(app):
    @register(app, "/animal-incidents", "POST", REPORTERS, schema=INCIDENT_SCHEMA)
    def report_incident(ctx):
        body = ctx.body
        animal = resolve_fk("animal", body["animal_record_id"])
        segment = None
        if body.get("segment_assignment_id") is not None:
            segment = resolve_fk("segment", body["segment_assignment_id"])
            domain.require(segment["animal_record_id"] == animal["id"],
                           "ERR_SEGMENT_ANIMAL_MISMATCH",
                           "the routing slot belongs to another animal")
        incident_type = body["incident_type"]
        raw = calc.raw_severity(
            incident_type, segment is not None,
            segment["required_welfare_check_count"] if segment else 0,
            segment["completed_welfare_check_count"] if segment else 0)
        preliminary = calc.preliminary_severity(raw)
        required = (incident_type in ("LOSS", "DEATH")
                    or preliminary >= calc.DISCLOSURE_SCORE_THRESHOLD)
        deadline = None
        if required:
            hours = calc.DISCLOSURE_BASE_HOURS[incident_type]
            if _itinerary_is_international(animal):
                hours = hours // 2
            deadline = format_instant(parse_iso(body["discovered_at_utc"])
                                      + timedelta(hours=hours))
        row = base_row()
        row.update({
            "animal_record_id": animal["id"],
            "segment_assignment_id": segment["id"] if segment else None,
            "incident_type": incident_type,
            "discovered_at_utc": body["discovered_at_utc"],
            "veterinary_finding": None,
            "reported_by_user_id": ctx.user_id,
            "investigated_by_user_id": None,
            "closed_by_user_id": None,
            "preliminary_severity_score": preliminary,
            "adjudicated_severity_score": None,
            "disclosure_required": required,
            "disclosure_deadline_utc": deadline,
            "disclosed_at_utc": None,
            "disclosure_on_time": None,
            "status": "REPORTED",
        })
        store.incidents[row["id"]] = row
        if incident_type in ("DEATH", "LOSS"):
            terminal = "DECEASED" if incident_type == "DEATH" else "DENIED"
            reservation, was_in_transit = domain.cascade_animal_removal(animal, terminal)
            if incident_type == "DEATH" or was_in_transit:
                if reservation["booking_status"] != "INTERRUPTED":
                    reservation["booking_status"] = "INTERRUPTED"
                    touch(reservation)
            before = reservation["animal_count"]
            domain.recompute_animal_count(reservation)
            if reservation["animal_count"] != before:
                touch(reservation)
            domain.run_charge_assembly(reservation)
        return created_response(serialize.dump("incident", row))

    @register(app, "/animal-incidents/<rid>", "GET", ALL_ROLES, path_entity="incident")
    def get_incident(ctx):
        return object_response(serialize.dump("incident", ctx.row))

    @register(app, "/animal-incidents", "GET", ALL_ROLES, paginated=True)
    def list_incidents(ctx):
        return listing("incident", sorted_rows(store.incidents), ctx,
                       [("animal_record_id", "animal_record_id", "str"),
                        ("segment_assignment_id", "segment_assignment_id", "str"),
                        ("status", "status", "str")])

    @register(app, "/animal-incidents/<rid>/investigate", "POST", COMPLIANCE, schema={},
              path_entity="incident")
    def investigate_incident(ctx):
        incident = ctx.row
        domain.require(ctx.user_id != incident["reported_by_user_id"],
                       "ERR_SEGREGATION_OF_DUTIES",
                       "the reporter may not investigate the incident")
        domain.require(incident["status"] == "REPORTED", "ERR_INCIDENT_INVALID_STATE",
                       "a %s incident cannot be investigated" % incident["status"])
        incident["status"] = "INVESTIGATING"
        incident["investigated_by_user_id"] = ctx.user_id
        touch(incident)
        return object_response(serialize.dump("incident", incident))

    @register(app, "/animal-incidents/<rid>/disclose", "POST", COMPLIANCE,
              schema=DISCLOSE_SCHEMA, path_entity="incident")
    def disclose_incident(ctx):
        incident = ctx.row
        domain.require(incident["status"] == "INVESTIGATING",
                       "ERR_INCIDENT_INVALID_STATE",
                       "a %s incident cannot be disclosed" % incident["status"])
        domain.require(incident["disclosure_required"] is True,
                       "ERR_DISCLOSURE_NOT_REQUIRED",
                       "this incident does not require regulatory disclosure")
        incident["status"] = "REGULATOR_DISCLOSED"
        incident["disclosed_at_utc"] = domain.clock_iso()
        deadline = incident["disclosure_deadline_utc"]
        incident["disclosure_on_time"] = bool(
            deadline is None or store.clock <= parse_iso(deadline))
        touch(incident)
        return object_response(serialize.dump("incident", incident))

    @register(app, "/animal-incidents/<rid>/close", "POST", COMPLIANCE,
              schema=CLOSE_SCHEMA, path_entity="incident")
    def close_incident(ctx):
        incident = ctx.row
        domain.require(ctx.user_id != incident["investigated_by_user_id"],
                       "ERR_SEGREGATION_OF_DUTIES",
                       "the investigator may not close the incident")
        domain.require(incident["status"] in ("INVESTIGATING", "REGULATOR_DISCLOSED"),
                       "ERR_INCIDENT_INVALID_STATE",
                       "a %s incident cannot be closed" % incident["status"])
        if incident["status"] == "INVESTIGATING":
            domain.require(incident["disclosure_required"] is not True,
                           "ERR_DISCLOSURE_PENDING",
                           "the regulatory disclosure has not been filed")
        finding = ctx.body["veterinary_finding"]
        incident["veterinary_finding"] = finding
        incident["adjudicated_severity_score"] = calc.adjudicated_severity(
            _raw_severity(incident), finding, incident["disclosure_required"],
            incident["disclosure_on_time"])
        incident["closed_by_user_id"] = ctx.user_id
        incident["status"] = "CLOSED"
        touch(incident)
        return object_response(serialize.dump("incident", incident))
