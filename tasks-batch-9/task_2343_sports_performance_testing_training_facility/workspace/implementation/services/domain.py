"""Cross-entity domain logic: derived fields, state transitions and cascades."""

from decimal import Decimal

from db import (add_days, now, ordered, parse_date, parse_instant, sort_key,
                store, today, touch)
from errors import ApiError
from services import calc

OPEN_RTS_STATUSES = ("STAGE_ACTIVE", "STAGE_TESTING", "MEDICAL_REVIEW")
ACTIVE_ENROLLMENT_STATUSES = ("RESERVED", "WAITLISTED", "ATTENDED", "NO_SHOW")
OPEN_SESSION_STATUSES = ("SCHEDULED", "ROSTER_LOCKED")


# --------------------------------------------------------------- athletes ----
def athlete_age_years(athlete, reference_date=None):
    dob = parse_date(athlete["date_of_birth"])
    return calc.age_years_from(dob, reference_date or today())


def open_rts_plan(athlete_id):
    for plan in ordered(store.rts_plans):
        if plan["athlete_id"] == athlete_id and plan["status"] in OPEN_RTS_STATUSES:
            return plan
    return None


def active_rehab_count(athlete_id):
    return sum(
        1
        for record in store.injury_records.values()
        if record["athlete_id"] == athlete_id and record["status"] == "ACTIVE_REHAB"
    )


def athlete_readiness(athlete):
    days_since = 0
    last = athlete.get("last_performance_test_at")
    if last:
        last_dt = parse_instant(last)
        delta = now() - last_dt
        seconds = int(delta.total_seconds())
        if seconds < 0:
            seconds = 0
        days_since = seconds // 86400
    return calc.readiness_index(
        athlete.get("last_composite_percentile"),
        days_since,
        athlete.get("attended_count", 0),
        athlete.get("no_show_count", 0),
        open_rts_plan(athlete["id"]) is not None,
    )


def enforce_athlete_scope(ctx, athlete):
    """Tier 6 - ownership scoping for the two athlete-facing roles."""
    if not ctx.is_athlete_role:
        return
    if not ctx.user_id or ctx.user_id != athlete["id"]:
        raise ApiError("ERR_ATHLETE_SCOPE_VIOLATION", "Caller may only access their own athlete record")
    if ctx.role == "Guardian":
        if athlete_age_years(athlete) >= 18 or not athlete.get("guardian_email"):
            raise ApiError(
                "ERR_ATHLETE_SCOPE_VIOLATION",
                "Guardian access requires a minor athlete with a guardian_email on file",
            )


def finalized_batteries(athlete_id):
    """Finalized PERFORMANCE_BATTERY sessions, finalized_at DESC then created_at DESC."""
    rows = [
        t
        for t in store.test_sessions.values()
        if t["athlete_id"] == athlete_id
        and t["battery_type"] == "PERFORMANCE_BATTERY"
        and t["status"] == "FINALIZED"
    ]
    rows.sort(key=lambda t: (t["finalized_at"] or "", t["created_at"], t["_seq"]), reverse=True)
    return rows


def apply_screen_clearance(athlete, risk_score):
    """training_clearance transitions driven by a finalized movement screen."""
    current = athlete["training_clearance"]
    if current == "MEDICAL_HOLD":
        return
    restricted = risk_score >= calc.RESTRICTED_RISK_THRESHOLD
    if current == "SCREEN_PENDING":
        athlete["training_clearance"] = "RESTRICTED" if restricted else "CLEARED"
    elif current == "CLEARED":
        if restricted:
            athlete["training_clearance"] = "RESTRICTED"
    elif current == "RESTRICTED":
        if not restricted and open_rts_plan(athlete["id"]) is None:
            athlete["training_clearance"] = "CLEARED"


# ---------------------------------------------------------- group session ----
def session_enrollments(group_session_id):
    return sorted(
        [e for e in store.enrollments.values() if e["group_session_id"] == group_session_id],
        key=sort_key,
    )


