"""Derived postures, counters, indices, the wear ledger and the cascades.

Every value a client never writes is recomputed here from the store, so the two
conserved quantities of PRD 2.9 hold by construction rather than by bookkeeping.
"""

from decimal import Decimal as D

import calc
from db import bump, by_creation, common_fields, db, new_id, now
from timeutil import Instant, hours_between

try:  # pragma: no cover - flask is always present at runtime
    from flask import g
except Exception:  # pragma: no cover
    g = None


# ------------------------------------------------------------------ dirty set
def touch_field(field):
    """Mark a field as mutated: recompute now, bump ``version`` exactly once.

    PRD 2.8: a single request never bumps Field.version more than once, however
    many derived values it touched.
    """
    recompute_field(field)
    dirty = getattr(g, "_dirty_fields", None)
    if dirty is None:
        dirty = {}
        setattr(g, "_dirty_fields", dirty)
    dirty[field["id"]] = field


def flush_field_versions():
    dirty = getattr(g, "_dirty_fields", None) if g is not None else None
    if not dirty:
        return
    for field in dirty.values():
        bump(field)
    dirty.clear()


# ------------------------------------------------------------------ selectors
def field_rows(collection, field_id):
    return [r for r in collection.values() if r["field_id"] == field_id]


def live_impact_assessments(field_id):
    rows = [a for a in db.safety_assessments.values()
            if a["field_id"] == field_id
            and a["assessment_type"] == "IMPACT_ATTENUATION"
            and a["status"] == "RECORDED"]
    rows.sort(key=lambda a: (a["assessed_at_utc"].dt, a["created_at"].dt, a["_seq"]),
              reverse=True)
    return rows


def field_ledger(field_id):
    """The field's ledger entries in replay order: effective_at ASC, created_at ASC."""
    rows = [e for e in db.ledger_entries.values() if e["field_id"] == field_id]
    rows.sort(key=lambda e: (e["effective_at_utc"].dt, e["created_at"].dt, e["_seq"]))
    return rows


def governing_rest_entry(field_id):
    """PRD 3.7: the PLAY_WEAR entry with the greatest rest_window_end_utc."""
    candidates = [e for e in db.ledger_entries.values()
                  if e["field_id"] == field_id and e["entry_type"] == "PLAY_WEAR"
                  and e["rest_window_end_utc"] is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda e: (e["rest_window_end_utc"].dt,
                                   e["effective_at_utc"].dt,
                                   e["created_at"].dt, e["_seq"]))
    return candidates[-1]


def approved_packet(field_id):
    rows = [p for p in db.certification_packets.values()
            if p["field_id"] == field_id and p["status"] == "APPROVED"]
    if not rows:
        return None
    return by_creation(rows)[-1]


# ------------------------------------------------------------------ recompute
DERIVED_KEYS = (
    "age_years", "warranty_status", "play_status", "certification_status",
    "certified_until_utc", "latest_gmax_mean_value", "cumulative_wear_units",
    "usage_hours_ytd", "rest_debt_hours",
    "nitrogen_applied_ytd_lb_per_1000_sq_ft", "condition_index_agronomic",
    "open_mandatory_remediation_count", "open_advisory_remediation_count",
    "open_certification_packet_count", "open_replacement_plan_count",
    "unsafe_cancellation_count",
)


def snapshot(field):
    out = {}
    for key in DERIVED_KEYS:
        value = field.get(key)
        out[key] = value.raw if isinstance(value, Instant) else value
    return out


