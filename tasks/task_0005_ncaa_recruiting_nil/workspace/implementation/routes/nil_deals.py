"""NILDeal endpoints (state machine: PROPOSED/UNDER_REVIEW/APPROVED/REJECTED)."""

from flask import Blueprint, g, request

import db
import services
from errors import (
    APIError,
    ERR_ATHLETE_NOT_CERTIFIED,
    ERR_PROGRAM_UNDER_SANCTION,
    ERR_SOD_VIOLATION,
    invalid_request,
    invalid_state,
    not_found,
    unauthorized,
)
from helpers import (
    get_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("nil_deals", __name__)


NIL_STATUSES = {"PROPOSED", "UNDER_REVIEW", "APPROVED", "REJECTED"}
NIL_TIERS = {"DE_MINIMIS", "STANDARD", "HIGH_VALUE"}
REJECTION_REASONS = {"BRAND_PROHIBITED", "ATHLETE_INELIGIBLE", "EXCEEDS_PROGRAM_LIMIT"}


@bp.post("/ncaa/nil-deals")
def create_deal():
    require_roles("StudentAthlete")
    body = get_body()
    athlete_id = require_field(body, "student_athlete_id", str)
    brand = require_field(body, "brand_name", str)
    raw_gross = body.get("gross_value_cents")
    if raw_gross is None:
        raise invalid_request("Required field 'gross_value_cents' is missing.")
    if isinstance(raw_gross, bool) or not isinstance(raw_gross, int):
        raise invalid_request("gross_value_cents must be an integer.")
    if raw_gross < 0:
        raise invalid_request("gross_value_cents must be >= 0.")
    raw_fee = body.get("agent_fee_pct")
    if raw_fee is None:
        agent_fee = 0.0
    else:
        if isinstance(raw_fee, bool) or not isinstance(raw_fee, (int, float)):
            raise invalid_request("agent_fee_pct must be numeric.")
        agent_fee = float(raw_fee)
        if not (0.0 <= agent_fee <= 0.30):
            raise invalid_request("agent_fee_pct must be in [0.0, 0.30].")
    # FK resolution
    athlete = db.student_athletes.get(athlete_id)
    if athlete is None:
        raise not_found("StudentAthlete not found.")
    # Ownership: the creating StudentAthlete must be the athlete on the deal
    if g.user_id != athlete_id:
        raise unauthorized(
            "StudentAthlete may only propose NIL deals for themselves."
        )
    net, tier = services.compute_nil_net_and_tier(int(raw_gross), agent_fee)
    row = {
        "id": db.new_id(),
        "student_athlete_id": athlete_id,
        "brand_name": brand,
        "gross_value_cents": int(raw_gross),
        "agent_fee_pct": agent_fee,
        "net_value_cents": net,
        "tier": tier,
        "review_round": 0,
        "status": "PROPOSED",
        "rejection_reason": None,
    }
    db.stamp_create(row)
    db.nil_deals[row["id"]] = row
    db.nil_actor_history[row["id"]] = set()
    return ok_object(row, 201)


@bp.get("/ncaa/nil-deals/<deal_id>")
def get_deal(deal_id):
    require_roles("NILReviewer", "ComplianceOfficer", "StudentAthlete")
    row = db.nil_deals.get(deal_id)
    if row is None:
        raise not_found("NILDeal not found.")
    return ok_object(row)


@bp.get("/ncaa/nil-deals")
def list_deals():
    require_roles("NILReviewer", "ComplianceOfficer", "StudentAthlete")
    limit, offset = parse_pagination()
    athlete = request.args.get("student_athlete_id")
    status = request.args.get("status")
    tier = request.args.get("tier")
    if status is not None and status not in NIL_STATUSES:
        raise invalid_request("status filter is not a valid enum.")
    if tier is not None and tier not in NIL_TIERS:
        raise invalid_request("tier filter is not a valid enum.")
    rows = list(db.nil_deals.values())
    if athlete is not None:
        rows = [r for r in rows if r["student_athlete_id"] == athlete]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/ncaa/nil-deals/<deal_id>/submit-for-review")
def submit_for_review(deal_id):
    require_roles("NILReviewer")
    deal = db.nil_deals.get(deal_id)
    if deal is None:
        raise not_found("NILDeal not found.")
    if deal["status"] != "PROPOSED":
        raise invalid_state("NILDeal is not in PROPOSED state.")
    # Precondition: athlete CERTIFIED
    athlete = db.student_athletes.get(deal["student_athlete_id"])
    if athlete is None or athlete["eligibility_status"] != "CERTIFIED":
        raise APIError(
            ERR_ATHLETE_NOT_CERTIFIED,
            "Athlete must be CERTIFIED to submit NIL deal for review.",
            422,
        )
    deal["status"] = "UNDER_REVIEW"
    db.stamp_update(deal)
    # Record submitter in the SoD ledger
    db.nil_actor_history.setdefault(deal_id, set()).add(g.user_id)
    return ok_object(deal)


@bp.post("/ncaa/nil-deals/<deal_id>/request-revision")
def request_revision(deal_id):
    require_roles("NILReviewer")
    deal = db.nil_deals.get(deal_id)
    if deal is None:
        raise not_found("NILDeal not found.")
    if deal["status"] != "UNDER_REVIEW":
        raise invalid_state("NILDeal is not in UNDER_REVIEW state.")
    # Cap: review_round + 1 <= 3
    if int(deal["review_round"]) + 1 > 3:
        raise invalid_state("NILDeal has exhausted the 3-revision cap.")
    deal["review_round"] = int(deal["review_round"]) + 1
    deal["status"] = "PROPOSED"
    db.stamp_update(deal)
    db.nil_actor_history.setdefault(deal_id, set()).add(g.user_id)
    return ok_object(deal)


@bp.post("/ncaa/nil-deals/<deal_id>/approve")
def approve_deal(deal_id):
    require_roles("NILReviewer")
    deal = db.nil_deals.get(deal_id)
    if deal is None:
        raise not_found("NILDeal not found.")
    if deal["status"] != "UNDER_REVIEW":
        raise invalid_state("NILDeal is not in UNDER_REVIEW state.")
    # Priority 13: SoD violation
    history = db.nil_actor_history.get(deal_id, set())
    if g.user_id in history:
        raise APIError(
            ERR_SOD_VIOLATION,
            "Approver must not be the same user_id as any prior submitter or revision-requester.",
            403,
        )
    # Priority 16: HIGH_VALUE deal blocked when athlete's enrolled program is sanctioned
    if deal["tier"] == "HIGH_VALUE":
        athlete = db.student_athletes.get(deal["student_athlete_id"])
        enrolled_program_id = athlete.get("enrolled_program_id") if athlete else None
        if enrolled_program_id is not None:
            program = db.programs.get(enrolled_program_id)
            if program is not None and program.get("penalty_tier", "NONE") != "NONE":
                raise APIError(
                    ERR_PROGRAM_UNDER_SANCTION,
                    "HIGH_VALUE NIL deal cannot be approved while the athlete's enrolled program is sanctioned.",
                    422,
                )
    deal["status"] = "APPROVED"
    db.stamp_update(deal)
    return ok_object(deal)


@bp.post("/ncaa/nil-deals/<deal_id>/reject")
def reject_deal(deal_id):
    require_roles("NILReviewer")
    deal = db.nil_deals.get(deal_id)
    if deal is None:
        raise not_found("NILDeal not found.")
    if deal["status"] != "UNDER_REVIEW":
        raise invalid_state("NILDeal is not in UNDER_REVIEW state.")
    body = get_body()
    reason = require_field(body, "rejection_reason", str)
    require_enum(reason, "rejection_reason", REJECTION_REASONS)
    deal["status"] = "REJECTED"
    deal["rejection_reason"] = reason
    db.stamp_update(deal)
    return ok_object(deal)
