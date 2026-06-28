"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so that setup failures
surface as clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating a Driver, every ownership-gated DriverUser call
uses make_driver_headers(driver["id"]) — never the shared TEST_USERS fallback.

The system starts each test against an empty database (the runner restarts the
server before every test), so each fixture builds all of its preconditions from
scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_rate_plan_payload,
    create_driver_payload,
    create_enrollment_payload,
    create_trip_payload,
    create_trip_event_payload,
    create_quote_payload,
    create_policy_payload,
    create_statement_payload,
    create_claim_payload,
)
from .test_users import TEST_USERS, make_driver_headers


UW = TEST_USERS["underwriting_headers"]
CLAIMS = TEST_USERS["claims_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1: primitives — clock, rate plan, driver
# ─────────────────────────────────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the logical clock to an absolute UTC instant (PRD §2.4)."""
    return get_success_data(api_client.set_clock(iso, UW))


def create_rate_plan(**overrides) -> dict:
    """Create an ACTIVE rate plan (defaults to the shared CA UBI literals)."""
    return get_success_data(api_client.create_rate_plan(create_rate_plan_payload(**overrides), UW))


def create_driver(**overrides) -> dict:
    """Register a driver; the system also provisions its discount bank (PRD §3.2)."""
    return get_success_data(api_client.create_driver(create_driver_payload(**overrides), UW))


def driver_headers(driver: dict) -> dict:
    return make_driver_headers(driver["id"])


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2: enrollment + scoring trips
# ─────────────────────────────────────────────────────────────────────────────

def create_enrollment(driver: dict, rate_plan: dict, scoring_days: int = 30) -> dict:
    """Open a SCORING enrollment owned by the driver (PRD §3.3)."""
    hdr = driver_headers(driver)
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(driver["id"], rate_plan["id"], scoring_days), hdr))


def add_enrollment_trip(driver: dict, enrollment: dict, started_at: str, ended_at: str,
                        distance_miles: float, events=None, accept: bool = True) -> dict:
    """Create an enrollment-bound trip, optionally attach events, optionally accept.

    `events` is a list of (event_type, severity, occurred_at) tuples.
    """
    hdr = driver_headers(driver)
    trip = get_success_data(api_client.create_trip(
        create_trip_payload(started_at, ended_at, distance_miles, enrollment_id=enrollment["id"]), hdr))
    for (etype, sev, occ) in (events or []):
        get_success_data(api_client.create_trip_event(
            trip["id"], create_trip_event_payload(etype, sev, occ), hdr))
    if accept:
        trip = get_success_data(api_client.accept_trip(trip["id"], hdr))
    return trip


def add_three_clean_scoring_trips(driver: dict, enrollment: dict, day: str = "2026-02-01",
                                  distance: float = 4.0):
    """Attach + accept three clean short scoring trips (satisfies MIN_SCORING_TRIPS=3).

    Three clean trips keep provisional_risk_score at 0.0 (SAFE tier). Returns the trips.
    """
    trips = []
    for hour in ("01", "02", "03"):
        trips.append(add_enrollment_trip(
            driver, enrollment,
            f"{day}T{hour}:00:00Z", f"{day}T{hour}:10:00Z", distance, accept=True))
    return trips


def finalize_scoring(driver: dict, enrollment: dict) -> dict:
    """Finalize scoring (SCORING -> READY_TO_QUOTE), recomputing provisional score."""
    return get_success_data(api_client.finalize_scoring(enrollment["id"], driver_headers(driver)))


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3: quote + policy lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def create_quote(enrollment: dict) -> dict:
    """Generate a quote from a READY_TO_QUOTE enrollment (UnderwritingOps; PRD §3.4)."""
    return get_success_data(api_client.create_quote(create_quote_payload(enrollment["id"]), UW))


def bind_policy(quote: dict) -> dict:
    """Bind an OPEN quote into a policy (UnderwritingOps; PRD §3.4)."""
    return get_success_data(api_client.create_policy(create_policy_payload(quote["id"]), UW))


def setup_bound_policy(clock="2026-02-01T00:00:00Z", rate_plan_overrides=None,
                       scoring_days=30, scoring_day="2026-02-01"):
    """Full preamble through a bound, ACTIVE policy with PERIOD_OPEN / CAPTURING.

    Sequence: set clock -> create rate plan -> register driver -> open enrollment ->
    3 clean scoring trips -> finalize -> quote -> bind policy.

    Returns dict with: driver, rate_plan, enrollment, quote, policy, dheaders.
    """
    set_clock(clock)
    rate_plan = create_rate_plan(**(rate_plan_overrides or {}))
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, scoring_days)
    add_three_clean_scoring_trips(driver, enrollment, day=scoring_day)
    finalize_scoring(driver, enrollment)
    quote = create_quote(enrollment)
    policy = bind_policy(quote)
    return {
        "driver": driver,
        "rate_plan": rate_plan,
        "enrollment": enrollment,
        "quote": quote,
        "policy": policy,
        "dheaders": driver_headers(driver),
    }


