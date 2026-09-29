"""Player registration and reads (PRD 3.2)."""
from flask import Blueprint, request

import domain
import shape
import views
from auth import ALL_ROLES, LEAGUE_OFFICER, endpoint
from envelope import filter_records, paginate, single
from store import base_record, db, values

bp = Blueprint("players", __name__)

POSITIONS = ("QB", "RB", "WR", "OL", "DL", "LB", "DB", "K")


@bp.route("/players", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def create_player(actor):
    body = shape.body()
    full_name = shape.req_str(body, "full_name", min_len=1, max_len=80)
    position = shape.req_enum(body, "position", POSITIONS)
    active_days = shape.opt_int(body, "accrued_active_days", 0, minimum=0)
    reserve_days = shape.opt_int(body, "accrued_reserve_days", 0, minimum=0)
    ir_days = shape.opt_int(body, "accrued_ir_days", 0, minimum=0)
    practice_days = shape.opt_int(body, "accrued_practice_days", 0, minimum=0)
    seasons_used = shape.opt_int(body, "practice_squad_seasons_used", 0, minimum=0)
    record = base_record()
    record.update({
        "full_name": full_name,
        "position": position,
        "current_team_id": None,
        "roster_designation": "UNROSTERED",
        "medical_status": "CLEARED",
        "designation_effective_at": db.clock,
        "accrued_active_days": active_days,
        "accrued_reserve_days": reserve_days,
        "accrued_ir_days": ir_days,
        "accrued_practice_days": practice_days,
        "practice_squad_seasons_used": seasons_used,
    })
    db.players[record["id"]] = record
    return single(views.player(record), 201)


@bp.route("/players/<player_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_player(actor, player_id):
    player = domain.get_player(player_id)
    return single(views.player(player))


@bp.route("/players", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_players(actor):
    records = values(db.players)
    records = filter_records(records, {
        "current_team_id": "current_team_id",
        "roster_designation": "roster_designation",
        "medical_status": "medical_status",
    })
    rights = request.args.get("contract_rights_class")
    if rights:
        records = [
            item for item in records if domain.contract_rights_class(item) == rights
        ]
    return paginate(records, views.player)
