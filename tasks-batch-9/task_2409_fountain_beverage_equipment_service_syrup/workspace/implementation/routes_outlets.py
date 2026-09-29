"""Logical clock (PRD 2.4) and outlets (PRD 3.1)."""

from flask import Blueprint, g

from cascade import recompute_posture, skip_outlet_stops
from calc import brand_mix_report
from core import (
    OUTLET_STATUSES,
    SERVICE_POSTURES,
    THROUGHPUT_TIERS,
    body,
    db,
    f_dt,
    f_num,
    f_str,
    fail,
    get_outlet,
    iso_flex,
    iso_ms,
    new_id,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    q_str,
    require,
    require_outlet_ownership,
    sort_rows,
    stamp_new,
    touch,
    endpoint,
)
from serialize import ser_outlet

bp = Blueprint("outlets", __name__)


# ---------------------------------------------------------------------------
# POST /fountain-network/_clock/set_current_utc
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint(["NetworkAdmin", "SupplyPlanner", "ComplianceOfficer", "ServiceTechnician", "RouteDriver"])
def set_clock():
    payload = body()
    # rung 3
    _raw, target = f_dt(payload, "to_iso8601", required=True)
    # setting the clock mutates no entity
    db.clock = target
    return ok({"current_utc": iso_flex(db.clock)})


# ---------------------------------------------------------------------------
# POST /fountain-network/outlets
# ---------------------------------------------------------------------------
@bp.post("/outlets")
@endpoint(["NetworkAdmin"])
def create_outlet():
    payload = body()
    # rung 3
    name = f_str(payload, "name", required=True)
    account_code = f_str(payload, "account_code", required=True)
    region_code = f_str(payload, "region_code", required=True)
    tier = f_str(payload, "throughput_tier", default="MEDIUM", enum=THROUGHPUT_TIERS)
    hardness = f_num(payload, "water_hardness_gpg", default=10, ge=0, le=60)
    # rung 30
    for row in db.outlets.values():
        if row["account_code"] == account_code:
            fail("ERR_DUPLICATE_ACCOUNT_CODE", "Account code %s already exists." % account_code)

    outlet = {
        "id": new_id(),
        "name": name,
        "account_code": account_code,
        "region_code": region_code,
        "throughput_tier": tier,
        "water_hardness_gpg": hardness,
        "status": "ACTIVE",
        "service_posture": "OPEN",
        "open_compliance_hold_count": 0,
        "overdue_task_count": 0,
        "last_hold_placed_by_user_id": None,
    }
    stamp_new(outlet)
    db.outlets[outlet["id"]] = outlet
    return ok(ser_outlet(outlet), 201)


# ---------------------------------------------------------------------------
# GET /fountain-network/outlets/{id}
# ---------------------------------------------------------------------------
@bp.get("/outlets/<oid>")
@endpoint(
    [
        "NetworkAdmin",
        "SupplyPlanner",
        "RouteDriver",
        "ServiceTechnician",
        "ComplianceOfficer",
        "OutletManager",
    ]
)
def read_outlet(oid):
    return ok(ser_outlet(get_outlet(oid)))


