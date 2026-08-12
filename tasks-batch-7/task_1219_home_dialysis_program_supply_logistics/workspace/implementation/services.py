"""Business logic: calculations, posture derivation, lazy evaluation, cascades.

Every rule here traces to SCAFFOLD.yaml §1.3 (calculations), §1.2 (state
machines) and PRD §3 (workflows). The logical clock (db.now()) is the only
time source.
"""
import math
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

import db

S = db.STORES

# --- constants (SCAFFOLD calculations.constants) ---
MODULE_PASS_PCT = 80
MODULES = ["WATER_HANDLING", "MACHINE_OPERATION", "ASEPTIC_TECHNIQUE",
           "EMERGENCY_RESPONSE", "SUPPLY_STORAGE"]
SQFT_TO_UNITS = 4
MAX_STORAGE_UNITS = 400
MIN_STORAGE_SQFT = 25
CHLORAMINE_MAX_PPM = 0.1
WEEKS_PER_MONTH = 4
BASE_HANDLING_CENTS = 500
VOLUME_DISCOUNT_THRESHOLD_CENTS = 20000
VOLUME_DISCOUNT_RATIO = Decimal("0.05")
RETURN_FULL_CREDIT_LIMIT = 10
RETURN_OVERAGE_CREDIT_RATIO = Decimal("0.5")
MAINTENANCE_INTERVAL_HOURS = 500
RECERT_DAYS = 365
ASSESSMENT_VALIDITY_DAYS = 730
DRILL_VALIDITY_DAYS = 90
REVIEW_SLA_DAYS = 5
ROLLING_WINDOW_DAYS = 28

OPEN_ORDER_STATES = ["DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"]


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 datetime to an aware datetime (UTC default)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def round_half_up_cents(value):
    """Round a Decimal/float to integer cents, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(value):
    """Hours at 2 decimal places (float, half up)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def month_bounds(ym):
    """Return (first_date, first_of_next_month_date) for 'YYYY-MM'."""
    y, m = int(ym[:4]), int(ym[5:7])
    first = date(y, m, 1)
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return first, nxt


def valid_month(ym):
    if not isinstance(ym, str) or len(ym) != 7 or ym[4] != "-":
        return False
    try:
        month_bounds(ym)
        return True
    except (ValueError, IndexError):
        return False


def get(store, rid):
    return S[store].get(rid)


# ---------------------------------------------------------------------------
# lazy evaluation (PRD §2.5)
# ---------------------------------------------------------------------------

def lazy_eval_plan(plan):
    """ACTIVE plan with last_drill_at >= 90 days old reads as EXPIRED."""
    if plan["status"] == "ACTIVE":
        last = parse_dt(plan["last_drill_at"])
        if last is not None and db.now() >= last + timedelta(days=DRILL_VALIDITY_DAYS):
            plan["status"] = "EXPIRED"
            db.touch(plan)
    return plan


def lazy_eval_reservation(res):
    """RESERVED past slot_end reads as NO_SHOW; increments patient no_show_count once."""
    if res["status"] == "RESERVED":
        end = parse_dt(res["slot_end"])
        if end is not None and db.now() > end:
            res["status"] = "NO_SHOW"
            db.touch(res)
            patient = get("patients", res["patient_id"])
            if patient is not None:
                patient["no_show_count"] = patient.get("no_show_count", 0) + 1
                db.touch(patient)
    return res


def lazy_eval_transition(tr):
    """Temporary ACTIVE transition past effective_to reads as COMPLETED; patient
    SUSPENDED -> ACTIVE_HOME with no readiness-gate recheck (PRD §3.9)."""
    if tr["status"] == "ACTIVE" and tr.get("effective_to"):
        et = parse_date(tr["effective_to"])
        if et is not None and db.now().date() > et:
            tr["status"] = "COMPLETED"
            db.touch(tr)
            patient = get("patients", tr["patient_id"])
            if patient is not None and patient["program_status"] == "SUSPENDED":
                patient["program_status"] = "ACTIVE_HOME"
                db.touch(patient)
    return tr


