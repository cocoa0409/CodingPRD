"""Plan CRUD and StarRatingSnapshot publishing."""
from flask import Blueprint, g, request

from auth import require_roles
from errors import err
from response import ok_array, ok_object
from serializers import serialize_plan, serialize_star_rating_snapshot
from services.star_rating import band, composite
from store import store
from utils import (
    STATE_RE,
    iso_string,
    optional_field,
    paginate,
    paginate as _,  # noqa
    parse_pagination,
    require_enum,
    require_field,
    require_int,
    require_number,
    require_str,
    stamp_create,
    stamp_update,
)

bp = Blueprint("plans", __name__)

PLAN_TYPES = {"PART_A", "PART_B", "PART_C", "PART_D", "MEDIGAP"}
HALF_STARS = {1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0}


@bp.route("/plans", methods=["POST"])
@require_roles("PlanAdmin")
def create_plan():
    body = request.get_json(silent=True) or {}
    plan_code = require_str(require_field(body, "plan_code"), field="plan_code", max_len=40)
    if plan_code in store.plan_codes:
        raise err("ERR_VALIDATION", "plan_code must be unique")
    plan_type = require_enum(require_field(body, "plan_type"), field="plan_type", allowed=PLAN_TYPES)
    plan_year = require_int(require_field(body, "plan_year"), field="plan_year", minimum=2020, maximum=2030)
    monthly_premium = require_int(
        require_field(body, "monthly_premium_cents"), field="monthly_premium_cents", minimum=0
    )
    star_rating = require_number(require_field(body, "star_rating"), field="star_rating", minimum=1.0, maximum=5.0)
    if star_rating not in HALF_STARS:
        raise err("ERR_VALIDATION", "star_rating must be in half-star increments")

    annual_ded = optional_field(body, "annual_deductible_cents", default=0)
    initial_cov = optional_field(body, "initial_coverage_limit_cents", default=0)
    cat_thresh = optional_field(body, "catastrophic_threshold_cents", default=0)
    if not (isinstance(annual_ded, int) and not isinstance(annual_ded, bool) and annual_ded >= 0):
        raise err("ERR_VALIDATION", "annual_deductible_cents must be non-negative integer")
    if not (isinstance(initial_cov, int) and not isinstance(initial_cov, bool) and initial_cov >= 0):
        raise err("ERR_VALIDATION", "initial_coverage_limit_cents must be non-negative integer")
    if not (isinstance(cat_thresh, int) and not isinstance(cat_thresh, bool) and cat_thresh >= 0):
        raise err("ERR_VALIDATION", "catastrophic_threshold_cents must be non-negative integer")

    state_code = optional_field(body, "state_code", default=None)
    if plan_type == "MEDIGAP":
        if not state_code:
            raise err("ERR_VALIDATION", "state_code required for MEDIGAP plans")
        if not isinstance(state_code, str) or not STATE_RE.match(state_code):
            raise err("ERR_VALIDATION", "state_code must be 2 uppercase letters")
    else:
        state_code = None
        # PRD: for non-MEDIGAP, the three drug thresholds default to 0
        if plan_type != "PART_D":
            annual_ded = 0
            initial_cov = 0
            cat_thresh = 0

    is_active = optional_field(body, "is_active", default=True)
    if not isinstance(is_active, bool):
        raise err("ERR_VALIDATION", "is_active must be boolean")

    now_iso = store.now_iso()
    pid = store.new_id()
    plan = {
        "id": pid,
        "plan_code": plan_code,
        "plan_type": plan_type,
        "plan_year": plan_year,
        "state_code": state_code,
        "monthly_premium_cents": monthly_premium,
        "annual_deductible_cents": annual_ded,
        "initial_coverage_limit_cents": initial_cov,
        "catastrophic_threshold_cents": cat_thresh,
        "star_rating": star_rating,
        "is_active": is_active,
    }
    stamp_create(plan, store_now_iso=now_iso)
    store.plans[pid] = plan
    store.plan_codes.add(plan_code)
    return ok_object(serialize_plan(plan), status=201)


@bp.route("/plans/<pid>", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def get_plan(pid):
    p = store.plans.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", "Plan not found")
    return ok_object(serialize_plan(p))


@bp.route("/plans", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def list_plans():
    limit, offset = parse_pagination(request.args)
    plan_type = request.args.get("plan_type")
    plan_year = request.args.get("plan_year")
    state_code = request.args.get("state_code")
    min_star = request.args.get("min_star_rating")

    items = sorted(store.plans.values(), key=lambda p: p["created_at"])
    if plan_type:
        items = [p for p in items if p["plan_type"] == plan_type]
    if plan_year:
        try:
            py = int(plan_year)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "plan_year must be integer")
        items = [p for p in items if p["plan_year"] == py]
    if state_code:
        items = [p for p in items if p.get("state_code") == state_code]
    if min_star is not None:
        try:
            ms = float(min_star)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "min_star_rating must be number")
        items = [p for p in items if p["star_rating"] >= ms]

    page, pagination = paginate(items, limit, offset)
    return ok_array([serialize_plan(p) for p in page], pagination)


@bp.route("/plans/<pid>/star-ratings", methods=["POST"])
@require_roles("PlanAdmin")
def publish_star_rating(pid):
    p = store.plans.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", "Plan not found")
    body = request.get_json(silent=True) or {}
    measurement_year = require_int(
        require_field(body, "measurement_year"), field="measurement_year", minimum=2020, maximum=2030
    )
    clinical = require_number(
        require_field(body, "clinical_quality_score"),
        field="clinical_quality_score", minimum=0, maximum=100,
    )
    experience = require_number(
        require_field(body, "member_experience_score"),
        field="member_experience_score", minimum=0, maximum=100,
    )
    service = require_number(
        require_field(body, "customer_service_score"),
        field="customer_service_score", minimum=0, maximum=100,
    )

    comp = composite(clinical, experience, service)
    weighted = band(comp)
    now_iso = store.now_iso()
    sid = store.new_id()
    snap = {
        "id": sid,
        "plan_id": pid,
        "measurement_year": measurement_year,
        "clinical_quality_score": clinical,
        "member_experience_score": experience,
        "customer_service_score": service,
        "weighted_star_rating": weighted,
        "_published_dt": store.clock,
    }
    # StarRatingSnapshot only carries id and created_at (no updated_at/version)
    snap["created_at"] = now_iso
    store.star_rating_snapshots[sid] = snap

    # If this is the latest measurement_year for this plan, update Plan.star_rating
    max_year = max(
        (s["measurement_year"] for s in store.star_rating_snapshots.values() if s["plan_id"] == pid),
        default=measurement_year,
    )
    if measurement_year == max_year:
        p["star_rating"] = weighted
        stamp_update(p, store_now_iso=now_iso)

    return ok_object(serialize_star_rating_snapshot(snap), status=201)
