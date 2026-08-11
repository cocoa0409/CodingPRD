"""Vessels, quota ledgers, trips, landings and vendor settlement
(PRD 3.3, 3.9)."""
from flask import Blueprint, g, request

import authz
import calc
import clock
import constants as C
import guards
import lookup
import store
import validate as V
from errors import ApiError
from routes.common import created, filter_eq, listing, ok, always

bp = Blueprint("vessels", __name__)


# --------------------------------------------------------------------------
# Vessels
# --------------------------------------------------------------------------
@bp.post("/vessels")
def create_vessel():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "vessel_name", "permit_number", "home_port", "gear_types")
    gear_types = V.enum_list_field(body["gear_types"], C.GEAR_TYPES, "gear_types")
    vessel_name = V.string_field(body["vessel_name"], "vessel_name", 1, 120)
    permit = V.string_field(body["permit_number"], "permit_number", 1, 32)
    home_port = V.string_field(body["home_port"], "home_port", 1)
    guards.unique("Vessel", lambda v: v["permit_number"] == permit)      # rung 53
    rec = store.create("Vessel", {
        "vessel_name": vessel_name, "permit_number": permit,
        "home_port": home_port, "gear_types": gear_types,
        "compliance_status": "COMPLIANT", "violation_count": 0,
    })
    return created(rec)


@bp.get("/vessels/<vid>")
def read_vessel(vid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    vessel = lookup.vessel(vid)                                          # rung 11
    authz.own_vessel(vessel["id"])                                       # rung 22
    return ok(vessel)


@bp.post("/vessels/<vid>/compliance")
def move_compliance(vid):
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "target_status")                                     # rung 4
    target = V.enum_field(body["target_status"], C.COMPLIANCE_STATUSES,
                          "target_status")                              # rung 5
    vessel = lookup.vessel(vid)                                          # rung 11
    current = vessel["compliance_status"]
    allowed = {("COMPLIANT", "PROBATION"), ("PROBATION", "SUSPENDED"),
               ("SUSPENDED", "COMPLIANT"), ("PROBATION", "COMPLIANT")}
    guards.state_require((current, target) in allowed,                   # rung 28
                         "The compliance axis declares no %s -> %s transition."
                         % (current, target))

    if target == "PROBATION":
        vessel["violation_count"] = vessel["violation_count"] + 1
    elif target == "SUSPENDED":
        vessel["violation_count"] = vessel["violation_count"] + 1
        for ledger in store.ordered("QuotaLedger",
                                    lambda l: l["vessel_id"] == vessel["id"]
                                    and l["status"] in ("OPEN", "WARNING")):
            ledger["status"] = "SUSPENDED"
            store.touch(ledger)
    elif target == "COMPLIANT" and current == "SUSPENDED":
        for ledger in store.ordered("QuotaLedger",
                                    lambda l: l["vessel_id"] == vessel["id"]
                                    and l["status"] == "SUSPENDED"):
            ledger["status"] = calc.ledger_status_after(ledger)
            store.touch(ledger)
    vessel["compliance_status"] = target
    store.touch(vessel)
    return ok(vessel)


