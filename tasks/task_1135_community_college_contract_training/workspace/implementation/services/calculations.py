"""Calculation rules (scaffold 1.3 / PRD 3): quote_pricing, invoice_gross,
invoice_grant_offset, grant_award, credential_match_score, attendance_completion,
instructor_committed_hours, grant_program_fund_rollup, placement_rate, employer_rollup.

All money is integer cents; round half up applied exactly where each rule says.
"""

from datetime import timedelta
from decimal import Decimal

from db import store
from errors import fail
from services import lookups
from util import dec, floor_cents, parse_dt, round_half_up_cents, round_half_up_int, round_half_up_2dp

# quote_pricing constants
TIER1_LIMIT = 10
TIER1_RATE_CENTS = 45000
TIER2_LIMIT = 15
TIER2_RATE_CENTS = 40000
TIER3_RATE_CENTS = 35000
MATERIALS_PER_HEAD_CENTS = 7500
FLAT_BASE_CENTS = 480000
FLAT_INCLUDED_HEADS = 12
FLAT_OVERAGE_PER_HEAD_CENTS = 38000
ON_SITE_SURCHARGE_CENTS = 25000
MIN_CONTRACT_CENTS = 150000
RUSH_THRESHOLD_DAYS = 14
RUSH_UPLIFT = Decimal("1.10")

INVOICE_LOAD_FACTOR = Decimal("1.15")

CONFIRM_THRESHOLD = 80
FULL_WEIGHT_HORIZON_DAYS = 30

COMPLETION_THRESHOLD_PCT = Decimal("80.00")


def quote_pricing(agreement, quote_dt):
    """PRD 3.2. Pinned evaluation order: tuition/materials -> mode adjustment ->
    rush uplift (single round_half_up here) -> floor."""
    n = agreement["est_participant_count"]
    if agreement["pricing_model"] == "PER_PARTICIPANT":
        tuition = (
            TIER1_RATE_CENTS * min(n, TIER1_LIMIT)
            + TIER2_RATE_CENTS * max(0, min(n - TIER1_LIMIT, TIER2_LIMIT))
            + TIER3_RATE_CENTS * max(0, n - TIER1_LIMIT - TIER2_LIMIT)
        )
        materials = n * MATERIALS_PER_HEAD_CENTS
        base = dec(tuition + materials)
    else:  # FLAT_COHORT
        base = dec(FLAT_BASE_CENTS + FLAT_OVERAGE_PER_HEAD_CENTS * max(0, n - FLAT_INCLUDED_HEADS))

    if agreement["delivery_mode"] == "ON_SITE":
        base += ON_SITE_SURCHARGE_CENTS
    else:  # ON_CAMPUS
        venue = store["venues"].get(agreement.get("campus_venue_id") or "")
        if venue is not None:
            base += dec(agreement["est_delivery_hours"]) * dec(venue["hourly_cost_cents"])

    target = parse_dt(agreement["target_start_date"])
    if target is not None and (target - quote_dt) < timedelta(days=RUSH_THRESHOLD_DAYS):
        base = dec(round_half_up_cents(base * RUSH_UPLIFT))

    quoted = base if base > MIN_CONTRACT_CENTS else dec(MIN_CONTRACT_CENTS)
    return int(quoted)


