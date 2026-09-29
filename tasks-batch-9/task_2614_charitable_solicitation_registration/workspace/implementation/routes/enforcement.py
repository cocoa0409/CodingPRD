"""Enforcement, remediation and the compliance sweep (PRD 3.9)."""
from flask import Blueprint, request

import clock
import response
import validate
from dates import parse_iso
from auth import endpoint
from db import db, public, sorted_rows, touch_once
from errors import ApiError
from services import calc
from services.cascades import (apply_cure, apply_escalate, apply_vacate,
                              issue_enforcement_action, run_sweep)
from services.derive import recompute_organization

bp = Blueprint("enforcement", __name__)

ACTION_TYPES = ("DELINQUENCY_NOTICE", "PENALTY_ASSESSMENT", "CEASE_SOLICITATION_ORDER")
CEASE_ELIGIBLE_FILING_STATUSES = ("DELINQUENT", "CEASED")


@bp.post("/enforcement-actions")
@endpoint(["StateRegulator"])
def create_enforcement_action():
    """state_code is copied from the linked filing rather than supplied."""
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    registration_id = validate.req_string(body, "registration_id")
    action_type = validate.req_enum(body, "action_type", ACTION_TYPES)
    penalty_override = validate.opt_int(body, "penalty_cents_override", None, minimum=0)

    organization = validate.find_organization(organization_id)
    registration = validate.find_registration(registration_id)

    if penalty_override is not None:
        penalty_cents = penalty_override
    else:
        profile = validate.find_state_profile(registration["state_code"])
        penalty_cents = calc.late_penalty_accrual(registration, profile, clock.now())

    action = issue_enforcement_action(organization, registration, action_type, penalty_cents)
    # Issuance raises penalty_outstanding_cents by exactly penalty_cents.
    recompute_organization(organization)
    return response.created(public(action))


@bp.post("/enforcement-actions/<action_id>/remediate")
@endpoint(["ComplianceOfficer"])
def remediate_enforcement_action(action_id):
    """An escalated cease-solicitation order can be remediated repeatedly."""
    body = validate.json_body()
    remediation_note = validate.req_string(body, "remediation_note", min_len=0,
                                          allow_blank=True)

    action = validate.find_enforcement_action(action_id)

    # Ladder rung 10.
    if action["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE")
    # Ladder rung 25 -- the cure window must still be open.
    if clock.now() > parse_iso(action["cure_deadline"]):
        raise ApiError("ERR_CURE_WINDOW_EXPIRED")

    registration = db.state_registrations[action["registration_id"]]
    profile = db.state_profiles[registration["state_code"]]

    action["status"] = "REMEDIATION_SUBMITTED"
    action["remediation_note"] = remediation_note
    action["settlement_total_cents"] = calc.remediation_settlement_total(action, profile)
    # penalty_outstanding_cents is deliberately untouched: a submitted remediation
    # is still an outstanding matter.
    touch_once(action, "enforcement_action")
    return response.ok(public(action))


@bp.post("/enforcement-actions/<action_id>/decide")
@endpoint(["StateRegulator"])
def decide_enforcement_action(action_id):
    body = validate.json_body()
    decision = validate.req_enum(body, "decision", ("CURE", "ESCALATE"))

    action = validate.find_enforcement_action(action_id)
    registration = db.state_registrations[action["registration_id"]]

    if decision == "CURE":
        # Ladder rung 10 -- CURE is available only from REMEDIATION_SUBMITTED.
        if action["status"] != "REMEDIATION_SUBMITTED":
            raise ApiError("ERR_INVALID_ENFORCEMENT_STATE")
        # There is nothing to cure before a settlement has been computed.
        if action["settlement_total_cents"] <= 0:
            raise ApiError(
                "ERR_INVALID_ENFORCEMENT_STATE",
                "settlement_total_cents must be greater than 0 to cure an action.",
            )
        apply_cure(action)
    else:
        # Ladder rung 10 -- ESCALATE is available from REMEDIATION_SUBMITTED and OPEN.
        if action["status"] not in ("REMEDIATION_SUBMITTED", "OPEN"):
            raise ApiError("ERR_INVALID_ENFORCEMENT_STATE")
        if registration["status"] not in CEASE_ELIGIBLE_FILING_STATUSES:
            raise ApiError("ERR_INVALID_REGISTRATION_STATE")
        # Ladder rung 25 -- escalating an OPEN action needs a closed cure window.
        if action["status"] == "OPEN" and not clock.now() > parse_iso(action["cure_deadline"]):
            raise ApiError("ERR_CURE_WINDOW_EXPIRED")
        apply_escalate(action)

    return response.ok(public(action))


@bp.post("/enforcement-actions/<action_id>/vacate")
@endpoint(["StateRegulator"])
def vacate_enforcement_action(action_id):
    """The compensating action for issuance under penalty_ledger_conservation."""
    body = validate.json_body()
    validate.req_string(body, "vacate_reason")

    action = validate.find_enforcement_action(action_id)

    # Ladder rung 10 -- CURED and VACATED are terminal.
    if action["status"] not in ("OPEN", "REMEDIATION_SUBMITTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE")

    apply_vacate(action)
    return response.ok(public(action))


@bp.get("/enforcement-actions")
@endpoint(["ComplianceOfficer", "StateRegulator", "SystemAdmin"])
def list_enforcement_actions():
    rows = list(db.enforcement_actions.values())
    for field in ("organization_id", "registration_id", "status", "action_type", "state_code"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/enforcement-actions/<action_id>")
@endpoint(["ComplianceOfficer", "StateRegulator", "SystemAdmin"])
def read_enforcement_action(action_id):
    return response.ok(public(validate.find_enforcement_action(action_id)))


@bp.post("/compliance-sweeps")
@endpoint(["SystemAdmin", "StateRegulator"])
def create_compliance_sweep():
    """Two independent passes at the current logical clock."""
    body = validate.json_body()
    state_code = validate.opt_string(body, "state_code", default=None, allow_blank=False)
    if state_code is not None:
        validate.find_state_profile(state_code)
    return response.ok(run_sweep(state_code))