# --------------------------------------------------------------------------
# Quota ledgers
# --------------------------------------------------------------------------
@bp.post("/quota-ledgers")
def create_ledger():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "vessel_id", "season_id", "species", "management_area",
              "entitlement_pounds", "species_open_date", "species_close_date",
              "permitted_gears")                                         # rung 4
    species = V.enum_field(body["species"], C.SPECIES, "species")
    gears = V.enum_list_field(body["permitted_gears"], C.GEAR_TYPES,
                              "permitted_gears")                        # rung 5
    V.id_field(body["vessel_id"], "vessel_id")
    V.id_field(body["season_id"], "season_id")
    area = V.string_field(body["management_area"], "management_area", 1, 16)  # rung 6
    entitlement = V.pounds_field(body["entitlement_pounds"], "entitlement_pounds")
    open_date = V.datetime_field(body["species_open_date"], "species_open_date")
    close_date = V.datetime_field(body["species_close_date"], "species_close_date")
    if close_date < open_date:
        raise ApiError("ERR_VALIDATION",
                       "species_close_date must be at or after species_open_date.")
    area_closed = body.get("area_closed")
    area_closed = False if area_closed is None else \
        V.bool_field(area_closed, "area_closed")
    penalty = body.get("area_sensitivity_penalty")
    penalty = 0 if penalty is None else \
        V.int_field(penalty, "area_sensitivity_penalty", 0, 40)
    adjustment = body.get("species_stock_adjustment")
    adjustment = 0 if adjustment is None else \
        V.int_field(adjustment, "species_stock_adjustment", -20, 10)

    season = lookup.season(body["season_id"])                            # rung 7
    vessel = lookup.vessel(body["vessel_id"])                            # rung 11
    guards.season_not_closed(season)                                     # rung 24
    guards.unique("QuotaLedger",
                  lambda l: l["vessel_id"] == vessel["id"]
                  and l["season_id"] == season["id"]
                  and l["species"] == species
                  and l["management_area"] == area)                      # rung 53

    rec = store.create("QuotaLedger", {
        "vessel_id": vessel["id"], "season_id": season["id"],
        "species": species, "management_area": area,
        "entitlement_pounds": entitlement, "committed_pounds": calc.ZERO_LB,
        "remaining_pounds": entitlement, "area_closed": area_closed,
        "species_open_date": open_date, "species_close_date": close_date,
        "permitted_gears": gears, "area_sensitivity_penalty": penalty,
        "species_stock_adjustment": adjustment, "status": "OPEN",
    })
    return created(rec)


