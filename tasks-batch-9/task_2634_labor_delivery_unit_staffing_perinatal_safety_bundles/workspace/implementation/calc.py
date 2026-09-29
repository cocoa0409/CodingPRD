"""Derivations and calculations (PRD 3.2, 3.3, 3.5-3.9).

Nothing here is ever supplied by a caller: every figure in this module is
derived from stored rows on each mutation that can move it.
"""

import clock
import const
import rev
import store
from clock import one_dp, two_dp, four_dp, whole_minutes_between
from store import S, sort_rows


# ---------------------------------------------------------------- accessors

def rows(kind, **filters):
    out = []
    for rec in getattr(S, kind).values():
        ok = True
        for field, value in filters.items():
            if rec.get(field) != value:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def active_care_on_encounter(encounter_id):
    return rows("care", encounter_id=encounter_id, status="ACTIVE")


def active_care_on_shift(shift_id):
    return rows("care", shift_assignment_id=shift_id, status="ACTIVE")


def live_activations(encounter_id):
    """Activations that still count: CLOSED and RESCINDED are excluded."""
    return [a for a in rows("activations", encounter_id=encounter_id)
            if a["status"] in const.ACTIVATION_NON_TERMINAL]


def live_cesareans(encounter_id):
    """Cesarean events that still count: CLOSED / ABORTED_TO_VAGINAL excluded."""
    return [c for c in rows("cesareans", encounter_id=encounter_id)
            if c["status"] in const.CESAREAN_NON_TERMINAL]


def latest_assessment(encounter_id):
    """Greatest assessed_at, later created_at winning a tie."""
    found = rows("assessments", encounter_id=encounter_id)
    if not found:
        return None
    return sort_rows(found, [("assessed_at", "desc"), ("created_at", "desc")])[0]


def items_of(activation_id):
    return sort_rows(rows("items", activation_id=activation_id),
                     [("step_sequence", "asc")])


def unit_of_encounter(enc):
    return S.units.get(enc["unit_id"])


def encounters_of_unit(unit_id):
    return rows("encounters", unit_id=unit_id)


def active_shifts_of_unit(unit_id):
    return rows("shifts", unit_id=unit_id, status="ACTIVE")


def on_the_case(staff_id, enc):
    """PRD 3.6/3.7 'on the case': an ACTIVE care assignment on the encounter,
    or an ACTIVE roster entry on the unit in the CHARGE or OR_STANDBY slot."""
    for row in active_care_on_encounter(enc["id"]):
        if row["staff_id"] == staff_id:
            return True
    for shift in active_shifts_of_unit(enc["unit_id"]):
        if shift["staff_id"] == staff_id and shift["role_slot"] in ("CHARGE", "OR_STANDBY"):
            return True
    return False


# ------------------------------------------------- 3.2 staff capacity units

def staff_capacity_units(staff, role_slot, shift=None):
    """PRD 3.2: nested min/max, not a linear sum. 1dp, halves away from zero."""
    if staff is None:
        return 0.0
    if staff["employment_status"] != "ACTIVE":
        return 0.0
    expires = staff.get("credential_expires_at")
    if expires is None or expires <= clock.now():
        return 0.0
    cert = staff["fetal_monitoring_cert_level"]
    if cert == "EXPIRED":
        return 0.0
    if role_slot is None:
        # capacity is keyed by the slot a member is rostered into; no slot, no capacity
        return 0.0
    raw = min(const.BASE_CAPACITY_UNITS[role_slot], const.CERT_CAP_UNITS[cert])
    admin = const.CHARGE_ADMIN_OFFSET_UNITS if role_slot == "CHARGE" else 0.0
    focus = 0.0
    if shift is not None:
        for row in active_care_on_shift(shift["id"]):
            enc = S.encounters.get(row["encounter_id"])
            if enc is not None and enc.get("acuity_tier") == "TIER_IV":
                focus = const.TIER_IV_FOCUS_PENALTY_UNITS
                break
    return one_dp(max(0.0, raw - admin - focus))


def current_shift_of(staff_id):
    """The ACTIVE roster entry a member currently occupies, latest start first."""
    found = rows("shifts", staff_id=staff_id, status="ACTIVE")
    if not found:
        return None
    return sort_rows(found, [("shift_start_utc", "desc"), ("created_at", "desc")])[0]


