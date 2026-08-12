"""Cross-entity lifecycle services: movement scheduling/promotion, custody
cascades (tank inventory, statement rollup, loss-control suspension), and
monthly statement recompute."""
from clock import CLOCK
from db import STORE
from errors import err
from services import calc
from services.common import touch, lazy_lease


# --- Lease reserved capacity ----------------------------------------------------
def recompute_reserved_capacity(lease):
    """reserved_capacity_bbl = SUM(allocated_bbl) over this lease's ACTIVE
    allocations. Counts as a lease mutation: updated_at refresh + version bump."""
    total = sum(a["allocated_bbl"] for a in STORE.allocations.values()
                if a["lease_id"] == lease["id"] and a["status"] == "ACTIVE")
    lease["reserved_capacity_bbl"] = total
    touch(lease)


# --- Movement scheduling / waitlist promotion -----------------------------------
def promote_to_scheduled(movement, resource):
    """Shared by POST /movements/{id}/schedule and waitlist promotion:
    set resource, compute scheduled-estimate demurrage, move to SCHEDULED."""
    movement["resource_id"] = resource["id"]
    movement["demurrage_estimated_amount"] = calc.demurrage_scheduled_estimate(movement)
    movement["status"] = "SCHEDULED"
    touch(movement)


# --- Monthly statement recompute --------------------------------------------------
def _statement_period_movements(statement):
    """COMPLETED movements of the statement's lease completing in the period."""
    out = []
    for m in STORE.movements.values():
        if m["lease_id"] != statement["lease_id"]:
            continue
        if m["status"] != "COMPLETED" or m["actual_complete_at"] is None:
            continue
        if statement["period_start"] <= m["actual_complete_at"] < statement["period_end_exclusive"]:
            out.append(m)
    return out


def _statement_period_custody(statement):
    """CERTIFIED/DISPUTED custody transfers whose movement completed in period.

    Scoped to the statement's lease (via movement join)."""
    out = []
    for ct in STORE.custody_transfers.values():
        if ct["status"] not in ("CERTIFIED", "DISPUTED"):
            continue
        m = STORE.movements.get(ct["movement_id"])
        if m is None or m["lease_id"] != statement["lease_id"]:
            continue
        if m["actual_complete_at"] is None:
            continue
        if statement["period_start"] <= m["actual_complete_at"] < statement["period_end_exclusive"]:
            out.append(ct)
    return out


def recompute_statement(statement):
    """monthly_statement_aggregation: round-per-line-then-sum discipline."""
    lease = STORE.leases.get(statement["lease_id"])
    custody = _statement_period_custody(statement)
    movements = _statement_period_movements(statement)

    total_throughput = sum(int(ct["certified_volume_bbl"] or 0) for ct in custody)
    total_excess_loss = sum(int(ct["excess_loss_bbl"] or 0) for ct in custody)
    excess_loss_amount = sum(float(ct["excess_loss_charge"] or 0) for ct in custody)
    demurrage = sum(float(m["demurrage_actual_amount"] or 0)
                    for m in movements if m["mode"] in ("VESSEL", "RAIL"))
    dwell = sum(float(m["demurrage_actual_amount"] or 0)
                for m in movements if m["mode"] == "TRUCK")

    statement["total_throughput_bbl"] = int(total_throughput)
    statement["throughput_fee_amount"] = calc.tiered_throughput_fee(
        total_throughput, lease["throughput_fee_per_bbl"])
    shortfall_bbl, shortfall_fee = calc.shortfall_fields(lease, total_throughput)
    statement["shortfall_bbl"] = shortfall_bbl
    statement["shortfall_fee_amount"] = shortfall_fee
    statement["total_excess_loss_bbl"] = int(total_excess_loss)
    statement["excess_loss_amount"] = calc.round2(calc.dec(excess_loss_amount))
    statement["total_demurrage_amount"] = calc.round2(calc.dec(demurrage))
    statement["total_dwell_amount"] = calc.round2(calc.dec(dwell))
    statement["statement_total_amount"] = calc.round2(
        calc.dec(statement["throughput_fee_amount"])
        + calc.dec(statement["shortfall_fee_amount"])
        + calc.dec(statement["excess_loss_amount"])
        + calc.dec(statement["total_demurrage_amount"])
        + calc.dec(statement["total_dwell_amount"]))
    touch(statement)


def open_statement_for(lease_id, when):
    """The OPEN statement of the lease whose period contains `when`, or None."""
    for s in STORE.statements.values():
        if s["lease_id"] != lease_id or s["status"] != "OPEN":
            continue
        if s["period_start"] <= when < s["period_end_exclusive"]:
            return s
    return None


def maybe_loss_control_suspend(statement):
    """After an OPEN-statement recompute: total_excess_loss_bbl > 100
    auto-suspends an ACTIVE lease with suspension_reason LOSS_CONTROL.
    One-directional: never auto-reactivates."""
    if statement["total_excess_loss_bbl"] > calc.LOSS_CONTROL_CAP_BBL:
        lease = STORE.leases.get(statement["lease_id"])
        if lease is not None:
            lazy_lease(lease)
            if lease["status"] == "ACTIVE":
                lease["status"] = "SUSPENDED"
                lease["suspension_reason"] = "LOSS_CONTROL"
                touch(lease)


# --- Custody cascade ----------------------------------------------------------------
def custody_cascade(ct, suspend_check=True):
    """Shared cascade after certify / resolve / void:
    tank inventory recompute + posture, OPEN statement recompute, loss control."""
    movement = STORE.movements.get(ct["movement_id"])
    if movement is None:
        return
    tank = STORE.tanks.get(movement["tank_id"])
    if tank is not None:
        calc.recompute_tank_inventory(tank)
        touch(tank)
    if movement["actual_complete_at"] is not None:
        statement = open_statement_for(movement["lease_id"], movement["actual_complete_at"])
        if statement is not None:
            recompute_statement(statement)
            if suspend_check:
                maybe_loss_control_suspend(statement)


def gauge_pair(movement_id):
    opening = None
    closing = None
    for g in STORE.gauge_tickets.values():
        if g["movement_id"] != movement_id:
            continue
        if g["ticket_type"] == "OPENING":
            opening = g
        elif g["ticket_type"] == "CLOSING":
            closing = g
    return opening, closing


def passed_sample(movement_id):
    for s in STORE.samples.values():
        if s["movement_id"] == movement_id and s["lab_result"] == "PASSED":
            return s
    return None


def custody_for_movement(movement_id):
    for ct in STORE.custody_transfers.values():
        if ct["movement_id"] == movement_id:
            return ct
    return None