@bp.get("/quota-ledgers/<lid>")
def read_ledger(lid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    ledger = lookup.quota_ledger(lid)                                    # rung 12
    authz.own_vessel(ledger["vessel_id"])                                # rung 22
    return ok(ledger)


@bp.get("/quota-ledgers")
def list_ledgers():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    pred = filter_eq(request.args, "vessel_id", lambda r: r["vessel_id"], always)
    pred = filter_eq(request.args, "season_id", lambda r: r["season_id"], pred)
    return listing("QuotaLedger", request.args, pred)


# --------------------------------------------------------------------------
# Trips
# --------------------------------------------------------------------------
@bp.post("/trips")
def create_trip():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    body = V.body_of(request)
    V.require(body, "vessel_id", "season_id", "quota_ledger_id", "gear_type",
              "management_area")                                         # rung 4
    gear = V.enum_field(body["gear_type"], C.GEAR_TYPES, "gear_type")    # rung 5
    V.id_field(body["vessel_id"], "vessel_id")
    V.id_field(body["season_id"], "season_id")
    V.id_field(body["quota_ledger_id"], "quota_ledger_id")
    area = V.string_field(body["management_area"], "management_area", 1, 16)  # rung 6

    season = lookup.season(body["season_id"])                            # rung 7
    vessel = lookup.vessel(body["vessel_id"])                            # rung 11
    ledger = lookup.quota_ledger(body["quota_ledger_id"])                # rung 12
    authz.own_vessel(vessel["id"])                                       # rung 22
    guards.reference(area == ledger["management_area"],                  # rung 23
                     "The trip's management_area must equal the ledger's.")
    guards.reference(vessel["id"] == ledger["vessel_id"],
                     "The trip's vessel_id must equal the ledger's vessel_id.")
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25
    guards.vessel_not_suspended(vessel)                                  # rung 27

    rec = store.create("Trip", {
        "vessel_id": vessel["id"], "season_id": season["id"],
        "quota_ledger_id": ledger["id"], "gear_type": gear,
        "management_area": area, "landed_at": None, "offload_minutes": 0,
        "sustainability_score": 0, "sustainability_band": "GREEN",
        "status": "PLANNED",
    })
    return created(rec)


@bp.get("/trips/<tid>")
def read_trip(tid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    trip = lookup.trip(tid)                                              # rung 13
    authz.own_vessel(trip["vessel_id"])                                  # rung 22
    return ok(trip)


@bp.get("/trips")
def list_trips():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    a = request.args
    pred = filter_eq(a, "vessel_id", lambda r: r["vessel_id"], always)
    pred = filter_eq(a, "season_id", lambda r: r["season_id"], pred)
    pred = filter_eq(a, "quota_ledger_id", lambda r: r["quota_ledger_id"], pred)
    return listing("Trip", a, pred)


# --------------------------------------------------------------------------
# POST /csf/trips/{id}/land
# --------------------------------------------------------------------------
@bp.post("/trips/<tid>/land")
def land(tid):
    authz.require_roles(C.ROLE_VENDOR)
    body = V.body_of(request)
    V.require(body, "species", "landed_pounds_gross", "ex_vessel_price_cents_per_lb",
              "offload_minutes")                                         # rung 4
    species = V.enum_field(body["species"], C.SPECIES, "species")        # rung 5
    gross = V.pounds_field(body["landed_pounds_gross"], "landed_pounds_gross")  # rung 6
    ex_vessel_price = V.int_field(body["ex_vessel_price_cents_per_lb"],
                                  "ex_vessel_price_cents_per_lb", minimum=1)
    offload_minutes = V.int_field(body["offload_minutes"], "offload_minutes",
                                  minimum=0)
    allow_partial = body.get("allow_partial_fill")
    allow_partial = False if allow_partial is None else \
        V.bool_field(allow_partial, "allow_partial_fill")

    trip = lookup.trip(tid)                                              # rung 13
    authz.own_vessel(trip["vessel_id"])                                  # rung 22
    ledger = lookup.maybe("QuotaLedger", trip["quota_ledger_id"])
    vessel = lookup.maybe("Vessel", trip["vessel_id"])
    season = lookup.maybe("Season", trip["season_id"])
    guards.reference(species == ledger["species"],                       # rung 23
                     "The lot's species must equal the ledger's species.")
    guards.season_not_closed(season)                                     # rung 24
    guards.season_status(season, "OPEN")                                 # rung 25
    guards.vessel_not_suspended(vessel)                                  # rung 27
    guards.state_in(trip["status"], ("PLANNED",))                        # rung 28

    if ledger["area_closed"]:                                            # rung 32
        raise ApiError("ERR_AREA_CLOSED")
    now = clock.now()
    if now < ledger["species_open_date"] or now > ledger["species_close_date"]:
        raise ApiError("ERR_SPECIES_OUT_OF_SEASON")                      # rung 33
    if trip["gear_type"] not in ledger["permitted_gears"] or \
            trip["gear_type"] not in vessel["gear_types"]:
        raise ApiError("ERR_GEAR_NOT_PERMITTED")                         # rung 34

    score, band = calc.sustainability_score(
        trip["gear_type"], ledger["area_sensitivity_penalty"],
        ledger["species_stock_adjustment"])
    if band == "RED":
        raise ApiError("ERR_SUSTAINABILITY_BLOCKED")                     # rung 35

    if ledger["status"] in ("EXHAUSTED", "SUSPENDED"):                   # rung 36
        raise ApiError("ERR_QUOTA_EXCEEDED")
    debit = calc.quota_debit(gross, ledger["remaining_pounds"], allow_partial)
    if debit is None:
        raise ApiError("ERR_QUOTA_EXCEEDED")
    net, discarded = debit

    ledger["committed_pounds"] = calc.lb(ledger["committed_pounds"] + net)
    ledger["remaining_pounds"] = calc.lb(
        ledger["entitlement_pounds"] - ledger["committed_pounds"])
    ledger["status"] = calc.ledger_status_after(ledger)
    store.touch(ledger)

    trip["status"] = "LANDED"
    trip["landed_at"] = now
    trip["offload_minutes"] = offload_minutes
    trip["sustainability_score"] = score
    trip["sustainability_band"] = band
    store.touch(trip)

    lot = store.create("LandingLot", {
        "trip_id": trip["id"], "species": species,
        "landed_pounds_gross": gross, "landed_pounds_net": net,
        "discarded_over_quota_pounds": discarded, "allocation_week_index": None,
        "allocated_pounds_total": calc.ZERO_LB,
        "surplus_secondary_pounds": calc.ZERO_LB,
        "surplus_donated_pounds": calc.ZERO_LB,
        "split_pounds_total": calc.ZERO_LB,
        "ex_vessel_price_cents_per_lb": ex_vessel_price,
        "retail_value_cents_per_lb": calc.lot_retail_value(species),
        "cold_chain_cumulative_minutes": 0, "cold_chain_max_single_minutes": 0,
        "peak_temp_c": calc.Decimal("0"), "allocation_variant": "NONE",
        "status": "RECORDED", "quality_status": "CLEAR",
    })
    return created(lot)


# --------------------------------------------------------------------------
# POST /csf/trips/{id}/verify
# --------------------------------------------------------------------------
@bp.post("/trips/<tid>/verify")
def verify(tid):
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "accepted")                                          # rung 4
    accepted = V.bool_field(body["accepted"], "accepted")                # rung 6
    trip = lookup.trip(tid)                                              # rung 13
    guards.season_not_closed(lookup.maybe("Season", trip["season_id"]))  # rung 24
    guards.state_in(trip["status"], ("LANDED",))                         # rung 28

    lot = store.find("LandingLot", lambda l: l["trip_id"] == trip["id"])
    if accepted:
        trip["status"] = "VERIFIED"
        store.touch(trip)
        return ok(trip)

    guards.state_require(lot is not None and lot["status"] == "RECORDED",
                         "A landing report can only be rejected while its lot is RECORDED.")
    ledger = lookup.maybe("QuotaLedger", trip["quota_ledger_id"])
    if ledger is not None:
        ledger["committed_pounds"] = calc.lb(
            ledger["committed_pounds"] - lot["landed_pounds_net"])
        ledger["remaining_pounds"] = calc.lb(
            ledger["entitlement_pounds"] - ledger["committed_pounds"])
        if ledger["status"] in ("OPEN", "WARNING", "EXHAUSTED"):
            ledger["status"] = calc.ledger_status_after(ledger)
        store.touch(ledger)
    lot["status"] = "CLOSED"
    store.touch(lot)
    trip["status"] = "REJECTED"
    store.touch(trip)
    return ok(trip)


# --------------------------------------------------------------------------
# POST /csf/trips/{id}/settlements
# --------------------------------------------------------------------------
@bp.post("/trips/<tid>/settlements")
def create_settlement(tid):
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "expected_trip_version")                             # rung 4
    expected = V.int_field(body["expected_trip_version"], "expected_trip_version",
                           minimum=0)                                    # rung 6
    trip = lookup.trip(tid)                                              # rung 13
    guards.season_not_closed(lookup.maybe("Season", trip["season_id"]))  # rung 24
    guards.state_in(trip["status"], ("VERIFIED",))                       # rung 28
    guards.expected_version(expected, trip)                              # rung 31

    lot = store.find("LandingLot", lambda l: l["trip_id"] == trip["id"])
    guards.state_require(lot is not None, "The trip carries no landing lot.")

    ex_vessel, premium, gross = calc.vendor_settlement_gross(
        lot["landed_pounds_net"], lot["ex_vessel_price_cents_per_lb"],
        trip["sustainability_band"])
    dock, ice, labor, levy, deductions = calc.vendor_settlement_deductions(
        lot["landed_pounds_net"], trip["offload_minutes"], gross)
    holdback = calc.holdback_cents(gross)

    for older in store.ordered("SettlementStatement",
                               lambda s: s["trip_id"] == trip["id"]
                               and s["status"] in ("DRAFT", "PROVISIONAL")):
        older["status"] = "VOID"
        store.touch(older)

    rec = store.create("SettlementStatement", {
        "trip_id": trip["id"], "landing_lot_id": lot["id"],
        "vessel_id": trip["vessel_id"], "ex_vessel_cents": ex_vessel,
        "premium_cents": premium, "gross_cents": gross,
        "dock_fee_cents": dock, "ice_handling_cents": ice,
        "offload_labor_cents": labor, "handling_levy_cents": levy,
        "deductions_cents": deductions, "holdback_cents": holdback,
        "holdback_released_cents": 0, "holdback_forfeited_cents": 0,
        "offset_cents": 0, "net_payable_cents": gross - deductions - holdback,
        "net_paid_cents": 0, "variant": "PROVISIONAL", "status": "PROVISIONAL",
    })
    store.touch(trip)
    return created(rec)


