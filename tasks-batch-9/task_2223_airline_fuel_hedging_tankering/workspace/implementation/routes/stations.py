"""Station, SupplyContract and inventory-adjustment endpoints (PRD 3.2)."""

import re
from datetime import timedelta

from flask import Blueprint, g

import calc
import domain
import fetch
import serializers as ser
import validators as v
from calc import ZERO, r2
from db import db
from errors import fail
from middleware import (ALL_ROLES, FUEL_ANALYST, FUEL_OPS_CONTROLLER,
                        RISK_POLICY_ADMIN, STATION_COORDINATOR,
                        TREASURY_RISK_MANAGER, endpoint, new_row, touch)
from response import created, ok, ok_list
from validators import parse_date

bp = Blueprint("stations", __name__)

IATA_RE = re.compile(r"^[A-Z]{3}$")
CONTRACT_STATUSES = ("SCHEDULED", "ACTIVE", "EXPIRED")


@bp.post("/fuel/stations")
@endpoint(RISK_POLICY_ADMIN)
def create_station():
    data = v.body()
    iata = v.get_string(data, "iata_code", min_len=3, max_len=3, pattern=IATA_RE)
    name = v.get_string(data, "name", min_len=1, max_len=80)
    fee = v.get_number(data, "into_plane_fee_usd_per_gal", minimum=0, places=4)
    liftings = v.get_number(data, "avg_daily_liftings_gallons", exclusive_minimum=0)
    member = v.get_bool(data, "consortium_member", default=False)
    share = v.get_number(data, "consortium_share_pct", required=False, minimum=0,
                         maximum=100, places=2, default=ZERO)
    pool = v.get_number(data, "consortium_pool_gallons", required=False, minimum=0,
                        default=ZERO)

    if not member and (share != 0 or pool != 0):
        fail("ERR_INVALID_REQUEST",
             "consortium_share_pct and consortium_pool_gallons must be 0 when "
             "consortium_member is false.")

    for row in db.stations.values():
        if row["iata_code"] == iata:
            fail("ERR_DUPLICATE_STATION_CODE", "iata_code %r is already in use." % iata)

    row = new_row()
    row.update({
        "iata_code": iata,
        "name": name,
        "into_plane_fee_usd_per_gal": fee,
        "consortium_member": member,
        "consortium_share_pct": share,
        "consortium_pool_gallons": pool,
        "avg_daily_liftings_gallons": liftings,
        "inventory_gallons": r2(0),
    })
    db.stations[row["id"]] = row
    return created(ser.station(row))


@bp.get("/fuel/stations/<station_id>")
@endpoint(*ALL_ROLES)
def read_station(station_id):
    return ok(ser.station(fetch.station(station_id)))


@bp.post("/fuel/stations/<station_id>/supply-contracts")
@endpoint(RISK_POLICY_ADMIN)
def create_contract(station_id):
    data = v.body()
    ref = v.get_string(data, "contract_ref", min_len=1, max_len=32)
    basis = v.get_enum(data, "index_basis", calc.INDEX_BASES)
    index_price = v.get_number(data, "index_price_usd_per_gal", exclusive_minimum=0, places=4)
    differential = v.get_number(data, "differential_usd_per_gal", places=4)
    start = v.get_date(data, "term_start_date")
    end = v.get_date(data, "term_end_date")
    min_monthly = v.get_number(data, "min_monthly_gallons", minimum=0)
    max_monthly = v.get_number(data, "max_monthly_gallons")

    if index_price + differential <= 0:
        fail("ERR_INVALID_REQUEST",
             "index_price_usd_per_gal + differential_usd_per_gal must be greater than 0.")
    if parse_date(end) < parse_date(start):
        fail("ERR_INVALID_REQUEST",
             "term_end_date must not be earlier than term_start_date.")
    if max_monthly <= min_monthly:
        fail("ERR_INVALID_REQUEST",
             "max_monthly_gallons must be greater than min_monthly_gallons.")

    station = fetch.station(station_id)
    siblings = domain.station_contracts(station["id"])
    new_start = parse_date(start)
    new_end = parse_date(end)

    for other in siblings:
        other_start = parse_date(other["term_start_date"])
        other_end = parse_date(other["term_end_date"])
        if new_start <= other_end and other_start <= new_end:
            fail("ERR_CONTRACT_TERM_OVERLAP",
                 "Contract term intersects contract %r at this station." % other["contract_ref"])

    for other in siblings:
        other_start = parse_date(other["term_start_date"])
        other_end = parse_date(other["term_end_date"])
        if new_start > other_end:
            gap = (new_start - other_end).days
        else:
            gap = (other_start - new_end).days
        if gap < calc.CHANGEOVER_BUFFER_DAYS:
            fail("ERR_CONTRACT_BUFFER_VIOLATION",
                 "Contracts at one station must be separated by at least %d changeover days."
                 % calc.CHANGEOVER_BUFFER_DAYS)

    for other in siblings:
        if other["contract_ref"] == ref:
            fail("ERR_DUPLICATE_CONTRACT_REF",
                 "contract_ref %r is already used at this station." % ref)

    row = new_row()
    row.update({
        "station_id": station["id"],
        "contract_ref": ref,
        "index_basis": basis,
        "index_price_usd_per_gal": index_price,
        "differential_usd_per_gal": differential,
        "term_start_date": start,
        "term_end_date": end,
        "min_monthly_gallons": min_monthly,
        "max_monthly_gallons": max_monthly,
    })
    db.contracts[row["id"]] = row
    return created(ser.contract(row))


@bp.get("/fuel/stations/<station_id>/supply-contracts")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER,
          FUEL_OPS_CONTROLLER, STATION_COORDINATOR)
def list_contracts(station_id):
    limit, offset = v.pagination()
    status = v.enum_filter("status", CONTRACT_STATUSES)
    station = fetch.station(station_id)

    rows = domain.station_contracts(station["id"])
    rows.sort(key=lambda r: (r["term_start_date"], r["_seq"]))
    if status is not None:
        rows = [r for r in rows if domain.contract_status(r) == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.contract(r) for r in page], limit, offset, total)


@bp.post("/fuel/stations/<station_id>/inventory-adjustments")
@endpoint(FUEL_OPS_CONTROLLER, STATION_COORDINATOR)
def inventory_adjustment(station_id):
    data = v.body()
    delta = v.get_number(data, "delta_gallons")
    reason = v.get_string(data, "reason", min_len=1)
    pool = v.get_number(data, "consortium_pool_gallons", required=False, minimum=0)

    station = fetch.station(station_id)

    if g.user_role == STATION_COORDINATOR and g.user_id != station["id"]:
        fail("ERR_STATION_NOT_OWNED",
             "A StationCoordinator may only adjust inventory at its own station.")

    new_inventory = station["inventory_gallons"] + delta
    if new_inventory < 0:
        fail("ERR_INVALID_REQUEST",
             "delta_gallons would drive inventory_gallons below zero.")

    station["inventory_gallons"] = r2(new_inventory)
    if pool is not None:
        station["consortium_pool_gallons"] = pool
    touch(station)
    return ok(ser.station(station))