def recompute_staff_capacity(staff):
    if staff is None:
        return
    shift = current_shift_of(staff["id"])
    slot = shift["role_slot"] if shift is not None else None
    value = staff_capacity_units(staff, slot, shift)
    if staff.get("capacity_units") != value:
        staff["capacity_units"] = value
        rev.touch(staff)


# ------------------------------------------------------- 3.3 coverage pricing

def care_debit(coverage_mode, shift, enc):
    if coverage_mode == "ONE_TO_ONE":
        debit = shift.get("capacity_units_effective") or 0.0
    else:
        debit = (const.ACUITY_UNITS[enc["acuity_tier"]]
                 * const.PHASE_MULTIPLIER[enc["labor_phase"]])
    return one_dp(debit)


def derive_acuity(enc):
    """PRD 3.3 step 1: highest firing clause wins; the first clause inside a
    tier names the reason. Returns (tier, reason)."""
    best = 0
    reason = "BASELINE"

    def fire(index, code):
        nonlocal best, reason
        if index > best:
            best = index
            reason = code

    if (enc["gestational_age_weeks"] < 37 or enc["fetus_count"] > 1
            or enc["presentation"] != "VERTEX" or enc["prior_cesarean"] is True):
        fire(1, "GESTATION_OR_PRESENTATION")
    if enc["labor_phase"] in ("ACTIVE_FIRST_STAGE", "THIRD_STAGE_DELIVERED"):
        fire(1, "PHASE_FLOOR")

    if enc["labor_phase"] == "SECOND_STAGE":
        fire(2, "PHASE_FLOOR")
    if any(a["status"] == "STAGE_1_IN_PROGRESS" for a in live_activations(enc["id"])):
        fire(2, "STAGE_1_BUNDLE")
    latest = latest_assessment(enc["id"])
    if (latest is not None and latest["category"] == "CATEGORY_II"
            and latest["escalation_status"] in const.CAT_II_TIER_III_STATUSES):
        fire(2, "CATEGORY_II_UNRESOLVED")

    if any(a["status"] in ("STAGE_2_ESCALATED", "STAGE_3_MASSIVE_TRANSFUSION")
           for a in live_activations(enc["id"])):
        fire(3, "STAGE_2_OR_3_BUNDLE")
    if enc.get("magnesium_infusion_active") is True:
        fire(3, "MAGNESIUM")
    if (latest is not None and latest["category"] == "CATEGORY_III"
            and latest["escalation_status"] != "RESOLVED"):
        fire(3, "CATEGORY_III_UNRESOLVED")
    if any(c["status"] in const.CESAREAN_IN_THEATRE for c in live_cesareans(enc["id"])):
        fire(3, "CESAREAN_IN_PROGRESS")

    return const.TIERS[best], reason


def derive_requirements(enc):
    """PRD 3.3 steps 1-3. Returns (tier, tier_reason, one_to_one, required)."""
    tier, reason = derive_acuity(enc)
    one_to_one = (enc["labor_phase"] == "SECOND_STAGE" or tier == "TIER_IV"
                  or enc.get("magnesium_infusion_active") is True)
    if enc["labor_phase"] in const.TERMINAL_PHASES:
        required = 0.0
    elif one_to_one:
        required = const.ONE_TO_ONE_REQUIRED_UNITS
    else:
        required = (const.ACUITY_UNITS[tier]
                    * const.PHASE_MULTIPLIER[enc["labor_phase"]])
    return tier, reason, one_to_one, one_dp(required)


def recompute_assigned(enc):
    total = 0.0
    for row in active_care_on_encounter(enc["id"]):
        total += row["acuity_units_consumed"] or 0.0
    total = one_dp(total)
    if enc.get("assigned_coverage_units") != total:
        enc["assigned_coverage_units"] = total
        rev.touch(enc)


def shift_load_from_rows(shift):
    total = 0.0
    for row in active_care_on_shift(shift["id"]):
        total += row["acuity_units_consumed"] or 0.0
    return one_dp(total)


