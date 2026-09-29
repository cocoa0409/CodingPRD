"""Proposed actions, extraordinary-circumstance screens, classification, record."""

from flask import Blueprint

import db
import response
import validation as v
from errors import fail, invalid
from middleware import endpoint
from routes.helpers import body_ref, list_response, of_action, office_of, path_row
from services import calc, cascade, record

bp = Blueprint("actions", __name__)

ACTION_SPEC = {
    "office_id": {"required": True, "check": v.c_str(1)},
    "title": {"required": True, "check": v.c_str(1)},
    "disturbance_hectares": {"required": True, "check": v.c_num(lo=0)},
    "reference_cost_cents": {"required": True, "check": v.c_int(lo=1)},
    "in_critical_habitat": {"check": v.c_bool, "default": False},
    "affects_historic_property": {"check": v.c_bool, "default": False},
    "tribal_interest": {"check": v.c_bool, "default": False},
    "floodplain_or_wetland": {"check": v.c_bool, "default": False},
}

SCREEN_STAGES = ("INTAKE", "SCREENED", "CLASSIFIED", "SCOPING", "ANALYSIS", "DRAFT_PUBLISHED")

READ_ACTION_ROLES = [
    "PolicyAdmin",
    "NepaCoordinator",
    "ResourceSpecialist",
    "ReviewingOfficial",
    "DecidingOfficial",
    "ObjectionReviewingOfficer",
]
SCREEN_READ_ROLES = ["NepaCoordinator", "ReviewingOfficial", "DecidingOfficial"]


@endpoint(bp, "/proposed-actions", ["POST"], ["NepaCoordinator"])
def create_action():
    body = v.parse_body(ACTION_SPEC)
    body_ref("offices", body["office_id"], "office_id")
    fields = dict(body)
    fields.update(
        {
            "classification": None,
            "review_stage": "INTAKE",
            "ec_screen_outcome": None,
            "extraordinary_circumstance_flag": False,
            "significant_issue_count": 0,
            "unaddressed_issue_count": 0,
            "alternatives_screened_in_count": 0,
            "finalized_analysis_count": 0,
            "max_unmitigated_score": 0.0,
            "cumulative_intensity_index": 0.0,
            "record_entry_count": 0,
            "record_certified_at": None,
        }
    )
    row = db.new_row("actions", fields)
    return response.created(db.public(row))


@endpoint(bp, "/proposed-actions/<action_id>", ["GET"], READ_ACTION_ROLES)
def get_action(action_id):
    action = path_row("actions", action_id, "proposed action")
    return response.ok(db.public(action))


@endpoint(bp, "/proposed-actions", ["GET"], [
    "PolicyAdmin",
    "NepaCoordinator",
    "ResourceSpecialist",
    "ReviewingOfficial",
    "DecidingOfficial",
])
def list_actions():
    return list_response(db.rows("actions"), "office_id", "classification", "review_stage")


@endpoint(bp, "/proposed-actions/<action_id>/classify", ["POST"], ["NepaCoordinator"])
def classify_action(action_id):
    v.no_body()
    action = path_row("actions", action_id, "proposed action")
    if action["review_stage"] != "SCREENED" or action["ec_screen_outcome"] is None:
        fail(
            "ERR_INVALID_STATE",
            "classification requires review_stage SCREENED and an adjudicated screen outcome",
        )
    office = office_of(action)
    action["classification"] = calc.classify(action, office)
    action["review_stage"] = "CLASSIFIED"
    db.touch(action)
    record.add_entry(
        action,
        "CLASSIFICATION_ASSIGNED",
        "ProposedAction",
        action["id"],
        "Classification assigned: %s" % action["classification"],
    )
    return response.ok(db.public(action))


# ------------------------------------------- extraordinary-circumstance screens


def _check_codes(findings, office):
    permitted = set(office["extraordinary_circumstance_codes"])
    for finding in findings:
        if finding["code"] not in permitted:
            raise invalid(
                "findings.code %s is not screened for by this office" % finding["code"]
            )


