"""Calculation rules (SCAFFOLD table 3). Derived fields are computed on read."""
from datetime import datetime, timezone, time, timedelta
from decimal import Decimal
from clock import clock
from db import store
from util import q2, to_dec

RECORDABLE_SEVERITIES = ("MEDICAL_TREATMENT", "LOST_TIME", "FATALITY")
EXCUSABLE = ("EXCUSABLE_COMPENSABLE", "EXCUSABLE_NON_COMPENSABLE")
CLOSED_INCIDENT_STATUSES = ("CLOSED_RECORDABLE", "CLOSED_NOT_RECORDABLE")

OT_MULT = Decimal("1.5")
DT_MULT = Decimal("2")
STANDBY_MULT = Decimal("0.5")
TIER_CAP_CENTS = 100000
MARKUP_LOW_PCT = Decimal("0.10")
MARKUP_HIGH_PCT = Decimal("0.05")


def touch(rec):
    """Every mutation refreshes updated_at and bumps version (common_fields)."""
    rec["updated_at"] = clock.now()
    rec["version"] += 1


def bump_report(report):
    touch(report)


# ---------------------------------------------------------------------------
# calc_manpower_split
# ---------------------------------------------------------------------------

def crew_bands(worker_count, hours_per_worker):
    hpw = to_dec(hours_per_worker)
    wc = Decimal(worker_count)
    reg = q2(wc * min(hpw, Decimal(8)))
    ot = q2(wc * min(max(hpw - Decimal(8), Decimal(0)), Decimal(4)))
    dt = q2(wc * max(hpw - Decimal(12), Decimal(0)))
    return reg, ot, dt


def report_manpower(report_id):
    workers = 0
    reg = Decimal(0)
    ot = Decimal(0)
    dt = Decimal(0)
    for c in store.crew_entries.values():
        if c["report_id"] == report_id and c["status"] == "ACTIVE":
            workers += c["worker_count"]
            reg += c["regular_hours"]
            ot += c["ot_hours"]
            dt += c["dt_hours"]
    return workers, q2(reg), q2(ot), q2(dt)


# ---------------------------------------------------------------------------
# calc_lost_hours / calc_lost_day_classification
# ---------------------------------------------------------------------------

def shift_window(report, project):
    if report.get("shift_start_actual") is not None:
        start = report["shift_start_actual"]
    else:
        hh, mm = project["scheduled_shift_start"].split(":")
        start = datetime.combine(
            report["report_date"], time(int(hh), int(mm)), tzinfo=timezone.utc
        )
    hours = to_dec(project["scheduled_shift_hours"])
    end = start + timedelta(seconds=float(hours * Decimal(3600)))
    return start, end


def calc_lost_hours(event, report, project):
    ss, se = shift_window(report, project)
    s = max(event["start_at"], ss)
    e = min(event["end_at"], se)
    secs = Decimal(str((e - s).total_seconds()))
    if secs <= 0:
        return Decimal("0.00")
    return q2(secs / Decimal(3600))


def report_weather(report_id, project):
    total = Decimal(0)
    for ev in store.delay_events.values():
        if (
            ev["report_id"] == report_id
            and ev["cause"] == "WEATHER"
            and ev["status"] in ("CLASSIFIED", "FINAL")
            and ev["classification"] in EXCUSABLE
            and ev["lost_hours"] is not None
        ):
            total += ev["lost_hours"]
    total = q2(total)
    shift_hours = to_dec(project["scheduled_shift_hours"])
    calendar = total >= (shift_hours * Decimal("0.5"))
    fraction = q2(min(total / shift_hours, Decimal(1)))
    return total, calendar, fraction


# ---------------------------------------------------------------------------
# calc_quantity_rollup / calc_progress_percent
# ---------------------------------------------------------------------------

def installed_to_date(work_item_id):
    total = Decimal(0)
    for qe in store.quantity_entries.values():
        if qe["work_item_id"] != work_item_id or qe["status"] != "ACTIVE":
            continue
        rep = store.daily_reports.get(qe["report_id"])
        if rep is not None and rep["status"] in ("APPROVED", "LOCKED"):
            total += qe["rounded_quantity"]
    return total


def work_item_status(wi, installed):
    if installed == 0:
        return "NOT_STARTED"
    if installed >= wi["budgeted_quantity"]:
        return "COMPLETE"
    return "IN_PROGRESS"


def project_percents(project_id):
    items = [w for w in store.work_items.values() if w["project_id"] == project_id]
    count = len(items)
    if count == 0:
        return Decimal("0.00"), Decimal("0.00"), 0
    ratio_sum = Decimal(0)
    num = Decimal(0)
    den = Decimal(0)
    for wi in items:
        inst = installed_to_date(wi["id"])
        b = wi["budgeted_quantity"]
        c = Decimal(wi["unit_cost_cents"])
        ratio_sum += min(inst, b) / b
        num += inst * c
        den += b * c
    units = q2(ratio_sum / Decimal(count) * Decimal(100))
    cost = q2(num / den * Decimal(100)) if den != 0 else Decimal("0.00")
    return units, cost, count


# ---------------------------------------------------------------------------
# calc_tm_ticket_total / calc_material_markup
# ---------------------------------------------------------------------------

def report_has_stoppage(report_id):
    return any(
        w["report_id"] == report_id and w["work_impact"] == "STOPPAGE"
        for w in store.weather_observations.values()
    )


