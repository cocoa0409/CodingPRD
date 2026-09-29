"""Engagements: mobilisation, the economics view and the two-act closure."""

from flask import Blueprint, g

from db import clock_stamp, db, rows, touch
from errors import fail
from middleware import (
    READ_ROLES,
    ROLE_ADMIN,
    ROLE_CLIENT,
    ROLE_LEADERSHIP,
    ROLE_MANAGER,
    ROLE_PARTNER,
    client_scope,
    require_roles,
)
from response import ok
from routes.common import fetch, filtered, fk, paged
from serializers import engagement_out
from services import economics
from services.cascade import opportunity_deliverables
from validators import filter_arg, get_id, json_body

bp = Blueprint("engagements", __name__)

OPEN_CHANGE_STATES = (
    "DRAFT",
    "IMPACT_ASSESSED",
    "PENDING_LEADERSHIP_APPROVAL",
    "PENDING_CLIENT_APPROVAL",
)
UNRESOLVED_ESCALATIONS = ("OPEN", "ACKNOWLEDGED", "DELIVERY_HELD")


def partner_binding(engagement):
    if g.user_id != engagement["lead_partner_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the engagement's lead partner may perform this operation.",
        )


def engagement_reviews(engagement_id):
    return [r for r in rows("quality_reviews") if r["engagement_id"] == engagement_id]


def engagement_changes(engagement_id):
    return [c for c in rows("change_requests") if c["engagement_id"] == engagement_id]


def escalations(engagement_id):
    return [e for e in rows("risk_escalations") if e["engagement_id"] == engagement_id]


def failed_gate_unresolved(engagement_id):
    for review in engagement_reviews(engagement_id):
        if review["status"] != "FAILED":
            continue
        for esc in escalations(engagement_id):
            if esc["source_quality_review_id"] == review["id"] and esc["status"] != "RESOLVED":
                return True
    return False


# ------------------------------------------------------------------ read / list


@bp.get("/engagements/<engagement_id>")
def read_engagement(engagement_id):
    require_roles(*READ_ROLES)
    row = fetch("engagements", engagement_id)
    client_scope(row["client_id"])
    return ok(engagement_out(row))


@bp.get("/engagements")
def list_engagements():
    require_roles(*READ_ROLES)
    sow_id = filter_arg("sow_id")
    opportunity_id = filter_arg("opportunity_id")
    client_id = filter_arg("client_id")
    partner = filter_arg("lead_partner_consultant_id")
    manager = filter_arg("engagement_manager_consultant_id")
    delivery_state = filter_arg("delivery_state")
    economics_state = filter_arg("economics_state")

    def keep(row):
        if sow_id is not None and row["sow_id"] != sow_id:
            return False
        if opportunity_id is not None and row["opportunity_id"] != opportunity_id:
            return False
        if client_id is not None and row["client_id"] != client_id:
            return False
        if partner is not None and row["lead_partner_consultant_id"] != partner:
            return False
        if manager is not None and row["engagement_manager_consultant_id"] != manager:
            return False
        if delivery_state is not None and row["delivery_state"] != delivery_state:
            return False
        if economics_state is not None and row["economics_state"] != economics_state:
            return False
        if g.role == ROLE_CLIENT and row["client_id"] != g.user_id:
            return False
        return True

    return paged(filtered("engagements", keep), engagement_out)


# ------------------------------------------------------------------ mobilisation


@bp.post("/engagements/<engagement_id>/mobilize")
def mobilize(engagement_id):
    require_roles(ROLE_PARTNER)
    row = fetch("engagements", engagement_id)
    partner_binding(row)

    body = json_body()
    manager_id = get_id(body, "engagement_manager_consultant_id")
    consultant = fk("consultants", manager_id)

    if row["delivery_state"] != "MOBILIZING":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement has already been mobilised.")

    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None and consultant["practice_code"] != opportunity[
        "requested_practice_code"
    ]:
        fail(
            "ERR_CONSULTANT_PRACTICE_MISMATCH",
            "The consultant's practice does not match the pursuit's requested practice.",
        )

    row["engagement_manager_consultant_id"] = manager_id
    row["delivery_state"] = "ACTIVE"
    touch(row)
    return ok(engagement_out(row))


# ------------------------------------------------------------------ economics view


@bp.get("/engagements/<engagement_id>/economics")
def read_economics(engagement_id):
    require_roles(ROLE_PARTNER, ROLE_MANAGER, ROLE_LEADERSHIP, ROLE_ADMIN)
    row = fetch("engagements", engagement_id)
    figures = economics.compute(row)
    return ok(
        {
            "hours_burn_pct": float(figures["hours_burn_pct"]),
            "completion_pct": float(figures["completion_pct"]),
            "progress_variance_pct": float(figures["progress_variance_pct"]),
            "projected_cost_cents": figures["projected_cost_cents"],
            "projected_margin_pct": float(figures["projected_margin_pct"]),
            "economics_state": row["economics_state"],
        }
    )


# ------------------------------------------------------------------ closure


@bp.post("/engagements/<engagement_id>/begin-closing")
def begin_closing(engagement_id):
    require_roles(ROLE_PARTNER)
    row = fetch("engagements", engagement_id)
    partner_binding(row)

    if row["delivery_state"] != "ACTIVE":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "Only an ACTIVE engagement may begin closing.")
    if failed_gate_unresolved(row["id"]):
        fail("ERR_QUALITY_GATE_FAILED", "A failed quality checkpoint is still unresolved.")
    for review in engagement_reviews(row["id"]):
        if review["status"] == "SCHEDULED":
            fail("ERR_QUALITY_GATE_PENDING", "A quality checkpoint is still SCHEDULED.")
    deliverables = opportunity_deliverables(row["opportunity_id"])
    for d in deliverables:
        if d["status"] != "ACCEPTED":
            fail("ERR_DELIVERABLES_NOT_ACCEPTED", "Every deliverable must be ACCEPTED first.")
    for change in engagement_changes(row["id"]):
        if change["status"] in OPEN_CHANGE_STATES:
            fail(
                "ERR_OPEN_CHANGE_REQUEST_BLOCKS_CLOSING",
                "An unfinished change request blocks closing.",
            )

    row["delivery_state"] = "CLOSING"
    touch(row)
    return ok(engagement_out(row))


@bp.post("/engagements/<engagement_id>/close")
def close_engagement(engagement_id):
    require_roles(ROLE_LEADERSHIP)
    row = fetch("engagements", engagement_id)

    if row["delivery_state"] != "CLOSING":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "Only a CLOSING engagement may be closed.")
    for esc in escalations(row["id"]):
        if esc["status"] in UNRESOLVED_ESCALATIONS:
            fail("ERR_OPEN_ESCALATION_BLOCKS_CLOSE", "An unresolved risk escalation blocks closure.")

    row["delivery_state"] = "CLOSED"
    row["closed_at"] = clock_stamp()
    touch(row)
    client = db.clients.get(row["client_id"])
    if client is not None:
        client["completed_engagement_count"] = client["completed_engagement_count"] + 1
        touch(client)
    return ok(engagement_out(row))
