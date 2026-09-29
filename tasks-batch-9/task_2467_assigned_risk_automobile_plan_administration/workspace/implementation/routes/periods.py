"""Plan periods and the assignment cycles that apportion inside them."""

from flask import Blueprint, request

import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, days, new_row, touch

bp = Blueprint("periods", __name__)

READ_ROLES = ("PlanAdministrator", "ComplianceExaminer", "ServicingCarrier")


# -------------------------------------------------------------- plan periods
@bp.post("/plan/plan-periods")
def create_plan_period():
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    period_code = guards.req_str(data, "period_code", min_len=1, max_len=64)
    window_start = guards.req_dt(data, "window_start")
    window_end = guards.req_dt(data, "window_end")
    underserved = guards.opt_territories(data, "underserved_territories", default=[])

    if window_end < window_start:
        guards.invalid("window_end must not precede window_start.")

    # Closed windows: any intersection at all is refused.
    for existing in db.plan_periods.values():
        if window_start <= existing["window_end"] and existing["window_start"] <= window_end:
            fail("ERR_PERIOD_WINDOW_CONFLICT")
    for existing in db.plan_periods.values():
        if existing["period_code"] == period_code:
            fail("ERR_DUPLICATE_IDENTIFIER", "period_code already exists.")

    row = new_row()
    row.update(
        {
            "period_code": period_code,
            "window_start": window_start,
            "window_end": window_end,
            "underserved_territories": underserved,
            "status": "OPEN",
            "_frozen_units": None,
            "_frozen_car_years": None,
        }
    )
    db.plan_periods[row["id"]] = row
    return created(domain.plan_period_out(row))


@bp.get("/plan/plan-periods/<plan_period_id>")
def read_plan_period(plan_period_id):
    guards.authenticate(READ_ROLES)
    period = guards.need_plan_period(plan_period_id)
    return ok(domain.plan_period_out(period))


@bp.post("/plan/plan-periods/<plan_period_id>/closure")
def close_plan_period(plan_period_id):
    guards.authenticate(("PlanAdministrator",))
    guards.body()
    period = guards.need_plan_period(plan_period_id)

    if period["status"] != "OPEN":
        fail("ERR_INVALID_PERIOD_STATE")
    if db.clock < period["window_end"]:
        fail("ERR_WINDOW_NOT_REACHED")
    for cycle in db.assignment_cycles.values():
        if cycle["plan_period_id"] == period["id"] and cycle["status"] == "SCHEDULED":
            fail("ERR_CYCLE_STILL_SCHEDULED")

    # Freeze the two period totals at the closure instant.
    frozen_units = domain.period_total_assignable_units(period)
    frozen_car_years = domain.period_total_car_years(period)
    period["status"] = "RECONCILING"
    period["_frozen_units"] = frozen_units
    period["_frozen_car_years"] = frozen_car_years
    touch(period)

    # Turn the page for every carrier still in the plan.
    for carrier in db.carriers.values():
        if carrier["status"] != "ACTIVE":
            continue
        carrier["breach_count_current_period"] = 0
        carrier["non_renewal_count_current_period"] = 0
        domain.adjust_score(carrier, +10)

    return ok(domain.plan_period_out(period))


# ---------------------------------------------------------- assignment cycles
@bp.post("/plan/assignment-cycles")
def create_cycle():
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    plan_period_id = guards.req_str(data, "plan_period_id")
    window_start = guards.req_dt(data, "window_start")
    window_end = guards.req_dt(data, "window_end")

    if window_end < window_start:
        guards.invalid("window_end must not precede window_start.")

    period = guards.need_plan_period(plan_period_id)

    if window_start < period["window_start"] or window_end > period["window_end"]:
        fail("ERR_CYCLE_WINDOW_OUTSIDE_PERIOD")

    # Cycle windows need a clear settlement day between them.
    for sibling in db.assignment_cycles.values():
        if sibling["plan_period_id"] != period["id"]:
            continue
        separated = (
            window_start >= sibling["window_end"] + days(2)
            or window_end + days(2) <= sibling["window_start"]
        )
        if not separated:
            fail("ERR_CYCLE_WINDOW_CONFLICT")

    row = new_row()
    row.update(
        {
            "plan_period_id": period["id"],
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
            "assigned_count": 0,
            "deferred_count": 0,
            "run_at": None,
        }
    )
    db.assignment_cycles[row["id"]] = row
    return created(domain.cycle_out(row))


@bp.get("/plan/plan-periods/<plan_period_id>/assignment-cycles")
def list_cycles(plan_period_id):
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    period = guards.need_plan_period(plan_period_id)
    status = request.args.get("status")

    rows = [
        c for c in db.assignment_cycles.values() if c["plan_period_id"] == period["id"]
    ]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = domain.sort_default(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.cycle_out(r) for r in page], limit, offset, total)


@bp.get("/plan/assignment-cycles/<cycle_id>")
def read_cycle(cycle_id):
    guards.authenticate(READ_ROLES)
    cycle = guards.need_cycle(cycle_id)
    return ok(domain.cycle_out(cycle))


@bp.post("/plan/assignment-cycles/<cycle_id>/run")
def run_cycle(cycle_id):
    guards.authenticate(("PlanAdministrator",))
    guards.body()
    cycle = guards.need_cycle(cycle_id)

    if cycle["status"] != "SCHEDULED":
        fail("ERR_INVALID_CYCLE_STATE")
    period = db.plan_periods[cycle["plan_period_id"]]
    if period["status"] != "OPEN":
        fail("ERR_INVALID_PERIOD_STATE")
    if db.clock < cycle["window_start"]:
        fail("ERR_WINDOW_NOT_REACHED")

    queue = []
    for application in db.applications.values():
        if application["status"] not in ("CERTIFIED_AWAITING_ASSIGNMENT", "DEFERRED_NO_CARRIER"):
            continue
        certified_at = application["certified_at"]
        if certified_at is None:
            continue
        if cycle["window_start"] <= certified_at <= cycle["window_end"]:
            queue.append(application)
    queue.sort(key=lambda a: (a["certified_at"], a["intake_sequence"]))

    assigned_count = 0
    deferred_count = 0
    batch_sequence = 0
    for application in queue:
        vehicle = db.vehicles[application["vehicle_id"]]
        # The ranking is recomputed for every application, after the previous
        # placement has already been written.
        carrier, deficit = domain.select_carrier(vehicle["garaging_territory_code"])
        if carrier is None:
            application["status"] = "DEFERRED_NO_CARRIER"
            touch(application)
            deferred_count += 1
            continue
        batch_sequence += 1
        domain.create_assignment(
            application,
            carrier,
            deficit,
            batch_sequence,
            "INITIAL",
            assignment_cycle_id=cycle["id"],
        )
        application["status"] = "ASSIGNED"
        touch(application)
        assigned_count += 1

    cycle["status"] = "COMPLETED"
    cycle["assigned_count"] = assigned_count
    cycle["deferred_count"] = deferred_count
    cycle["run_at"] = db.clock
    touch(cycle)
    return ok(domain.cycle_out(cycle))
