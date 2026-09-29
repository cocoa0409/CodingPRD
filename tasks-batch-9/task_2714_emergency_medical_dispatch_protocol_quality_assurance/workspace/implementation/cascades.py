"""Derived-field reconciliation and the four named cascades (PRD 2.8).

Every derived field is a full recomputation from its source rows, never an
incremental adjustment, which is what makes voiding an exact compensating
action.  A row whose derived fields actually change is a mutation of that row:
updated_at is refreshed and version is incremented.
"""
from datetime import timedelta
from decimal import Decimal

import calc
from store import base_row, clock, db, order_rows, touch

OPEN_PLAN_STATES = ("ASSIGNED", "IN_PROGRESS", "SUSPENDED")
COUNTED_REVIEW_STATES = ("SELECTED", "SCORED", "DISPUTED", "FINALIZED")


def set_fields(row, updates):
    """Assign changed fields only, mutating the row once when anything moved."""
    changed = False
    for key, value in updates.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def program_of_dispatcher(dispatcher):
    return db.programs.get(dispatcher["program_id"])


def program_of_period(period):
    return db.programs.get(period["program_id"])


def program_of_review(review):
    period = db.sampling_periods.get(review["sampling_period_id"])
    if period is None:
        return None
    return program_of_period(period)


def reviews_of_period(period_id):
    return [r for r in db.reviews.values() if r["sampling_period_id"] == period_id]


def reviews_of_dispatcher(dispatcher_id):
    return [r for r in db.reviews.values() if r["dispatcher_id"] == dispatcher_id]


def plans_of_dispatcher(dispatcher_id):
    return [p for p in db.coaching_plans.values() if p["dispatcher_id"] == dispatcher_id]


def sessions_of_plan(plan_id):
    return [s for s in db.sessions.values() if s["coaching_plan_id"] == plan_id]


def sessions_of_dispatcher(dispatcher_id):
    plan_ids = set(p["id"] for p in plans_of_dispatcher(dispatcher_id))
    return [s for s in db.sessions.values() if s["coaching_plan_id"] in plan_ids]


def hrcr_of_review(review_id):
    for record in db.high_risk_reviews.values():
        if record["review_id"] == review_id:
            return record
    return None


def current_sheet(review):
    """The sheet whose sheet_round equals the review's current_sheet_round."""
    if review["current_sheet_round"] == 0:
        return None
    for sheet in db.score_sheets.values():
        if (
            sheet["review_id"] == review["id"]
            and sheet["sheet_round"] == review["current_sheet_round"]
        ):
            return sheet
    return None


def sheets_of_review(review_id):
    return [s for s in db.score_sheets.values() if s["review_id"] == review_id]


def rebuttals_of_review(review_id):
    return [r for r in db.rebuttals.values() if r["review_id"] == review_id]


# --------------------------------------------------------------------------
# sampling period counters
# --------------------------------------------------------------------------

def recompute_period_counters(period):
    if period is None:
        return
    rows = reviews_of_period(period["id"])
    selected = len([r for r in rows if r["status"] in COUNTED_REVIEW_STATES])
    finalized = len([r for r in rows if r["status"] == "FINALIZED"])
    set_fields(
        period,
        {"selected_review_count": selected, "finalized_review_count": finalized},
    )


# --------------------------------------------------------------------------
# dispatcher ledgers
# --------------------------------------------------------------------------

def recompute_dispatcher_compliance(dispatcher):
    """PRD 3.7 Cascade A link 2/3 — a full walk of the FINALIZED reviews."""
    program = program_of_dispatcher(dispatcher)
    pool = [
        r
        for r in reviews_of_dispatcher(dispatcher["id"])
        if r["status"] == "FINALIZED"
    ]
    count = len(pool)
    total = calc.q1(sum((r["final_composite_score"] for r in pool), Decimal("0")))
    if count == 0:
        pct = None
    else:
        pct = calc.q1(total / Decimal(count))
    posture = calc.posture_for(pct, program) if program else "UNRATED"
    set_fields(
        dispatcher,
        {
            "reviewed_case_count": count,
            "compliance_points_total": total,
            "compliance_pct": pct,
            "compliance_posture": posture,
        },
    )


def recompute_dispatcher_sentinel(dispatcher):
    count = 0
    for record in db.high_risk_reviews.values():
        if record["classification"] != "SENTINEL_EVENT":
            continue
        review = db.reviews.get(record["review_id"])
        if review is None or review["status"] == "VOIDED":
            continue
        if review["dispatcher_id"] == dispatcher["id"]:
            count += 1
    set_fields(dispatcher, {"sentinel_event_count": count})


