"""ReserveComponent + ReserveStudy endpoints."""
from __future__ import annotations

import math

from flask import Blueprint, request

import db
from errors import ERR_DUPLICATE_RESERVE_STUDY, raise_err
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
)


bp = Blueprint("reserves", __name__)

HORIZON_YEARS = 30


# ---------------------------------------------------------------------------
# ReserveComponent
# ---------------------------------------------------------------------------
def _serialize_component(c: dict) -> dict:
    return {
        "id": c["id"],
        "community_id": c["community_id"],
        "label": c["label"],
        "useful_life_years": int(c["useful_life_years"]),
        "remaining_life_years": int(c["remaining_life_years"]),
        "replacement_cost_cents": int(c["replacement_cost_cents"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/hoa/reserve-components", methods=["POST"])
@auth_required({"PlatformAdmin", "BoardPresident"})
def create_reserve_component():
    body = get_json_body()
    community_id = require_str(body, "community_id")
    label = require_str(body, "label")
    useful = require_int(body, "useful_life_years", min_value=1)
    remaining = require_int(body, "remaining_life_years", min_value=0)
    cost = require_int(body, "replacement_cost_cents", min_value=0)

    fetch_or_404(db.communities, community_id, "Community")

    # label unique within community
    for existing in db.reserve_components.values():
        if (existing["community_id"] == community_id
                and existing["label"] == label):
            raise_err("ERR_INVALID_REQUEST",
                      f"ReserveComponent label already used: {label}")

    record = {
        **db.make_common_fields(),
        "community_id": community_id,
        "label": label,
        "useful_life_years": useful,
        "remaining_life_years": remaining,
        "replacement_cost_cents": cost,
    }
    db.reserve_components[record["id"]] = record
    return success(_serialize_component(record), status=201)


@bp.route("/hoa/reserve-components/<cid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer"})
def fetch_reserve_component(cid):
    c = fetch_or_404(db.reserve_components, cid, "ReserveComponent")
    return success(_serialize_component(c))


@bp.route("/hoa/reserve-components", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer"})
def list_reserve_components():
    limit, offset = parse_pagination()
    community_id = request.args.get("community_id")
    rows = list(db.reserve_components.values())
    if community_id is not None:
        rows = [r for r in rows if r["community_id"] == community_id]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize_component(r) for r in page],
                        total, limit, offset)


# ---------------------------------------------------------------------------
# ReserveStudy
# ---------------------------------------------------------------------------
def _serialize_study(s: dict) -> dict:
    return {
        "id": s["id"],
        "community_id": s["community_id"],
        "fiscal_year": int(s["fiscal_year"]),
        "method": s["method"],
        "accumulated_funds_cents": int(s["accumulated_funds_cents"]),
        "projected_obligation_cents": int(s["projected_obligation_cents"]),
        "percent_funded_bps": int(s["percent_funded_bps"]),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _compute_obligation_component(community: dict, components: list) -> int:
    bps = int(community["reserve_inflation_bps"])
    total = 0
    for c in components:
        factor = (1 + bps / 10000.0) ** int(c["remaining_life_years"])
        inflated = math.floor(int(c["replacement_cost_cents"]) * factor)
        total += int(inflated)
    return total


def _compute_obligation_cash_flow(community: dict, components: list) -> int:
    bps = int(community["reserve_inflation_bps"])
    annual_draw = [0.0] * HORIZON_YEARS
    for c in components:
        rep = int(c["replacement_cost_cents"])
        useful = int(c["useful_life_years"])
        year = int(c["remaining_life_years"])
        while year < HORIZON_YEARS:
            factor = (1 + bps / 10000.0) ** year
            annual_draw[year] += rep * factor
            year += useful
    return int(math.floor(sum(annual_draw)))


def _compute_percent_funded_bps(accumulated: int, obligation: int) -> int:
    if obligation == 0:
        return 10000
    # floor(accumulated * 10000 / obligation)
    return (accumulated * 10000) // obligation


@bp.route("/hoa/reserve-studies", methods=["POST"])
@auth_required({"BoardPresident"})
def create_reserve_study():
    body = get_json_body()
    community_id = require_str(body, "community_id")
    fiscal_year = require_int(body, "fiscal_year", min_value=1)
    method = require_enum(body, "method", {"COMPONENT", "CASH_FLOW"})
    accumulated = require_int(body, "accumulated_funds_cents", min_value=0)

    community = fetch_or_404(db.communities, community_id, "Community")

    # (community_id, fiscal_year) uniqueness (priority 15)
    for existing in db.reserve_studies.values():
        if (existing["community_id"] == community_id
                and int(existing["fiscal_year"]) == fiscal_year):
            raise_err(ERR_DUPLICATE_RESERVE_STUDY,
                      f"ReserveStudy already exists for fiscal year {fiscal_year}")

    # Pull components for this community
    components = [c for c in db.reserve_components.values()
                  if c["community_id"] == community_id]
    if method == "COMPONENT":
        obligation = _compute_obligation_component(community, components)
    else:
        obligation = _compute_obligation_cash_flow(community, components)
    pct_bps = _compute_percent_funded_bps(accumulated, obligation)

    record = {
        **db.make_common_fields(),
        "community_id": community_id,
        "fiscal_year": fiscal_year,
        "method": method,
        "accumulated_funds_cents": accumulated,
        "projected_obligation_cents": int(obligation),
        "percent_funded_bps": int(pct_bps),
    }
    db.reserve_studies[record["id"]] = record
    return success(_serialize_study(record), status=201)


@bp.route("/hoa/reserve-studies/<sid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer"})
def fetch_reserve_study(sid):
    s = fetch_or_404(db.reserve_studies, sid, "ReserveStudy")
    return success(_serialize_study(s))


@bp.route("/hoa/reserve-studies", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer"})
def list_reserve_studies():
    limit, offset = parse_pagination()
    community_id = request.args.get("community_id")
    fiscal_year = request.args.get("fiscal_year")
    rows = list(db.reserve_studies.values())
    if community_id is not None:
        rows = [r for r in rows if r["community_id"] == community_id]
    if fiscal_year is not None:
        try:
            fy = int(fiscal_year)
        except ValueError:
            raise_err("ERR_INVALID_REQUEST", "fiscal_year must be an integer")
        rows = [r for r in rows if int(r["fiscal_year"]) == fy]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize_study(r) for r in page],
                        total, limit, offset)
