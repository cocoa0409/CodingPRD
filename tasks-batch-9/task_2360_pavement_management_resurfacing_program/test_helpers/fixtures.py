"""Composite state builders for the Pavement Management & Resurfacing Program API.

The server under test starts from an empty database for every single test, so
every precondition has to be built from scratch through the API's own endpoints.
The builders below climb the program's dependency chain one tier at a time:

  Tier 1  primitive writes            set_clock, create_segment, open_survey, ...
  Tier 2  entity hierarchy            sealed_survey, survey_with_candidates
  Tier 3  lifecycle shortcuts         adopted_program, draft_project,
                                      coordinating_project, bid_ready_project,
                                      awarded_project, in_construction_project
  Tier 4  accumulation targeting      quality_accepted_project, failing_test
  Tier 5  terminal / finalisation     substantially_complete_project,
                                      accepted_project, moratorium_segment

Every builder returns the API's own response rows so tests can assert against
them, and every builder threads the captured identifiers forward rather than
guessing them.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import PavementApiClient
from .constants import (
    CLOCK_2026_09_15,
    CLOCK_2026_10_01,
    DEFAULT_CLOCK,
    FUNDING_STANDARD,
    HORIZON_YEARS,
    OBS_CS75,
    OBS_MILL,
    OBS_RECON,
    SEG_ELM,
    SEG_GRAND,
    SEG_MAPLE,
    SEG_OAK,
    SEG_PINE,
    STRATEGY_WORST_FIRST,
    UTILITY_ROSTER,
)
from .test_users import (
    ENGINEER,
    INSPECTOR_ACCEPTOR,
    INSPECTOR_DECIDER,
    INSPECTOR_WITNESS,
    OFFICER,
    OFFICER_ADOPTER,
    OFFICER_AWARDER,
    COORDINATOR,
    make_contractor_headers,
)

# Default notice window: well clear of the mandatory 72-hour lead time from the
# 2026-08-01 logical clock.
NOTICE_START = "2026-09-01T00:00:00Z"
NOTICE_END = "2026-09-15T00:00:00Z"

# ----------------------------------------------------------------------
# Tier 1 — primitive writes
# ----------------------------------------------------------------------


def set_clock(api: PavementApiClient, instant: str = DEFAULT_CLOCK) -> Dict[str, Any]:
    """Pin the logical clock. Every scenario starts by doing this explicitly."""
    return get_success_data(api.set_clock(instant, ENGINEER))


def create_segment(
    api: PavementApiClient, profile: Dict[str, Any] = SEG_MAPLE, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_segment(f.segment_payload(profile, **overrides), ENGINEER), 201
    )


def create_segments(
    api: PavementApiClient, profiles: Sequence[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Create several segments and key the returned rows by street name."""
    rows: Dict[str, Dict[str, Any]] = {}
    for profile in profiles:
        row = create_segment(api, profile)
        rows[profile["street_name"]] = row
    return rows


def open_survey(api: PavementApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_survey(f.survey_payload(**overrides), ENGINEER), 201)


def file_observation(
    api: PavementApiClient,
    survey_id: str,
    segment_id: str,
    profile: Dict[str, Any] = OBS_MILL,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_observation(
            f.observation_payload(survey_id, segment_id, profile, **overrides), ENGINEER
        ),
        201,
    )


def accept_observation(api: PavementApiClient, observation_id: str) -> Dict[str, Any]:
    return get_success_data(api.qc_observation(observation_id, f.qc_payload("ACCEPT"), ENGINEER))


def seal_survey(api: PavementApiClient, survey_id: str) -> Dict[str, Any]:
    return get_success_data(api.seal_survey(survey_id, ENGINEER))


def generate_candidates(api: PavementApiClient, survey_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.generate_candidates(survey_id, ENGINEER))


def register_contractor(
    api: PavementApiClient, legal_name: str = "Ace Paving LLC", max_concurrent_projects: int = 2
) -> Dict[str, Any]:
    return get_success_data(
        api.create_contractor(
            f.contractor_payload(legal_name, max_concurrent_projects), ENGINEER
        ),
        201,
    )