def recompute_program_sentinel(program):
    if program is None:
        return
    count = 0
    for record in db.high_risk_reviews.values():
        if record["classification"] != "SENTINEL_EVENT":
            continue
        review = db.reviews.get(record["review_id"])
        if review is None or review["status"] == "VOIDED":
            continue
        dispatcher = db.dispatchers.get(review["dispatcher_id"])
        if dispatcher is not None and dispatcher["program_id"] == program["id"]:
            count += 1
    set_fields(program, {"sentinel_event_count": count})


def recompute_plan_credited_hours(plan):
    """PRD 3.8 — full recompute over the plan's COMPLETED sessions."""
    total = Decimal("0")
    for session in sessions_of_plan(plan["id"]):
        if session["status"] == "COMPLETED":
            total += session["duration_hours"]
    set_fields(plan, {"credited_hours": calc.q2(total)})


def recompute_hours_and_privilege(dispatcher):
    """PRD 3.8 — the owed-hours ledger, then the derived dispatch privilege."""
    owed = Decimal("0")
    for plan in plans_of_dispatcher(dispatcher["id"]):
        if plan["status"] in OPEN_PLAN_STATES:
            shortfall = plan["required_hours"] - plan["credited_hours"]
            if shortfall < 0:
                shortfall = Decimal("0")
            owed += shortfall
    updates = {"remediation_hours_owed": calc.q2(owed)}
    program = program_of_dispatcher(dispatcher)
    threshold = program["hours_owed_restriction_threshold"] if program else Decimal("0")
    sentinels = dispatcher["sentinel_event_count"]
    if sentinels >= 2:
        privilege = "SUSPENDED"
    elif updates["remediation_hours_owed"] > threshold:
        privilege = "RESTRICTED"
    elif dispatcher["certification_status"] == "LAPSED":
        privilege = "RESTRICTED"
    elif sentinels >= 1:
        privilege = "RESTRICTED"
    else:
        privilege = "FULL"
    updates["dispatch_privilege"] = privilege
    set_fields(dispatcher, updates)


# --------------------------------------------------------------------------
# rollout training dimension
# --------------------------------------------------------------------------

def trained_count_for_version(version_id):
    return len(
        [
            d
            for d in db.dispatchers.values()
            if d["certified_protocol_version_id"] == version_id
            and d["certification_status"] == "CERTIFIED"
        ]
    )


def training_status_for(count, target):
    if count == 0:
        return "NOT_STARTED"
    if count >= target:
        return "COMPLETE"
    return "IN_PROGRESS"


def recompute_rollouts_for_version(version_id):
    if version_id is None:
        return
    count = trained_count_for_version(version_id)
    for rollout in db.rollouts.values():
        if rollout["protocol_version_id"] != version_id:
            continue
        set_fields(
            rollout,
            {
                "trained_dispatcher_count": count,
                "training_status": training_status_for(
                    count, rollout["target_dispatcher_count"]
                ),
            },
        )

# --------------------------------------------------------------------------
# the automatic coaching plan (PRD 3.8)
# --------------------------------------------------------------------------

def choose_auto_plan(dispatcher, review, hrcr, use_posture):
    """The ordered ladder, most severe first; None means 'leave them alone'.

    ``use_posture`` is true only on the finalization trigger, because the two
    posture clauses read the dispatcher's *freshly recomputed* posture and no
    posture recomputation happens at clinical sign-off (PRD 3.6 describes that
    branch's plan directly as CRITICAL/DACPR or ADVISORY/DACPR).
    """
    accuracy = review.get("determinant_accuracy") if review else None
    classification = hrcr.get("classification") if hrcr else None
    if accuracy == "UNDER_TRIAGE":
        return "CRITICAL", "DETERMINANT_CODING"
    if classification == "SENTINEL_EVENT":
        return "CRITICAL", "DACPR"
    if use_posture:
        sheet = current_sheet(review) if review else None
        if dispatcher["compliance_posture"] == "PROBATION":
            focus = calc.weakest_section_focus(sheet) if sheet else "CASE_ENTRY"
            return "STANDARD", focus
        if dispatcher["compliance_posture"] == "WATCH":
            focus = calc.weakest_section_focus(sheet) if sheet else "CASE_ENTRY"
            return "ADVISORY", focus
    if classification == "COACHING_ONLY" and hrcr.get("dacpr_pass") is False:
        return "ADVISORY", "DACPR"
    return None


