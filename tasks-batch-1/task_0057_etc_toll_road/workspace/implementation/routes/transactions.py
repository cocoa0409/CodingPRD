from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, require_bool, require_enum,
                  parse_dt, parse_iso, paginate, sorted_by_created)
from serialize import public, public_list
from services import core

bp = Blueprint("transactions", __name__)

READ_ROLES = {"AccountHolder", "TollOperator", "InteropClerk", "SystemAdmin"}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def _resolve_transponder_read(transponder, read_at_dt):
    """Resolve (account_id, vehicle_id) for a transponder read at read_at_dt."""
    binding = _active_binding_at(transponder["id"], read_at_dt)
    if binding is None:
        return None, None
    vehicle = db.vehicles.get(binding["vehicle_id"])
    if vehicle is None:
        return None, None
    return vehicle["account_id"], vehicle["id"]


def _active_binding_at(transponder_id, read_at_dt):
    for b in db.transponder_bindings.values():
        if b["transponder_id"] != transponder_id:
            continue
        ef = parse_iso(b["effective_from"])
        et = parse_iso(b["effective_to"]) if b["effective_to"] else None
        if ef <= read_at_dt and (et is None or read_at_dt < et):
            return b
    return None


def _resolve_plate_read(plate_number, plate_state_code):
    if not plate_number or not plate_state_code:
        return None, None
    pn = plate_number.upper()
    for v in db.vehicles.values():
        if v["plate_number"] == pn and v["plate_state_code"] == plate_state_code:
            return v["account_id"], v["id"]
    return None, None


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------
@bp.post("/etc/toll-transactions")
def create_transaction():
    _, role = get_auth()
    require_roles(role, {"TollOperator", "InteropClerk"})
    body = get_body()

    # Existence (priority 3) left-to-right: plaza_id, transponder_id?, interop_agency_id?
    plaza_id = body.get("plaza_id")
    plaza = None
    if isinstance(plaza_id, str):
        plaza = db.plazas.get(plaza_id)
        if plaza is None:
            raise err(errors.ERR_NOT_FOUND, "Plaza not found")

    transponder = None
    if isinstance(body.get("transponder_id"), str):
        transponder = db.transponders.get(body["transponder_id"])
        if transponder is None:
            raise err(errors.ERR_NOT_FOUND, "Transponder not found")

    agency = None
    if isinstance(body.get("interop_agency_id"), str):
        agency = db.interop_agencies.get(body["interop_agency_id"])
        if agency is None:
            raise err(errors.ERR_NOT_FOUND, "Interop agency not found")

    # Interop-agency active (priority 14)
    if agency is not None and not agency["active"]:
        raise err(errors.ERR_INTEROP_AGENCY_INACTIVE, "Interop agency is inactive")

    # Structural
    if plaza is None:
        require_str(body, "plaza_id")
    read_method = require_enum(body, "read_method", {"TRANSPONDER", "PLATE"})
    read_at = require_str(body, "read_at")
    read_at_dt = parse_dt(body, "read_at")
    is_peak = require_bool(body, "is_peak")
    declared_axles = require_int(body, "declared_axles", required=False, default=2, min_value=2)
    plate_number = require_str(body, "plate_number", required=False, default=None)
    plate_state_code = require_str(body, "plate_state_code", required=False, default=None)

    # Resolve owner
    account_id = None
    vehicle_id = None
    if read_method == "TRANSPONDER":
        if transponder is not None:
            account_id, vehicle_id = _resolve_transponder_read(transponder, read_at_dt)
    else:  # PLATE
        account_id, vehicle_id = _resolve_plate_read(plate_number, plate_state_code)

    tx = {
        "plaza_id": plaza["id"],
        "account_id": account_id,
        "vehicle_id": vehicle_id,
        "transponder_id": transponder["id"] if transponder else None,
        "read_method": read_method,
        "plate_number": plate_number.upper() if plate_number else None,
        "plate_state_code": plate_state_code,
        "read_at": read_at,
        "is_peak": is_peak,
        "declared_axles": declared_axles,
        "pricing_status": "PENDING",
        "settlement_status": "UNSETTLED",
        "gross_toll_cents": 0,
        "toll_cents": 0,
        "hov_exempt": False,
        "interop_agency_id": agency["id"] if agency else None,
    }
    init_common(tx)
    db.toll_transactions[tx["id"]] = tx
    return success(public(tx), status=201)


@bp.get("/etc/toll-transactions/<tid>")
def get_transaction(tid):
    user_id, role = get_auth()
    require_roles(role, READ_ROLES)
    tx = db.toll_transactions.get(tid)
    if tx is None:
        raise err(errors.ERR_NOT_FOUND, "Toll transaction not found")
    if role == "AccountHolder" and tx.get("account_id") != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this transaction")
    return success(public(tx))


