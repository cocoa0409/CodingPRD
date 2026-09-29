"""Cascade A, Cascade B, teach-out liability and the counselor performance run.

The hop structure is normative: a later hop is caused by an earlier hop's effect
rather than by the original request (PRD 2.8).
"""

import constants as C
import db
from db import store, touch
from services.derive import (recompute_counselor_pipeline,
                             recompute_enrollment_cash, recompute_partnership,
                             recompute_program)
from services.money import D, as_float, day_span, floor_int, parse_iso_date, rhu, rhu_int


# --------------------------------------------------------------------------- #
# program teach-out (Cascade A hops 2 and 3, and the BEGIN_TEACH_OUT edge)     #
# --------------------------------------------------------------------------- #

def enter_teach_out(program):
    program["status"] = "TEACH_OUT"
    program["teach_out_started_at"] = db.now_iso()
    touch(program)

    # hop 2 — the program's own leads and in-flight course designs
    counselor_ids = []
    for lead in db.leads_of_program(program["id"]):
        if lead["status"] in ("NEW", "CONTACTED", "APPLIED"):
            lead["status"] = "DISQUALIFIED"
            lead["disqualification_reason"] = "PROGRAM_TEACH_OUT"
            touch(lead)
            if lead["counselor_id"] not in counselor_ids:
                counselor_ids.append(lead["counselor_id"])
    for course in db.courses_of(program["id"]):
        if course["design_status"] in ("IN_DESIGN", "FACULTY_REVIEW"):
            course["design_status"] = "DESIGN_SUSPENDED"
            touch(course)

    # hop 3 — caused by hop 2
    for counselor_id in counselor_ids:
        counselor = store.counselors.get(counselor_id)
        if counselor is None:  # pragma: no cover
            continue
        recompute_counselor_pipeline(counselor)
        if (counselor["open_pipeline_count"] == 0
                and counselor["performance_status"] != "INACTIVE_PENDING_REVIEW"):
            # the incentive dimension is deliberately left untouched
            counselor["performance_status"] = "INACTIVE_PENDING_REVIEW"
            touch(counselor)


def cascade_a(partnership):
    """Partnership WIND_DOWN — hop 1 in ascending Program.created_at order."""
    for program in db.programs_of(partnership["id"]):
        if program["status"] in ("LAUNCHED", "SUSPENDED"):
            enter_teach_out(program)


# --------------------------------------------------------------------------- #
# Cascade B — withdrawal                                                      #
# --------------------------------------------------------------------------- #

def refund_band(partnership, days_elapsed):
    for band in partnership["refund_schedule"]:
        through = band["through_day"]
        if through is None or through >= days_elapsed:
            return band["refund_pct"]
    return 0.0


def withdraw_enrollment(enrollment, withdrawal_date, program, partnership):
    days = day_span(parse_iso_date(enrollment["term_start_date"]),
                    parse_iso_date(withdrawal_date))
    pct = refund_band(partnership, days)

    refundable = enrollment["collected_cents"] - enrollment["refunded_cents"]
    owed = rhu_int(D(enrollment["tuition_charged_cents"]) * D(pct))
    amount = refundable if refundable < owed else owed

    enrollment["status"] = "WITHDRAWN"
    enrollment["withdrawal_date"] = withdrawal_date
    enrollment["days_elapsed_at_withdrawal"] = days
    enrollment["refund_pct_applied"] = float(D(pct))
    touch(enrollment)

    # hop 1 — the compensating ledger entry
    if amount > 0:
        entry = db.base_entity(full=False)
        entry.update({
            "enrollment_id": enrollment["id"],
            "entry_type": "REFUND",
            "amount_cents": amount,
            "posted_date": withdrawal_date,
            "reference_note": None,
            "generated_by": "WITHDRAWAL_REFUND",
        })
        store.tuition_payments[entry["id"]] = entry
        recompute_enrollment_cash(enrollment)

    recompute_program(program)
    recompute_partnership(partnership)

    # hop 2 — caused by hop 1's refund entry
    lead = store.leads.get(enrollment["lead_id"])
    counselor = store.counselors.get(lead["counselor_id"]) if lead else None
    if counselor is not None and days <= C.CLAWBACK_WINDOW_DAYS:
        accrual = rhu_int(D(counselor["variable_component_cents"]) * D(pct))
        if accrual:
            counselor["clawback_pending_cents"] += accrual
            touch(counselor)
        # hop 3 — caused by hop 2's accrual
        if (counselor["clawback_pending_cents"] >= C.CLAWBACK_SUSPENSION_TRIGGER_CENTS
                and counselor["incentive_eligibility"] == "ELIGIBLE"):
            counselor["incentive_eligibility"] = "SUSPENDED"
            touch(counselor)

    stale_statements(partnership, enrollment)