def setup_ready_quote(clock="2026-02-01T00:00:00Z", rate_plan_overrides=None,
                      scoring_days=30, scoring_day="2026-02-01"):
    """Preamble through an OPEN quote (enrollment QUOTED), but NOT yet bound.

    Returns dict with: driver, rate_plan, enrollment, quote, dheaders.
    """
    set_clock(clock)
    rate_plan = create_rate_plan(**(rate_plan_overrides or {}))
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, scoring_days)
    add_three_clean_scoring_trips(driver, enrollment, day=scoring_day)
    finalize_scoring(driver, enrollment)
    quote = create_quote(enrollment)
    return {
        "driver": driver,
        "rate_plan": rate_plan,
        "enrollment": enrollment,
        "quote": quote,
        "dheaders": driver_headers(driver),
    }


def setup_ready_enrollment(clock="2026-02-01T00:00:00Z", rate_plan_overrides=None,
                           scoring_days=30, scoring_day="2026-02-01"):
    """Preamble through a READY_TO_QUOTE enrollment (3 clean accepted trips, finalized).

    Returns dict with: driver, rate_plan, enrollment, dheaders.
    """
    set_clock(clock)
    rate_plan = create_rate_plan(**(rate_plan_overrides or {}))
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, scoring_days)
    add_three_clean_scoring_trips(driver, enrollment, day=scoring_day)
    finalize_scoring(driver, enrollment)
    return {
        "driver": driver,
        "rate_plan": rate_plan,
        "enrollment": enrollment,
        "dheaders": driver_headers(driver),
    }


def setup_scoring_enrollment(clock="2026-02-01T00:00:00Z", rate_plan_overrides=None,
                             scoring_days=30):
    """Preamble through a fresh SCORING enrollment (no trips).

    Returns dict with: driver, rate_plan, enrollment, dheaders.
    """
    set_clock(clock)
    rate_plan = create_rate_plan(**(rate_plan_overrides or {}))
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, scoring_days)
    return {
        "driver": driver,
        "rate_plan": rate_plan,
        "enrollment": enrollment,
        "dheaders": driver_headers(driver),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tier 4: policy trips, scores, statements, claims
# ─────────────────────────────────────────────────────────────────────────────

def add_policy_trip(ctx, started_at, ended_at, distance_miles, events=None,
                    accept=True) -> dict:
    """Create a policy-bound trip on ctx['policy'], optionally attach events / accept.

    `events` is a list of (event_type, severity, occurred_at) tuples.
    """
    hdr = ctx["dheaders"]
    trip = get_success_data(api_client.create_trip(
        create_trip_payload(started_at, ended_at, distance_miles, policy_id=ctx["policy"]["id"]), hdr))
    for (etype, sev, occ) in (events or []):
        get_success_data(api_client.create_trip_event(
            trip["id"], create_trip_event_payload(etype, sev, occ), hdr))
    if accept:
        trip = get_success_data(api_client.accept_trip(trip["id"], hdr))
    return trip


def hard_brake_events(n: int, day: str = "2026-05-02", base_hour: str = "01") -> list:
    """Build n HARD_BRAKE (event_type, severity, occurred_at) tuples within a trip window."""
    out = []
    for i in range(n):
        minute = f"{5 + i:02d}"
        out.append(("HARD_BRAKE", 2, f"{day}T{base_hour}:{minute}:00Z"))
    return out


def get_policy(ctx) -> dict:
    return get_success_data(api_client.get_policy(ctx["policy"]["id"], UW))


def policy_version(ctx) -> int:
    return get_policy(ctx)["version"]


def create_manual_claim(ctx, reported_severity: int, **overrides) -> dict:
    """File a MANUAL claim against ctx['policy'] as the owning driver (PRD §3.8)."""
    return get_success_data(api_client.create_claim(
        create_claim_payload(ctx["policy"]["id"], reported_severity, **overrides),
        ctx["dheaders"]))


def setup_bound_policy_with_standard_score(clock="2026-05-01T00:00:00Z", scoring_day="2026-05-01",
                                           drive_day="2026-05-02", distance=30.0):
    """Bound policy + one accepted hb=6 policy trip -> operational score 12.0 (STANDARD, mult 1.0).

    Returns (ctx, policy_trip). The shared rate plan has hard_brake_weight=2.0, so
    6 hard-brake events => 6 * 2.0 == 12.0, which lands in STANDARD [10,25) -> 1.00.
    """
    ctx = setup_bound_policy(clock=clock, scoring_day=scoring_day)
    trip = add_policy_trip(
        ctx, f"{drive_day}T01:00:00Z", f"{drive_day}T02:00:00Z", distance,
        events=hard_brake_events(6, day=drive_day, base_hour="01"), accept=True)
    return ctx, trip


def setup_closed_claim(clock="2026-04-01T00:00:00Z", reported_severity=3):
    """Bound policy + MANUAL claim driven to CLOSED with reopen_count 0.

    Returns (ctx, claim) where claim is the freshly closed claim record.
    """
    ctx = setup_bound_policy(clock=clock, scoring_day="2026-04-01")
    claim = create_manual_claim(ctx, reported_severity)
    get_success_data(api_client.triage_claim(claim["id"], {}, CLAIMS))
    get_success_data(api_client.close_claim(claim["id"], CLAIMS))
    claim = get_success_data(api_client.get_claim(claim["id"], CLAIMS))
    return ctx, claim


def get_driver(ctx) -> dict:
    return get_success_data(api_client.get_driver(ctx["driver"]["id"], ctx["dheaders"]))


def get_discount_bank(ctx) -> dict:
    """Fetch the driver's single discount bank (PRD §3.10)."""
    res = api_client.list_discount_banks(UW, params={"driver_id": ctx["driver"]["id"]})
    data, _meta = _paginated(res)
    assert data, "Setup failed: driver has no discount bank"
    return data[0]


def _paginated(res):
    """Tolerant pagination reader for setup (returns (list, meta))."""
    body = res.json()
    payload = body.get("data", [])
    meta = body.get("meta", {})
    return payload, meta


def get_enrollment(ctx) -> dict:
    return get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], ctx["dheaders"]))


