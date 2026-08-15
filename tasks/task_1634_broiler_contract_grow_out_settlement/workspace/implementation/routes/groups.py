"""SettlementGroup lifecycle: create, read, member flocks, lock (PRD §3.7)."""
from flask import Blueprint

import db
import utils
from helpers import check_unique, get_or_404, need_date, need_str
from middleware import body, list_response, require_roles
from response import ok
from services import domain

bp = Blueprint("groups", __name__)

ADMIN = "IntegratorAdmin"
GROWER = "Grower"
ANALYST = "SettlementAnalyst"


@bp.route("/api/settlement-groups", methods=["POST"])
@require_roles(ANALYST)
def create_group():
    b = body()
    group_code = need_str(b, "group_code")
    week_ending_date = need_date(b, "week_ending_date")
    check_unique(
        db.settlement_groups.values(), "group_code", group_code, "group_code"
    )
    rec = utils.make_record(
        {
            "group_code": group_code,
            "week_ending_date": week_ending_date,
            "status": "OPEN",
            "group_avg_fcr": None,
            "group_avg_livability_pct": None,
            "group_avg_condemnation_pct": None,
        }
    )
    db.settlement_groups[rec["id"]] = rec
    return ok(utils.pub(rec), 201)


@bp.route("/api/settlement-groups/<gid>", methods=["GET"])
@require_roles(ADMIN, ANALYST, GROWER)
def get_group(gid):
    rec = get_or_404(db.settlement_groups, gid, "SettlementGroup")
    return ok(utils.pub(rec))


@bp.route("/api/settlement-groups/<gid>/flocks", methods=["GET"])
@require_roles(ADMIN, ANALYST, GROWER)
def list_group_flocks(gid):
    get_or_404(db.settlement_groups, gid, "SettlementGroup")
    rows = [f for f in db.flocks.values() if f["settlement_group_id"] == gid]
    return list_response(rows)


@bp.route("/api/settlement-groups/<gid>/lock", methods=["POST"])
@require_roles(ANALYST)
def lock(gid):
    rec = get_or_404(db.settlement_groups, gid, "SettlementGroup")
    from errors import ApiError

    if rec["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an OPEN settlement group can be locked (current: %s)." % rec["status"],
            409,
        )
    domain.lock_group(rec)
    return ok(utils.pub(rec))
