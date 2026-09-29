"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch through the documented endpoints only. The helpers
are layered: single-row creators at the bottom, then progression helpers that
drive one entity along its state machine, then whole-chain shortcuts that hand
back a residency already parked in the state a test needs.

Two chains recur throughout the suite:

* the short chain — set the clock, create a cycle, add a discipline, register an
  artist, open the cycle, create a residency directly and schedule it;
* the panel chain — the first five steps of the short chain, then an
  application with portfolio items and a settled fee, a submission, screening,
  panel review and scores.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient
from .assertions import expected_session_end, require_by, shift_days
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    make_applicant_payload,
    make_application_payload,
    make_chair_payload,
    make_compliance_payload,
    make_conflict_payload,
    make_cycle_payload,
    make_discipline_payload,
    make_fee_resolution_payload,
    make_housing_assignment_payload,
    make_housing_unit_payload,
    make_international_applicant_payload,
    make_lifecycle_payload,
    make_obligation_progress_payload,
    make_offer_response_payload,
    make_panel_assignment_payload,
    make_panelist_payload,
    make_portfolio_item_payload,
    make_residency_payload,
    make_schedule_payload,
    make_score_payload,
    make_screening_decision_payload,
    make_settlement_payload,
    make_stipend_schedule_payload,
    make_studio_assignment_payload,
    make_studio_payload,
    make_training_payload,
    make_visa_case_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    FACILITIES_HEADERS,
    FINANCE_PAYER_HEADERS,
    FINANCE_SCHEDULER_HEADERS,
    VISA_HEADERS,
    make_applicant_headers,
    make_panel_chair_headers,
    make_panelist_headers,
)
from .types import (
    ApplicantContext,
    ApplicationContext,
    CycleContext,
    HousingUnitContext,
    PanelistContext,
    ResidencyContext,
    StudioContext,
)

# Canonical calendar landmarks used across the suite.
CLOCK_INSIDE_WINDOW = "2026-08-10T00:00:00Z"
DEFAULT_SESSION_START = "2026-11-02"
DEFAULT_SESSION_WEEKS = 8
DEFAULT_SESSION_END = expected_session_end(DEFAULT_SESSION_START, DEFAULT_SESSION_WEEKS)

