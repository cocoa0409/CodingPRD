"""Business logic: calculations, state machines, cascades (PRD §3).

Every rule traces to a verbatim PRD sentence. Rounding is round-half-up via
Decimal; money is integer cents; flight time is integer tenths of an hour.
"""
from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_CONTRACT_NOT_ACTIVE,
    ERR_AIRCRAFT_NOT_CARDED, ERR_CREW_NOT_CARDED, ERR_DISPATCH_ALREADY_FILLED,
    ERR_ASSIGNMENT_OVERLAP, ERR_AVAILABILITY_OVERLAP, ERR_INVOICE_PERIOD_OVERLAP,
    ERR_CARDING_EXPIRED, ERR_CREW_ON_FATIGUE_HOLD, ERR_FLIGHT_HOUR_LIMIT_EXCEEDED,
    ERR_CREW_DAY_LIMIT_EXCEEDED, ERR_DUTY_REST_VIOLATION,
    ERR_ACCEPTANCE_WINDOW_EXPIRED, ERR_CONFIRM_WINDOW_EXPIRED,
    ERR_SERVICE_DATE_OUTSIDE_SEASON, ERR_BILLING_PERIOD_NOT_CLOSED,
    ERR_SEASON_FLIGHT_CAP_EXCEEDED, ERR_AIRCRAFT_NOT_ON_CONTRACT,
    ERR_PILOT_NOT_ON_CONTRACT, ERR_MODEL_MISMATCH, ERR_MODEL_NOT_QUALIFIED,
    ERR_TANK_CAPACITY_EXCEEDED,
)
from helpers import fmt_dt, fmt_date, str_to_date

DEFAULT_MIN_DAILY_MINUTES = 570
COMPLIANCE_THRESHOLD_NUM = 98   # compared as exact rational: compliant*100 < expected*98
PENALTY_RATE = Decimal("0.05")
DAILY_FLIGHT_LIMIT_TENTHS = 80
CREW_DAY_LIMIT_MINUTES = 840
REST_BUFFER_MINUTES = 60
MATCH_TOLERANCE_TENTHS = 1
RELOAD_SLA_MINUTES = Decimal("30.0")

FILLED_STATUSES = {"ASSIGNED", "EN_ROUTE", "ON_INCIDENT"}
SEASON_BILLED_STATUSES = {"SUBMITTED", "DISPUTED", "RECONCILED", "PAID"}
OPEN_ORDER_STATUSES = {"PLACED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED"}

CONTRACT_TERMINAL = {"CLOSED"}
INCIDENT_TERMINAL = {"CLOSED"}
ORDER_TERMINAL = {"DECLINED", "CANCELLED", "CLOSED"}
AIRCRAFT_TERMINAL = {"DECARDED"}
INVOICE_TERMINAL = {"PAID", "VOID"}
ASSIGNMENT_TERMINAL = {"DEMOBILIZED"}
LOAD_TERMINAL = {"DROPPED"}
PERIOD_TERMINAL = {"EXCUSED", "UNAVAILABLE"}


def touch(entity):
    """PRD §2.4: every mutation refreshes updated_at and increments version by 1."""
    entity["updated_at"] = db.iso_now_ms()
    entity["version"] = entity.get("version", 0) + 1


