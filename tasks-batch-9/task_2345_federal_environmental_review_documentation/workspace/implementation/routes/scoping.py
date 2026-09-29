"""Purpose and need statements, scoping periods and scoping issues."""

from flask import Blueprint

import db
import response
import validation as v
from errors import fail, invalid
from middleware import endpoint
from routes.helpers import body_ref, list_response, of_action, office_of, path_row
from services import record, rollups

bp = Blueprint("scoping", __name__)

PN_SPEC = {
    "purpose_text": {"required": True, "check": v.c_str(1)},
    "need_text": {"required": True, "check": v.c_str(1)},
    "goal_codes": {"required": True, "check": v.c_code_array(min_items=1)},
    "constraint_codes": {"check": v.c_code_array(), "default": []},
}

SCOPING_SPEC = {
    "scoping_kind": {"required": True, "check": v.c_enum(("PUBLIC", "AGENCY"))},
    "start_at": {"required": True, "check": v.c_datetime},
    "end_at": {"required": True, "check": v.c_datetime},
}

ISSUE_SPEC = {
    "scoping_period_id": {"required": True, "check": v.c_str(1)},
    "resource_area": {"required": True, "check": v.c_enum(v.RESOURCE_AREAS)},
    "origin": {"required": True, "check": v.c_enum(("PUBLIC", "AGENCY"))},
    "significance": {"required": True, "check": v.c_enum(("SIGNIFICANT", "NON_SIGNIFICANT"))},
    "summary": {"required": True, "check": v.c_str(1)},
}

PN_READ_ROLES = ["NepaCoordinator", "ReviewingOfficial", "DecidingOfficial"]
SCOPING_READ_ROLES = ["NepaCoordinator", "ReviewingOfficial", "ResourceSpecialist"]
ISSUE_READ_ROLES = ["NepaCoordinator", "ResourceSpecialist", "ReviewingOfficial"]


def adopted_statement(action_id):
    for statement in db.rows("statements"):
        if statement["action_id"] == action_id and statement["status"] == "ADOPTED":
            return statement
    return None


# ------------------------------------------------------ purpose and need


@endpoint(
    bp, "/proposed-actions/<action_id>/purpose-need-statements", ["POST"], ["NepaCoordinator"]
)
def create_statement(action_id):
    body = v.parse_body(PN_SPEC)
    action = path_row("actions", action_id, "proposed action")
    highest = 0
    for statement in of_action("statements", action["id"]):
        if statement["version_no"] > highest:
            highest = statement["version_no"]
    row = db.new_row(
        "statements",
        {
            "action_id": action["id"],
            "version_no": highest + 1,
            "purpose_text": body["purpose_text"],
            "need_text": body["need_text"],
            "goal_codes": body["goal_codes"],
            "constraint_codes": body["constraint_codes"],
            "status": "DRAFT",
        },
    )
    return response.created(db.public(row))