def recompute_field(field):
    """Recompute every derived value on the field from the store and the clock."""
    current = now()
    fid = field["id"]

    # --- age and warranty (PRD 3.1)
    field["age_years"] = calc.field_age_years(field["installed_on_date"], current)
    field["warranty_status"] = calc.field_warranty_status(
        field["warranty_expires_on"], current)

    # --- remediation / packet / plan / cancellation counters (PRD 2.8)
    orders = field_rows(db.remediation_orders, fid)
    open_states = ("OPEN", "VERIFICATION_SUBMITTED")
    field["open_mandatory_remediation_count"] = sum(
        1 for o in orders if o["severity"] == "MANDATORY" and o["status"] in open_states)
    field["open_advisory_remediation_count"] = sum(
        1 for o in orders if o["severity"] == "ADVISORY" and o["status"] in open_states)
    field["open_certification_packet_count"] = sum(
        1 for p in field_rows(db.certification_packets, fid)
        if p["status"] in ("DRAFT", "SUBMITTED", "RETURNED"))
    field["open_replacement_plan_count"] = sum(
        1 for p in field_rows(db.replacement_plans, fid)
        if p["funding_status"] in ("DRAFT", "SUBMITTED", "DEFERRED", "APPROVED"))

    bookings = field_rows(db.usage_bookings, fid)
    field["unsafe_cancellation_count"] = sum(
        1 for b in bookings if b["status"] == "CANCELLED_UNSAFE")

    # --- year-to-date accumulators (PRD 2.8)
    year = current.dt.year
    hours = calc.ZERO
    for b in bookings:
        if b["status"] in ("PLAYED", "RAINED_OUT") and b["closed_out_at_utc"] is not None:
            if b["closed_out_at_utc"].dt.year == year:
                hours = hours + D(b["actual_duration_hours"])
    field["usage_hours_ytd"] = calc.r2(hours)

    nitrogen = calc.ZERO
    for t in field_rows(db.maintenance_tasks, fid):
        if (t["status"] == "COMPLETED" and t["task_type"] == "FERTILITY"
                and t["nitrogen_lb_per_1000_sq_ft"] is not None
                and t["completed_at_utc"] is not None
                and t["completed_at_utc"].dt.year == year):
            nitrogen = nitrogen + D(t["nitrogen_lb_per_1000_sq_ft"])
    field["nitrogen_applied_ytd_lb_per_1000_sq_ft"] = calc.r2(nitrogen)

    # --- latest impact reading (PRD 3.3: assessed_at DESC then created_at DESC)
    live = live_impact_assessments(fid)
    field["latest_gmax_mean_value"] = live[0]["gmax_mean_value"] if live else None

    # --- the wear ledger (PRD 2.9)
    total = calc.ZERO
    for entry in field_ledger(fid):
        total = total + D(entry["wear_units_delta"])
    field["cumulative_wear_units"] = calc.r2(total)

    # --- rest debt (PRD 3.7)
    field["rest_debt_hours"] = _rest_debt(field)

    # --- condition index, AGRONOMIC variant (PRD 3.7)
    field["condition_index_agronomic"] = calc.condition_index(
        field["cumulative_wear_units"], field["age_years"],
        field["expected_life_years"], field["latest_gmax_mean_value"], "AGRONOMIC")

    # --- certification posture (PRD 2.5)
    approved = approved_packet(fid)
    submitted = any(p["status"] == "SUBMITTED"
                    for p in field_rows(db.certification_packets, fid))
    if field["retired_at"] is not None:
        status = "NOT_CERTIFIED"
    elif approved is not None and approved["certified_until_utc"].dt > current.dt:
        status = "CERTIFIED"
    elif submitted:
        status = "PENDING_REVIEW"
    elif approved is not None:
        status = "EXPIRED"
    else:
        status = "NOT_CERTIFIED"
    field["certification_status"] = status
    field["certified_until_utc"] = (approved["certified_until_utc"]
                                   if status == "CERTIFIED" else None)

    # --- play posture (PRD 2.5), strict precedence, first match wins
    if field["retired_at"] is not None:
        posture = "RETIRED"
    elif field["open_mandatory_remediation_count"] > 0:
        posture = "CLOSED_UNSAFE"
    elif field["admin_closure_active"]:
        posture = "CLOSED_ADMIN"
    elif (field["rest_debt_hours"] > calc.ZERO
          or field["open_advisory_remediation_count"] > 0):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    field["play_status"] = posture
    return field