def move_load(shift, credit=0.0, debit=0.0):
    """Ledger movement with the pinned order: credit the old value first,
    debit the new value second (PRD 3.3)."""
    if shift is None:
        return
    current = shift.get("assigned_acuity_load_units") or 0.0
    if credit:
        current = one_dp(current - credit)
    if debit:
        current = one_dp(current + debit)
    shift["assigned_acuity_load_units"] = current
    rev.touch(shift)


def reprice_active_care(enc, affected_shifts=None):
    """Re-price every ACTIVE row on the encounter in place."""
    for row in sort_rows(active_care_on_encounter(enc["id"]), [("created_at", "asc")]):
        shift = S.shifts.get(row["shift_assignment_id"])
        if shift is None:
            continue
        old = row["acuity_units_consumed"] or 0.0
        new = care_debit(row["coverage_mode"], shift, enc)
        if new == old:
            continue
        move_load(shift, credit=old, debit=new)
        row["acuity_units_consumed"] = new
        rev.touch(row)
        if affected_shifts is not None:
            affected_shifts.add(shift["id"])
    recompute_assigned(enc)


def shift_over_capacity(shift):
    cap = shift.get("capacity_units_effective")
    if cap is None:
        return False
    return (shift.get("assigned_acuity_load_units") or 0.0) > cap


def recompute_staffing_state(enc, forced=None):
    """The coverage axis (PRD 3.3). RELEASED is terminal."""
    if enc.get("staffing_state") == "RELEASED":
        return
    if forced is not None:
        if enc["staffing_state"] != forced:
            enc["staffing_state"] = forced
            rev.touch(enc)
        return
    active = active_care_on_encounter(enc["id"])
    if not active:
        if enc["staffing_state"] not in ("UNASSIGNED",):
            enc["staffing_state"] = "COVERAGE_BREACH"
            rev.touch(enc)
        return
    one_to_one_rows = [r for r in active if r["coverage_mode"] == "ONE_TO_ONE"]
    breached = (enc.get("assigned_coverage_units") or 0.0) < (enc.get("required_coverage_units") or 0.0)
    if not breached and enc.get("one_to_one_required") and not one_to_one_rows:
        breached = True
    if not breached:
        for row in active:
            if shift_over_capacity(S.shifts.get(row["shift_assignment_id"]) or {}):
                breached = True
                break
    if breached:
        # UNASSIGNED never falls to COVERAGE_BREACH: a partial first row that
        # leaves the encounter short succeeds and the axis simply stays put.
        target = "UNASSIGNED" if enc["staffing_state"] == "UNASSIGNED" else "COVERAGE_BREACH"
    elif one_to_one_rows:
        target = "ONE_TO_ONE_COVERED"
    else:
        target = "RATIO_COVERED"
    if enc["staffing_state"] != target:
        enc["staffing_state"] = target
        rev.touch(enc)


# ------------------------------------------------- 3.8 cesarean readiness

def current_drill(unit_id):
    found = [d for d in rows("drills", unit_id=unit_id)
             if d["status"] == "VALIDATED" and d.get("expires_at") is not None
             and d["expires_at"] > clock.now()]
    if not found:
        return None
    return sort_rows(found, [("validated_at", "desc"), ("created_at", "desc")])[0]


def rolling_events(unit_id):
    found = []
    for event in S.cesareans.values():
        enc = S.encounters.get(event["encounter_id"])
        if enc is None or enc["unit_id"] != unit_id:
            continue
        if event.get("decision_to_incision_minutes") is None:
            continue
        if event["status"] not in const.CESAREAN_MEASURED:
            continue
        found.append(event)
    found = sort_rows(found, [("incision_at", "desc"), ("created_at", "desc")])
    return found[:const.ROLLING_EVENT_WINDOW]


def or_standby_staffed(unit_id):
    for shift in active_shifts_of_unit(unit_id):
        if shift["role_slot"] != "OR_STANDBY":
            continue
        staff = S.staff.get(shift["staff_id"])
        if staff is not None and staff.get("drill_currency_state") == "CURRENT":
            return True
    return False