def create_scenario(api: PavementApiClient, survey_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_scenario(f.scenario_payload(survey_id, **overrides), OFFICER), 201
    )


def run_scenario(api: PavementApiClient, scenario_id: str) -> Dict[str, Any]:
    return get_success_data(api.run_scenario(scenario_id, OFFICER))


def adopt_scenario(api: PavementApiClient, scenario_id: str) -> Dict[str, Any]:
    """Adoption is recorded against officer-adopt-1, who may then not award."""
    return get_success_data(api.adopt_scenario(scenario_id, OFFICER_ADOPTER))


def read_scenario(api: PavementApiClient, scenario_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_scenario(scenario_id, OFFICER))


def read_project(api: PavementApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_project(project_id, ENGINEER))


def read_segment(api: PavementApiClient, segment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_segment(segment_id, ENGINEER))


def read_line(api: PavementApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_project_segment(line_id, ENGINEER))


def read_candidate(api: PavementApiClient, candidate_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_candidate(candidate_id, ENGINEER))


def read_contractor(api: PavementApiClient, contractor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contractor(contractor_id, ENGINEER))


def project_version(api: PavementApiClient, project_id: str) -> int:
    """Fresh read of the parent project's version for the stale-read guard."""
    return read_project(api, project_id)["version"]


def scenario_version(api: PavementApiClient, scenario_id: str) -> int:
    return read_scenario(api, scenario_id)["version"]


def create_project(
    api: PavementApiClient, scenario_id: str, geo_zone: str = "Z1", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_project(f.project_payload(scenario_id, geo_zone, **overrides), ENGINEER), 201
    )