@bp.get("/settlement-statements/<sid>")
def read_settlement(sid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    statement = lookup.settlement(sid)                                   # rung 19
    authz.own_vessel(statement["vessel_id"])                             # rung 22
    return ok(statement)


@bp.get("/settlement-statements")
def list_settlements():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_VENDOR)
    a = request.args
    pred = filter_eq(a, "trip_id", lambda r: r["trip_id"], always)
    pred = filter_eq(a, "landing_lot_id", lambda r: r["landing_lot_id"], pred)
    pred = filter_eq(a, "vessel_id", lambda r: r["vessel_id"], pred)
    return listing("SettlementStatement", a, pred)


@bp.post("/settlement-statements/<sid>/finalize")
def finalize_settlement(sid):
    authz.require_roles(C.ROLE_ADMIN)
    statement = lookup.settlement(sid)                                   # rung 19
    trip = lookup.maybe("Trip", statement["trip_id"])
    guards.season_not_closed(lookup.maybe("Season", trip["season_id"]))  # rung 24
    guards.state_in(statement["status"], ("PROVISIONAL", "HELD"))        # rung 28
    lot = lookup.maybe("LandingLot", statement["landing_lot_id"])
    if lot["quality_status"] == "HOLD":                                  # rung 52
        raise ApiError("ERR_HOLDBACK_NOT_CLEARED")
    # The remaining half of rung 28's from-state pairing is evaluated after rung
    # 52 so that a statement whose lot is still on HOLD reports
    # ERR_HOLDBACK_NOT_CLEARED rather than swallowing rung 52 entirely.
    if statement["status"] == "PROVISIONAL":
        guards.state_in(lot["quality_status"], ("CLEAR", "RELEASED"))
    else:
        guards.state_in(lot["quality_status"], ("DISCOUNTED", "DISCARDED"))

    released, forfeited, offset, net = calc.settlement_final(
        lot["quality_status"], statement["gross_cents"],
        statement["deductions_cents"], statement["holdback_cents"],
        statement["ex_vessel_cents"])
    statement["holdback_released_cents"] = released
    statement["holdback_forfeited_cents"] = forfeited
    statement["offset_cents"] = offset
    statement["net_payable_cents"] = net
    statement["variant"] = "FINAL"
    statement["status"] = "FINAL"
    store.touch(statement)
    return ok(statement)


@bp.post("/settlement-statements/<sid>/pay")
def pay_settlement(sid):
    authz.require_roles(C.ROLE_ADMIN)
    statement = lookup.settlement(sid)                                   # rung 19
    trip = lookup.maybe("Trip", statement["trip_id"])
    guards.season_not_closed(lookup.maybe("Season", trip["season_id"]))  # rung 24
    guards.state_in(statement["status"], ("FINAL",))                     # rung 28
    statement["net_paid_cents"] = statement["net_payable_cents"]
    statement["status"] = "PAID"
    store.touch(statement)
    return ok(statement)