def readiness_view(unit):
    """Returns the whole derivation (PRD 3.8 last paragraph)."""
    drill = current_drill(unit["id"])
    events = rolling_events(unit["id"])
    mean = None
    if events:
        total = sum(e["decision_to_incision_minutes"] for e in events)
        mean = two_dp(total / float(len(events)))
    standby = or_standby_staffed(unit["id"])
    if drill is None:
        state, reason = "NOT_READY", "NO_CURRENT_DRILL"
    elif mean is not None and mean > const.MEAN_D2I_DEGRADED_CEILING:
        state, reason = "NOT_READY", "MEAN_D2I_ABOVE_DEGRADED_CEILING"
    elif not standby:
        state, reason = "DEGRADED", "NO_OR_STANDBY"
    elif mean is not None and mean > const.MEAN_D2I_READY_CEILING:
        state, reason = "DEGRADED", "MEAN_D2I_ABOVE_READY_CEILING"
    else:
        state, reason = "READY", "READY"
    return {
        "unit_id": unit["id"],
        "cesarean_readiness_state": state,
        "readiness_reason": reason,
        "current_drill_id": drill["id"] if drill is not None else None,
        "current_drill_expires_at": drill["expires_at"] if drill is not None else None,
        "mean_d2i_minutes": mean,
        "rolling_event_ids": [e["id"] for e in events],
        "or_standby_staffed": standby,
    }


# ------------------------------------------------------ 3.3 unit posture

def encounter_deficit(enc):
    return one_dp(max(0.0, (enc.get("required_coverage_units") or 0.0)
                      - (enc.get("assigned_coverage_units") or 0.0)))


def live_encounters(unit_id):
    return [e for e in encounters_of_unit(unit_id) if e["labor_phase"] in const.LIVE_PHASES]


def available_ldr_beds(unit_id):
    return [b for b in rows("beds", unit_id=unit_id)
            if b["bed_type"] == "LDR" and b["status"] == "AVAILABLE"]


def posture_view(unit):
    """First matching branch of four decides; no later branch is consulted."""
    deficit = 0.0
    for enc in live_encounters(unit["id"]):
        deficit += encounter_deficit(enc)
    deficit = one_dp(deficit)
    ldr_free = len(available_ldr_beds(unit["id"]))
    activations = [a for a in rows("activations", unit_id=unit["id"])]
    stage3 = any(a["status"] == "STAGE_3_MASSIVE_TRANSFUSION" for a in activations)
    stage2 = any(a["status"] == "STAGE_2_ESCALATED" for a in activations)
    breached = any(e["staffing_state"] == "COVERAGE_BREACH"
                   for e in encounters_of_unit(unit["id"]))

    if deficit >= const.DIVERT_DEFICIT_UNITS:
        posture, reason = "DIVERT", "DIVERT_DEFICIT"
    elif ldr_free == 0:
        posture, reason = "DIVERT", "NO_AVAILABLE_LDR_BED"
    elif stage3:
        posture, reason = "DIVERT", "STAGE_3_BUNDLE"
    elif deficit >= const.FREEZE_DEFICIT_UNITS:
        posture, reason = "INDUCTION_FROZEN", "FREEZE_DEFICIT"
    elif (unit.get("escalation_breach_count") or 0) >= const.ESCALATION_BREACH_FREEZE:
        posture, reason = "INDUCTION_FROZEN", "ESCALATION_BREACH"
    elif (unit.get("bundle_breach_count") or 0) >= const.BUNDLE_BREACH_FREEZE:
        posture, reason = "INDUCTION_FROZEN", "BUNDLE_BREACH"
    elif unit.get("cesarean_readiness_state") == "NOT_READY":
        posture, reason = "INDUCTION_FROZEN", "READINESS_NOT_READY"
    elif deficit > 0.0 and stage2:
        posture, reason = "INDUCTION_FROZEN", "STAGE_2_WITH_DEFICIT"
    elif deficit > 0.0:
        posture, reason = "RATIO_STRAINED", "DEFICIT_POSITIVE"
    elif breached:
        posture, reason = "RATIO_STRAINED", "BREACHED_ENCOUNTER"
    else:
        posture, reason = "OPEN", "NONE"
    return deficit, posture, reason


