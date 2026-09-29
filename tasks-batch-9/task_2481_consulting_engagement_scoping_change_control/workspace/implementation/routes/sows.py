"""Statements of work: risk scoring, pricing models and the negotiation loop."""

from decimal import Decimal

from flask import Blueprint, g

from calc import (
    PRICING_MODELS,
    RISK_PREMIUM_PCT,
    engagement_risk_score,
    risk_tier,
    sow_quoted_fee,
)
from db import clock_stamp, db, new_row, rows, touch
from errors import fail
from middleware import (
    READ_ROLES,
    ROLE_CLIENT,
    ROLE_LEADERSHIP,
    ROLE_PARTNER,
    client_scope,
    require_roles,
)
from response import ok
from routes.common import fetch, filtered, fk, paged
from routes.opportunities import clear_baseline
from serializers import sow_out
from validators import filter_arg, get_enum, get_id, get_int, get_str, json_body

bp = Blueprint("sows", __name__)

NON_TERMINAL = ("DRAFT", "INTERNAL_REVIEW", "CLIENT_REVIEW", "REVISION_REQUESTED")
CLEARED = ("CLEAR", "CLEARED_WITH_WAIVER")
REVISION_LIMIT = 3


def owner_binding(opportunity):
    if g.user_id != opportunity["owner_partner_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the pursuit's owning partner may perform this operation.",
        )


def conflict_guard(opportunity, include_blocked=True):
    if include_blocked and opportunity["conflict_status"] == "BLOCKED":
        fail("ERR_CONFLICT_BLOCKED", "The pursuit's conflict position is BLOCKED.")
    if opportunity["conflict_status"] not in CLEARED:
        fail("ERR_CONFLICT_NOT_CLEARED", "The pursuit's conflict position is not cleared.")


def price(sow, opportunity, client):
    """Writes the whole pricing chain onto the Sow row (PRD 3.5)."""
    score = engagement_risk_score(sow["pricing_model"], client, opportunity)
    tier = risk_tier(score)
    premium = RISK_PREMIUM_PCT[tier]
    baseline = opportunity["baseline_effort_cost_cents"]
    figures = sow_quoted_fee(
        sow["pricing_model"], baseline, premium, tier, sow["target_bonus_cents"]
    )
    sow["risk_score"] = score
    sow["risk_premium_pct"] = premium
    sow["pinned_scope_discount_pct"] = opportunity["scope_discount_pct"]
    sow["baseline_effort_cost_cents"] = baseline
    sow["quoted_fee_cents"] = figures["quoted_fee_cents"]
    sow["fixed_component_cents"] = figures["fixed_component_cents"]
    sow["at_risk_component_cents"] = figures["at_risk_component_cents"]
    sow["not_to_exceed_cents"] = figures["not_to_exceed_cents"]


def bonus_guards(pricing_model, bonus, supplied):
    if pricing_model == "OUTCOME_BASED":
        if bonus is None or bonus <= 0:
            fail(
                "ERR_OUTCOME_TARGET_BONUS_REQUIRED",
                "An OUTCOME_BASED statement of work needs a positive target_bonus_cents.",
            )
    elif supplied:
        fail(
            "ERR_TARGET_BONUS_NOT_APPLICABLE",
            "target_bonus_cents is not applicable to this pricing model.",
        )


def create_engagement(sow, opportunity):
    row = new_row(
        {
            "sow_id": sow["id"],
            "opportunity_id": opportunity["id"],
            "client_id": opportunity["client_id"],
            "lead_partner_consultant_id": opportunity["owner_partner_consultant_id"],
            "engagement_manager_consultant_id": None,
            "delivery_state": "MOBILIZING",
            "economics_state": "ON_TRACK",
            "pricing_model": sow["pricing_model"],
            "original_fee_cents": sow["quoted_fee_cents"],
            "contracted_fee_cents": sow["quoted_fee_cents"],
            "contracted_hours": opportunity["total_estimated_hours"],
            "not_to_exceed_cents": sow["not_to_exceed_cents"],
            "pinned_scope_discount_pct": sow["pinned_scope_discount_pct"],
            "pinned_risk_premium_pct": sow["risk_premium_pct"],
            "approved_hours_burned": Decimal("0.00"),
            "burned_cost_cents": 0,
            "cumulative_change_pct": Decimal("0.00"),
            "suspended_deliverable_count": 0,
            "schedule_relief_days": 0,
            "planned_start_date": opportunity["target_start_date"],
            "planned_end_date": opportunity["target_end_date"],
            "leadership_review_required": False,
            "closed_at": None,
            "_base_planned_end_date": opportunity["target_end_date"],
            "_base_contracted_hours": opportunity["total_estimated_hours"],
        }
    )
    db.engagements[row["id"]] = row
    return row