def stale_statements(partnership, enrollment):
    """Settlement work already done for a closed period containing the
    enrollment's term start is invalidated."""
    term_start = parse_iso_date(enrollment["term_start_date"])
    for statement in db.statements_of(partnership["id"]):
        if statement["status"] not in ("CALCULATED", "UNIVERSITY_APPROVED"):
            continue
        start = parse_iso_date(statement["period_start"])
        end = parse_iso_date(statement["period_end"])
        if start <= term_start <= end:
            statement["status"] = "STALE"
            statement["requires_recalculation"] = True
            touch(statement)


# --------------------------------------------------------------------------- #
# teach-out liability                                                         #
# --------------------------------------------------------------------------- #

def plan_snapshot(program):
    affected = [e for e in db.enrollments_of_program(program["id"])
                if e["status"] in ("ENROLLED", "ACTIVE")]
    remaining = sum(e["credits_enrolled"] - e["credits_completed"] for e in affected)
    return len(affected), remaining, remaining * C.TEACH_OUT_COST_PER_CREDIT_CENTS


def allocate_liability(plan, program, partnership):
    cost = plan["teach_out_cost_cents"]
    balance = partnership["holdback_balance_cents"]
    holdback_applied = balance if balance < cost else cost
    if holdback_applied < 0:
        holdback_applied = 0
    residual = cost - holdback_applied
    cap = floor_int(D(cost) * D(C.PARTNER_OBLIGATION_CAP_PCT))
    partner_obligation = residual if residual < cap else cap
    university_residual = cost - holdback_applied - partner_obligation

    scope = plan["asset_transfer_scope"]
    if scope == "NONE":
        asset_value = 0
    else:
        book = sum(c["design_cost_cents"] for c in db.courses_of(program["id"])
                   if c["design_status"] in ("APPROVED", "DESIGN_SUSPENDED", "RETIRED"))
        asset_value = rhu_int(D(book) * D(C.ASSET_TRANSFER_SCOPE_FACTOR[scope]))

    plan["holdback_applied_cents"] = holdback_applied
    plan["partner_obligation_cents"] = partner_obligation
    plan["university_residual_cents"] = university_residual
    plan["transferred_asset_value_cents"] = asset_value


# --------------------------------------------------------------------------- #
# counselor performance run                                                   #
# --------------------------------------------------------------------------- #

RATED_STATUSES = ("CONTACTED", "APPLIED", "ENROLLED", "DISQUALIFIED")


def _sla_hours(program_id):
    for assignment in db.assignments_of(program_id):
        if assignment["service_domain"] == "ENROLLMENT_COUNSELING":
            return assignment["sla_response_hours"]
    return None


def performance_run(partnership, window_start, window_end):
    evaluated = 0
    rated = 0
    downgraded = 0

    for counselor in db.counselors_of(partnership["id"]):
        if counselor["performance_status"] == "INACTIVE_PENDING_REVIEW":
            continue
        evaluated += 1

        leads = [lead for lead in db.leads_of_counselor(counselor["id"])
                 if window_start <= lead["created_at"][:10] <= window_end]

        rated_leads = [lead for lead in leads if lead["status"] in RATED_STATUSES]
        rated_count = len(rated_leads)
        enrolled_count = sum(1 for lead in rated_leads if lead["status"] == "ENROLLED")

        breaches = 0
        for lead in rated_leads:
            hours = lead["hours_to_first_contact"]
            if hours is None:
                continue
            limit = _sla_hours(lead["program_id"])
            if limit is not None and hours > limit:
                breaches += 1

        counselor["rated_lead_count"] = rated_count
        counselor["enrolled_lead_count"] = enrolled_count
        counselor["sla_breach_count"] = breaches

        if rated_count < C.MIN_RATED_PIPELINE:
            counselor["conversion_rate"] = 0.0
            counselor["performance_status"] = "NOT_RATED"
        else:
            rated += 1
            rate = rhu(D(enrolled_count) / D(rated_count), 4)
            counselor["conversion_rate"] = as_float(rate)
            if rate >= D(C.MEETS_THRESHOLD):
                status = "MEETS_STANDARD"
            elif rate >= D(C.WATCH_THRESHOLD):
                status = "WATCH"
            else:
                status = "PROBATION"
            ratio = rhu(D(breaches) / D(rated_count), 4)
            if ratio > D(C.SLA_BREACH_MAX_RATIO):
                downgraded += 1
                status = {"MEETS_STANDARD": "WATCH",
                          "WATCH": "PROBATION",
                          "PROBATION": "PROBATION"}[status]
            counselor["performance_status"] = status

        # the incentive dimension is never read or written here
        touch(counselor)

    return {
        "evaluated_count": evaluated,
        "rated_count": rated,
        "downgraded_count": downgraded,
        "run_completed_at": db.now_iso(),
    }
