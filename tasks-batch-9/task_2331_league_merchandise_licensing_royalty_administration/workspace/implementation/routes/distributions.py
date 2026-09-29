"""Central-pool distribution runs and club distributions (PRD 3.9)."""

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, touch
from errors import ApiError
from middleware import (ROLE_AUDITOR, ROLE_CLUB, ROLE_FINANCE, ROLE_MANAGER, guard,
                        paginate, pagination)
from routes.reports import effective_royalty
from services import calc, domain

bp = Blueprint("distributions", __name__)

READ_ROLES = [ROLE_MANAGER, ROLE_FINANCE, ROLE_AUDITOR, ROLE_CLUB]

ELIGIBLE_REPORT_STATUSES = ("ACCEPTED", "ADJUSTED", "CLOSED")


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def _find_run(run_id):
    row = S.runs.get(run_id)
    if row is None:
        raise ApiError("ERR_RUN_NOT_FOUND")
    return row


def _central_agreement(report):
    agreement = S.agreements.get(report["agreement_id"])
    return agreement if agreement and agreement["central_licensing_flag"] else None


def _pending_reports_block(period_quarter):
    for report in S.reports.values():
        if report["period_quarter"] != period_quarter:
            continue
        if report["status"] not in ("FILED", "RETURNED"):
            continue
        if _central_agreement(report) is not None:
            raise ApiError("ERR_PENDING_REPORTS_BLOCK_DISTRIBUTION")


def _eligible_reports(period_quarter):
    rows = []
    for report in S.reports.values():
        if report["period_quarter"] != period_quarter:
            continue
        if report["status"] not in ELIGIBLE_REPORT_STATUSES:
            continue
        if _central_agreement(report) is None:
            continue
        rows.append(report)
    return sorted(rows, key=lambda r: r["created_at"])


def _check_version(run, body):
    expected = V.req_int(body, "expected_run_version")
    if expected != run["version"]:
        raise ApiError("ERR_STALE_DISTRIBUTION_VERSION")


# --------------------------------------------------------------------------- #
# opening and reads                                                           #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/distribution-runs")
def create_run():
    ctx = guard([ROLE_FINANCE])
    body = ctx.body
    period_quarter = V.req_quarter(body, "period_quarter")
    rate = V.opt_int(body, "league_admin_rate_bps", K.LEAGUE_ADMIN_RATE_DEFAULT_BPS)
    if rate < 0 or rate > 3000:
        _bad("league_admin_rate_bps must be between 0 and 3000.")

    for run in S.runs.values():
        if run["period_quarter"] == period_quarter:
            _bad("A distribution run already exists for this quarter.")

    row = db.base_row()
    row.update({
        "period_quarter": period_quarter,
        "league_admin_rate_bps": rate,
        "status": "OPEN",
        "projected_pool_cents": 0,
        "pool_gross_cents": 0,
        "league_admin_cents": 0,
        "player_pool_cents": 0,
        "club_pool_cents": 0,
        "report_count": 0,
        "locked_at": None,
        "distributed_at": None,
    })
    S.runs[row["id"]] = row
    return response.created(serializers.dump("DistributionRun", row))


@bp.get("/licensing/distribution-runs")
def list_runs():
    guard(READ_ROLES)
    limit, offset = pagination()
    period_quarter = mw.filter_str("period_quarter")
    status = mw.filter_enum("status", K.RUN_STATUSES)

    rows = list(S.runs.values())
    if period_quarter is not None:
        rows = [r for r in rows if r["period_quarter"] == period_quarter]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("DistributionRun", page),
                            limit, offset, total)


@bp.get("/licensing/distribution-runs/<run_id>")
def get_run(run_id):
    guard(READ_ROLES)
    run = _find_run(run_id)
    return response.ok(serializers.dump("DistributionRun", run))


