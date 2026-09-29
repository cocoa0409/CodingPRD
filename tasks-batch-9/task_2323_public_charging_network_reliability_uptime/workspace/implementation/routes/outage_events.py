"""Remote monitoring, fault classification, exclusion adjudication and
post-repair review (PRD §3.4)."""
from flask import Blueprint

import cascades
import clock
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, current_user_id, require_role_for_leg
from response import object_response

bp = Blueprint("outage_events", __name__)

FAULT_CLASSES = ("CRITICAL", "MAJOR", "MINOR", "INFORMATIONAL")
EXCLUDED_CAUSES = ("NONE", "UTILITY_OUTAGE", "NATURAL_DISASTER", "VANDALISM",
                   "HOST_SITE_CLOSURE", "EVSE_MANUFACTURER_RECALL")
EXCLUSION_ACTIONS = ("REQUEST", "APPROVE", "REJECT", "REVOKE")
REVIEW_OUTCOMES = ("VERIFY", "REOPEN")
OUT_OF_SERVICE_CLASSES = ("CRITICAL", "MAJOR")


@bp.post("/outage-events")
@endpoint("NetworkOperator")
def ingest_outage():
    body = validation.json_body()
    port_id = validation.as_string(body, "port_id")
    port = lookup.port(port_id)

    fault_code = validation.as_string(body, "fault_code")
    fault_class = validation.as_enum(body, "fault_class", FAULT_CLASSES)
    detected_at = validation.as_datetime(body, "detected_at")
    excluded_cause_claim = validation.as_enum(body, "excluded_cause_claim", EXCLUDED_CAUSES,
                                              required=False, default="NONE")

    if detected_at > clock.now():
        raise err("ERR_DETECTED_AT_IN_FUTURE",
                  "detected_at may not be later than the current logical clock reading.")
    if detected_at < port["created_at"]:
        raise err("ERR_DETECTED_AT_BEFORE_PORT",
                  "detected_at may not be earlier than the dispenser's created_at.")

    row = db.base_record()
    row.update({
        "port_id": port["id"],
        "fault_code": fault_code,
        "fault_class": fault_class,
        "detected_at": detected_at,
        "cleared_at": None,
        "excluded_cause_claim": excluded_cause_claim,
        "state": "DETECTED",
        "pre_exclusion_state": None,
        "excluded_at": None,
        "dispatch_created_by_user_id": None,
        "is_system_generated": False,
    })
    db.outages[row["id"]] = row
    db.mark_fresh(row)

    if fault_class in OUT_OF_SERVICE_CLASSES:
        cascades.port_out_of_service(port)

    return object_response(serialize.outage_event(row), 201)


@bp.get("/outage-events/<outage_event_id>")
@endpoint()
def get_outage(outage_event_id):
    return object_response(serialize.outage_event(lookup.outage(outage_event_id)))


@bp.post("/outage-events/<outage_event_id>/classify")
@endpoint("NetworkOperator")
def classify_outage(outage_event_id):
    outage = lookup.outage(outage_event_id)
    body = validation.json_body()
    fault_class = validation.as_enum(body, "fault_class", FAULT_CLASSES)
    excluded_cause_claim = validation.as_enum(body, "excluded_cause_claim", EXCLUDED_CAUSES,
                                              required=False)

    if outage["state"] != "DETECTED":
        raise err("ERR_INVALID_STATE", "Only a DETECTED outage may be classified.")

    port = db.ports.get(outage["port_id"])
    if port["service_state"] == "RETIRED":
        raise err("ERR_PORT_RETIRED", "The dispenser is retired.")

    outage["fault_class"] = fault_class
    if excluded_cause_claim is not None:
        outage["excluded_cause_claim"] = excluded_cause_claim
    outage["state"] = "CLASSIFIED"
    db.touch(outage)

    if fault_class in OUT_OF_SERVICE_CLASSES:
        cascades.port_out_of_service(port)

    return object_response(serialize.outage_event(outage))


