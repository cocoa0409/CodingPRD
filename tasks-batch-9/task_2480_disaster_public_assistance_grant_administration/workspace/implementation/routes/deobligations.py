"""Deobligation endpoints: determination and finalization."""
from datetime import timedelta

from flask import Blueprint

from db import format_instant, new_row, now, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.constants import APPEAL_WINDOW_DAYS, DEOBLIGATION_REASONS, LEDGER_PROJECT_STATUSES
from services.ledger import (
    applicant_of_project,
    cascade_applicant,
    recompute_project_deobligations,
)
from validate import body, v_enum, v_id, v_int

bp = Blueprint("deobligations", __name__)


@bp.route(PREFIX + "/deobligations", methods=["POST"])
def create_deobligation_row():
    actor = authenticate(("GrantsOfficer", "StateAuditor"))
    payload = body()

    project_id = v_id(payload, "project_id")
    reason = v_enum(payload, "reason", DEOBLIGATION_REASONS)
    amount_cents = v_int(payload, "amount_cents", minimum=1)
    expected_version = v_int(payload, "expected_project_version", minimum=0)

    project = require("projects", project_id)

    if project["version"] != expected_version:
        fail("ERR_STALE_PROJECT_VERSION",
             "expected_project_version %s does not match the current version %s"
             % (expected_version, project["version"]))

    if project["status"] not in LEDGER_PROJECT_STATUSES:
        fail("ERR_PROJECT_INVALID_STATE",
             "there is no obligation to reduce in status %s" % project["status"])

    remaining = (project["federal_share_obligated_cents"]
                 - project["deobligated_cents"]
                 - project["pending_deobligation_cents"])
    if amount_cents > remaining:
        fail("ERR_DEOBLIGATION_EXCEEDS_OBLIGATION",
             "amount_cents exceeds the remaining reducible obligation")

    row = new_row("deobligations", {
        "project_id": project_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "status": "PROPOSED",
        "determined_by_user_id": actor.user_id,
        "finalized_at": None,
        "appeal_deadline_at": None,
        "reversed_cents": 0,
    })

    recompute_project_deobligations(project)
    touch(project)
    applicant = applicant_of_project(project)
    cascade_applicant(applicant)
    if applicant is not None:
        touch(applicant)
    return respond(row, 201)


@bp.route(PREFIX + "/deobligations", methods=["GET"])
def list_deobligations():
    authenticate(ALL_ROLES)
    return render_list("deobligations", {
        "project_id": "project_id",
        "status": "status",
        "reason": "reason",
    })


@bp.route(PREFIX + "/deobligations/<deobligation_id>", methods=["GET"])
def get_deobligation(deobligation_id):
    actor = authenticate(ALL_ROLES)
    row = find("deobligations", deobligation_id)
    if row is not None:
        project = find("projects", row["project_id"])
        if project is not None:
            check_scope(actor, project["applicant_id"])
    row = require("deobligations", deobligation_id)
    return respond(row)


@bp.route(PREFIX + "/deobligations/<deobligation_id>/finalize", methods=["POST"])
def finalize_deobligation(deobligation_id):
    authenticate(("GrantsOfficer",))
    row = require("deobligations", deobligation_id)

    if row["status"] != "PROPOSED":
        fail("ERR_DEOBLIGATION_INVALID_STATE",
             "only a PROPOSED determination may be finalized")

    project = find("projects", row["project_id"])
    if project is None or project["status"] not in LEDGER_PROJECT_STATUSES:
        fail("ERR_PROJECT_INVALID_STATE",
             "finalization requires an obligated project")

    clock = now()
    setf(row, "status", "FINAL")
    setf(row, "finalized_at", format_instant(clock))
    setf(row, "appeal_deadline_at",
         format_instant(clock + timedelta(days=APPEAL_WINDOW_DAYS)))
    touch(row)

    recompute_project_deobligations(project)
    touch(project)
    applicant = applicant_of_project(project)
    disaster = cascade_applicant(applicant)
    if applicant is not None:
        touch(applicant)
    if disaster is not None:
        touch(disaster)
    return respond(row)
