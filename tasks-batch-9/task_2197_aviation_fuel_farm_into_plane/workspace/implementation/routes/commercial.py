"""Airline accounts, flights and fuel release authorizations."""
import re

from flask import Blueprint, request

import calc
import services as svc
from authz import (auth, body, enum, opt_bool, opt_num, out_of_range, req_dt,
                   req_num, req_str, resolve, resolve_ref, rng)
from core import (ApiError, D, base_row, created, db, f2, fmt_dt, listing, now,
                  now_iso, ok, parse_dt, public, touch)

bp = Blueprint("commercial", __name__)

IATA2 = re.compile(r"^[A-Z0-9]{2}$")
CONTRACT_TYPES = ("CONTRACT_FUEL", "INTO_PLANE_ONLY")


def own_account(uid, role, account_id):
    """An AirlineRep's X-User-ID is the AirlineAccount id it may act for."""
    if role == "AirlineRep" and uid != account_id:
        raise ApiError("ERR_ACCOUNT_OWNERSHIP_REQUIRED",
                       "This airline representative may not act for that account")


# ------------------------------------------------------------------ accounts
@bp.post("/airline-accounts")
def create_account():
    auth("ConsortiumAdmin")
    data = body()
    iata = req_str(data, "airline_iata_code")
    legal = req_str(data, "legal_name")
    contract = req_str(data, "contract_type")
    base_price = req_num(data, "base_price_cents_per_liter")
    credit_limit = req_num(data, "credit_limit_cents")
    tax_exempt = opt_bool(data, "tax_exempt", False)

    if not IATA2.match(iata):
        out_of_range("airline_iata_code must be exactly 2 uppercase alphanumeric characters")
    enum(contract, "contract_type", CONTRACT_TYPES)
    rng(base_price, "base_price_cents_per_liter", minimum=0)
    rng(credit_limit, "credit_limit_cents", minimum=0)

    for a in db.accounts.values():
        if a["airline_iata_code"] == iata:
            raise ApiError("ERR_DUPLICATE_KEY", "airline_iata_code %s already exists" % iata)

    account = base_row()
    account.update({
        "airline_iata_code": iata,
        "legal_name": legal,
        "contract_type": contract,
        "base_price_cents_per_liter": 0.0 if contract == "INTO_PLANE_ONLY" else float(D(base_price)),
        "credit_limit_cents": int(D(credit_limit)),
        "tax_exempt": tax_exempt,
        "status": "ACTIVE",
        "invoiced_exposure_cents": 0,
        "accrual_exposure_cents": 0,
    })
    db.accounts[account["id"]] = account
    return created(public(account))


@bp.get("/airline-accounts/<aid>")
def get_account(aid):
    uid, role = auth("ConsortiumAdmin", "BillingClerk", "AirlineRep")
    account = resolve(db.accounts, aid, "Airline account not found")
    own_account(uid, role, account["id"])
    calc.recompute_exposure(account)
    return ok(public(account))


# ------------------------------------------------------------------ flights
@bp.post("/flights")
def create_flight():
    uid, role = auth("AirlineRep", "ConsortiumAdmin")
    data = body()
    account = resolve_ref(db.accounts, data.get("airline_account_id"),
                          "Airline account not found") if isinstance(
                              data.get("airline_account_id"), str) else None
    account_id = req_str(data, "airline_account_id")
    flight_number = req_str(data, "flight_number")
    tail = req_str(data, "tail_number")
    departure = req_dt(data, "scheduled_departure_utc")
    stand = req_str(data, "stand_code")

    if account is not None:
        own_account(uid, role, account["id"])
    for f in db.flights.values():
        if (f["airline_account_id"] == account_id
                and f["flight_number"] == flight_number
                and f["scheduled_departure_utc"] == fmt_dt(departure)):
            raise ApiError("ERR_DUPLICATE_KEY",
                           "flight_number %s already exists for that departure" % flight_number)

    flight = base_row()
    flight.update({
        "airline_account_id": account_id,
        "flight_number": flight_number,
        "tail_number": tail,
        "scheduled_departure_utc": fmt_dt(departure),
        "stand_code": stand,
        "status": "SCHEDULED",
    })
    db.flights[flight["id"]] = flight
    return created(public(flight))