def athlete_units_for(enrollments):
    units = Decimal("0")
    for enrollment in enrollments:
        if enrollment["status"] not in ("RESERVED", "ATTENDED"):
            continue
        athlete = store.athletes.get(enrollment["athlete_id"])
        if athlete is None:
            continue
        units += calc.athlete_unit(
            athlete_age_years(athlete), open_rts_plan(athlete["id"]) is not None
        )
    return units


def compliant_coach_count(session):
    count = 0
    for row in session["assigned_staff"]:
        staff = store.staff_members.get(row["staff_member_id"])
        if staff is not None and staff["credential_status"] != "LAPSED":
            count += 1
    return count


def staffing_status_for(session, compliant, required):
    # PRD 3.4 step 3: when the credential-review lapse cascade strips a coach off a
    # future session, "each affected session's staffing_status becomes UNDERSTAFFED"
    # - the session never falls back to the pristine STAFF_PENDING value even though
    # assigned_staff is empty again.  The latch records that a cascade has run.
    if compliant == 0 and not session["assigned_staff"] and not session.get("_lapse_understaffed"):
        return "STAFF_PENDING"
    if compliant < required:
        return "UNDERSTAFFED"
    return "STAFFED"


def session_derived(session, extra_units=Decimal("0")):
    enrollments = session_enrollments(session["id"])
    units = calc.rhu(athlete_units_for(enrollments) + extra_units, 1)
    required = calc.required_coach_count(units, session["site_code"], session["station_count"])
    compliant = compliant_coach_count(session)
    counts = {"RESERVED": 0, "WAITLISTED": 0, "ATTENDED": 0, "NO_SHOW": 0}
    for enrollment in enrollments:
        if enrollment["status"] in counts:
            counts[enrollment["status"]] += 1
    return {
        "athlete_units": units,
        "required_coach_count": required,
        "compliant_coach_count": compliant,
        "staffing_status": staffing_status_for(session, compliant, required),
        "reserved_count": counts["RESERVED"],
        "waitlisted_count": counts["WAITLISTED"],
        "attended_count": counts["ATTENDED"],
        "no_show_count": counts["NO_SHOW"],
    }


def apply_staffing_side_effects(session):
    """A locked roster reverts to SCHEDULED the moment staffing slips."""
    derived = session_derived(session)
    if derived["staffing_status"] != "STAFFED" and session["session_status"] == "ROSTER_LOCKED":
        session["session_status"] = "SCHEDULED"
        touch(session)
        for enrollment in session_enrollments(session["id"]):
            if enrollment["station_number"] is not None:
                enrollment["station_number"] = None
                touch(enrollment)


def assign_stations(session):
    """Station rotation over RESERVED rows, created_at ASC, 1-based wrap."""
    reserved = [e for e in session_enrollments(session["id"]) if e["status"] == "RESERVED"]
    station_count = session["station_count"]
    for index, enrollment in enumerate(reserved):
        enrollment["station_number"] = 1 + (index % station_count)
        touch(enrollment)


def recompute_athlete_sessions(athlete):
    """An athlete's unit weighting changed - refresh every roster they hold."""
    seen = set()
    for enrollment in ordered(store.enrollments):
        if enrollment["athlete_id"] != athlete["id"]:
            continue
        if enrollment["status"] not in ("RESERVED", "ATTENDED"):
            continue
        session = store.group_sessions.get(enrollment["group_session_id"])
        if session is None or session["id"] in seen:
            continue
        seen.add(session["id"])
        apply_staffing_side_effects(session)


def sessions_for_staff(staff_id):
    return [
        s
        for s in ordered(store.group_sessions)
        if any(row["staff_member_id"] == staff_id for row in s["assigned_staff"])
    ]


