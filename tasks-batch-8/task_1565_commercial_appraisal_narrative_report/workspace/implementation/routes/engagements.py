from datetime import timedelta

from flask import Blueprint, request

import response
from db import store, new_rec, touch, serialize
from errors import (
    ApiError,
    ERR_NOT_ENGAGEMENT_CLIENT,
    ERR_INVALID_STATE,
    ERR_SEGREGATION,
    ERR_CONTINGENT_FEE,
    ERR_TURNAROUND,
    ERR_OVERCOMMITTED,
    ERR_FEE_WRITTEN_OFF,
)
from middleware import (
    auth,
    require_role,
    get_body,
    req_str,
    req_enum,
    opt_enum,
    req_int,
    opt_bool,
    req_list,
)
from response import sort_by_creation
from services import calc, domain

bp = Blueprint("engagements", __name__)

PROPERTY_TYPES = ("OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY", "SPECIAL_PURPOSE")
INTENDED_USES = ("FINANCING", "LITIGATION", "FINANCIAL_REPORTING", "TAX_APPEAL")
FEE_SCHEDULES = ("TIERED", "PER_SF")


@bp.post("/engagements")
def create_engagement():
    _, role = auth()
    require_role(role, {"EngagementManager"})
    body = get_body()
    # Priority 3: body FK references, validated left to right (when present).
    if body.get("client_id") is not None:
        domain.get_client(body["client_id"])
    if body.get("author_appraiser_id") is not None:
        domain.get_appraiser(body["author_appraiser_id"])
    if body.get("reviewer_appraiser_id") is not None:
        domain.get_appraiser(body["reviewer_appraiser_id"])
    # Priority 4: request schema.
    client_id = req_str(body, "client_id")
    author_appraiser_id = req_str(body, "author_appraiser_id")
    reviewer_appraiser_id = req_str(body, "reviewer_appraiser_id")
    property_address = req_str(body, "property_address")
    property_type = req_enum(body, "property_type", PROPERTY_TYPES)
    building_sf = req_int(body, "building_sf", minimum=1)
    intended_use = req_enum(body, "intended_use", INTENDED_USES)
    intended_users = req_list(body, "intended_users")
    requested_turnaround_days = req_int(body, "requested_turnaround_days", minimum=1)
    planned_approach_count = req_int(body, "planned_approach_count", minimum=1, maximum=3)
    fee_schedule = opt_enum(body, "fee_schedule", FEE_SCHEDULES, default="TIERED")
    is_contingent_fee = opt_bool(body, "is_contingent_fee", default=False)
    tier = calc.complexity_tier(property_type, building_sf, intended_use)
    rec = new_rec(
        {
            "client_id": client_id,
            "author_appraiser_id": author_appraiser_id,
            "reviewer_appraiser_id": reviewer_appraiser_id,
            "property_address": property_address,
            "property_type": property_type,
            "building_sf": building_sf,
            "intended_use": intended_use,
            "intended_users": intended_users,
            "requested_turnaround_days": requested_turnaround_days,
            "planned_approach_count": planned_approach_count,
            "fee_schedule": fee_schedule,
            "is_contingent_fee": is_contingent_fee,
            "complexity_tier": tier,
            "minimum_turnaround_days": calc.minimum_turnaround_days(tier),
            "quoted_fee_cents": None,
            "final_fee_cents": None,
            "fee_written_off": False,
            "submitted_at": None,
            "accepted_at": None,
            "due_date": None,
            "litigation_matter_reference": None,
            "status": "DRAFT",
        }
    )
    store.engagements[rec["id"]] = rec
    return response.success(serialize(rec), status=201)


@bp.get("/engagements/<engagementId>")
def get_engagement(engagementId):
    auth()
    rec = domain.get_engagement(engagementId)
    return response.success(serialize(rec))


