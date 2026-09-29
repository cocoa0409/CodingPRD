"""Incident intake, classification and disposition (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("incidents", __name__)

REPORT_CHANNELS = ("CONSUMER_HOTLINE", "WEB_FORM", "RETAILER", "MEDICAL_EXAMINER")
INJURY_CLASSES = ("NO_INJURY", "FIRST_AID", "MEDICAL_TREATMENT",
                  "HOSPITALIZATION", "FATALITY")
HAZARD_CODES = ("LACERATION", "BURN", "CHOKING", "ELECTRIC_SHOCK", "FALL",
                "ENTRAPMENT")
INCIDENT_STATUSES = ("INTAKE", "CLASSIFIED", "CLUSTERED", "ESCALATED",
                     "MERGED_DUPLICATE", "CLOSED_NO_ACTION")
DISPOSITIONS = ("MERGED_DUPLICATE", "CLOSED_NO_ACTION")

READ_ROLES = ("ProgramAdmin", "IntakeSpecialist", "ComplianceOfficer",
              "SafetyDirector", "PenaltyCounsel")


@bp.route("/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    auth.authorize(*READ_ROLES)
    return responses.object_response(lookups.find("incident", incident_id))


@bp.route("/incidents", methods=["GET"])
def list_incidents():
    auth.authorize(*READ_ROLES)
    limit, offset = shapes.pagination()
    product_model_id = shapes.q_str("product_model_id")
    hazard_pattern_id = shapes.q_str("hazard_pattern_id")
    duplicate_of_incident_id = shapes.q_str("duplicate_of_incident_id")
    status = shapes.q_enum("status", INCIDENT_STATUSES)
    injury_class = shapes.q_enum("injury_class", INJURY_CLASSES)
    hazard_code = shapes.q_enum("hazard_code", HAZARD_CODES)

    def keep(row):
        if product_model_id is not None and row["product_model_id"] != product_model_id:
            return False
        if hazard_pattern_id is not None and row["hazard_pattern_id"] != hazard_pattern_id:
            return False
        if (duplicate_of_incident_id is not None
                and row["duplicate_of_incident_id"] != duplicate_of_incident_id):
            return False
        if status is not None and row["status"] != status:
            return False
        if injury_class is not None and row["injury_class"] != injury_class:
            return False
        if hazard_code is not None and row["hazard_code"] != hazard_code:
            return False
        return True

    return responses.list_response(store.ordered(store.incidents, keep), limit, offset)


@bp.route("/incidents", methods=["POST"])
def create_incident():
    auth.authorize("IntakeSpecialist", "ComplianceOfficer")
    data = shapes.body()
    product_model_id = shapes._req(data, "product_model_id")
    report_channel = shapes.req_enum(data, "report_channel", REPORT_CHANNELS)
    incident_date = shapes.req_ts(data, "incident_date")
    narrative = shapes.req_str(data, "narrative", 1, 2000)

    lookups.find("product_model", product_model_id)

    row = store.new_row(
        product_model_id=product_model_id,
        hazard_pattern_id=None,
        duplicate_of_incident_id=None,
        report_channel=report_channel,
        incident_date=incident_date,
        narrative=narrative,
        injury_class=None,
        hazard_code=None,
        injury_verified=False,
        severity_weight=store.rhu(Decimal("0"), 2),
        status="INTAKE",
        classified_at=None,
        escalation_deadline_at=None,
    )
    store.incidents[row["id"]] = row
    return responses.created(row)


@bp.route("/incidents/<incident_id>/classify", methods=["POST"])
def classify_incident(incident_id):
    auth.authorize("IntakeSpecialist", "ComplianceOfficer")
    incident = lookups.find("incident", incident_id)
    data = shapes.body()
    injury_class = shapes.req_enum(data, "injury_class", INJURY_CLASSES)
    hazard_code = shapes.req_enum(data, "hazard_code", HAZARD_CODES)
    injury_verified = shapes.req_bool(data, "injury_verified")

    status = incident["status"]
    if status == "CLASSIFIED":
        # Reclassification self-loop, legal only while unclaimed by a pattern.
        if incident["hazard_pattern_id"] is not None:
            raise_error("ERR_INCIDENT_STATE_INVALID")
    elif status != "INTAKE":
        raise_error("ERR_INCIDENT_STATE_INVALID")

    incident["injury_class"] = injury_class
    incident["hazard_code"] = hazard_code
    incident["injury_verified"] = injury_verified
    incident["classified_at"] = store.now_logical()
    incident["severity_weight"] = calc.severity_weight(
        injury_class, incident["report_channel"], injury_verified)
    incident["status"] = "CLASSIFIED"
    store.touch(incident)
    return responses.object_response(incident)


@bp.route("/incidents/<incident_id>/dispose", methods=["POST"])
def dispose_incident(incident_id):
    auth.authorize("IntakeSpecialist", "ComplianceOfficer")
    incident = lookups.find("incident", incident_id)
    data = shapes.body()
    disposition = shapes.req_enum(data, "disposition", DISPOSITIONS)
    shapes.opt_str(data, "note", 0, 2000)

    supplied = shapes.present(data, "duplicate_of_incident_id")
    if disposition == "MERGED_DUPLICATE":
        if not supplied:
            shapes.bad()
        duplicate_of_incident_id = data["duplicate_of_incident_id"]
    else:
        if supplied:
            shapes.bad()
        duplicate_of_incident_id = None

    target = None
    if duplicate_of_incident_id is not None:
        target = lookups.find("incident", duplicate_of_incident_id)

    status = incident["status"]
    if status == "CLASSIFIED":
        if incident["hazard_pattern_id"] is not None:
            raise_error("ERR_INCIDENT_STATE_INVALID")
    elif status != "INTAKE":
        raise_error("ERR_INCIDENT_STATE_INVALID")

    if target is not None:
        if target["id"] == incident["id"]:
            raise_error("ERR_SELF_DUPLICATE_REFERENCE")
        if (target["duplicate_of_incident_id"] is not None
                or target["status"] == "MERGED_DUPLICATE"
                or target["product_model_id"] != incident["product_model_id"]):
            raise_error("ERR_DUPLICATE_CHAIN_FORBIDDEN")

    incident["status"] = disposition
    if duplicate_of_incident_id is not None:
        incident["duplicate_of_incident_id"] = duplicate_of_incident_id
    store.touch(incident)
    return responses.object_response(incident)