def rederive_unit(unit, bump=True):
    """Readiness first (posture reads it), then posture, then — only after the
    posture is settled — the turnover buffer, which is never fed back."""
    if unit is None:
        return None, None
    view = readiness_view(unit)
    unit["cesarean_readiness_state"] = view["cesarean_readiness_state"]
    unit["readiness_reason"] = view["readiness_reason"]
    unit["current_drill_id"] = view["current_drill_id"]
    unit["current_drill_expires_at"] = view["current_drill_expires_at"]
    unit["mean_d2i_minutes"] = view["mean_d2i_minutes"]
    deficit, posture, reason = posture_view(unit)
    previous = unit.get("staffing_posture")
    unit["coverage_deficit_units"] = deficit
    unit["staffing_posture"] = posture
    unit["_posture_reason"] = reason
    unit["turnover_buffer_minutes"] = (const.TURNOVER_BUFFER_OPEN if posture == "OPEN"
                                       else const.TURNOVER_BUFFER_STRAINED)
    if bump:
        rev.touch(unit)
    return previous, posture


def derive_review_required(enc):
    for review in rows("reviews", encounter_id=enc["id"]):
        if review["status"] != "CLOSED":
            return True
    for event in rows("cesareans", encounter_id=enc["id"]):
        if event["status"] == "REVIEW_PENDING":
            return True
    return False


def rederive_encounter(enc, forced_state=None, bump_unit=True, bump_self=True):
    """The whole 3.3 cascade: requirements -> re-pricing -> sibling breach ->
    staff capacity -> unit posture."""
    if enc is None:
        return
    unit = S.units.get(enc["unit_id"])
    tier, reason, one_to_one, required = derive_requirements(enc)
    review = derive_review_required(enc)
    changed = False
    for field, value in (("acuity_tier", tier), ("one_to_one_required", one_to_one),
                         ("required_coverage_units", required),
                         ("review_required", review)):
        if enc.get(field) != value:
            enc[field] = value
            changed = True
    enc["_acuity_tier_reason"] = reason
    if changed and bump_self:
        # `version` starts at 1 when the record is created, so the derivation
        # that runs as part of a creation is not a mutation of its own subject.
        rev.touch(enc)

    affected = set()
    reprice_active_care(enc, affected)
    for row in active_care_on_encounter(enc["id"]):
        affected.add(row["shift_assignment_id"])
    for shift_id in affected:
        shift = S.shifts.get(shift_id)
        if shift is not None:
            recompute_staff_capacity(S.staff.get(shift["staff_id"]))

    recompute_staffing_state(enc, forced_state)
    for shift_id in affected:
        for row in sort_rows(active_care_on_shift(shift_id), [("created_at", "asc")]):
            other = S.encounters.get(row["encounter_id"])
            if other is not None and other["id"] != enc["id"]:
                recompute_staffing_state(other)
    rederive_unit(unit, bump=bump_unit)


# ------------------------------------------------- 3.5 induction bed minutes

def booking_priority_class(booking):
    code = booking["indication_code"]
    if code in ("PREECLAMPSIA", "POST_DATES_41W", "FGR", "PROM"):
        result = "MEDICALLY_INDICATED"
    elif (code in ("GDM_CONTROLLED", "ELECTIVE_NO_INDICATION")
          and booking["gestational_age_weeks"] >= 39):
        result = "ELECTIVE_39_WEEK"
    else:
        result = "PATIENT_REQUEST"
    if (booking.get("bump_count") or 0) >= const.BUMP_ESCALATION_LIMIT:
        result = "MEDICALLY_INDICATED"
    return result


def booking_day(booking):
    return clock.day_of(booking["requested_start_utc"])


def ledger_move(unit, map_name, day, minutes):
    """Bed-minute ledgers move by the frozen quantum, never a recomputed one."""
    ledger = unit.setdefault(map_name, {})
    value = (ledger.get(day) or 0) + minutes
    if value:
        ledger[day] = value
    else:
        ledger.pop(day, None)


def day_load(unit, day):
    committed = (unit.get("committed_bed_minutes_by_day") or {}).get(day) or 0
    held = (unit.get("held_bed_minutes_by_day") or {}).get(day) or 0
    return committed + held