# ----------------------------------------------------------------- funding ----
def allocate_funding(enrollment, athlete, session):
    """Waterfall allocation (PRD 3.7).  Raises ApiError when no bucket resolves."""
    session_date = session["_start_at"].date()
    contract_id = athlete.get("team_contract_id")
    contract = store.team_contracts.get(contract_id) if contract_id else None

    if contract is not None and contract["status"] == "ACTIVE":
        if session["site_code"] == "OFFSITE" and contract["offsite_sessions_used"] >= contract["offsite_allowance"]:
            raise ApiError(
                "ERR_OFFSITE_ALLOWANCE_EXHAUSTED",
                "The team contract has no offsite allowance left",
            )
        within_term = (
            parse_date(contract["term_start"]) <= session_date <= parse_date(contract["term_end"])
        )
        if contract["sessions_available"] >= 1 and within_term:
            enrollment["funding_source"] = "TEAM_CONTRACT"
            enrollment["membership_package_id"] = None
            enrollment["charge_cents"] = 0
            enrollment["_team_contract_id"] = contract["id"]
            contract["sessions_available"] -= 1
            contract["sessions_reserved"] += 1
            if session["site_code"] == "OFFSITE":
                contract["offsite_sessions_used"] += 1
            touch(contract)
            return

    candidates = [
        p
        for p in store.membership_packages.values()
        if p["athlete_id"] == athlete["id"]
        and p["status"] == "ACTIVE"
        and p["sessions_remaining"] >= 1
        and parse_date(p["effective_expires_on"]) >= session_date
    ]
    candidates.sort(key=lambda p: (p["effective_expires_on"], p["created_at"], p["_seq"]))
    if candidates:
        package = candidates[0]
        enrollment["funding_source"] = "MEMBERSHIP_PACKAGE"
        enrollment["membership_package_id"] = package["id"]
        enrollment["charge_cents"] = 0
        package["sessions_remaining"] -= 1
        package["sessions_reserved"] += 1
        if package["sessions_remaining"] == 0:
            package["status"] = "DEPLETED"
        touch(package)
        return

    if enrollment["funding_preference"] == "PACKAGE_ONLY":
        owned = [p for p in store.membership_packages.values() if p["athlete_id"] == athlete["id"]]
        if owned and all(
            p["status"] == "EXPIRED" or parse_date(p["effective_expires_on"]) < session_date
            for p in owned
        ):
            raise ApiError("ERR_PACKAGE_EXPIRED", "Every package the athlete owns has expired")
        raise ApiError("ERR_NO_SESSION_CREDIT", "The athlete has no session credit for this booking")

    enrollment["funding_source"] = "DROP_IN"
    enrollment["membership_package_id"] = None
    enrollment["charge_cents"] = calc.drop_in_charge_cents(session["site_code"])


def refund_funding(enrollment, session):
    """Return the consumed credit to its source (PRD 2.10)."""
    source = enrollment.get("funding_source")
    if source == "MEMBERSHIP_PACKAGE" and enrollment.get("membership_package_id"):
        package = store.membership_packages.get(enrollment["membership_package_id"])
        if package is not None:
            package["sessions_reserved"] -= 1
            package["sessions_remaining"] += 1
            if package["status"] == "DEPLETED" and package["sessions_remaining"] >= 1:
                package["status"] = "ACTIVE"
            touch(package)
    elif source == "TEAM_CONTRACT":
        contract = store.team_contracts.get(enrollment.get("_team_contract_id"))
        if contract is not None:
            contract["sessions_reserved"] -= 1
            contract["sessions_available"] += 1
            if session["site_code"] == "OFFSITE" and contract["offsite_sessions_used"] > 0:
                contract["offsite_sessions_used"] -= 1
            touch(contract)


def forfeit_funding_late_cancel(enrollment, session):
    source = enrollment.get("funding_source")
    if source == "MEMBERSHIP_PACKAGE" and enrollment.get("membership_package_id"):
        package = store.membership_packages.get(enrollment["membership_package_id"])
        if package is not None:
            package["sessions_reserved"] -= 1
            package["sessions_forfeited"] += 1
            touch(package)
    elif source == "TEAM_CONTRACT":
        contract = store.team_contracts.get(enrollment.get("_team_contract_id"))
        if contract is not None:
            contract["sessions_reserved"] -= 1
            contract["sessions_delivered"] += 1
            touch(contract)


