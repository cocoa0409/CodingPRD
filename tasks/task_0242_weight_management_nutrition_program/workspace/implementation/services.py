"""Cross-entity business services: derived-field recomputation, goal/milestone
auto-achievement, graduation eligibility, and the enrollment-ending cascade."""
from db import db
from common import touch
from lookups import iso_from_seconds, program_clock_seconds
import calculations as calc


# --------------------------------------------------------------------------
# Weigh-in driven recomputation
# --------------------------------------------------------------------------
def counted_weighins_for_enrollment(enrollment_id):
    return [w for w in db.weigh_ins.values()
            if w["enrollment_id"] == enrollment_id and w["counts"] is True]


def recompute_member_progress(member):
    """Refresh member latest_weight/latest_lean/progress fields from the
    member's most recent COUNTED weigh-ins. Member must be re-derived from all
    of its enrollments' counted weigh-ins (member_id copied onto each weigh-in).
    """
    counted = [w for w in db.weigh_ins.values()
               if w["member_id"] == member["id"] and w["counts"] is True]
    counted.sort(key=lambda w: w["_seq"])

    if counted:
        member["latest_weight_kg"] = counted[-1]["weight_kg"]
        # latest lean mass = lean mass of the most recent counted weigh-in that
        # carried a body-fat reading (null otherwise)
        latest_lean = None
        for w in reversed(counted):
            if w.get("lean_mass_kg") is not None:
                latest_lean = w["lean_mass_kg"]
                break
        member["latest_lean_mass_kg"] = latest_lean
    else:
        member["latest_weight_kg"] = None
        member["latest_lean_mass_kg"] = None

    member["scale_progress_pct"] = calc.compute_scale_progress_pct(
        member["baseline_weight_kg"], member["latest_weight_kg"]
    )
    member["lean_adjusted_progress_pct"] = calc.compute_lean_adjusted_progress_pct(
        member["baseline_weight_kg"], member["latest_weight_kg"],
        member["latest_lean_mass_kg"]
    )


def recompute_goal_progress_and_achieve(member, enrollment, program):
    """Recompute progress for all OPEN goals of the enrollment; auto-achieve
    goals at >= 100 and milestones at >= threshold; cascade primary->grad."""
    goals = [g for g in db.goals.values() if g["enrollment_id"] == enrollment["id"]]
    for goal in goals:
        if goal["status"] != "OPEN":
            continue
        new_progress = calc.compute_goal_progress_pct(
            member["baseline_weight_kg"], member["latest_weight_kg"],
            goal["target_weight_kg"]
        )
        if new_progress != goal["progress_pct"]:
            goal["progress_pct"] = new_progress
            touch(goal)
        # auto-achieve milestones whose threshold reached (inclusive)
        achieve_milestones_for_goal(goal, member, program)
        # auto-achieve goal at >= 100
        if goal["progress_pct"] >= 100.0:
            goal["status"] = "ACHIEVED"
            touch(goal)
            # on achievement, transition still-pending milestones (<=100) to ACHIEVED
            achieve_milestones_for_goal(goal, member, program, on_goal_achieve=True)
            if goal["kind"] == "PRIMARY":
                recompute_graduation_eligibility(enrollment)


def achieve_milestones_for_goal(goal, member, program, on_goal_achieve=False):
    """Transition PENDING milestones to ACHIEVED when goal progress reaches
    their threshold (inclusive). On goal achievement, all pending milestones
    with threshold <= 100 achieve."""
    now_utc = program["current_utc"]
    milestones = [m for m in db.milestones.values() if m["goal_id"] == goal["id"]]
    for ms in milestones:
        if ms["status"] != "PENDING":
            continue
        reached = (goal["progress_pct"] >= ms["threshold_pct"]) or \
                  (on_goal_achieve and ms["threshold_pct"] <= 100)
        if reached:
            ms["status"] = "ACHIEVED"
            ms["achieved_at_utc"] = now_utc
            ms["achieved_weight_kg"] = member["latest_weight_kg"]
            touch(ms)


def recompute_graduation_eligibility(enrollment):
    counted = counted_weighins_for_enrollment(enrollment["id"])
    has_primary_achieved = any(
        g["enrollment_id"] == enrollment["id"]
        and g["kind"] == "PRIMARY"
        and g["status"] == "ACHIEVED"
        for g in db.goals.values()
    )
    new_val = has_primary_achieved and len(counted) >= calc.MIN_COUNTED_WEIGHINS
    if new_val != enrollment["graduation_eligible"]:
        enrollment["graduation_eligible"] = new_val
        # graduation_eligible is a computed field on the enrollment; recompute
        # does not itself bump version beyond the weigh-in's own bump path.


# --------------------------------------------------------------------------
# HSA/FSA eligibility helper
# --------------------------------------------------------------------------
def enrollment_is_hsa_fsa_eligible(enrollment_id):
    for d in db.eligibility_determinations.values():
        if d["enrollment_id"] == enrollment_id \
                and d["status"] == "APPROVED" and d["hsa_fsa_eligible"] is True:
            return True
    return False


