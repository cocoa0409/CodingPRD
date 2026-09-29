"""Domain services: lookups, derived-field reconciliation and cascades.

Every derived field is recomputed from its inputs (PRD §2.11) and every
recomputation that actually changes a stored value is a mutation, so the row's
updated_at and version move with it (PRD §2.5).
"""

from datetime import timedelta

import calc
from db import db, now, ordered, touch
from errors import fail

OPEN_RECALL_STATUSES = ("INITIATED", "NOTIFYING", "MONITORING")
LIVE_LOT_STATUSES = ("AVAILABLE", "WATCH")
COMMITTED_ORDER_STATUSES = ("APPROVED", "HELD", "SCHEDULED")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def _find(table, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id, "%s not found" % row_id)
    row = table.get(row_id)
    if row is None:
        fail(error_id, "No such row: %s" % row_id)
    return row


def service_area(row_id):
    return _find(db.service_areas, row_id, "ERR_SERVICE_AREA_NOT_FOUND")


def agency(row_id):
    return _find(db.agencies, row_id, "ERR_AGENCY_NOT_FOUND")


def commodity(row_id):
    return _find(db.commodities, row_id, "ERR_COMMODITY_NOT_FOUND")


def warehouse(row_id):
    return _find(db.warehouses, row_id, "ERR_WAREHOUSE_NOT_FOUND")


def lot(row_id):
    return _find(db.lots, row_id, "ERR_INVENTORY_LOT_NOT_FOUND")


def cycle(row_id):
    return _find(db.cycles, row_id, "ERR_CYCLE_NOT_FOUND")


def allocation(row_id):
    return _find(db.allocations, row_id, "ERR_ALLOCATION_NOT_FOUND")


def order(row_id):
    return _find(db.orders, row_id, "ERR_ORDER_NOT_FOUND")


def order_line(row_id):
    return _find(db.order_lines, row_id, "ERR_ORDER_LINE_NOT_FOUND")


def appointment(row_id):
    return _find(db.appointments, row_id, "ERR_APPOINTMENT_NOT_FOUND")


def transfer(row_id):
    return _find(db.transfers, row_id, "ERR_TRANSFER_NOT_FOUND")


def recall(row_id):
    return _find(db.recalls, row_id, "ERR_RECALL_NOT_FOUND")


def recall_action(row_id):
    return _find(db.recall_actions, row_id, "ERR_RECALL_ACTION_NOT_FOUND")


def distribution(row_id):
    return _find(db.distributions, row_id, "ERR_DISTRIBUTION_NOT_FOUND")


# ---------------------------------------------------------------------------
# eligibility posture (PRD §3.2)
# ---------------------------------------------------------------------------
def posture_of(row):
    if row["agreement_status"] == "ACTIVE" and row["training_status"] == "CURRENT":
        return "ELIGIBLE"
    if row["agreement_status"] == "ACTIVE" and row["training_status"] == "LAPSED":
        return "PROBATION"
    return "INELIGIBLE"


def recompute_posture(row):
    """Write the derived posture, then the owning area's eligible count."""
    row["eligibility_posture"] = posture_of(row)
    recompute_area_count(row["service_area_id"])


def recompute_area_count(service_area_id):
    area = db.service_areas.get(service_area_id)
    if area is None:
        return
    count = 0
    for row in db.agencies.values():
        if row["service_area_id"] == service_area_id and row["eligibility_posture"] == "ELIGIBLE":
            count += 1
    if area["eligible_agency_count"] != count:
        area["eligible_agency_count"] = count
        touch(area)


def require_posture(row, allowed):
    if row["eligibility_posture"] not in allowed:
        fail("ERR_AGENCY_INELIGIBLE", "Agency posture is %s" % row["eligibility_posture"])


# ---------------------------------------------------------------------------
# entitlement bookkeeping (PRD §2.9)
# ---------------------------------------------------------------------------
def allocation_for(cycle_id, agency_id):
    for row in ordered(db.allocations.values()):
        if row["cycle_id"] == cycle_id and row["agency_id"] == agency_id:
            return row
    return None


def refresh_allocation(row):
    """Recompute cases_remaining and the draw status, then the cycle posture."""
    row["cases_remaining"] = (
        row["allocated_cases"] - row["cases_committed"] - row["cases_delivered"]
    )
    if row["status"] != "RECONCILED":
        if row["cases_committed"] == 0 and row["cases_delivered"] == 0:
            row["status"] = "ENTITLED"
        elif row["cases_remaining"] == 0 and row["cases_delivered"] > 0:
            row["status"] = "FULLY_DRAWN"
        else:
            row["status"] = "PARTIALLY_DRAWN"
    touch(row)
    recompute_draw_posture(row["cycle_id"])


