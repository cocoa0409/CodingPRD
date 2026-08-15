"""Derived counters, conserved ledgers, and calculations."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import store, clock, new_id, now_iso, _parse_iso, _fmt_ts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

Q4 = Decimal("0.0001")


def q4(value):
    return float(Decimal(str(value)).quantize(Q4, rounding=ROUND_HALF_UP))


def q0(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Program / cycle derived counters
# ---------------------------------------------------------------------------

def recompute_program(p):
    """Recompute a program's derived counters, ledgers, and intake posture."""
    apps = [a for a in store.applications.values() if a["program_id"] == p["id"]]
    p["admitted_count"] = sum(1 for a in apps if a["status"] == "ADMITTED")
    p["deposited_count"] = sum(1 for a in apps if a["status"] == "DEPOSITED")
    p["enrolled_count"] = sum(1 for a in apps if a["status"] == "ENROLLED")
    p["seats_open"] = p["capacity_seats"] - p["deposited_count"] - p["enrolled_count"]

    committed = 0
    for a in apps:
        for o in store.aid_offers.values():
            if o["application_id"] == a["id"] and o["status"] in ("OFFERED", "ACCEPTED"):
                committed += o["amount_cents"]
    p["scholarship_committed_cents"] = committed
    p["scholarship_available_cents"] = p["scholarship_budget_cents"] - committed

    cycle = store.cycles.get(p["cycle_id"])
    cycle_status = cycle["status"] if cycle else "SETUP"
    if cycle_status == "CLOSED":
        p["intake_posture"] = "CLOSED"
    elif (p["deposited_count"] + p["enrolled_count"]) >= p["target_enrollment"]:
        p["intake_posture"] = "PAUSED"
    elif cycle_status in ("OPEN", "REVIEW_CLOSED", "DECISIONS_RELEASED", "ENROLLMENT_TRACKING"):
        p["intake_posture"] = "OPEN"
    else:
        # Cycle in SETUP: no posture defined by spec; treat as PAUSED (not OPEN).
        p["intake_posture"] = "PAUSED"


def recompute_cycle(c):
    """Recompute a cycle's funnel aggregates."""
    apps = [a for a in store.applications.values() if a["cycle_id"] == c["id"]]
    c["inquiry_count"] = sum(1 for a in store.applicants.values() if a["cycle_id"] == c["id"])
    c["application_count"] = len(apps)
    c["admitted_count"] = sum(1 for a in apps if a["status"] == "ADMITTED")
    c["deposited_count"] = sum(1 for a in apps if a["status"] == "DEPOSITED")
    c["enrolled_count"] = sum(1 for a in apps if a["status"] == "ENROLLED")
    # decisioned: currently ADMITTED/DEPOSITED/ENROLLED/MELTED, or WITHDRAWN after
    # admission, or DENIED. We track ever_admitted via a private flag.
    ever_admitted = sum(1 for a in apps if a.get("_ever_admitted"))
    denied = sum(1 for a in apps if a["status"] == "DENIED")
    c["decisioned_count"] = ever_admitted + denied
    if c["decisioned_count"] > 0:
        c["admit_rate"] = q4(Decimal(ever_admitted) / Decimal(c["decisioned_count"]))
    else:
        c["admit_rate"] = 0.0


def recompute_all_programs_of_cycle(cycle_id):
    for p in store.programs.values():
        if p["cycle_id"] == cycle_id:
            recompute_program(p)


def recompute_application_aid_fields(app):
    """aid_accepted_cents, aid_gap_cents from ACCEPTED offers."""
    total = sum(
        o["amount_cents"]
        for o in store.aid_offers.values()
        if o["application_id"] == app["id"] and o["status"] == "ACCEPTED"
    )
    app["aid_accepted_cents"] = total
    program = store.programs.get(app["program_id"])
    tuition = program["tuition_cents"] if program else 0
    app["aid_gap_cents"] = max(0, tuition - total)


def recompute_submitted_read_count(app):
    app["submitted_read_count"] = sum(
        1
        for r in store.reviews.values()
        if r["application_id"] == app["id"] and r["status"] == "SUBMITTED"
    )