PLAN_UPSERT_STATES = ("ASSIGNED", "IN_PROGRESS", "SUSPENDED", "VERIFIED")


def find_auto_plan(dispatcher_id, source_review_id):
    """At most one automatic plan exists per dispatcher-and-review pairing."""
    for plan in order_rows(list(db.coaching_plans.values())):
        if (
            plan["origin"] == "AUTO"
            and plan["dispatcher_id"] == dispatcher_id
            and plan["source_review_id"] == source_review_id
            and plan["status"] in PLAN_UPSERT_STATES
        ):
            return plan
    return None


def auto_plan_upsert(dispatcher, review, hrcr=None, use_posture=True):
    chosen = choose_auto_plan(dispatcher, review, hrcr, use_posture)
    if chosen is None:
        return None
    severity, focus = chosen
    rank = calc.SEVERITY_RANK[severity]
    hours = calc.REQUIRED_HOURS[severity]
    existing = find_auto_plan(dispatcher["id"], review["id"])
    if existing is not None:
        # Ratchets upward only: an equal or higher existing rank changes nothing.
        if rank > existing["severity_rank"]:
            set_fields(
                existing,
                {
                    "severity": severity,
                    "severity_rank": rank,
                    "focus_area": focus,
                    "required_hours": calc.q1(hours),
                },
            )
        return existing
    plan = base_row()
    plan.update(
        {
            "dispatcher_id": dispatcher["id"],
            "origin": "AUTO",
            "severity": severity,
            "severity_rank": rank,
            "focus_area": focus,
            "source_review_id": review["id"],
            "required_hours": calc.q1(hours),
            "credited_hours": calc.q2(Decimal("0")),
            "status": "ASSIGNED",
            "closure_reason": None,
            "due_at": clock() + timedelta(days=calc.AUTO_PLAN_DUE_DAYS),
            "verified_at": None,
        }
    )
    db.coaching_plans[plan["id"]] = plan
    return plan


# --------------------------------------------------------------------------
# Cascade A — finalization (PRD 3.7)
# --------------------------------------------------------------------------

def cascade_a_finalize(review):
    period = db.sampling_periods.get(review["sampling_period_id"])
    recompute_period_counters(period)

    hrcr = hrcr_of_review(review["id"])
    if hrcr is not None:
        set_fields(hrcr, {"status": "CLOSED"})

    dispatcher = db.dispatchers.get(review["dispatcher_id"])
    if dispatcher is None:
        return
    recompute_dispatcher_compliance(dispatcher)
    recompute_dispatcher_sentinel(dispatcher)
    auto_plan_upsert(dispatcher, review, hrcr, use_posture=True)
    recompute_hours_and_privilege(dispatcher)


# --------------------------------------------------------------------------
# Cascade D — voiding, and the shared void routine (PRD 3.7)
# --------------------------------------------------------------------------

def void_review(review, reason):
    """Void one review from any live state and unwind whatever it caused."""
    was_finalized = review["status"] == "FINALIZED"
    was_scored = review["status"] == "SCORED"
    updates = {
        "status": "VOIDED",
        "voided_at": clock(),
        "void_reason": reason,
    }
    if was_scored:
        updates["provisional_composite_score"] = None
    if was_finalized:
        updates["pre_penalty_composite_score"] = None
        updates["penalty_points"] = None
        updates["final_composite_score"] = None
        updates["determinant_accuracy"] = None
        updates["compliant"] = None
    set_fields(review, updates)

    call = db.call_records.get(review["call_record_id"])
    if call is not None and call["status"] == "SELECTED":
        set_fields(call, {"status": "INGESTED"})

    period = db.sampling_periods.get(review["sampling_period_id"])
    recompute_period_counters(period)

    dispatcher = db.dispatchers.get(review["dispatcher_id"])
    hrcr = hrcr_of_review(review["id"])
    if dispatcher is None:
        return review

    if was_finalized:
        recompute_dispatcher_compliance(dispatcher)
        for plan in order_rows(plans_of_dispatcher(dispatcher["id"])):
            if (
                plan["origin"] == "AUTO"
                and plan["source_review_id"] == review["id"]
                and plan["status"] in OPEN_PLAN_STATES
            ):
                set_fields(
                    plan, {"status": "CANCELLED", "closure_reason": "SOURCE_VOIDED"}
                )
        if hrcr is not None:
            recompute_dispatcher_sentinel(dispatcher)
            recompute_program_sentinel(program_of_dispatcher(dispatcher))
        recompute_hours_and_privilege(dispatcher)
    elif hrcr is not None and hrcr["classification"] == "SENTINEL_EVENT":
        # A sentinel event restricts from sign-off and is removed only by
        # voiding the underlying review (PRD 3.6), even before finalization.
        recompute_dispatcher_sentinel(dispatcher)
        recompute_program_sentinel(program_of_dispatcher(dispatcher))
        recompute_hours_and_privilege(dispatcher)
    return review


