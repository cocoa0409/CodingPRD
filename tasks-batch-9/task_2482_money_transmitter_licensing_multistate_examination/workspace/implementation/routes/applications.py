"""Licence applications: filing, the deficiency loop and issuance (§3.3)."""

from flask import Blueprint

import calculations as calc
from db import base_row, db, days, now, serialize, set_dt, touch
from errors import ApiError
from middleware import authorize, regulator_matches, require_scope
from response import created, ok
from routes.common import (
    filter_rows,
    get_application,
    get_jurisdiction,
    get_licensee,
    paginate,
)
from services import engine
from validators import get_body, pagination, q_enum, q_str, v_enum, v_int, v_str

bp = Blueprint("applications", __name__)

APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "DEFICIENT",
    "APPROVED",
    "DENIED",
    "WITHDRAWN",
)
LIVE_APPLICATION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "DEFICIENT", "APPROVED")
REVIEW_ACTIONS = ("START_REVIEW", "ISSUE_DEFICIENCY", "APPROVE", "DENY", "WITHDRAW")


@bp.post("/license-applications")
def create_application():
    authorize("LicensingManager")
    body = get_body()
    licensee_id = v_str(body, "licensee_id")
    jurisdiction_id = v_str(body, "jurisdiction_id")
    license_class = v_enum(body, "license_class", calc.LICENSE_CLASSES)
    volume = v_int(body, "projected_annual_volume_cents", minimum=0)
    narrative = v_str(body, "new_product_narrative")

    get_licensee(licensee_id)
    get_jurisdiction(jurisdiction_id)

    row = base_row()
    row.update(
        {
            "licensee_id": licensee_id,
            "jurisdiction_id": jurisdiction_id,
            "license_class": license_class,
            "projected_annual_volume_cents": volume,
            "new_product_narrative": narrative,
            "status": "DRAFT",
            "required_bond_cents": 0,
            "required_net_worth_cents": 0,
            "deficiency_round_count": 0,
            "deficiency_deadline_at": None,
            "submitted_at": None,
            "decision_at": None,
            "denial_reason": None,
        }
    )
    db.applications[row["id"]] = row
    return created(serialize(row))


@bp.get("/license-applications/<application_id>")
def get_one(application_id):
    authorize("LicensingManager", "StateRegulator")
    return ok(serialize(get_application(application_id)))


@bp.get("/license-applications")
def list_all():
    authorize("LicensingManager", "StateRegulator")
    limit, offset = pagination()
    licensee_id = q_str("licensee_id")
    jurisdiction_id = q_str("jurisdiction_id")
    status = q_enum("status", APPLICATION_STATUSES)
    rows = filter_rows(
        db.applications.values(),
        {"licensee_id": licensee_id, "jurisdiction_id": jurisdiction_id, "status": status},
    )
    return paginate(rows, limit, offset)


@bp.post("/license-applications/<application_id>/submit")
def submit(application_id):
    authorize("LicensingManager")
    get_body()
    app_row = get_application(application_id)
    licensee = get_licensee(app_row["licensee_id"])
    jurisdiction = get_jurisdiction(app_row["jurisdiction_id"])

    if app_row["status"] != "DRAFT":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE",
            "Application %s is %s, not DRAFT" % (application_id, app_row["status"]),
        )
    if licensee["control_chain_status"] == "BLOCKED":
        raise ApiError("ERR_CONTROL_CHAIN_BLOCKED", "The licensee's control chain is blocked")
    if licensee["coverage_posture"] == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN", "The licensee's coverage posture is FROZEN")
    for other in db.applications.values():
        if (
            other["id"] != app_row["id"]
            and other["licensee_id"] == app_row["licensee_id"]
            and other["jurisdiction_id"] == app_row["jurisdiction_id"]
            and other["status"] in LIVE_APPLICATION_STATUSES
        ):
            raise ApiError(
                "ERR_DUPLICATE_LICENSE_APPLICATION",
                "A live application already exists for this licensee and jurisdiction",
            )

    app_row["status"] = "SUBMITTED"
    set_dt(app_row, "submitted_at", now())
    app_row["required_net_worth_cents"] = jurisdiction["min_net_worth_cents"]
    app_row["required_bond_cents"] = calc.surety_bond_requirement(
        jurisdiction,
        app_row["projected_annual_volume_cents"],
        app_row["license_class"],
        0,
    )
    touch(app_row)
    return ok(serialize(app_row))


@bp.post("/license-applications/<application_id>/resubmit")
def resubmit(application_id):
    authorize("LicensingManager")
    body = get_body()
    volume = v_int(body, "projected_annual_volume_cents", minimum=0)
    v_str(body, "remediation_note", required=False, allow_empty=True, default=None)

    app_row = get_application(application_id)
    get_licensee(app_row["licensee_id"])
    jurisdiction = get_jurisdiction(app_row["jurisdiction_id"])

    if app_row["status"] != "DEFICIENT":
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE",
            "Application %s is %s, not DEFICIENT" % (application_id, app_row["status"]),
        )
    deadline = app_row.get("_deficiency_deadline_at")
    if deadline is not None and now() > deadline:
        raise ApiError(
            "ERR_DEFICIENCY_DEADLINE_PASSED", "The deficiency response deadline has passed"
        )

    app_row["projected_annual_volume_cents"] = volume
    app_row["status"] = "UNDER_REVIEW"
    set_dt(app_row, "deficiency_deadline_at", None)
    app_row["required_bond_cents"] = calc.surety_bond_requirement(
        jurisdiction, volume, app_row["license_class"], 0
    )
    touch(app_row)
    return ok(serialize(app_row))