def recompute_draw_posture(cycle_id):
    parent = db.cycles.get(cycle_id)
    if parent is None:
        return
    rows = [r for r in db.allocations.values() if r["cycle_id"] == cycle_id]
    if not rows or all(r["status"] == "ENTITLED" for r in rows):
        posture = "NOT_STARTED"
    elif all(r["status"] == "FULLY_DRAWN" for r in rows):
        posture = "FULLY_DRAWN"
    else:
        posture = "PARTIAL"
    if parent["draw_posture"] != posture:
        parent["draw_posture"] = posture
        touch(parent)


# ---------------------------------------------------------------------------
# order helpers
# ---------------------------------------------------------------------------
def lines_of(order_id):
    return ordered([r for r in db.order_lines.values() if r["order_id"] == order_id])


def refresh_order_request_totals(row):
    lines = lines_of(row["id"])
    row["line_count"] = len(lines)
    row["total_cases_requested"] = sum(line["cases_requested"] for line in lines)


def live_appointment(order_id):
    for row in ordered(db.appointments.values()):
        if row["order_id"] == order_id and row["status"] in ("SCHEDULED", "BLOCKED", "DELIVERED"):
            return row
    return None


def order_appointment(order_id, statuses):
    for row in ordered(db.appointments.values()):
        if row["order_id"] == order_id and row["status"] in statuses:
            return row
    return None


def reserved_lot_ids(order_id):
    ids = []
    for line in lines_of(order_id):
        for entry in line["lot_assignments"]:
            if entry["lot_id"] not in ids:
                ids.append(entry["lot_id"])
    return ids


def release_order_commitments(row):
    """The compensating half of the approve/cancel pair (PRD §2.9)."""
    for line in lines_of(row["id"]):
        for entry in line["lot_assignments"]:
            target = db.lots.get(entry["lot_id"])
            if target is None:
                continue
            if target["status"] == "DISPOSED":
                # a disposed lot already had both counters written to zero
                continue
            target["cases_committed"] = target["cases_committed"] - entry["cases"]
            touch(target)
    entitlement = allocation_for(row["cycle_id"], row["agency_id"])
    if entitlement is not None and row["total_cases_approved"]:
        entitlement["cases_committed"] = (
            entitlement["cases_committed"] - row["total_cases_approved"]
        )
        refresh_allocation(entitlement)


def cancel_order(row, reason, cancel_appointment=True):
    """Cancel an order from any non-terminal state, compensating commitments."""
    had_commitments = row["status"] in COMMITTED_ORDER_STATUSES
    if cancel_appointment:
        appointment_row = order_appointment(row["id"], ("SCHEDULED", "BLOCKED"))
        if appointment_row is not None:
            appointment_row["status"] = "CANCELLED"
            appointment_row["cancel_reason"] = reason
            touch(appointment_row)
    if had_commitments:
        release_order_commitments(row)
    row["status"] = "CANCELLED"
    row["cancel_reason"] = reason
    touch(row)


# ---------------------------------------------------------------------------
# FEFO reservation (PRD §3.6)
# ---------------------------------------------------------------------------
def fefo_plan(order_row, approvals):
    """Plan the reservations for every line; return None when coverage fails.

    `approvals` maps order_line id -> cases_approved. The plan is a list of
    (line, [{lot_id, cases}, ...]) pairs in line created_at order; nothing is
    written until the caller commits it.
    """
    taken = {}
    plan = []
    for line in lines_of(order_row["id"]):
        need = approvals[line["id"]]
        candidates = [
            row
            for row in db.lots.values()
            if row["warehouse_id"] == order_row["warehouse_id"]
            and row["commodity_id"] == line["commodity_id"]
            and row["status"] in LIVE_LOT_STATUSES
            and (row["cases_on_hand"] - row["cases_committed"] - taken.get(row["id"], 0)) > 0
        ]
        candidates.sort(key=lambda row: (row["best_by_date"], row["created_at"], row["_seq"]))
        assignments = []
        for candidate in candidates:
            if need <= 0:
                break
            available = (
                candidate["cases_on_hand"]
                - candidate["cases_committed"]
                - taken.get(candidate["id"], 0)
            )
            grab = available if available < need else need
            if grab <= 0:
                continue
            assignments.append({"lot_id": candidate["id"], "cases": grab})
            taken[candidate["id"]] = taken.get(candidate["id"], 0) + grab
            need -= grab
        if need > 0:
            return None
        plan.append((line, assignments))
    return plan