# ---------------------------------------------------------------------------
# Melt risk
# ---------------------------------------------------------------------------

MELT_RISK_THRESHOLD = Decimal("0.70")
TIME_FACTOR_FULL_DAYS = 30
DISTANCE_FACTORS = {"LOCAL": 0.0, "REGIONAL": 0.3, "NATIONAL": 0.6, "INTERNATIONAL": 1.0}


def recompute_melt_risk(app, auto_intervention=True):
    """Recompute app.melt_risk_score; optionally auto-create threshold intervention."""
    if app["status"] != "DEPOSITED":
        return
    program = store.programs.get(app["program_id"])
    applicant = store.applicants.get(app["applicant_id"])
    cycle = store.cycles.get(app["cycle_id"])
    if not program or not applicant or not cycle:
        return

    tuition = program["tuition_cents"]
    if tuition and tuition > 0:
        aid_gap_factor = q4(min(1.0, app["aid_gap_cents"] / tuition))
    else:
        aid_gap_factor = 0.0

    distance_factor = DISTANCE_FACTORS.get(applicant["distance_band"], 0.0)

    engaged = any(
        i["application_id"] == app["id"]
        and i["status"] == "COMPLETED"
        and i.get("outcome") in ("REACHED_ENGAGED", "REACHED_CONFIRMED")
        for i in store.interventions.values()
    )
    engagement_factor = 0.0 if engaged else 1.0

    # time factor: whole days between paid_at and now / 30, capped at 1
    paid_deposit = next(
        (d for d in store.deposits.values()
         if d["application_id"] == app["id"] and d["status"] == "PAID"),
        None,
    )
    if paid_deposit:
        paid_at = _parse_iso(paid_deposit["paid_at"])
        now = clock.now()
        days = (now - paid_at).total_seconds() / 86400.0
        whole_days = int(days)
        time_factor = q4(min(1.0, whole_days / TIME_FACTOR_FULL_DAYS))
    else:
        time_factor = 0.0

    deadline = _parse_iso(cycle["deposit_deadline_at"])
    now = clock.now()
    if now <= deadline:
        # standard variant: 0.40/0.25/0.20/0.15
        products = [
            Decimal(str(0.40)) * Decimal(str(aid_gap_factor)),
            Decimal(str(0.25)) * Decimal(str(distance_factor)),
            Decimal(str(0.20)) * Decimal(str(engagement_factor)),
            Decimal(str(0.15)) * Decimal(str(time_factor)),
        ]
    else:
        # summer window: 0.50/0.30/0.20
        products = [
            Decimal(str(0.50)) * Decimal(str(aid_gap_factor)),
            Decimal(str(0.30)) * Decimal(str(engagement_factor)),
            Decimal(str(0.20)) * Decimal(str(time_factor)),
        ]
    rounded_products = [p.quantize(Q4, rounding=ROUND_HALF_UP) for p in products]
    total = sum(rounded_products, Decimal("0")).quantize(Q4, rounding=ROUND_HALF_UP)
    app["melt_risk_score"] = float(total)

    if auto_intervention and app["status"] == "DEPOSITED" and total >= MELT_RISK_THRESHOLD:
        has_scheduled = any(
            i["application_id"] == app["id"] and i["status"] == "SCHEDULED"
            for i in store.interventions.values()
        )
        if not has_scheduled:
            start = clock.now()
            end = start + timedelta(days=7)
            intervention = {
                "id": new_id(),
                "application_id": app["id"],
                "advisor_id": "AUTO_QUEUE",
                "intervention_type": "EMAIL_CAMPAIGN",
                "window_start_at": _fmt_ts(start),
                "window_end_at": _fmt_ts(end),
                "trigger_source": "AUTO_THRESHOLD",
                "outcome": None,
                "status": "SCHEDULED",
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "version": 1,
            }
            store.interventions[intervention["id"]] = intervention