# --------------------------------------------------------------------------
# Cascade B — rollout go-live (PRD 3.3), five links
# --------------------------------------------------------------------------

def cascade_b_golive(rollout):
    version = db.protocol_versions.get(rollout["protocol_version_id"])
    if version is None:
        return
    # link 1 — the rollout's own version becomes ACTIVE.
    set_fields(version, {"status": "ACTIVE", "activated_at": clock()})

    # link 2 — the previously ACTIVE version of the same family is superseded.
    superseded = None
    for other in order_rows(list(db.protocol_versions.values())):
        if other["id"] == version["id"]:
            continue
        if (
            other["program_id"] == version["program_id"]
            and other["protocol_family"] == version["protocol_family"]
            and other["status"] == "ACTIVE"
        ):
            superseded = other
            break
    if superseded is None:
        return
    # effective_to is left exactly as declared.
    set_fields(superseded, {"status": "SUPERSEDED", "superseded_at": clock()})

    # link 3 — every dispatcher certified on it lapses, keeping the audit FK.
    lapsed = []
    for dispatcher in order_rows(list(db.dispatchers.values())):
        if (
            dispatcher["certified_protocol_version_id"] == superseded["id"]
            and dispatcher["certification_status"] == "CERTIFIED"
        ):
            set_fields(dispatcher, {"certification_status": "LAPSED"})
            lapsed.append(dispatcher)

    # link 4 — their open plans are suspended and privilege is re-derived.
    for dispatcher in lapsed:
        for plan in order_rows(plans_of_dispatcher(dispatcher["id"])):
            if plan["status"] in ("ASSIGNED", "IN_PROGRESS"):
                set_fields(plan, {"status": "SUSPENDED"})
        recompute_hours_and_privilege(dispatcher)

    # link 5 — the superseded version's rollouts regress their training status.
    recompute_rollouts_for_version(superseded["id"])


# --------------------------------------------------------------------------
# Cascade C — accreditation filing (PRD 3.9)
# --------------------------------------------------------------------------

def winning_report(program_id):
    """Greatest window_end, then created_at, then submitted_at — never the id."""
    submitted = [
        r
        for r in db.reports.values()
        if r["program_id"] == program_id and r["status"] == "SUBMITTED"
    ]
    if not submitted:
        return None
    return max(
        submitted,
        key=lambda r: (r["window_end"], r["created_at"], r["submitted_at"]),
    )


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [a_start, a_end) against half-open [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def cascade_c_submit(report):
    program = db.programs.get(report["program_id"])
    if program is None:
        return
    count = len(
        [
            r
            for r in db.reports.values()
            if r["program_id"] == program["id"] and r["status"] == "SUBMITTED"
        ]
    )
    winner = winning_report(program["id"])
    updates = {"submitted_report_count": count}
    if winner is None:
        updates["latest_compliance_pct"] = None
        updates["accreditation_status"] = "SETUP"
    else:
        updates["latest_compliance_pct"] = winner["compliance_pct"]
        updates["accreditation_status"] = (
            "ACCREDITED" if winner["threshold_met"] else "AT_RISK"
        )
    set_fields(program, updates)
    recompute_program_sentinel(program)

    # The lock: closed periods whose window overlaps the report's window.
    for period in order_rows(list(db.sampling_periods.values())):
        if period["program_id"] != program["id"] or period["status"] != "CLOSED":
            continue
        if not windows_overlap(
            period["period_start"],
            period["period_end"],
            report["window_start"],
            report["window_end"],
        ):
            continue
        set_fields(period, {"status": "LOCKED", "locked_at": clock()})
        for review in order_rows(reviews_of_period(period["id"])):
            # Only never-worked selections are discarded; SCORED and DISPUTED
            # reviews are audit work product and are merely frozen.
            if review["status"] == "SELECTED":
                void_review(review, "PERIOD_LOCKED")
