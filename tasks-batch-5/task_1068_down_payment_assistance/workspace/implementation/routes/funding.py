from flask import Blueprint

import store
from errors import ApiError
import context as ctx
import domain
from serializers import public, public_list
import envelope as env

bp = Blueprint("funding", __name__)


# ---- Funding sources ---------------------------------------------------------
@bp.post("/funding-sources")
def create_source():
    ctx.authenticate(["ProgramAdmin"])
    data = ctx.body()
    name = ctx.req_str(data, "name")
    priority = ctx.req_int(data, "priority", 1)
    total = ctx.req_int(data, "total_appropriation_cents", 0)
    for s in store.funding_sources.values():
        if s["status"] == "ACTIVE" and s["priority"] == priority:
            raise ApiError("ERR_INVALID_REQUEST",
                           "priority must be unique across active funding sources.")
    rec = store.new_record("funding_source")
    rec.update({
        "name": name,
        "priority": priority,
        "total_appropriation_cents": total,
        "available_cents": total,
        "reserved_cents": 0,
        "disbursed_cents": 0,
        "status": "ACTIVE",
    })
    store.funding_sources[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/funding-sources/<fid>")
def get_source(fid):
    ctx.authenticate(["ProgramAdmin", "CaseManager"])
    rec = ctx.lookup("funding_source", fid)
    return env.success(public(rec), 200)


@bp.get("/funding-sources")
def list_sources():
    ctx.authenticate(["ProgramAdmin", "CaseManager"])
    limit, offset = ctx.pagination_params()
    page, total = ctx.paginate(
        store.funding_sources.values(), limit, offset,
        {"status": ctx.query_filter("status")})
    return env.list_response(public_list(page), limit, offset, total)


# ---- Funding allocations -----------------------------------------------------
@bp.post("/funding-allocations")
def create_allocation():
    ctx.authenticate(["CaseManager"])
    data = ctx.body()
    # Existence of body FKs (left-to-right): award, funding_source.
    award_id = data.get("award_id")
    if award_id is not None:
        ctx.lookup("award", award_id)
    funding_source_id = data.get("funding_source_id")
    if funding_source_id is not None:
        ctx.lookup("funding_source", funding_source_id)

    # Structural validation.
    award_id = ctx.req_str(data, "award_id")
    funding_source_id = ctx.req_str(data, "funding_source_id")
    amount_cents = ctx.req_int(data, "amount_cents", 1)
    lien_position = ctx.req_int(data, "lien_position", 1)
    expected_version = ctx.req_int(data, "expected_funding_source_version", 0)

    award = store.awards[award_id]
    source = store.funding_sources[funding_source_id]

    # Priority 6: award must be APPROVED (state gate before any fiscal/OCC check).
    if award["status"] != "APPROVED":
        raise ApiError("ERR_AWARD_NOT_APPROVED", "Award is not in APPROVED status.")

    # Priority 7: optimistic concurrency on the funding source's version.
    if expected_version != source["version"]:
        raise ApiError("ERR_STALE_VERSION", "Stale funding source version.")

    # Priority 17: subordination / lien order.
    existing = [a for a in domain.award_allocations(award_id)
                if a["status"] in ("RESERVED", "DISBURSED")]
    max_lien = max((a["lien_position"] for a in existing), default=0)
    max_priority = max((store.funding_sources[a["funding_source_id"]]["priority"]
                        for a in existing), default=0)
    if lien_position < max_lien or source["priority"] < max_priority:
        raise ApiError("ERR_LIEN_ORDER_INVALID", "lien_position violates subordination order.")

    # Priority 18: award ceiling.
    if award["allocated_cents"] + amount_cents > award["assistance_amount_cents"]:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_AWARD",
                       "Allocation would exceed the approved award amount.")

    # Priority 19: fiscal availability.
    if amount_cents > source["available_cents"]:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", "Insufficient available funds.")

    rec = store.new_record("allocation")
    rec.update({
        "award_id": award_id,
        "funding_source_id": funding_source_id,
        "amount_cents": amount_cents,
        "lien_position": lien_position,
        "status": "RESERVED",
    })
    store.allocations[rec["id"]] = rec
    domain.reserve_on_source(source, amount_cents)
    domain.recompute_allocated(award)
    domain.maybe_auto_fund(award)
    return env.success(public(rec), 201)


@bp.get("/funding-allocations/<aid>")
def get_allocation(aid):
    ctx.authenticate(["CaseManager", "ProgramAdmin"])
    rec = ctx.lookup("allocation", aid)
    return env.success(public(rec), 200)


@bp.get("/funding-allocations")
def list_allocations():
    ctx.authenticate(["CaseManager", "ProgramAdmin"])
    limit, offset = ctx.pagination_params()
    filters = {
        "award_id": ctx.query_filter("award_id"),
        "funding_source_id": ctx.query_filter("funding_source_id"),
        "status": ctx.query_filter("status"),
    }
    page, total = ctx.paginate(store.allocations.values(), limit, offset, filters)
    return env.list_response(public_list(page), limit, offset, total)
