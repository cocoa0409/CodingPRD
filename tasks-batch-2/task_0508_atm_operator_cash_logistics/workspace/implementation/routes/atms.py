"""ATM routes: provisioning, read/list, forecast, cassettes, transactions,
cash-counts and close-out."""
from flask import Blueprint, request

import lookups
import serialize
import validate
import services.forecast as forecast_svc
import services.reconciliation as recon_svc
import services.transaction as txn_svc
from constants import CASSETTE_POSITIONS, TXN_KINDS
from db import store
from errors import err
from middleware import authenticate, authorize
from response import ok_array, ok_object

bp = Blueprint("atms", __name__)

READ_ALL = {"PlatformAdmin", "FieldTech", "SettlementOfficer", "VaultController", "ComplianceOfficer"}


# --------------------------------------------------------------------------- #
# ATM provisioning + read
# --------------------------------------------------------------------------- #
@bp.route("/atms", methods=["POST"])
def create_atm():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = validate.get_body()
    serial_no = validate.require_str(body, "serial_no")
    location_id = validate.require_str(body, "location_id")
    surcharge = validate.require_int(body, "surcharge_cents")
    note = validate.optional_int(body, "note_denomination_cents", 2000)
    lookups.location(store, location_id)
    # Serial uniqueness (priority 5).
    for a in store.atms.values():
        if a["serial_no"] == serial_no:
            raise err("ERR_DUPLICATE_SERIAL", "serial_no already exists.")
    atm = {
        "serial_no": serial_no,
        "location_id": location_id,
        "surcharge_cents": surcharge,
        "note_denomination_cents": note,
        "operational_status": "IN_SERVICE",
        "cash_status": "EMPTY",
        "monthly_wd_count": 0,
        "dispensed_cents_since_load": 0,
        "fee_disclosure_id": None,
        "last_confirm_load_at": None,
    }
    store.stamp_new(atm)
    store.atms[atm["id"]] = atm
    return ok_object(store.clock, serialize.atm(store, atm), 201)


@bp.route("/atms/<aid>", methods=["GET"])
def get_atm(aid):
    _, role = authenticate()
    authorize(role, READ_ALL)
    atm = lookups.atm(store, aid)
    return ok_object(store.clock, serialize.atm(store, atm))


@bp.route("/atms", methods=["GET"])
def list_atms():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech", "SettlementOfficer"})
    limit, offset = validate.parse_pagination(request.args)
    location_id = request.args.get("location_id")
    fee_disclosure_id = request.args.get("fee_disclosure_id")
    items = store.sorted_values(store.atms)
    if location_id is not None:
        items = [a for a in items if a["location_id"] == location_id]
    if fee_disclosure_id is not None:
        items = [a for a in items if a["fee_disclosure_id"] == fee_disclosure_id]
    page, total = validate.paginate([serialize.atm(store, a) for a in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #
@bp.route("/atms/<aid>/forecast", methods=["GET"])
def forecast(aid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "VaultController", "FieldTech"})
    atm = lookups.atm(store, aid)
    basis = request.args.get("basis", "FORWARD")
    if basis not in ("FORWARD", "CHRONOLOGICAL"):
        raise err("ERR_INVALID_REQUEST", "basis must be FORWARD or CHRONOLOGICAL.")
    days_raw = request.args.get("days_until_next_visit")
    if days_raw is None or days_raw == "":
        raise err("ERR_INVALID_REQUEST", "days_until_next_visit is required.")
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "days_until_next_visit must be an integer.")
    if days < 1:
        raise err("ERR_VALIDATION", "days_until_next_visit must be at least 1.")
    result = forecast_svc.compute(store, atm, basis, days)
    return ok_object(store.clock, result)


