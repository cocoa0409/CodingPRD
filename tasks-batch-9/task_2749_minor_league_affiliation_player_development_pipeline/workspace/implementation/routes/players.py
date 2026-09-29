"""Player and medical clearance endpoints (PRD Section 3.5)."""
from decimal import Decimal

from flask import Blueprint

import auth
import common
import config
import derive
import envelope
import flows
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("players", __name__)

CLEARANCE_TRANSITIONS = {
    "ISSUE": ("REQUESTED",),
    "DENY": ("REQUESTED",),
    "REVOKE": ("ISSUED",),
}

ASSIGNMENT_TYPES_FOR_CLEARANCE = {
    "LEVEL_ASSIGNMENT": ("LEVEL", "COMPLEX"),
    "REHAB_START": ("REHAB",),
    "REHAB_COMPLETE": (),
}


@bp.post("/players")
def create_player():
    auth.require(config.ROLE_FARM, config.ROLE_SCOUT)
    body = validate.json_body()
    full_name = validate.str_field(body, "full_name", min_len=1, max_len=120)
    origin = validate.enum_field(body, "origin", config.ORIGINS)
    signed_date = validate.date_field(body, "signed_date")
    service_days = validate.int_field(body, "service_days_accrued", lo=0, hi=2000,
                                      required=False, default=0)

    record = store.base_record()
    record.update({
        "full_name": full_name,
        "origin": origin,
        "signed_date": signed_date,
        "service_days_accrued": service_days,
        "roster_status": "RESERVE_LIST",
        "medical_status": "PENDING_CLEARANCE",
        "is_on_domestic_reserve_list": origin in ("DOMESTIC_DRAFT", "FOREIGN_PRO"),
        "current_affiliate_id": None,
        "option_years_used": 0,
        "option_years_remaining": config.OPTION_YEARS_TOTAL,
        "workload_index": Decimal("0.00"),
        "workload_index_projected": Decimal("0.00"),
        "promotion_readiness": Decimal("0.0000"),
    })
    store.players[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.player(record), 201)


@bp.get("/players")
def list_players():
    auth.require(config.ROLE_FARM, config.ROLE_MEDICAL, config.ROLE_COMPLIANCE,
                 config.ROLE_SCOUT)
    rows = list(store.players.values())
    rows = common.apply_filters(rows, (("roster_status", "roster_status"),
                                       ("medical_status", "medical_status"),
                                       ("origin", "origin")))
    return envelope.paginate(rows, serialize.player)


@bp.get("/players/<player_id>")
def read_player(player_id):
    auth.require(*config.ALL_ROLES)
    record = common.need("players", player_id)
    return envelope.object_response(serialize.player(record))


@bp.post("/players/<player_id>/medical-clearances")
def request_clearance(player_id):
    user_id, _role = auth.require(config.ROLE_FARM, config.ROLE_MEDICAL)
    common.need("players", player_id)
    body = validate.json_body()
    clearance_type = validate.enum_field(body, "clearance_type", config.CLEARANCE_TYPES)

    record = store.base_record()
    record.update({
        "player_id": player_id,
        "clearance_type": clearance_type,
        "status": "REQUESTED",
        "requested_by_user_id": user_id,
        "issued_by_user_id": None,
        "cleared_workload_ceiling_index": None,
        "expires_on": None,
        "restriction_note": None,
        "is_expired": False,
    })
    store.clearances[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.clearance(record), 201)


@bp.get("/players/<player_id>/medical-clearances")
def list_clearances(player_id):
    auth.require(config.ROLE_FARM, config.ROLE_MEDICAL, config.ROLE_COMPLIANCE)
    common.need("players", player_id)
    rows = derive.clearances_of_player(player_id)
    rows = common.apply_filters(rows, (("clearance_type", "clearance_type"),
                                       ("status", "status")))
    return envelope.paginate(rows, serialize.clearance)


@bp.post("/medical-clearances/<clearance_id>/disposition")
def dispose_clearance(clearance_id):
    user_id, role = auth.require(config.ROLE_MEDICAL)
    raw = auth.raw_body()
    auth.check_action_role(raw.get("action"), role, config.CLEARANCE_ACTION_ROLES)
    clearance = common.need("clearances", clearance_id)
    body = validate.json_body()
    action = auth.require_action(body, config.CLEARANCE_ACTION_ROLES)
    ceiling = validate.dec_field(body, "cleared_workload_ceiling_index", lo=0,
                                 required=False, default=None, places=2)
    restriction_note = validate.str_field(body, "restriction_note", required=False,
                                          default=None, allow_blank=True)
    expires_on = validate.date_field(body, "expires_on", required=False, default=None)
    if action == "ISSUE":
        if expires_on is None:
            raise validate.bad("Field 'expires_on' is required to issue a clearance.")
        if store.parse_date(expires_on) <= store.clock_date():
            raise validate.bad("expires_on must be strictly after the current clock date.")

    player = store.players.get(clearance["player_id"])

    if clearance["status"] not in CLEARANCE_TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_CLEARANCE_STATE",
                       "A clearance in status %s does not accept %s."
                       % (clearance["status"], action))

    if action == "ISSUE" and clearance["clearance_type"] == "REHAB_COMPLETE":
        rehab = [a for a in derive.assignments_of_player(clearance["player_id"])
                 if a["assignment_type"] == "REHAB" and a["status"] == "ACTIVE"]
        if not rehab:
            raise ApiError("ERR_REHAB_ASSIGNMENT_REQUIRED")

    store.touch(clearance)
    if action == "ISSUE":
        clearance["status"] = "ISSUED"
        clearance["issued_by_user_id"] = user_id
        clearance["cleared_workload_ceiling_index"] = ceiling
        clearance["expires_on"] = expires_on
        if player is not None:
            player["medical_status"] = "CLEARED"
            has_active = any(a["status"] == "ACTIVE"
                             for a in derive.assignments_of_player(player["id"]))
            if player["roster_status"] == "RESTRICTED" and not has_active:
                player["roster_status"] = "RESERVE_LIST"
    elif action == "DENY":
        clearance["status"] = "DENIED"
        clearance["restriction_note"] = restriction_note
        if player is not None:
            player["medical_status"] = "RESTRICTED"
            if player["roster_status"] == "RESERVE_LIST":
                player["roster_status"] = "RESTRICTED"
    elif action == "REVOKE":
        clearance["status"] = "REVOKED"
        clearance["restriction_note"] = restriction_note
        types = ASSIGNMENT_TYPES_FOR_CLEARANCE[clearance["clearance_type"]]
        for assignment in store.sorted_rows(
                derive.assignments_of_player(clearance["player_id"])):
            if assignment["status"] == "ACTIVE" and assignment["assignment_type"] in types:
                flows.suspend_assignment(assignment, by_clearance_revocation=True)
        if player is not None:
            remaining = [c for c in derive.issued_clearances(player["id"])
                         if c["id"] != clearance["id"]
                         and not derive.clearance_is_expired(c)]
            if not remaining:
                player["medical_status"] = "RESTRICTED"
            player["roster_status"] = "RESTRICTED"

    common.commit()
    return envelope.object_response(serialize.clearance(clearance))
