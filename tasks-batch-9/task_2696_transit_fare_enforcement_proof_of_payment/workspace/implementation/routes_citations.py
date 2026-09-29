"""Citation issuance, the progressive ladder, adjudication and appellate review."""

from flask import Blueprint

import calc
import cascade
import serial
from core import (ApiError, authorize, base_record, body, db, days, lookup,
                  opt_enum, opt_int, ordered, page, pagination, query_filter,
                  req_enum, req_int, req_str, respond_object, touch)

bp = Blueprint("citations", __name__)

CITATION_READ_ROLES = ("EnforcementPlanner", "EquityAnalyst", "FareInspector",
                       "HearingOfficer", "AppealsBoardMember", "Rider")
PAYMENT_READ_ROLES = ("EnforcementPlanner", "HearingOfficer", "AppealsBoardMember", "Rider")
HEARING_READ_ROLES = ("EnforcementPlanner", "HearingOfficer", "AppealsBoardMember",
                      "Rider", "EquityAnalyst")


def _mint_citation(encounter, zone, rider, inspector, issued_at,
                   reissued_from_citation_id=None):
    offense_sequence, citation_only_sequence = calc.offense_sequences(
        rider["id"], issued_at)
    assessed = calc.assess_penalty(offense_sequence, zone["penalty_multiplier_bps"],
                                   rider["fare_assistance_enrolled"])
    floor = calc.assess_penalty(citation_only_sequence, zone["penalty_multiplier_bps"],
                                rider["fare_assistance_enrolled"])
    fee = calc.admin_fee_cents(assessed)
    citation = base_record()
    citation.update({
        "encounter_id": encounter["id"],
        "rider_id": rider["id"],
        "zone_id": zone["id"],
        "issuing_inspector_id": inspector["id"],
        "reissued_from_citation_id": reissued_from_citation_id,
        "issued_at": issued_at,
        "offense_sequence": offense_sequence,
        "citation_only_sequence": citation_only_sequence,
        "assessed_penalty_cents": assessed,
        "reduction_floor_cents": floor,
        "admin_fee_cents": fee,
        "total_due_cents": assessed + fee,
        "amount_paid_cents": 0,
        "service_credit_cents": 0,
        "outstanding_balance_cents": assessed + fee,
        "contest_deadline_at": issued_at + days(calc.CONTEST_WINDOW_DAYS),
        "adjudication_status": "ISSUED",
        "settlement_status": "OUTSTANDING",
        "dismissal_reason_code": None,
        "dismissed_at": None,
    })
    db.citations[citation["id"]] = citation
    return citation


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------

@bp.post("/citations")
def issue_citation():
    actor = authorize("FareInspector")
    payload = body()
    encounter_id = req_str(payload, "encounter_id", min_len=1)
    encounter = lookup(db.encounters, encounter_id, "ERR_ENCOUNTER_NOT_FOUND")

    if actor.user_id != encounter["inspector_id"]:
        raise ApiError("ERR_INSPECTOR_NOT_ON_ENCOUNTER",
                       "X-User-ID must equal the encounter's inspector_id.")
    if encounter["outcome"] != "PENDING":
        raise ApiError("ERR_ENCOUNTER_NOT_PENDING",
                       "Encounter is %s, not PENDING." % encounter["outcome"])

    deployment = db.deployments[encounter["deployment_id"]]
    zone = db.zones[deployment["zone_id"]]
    inspector = db.inspectors[encounter["inspector_id"]]

    if zone["designation_status"] != "DESIGNATED":
        raise ApiError("ERR_ZONE_NOT_DESIGNATED",
                       "The governing zone is %s, not DESIGNATED."
                       % zone["designation_status"])
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_SUSPENDED", "The inspector is SUSPENDED.")
    if not inspector["certification_expiry"] > encounter["occurred_at"]:
        raise ApiError("ERR_INSPECTOR_CERT_EXPIRED",
                       "The inspector's certification had lapsed at occurred_at.")
    if (encounter["rider_id"] is None
            or encounter["identity_capture_method"] not in ("GOVT_ID", "SELF_REPORTED")):
        raise ApiError("ERR_IDENTITY_NOT_ESTABLISHED",
                       "Identity was not established on this encounter.")

    rider = db.riders[encounter["rider_id"]]
    issued_at = db.now()
    offense_sequence, _citation_only = calc.offense_sequences(rider["id"], issued_at)

    if zone["enforcement_policy"] == "WARNING_FIRST" and offense_sequence < 2:
        raise ApiError("ERR_WARNING_REQUIRED_FIRST_OFFENSE",
                       "A first contact in a WARNING_FIRST zone must be a warning.")
    if encounter["validation_result"] not in calc.NONCOMPLIANT_RESULTS:
        raise ApiError("ERR_DISPOSITION_NOT_SUPPORTED",
                       "A citation requires a non-compliant fare-media verdict.")
    for existing in db.citations.values():
        if existing["encounter_id"] == encounter["id"]:
            raise ApiError("ERR_ENCOUNTER_ALREADY_CITED",
                           "A citation already references this encounter.")

    citation = _mint_citation(encounter, zone, rider, inspector, issued_at)
    encounter["outcome"] = "CITATION_ISSUED"
    touch(encounter)
    return respond_object(serial.citation_out(citation), 201)