def lazy_eval_patient_scoped(patient_id):
    """Apply lazy transitions for plans, reservations, transitions of a patient."""
    for plan in S["emergency_backup_plans"].values():
        if plan["patient_id"] == patient_id:
            lazy_eval_plan(plan)
    for res in S["backup_slot_reservations"].values():
        if res["patient_id"] == patient_id:
            lazy_eval_reservation(res)
    for tr in S["transition_records"].values():
        if tr["patient_id"] == patient_id:
            lazy_eval_transition(tr)


# ---------------------------------------------------------------------------
# derived patient fields (SCAFFOLD calculations)
# ---------------------------------------------------------------------------

def patient_program(patient):
    return get("dialysis_programs", patient["program_id"])


def compute_on_hand_units(patient_id):
    delivered = sum(a.get("delivered_units", 0)
                    for a in S["delivery_appointments"].values()
                    if a["status"] == "DELIVERED"
                    and (lambda o: o is not None and o["patient_id"] == patient_id)(
                        get("supply_orders", a["supply_order_id"])))
    consumed = sum(l["consumption_units"]
                   for l in S["treatment_logs"].values()
                   if l["patient_id"] == patient_id)
    wasted = sum(w["total_units"]
                 for w in S["waste_return_records"].values()
                 if w["patient_id"] == patient_id and w["status"] in ("CREDITED", "VERIFIED"))
    return delivered - consumed - wasted


def compute_missed_log_streak(patient):
    program = patient_program(patient)
    tpw = patient["prescription_treatments_per_week"]
    expected_interval_days = max(1, math.floor(7 / tpw))
    logs = [l for l in S["treatment_logs"].values() if l["patient_id"] == patient["id"]]
    if logs:
        anchor = max(parse_date(l["treatment_date"]) for l in logs)
    else:
        anchor = parse_dt(patient["created_at"]).date()
    silence_days = max(0, (db.now().date() - anchor).days)
    return math.floor(silence_days / expected_interval_days)


def latest_accepted_assessment(patient_id):
    accepted = [a for a in S["home_assessments"].values()
                if a["patient_id"] == patient_id and a["status"] == "ACCEPTED"]
    if not accepted:
        return None
    return max(accepted, key=lambda a: (a["accepted_at"] or "", a["created_at"], a.get("_seq", 0)))


def cert_current(patient_id):
    for module in MODULES:
        ok = False
        for att in S["training_attempts"].values():
            if (att["patient_id"] == patient_id and att["module_code"] == module
                    and att["status"] == "SIGNED_OFF" and att["is_passing"]):
                so = parse_dt(att["signed_off_at"])
                if so is not None and so > db.now() - timedelta(days=RECERT_DAYS):
                    ok = True
                    break
        if not ok:
            return False
    return True


def assessment_current(patient_id):
    for a in S["home_assessments"].values():
        if a["patient_id"] == patient_id and a["status"] == "ACCEPTED":
            acc = parse_dt(a["accepted_at"])
            if acc is not None and acc > db.now() - timedelta(days=ASSESSMENT_VALIDITY_DAYS):
                return True
    return False


def assigned_machine(patient_id):
    for m in S["dialysis_machines"].values():
        if m["status"] == "ASSIGNED" and m.get("assigned_patient_id") == patient_id:
            return m
    return None


def active_plan(patient_id):
    for p in S["emergency_backup_plans"].values():
        if p["patient_id"] == patient_id:
            lazy_eval_plan(p)
            if p["status"] == "ACTIVE":
                return p
    return None


def readiness_gates(patient):
    """Return dict of the four gates."""
    pid = patient["id"]
    return {
        "cert": cert_current(pid),
        "assessment": assessment_current(pid),
        "machine": assigned_machine(pid) is not None,
        "plan": active_plan(pid) is not None,
    }


