"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its startup default, PRD §2.4). Setup calls
use get_success_data so failures surface as clear "Setup failed" errors.

Pipeline tiers:
  Tier 1 — segment / resident / request stand-up, petition drive
  Tier 2 — speed study commission, observation recording, analyze/certify
  Tier 3 — funding cycle + ranking publication (FUNDED)
  Tier 4 — treatment plan design/approval (BALLOT_READY) and ballot (BALLOT_OPEN)
  Tier 5 — consent tally, work order, installation, post-study, removal
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_DEFAULT, PETITION_RATIO
from .factories import (
    create_ballot_payload,
    create_funding_cycle_payload,
    create_observation_payload,
    create_request_payload,
    create_resident_payload,
    create_review_payload,
    create_schedule_payload,
    create_segment_payload,
    create_speed_study_payload,
    create_treatment_plan_payload,
    create_vote_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_city_engineer_headers,
    make_emergency_reviewer_headers,
    make_resident_headers,
    make_traffic_engineer_headers,
)

ADMIN = TEST_USERS["city_admin_headers"]
TE = TEST_USERS["traffic_engineer_headers"]

# Opaque operator ids (PRD §2.1). The default plan author is "te-1" and the
# default approver is "ce-1" so segregation of duties is always satisfied.
DEFAULT_PLAN_AUTHOR = "te-1"
DEFAULT_PLAN_APPROVER = "ce-1"
DEFAULT_REVIEWER = "er-1"

# Standard 3-day observation recipe on a 30 mph / 0-crash / 0-generator
# segment: speed excess 10 -> 40 points, volume 3000 -> 20 points => score 60.
STANDARD_OBS = (3000, 40.0, 33.0)
STANDARD_WINDOW = ("2026-08-03", "2026-08-05")


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tier 0 — logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=LOGICAL_CLOCK_DEFAULT):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 1 — segments, residents, requests, petitions
# ---------------------------------------------------------------------------

def create_segment(name="Maple Ave", speed_limit_mph=30, household_count=4,
                   functional_class="LOCAL", emergency_route=False,
                   crash_count_3yr=0, pedestrian_generator_count=0):
    resp = api_client.create_segment(
        create_segment_payload(
            name=name,
            speed_limit_mph=speed_limit_mph,
            household_count=household_count,
            functional_class=functional_class,
            emergency_route=emergency_route,
            crash_count_3yr=crash_count_3yr,
            pedestrian_generator_count=pedestrian_generator_count,
        ),
        ADMIN,
    )
    return _ok("create_segment", resp)


def create_resident(segment_id, full_name="Robin Rivera",
                    email="robin@example.com", household_ref="H1"):
    resp = api_client.create_resident(
        create_resident_payload(
            full_name=full_name,
            email=email,
            street_segment_id=segment_id,
            household_ref=household_ref,
        ),
        ADMIN,
    )
    return _ok("create_resident", resp)


def create_residents(segment_id, count, prefix="r"):
    """Create `count` residents on one segment with unique emails and
    unique household refs (PRD §3.1 uniqueness rules)."""
    residents = []
    for i in range(1, count + 1):
        residents.append(
            create_resident(
                segment_id,
                full_name=f"{prefix.upper()}{i}",
                email=f"{prefix}-{i}@example.com",
                household_ref=f"{prefix.upper()}-H{i}",
            )
        )
    return residents


def required_signatures_for(household_count: int) -> int:
    """ceil(household_count * 60%) — the petition threshold (PRD §3.2)."""
    import math
    return math.ceil(household_count * float(PETITION_RATIO))


def file_request(segment_id, resident_id, title="Calm our street",
                 requested_budget_cents=10000):
    resp = api_client.create_request(
        create_request_payload(
            street_segment_id=segment_id,
            title=title,
            requested_budget_cents=requested_budget_cents,
        ),
        make_resident_headers(resident_id),
    )
    return _ok("file_request", resp)


def get_request(request_id):
    resp = api_client.get_request(request_id, ADMIN)
    return _ok("get_request", resp)


def open_petition(request_id):
    resp = api_client.open_petition(request_id, TE)
    return _ok("open_petition", resp)


def sign_petition(request_id, resident_id):
    resp = api_client.sign_petition(
        request_id, make_resident_headers(resident_id)
    )
    return _ok("sign_petition", resp)