@bp.get("/citations/<citation_id>")
def get_citation(citation_id):
    authorize(*CITATION_READ_ROLES)
    citation = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    return respond_object(serial.citation_out(citation))


@bp.get("/citations")
def list_citations():
    authorize(*CITATION_READ_ROLES)
    limit, offset = pagination()
    rider_id = query_filter("rider_id")
    zone_id = query_filter("zone_id")
    encounter_id = query_filter("encounter_id")
    issuing_inspector_id = query_filter("issuing_inspector_id")
    reissued_from = query_filter("reissued_from_citation_id")
    adjudication_status = query_filter("adjudication_status")
    settlement_status = query_filter("settlement_status")
    rows = [c for c in db.citations.values()
            if (rider_id is None or c["rider_id"] == rider_id)
            and (zone_id is None or c["zone_id"] == zone_id)
            and (encounter_id is None or c["encounter_id"] == encounter_id)
            and (issuing_inspector_id is None
                 or c["issuing_inspector_id"] == issuing_inspector_id)
            and (reissued_from is None or c["reissued_from_citation_id"] == reissued_from)
            and (adjudication_status is None
                 or c["adjudication_status"] == adjudication_status)
            and (settlement_status is None or c["settlement_status"] == settlement_status)]
    return page(ordered(rows), limit, offset, serial.citation_out)


@bp.get("/citations/<citation_id>/payments")
def list_citation_payments(citation_id):
    authorize(*PAYMENT_READ_ROLES)
    limit, offset = pagination()
    citation = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    rows = ordered(calc.citation_payments(citation["id"]))
    return page(rows, limit, offset, serial.payment_out)


# ---------------------------------------------------------------------------
# Contest -> hearing
# ---------------------------------------------------------------------------

@bp.post("/citations/<citation_id>/contest")
def contest_citation(citation_id):
    actor = authorize("Rider")
    citation = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    if actor.user_id != citation["rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the cited rider may contest this citation.")
    if citation["adjudication_status"] != "ISSUED":
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s; only ISSUED may be contested."
                       % citation["adjudication_status"])
    if db.now() > citation["contest_deadline_at"]:
        raise ApiError("ERR_CONTEST_WINDOW_CLOSED",
                       "The 30-day contest window has closed.")

    citation["adjudication_status"] = "CONTESTED"
    touch(citation)

    hearing = base_record()
    hearing.update({
        "citation_id": citation["id"],
        "requested_by_rider_id": citation["rider_id"],
        "scheduled_for": db.now() + days(calc.HEARING_LEAD_DAYS),
        "hearing_officer_user_id": None,
        "decision": "PENDING",
        "dismissal_reason_code": None,
        "reduced_penalty_cents": None,
        "decided_at": None,
        "status": "SCHEDULED",
    })
    db.hearings[hearing["id"]] = hearing
    return respond_object(serial.hearing_out(hearing), 201)


# ---------------------------------------------------------------------------
# Reissue
# ---------------------------------------------------------------------------

@bp.post("/citations/<citation_id>/reissue")
def reissue_citation(citation_id):
    authorize("EnforcementPlanner")
    original = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")
    if original["adjudication_status"] != "DISMISSED":
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s; only DISMISSED may be reissued."
                       % original["adjudication_status"])
    for existing in db.citations.values():
        if existing["id"] == original["id"]:
            continue
        if (existing["encounter_id"] == original["encounter_id"]
                and existing["adjudication_status"] not in ("DISMISSED", "VOID")):
            raise ApiError("ERR_ENCOUNTER_ALREADY_CITED",
                           "A live citation already references this encounter.")
    if original["dismissal_reason_code"] != "PROCEDURAL_DEFECT":
        raise ApiError("ERR_REISSUE_NOT_PERMITTED",
                       "Only a citation dismissed for PROCEDURAL_DEFECT may be reissued.")
    if db.now() > original["dismissed_at"] + days(calc.REISSUE_WINDOW_DAYS):
        raise ApiError("ERR_REISSUE_WINDOW_CLOSED",
                       "The 14-day reissue window has closed.")

    encounter = db.encounters[original["encounter_id"]]
    zone = db.zones[original["zone_id"]]
    rider = db.riders[original["rider_id"]]
    inspector = db.inspectors[original["issuing_inspector_id"]]
    citation = _mint_citation(encounter, zone, rider, inspector, original["issued_at"],
                              reissued_from_citation_id=original["id"])
    return respond_object(serial.citation_out(citation), 201)


# ---------------------------------------------------------------------------
# Adjudication hearings
# ---------------------------------------------------------------------------