# ------------------------------------------------------------------ create / read / list


@bp.post("/sows")
def create_sow():
    require_roles(ROLE_PARTNER)
    body = json_body()
    opportunity_id = get_id(body, "opportunity_id")
    pricing_model = get_enum(body, "pricing_model", PRICING_MODELS)
    acceptance_summary = get_str(body, "acceptance_summary", min_len=1, max_len=2000)
    expected_version = get_int(body, "expected_opportunity_version", minimum=0)
    bonus_supplied = body.get("target_bonus_cents") is not None
    target_bonus_cents = get_int(body, "target_bonus_cents", required=False)

    opportunity = fk("opportunities", opportunity_id)
    owner_binding(opportunity)

    if expected_version != opportunity["version"]:
        fail(
            "ERR_STALE_OPPORTUNITY_VERSION",
            "expected_opportunity_version does not match the pursuit's current version.",
        )
    if opportunity["status"] not in ("SCOPE_BASELINED", "SOW_ISSUED"):
        fail(
            "ERR_OPPORTUNITY_STATE_INVALID",
            "The pursuit must be SCOPE_BASELINED or SOW_ISSUED to receive a statement of work.",
        )
    conflict_guard(opportunity)
    bonus_guards(pricing_model, target_bonus_cents, bonus_supplied)

    superseded_id = None
    for existing in rows("sows"):
        if existing["opportunity_id"] == opportunity_id and existing["status"] in NON_TERMINAL:
            existing["status"] = "SUPERSEDED"
            touch(existing)
            superseded_id = existing["id"]

    row = new_row(
        {
            "opportunity_id": opportunity_id,
            "supersedes_sow_id": superseded_id,
            "pricing_model": pricing_model,
            "target_bonus_cents": target_bonus_cents if pricing_model == "OUTCOME_BASED" else None,
            "acceptance_summary": acceptance_summary,
            "status": "DRAFT",
            "revision_round": 0,
            "risk_score": None,
            "risk_premium_pct": None,
            "pinned_scope_discount_pct": None,
            "baseline_effort_cost_cents": None,
            "quoted_fee_cents": None,
            "fixed_component_cents": None,
            "at_risk_component_cents": None,
            "not_to_exceed_cents": None,
            "signature_name": None,
            "signed_at": None,
        }
    )
    price(row, opportunity, db.clients.get(opportunity["client_id"]))
    db.sows[row["id"]] = row

    if opportunity["status"] == "SCOPE_BASELINED":
        opportunity["status"] = "SOW_ISSUED"
    touch(opportunity)
    return ok(sow_out(row), 201)