def compute_machine_runtime(machine_id):
    minutes = sum(l["duration_minutes"] for l in S["treatment_logs"].values()
                  if l["machine_id"] == machine_id)
    return round2(minutes / 60)


def compute_runtime_at_last_service(machine_id):
    completed = [e for e in S["maintenance_events"].values()
                 if e["machine_id"] == machine_id and e["status"] == "COMPLETED"]
    if not completed:
        return 0
    latest = max(completed, key=lambda e: (e["updated_at"], e["created_at"], e.get("_seq", 0)))
    return latest.get("runtime_hours_at_service", 0)


def compute_maintenance_due(machine):
    total = compute_machine_runtime(machine["id"])
    last = compute_runtime_at_last_service(machine["id"])
    return (Decimal(str(total)) - Decimal(str(last))) >= Decimal(MAINTENANCE_INTERVAL_HOURS)


def review_overdue(patient_id):
    for r in S["clinical_reviews"].values():
        if r["patient_id"] == patient_id and r["status"] == "PENDING":
            due = parse_dt(r["due_at"])
            if due is not None and due < db.now():
                return True
    return False


def escalation_open(patient_id):
    escalated = [r for r in S["clinical_reviews"].values()
                 if r["patient_id"] == patient_id and r["status"] == "ESCALATED"]
    if not escalated:
        return False
    signed = [r for r in S["clinical_reviews"].values()
              if r["patient_id"] == patient_id and r["status"] == "SIGNED_OFF"]
    if not signed:
        return True
    latest_signed = max(r["created_at"] for r in signed)
    return any(r["created_at"] > latest_signed for r in escalated)


def compute_posture(patient):
    """SCAFFOLD calculations.posture_derivation — precedence ladder, first match wins."""
    lazy_eval_patient_scoped(patient["id"])
    program = patient_program(patient)

    if patient["program_status"] == "TRAINING":
        return "NOT_READY"
    if patient["program_status"] == "TRANSITIONED_OUT":
        return "BLOCKED"

    gates = readiness_gates(patient)
    if not patient["ever_home_ready"]:
        return "HOME_READY" if all(gates.values()) else "NOT_READY"

    # rung 4 — BLOCKED
    if (not gates["cert"]) or (not gates["assessment"]):
        return "BLOCKED"
    if review_overdue(patient["id"]) or escalation_open(patient["id"]):
        return "BLOCKED"
    if patient.get("retraining_required"):
        return "BLOCKED"

    # rung 5 — AT_RISK
    machine = assigned_machine(patient["id"])
    if machine is None:
        return "AT_RISK"
    if compute_maintenance_due(machine):
        return "AT_RISK"
    # assigned machine in UNDER_MAINTENANCE degrades (machine gate requires ASSIGNED)
    if not gates["machine"]:
        return "AT_RISK"
    if active_plan(patient["id"]) is None:
        return "AT_RISK"
    streak = compute_missed_log_streak(patient)
    if program is not None and streak >= program["max_missed_log_streak"]:
        return "AT_RISK"
    if patient.get("waste_alert_active"):
        return "AT_RISK"
    return "HOME_READY"


def patient_view(patient, recompute=True):
    """Return the serialized patient with derived fields refreshed."""
    patient["on_hand_units"] = compute_on_hand_units(patient["id"])
    patient["missed_log_streak"] = compute_missed_log_streak(patient)
    latest = latest_accepted_assessment(patient["id"])
    patient["storage_cap_units"] = latest["storage_cap_units"] if latest else 0
    if recompute:
        patient["posture"] = compute_posture(patient)
    return patient


def machine_view(machine):
    machine["total_runtime_hours"] = compute_machine_runtime(machine["id"])
    machine["runtime_hours_at_last_service"] = compute_runtime_at_last_service(machine["id"])
    machine["maintenance_due"] = compute_maintenance_due(machine)
    return machine


