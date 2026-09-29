"""Peer groups, memberships, screening and approval (PRD §3.2)."""

from flask import Blueprint

import calc
from db import apply_changes, insert, store, touch
from errors import ApiError
from middleware import ROLE_CHAIR, ROLE_COMP_CONSULTANT, ROLE_COUNSEL, authenticate
from response import object_response
from routes.common import body_fk, fetch, paginated
from services import domain
from validation import Body

bp = Blueprint("peer_groups", __name__)

BENCHMARK_BASES = {"RAW_MEDIAN", "SIZE_ADJUSTED"}
INCLUSION_REASONS = {
    "SIZE_MATCH",
    "INDUSTRY_MATCH",
    "BUSINESS_MODEL_ANALOG",
    "TALENT_COMPETITOR",
}
OUT_OF_BAND_ALLOWED_AT_ADD = {"BUSINESS_MODEL_ANALOG", "TALENT_COMPETITOR"}
OUT_OF_BAND_ALLOWED_AT_SCREEN = {"BUSINESS_MODEL_ANALOG"}


@bp.post("/exec-comp/peer-groups")
def create_peer_group():
    authenticate([ROLE_COMP_CONSULTANT])
    body = Body()
    issuer = body_fk(body, "issuer_company_id", "companies")
    if issuer is None:
        raise ApiError("ERR_INVALID_REQUEST", "issuer_company_id is required")
    fiscal_year = body.integer(
        "fiscal_year", required=True, minimum=2020, maximum=2035
    )
    benchmark_basis = body.enum(
        "benchmark_basis", BENCHMARK_BASES, default="RAW_MEDIAN"
    )
    if not issuer["is_issuer"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "issuer_company_id must name the company flagged as issuer",
        )
    group = insert(
        store.peer_groups,
        {
            "issuer_company_id": issuer["id"],
            "fiscal_year": fiscal_year,
            "benchmark_basis": benchmark_basis,
            "status": "DRAFT",
            "accepted_member_count": 0,
            "median_revenue_usd": None,
            "median_market_cap_usd": None,
            "benchmark_target_tdc_raw_usd": None,
            "benchmark_target_tdc_adjusted_usd": None,
            "benchmark_target_tdc_usd": None,
            "size_fit_score": None,
            "screened_at": None,
            "approved_by_user_id": None,
        },
    )
    return object_response(group, 201)


@bp.get("/exec-comp/peer-groups/<gid>")
def read_peer_group(gid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    return object_response(fetch("peer_groups", gid))


@bp.get("/exec-comp/peer-groups/<gid>/members")
def list_members(gid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    group = fetch("peer_groups", gid)
    return paginated(domain.group_members(group["id"]))


@bp.post("/exec-comp/peer-groups/<gid>/members")
def add_member(gid):
    authenticate([ROLE_COMP_CONSULTANT])
    group = fetch("peer_groups", gid)
    body = Body()
    peer = body_fk(body, "peer_company_id", "companies")
    if peer is None:
        raise ApiError("ERR_INVALID_REQUEST", "peer_company_id is required")
    inclusion_reason = body.enum("inclusion_reason", INCLUSION_REASONS, required=True)
    expected_version = body.integer("expected_peer_group_version", required=True)

    if expected_version != group["version"]:
        raise ApiError("ERR_STALE_PEER_GROUP_VERSION")
    if group["status"] != "DRAFT":
        raise ApiError("ERR_PEER_GROUP_NOT_MUTABLE")
    if peer["listing_status"] == "DELISTED":
        raise ApiError("ERR_PEER_COMPANY_DELISTED")
    if peer["id"] == group["issuer_company_id"]:
        raise ApiError("ERR_PEER_IS_ISSUER")
    for existing in domain.group_members(group["id"]):
        if existing["peer_company_id"] == peer["id"]:
            raise ApiError("ERR_PEER_ALREADY_IN_GROUP")

    issuer = store.companies[group["issuer_company_id"]]
    revenue_ratio, market_cap_ratio, in_band = calc.size_band_fit(issuer, peer)
    if not in_band and inclusion_reason not in OUT_OF_BAND_ALLOWED_AT_ADD:
        raise ApiError("ERR_PEER_OUTSIDE_SIZE_BAND")

    member = insert(
        store.peer_group_members,
        {
            "peer_group_id": group["id"],
            "peer_company_id": peer["id"],
            "inclusion_reason": inclusion_reason,
            "revenue_ratio": revenue_ratio,
            "market_cap_ratio": market_cap_ratio,
            "in_size_band": in_band,
            "status": "ACCEPTED",
            "exclusion_reason": None,
        },
    )
    apply_changes(
        group, {"accepted_member_count": group["accepted_member_count"] + 1}
    )
    touch(group)
    return object_response(member, 201)


@bp.post("/exec-comp/peer-group-members/<mid>/exclude")
def exclude_member(mid):
    authenticate([ROLE_COMP_CONSULTANT])
    member = fetch("peer_group_members", mid)
    body = Body()
    exclusion_reason = body.string("exclusion_reason", required=True, max_len=500)

    group = store.peer_groups[member["peer_group_id"]]
    if group["status"] not in ("DRAFT", "SCREENED"):
        raise ApiError("ERR_PEER_GROUP_NOT_MUTABLE")
    if member["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_PEER_GROUP_NOT_MUTABLE", "this membership has already been excluded"
        )

    # L1
    apply_changes(
        member, {"status": "EXCLUDED", "exclusion_reason": exclusion_reason}
    )
    # L2
    domain.recompute_accepted_member_count(group)
    reverted = False
    if group["status"] == "SCREENED":
        domain.revert_group_to_draft(group)
        reverted = True
    touch(group)
    # L3 + L4
    if reverted:
        domain.clear_dependent_draft_programs(group)
    return object_response(member)


@bp.post("/exec-comp/peer-groups/<gid>/screen")
def screen(gid):
    authenticate([ROLE_COMP_CONSULTANT])
    group = fetch("peer_groups", gid)
    if group["status"] != "DRAFT":
        raise ApiError("ERR_PEER_GROUP_NOT_MUTABLE")
    members = domain.group_members(group["id"], accepted_only=True)
    for member in members:
        if (
            not member["in_size_band"]
            and member["inclusion_reason"] not in OUT_OF_BAND_ALLOWED_AT_SCREEN
        ):
            raise ApiError("ERR_PEER_OUTSIDE_SIZE_BAND")
    if not members:
        raise ApiError("ERR_PEER_GROUP_EMPTY")
    domain.screen_group(group)
    return object_response(group)


@bp.post("/exec-comp/peer-groups/<gid>/approve")
def approve(gid):
    user_id, _ = authenticate([ROLE_CHAIR])
    group = fetch("peer_groups", gid)
    if group["status"] != "SCREENED":
        raise ApiError("ERR_PEER_GROUP_NOT_SCREENED")
    if group["benchmark_target_tdc_usd"] is None:
        raise ApiError("ERR_PEER_GROUP_NOT_SCREENED", "the benchmark is not computed")
    apply_changes(group, {"status": "APPROVED", "approved_by_user_id": user_id})
    touch(group)
    domain.push_group_benchmark(group)
    return object_response(group)