@endpoint(bp, "/proposed-actions/<action_id>/ec-screens", ["POST"], ["NepaCoordinator"])
def create_screen(action_id):
    body = v.parse_body({"findings": {"required": True, "check": v.c_findings}})
    action = path_row("actions", action_id, "proposed action")
    office = office_of(action)
    _check_codes(body["findings"], office)
    if action["review_stage"] not in SCREEN_STAGES:
        fail("ERR_INVALID_STATE", "the action's review_stage does not permit screening")
    triggered, max_severity = calc.screen_derived(body["findings"], office)
    row = db.new_row(
        "screens",
        {
            "action_id": action["id"],
            "screen_round": 1,
            "findings": body["findings"],
            "triggered_codes": triggered,
            "max_severity": max_severity,
            "status": "SUBMITTED",
            "adjudicator_note": None,
        },
    )
    return response.created(db.public(row))


@endpoint(bp, "/proposed-actions/<action_id>/ec-screens", ["GET"], SCREEN_READ_ROLES)
def list_screens(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(of_action("screens", action_id), "status")


@endpoint(bp, "/ec-screens/<screen_id>", ["GET"], SCREEN_READ_ROLES)
def get_screen(screen_id):
    screen = path_row("screens", screen_id, "extraordinary-circumstance screen")
    return response.ok(db.public(screen))


@endpoint(bp, "/ec-screens/<screen_id>/adjudicate", ["POST"], ["ReviewingOfficial"])
def adjudicate_screen(screen_id):
    body = v.parse_body(
        {
            "disposition": {
                "required": True,
                "check": v.c_enum(("RETURNED", "CLEARED", "TRIGGERED")),
            },
            "adjudicator_note": {"required": True, "check": v.c_str(0)},
        }
    )
    disposition = body["disposition"]
    note = body["adjudicator_note"]
    if disposition == "RETURNED" and not note.strip():
        raise invalid("adjudicator_note must be non-empty for a RETURNED disposition")

    screen = path_row("screens", screen_id, "extraordinary-circumstance screen")
    if screen["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED screen may be adjudicated")

    triggered = list(screen["triggered_codes"])
    if disposition == "CLEARED" and triggered:
        fail(
            "ERR_EC_SCREEN_NOT_TRIGGERED",
            "the screen has triggered codes and may not be CLEARED",
        )
    if disposition == "TRIGGERED" and not triggered:
        fail(
            "ERR_EC_SCREEN_NOT_TRIGGERED",
            "the screen has no triggered codes and may not be TRIGGERED",
        )

    screen["adjudicator_note"] = note
    screen["status"] = disposition
    db.touch(screen)

    if disposition == "RETURNED":
        # A return is not an adjudicated outcome: nothing on the action moves.
        return response.ok(db.public(screen))

    action = db.find("actions", screen["action_id"])
    action["ec_screen_outcome"] = disposition
    action["extraordinary_circumstance_flag"] = disposition == "TRIGGERED"
    if action["review_stage"] == "INTAKE":
        action["review_stage"] = "SCREENED"
    db.touch(action)
    record.add_entry(
        action,
        "EC_SCREEN_ADJUDICATED",
        "ExtraordinaryCircumstanceScreen",
        screen["id"],
        "Extraordinary-circumstance screen adjudicated %s" % disposition,
    )
    if disposition == "TRIGGERED":
        cascade.escalate_classification(action)
    return response.ok(db.public(screen))


@endpoint(bp, "/ec-screens/<screen_id>/resubmit", ["POST"], ["NepaCoordinator"])
def resubmit_screen(screen_id):
    body = v.parse_body({"findings": {"required": True, "check": v.c_findings}})
    screen = path_row("screens", screen_id, "extraordinary-circumstance screen")
    action = db.find("actions", screen["action_id"])
    office = office_of(action)
    _check_codes(body["findings"], office)
    if screen["status"] != "RETURNED":
        fail("ERR_INVALID_STATE", "only a RETURNED screen may be resubmitted")
    triggered, max_severity = calc.screen_derived(body["findings"], office)
    screen["findings"] = body["findings"]
    screen["screen_round"] = screen["screen_round"] + 1
    screen["triggered_codes"] = triggered
    screen["max_severity"] = max_severity
    screen["status"] = "SUBMITTED"
    screen["adjudicator_note"] = None
    db.touch(screen)
    return response.ok(db.public(screen))


# ----------------------------------------------------- administrative record


@endpoint(bp, "/proposed-actions/<action_id>/record-entries", ["GET"], [
    "NepaCoordinator",
    "ReviewingOfficial",
    "DecidingOfficial",
    "ObjectionReviewingOfficer",
    "PublicCommenter",
])
def list_record_entries(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(record.entries_for(action_id), "entry_code")