def _rest_debt(field):
    governing = governing_rest_entry(field["id"])
    if governing is None:
        return calc.r2(calc.ZERO)
    current = now()
    remaining = hours_between(current.dt, governing["rest_window_end_utc"].dt)
    outstanding = calc.r2(max(calc.ZERO, remaining))
    credit = calc.ZERO
    for task in field_rows(db.maintenance_tasks, field["id"]):
        if (task["status"] == "COMPLETED" and task["completed_at_utc"] is not None
                and task["completed_at_utc"].dt >= governing["effective_at_utc"].dt):
            credit = credit + D(task["recovery_credit_hours"])
    return calc.r2(outstanding - min(outstanding, credit))


# ------------------------------------------------------------------ the ledger
def append_ledger(field, entry_type, wear_units_delta,
                  rest_requirement_hours=None, rest_credit_hours=None,
                  rest_window_end_utc=None, booking_id=None,
                  maintenance_task_id=None, note=""):
    """Append an immutable UsageLedgerEntry (PRD 2.4: no updated_at, no version)."""
    stamp = Instant.now()
    delta = calc.r2(wear_units_delta)
    balance = calc.r2(D(field["cumulative_wear_units"]) + delta)
    entry = {
        "id": new_id(),
        "field_id": field["id"],
        "booking_id": booking_id,
        "maintenance_task_id": maintenance_task_id,
        "entry_type": entry_type,
        "wear_units_delta": delta,
        "rest_requirement_hours": calc.r2(rest_requirement_hours or calc.ZERO),
        "rest_credit_hours": calc.r2(rest_credit_hours or calc.ZERO),
        "rest_window_end_utc": rest_window_end_utc,
        "effective_at_utc": now(),
        "running_balance_after": balance,
        "note": note,
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    db.ledger_entries[entry["id"]] = entry
    recompute_field(field)
    return entry


# ------------------------------------------------------------------ cascades
def _cancel_bookings(field, rows, note):
    for booking in rows:
        booking["status"] = "CANCELLED_UNSAFE"
        bump(booking)
        append_ledger(field, "UNSAFE_CANCELLATION", calc.ZERO,
                      rest_requirement_hours=calc.ZERO,
                      booking_id=booking["id"], note=note)
    recompute_field(field)


def cascade_unsafe(field, note):
    """PRD 3.4 hops four and five: cancel forward bookings on an unsafe closure."""
    if field["play_status"] != "CLOSED_UNSAFE":
        return
    current = now()
    rows = [b for b in field_rows(db.usage_bookings, field["id"])
            if b["status"] in ("SCHEDULED", "CONFIRMED")
            and b["window_start_utc"].dt >= current.dt]
    rows.sort(key=lambda b: (b["window_start_utc"].dt, b["created_at"].dt, b["_seq"]))
    _cancel_bookings(field, rows, note)


def cascade_retire(field, retired_at, note):
    """PRD 3.9: retirement cancels every non-terminal booking, with no window filter."""
    field["retired_at"] = retired_at
    rows = [b for b in field_rows(db.usage_bookings, field["id"])
            if b["status"] in ("SCHEDULED", "CONFIRMED")]
    rows.sort(key=lambda b: (b["window_start_utc"].dt, b["created_at"].dt, b["_seq"]))
    _cancel_bookings(field, rows, note)


# ------------------------------------------------------------------ budgets
def recompute_budget(budget):
    """PRD 2.9: committed capital is the sum over this budget's APPROVED plans."""
    committed = 0
    for plan in db.replacement_plans.values():
        if (plan["capital_budget_id"] == budget["id"]
                and plan["funding_status"] == "APPROVED"):
            committed += plan["plan_funding_amount_cents"]
    budget["committed_amount_cents"] = committed
    budget["available_amount_cents"] = (
        budget["total_authorized_amount_cents"] - committed)
    budget["status"] = ("LOCKED"
                       if committed >= budget["lock_threshold_amount_cents"]
                       else "OPEN")
    return budget


# ---------------------------------------------- certification completeness
def _in_window(instant, window_start, window_end):
    return window_start.dt <= instant.dt <= window_end.dt


def completeness_score(field, governing, submitted_at):
    """PRD 3.8: six weighted ratios, each rounded to 2dp BEFORE being summed."""
    window_start = submitted_at.minus_days(calc.CERTIFICATION_WINDOW_DAYS)
    fid = field["id"]

    safety_ratio = D("1.00") if (
        governing["status"] == "RECORDED"
        and governing["result"] in ("PASS", "ADVISORY")
        and _in_window(governing["assessed_at_utc"], window_start, submitted_at)
    ) else calc.ZERO

    planned = [t for t in field_rows(db.maintenance_tasks, fid)
               if t["planned_for_certification_window"]
               and t["status"] != "CANCELLED"
               and _in_window(t["scheduled_start_utc"], window_start, submitted_at)]
    if not planned:
        agronomic_ratio = D("1.00")
    else:
        done = sum(1 for t in planned if t["status"] == "COMPLETED")
        agronomic_ratio = D(done) / D(len(planned))

    def inspection_ratio(kind):
        for a in field_rows(db.safety_assessments, fid):
            if (a["assessment_type"] == kind and a["status"] == "RECORDED"
                    and a["result"] == "PASS"
                    and _in_window(a["assessed_at_utc"], window_start, submitted_at)):
                return D("1.00")
        return calc.ZERO

    striping_ratio = inspection_ratio("STRIPING_LAYOUT")
    goal_ratio = inspection_ratio("GOAL_ANCHORING")

    if field["surface_type"] == "SYNTHETIC_TURF":
        measured = D(field["infill_depth_mm"] or 0)
        spec_ratio = min(D("1.00"), measured / calc.REQUIRED_INFILL_DEPTH_MM)
    else:
        applied = D(field["nitrogen_applied_ytd_lb_per_1000_sq_ft"])
        spec_ratio = min(D("1.00"),
                         applied / calc.REQUIRED_NITROGEN_LB_PER_1000_SQ_FT)

    opened = [o for o in field_rows(db.remediation_orders, fid)
              if _in_window(o["opened_at_utc"], window_start, submitted_at)]
    if not opened:
        remediation_ratio = D("1.00")
    else:
        closed = sum(1 for o in opened
                     if o["status"] in ("CLOSED_VERIFIED", "CANCELLED"))
        remediation_ratio = D(closed) / D(len(opened))

    weights = calc.COMPONENT_WEIGHTS
    total = (calc.r2(weights["SAFETY_TEST"] * safety_ratio)
             + calc.r2(weights["AGRONOMIC_PROGRAM"] * agronomic_ratio)
             + calc.r2(weights["STRIPING_LAYOUT"] * striping_ratio)
             + calc.r2(weights["GOAL_ANCHORING"] * goal_ratio)
             + calc.r2(weights["SURFACE_SPEC_COMPLIANCE"] * spec_ratio)
             + calc.r2(weights["REMEDIATION_CLOSURE"] * remediation_ratio))
    return calc.r2(total)


# ---------------------------------------------- the remediation cascade head
def open_remediation_order(field, assessment):
    """PRD 3.4 hops two, three, four and five."""
    if assessment["result"] == "PASS":
        return None
    severity = "MANDATORY" if assessment["result"] == "FAIL" else "ADVISORY"
    order = {
        "id": new_id(),
        "field_id": field["id"],
        "source_assessment_id": assessment["id"],
        "verification_assessment_id": None,
        "submitted_by_staff_member_id": None,
        "severity": severity,
        "status": "OPEN",
        "opened_at_utc": now(),
        "remediation_notes": None,
        "rejection_count": 0,
        "closed_at_utc": None,
    }
    order.update(common_fields())
    db.remediation_orders[order["id"]] = order
    recompute_field(field)
    if severity == "MANDATORY":
        cascade_unsafe(field, "UNSAFE_CLOSURE_CASCADE_FROM_ASSESSMENT")
    return order