@bp.post("/adjudication-hearings/<hearing_id>/decide")
def decide_hearing(hearing_id):
    actor = authorize("HearingOfficer")
    payload = body()
    decision = req_enum(payload, "decision", calc.DECIDE_DECISIONS)
    dismissal_reason_code = opt_enum(payload, "dismissal_reason_code",
                                     calc.DISMISSAL_REASONS)
    reduced_penalty_cents = opt_int(payload, "reduced_penalty_cents")

    hearing = lookup(db.hearings, hearing_id, "ERR_HEARING_NOT_FOUND")
    if hearing["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED",
                       "Hearing is %s, not SCHEDULED." % hearing["status"])
    citation = db.citations[hearing["citation_id"]]
    if citation["adjudication_status"] != "CONTESTED":
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s, not CONTESTED." % citation["adjudication_status"])

    if decision == "DISMISS":
        if dismissal_reason_code is None or reduced_penalty_cents is not None:
            raise ApiError("ERR_DECISION_FIELDS_INVALID",
                           "A DISMISS decision carries dismissal_reason_code only.")
    elif decision == "REDUCE":
        if reduced_penalty_cents is None or dismissal_reason_code is not None:
            raise ApiError("ERR_DECISION_FIELDS_INVALID",
                           "A REDUCE decision carries reduced_penalty_cents only.")
    else:
        if dismissal_reason_code is not None or reduced_penalty_cents is not None:
            raise ApiError("ERR_DECISION_FIELDS_INVALID",
                           "An UPHOLD decision carries neither optional field.")

    if dismissal_reason_code == "FIRST_OFFENSE_DIVERSION" and citation["offense_sequence"] != 1:
        raise ApiError("ERR_DIVERSION_NOT_ELIGIBLE",
                       "FIRST_OFFENSE_DIVERSION requires offense_sequence 1.")

    if decision == "REDUCE":
        if not (citation["reduction_floor_cents"] <= reduced_penalty_cents
                < citation["assessed_penalty_cents"]):
            raise ApiError("ERR_REDUCTION_BELOW_FLOOR",
                           "reduced_penalty_cents must be within [reduction_floor, assessed).")

    hearing["status"] = "HELD"
    hearing["decision"] = decision
    hearing["decided_at"] = db.now()
    hearing["hearing_officer_user_id"] = actor.user_id
    hearing["dismissal_reason_code"] = dismissal_reason_code
    hearing["reduced_penalty_cents"] = reduced_penalty_cents
    touch(hearing)

    if decision == "UPHOLD":
        citation["adjudication_status"] = "UPHELD"
    elif decision == "REDUCE":
        citation["adjudication_status"] = "REDUCED"
        citation["assessed_penalty_cents"] = reduced_penalty_cents
        citation["admin_fee_cents"] = calc.admin_fee_cents(reduced_penalty_cents)
        citation["total_due_cents"] = (citation["assessed_penalty_cents"]
                                       + citation["admin_fee_cents"])
        calc.refresh_citation_money(citation)
    else:
        citation["adjudication_status"] = "DISMISSED"
        citation["dismissal_reason_code"] = dismissal_reason_code
        citation["dismissed_at"] = db.now()
        cascade.dismissal_unwind(citation)
    touch(citation)
    return respond_object(serial.hearing_out(hearing))


@bp.post("/adjudication-hearings/<hearing_id>/cancel")
def cancel_hearing(hearing_id):
    authorize("HearingOfficer")
    hearing = lookup(db.hearings, hearing_id, "ERR_HEARING_NOT_FOUND")
    if hearing["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED",
                       "Hearing is %s, not SCHEDULED." % hearing["status"])
    citation = db.citations[hearing["citation_id"]]
    if citation["adjudication_status"] != "CONTESTED":
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s, not CONTESTED." % citation["adjudication_status"])
    hearing["status"] = "CANCELLED"
    touch(hearing)
    citation["adjudication_status"] = "ISSUED"
    touch(citation)
    return respond_object(serial.hearing_out(hearing))


@bp.get("/adjudication-hearings/<hearing_id>")
def get_hearing(hearing_id):
    authorize(*HEARING_READ_ROLES)
    hearing = lookup(db.hearings, hearing_id, "ERR_HEARING_NOT_FOUND")
    return respond_object(serial.hearing_out(hearing))


@bp.get("/adjudication-hearings")
def list_hearings():
    authorize(*HEARING_READ_ROLES)
    limit, offset = pagination()
    citation_id = query_filter("citation_id")
    requested_by_rider_id = query_filter("requested_by_rider_id")
    status = query_filter("status")
    rows = [h for h in db.hearings.values()
            if (citation_id is None or h["citation_id"] == citation_id)
            and (requested_by_rider_id is None
                 or h["requested_by_rider_id"] == requested_by_rider_id)
            and (status is None or h["status"] == status)]
    return page(ordered(rows), limit, offset, serial.hearing_out)
