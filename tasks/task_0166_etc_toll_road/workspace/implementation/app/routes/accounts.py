"""Account, vehicle, transponder, and reload endpoints."""
from flask import Blueprint, request

from ..auth import check_account_holder_owns, require_roles
from ..errors import ApiError, raise_api_error
from ..responses import paginate, parse_pagination, success_array, success_object, empty
from ..serializers import (
    account_summary,
    serialize_account,
    serialize_reload,
    serialize_transponder,
    serialize_vehicle,
)
from ..services.pricing import class_for_axles
from ..store import store
from ..validators import (
    AGENCIES,
    PLATE_STATES,
    normalize_plate,
    normalize_serial,
    optional_bool,
    optional_enum,
    optional_int,
    optional_str,
    require_enum,
    require_int,
    require_json,
    require_str,
)


accounts_bp = Blueprint("accounts", __name__)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def _find_account_or_404(account_id: str) -> dict:
    acct = store.accounts.get(account_id)
    if acct is None:
        raise_api_error("ERR_NOT_FOUND")
    return acct


@accounts_bp.route("/accounts", methods=["POST"])
@require_roles("AgencyAdmin")
def create_account():
    payload = require_json(request.get_json(silent=True))
    holder_name = require_str(payload, "holder_name", min_len=1, max_len=120)
    home_agency_code = require_enum(payload, "home_agency_code", AGENCIES)
    auto_reload_enabled = optional_bool(payload, "auto_reload_enabled", default=False)
    auto_reload_threshold_cents = optional_int(payload, "auto_reload_threshold_cents", 0, 10000, default=1000)
    auto_reload_topup_cents = optional_int(payload, "auto_reload_topup_cents", 1000, 20000, default=4000)
    payment_method_token = optional_str(payload, "payment_method_token", default=None)
    if auto_reload_enabled and not payment_method_token:
        raise_api_error("ERR_VALIDATION", "payment_method_token is required when auto_reload_enabled is true.")

    with store.lock:
        account = store.stamp_new({
            "holder_name": holder_name,
            "home_agency_code": home_agency_code,
            "balance_cents": 0,
            "auto_reload_enabled": auto_reload_enabled,
            "auto_reload_threshold_cents": auto_reload_threshold_cents,
            "auto_reload_topup_cents": auto_reload_topup_cents,
            "payment_method_token": payment_method_token,
            "status": "ACTIVE",
            "outstanding_fine_cents": 0,
        })
        store.accounts[account["id"]] = account
        return success_object(serialize_account(account), status=201)