def release_booking_minutes(unit, booking):
    """Credit back exactly the frozen projection from whichever ledger holds it."""
    minutes = booking.get("projected_occupancy_minutes")
    if not minutes:
        return
    day = booking_day(booking)
    if booking["status"] == "CAPACITY_HELD":
        ledger_move(unit, "held_bed_minutes_by_day", day, -minutes)
    elif booking["status"] in ("CONFIRMED", "ADMITTED"):
        ledger_move(unit, "committed_bed_minutes_by_day", day, -minutes)


def release_booking_bed(booking):
    bed = S.beds.get(booking.get("bed_id") or "")
    if bed is None:
        return None
    if bed["status"] == "HELD":
        bed["status"] = "AVAILABLE"
    bed["held_booking_id"] = None
    rev.touch(bed)
    return bed


def bed_reservation_conflict(bed_id, start, minutes, exclude_id=None):
    """PRD 2.7: closed on both ends, so touching endpoints DO collide."""
    new_end = clock.plus_minutes(start, minutes)
    for other in S.bookings.values():
        if other.get("bed_id") != bed_id or other["id"] == exclude_id:
            continue
        if other["status"] not in ("CAPACITY_HELD", "CONFIRMED", "ADMITTED"):
            continue
        frozen = other.get("projected_occupancy_minutes")
        if frozen is None or other.get("requested_start_utc") is None:
            continue
        other_start = other["requested_start_utc"]
        other_end = clock.plus_minutes(other_start, frozen)
        if start <= other_end and other_start <= new_end:
            return True
    return False


def bump_booking(booking, unit):
    """The compensating exit shared by every automatic cascade."""
    release_booking_minutes(unit, booking)
    release_booking_bed(booking)
    booking["status"] = "BUMPED"
    booking["bump_count"] = (booking.get("bump_count") or 0) + 1
    booking["bed_id"] = None
    booking["hold_expires_at"] = None
    rev.touch(booking)
    return booking


def cascade_bump(unit, statuses, classes=("ELECTIVE_39_WEEK", "PATIENT_REQUEST")):
    """PRD 3.5: PATIENT_REQUEST first, then requested_start_utc DESC, created_at DESC."""
    found = [b for b in rows("bookings", unit_id=unit["id"])
             if b["status"] in statuses and b["priority_class"] in classes]
    found.sort(key=lambda b: (-const.PRIORITY_RANK[b["priority_class"]],
                              -b["requested_start_utc"].timestamp(),
                              -b["created_at"].timestamp(), -b["_seq"]))
    for booking in found:
        bump_booking(booking, unit)
    return found


def promotion_order(bookings):
    """The sweep's own order: rank ASC, requested_start_utc ASC, created_at ASC."""
    return sorted(bookings, key=lambda b: (const.PRIORITY_RANK[b["priority_class"]],
                                           b["requested_start_utc"].timestamp(),
                                           b["created_at"].timestamp(), b["_seq"]))


# ---------------------------------------------------- 3.6 bundle checklists

def cumulative_minutes(bundle_type, sequence):
    total = 0
    for seq, _code, _gate, minutes in const.CHECKLIST_TEMPLATE[bundle_type]:
        if seq <= sequence:
            total += minutes
    return total


def recompute_sequence_due(activation, sequence):
    """Advisory recomputation of one item's sequence-anchored date."""
    items = items_of(activation["id"])
    target = None
    predecessor = None
    for item in items:
        if item["step_sequence"] == sequence:
            target = item
        if item["step_sequence"] == sequence - 1:
            predecessor = item
    if target is None:
        return
    if sequence == 1:
        due = clock.plus_minutes(activation["activated_at"], target["required_within_minutes"])
    elif predecessor is not None and predecessor.get("completed_at") is not None:
        due = clock.plus_minutes(predecessor["completed_at"], target["required_within_minutes"])
    else:
        due = None
    if target.get("due_at_sequence_anchored") != due:
        target["due_at_sequence_anchored"] = due
        rev.touch(target)