@endpoint(bp, "/proposed-actions/<action_id>/purpose-need-statements", ["GET"], PN_READ_ROLES)
def list_statements(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(of_action("statements", action_id), "status")


@endpoint(bp, "/purpose-need-statements/<statement_id>", ["GET"], PN_READ_ROLES)
def get_statement(statement_id):
    statement = path_row("statements", statement_id, "purpose and need statement")
    return response.ok(db.public(statement))


@endpoint(bp, "/purpose-need-statements/<statement_id>/adopt", ["POST"], ["ReviewingOfficial"])
def adopt_statement(statement_id):
    body = v.parse_body(
        {"expected_action_version": {"required": True, "check": v.c_int(lo=0)}}
    )
    statement = path_row("statements", statement_id, "purpose and need statement")
    action = db.find("actions", statement["action_id"])

    if statement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT statement may be adopted")
    if action["review_stage"] not in ("CLASSIFIED", "SCOPING", "ANALYSIS"):
        fail("ERR_INVALID_STATE", "the action's review_stage does not permit adoption")
    if body["expected_action_version"] != action["version"]:
        fail("ERR_STALE_ACTION_VERSION", "expected_action_version does not match the action")

    statement["status"] = "ADOPTED"
    db.touch(statement)

    superseded = None
    for other in of_action("statements", action["id"]):
        if other["id"] != statement["id"] and other["status"] == "ADOPTED":
            other["status"] = "SUPERSEDED"
            db.touch(other)
            superseded = other

    if superseded is not None:
        for alternative in of_action("alternatives", action["id"]):
            if alternative["pinned_pn_statement_id"] != superseded["id"]:
                continue
            if alternative["screening_status"] not in ("PROPOSED", "SCREENED_IN"):
                continue
            alternative["screening_status"] = "STALE"
            db.touch(alternative)

    rollups.refresh_action(action)
    record.add_entry(
        action,
        "PN_ADOPTED",
        "PurposeNeedStatement",
        statement["id"],
        "Purpose and need statement version %s adopted" % statement["version_no"],
    )
    return response.ok(db.public(statement))


# ---------------------------------------------------------- scoping periods


@endpoint(bp, "/proposed-actions/<action_id>/scoping-periods", ["POST"], ["NepaCoordinator"])
def create_scoping_period(action_id):
    body = v.parse_body(SCOPING_SPEC)
    start = db.parse_dt(body["start_at"])
    end = db.parse_dt(body["end_at"])
    if not end > start:
        raise invalid("end_at must be strictly later than start_at")

    action = path_row("actions", action_id, "proposed action")
    if action["classification"] is None or action["review_stage"] not in ("CLASSIFIED", "SCOPING"):
        fail("ERR_INVALID_STATE", "the action's review_stage does not permit opening a scoping period")

    for period in of_action("scoping_periods", action["id"]):
        if period["scoping_kind"] != body["scoping_kind"]:
            continue
        other_start = db.parse_dt(period["start_at"])
        other_end = db.parse_dt(period["end_at"])
        # Half-open [start, end): touching endpoints do not collide.
        if start < other_end and other_start < end:
            fail(
                "ERR_SCOPING_PERIOD_OVERLAP",
                "the interval overlaps an existing %s scoping period" % body["scoping_kind"],
            )

    row = db.new_row(
        "scoping_periods",
        {
            "action_id": action["id"],
            "scoping_kind": body["scoping_kind"],
            "start_at": body["start_at"],
            "end_at": body["end_at"],
            "duration_days": db.floor_days(start, end),
            "status": "OPEN",
        },
    )
    if action["review_stage"] == "CLASSIFIED":
        action["review_stage"] = "SCOPING"
        db.touch(action)
    return response.created(db.public(row))


@endpoint(bp, "/proposed-actions/<action_id>/scoping-periods", ["GET"], SCOPING_READ_ROLES)
def list_scoping_periods(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(of_action("scoping_periods", action_id), "scoping_kind", "status")


@endpoint(bp, "/scoping-periods/<period_id>", ["GET"], SCOPING_READ_ROLES)
def get_scoping_period(period_id):
    period = path_row("scoping_periods", period_id, "scoping period")
    return response.ok(db.public(period))


@endpoint(bp, "/scoping-periods/<period_id>/close", ["POST"], ["NepaCoordinator"])
def close_scoping_period(period_id):
    v.no_body()
    period = path_row("scoping_periods", period_id, "scoping period")
    action = db.find("actions", period["action_id"])
    office = office_of(action)

    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "only an OPEN scoping period may be closed")
    if adopted_statement(action["id"]) is None:
        fail(
            "ERR_NO_ADOPTED_PURPOSE_NEED",
            "the action has no ADOPTED purpose and need statement",
        )
    if period["scoping_kind"] == "PUBLIC" and period["duration_days"] < office["min_scoping_days"]:
        fail(
            "ERR_SCOPING_PERIOD_TOO_SHORT",
            "a PUBLIC scoping period must run at least %d whole days"
            % office["min_scoping_days"],
        )

    period["status"] = "CLOSED"
    db.touch(period)

    remaining = [p for p in of_action("scoping_periods", action["id"]) if p["status"] != "CLOSED"]
    if not remaining:
        if action["review_stage"] == "SCOPING":
            action["review_stage"] = "ANALYSIS"
            db.touch(action)
        record.add_entry(
            action,
            "SCOPING_CLOSED",
            "ScopingPeriod",
            period["id"],
            "Scoping closed for the action",
        )
    return response.ok(db.public(period))


# ------------------------------------------------------------------ issues


@endpoint(bp, "/proposed-actions/<action_id>/issues", ["POST"], ["NepaCoordinator"])
def create_issue(action_id):
    body = v.parse_body(ISSUE_SPEC)
    action = path_row("actions", action_id, "proposed action")
    period = body_ref("scoping_periods", body["scoping_period_id"], "scoping_period_id")

    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "issues may only be recorded against an OPEN scoping period")
    if period["action_id"] != action["id"]:
        fail("ERR_REFERENCE_MISMATCH", "the scoping period belongs to a different action")

    row = db.new_row(
        "issues",
        {
            "action_id": action["id"],
            "scoping_period_id": period["id"],
            "resource_area": body["resource_area"],
            "origin": body["origin"],
            "significance": body["significance"],
            "summary": body["summary"],
            "status": "OPEN",
        },
    )
    rollups.refresh_action(action)
    return response.created(db.public(row))


@endpoint(bp, "/proposed-actions/<action_id>/issues", ["GET"], ISSUE_READ_ROLES)
def list_action_issues(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(
        of_action("issues", action_id), "resource_area", "status", "scoping_period_id"
    )


@endpoint(bp, "/issues/<issue_id>", ["GET"], ISSUE_READ_ROLES)
def get_issue(issue_id):
    issue = path_row("issues", issue_id, "issue")
    return response.ok(db.public(issue))


@endpoint(bp, "/issues", ["GET"], ISSUE_READ_ROLES)
def list_issues():
    return list_response(
        db.rows("issues"), "action_id", "scoping_period_id", "status", "resource_area"
    )