# --------------------------------------------------------------------------- #
# Cassettes
# --------------------------------------------------------------------------- #
@bp.route("/atms/<aid>/cassettes", methods=["POST"])
def add_cassette(aid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech"})
    atm = lookups.atm(store, aid)
    body = validate.get_body()
    position = validate.require_enum(body, "position", CASSETTE_POSITIONS)
    c = {
        "atm_id": atm["id"],
        "position": position,
        "loaded_cents": 0,
        "dispensed_cents": 0,
        "balance_status": "BALANCED",
    }
    store.stamp_new(c)
    store.cassettes[c["id"]] = c
    return ok_object(store.clock, serialize.cassette(c), 201)


@bp.route("/atms/<aid>/cassettes", methods=["GET"])
def list_cassettes(aid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech", "SettlementOfficer"})
    atm = lookups.atm(store, aid)
    limit, offset = validate.parse_pagination(request.args)
    items = [c for c in store.sorted_values(store.cassettes) if c["atm_id"] == atm["id"]]
    page, total = validate.paginate([serialize.cassette(c) for c in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
@bp.route("/atms/<aid>/transactions", methods=["POST"])
def post_transaction(aid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech"})
    atm = lookups.atm(store, aid)
    body = validate.get_body()
    kind = validate.require_enum(body, "kind", TXN_KINDS)
    if kind == "WITHDRAWAL":
        amount = validate.require_int(body, "amount_cents")
        # ERR_AMOUNT_NOT_DENOMINATED (priority 14).
        note = atm["note_denomination_cents"]
        if note <= 0 or amount % note != 0:
            raise err("ERR_AMOUNT_NOT_DENOMINATED",
                      "amount_cents must be a multiple of note_denomination_cents.")
        # ERR_NO_FEE_DISCLOSURE (priority 11).
        if not atm.get("fee_disclosure_id"):
            raise err("ERR_NO_FEE_DISCLOSURE", "ATM has no approved fee disclosure.")
        txn = txn_svc.post(store, atm, kind, amount)
    else:
        txn = txn_svc.post(store, atm, kind, 0)
    return ok_object(store.clock, serialize.transaction(txn), 201)


@bp.route("/atms/<aid>/transactions", methods=["GET"])
def list_atm_transactions(aid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech", "SettlementOfficer"})
    atm = lookups.atm(store, aid)
    limit, offset = validate.parse_pagination(request.args)
    kind = request.args.get("kind")
    items = [t for t in store.sorted_values(store.transactions) if t["atm_id"] == atm["id"]]
    if kind is not None:
        items = [t for t in items if t["kind"] == kind]
    page, total = validate.paginate([serialize.transaction(t) for t in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


# --------------------------------------------------------------------------- #
# Cash counts + close-out
# --------------------------------------------------------------------------- #
@bp.route("/atms/<aid>/cash-counts", methods=["POST"])
def open_cash_count(aid):
    _, role = authenticate()
    authorize(role, {"FieldTech"})
    atm = lookups.atm(store, aid)
    body = validate.get_body()
    counted = validate.require_int(body, "counted_cents")
    tolerance = validate.optional_int(body, "tolerance_cents", 500)
    # State: cash_status must be LOADED or LOW.
    if atm["cash_status"] not in ("LOADED", "LOW"):
        raise err("ERR_INVALID_STATE",
                  "ATM must be LOADED or LOW to open a cash count.")
    count = recon_svc.open_count(store, atm, counted, tolerance)
    return ok_object(store.clock, serialize.cash_count(count), 201)


@bp.route("/atms/<aid>/cash-counts", methods=["GET"])
def list_cash_counts(aid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech", "SettlementOfficer"})
    atm = lookups.atm(store, aid)
    limit, offset = validate.parse_pagination(request.args)
    items = [c for c in store.sorted_values(store.cash_counts) if c["atm_id"] == atm["id"]]
    page, total = validate.paginate([serialize.cash_count(c) for c in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


@bp.route("/atms/<aid>/cash-counts/<cc_id>/close-out", methods=["POST"])
def close_out(aid, cc_id):
    _, role = authenticate()
    authorize(role, {"FieldTech"})
    atm = lookups.atm(store, aid)          # path id 1
    count = lookups.cash_count(store, cc_id)  # path id 2
    # Nested ownership: count must belong to the ATM in the path.
    if count["atm_id"] != atm["id"]:
        raise err("ERR_NOT_FOUND", "Cash count does not belong to this ATM.")
    # State: ATM must be RECONCILING (PRD §3.6 close-out precondition).
    if atm["cash_status"] != "RECONCILING":
        raise err("ERR_INVALID_STATE", "ATM is not in RECONCILING.")
    count = recon_svc.close_out(store, atm, count)
    return ok_object(store.clock, serialize.cash_count(count))