def sweep_melt_risk_all_deposited():
    for app in store.applications.values():
        if app["status"] == "DEPOSITED":
            recompute_melt_risk(app)


# ---------------------------------------------------------------------------
# Aid leveraging
# ---------------------------------------------------------------------------

MERIT_MAX_CENTS = 2500000
NEED_MAX_CENTS = 3000000
NEED_TUITION_COVER_RATE = Decimal("0.60")


def compute_aid_award(application, program, fund_type):
    """Return (base, award) cents. Caller checks base==0 and available==0 errors."""
    tuition = program["tuition_cents"]
    if fund_type == "MERIT":
        score = application["academic_score"]
        if score >= 95:
            tier = Decimal("0.50")
        elif score >= 90:
            tier = Decimal("0.35")
        elif score >= 80:
            tier = Decimal("0.20")
        else:
            tier = Decimal("0")
        base = q0(tier * Decimal(tuition))
        base = min(base, MERIT_MAX_CENTS)
    else:  # NEED_BASED
        need_base = max(0, tuition - application["efc_cents"])
        base = q0(min(Decimal(need_base), NEED_TUITION_COVER_RATE * Decimal(tuition)))
        base = min(base, NEED_MAX_CENTS)
    available = program["scholarship_available_cents"]
    award = min(base, available)
    return base, award


# ---------------------------------------------------------------------------
# Waitlist
# ---------------------------------------------------------------------------

def compute_waitlist_rank_score(application):
    submitted = [
        r for r in store.reviews.values()
        if r["application_id"] == application["id"] and r["status"] == "SUBMITTED"
    ]
    admit_recs = sum(1 for r in submitted if r.get("recommendation") == "ADMIT")
    rec_strength = (100.0 * admit_recs / len(submitted)) if submitted else 0.0
    score = 0.6 * application["academic_score"] + 0.4 * rec_strength
    return q4(score)


def select_top_waitlist_entry(program_id):
    """Return top-ranked ACTIVE entry of program, or None."""
    candidates = [
        e for e in store.waitlist_entries.values()
        if e["program_id"] == program_id and e["status"] == "ACTIVE"
    ]
    if not candidates:
        return None

    def key(e):
        app = store.applications.get(e["application_id"])
        submitted_at = _parse_iso(app["submitted_at"]) if app else None
        return (-e["rank_score"], submitted_at)

    candidates.sort(key=key)
    return candidates[0]


def activate_waitlist_entry(entry):
    """ACTIVE -> ACTIVATED; application WAITLISTED -> ADMITTED."""
    entry["status"] = "ACTIVATED"
    from services.serializers import touch
    touch(entry)
    app = store.applications.get(entry["application_id"])
    if app and app["status"] == "WAITLISTED":
        app["status"] = "ADMITTED"
        app["_ever_admitted"] = True
        touch(app)
    program = store.programs.get(entry["program_id"])
    if program:
        recompute_program(program)
        touch(program)
        cycle = store.cycles.get(program["cycle_id"])
        if cycle:
            recompute_cycle(cycle)


def cancel_assigned_reviews(application_id):
    from services.serializers import touch
    for r in store.reviews.values():
        if r["application_id"] == application_id and r["status"] == "ASSIGNED":
            r["status"] = "CANCELLED"
            touch(r)


def revoke_aid_offers(application_id, statuses):
    from services.serializers import touch
    for o in store.aid_offers.values():
        if o["application_id"] == application_id and o["status"] in statuses:
            o["status"] = "REVOKED"
            touch(o)
    app = store.applications.get(application_id)
    if app:
        recompute_application_aid_fields(app)
        recompute_melt_risk(app)
        program = store.programs.get(app["program_id"])
        if program:
            recompute_program(program)


def maybe_auto_activate(program):
    """Auto-activate top waitlist entry if flag set and posture OPEN."""
    if not program.get("auto_waitlist_activation"):
        return None
    recompute_program(program)
    if program["intake_posture"] != "OPEN":
        return None
    entry = select_top_waitlist_entry(program["id"])
    if not entry:
        return None
    activate_waitlist_entry(entry)
    return entry
