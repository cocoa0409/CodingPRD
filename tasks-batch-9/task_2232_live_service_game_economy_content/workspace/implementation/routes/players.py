"""Players, currency accounts, the ledger read surface and pacing (PRD 3.4)."""
from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate, require_owner
from response import list_response, object_response, touch
from services import calc, cascades, ledger

bp = Blueprint("players", __name__)

PLAYER_READ_ROLES = (
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_PLAYER,
)
OPERATOR_READ_ROLES = (
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_ECONOMY_DESIGNER,
)
LEDGER_ROLES = (
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_COMPLIANCE_OFFICER,
)


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
@bp.post("/players")
def create_player():
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    payload = v.body()
    season = resolve.body_fk(payload, "active_season_id", db.db.seasons, "ERR_SEASON_NOT_FOUND")
    handle = v.req_string(payload, "handle")
    region_code = v.req_enum(payload, "region_code", config.REGION_CODES)
    v.req_string(payload, "active_season_id")
    is_minor = v.opt_bool(payload, "is_minor", default=False)
    guardian_verified = v.opt_bool(payload, "guardian_verified", default=False)

    for existing in db.db.players.values():
        if existing["handle"] == handle:
            fail("ERR_PLAYER_HANDLE_DUPLICATE", "A player with this handle already exists.")

    player = db.insert(
        db.db.players,
        {
            "handle": handle,
            "region_code": region_code,
            "active_season_id": season["id"],
            "is_minor": is_minor,
            "guardian_verified": guardian_verified,
            "spend_state": "UNRESTRICTED",
            "season_xp_total": 0,
            "session_count": 0,
            "last_active_at": None,
            "pacing_bp_realized": 10000,
            "retention_band": "HEALTHY",
            "spend_30d_minor": 0,
            "pending_spend_minor": 0,
            "lifetime_spend_minor": 0,
        },
    )
    return object_response(serialize(player), 201)


@bp.get("/players/<player_id>")
def read_player(player_id):
    user_id, role = authenticate(*PLAYER_READ_ROLES)
    player = resolve.player(player_id)
    require_owner(role, user_id, player["id"])
    return object_response(serialize(player))


