"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints (each test starts against an empty database) and uses the lenient
setup validator so failures surface as clear "Setup step failed" errors.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    advance_payload,
    appeal_payload,
    availability_report_payload,
    claim_line_item,
    claim_payload,
    claim_submit_payload,
    clearance_decision_payload,
    clearance_request_payload,
    clock_payload,
    daily_status_entry_payload,
    diagnosis_code_payload,
    disclosure_grant_payload,
    injury_case_payload,
    insurance_policy_payload,
    regress_payload,
    rtp_protocol_payload,
    team_payload,
    athlete_payload,
    treatment_plan_payload,
    workload_session_payload,
)
from .test_users import TEST_USERS, medical_headers, physician_headers

ADMIN = TEST_USERS["team_admin"]
MEDICAL = TEST_USERS["medical_staff"]
PHYSICIAN = TEST_USERS["team_physician"]
PERFORMANCE = TEST_USERS["performance_staff"]
BILLING = TEST_USERS["billing_staff"]
COACHING = TEST_USERS["coaching_staff"]


def _iso_day(iso_date_str: str, plus_days: int = 0) -> str:
    return (date.fromisoformat(iso_date_str) + timedelta(days=plus_days)).isoformat()


def _clock_iso(iso_date_str: str) -> str:
    return f"{iso_date_str}T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock for all teams (PRD §2.4)."""
    return get_success_data(api_client.set_current_utc(clock_payload(to_iso8601), ADMIN))


def create_team(**overrides) -> dict:
    return get_success_data(api_client.create_team(team_payload(**overrides), ADMIN))


def create_athlete(team_id, **overrides) -> dict:
    return get_success_data(api_client.create_athlete(athlete_payload(team_id, **overrides), ADMIN))


def create_diagnosis_code(**overrides) -> dict:
    return get_success_data(api_client.create_diagnosis_code(diagnosis_code_payload(**overrides), ADMIN))


def create_injury_case(athlete_id, diagnosis_code_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_injury_case(
            injury_case_payload(athlete_id, diagnosis_code_id, **overrides),
            headers or MEDICAL,
        )
    )


def record_status_entry(
    case_id,
    entry_date,
    designation="OUT",
    symptom_free=False,
    functional_test_score=40,
    recorder_id=None,
    **overrides,
) -> dict:
    """Record a DailyStatusEntry; recorder_id pins X-User-ID when the caller's
    identity matters (segregation-of-duties scenarios, PRD §3.5)."""
    headers = medical_headers(recorder_id) if recorder_id else MEDICAL
    return get_success_data(
        api_client.create_daily_status_entry(
            daily_status_entry_payload(
                case_id,
                entry_date,
                designation=designation,
                symptom_free=symptom_free,
                functional_test_score=functional_test_score,
                **overrides,
            ),
            headers,
        )
    )


def create_plan(case_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_treatment_plan(treatment_plan_payload(case_id, **overrides), MEDICAL)
    )


def create_active_plan(case_id, **overrides) -> dict:
    plan = create_plan(case_id, **overrides)
    return get_success_data(api_client.activate_plan(plan["id"], MEDICAL))


def get_protocol(protocol_id) -> dict:
    return get_success_data(api_client.get_rtp_protocol(protocol_id, MEDICAL))


def get_case(case_id) -> dict:
    return get_success_data(api_client.get_injury_case(case_id, MEDICAL))


def get_athlete(athlete_id, headers=None) -> dict:
    return get_success_data(api_client.get_athlete(athlete_id, headers or MEDICAL))


def get_policy(policy_id) -> dict:
    return get_success_data(api_client.get_insurance_policy(policy_id, BILLING))


# ---------------------------------------------------------------------------
# Tier 2: entity-hierarchy scenarios (team + athlete + diagnosis code + case)
# ---------------------------------------------------------------------------

def setup_open_case(
    *,
    sport="SOCCER",
    position="F",
    severity_class="MINOR",
    is_concussion=False,
    dx_code="S83.5",
    body_region="KNEE",
    occurred_on="2026-08-01",
    surface="GRASS",
    mechanism="CONTACT",
    clock=None,
    hipaa_mode=None,
    acwr_variant=None,
    enrollment_date="2026-08-01",
    season=("2026-08-01", "2026-12-01"),
) -> dict:
    """Team + athlete + diagnosis code + one OPEN injury case."""
    team_kwargs = {"sport": sport, "season_start_date": season[0], "season_end_date": season[1]}
    if hipaa_mode is not None:
        team_kwargs["hipaa_mode"] = hipaa_mode
    if acwr_variant is not None:
        team_kwargs["acwr_variant"] = acwr_variant
    team = create_team(**team_kwargs)
    athlete = create_athlete(team["id"], position=position, enrollment_date=enrollment_date)
    dx = create_diagnosis_code(
        code=dx_code,
        body_region=body_region,
        severity_class=severity_class,
        is_concussion=is_concussion,
    )
    if clock is not None:
        set_clock(clock)
    case = create_injury_case(
        athlete["id"], dx["id"], occurred_on=occurred_on, surface=surface, mechanism=mechanism
    )
    return {"team": team, "athlete": athlete, "diagnosis_code": dx, "case": case}


