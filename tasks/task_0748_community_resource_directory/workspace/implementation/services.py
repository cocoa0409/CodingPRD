"""Business logic: entity constructors, state transitions, calculations, cascades."""
from datetime import datetime, timedelta, timezone

from db import db
from util import fmt_ts, half_up_2, half_up_int, floor_years_between, new_id, parse_ts


SPEED_KPH = {
    "PUBLIC_TRANSIT": 25.0,
    "CAR": 40.0,
    "WALKING": 5.0,
    "AGENCY_SHUTTLE": 20.0,
}
WINDING_FACTOR = 1.35
DEG_TO_KM = 111.0

URGENCY_MULT = {"ROUTINE": 1.00, "PRIORITY": 1.20, "EMERGENCY": 1.50}
REFERRAL_ACCEPT_THRESHOLD = 75.0

REFERRAL_INFLIGHT = {"PROPOSED", "ACCEPTED", "SERVICE_IN_PROGRESS"}
REFERRAL_TERMINAL = {"DECLINED", "COMPLETED_SUCCESS", "COMPLETED_UNSUCCESSFUL", "WITHDRAWN"}


# ---------- Common field helpers ----------

def _stamp_new(entity: dict, include_version: bool = True) -> None:
    now = db.clock
    entity["id"] = entity.get("id") or new_id()
    entity["created_at"] = fmt_ts(now)
    if include_version:
        entity["updated_at"] = fmt_ts(now)
        entity["version"] = 1


def _touch(entity: dict) -> None:
    entity["updated_at"] = fmt_ts(db.clock)
    entity["version"] = entity.get("version", 1) + 1


# ---------- Serialisation ----------