@bp.get("/flights")
def list_flights():
    uid, role = auth("ConsortiumAdmin", "AirlineRep", "IntoPlaneAgent", "BillingClerk")
    rows = list(db.flights.values())
    if role == "AirlineRep":
        rows = [f for f in rows if f["airline_account_id"] == uid]
    account_id = request.args.get("airline_account_id")
    status = request.args.get("status")
    if account_id:
        rows = [f for f in rows if f["airline_account_id"] == account_id]
    if status:
        rows = [f for f in rows if f["status"] == status]
    return listing(rows)


@bp.get("/flights/<fid>")
def get_flight(fid):
    uid, role = auth("ConsortiumAdmin", "AirlineRep", "IntoPlaneAgent", "BillingClerk")
    flight = resolve(db.flights, fid, "Flight not found")
    own_account(uid, role, flight["airline_account_id"])
    return ok(public(flight))


# ------------------------------------------------------------------ authorizations
@bp.post("/fuel-authorizations")
def create_authorization():
    uid, role = auth("AirlineRep", "BillingClerk")
    data = body()
    account = resolve_ref(db.accounts, data.get("airline_account_id"),
                          "Airline account not found") if isinstance(
                              data.get("airline_account_id"), str) else None
    flight = resolve_ref(db.flights, data.get("flight_id"),
                         "Flight not found") if isinstance(
                             data.get("flight_id"), str) else None
    account_id = req_str(data, "airline_account_id")
    flight_id = req_str(data, "flight_id")
    max_liters = req_num(data, "max_authorized_liters")
    rng(max_liters, "max_authorized_liters", minimum=0, exclusive_min=True)

    own_account(uid, role, account_id)
    if flight is not None and account is not None and flight["airline_account_id"] != account["id"]:
        raise ApiError("ERR_CROSS_FARM_REFERENCE",
                       "Flight does not belong to the named airline account")

    code, day_sequence, expires = calc.mint_authorization(account, flight)
    row = base_row()
    row.update({
        "airline_account_id": account_id,
        "flight_id": flight_id,
        "max_authorized_liters": f2(max_liters),
        "authorization_code": code,
        "day_sequence": day_sequence,
        "expires_at_utc": expires,
        "status": "ISSUED",
        "voided_reason": None,
    })
    db.authorizations[row["id"]] = row
    svc.expire_authorization(row)
    return created(public(row))


@bp.get("/fuel-authorizations")
def list_authorizations():
    uid, role = auth("ConsortiumAdmin", "AirlineRep", "IntoPlaneAgent", "BillingClerk")
    rows = list(db.authorizations.values())
    for a in rows:
        svc.expire_authorization(a)
    if role == "AirlineRep":
        rows = [a for a in rows if a["airline_account_id"] == uid]
    account_id = request.args.get("airline_account_id")
    flight_id = request.args.get("flight_id")
    status = request.args.get("status")
    if account_id:
        rows = [a for a in rows if a["airline_account_id"] == account_id]
    if flight_id:
        rows = [a for a in rows if a["flight_id"] == flight_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    return listing(rows)


@bp.get("/fuel-authorizations/<aid>")
def get_authorization(aid):
    uid, role = auth("ConsortiumAdmin", "AirlineRep", "IntoPlaneAgent", "BillingClerk")
    row = resolve(db.authorizations, aid, "Fuel authorization not found")
    own_account(uid, role, row["airline_account_id"])
    svc.expire_authorization(row)
    return ok(public(row))


@bp.post("/fuel-authorizations/<aid>/void")
def void_authorization(aid):
    auth("BillingClerk")
    row = resolve(db.authorizations, aid, "Fuel authorization not found")
    body()
    svc.expire_authorization(row)
    svc.terminal_guard("authorization", row["status"])
    if row["status"] != "ISSUED":
        raise ApiError("ERR_AUTHORIZATION_NOT_REDEEMABLE",
                       "Authorization status is %s, not ISSUED" % row["status"])
    for o in db.orders.values():
        if o["fuel_authorization_id"] == row["id"] and o["status"] in ("ASSIGNED", "FUELING"):
            raise ApiError("ERR_INVALID_ORDER_STATE",
                           "An order quoting this authorization is ASSIGNED or FUELING")
    svc.void_authorization(row, "MANUAL")
    return ok(public(row))