def setup_rehab_case(
    *,
    entry_date="2026-08-01",
    recorder_id=None,
    **kwargs,
) -> dict:
    """OPEN case + one is_current status entry + start-rehab -> REHAB."""
    sc = setup_open_case(**kwargs)
    entry = record_status_entry(sc["case"]["id"], entry_date, recorder_id=recorder_id)
    case = get_success_data(api_client.start_rehab(sc["case"]["id"], MEDICAL))
    sc["entry"] = entry
    sc["case"] = case
    return sc


def setup_rtp_case(*, total_stages=3, **kwargs) -> dict:
    """REHAB case + ACTIVE treatment plan + RTP protocol (case -> RTP)."""
    sc = setup_rehab_case(**kwargs)
    plan = create_active_plan(sc["case"]["id"])
    protocol = get_success_data(
        api_client.create_rtp_protocol(
            rtp_protocol_payload(sc["case"]["id"], total_stages=total_stages), MEDICAL
        )
    )
    sc["plan"] = plan
    sc["protocol"] = protocol
    sc["case"] = get_case(sc["case"]["id"])
    return sc


# ---------------------------------------------------------------------------
# Tier 3: RTP lifecycle shortcuts
# ---------------------------------------------------------------------------

def advance_protocol_with_ready_entry(
    case_id,
    protocol_id,
    advance_date,
    designation="LIMITED",
    functional_test_score=90,
    recorder_id=None,
):
    """Move the clock to advance_date, record a ready entry (symptom_free,
    score >= 80), then advance the protocol one stage with the current
    version. Returns (advance_row, protocol)."""
    set_clock(_clock_iso(advance_date))
    record_status_entry(
        case_id,
        advance_date,
        designation=designation,
        symptom_free=True,
        functional_test_score=functional_test_score,
        recorder_id=recorder_id,
    )
    protocol = get_protocol(protocol_id)
    advance_row = get_success_data(
        api_client.advance_rtp_protocol(
            protocol_id, advance_payload(protocol["version"]), MEDICAL
        )
    )
    return advance_row, get_protocol(protocol_id)


def setup_awaiting_clearance(
    *,
    recorder_id="med-1",
    base_date="2026-08-02",
    total_stages=3,
    stage_step_days=3,
    **kwargs,
) -> dict:
    """Protocol progressed to its final stage (AWAITING_CLEARANCE).

    The case opens on base_date (clock pinned there), one stage advance per
    stage_step_days satisfies the readiness gate for a MINOR non-concussion
    case (2-day minimum per stage).
    """
    kwargs.setdefault("occurred_on", base_date)
    kwargs.setdefault("entry_date", base_date)
    kwargs.setdefault("clock", _clock_iso(base_date))
    kwargs.setdefault("season", (base_date, "2027-02-01"))
    kwargs.setdefault("enrollment_date", "2026-08-01")
    sc = setup_rtp_case(total_stages=total_stages, **kwargs)
    for i in range(total_stages - 1):
        advance_protocol_with_ready_entry(
            sc["case"]["id"],
            sc["protocol"]["id"],
            _iso_day(base_date, stage_step_days * (i + 1)),
            recorder_id=recorder_id,
        )
    sc["protocol"] = get_protocol(sc["protocol"]["id"])
    assert sc["protocol"]["status"] == "AWAITING_CLEARANCE", (
        f"Setup failed: protocol is {sc['protocol']['status']}, expected AWAITING_CLEARANCE"
    )
    sc["case"] = get_case(sc["case"]["id"])
    return sc


def setup_pending_clearance(
    *,
    requester_id="med-1",
    recorder_id="med-1",
    base_date="2026-08-02",
    request_date=None,
    **kwargs,
) -> dict:
    """AWAITING_CLEARANCE protocol + fresh same-day status entry + PENDING
    clearance request. Returns the scenario dict including 'clearance' and
    'request_date'."""
    request_date = request_date or _iso_day(base_date, 10)
    sc = setup_awaiting_clearance(
        recorder_id=recorder_id, base_date=base_date, **kwargs
    )
    set_clock(_clock_iso(request_date))
    record_status_entry(
        sc["case"]["id"],
        request_date,
        designation="FULL",
        symptom_free=True,
        functional_test_score=95,
        recorder_id=recorder_id,
    )
    protocol = get_protocol(sc["protocol"]["id"])
    clearance = get_success_data(
        api_client.request_clearance(
            protocol["id"],
            clearance_request_payload(protocol["version"]),
            medical_headers(requester_id),
        )
    )
    sc["clearance"] = clearance
    sc["request_date"] = request_date
    sc["protocol"] = get_protocol(protocol["id"])
    return sc


