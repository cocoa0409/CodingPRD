"""Delegate authorizations: creation, activation and termination (§3.6)."""

from flask import Blueprint

import calculations as calc
from db import base_row, db, get_dt, now, serialize, set_dt, set_input_dt, touch
from errors import ApiError
from middleware import authorize, require_scope
from response import created, ok
from routes.common import (
    filter_rows,
    get_authorization,
    get_delegate,
    get_licensee,
    get_license,
    paginate,
)
from services import engine
from validators import bad, get_body, pagination, q_enum, q_str, v_dt, v_int, v_str

bp = Blueprint("authorizations", __name__)

AUTHORIZATION_STATUSES = (
    "PENDING_OVERSIGHT",
    "ACTIVE",
    "SUSPENDED_BY_POSTURE",
    "SUSPENDED",
    "TERMINATED",
)


@bp.post("/delegate-authorizations")
def create_authorization():
    authorize("LicensingManager")
    body = get_body()
    delegate_id = v_str(body, "delegate_id")
    state_license_id = v_str(body, "state_license_id")
    raw_effective, effective = v_dt(body, "effective_date", required=True)
    raw_expiry, expiry = v_dt(body, "expiry_date", required=True)
    cap = v_int(body, "monthly_volume_cap_cents", minimum=1)
    if expiry < effective:
        bad("expiry_date must not precede effective_date")

    license_row = get_license(state_license_id)
    delegate = get_delegate(delegate_id)
    licensee = get_licensee(license_row["licensee_id"])

    if license_row["license_status"] != "ACTIVE":
        raise ApiError(
            "ERR_LICENSE_NOT_ACTIVE",
            "Licence %s is %s, not ACTIVE" % (state_license_id, license_row["license_status"]),
        )
    if licensee["coverage_posture"] == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN", "The licensee's coverage posture is FROZEN")
    if delegate["licensee_id"] != license_row["licensee_id"]:
        raise ApiError(
            "ERR_CROSS_LICENSEE_REFERENCE",
            "The delegate and the licence belong to different licensees",
        )

    for other in engine.authorizations_of_delegate(delegate_id):
        if other["status"] == "TERMINATED":
            continue
        other_license = db.state_licenses.get(other["state_license_id"])
        if other_license is None:
            continue
        if other_license["jurisdiction_id"] != license_row["jurisdiction_id"]:
            continue
        if effective <= get_dt(other, "expiry_date") and get_dt(other, "effective_date") <= expiry:
            raise ApiError(
                "ERR_DELEGATE_PERIOD_OVERLAP",
                "The delegate already holds an overlapping authorization in this jurisdiction",
            )

    row = base_row()
    row.update(
        {
            "delegate_id": delegate_id,
            "state_license_id": state_license_id,
            "monthly_volume_cap_cents": cap,
            "status": "PENDING_OVERSIGHT",
            "activated_at": None,
            "oversight_score_at_activation": None,
        }
    )
    set_input_dt(row, "effective_date", raw_effective, effective)
    set_input_dt(row, "expiry_date", raw_expiry, expiry)
    db.authorizations[row["id"]] = row
    return created(serialize(row))


@bp.get("/delegate-authorizations/<authorization_id>")
def get_one(authorization_id):
    user_id, role = authorize(
        "LicensingManager", "ComplianceOfficer", "DelegateOperator", "StateRegulator"
    )
    row = get_authorization(authorization_id)
    if role == "DelegateOperator":
        require_scope(
            user_id == row["delegate_id"], user_id, "authorization %s" % authorization_id
        )
    return ok(serialize(row))


@bp.get("/delegate-authorizations")
def list_all():
    user_id, role = authorize(
        "LicensingManager", "ComplianceOfficer", "DelegateOperator", "StateRegulator"
    )
    limit, offset = pagination()
    filters = {
        "delegate_id": q_str("delegate_id"),
        "state_license_id": q_str("state_license_id"),
        "status": q_enum("status", AUTHORIZATION_STATUSES),
    }
    rows = filter_rows(db.authorizations.values(), filters)
    if role == "DelegateOperator":
        rows = [r for r in rows if r["delegate_id"] == user_id]
    return paginate(rows, limit, offset)


@bp.post("/delegate-authorizations/<authorization_id>/activate")
def activate(authorization_id):
    authorize("LicensingManager")
    get_body()
    row = get_authorization(authorization_id)
    license_row = get_license(row["state_license_id"])
    delegate = get_delegate(row["delegate_id"])
    licensee = get_licensee(license_row["licensee_id"])

    if license_row["license_status"] != "ACTIVE":
        raise ApiError(
            "ERR_LICENSE_NOT_ACTIVE",
            "Licence %s is %s, not ACTIVE"
            % (license_row["id"], license_row["license_status"]),
        )
    if row["status"] not in ("PENDING_OVERSIGHT", "SUSPENDED_BY_POSTURE"):
        raise ApiError(
            "ERR_AUTHORIZATION_INVALID_STATE",
            "Authorization %s is %s and cannot be activated" % (authorization_id, row["status"]),
        )
    if license_row["expansion_gate"] != "OPEN":
        raise ApiError(
            "ERR_EXPANSION_GATE_BLOCKED", "The licence's expansion gate is BLOCKED"
        )
    score = delegate["oversight_score"]
    if score is None or score < calc.OVERSIGHT_MIN_SCORE:
        raise ApiError(
            "ERR_OVERSIGHT_SCORE_INSUFFICIENT",
            "The delegate's oversight score is below %d" % calc.OVERSIGHT_MIN_SCORE,
        )
    if delegate["licensee_id"] != license_row["licensee_id"]:
        raise ApiError(
            "ERR_CROSS_LICENSEE_REFERENCE",
            "The delegate and the licence belong to different licensees",
        )

    row["status"] = "ACTIVE"
    set_dt(row, "activated_at", now())
    row["oversight_score_at_activation"] = score
    touch(row)

    license_row["active_delegate_count"] += 1
    engine.recompute_bond_requirement(license_row)
    touch(license_row)

    delegate["authorized_state_count"] += 1
    if delegate["status"] in ("ONBOARDING", "SUSPENDED"):
        delegate["status"] = "ACTIVE"
        delegate["oversight_hold"] = False
    touch(delegate)
    return ok(serialize(row))


@bp.post("/delegate-authorizations/<authorization_id>/terminate")
def terminate(authorization_id):
    authorize("LicensingManager")
    body = get_body()
    v_str(body, "reason", required=False, allow_empty=True, default=None)

    row = get_authorization(authorization_id)
    license_row = get_license(row["state_license_id"])
    delegate = get_delegate(row["delegate_id"])

    if row["status"] == "TERMINATED":
        raise ApiError(
            "ERR_AUTHORIZATION_INVALID_STATE",
            "Authorization %s is already TERMINATED" % authorization_id,
        )

    was_active = row["status"] == "ACTIVE"
    row["status"] = "TERMINATED"
    touch(row)

    if was_active:
        license_row["active_delegate_count"] = max(0, license_row["active_delegate_count"] - 1)
        engine.recompute_bond_requirement(license_row)
        touch(license_row)
        delegate["authorized_state_count"] = max(0, delegate["authorized_state_count"] - 1)
        touch(delegate)
        if not engine.delegate_has_live_authorization(delegate["id"]):
            delegate["status"] = "TERMINATED"
    return ok(serialize(row))