def recompute_invoice_hsa_fsa(invoice):
    eligible = enrollment_is_hsa_fsa_eligible(invoice["enrollment_id"])
    invoice["hsa_fsa_eligible_cents"] = calc.compute_hsa_fsa_eligible_cents(
        invoice["line_items"], eligible
    )


# --------------------------------------------------------------------------
# Cascade on enrollment graduate / withdraw
# --------------------------------------------------------------------------
def run_enrollment_end_cascade(enrollment, program):
    """Close OPEN goals -> void their PENDING milestones; end ACTIVE coach
    assignments (decrement coach load) -> archive their OPEN threads."""
    now_utc = program["current_utc"]

    # 1. every OPEN goal -> CLOSED; each goal-closure VOIDs its PENDING milestones
    for goal in db.goals.values():
        if goal["enrollment_id"] != enrollment["id"]:
            continue
        if goal["status"] == "OPEN":
            goal["status"] = "CLOSED"
            touch(goal)
            for ms in db.milestones.values():
                if ms["goal_id"] == goal["id"] and ms["status"] == "PENDING":
                    ms["status"] = "VOIDED"
                    touch(ms)

    # 2. every ACTIVE coach assignment -> ENDED (decrement load); archive threads
    for assignment in db.coach_assignments.values():
        if assignment["enrollment_id"] != enrollment["id"]:
            continue
        if assignment["status"] == "ACTIVE":
            end_coach_assignment(assignment, program)


def end_coach_assignment(assignment, program):
    """Transition a CoachAssignment ACTIVE -> ENDED: stamp ended_at_utc,
    decrement coach.active_member_count, archive OPEN threads."""
    now_utc = program["current_utc"]
    assignment["status"] = "ENDED"
    assignment["ended_at_utc"] = now_utc
    touch(assignment)
    coach = db.coaches.get(assignment["coach_id"])
    if coach is not None:
        coach["active_member_count"] = recompute_coach_active_count(coach["id"])
        touch(coach)
    # archive owning OPEN message threads
    for thread in db.message_threads.values():
        if thread["coach_assignment_id"] == assignment["id"] and thread["status"] == "OPEN":
            thread["status"] = "ARCHIVED"
            touch(thread)


def recompute_coach_active_count(coach_id):
    return sum(1 for a in db.coach_assignments.values()
               if a["coach_id"] == coach_id and a["status"] == "ACTIVE")


# --------------------------------------------------------------------------
# Settlement invoice (proration) on graduate / withdraw
# --------------------------------------------------------------------------
def issue_settlement_invoice(enrollment, program, plan, member):
    """Issue the final settlement invoice with a PRORATION_CREDIT line for the
    unused days of the current ISSUED invoice's period; credit member balance."""
    from common import init_common

    # locate the current (latest non-VOID) ISSUED-or-active invoice's period
    invoices = [inv for inv in db.invoices.values()
                if inv["enrollment_id"] == enrollment["id"] and inv["status"] != "VOID"]
    invoices.sort(key=lambda inv: inv["_seq"])
    if not invoices:
        return None
    current_inv = invoices[-1]

    current_secs = program_clock_seconds(program)
    period_start_secs = _iso_to_secs(current_inv["period_start_utc"])
    cycle_len = enrollment["cycle_length_days"]
    monthly = plan["monthly_fee_cents"]

    credit = calc.compute_proration_credit(
        current_secs, period_start_secs, cycle_len, monthly
    )

    cycle_index = enrollment["cycles_billed"]
    period_start = program["current_utc"]
    period_end = iso_from_seconds(current_secs + cycle_len * calc.SECONDS_PER_DAY)

    line_items = []
    prorated = False
    if credit > 0:
        line_items.append({"code": "PRORATION_CREDIT", "amount_cents": -credit})
        prorated = True
        member["account_balance_cents"] += credit
        touch(member)

    subtotal = sum(li["amount_cents"] for li in line_items)

    invoice = {
        "enrollment_id": enrollment["id"],
        "member_id": member["id"],
        "cycle_index": cycle_index,
        "period_start_utc": period_start,
        "period_end_utc": period_end,
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "hsa_fsa_eligible_cents": 0,
        "prorated": prorated,
        "status": "ISSUED",
    }
    init_common(invoice)
    invoice["hsa_fsa_eligible_cents"] = calc.compute_hsa_fsa_eligible_cents(
        invoice["line_items"], enrollment_is_hsa_fsa_eligible(enrollment["id"])
    )
    db.invoices[invoice["id"]] = invoice
    enrollment["cycles_billed"] += 1
    return invoice


def _iso_to_secs(iso):
    from lookups import parse_instant
    return parse_instant(iso, "period_start_utc")