def consume_package_credit(enrollment):
    if enrollment.get("funding_source") == "MEMBERSHIP_PACKAGE" and enrollment.get("membership_package_id"):
        package = store.membership_packages.get(enrollment["membership_package_id"])
        if package is not None:
            package["sessions_reserved"] -= 1
            package["sessions_consumed"] += 1
            touch(package)


def forfeit_package_credit(enrollment):
    if enrollment.get("funding_source") == "MEMBERSHIP_PACKAGE" and enrollment.get("membership_package_id"):
        package = store.membership_packages.get(enrollment["membership_package_id"])
        if package is not None:
            package["sessions_reserved"] -= 1
            package["sessions_forfeited"] += 1
            touch(package)


def unconsume_package_credit(enrollment):
    if enrollment.get("funding_source") == "MEMBERSHIP_PACKAGE" and enrollment.get("membership_package_id"):
        package = store.membership_packages.get(enrollment["membership_package_id"])
        if package is not None:
            package["sessions_consumed"] -= 1
            package["sessions_reserved"] += 1
            touch(package)


# -------------------------------------------------------------- waitlist ----
def promote_waitlist(session):
    """At most one promotion per freed roster slot (PRD 2.10)."""
    if session["session_status"] not in OPEN_SESSION_STATUSES:
        return
    while True:
        derived = session_derived(session)
        if derived["reserved_count"] >= session["max_athletes"]:
            return
        waiting = [e for e in session_enrollments(session["id"]) if e["status"] == "WAITLISTED"]
        if not waiting:
            return
        candidate = waiting[0]
        athlete = store.athletes.get(candidate["athlete_id"])
        try:
            allocate_funding(candidate, athlete, session)
        except ApiError:
            candidate["status"] = "CANCELED"
            candidate["cancel_reason"] = "FUNDING_UNAVAILABLE"
            touch(candidate)
            touch(session)
            continue
        candidate["status"] = "RESERVED"
        candidate["promoted_from_waitlist"] = True
        touch(candidate)
        touch(session)
        return


# ------------------------------------------------------------- cascades ----
def cancel_forward_book(athlete, cancel_reason, statuses=("RESERVED", "WAITLISTED")):
    """Cancel and refund the athlete's future bookings, then run promotions."""
    freed_sessions = []
    for enrollment in ordered(store.enrollments):
        if enrollment["athlete_id"] != athlete["id"]:
            continue
        if enrollment["status"] not in statuses:
            continue
        session = store.group_sessions.get(enrollment["group_session_id"])
        if session is None or session["session_status"] not in OPEN_SESSION_STATUSES:
            continue
        if not session["_start_at"] > now():
            continue
        was_reserved = enrollment["status"] == "RESERVED"
        if was_reserved:
            refund_funding(enrollment, session)
        enrollment["status"] = "CANCELED"
        enrollment["cancel_reason"] = cancel_reason
        enrollment["station_number"] = None
        touch(enrollment)
        touch(session)
        if was_reserved and session["id"] not in [s["id"] for s in freed_sessions]:
            freed_sessions.append(session)
    for session in freed_sessions:
        promote_waitlist(session)
        apply_staffing_side_effects(session)


def suspend_athlete(athlete, statuses=("RESERVED", "WAITLISTED")):
    athlete["membership_status"] = "SUSPENDED"
    touch(athlete)
    cancel_forward_book(athlete, "ATHLETE_SUSPENDED", statuses)


def place_on_medical_hold(athlete):
    athlete["training_clearance"] = "MEDICAL_HOLD"
    touch(athlete)
    cancel_forward_book(athlete, "ATHLETE_SUSPENDED")