# A sponsored artist has to clear a consulate before checking in, and the filing
# deadline sits 111 days before the session opens.  A March session therefore
# keeps that deadline in the future while the clock still reads August 2026.
SPONSORED_SESSION_START = "2027-03-01"
SPONSORED_SESSION_END = expected_session_end(
    SPONSORED_SESSION_START, DEFAULT_SESSION_WEEKS
)
SPONSORED_CONSULATE_DATE = "2026-12-01"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; this writes no row and bumps no version."""
    return get_success_data(api.set_clock(current_utc, ADMIN_HEADERS))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    return set_clock(api, DEFAULT_CLOCK_UTC)


# ---------------------------------------------------------------------------
# Single-row creators
# ---------------------------------------------------------------------------
def create_cycle(api: ApiClient, **overrides) -> CycleContext:
    payload = make_cycle_payload(**overrides)
    cycle = get_success_data(api.create_cycle(payload, ADMIN_HEADERS), 201)
    return CycleContext(
        cycle_id=cycle["id"], cycle_code=cycle["code"], cycle=cycle
    )


def refresh_cycle(api: ApiClient, ctx: CycleContext) -> Dict[str, Any]:
    ctx.cycle = get_success_data(api.get_cycle(ctx.cycle_id, ADMIN_HEADERS))
    return ctx.cycle


def read_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cycle(cycle_id, ADMIN_HEADERS))


def add_discipline(api: ApiClient, ctx: CycleContext, **overrides) -> Dict[str, Any]:
    payload = make_discipline_payload(ctx.cycle_id, **overrides)
    discipline = get_success_data(api.create_discipline(payload, ADMIN_HEADERS), 201)
    ctx.discipline_ids[discipline["code"]] = discipline["id"]
    ctx.disciplines[discipline["code"]] = discipline
    return discipline


def create_applicant(api: ApiClient, **overrides) -> ApplicantContext:
    payload = make_applicant_payload(**overrides)
    row = get_success_data(api.create_applicant(payload, ADMIN_HEADERS), 201)
    return ApplicantContext(
        applicant_id=row["id"],
        email=row["email"],
        applicant=row,
        headers=make_applicant_headers(row["id"]),
    )


def create_international_applicant(api: ApiClient, **overrides) -> ApplicantContext:
    payload = make_international_applicant_payload(**overrides)
    row = get_success_data(api.create_applicant(payload, ADMIN_HEADERS), 201)
    return ApplicantContext(
        applicant_id=row["id"],
        email=row["email"],
        applicant=row,
        headers=make_applicant_headers(row["id"]),
    )


def create_panelist(api: ApiClient, **overrides) -> PanelistContext:
    payload = make_panelist_payload(**overrides)
    row = get_success_data(api.create_panelist(payload, ADMIN_HEADERS), 201)
    return PanelistContext(
        panelist_id=row["id"],
        email=row["email"],
        panelist=row,
        headers=make_panelist_headers(row["id"]),
        chair_headers=make_panel_chair_headers(row["id"]),
    )


def create_chair(api: ApiClient, **overrides) -> PanelistContext:
    payload = make_chair_payload(**overrides)
    row = get_success_data(api.create_panelist(payload, ADMIN_HEADERS), 201)
    return PanelistContext(
        panelist_id=row["id"],
        email=row["email"],
        panelist=row,
        headers=make_panelist_headers(row["id"]),
        chair_headers=make_panel_chair_headers(row["id"]),
    )


def create_studio(api: ApiClient, **overrides) -> StudioContext:
    payload = make_studio_payload(**overrides)
    row = get_success_data(api.create_studio(payload, FACILITIES_HEADERS), 201)
    return StudioContext(studio_id=row["id"], code=row["code"], studio=row)


def refresh_studio(api: ApiClient, ctx: StudioContext) -> Dict[str, Any]:
    ctx.studio = get_success_data(api.get_studio(ctx.studio_id, FACILITIES_HEADERS))
    return ctx.studio


def create_housing_unit(api: ApiClient, **overrides) -> HousingUnitContext:
    payload = make_housing_unit_payload(**overrides)
    row = get_success_data(api.create_housing_unit(payload, ADMIN_HEADERS), 201)
    return HousingUnitContext(housing_unit_id=row["id"], code=row["code"], unit=row)


def refresh_housing_unit(api: ApiClient, ctx: HousingUnitContext) -> Dict[str, Any]:
    ctx.unit = get_success_data(api.get_housing_unit(ctx.housing_unit_id, ADMIN_HEADERS))
    return ctx.unit


# ---------------------------------------------------------------------------
# Cycle stage progression
# ---------------------------------------------------------------------------
def advance_stage(api: ApiClient, cycle_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(api.advance_cycle_stage(cycle_id, to_status, ADMIN_HEADERS))


def open_cycle(api: ApiClient, ctx: CycleContext) -> Dict[str, Any]:
    ctx.cycle = advance_stage(api, ctx.cycle_id, "OPEN")
    return ctx.cycle


def advance_to_screening(api: ApiClient, ctx: CycleContext) -> Dict[str, Any]:
    ctx.cycle = advance_stage(api, ctx.cycle_id, "SCREENING")
    return ctx.cycle


def advance_to_panel_review(api: ApiClient, ctx: CycleContext) -> Dict[str, Any]:
    ctx.cycle = advance_stage(api, ctx.cycle_id, "PANEL_REVIEW")
    return ctx.cycle


def setup_open_cycle(
    api: ApiClient,
    clock: str = CLOCK_INSIDE_WINDOW,
    discipline_overrides: Optional[Dict[str, Any]] = None,
    discipline_specs: Optional[List[Dict[str, Any]]] = None,
    **cycle_overrides,
) -> CycleContext:
    """Clock, cycle, one or more disciplines, cycle opened for applications."""
    set_clock(api, clock)
    ctx = create_cycle(api, **cycle_overrides)
    for spec in discipline_specs or [discipline_overrides or {}]:
        add_discipline(api, ctx, **spec)
    open_cycle(api, ctx)
    return ctx


def setup_draft_cycle(
    api: ApiClient, clock: str = CLOCK_INSIDE_WINDOW, **cycle_overrides
) -> CycleContext:
    """Clock plus a cycle still in its configuration stage."""
    set_clock(api, clock)
    return create_cycle(api, **cycle_overrides)


# ---------------------------------------------------------------------------
# Residencies created directly
# ---------------------------------------------------------------------------
def create_residency(
    api: ApiClient,
    cycle: CycleContext,
    applicant: ApplicantContext,
    discipline_code: str = "SCULPT",
    **overrides,
) -> ResidencyContext:
    payload = make_residency_payload(
        cycle.cycle_id,
        applicant.applicant_id,
        cycle.discipline_id(discipline_code),
        **overrides,
    )
    row = get_success_data(api.create_residency(payload, ADMIN_HEADERS), 201)
    return ResidencyContext(
        residency_id=row["id"],
        residency=row,
        cycle_id=cycle.cycle_id,
        applicant_id=applicant.applicant_id,
        discipline_id=cycle.discipline_id(discipline_code),
        applicant_headers=applicant.headers,
        application_id=row.get("application_id"),
    )


def refresh_residency(api: ApiClient, ctx: ResidencyContext) -> Dict[str, Any]:
    ctx.residency = get_success_data(api.get_residency(ctx.residency_id, ADMIN_HEADERS))
    return ctx.residency


def read_residency(api: ApiClient, residency_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_residency(residency_id, ADMIN_HEADERS))


def schedule_residency(
    api: ApiClient,
    ctx: ResidencyContext,
    session_start_date: str = DEFAULT_SESSION_START,
    session_length_weeks: int = DEFAULT_SESSION_WEEKS,
) -> Dict[str, Any]:
    payload = make_schedule_payload(session_start_date, session_length_weeks)
    ctx.residency = get_success_data(
        api.schedule_residency(ctx.residency_id, payload, ADMIN_HEADERS)
    )
    return ctx.residency


def setup_scheduled_residency(
    api: ApiClient,
    clock: str = CLOCK_INSIDE_WINDOW,
    session_start_date: str = DEFAULT_SESSION_START,
    session_length_weeks: int = DEFAULT_SESSION_WEEKS,
    international: bool = False,
    discipline_overrides: Optional[Dict[str, Any]] = None,
    discipline_specs: Optional[List[Dict[str, Any]]] = None,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    **cycle_overrides,
) -> Tuple[CycleContext, ApplicantContext, ResidencyContext]:
    """The short chain, ending on a residency with a fixed session window."""
    cycle = setup_open_cycle(
        api,
        clock=clock,
        discipline_overrides=discipline_overrides,
        discipline_specs=discipline_specs,
        **cycle_overrides,
    )
    maker = create_international_applicant if international else create_applicant
    applicant = maker(api, **(applicant_overrides or {}))
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, session_start_date, session_length_weeks)
    return cycle, applicant, residency


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
def create_application(
    api: ApiClient,
    cycle: CycleContext,
    applicant: ApplicantContext,
    discipline_code: str = "SCULPT",
    **overrides,
) -> ApplicationContext:
    payload = make_application_payload(
        cycle.cycle_id,
        applicant.applicant_id,
        cycle.discipline_id(discipline_code),
        **overrides,
    )
    row = get_success_data(api.create_application(payload, ADMIN_HEADERS), 201)
    return ApplicationContext(
        application_id=row["id"],
        application=row,
        applicant=applicant,
        cycle_id=cycle.cycle_id,
        discipline_id=cycle.discipline_id(discipline_code),
    )


def refresh_application(api: ApiClient, ctx: ApplicationContext) -> Dict[str, Any]:
    ctx.application = get_success_data(
        api.get_application(ctx.application_id, ADMIN_HEADERS)
    )
    return ctx.application


def read_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_application(application_id, ADMIN_HEADERS))


def add_portfolio_item(
    api: ApiClient, ctx: ApplicationContext, **overrides
) -> Dict[str, Any]:
    payload = make_portfolio_item_payload(ctx.application_id, **overrides)
    row = get_success_data(api.create_portfolio_item(payload, ADMIN_HEADERS), 201)
    ctx.portfolio_item_ids.append(row["id"])
    return row


def settle_fee(
    api: ApiClient, ctx: ApplicationContext, action: str = "PAY"
) -> Dict[str, Any]:
    ctx.application = get_success_data(
        api.resolve_application_fee(
            ctx.application_id, make_fee_resolution_payload(action), ADMIN_HEADERS
        )
    )
    return ctx.application


def submit_application(api: ApiClient, ctx: ApplicationContext) -> Dict[str, Any]:
    ctx.application = get_success_data(
        api.submit_application(ctx.application_id, ADMIN_HEADERS)
    )
    return ctx.application


def decide_screening(
    api: ApiClient, ctx: ApplicationContext, decision: str = "ADVANCE"
) -> Dict[str, Any]:
    ctx.application = get_success_data(
        api.decide_screening(
            ctx.application_id, make_screening_decision_payload(decision), ADMIN_HEADERS
        )
    )
    return ctx.application


def setup_submitted_application(
    api: ApiClient,
    cycle: CycleContext,
    applicant: ApplicantContext,
    discipline_code: str = "SCULPT",
    media_types: Optional[List[str]] = None,
    hazardous: bool = False,
    fee_action: str = "PAY",
    **application_overrides,
) -> ApplicationContext:
    """An application with portfolio items, a settled fee and a submission."""
    app = create_application(
        api, cycle, applicant, discipline_code, **application_overrides
    )
    for media_type in media_types or ["IMAGE"]:
        add_portfolio_item(
            api,
            app,
            media_type=media_type,
            hazardous_materials_declared=hazardous,
        )
    settle_fee(api, app, fee_action)
    submit_application(api, app)
    return app


# ---------------------------------------------------------------------------
# Panel review
# ---------------------------------------------------------------------------
def assign_panelist(
    api: ApiClient, app: ApplicationContext, panelist: PanelistContext
) -> Dict[str, Any]:
    payload = make_panel_assignment_payload(app.application_id, panelist.panelist_id)
    return get_success_data(api.create_panel_assignment(payload, ADMIN_HEADERS), 201)


def score_assignment(
    api: ApiClient,
    assignment_id: str,
    panelist: PanelistContext,
    artistic: int = 8,
    feasibility: int = 8,
    community: int = 8,
    technical: int = 8,
) -> Dict[str, Any]:
    payload = make_score_payload(artistic, feasibility, community, technical)
    return get_success_data(api.submit_scores(assignment_id, payload, panelist.headers))


def assign_and_score(
    api: ApiClient,
    app: ApplicationContext,
    panelist: PanelistContext,
    artistic: int = 8,
    feasibility: int = 8,
    community: int = 8,
    technical: int = 8,
) -> Dict[str, Any]:
    """Seat a reviewer on an application and record their rubric line."""
    assignment = assign_panelist(api, app, panelist)
    return score_assignment(
        api,
        assignment["id"],
        panelist,
        artistic,
        feasibility,
        community,
        technical,
    )


def declare_conflict(
    api: ApiClient,
    assignment_id: str,
    panelist: PanelistContext,
    conflict_type: str = "FAMILIAL",
    detail: str = "the applicant is my sibling-in-law",
) -> Dict[str, Any]:
    """A reviewer's own escape hatch, exercised with the reviewer's identity."""
    return get_success_data(
        api.declare_conflict(
            assignment_id,
            make_conflict_payload(conflict_type, detail),
            panelist.headers,
        )
    )


def read_panelist(api: ApiClient, panelist_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_panelist(panelist_id, ADMIN_HEADERS))


def read_panel_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_panel_assignment(assignment_id, ADMIN_HEADERS))


def assignments_for(api: ApiClient, **params) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    rows, _ = validate_paginated(api.list_panel_assignments(ADMIN_HEADERS, query))
    return rows


def setup_panel_review_cycle(
    api: ApiClient,
    clock: str = CLOCK_INSIDE_WINDOW,
    applicant_count: int = 1,
    international_flags: Optional[List[bool]] = None,
    discipline_overrides: Optional[Dict[str, Any]] = None,
    discipline_specs: Optional[List[Dict[str, Any]]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    **cycle_overrides,
) -> Tuple[CycleContext, List[ApplicationContext]]:
    """The panel chain up to the point where reviewers can be seated.

    Applications are spread across the cycle's disciplines in creation order,
    so a two-discipline cycle with two artists puts one artist in each.
    """
    cycle = setup_open_cycle(
        api,
        clock=clock,
        discipline_overrides=discipline_overrides,
        discipline_specs=discipline_specs,
        **cycle_overrides,
    )
    codes = list(cycle.discipline_ids)
    apps: List[ApplicationContext] = []
    for index in range(applicant_count):
        abroad = bool(international_flags[index]) if international_flags else False
        maker = create_international_applicant if abroad else create_applicant
        applicant = maker(api)
        apps.append(
            setup_submitted_application(
                api,
                cycle,
                applicant,
                codes[index % len(codes)],
                **(application_overrides or {}),
            )
        )
    advance_to_screening(api, cycle)
    for app in apps:
        decide_screening(api, app, "ADVANCE")
    advance_to_panel_review(api, cycle)
    return cycle, apps


def setup_scored_application(
    api: ApiClient,
    clock: str = CLOCK_INSIDE_WINDOW,
    panelist_count: int = 2,
    scores: Optional[List[Tuple[int, int, int, int]]] = None,
    discipline_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    **cycle_overrides,
) -> Tuple[CycleContext, ApplicationContext, List[PanelistContext]]:
    """One application carried all the way to a completed panel score."""
    cycle, apps = setup_panel_review_cycle(
        api,
        clock=clock,
        applicant_count=1,
        discipline_overrides=discipline_overrides,
        application_overrides=application_overrides,
        **cycle_overrides,
    )
    app = apps[0]
    panelists: List[PanelistContext] = []
    for index in range(panelist_count):
        panelist = create_panelist(api)
        panelists.append(panelist)
        leg = scores[index] if scores and index < len(scores) else (8, 8, 8, 8)
        assign_and_score(api, app, panelist, *leg)
    refresh_application(api, app)
    return cycle, app, panelists


# ---------------------------------------------------------------------------
# Slate lock and offer response
# ---------------------------------------------------------------------------
def lock_slate(api: ApiClient, cycle: CycleContext, chair: PanelistContext):
    """Lock the slate as a chair who never reviewed inside this cycle."""
    data = get_success_data(api.lock_slate(cycle.cycle_id, chair.chair_headers))
    cycle.cycle = read_cycle(api, cycle.cycle_id)
    return data


def setup_locked_slate(
    api: ApiClient,
    clock: str = CLOCK_INSIDE_WINDOW,
    applicant_count: int = 1,
    panelist_count: int = 2,
    international_flags: Optional[List[bool]] = None,
    score_legs: Optional[List[List[Tuple[int, int, int, int]]]] = None,
    discipline_overrides: Optional[Dict[str, Any]] = None,
    discipline_specs: Optional[List[Dict[str, Any]]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    **cycle_overrides,
) -> Tuple[CycleContext, List[ApplicationContext], PanelistContext]:
    """Every application scored, then the slate locked by an uninvolved chair."""
    cycle, apps = setup_panel_review_cycle(
        api,
        clock=clock,
        applicant_count=applicant_count,
        international_flags=international_flags,
        discipline_overrides=discipline_overrides,
        discipline_specs=discipline_specs,
        application_overrides=application_overrides,
        **cycle_overrides,
    )
    panelists = [create_panelist(api) for _ in range(panelist_count)]
    for app_index, app in enumerate(apps):
        legs = None
        if score_legs and app_index < len(score_legs):
            legs = score_legs[app_index]
        for p_index, panelist in enumerate(panelists):
            leg = legs[p_index] if legs and p_index < len(legs) else (8, 8, 8, 8)
            assign_and_score(api, app, panelist, *leg)
    chair = create_chair(api)
    lock_slate(api, cycle, chair)
    for app in apps:
        refresh_application(api, app)
    return cycle, apps, chair


def respond_to_offer(
    api: ApiClient, app: ApplicationContext, response: str = "ACCEPT"
) -> Dict[str, Any]:
    """Answer an offer as the artist who owns the application."""
    app.application = get_success_data(
        api.respond_to_offer(
            app.application_id,
            make_offer_response_payload(response),
            app.applicant.headers,
        )
    )
    return app.application


def residency_for_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    rows, _ = validate_paginated(
        api.list_residencies(ADMIN_HEADERS, {"application_id": application_id})
    )
    assert rows, f"no residency exists for application {application_id}"
    return rows[0]


def setup_accepted_residency(
    api: ApiClient,
    clock: str = CLOCK_INSIDE_WINDOW,
    international: bool = False,
    panelist_count: int = 2,
    application_overrides: Optional[Dict[str, Any]] = None,
    discipline_overrides: Optional[Dict[str, Any]] = None,
    discipline_specs: Optional[List[Dict[str, Any]]] = None,
    **cycle_overrides,
) -> Tuple[CycleContext, ApplicationContext, ResidencyContext]:
    """Accept an offer and hand back the residency the acceptance created."""
    cycle, apps, _chair = setup_locked_slate(
        api,
        clock=clock,
        applicant_count=1,
        panelist_count=panelist_count,
        international_flags=[international],
        discipline_overrides=discipline_overrides,
        discipline_specs=discipline_specs,
        application_overrides=application_overrides,
        **cycle_overrides,
    )
    app = apps[0]
    respond_to_offer(api, app, "ACCEPT")
    row = residency_for_application(api, app.application_id)
    residency = ResidencyContext(
        residency_id=row["id"],
        residency=row,
        cycle_id=cycle.cycle_id,
        applicant_id=app.applicant.applicant_id,
        discipline_id=app.discipline_id,
        applicant_headers=app.applicant.headers,
        application_id=app.application_id,
    )
    return cycle, app, residency


# ---------------------------------------------------------------------------
# Trainings and compliance
# ---------------------------------------------------------------------------
def record_training(
    api: ApiClient, ctx: ResidencyContext, training_type: str
) -> Dict[str, Any]:
    return get_success_data(
        api.record_training(
            ctx.residency_id, make_training_payload(training_type), FACILITIES_HEADERS
        )
    )


def complete_all_trainings(api: ApiClient, ctx: ResidencyContext) -> Dict[str, Any]:
    """Record every training the residency requires, clearing compliance."""
    refresh_residency(api, ctx)
    for training_type in ctx.residency["required_training_types"]:
        record_training(api, ctx, training_type)
    return refresh_residency(api, ctx)


def suspend_compliance(
    api: ApiClient, ctx: ResidencyContext, reason: str = "Unsafe practice observed"
) -> Dict[str, Any]:
    ctx.residency = get_success_data(
        api.residency_compliance(
            ctx.residency_id,
            make_compliance_payload("SUSPEND", reason=reason),
            FACILITIES_HEADERS,
        )
    )
    return ctx.residency


def reinstate_compliance(api: ApiClient, ctx: ResidencyContext) -> Dict[str, Any]:
    ctx.residency = get_success_data(
        api.residency_compliance(
            ctx.residency_id, make_compliance_payload("REINSTATE"), FACILITIES_HEADERS
        )
    )
    return ctx.residency


# ---------------------------------------------------------------------------
# Residency lifecycle
# ---------------------------------------------------------------------------
def lifecycle(
    api: ApiClient,
    ctx: ResidencyContext,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    **extra,
) -> Dict[str, Any]:
    ctx.residency = get_success_data(
        api.residency_lifecycle(
            ctx.residency_id,
            make_lifecycle_payload(action, **extra),
            headers or ADMIN_HEADERS,
        )
    )
    return ctx.residency


def check_in(api: ApiClient, ctx: ResidencyContext) -> Dict[str, Any]:
    return lifecycle(api, ctx, "CHECK_IN")


def complete_residency(api: ApiClient, ctx: ResidencyContext) -> Dict[str, Any]:
    return lifecycle(api, ctx, "COMPLETE")


def terminate_residency(
    api: ApiClient, ctx: ResidencyContext, reason: str = "Studio safety breach"
) -> Dict[str, Any]:
    return lifecycle(api, ctx, "TERMINATE", reason=reason)


def withdraw_residency(
    api: ApiClient, ctx: ResidencyContext, reason: str = "Family circumstances"
) -> Dict[str, Any]:
    """Withdrawal is the artist's own action, so it uses the artist's headers."""
    return lifecycle(api, ctx, "WITHDRAW", headers=ctx.applicant_headers, reason=reason)


def setup_in_residence(
    api: ApiClient,
    clock: str = CLOCK_INSIDE_WINDOW,
    session_start_date: str = DEFAULT_SESSION_START,
    session_length_weeks: int = DEFAULT_SESSION_WEEKS,
    **kwargs,
) -> Tuple[CycleContext, ApplicantContext, ResidencyContext]:
    """A scheduled residency with trainings cleared and the artist checked in."""
    cycle, applicant, residency = setup_scheduled_residency(
        api,
        clock=clock,
        session_start_date=session_start_date,
        session_length_weeks=session_length_weeks,
        **kwargs,
    )
    complete_all_trainings(api, residency)
    set_clock(api, f"{session_start_date}T09:00:00Z")
    check_in(api, residency)
    return cycle, applicant, residency


# ---------------------------------------------------------------------------
# Studio assignments
# ---------------------------------------------------------------------------
def assign_studio(
    api: ApiClient,
    residency: ResidencyContext,
    start_date: str,
    end_date: str,
    studio: Optional[StudioContext] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Book a studio window; the residency version guards the write."""
    refresh_residency(api, residency)
    payload = make_studio_assignment_payload(
        residency.residency_id,
        start_date,
        end_date,
        residency.version if expected_version is None else expected_version,
        studio.studio_id if studio else None,
    )
    return get_success_data(api.create_studio_assignment(payload, FACILITIES_HEADERS), 201)