@bp.get("/etc/toll-transactions")
def list_transactions():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    items = list(db.toll_transactions.values())
    for field in ("account_id", "vehicle_id", "transponder_id", "interop_agency_id"):
        val = request.args.get(field)
        if val is not None:
            items = [t for t in items if t.get(field) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------
@bp.post("/etc/toll-transactions/<tid>/price")
def price_transaction(tid):
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    tx = db.toll_transactions.get(tid)
    if tx is None:
        raise err(errors.ERR_NOT_FOUND, "Toll transaction not found")

    # State (priority 5): must be PENDING
    if tx["pricing_status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Transaction is not PENDING")

    # Resolution must have succeeded
    if tx.get("account_id") is None:
        raise err(errors.ERR_UNRESOLVED_READ, "Account/vehicle could not be resolved")

    plaza = db.plazas[tx["plaza_id"]]
    account = db.accounts[tx["account_id"]]

    # HOV exemption check
    exempt = _hov_exempt(tx, plaza)

    gross = core.compute_gross_toll(plaza, tx["declared_axles"], tx["is_peak"])

    if exempt:
        tx["hov_exempt"] = True
        tx["gross_toll_cents"] = gross
        tx["toll_cents"] = 0
        tx["pricing_status"] = "EXEMPT"
        tx["settlement_status"] = "SETTLED"
        touch(tx)
        return success(public(tx))

    # Plate-registration eligibility (priority 8): transponder-rate path requires
    # matched vehicle REGISTERED. A PLATE read with a LAPSED matched vehicle is rejected.
    if tx["read_method"] == "PLATE":
        vehicle = db.vehicles.get(tx.get("vehicle_id"))
        if vehicle is not None and vehicle["registration_status"] == "LAPSED":
            raise err(errors.ERR_PLATE_UNREGISTERED,
                      "Plate-matched vehicle is LAPSED")

    toll = core.compute_toll_cents(gross, tx["read_method"], plaza, hov_exempt=False)
    tx["gross_toll_cents"] = gross
    tx["toll_cents"] = toll
    tx["pricing_status"] = "PRICED"

    # Debit behavior
    if tx["read_method"] == "TRANSPONDER":
        core.apply_debit_and_reload(account, toll, "TOLL_DEBIT", ref_transaction_id=tx["id"])
        tx["settlement_status"] = "SETTLED"
    elif tx["read_method"] == "PLATE" and tx.get("interop_agency_id"):
        agency = db.interop_agencies[tx["interop_agency_id"]]
        home_debit = core.interop_home_debit(toll, agency)
        core.apply_debit_and_reload(account, home_debit, "INTEROP_DEBIT",
                                    ref_transaction_id=tx["id"])
        tx["settlement_status"] = "SETTLED"
    # else PLATE with no interop: no debit, stays UNSETTLED

    touch(tx)
    return success(public(tx))


def _hov_exempt(tx, plaza):
    if tx.get("vehicle_id") is None:
        return False
    read_at = parse_iso(tx["read_at"])
    for w in db.hov_windows.values():
        if w["vehicle_id"] != tx["vehicle_id"] or w["status"] != "DECLARED":
            continue
        wf = parse_iso(w["window_from"])
        wt = parse_iso(w["window_to"])
        if wf <= read_at < wt and w["declared_occupants"] >= plaza["hov_min_occupants"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Reprice
# ---------------------------------------------------------------------------
@bp.post("/etc/toll-transactions/<tid>/reprice")
def reprice_transaction(tid):
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    tx = db.toll_transactions.get(tid)
    if tx is None:
        raise err(errors.ERR_NOT_FOUND, "Toll transaction not found")

    # State (priority 5): PRICED and not WRITTEN_OFF
    if tx["pricing_status"] != "PRICED":
        raise err(errors.ERR_INVALID_STATE, "Transaction is not PRICED")
    if tx["settlement_status"] == "WRITTEN_OFF":
        raise err(errors.ERR_INVALID_STATE, "Transaction is WRITTEN_OFF")

    body = get_body()
    declared_axles = require_int(body, "declared_axles", min_value=2)
    is_peak = require_bool(body, "is_peak")

    # OCC (priority 17)
    expected = require_int(body, "expected_transaction_version")
    if expected != tx["version"]:
        raise err(errors.ERR_STALE_VERSION, "Transaction version is stale")

    plaza = db.plazas[tx["plaza_id"]]
    account = db.accounts[tx["account_id"]]
    old_toll = tx["toll_cents"]

    gross = core.compute_gross_toll(plaza, declared_axles, is_peak)
    new_toll = core.compute_toll_cents(gross, tx["read_method"], plaza, hov_exempt=False)

    tx["declared_axles"] = declared_axles
    tx["is_peak"] = is_peak
    tx["gross_toll_cents"] = gross
    tx["toll_cents"] = new_toll
    tx["pricing_status"] = "REPRICED"

    delta = new_toll - old_toll
    if delta != 0:
        # adjust balance by (new - old); a debit when delta>0
        core.append_ledger(account, "TOLL_DEBIT", -delta, ref_transaction_id=tx["id"])
        core.evaluate_auto_reload(account)
        touch(account)
    touch(tx)
    return success(public(tx))


# ---------------------------------------------------------------------------
# Settle
# ---------------------------------------------------------------------------
@bp.post("/etc/toll-transactions/<tid>/settle")
def settle_transaction(tid):
    user_id, role = get_auth()
    require_roles(role, {"TollOperator", "AccountHolder"})
    tx = db.toll_transactions.get(tid)
    if tx is None:
        raise err(errors.ERR_NOT_FOUND, "Toll transaction not found")
    if role == "AccountHolder" and tx.get("account_id") != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this transaction")

    # State (priority 5): UNSETTLED and pricing in {PRICED, EXEMPT, REPRICED}
    if tx["settlement_status"] != "UNSETTLED":
        raise err(errors.ERR_INVALID_STATE, "Transaction is not UNSETTLED")
    if tx["pricing_status"] not in ("PRICED", "EXEMPT", "REPRICED"):
        raise err(errors.ERR_INVALID_STATE, "Transaction is not priced")

    account = db.accounts[tx["account_id"]]
    # Debit remainder (full toll, since unsettled plate reads were never debited)
    remainder = tx["toll_cents"]
    if remainder != 0:
        core.apply_debit_and_reload(account, remainder, "TOLL_DEBIT",
                                    ref_transaction_id=tx["id"])
    tx["settlement_status"] = "SETTLED"
    touch(tx)
    return success(public(tx))


# ---------------------------------------------------------------------------
# Batch trip
# ---------------------------------------------------------------------------
@bp.post("/etc/toll-transactions/batch-trip")
def batch_trip():
    _, role = get_auth()
    require_roles(role, {"TollOperator"})
    body = get_body()

    # Existence (priority 3): account_id, then each segment's plaza_id
    account_id = body.get("account_id")
    account = None
    if isinstance(account_id, str):
        account = db.accounts.get(account_id)
        if account is None:
            raise err(errors.ERR_NOT_FOUND, "Account not found")
    if account is None:
        require_str(body, "account_id")

    segments = body.get("segments")
    if not isinstance(segments, list) or len(segments) == 0:
        raise err(errors.ERR_VALIDATION, "segments must be a non-empty list")

    parsed = []
    for seg in segments:
        if not isinstance(seg, dict):
            raise err(errors.ERR_VALIDATION, "each segment must be an object")
        pid = seg.get("plaza_id")
        if not isinstance(pid, str):
            raise err(errors.ERR_VALIDATION, "segment plaza_id required")
        plaza = db.plazas.get(pid)
        if plaza is None:
            raise err(errors.ERR_NOT_FOUND, "Plaza not found")
        read_method = require_enum(seg, "read_method", {"TRANSPONDER", "PLATE"})
        read_at = require_str(seg, "read_at")
        parse_iso(read_at)
        is_peak = require_bool(seg, "is_peak")
        declared_axles = require_int(seg, "declared_axles", required=False, default=2, min_value=2)
        parsed.append({
            "plaza": plaza, "read_method": read_method, "read_at": read_at,
            "is_peak": is_peak, "declared_axles": declared_axles,
            "plate_number": seg.get("plate_number"),
            "plate_state_code": seg.get("plate_state_code"),
            "transponder_id": seg.get("transponder_id"),
        })

    # Compute per-segment toll (round per segment), then sum.
    created = []
    trip_total = 0
    for p in parsed:
        gross = core.compute_gross_toll(p["plaza"], p["declared_axles"], p["is_peak"])
        toll = core.compute_toll_cents(gross, p["read_method"], p["plaza"], hov_exempt=False)
        trip_total += toll
        tx = {
            "plaza_id": p["plaza"]["id"],
            "account_id": account["id"],
            "vehicle_id": None,
            "transponder_id": p["transponder_id"],
            "read_method": p["read_method"],
            "plate_number": p["plate_number"].upper() if p["plate_number"] else None,
            "plate_state_code": p["plate_state_code"],
            "read_at": p["read_at"],
            "is_peak": p["is_peak"],
            "declared_axles": p["declared_axles"],
            "pricing_status": "PRICED",
            "settlement_status": "SETTLED",
            "gross_toll_cents": gross,
            "toll_cents": toll,
            "hov_exempt": False,
            "interop_agency_id": None,
        }
        init_common(tx)
        db.toll_transactions[tx["id"]] = tx
        created.append(tx)

    if trip_total != 0:
        core.apply_debit_and_reload(account, trip_total, "TOLL_DEBIT")

    return success(public_list(created), status=201)
