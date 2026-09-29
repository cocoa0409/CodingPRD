"""Plan attainment (both variants) and resident metric refresh."""
from datetime import timedelta

from db import parse_datetime
from services import clinical
from services import constants as C
from services.numbers import dec, divide, rhu


def plan_window(plan):
    lo = parse_datetime(plan["cycle_start_at"])
    return lo, lo + timedelta(days=C.CYCLE_DAYS)


def live_plans(st, resident_id):
    return [
        p
        for p in st.plans.values()
        if p["resident_id"] == resident_id and p["status"] in C.LIVE_PLAN_STATUSES
    ]


def live_plan(st, resident_id):
    rows = sorted(
        live_plans(st, resident_id),
        key=lambda p: (p["created_at"], p["_seq"]),
        reverse=True,
    )
    return rows[0] if rows else None


def _session_domain(st, record):
    session = st.sessions.get(record["session_id"])
    if session is None:
        return None, None
    program = st.programs.get(session["program_id"])
    return (program["domain"] if program else None), session


def _qualifies(outcome, record, variant):
    if variant == "credited":
        return outcome == "ATTENDED" and record.get("engagement_level") in (
            C.CREDITED_ENGAGEMENT
        )
    return outcome in C.OFFERED_OUTCOMES


def attainment(st, plan, variant):
    """Cap each domain ratio at 1.0, average, multiply by 100, round once."""
    targets = plan["domain_frequency_targets"]
    scored = [d for d in C.DOMAINS if int(targets.get(d, 0)) > 0]
    if not scored:
        return float(rhu(0, 1))
    lo, hi = plan_window(plan)
    records = clinical.resident_records(st, plan["resident_id"])
    total = dec(0)
    for domain in scored:
        target = int(targets[domain])
        count = 0
        for record in records:
            outcome = clinical.record_outcome(record)
            if not _qualifies(outcome, record, variant):
                continue
            record_domain, session = _session_domain(st, record)
            if record_domain != domain or session is None:
                continue
            starts_at = parse_datetime(session["starts_at"])
            if starts_at is None or not (lo <= starts_at < hi):
                continue
            count += 1
        ratio = divide(count, target)
        if ratio > 1:
            ratio = dec(1)
        total += ratio
    average = divide(total, len(scored)) * 100
    return float(rhu(average, 1))


def recompute_plan(st, plan, ctx):
    """Frozen plans (DRAFT, SUPERSEDED, CLOSED) are never recomputed."""
    if plan["status"] not in C.LIVE_PLAN_STATUSES:
        return
    ctx.set_fields(
        plan,
        {
            "credited_attainment_pct": attainment(st, plan, "credited"),
            "offered_attainment_pct": attainment(st, plan, "offered"),
        },
    )


def recompute_resident_plans(st, resident_id, ctx):
    for plan in live_plans(st, resident_id):
        recompute_plan(st, plan, ctx)


def recompute_all_live_plans(st, ctx):
    for plan in list(st.plans.values()):
        recompute_plan(st, plan, ctx)


def refresh_resident_metrics(st, resident, ctx, skip_engagement=False):
    values = {
        "refusal_streak": clinical.refusal_streak(st, resident["id"]),
        "absence_count": clinical.absence_count(st, resident["id"]),
    }
    if not skip_engagement:
        values["engagement_index"] = clinical.engagement_index(st, resident["id"])
    ctx.set_fields(resident, values)


def release_gate(resident, ctx):
    ctx.set_fields(
        resident, {"care_plan_review_due": False, "enrollment_gate": "NONE"}
    )


def raise_gate(resident, ctx):
    ctx.set_fields(
        resident,
        {"care_plan_review_due": True, "enrollment_gate": "THERAPIST_REVIEW"},
    )
