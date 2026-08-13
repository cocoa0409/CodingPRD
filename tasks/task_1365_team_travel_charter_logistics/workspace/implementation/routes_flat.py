"""Flat single-resource and filtered-list accessors under /travel."""
from flask import Blueprint, g

from util import apply_filters, not_found, paginate, team_member_read_guard
from envelope import ok, ok_list
from state import STORE, public
from routes_core import serialize_season

bp = Blueprint("flat", __name__)

# collection segment -> (store key, not-found kind, allowed filters, member-backed)
SPECS = {
    "seasons": ("seasons", "season", ["team_id"], False),
    "trips": ("trips", "trip", ["team_id", "season_id"], False),
    "members": ("members", "member", ["trip_id"], True),
    "charter-contracts": ("contracts", "contract", ["trip_id"], False),
    "flight-legs": ("legs", "leg", ["trip_id", "contract_id"], False),
    "manifest-entries": ("entries", "entry", ["flight_leg_id", "member_id"], True),
    "hotel-blocks": ("blocks", "block", ["trip_id"], False),
    "rooms": ("rooms", "room", ["hotel_block_id", "member_id", "roommate_member_id"], True),
    "per-diem": ("ledgers", "ledger", ["member_id"], True),
    "equipment": ("shipments", "shipment", ["trip_id", "assigned_contract_id"], False),
    "contingencies": ("events", "event", ["trip_id", "affected_leg_id"], False),
    "credentials": ("credentials", "credential", ["trip_id", "member_id"], True),
}


def _serialize(coll, res):
    if coll == "seasons":
        return serialize_season(res)
    return public(res)


def register(segment):
    store_key, kind, filters, member_backed = SPECS[segment]

    def get_one(res_id):
        res = STORE[store_key].get(res_id)
        if res is None:
            raise not_found(kind)
        if segment == "members":
            team_member_read_guard(res)
        elif member_backed:
            team_member_read_guard(res)
        return ok(_serialize(segment, res), 200)

    def list_all():
        items = sorted(STORE[store_key].values(), key=lambda r: (r["created_at"], r["_seq"]))
        if g.user_role == "TeamMember":
            if segment == "members":
                items = [r for r in items if r["id"] == g.user_id]
            elif member_backed:
                items = [
                    r
                    for r in items
                    if r.get("member_id") == g.user_id
                    or r.get("roommate_member_id") == g.user_id
                ]
        items = apply_filters(items, filters)
        page, total, limit, offset = paginate(items)
        return ok_list([_serialize(segment, r) for r in page], total, limit, offset)

    get_one.__name__ = "flat_get_" + segment.replace("-", "_")
    list_all.__name__ = "flat_list_" + segment.replace("-", "_")
    bp.add_url_rule(
        "/travel/%s/<res_id>" % segment, view_func=get_one, methods=["GET"]
    )
    bp.add_url_rule("/travel/%s" % segment, view_func=list_all, methods=["GET"])


for _segment in SPECS:
    register(_segment)
