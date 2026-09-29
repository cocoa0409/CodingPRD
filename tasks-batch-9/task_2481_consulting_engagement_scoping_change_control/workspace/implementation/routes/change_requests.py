"""Change control: identification, impact, routing, approval and rescission (PRD 3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from calc import (
    BLENDED_FORECAST_COST_RATE_CENTS_PER_HOUR,
    D,
    GRADES,
    HUNDRED,
    LEADERSHIP_ROUTING_PCT,
    MATERIALITY_CEILING_PCT,
    change_request_impact,
    r2,
    rc,
    routing_for,
)
from db import clock_stamp, db, new_row, rows, touch
from errors import fail
from middleware import (
    READ_ROLES,
    ROLE_CLIENT,
    ROLE_LEADERSHIP,
    ROLE_MANAGER,
    client_scope,
    require_roles,
)
from response import ok
from routes.common import fetch, filtered, fk, paged
from serializers import change_request_out
from services import economics
from validators import (
    filter_arg,
    get_decimal,
    get_enum,
    get_id,
    get_int,
    get_str,
    json_body,
    parse_date,
)

bp = Blueprint("change_requests", __name__)

ORIGINS = ("CLIENT_REQUEST", "DELIVERY_TEAM")


def engagement_changes(engagement_id):
    return [c for c in rows("change_requests") if c["engagement_id"] == engagement_id]


def approved_siblings(engagement_id, exclude_id=None):
    return [
        c
        for c in engagement_changes(engagement_id)
        if c["status"] == "APPROVED" and c["id"] != exclude_id
    ]


def manager_binding(engagement):
    if engagement is None or g.user_id != engagement["engagement_manager_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the engagement manager may perform this operation.",
        )


# ------------------------------------------------------------------ create


@bp.post("/change-requests")
def create_change_request():
    require_roles(ROLE_MANAGER)
    body = json_body()
    engagement_id = get_id(body, "engagement_id")
    origin = get_enum(body, "origin", ORIGINS)
    summary = get_str(body, "summary", min_len=1, max_len=1000)
    added_hours = get_decimal(body, "added_hours", gt=0, le=5000)
    added_grade = get_enum(body, "added_grade", GRADES)
    schedule_days = get_int(body, "requested_schedule_days", minimum=0, maximum=180)
    expected_version = get_int(body, "expected_engagement_version", minimum=0)
    supersedes_id = get_id(body, "supersedes_change_request_id", required=False)

    engagement = fk("engagements", engagement_id)
    predecessor = fk("change_requests", supersedes_id) if supersedes_id else None

    if expected_version != engagement["version"]:
        fail(
            "ERR_STALE_ENGAGEMENT_VERSION",
            "expected_engagement_version does not match the engagement's current version.",
        )
    if engagement["delivery_state"] == "CLOSED":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement is CLOSED.")
    if predecessor is not None and predecessor["engagement_id"] != engagement_id:
        fail(
            "ERR_DELIVERABLE_NOT_IN_ENGAGEMENT_SCOPE",
            "The superseded change request belongs to another engagement.",
        )

    row = new_row(
        {
            "engagement_id": engagement_id,
            "requested_by_consultant_id": g.user_id,
            "leadership_approver_consultant_id": None,
            "supersedes_change_request_id": supersedes_id,
            "origin": origin,
            "summary": summary,
            "added_hours": added_hours,
            "added_grade": added_grade,
            "requested_schedule_days": schedule_days,
            "status": "DRAFT",
            "routing": None,
            "gross_delta_cents": None,
            "fee_delta_cents": None,
            "cumulative_change_pct_at_assessment": None,
            "approved_at": None,
            "rescinded_at": None,
            "note": None,
        }
    )
    db.change_requests[row["id"]] = row
    touch(engagement)
    return ok(change_request_out(row), 201)


# ------------------------------------------------------------------ read / list


@bp.get("/change-requests/<change_id>")
def read_change_request(change_id):
    require_roles(*READ_ROLES)
    row = fetch("change_requests", change_id)
    engagement = db.engagements.get(row["engagement_id"])
    if engagement is not None:
        client_scope(engagement["client_id"])
    return ok(change_request_out(row))


@bp.get("/change-requests")
def list_change_requests():
    require_roles(*READ_ROLES)
    engagement_id = filter_arg("engagement_id")
    requester = filter_arg("requested_by_consultant_id")
    approver = filter_arg("leadership_approver_consultant_id")
    supersedes = filter_arg("supersedes_change_request_id")
    status = filter_arg("status")
    own_client = g.user_id if g.role == ROLE_CLIENT else None

    def keep(row):
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            return False
        if requester is not None and row["requested_by_consultant_id"] != requester:
            return False
        if approver is not None and row["leadership_approver_consultant_id"] != approver:
            return False
        if supersedes is not None and row["supersedes_change_request_id"] != supersedes:
            return False
        if status is not None and row["status"] != status:
            return False
        if own_client is not None:
            engagement = db.engagements.get(row["engagement_id"])
            if engagement is None or engagement["client_id"] != own_client:
                return False
        return True

    return paged(filtered("change_requests", keep), change_request_out)


# ------------------------------------------------------------------ impact assessment


@bp.post("/change-requests/<change_id>/assess-impact")
def assess_impact(change_id):
    require_roles(ROLE_MANAGER)
    row = fetch("change_requests", change_id)
    engagement = db.engagements.get(row["engagement_id"])
    manager_binding(engagement)

    if row["status"] != "DRAFT":
        fail("ERR_CHANGE_REQUEST_STATE_INVALID", "Only a DRAFT change request may be assessed.")
    if engagement["delivery_state"] not in ("MOBILIZING", "ACTIVE"):
        fail(
            "ERR_ENGAGEMENT_STATE_INVALID",
            "Impact may only be assessed while the engagement is MOBILIZING or ACTIVE.",
        )

    approved_sum = 0
    for sibling in approved_siblings(engagement["id"], exclude_id=row["id"]):
        approved_sum += int(sibling["fee_delta_cents"] or 0)

    gross, fee_delta, cumulative = change_request_impact(
        row["added_hours"],
        row["added_grade"],
        engagement["pinned_scope_discount_pct"],
        engagement["pinned_risk_premium_pct"],
        approved_sum,
        engagement["original_fee_cents"],
    )
    if cumulative > MATERIALITY_CEILING_PCT:
        fail(
            "ERR_CHANGE_EXCEEDS_MATERIALITY",
            "The cumulative change of %s%% exceeds the 40.00%% ceiling." % cumulative,
        )

    row["gross_delta_cents"] = gross
    row["fee_delta_cents"] = fee_delta
    row["cumulative_change_pct_at_assessment"] = cumulative
    row["routing"] = routing_for(cumulative)
    row["status"] = (
        "PENDING_LEADERSHIP_APPROVAL"
        if row["routing"] == "LEADERSHIP_THEN_CLIENT"
        else "PENDING_CLIENT_APPROVAL"
    )
    touch(row)
    return ok(change_request_out(row))


# ------------------------------------------------------------------ leadership decision


@bp.post("/change-requests/<change_id>/leadership-decision")
def leadership_decision(change_id):
    require_roles(ROLE_LEADERSHIP)
    row = fetch("change_requests", change_id)
    if g.user_id == row["requested_by_consultant_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The requester may not take the leadership decision.")

    body = json_body()
    decision = get_enum(body, "decision", ("APPROVE", "REJECT"))
    note = get_str(body, "note", required=False, min_len=0, max_len=None)

    if row["status"] != "PENDING_LEADERSHIP_APPROVAL":
        fail(
            "ERR_CHANGE_REQUEST_STATE_INVALID",
            "The change request is not awaiting a leadership decision.",
        )

    row["leadership_approver_consultant_id"] = g.user_id
    if note is not None:
        row["note"] = note
    row["status"] = "PENDING_CLIENT_APPROVAL" if decision == "APPROVE" else "REJECTED"
    touch(row)
    return ok(change_request_out(row))


# ------------------------------------------------------------------ client decision


def _projected_post_change_cost(engagement, added_hours):
    contracted = D(engagement["contracted_hours"]) + D(added_hours)
    remaining = contracted - D(engagement["approved_hours_burned"])
    if remaining < Decimal("0"):
        remaining = Decimal("0")
    return int(engagement["burned_cost_cents"]) + rc(
        remaining * BLENDED_FORECAST_COST_RATE_CENTS_PER_HOUR
    )


@bp.post("/change-requests/<change_id>/client-decision")
def client_decision(change_id):
    require_roles(ROLE_CLIENT)
    row = fetch("change_requests", change_id)
    engagement = db.engagements.get(row["engagement_id"])
    if engagement is not None:
        client_scope(engagement["client_id"])

    body = json_body()
    decision = get_enum(body, "decision", ("APPROVE", "REJECT"))
    note = get_str(body, "note", required=False, min_len=0, max_len=None)

    if row["status"] != "PENDING_CLIENT_APPROVAL":
        fail(
            "ERR_CHANGE_REQUEST_STATE_INVALID",
            "The change request is not awaiting a client decision.",
        )

    if note is not None:
        row["note"] = note

    if decision == "REJECT":
        row["status"] = "REJECTED"
        touch(row)
        return ok(change_request_out(row))

    if engagement["pricing_model"] == "TIME_AND_MATERIALS":
        ceiling = engagement["not_to_exceed_cents"]
        if ceiling is not None:
            projected = _projected_post_change_cost(engagement, row["added_hours"])
            if projected > int(ceiling):
                fail(
                    "ERR_NOT_TO_EXCEED_BREACHED",
                    "The post-change forecast would breach the not-to-exceed ceiling.",
                )

    row["status"] = "APPROVED"
    row["approved_at"] = clock_stamp()
    touch(row)

    fee_delta = int(row["fee_delta_cents"] or 0)
    engagement["contracted_fee_cents"] = int(engagement["contracted_fee_cents"]) + fee_delta
    engagement["contracted_hours"] = D(engagement["contracted_hours"]) + D(row["added_hours"])
    engagement["schedule_relief_days"] = int(engagement["schedule_relief_days"]) + int(
        row["requested_schedule_days"]
    )
    engagement["planned_end_date"] = (
        parse_date(engagement["planned_end_date"])
        + timedelta(days=int(row["requested_schedule_days"]))
    ).isoformat()
    engagement["cumulative_change_pct"] = row["cumulative_change_pct_at_assessment"]
    if engagement["pricing_model"] == "TIME_AND_MATERIALS" and engagement[
        "not_to_exceed_cents"
    ] is not None:
        engagement["not_to_exceed_cents"] = int(engagement["not_to_exceed_cents"]) + fee_delta
    touch(engagement)
    economics.recompute(engagement)
    return ok(change_request_out(row))


# ------------------------------------------------------------------ rescission


def _recompute_contract(engagement):
    """Rebuild the contracted figures from the surviving APPROVED requests."""
    survivors = approved_siblings(engagement["id"])
    fee_sum = 0
    hours_sum = Decimal("0")
    days_sum = 0
    for cr in survivors:
        fee_sum += int(cr["fee_delta_cents"] or 0)
        hours_sum += D(cr["added_hours"])
        days_sum += int(cr["requested_schedule_days"] or 0)

    engagement["contracted_fee_cents"] = int(engagement["original_fee_cents"]) + fee_sum
    engagement["contracted_hours"] = D(engagement["_base_contracted_hours"]) + hours_sum
    engagement["schedule_relief_days"] = days_sum
    engagement["planned_end_date"] = (
        parse_date(engagement["_base_planned_end_date"]) + timedelta(days=days_sum)
    ).isoformat()
    original = D(engagement["original_fee_cents"])
    if original == Decimal("0"):
        engagement["cumulative_change_pct"] = Decimal("0.00")
    else:
        engagement["cumulative_change_pct"] = r2(HUNDRED * D(fee_sum) / original)


@bp.post("/change-requests/<change_id>/rescind")
def rescind(change_id):
    require_roles(ROLE_LEADERSHIP, ROLE_MANAGER)
    row = fetch("change_requests", change_id)
    engagement = db.engagements.get(row["engagement_id"])

    if row["status"] == "DRAFT":
        if g.user_id != row["requested_by_consultant_id"]:
            fail(
                "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
                "Only the manager who raised the request may rescind a DRAFT.",
            )
    elif row["status"] == "APPROVED":
        if g.role != ROLE_LEADERSHIP:
            fail("ERR_FORBIDDEN_ROLE", "Only firm leadership may rescind an APPROVED request.")
    else:
        fail(
            "ERR_CHANGE_REQUEST_STATE_INVALID",
            "A %s change request may not be rescinded." % row["status"],
        )

    body = json_body()
    note = get_str(body, "note", required=False, min_len=0, max_len=None)

    was_approved = row["status"] == "APPROVED"
    if was_approved and engagement["delivery_state"] == "CLOSED":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement is CLOSED.")

    if note is not None:
        row["note"] = note
    row["status"] = "RESCINDED"
    row["rescinded_at"] = clock_stamp()
    touch(row)

    if was_approved:
        _recompute_contract(engagement)
        touch(engagement)
        economics.recompute(engagement)
    return ok(change_request_out(row))