def setup_petition_open(name="Maple Ave", household_count=4,
                        speed_limit_mph=30, functional_class="LOCAL",
                        emergency_route=False, crash_count_3yr=0,
                        pedestrian_generator_count=0,
                        requested_budget_cents=10000, title=None,
                        resident_prefix="r", resident_count=None,
                        signatures=0):
    """Segment + residents + request + open petition + `signatures` signatures.

    Returns a context dict with segment, residents, request and the
    open-petition response. Default resident_count covers the petition
    threshold; pass signatures=0 (default) to stay PETITION_OPEN.
    """
    set_clock()
    segment = create_segment(
        name=name, speed_limit_mph=speed_limit_mph,
        household_count=household_count, functional_class=functional_class,
        emergency_route=emergency_route, crash_count_3yr=crash_count_3yr,
        pedestrian_generator_count=pedestrian_generator_count,
    )
    if resident_count is None:
        resident_count = max(1, required_signatures_for(household_count))
    residents = create_residents(segment["id"], resident_count, resident_prefix)
    request = file_request(
        segment["id"], residents[0]["id"],
        title=title or f"Calm {name}",
        requested_budget_cents=requested_budget_cents,
    )
    opened = open_petition(request["id"])
    signatures_made = []
    for i in range(signatures):
        signatures_made.append(sign_petition(request["id"], residents[i]["id"]))
    return {
        "segment": segment,
        "residents": residents,
        "request": request,
        "opened": opened,
        "signatures": signatures_made,
    }