def release_studio_assignment(
    api: ApiClient, assignment_id: str, reason: str = "Artist relocated"
) -> Dict[str, Any]:
    return get_success_data(
        api.release_studio_assignment(assignment_id, {"reason": reason}, FACILITIES_HEADERS)
    )


def studio_assignments_for(api: ApiClient, residency_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_studio_assignments(FACILITIES_HEADERS, {"residency_id": residency_id})
    )
    return rows


# ---------------------------------------------------------------------------
# Housing assignments
# ---------------------------------------------------------------------------
def assign_housing(
    api: ApiClient,
    unit: HousingUnitContext,
    residency: ResidencyContext,
    check_in_date: str,
    check_out_date: str,
    meal_plan_selected: Optional[bool] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Book a bed for a half-open date range; the unit version guards the write."""
    refresh_housing_unit(api, unit)
    payload = make_housing_assignment_payload(
        unit.housing_unit_id,
        residency.residency_id,
        check_in_date,
        check_out_date,
        unit.version if expected_version is None else expected_version,
    )
    if meal_plan_selected is not None:
        payload["meal_plan_selected"] = meal_plan_selected
    return get_success_data(api.create_housing_assignment(payload, ADMIN_HEADERS), 201)


def release_housing_assignment(
    api: ApiClient, assignment_id: str, reason: str = "Bed reallocated"
) -> Dict[str, Any]:
    return get_success_data(
        api.release_housing_assignment(assignment_id, {"reason": reason}, ADMIN_HEADERS)
    )


def housing_assignments_for(api: ApiClient, residency_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_housing_assignments(ADMIN_HEADERS, {"residency_id": residency_id})
    )
    return rows


# ---------------------------------------------------------------------------
# Stipend disbursements
# ---------------------------------------------------------------------------
def generate_stipend_schedule(
    api: ApiClient,
    residency: ResidencyContext,
    weekly_rate_override_cents: Optional[int] = None,
    expected_version: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Generate the payment calendar as the scheduling finance officer."""
    refresh_residency(api, residency)
    payload = make_stipend_schedule_payload(
        residency.version if expected_version is None else expected_version
    )
    if weekly_rate_override_cents is not None:
        payload["weekly_rate_override_cents"] = weekly_rate_override_cents
    return get_success_data(
        api.generate_stipend_schedule(
            residency.residency_id, payload, FINANCE_SCHEDULER_HEADERS
        ),
        201,
    )


def disbursements_for(
    api: ApiClient, residency_id: str, **params
) -> List[Dict[str, Any]]:
    query = {"residency_id": residency_id, "limit": 100}
    query.update(params)
    rows, _ = validate_paginated(api.list_disbursements(FINANCE_SCHEDULER_HEADERS, query))
    return sorted(rows, key=lambda r: (r["period_index"], r["created_at"]))


def scheduled_disbursements_for(api: ApiClient, residency_id: str) -> List[Dict[str, Any]]:
    return [r for r in disbursements_for(api, residency_id) if r["status"] == "SCHEDULED"]


def pay_disbursement(
    api: ApiClient, disbursement_id: str, paid_on_date: Optional[str] = None
) -> Dict[str, Any]:
    """Pay as an officer who did not schedule the calendar."""
    payload = make_settlement_payload("PAY")
    if paid_on_date is not None:
        payload["paid_on_date"] = paid_on_date
    return get_success_data(
        api.settle_disbursement(disbursement_id, payload, FINANCE_PAYER_HEADERS)
    )


def reverse_disbursement(
    api: ApiClient,
    disbursement_id: str,
    headers: Optional[Dict[str, str]] = None,
    reason: str = "Bank returned the transfer",
) -> Dict[str, Any]:
    """Reverse as an officer who did not pay the row."""
    return get_success_data(
        api.settle_disbursement(
            disbursement_id,
            make_settlement_payload("REVERSE", reason=reason),
            headers or FINANCE_SCHEDULER_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Obligations
# ---------------------------------------------------------------------------
def obligations_for(api: ApiClient, residency_id: str, **params) -> List[Dict[str, Any]]:
    query = {"residency_id": residency_id, "limit": 100}
    query.update(params)
    rows, _ = validate_paginated(api.list_obligations(ADMIN_HEADERS, query))
    return rows


def obligation_of_type(
    api: ApiClient, residency_id: str, obligation_type: str
) -> Dict[str, Any]:
    return require_by(
        obligations_for(api, residency_id), obligation_type=obligation_type
    )


def log_obligation_completion(
    api: ApiClient, obligation_id: str, attendance: Optional[int] = None
) -> Dict[str, Any]:
    payload = make_obligation_progress_payload("LOG_COMPLETION")
    if attendance is not None:
        payload["attendance"] = attendance
    return get_success_data(
        api.update_obligation_progress(obligation_id, payload, ADMIN_HEADERS)
    )


def waive_obligation(
    api: ApiClient, obligation_id: str, waived_reason: str = "Venue closed"
) -> Dict[str, Any]:
    return get_success_data(
        api.update_obligation_progress(
            obligation_id,
            make_obligation_progress_payload("WAIVE", waived_reason=waived_reason),
            ADMIN_HEADERS,
        )
    )


def fulfil_all_obligations(
    api: ApiClient, residency_id: str, attendance: int = 10
) -> List[Dict[str, Any]]:
    """Log completions until every obligation has met its required count."""
    results: List[Dict[str, Any]] = []
    for row in obligations_for(api, residency_id):
        remaining = row["required_count"] - row["completed_count"]
        for _ in range(max(0, remaining)):
            results.append(log_obligation_completion(api, row["id"], attendance))
    return results


# ---------------------------------------------------------------------------
# Visa cases
# ---------------------------------------------------------------------------
def open_visa_case(api: ApiClient, residency_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.create_visa_case(make_visa_case_payload(residency_id), VISA_HEADERS), 201
    )


def visa_case_for(api: ApiClient, residency_id: str) -> Dict[str, Any]:
    rows, _ = validate_paginated(
        api.list_visa_cases(VISA_HEADERS, {"residency_id": residency_id})
    )
    assert rows, f"no visa case exists for residency {residency_id}"
    return rows[0]


def read_visa_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_visa_case(case_id, VISA_HEADERS))


def request_visa_docs(
    api: ApiClient, case_id: str, doc_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    payload = {
        "action": "REQUEST",
        "doc_list": doc_list or ["PASSPORT", "INVITATION_LETTER"],
    }
    return get_success_data(api.visa_docs(case_id, payload, VISA_HEADERS))


def submit_visa_docs(
    api: ApiClient, case_id: str, doc_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    payload = {
        "action": "SUBMIT",
        "doc_list": doc_list or ["PASSPORT", "INVITATION_LETTER"],
    }
    return get_success_data(api.visa_docs(case_id, payload, VISA_HEADERS))


def file_visa_case(
    api: ApiClient, case_id: str, consulate_appointment_date: str
) -> Dict[str, Any]:
    payload = {
        "action": "FILE",
        "consulate_appointment_date": consulate_appointment_date,
    }
    return get_success_data(api.visa_adjudication(case_id, payload, VISA_HEADERS))


def approve_visa_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.visa_adjudication(case_id, {"action": "APPROVE"}, VISA_HEADERS)
    )


def deny_visa_case(
    api: ApiClient, case_id: str, reason: str = "Insufficient ties"
) -> Dict[str, Any]:
    return get_success_data(
        api.visa_adjudication(
            case_id, {"action": "DENY", "reason": reason}, VISA_HEADERS
        )
    )


def carry_visa_case_to_approved(
    api: ApiClient,
    residency: ResidencyContext,
    consulate_appointment_date: str,
) -> Dict[str, Any]:
    """Walk a case from intake through filing to approval."""
    case = visa_case_for(api, residency.residency_id)
    request_visa_docs(api, case["id"])
    submit_visa_docs(api, case["id"])
    file_visa_case(api, case["id"], consulate_appointment_date)
    return approve_visa_case(api, case["id"])


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def tax_report(api: ApiClient, residency_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_tax_report(residency_id, FINANCE_SCHEDULER_HEADERS)
    )


def funder_outcome_report(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_funder_outcome_report(cycle_id, ADMIN_HEADERS))


def setup_residency_ready_for_payment(
    api: ApiClient,
    session_length_weeks: int = DEFAULT_SESSION_WEEKS,
    international: bool = False,
    treaty_country: bool = True,
    weekly_rate_override_cents: Optional[int] = None,
    session_start_date: Optional[str] = None,
    consulate_appointment_date: str = SPONSORED_CONSULATE_DATE,
    clock: str = CLOCK_INSIDE_WINDOW,
    discipline_overrides: Optional[Dict[str, Any]] = None,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    **cycle_overrides,
) -> Tuple[CycleContext, ApplicantContext, ResidencyContext, List[Dict[str, Any]]]:
    """A residency whose disbursements may legally be paid.

    Payment demands a residency that has already checked in, so the chain
    generates the calendar while the residency is still schedulable, clears the
    sponsorship and safety axes, then moves the clock onto the session start.
    Obligations are deliberately left untouched and therefore stay pending, so
    the final period's engagement guard is satisfied.
    """
    if session_start_date is None:
        session_start_date = (
            SPONSORED_SESSION_START if international else DEFAULT_SESSION_START
        )
    overrides = dict(applicant_overrides or {})
    if international:
        overrides.setdefault("treaty_country", treaty_country)
    cycle, applicant, residency = setup_scheduled_residency(
        api,
        clock=clock,
        session_start_date=session_start_date,
        session_length_weeks=session_length_weeks,
        international=international,
        discipline_overrides=discipline_overrides,
        applicant_overrides=overrides,
        **cycle_overrides,
    )
    generate_stipend_schedule(
        api, residency, weekly_rate_override_cents=weekly_rate_override_cents
    )
    if international:
        carry_visa_case_to_approved(api, residency, consulate_appointment_date)
    complete_all_trainings(api, residency)
    set_clock(api, f"{session_start_date}T09:00:00Z")
    check_in(api, residency)
    return cycle, applicant, residency, disbursements_for(api, residency.residency_id)


def payment_dates(session_start_date: str, count: int) -> List[str]:
    """One settlement date per period, each a fortnight after the previous one."""
    return [shift_days(session_start_date, 13 + 14 * index) for index in range(count)]