# ---------------------------------------------------------------------------
# calculations: assessment, order money, allowance, return credit
# ---------------------------------------------------------------------------

def evaluate_assessment(water_chloramine_ppm, electrical_dedicated_circuit,
                        electrical_voltage_verified, storage_area_sqft):
    cap = min(MAX_STORAGE_UNITS, math.floor(storage_area_sqft * SQFT_TO_UNITS))
    result = ("PASS" if (water_chloramine_ppm <= CHLORAMINE_MAX_PPM
                         and electrical_dedicated_circuit is True
                         and electrical_voltage_verified is True
                         and storage_area_sqft >= MIN_STORAGE_SQFT)
              else "FAIL")
    return cap, result


def catalog_map(program):
    return {e["sku"]: e for e in program.get("supply_catalog", [])}


def compute_order_money(program, lines):
    """Returns (provisional_total_units, subtotal_cents, handling_fee_cents,
    discount_cents, grand_total_cents). Per-line round-half-up pinned (mode b);
    discount keyed on subtotal (mode c)."""
    catalog = catalog_map(program)
    provisional = sum(int(l["quantity"]) for l in lines)
    subtotal = sum(int(l["quantity"]) * int(catalog[l["sku"]]["unit_price_cents"])
                   for l in lines)
    handling = BASE_HANDLING_CENTS + sum(
        round_half_up_cents(Decimal(str(l["quantity"])) * Decimal(str(catalog[l["sku"]]["handling_rate_cents"])))
        for l in lines)
    discount = (round_half_up_cents(Decimal(subtotal) * VOLUME_DISCOUNT_RATIO)
                if subtotal >= VOLUME_DISCOUNT_THRESHOLD_CENTS else 0)
    grand = subtotal - discount + handling
    return provisional, subtotal, handling, discount, grand


def compute_carried_adjustment(patient_id, order_month):
    """adjustment_units of patient's CLOSED order for the immediately preceding month."""
    first, _ = month_bounds(order_month)
    prev_first = (date(first.year - 1, 12, 1) if first.month == 1
                  else date(first.year, first.month - 1, 1))
    prev_ym = f"{prev_first.year:04d}-{prev_first.month:02d}"
    for o in S["supply_orders"].values():
        if (o["patient_id"] == patient_id and o["order_month"] == prev_ym
                and o["order_status"] == "CLOSED"):
            return o.get("adjustment_units") or 0
    return 0


def compute_actualized_units(patient_id, order_month):
    first, nxt = month_bounds(order_month)
    total = 0
    for l in S["treatment_logs"].values():
        if l["patient_id"] != patient_id:
            continue
        d = parse_date(l["treatment_date"])
        if d is not None and first <= d < nxt:
            total += l["consumption_units"]
    return total


def delivered_sku_month(patient_id, activity_month):
    """Delivered attribution: allocate each DELIVERED appointment's units across
    its order's lines in stored line order; bucket by appointment window_start month."""
    first, nxt = month_bounds(activity_month)
    result = {}
    appointments = [a for a in S["delivery_appointments"].values()
                    if a["status"] == "DELIVERED"]
    appointments.sort(key=lambda a: (a["created_at"], a.get("_seq", 0)))
    for a in appointments:
        ws = parse_dt(a["window_start"])
        if ws is None or not (first <= ws.date() < nxt):
            continue
        order = get("supply_orders", a["supply_order_id"])
        if order is None or order["patient_id"] != patient_id:
            continue
        remaining = a.get("delivered_units", 0)
        for line in order["lines"]:
            if remaining <= 0:
                break
            take = min(remaining, int(line["quantity"]))
            result[line["sku"]] = result.get(line["sku"], 0) + take
            remaining -= take
    return result