def serialise_funder(f: dict) -> dict:
    return {
        "id": f["id"],
        "name": f["name"],
        "fiscal_year_start_month": f["fiscal_year_start_month"],
        "grant_cents_total": f["grant_cents_total"],
        "grant_cents_remaining": f["grant_cents_remaining"],
        "reporting_currency": f["reporting_currency"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialise_provider(p: dict) -> dict:
    return {
        "id": p["id"],
        "legal_name": p["legal_name"],
        "location_lat": p["location_lat"],
        "location_lng": p["location_lng"],
        "accessibility_features": list(p["accessibility_features"]),
        "languages_supported": list(p["languages_supported"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialise_program(p: dict) -> dict:
    return {
        "id": p["id"],
        "provider_id": p["provider_id"],
        "funder_id": p["funder_id"],
        "category": p["category"],
        "eligibility_income_max_cents": p["eligibility_income_max_cents"],
        "eligibility_age_min": p["eligibility_age_min"],
        "eligibility_age_max": p["eligibility_age_max"],
        "unit_cost_cents": p["unit_cost_cents"],
        "capacity_slots_total": p["capacity_slots_total"],
        "capacity_slots_taken": p["capacity_slots_taken"],
        "intake_posture": p["intake_posture"],
        "funder_reporting_posture": p["funder_reporting_posture"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialise_availability(w: dict) -> dict:
    return {
        "id": w["id"],
        "program_id": w["program_id"],
        "start_ts": w["start_ts"],
        "end_ts": w["end_ts"],
        "max_slots": w["max_slots"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialise_client(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"],
        "monthly_income_cents": c["monthly_income_cents"],
        "home_lat": c["home_lat"],
        "home_lng": c["home_lng"],
        "preferred_language": c["preferred_language"],
        "accessibility_needs": list(c["accessibility_needs"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialise_intake(i: dict) -> dict:
    return {
        "id": i["id"],
        "client_id": i["client_id"],
        "presenting_needs": list(i["presenting_needs"]),
        "urgency": i["urgency"],
        "household_size": i["household_size"],
        "disability_flag": i["disability_flag"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialise_consent(c: dict) -> dict:
    return {
        "id": c["id"],
        "client_id": c["client_id"],
        "provider_id": c["provider_id"],
        "scope": c["scope"],
        "granted_at": c["granted_at"],
        "expires_at": c["expires_at"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialise_referral(r: dict) -> dict:
    return {
        "id": r["id"],
        "intake_id": r["intake_id"],
        "program_id": r["program_id"],
        "consent_grant_id": r["consent_grant_id"],
        "transport_mode": r["transport_mode"],
        "travel_burden_naive_min": r["travel_burden_naive_min"],
        "travel_burden_routed_min": r["travel_burden_routed_min"],
        "eligibility_score": r["eligibility_score"],
        "provisional_cost_cents": r["provisional_cost_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialise_transport(t: dict) -> dict:
    return {
        "id": t["id"],
        "referral_id": t["referral_id"],
        "pickup_start_ts": t["pickup_start_ts"],
        "pickup_end_ts": t["pickup_end_ts"],
        "mode": t["mode"],
        "cost_cents": t["cost_cents"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialise_outcome(o: dict) -> dict:
    return {
        "id": o["id"],
        "referral_id": o["referral_id"],
        "outcome": o["outcome"],
        "service_hours": o["service_hours"],
        "follow_up_needed": o["follow_up_needed"],
        "service_cost_final_cents": o["service_cost_final_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialise_funder_report(fr: dict) -> dict:
    # FunderReport carries only id and created_at (no updated_at, no version).
    return {
        "id": fr["id"],
        "funder_id": fr["funder_id"],
        "reporting_period_start": fr["reporting_period_start"],
        "reporting_period_end": fr["reporting_period_end"],
        "rounding_variant": fr["rounding_variant"],
        "total_referrals": fr["total_referrals"],
        "total_completions": fr["total_completions"],
        "total_disbursement_cents": fr["total_disbursement_cents"],
        "language_breakdown": dict(fr["language_breakdown"]),
        "created_at": fr["created_at"],
    }


# ---------- Calculations ----------

def compute_travel_burden(client: dict, provider: dict, transport_mode: str) -> tuple[float, float]:
    # Use Decimal arithmetic to preserve PRD's decimal-literal semantics and avoid
    # binary floating-point drift on values like |40.10 - 40.00| + |-74.05 - -74.00|.
    from decimal import Decimal, ROUND_HALF_UP

    d_client_lat = Decimal(str(client["home_lat"]))
    d_provider_lat = Decimal(str(provider["location_lat"]))
    d_client_lng = Decimal(str(client["home_lng"]))
    d_provider_lng = Decimal(str(provider["location_lng"]))
    dist_deg = abs(d_client_lat - d_provider_lat) + abs(d_client_lng - d_provider_lng)

    speed = Decimal(str(SPEED_KPH[transport_mode]))
    deg_to_km = Decimal(str(DEG_TO_KM))
    winding = Decimal(str(WINDING_FACTOR))
    sixty = Decimal("60.0")

    naive_km = dist_deg * deg_to_km
    naive_raw = (naive_km / speed) * sixty
    naive_min = float(naive_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    routed_km = dist_deg * deg_to_km * winding
    routed_raw = (routed_km / speed) * sixty
    routed_min = float(routed_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return naive_min, routed_min


def compute_eligibility_score(client: dict, intake: dict, program: dict, provider: dict) -> float:
    age_years = floor_years_between(client["date_of_birth"], db.clock)

    denom = max(program["eligibility_income_max_cents"], 1)
    income_ratio = client["monthly_income_cents"] / denom
    if income_ratio <= 0.50:
        income_score = 100.0
    elif income_ratio <= 0.80:
        income_score = 75.0
    elif income_ratio <= 1.00:
        income_score = 50.0
    else:
        income_score = 0.0

    if program["eligibility_age_min"] <= age_years <= program["eligibility_age_max"]:
        age_score = 100.0
    else:
        age_score = 0.0

    if program["category"] in intake["presenting_needs"]:
        category_score = 100.0
    else:
        category_score = 0.0

    if client["preferred_language"] in provider["languages_supported"]:
        language_match = 100.0
    else:
        language_match = 50.0

    if set(client["accessibility_needs"]).issubset(set(provider["accessibility_features"])):
        accessibility_match = 100.0
    else:
        accessibility_match = 0.0

    weighted = (
        0.30 * income_score
        + 0.20 * age_score
        + 0.25 * category_score
        + 0.15 * language_match
        + 0.10 * accessibility_match
    )
    mult = URGENCY_MULT[intake["urgency"]]
    return half_up_2(weighted * mult)


def compute_service_cost_final(outcome: str, service_hours: float, unit_cost_cents: int) -> int:
    if outcome == "UNMET":
        raw_ratio = 0.50
    else:
        raw_ratio = 0.50 + service_hours * 0.10
    raw_cents = unit_cost_cents * raw_ratio
    return half_up_int(raw_cents)


def raw_cost_float(outcome: str, service_hours: float, unit_cost_cents: int) -> float:
    if outcome == "UNMET":
        return unit_cost_cents * 0.50
    return unit_cost_cents * (0.50 + service_hours * 0.10)


# ---------- Utilisation posture recompute ----------

def recompute_program_posture(program: dict) -> bool:
    """Recompute intake_posture from capacity_slots_taken/total.
    Returns True if the posture changed (caller should bump version)."""
    taken = program["capacity_slots_taken"]
    total = program["capacity_slots_total"]
    if taken * 100 >= 100 * total:
        new_posture = "CLOSED"
    elif taken * 100 >= 80 * total:
        new_posture = "RESTRICTED"
    else:
        new_posture = "OPEN"
    if program["intake_posture"] != new_posture:
        program["intake_posture"] = new_posture
        return True
    return False


def increment_capacity(program: dict) -> None:
    """Increment program capacity_slots_taken by 1 and recompute posture.
    Always bumps program.version by 1 (creation of a referral is a program mutation).
    """
    program["capacity_slots_taken"] += 1
    recompute_program_posture(program)
    _touch(program)


def decrement_capacity(program: dict) -> None:
    """Decrement program capacity_slots_taken by 1 and recompute posture.
    Always bumps program.version by 1 (a referral exiting the in-flight set is a program mutation).
    """
    program["capacity_slots_taken"] -= 1
    if program["capacity_slots_taken"] < 0:
        program["capacity_slots_taken"] = 0
    recompute_program_posture(program)
    _touch(program)


# ---------- Grant ledger ----------

def recompute_grant_remaining(funder: dict) -> None:
    debit = 0
    for o in db.outcome_reports.values():
        if o["status"] != "ACTIVE":
            continue
        ref = db.referrals.get(o["referral_id"])
        if not ref:
            continue
        prog = db.programs.get(ref["program_id"])
        if not prog or prog["funder_id"] != funder["id"]:
            continue
        debit += o["service_cost_final_cents"]
    funder["grant_cents_remaining"] = funder["grant_cents_total"] - debit


# ---------- Intake bubble-up ----------

def maybe_bubble_intake_closed(intake_id: str) -> None:
    intake = db.intakes.get(intake_id)
    if not intake or intake["status"] != "SCREENED":
        return
    referrals = [r for r in db.referrals.values() if r["intake_id"] == intake_id]
    if not referrals:
        return
    if all(r["status"] in REFERRAL_TERMINAL for r in referrals):
        intake["status"] = "CLOSED"
        _touch(intake)


# ---------- Clock advance cascades ----------

def advance_clock(new_clock: datetime) -> None:
    old_clock = db.clock
    db.clock = new_clock

    # ConsentGrant GRANTED -> EXPIRED when expires_at <= new clock.
    for cg in db.consent_grants.values():
        if cg["status"] != "GRANTED":
            continue
        expires = parse_ts(cg["expires_at"])
        if expires <= new_clock:
            cg["status"] = "EXPIRED"
            _touch(cg)

    # Program funder_reporting_posture LOCKED -> ARCHIVED when a fiscal-year
    # rollover for the program's funder falls in (old_clock, new_clock].
    for prog in db.programs.values():
        if prog["funder_reporting_posture"] != "LOCKED":
            continue
        funder = db.funders.get(prog["funder_id"])
        if not funder:
            continue
        if _fiscal_rollover_in(old_clock, new_clock, funder["fiscal_year_start_month"]):
            prog["funder_reporting_posture"] = "ARCHIVED"
            _touch(prog)


def _fiscal_rollover_in(old_clock: datetime, new_clock: datetime, month: int) -> bool:
    """True iff any moment M with (M.month == month and M.day == 1 and M.time == 00:00:00 UTC)
    lies strictly greater than old_clock and less-than-or-equal to new_clock."""
    if new_clock <= old_clock:
        return False
    # Enumerate candidate rollover instants for years in [old.year, new.year+1].
    y = old_clock.year
    end_year = new_clock.year + 1
    while y <= end_year:
        candidate = datetime(y, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        if old_clock < candidate <= new_clock:
            return True
        y += 1
    return False


# ---------- Constructors ----------

def make_funder(name: str, fiscal_month: int, grant_total: int, currency: str) -> dict:
    entity = {
        "name": name,
        "fiscal_year_start_month": fiscal_month,
        "grant_cents_total": grant_total,
        "grant_cents_remaining": grant_total,
        "reporting_currency": currency,
    }
    _stamp_new(entity)
    db.funders[entity["id"]] = entity
    return entity


def make_provider(legal_name: str, lat: float, lng: float, features: list, languages: list) -> dict:
    entity = {
        "legal_name": legal_name,
        "location_lat": lat,
        "location_lng": lng,
        "accessibility_features": list(features),
        "languages_supported": list(languages),
    }
    _stamp_new(entity)
    db.providers[entity["id"]] = entity
    return entity


def make_program(provider_id: str, funder_id: str, category: str, income_max: int,
                 age_min: int, age_max: int, unit_cost: int, capacity_total: int) -> dict:
    entity = {
        "provider_id": provider_id,
        "funder_id": funder_id,
        "category": category,
        "eligibility_income_max_cents": income_max,
        "eligibility_age_min": age_min,
        "eligibility_age_max": age_max,
        "unit_cost_cents": unit_cost,
        "capacity_slots_total": capacity_total,
        "capacity_slots_taken": 0,
        "intake_posture": "OPEN",
        "funder_reporting_posture": "OPEN",
    }
    _stamp_new(entity)
    db.programs[entity["id"]] = entity
    return entity


def make_availability(program_id: str, start_ts: str, end_ts: str, max_slots: int) -> dict:
    entity = {
        "program_id": program_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "max_slots": max_slots,
    }
    _stamp_new(entity)
    db.availability_windows[entity["id"]] = entity
    return entity


def make_client(name: str, dob: str, income: int, lat: float, lng: float,
                pref_lang: str, needs: list) -> dict:
    entity = {
        "full_name": name,
        "date_of_birth": dob,
        "monthly_income_cents": income,
        "home_lat": lat,
        "home_lng": lng,
        "preferred_language": pref_lang,
        "accessibility_needs": list(needs),
    }
    _stamp_new(entity)
    db.clients[entity["id"]] = entity
    return entity


def make_intake(client_id: str, presenting: list, urgency: str, hh_size: int,
                disability: bool) -> dict:
    entity = {
        "client_id": client_id,
        "presenting_needs": list(presenting),
        "urgency": urgency,
        "household_size": hh_size,
        "disability_flag": bool(disability),
        "status": "DRAFT",
    }
    _stamp_new(entity)
    db.intakes[entity["id"]] = entity
    return entity


def make_consent(client_id: str, provider_id: str, scope: str) -> dict:
    now = db.clock
    granted_at = fmt_ts(now)
    expires = now + timedelta(days=90)
    entity = {
        "client_id": client_id,
        "provider_id": provider_id,
        "scope": scope,
        "granted_at": granted_at,
        "expires_at": fmt_ts(expires),
        "status": "GRANTED",
    }
    _stamp_new(entity)
    db.consent_grants[entity["id"]] = entity
    return entity


def make_transport(referral_id: str, pickup_start: str, pickup_end: str, mode: str,
                   cost: int) -> dict:
    entity = {
        "referral_id": referral_id,
        "pickup_start_ts": pickup_start,
        "pickup_end_ts": pickup_end,
        "mode": mode,
        "cost_cents": cost,
        "status": "SCHEDULED",
    }
    _stamp_new(entity)
    db.transport_plans[entity["id"]] = entity
    return entity


# ---------- Referral state transitions with cascades ----------

def cascade_referral_withdraw(referral: dict) -> None:
    """Mirror the client-withdraw cascade.
    - status -> WITHDRAWN
    - decrement program capacity (posture recompute + version bump)
    - cancel any SCHEDULED TransportPlan on this referral
    - bubble parent intake to CLOSED if all referrals now terminal
    - referral version/updated_at bumped
    """
    referral["status"] = "WITHDRAWN"
    _touch(referral)

    program = db.programs.get(referral["program_id"])
    if program:
        decrement_capacity(program)

    for tp in db.transport_plans.values():
        if tp["referral_id"] == referral["id"] and tp["status"] == "SCHEDULED":
            tp["status"] = "CANCELLED"
            _touch(tp)

    maybe_bubble_intake_closed(referral["intake_id"])
