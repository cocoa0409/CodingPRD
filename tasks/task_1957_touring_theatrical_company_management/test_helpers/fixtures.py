"""Composite setup helpers for the touring-management test suite.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before each test, so the database starts
empty). Setup calls use get_success_data() so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_cast_member_payload,
    create_coverage_payload,
    create_crew_call_payload,
    create_injury_payload,
    create_per_diem_payload,
    create_performance_payload,
    create_stop_payload,
    create_tech_check_payload,
    create_track_payload,
    create_tour_payload,
    create_venue_payload,
    crew_actual_lines,
    settlement_figures_payload,
)
from .test_users import (
    TEST_USERS,
    make_company_manager_headers,
    make_producer_headers,
    make_tour_manager_headers,
    make_treasurer_headers,
)

PRODUCER = TEST_USERS["producer_headers"]
TOUR_MANAGER = TEST_USERS["tour_manager_headers"]
COMPANY_MANAGER = TEST_USERS["company_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]

# Canonical settlement figure set ("S1"): audited 6,000,000 / taxes 300,000 /
# levies 200,000 against guarantee 4,000,000 at split 70 -> venue payment
# 4,000,000, producer share 1,500,000, pre-recoup royalty 105,000 at T=1,000,000.
S1_FIGURES = {"audited_gross_cents": 6_000_000, "taxes_cents": 300_000, "levies_cents": 200_000}
S1_VENUE_PAYMENT = 4_000_000
S1_PRODUCER_SHARE = 1_500_000
S1_ROYALTY = 105_000


# --- Tier 1: single-resource creators ---------------------------------------

def create_tour(**overrides):
    """Create a tour (PLANNING). Returns the tour dict."""
    resp = api_client.create_tour(create_tour_payload(**overrides), PRODUCER)
    return get_success_data(resp, 201)


def create_venue(**overrides):
    resp = api_client.create_venue(create_venue_payload(**overrides), PRODUCER)
    return get_success_data(resp, 201)


def get_tour(tour_id):
    resp = api_client.get_tour(tour_id, PRODUCER)
    return get_success_data(resp)


def get_stop(stop_id):
    resp = api_client.get_stop(stop_id, PRODUCER)
    return get_success_data(resp)


def get_cast_member(cast_id):
    resp = api_client.get_cast_member(cast_id, COMPANY_MANAGER)
    return get_success_data(resp)


def get_track(track_id):
    resp = api_client.get_track(track_id, COMPANY_MANAGER)
    return get_success_data(resp)


def get_stop_settlement(stop_id):
    """Fetch the (possibly empty) settlement list of a stop; return first or None."""
    resp = api_client.get_stop_settlement(stop_id, PRODUCER)
    rows = get_success_data(resp)
    return rows[0] if rows else None


def set_clock(iso8601):
    resp = api_client.set_clock({"to_iso8601": iso8601}, PRODUCER)
    return get_success_data(resp)


# --- Tier 2: stops and booking-state progression -----------------------------

def add_stop(tour_id, venue_id, expected_tour_version=None, **overrides):
    """Add a stop, reading the tour fresh for its OCC version unless one is
    supplied explicitly. Returns the stop dict (TENTATIVE/PENDING)."""
    if expected_tour_version is None:
        expected_tour_version = get_tour(tour_id)["version"]
    payload = create_stop_payload(venue_id, expected_tour_version, **overrides)
    resp = api_client.create_stop(tour_id, payload, TOUR_MANAGER)
    return get_success_data(resp, 201)


def put_stop_status(stop_id, status, headers):
    resp = api_client.put_stop(stop_id, {"status": status}, headers)
    return get_success_data(resp)


def contract_stop(stop_id):
    return put_stop_status(stop_id, "CONTRACTED", PRODUCER)


def advance_stop(stop_id):
    return put_stop_status(stop_id, "ADVANCED", TOUR_MANAGER)


def certify_stop(stop_id):
    """ADVANCED -> READY; freezes estimated_venue_payment_cents."""
    return put_stop_status(stop_id, "READY", TOUR_MANAGER)


def wrap_stop(stop_id):
    return put_stop_status(stop_id, "WRAPPED", PRODUCER)


def cancel_stop(stop_id):
    return put_stop_status(stop_id, "CANCELLED", PRODUCER)


def create_tech_check(stop_id, **overrides):
    resp = api_client.create_tech_check(stop_id, create_tech_check_payload(**overrides), TOUR_MANAGER)
    return get_success_data(resp, 201)


def record_check_actual(check_id, actual_value):
    resp = api_client.put_tech_check(check_id, {"actual_value": actual_value}, TOUR_MANAGER)
    return get_success_data(resp)


def add_passing_check(stop_id, item="STAGE_WIDTH_FT", required_value=40, actual_value=42):
    """Create a check and record a passing measurement. Returns the check."""
    check = create_tech_check(stop_id, item=item, required_value=required_value)
    return record_check_actual(check["id"], actual_value)


def setup_ready_stop(tour_overrides=None, stop_overrides=None, check_kwargs=None):
    """Tour + venue + stop walked to READY with one PASS check.

    Returns dict(tour, venue, stop, check). The stop is returned in READY state.
    """
    tour = create_tour(**(tour_overrides or {}))
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"], **(stop_overrides or {}))
    contract_stop(stop["id"])
    advance_stop(stop["id"])
    check = add_passing_check(stop["id"], **(check_kwargs or {}))
    stop = certify_stop(stop["id"])
    return {"tour": tour, "venue": venue, "stop": stop, "check": check}


def setup_advanced_stop(tour_overrides=None, stop_overrides=None):
    """Tour + venue + stop walked to ADVANCED (no tech checks)."""
    tour = create_tour(**(tour_overrides or {}))
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"], **(stop_overrides or {}))
    contract_stop(stop["id"])
    stop = advance_stop(stop["id"])
    return {"tour": tour, "venue": venue, "stop": stop}


# --- Tier 3: performances, closure, settlement lifecycle ----------------------

def schedule_performance(stop_id, perf_date="2026-09-08", curtain_time="19:30",
                         duration_minutes=150):
    resp = api_client.create_performance(
        stop_id,
        create_performance_payload(perf_date=perf_date, curtain_time=curtain_time,
                                   duration_minutes=duration_minutes),
        TOUR_MANAGER,
    )
    return get_success_data(resp, 201)


def play_performance(perf_id, gross_cents):
    resp = api_client.put_performance(
        perf_id, {"status": "PLAYED", "gross_cents": gross_cents}, TREASURER)
    return get_success_data(resp)


def cancel_performance(perf_id):
    resp = api_client.put_performance(perf_id, {"status": "CANCELLED"}, TOUR_MANAGER)
    return get_success_data(resp)


def setup_closed_stop_with_settlement(tour_overrides=None, stop_overrides=None,
                                      played_gross=750_000):
    """READY stop, one performance PLAYED -> stop CLOSED, settlement auto-created
    in DRAFT. Returns dict(tour, venue, stop, performance, settlement)."""
    ctx = setup_ready_stop(tour_overrides, stop_overrides)
    perf = schedule_performance(ctx["stop"]["id"])
    play_performance(perf["id"], played_gross)
    stop = get_stop(ctx["stop"]["id"])
    settlement = get_stop_settlement(stop["id"])
    assert settlement is not None, "Setup failed: settlement must auto-exist after close"
    ctx.update({"performance": perf, "stop": stop, "settlement": settlement})
    return ctx


def set_settlement_figures(settlement_id, audited_gross_cents, taxes_cents, levies_cents):
    resp = api_client.put_settlement(
        settlement_id,
        settlement_figures_payload(audited_gross_cents, taxes_cents, levies_cents),
        TREASURER,
    )
    return get_success_data(resp)


def submit_settlement(settlement_id, user_id="trs-1"):
    resp = api_client.put_settlement(
        settlement_id, {"status": "SUBMITTED"}, make_treasurer_headers(user_id))
    return get_success_data(resp)


def approve_settlement(settlement_id, user_id="prod-1"):
    resp = api_client.put_settlement(
        settlement_id, {"status": "APPROVED"}, make_producer_headers(user_id))
    return get_success_data(resp)


def pay_settlement(settlement_id, user_id="trs-1"):
    resp = api_client.put_settlement(
        settlement_id, {"status": "PAID"}, make_treasurer_headers(user_id))
    return get_success_data(resp)


def dispute_settlement(settlement_id, reason="audit query", user_id="prod-1"):
    resp = api_client.put_settlement(
        settlement_id, {"status": "DISPUTED", "dispute_reason": reason},
        make_producer_headers(user_id))
    return get_success_data(resp)


def setup_submitted_settlement(figures=S1_FIGURES, submitter="trs-1", **setup_kw):
    """Closed stop with figures recorded and status SUBMITTED."""
    ctx = setup_closed_stop_with_settlement(**setup_kw)
    s = ctx["settlement"]
    set_settlement_figures(s["id"], figures["audited_gross_cents"],
                           figures["taxes_cents"], figures["levies_cents"])
    ctx["settlement"] = submit_settlement(s["id"], submitter)
    return ctx


def setup_approved_settlement(figures=S1_FIGURES, submitter="trs-1",
                              approver="prod-1", **setup_kw):
    ctx = setup_submitted_settlement(figures, submitter, **setup_kw)
    ctx["settlement"] = approve_settlement(ctx["settlement"]["id"], approver)
    return ctx


def setup_paid_settlement(figures=S1_FIGURES, submitter="trs-1", approver="prod-1",
                          payer="trs-1", **setup_kw):
    """Full custody chain through PAID. Stop remains CLOSED (not yet wrapped)."""
    ctx = setup_approved_settlement(figures, submitter, approver, **setup_kw)
    ctx["settlement"] = pay_settlement(ctx["settlement"]["id"], payer)
    return ctx


def setup_wrapped_stop(figures=S1_FIGURES, **setup_kw):
    """Full lifecycle through WRAPPED. Returns ctx with refreshed tour/stop."""
    ctx = setup_paid_settlement(figures, **setup_kw)
    ctx["stop"] = wrap_stop(ctx["stop"]["id"])
    ctx["tour"] = get_tour(ctx["tour"]["id"])
    return ctx


# --- Tier 4: company: cast, tracks, coverage, injuries ------------------------

def create_cast_member(tour_id, name="Pat Performer", contract_type="PRINCIPAL",
                       weekly_salary_cents=800_000):
    resp = api_client.create_cast_member(
        tour_id,
        create_cast_member_payload(name=name, contract_type=contract_type,
                                   weekly_salary_cents=weekly_salary_cents),
        COMPANY_MANAGER,
    )
    return get_success_data(resp, 201)


def contract_member(cast_id):
    resp = api_client.put_cast(cast_id, {"status": "CONTRACTED"}, COMPANY_MANAGER)
    return get_success_data(resp)


def create_contracted_member(tour_id, **kwargs):
    member = create_cast_member(tour_id, **kwargs)
    return contract_member(member["id"])


def create_track(tour_id, track_name="Lead", required_covers=1, principal_member_id=None):
    payload = create_track_payload(track_name=track_name, required_covers=required_covers)
    if principal_member_id is not None:
        payload["principal_member_id"] = principal_member_id
    resp = api_client.create_track(tour_id, payload, COMPANY_MANAGER)
    return get_success_data(resp, 201)


def create_coverage(track_id, cast_member_id, kind="UNDERSTUDY", priority_rank=1):
    resp = api_client.create_coverage(
        track_id,
        create_coverage_payload(cast_member_id, kind=kind, priority_rank=priority_rank),
        COMPANY_MANAGER,
    )
    return get_success_data(resp, 201)


def report_injury(cast_id, notes="injury reported"):
    resp = api_client.create_injury(cast_id, create_injury_payload(notes=notes),
                                    COMPANY_MANAGER)
    return get_success_data(resp, 201)


def resolve_injury(injury_id):
    resp = api_client.put_injury(injury_id, {"status": "RESOLVED"}, COMPANY_MANAGER)
    return get_success_data(resp)


def setup_principal_with_understudy(required_covers=1, principal_salary=800_000,
                                    understudy_salary=500_000):
    """Tour with CONTRACTED principal P (track T) and CONTRACTED understudy U
    holding a STANDBY UNDERSTUDY rank-1 coverage on T."""
    tour = create_tour()
    p = create_contracted_member(tour["id"], name="P", contract_type="PRINCIPAL",
                                 weekly_salary_cents=principal_salary)
    u = create_contracted_member(tour["id"], name="U", contract_type="UNDERSTUDY",
                                 weekly_salary_cents=understudy_salary)
    track = create_track(tour["id"], track_name="Lead", required_covers=required_covers,
                         principal_member_id=p["id"])
    coverage = create_coverage(track["id"], u["id"], kind="UNDERSTUDY", priority_rank=1)
    return {"tour": tour, "principal": p, "understudy": u, "track": track,
            "coverage": coverage}


# --- Tier 5: per-diems and crew calls -----------------------------------------

def issue_per_diem(stop_id, cast_member_id, days_present=7, travel_days=0):
    resp = api_client.create_per_diem(
        stop_id,
        create_per_diem_payload(cast_member_id, days_present=days_present,
                                travel_days=travel_days),
        COMPANY_MANAGER,
    )
    return get_success_data(resp, 201)


def pay_per_diem(pd_id):
    resp = api_client.put_per_diem(pd_id, {"status": "PAID"}, COMPANY_MANAGER)
    return get_success_data(resp)


def create_crew_call(stop_id, **overrides):
    resp = api_client.create_crew_call(stop_id, create_crew_call_payload(**overrides),
                                       TOUR_MANAGER)
    return get_success_data(resp, 201)


def settle_crew_call(cc_id, *position_hours):
    resp = api_client.put_crew_call(
        cc_id, {"status": "SETTLED", "actual_lines": crew_actual_lines(*position_hours)},
        TOUR_MANAGER)
    return get_success_data(resp)


def cancel_crew_call(cc_id):
    resp = api_client.put_crew_call(cc_id, {"status": "CANCELLED"}, TOUR_MANAGER)
    return get_success_data(resp)