# ---------------------------------------------------------------------------
# GET /fountain-network/outlets
# ---------------------------------------------------------------------------
@bp.get("/outlets")
@endpoint(["NetworkAdmin", "SupplyPlanner", "ComplianceOfficer"])
def list_outlets():
    limit, offset = pagination()
    region_code = q_str("region_code")
    status = q_str("status", enum=OUTLET_STATUSES)
    posture = q_str("service_posture", enum=SERVICE_POSTURES)
    rows = list(db.outlets.values())
    if region_code is not None:
        rows = [r for r in rows if r["region_code"] == region_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if r["service_posture"] == posture]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_outlet(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /fountain-network/outlets/{id}/status-change
# ---------------------------------------------------------------------------
@bp.post("/outlets/<oid>/status-change")
@endpoint(["NetworkAdmin"])
def outlet_status_change(oid):
    payload = body()
    # rung 3
    action = f_str(payload, "action", required=True, enum=("SUSPEND", "REINSTATE", "CLOSE"))
    f_str(payload, "reason_code")
    # rung 4
    outlet = get_outlet(oid)

    # rung 9
    if action == "SUSPEND":
        require(
            outlet["status"] == "ACTIVE",
            "ERR_INVALID_STATE_TRANSITION",
            "Only an ACTIVE outlet can be suspended.",
        )
        outlet["status"] = "SUSPENDED"
        touch(outlet)
        skip_outlet_stops(outlet["id"], "OUTLET_CLOSED", ("PENDING", "ARRIVED"))
    elif action == "REINSTATE":
        require(
            outlet["status"] == "SUSPENDED" and outlet["open_compliance_hold_count"] == 0,
            "ERR_INVALID_STATE_TRANSITION",
            "Only a SUSPENDED outlet without an open compliance hold can be reinstated.",
        )
        outlet["status"] = "ACTIVE"
        recompute_posture(outlet)
    else:  # CLOSE
        require(
            outlet["status"] in ("ACTIVE", "SUSPENDED"),
            "ERR_INVALID_STATE_TRANSITION",
            "Only an ACTIVE or SUSPENDED outlet can be closed.",
        )
        units = [u for u in db.units.values() if u["outlet_id"] == outlet["id"]]
        require(
            all(u["status"] == "RETURNED" for u in units),
            "ERR_INVALID_STATE_TRANSITION",
            "Every dispenser unit at the outlet must be RETURNED before it can be closed.",
        )
        outlet["status"] = "CLOSED"
        touch(outlet)
    return ok(ser_outlet(outlet))


# ---------------------------------------------------------------------------
# POST /fountain-network/outlets/{id}/compliance-hold
# ---------------------------------------------------------------------------
@bp.post("/outlets/<oid>/compliance-hold")
@endpoint(["ComplianceOfficer"])
def outlet_compliance_hold(oid):
    payload = body()
    # rung 3
    action = f_str(payload, "action", required=True, enum=("PLACE", "RELEASE"))
    f_str(payload, "hold_reason_code", required=True)
    # rung 4
    outlet = get_outlet(oid)

    # rung 9
    require(
        outlet["status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "The outlet must be ACTIVE to move its compliance hold.",
    )
    if action == "PLACE":
        require(
            outlet["open_compliance_hold_count"] == 0,
            "ERR_INVALID_STATE_TRANSITION",
            "A compliance hold is already open on this outlet.",
        )
        outlet["open_compliance_hold_count"] = 1
        outlet["last_hold_placed_by_user_id"] = g.user_id
    else:
        require(
            outlet["open_compliance_hold_count"] == 1,
            "ERR_INVALID_STATE_TRANSITION",
            "No compliance hold is currently open on this outlet.",
        )
        outlet["open_compliance_hold_count"] = 0
        # last_hold_placed_by_user_id is deliberately retained (PRD 2.12)
    recompute_posture(outlet)
    return ok(ser_outlet(outlet))


# ---------------------------------------------------------------------------
# GET /fountain-network/outlets/{id}/brand-mix-report
# ---------------------------------------------------------------------------
@bp.get("/outlets/<oid>/brand-mix-report")
@endpoint(["NetworkAdmin", "SupplyPlanner", "OutletManager"])
def outlet_brand_mix_report(oid):
    # rung 4
    outlet = get_outlet(oid)
    # rung 6
    require_outlet_ownership(outlet["id"])
    report = brand_mix_report(outlet, now())
    return ok(
        {
            "outlet_id": outlet["id"],
            "period_start": iso_ms(report["period_start"]),
            "period_end": iso_ms(report["period_end"]),
            "total_ounces": report["total_ounces"],
            "lines": report["lines"],
            "top_brand_name": report["top_brand_name"],
            "promo_available_skus": report["promo_available_skus"],
        }
    )