# ---------------------------------------------------------------------------
# recall exposure and cascades (PRD §3.8)
# ---------------------------------------------------------------------------
def held_lot_ids(recall_row):
    return [
        row["id"]
        for row in db.lots.values()
        if row["hold_recall_id"] == recall_row["id"]
    ]


def exposure_by_agency(lot_ids):
    """Cases that reached each agency from the named lots."""
    totals = {}
    for order_row in db.orders.values():
        if order_row["status"] != "DELIVERED":
            continue
        for line in lines_of(order_row["id"]):
            for entry in line["lot_assignments"]:
                if entry["lot_id"] in lot_ids:
                    key = order_row["agency_id"]
                    totals[key] = totals.get(key, 0) + entry["cases"]
    for row in db.transfers.values():
        if row["status"] == "ACCEPTED" and row["from_lot_id"] in lot_ids:
            key = row["to_agency_id"]
            totals[key] = totals.get(key, 0) + row["cases"]
    return totals


def open_recall_for_lot(lot_row):
    for row in ordered(db.recalls.values()):
        if row["status"] not in OPEN_RECALL_STATUSES:
            continue
        if row["source_lot_id"] == lot_row["id"]:
            return row
        if lot_row["hold_recall_id"] == row["id"]:
            return row
        if row["hold_scope"] == "COMMODITY_WIDE":
            source = db.lots.get(row["source_lot_id"])
            if source is not None and source["commodity_id"] == lot_row["commodity_id"]:
                return row
    return None


def lot_under_open_recall(lot_row):
    return open_recall_for_lot(lot_row) is not None


def orders_touching_lot(lot_id, statuses):
    matches = []
    for order_row in ordered(db.orders.values()):
        if order_row["status"] not in statuses:
            continue
        if lot_id in reserved_lot_ids(order_row["id"]):
            matches.append(order_row)
    return matches


def block_downstream(lot_id):
    """Cascade links 2 and 3: appointment BLOCKED, then order HELD."""
    for order_row in orders_touching_lot(lot_id, ("APPROVED", "SCHEDULED")):
        appointment_row = order_appointment(order_row["id"], ("SCHEDULED",))
        if appointment_row is not None:
            appointment_row["status"] = "BLOCKED"
            touch(appointment_row)
        order_row["status"] = "HELD"
        touch(order_row)


def release_lot(lot_row):
    """HOLD -> AVAILABLE with the release cascade."""
    lot_row["status"] = "AVAILABLE"
    lot_row["hold_recall_id"] = None
    touch(lot_row)
    for order_row in orders_touching_lot(lot_row["id"], ("HELD",)):
        if any(
            db.lots[lot_id]["status"] not in LIVE_LOT_STATUSES
            for lot_id in reserved_lot_ids(order_row["id"])
            if lot_id in db.lots
        ):
            continue
        appointment_row = order_appointment(order_row["id"], ("BLOCKED",))
        if appointment_row is not None:
            appointment_row["status"] = "SCHEDULED"
            touch(appointment_row)
            order_row["status"] = "SCHEDULED"
        else:
            order_row["status"] = "APPROVED"
        touch(order_row)


def dispose_lot(lot_row):
    """HOLD -> DISPOSED with the disposal cascade."""
    for order_row in orders_touching_lot(lot_row["id"], ("HELD", "APPROVED")):
        appointment_row = order_appointment(order_row["id"], ("SCHEDULED", "BLOCKED"))
        if appointment_row is not None:
            appointment_row["status"] = "CANCELLED"
            appointment_row["cancel_reason"] = "LOT_DISPOSED"
            touch(appointment_row)
        release_order_commitments(order_row)
        order_row["status"] = "CANCELLED"
        order_row["cancel_reason"] = "LOT_DISPOSED"
        touch(order_row)
    for appointment_row in ordered(db.appointments.values()):
        if appointment_row["status"] not in ("SCHEDULED", "BLOCKED"):
            continue
        if lot_row["id"] in reserved_lot_ids(appointment_row["order_id"]):
            appointment_row["status"] = "CANCELLED"
            appointment_row["cancel_reason"] = "LOT_DISPOSED"
            touch(appointment_row)
    lot_row["status"] = "DISPOSED"
    lot_row["cases_on_hand"] = 0
    lot_row["cases_committed"] = 0
    lot_row["hold_recall_id"] = None
    touch(lot_row)


