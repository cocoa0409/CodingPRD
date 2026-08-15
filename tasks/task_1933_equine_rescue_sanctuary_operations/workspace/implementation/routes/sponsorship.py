from flask import Blueprint

import calc
import clock
import db
import services
from auth import (
    authenticate,
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_ADOPTION_OFFICER,
    ROLE_SPONSOR,
)
from errors import (
    raise_err,
    ERR_HORSE_NOT_FOUND,
    ERR_SPONSOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_HORSE_NOT_RESIDENT,
    ERR_PLEDGE_BELOW_MINIMUM,
    ERR_STALE_HORSE_VERSION,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_enum,
    as_str,
    body,
    get_path_or_404,
    opt_str,
    pagination_args,
    query_str,
    require_present,
    sorted_page,
)

bp = Blueprint("sponsorship", __name__)

READ_ROLES = [ROLE_SANCTUARY_DIRECTOR, ROLE_ADOPTION_OFFICER]


# --------------------------------------------------------------------------
# Sponsors
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/sponsors")
def create_sponsor():
    authenticate([ROLE_SPONSOR])
    data = body()
    name = as_str(require_present(data, "name"), "name")
    email = as_str(require_present(data, "contact_email"), "contact_email")
    rec = services.new_entity({"name": name, "contact_email": email, "status": "INACTIVE"})
    db.sponsors[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/sponsors")
def list_sponsors():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    value = query_str("status")
    if value is not None:
        filters.append(("status", value))
    rows, total = sorted_page(db.sponsors.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/sponsors/<sponsor_id>")
def get_sponsor(sponsor_id):
    user_id, role = authenticate(READ_ROLES + [ROLE_SPONSOR])
    rec = get_path_or_404(db.sponsors, sponsor_id)
    if role == ROLE_SPONSOR and user_id != sponsor_id:
        raise_err(ERR_FORBIDDEN, "Sponsors may read only their own record")
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Sponsorships
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/sponsorships")
def create_sponsorship():
    user_id, _ = authenticate([ROLE_SPONSOR])
    data = body()
    sponsor_id = data.get("sponsor_id")
    if sponsor_id is not None and sponsor_id not in db.sponsors:
        raise_err(ERR_SPONSOR_NOT_FOUND, "sponsor_id does not reference an existing sponsor")
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    sponsor_id = require_present(data, "sponsor_id")
    horse_id = require_present(data, "horse_id")
    pledge = require_present(data, "monthly_pledge_cents")
    if isinstance(pledge, bool) or not isinstance(pledge, int) or pledge < 1:
        raise_err(ERR_INVALID_REQUEST, "monthly_pledge_cents must be a positive integer")
    if sponsor_id != user_id:
        raise_err(ERR_FORBIDDEN, "Sponsor may pledge only under their own id")
    horse = db.horses[horse_id]
    if horse["status"] in ("ADOPTED", "DECEASED"):
        raise_err(ERR_HORSE_NOT_RESIDENT, "Horse is not a resident")
    if pledge < 2500:
        raise_err(ERR_PLEDGE_BELOW_MINIMUM, "monthly_pledge_cents must be at least 2500")
    rec = services.new_entity(
        {
            "sponsor_id": sponsor_id,
            "horse_id": horse_id,
            "monthly_pledge_cents": pledge,
            "status": "PLEDGED",
            "completion_reason": None,
            "cancellation_reason": None,
            "activated_at": None,
        }
    )
    db.sponsorships[rec["id"]] = rec
    services.recompute_sponsor_status(sponsor_id)
    return ok_object(serialize(rec), 201)


def _get_scoped_sponsorship(user_id, role, sship_id):
    rec = get_path_or_404(db.sponsorships, sship_id)
    if role == ROLE_SPONSOR and rec["sponsor_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Sponsors may access only their own sponsorships")
    return rec


@bp.get("/rescue-ops/sponsorships")
def list_sponsorships():
    user_id, role = authenticate(READ_ROLES + [ROLE_SPONSOR])
    limit, offset = pagination_args()
    filters = []
    for param in ("sponsor_id", "horse_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    if role == ROLE_SPONSOR:
        filters.append(("sponsor_id", user_id))
    rows, total = sorted_page(db.sponsorships.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/sponsorships/<sship_id>")
def get_sponsorship(sship_id):
    user_id, role = authenticate(READ_ROLES + [ROLE_SPONSOR])
    return ok_object(serialize(_get_scoped_sponsorship(user_id, role, sship_id)))


def _ownership_gate(user_id, role, rec):
    if role == ROLE_SPONSOR and rec["sponsor_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Sponsor may act only on their own sponsorships")


def _resident_gate(rec):
    horse = db.horses[rec["horse_id"]]
    if horse["status"] in ("ADOPTED", "DECEASED"):
        raise_err(ERR_HORSE_NOT_RESIDENT, "Horse is not a resident")


@bp.post("/rescue-ops/sponsorships/<sship_id>/activate")
def activate_sponsorship(sship_id):
    user_id, role = authenticate([ROLE_SPONSOR, ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.sponsorships, sship_id)
    if rec["status"] != "PLEDGED":
        raise_err(ERR_INVALID_STATE, "Sponsorship is not PLEDGED")
    _ownership_gate(user_id, role, rec)
    _resident_gate(rec)
    rec["status"] = "ACTIVE"
    rec["activated_at"] = clock.now()
    services.touch(rec)
    services.recompute_care_plan_coverage(rec["horse_id"])
    services.recompute_sponsor_status(rec["sponsor_id"])
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/sponsorships/<sship_id>/lapse")
def lapse_sponsorship(sship_id):
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.sponsorships, sship_id)
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Sponsorship is not ACTIVE")
    rec["status"] = "LAPSED"
    services.touch(rec)
    services.recompute_care_plan_coverage(rec["horse_id"])
    services.recompute_sponsor_status(rec["sponsor_id"])
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/sponsorships/<sship_id>/reinstate")
def reinstate_sponsorship(sship_id):
    user_id, role = authenticate([ROLE_SPONSOR, ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.sponsorships, sship_id)
    if rec["status"] != "LAPSED":
        raise_err(ERR_INVALID_STATE, "Sponsorship is not LAPSED")
    _ownership_gate(user_id, role, rec)
    _resident_gate(rec)
    rec["status"] = "ACTIVE"
    services.touch(rec)
    services.recompute_care_plan_coverage(rec["horse_id"])
    services.recompute_sponsor_status(rec["sponsor_id"])
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/sponsorships/<sship_id>/cancel")
def cancel_sponsorship(sship_id):
    user_id, role = authenticate([ROLE_SPONSOR, ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.sponsorships, sship_id)
    data = body()
    reason = opt_str(data, "reason")
    if rec["status"] not in ("PLEDGED", "ACTIVE", "LAPSED"):
        raise_err(ERR_INVALID_STATE, "Sponsorship cannot be cancelled from its current state")
    _ownership_gate(user_id, role, rec)
    was_active = rec["status"] == "ACTIVE"
    rec["status"] = "CANCELLED"
    if reason is not None:
        rec["cancellation_reason"] = reason
    services.touch(rec)
    if was_active:
        services.recompute_care_plan_coverage(rec["horse_id"])
    services.recompute_sponsor_status(rec["sponsor_id"])
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Sanctuary care plans
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/sanctuary-care-plans")
def create_care_plan():
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    data = body()
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    horse_id = require_present(data, "horse_id")
    variant = as_enum(require_present(data, "variant"), "variant", {"ACTUARIAL", "STRAIGHT_LINE"})
    expected_raw = require_present(data, "expected_horse_version")
    if isinstance(expected_raw, bool) or not isinstance(expected_raw, int):
        raise_err(ERR_INVALID_REQUEST, "expected_horse_version must be an integer")
    horse = db.horses[horse_id]
    if expected_raw != horse["version"]:
        raise_err(ERR_STALE_HORSE_VERSION, "expected_horse_version is stale")
    if horse["status"] != "SANCTUARY":
        raise_err(ERR_INVALID_STATE, "Horse is not in SANCTUARY")

    months, monthly, total = calc.care_projection(
        horse["breed_class"], horse["age_years"], variant
    )
    for plan in db.care_plans.values():
        if plan["horse_id"] == horse_id and plan["status"] in ("DRAFT", "APPROVED"):
            plan["status"] = "SUPERSEDED"
            services.touch(plan)
    coverage = services.active_pledge_sum(horse_id)
    if coverage == 0:
        funding = "UNFUNDED"
    elif coverage < monthly:
        funding = "PARTIALLY_FUNDED"
    else:
        funding = "FUNDED"
    rec = services.new_entity(
        {
            "horse_id": horse_id,
            "variant": variant,
            "projected_months": months,
            "monthly_cost_cents": monthly,
            "total_lifetime_cost_cents": total,
            "funding_coverage_cents": coverage,
            "funding_status": funding,
            "status": "DRAFT",
        }
    )
    db.care_plans[rec["id"]] = rec
    services.touch(horse)
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/sanctuary-care-plans")
def list_care_plans():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("horse_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.care_plans.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/sanctuary-care-plans/<plan_id>")
def get_care_plan(plan_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.care_plans, plan_id)))


@bp.post("/rescue-ops/sanctuary-care-plans/<plan_id>/approve")
def approve_care_plan(plan_id):
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.care_plans, plan_id)
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Care plan is not in DRAFT")
    horse = db.horses[rec["horse_id"]]
    if horse["status"] != "SANCTUARY":
        raise_err(ERR_INVALID_STATE, "Horse is not in SANCTUARY")
    services.recompute_care_plan_coverage(rec["horse_id"])
    rec["status"] = "APPROVED"
    services.touch(rec)
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/sanctuary-care-plans/<plan_id>/close")
def close_care_plan(plan_id):
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.care_plans, plan_id)
    body()
    if rec["status"] not in ("DRAFT", "APPROVED"):
        raise_err(ERR_INVALID_STATE, "Care plan cannot be closed from its current state")
    rec["status"] = "CLOSED"
    services.touch(rec)
    return ok_object(serialize(rec))
