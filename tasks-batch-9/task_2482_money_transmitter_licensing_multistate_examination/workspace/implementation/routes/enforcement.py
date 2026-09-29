"""Enforcement, remediation and revocation (§3.9)."""

from flask import Blueprint

from db import base_row, days, db, now, serialize, set_dt, set_input_dt, touch
from errors import ApiError
from middleware import authorize, require_scope
from response import created, ok
from routes.common import (
    filter_rows,
    get_enforcement,
    get_exam,
    get_jurisdiction,
    get_licensee,
    get_license,
    paginate,
)
from routes.state_licenses import _require_not_terminal
from services import engine
from validators import get_body, pagination, q_enum, q_str, v_bool, v_dt, v_enum, v_int, v_str

bp = Blueprint("enforcement", __name__)

ENFORCEMENT_STATUSES = ("ISSUED", "CONSENT_ORDER", "CONTESTED", "RESOLVED", "REVOCATION")
BASES = (
    "PERMISSIBLE_INVESTMENT_SHORTFALL",
    "BOND_LAPSE",
    "DELINQUENT_REPORTING",
    "UNAUTHORIZED_DELEGATE",
    "EXAM_FINDING",
)
RESPONSE_WINDOW_DAYS = 20


def _invalid_state(detail):
    raise ApiError("ERR_ENFORCEMENT_INVALID_STATE", detail)


@bp.post("/enforcement-actions")
def create_action():
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    state_license_id = v_str(body, "state_license_id")
    jurisdiction_id = v_str(body, "jurisdiction_id")
    basis = v_enum(body, "basis", BASES)
    penalty = v_int(body, "penalty_cents", minimum=0)
    raw_deadline, deadline = v_dt(body, "remediation_deadline_at", required=True)
    exam_id = v_str(body, "originating_exam_id", required=False, default=None)

    get_jurisdiction(jurisdiction_id)
    license_row = get_license(state_license_id)
    if exam_id is not None:
        get_exam(exam_id)

    require_scope(
        user_id == jurisdiction_id, user_id, "enforcement for jurisdiction %s" % jurisdiction_id
    )
    _require_not_terminal(license_row)

    if jurisdiction_id != license_row["jurisdiction_id"]:
        raise ApiError(
            "ERR_JURISDICTION_MISMATCH",
            "Jurisdiction %s does not licence %s" % (jurisdiction_id, state_license_id),
        )

    row = base_row()
    row.update(
        {
            "state_license_id": state_license_id,
            "jurisdiction_id": jurisdiction_id,
            "originating_exam_id": exam_id,
            "basis": basis,
            "penalty_cents": penalty,
            "status": "ISSUED",
            "response_at": None,
            "remediation_plan_narrative": None,
            "remediation_accepted": False,
            "resolved_at": None,
        }
    )
    set_input_dt(row, "remediation_deadline_at", raw_deadline, deadline)
    set_dt(row, "issued_at", now())
    db.enforcements[row["id"]] = row
    return created(serialize(row))


@bp.get("/enforcement-actions/<action_id>")
def get_one(action_id):
    authorize("StateRegulator", "LicensingManager")
    return ok(serialize(get_enforcement(action_id)))


@bp.get("/enforcement-actions")
def list_all():
    authorize("StateRegulator", "LicensingManager")
    limit, offset = pagination()
    filters = {
        "state_license_id": q_str("state_license_id"),
        "jurisdiction_id": q_str("jurisdiction_id"),
        "originating_exam_id": q_str("originating_exam_id"),
        "status": q_enum("status", ENFORCEMENT_STATUSES),
    }
    return paginate(filter_rows(db.enforcements.values(), filters), limit, offset)


@bp.post("/enforcement-actions/<action_id>/responses")
def respond(action_id):
    authorize("LicensingManager")
    body = get_body()
    response = v_enum(body, "response", ("CONSENT_ORDER", "CONTEST"))
    narrative = v_str(
        body, "remediation_plan_narrative", required=False, allow_empty=True, default=None
    )

    row = get_enforcement(action_id)
    license_row = get_license(row["state_license_id"])
    licensee = get_licensee(license_row["licensee_id"])

    if row["status"] != "ISSUED":
        _invalid_state(
            "Enforcement action %s is %s, not ISSUED" % (action_id, row["status"])
        )
    if response == "CONSENT_ORDER" and not (narrative or "").strip():
        raise ApiError(
            "ERR_REMEDIATION_PLAN_REQUIRED",
            "A consent order response must carry a remediation plan narrative",
        )
    if now() > row["_issued_at"] + days(RESPONSE_WINDOW_DAYS):
        raise ApiError(
            "ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED",
            "The twenty-day response window for action %s has closed" % action_id,
        )

    set_dt(row, "response_at", now())
    if response == "CONSENT_ORDER":
        row["status"] = "CONSENT_ORDER"
        row["remediation_plan_narrative"] = narrative
        touch(row)
        if license_row["license_status"] == "ACTIVE":
            engine.suspend_license_cascade(license_row, licensee)
    else:
        row["status"] = "CONTESTED"
        touch(row)
    return ok(serialize(row))


@bp.post("/enforcement-actions/<action_id>/resolutions")
def resolve(action_id):
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    outcome = v_enum(body, "outcome", ("RESOLVED", "REVOCATION"))
    accepted = v_bool(body, "remediation_accepted", required=False, default=False)

    row = get_enforcement(action_id)
    license_row = get_license(row["state_license_id"])
    licensee = get_licensee(license_row["licensee_id"])
    require_scope(
        user_id == row["jurisdiction_id"], user_id, "enforcement action %s" % action_id
    )

    if row["status"] not in ("CONSENT_ORDER", "CONTESTED"):
        _invalid_state(
            "Enforcement action %s is %s and cannot be resolved" % (action_id, row["status"])
        )
    from_consent = row["status"] == "CONSENT_ORDER"
    if outcome == "RESOLVED" and from_consent and now() > row["_remediation_deadline_at"]:
        raise ApiError(
            "ERR_REMEDIATION_DEADLINE_PASSED",
            "The remediation deadline for action %s has passed" % action_id,
        )

    set_dt(row, "resolved_at", now())
    if outcome == "RESOLVED":
        row["status"] = "RESOLVED"
        row["remediation_accepted"] = bool(accepted) if from_consent else False
        touch(row)
        if from_consent and accepted:
            if (
                license_row["license_status"] == "SUSPENDED"
                and license_row["bond_status"] == "POSTED"
            ):
                license_row["license_status"] = "ACTIVE"
                license_row["exam_findings_open"] = False
                touch(license_row)
                licensee["active_license_count"] += 1
                touch(licensee)
                engine.refresh_gate(license_row, licensee)
    else:
        row["status"] = "REVOCATION"
        touch(row)
        engine.revoke_license_cascade(license_row, licensee)
    return ok(serialize(row))