def grant_clearance(clearance_id, decider_id, decision="GRANTED") -> dict:
    return get_success_data(
        api_client.decide_clearance(
            clearance_id, clearance_decision_payload(decision), physician_headers(decider_id)
        )
    )


def setup_closed_case(**kwargs) -> dict:
    """Full lifecycle: case progressed to CLEARED via clearance grant, plan
    completed, case closed (terminal)."""
    sc = setup_pending_clearance(**kwargs)
    grant_clearance(sc["clearance"]["id"], "phys-9")
    get_success_data(api_client.complete_plan(sc["plan"]["id"], MEDICAL))
    case = get_success_data(api_client.close_case(sc["case"]["id"], MEDICAL))
    sc["case"] = case
    return sc


# ---------------------------------------------------------------------------
# Tier 4: billing / claims scenarios
# ---------------------------------------------------------------------------

def create_policy(athlete_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_insurance_policy(
            insurance_policy_payload(athlete_id, **overrides), BILLING
        )
    )


def setup_policy_scenario(
    *,
    deductible_cents=0,
    coinsurance_pct=80,
    oop_max_cents=500000,
    policy_number="PN-1",
    clock="2026-08-01T00:00:00Z",
    **kwargs,
) -> dict:
    """OPEN case + ACTIVE insurance policy."""
    sc = setup_open_case(clock=clock, **kwargs)
    policy = create_policy(
        sc["athlete"]["id"],
        deductible_cents=deductible_cents,
        coinsurance_pct=coinsurance_pct,
        oop_max_cents=oop_max_cents,
        policy_number=policy_number,
    )
    sc["policy"] = policy
    return sc


def create_claim(
    case_id,
    policy_id,
    billed_amount_cents,
    *,
    line_items=None,
    service_date="2026-08-02",
    cpt_code="X1",
) -> dict:
    if line_items is None:
        line_items = [
            claim_line_item(cpt_code=cpt_code, charge_cents=billed_amount_cents,
                            service_date=service_date)
        ]
    return get_success_data(
        api_client.create_claim(
            claim_payload(case_id, policy_id, billed_amount_cents, line_items=line_items),
            BILLING,
        )
    )


def submit_claim(claim_id, policy_id) -> dict:
    """Submit with the policy's current version (OCC field re-read)."""
    policy = get_policy(policy_id)
    return get_success_data(
        api_client.submit_claim(claim_id, claim_submit_payload(policy["version"]), BILLING)
    )


def adjudicate_claim(claim_id, payload=None) -> dict:
    return get_success_data(api_client.adjudicate_claim(claim_id, payload or {}, BILLING))


def appeal_claim(claim_id, reason="reconsider") -> dict:
    return get_success_data(api_client.appeal_claim(claim_id, appeal_payload(reason), BILLING))


# ---------------------------------------------------------------------------
# Tier 4b: workload / ACWR scenarios
# ---------------------------------------------------------------------------

def ingest_session(
    athlete_id,
    session_date,
    *,
    session_type="PRACTICE",
    surface="GRASS",
    duration_minutes=60,
    rpe=5,
    headers=None,
) -> dict:
    return get_success_data(
        api_client.create_workload_session(
            workload_session_payload(
                athlete_id,
                session_date,
                session_type=session_type,
                surface=surface,
                duration_minutes=duration_minutes,
                rpe=rpe,
            ),
            headers or PERFORMANCE,
        )
    )


def ingest_load_history(athlete_id, date_loads) -> list:
    """Ingest PRACTICE sessions whose session_load equals the given value
    (duration_minutes = load, rpe = 1)."""
    return [
        ingest_session(athlete_id, d, duration_minutes=load, rpe=1)
        for d, load in date_loads
    ]


def setup_acwr_athlete(history, *, acwr_variant="ROLLING", clock_date="2026-07-28") -> dict:
    """Athlete with a caller-specified session history of (date, load) pairs,
    clock pinned at clock_date; returns the scenario with the athlete re-read
    after ingestion so computed fields reflect the full history."""
    team = create_team(
        name="ACWR",
        sport="FOOTBALL",
        season_start_date="2026-07-01",
        season_end_date="2027-02-01",
        acwr_variant=acwr_variant,
    )
    athlete = create_athlete(
        team["id"], full_name="ACWR Athlete", position="QB", enrollment_date="2026-07-01"
    )
    set_clock(f"{clock_date}T00:00:00Z")
    ingest_load_history(athlete["id"], history)
    return {"team": team, "athlete": get_athlete(athlete["id"], PERFORMANCE)}


# ---------------------------------------------------------------------------
# Tier 5: reporting / confidentiality
# ---------------------------------------------------------------------------

def create_grant(athlete_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_disclosure_grant(
            disclosure_grant_payload(athlete_id, **overrides), MEDICAL
        )
    )


def generate_report(team_id, audience, headers) -> dict:
    return get_success_data(
        api_client.create_availability_report(
            availability_report_payload(team_id, audience), headers
        )
    )