def score_run(activation, anchor_field):
    """One procedure run twice; only the governing due date differs."""
    applicable = [i for i in items_of(activation["id"])
                  if i["status"] != "NOT_APPLICABLE"]
    per_item = {}
    if not applicable:
        return None, 0, 0, 0, per_item
    on_time = 0
    late = 0
    missed = 0
    for item in applicable:
        due = item.get(anchor_field)
        done = item.get("completed_at")
        flag = None
        if done is not None and due is not None:
            if done <= due:
                on_time += 1
                flag = True
            else:
                late += 1
                flag = False
        if item["status"] == "MISSED":
            missed += 1
        per_item[item["id"]] = flag
    raw = 100.0 * (on_time + 0.5 * late) / len(applicable) - 10.0 * missed
    clamped = min(100.0, max(0.0, raw))
    return two_dp(clamped), on_time, late, missed, per_item


def timeliness_scores(activation):
    """Authoritative run drives the stored counters; advisory run gates nothing."""
    auth, on_time, late, missed, _ = score_run(activation, "due_at_activation_anchored")
    advisory, _a, _b, _c, _d = score_run(activation, "due_at_sequence_anchored")
    return auth, advisory, on_time, late, missed


# ------------------------------------------------- 3.9 support occupancy

def checked_in_count(encounter_id):
    return len(rows("passes", encounter_id=encounter_id, status="CHECKED_IN"))


def support_allowance(enc):
    """PRD 3.9: derived, never stored as a limit."""
    unit = S.units.get(enc["unit_id"])
    posture = unit.get("staffing_posture") if unit is not None else None
    staff_in_room = len(active_care_on_encounter(enc["id"]))
    base = const.SUPPORT_BASE_ALLOWANCE[enc["labor_phase"]]
    bonus = 0
    if posture != "DIVERT":
        for row in rows("passes", encounter_id=enc["id"]):
            if (row["credential_type"] == "DOULA_CERTIFIED"
                    and row["status"] in const.PASS_PRESENT
                    and row.get("doula_certification_expires_at") is not None
                    and row["doula_certification_expires_at"] > clock.now()):
                bonus = 1
                break
    allowance = min(base + bonus, const.MAX_ROOM_OCCUPANCY - staff_in_room)
    if posture in ("INDUCTION_FROZEN", "DIVERT") and allowance > 1:
        allowance = 1
    for event in rows("cesareans", encounter_id=enc["id"]):
        if event["status"] in const.CESAREAN_OR_ACTIVE:
            allowance = 1
            break
    if allowance < 0:
        allowance = 0
    return allowance


# ------------------------------------------------- 3.9 quality measure rates

def _cohort(unit_id, anchor_field, start, end):
    found = []
    for enc in encounters_of_unit(unit_id):
        if enc.get("delivery_mode") is None:
            continue
        instant = enc.get(anchor_field)
        if instant is None:
            continue
        if start <= instant < end:
            found.append(enc)
    return found


def _rate(numerator, denominator):
    if denominator == 0:
        return None
    return four_dp(100.0 * numerator / denominator)


def delivery_cohort(snap):
    return _cohort(snap["unit_id"], "delivery_recorded_at",
                   snap["period_start_utc"], snap["period_end_utc"])


def compute_snapshot(snap):
    """Computed twice on the same call: authoritative + shadow (PRD 3.9)."""
    cohort = delivery_cohort(snap)
    ntsv_den = [e for e in cohort if e.get("is_ntsv") is True]
    ntsv_num = [e for e in ntsv_den if e["delivery_mode"] == "CESAREAN_PRIMARY"]
    epi_den = [e for e in cohort if e["delivery_mode"] in const.VAGINAL_MODES]
    epi_num = [e for e in epi_den if e.get("episiotomy_performed") is True]
    snap["ntsv_cesarean_numerator"] = len(ntsv_num)
    snap["ntsv_cesarean_denominator"] = len(ntsv_den)
    snap["episiotomy_numerator"] = len(epi_num)
    snap["episiotomy_denominator"] = len(epi_den)
    ntsv_rate = _rate(len(ntsv_num), len(ntsv_den))
    epi_rate = _rate(len(epi_num), len(epi_den))
    snap["ntsv_cesarean_rate_pct"] = ntsv_rate
    snap["episiotomy_rate_pct"] = epi_rate
    if ntsv_rate is None or epi_rate is None:
        snap["composite_quality_index"] = None
    else:
        # the already-rounded 4dp rates are what get averaged; this order is pinned
        snap["composite_quality_index"] = two_dp((ntsv_rate + epi_rate) / 2.0)
    shadow = _cohort(snap["unit_id"], "admitted_at",
                     snap["period_start_utc"], snap["period_end_utc"])
    shadow_den = [e for e in shadow if e.get("is_ntsv") is True]
    shadow_num = [e for e in shadow_den if e["delivery_mode"] == "CESAREAN_PRIMARY"]
    snap["shadow_ntsv_rate_pct"] = _rate(len(shadow_num), len(shadow_den))
    return snap