# --------------------------------------------------------------------------- #
# lock / unlock                                                               #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/distribution-runs/<run_id>/lock")
def lock_run(run_id):
    ctx = guard([ROLE_FINANCE])
    run = _find_run(run_id)
    _check_version(run, ctx.body)
    if run["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    _pending_reports_block(run["period_quarter"])

    run["status"] = "LOCKED"
    run["locked_at"] = db.now_iso()
    touch(run)
    return response.ok(serializers.dump("DistributionRun", run))


@bp.post("/licensing/distribution-runs/<run_id>/unlock")
def unlock_run(run_id):
    guard([ROLE_FINANCE])
    run = _find_run(run_id)
    if run["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE")
    run["status"] = "OPEN"
    run["locked_at"] = None
    touch(run)
    return response.ok(serializers.dump("DistributionRun", run))


# --------------------------------------------------------------------------- #
# distribute                                                                  #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/distribution-runs/<run_id>/distribute")
def distribute_run(run_id):
    ctx = guard([ROLE_FINANCE])
    run = _find_run(run_id)
    _check_version(run, ctx.body)
    if run["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE")
    _pending_reports_block(run["period_quarter"])

    eligible = _eligible_reports(run["period_quarter"])
    clubs = [c for c in S.clubs.values() if c["status"] == "ACTIVE"]
    if not eligible or not clubs:
        raise ApiError("ERR_EMPTY_DISTRIBUTION_POOL")

    pool_gross = 0
    player_basis = 0
    for report in eligible:
        royalty = effective_royalty(report)
        pool_gross += royalty
        agreement = S.agreements[report["agreement_id"]]
        category = domain.category_of(agreement)
        if category["mark_usage_class"] == "LEAGUE_CLUB_AND_PLAYER":
            player_basis += royalty

    league_admin = calc.apply_rate_half_up(pool_gross, run["league_admin_rate_bps"])
    player_pool = calc.apply_rate_half_up(player_basis, calc.GROUP_LICENSING_SHARE_BPS)
    club_pool = pool_gross - league_admin - player_pool

    allocations = calc.split_club_pool(club_pool, clubs)
    for allocation in allocations:
        club = allocation["club"]
        row = db.base_row(versioned=False)
        row.update({
            "run_id": run["id"],
            "club_id": club["id"],
            "club_code": club["club_code"],
            "revenue_share_units_snapshot": club["revenue_share_units"],
            "equal_component_cents": allocation["equal_component_cents"],
            "weighted_component_cents": allocation["weighted_component_cents"],
            "remainder_cent_applied": allocation["remainder_cent_applied"],
            "amount_cents": allocation["amount_cents"],
        })
        S.club_distributions[row["id"]] = row

    for allocation in allocations:
        club = allocation["club"]
        lifetime = sum(d["amount_cents"] for d in S.club_distributions.values()
                       if d["club_id"] == club["id"])
        club["lifetime_distributed_cents"] = lifetime
        touch(club)

    run["status"] = "DISTRIBUTED"
    run["pool_gross_cents"] = pool_gross
    run["league_admin_cents"] = league_admin
    run["player_pool_cents"] = player_pool
    run["club_pool_cents"] = club_pool
    run["report_count"] = len(eligible)
    run["distributed_at"] = db.now_iso()
    touch(run)
    return response.ok(serializers.dump("DistributionRun", run))


# --------------------------------------------------------------------------- #
# club distributions                                                          #
# --------------------------------------------------------------------------- #

@bp.get("/licensing/club-distributions")
def list_club_distributions():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    run_id = mw.filter_str("run_id")
    club_id = mw.filter_str("club_id")

    rows = list(S.club_distributions.values())
    if ctx.role == ROLE_CLUB:
        rows = [r for r in rows if r["club_id"] == ctx.uid]
    if run_id is not None:
        rows = [r for r in rows if r["run_id"] == run_id]
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("ClubDistribution", page),
                            limit, offset, total)


@bp.get("/licensing/club-distributions/<distribution_id>")
def get_club_distribution(distribution_id):
    ctx = guard(READ_ROLES)
    row = S.club_distributions.get(distribution_id)
    if row is None:
        raise ApiError("ERR_RUN_NOT_FOUND")
    mw.scope_club(ctx, row["club_id"])
    return response.ok(serializers.dump("ClubDistribution", row))
