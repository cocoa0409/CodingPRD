"""PRD 3.7 -- withdrawal, grants, the equity waiver and indicator reports."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import envelope
import lookup
import serialize
import store
import validate
from auth import (ROLE_EQUITY_OFFICER, ROLE_PROJECT_SPONSOR,
                  ROLE_REGIONAL_ADMINISTRATOR, guard, require_owned_jurisdiction)
from core import clock
from errors import fail

bp = Blueprint("project_ops", __name__)

GRANT_FUNDERS = ("BRIC", "HMGP", "STATE_RESILIENCE")
WITHDRAWABLE = ("PROGRAMMED", "GRANT_SUBMITTED")


@bp.post("/resilience/projects/<project_id>/withdraw")
@guard(ROLE_PROJECT_SPONSOR)
def withdraw_project(project_id):
    project = lookup.need("project", project_id)
    require_owned_jurisdiction(project["jurisdiction_id"], roles=(ROLE_PROJECT_SPONSOR,))
    if project["program_status"] not in WITHDRAWABLE:
        fail(
            "ERR_PROJECT_NOT_PROGRAMMED",
            "Only a PROGRAMMED or GRANT_SUBMITTED project may be withdrawn.",
        )

    # Hop 1: the project leaves the committed set; capital_program_id and any grant
    # fields are deliberately retained for audit.
    program = store.programs.get(project["capital_program_id"])
    project["program_status"] = "WITHDRAWN"
    project["allocated_cents"] = 0

    # Hops 2 to 4: the ledger is recomputed from scratch over the surviving set,
    # the posture is re-derived and the grant hold is cleared on the siblings.
    if program is not None:
        cascades.recompute_program_ledger(program, skip_touch=(project["id"],))
        store.touch(program)
    store.touch(project)
    return envelope.ok(serialize.project(project))


@bp.post("/resilience/projects/<project_id>/grant-submission")
@guard(ROLE_PROJECT_SPONSOR)
def submit_grant(project_id):
    project = lookup.need("project", project_id)
    require_owned_jurisdiction(project["jurisdiction_id"], roles=(ROLE_PROJECT_SPONSOR,))
    body = validate.json_body()
    funder = validate.enum_field(body, "grant_funder", GRANT_FUNDERS, required=True)

    if project["program_status"] != "PROGRAMMED":
        fail("ERR_PROJECT_NOT_PROGRAMMED", "The project is not PROGRAMMED.")
    prerequisite_id = project["prerequisite_project_id"]
    if prerequisite_id is not None:
        prerequisite = store.projects.get(prerequisite_id)
        if prerequisite is None or prerequisite["program_status"] != "AWARDED":
            fail("ERR_PREREQUISITE_NOT_AWARDED", "The prerequisite project is not AWARDED.")
    analysis = lookup.certified_analysis(project["id"])
    if (
        analysis is None
        or analysis["bcr"] is None
        or analysis["bcr"] < Decimal("1.0000")
        or not analysis["grant_eligible"]
    ):
        fail("ERR_BCR_BELOW_FLOOR", "The project's certified analysis is not grant-eligible.")
    if project["grant_hold_flag"]:
        fail("ERR_GRANT_ON_HOLD", "The project is on grant hold.")

    project["program_status"] = "GRANT_SUBMITTED"
    project["grant_funder"] = funder
    project["grant_submitted_at"] = clock.now()
    store.touch(project)
    return envelope.ok(serialize.project(project))


@bp.post("/resilience/projects/<project_id>/grant-award")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def award_grant(project_id):
    project = lookup.need("project", project_id)
    if project["program_status"] != "GRANT_SUBMITTED":
        fail("ERR_PROJECT_NOT_PROGRAMMED", "The project is not GRANT_SUBMITTED.")
    if project["analysis_status"] != "BCA_CERTIFIED":
        fail("ERR_BCA_NOT_CERTIFIED", "The project's analysis is no longer BCA_CERTIFIED.")

    project["program_status"] = "AWARDED"
    project["awarded_at"] = clock.now()
    store.touch(project)
    return envelope.ok(serialize.project(project))


@bp.post("/resilience/projects/<project_id>/equity-waiver")
@guard(ROLE_EQUITY_OFFICER)
def grant_equity_waiver(project_id):
    project = lookup.need("project", project_id)
    body = validate.json_body()
    rationale = validate.string_field(body, "waiver_rationale", required=True, min_len=1)

    project["equity_waiver_granted"] = True
    project["waiver_rationale"] = rationale
    store.touch(project)
    return envelope.ok(serialize.project(project))


@bp.post("/resilience/projects/<project_id>/indicator-reports")
@guard(ROLE_PROJECT_SPONSOR)
def file_indicator_report(project_id):
    project = lookup.need("project", project_id)
    require_owned_jurisdiction(project["jurisdiction_id"], roles=(ROLE_PROJECT_SPONSOR,))
    body = validate.json_body()
    reported_value = validate.dec_field(body, "reported_value", required=True)
    period_label = validate.string_field(body, "period_label", required=True, min_len=1)

    if project["program_status"] != "AWARDED":
        fail("ERR_PROJECT_NOT_PROGRAMMED", "Indicator reports require an AWARDED project.")
    if project["indicator_code"] is None or project["indicator_target_value"] is None:
        fail("ERR_INDICATOR_NOT_DEFINED", "The project has no indicator definition.")

    attainment = calc.indicator_attainment(reported_value, project["indicator_target_value"])
    project["indicator_latest_value"] = reported_value
    project["latest_period_label"] = period_label
    project["indicator_attainment_pct"] = attainment
    project["reported_period_count"] = int(project["reported_period_count"]) + 1
    project["implementation_status"] = calc.implementation_status(attainment)
    store.touch(project)
    return envelope.ok(serialize.project(project))
