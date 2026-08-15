"""FuelingSession endpoints: authorize, authorize-public, complete, void, list, get."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

from db import STORE, new_id, now_utc, month_of
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_DISPENSER_NOT_FOUND,
    ERR_FLEET_CARD_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
    ERR_CARD_OWNERSHIP_MISMATCH,
    ERR_ACCOUNT_OWNERSHIP_MISMATCH,
    ERR_FORBIDDEN_ROLE,
    ERR_STATION_NOT_ACTIVE,
    ERR_DISPENSER_NOT_IN_SERVICE,
    ERR_CARD_NOT_ACTIVE,
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_STATION_OUTAGE,
    ERR_ACCESS_MODE_MISMATCH,
    ERR_DUPLICATE_CLIENT_REF,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_DAILY_LIMIT_EXCEEDED,
    ERR_SESSION_NOT_COMPLETABLE,
    ERR_SESSION_NOT_VOIDABLE,
)
from middleware import get_caller, require_role, check_card_ownership
from response import success_object, success_list
from serializers import fueling_session_out
from services.core import (
    GGE_KG,
    touch,
    round_half_up_3,
    round_half_up_cents,
)
from services.pricing import resolve_unit_price_private, resolve_unit_price_public
from validators import (
    body, require_fields, require_string, require_positive_number,
    parse_pagination, paginate,
)

bp = Blueprint("sessions", __name__)

_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
         "FleetAccountManager", "FleetDriver"]


def get_session_or_404(sid: str) -> dict:
    s = STORE.fueling_sessions.get(sid)
    if s is None:
        raise ApiError(ERR_SESSION_NOT_FOUND, 404, "Fueling session id does not exist")
    return s


def _access_mode_serves(access_mode: str, access_type: str) -> bool:
    if access_mode == "DUAL":
        return True
    return access_mode == access_type


def _find_ref_session(station_id: str, client_ref: str) -> list[dict]:
    """Non-VOIDED sessions at this station with this client_ref, oldest first."""
    matches = [
        s for s in STORE.fueling_sessions.values()
        if s["station_id"] == station_id
        and s["client_ref"] == client_ref
        and s["status"] != "VOIDED"
    ]
    matches.sort(key=lambda s: (s["created_at"], s["id"]))
    return matches


@bp.post("/cng/fueling-sessions/authorize")
def authorize_private():
    caller = get_caller()
    require_role(caller, ["FleetDriver"])
    data = body()
    require_fields(data, ["fleet_card_id", "dispenser_id", "client_ref",
                          "estimated_gge", "expected_fleet_account_version"])
    fleet_card_id = require_string(data, "fleet_card_id")
    dispenser_id = require_string(data, "dispenser_id")
    client_ref = require_string(data, "client_ref")
    estimated_gge = require_positive_number(data, "estimated_gge")
    eav = data.get("expected_fleet_account_version")
    if isinstance(eav, bool) or not isinstance(eav, int):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_fleet_account_version must be an integer")

    # Existence (stage 4): body FKs in order fleet_card_id, dispenser_id
    card = STORE.fleet_cards.get(fleet_card_id)
    if card is None:
        raise ApiError(ERR_FLEET_CARD_NOT_FOUND, 404, "Fleet card id does not exist")
    dispenser = STORE.dispensers.get(dispenser_id)
    if dispenser is None:
        raise ApiError(ERR_DISPENSER_NOT_FOUND, 404, "Dispenser id does not exist")

    # Ownership (stage 5)
    check_card_ownership(caller, fleet_card_id)

    account = STORE.fleet_accounts.get(card["fleet_account_id"])
    station = STORE.stations.get(dispenser["station_id"])

    # Idempotency: same client_ref + same card -> return original session.
    # Must come after ownership check but before state gates so that retries
    # succeed even if the account/card has since changed state. A client_ref
    # used by a different card or access type is rejected (stage 8, but the
    # retry path must be recognized first).
    existing = _find_ref_session(dispenser["station_id"], client_ref)
    for s in existing:
        if s["access_type"] == "PRIVATE" and s["fleet_card_id"] == fleet_card_id:
            return success_object(fueling_session_out(s), status=201)

    # State (stage 6)
    if card["status"] != "ACTIVE":
        raise ApiError(ERR_CARD_NOT_ACTIVE, 409, "Authorize requires card status ACTIVE")
    if account is None or account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, "Authorize requires account ACTIVE")
    if dispenser["status"] != "IN_SERVICE":
        raise ApiError(ERR_DISPENSER_NOT_IN_SERVICE, 409,
                       "Authorize requires dispenser status IN_SERVICE")
    if station is None or station["status"] != "ACTIVE":
        raise ApiError(ERR_STATION_NOT_ACTIVE, 409,
                       "Authorize requires station status ACTIVE")
    if eav != account["version"]:
        raise ApiError(ERR_STALE_ACCOUNT_VERSION, 412,
                       "expected_fleet_account_version does not match current FleetAccount.version")

    # Safety (stage 7)
    if station["uptime_posture"] == "OUTAGE":
        raise ApiError(ERR_STATION_OUTAGE, 409,
                       "Station uptime_posture is OUTAGE")

    # Uniqueness (stage 8)
    if not _access_mode_serves(station["access_mode"], "PRIVATE"):
        raise ApiError(ERR_ACCESS_MODE_MISMATCH, 409,
                       "Station access_mode does not serve PRIVATE sessions")
    for s in existing:
        raise ApiError(ERR_DUPLICATE_CLIENT_REF, 409,
                       "client_ref already used at this station by a different card or access type")

    # Price resolution + fiscal gates (stage 10)
    unit_price = resolve_unit_price_private(account["id"], station["id"], dispenser)
    hold_amount = round_half_up_cents(estimated_gge * unit_price)
    if account["outstanding_balance_cents"] + hold_amount > account["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402,
                       "outstanding_balance_cents + hold_amount_cents exceeds credit_limit_cents")
    if card["current_day_gge"] + estimated_gge > card["daily_gge_limit"]:
        raise ApiError(ERR_DAILY_LIMIT_EXCEEDED, 409,
                       "current_day_gge + estimated_gge exceeds daily_gge_limit")

    now = now_utc()
    session = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "access_type": "PRIVATE",
        "station_id": station["id"],
        "dispenser_id": dispenser_id,
        "fleet_card_id": fleet_card_id,
        "fleet_account_id": account["id"],
        "client_ref": client_ref,
        "estimated_gge": estimated_gge,
        "unit_price_cents": unit_price,
        "hold_amount_cents": hold_amount,
        "metered_mass_kg": None,
        "correction_factor_applied": None,
        "provisional_gge": None,
        "settled_gge": None,
        "total_amount_cents": None,
        "status": "AUTHORIZED",
        "void_reason": None,
        "authorized_at": now,
        "completed_at": None,
        "voided_at": None,
        "settled_at": None,
    }
    STORE.fueling_sessions[session["id"]] = session
    account["outstanding_balance_cents"] += hold_amount
    touch(account)
    return success_object(fueling_session_out(session), status=201)


@bp.post("/cng/fueling-sessions/authorize-public")
def authorize_public():
    caller = get_caller()
    require_role(caller, ["Anonymous"])
    data = body()
    # fleet_card_id must not be sent
    if "fleet_card_id" in data and data["fleet_card_id"] is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "fleet_card_id must not be sent to authorize-public")
    require_fields(data, ["dispenser_id", "client_ref", "estimated_gge"])
    dispenser_id = require_string(data, "dispenser_id")
    client_ref = require_string(data, "client_ref")
    estimated_gge = require_positive_number(data, "estimated_gge")

    dispenser = STORE.dispensers.get(dispenser_id)
    if dispenser is None:
        raise ApiError(ERR_DISPENSER_NOT_FOUND, 404, "Dispenser id does not exist")
    station = STORE.stations.get(dispenser["station_id"])

    # Idempotency on (station, client_ref): same access type with null card
    existing = _find_ref_session(dispenser["station_id"], client_ref)
    for s in existing:
        if s["access_type"] == "PUBLIC":
            return success_object(fueling_session_out(s), status=201)

    # State
    if dispenser["status"] != "IN_SERVICE":
        raise ApiError(ERR_DISPENSER_NOT_IN_SERVICE, 409,
                       "Authorize requires dispenser status IN_SERVICE")
    if station is None or station["status"] != "ACTIVE":
        raise ApiError(ERR_STATION_NOT_ACTIVE, 409,
                       "Authorize requires station status ACTIVE")

    # Safety
    if station["uptime_posture"] == "OUTAGE":
        raise ApiError(ERR_STATION_OUTAGE, 409,
                       "Station uptime_posture is OUTAGE")

    # Uniqueness
    if not _access_mode_serves(station["access_mode"], "PUBLIC"):
        raise ApiError(ERR_ACCESS_MODE_MISMATCH, 409,
                       "Station access_mode does not serve PUBLIC sessions")
    for s in existing:
        raise ApiError(ERR_DUPLICATE_CLIENT_REF, 409,
                       "client_ref already used at this station")

    unit_price = resolve_unit_price_public(station["id"], dispenser)

    now = now_utc()
    session = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "access_type": "PUBLIC",
        "station_id": station["id"],
        "dispenser_id": dispenser_id,
        "fleet_card_id": None,
        "fleet_account_id": None,
        "client_ref": client_ref,
        "estimated_gge": estimated_gge,
        "unit_price_cents": unit_price,
        "hold_amount_cents": 0,
        "metered_mass_kg": None,
        "correction_factor_applied": None,
        "provisional_gge": None,
        "settled_gge": None,
        "total_amount_cents": None,
        "status": "AUTHORIZED",
        "void_reason": None,
        "authorized_at": now,
        "completed_at": None,
        "voided_at": None,
        "settled_at": None,
    }
    STORE.fueling_sessions[session["id"]] = session
    return success_object(fueling_session_out(session), status=201)


@bp.post("/cng/fueling-sessions/<sessionId>/complete")
def complete_session(sessionId: str):
    caller = get_caller()
    require_role(caller, ["FleetDriver", "Anonymous"])
    data = body()
    require_fields(data, ["metered_mass_kg"])
    metered_mass_kg = require_positive_number(data, "metered_mass_kg")

    session = get_session_or_404(sessionId)

    # Access-type-specific role gate (stage 2 refinement per PRD §2.8 stage 2):
    # PUBLIC session completed by any role other than Anonymous -> ERR_FORBIDDEN_ROLE;
    # PRIVATE session completed by non-FleetDriver -> ERR_FORBIDDEN_ROLE.
    if session["access_type"] == "PUBLIC" and caller.role != "Anonymous":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "A PUBLIC session may only be completed by an Anonymous caller")
    if session["access_type"] == "PRIVATE" and caller.role != "FleetDriver":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "A PRIVATE session may only be completed by a FleetDriver")

    # Ownership (stage 5)
    if session["access_type"] == "PRIVATE":
        check_card_ownership(caller, session["fleet_card_id"])

    # State (stage 6)
    if session["status"] != "AUTHORIZED":
        raise ApiError(ERR_SESSION_NOT_COMPLETABLE, 409,
                       "Complete requires session AUTHORIZED")

    dispenser = STORE.dispensers.get(session["dispenser_id"])
    cf = dispenser["correction_factor"] if dispenser is not None else Decimal("1.0")

    provisional = round_half_up_3(metered_mass_kg / GGE_KG)
    settled = round_half_up_3(metered_mass_kg * cf / GGE_KG)
    total_amount = round_half_up_cents(settled * session["unit_price_cents"])

    now = now_utc()
    session["metered_mass_kg"] = metered_mass_kg
    session["correction_factor_applied"] = cf
    session["provisional_gge"] = provisional
    session["settled_gge"] = settled
    session["total_amount_cents"] = total_amount
    session["status"] = "COMPLETED"
    session["completed_at"] = now
    touch(session)

    if session["access_type"] == "PRIVATE":
        account = STORE.fleet_accounts.get(session["fleet_account_id"])
        if account is not None:
            account["outstanding_balance_cents"] += (total_amount - session["hold_amount_cents"])
            touch(account)
        card = STORE.fleet_cards.get(session["fleet_card_id"])
        if card is not None:
            card["current_day_gge"] += settled
            touch(card)

    return success_object(fueling_session_out(session))


@bp.post("/cng/fueling-sessions/<sessionId>/void")
def void_session_endpoint(sessionId: str):
    caller = get_caller()
    require_role(caller, ["FleetDriver", "Anonymous", "StationManager"])
    data = body()

    session = get_session_or_404(sessionId)

    # Access-type role refinement
    if session["access_type"] == "PUBLIC" and caller.role == "FleetDriver":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "A FleetDriver cannot void a PUBLIC session")
    if session["access_type"] == "PRIVATE" and caller.role == "Anonymous":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "An Anonymous caller cannot void a PRIVATE session")

    # Ownership
    if session["access_type"] == "PRIVATE" and caller.role == "FleetDriver":
        check_card_ownership(caller, session["fleet_card_id"])

    # State
    if session["status"] not in ("AUTHORIZED", "COMPLETED"):
        raise ApiError(ERR_SESSION_NOT_VOIDABLE, 409,
                       "Void requires session AUTHORIZED or COMPLETED")

    # void_reason: driver/anon -> CUSTOMER_REQUEST; StationManager -> MANAGER_VOID
    if caller.role == "StationManager":
        reason = "MANAGER_VOID"
    else:
        reason = "CUSTOMER_REQUEST"

    from services.core import void_session as _void
    _void(session, reason)
    return success_object(fueling_session_out(session))


@bp.get("/cng/fueling-sessions")
def list_sessions():
    caller = get_caller()
    require_role(caller, _READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    fleet_account_id = request.args.get("fleet_account_id")
    fleet_card_id = request.args.get("fleet_card_id")
    dispenser_id = request.args.get("dispenser_id")
    status = request.args.get("status")
    month = request.args.get("month")
    items = sorted(STORE.fueling_sessions.values(), key=lambda s: (s["created_at"], s["id"]))
    if station_id is not None:
        items = [s for s in items if s["station_id"] == station_id]
    if fleet_account_id is not None:
        items = [s for s in items if s["fleet_account_id"] == fleet_account_id]
    if fleet_card_id is not None:
        items = [s for s in items if s["fleet_card_id"] == fleet_card_id]
    if dispenser_id is not None:
        items = [s for s in items if s["dispenser_id"] == dispenser_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if month is not None:
        items = [
            s for s in items
            if s["completed_at"] is not None and month_of(s["completed_at"]) == month
        ]
    if caller.role == "FleetAccountManager":
        items = [s for s in items if s["fleet_account_id"] == caller.user_id]
    elif caller.role == "FleetDriver":
        items = [s for s in items if s["fleet_card_id"] == caller.user_id]
    page, total = paginate(items, limit, offset)
    return success_list([fueling_session_out(s) for s in page], limit, offset, total)


@bp.get("/cng/fueling-sessions/<sessionId>")
def get_session(sessionId: str):
    caller = get_caller()
    require_role(caller, _READ)
    session = get_session_or_404(sessionId)
    if caller.role == "FleetAccountManager":
        if session["fleet_account_id"] != caller.user_id:
            raise ApiError(ERR_ACCOUNT_OWNERSHIP_MISMATCH, 403,
                           "FleetAccountManager may only view own account's sessions")
    elif caller.role == "FleetDriver":
        if session["fleet_card_id"] != caller.user_id:
            raise ApiError(ERR_CARD_OWNERSHIP_MISMATCH, 403,
                           "FleetDriver may only view own card's sessions")
    return success_object(fueling_session_out(session))