@accounts_bp.route("/accounts/<account_id>", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def get_account(account_id: str):
    account = _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    return success_object(serialize_account(account))


@accounts_bp.route("/accounts/<account_id>", methods=["PATCH"])
@require_roles("AccountHolder", "AgencyAdmin")
def patch_account(account_id: str):
    account = _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    payload = require_json(request.get_json(silent=True))

    # OCC check (only when version is supplied)
    if "version" in payload and payload["version"] is not None:
        if not isinstance(payload["version"], int) or isinstance(payload["version"], bool):
            raise_api_error("ERR_VALIDATION", "version must be an integer.")
        if payload["version"] != account["version"]:
            raise_api_error("ERR_VERSION_CONFLICT")

    new_auto = optional_bool(payload, "auto_reload_enabled", default=None)
    new_threshold = optional_int(payload, "auto_reload_threshold_cents", 0, 10000, default=None)
    new_topup = optional_int(payload, "auto_reload_topup_cents", 1000, 20000, default=None)
    new_token = optional_str(payload, "payment_method_token", default=None)

    with store.lock:
        if new_auto is not None:
            account["auto_reload_enabled"] = new_auto
        if new_threshold is not None:
            account["auto_reload_threshold_cents"] = new_threshold
        if new_topup is not None:
            account["auto_reload_topup_cents"] = new_topup
        if new_token is not None:
            account["payment_method_token"] = new_token
        # Enforce the token requirement when auto-reload is enabled
        if account["auto_reload_enabled"] and not account.get("payment_method_token"):
            raise_api_error("ERR_VALIDATION", "payment_method_token is required when auto_reload_enabled is true.")
        store.bump(account)
        return success_object(serialize_account(account))


@accounts_bp.route("/accounts/<account_id>", methods=["DELETE"])
@require_roles("AgencyAdmin")
def delete_account(account_id: str):
    account = _find_account_or_404(account_id)
    with store.lock:
        if int(account.get("outstanding_fine_cents", 0)) != 0:
            raise_api_error("ERR_ACCOUNT_HAS_OBLIGATIONS")
        for t in store.transponders_of(account_id):
            if t["status"] in ("ACTIVE", "SUSPENDED"):
                raise_api_error("ERR_ACCOUNT_HAS_OBLIGATIONS")
        account["status"] = "CLOSED"
        store.bump(account)
        for v in store.vehicles_of(account_id):
            if v["status"] != "BLOCKED":
                v["status"] = "BLOCKED"
                store.bump(v)
        return empty(204)


@accounts_bp.route("/accounts", methods=["GET"])
@require_roles("AgencyAdmin")
def list_accounts():
    limit, offset = parse_pagination(request.args)
    home = request.args.get("home_agency_code")
    status = request.args.get("status")
    if home is not None and home not in AGENCIES:
        raise_api_error("ERR_VALIDATION", "Invalid home_agency_code filter.")
    if status is not None and status not in ("ACTIVE", "SUSPENDED", "CLOSED"):
        raise_api_error("ERR_VALIDATION", "Invalid status filter.")
    rows = list(store.accounts.values())
    if home:
        rows = [r for r in rows if r["home_agency_code"] == home]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([serialize_account(r) for r in page], limit, offset, total)


@accounts_bp.route("/accounts/<account_id>/summary", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def account_summary_endpoint(account_id: str):
    account = _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    veh_count = len(store.vehicles_of(account_id))
    trans_count = len(store.transponders_of(account_id))
    return success_object(account_summary(account, veh_count, trans_count))


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

@accounts_bp.route("/accounts/<account_id>/vehicles", methods=["POST"])
@require_roles("AccountHolder", "AgencyAdmin")
def create_vehicle(account_id: str):
    account = _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    if account["status"] != "ACTIVE":
        raise_api_error("ERR_ACCOUNT_NOT_ACTIVE")
    payload = require_json(request.get_json(silent=True))
    raw_plate = require_str(payload, "plate_number", min_len=1, max_len=20)
    plate_number = normalize_plate(raw_plate)
    plate_state = require_enum(payload, "plate_state", PLATE_STATES)
    axle_count = optional_int(payload, "axle_count", 2, 7, default=2)
    hov_capable = optional_bool(payload, "hov_capable", default=True)
    with store.lock:
        if store.find_vehicle_by_plate(plate_number, plate_state) is not None:
            raise_api_error("ERR_DUPLICATE_RESOURCE")
        vehicle = store.stamp_new({
            "account_id": account_id,
            "plate_number": plate_number,
            "plate_state": plate_state,
            "axle_count": axle_count,
            "vehicle_class": class_for_axles(axle_count),
            "hov_capable": hov_capable,
            "status": "ACTIVE",
        })
        store.vehicles[vehicle["id"]] = vehicle
        return success_object(serialize_vehicle(vehicle), status=201)


@accounts_bp.route("/accounts/<account_id>/vehicles/<vehicle_id>", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def get_vehicle(account_id: str, vehicle_id: str):
    _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    vehicle = store.vehicles.get(vehicle_id)
    if vehicle is None or vehicle["account_id"] != account_id:
        raise_api_error("ERR_NOT_FOUND")
    return success_object(serialize_vehicle(vehicle))


@accounts_bp.route("/accounts/<account_id>/vehicles", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def list_vehicles(account_id: str):
    _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    if status is not None and status not in ("ACTIVE", "BLOCKED"):
        raise_api_error("ERR_VALIDATION", "Invalid status filter.")
    rows = store.vehicles_of(account_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([serialize_vehicle(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Transponders
# ---------------------------------------------------------------------------

@accounts_bp.route("/accounts/<account_id>/transponders", methods=["POST"])
@require_roles("AccountHolder", "AgencyAdmin")
def create_transponder(account_id: str):
    account = _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    # PRD §3.2: registration of a transponder is not gated on
    # account.status (only binding requires ACTIVE). PRD §2.11's
    # state-check enumerates "register a vehicle, bind a transponder,
    # ingest a toll attributed to the account, or pay a fine" — not
    # transponder registration.
    payload = require_json(request.get_json(silent=True))
    raw_serial = require_str(payload, "serial_number", min_len=1, max_len=64)
    serial = normalize_serial(raw_serial)
    with store.lock:
        if store.find_transponder_by_serial(serial) is not None:
            raise_api_error("ERR_DUPLICATE_RESOURCE")
        transponder = store.stamp_new({
            "account_id": account_id,
            "serial_number": serial,
            "bound_vehicle_id": None,
            "status": "UNBOUND",
            "bound_at": None,
        })
        store.transponders[transponder["id"]] = transponder
        return success_object(serialize_transponder(transponder), status=201)


@accounts_bp.route("/accounts/<account_id>/transponders/<transponder_id>/bind", methods=["POST"])
@require_roles("AccountHolder", "AgencyAdmin")
def bind_transponder(account_id: str, transponder_id: str):
    account = _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    transponder = store.transponders.get(transponder_id)
    if transponder is None or transponder["account_id"] != account_id:
        raise_api_error("ERR_NOT_FOUND")
    if account["status"] != "ACTIVE":
        raise_api_error("ERR_ACCOUNT_NOT_ACTIVE")
    if transponder["status"] != "UNBOUND":
        raise_api_error("ERR_INVALID_STATE")
    payload = require_json(request.get_json(silent=True))
    vehicle_id = require_str(payload, "vehicle_id", min_len=1, max_len=128)
    vehicle = store.vehicles.get(vehicle_id)
    if vehicle is None or vehicle["account_id"] != account_id:
        raise_api_error("ERR_NOT_FOUND")
    if vehicle["status"] != "ACTIVE":
        raise_api_error("ERR_VEHICLE_BLOCKED")
    with store.lock:
        # business-constraint: only one ACTIVE transponder per vehicle
        for t in store.transponders.values():
            if t.get("bound_vehicle_id") == vehicle_id and t["status"] == "ACTIVE":
                raise_api_error("ERR_VEHICLE_ALREADY_BOUND")
        transponder["bound_vehicle_id"] = vehicle_id
        transponder["status"] = "ACTIVE"
        from ..clock import iso_now as _iso_now
        transponder["bound_at"] = _iso_now()
        store.bump(transponder)
        return success_object(serialize_transponder(transponder))


@accounts_bp.route("/accounts/<account_id>/transponders/<transponder_id>/unbind", methods=["POST"])
@require_roles("AccountHolder", "AgencyAdmin")
def unbind_transponder(account_id: str, transponder_id: str):
    _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    transponder = store.transponders.get(transponder_id)
    if transponder is None or transponder["account_id"] != account_id:
        raise_api_error("ERR_NOT_FOUND")
    if transponder["status"] != "ACTIVE":
        raise_api_error("ERR_INVALID_STATE")
    with store.lock:
        transponder["bound_vehicle_id"] = None
        transponder["status"] = "UNBOUND"
        transponder["bound_at"] = None
        store.bump(transponder)
        return success_object(serialize_transponder(transponder))


@accounts_bp.route("/accounts/<account_id>/transponders/<transponder_id>", methods=["DELETE"])
@require_roles("AccountHolder", "AgencyAdmin")
def delete_transponder(account_id: str, transponder_id: str):
    _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    transponder = store.transponders.get(transponder_id)
    if transponder is None or transponder["account_id"] != account_id:
        raise_api_error("ERR_NOT_FOUND")
    if transponder["status"] != "UNBOUND":
        raise_api_error("ERR_INVALID_STATE")
    with store.lock:
        transponder["status"] = "RETURNED"
        store.bump(transponder)
        return empty(204)


# ---------------------------------------------------------------------------
# Reloads
# ---------------------------------------------------------------------------

@accounts_bp.route("/accounts/<account_id>/reloads", methods=["POST"])
@require_roles("AccountHolder", "AgencyAdmin")
def manual_reload(account_id: str):
    account = _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    if account["status"] != "ACTIVE":
        raise_api_error("ERR_ACCOUNT_NOT_ACTIVE")
    payload = require_json(request.get_json(silent=True))
    # We need a specific validation error for out-of-range reload amounts.
    if "amount_cents" not in payload or payload["amount_cents"] is None:
        raise_api_error("ERR_VALIDATION", "Missing required field: amount_cents")
    amt = payload["amount_cents"]
    if isinstance(amt, bool) or not isinstance(amt, int):
        raise_api_error("ERR_VALIDATION", "amount_cents must be an integer.")
    if amt < 100 or amt > 50000:
        raise_api_error("ERR_INVALID_RELOAD_AMOUNT")
    with store.lock:
        balance_before = int(account["balance_cents"])
        account["balance_cents"] = balance_before + amt
        store.bump(account)
        reload_event = store.stamp_event({
            "account_id": account_id,
            "kind": "MANUAL",
            "amount_cents": amt,
            "balance_before_cents": balance_before,
            "balance_after_cents": account["balance_cents"],
            "triggered_by_event_id": None,
        })
        store.reload_events[reload_event["id"]] = reload_event
        return success_object(serialize_reload(reload_event), status=201)


@accounts_bp.route("/accounts/<account_id>/reloads", methods=["GET"])
@require_roles("AccountHolder", "AgencyAdmin")
def list_reloads(account_id: str):
    _find_account_or_404(account_id)
    check_account_holder_owns(account_id)
    limit, offset = parse_pagination(request.args)
    kind = request.args.get("kind")
    if kind is not None and kind not in ("MANUAL", "AUTO"):
        raise_api_error("ERR_VALIDATION", "Invalid kind filter.")
    rows = store.reloads_of(account_id)
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([serialize_reload(r) for r in page], limit, offset, total)