def compute_return_credit(patient, record):
    """calculations.return_credit — mode (a) with tiered full/half credit."""
    program = patient_program(patient)
    catalog = catalog_map(program)
    delivered = delivered_sku_month(patient["id"], record["activity_month"])
    # prior credited returns, same month, grouped by sku (request order replay)
    prior_records = [w for w in S["waste_return_records"].values()
                     if w["patient_id"] == patient["id"]
                     and w["status"] == "CREDITED"
                     and w["record_type"] == "RETURN"
                     and w["activity_month"] == record["activity_month"]]
    prior_records.sort(key=lambda w: (w["created_at"], w.get("_seq", 0)))
    returned_prior = {}
    for w in prior_records:
        for line in w["lines"]:
            returned_prior[line["sku"]] = returned_prior.get(line["sku"], 0) + int(line["units"])

    credit_cents = 0
    for line in record["lines"]:
        if line.get("expired"):
            continue
        sku = line["sku"]
        prior = returned_prior.get(sku, 0)
        eligible = max(0, min(int(line["units"]), delivered.get(sku, 0) - prior))
        full_credit_used_prior = min(prior, RETURN_FULL_CREDIT_LIMIT)
        full_portion = min(eligible, RETURN_FULL_CREDIT_LIMIT - full_credit_used_prior)
        overage = eligible - full_portion
        unit_credit = Decimal(str(catalog[sku]["unit_credit_cents"]))
        line_credit = (full_portion * unit_credit
                       + round_half_up_cents(Decimal(overage) * unit_credit * RETURN_OVERAGE_CREDIT_RATIO))
        credit_cents += int(line_credit)
        returned_prior[sku] = prior + int(line["units"])
    return credit_cents


