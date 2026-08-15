"""Regulatory action endpoints (PRD 3.7): report, confirm (maker-checker,
probation spacing, disciplinary cascade, fine allocation), dismiss."""

from datetime import timedelta

from flask import Blueprint

from core import calc, cascade, constants as K
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import (
    authorize, producer_scope, req_dt, req_enum, req_str,
    require_exactly_one_subject, resolve, resolve_subject_refs, subject_ids,
)
from core.serialize import regulatory_action as serialize_action
from core.store import db, new_row, bump

bp = Blueprint("regulatory_actions", __name__)

_READ_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin", "Producer")
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin")


@bp.route("/api/regulatory-actions", methods=["POST"])
def create_action():
    ctx = authorize("ComplianceOfficer")
    producer_id, agency_id = subject_ids(ctx)
    state_code = req_str(ctx.body, "state_code")
    action_type = req_enum(ctx.body, "action_type", K.ACTION_TYPES)
    effective_date = req_dt(ctx.body, "effective_date")
    fine_amount = ctx.body.get("fine_amount_cents")
    if action_type == "FINE":
        if (
            not isinstance(fine_amount, int)
            or isinstance(fine_amount, bool)
            or fine_amount <= 0
        ):
            fail(
                "ERR_INVALID_REQUEST",
                "fine_amount_cents is required for a FINE and must be greater than zero.",
            )
    else:
        # For any other action type the fine amount stays null.
        fine_amount = None
    resolve_subject_refs(ctx, producer_id, agency_id)
    require_exactly_one_subject(producer_id, agency_id)
    row = new_row("regulatory_actions", {
        "producer_id": producer_id,
        "agency_id": agency_id,
        "state_code": state_code,
        "action_type": action_type,
        "fine_amount_cents": fine_amount,
        "effective_date": effective_date,
        "status": "REPORTED",
        "created_by_user_id": ctx.user_id,
        "decided_by_user_id": None,
        "fine_allocations": [],
    })
    return object_response(serialize_action(row), 201)


@bp.route("/api/regulatory-actions/<regulatoryActionId>", methods=["GET"])
def get_action(regulatoryActionId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("regulatory_actions", regulatoryActionId)
    producer_scope(ctx, row["producer_id"])
    return object_response(serialize_action(row), 200)


@bp.route("/api/regulatory-actions", methods=["GET"])
def list_actions():
    authorize(*_LIST_ROLES)
    rows = db.ordered("regulatory_actions")
    rows = filter_exact(rows, "producer_id")
    rows = filter_exact(rows, "agency_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize_action)


def _checker_guard(ctx, action):
    """Maker-checker segregation of duties (rung 3)."""
    if ctx.user_id == action["created_by_user_id"]:
        fail(
            "ERR_SOD_VIOLATION",
            "The reporting operator may not confirm or dismiss their own action.",
        )


@bp.route("/api/regulatory-actions/<regulatoryActionId>/confirm", methods=["POST"])
def confirm_action(regulatoryActionId):
    ctx = authorize("ComplianceOfficer")
    action = resolve("regulatory_actions", regulatoryActionId)
    _checker_guard(ctx, action)
    if action["status"] != "REPORTED":
        fail(
            "ERR_INVALID_STATE",
            "Regulatory action in status {} cannot be confirmed.".format(action["status"]),
        )
    if action["action_type"] == "PROBATION":
        # Spacing: effective_date must be at least 365 days after any other
        # CONFIRMED probation for the same subject and state.
        for other in db.regulatory_actions.values():
            if (
                other["id"] == action["id"]
                or other["action_type"] != "PROBATION"
                or other["status"] != "CONFIRMED"
                or other["state_code"] != action["state_code"]
                or other["producer_id"] != action["producer_id"]
                or other["agency_id"] != action["agency_id"]
            ):
                continue
            gap = action["effective_date"] - other["effective_date"]
            if timedelta(0) <= gap < timedelta(days=K.PROBATION_SPACING_DAYS):
                fail(
                    "ERR_PROBATION_SPACING",
                    "Another CONFIRMED probation for this subject and state lies within 365 days.",
                )
    action["status"] = "CONFIRMED"
    action["decided_by_user_id"] = ctx.user_id
    if action["action_type"] == "FINE":
        action["fine_allocations"] = calc.compute_fine_allocations(action)
    bump(action)
    if action["action_type"] in ("SUSPENSION", "REVOCATION"):
        cascade.apply_license_discipline(action)
    return object_response(serialize_action(action), 200)


@bp.route("/api/regulatory-actions/<regulatoryActionId>/dismiss", methods=["POST"])
def dismiss_action(regulatoryActionId):
    ctx = authorize("ComplianceOfficer")
    action = resolve("regulatory_actions", regulatoryActionId)
    _checker_guard(ctx, action)
    if action["status"] != "REPORTED":
        fail(
            "ERR_INVALID_STATE",
            "Regulatory action in status {} cannot be dismissed.".format(action["status"]),
        )
    action["status"] = "DISMISSED"
    action["decided_by_user_id"] = ctx.user_id
    bump(action)
    return object_response(serialize_action(action), 200)