def deplete_if_empty(lot_row):
    if lot_row["cases_on_hand"] == 0 and lot_row["status"] in LIVE_LOT_STATUSES:
        lot_row["status"] = "DEPLETED"
        lot_row["monitor_flag"] = "NONE"


# ---------------------------------------------------------------------------
# distribution rollup (PRD §3.9)
# ---------------------------------------------------------------------------
def recompute_rollup(cycle_id, agency_id):
    entitlement = allocation_for(cycle_id, agency_id)
    if entitlement is None:
        return None
    rows = [
        row
        for row in db.distributions.values()
        if row["cycle_id"] == cycle_id
        and row["agency_id"] == agency_id
        and row["status"] == "RECORDED"
    ]
    count = len(rows)
    entitlement["distribution_record_count"] = count
    entitlement["distributed_pounds"] = calc.rhu(
        sum(row["pounds_distributed"] for row in rows) if rows else 0, 2
    )
    if count == 0:
        entitlement["record_compliance_pct"] = calc.ZERO_4
    else:
        signed = sum(1 for row in rows if row["self_declaration_signed"])
        entitlement["record_compliance_pct"] = calc.rhu(
            calc.dec(signed) / calc.dec(count), 4
        )
    touch(entitlement)
    return entitlement


# ---------------------------------------------------------------------------
# appointment geometry (PRD §3.7)
# ---------------------------------------------------------------------------
def minute(instant):
    return instant.replace(second=0, microsecond=0)


BUFFER = timedelta(minutes=calc.DOCK_TURNAROUND_MINUTES)


def dock_conflict(warehouse_id, dock_number, start, end, order_id):
    start = minute(start)
    end = minute(end)
    for row in ordered(db.appointments.values()):
        if row["order_id"] == order_id:
            continue
        if row["warehouse_id"] != warehouse_id or row["dock_number"] != dock_number:
            continue
        if row["status"] not in ("SCHEDULED", "BLOCKED", "DELIVERED"):
            continue
        peer_start = minute(row["window_start"])
        peer_end = minute(row["window_end"])
        if start < peer_end + BUFFER and peer_start < end + BUFFER:
            return True
    return False


def staging_peers(warehouse_id, start, end, order_id):
    start = minute(start)
    end = minute(end)
    peers = []
    for row in ordered(db.appointments.values()):
        if row["order_id"] == order_id:
            continue
        if row["warehouse_id"] != warehouse_id:
            continue
        if row["status"] not in ("SCHEDULED", "BLOCKED"):
            continue
        if minute(row["window_start"]) < end and start < minute(row["window_end"]):
            peers.append(row)
    return peers


def agency_peers(agency_id, start, end, order_id):
    start = minute(start)
    end = minute(end)
    peers = []
    for row in ordered(db.appointments.values()):
        if row["order_id"] == order_id:
            continue
        if row["agency_id"] != agency_id:
            continue
        if row["status"] not in ("SCHEDULED", "BLOCKED"):
            continue
        if minute(row["window_start"]) <= end and start <= minute(row["window_end"]):
            peers.append(row)
    return peers


# ---------------------------------------------------------------------------
# monitor run scoring (PRD §3.3)
# ---------------------------------------------------------------------------
def score_lot(lot_row):
    stamp = now()
    house = db.warehouses.get(lot_row["warehouse_id"])
    item = db.commodities.get(lot_row["commodity_id"])
    if lot_row["posted_at"] is not None:
        days_on_hand = int((stamp - lot_row["posted_at"]).total_seconds() // 86400)
    else:
        days_on_hand = 0
    shelf_span = (lot_row["best_by_date"] - lot_row["pack_date"]).days
    days_to_best_by = (lot_row["best_by_date"] - stamp.date()).days
    index = calc.monitor_score(
        days_on_hand,
        lot_row["cases_received"],
        lot_row["cases_shipped_to_date"],
        shelf_span,
        days_to_best_by,
        house["monitor_policy"] if house else "TURNOVER_BASED",
    )
    ceiling = item["excess_case_ceiling"] if item else 0
    flag = calc.monitor_flag(lot_row["cases_on_hand"], ceiling, index)
    lot_row["slow_moving_index"] = index
    lot_row["monitor_flag"] = flag
    lot_row["last_monitored_at"] = stamp
    if flag == "NONE":
        if lot_row["status"] == "WATCH":
            lot_row["status"] = "AVAILABLE"
    elif lot_row["status"] == "AVAILABLE":
        lot_row["status"] = "WATCH"
    touch(lot_row)
    return lot_row
