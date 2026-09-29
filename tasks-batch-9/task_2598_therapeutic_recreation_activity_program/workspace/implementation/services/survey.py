"""Survey packet compilation: cohort selection, penalties, provision score."""
from db import parse_date, parse_datetime
from services import clinical
from services import constants as C
from services import plans as plan_svc
from services.numbers import dec, divide, rhu


def _in_window(day, window_start, window_end):
    return window_start <= day <= window_end


def cohort_for(st, window_start, window_end):
    """Admitted residents whose live plan cycle opens inside the window."""
    selected = []
    for resident in st.residents.values():
        if resident["status"] != "ADMITTED":
            continue
        candidates = []
        for plan in st.plans.values():
            if plan["resident_id"] != resident["id"]:
                continue
            if plan["status"] not in C.LIVE_PLAN_STATUSES:
                continue
            cycle_day = parse_datetime(plan["cycle_start_at"]).date()
            if not _in_window(cycle_day, window_start, window_end):
                continue
            candidates.append(plan)
        if not candidates:
            continue
        governing = sorted(
            candidates,
            key=lambda p: (p["cycle_start_at"], p["created_at"], p["_seq"]),
            reverse=True,
        )[0]
        selected.append((resident, governing))
    selected.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["_seq"]))
    return selected


def _records_in_window(st, resident_id, window_start, window_end):
    rows = []
    for record in clinical.resident_records(st, resident_id):
        if clinical.record_outcome(record) not in C.OFFERED_OUTCOMES:
            continue
        session = st.sessions.get(record["session_id"])
        if session is None:
            continue
        day = parse_datetime(session["starts_at"]).date()
        if _in_window(day, window_start, window_end):
            rows.append(record)
    return rows


def _domain_covered(st, resident_id, plan, domain):
    lo, hi = plan_svc.plan_window(plan)
    for record in clinical.resident_records(st, resident_id):
        if clinical.record_outcome(record) not in C.OFFERED_OUTCOMES:
            continue
        session = st.sessions.get(record["session_id"])
        if session is None:
            continue
        program = st.programs.get(session["program_id"])
        if program is None or program["domain"] != domain:
            continue
        starts_at = parse_datetime(session["starts_at"])
        if lo <= starts_at < hi:
            return True
    return False


def unscreened_volunteer_count(st, window_start, window_end):
    count = 0
    for assignment in st.assignments.values():
        if assignment["status"] not in ("CONFIRMED", "COMPLETED"):
            continue
        session = st.sessions.get(assignment["session_id"])
        if session is None:
            continue
        day = parse_datetime(session["starts_at"]).date()
        if not _in_window(day, window_start, window_end):
            continue
        volunteer = st.volunteers.get(assignment["volunteer_id"])
        if volunteer is None or volunteer["status"] != "CLEARED":
            count += 1
    return count


def compile_packet(st, packet):
    """Every score field is overwritten from scratch on each compile."""
    window_start = parse_date(packet["window_start"])
    window_end = parse_date(packet["window_end"])
    cohort = cohort_for(st, window_start, window_end)

    targeted = 0
    delivered = 0
    attainment_total = dec(0)
    unmet_domains = 0
    unaddressed = 0

    for resident, plan in cohort:
        targeted += plan["target_total_sessions"]
        delivered += len(
            _records_in_window(st, resident["id"], window_start, window_end)
        )
        attainment_total += dec(repr(plan["offered_attainment_pct"]))
        targets = plan["domain_frequency_targets"]
        for domain in C.DOMAINS:
            if int(targets.get(domain, 0)) <= 0:
                continue
            if not _domain_covered(st, resident["id"], plan, domain):
                unmet_domains += 1
        if resident["care_plan_review_due"] and (
            resident["enrollment_gate"] == "THERAPIST_REVIEW"
        ):
            unaddressed += 1

    unscreened = unscreened_volunteer_count(st, window_start, window_end)

    if not cohort:
        base_score = rhu(0, 1)
    else:
        base_score = rhu(divide(attainment_total, len(cohort)), 1)
    domain_penalty = rhu(dec(C.DOMAIN_PENALTY) * unmet_domains, 1)
    refusal_penalty = rhu(dec(C.REFUSAL_PENALTY_PER_RESIDENT) * unaddressed, 1)
    preliminary = base_score - domain_penalty - refusal_penalty
    if preliminary < 0:
        preliminary = dec(0)
    preliminary = rhu(preliminary, 1)

    flags = []
    if preliminary < dec(C.F248_THRESHOLD):
        flags.append(C.FLAG_INSUFFICIENT_FREQUENCY)
    if unaddressed > 0:
        flags.append(C.FLAG_UNADDRESSED_REFUSAL)
    if unscreened > 0:
        flags.append(C.FLAG_UNSCREENED_VOLUNTEER)
    flags.sort()

    provision = preliminary - dec(C.DEFICIENCY_PENALTY) * len(flags)
    if provision < 0:
        provision = dec(0)
    provision = rhu(provision, 1)

    return {
        "cohort_resident_count": len(cohort),
        "offered_sessions_targeted": targeted,
        "offered_sessions_delivered": delivered,
        "base_score": float(base_score),
        "domain_coverage_penalty": float(domain_penalty),
        "refusal_penalty": float(refusal_penalty),
        "preliminary_score": float(preliminary),
        "deficiency_flags": flags,
        "provision_score": float(provision),
    }
