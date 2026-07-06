"""FeeRun endpoints & state machine (PRD §3.4, §3.5, §2.6)."""

from datetime import date

from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from services import calculations as calc
from util import body, require_str, require_iso_date, require_int, require_enum, pagination, paginate

bp = Blueprint("fee_runs", __name__)

READ_ROLES = {"BillingAdmin", "Advisor", "ComplianceOfficer"}
ACTIONS = {"CALCULATE", "RECALC", "FINALIZE", "VOID"}


def serialize(r):
    return {
        "id": r["id"],
        "household_id": r["household_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "billing_method_snapshot": r["billing_method_snapshot"],
        "fee_schedule_snapshot_id": r["fee_schedule_snapshot_id"],
        "basis_aum_cents": r["basis_aum_cents"],
        "gross_fee_cents": r["gross_fee_cents"],
        "assessed_fee_cents": r["assessed_fee_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _ranges_overlap(s1, e1, s2, e2):
    """Inclusive day-range overlap on ISO dates."""
    a0, a1 = date.fromisoformat(s1), date.fromisoformat(e1)
    b0, b1 = date.fromisoformat(s2), date.fromisoformat(e2)
    return a0 <= b1 and b0 <= a1


@bp.route("/fee-runs", methods=["POST"])
def create():
    user_id, role = authenticate()
    authorize(role, {"BillingAdmin"})
    data = body()
    household_id = require_str(data, "household_id")
    period_start = require_iso_date(data, "period_start")
    period_end = require_iso_date(data, "period_end")
    expected_version = require_int(data, "expected_household_version")
    # body-reference existence (priority 4)
    household = ref_or_422(db.households, household_id, "household_id")
    # period validity (priority 12)
    if date.fromisoformat(period_end) <= date.fromisoformat(period_start):
        raise err("ERR_INVALID_PERIOD", "period_end must be strictly after period_start")
    # OCC (priority 13)
    if expected_version != household["version"]:
        raise err("ERR_STALE_HOUSEHOLD_VERSION", "expected_household_version is stale")
    r = {
        "household_id": household_id,
        "period_start": period_start,
        "period_end": period_end,
        "billing_method_snapshot": household["billing_method"],
        "fee_schedule_snapshot_id": household["fee_schedule_id"],
        "basis_aum_cents": 0,
        "gross_fee_cents": 0,
        "assessed_fee_cents": 0,
        "status": "DRAFT",
        "creator_user_id": user_id,
    }
    stamp_new(r)
    db.fee_runs[r["id"]] = r
    # creating the run is a household-level mutation: bump household version
    touch(household)
    return created(serialize(r))


@bp.route("/fee-runs/<rid>", methods=["GET"])
def read(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    r = get_or_404(db.fee_runs, rid)
    return ok(serialize(r))


@bp.route("/fee-runs", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    household_id = request.args.get("household_id")
    fee_schedule_snapshot_id = request.args.get("fee_schedule_snapshot_id")
    items = list(db.fee_runs.values())
    if household_id is not None:
        items = [x for x in items if x["household_id"] == household_id]
    if fee_schedule_snapshot_id is not None:
        items = [x for x in items if x["fee_schedule_snapshot_id"] == fee_schedule_snapshot_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


def _select_basis(r, household):
    if r["billing_method_snapshot"] == "ARREARS":
        return household["billable_aum_cents"]
    # ADVANCE: prior FINALIZED run whose period_end == this run's period_start
    priors = [
        x for x in db.fee_runs.values()
        if x["household_id"] == household["id"]
        and x["status"] == "FINALIZED"
        and x["period_end"] == r["period_start"]
    ]
    if priors:
        priors.sort(key=lambda x: (x["created_at"], x["id"]))
        return priors[-1]["basis_aum_cents"]
    return household["billable_aum_cents"]


@bp.route("/fee-runs/<rid>/state", methods=["POST"])
def state(rid):
    user_id, role = authenticate()
    authorize(role, {"BillingAdmin"})
    r = get_or_404(db.fee_runs, rid)
    data = body()
    action = require_enum(data, "action", ACTIONS)
    household = db.households.get(r["household_id"])

    if action == "CALCULATE":
        if r["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "CALCULATE requires DRAFT")
        if household is None or household["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Owning household must be ACTIVE")
        if date.fromisoformat(r["period_end"]) <= date.fromisoformat(r["period_start"]):
            raise err("ERR_INVALID_PERIOD", "period_end must be strictly after period_start")
        schedule = db.fee_schedules.get(r["fee_schedule_snapshot_id"])
        tiers = schedule["tiers"] if schedule else []
        minimum = schedule["minimum_annual_fee_cents"] if schedule else 0
        basis = _select_basis(r, household)
        gross, assessed = calc.compute_fee(
            basis, tiers, minimum, r["period_start"], r["period_end"])
        r["basis_aum_cents"] = basis
        r["gross_fee_cents"] = gross
        r["assessed_fee_cents"] = assessed
        r["status"] = "CALCULATED"
        touch(r)
        # lock the referenced schedule
        if schedule and not schedule["is_locked"]:
            schedule["is_locked"] = True
            touch(schedule)
        return ok(serialize(r))

    if action == "RECALC":
        if r["status"] != "CALCULATED":
            raise err("ERR_INVALID_STATE", "RECALC requires CALCULATED")
        r["basis_aum_cents"] = 0
        r["gross_fee_cents"] = 0
        r["assessed_fee_cents"] = 0
        r["status"] = "DRAFT"
        touch(r)
        return ok(serialize(r))

    if action == "FINALIZE":
        if r["status"] != "CALCULATED":
            raise err("ERR_INVALID_STATE", "FINALIZE requires CALCULATED")
        # segregation of duties (priority 6)
        if user_id == r.get("creator_user_id"):
            raise err("ERR_SEGREGATION_OF_DUTIES", "Finalizer must differ from creator")
        # billing-period overlap (priority 9)
        for other in db.fee_runs.values():
            if (other["id"] != rid and other["household_id"] == r["household_id"]
                    and other["status"] == "FINALIZED"
                    and _ranges_overlap(r["period_start"], r["period_end"],
                                        other["period_start"], other["period_end"])):
                raise err("ERR_BILLING_PERIOD_OVERLAP",
                          "Overlapping FINALIZED fee run for this household")
        r["status"] = "FINALIZED"
        touch(r)
        # side effects: compliance item + household version bump
        from routes.compliance import make_item
        make_item("HOUSEHOLD", r["household_id"], "FEE_DISCLOSURE", due_date=None)
        if household:
            touch(household)
        return ok(serialize(r))

    if action == "VOID":
        if r["status"] not in {"DRAFT", "CALCULATED"}:
            raise err("ERR_INVALID_STATE", "VOID requires DRAFT or CALCULATED")
        r["status"] = "VOIDED"
        touch(r)
        return ok(serialize(r))