def list_risk_snapshots(ctx) -> list:
    """Return the policy's risk-score snapshots, ascending by creation (PRD §3.11)."""
    res = api_client.list_risk_snapshots(ctx["policy"]["id"], UW)
    data, _meta = _paginated(res)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Tier 5: specialized calculation scenarios (mirror difficulty/corner recipes)
# ─────────────────────────────────────────────────────────────────────────────

def setup_dual_variant_divergence():
    """Replay identical event totals on enrollment and on policy to expose the
    per-100-miles vs absolute divergence (PRD §2.7, §3.3, §3.5).

    Enrollment trips: hb=4, sp=2, pu=1 over 40 miles (20 + 15 + 5).
      provisional = 2.0*(4*100/40) + 1.5*(2*100/40) + 1.0*(1*100/40)
                  = 2.0*10 + 1.5*5 + 1.0*2.5 = 20 + 7.5 + 2.5 = 30.0
    Policy trip: same hb=4, sp=2, pu=1 (absolute).
      operational = 2.0*4 + 1.5*2 + 1.0*1 = 8 + 3 + 1 = 12.0

    Returns ctx (with enrollment finalized -> quote -> policy, plus the replayed
    accepted policy trip).
    """
    ctx = setup_bound_policy_with_divergent_enrollment()
    # replay identical events as a single policy-bound trip (hb=4 sp=2 pu=1)
    pt_events = (
        [("HARD_BRAKE", 2, f"2026-02-02T01:0{i}:00Z") for i in range(5, 9)]
        + [("SPEEDING", 3, "2026-02-02T01:09:00Z"), ("SPEEDING", 3, "2026-02-02T01:10:00Z")]
        + [("PHONE_USE", 1, "2026-02-02T01:11:00Z")]
    )
    add_policy_trip(ctx, "2026-02-02T01:00:00Z", "2026-02-02T01:30:00Z", 20.0,
                    events=pt_events, accept=True)
    return ctx


def setup_bound_policy_with_divergent_enrollment():
    """Bound policy whose source enrollment carries hb=4, sp=2, pu=1 over 40 miles
    (provisional_risk_score == 30.0). Returns ctx."""
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    # enrollment trip 1: 20 mi, hb=2 sp=1
    add_enrollment_trip(driver, enrollment, "2026-02-01T01:00:00Z", "2026-02-01T01:30:00Z", 20.0,
                        events=[("HARD_BRAKE", 2, "2026-02-01T01:05:00Z"),
                                ("HARD_BRAKE", 2, "2026-02-01T01:06:00Z"),
                                ("SPEEDING", 3, "2026-02-01T01:07:00Z")], accept=True)
    # enrollment trip 2: 15 mi, hb=2 pu=1
    add_enrollment_trip(driver, enrollment, "2026-02-01T02:00:00Z", "2026-02-01T02:30:00Z", 15.0,
                        events=[("HARD_BRAKE", 2, "2026-02-01T02:05:00Z"),
                                ("HARD_BRAKE", 2, "2026-02-01T02:06:00Z"),
                                ("SPEEDING", 3, "2026-02-01T02:07:00Z"),
                                ("PHONE_USE", 1, "2026-02-01T02:08:00Z")], accept=True)
    # enrollment trip 3: 5 mi, clean (satisfies MIN_SCORING_TRIPS=3)
    add_enrollment_trip(driver, enrollment, "2026-02-01T03:00:00Z", "2026-02-01T03:15:00Z", 5.0,
                        events=None, accept=True)
    finalize_scoring(driver, enrollment)
    quote = create_quote(enrollment)
    policy = bind_policy(quote)
    return {
        "driver": driver, "rate_plan": rate_plan, "enrollment": enrollment,
        "quote": quote, "policy": policy, "dheaders": driver_headers(driver),
    }