def recompute_draft_snapshots(unit_id, instant):
    """A DRAFT snapshot whose window contains a new delivery re-derives both
    variants; a CERTIFIED snapshot is never retro-mutated."""
    for snap in rows("snapshots", unit_id=unit_id, status="DRAFT"):
        if snap["period_start_utc"] <= instant < snap["period_end_utc"]:
            compute_snapshot(snap)
            rev.touch(snap)


# ------------------------------------------------- 3.7 escalation chain

def escalation_due_from(assessment, instant):
    """20 minutes for CATEGORY_II, 5 for CATEGORY_III, off the immutable category."""
    minutes = const.ESCALATION_DUE_MINUTES.get(assessment["category"])
    if minutes is None:
        return None
    return clock.plus_minutes(instant, minutes)


def rearm_chain(assessment, instant):
    """REASSESSMENT_PENDING -> ESCALATION_DUE, preserving the high-water mark so
    the second lap resumes above the first."""
    assessment["escalation_status"] = "ESCALATION_DUE"
    assessment["escalation_due_at"] = escalation_due_from(assessment, instant)
    assessment["reassessment_due_at"] = None
    assessment["next_tier_due_at"] = None
    rev.touch(assessment)


def rearmable(assessment):
    """A chain may re-arm until its high-water mark reaches 3."""
    return (assessment["category"] != "CATEGORY_I"
            and (assessment.get("escalation_tier_high_water") or 0) < 3)


def settle_predecessor(predecessor, newer):
    """A newer reading inside the reassessment window settles the predecessor."""
    if predecessor is None or predecessor["escalation_status"] != "REASSESSMENT_PENDING":
        return
    due = predecessor.get("reassessment_due_at")
    if due is None or newer["assessed_at"] > due:
        return
    if newer["category"] == "CATEGORY_I":
        predecessor["escalation_status"] = "RESOLVED"
        predecessor["reassessment_due_at"] = None
        predecessor["next_tier_due_at"] = None
        rev.touch(predecessor)
    elif rearmable(predecessor):
        rearm_chain(predecessor, newer["assessed_at"])


def escalation_target_eligible(staff, tier, unit_id):
    """Tier 1 wants an ACTIVE CHARGE nurse, tier 2 an ACTIVE OB_ATTENDING."""
    if staff is None:
        return False
    shifts = [s for s in active_shifts_of_unit(unit_id) if s["staff_id"] == staff["id"]]
    if not shifts:
        return False
    if tier == 1:
        return any(s["role_slot"] == "CHARGE" for s in shifts)
    return staff["staff_role"] == "OB_ATTENDING"


def mint_cesarean(enc, triggering_assessment_id=None, triggering_activation_id=None):
    event = store.new_record({
        "encounter_id": enc["id"],
        "or_bed_id": None,
        "triggering_assessment_id": triggering_assessment_id,
        "triggering_activation_id": triggering_activation_id,
        "urgency_class": "CATEGORY_1_CRASH",
        "decision_at": clock.now(),
        "incision_at": None,
        "delivery_at": None,
        "decision_to_incision_minutes": None,
        "met_target": None,
        "mobilized_staff_ids": [],
        "status": "DECISION_DECLARED",
    })
    S.cesareans[event["id"]] = event
    return event


def breach_escalation(assessment, unit):
    """Sweep edge: a missed deadline is a unit-level escalation breach."""
    assessment["escalation_status"] = "TIMED_OUT_BREACH"
    assessment["next_tier_due_at"] = None
    rev.touch(assessment)
    if unit is not None:
        unit["escalation_breach_count"] = (unit.get("escalation_breach_count") or 0) + 1
        rev.touch(unit)