# ---------------------------------------------------------------------------
# availability_charge (PRD §3.3)
# ---------------------------------------------------------------------------
def compute_availability_charge(period, contract):
    status = period["status"]
    if status in ("EXCUSED", "UNAVAILABLE"):
        return 0
    if contract["contract_type"] == "CALL_WHEN_NEEDED":
        return contract["daily_availability_rate_cents"] if status == "CONFIRMED" else 0
    # EXCLUSIVE_USE, CONFIRMED
    if period["available_minutes"] >= contract["min_daily_available_minutes"]:
        return contract["daily_availability_rate_cents"]
    rate = Decimal(contract["daily_availability_rate_cents"])
    mins = Decimal(period["available_minutes"])
    req = Decimal(contract["min_daily_available_minutes"])
    return int((rate * mins / req).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# crew_duty_projection (PRD §3.5 / calculation table)
# ---------------------------------------------------------------------------
def planned_tenths(assignment):
    start = assignment["planned_start"]
    end = assignment["planned_end"]
    hours = Decimal(str((end - start).total_seconds())) / Decimal(3600)
    return int((hours * 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_duty_day(crew_member_id, duty_date_str):
    for dd in db.crew_duty_days.values():
        if dd["crew_member_id"] == crew_member_id and dd["duty_date"] == duty_date_str:
            return dd
    return None


def create_duty_day(crew_member_id, duty_date_str, duty_start):
    dd = {
        "id": db.new_id(),
        "created_at": db.iso_now_ms(),
        "updated_at": db.iso_now_ms(),
        "version": 1,
        "crew_member_id": crew_member_id,
        "duty_date": duty_date_str,
        "duty_start": duty_start,
        "flown_tenths": 0,
        "projected_tenths": 0,
    }
    db.stamp_new(dd)
    db.crew_duty_days[dd["id"]] = dd
    return dd


def recompute_duty_day(dd):
    """Recompute flown_tenths (chronological) and projected_tenths (forward-looking)."""
    crew_id = dd["crew_member_id"]
    duty_date = dd["duty_date"]
    flown = sum(
        fl["flight_hours_tenths"]
        for fl in db.flight_logs.values()
        if fl["pilot_id"] == crew_id and fl["logged_date"] == duty_date
    )
    projected = flown
    for a in db.assignments.values():
        if (
            a["pilot_id"] == crew_id
            and a["status"] == "ASSIGNED"
            and a["planned_start"].date().isoformat() == duty_date
        ):
            projected += planned_tenths(a)
    dd["flown_tenths"] = flown
    dd["projected_tenths"] = projected


# ---------------------------------------------------------------------------
# filled_count_invariant (PRD §3.4)
# ---------------------------------------------------------------------------
def recompute_order_fill(order):
    """Recompute filled_count and auto-transition the fill band. Returns order."""
    count = sum(
        1
        for a in db.assignments.values()
        if a["dispatch_order_id"] == order["id"] and a["status"] in FILLED_STATUSES
    )
    order["filled_count"] = count
    qty = order["aircraft_quantity"]
    if order["status"] in ("ACCEPTED", "PARTIALLY_FILLED", "FILLED"):
        if count == 0:
            new_status = "ACCEPTED"
        elif count < qty:
            new_status = "PARTIALLY_FILLED"
        else:
            new_status = "FILLED"
        if new_status != order["status"]:
            order["status"] = new_status
    return order


def maybe_close_order(order):
    """Demobilize bubble-up: all assignments DEMOBILIZED (>= 1) -> CLOSED."""
    if order["status"] not in ("ACCEPTED", "PARTIALLY_FILLED", "FILLED"):
        return
    order_assignments = [
        a for a in db.assignments.values() if a["dispatch_order_id"] == order["id"]
    ]
    if len(order_assignments) >= 1 and all(
        a["status"] == "DEMOBILIZED" for a in order_assignments
    ):
        order["status"] = "CLOSED"
        order["filled_count"] = sum(
            1 for a in order_assignments if a["status"] in FILLED_STATUSES
        )
        touch(order)


# ---------------------------------------------------------------------------
# season_flight_hours invariant (PRD §1.1 Contract.season_flight_hours_tenths)
# ---------------------------------------------------------------------------
def recompute_contract_season_hours(contract):
    total = 0
    for a in db.assignments.values():
        order = db.dispatch_orders.get(a["dispatch_order_id"])
        if order is None or order["contract_id"] != contract["id"]:
            continue
        for fl in db.flight_logs.values():
            if fl["assignment_id"] == a["id"]:
                total += fl["flight_hours_tenths"]
    contract["season_flight_hours_tenths"] = total


# ---------------------------------------------------------------------------
# reload_turn_time (PRD §3.7)
# ---------------------------------------------------------------------------
def compute_reload_turn(load, assignment_id):
    """Previous = load of the same assignment with greatest dropped_at strictly
    before this load's loaded_at; tie-break on equal dropped_at: earlier
    created_at first; never id."""
    candidates = [
        l
        for l in db.retardant_loads.values()
        if l["assignment_id"] == assignment_id
        and l["id"] != load["id"]
        and l["dropped_at"] is not None
        and l["dropped_at"] < load["loaded_at"]
    ]
    if not candidates:
        return None
    # greatest dropped_at; tie-break on equal dropped_at -> earlier created_at
    candidates.sort(key=lambda l: l["created_at"])
    max_drop = max(l["dropped_at"] for l in candidates)
    tied = [l for l in candidates if l["dropped_at"] == max_drop]
    tied.sort(key=lambda l: l["created_at"])
    previous = tied[0]
    delta = load["loaded_at"] - previous["dropped_at"]
    return int(delta.total_seconds() // 60)


def recompute_assignment_reload_fields(assignment):
    turns = [
        l["reload_turn_minutes"]
        for l in db.retardant_loads.values()
        if l["assignment_id"] == assignment["id"] and l["reload_turn_minutes"] is not None
    ]
    if not turns:
        assignment["reload_turn_avg_minutes"] = None
        assignment["reload_sla_breach"] = False
    else:
        avg = (Decimal(sum(turns)) / Decimal(len(turns))).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        assignment["reload_turn_avg_minutes"] = float(avg)
        assignment["reload_sla_breach"] = bool(avg > RELOAD_SLA_MINUTES)


# ---------------------------------------------------------------------------
# invoice_net_composition + reconciliation_billing (PRD §3.8)
# ---------------------------------------------------------------------------
def rederive_invoice(invoice):
    """Regenerate line items and recompute totals for a DRAFT invoice.

    Pinned line order: AVAILABILITY_DAY by service_date ASC, then FLIGHT_DAY by
    reference_date ASC (tie: assignment created_at ASC), then PENALTY last.
    """
    contract = db.contracts[invoice["contract_id"]]
    # drop existing lines
    doomed = [lid for lid, li in db.invoice_line_items.items() if li["invoice_id"] == invoice["id"]]
    for lid in doomed:
        del db.invoice_line_items[lid]

    period_start = str_to_date(invoice["period_start"])
    period_end = str_to_date(invoice["period_end"])

    # --- AVAILABILITY_DAY lines ---
    periods = [
        p
        for p in db.availability_periods.values()
        if p["contract_id"] == contract["id"]
        and period_start <= str_to_date(p["service_date"]) <= period_end
        and p["status"] in ("CONFIRMED", "UNAVAILABLE", "EXCUSED")
    ]
    periods.sort(key=lambda p: (p["service_date"], p["created_at"]))
    lines = []
    for p in periods:
        charge = compute_availability_charge(p, contract)
        p["availability_charge_cents"] = charge
        line = {
            "id": db.new_id(),
            "created_at": db.iso_now_ms(),
            "invoice_id": invoice["id"],
            "line_type": "AVAILABILITY_DAY",
            "reference_date": p["service_date"],
            "source_ref_id": p["id"],
            "carrier_qty": p["available_minutes"],
            "carrier_amount_cents": charge,
            "agency_qty": None,
            "agency_amount_cents": charge,
            "billed_amount_cents": charge,
            "mismatch_flag": False,
        }
        db.stamp_new(line)
        db.invoice_line_items[line["id"]] = line
        lines.append(line)

    # --- FLIGHT_DAY lines (per assignment per logged_date) ---
    groups = {}
    for a in db.assignments.values():
        order = db.dispatch_orders.get(a["dispatch_order_id"])
        if order is None or order["contract_id"] != contract["id"]:
            continue
        for fl in db.flight_logs.values():
            if fl["assignment_id"] != a["id"]:
                continue
            if not (period_start <= str_to_date(fl["logged_date"]) <= period_end):
                continue
            key = (fl["logged_date"], a["id"])
            grp = groups.setdefault(
                key,
                {
                    "reference_date": fl["logged_date"],
                    "assignment_id": a["id"],
                    "assignment_created_at": a["created_at"],
                    "carrier_qty": 0,
                    "carrier_amount_cents": 0,
                },
            )
            grp["carrier_qty"] += fl["flight_hours_tenths"]
            grp["carrier_amount_cents"] += fl["billable_cents"]

    flight_groups = sorted(
        groups.values(),
        key=lambda g: (g["reference_date"], g["assignment_created_at"]),
    )
    for g in flight_groups:
        line = {
            "id": db.new_id(),
            "created_at": db.iso_now_ms(),
            "invoice_id": invoice["id"],
            "line_type": "FLIGHT_DAY",
            "reference_date": g["reference_date"],
            "source_ref_id": g["assignment_id"],
            "carrier_qty": g["carrier_qty"],
            "carrier_amount_cents": g["carrier_amount_cents"],
            "agency_qty": None,
            "agency_amount_cents": g["carrier_amount_cents"],
            "billed_amount_cents": g["carrier_amount_cents"],
            "mismatch_flag": False,
        }
        db.stamp_new(line)
        db.invoice_line_items[line["id"]] = line
        lines.append(line)

    recompute_invoice_totals(invoice, lines)
    return lines


def recompute_invoice_totals(invoice, lines=None):
    """Pinned six-step evaluation order (invoice_net_composition)."""
    if lines is None:
        lines = [
            li for li in db.invoice_line_items.values() if li["invoice_id"] == invoice["id"]
        ]
        lines.sort(key=lambda li: li["created_at"])

    availability_lines = [li for li in lines if li["line_type"] == "AVAILABILITY_DAY"]
    flight_lines = [li for li in lines if li["line_type"] == "FLIGHT_DAY"]

    # remove any existing PENALTY line before recomputation
    for li in list(db.invoice_line_items.values()):
        if li["invoice_id"] == invoice["id"] and li["line_type"] == "PENALTY":
            del db.invoice_line_items[li["id"]]
    lines = [li for li in lines if li["line_type"] != "PENALTY"]

    # (1)
    invoice["availability_subtotal_cents"] = sum(
        li["carrier_amount_cents"] for li in availability_lines
    )
    # (2)
    invoice["flight_subtotal_cents"] = sum(
        li["billed_amount_cents"] for li in flight_lines
    )
    # (3)
    expected_days = len(availability_lines)
    # (4)
    contract = db.contracts[invoice["contract_id"]]
    compliant_days = 0
    for li in availability_lines:
        period = db.availability_periods.get(li["source_ref_id"])
        if period is None:
            continue
        if period["status"] == "CONFIRMED" and (
            period["available_minutes"] >= contract["min_daily_available_minutes"]
        ):
            compliant_days += 1
        elif period["status"] == "EXCUSED":
            compliant_days += 1
    # (5) exact rational comparison: compliant*100 < expected*98
    if expected_days > 0 and compliant_days * 100 < expected_days * COMPLIANCE_THRESHOLD_NUM:
        invoice["penalty_cents"] = int(
            (Decimal(invoice["availability_subtotal_cents"]) * PENALTY_RATE).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    else:
        invoice["penalty_cents"] = 0
    # PENALTY line last
    if invoice["penalty_cents"] > 0:
        pline = {
            "id": db.new_id(),
            "created_at": db.iso_now_ms(),
            "invoice_id": invoice["id"],
            "line_type": "PENALTY",
            "reference_date": invoice["period_end"],
            "source_ref_id": invoice["id"],
            "carrier_qty": 0,
            "carrier_amount_cents": -invoice["penalty_cents"],
            "agency_qty": None,
            "agency_amount_cents": -invoice["penalty_cents"],
            "billed_amount_cents": -invoice["penalty_cents"],
            "mismatch_flag": False,
        }
        db.stamp_new(pline)
        db.invoice_line_items[pline["id"]] = pline
    # (6)
    invoice["net_cents"] = (
        invoice["availability_subtotal_cents"]
        + invoice["flight_subtotal_cents"]
        - invoice["penalty_cents"]
    )


def rederive_covering_draft_invoices(contract_id, service_date_str):
    """Re-derive every DRAFT invoice of the contract whose period covers the date."""
    d = str_to_date(service_date_str)
    for inv in db.invoices.values():
        if inv["contract_id"] != contract_id or inv["status"] != "DRAFT":
            continue
        if str_to_date(inv["period_start"]) <= d <= str_to_date(inv["period_end"]):
            rederive_invoice(inv)
            touch(inv)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def fire_aircraft_failed_inspection_cascade(aircraft_entity, completed_at):
    """Aircraft CARDED -> SUSPENDED cascade (3 links)."""
    fail_date = completed_at.date()
    for p in db.availability_periods.values():
        if (
            p["aircraft_id"] == aircraft_entity["id"]
            and p["status"] == "CONFIRMED"
            and str_to_date(p["service_date"]) >= fail_date
        ):
            p["status"] = "UNAVAILABLE"
            p["excuse_reason"] = "CARDING"
            p["availability_charge_cents"] = 0
            touch(p)
            rederive_covering_draft_invoices(p["contract_id"], p["service_date"])


def fire_fatigue_cascade(crew, duty_day):
    """FlightLog -> CrewDutyDay -> CrewMember -> Assignment -> DispatchOrder."""
    if crew["duty_status"] != "AVAILABLE":
        return
    crew["duty_status"] = "FATIGUE_HOLD"
    touch(crew)
    now = db.clock_now()
    for a in db.assignments.values():
        if a["pilot_id"] == crew["id"] and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            a["release_reason"] = "FATIGUE"
            a["released_at"] = fmt_dt(now)
            touch(a)
            order = db.dispatch_orders.get(a["dispatch_order_id"])
            if order is not None:
                old_status = order["status"]
                recompute_order_fill(order)
                if order["status"] != old_status or True:
                    touch(order)
            # refresh the released assignment's duty day projection
            dd = get_duty_day(a["pilot_id"], a["planned_start"].date().isoformat())
            if dd is not None:
                recompute_duty_day(dd)


# ---------------------------------------------------------------------------
# flight_sortie_billing (PRD §3.6)
# ---------------------------------------------------------------------------
def sortie_tenths_and_billable(hobbs_start, hobbs_stop, flight_hour_rate_cents):
    hours = Decimal(str(hobbs_stop)) - Decimal(str(hobbs_start))
    tenths = int((hours * 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    billable = int(
        (Decimal(tenths) / Decimal(10) * Decimal(flight_hour_rate_cents)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return tenths, billable


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def _clean(out):
    out.pop("_seq", None)
    return out


def ser_contract(c):
    return _clean(dict(c))


def ser_aircraft(a):
    return _clean(dict(a))


def ser_crew(m):
    return _clean(dict(m))


def ser_inspection(i):
    out = dict(i)
    out["scheduled_for"] = fmt_dt(i["scheduled_for"]) if isinstance(i["scheduled_for"], type(db.clock_now())) else i["scheduled_for"]
    out["completed_at"] = fmt_dt(i["completed_at"]) if i["completed_at"] is not None and not isinstance(i["completed_at"], str) else i["completed_at"]
    return _clean(out)


def ser_period(p):
    out = dict(p)
    out["available_start"] = fmt_dt(p["available_start"])
    out["available_end"] = fmt_dt(p["available_end"])
    return _clean(out)


def ser_incident(i):
    return _clean(dict(i))


def ser_order(o):
    out = dict(o)
    out["placed_at"] = fmt_dt(o["placed_at"])
    out["accept_deadline"] = fmt_dt(o["accept_deadline"])
    return _clean(out)


def ser_assignment(a):
    out = dict(a)
    out["planned_start"] = fmt_dt(a["planned_start"])
    out["planned_end"] = fmt_dt(a["planned_end"])
    for f in ("assigned_at", "launched_at", "arrived_at", "released_at", "demobilized_at"):
        v = out.get(f)
        if v is not None and not isinstance(v, str):
            out[f] = fmt_dt(v)
    return _clean(out)


def ser_flight_log(fl):
    return _clean(dict(fl))


def ser_load(l):
    out = dict(l)
    for f in ("requested_at", "loaded_at", "dropped_at"):
        v = out.get(f)
        if v is not None and not isinstance(v, str):
            out[f] = fmt_dt(v)
    return _clean(out)


def ser_duty_day(dd):
    out = dict(dd)
    v = out.get("duty_start")
    if v is not None and not isinstance(v, str):
        out["duty_start"] = fmt_dt(v)
    return _clean(out)


def ser_invoice(inv):
    return _clean(dict(inv))


def ser_line_item(li):
    return _clean(dict(li))


def ser_agency_record(r):
    return _clean(dict(r))
