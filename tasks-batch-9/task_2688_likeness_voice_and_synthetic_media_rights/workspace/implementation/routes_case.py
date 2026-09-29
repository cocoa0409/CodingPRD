"""Unauthorized-use monitoring: case intake, triage, escalation and closure."""

from flask import Blueprint, g

import calc
import guards
import services
from core import (
    authorize, body_json, collection, db, dec, fail, now, public, respond, touch,
    want_code, want_enum, want_int, want_pct, want_str,
)

bp = Blueprint("cases", __name__)

DETECTION_SOURCES = ("MONITORING_FEED", "SWEEP", "MANUAL_REPORT")
CASE_READ_ROLES = ("RightsAdministrator", "ComplianceOfficer",
                   "TalentRepresentative", "EstateRepresentative")


@bp.post("/infringement-cases")
def open_case():
    authorize("ComplianceOfficer")
    body = body_json()
    talent_id = want_str(body, "talent_id", 1, None)
    detection_source = want_enum(body, "detection_source", DETECTION_SOURCES,
                                 required=False, default="MONITORING_FEED")
    suspect_url = want_str(body, "suspect_url", 1, 300)
    detected_channel = want_enum(body, "detected_channel", calc.CHANNELS)
    detected_state_code = want_code(body, "detected_state_code")
    detected_view_count = want_int(body, "detected_view_count", 0)
    match_confidence = want_pct(body, "match_confidence", 0, 1, False, False, decimals=3)
    matched_usage_license_id = want_str(body, "matched_usage_license_id", 1, None,
                                       required=False)

    talent = guards.need_talent(talent_id)
    if matched_usage_license_id is not None:
        guards.need_license(matched_usage_license_id)

    domicile_profile = guards.need_profile(talent["domicile_state_code"])
    detected_profile = guards.need_profile(detected_state_code)

    case = services.create_case(talent, domicile_profile, detected_profile, {
        "detection_source": detection_source,
        "suspect_url": suspect_url,
        "detected_channel": detected_channel,
        "detected_state_code": detected_state_code,
        "detected_view_count": detected_view_count,
        "match_confidence": match_confidence,
        "matched_usage_license_id": matched_usage_license_id,
    })
    services.recompute_talent(talent)
    return respond(public(case), 201)


@bp.get("/infringement-cases/<row_id>")
def read_case(row_id):
    authorize(*CASE_READ_ROLES)
    return respond(public(guards.need_case(row_id)))


@bp.get("/infringement-cases")
def list_cases():
    authorize(*CASE_READ_ROLES)
    return collection(db.infringement_cases.values(), {
        "talent_id": "talent_id",
        "matched_usage_license_id": "matched_usage_license_id",
        "status": "status",
        "detection_source": "detection_source",
    })


@bp.post("/infringement-cases/<row_id>/triage")
def triage_case(row_id):
    authorize("ComplianceOfficer")
    body = body_json()
    decision = want_enum(body, "decision", ("DISMISS", "ISSUE_TAKEDOWN"))
    case = guards.need_case(row_id)
    talent = db.talents[case["talent_id"]]
    if case["status"] != "DETECTED":
        fail("ERR_INVALID_CASE_STATE", "only a DETECTED case may be triaged")

    enforceable = bool(case["enforceable_under_use_state"])
    severity = dec(case["severity_score"])
    if decision == "ISSUE_TAKEDOWN":
        if not enforceable:
            fail("ERR_POSTMORTEM_RIGHTS_EXPIRED",
                 "no post-mortem right is enforceable in the detected state")
    else:
        # A case at or above the mandatory-takedown threshold may not be
        # dismissed -- unless nothing could be enforced in the detected state.
        if severity >= calc.MANDATORY_TAKEDOWN_THRESHOLD and enforceable:
            fail("ERR_TAKEDOWN_MANDATORY",
                 "a case scoring %s or above may only be triaged as ISSUE_TAKEDOWN"
                 % calc.MANDATORY_TAKEDOWN_THRESHOLD)

    if decision == "ISSUE_TAKEDOWN":
        case["status"] = "TAKEDOWN_ISSUED"
        case["takedown_issued_at"] = now()
    else:
        matched = None
        if case["matched_usage_license_id"]:
            matched = db.usage_licenses.get(case["matched_usage_license_id"])
        if matched is not None and matched["distribution_status"] in ("ISSUED", "LIVE"):
            case["status"] = "DISMISSED_LICENSED"
            case["closure_outcome"] = "LICENSED_USE_CONFIRMED"
        else:
            case["status"] = "DISMISSED_NO_ACTION"
            case["closure_outcome"] = "BELOW_ENFORCEMENT_THRESHOLD"
    case["triaged_by_user_id"] = g.user_id
    touch(case)
    services.recompute_talent(talent)
    return respond(public(case))


@bp.post("/infringement-cases/<row_id>/escalate")
def escalate_case(row_id):
    authorize("RightsAdministrator")
    body = body_json()
    want_str(body, "escalation_note", 1, None)
    case = guards.need_case(row_id)
    talent = db.talents[case["talent_id"]]
    if case["triaged_by_user_id"] is not None \
            and case["triaged_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the administrator escalating a case may not be the officer who triaged it")
    if case["status"] != "TAKEDOWN_ISSUED":
        fail("ERR_INVALID_CASE_STATE",
             "only a TAKEDOWN_ISSUED case may be escalated to legal")
    if dec(case["severity_score"]) < calc.ESCALATION_FLOOR:
        fail("ERR_SEVERITY_BELOW_ESCALATION_FLOOR",
             "escalation requires a severity score of at least %s" % calc.ESCALATION_FLOOR)
    case["status"] = "LEGAL_ESCALATED"
    case["escalated_by_user_id"] = g.user_id
    touch(case)
    services.escalation_cascade(case, talent)
    touch(talent)
    return respond(public(case))


@bp.post("/infringement-cases/<row_id>/close")
def close_case(row_id):
    authorize("RightsAdministrator", "ComplianceOfficer")
    body = body_json()
    outcome = want_enum(body, "outcome", ("REMOVED", "SETTLED", "LITIGATED"))
    case = guards.need_case(row_id)
    talent = db.talents[case["talent_id"]]
    status = case["status"]
    if status == "TAKEDOWN_ISSUED" and outcome == "REMOVED":
        case["status"] = "RESOLVED_REMOVED"
        case["closure_outcome"] = "VOLUNTARY_REMOVAL"
        release = False
    elif status == "LEGAL_ESCALATED" and outcome == "SETTLED":
        case["status"] = "CLOSED_SETTLED"
        case["closure_outcome"] = "SETTLED"
        release = True
    elif status == "LEGAL_ESCALATED" and outcome == "LITIGATED":
        case["status"] = "CLOSED_LITIGATED"
        case["closure_outcome"] = "LITIGATED"
        release = True
    else:
        fail("ERR_INVALID_CASE_STATE",
             "outcome %s does not match a case in %s" % (outcome, status))
        return
    case["closed_by_user_id"] = g.user_id
    touch(case)
    if release:
        services.release_legal_holds(case, talent)
    else:
        services.recompute_talent(talent)
    touch(talent)
    return respond(public(case))