@bp.get("/sows/<sow_id>")
def read_sow(sow_id):
    require_roles(*READ_ROLES)
    row = fetch("sows", sow_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None:
        client_scope(opportunity["client_id"])
    return ok(sow_out(row))


@bp.get("/sows")
def list_sows():
    require_roles(*READ_ROLES)
    opportunity_id = filter_arg("opportunity_id")
    supersedes = filter_arg("supersedes_sow_id")
    status = filter_arg("status")
    pricing_model = filter_arg("pricing_model")
    own_client = g.user_id if g.role == ROLE_CLIENT else None

    def keep(row):
        if opportunity_id is not None and row["opportunity_id"] != opportunity_id:
            return False
        if supersedes is not None and row["supersedes_sow_id"] != supersedes:
            return False
        if status is not None and row["status"] != status:
            return False
        if pricing_model is not None and row["pricing_model"] != pricing_model:
            return False
        if own_client is not None:
            opportunity = db.opportunities.get(row["opportunity_id"])
            if opportunity is None or opportunity["client_id"] != own_client:
                return False
        return True

    return paged(filtered("sows", keep), sow_out)


# ------------------------------------------------------------------ internal review


@bp.post("/sows/<sow_id>/submit-internal")
def submit_internal(sow_id):
    require_roles(ROLE_PARTNER)
    row = fetch("sows", sow_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None:
        owner_binding(opportunity)
    if row["status"] != "DRAFT":
        fail("ERR_SOW_STATE_INVALID", "Only a DRAFT statement of work may be submitted.")
    conflict_guard(opportunity, include_blocked=False)
    row["status"] = "INTERNAL_REVIEW"
    touch(row)
    return ok(sow_out(row))


@bp.post("/sows/<sow_id>/internal-decision")
def internal_decision(sow_id):
    require_roles(ROLE_LEADERSHIP)
    row = fetch("sows", sow_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None and g.user_id == opportunity["owner_partner_consultant_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The owning partner may not take the internal review decision.",
        )
    body = json_body()
    decision = get_enum(body, "decision", ("APPROVE", "RETURN"))
    get_str(body, "note", required=False, min_len=0, max_len=None)

    if row["status"] != "INTERNAL_REVIEW":
        fail("ERR_SOW_STATE_INVALID", "The statement of work is not in internal review.")
    if decision == "APPROVE":
        conflict_guard(opportunity, include_blocked=False)
        row["status"] = "CLIENT_REVIEW"
    else:
        row["status"] = "DRAFT"
    touch(row)
    return ok(sow_out(row))


# ------------------------------------------------------------------ client decision


@bp.post("/sows/<sow_id>/client-decision")
def client_decision(sow_id):
    require_roles(ROLE_CLIENT)
    row = fetch("sows", sow_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None:
        client_scope(opportunity["client_id"])

    body = json_body()
    decision = get_enum(body, "decision", ("SIGN", "REQUEST_REVISION", "DECLINE"))
    signature_name = get_str(body, "signature_name", required=False, min_len=1, max_len=None)
    get_str(body, "note", required=False, min_len=0, max_len=None)
    if decision == "SIGN" and signature_name is None:
        fail("ERR_INVALID_REQUEST", "signature_name is required to sign.")

    if row["status"] != "CLIENT_REVIEW":
        fail("ERR_SOW_STATE_INVALID", "The statement of work is not in client review.")

    client = db.clients.get(opportunity["client_id"]) if opportunity else None

    if decision == "SIGN":
        conflict_guard(opportunity, include_blocked=False)
        if client is None or client["status"] != "ACTIVE":
            fail(
                "ERR_CLIENT_NOT_ELIGIBLE_FOR_SIGNATURE",
                "Only an ACTIVE client may sign a statement of work.",
            )
        row["status"] = "SIGNED"
        row["signature_name"] = signature_name
        row["signed_at"] = clock_stamp()
        touch(row)
        create_engagement(row, opportunity)
        opportunity["status"] = "WON"
        touch(opportunity)
        return ok(sow_out(row))

    if decision == "REQUEST_REVISION":
        if row["revision_round"] >= REVISION_LIMIT:
            fail("ERR_REVISION_LIMIT_REACHED", "The negotiation revision limit has been reached.")
        row["status"] = "REVISION_REQUESTED"
        touch(row)
        opportunity["status"] = "SCOPING"
        clear_baseline(opportunity)
        touch(opportunity)
        return ok(sow_out(row))

    row["status"] = "DECLINED"
    touch(row)
    opportunity["status"] = "LOST"
    touch(opportunity)
    return ok(sow_out(row))


# ------------------------------------------------------------------ re-draft


@bp.post("/sows/<sow_id>/revise")
def revise(sow_id):
    require_roles(ROLE_PARTNER)
    row = fetch("sows", sow_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None:
        owner_binding(opportunity)

    body = json_body()
    pricing_model = get_enum(body, "pricing_model", PRICING_MODELS, required=False)
    bonus_supplied = body.get("target_bonus_cents") is not None
    target_bonus_cents = get_int(body, "target_bonus_cents", required=False)
    acceptance_summary = get_str(
        body, "acceptance_summary", required=False, min_len=1, max_len=2000
    )

    if row["status"] != "REVISION_REQUESTED":
        fail("ERR_SOW_STATE_INVALID", "Only a REVISION_REQUESTED statement of work may be revised.")
    if opportunity["status"] != "SCOPE_BASELINED":
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The pursuit has not been re-baselined.")
    if row["revision_round"] >= REVISION_LIMIT:
        fail("ERR_REVISION_LIMIT_REACHED", "The negotiation revision limit has been reached.")

    effective_model = pricing_model or row["pricing_model"]
    effective_bonus = (
        target_bonus_cents if bonus_supplied else row["target_bonus_cents"]
    )
    bonus_guards(effective_model, effective_bonus, bonus_supplied)

    row["pricing_model"] = effective_model
    row["target_bonus_cents"] = effective_bonus if effective_model == "OUTCOME_BASED" else None
    if acceptance_summary is not None:
        row["acceptance_summary"] = acceptance_summary
    row["revision_round"] = row["revision_round"] + 1
    row["status"] = "DRAFT"
    price(row, opportunity, db.clients.get(opportunity["client_id"]))
    touch(row)

    opportunity["status"] = "SOW_ISSUED"
    touch(opportunity)
    return ok(sow_out(row))