def setup_petition_met(**kwargs):
    """Petition driven to PETITION_MET (exactly `required` signatures)."""
    kwargs.setdefault("signatures", None)
    signatures = kwargs.pop("signatures")
    ctx = setup_petition_open(**kwargs)
    if signatures is None:
        signatures = required_signatures_for(ctx["segment"]["household_count"])
    for i in range(signatures):
        sign_petition(ctx["request"]["id"], ctx["residents"][i]["id"])
    ctx["request"] = get_request(ctx["request"]["id"])
    assert ctx["request"]["status"] == "PETITION_MET", (
        f"Setup failed: expected PETITION_MET, got {ctx['request']['status']}"
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 — speed studies and observations
# ---------------------------------------------------------------------------

def commission_study(request_id, study_type="INITIAL",
                     window_start_date=STANDARD_WINDOW[0],
                     window_end_date=STANDARD_WINDOW[1]):
    resp = api_client.create_speed_study(
        request_id,
        create_speed_study_payload(
            study_type=study_type,
            window_start_date=window_start_date,
            window_end_date=window_end_date,
        ),
        TE,
    )
    return _ok("commission_study", resp)


def record_observation(study_id, observation_date, vehicle_count=3000,
                       p85_speed_mph=40.0, mean_speed_mph=33.0,
                       is_valid=None):
    payload = create_observation_payload(
        observation_date=observation_date,
        vehicle_count=vehicle_count,
        p85_speed_mph=p85_speed_mph,
        mean_speed_mph=mean_speed_mph,
    )
    if is_valid is not None:
        payload["is_valid"] = is_valid
    resp = api_client.record_observation(study_id, payload, TE)
    return _ok("record_observation", resp)


def record_daily_observations(study_id, dates, vehicle_count=3000,
                              p85_speed_mph=40.0, mean_speed_mph=33.0):
    return [
        record_observation(study_id, d, vehicle_count, p85_speed_mph,
                           mean_speed_mph)
        for d in dates
    ]


def analyze_study(study_id):
    resp = api_client.analyze_study(study_id, TE)
    return _ok("analyze_study", resp)


def return_study_for_recollection(study_id):
    resp = api_client.return_study_for_recollection(study_id, TE)
    return _ok("return_study_for_recollection", resp)


def certify_study(study_id):
    resp = api_client.certify_study(study_id, TE)
    return _ok("certify_study", resp)


def get_speed_study(study_id):
    resp = api_client.get_speed_study(study_id, ADMIN)
    return _ok("get_speed_study", resp)


def setup_study_collecting(observations=None, window=STANDARD_WINDOW, **kwargs):
    """Petition-met request + INITIAL study in COLLECTING; optionally records
    observations (list of (date, vehicle_count, p85, mean[, is_valid]))."""
    ctx = setup_petition_met(**kwargs)
    study = commission_study(
        ctx["request"]["id"], "INITIAL", window[0], window[1]
    )
    ctx["study"] = study
    if observations:
        for spec in observations:
            record_observation(study["id"], *spec)
    return ctx


def setup_ranking_eligible(obs_spec=None, window=STANDARD_WINDOW, **kwargs):
    """Full drive to RANKING_ELIGIBLE: petition met, INITIAL study with three
    standard days (score 60 + crash/ped points), analyzed and certified."""
    ctx = setup_study_collecting(window=window, **kwargs)
    if obs_spec is None:
        dates = [window[0]]
        start_day = int(window[0][-2:])
        dates = [
            f"{window[0][:-2]}{start_day + i:02d}" for i in range(3)
        ]
        record_daily_observations(ctx["study"]["id"], dates)
    else:
        for spec in obs_spec:
            record_observation(ctx["study"]["id"], *spec)
    analyze_study(ctx["study"]["id"])
    ctx["study"] = certify_study(ctx["study"]["id"])
    ctx["request"] = get_request(ctx["request"]["id"])
    return ctx


def build_certified_request(name, resident_prefix, crash_count_3yr=0,
                                   pedestrian_generator_count=0,
                                   requested_budget_cents=10000,
                                   household_count=4,
                                   speed_limit_mph=30,
                                   functional_class="LOCAL",
                                   emergency_route=False,
                                   obs_recipe=STANDARD_OBS,
                                   window=STANDARD_WINDOW):
    """Standalone drive of one segment/request through INITIAL-study
    certification without touching the clock (the caller owns clock state in
    multi-request setups). The landing stage depends on the observation
    recipe: the standard recipe reaches RANKING_ELIGIBLE, a low recipe lands
    in SCORE_INELIGIBLE."""
    segment = create_segment(
        name=name, speed_limit_mph=speed_limit_mph,
        household_count=household_count, functional_class=functional_class,
        emergency_route=emergency_route, crash_count_3yr=crash_count_3yr,
        pedestrian_generator_count=pedestrian_generator_count,
    )
    residents = create_residents(
        segment["id"], required_signatures_for(household_count), resident_prefix
    )
    request = file_request(
        segment["id"], residents[0]["id"], title=f"Calm {name}",
        requested_budget_cents=requested_budget_cents,
    )
    open_petition(request["id"])
    for r in residents:
        sign_petition(request["id"], r["id"])
    study = commission_study(request["id"], "INITIAL", window[0], window[1])
    start_day = int(window[0][-2:])
    dates = [f"{window[0][:-2]}{start_day + i:02d}" for i in range(3)]
    for d in dates:
        record_observation(study["id"], d, *obs_recipe)
    analyze_study(study["id"])
    study = certify_study(study["id"])
    request = get_request(request["id"])
    return {
        "segment": segment, "residents": residents,
        "request": request, "study": study,
    }


# ---------------------------------------------------------------------------
# Tier 3 — funding cycles and the ranking waterfall
# ---------------------------------------------------------------------------

def create_funding_cycle(cycle_year=2026, budget_total_cents=50000):
    resp = api_client.create_funding_cycle(
        create_funding_cycle_payload(
            cycle_year=cycle_year, budget_total_cents=budget_total_cents,
        ),
        ADMIN,
    )
    return _ok("create_funding_cycle", resp)


def get_funding_cycle(cycle_id):
    resp = api_client.get_funding_cycle(cycle_id, ADMIN)
    return _ok("get_funding_cycle", resp)


def publish_ranking(cycle_id):
    """Publish with the cycle's current version (PRD §2.7 OCC input)."""
    version = get_funding_cycle(cycle_id)["version"]
    resp = api_client.publish_ranking(
        cycle_id, {"expected_funding_cycle_version": version}, ADMIN
    )
    return _ok("publish_ranking", resp)


def close_cycle(cycle_id):
    resp = api_client.close_cycle(cycle_id, ADMIN)
    return _ok("close_cycle", resp)


def setup_funded(cycle_year=2026, cycle_budget_total_cents=50000, **kwargs):
    """Drive one request through certification and fund it via ranking
    publication. Returns ctx with cycle added."""
    ctx = setup_ranking_eligible(**kwargs)
    cycle = create_funding_cycle(cycle_year, cycle_budget_total_cents)
    cycle = publish_ranking(cycle["id"])
    ctx["cycle"] = cycle
    ctx["request"] = get_request(ctx["request"]["id"])
    assert ctx["request"]["status"] == "FUNDED", (
        f"Setup failed: expected FUNDED, got {ctx['request']['status']}"
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — treatment plans and ballots
# ---------------------------------------------------------------------------

def create_treatment_plan(request_id, treatment_type="SPEED_HUMP",
                          estimated_cost_cents=9000,
                          author_user_id=DEFAULT_PLAN_AUTHOR):
    """Create a plan draft against the request's current version."""
    version = get_request(request_id)["version"]
    resp = api_client.create_treatment_plan(
        request_id,
        create_treatment_plan_payload(
            treatment_type=treatment_type,
            estimated_cost_cents=estimated_cost_cents,
            expected_request_version=version,
        ),
        make_traffic_engineer_headers(author_user_id),
    )
    return _ok("create_treatment_plan", resp)


def submit_plan_for_review(plan_id, user_id=DEFAULT_PLAN_AUTHOR):
    resp = api_client.submit_plan_for_review(
        plan_id, make_traffic_engineer_headers(user_id)
    )
    return _ok("submit_plan_for_review", resp)


def approve_plan(plan_id, user_id=DEFAULT_PLAN_APPROVER):
    resp = api_client.approve_plan(
        plan_id, make_city_engineer_headers(user_id)
    )
    return _ok("approve_plan", resp)


def get_treatment_plan(plan_id):
    resp = api_client.get_treatment_plan(plan_id, ADMIN)
    return _ok("get_treatment_plan", resp)


def setup_ballot_ready(treatment_type="SPEED_HUMP", estimated_cost_cents=9000,
                       plan_author=DEFAULT_PLAN_AUTHOR,
                       plan_approver=DEFAULT_PLAN_APPROVER, **kwargs):
    """FUNDED request + plan created, submitted and approved; the request
    reaches BALLOT_READY."""
    ctx = setup_funded(**kwargs)
    plan = create_treatment_plan(
        ctx["request"]["id"], treatment_type, estimated_cost_cents, plan_author
    )
    plan = submit_plan_for_review(plan["id"], plan_author)
    plan = approve_plan(plan["id"], plan_approver)
    ctx["plan"] = plan
    ctx["request"] = get_request(ctx["request"]["id"])
    assert ctx["request"]["status"] == "BALLOT_READY", (
        f"Setup failed: expected BALLOT_READY, got {ctx['request']['status']}"
    )
    return ctx


def create_ballot(request_id, close_date="2026-08-10T00:00:00Z"):
    resp = api_client.create_ballot(
        request_id, create_ballot_payload(close_date=close_date), TE
    )
    return _ok("create_ballot", resp)


def get_ballot(ballot_id):
    resp = api_client.get_ballot(ballot_id, ADMIN)
    return _ok("get_ballot", resp)


def cast_vote(ballot_id, resident_id, choice="FOR"):
    resp = api_client.cast_vote(
        ballot_id, create_vote_payload(choice=choice),
        make_resident_headers(resident_id),
    )
    return _ok("cast_vote", resp)


def setup_ballot_open(close_date="2026-08-10T00:00:00Z", **kwargs):
    """BALLOT_READY + ballot opened (approved plan locks). Adds ballot."""
    ctx = setup_ballot_ready(**kwargs)
    ballot = create_ballot(ctx["request"]["id"], close_date)
    ctx["ballot"] = ballot
    return ctx


def drive_funded_request_to_ballot_open(request_id,
                                        close_date="2026-08-10T00:00:00Z",
                                        treatment_type="SPEED_HUMP",
                                        estimated_cost_cents=10000,
                                        plan_author=DEFAULT_PLAN_AUTHOR,
                                        plan_approver=DEFAULT_PLAN_APPROVER):
    """For multi-request scenarios: plan -> submit -> approve -> ballot."""
    plan = create_treatment_plan(
        request_id, treatment_type, estimated_cost_cents, plan_author
    )
    plan = submit_plan_for_review(plan["id"], plan_author)
    plan = approve_plan(plan["id"], plan_approver)
    ballot = create_ballot(request_id, close_date)
    return {"plan": plan, "ballot": ballot}


def setup_consent_granted(close_date="2026-08-10T00:00:00Z",
                          sweep_to="2026-08-11T00:00:00Z",
                          voter_choices=None, **kwargs):
    """BALLOT_OPEN + FOR votes + clock sweep past close_date; the request
    reaches CONSENT_GRANTED. Default: one FOR vote (meets the 4-household
    quorum of 1)."""
    ctx = setup_ballot_open(close_date=close_date, **kwargs)
    if voter_choices is None:
        voter_choices = ["FOR"]
    for resident, choice in zip(ctx["residents"], voter_choices):
        cast_vote(ctx["ballot"]["id"], resident["id"], choice)
    set_clock(sweep_to)
    ctx["ballot"] = get_ballot(ctx["ballot"]["id"])
    ctx["request"] = get_request(ctx["request"]["id"])
    assert ctx["request"]["status"] == "CONSENT_GRANTED", (
        f"Setup failed: expected CONSENT_GRANTED, "
        f"got {ctx['request']['status']}"
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — installation work orders, post-study, removal
# ---------------------------------------------------------------------------

def create_work_order(request_id, crew_ref="CREW-1"):
    resp = api_client.create_work_order(
        request_id, create_work_order_payload(crew_ref=crew_ref), TE
    )
    return _ok("create_work_order", resp)


def get_work_order(work_order_id):
    resp = api_client.get_work_order(work_order_id, ADMIN)
    return _ok("get_work_order", resp)


def schedule_work_order(work_order_id, scheduled_date="2026-08-15",
                        duration_days=1):
    resp = api_client.schedule_work_order(
        work_order_id,
        create_schedule_payload(
            scheduled_date=scheduled_date, duration_days=duration_days
        ),
        TE,
    )
    return _ok("schedule_work_order", resp)


def review_work_order(work_order_id, decision="CLEARED",
                      reviewer=DEFAULT_REVIEWER):
    resp = api_client.review_work_order(
        work_order_id, create_review_payload(decision=decision),
        make_emergency_reviewer_headers(reviewer),
    )
    return _ok("review_work_order", resp)


def mark_installed(work_order_id):
    resp = api_client.mark_work_order_installed(work_order_id, TE)
    return _ok("mark_installed", resp)


def setup_installation_planned(crew_ref="CREW-1", **kwargs):
    """CONSENT_GRANTED + work order created (UNSCHEDULED / PENDING_REVIEW)."""
    ctx = setup_consent_granted(**kwargs)
    work_order = create_work_order(ctx["request"]["id"], crew_ref)
    ctx["work_order"] = work_order
    return ctx


def setup_installed(scheduled_date="2026-08-15", duration_days=1, **kwargs):
    """Full drive to INSTALLED: work order scheduled, emergency review
    CLEARED, clock advanced to scheduled_date, mark-installed."""
    ctx = setup_installation_planned(**kwargs)
    wo_id = ctx["work_order"]["id"]
    schedule_work_order(wo_id, scheduled_date, duration_days)
    review_work_order(wo_id, "CLEARED")
    set_clock(f"{scheduled_date}T00:00:00Z")
    ctx["work_order"] = mark_installed(wo_id)
    ctx["request"] = get_request(ctx["request"]["id"])
    assert ctx["request"]["status"] == "INSTALLED", (
        f"Setup failed: expected INSTALLED, got {ctx['request']['status']}"
    )
    return ctx


def setup_effectiveness_certified(post_window=("2026-09-20", "2026-09-22"),
                                  post_clock="2026-09-20T00:00:00Z",
                                  post_obs_recipe=(2500, 33.0, 27.0),
                                  **kwargs):
    """Full drive to EFFECTIVENESS_CERTIFIED: installed, then a
    POST_INSTALLATION study (commissioned at/after the 30-day settling
    period) collected, analyzed and certified."""
    ctx = setup_installed(**kwargs)
    set_clock(post_clock)
    study2 = commission_study(
        ctx["request"]["id"], "POST_INSTALLATION",
        post_window[0], post_window[1],
    )
    start_day = int(post_window[0][-2:])
    dates = [f"{post_window[0][:-2]}{start_day + i:02d}" for i in range(3)]
    for d in dates:
        record_observation(study2["id"], d, *post_obs_recipe)
    analyze_study(study2["id"])
    ctx["study2"] = certify_study(study2["id"])
    ctx["request"] = get_request(ctx["request"]["id"])
    assert ctx["request"]["status"] == "EFFECTIVENESS_CERTIFIED", (
        f"Setup failed: expected EFFECTIVENESS_CERTIFIED, "
        f"got {ctx['request']['status']}"
    )
    return ctx


def file_removal_request(request_id, resident_id, reason="Too noisy"):
    resp = api_client.create_removal_request(
        request_id,
        {"reason": reason},
        make_resident_headers(resident_id),
    )
    return _ok("file_removal_request", resp)