def normalize_labor_line(x):
    from validate import req_str, req_int, req_num

    if not isinstance(x, dict):
        from errors import bad
        bad("labor_lines entries must be objects")
    return {
        "trade": req_str(x, "trade"),
        "worker_count": req_int(x, "worker_count", mn=1),
        "regular_hours": req_num(x, "regular_hours", mn=Decimal(0)),
        "ot_hours": req_num(x, "ot_hours", mn=Decimal(0)),
        "dt_hours": req_num(x, "dt_hours", mn=Decimal(0)),
        "rate_cents": req_int(x, "rate_cents", mn=0),
    }


def normalize_equipment_line(x):
    from validate import req_str, req_int, req_num, opt_bool
    from errors import bad

    if not isinstance(x, dict):
        bad("equipment_lines entries must be objects")
    return {
        "equipment_type": req_str(x, "equipment_type"),
        "hours": req_num(x, "hours", mn=Decimal(0)),
        "rate_cents": req_int(x, "rate_cents", mn=0),
        "standby": opt_bool(x, "standby", False),
    }


def normalize_material_line(x):
    from validate import req_str, req_int, req_num
    from errors import bad

    if not isinstance(x, dict):
        bad("material_lines entries must be objects")
    return {
        "description": req_str(x, "description"),
        "quantity": req_num(x, "quantity", gt=Decimal(0)),
        "unit_price_cents": req_int(x, "unit_price_cents", mn=0),
    }


def price_ticket(labor_lines, equipment_lines, material_lines, has_stoppage):
    labor_total = 0
    for ln in labor_lines:
        rate = Decimal(ln["rate_cents"])
        per_worker = (
            ln["regular_hours"] * rate
            + ln["ot_hours"] * rate * OT_MULT
            + ln["dt_hours"] * rate * DT_MULT
        )
        line_cost = (Decimal(ln["worker_count"]) * per_worker).quantize(
            Decimal("1"), rounding="ROUND_HALF_UP"
        )
        labor_total += int(line_cost)

    equipment_total = 0
    for ln in equipment_lines:
        mult = STANDBY_MULT if (ln.get("standby") and has_stoppage) else Decimal(1)
        line_cost = (ln["hours"] * Decimal(ln["rate_cents"]) * mult).quantize(
            Decimal("1"), rounding="ROUND_HALF_UP"
        )
        equipment_total += int(line_cost)

    subtotal = 0
    for ln in material_lines:
        line_cost = (ln["quantity"] * Decimal(ln["unit_price_cents"])).quantize(
            Decimal("1"), rounding="ROUND_HALF_UP"
        )
        subtotal += int(line_cost)
    pct = MARKUP_LOW_PCT if subtotal <= TIER_CAP_CENTS else MARKUP_HIGH_PCT
    markup = int(
        (Decimal(subtotal) * pct).quantize(Decimal("1"), rounding="ROUND_HALF_UP")
    )
    materials_cost = subtotal + markup

    return {
        "labor_cost_cents": labor_total,
        "equipment_cost_cents": equipment_total,
        "materials_subtotal_cents": subtotal,
        "materials_markup_cents": markup,
        "materials_cost_cents": materials_cost,
        "total_cents": labor_total + equipment_total + materials_cost,
    }


# ---------------------------------------------------------------------------
# calc_report_posture / calc_osha_deadline / calc_retention_release
# ---------------------------------------------------------------------------

def content_posture(report):
    return (
        "EDITABLE"
        if report["status"] in ("DRAFT", "REVISION_REQUESTED")
        else "SEALED"
    )


def report_incident_flags(report_id):
    incs = [i for i in store.incidents.values() if i["report_id"] == report_id]
    has_open = any(i["status"] not in CLOSED_INCIDENT_STATUSES for i in incs)
    claims_hold = any(i["recordable"] for i in incs)
    return has_open, ("CLAIMS_HOLD" if claims_hold else "STANDARD")


def osha_deadline(severity, occurred_at):
    if severity == "FATALITY":
        return occurred_at + timedelta(hours=8)
    if severity == "LOST_TIME":
        return occurred_at + timedelta(hours=24)
    return None


def is_recordable(severity):
    return severity in RECORDABLE_SEVERITIES


def notification_overdue(inc):
    return bool(
        inc["recordable"]
        and inc["osha_notification_deadline"] is not None
        and inc["osha_notified_at"] is None
        and clock.now() > inc["osha_notification_deadline"]
    )


def retention_release(report):
    _, cls = report_incident_flags(report["id"])
    if cls == "CLAIMS_HOLD":
        return None
    sent = [
        d
        for d in store.distribution_records.values()
        if d["report_id"] == report["id"] and d["status"] in ("SENT", "ACKNOWLEDGED")
    ]
    if not sent:
        return None
    project = store.projects.get(report["project_id"])
    latest = max(d["sent_at"] for d in sent)
    return latest + timedelta(days=project["retention_days"])


def apply_hold_cascade(report):
    """distribution_hold follows has_open_incident; PENDING<->BLOCKED flips."""
    has_open, _ = report_incident_flags(report["id"])
    for d in store.distribution_records.values():
        if d["report_id"] != report["id"]:
            continue
        if has_open and d["status"] == "PENDING":
            d["status"] = "BLOCKED"
            touch(d)
        elif not has_open and d["status"] == "BLOCKED":
            d["status"] = "PENDING"
            touch(d)


def distribution_hold(report):
    has_open, _ = report_incident_flags(report["id"])
    return has_open
