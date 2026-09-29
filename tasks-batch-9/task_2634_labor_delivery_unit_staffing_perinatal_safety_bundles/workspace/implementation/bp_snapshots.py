"""Quality measure snapshots (PRD 3.9): 5 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_dt, s_int
from pipeline import begin, need, run_checks
from store import S

bp = Blueprint("snapshots", __name__)

READ_ROLES = ["PerinatalSafetyOfficer", "ChargeNurse"]


def _filtered(records):
    status = q_enum("status", const.SNAPSHOT_STATUSES)
    superseded = q_str("superseded_by_snapshot_id")
    return [s for s in records
            if common.match(s, "status", status)
            and common.match(s, "superseded_by_snapshot_id", superseded)]


@bp.post("/obstetric-units/<unit_id>/quality-measure-snapshots")
def create_snapshot(unit_id):
    ctx = begin(
        roles=["PerinatalSafetyOfficer"],
        path=[("unit", unit_id)],
        specs=[s_dt("period_start_utc", required=True),
               s_dt("period_end_utc", required=True),
               s_int("expected_unit_version", required=True)],
        occ=("expected_unit_version", "ERR_STALE_UNIT_VERSION",
             lambda c: c.p["unit"]),
    )
    unit = ctx.p["unit"]
    start = ctx.v["period_start_utc"]
    end = ctx.v["period_end_utc"]

    def period():
        need(end > start, "ERR_MEASURE_PERIOD_INVALID")

    run_checks([(14.2, period)])

    snap = store.new_record({
        "unit_id": unit["id"],
        "period_start_utc": start,
        "period_end_utc": end,
        "attribution_basis": "DELIVERY_COHORT",
        "ntsv_cesarean_numerator": 0,
        "ntsv_cesarean_denominator": 0,
        "ntsv_cesarean_rate_pct": None,
        "episiotomy_numerator": 0,
        "episiotomy_denominator": 0,
        "episiotomy_rate_pct": None,
        "shadow_ntsv_rate_pct": None,
        "composite_quality_index": None,
        "status": "DRAFT",
        "certified_at": None,
        "certified_by_user_id": None,
        "superseded_by_snapshot_id": None,
    })
    calc.compute_snapshot(snap)
    S.snapshots[snap["id"]] = snap
    # An identical window supersedes every prior row; a CERTIFIED one keeps its
    # frozen counts for audit and is never recomputed.
    for other in calc.rows("snapshots", unit_id=unit["id"]):
        if other["id"] == snap["id"] or other["status"] == "SUPERSEDED":
            continue
        if (other["period_start_utc"] == start and other["period_end_utc"] == end):
            other["status"] = "SUPERSEDED"
            other["superseded_by_snapshot_id"] = snap["id"]
            rev.touch(other)
    rev.touch(unit)
    return common.created("snapshots", snap)


@bp.get("/obstetric-units/<unit_id>/quality-measure-snapshots")
def list_unit_snapshots(unit_id):
    ctx = begin(roles=READ_ROLES, path=[("unit", unit_id)])
    found = _filtered(calc.rows("snapshots", unit_id=ctx.p["unit"]["id"]))
    return common.listing("snapshots", found,
                          [("period_start_utc", "desc"), ("created_at", "desc")])


@bp.get("/quality-measure-snapshots")
def list_snapshots():
    begin(roles=READ_ROLES)
    unit_id = q_str("unit_id")
    found = _filtered([s for s in S.snapshots.values()
                       if common.match(s, "unit_id", unit_id)])
    return common.listing("snapshots", found,
                          [("period_start_utc", "asc"), ("created_at", "asc")])


@bp.get("/quality-measure-snapshots/<snapshot_id>")
def read_snapshot(snapshot_id):
    ctx = begin(roles=READ_ROLES, path=[("snapshot", snapshot_id)])
    return common.single("snapshots", ctx.p["snapshot"])


@bp.post("/quality-measure-snapshots/<snapshot_id>/certify")
def certify_snapshot(snapshot_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"], path=[("snapshot", snapshot_id)])
    snap = ctx.p["snapshot"]

    def declared():
        need(snap["status"] == "DRAFT", "ERR_INVALID_STATE_TRANSITION")

    def duties():
        for review in calc.rows("reviews"):
            enc = S.encounters.get(review["encounter_id"])
            if enc is None or enc["unit_id"] != snap["unit_id"]:
                continue
            opened = review["opened_at"]
            if snap["period_start_utc"] <= opened < snap["period_end_utc"]:
                need(review["facilitator_staff_id"] != ctx.user_id,
                     "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    def denominators():
        need(snap["ntsv_cesarean_denominator"] >= 1
             and snap["episiotomy_denominator"] >= 1,
             "ERR_EMPTY_MEASURE_DENOMINATOR")

    def closed_period():
        need(snap["period_end_utc"] <= clock.now(), "ERR_MEASURE_PERIOD_NOT_CLOSED")

    def bundles():
        # The very last check evaluated on any request in the system.
        for enc in calc.delivery_cohort(snap):
            for activation in calc.rows("activations", encounter_id=enc["id"]):
                need(activation["status"] in ("CLOSED", "RESCINDED"),
                     "ERR_BUNDLE_NOT_CLOSED")

    run_checks([(8, declared), (10, duties), (16, denominators),
                (16.1, closed_period), (16.2, bundles)])

    snap["status"] = "CERTIFIED"
    snap["certified_at"] = clock.now()
    snap["certified_by_user_id"] = ctx.user_id
    rev.touch(snap)
    return common.single("snapshots", snap)
