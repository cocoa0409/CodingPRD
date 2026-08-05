"""Departmental reporting and the logical-clock test-driving endpoint."""
from flask import Blueprint

import calc
import derive
import response
import store
import validate as v
from auth import ALL_ROLES, authenticate
from store import ordered, touch
from util import now, parse_dt, render_dt, set_now

bp = Blueprint("misc", __name__)


@bp.get("/reports/compliance-summary")
def compliance_summary():
    authenticate(["HealthOfficer", "RecordsClerk"])
    county_code = v.q("county_code")

    parcels = ordered(store.parcels.values())
    if county_code is not None:
        parcels = [p for p in parcels if p["county_code"] == county_code]
    in_scope = set(p["id"] for p in parcels)

    permits = [p for p in store.operating_permits.values()
               if p["parcel_id"] in in_scope]
    orders = [r for r in store.repair_orders.values()
              if r["parcel_id"] in in_scope]
    wells = [w for w in store.wells.values() if w["parcel_id"] in in_scope]

    data = {
        "parcel_count": len(parcels),
        "active_operating_permit_count": sum(1 for p in permits
                                             if p["status"] == "ACTIVE"),
        "delinquent_permit_count": sum(1 for p in permits
                                       if p["compliance_status"] == "DELINQUENT"),
        "due_soon_permit_count": sum(1 for p in permits
                                     if p["compliance_status"] == "DUE_SOON"),
        "open_repair_order_count": sum(1 for r in orders
                                       if r["status"] in calc.OPEN_REPAIR_STATES),
        "high_risk_parcel_count": sum(1 for p in parcels
                                      if p["risk_tier"] == "HIGH"),
        "total_fee_balance_cents": sum(p["fee_balance_cents"] for p in parcels),
        "advisory_well_count": sum(1 for w in wells
                                   if w["advisory_status"] in ("ADVISORY",
                                                               "CONDEMNED")),
    }
    return response.ok(data)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ALL_ROLES)
    body = v.body()
    raw = v.req_str(body, "to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        raise v.bad("to_iso8601 must be an ISO 8601 instant.")

    set_now(parsed)
    clock = now()

    # Construction permits die of old age, releasing flow and cancelling visits.
    for permit in ordered(store.construction_permits.values()):
        if permit["status"] in ("ISSUED", "UNDER_CONSTRUCTION") \
                and permit["valid_until"] < clock:
            permit["status"] = "EXPIRED"
            touch(permit)
            derive.release_permit(permit, cancel_failed=False)

    # Operating permits lapse with no further side effects.
    for permit in ordered(store.operating_permits.values()):
        if permit["status"] in ("ACTIVE", "SUSPENDED") \
                and permit["expires_on"] < clock:
            permit["status"] = "EXPIRED"
            touch(permit)

    # Compliance postures are re-derived against the new clock ...
    for permit in ordered(store.operating_permits.values()):
        derive.recompute_operating_permit_compliance(permit)

    # ... and then every parcel's roll-ups, including risk_tier.
    for parcel in ordered(store.parcels.values()):
        derive.recompute_parcel(parcel)

    return response.ok({"current_utc": render_dt(clock)})