@bp.get("/engagements")
def list_engagements():
    auth()
    items = list(store.engagements.values())
    for field in ("client_id", "author_appraiser_id", "reviewer_appraiser_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sort_by_creation(items)
    return response.list_response([serialize(r) for r in items])


@bp.post("/engagements/<engagementId>/submit")
def submit_engagement(engagementId):
    _, role = auth()
    require_role(role, {"EngagementManager"})
    eng = domain.get_engagement(engagementId)
    if eng["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not in DRAFT")
    if eng["author_appraiser_id"] == eng["reviewer_appraiser_id"]:
        raise ApiError(
            ERR_SEGREGATION,
            409,
            "author_appraiser_id must differ from reviewer_appraiser_id at submit",
        )
    client = store.clients[eng["client_id"]]
    eng["quoted_fee_cents"] = calc.fee_quote(eng, client)
    eng["submitted_at"] = store.clock
    eng["status"] = "PENDING_ACCEPTANCE"
    touch(eng)
    return response.success(serialize(eng))


def _require_engagement_client(eng, uid):
    if eng["client_id"] != uid:
        raise ApiError(
            ERR_NOT_ENGAGEMENT_CLIENT, 403, "Caller is not the engagement's client"
        )


@bp.post("/engagements/<engagementId>/accept")
def accept_engagement(engagementId):
    uid, role = auth()
    require_role(role, {"Client"})
    eng = domain.get_engagement(engagementId)
    _require_engagement_client(eng, uid)
    if eng["status"] != "PENDING_ACCEPTANCE":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Engagement letter is not open for acceptance"
        )
    if eng["is_contingent_fee"]:
        raise ApiError(
            ERR_CONTINGENT_FEE, 409, "Contingent fees are prohibited"
        )
    if eng["requested_turnaround_days"] < eng["minimum_turnaround_days"]:
        raise ApiError(
            ERR_TURNAROUND,
            409,
            "requested_turnaround_days is below the minimum feasible turnaround",
        )
    if domain.author_has_overlap(eng):
        raise ApiError(
            ERR_OVERCOMMITTED,
            409,
            "Author appraiser has an overlapping active assignment window",
        )
    eng["accepted_at"] = store.clock
    eng["due_date"] = store.clock + timedelta(days=eng["requested_turnaround_days"])
    client = store.clients[eng["client_id"]]
    eng["final_fee_cents"] = calc.fee_quote(eng, client)
    eng["status"] = "IN_PROGRESS"
    touch(eng)
    return response.success(serialize(eng))


@bp.post("/engagements/<engagementId>/decline")
def decline_engagement(engagementId):
    uid, role = auth()
    require_role(role, {"Client"})
    eng = domain.get_engagement(engagementId)
    get_body()  # optional reason; not persisted
    _require_engagement_client(eng, uid)
    if eng["status"] != "PENDING_ACCEPTANCE":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Engagement letter is not open for decline"
        )
    eng["status"] = "DECLINED"
    touch(eng)
    return response.success(serialize(eng))


@bp.post("/engagements/<engagementId>/cancel")
def cancel_engagement(engagementId):
    _, role = auth()
    require_role(role, {"EngagementManager"})
    eng = domain.get_engagement(engagementId)
    get_body()  # optional reason; not persisted
    if eng["status"] not in ("DRAFT", "PENDING_ACCEPTANCE", "IN_PROGRESS"):
        raise ApiError(
            ERR_INVALID_STATE, 409, "Engagement cannot be cancelled from its state"
        )
    if eng["status"] == "IN_PROGRESS":
        domain.supersede_reports(eng["id"])
    eng["status"] = "CANCELLED"
    touch(eng)
    return response.success(serialize(eng))


@bp.post("/engagements/<engagementId>/write_off_fee")
def write_off_fee(engagementId):
    _, role = auth()
    require_role(role, {"EngagementManager"})
    eng = domain.get_engagement(engagementId)
    if eng["status"] != "COMPLETED":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Only a COMPLETED engagement has a final fee to write off",
        )
    if eng["fee_written_off"]:
        raise ApiError(ERR_FEE_WRITTEN_OFF, 409, "Final fee is already written off")
    client = store.clients[eng["client_id"]]
    client["total_billed_cents"] -= eng["final_fee_cents"]
    client["volume_discount_tier"] = calc.volume_discount_tier(
        client["total_billed_cents"]
    )
    touch(client)
    eng["fee_written_off"] = True
    touch(eng)
    return response.success(serialize(eng))


@bp.post("/engagements/<engagementId>/litigation-hold")
def place_hold(engagementId):
    _, role = auth()
    require_role(role, {"LegalCounsel"})
    eng = domain.get_engagement(engagementId)
    body = get_body()
    matter_reference = req_str(body, "matter_reference")
    domain.place_litigation_hold(eng, matter_reference)
    return response.success(serialize(eng))


@bp.delete("/engagements/<engagementId>/litigation-hold")
def release_hold(engagementId):
    _, role = auth()
    require_role(role, {"LegalCounsel"})
    eng = domain.get_engagement(engagementId)
    domain.release_litigation_hold(eng)
    return response.success(serialize(eng))
