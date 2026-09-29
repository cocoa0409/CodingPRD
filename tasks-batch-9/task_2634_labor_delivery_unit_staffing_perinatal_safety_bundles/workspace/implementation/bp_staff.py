"""Staff members (PRD 3.1): 5 endpoints.

POST+GET /obstetric-units/{unitId}/staff-members, GET+PATCH /staff-members/{staffId},
GET /staff-members
"""

from flask import Blueprint

import calc
import common
import const
import rev
import store
from fields import q_bool, q_enum, q_str, s_bool, s_dt, s_enum, s_str
from pipeline import begin
from store import S

bp = Blueprint("staff", __name__)

READ_ROLES = ["ChargeNurse", "BedsideNurse", "ObstetricianAttending",
              "AnesthesiaLead", "PerinatalSafetyOfficer"]


def _filtered(records):
    role = q_enum("staff_role", const.STAFF_ROLES)
    employment = q_enum("employment_status", const.EMPLOYMENT)
    currency = q_enum("drill_currency_state", const.CURRENCY)
    circulating = q_bool("or_circulating_qualified")
    return [s for s in records
            if common.match(s, "staff_role", role)
            and common.match(s, "employment_status", employment)
            and common.match(s, "drill_currency_state", currency)
            and common.match(s, "or_circulating_qualified", circulating)]


@bp.post("/obstetric-units/<unit_id>/staff-members")
def create_staff(unit_id):
    ctx = begin(
        roles=["PerinatalSafetyOfficer", "ChargeNurse"],
        path=[("unit", unit_id)],
        specs=[s_str("full_name", required=True, min_len=1, max_len=120),
               s_enum("staff_role", const.STAFF_ROLES, required=True),
               s_enum("fetal_monitoring_cert_level", const.CERT_LEVELS, default="BASIC"),
               s_dt("credential_expires_at", required=True),
               s_bool("or_circulating_qualified", default=False)],
    )
    staff = store.new_record({
        "unit_id": ctx.p["unit"]["id"],
        "full_name": ctx.v["full_name"],
        "staff_role": ctx.v["staff_role"],
        "fetal_monitoring_cert_level": ctx.v["fetal_monitoring_cert_level"],
        "credential_expires_at": ctx.v["credential_expires_at"],
        "or_circulating_qualified": ctx.v["or_circulating_qualified"],
        "employment_status": "ACTIVE",
        "last_validated_drill_at": None,
        "drill_currency_state": "LAPSED",
        "capacity_units": 0.0,
    })
    # Capacity is keyed by the rostered slot, so a brand new member sits at 0.0.
    S.staff[staff["id"]] = staff
    return common.created("staff", staff)


@bp.get("/obstetric-units/<unit_id>/staff-members")
def list_unit_staff(unit_id):
    ctx = begin(roles=READ_ROLES, path=[("unit", unit_id)])
    found = _filtered(calc.rows("staff", unit_id=ctx.p["unit"]["id"]))
    return common.listing("staff", found, [("created_at", "asc")])


@bp.get("/staff-members")
def list_staff():
    begin(roles=READ_ROLES)
    unit_id = q_str("unit_id")
    found = _filtered([s for s in S.staff.values()
                       if common.match(s, "unit_id", unit_id)])
    return common.listing("staff", found, [("created_at", "asc")])


@bp.get("/staff-members/<staff_id>")
def read_staff(staff_id):
    ctx = begin(roles=READ_ROLES, path=[("staff", staff_id)])
    return common.single("staff", ctx.p["staff"])


@bp.patch("/staff-members/<staff_id>")
def patch_staff(staff_id):
    ctx = begin(
        roles=["PerinatalSafetyOfficer", "ChargeNurse"],
        path=[("staff", staff_id)],
        specs=[s_enum("employment_status", const.EMPLOYMENT),
               s_enum("fetal_monitoring_cert_level", const.CERT_LEVELS),
               s_dt("credential_expires_at"),
               s_bool("or_circulating_qualified")],
    )
    staff = ctx.p["staff"]
    for field in ("employment_status", "fetal_monitoring_cert_level",
                  "credential_expires_at", "or_circulating_qualified"):
        if ctx.v.has(field):
            staff[field] = ctx.v[field]
    rev.touch(staff)
    # Already-snapshotted shift capacities are deliberately never retro-changed.
    calc.recompute_staff_capacity(staff)
    return common.single("staff", staff)