def add_line(
    api: PavementApiClient,
    project_id: str,
    segment_id: str,
    candidate_id: str,
    work_window_start: str = "2026-09-01T00:00:00Z",
    work_window_end: str = "2026-09-15T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Add one line, reading the project's current version for the guard first."""
    payload = f.project_segment_payload(
        project_id,
        segment_id,
        candidate_id,
        project_version(api, project_id),
        work_window_start,
        work_window_end,
        **overrides,
    )
    return get_success_data(api.create_project_segment(payload, ENGINEER), 201)


def advance(api: PavementApiClient, project_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(api.advance_project(project_id, f.advance_payload(action), ENGINEER))


def list_coordinations(api: PavementApiClient, project_id: str) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(
        api.list_coordinations(ENGINEER, {"project_id": project_id, "limit": 100})
    )
    return rows


def respond_coordination(
    api: PavementApiClient, coordination_id: str, response: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_coordination(
            coordination_id, f.respond_payload(response, **overrides), COORDINATOR
        )
    )


def complete_coordination_work(api: PavementApiClient, coordination_id: str) -> Dict[str, Any]:
    return get_success_data(api.complete_coordination_work(coordination_id, COORDINATOR))


def award(
    api: PavementApiClient,
    project_id: str,
    contractor_id: str,
    award_amount_cents: int,
) -> Dict[str, Any]:
    """Awards run as officer-award-1, who is not the adopting officer."""
    return get_success_data(
        api.award_project(
            project_id, f.award_payload(contractor_id, award_amount_cents), OFFICER_AWARDER
        )
    )


def schedule_notice(
    api: PavementApiClient,
    line_id: str,
    start: str = NOTICE_START,
    end: str = NOTICE_END,
    plan: str = "MAINTAINED",
) -> Dict[str, Any]:
    return get_success_data(
        api.notice(line_id, f.schedule_notice_payload(start, end, plan), ENGINEER)
    )


def deliver_notice(api: PavementApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(api.notice(line_id, f.notice_payload("DELIVER"), ENGINEER))


def submit_test(
    api: PavementApiClient,
    line_id: str,
    core_density_pct: float = 97.0,
    iri_in_per_mi: float = 55.0,
    thickness_in: float = 2.10,
    witness: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.acceptance_test_payload(
        line_id,
        witness or INSPECTOR_WITNESS["X-User-ID"],
        core_density_pct,
        iri_in_per_mi,
        thickness_in,
    )
    return get_success_data(api.create_acceptance_test(payload, INSPECTOR_WITNESS), 201)


def decide_test(
    api: PavementApiClient,
    test_id: str,
    decision: str,
    decision_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Decisions run as insp-decider-1, who never witnesses a coring."""
    return get_success_data(
        api.decide_acceptance_test(
            test_id, f.acceptance_decision_payload(decision, decision_note), headers or INSPECTOR_DECIDER
        )
    )


def declare_substantial_completion(
    api: PavementApiClient, project_id: str, contractor_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.substantial_completion(project_id, {}, make_contractor_headers(contractor_id))
    )


def sign_acceptance(api: PavementApiClient, project_id: str) -> Dict[str, Any]:
    """Final acceptance runs as insp-acceptor-1, who witnessed nothing."""
    return get_success_data(api.accept_project(project_id, {}, INSPECTOR_ACCEPTOR))


def apply_cut_permit(
    api: PavementApiClient, segment_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cut_permit(f.cut_permit_payload(segment_id, **overrides), COORDINATOR), 201
    )


def decide_cut_permit(
    api: PavementApiClient, permit_id: str, decision: str = "APPROVE", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_cut_permit(permit_id, f.cut_decide_payload(decision, **overrides), ENGINEER)
    )


def file_service_request(
    api: PavementApiClient, segment_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    from .test_users import RESIDENT

    return get_success_data(
        api.create_service_request(
            f.service_request_payload(segment_id, **overrides), headers or RESIDENT
        ),
        201,
    )


def triage_service_request(
    api: PavementApiClient, request_id: str, disposition: str, target_project_id: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.triage_service_request(
            request_id, f.triage_payload(disposition, target_project_id), ENGINEER
        )
    )


def close_service_request(
    api: PavementApiClient, request_id: str, closure_code: str
) -> Dict[str, Any]:
    return get_success_data(
        api.close_service_request(request_id, f.close_payload(closure_code), ENGINEER)
    )


# ----------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ----------------------------------------------------------------------

# A survey plan is a list of (segment profile, observation profile) pairs.
SegmentPlan = Sequence[Tuple[Dict[str, Any], Dict[str, Any]]]

MAPLE_ONLY: SegmentPlan = [(SEG_MAPLE, OBS_MILL)]
MAPLE_AND_GRAND: SegmentPlan = [(SEG_MAPLE, OBS_MILL), (SEG_GRAND, OBS_RECON)]
MAPLE_AND_OAK: SegmentPlan = [(SEG_MAPLE, OBS_MILL), (SEG_OAK, OBS_CS75)]
ELM_AND_PINE: SegmentPlan = [(SEG_ELM, OBS_CS75), (SEG_PINE, OBS_CS75)]


def open_survey_with_observations(
    api: PavementApiClient,
    plan: SegmentPlan = MAPLE_ONLY,
    clock: str = DEFAULT_CLOCK,
    accept_all: bool = True,
    survey_year: int = 2026,
) -> Dict[str, Any]:
    """Clock, segments, an OPEN survey and one observation per segment."""
    set_clock(api, clock)
    ctx: Dict[str, Any] = {
        "clock": clock,
        "segments": {},
        "observations": {},
        "candidates": {},
        "lines": {},
    }
    for segment_profile, _obs_profile in plan:
        row = create_segment(api, segment_profile)
        ctx["segments"][segment_profile["street_name"]] = row
    ctx["survey"] = open_survey(api, survey_year=survey_year)
    for segment_profile, obs_profile in plan:
        segment = ctx["segments"][segment_profile["street_name"]]
        observation = file_observation(
            api, ctx["survey"]["id"], segment["id"], obs_profile
        )
        ctx["observations"][segment_profile["street_name"]] = observation
        if accept_all:
            accept_observation(api, observation["id"])
    return ctx


def sealed_survey(
    api: PavementApiClient,
    plan: SegmentPlan = MAPLE_ONLY,
    clock: str = DEFAULT_CLOCK,
    survey_year: int = 2026,
) -> Dict[str, Any]:
    """Everything from ``open_survey_with_observations``, then the seal cascade."""
    ctx = open_survey_with_observations(api, plan, clock, survey_year=survey_year)
    ctx["survey"] = seal_survey(api, ctx["survey"]["id"])
    return ctx


def survey_with_candidates(
    api: PavementApiClient,
    plan: SegmentPlan = MAPLE_ONLY,
    clock: str = DEFAULT_CLOCK,
) -> Dict[str, Any]:
    """A sealed survey whose priced treatment candidates have been generated."""
    ctx = sealed_survey(api, plan, clock)
    candidates = generate_candidates(api, ctx["survey"]["id"])
    ctx["candidate_list"] = candidates
    for candidate in candidates:
        ctx["candidates"][candidate["segment_id"]] = candidate
    return ctx


def candidate_for(ctx: Dict[str, Any], street_name: str) -> Dict[str, Any]:
    """The candidate generated for one named street."""
    segment = ctx["segments"][street_name]
    return ctx["candidates"][segment["id"]]


def segment_for(ctx: Dict[str, Any], street_name: str) -> Dict[str, Any]:
    return ctx["segments"][street_name]


# ----------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ----------------------------------------------------------------------


def computed_scenario(
    api: PavementApiClient,
    plan: SegmentPlan = MAPLE_ONLY,
    funding_cents: int = FUNDING_STANDARD,
    strategy: str = STRATEGY_WORST_FIRST,
    horizon_years: int = HORIZON_YEARS,
    clock: str = DEFAULT_CLOCK,
    contractor_name: str = "Ace Paving LLC",
    max_concurrent_projects: int = 2,
) -> Dict[str, Any]:
    """Candidates generated, a contractor registered and the waterfall run."""
    ctx = survey_with_candidates(api, plan, clock)
    ctx["contractor"] = register_contractor(api, contractor_name, max_concurrent_projects)
    ctx["scenario"] = create_scenario(
        api,
        ctx["survey"]["id"],
        funding_cents=funding_cents,
        strategy=strategy,
        horizon_years=horizon_years,
    )
    ctx["scenario"] = run_scenario(api, ctx["scenario"]["id"])
    return ctx


def adopted_program(
    api: PavementApiClient,
    plan: SegmentPlan = MAPLE_ONLY,
    funding_cents: int = FUNDING_STANDARD,
    strategy: str = STRATEGY_WORST_FIRST,
    horizon_years: int = HORIZON_YEARS,
    clock: str = DEFAULT_CLOCK,
    contractor_name: str = "Ace Paving LLC",
    max_concurrent_projects: int = 2,
) -> Dict[str, Any]:
    """A run scenario adopted as the capital program of record."""
    ctx = computed_scenario(
        api,
        plan,
        funding_cents,
        strategy,
        horizon_years,
        clock,
        contractor_name,
        max_concurrent_projects,
    )
    ctx["scenario"] = adopt_scenario(api, ctx["scenario"]["id"])
    return ctx


LineSpec = Tuple[str, str, str]  # (street name, work_window_start, work_window_end)

MAPLE_LINE: Sequence[LineSpec] = [("Maple St", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")]


def draft_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    geo_zone: str = "Z1",
    planned_start_date: str = "2026-09-01T00:00:00Z",
    planned_end_date: str = "2026-09-30T00:00:00Z",
    project_name: str = "Zone 1 fall package",
    **line_overrides: Any,
) -> Dict[str, Any]:
    """A DRAFT project under the adopted scenario, carrying the named lines."""
    ctx["project"] = create_project(
        api,
        ctx["scenario"]["id"],
        geo_zone,
        project_name=project_name,
        planned_start_date=planned_start_date,
        planned_end_date=planned_end_date,
    )
    for street_name, window_start, window_end in lines:
        segment = segment_for(ctx, street_name)
        candidate = candidate_for(ctx, street_name)
        line = add_line(
            api,
            ctx["project"]["id"],
            segment["id"],
            candidate["id"],
            window_start,
            window_end,
            **line_overrides,
        )
        ctx["lines"][street_name] = line
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def coordinating_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A project advanced into COORDINATING with its four utility rows open."""
    if "project" not in ctx:
        ctx = draft_project(api, ctx, lines, **kwargs)
    ctx["project"] = advance(api, ctx["project"]["id"], "START_COORDINATION")
    ctx["coordinations"] = list_coordinations(api, ctx["project"]["id"])
    return ctx


def coordination_for(ctx: Dict[str, Any], utility: str) -> Dict[str, Any]:
    for row in ctx["coordinations"]:
        if row["utility"] == utility:
            return row
    raise AssertionError(f"no coordination row for utility {utility}")


def clear_all_coordinations(api: PavementApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Answer CLEAR on all four clearance rows, in roster order."""
    for utility in UTILITY_ROSTER:
        row = coordination_for(ctx, utility)
        respond_coordination(api, row["id"], "CLEAR", response_note="no facilities in conflict")
    ctx["coordinations"] = list_coordinations(api, ctx["project"]["id"])
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def bid_ready_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Every utility cleared and the bundle priced at BID_READY."""
    if "coordinations" not in ctx:
        ctx = coordinating_project(api, ctx, lines, **kwargs)
    ctx = clear_all_coordinations(api, ctx)
    ctx["project"] = advance(api, ctx["project"]["id"], "BID_READY")
    return ctx


def awarded_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    award_amount_cents: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A BID_READY bundle awarded to the registered contractor."""
    if ctx.get("project", {}).get("delivery_status") != "BID_READY":
        ctx = bid_ready_project(api, ctx, lines, **kwargs)
    amount = (
        award_amount_cents
        if award_amount_cents is not None
        else ctx["project"]["project_total_estimate_cents"]
    )
    ctx["award_amount_cents"] = amount
    ctx["project"] = award(api, ctx["project"]["id"], ctx["contractor"]["id"], amount)
    ctx["scenario"] = read_scenario(api, ctx["scenario"]["id"])
    return ctx


def deliver_all_notices(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    start: str = NOTICE_START,
    end: str = NOTICE_END,
) -> Dict[str, Any]:
    """Schedule and deliver the resident notice on every line of the bundle."""
    for street_name, line in list(ctx["lines"].items()):
        schedule_notice(api, line["id"], start, end)
        ctx["lines"][street_name] = deliver_notice(api, line["id"])
    return ctx


def in_construction_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    award_amount_cents: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Notices delivered on every line and crews on the street."""
    if ctx.get("project", {}).get("delivery_status") != "AWARDED":
        ctx = awarded_project(api, ctx, lines, award_amount_cents, **kwargs)
    ctx = deliver_all_notices(api, ctx)
    ctx["project"] = advance(api, ctx["project"]["id"], "START_CONSTRUCTION")
    for street_name, line in list(ctx["lines"].items()):
        ctx["lines"][street_name] = read_line(api, line["id"])
    return ctx


# ----------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ----------------------------------------------------------------------


def passing_test_on(
    api: PavementApiClient, ctx: Dict[str, Any], street_name: str
) -> Dict[str, Any]:
    """Submit a full-marks test on one line and decide it PASS."""
    line = ctx["lines"][street_name]
    submitted = submit_test(api, line["id"])
    decided = decide_test(api, submitted["id"], "PASS", "cores conform")
    ctx.setdefault("tests", {})[street_name] = decided
    ctx["lines"][street_name] = read_line(api, line["id"])
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


def failing_test_on(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    street_name: str,
    core_density_pct: float = 91.9,
) -> Dict[str, Any]:
    """Submit a below-floor density test on one line and decide it FAIL."""
    line = ctx["lines"][street_name]
    submitted = submit_test(api, line["id"], core_density_pct=core_density_pct)
    decided = decide_test(api, submitted["id"], "FAIL", "density below the floor")
    ctx.setdefault("tests", {})[street_name] = decided
    ctx["lines"][street_name] = read_line(api, line["id"])
    ctx["project"] = read_project(api, ctx["project"]["id"])
    ctx["contractor"] = read_contractor(api, ctx["contractor"]["id"])
    return ctx


def quality_accepted_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Every non-crack-seal line passing, so the quality dimension is accepted."""
    if ctx.get("project", {}).get("delivery_status") != "IN_CONSTRUCTION":
        ctx = in_construction_project(api, ctx, lines, **kwargs)
    for street_name, line in list(ctx["lines"].items()):
        if line["treatment_type"] == "CRACK_SEAL":
            # A crack-seal line needs no acceptance test, but it still has to
            # reach WORK_COMPLETE, which only a passed test delivers.
            ctx = passing_test_on(api, ctx, street_name)
        else:
            ctx = passing_test_on(api, ctx, street_name)
    ctx["project"] = read_project(api, ctx["project"]["id"])
    return ctx


# ----------------------------------------------------------------------
# Tier 5 — terminal states and finalisation
# ----------------------------------------------------------------------


def substantially_complete_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    completion_clock: str = CLOCK_2026_09_15,
    **kwargs: Any,
) -> Dict[str, Any]:
    """All lines complete, the clock moved on and the contractor's declaration in."""
    if ctx.get("project", {}).get("quality_status") != "QUALITY_ACCEPTED":
        ctx = quality_accepted_project(api, ctx, lines, **kwargs)
    set_clock(api, completion_clock)
    ctx["clock"] = completion_clock
    ctx["project"] = declare_substantial_completion(
        api, ctx["project"]["id"], ctx["contractor"]["id"]
    )
    ctx["contractor"] = read_contractor(api, ctx["contractor"]["id"])
    return ctx


def accepted_project(
    api: PavementApiClient,
    ctx: Dict[str, Any],
    lines: Sequence[LineSpec] = MAPLE_LINE,
    completion_clock: str = CLOCK_2026_09_15,
    acceptance_clock: str = CLOCK_2026_10_01,
    **kwargs: Any,
) -> Dict[str, Any]:
    """The widest cascade: final acceptance signed and the pavement republished."""
    if ctx.get("project", {}).get("delivery_status") != "SUBSTANTIALLY_COMPLETE":
        ctx = substantially_complete_project(api, ctx, lines, completion_clock, **kwargs)
    set_clock(api, acceptance_clock)
    ctx["clock"] = acceptance_clock
    ctx["project"] = sign_acceptance(api, ctx["project"]["id"])
    for street_name, segment in list(ctx["segments"].items()):
        ctx["segments"][street_name] = read_segment(api, segment["id"])
    for street_name, line in list(ctx["lines"].items()):
        ctx["lines"][street_name] = read_line(api, line["id"])
    ctx["contractor"] = read_contractor(api, ctx["contractor"]["id"])
    return ctx


# ----------------------------------------------------------------------
# One-call program shortcuts for the most reused states
# ----------------------------------------------------------------------


def maple_bid_ready(api: PavementApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The canonical single-line Maple St bundle, priced and out for bid."""
    ctx = adopted_program(api, MAPLE_ONLY, **kwargs)
    return bid_ready_project(api, ctx)


def maple_awarded(api: PavementApiClient, **kwargs: Any) -> Dict[str, Any]:
    ctx = adopted_program(api, MAPLE_ONLY, **kwargs)
    return awarded_project(api, ctx)


def maple_in_construction(api: PavementApiClient, **kwargs: Any) -> Dict[str, Any]:
    ctx = adopted_program(api, MAPLE_ONLY, **kwargs)
    return in_construction_project(api, ctx)


def maple_accepted(api: PavementApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A Maple St mill-and-overlay carried all the way to final acceptance."""
    ctx = adopted_program(api, MAPLE_ONLY, **kwargs)
    return accepted_project(api, ctx)


def moratorium_segment(api: PavementApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Maple St under a three-year mill-and-overlay moratorium from 2026-10-01."""
    return maple_accepted(api, **kwargs)
