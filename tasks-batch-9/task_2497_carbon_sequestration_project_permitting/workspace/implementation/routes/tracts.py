"""Pore-space tract endpoints (PRD 3.5)."""

from decimal import Decimal as D

from flask import Blueprint

import clock
import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import derive, lookup, serialize

bp = Blueprint("tracts", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"
LANDOWNER = "Landowner"


@bp.post("/ccs/pore-space-tracts")
@mw.require(DEV)
def create_tract():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    tract_label = mw.req_str(payload, "tract_label")
    acreage = mw.req_num(payload, "acreage", gt=0)
    ownership_pct = mw.opt_num(payload, "ownership_pct", default=D("100"), gt=0, le=100)
    landowner_user_id = mw.req_str(payload, "landowner_user_id")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "tract_label": tract_label,
            "acreage": acreage,
            "ownership_pct": ownership_pct,
            "landowner_user_id": landowner_user_id,
            "lease_status": "UNLEASED",
            "current_offer_bonus_per_acre_usd": None,
            "current_offer_royalty_rate_pct": None,
            "counter_bonus_per_acre_usd": None,
            "executed_bonus_per_acre_usd": None,
            "executed_royalty_rate_pct": None,
            "lease_term_start": None,
            "lease_term_end": None,
            "negotiation_round_count": 0,
            "bonus_settlement_usd": D("0.00"),
            "net_acreage": D("0.0000"),
        }
    )
    db.pore_space_tracts[row["id"]] = row
    return response.object_response(serialize.tract(row), 201)


@bp.get("/ccs/pore-space-tracts/<tract_id>")
@mw.require(ADMIN, DEV, REVIEWER, LANDOWNER)
def get_tract(tract_id):
    return response.object_response(serialize.tract(lookup.tract(tract_id)))


@bp.post("/ccs/pore-space-tracts/<tract_id>/offers")
@mw.require(DEV)
def send_offer(tract_id):
    payload = mw.body()
    expected_tract_version = mw.req_int(payload, "expected_tract_version")
    bonus_per_acre_usd = mw.req_num(payload, "bonus_per_acre_usd", ge=0)
    royalty_rate_pct = mw.req_num(payload, "royalty_rate_pct", ge=0)

    tract = lookup.tract(tract_id)
    project = db.projects.get(tract["project_id"])
    derive.require_not_frozen(project)

    if tract["lease_status"] not in ("UNLEASED", "COUNTERED"):
        raise ApiError(
            "ERR_INVALID_TRACT_STATE", "an offer is only admissible from UNLEASED or COUNTERED"
        )

    if expected_tract_version != tract["version"]:
        raise ApiError("ERR_STALE_TRACT_VERSION", "expected_tract_version does not match")

    tract["counter_bonus_per_acre_usd"] = None
    tract["current_offer_bonus_per_acre_usd"] = bonus_per_acre_usd
    tract["current_offer_royalty_rate_pct"] = royalty_rate_pct
    tract["negotiation_round_count"] = tract["negotiation_round_count"] + 1
    tract["lease_status"] = "OFFER_SENT"
    db.touch(tract)
    return response.object_response(serialize.tract(tract))


@bp.post("/ccs/pore-space-tracts/<tract_id>/respond")
@mw.require(LANDOWNER)
def respond_to_offer(tract_id):
    existing = lookup.maybe_tract(tract_id)
    if existing is not None and existing["landowner_user_id"] != mw.caller_id():
        raise ApiError(
            "ERR_NOT_TRACT_LANDOWNER", "only the tract's landowner may respond to its offer"
        )

    payload = mw.body()
    decision = mw.req_enum(payload, "response", enums.TRACT_RESPONSE)
    counter_bonus = None
    lease_term_start = None
    lease_term_end = None
    if decision == "COUNTER":
        counter_bonus = mw.req_num(payload, "counter_bonus_per_acre_usd", ge=0)
    elif decision == "ACCEPT":
        lease_term_start = mw.req_ts(payload, "lease_term_start")
        lease_term_end = mw.req_ts(payload, "lease_term_end")
        if not clock.must_parse(lease_term_end, "lease_term_end") > clock.must_parse(
            lease_term_start, "lease_term_start"
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST", "lease_term_end must be strictly later than lease_term_start"
            )

    tract = lookup.tract(tract_id)
    project = db.projects.get(tract["project_id"])
    derive.require_not_frozen(project)

    if tract["lease_status"] != "OFFER_SENT":
        raise ApiError("ERR_INVALID_TRACT_STATE", "the tract has no outstanding offer")

    if decision == "COUNTER":
        if not counter_bonus > D(tract["current_offer_bonus_per_acre_usd"]):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "counter_bonus_per_acre_usd must be strictly greater than the current offer",
            )
        tract["counter_bonus_per_acre_usd"] = counter_bonus
        tract["lease_status"] = "COUNTERED"
        db.touch(tract)
        return response.object_response(serialize.tract(tract))

    if decision == "REJECT":
        tract["current_offer_bonus_per_acre_usd"] = None
        tract["current_offer_royalty_rate_pct"] = None
        tract["lease_status"] = "REJECTED"
        db.touch(tract)
        return response.object_response(serialize.tract(tract))

    tract["executed_bonus_per_acre_usd"] = tract["current_offer_bonus_per_acre_usd"]
    tract["executed_royalty_rate_pct"] = tract["current_offer_royalty_rate_pct"]
    tract["lease_term_start"] = lease_term_start
    tract["lease_term_end"] = lease_term_end
    tract["lease_status"] = "EXECUTED"
    derive.refresh_tract(tract)
    db.touch(tract)

    derive.recompute_pore_space(project)
    db.touch(project)

    return response.object_response(serialize.tract(tract))


@bp.post("/ccs/pore-space-tracts/<tract_id>/terminate-lease")
@mw.require(DEV)
def terminate_lease(tract_id):
    payload = mw.body()
    mw.req_str(payload, "termination_reason")

    tract = lookup.tract(tract_id)
    project = db.projects.get(tract["project_id"])
    derive.require_not_frozen(project)

    if tract["lease_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_TRACT_STATE", "only an EXECUTED lease may be terminated")
    if project["status"] not in ("DRAFT", "SITE_CHARACTERIZATION", "PERMITTING"):
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            "acreage cannot be handed back once injection has been authorized",
        )

    tract["executed_bonus_per_acre_usd"] = None
    tract["executed_royalty_rate_pct"] = None
    tract["lease_term_start"] = None
    tract["lease_term_end"] = None
    tract["bonus_settlement_usd"] = D("0.00")
    tract["net_acreage"] = D("0.0000")
    tract["lease_status"] = "TERMINATED"
    db.touch(tract)

    derive.recompute_pore_space(project)
    db.touch(project)

    return response.object_response(serialize.tract(tract))