def compute_adherence_rolling_pct(patient):
    """calculations.adherence_rolling_pct — trailing 28-day window, 1 dp half-up."""
    window_start = db.now().date() - timedelta(days=ROLLING_WINDOW_DAYS - 1)
    scheduled = patient["prescription_treatments_per_week"] * 4
    actual = 0
    for l in S["treatment_logs"].values():
        if l["patient_id"] != patient["id"]:
            continue
        d = parse_date(l["treatment_date"])
        if d is not None and window_start <= d <= db.now().date():
            actual += 1
    if scheduled <= 0:
        return 0.0
    pct = Decimal(min(actual, scheduled)) / Decimal(scheduled) * Decimal(100)
    return float(pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_waste_ratio_and_maybe_escalate(patient, activity_month):
    """calculations.waste_ratio — inclusive threshold; latch + ESCALATION review."""
    program = patient_program(patient)
    first, nxt = month_bounds(activity_month)
    waste_units = sum(w["total_units"] for w in S["waste_return_records"].values()
                      if w["patient_id"] == patient["id"]
                      and w["status"] == "VERIFIED" and w["record_type"] == "WASTE"
                      and w["activity_month"] == activity_month)
    delivered_month = 0
    for a in S["delivery_appointments"].values():
        if a["status"] != "DELIVERED":
            continue
        ws = parse_dt(a["window_start"])
        if ws is None or not (first <= ws.date() < nxt):
            continue
        order = get("supply_orders", a["supply_order_id"])
        if order is not None and order["patient_id"] == patient["id"]:
            delivered_month += a.get("delivered_units", 0)
    ratio = 0.0 if delivered_month == 0 else waste_units / delivered_month
    if ratio >= program["waste_ratio_alert_threshold"]:
        patient["waste_alert_active"] = True
        db.touch(patient)
        if not any(r["patient_id"] == patient["id"] and r["status"] == "PENDING"
                   for r in S["clinical_reviews"].values()):
            create_review(patient, "ESCALATION")


# ---------------------------------------------------------------------------
# reviews (system-created) and cadence trigger
# ---------------------------------------------------------------------------

def create_review(patient, due_reason):
    prior = [r for r in S["clinical_reviews"].values()
             if r["patient_id"] == patient["id"]]
    if prior:
        latest_end = max(r["period_end"] for r in prior)
        period_start = (parse_date(latest_end) + timedelta(days=1)).isoformat()
    else:
        period_start = parse_dt(patient["created_at"]).date().isoformat()
    logs = [l for l in S["treatment_logs"].values() if l["patient_id"] == patient["id"]]
    period_end = (max(parse_date(l["treatment_date"]) for l in logs).isoformat()
                  if logs else db.now().date().isoformat())
    review = {
        "patient_id": patient["id"],
        "period_start": period_start,
        "period_end": period_end,
        "due_reason": due_reason,
        "due_at": db.iso(db.now() + timedelta(days=REVIEW_SLA_DAYS)),
        "outcome": None,
        "adherence_rolling_pct": None,
        "signed_off_at": None,
        "status": "PENDING",
    }
    db.stamp_new(review)
    S["clinical_reviews"][review["id"]] = review
    return review


def review_cadence_trigger(patient):
    """After inserting a log: open a CADENCE review when unreviewed count reaches
    the program cadence and no PENDING review exists."""
    program = patient_program(patient)
    unreviewed = sum(1 for l in S["treatment_logs"].values()
                     if l["patient_id"] == patient["id"]
                     and l["status"] in ("SUBMITTED", "FLAGGED"))
    if unreviewed >= program["review_cadence_treatments"]:
        if not any(r["patient_id"] == patient["id"] and r["status"] == "PENDING"
                   for r in S["clinical_reviews"].values()):
            create_review(patient, "CADENCE")


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------

def cancel_order_cascade(order):
    """Cancel an order and its SCHEDULED appointments."""
    order["order_status"] = "CANCELLED"
    db.touch(order)
    for a in S["delivery_appointments"].values():
        if a["supply_order_id"] == order["id"] and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            db.touch(a)


def transition_cascade(patient, permanent):
    """PRD §3.9 activation cascade. Machine -> IN_STOCK (events cancelled);
    open orders + their appointments cancelled; future RESERVED slots cancelled;
    permanent additionally closes the plan."""
    pid = patient["id"]
    # link 1: machine
    machine = assigned_machine(pid)
    if machine is not None:
        machine["status"] = "IN_STOCK"
        machine["assigned_patient_id"] = None
        db.touch(machine)
        # link 2: its SCHEDULED maintenance events
        for e in S["maintenance_events"].values():
            if e["machine_id"] == machine["id"] and e["status"] == "SCHEDULED":
                e["status"] = "CANCELLED"
                db.touch(e)
    # plans
    if permanent:
        for p in S["emergency_backup_plans"].values():
            if p["patient_id"] == pid:
                lazy_eval_plan(p)
                if p["status"] in ("ACTIVE", "EXPIRED"):
                    p["status"] = "CLOSED"
                    db.touch(p)
    # open orders (all four open states) + their SCHEDULED appointments
    for o in S["supply_orders"].values():
        if o["patient_id"] == pid and o["order_status"] in OPEN_ORDER_STATES:
            cancel_order_cascade(o)
    # future RESERVED reservations
    for r in S["backup_slot_reservations"].values():
        if r["patient_id"] == pid and r["status"] == "RESERVED":
            start = parse_dt(r["slot_start"])
            if start is not None and start >= db.now():
                r["status"] = "CANCELLED"
                db.touch(r)


def cap_shrink_cascade(patient):
    """Assessment accept link 3: cancel over-cap open orders (DRAFT/SUBMITTED/
    CHANGES_REQUESTED) and their SCHEDULED appointments."""
    on_hand = compute_on_hand_units(patient["id"])
    cap = patient["storage_cap_units"]
    for o in S["supply_orders"].values():
        if (o["patient_id"] == patient["id"]
                and o["order_status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED")
                and on_hand + o["provisional_total_units"] > cap):
            cancel_order_cascade(o)