def _mint_license(app_row, jurisdiction):
    row = base_row()
    row.update(
        {
            "licensee_id": app_row["licensee_id"],
            "jurisdiction_id": app_row["jurisdiction_id"],
            "application_id": app_row["id"],
            "license_number": engine.mint_license_number(jurisdiction),
            "license_class": app_row["license_class"],
            "license_status": "PENDING_BOND",
            "reporting_status": "CURRENT",
            "expansion_gate": "BLOCKED",
            "annual_volume_cents": 0,
            "outstanding_obligations_cents": 0,
            "active_delegate_count": 0,
            "bond_requirement_cents": app_row["required_bond_cents"],
            "bond_posted_cents": 0,
            "bond_status": "NONE",
            "bond_issuer": None,
            "bond_cancellation_effective_date": None,
            "renewal_year": None,
            "renewal_status": "NOT_RENEWED",
            "renewal_total_fee_cents": 0,
            "exam_findings_open": False,
            "authorized_at": None,
        }
    )
    db.state_licenses[row["id"]] = row
    return row


@bp.post("/license-applications/<application_id>/review-actions")
def review_action(application_id):
    user_id, _ = authorize("StateRegulator")
    body = get_body()
    action = v_enum(body, "action", REVIEW_ACTIONS)
    v_str(body, "note", required=False, allow_empty=True, default=None)

    app_row = get_application(application_id)
    licensee = get_licensee(app_row["licensee_id"])
    jurisdiction = get_jurisdiction(app_row["jurisdiction_id"])
    require_scope(
        regulator_matches(user_id, app_row["jurisdiction_id"]),
        user_id,
        "application %s" % application_id,
    )

    required = {
        "START_REVIEW": ("SUBMITTED",),
        "ISSUE_DEFICIENCY": ("UNDER_REVIEW",),
        "APPROVE": ("UNDER_REVIEW",),
        "DENY": ("UNDER_REVIEW",),
        "WITHDRAW": ("DEFICIENT",),
    }[action]
    if app_row["status"] not in required:
        raise ApiError(
            "ERR_APPLICATION_INVALID_STATE",
            "Action %s is not admissible from %s" % (action, app_row["status"]),
        )

    if action == "START_REVIEW":
        app_row["status"] = "UNDER_REVIEW"
        touch(app_row)
    elif action == "ISSUE_DEFICIENCY":
        # The action always increments the counter; the branch is chosen by how
        # many rounds had already been spent before this action.
        rounds_already_spent = app_row["deficiency_round_count"]
        app_row["deficiency_round_count"] = rounds_already_spent + 1
        if rounds_already_spent >= 3:
            app_row["status"] = "DENIED"
            app_row["denial_reason"] = "EXCESSIVE_DEFICIENCY_ROUNDS"
            set_dt(app_row, "decision_at", now())
            set_dt(app_row, "deficiency_deadline_at", None)
        else:
            app_row["status"] = "DEFICIENT"
            set_dt(app_row, "deficiency_deadline_at", now() + days(30))
        touch(app_row)
    elif action == "DENY":
        app_row["status"] = "DENIED"
        app_row["denial_reason"] = "REGULATOR_DENIAL"
        set_dt(app_row, "decision_at", now())
        touch(app_row)
    elif action == "WITHDRAW":
        app_row["status"] = "WITHDRAWN"
        set_dt(app_row, "deficiency_deadline_at", None)
        set_dt(app_row, "decision_at", now())
        touch(app_row)
    else:  # APPROVE
        pending = [
            c
            for c in engine.control_persons_of(licensee["id"])
            if c["status"] != "REMOVED"
            and c["control_determination"] == "CONTROL"
            and c["background_check_status"] != "CLEARED"
        ]
        if pending:
            raise ApiError(
                "ERR_BACKGROUND_CHECK_INCOMPLETE",
                "A control person of this licensee has an incomplete background check",
            )
        if licensee["control_chain_status"] == "BLOCKED":
            raise ApiError("ERR_CONTROL_CHAIN_BLOCKED", "The licensee's control chain is blocked")
        if licensee["coverage_posture"] == "FROZEN":
            raise ApiError("ERR_POSTURE_FROZEN", "The licensee's coverage posture is FROZEN")
        if licensee["reported_tangible_net_worth_cents"] < app_row["required_net_worth_cents"]:
            raise ApiError(
                "ERR_NET_WORTH_INSUFFICIENT",
                "Reported tangible net worth is below the pinned requirement",
            )
        app_row["status"] = "APPROVED"
        set_dt(app_row, "decision_at", now())
        touch(app_row)
        _mint_license(app_row, jurisdiction)

    return ok(serialize(app_row))