def _session_instructor_assignment(session):
    """The session's single COMPLETED-or-CONFIRMED assignment (earliest created)."""
    candidates = [
        a
        for a in lookups.assignments_of_session(session["id"])
        if a["status"] in ("COMPLETED", "CONFIRMED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a["created_at"])
    return candidates[0]


def invoice_gross(cohort, variant):
    """PRD 3.7. Per-line rounding, then integer sum. Returns (lines, gross_cents)."""
    if variant == "FINAL":
        sessions = [s for s in lookups.sessions_of_cohort(cohort["id"]) if s["status"] == "HELD"]
    else:  # PROVISIONAL
        sessions = [s for s in lookups.sessions_of_cohort(cohort["id"]) if s["status"] == "PLANNED"]
    sessions.sort(key=lambda s: s["created_at"])

    lines = []
    gross = 0
    for session in sessions:
        if variant == "FINAL":
            attendance = session.get("_attendance", {})
            attendees = sum(1 for h in attendance.values() if h > 0)
        else:
            attendees = cohort["enrolled_count"]
        assignment = _session_instructor_assignment(session)
        if assignment is None:
            fail(
                "ERR_INVALID_STATE",
                f"Session {session['id']} has no COMPLETED-or-CONFIRMED instructor assignment",
            )
        instructor = store["instructors"].get(assignment["instructor_id"])
        if instructor is None:
            fail("ERR_INVALID_STATE", "Session assignment references a missing instructor")
        instruction_cents = round_half_up_cents(
            dec(session["hours"]) * dec(instructor["hourly_rate_cents"]) * INVOICE_LOAD_FACTOR
        )
        materials_cents = round_half_up_cents(dec(attendees) * MATERIALS_PER_HEAD_CENTS)
        line_cents = instruction_cents + materials_cents
        lines.append(
            {
                "session_id": session["id"],
                "instruction_cents": instruction_cents,
                "materials_cents": materials_cents,
                "line_cents": line_cents,
            }
        )
        gross += line_cents
    return lines, gross


def invoice_grant_offset(cohort, variant, gross_cents):
    """PRD 3.7 pinned three-step order; step 2 offset."""
    covering = [
        a
        for a in lookups.applications_of_cohort(cohort["id"])
        if a["status"] in ("APPROVED", "CLAIMED", "PAID")
    ]
    if not covering:
        return 0
    covering.sort(key=lambda a: a["created_at"])
    application = covering[-1]
    program = store["programs"][application["program_id"]]
    if application["status"] in ("CLAIMED", "PAID"):
        award_basis = application["final_award_cents"] or 0
    else:
        award_basis = application["provisional_award_cents"] or 0
    headcount = cohort["completer_count"] if variant == "FINAL" else cohort["enrolled_count"]
    share_ceiling = floor_cents(dec(gross_cents) * dec(program["max_share_pct"]))
    cap_ceiling = program["cap_per_trainee_cents"] * headcount
    return max(0, min(award_basis, share_ceiling, cap_ceiling))


def grant_award_provisional(application, cohort, agreement, program):
    share = floor_cents(dec(agreement["quoted_total_cents"]) * dec(program["max_share_pct"]))
    cap = program["cap_per_trainee_cents"] * cohort["enrolled_count"]
    return max(0, min(application["requested_cents"], share, cap))


def grant_award_final(application, cohort, program):
    final_invoices = [
        i
        for i in lookups.invoices_of_cohort(cohort["id"])
        if i["variant"] == "FINAL" and i["status"] in ("DRAFT", "ISSUED", "PAID")
    ]
    final_invoices.sort(key=lambda i: i["created_at"])
    gross = final_invoices[-1]["gross_cents"] if final_invoices else 0
    share = floor_cents(dec(gross) * dec(program["max_share_pct"]))
    cap = program["cap_per_trainee_cents"] * cohort["completer_count"]
    return max(0, min(application["requested_cents"], share, cap))


def required_credential_codes(cohort):
    """Union of required_credential_codes over the cohort's agreement's assessment modules."""
    agreement = lookups.agreement_of_cohort(cohort)
    if agreement is None:
        return []
    assessment = store["assessments"].get(agreement["needs_assessment_id"])
    if assessment is None:
        return []
    codes = []
    for module in assessment.get("curriculum_modules") or []:
        for code in (module or {}).get("required_credential_codes") or []:
            if code not in codes:
                codes.append(code)
    return codes


def credential_match_score(instructor, session, cohort):
    """Returns (match_score, expired_code_or_None). Weighted coverage per PRD 3.5."""
    required = required_credential_codes(cohort)
    if not required:
        return 100, None
    start_at = parse_dt(session["start_at"])
    horizon = start_at + timedelta(days=FULL_WEIGHT_HORIZON_DAYS)
    total = 0.0
    expired_code = None
    for code in required:
        cred = None
        for c in instructor.get("credentials") or []:
            if isinstance(c, dict) and c.get("code") == code:
                cred = c
                break
        if cred is None:
            weight = 0.0
        else:
            expires_on = parse_dt(cred.get("expires_on"))
            if expires_on is None or expires_on < start_at:
                weight = 0.0
                expired_code = code
            elif expires_on < horizon:
                weight = 0.5
            else:
                weight = 1.0
        total += weight
    score = round_half_up_int(dec(100) * dec(total) / dec(len(required)))
    return score, expired_code


def instructor_committed_hours(instructor_id):
    """Defined quantity: SUM(session.hours) over CONFIRMED assignments on PLANNED sessions."""
    total = 0.0
    for a in store["assignments"].values():
        if a["instructor_id"] != instructor_id or a["status"] != "CONFIRMED":
            continue
        session = store["sessions"].get(a["session_id"])
        if session is not None and session["status"] == "PLANNED":
            total += float(session["hours"])
    return round(total, 10)


def refresh_committed_hours(instructor_id):
    instructor = store["instructors"].get(instructor_id)
    if instructor is None:
        return
    new_value = instructor_committed_hours(instructor_id)
    if new_value != instructor["committed_hours"]:
        from db import touch

        instructor["committed_hours"] = new_value
        touch(instructor)


def attendance_completion(cohort):
    """Runs when a cohort reaches DELIVERED. Evaluates every ENROLLED participant."""
    from db import touch

    held = [s for s in lookups.sessions_of_cohort(cohort["id"]) if s["status"] == "HELD"]
    scheduled_held_hours = sum(float(s["hours"]) for s in held)
    for p in lookups.participants_of_cohort(cohort["id"]):
        if p["completion_status"] != "ENROLLED":
            continue
        if scheduled_held_hours > 0:
            pct = round_half_up_2dp(dec(100) * dec(p["attended_hours"]) / dec(scheduled_held_hours))
        else:
            pct = 0.0
        p["attendance_pct"] = pct
        if float(p["attended_hours"]) == 0.0:
            p["completion_status"] = "NO_SHOW"
        elif dec(pct) >= COMPLETION_THRESHOLD_PCT:
            p["completion_status"] = "COMPLETED"
        else:
            p["completion_status"] = "DROPPED"
        touch(p)
    completers = sum(
        1
        for p in lookups.participants_of_cohort(cohort["id"])
        if p["completion_status"] == "COMPLETED"
    )
    cohort["completer_count"] = completers


def placement_rate(agreement, completers_employed_90d):
    total_completers = sum(
        c["completer_count"]
        for c in lookups.cohorts_of_agreement(agreement["id"])
        if c["delivery_status"] == "CREDENTIALED"
    )
    if total_completers <= 0:
        fail("ERR_INVALID_REQUEST", "No completers across the agreement's CREDENTIALED cohorts")
    return round_half_up_2dp(dec(100) * dec(completers_employed_90d) / dec(total_completers))
