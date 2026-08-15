"""Domain services: credit conversion, budget ledger, waitlist waterfall,
promotion sweep, completion cascade, ops checkpoint, audit reversal."""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import store, now, new_resource, touch, fiscal_year
from serializers import budget_available, section_seats_registered, \
    plan_aligned_decimal

LANE_ORDER = ["BA", "BA15", "MA", "MA15", "MA30", "DOC"]
ANNUAL_CAP_CENTS = 250000
CREDITS_PER_LANE_STEP = Decimal("12.0")


# ---------- credit conversion (calc: credit_conversion) ----------

def credits_for_hours(hours):
    """district_credit = floor(hours*2/3)/10 (1dp, floored per entry);
    state_ceu = round(hours/10, 2) HALF_UP. Returns Decimals."""
    h = Decimal(str(hours))
    tenths = int((h * 2 / 3).to_integral_value(rounding=ROUND_FLOOR))
    district = Decimal(tenths) / Decimal(10)
    ceu = (h / Decimal(10)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return district, ceu


def mint_transcript_entry(employee_id, source_type, source_id, growth_plan_id,
                          clock_hours, counts_toward_lane,
                          negate=False, awarded_at=None):
    district, ceu = credits_for_hours(clock_hours)
    hours_val = clock_hours
    if negate:
        district, ceu = -district, -ceu
        hours_val = -hours_val
    ts = awarded_at if awarded_at is not None else now()
    e = new_resource()
    e.update({
        "employee_id": employee_id,
        "source_type": source_type,
        "source_id": source_id,
        "growth_plan_id": growth_plan_id,
        "fiscal_year": fiscal_year(ts),
        "clock_hours": hours_val,
        "district_credit": district,
        "state_ceu": ceu,
        "counts_toward_lane": counts_toward_lane,
        "status": "AWARDED",
        "awarded_at": ts,
        "reversed_by_entry_id": None,
    })
    store.transcript_entries[e["id"]] = e
    return e


# ---------- budgets (calc: budget_availability) ----------

def find_budget(building_id, fy):
    for b in store.budgets.values():
        if b["building_id"] == building_id and b["fiscal_year"] == fy:
            return b
    return None


def encumber(budget, amount):
    budget["encumbered_cents"] += amount
    touch(budget)


def release_encumbrance(budget, amount):
    budget["encumbered_cents"] -= amount
    touch(budget)


# ---------- growth plans (calc: growth_plan_progress) ----------

def recompute_plan(plan):
    """APPROVED -> FULFILLED when aligned >= target (inclusive);
    FULFILLED -> APPROVED when a reversal drops it below target."""
    aligned = plan_aligned_decimal(plan)
    target = Decimal(str(plan["target_credits"]))
    if plan["status"] == "APPROVED" and aligned >= target:
        plan["status"] = "FULFILLED"
        touch(plan)
    elif plan["status"] == "FULFILLED" and aligned < target:
        plan["status"] = "APPROVED"
        touch(plan)


# ---------- compliance ----------

def advance_assignments_on_registration(teacher_id, course_id):
    """ASSIGNED assignments of this teacher for this course -> IN_PROGRESS."""
    for a in store.assignments.values():
        if (a["employee_id"] == teacher_id and a["course_id"] == course_id
                and a["status"] == "ASSIGNED"):
            a["status"] = "IN_PROGRESS"
            touch(a)


def add_months(dt, months):
    idx = (dt.year * 12 + (dt.month - 1)) + months
    y, m0 = divmod(idx, 12)
    m = m0 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def satisfy_assignments(teacher_id, course_id, course, completed_at):
    for a in list(store.assignments.values()):
        if (a["employee_id"] == teacher_id and a["course_id"] == course_id
                and a["status"] in ("ASSIGNED", "IN_PROGRESS", "OVERDUE",
                                    "ESCALATED")):
            a["status"] = "SATISFIED"
            a["satisfied_at"] = completed_at
            touch(a)
            if course.get("recurrence_months"):
                spawn = new_resource()
                spawn.update({
                    "employee_id": a["employee_id"],
                    "course_id": a["course_id"],
                    "due_date": add_months(completed_at,
                                           course["recurrence_months"]),
                    "status": "ASSIGNED",
                    "assigned_by_user_id": a["assigned_by_user_id"],
                    "satisfied_at": None,
                    "extension_count": 0,
                })
                store.assignments[spawn["id"]] = spawn


# ---------- seats & waitlist (calc: seat_and_waitlist_allocation) ----------

def seats_open(section):
    return section["seat_capacity"] - section_seats_registered(section)


def next_waitlist_seq(section_id):
    n = store.waitlist_counters.get(section_id, 0) + 1
    store.waitlist_counters[section_id] = n
    return n


def _promotion_budget_ok(teacher_id, section):
    fee = section["fee_cents"]
    if fee <= 0:
        return True, None
    emp = store.employees.get(teacher_id)
    budget = find_budget(emp["primary_building_id"],
                         fiscal_year(section["starts_at"])) if emp else None
    if budget is None or budget["status"] != "OPEN":
        return False, None
    if budget_available(budget) < fee:
        return False, None
    return True, budget


def promotion_sweep(section, promoted_out=None):
    """WAITLISTED candidates in waitlist_seq ASC; budget-failing candidates
    are skipped (stay WAITLISTED); promote until no seat is open."""
    if section["status"] != "PUBLISHED":
        return
    candidates = [r for r in store.registrations.values()
                  if r["section_id"] == section["id"]
                  and r["status"] == "WAITLISTED"]
    candidates.sort(key=lambda r: (r["waitlist_seq"] or 0, r["_seq"]))
    for cand in candidates:
        if seats_open(section) < 1:
            break
        ok, budget = _promotion_budget_ok(cand["teacher_id"], section)
        if not ok:
            continue
        fee = section["fee_cents"]
        cand["status"] = "REGISTERED"
        cand["waitlist_seq"] = None
        if fee > 0 and budget is not None:
            encumber(budget, fee)
            cand["encumbered_cents"] = fee
        touch(cand)
        advance_assignments_on_registration(cand["teacher_id"],
                                            section["course_id"])
        if promoted_out is not None:
            promoted_out.append(cand["id"])


def drop_registration(reg):
    """REGISTERED -> DROPPED: release encumbrance, then promotion sweep."""
    reg["status"] = "DROPPED"
    if reg["encumbered_cents"] > 0:
        emp = store.employees.get(reg["teacher_id"])
        section = store.sections.get(reg["section_id"])
        if emp is not None and section is not None:
            budget = find_budget(emp["primary_building_id"],
                                 fiscal_year(section["starts_at"]))
            if budget is not None:
                release_encumbrance(budget, reg["encumbered_cents"])
        reg["encumbered_cents"] = 0
    touch(reg)
    section = store.sections.get(reg["section_id"])
    if section is not None:
        promotion_sweep(section)


# ---------- completion cascade (PRD 3.5) ----------

def complete_registration(reg):
    section = store.sections[reg["section_id"]]
    course = store.courses[section["course_id"]]
    emp = store.employees[reg["teacher_id"]]
    ts = now()
    reg["status"] = "COMPLETED"
    reg["completed_at"] = ts
    touch(reg)
    # 1. TranscriptEntry
    entry = mint_transcript_entry(
        employee_id=emp["id"],
        source_type="COURSE_COMPLETION",
        source_id=reg["id"],
        growth_plan_id=reg["growth_plan_id"],
        clock_hours=course["clock_hours"],
        counts_toward_lane=(course["compliance_tag"] is None),
        awarded_at=ts,
    )
    # 2. settle money: encumbered -> spent
    if reg["encumbered_cents"] > 0:
        budget = find_budget(emp["primary_building_id"],
                             fiscal_year(section["starts_at"]))
        if budget is not None:
            budget["encumbered_cents"] -= reg["encumbered_cents"]
            budget["spent_cents"] += reg["encumbered_cents"]
            touch(budget)
        reg["encumbered_cents"] = 0
    # 3. lane_credit_balance recomputes on read (no employee version bump)
    # 4. growth plan progress
    if reg["growth_plan_id"]:
        plan = store.growth_plans.get(reg["growth_plan_id"])
        if plan is not None and plan["status"] in ("APPROVED", "FULFILLED"):
            recompute_plan(plan)
    # 5. compliance satisfaction + recurrence
    satisfy_assignments(emp["id"], course["id"], course, ts)
    return entry


# ---------- workshop completion ----------

def complete_workshop(workshop):
    ts = now()
    workshop["status"] = "ATTENDED"
    touch(workshop)
    entry = mint_transcript_entry(
        employee_id=workshop["teacher_id"],
        source_type="EXTERNAL_WORKSHOP",
        source_id=workshop["id"],
        growth_plan_id=workshop["growth_plan_id"],
        clock_hours=workshop["actual_hours"],
        counts_toward_lane=True,
        awarded_at=ts,
    )
    if workshop["growth_plan_id"]:
        plan = store.growth_plans.get(workshop["growth_plan_id"])
        if plan is not None and plan["status"] in ("APPROVED", "FULFILLED"):
            recompute_plan(plan)
    return entry


# ---------- ops checkpoint (calc: ops_run_sweep, pinned 7-step order) ----------

def ops_run():
    ts = now()
    out = {
        "transitioned_section_ids": [],
        "promoted_registration_ids": [],
        "expired_registration_ids": [],
        "no_show_registration_ids": [],
        "expired_workshop_ids": [],
        "transitioned_assignment_ids": [],
    }
    # 1. Section windows (a section may advance multiple steps in one run)
    for s in sorted(store.sections.values(), key=lambda o: o["_seq"]):
        moved = False
        if s["status"] == "PUBLISHED" and ts > s["registration_closes_at"]:
            s["status"] = "REGISTRATION_CLOSED"
            touch(s)
            moved = True
        if s["status"] == "REGISTRATION_CLOSED" and ts >= s["starts_at"]:
            s["status"] = "IN_SESSION"
            touch(s)
            moved = True
        if s["status"] == "IN_SESSION" and ts > s["ends_at"]:
            s["status"] = "COMPLETED"
            touch(s)
            moved = True
        if moved:
            out["transitioned_section_ids"].append(s["id"])
    # 2. Waitlist promotion for sections still PUBLISHED
    for s in sorted(store.sections.values(), key=lambda o: o["_seq"]):
        if s["status"] == "PUBLISHED":
            promotion_sweep(s, out["promoted_registration_ids"])
    # 3. Waitlist expiry
    for r in sorted(store.registrations.values(), key=lambda o: o["_seq"]):
        if r["status"] != "WAITLISTED":
            continue
        s = store.sections.get(r["section_id"])
        if s is not None and s["status"] in ("IN_SESSION", "COMPLETED",
                                             "CANCELED"):
            r["status"] = "EXPIRED"
            touch(r)
            out["expired_registration_ids"].append(r["id"])
    # 4. NO_SHOW sweep
    for r in sorted(store.registrations.values(), key=lambda o: o["_seq"]):
        if r["status"] != "REGISTERED":
            continue
        s = store.sections.get(r["section_id"])
        if s is None or s["status"] != "COMPLETED":
            continue
        if r["attendance_status"] == "VERIFIED":
            continue
        r["status"] = "NO_SHOW"
        if r["attendance_status"] == "PENDING":
            r["attendance_status"] = "ABSENT"
        if r["encumbered_cents"] > 0:
            emp = store.employees.get(r["teacher_id"])
            if emp is not None:
                budget = find_budget(emp["primary_building_id"],
                                     fiscal_year(s["starts_at"]))
                if budget is not None:
                    release_encumbrance(budget, r["encumbered_cents"])
            r["encumbered_cents"] = 0
        touch(r)
        out["no_show_registration_ids"].append(r["id"])
    # 5. Workshop expiry (APPROVED, now > ends_at + 30d)
    for w in sorted(store.workshops.values(), key=lambda o: o["_seq"]):
        if w["status"] == "APPROVED" and ts > w["ends_at"] + timedelta(days=30):
            w["status"] = "EXPIRED"
            touch(w)
            budget = find_budget(w["building_id"], fiscal_year(w["starts_at"]))
            if budget is not None:
                release_encumbrance(budget, w["est_cost_cents"])
            out["expired_workshop_ids"].append(w["id"])
    # 6. Compliance deadlines (a run may move ASSIGNED -> OVERDUE -> ESCALATED)
    for a in sorted(store.assignments.values(), key=lambda o: o["_seq"]):
        moved = False
        if a["status"] in ("ASSIGNED", "IN_PROGRESS") and ts > a["due_date"]:
            a["status"] = "OVERDUE"
            touch(a)
            moved = True
        if a["status"] == "OVERDUE" and ts > a["due_date"] + timedelta(days=30):
            a["status"] = "ESCALATED"
            touch(a)
            emp = store.employees.get(a["employee_id"])
            if emp is not None:
                touch(emp)  # standing recompute -> NON_COMPLIANT
            moved = True
        if moved:
            out["transitioned_assignment_ids"].append(a["id"])
    # 7. Standing recompute: compliance_standing is derived on read, so all
    #    employees observe post-step-6 state immediately.
    return out