def mark_no_show(enrollment, session):
    """No-show cascade: strike, fee, credit forfeit, possible suspension."""
    athlete = store.athletes[enrollment["athlete_id"]]
    enrollment["status"] = "NO_SHOW"
    athlete["no_show_count"] += 1
    athlete["no_show_strikes"] += 1
    strike_index = athlete["no_show_strikes"]
    enrollment["strike_index_at_no_show"] = strike_index
    enrollment["no_show_fee_cents"] = calc.no_show_fee_cents(strike_index)
    forfeit_package_credit(enrollment)
    touch(enrollment)
    touch(athlete)
    touch(session)
    if strike_index >= calc.NO_SHOW_SUSPENSION_THRESHOLD and athlete["membership_status"] == "ACTIVE":
        suspend_athlete(athlete, statuses=("RESERVED",))


# ------------------------------------------------------------ staff/certs ----
def staff_certifications(staff_id):
    return [
        c for c in ordered(store.certifications) if c["staff_member_id"] == staff_id
    ]


def refresh_staff_counters(staff):
    certs = staff_certifications(staff["id"])
    staff["valid_certification_count"] = sum(1 for c in certs if c["status"] in ("VALID", "EXPIRING"))
    staff["lapsed_certification_count"] = sum(1 for c in certs if c["status"] == "LAPSED")
    staff["ceu_credits_earned_total"] = sum(c["ceu_credits_earned"] for c in certs)
    return certs


def derive_credential_status(staff):
    certs = refresh_staff_counters(staff)
    insurance = parse_date(staff["liability_insurance_expires_on"])
    if (
        staff["lapsed_certification_count"] >= 1
        or (insurance is not None and insurance < today())
        or staff["valid_certification_count"] == 0
    ):
        return "LAPSED"
    if any(c["status"] == "EXPIRING" for c in certs):
        return "EXPIRING"
    return "COMPLIANT"


def apply_credential_status(staff, new_status, remove_from_future_sessions=False):
    staff["credential_status"] = new_status
    if new_status == "LAPSED" and remove_from_future_sessions:
        for session in sessions_for_staff(staff["id"]):
            if session["session_status"] not in OPEN_SESSION_STATUSES:
                continue
            if not session["_start_at"] > now():
                continue
            before = len(session["assigned_staff"])
            session["assigned_staff"] = [
                row for row in session["assigned_staff"] if row["staff_member_id"] != staff["id"]
            ]
            if len(session["assigned_staff"]) != before:
                session["_lapse_understaffed"] = True
            touch(session)
            apply_staffing_side_effects(session)
    for session in sessions_for_staff(staff["id"]):
        apply_staffing_side_effects(session)


def credential_gate(staff):
    """Tier 11 - staff safety gate (PRD 3.4)."""
    insurance = parse_date(staff["liability_insurance_expires_on"])
    if staff["credential_status"] == "LAPSED" or (insurance is not None and insurance < today()):
        raise ApiError(
            "ERR_STAFF_CREDENTIAL_LAPSED",
            "The acting or assigned staff member's credentials are not current",
        )


# --------------------------------------------------------- clock sweeping ----
def sweep_clock(new_clock):
    """Only two sweeps run on a clock advance (PRD 2.4)."""
    new_date = new_clock.date()
    documents_expired = 0
    for document in ordered(store.clearance_documents):
        if document["status"] != "SIGNED":
            continue
        expires_on = parse_date(document["expires_on"])
        if expires_on is not None and expires_on < new_date:
            document["status"] = "EXPIRED"
            touch(document)
            documents_expired += 1
    packages_expired = 0
    for package in ordered(store.membership_packages):
        if package["status"] not in ("ACTIVE", "FROZEN", "DEPLETED"):
            continue
        effective = parse_date(package["effective_expires_on"])
        if effective is not None and effective < new_date:
            remaining = package["sessions_remaining"]
            if remaining:
                package["sessions_forfeited"] += remaining
                package["sessions_remaining"] = 0
            package["status"] = "EXPIRED"
            touch(package)
            packages_expired += 1
    return documents_expired, packages_expired


def recompute_package_expiry(package):
    package["effective_expires_on"] = add_days(
        parse_date(package["expires_on"]), package["frozen_days_total"]
    ).isoformat()


def next_test_due_on(finalized_date):
    return add_days(finalized_date, calc.TEST_CADENCE_DAYS).isoformat()