@bp.post("/outage-events/<outage_event_id>/exclusion-actions")
@endpoint("NetworkOperator", "ComplianceAuditor")
def exclusion_action(outage_event_id):
    outage = lookup.outage(outage_event_id)
    body = validation.json_body()
    action = validation.as_enum(body, "action", EXCLUSION_ACTIONS)
    claimed_cause = validation.as_enum(body, "excluded_cause_claim", EXCLUDED_CAUSES,
                                       required=False)

    require_role_for_leg("NetworkOperator" if action == "REQUEST" else "ComplianceAuditor")

    port = db.ports.get(outage["port_id"])
    station = db.stations.get(port["station_id"]) if port else None

    if action == "REQUEST":
        if outage["state"] not in ("CLASSIFIED", "RESOLVED"):
            raise err("ERR_INVALID_STATE",
                      "An exclusion may only be requested from CLASSIFIED or RESOLVED.")
        if port["service_state"] == "RETIRED":
            raise err("ERR_PORT_RETIRED", "The dispenser is retired.")
        effective_cause = (claimed_cause if claimed_cause is not None
                           else outage["excluded_cause_claim"])
        if effective_cause == "NONE":
            raise err("ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE",
                      "An excluded_cause_claim of NONE is not eligible for exclusion.")
        if claimed_cause is not None:
            outage["excluded_cause_claim"] = claimed_cause
        outage["pre_exclusion_state"] = outage["state"]
        outage["state"] = "EXCLUSION_REVIEW"
        db.touch(outage)

    elif action == "APPROVE":
        if outage["state"] != "EXCLUSION_REVIEW":
            raise err("ERR_INVALID_STATE",
                      "Only an outage in EXCLUSION_REVIEW may be approved.")
        if outage["excluded_cause_claim"] == "NONE":
            raise err("ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE",
                      "An excluded_cause_claim of NONE is not eligible for exclusion.")
        left_state = outage["pre_exclusion_state"]
        outage["state"] = "EXCLUDED"
        outage["excluded_at"] = clock.now()
        db.touch(outage)
        if station is not None:
            cascades.invalidate_provisional_reports(station["id"])
        if left_state == "CLASSIFIED":
            cascades.port_back_in_service(port)

    elif action == "REJECT":
        if outage["state"] != "EXCLUSION_REVIEW":
            raise err("ERR_INVALID_STATE",
                      "Only an outage in EXCLUSION_REVIEW may be rejected.")
        if outage["pre_exclusion_state"] is None:
            raise err("ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE",
                      "The outage has no recorded pre_exclusion_state to restore.")
        outage["state"] = outage["pre_exclusion_state"]
        outage["pre_exclusion_state"] = None
        db.touch(outage)

    else:  # REVOKE
        if outage["state"] != "EXCLUDED":
            raise err("ERR_INVALID_STATE", "Only an EXCLUDED outage may have its exclusion revoked.")
        if outage["pre_exclusion_state"] is None:
            raise err("ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE",
                      "The outage has no recorded pre_exclusion_state to restore.")
        destination = outage["pre_exclusion_state"]
        outage["state"] = destination
        outage["excluded_at"] = None
        outage["pre_exclusion_state"] = None
        db.touch(outage)
        if station is not None:
            cascades.invalidate_provisional_reports(station["id"])
        if destination == "CLASSIFIED" and outage["fault_class"] in OUT_OF_SERVICE_CLASSES:
            cascades.port_out_of_service(port)

    return object_response(serialize.outage_event(outage))


@bp.post("/outage-events/<outage_event_id>/resolution-reviews")
@endpoint("NetworkOperator", "ComplianceAuditor")
def resolution_review(outage_event_id):
    outage = lookup.outage(outage_event_id)
    body = validation.json_body()
    outcome = validation.as_enum(body, "outcome", REVIEW_OUTCOMES)

    require_role_for_leg("ComplianceAuditor" if outcome == "VERIFY" else "NetworkOperator")

    if outage["state"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "Only a RESOLVED outage may be reviewed.")

    port = db.ports.get(outage["port_id"])

    if outcome == "VERIFY":
        if (outage["dispatch_created_by_user_id"] is not None
                and outage["dispatch_created_by_user_id"] == current_user_id()):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "The operator who dispatched the repair may not verify it.")
        outage["state"] = "VERIFIED"
        db.touch(outage)
    else:  # REOPEN
        if port["service_state"] == "RETIRED":
            raise err("ERR_PORT_RETIRED", "The dispenser is retired.")
        outage["state"] = "CLASSIFIED"
        outage["cleared_at"] = None
        db.touch(outage)
        if outage["fault_class"] in OUT_OF_SERVICE_CLASSES:
            cascades.port_out_of_service(port)

    return object_response(serialize.outage_event(outage))