def setup_elevated_quote():
    """Enrollment finalized at provisional_risk_score 30.0 (ELEVATED tier 1.25),
    then a quote generated. Returns (ctx-like dict with quote)."""
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    # one trip carrying hb=4, sp=2, pu=1 over 20 miles, then two clean 10-mile trips
    add_enrollment_trip(driver, enrollment, "2026-02-01T01:00:00Z", "2026-02-01T01:30:00Z", 20.0,
                        events=[("HARD_BRAKE", 2, "2026-02-01T01:05:00Z"),
                                ("HARD_BRAKE", 2, "2026-02-01T01:06:00Z"),
                                ("HARD_BRAKE", 2, "2026-02-01T01:07:00Z"),
                                ("HARD_BRAKE", 2, "2026-02-01T01:08:00Z"),
                                ("SPEEDING", 3, "2026-02-01T01:09:00Z"),
                                ("SPEEDING", 3, "2026-02-01T01:10:00Z"),
                                ("PHONE_USE", 1, "2026-02-01T01:11:00Z")], accept=True)
    add_enrollment_trip(driver, enrollment, "2026-02-01T02:00:00Z", "2026-02-01T02:30:00Z", 10.0,
                        events=None, accept=True)
    add_enrollment_trip(driver, enrollment, "2026-02-01T03:00:00Z", "2026-02-01T03:30:00Z", 10.0,
                        events=None, accept=True)
    finalize_scoring(driver, enrollment)
    quote = create_quote(enrollment)
    return {
        "driver": driver, "rate_plan": rate_plan, "enrollment": enrollment,
        "quote": quote, "dheaders": driver_headers(driver),
    }


def setup_driver_two_active_policies(clock="2026-05-01T00:00:00Z"):
    """One driver with TWO bound ACTIVE policies, both CAPTURING. Returns
    (driver, policy1, policy2, dheaders)."""
    set_clock(clock)
    rate_plan = create_rate_plan()
    driver = create_driver()
    hdr = driver_headers(driver)
    policies = []
    days = [("2026-05-01", ["01", "02", "03"]), ("2026-05-01", ["04", "05", "06"])]
    for (day, hours) in days:
        enrollment = create_enrollment(driver, rate_plan, 30)
        for hour in hours:
            add_enrollment_trip(driver, enrollment,
                                f"{day}T{hour}:00:00Z", f"{day}T{hour}:10:00Z", 4.0, accept=True)
        finalize_scoring(driver, enrollment)
        quote = create_quote(enrollment)
        policies.append(bind_policy(quote))
    return driver, policies[0], policies[1], hdr


def setup_rounding_policy_standard_mult():
    """Bound policy with base_premium_cents producing bound 86706 at SAFE 0.85, then
    an accepted hb=6 4001-mile trip pushing the operational score to 12.0 (STANDARD,
    mult 1.0). Returns ctx (the policy is PERIOD_OPEN with one accepted big trip).

    rate plan base_premium_cents=102007, weights hb=2.0 sp=0 pu=0:
      quote SAFE 0.85 -> quoted = round(102007 * 0.85) = 86706 = bound_premium_cents
      policy hb=6 -> operational = 6 * 2.0 = 12.0 (STANDARD) -> mult 1.0
    """
    set_clock("2026-03-01T00:00:00Z")
    rate_plan = create_rate_plan(name="Round Plan", base_premium_cents=102007,
                                 per_mile_rate_cents=0.5, included_miles_per_period=1000,
                                 hard_brake_weight=2.0, speeding_weight=0.0, phone_use_weight=0.0)
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    add_three_clean_scoring_trips(driver, enrollment, day="2026-03-01")
    finalize_scoring(driver, enrollment)
    quote = create_quote(enrollment)
    policy = bind_policy(quote)
    ctx = {
        "driver": driver, "rate_plan": rate_plan, "enrollment": enrollment,
        "quote": quote, "policy": policy, "dheaders": driver_headers(driver),
    }
    add_policy_trip(ctx, "2026-03-02T01:00:00Z", "2026-03-02T05:00:00Z", 4001.0,
                    events=hard_brake_events(6, day="2026-03-02", base_hour="01"), accept=True)
    return ctx