@bp.get("/players")
def list_players():
    authenticate(*OPERATOR_READ_ROLES)
    active_season_id = request.args.get("active_season_id")
    spend_state = v.query_enum("spend_state", config.SPEND_STATES)
    retention_band = v.query_enum("retention_band", config.RETENTION_BANDS)
    limit, offset = v.pagination()
    rows = list(db.db.players.values())
    if active_season_id is not None:
        rows = [p for p in rows if p["active_season_id"] == active_season_id]
    if spend_state is not None:
        rows = [p for p in rows if p["spend_state"] == spend_state]
    if retention_band is not None:
        rows = [p for p in rows if p["retention_band"] == retention_band]
    records = [serialize(p) for p in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Currency accounts
# ---------------------------------------------------------------------------
@bp.post("/players/<player_id>/currency-accounts")
def create_account(player_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    player = resolve.player(player_id)
    payload = v.body()
    currency_code = v.req_enum(payload, "currency_code", config.CURRENCY_CODES)
    for existing in db.db.accounts.values():
        if existing["player_id"] == player["id"] and existing["currency_code"] == currency_code:
            fail(
                "ERR_DUPLICATE_CURRENCY_ACCOUNT",
                "The player already holds an account in this currency.",
            )
    account = db.insert(
        db.db.accounts,
        {
            "player_id": player["id"],
            "currency_code": currency_code,
            "balance_minor": 0,
            "lifetime_faucet_minor": 0,
            "lifetime_sink_minor": 0,
            "status": "FROZEN" if player["spend_state"] == "LOCKED" else "ACTIVE",
        },
    )
    return object_response(serialize(account), 201)


@bp.get("/players/<player_id>/currency-accounts")
def list_accounts(player_id):
    user_id, role = authenticate(*PLAYER_READ_ROLES)
    player = resolve.player(player_id)
    require_owner(role, user_id, player["id"])
    currency_code = v.query_enum("currency_code", config.CURRENCY_CODES)
    limit, offset = v.pagination()
    rows = [a for a in db.db.accounts.values() if a["player_id"] == player["id"]]
    if currency_code is not None:
        rows = [a for a in rows if a["currency_code"] == currency_code]
    records = [serialize(a) for a in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/currency-accounts/<account_id>")
def read_account(account_id):
    authenticate(*PLAYER_READ_ROLES)
    account = resolve.account(account_id)
    return object_response(serialize(account))


@bp.post("/currency-accounts/<account_id>/adjustments")
def create_adjustment(account_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    account = resolve.account(account_id)
    payload = v.body()
    purchase = None
    if payload.get("purchase_id") is not None:
        purchase = resolve.body_fk(payload, "purchase_id", db.db.purchases, "ERR_PURCHASE_NOT_FOUND")
    direction = v.req_enum(payload, "direction", config.LEDGER_DIRECTIONS)
    amount_minor = v.req_int(payload, "amount_minor", minimum=1)
    source_kind = v.req_enum(payload, "source_kind", config.LEDGER_SOURCE_KINDS)
    if payload.get("purchase_id") is not None:
        v.req_string(payload, "purchase_id")

    if account["status"] == "FROZEN":
        fail("ERR_CURRENCY_ACCOUNT_FROZEN", "The currency account is frozen.")
    if direction == "SINK" and amount_minor > account["balance_minor"]:
        fail("ERR_INSUFFICIENT_BALANCE", "The account holds less than the requested sink amount.")

    player = db.db.players.get(account["player_id"])
    season_id = player["active_season_id"] if player is not None else None
    entry = ledger.append_entry(
        account,
        direction,
        amount_minor,
        source_kind,
        season_id,
        purchase_id=purchase["id"] if purchase is not None else None,
    )
    if purchase is not None and direction == "SINK" and source_kind == "OFFER_SPEND":
        purchase["granted_consumed_minor"] += amount_minor
        touch(purchase)
    return object_response(serialize(entry), 201)


# ---------------------------------------------------------------------------
# Engagement, spend guard, pacing
# ---------------------------------------------------------------------------
@bp.post("/players/<player_id>/engagement-events")
def ingest_engagement(player_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    player = resolve.player(player_id)
    payload = v.body()
    xp_delta = v.req_int(payload, "xp_delta")
    sessions_delta = v.opt_int(payload, "sessions_delta", default=0)
    occurred_at = v.opt_datetime(payload, "occurred_at", default=db.now())

    player["season_xp_total"] += xp_delta
    player["session_count"] += sessions_delta
    player["last_active_at"] = occurred_at
    calc.refresh_realized_pacing(player)
    touch(player)
    return object_response(serialize(player))


@bp.post("/players/<player_id>/spend-guard")
def spend_guard(player_id):
    authenticate(config.ROLE_COMPLIANCE_OFFICER)
    player = resolve.player(player_id)
    payload = v.body()
    action = v.req_enum(payload, "action", ("LOCK", "UNLOCK"))
    v.opt_string(payload, "note")

    if action == "LOCK":
        if player["spend_state"] != "LOCKED":
            cascades.lock_player(player)
    else:
        if player["spend_state"] == "LOCKED":
            cascades.unlock_player(player)
    return object_response(serialize(player))


@bp.get("/players/<player_id>/pacing")
def read_pacing(player_id):
    user_id, role = authenticate(*PLAYER_READ_ROLES)
    player = resolve.player(player_id)
    variant = request.args.get("variant")
    if variant is None:
        v.bad("variant", "is required")
    if variant not in ("REALIZED", "PROJECTED"):
        v.bad("variant", "must be one of REALIZED, PROJECTED")
    require_owner(role, user_id, player["id"])

    season = db.db.seasons.get(player["active_season_id"])
    result = calc.pacing(player, season, variant)
    data = {"player_id": player["id"], "variant": variant}
    data.update(result)
    return object_response(data)


# ---------------------------------------------------------------------------
# Ledger reads
# ---------------------------------------------------------------------------
@bp.get("/ledger-entries")
def list_ledger_entries():
    authenticate(*LEDGER_ROLES)
    currency_account_id = request.args.get("currency_account_id")
    season_id = request.args.get("season_id")
    purchase_id = request.args.get("purchase_id")
    reversal_of_entry_id = request.args.get("reversal_of_entry_id")
    direction = v.query_enum("direction", config.LEDGER_DIRECTIONS)
    source_kind = v.query_enum("source_kind", config.LEDGER_SOURCE_KINDS)
    limit, offset = v.pagination()

    rows = list(db.db.ledger.values())
    if currency_account_id is not None:
        rows = [e for e in rows if e["currency_account_id"] == currency_account_id]
    if season_id is not None:
        rows = [e for e in rows if e["season_id"] == season_id]
    if purchase_id is not None:
        rows = [e for e in rows if e["purchase_id"] == purchase_id]
    if reversal_of_entry_id is not None:
        rows = [e for e in rows if e["reversal_of_entry_id"] == reversal_of_entry_id]
    if direction is not None:
        rows = [e for e in rows if e["direction"] == direction]
    if source_kind is not None:
        rows = [e for e in rows if e["source_kind"] == source_kind]
    records = [serialize(e) for e in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/ledger-entries/<entry_id>")
def read_ledger_entry(entry_id):
    authenticate(*LEDGER_ROLES)
    entry = resolve.ledger_entry(entry_id)
    return object_response(serialize(entry))
