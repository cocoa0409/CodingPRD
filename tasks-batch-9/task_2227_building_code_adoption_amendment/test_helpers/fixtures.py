"""Composite setup helpers.

Every helper drives the system from an empty database through PRD-declared
endpoints only, in the order the PRD's workflows require: a `CodeCycle` is
created in `DRAFT`, its committees are seated, intake is opened before a
proposal is submitted and closed before screening, both required analyses are
accepted before the cycle reaches `DELIBERATION`, the comment window runs its
30 days on the logical clock, and the hearing is convened at its
`scheduled_start` before any ballot is recorded.

Each helper returns a mutable `world` dict so that a caller can layer the next
stage on top of an earlier one, and each accepts overrides so a single boundary
value can be moved without rebuilding the chain by hand.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    ADMIN_EFFECTIVE_ID,
    ADMIN_FILER_ID,
    ADMIN_LOCAL_REVIEWER_ID,
    ADMIN_OPINION_PUBLISHER_ID,
    ADMIN_OPS_ID,
    ADMIN_PUBLISHER_ID,
    ADMIN_REVIEWER_ID,
    ADMIN_RULE_DRAFTER_ID,
    PETITIONER_FOUR_ID,
    PETITIONER_ONE_ID,
    PETITIONER_THREE_ID,
    PETITIONER_TWO_ID,
    STAFF_ANALYST_ID,
    STAFF_DRAFTER_ID,
    STAFF_INTAKE_ID,
    STAFF_SECOND_ANALYST_ID,
    make_council_admin_headers,
    make_council_chair_headers,
    make_jurisdiction_official_headers,
    make_petitioner_headers,
    make_technical_staff_headers,
)

# ---------------------------------------------------------------------------
# Logical-clock instants used by the setup chains
# ---------------------------------------------------------------------------
CLOCK_INTAKE = "2026-08-01T00:00:00Z"
CLOCK_MID_COMMENT = "2026-08-15T00:00:00Z"
CLOCK_COMMENT_CLOSES = "2026-09-09T00:00:00Z"
CLOCK_HEARING_START = "2026-10-05T14:00:00Z"
CLOCK_SECOND_HEARING_START = "2026-10-06T09:00:00Z"
CLOCK_SESSION_ENDS = "2027-01-10T17:00:00Z"
CLOCK_EFFECTIVE_DATE = "2027-02-02T00:00:00Z"

COMMENT_OPENS_AT = "2026-08-10T00:00:00Z"
COMMENT_CLOSES_AT = "2026-09-09T00:00:00Z"
HEARING_START = "2026-10-05T14:00:00Z"
HEARING_END = "2026-10-05T17:00:00Z"
SESSION_STARTS_AT = "2027-01-10T09:00:00Z"
SESSION_ENDS_AT = "2027-01-10T17:00:00Z"

# The ENERGY committee roster: six voting seats covering the four sectors the
# PRD requires before a committee may be seated.
ENERGY_ROSTER = (
    ("chair", "Dana Reyes", "INDUSTRY", True),
    ("fire", "Sam Ito", "FIRE_SERVICE", False),
    ("local", "Lee Park", "LOCAL_JURISDICTION", False),
    ("design", "Rae Oyelaran", "DESIGN_PROFESSIONAL", False),
    ("industry_two", "Kim Alvarez", "INDUSTRY", False),
    ("public", "Toni Blake", "PUBLIC", False),
)

MECHANICAL_ROSTER = (
    ("chair", "Nia Okafor", "INDUSTRY", True),
    ("fire", "Owen Diaz", "FIRE_SERVICE", False),
    ("local", "Priya Raman", "LOCAL_JURISDICTION", False),
)

FIRE_SAFETY_ROSTER = (
    ("chair", "Ada Kwan", "INDUSTRY", True),
    ("fire", "Bo Nkemelu", "FIRE_SERVICE", False),
    ("local", "Cyd Marsh", "LOCAL_JURISDICTION", False),
)

# A second ENERGY proposal on the same committee, NEUTRAL and uncommented, used
# wherever one proposal must be compared against a sibling.
SIBLING_PROPOSAL = {
    "code_section": "C403.1.1",
    "discipline": "ENERGY",
    "title": "Economizer table restatement",
    "proposed_text": (
        "Restate the economizer exception table without changing required "
        "performance."
    ),
    "stringency_direction": "NEUTRAL",
    "proposer_sector": "DESIGN_PROFESSIONAL",
}

# A MECHANICAL proposal, so it routes to the cycle's MECHANICAL committee rather
# than the ENERGY one, and owes no energy analysis because it is neither ENERGY
# nor MORE_STRINGENT.
MECHANICAL_PROPOSAL = {
    "code_section": "M403.3.2",
    "discipline": "MECHANICAL",
    "title": "Outdoor air rate table restatement",
    "proposed_text": (
        "Restate the outdoor air rate table without changing required "
        "ventilation performance."
    ),
    "stringency_direction": "NEUTRAL",
    "proposer_sector": "DESIGN_PROFESSIONAL",
}

SIBLING_COST_BENEFIT = {
    "incremental_cost_by_occupancy": {"R3": 10000, "R2": 12000, "B": 15000, "A2": 18000},
    "affected_permit_count": 700,
    "annual_cost_savings_cents": 900000,
    "measure_life_years": 20,
}

SIBLING_ENERGY_IMPACT = {
    "annual_energy_savings_kwh": 120000,
    "energy_delta_pct": -0.4,
}

GOLDEN_COMMENTS = (
    ("INDUSTRY", "SUPPORT", "Aligns with our product roadmap.", PETITIONER_ONE_ID),
    (
        "DESIGN_PROFESSIONAL",
        "SUPPORT",
        "Modelling shows the assembly is buildable.",
        PETITIONER_TWO_ID,
    ),
    (
        "LOCAL_JURISDICTION",
        "SUPPORT",
        "Plan review can absorb this change.",
        PETITIONER_THREE_ID,
    ),
    (
        "FIRE_SERVICE",
        "OPPOSE",
        "Concerned about interaction with sprinkler layout.",
        PETITIONER_FOUR_ID,
    ),
)


# ---------------------------------------------------------------------------
# Tier 1 — single-step primitives
# ---------------------------------------------------------------------------
def set_logical_clock(api, instant: str, headers=None):
    """Move the logical clock; every temporal rule in the PRD reads it."""
    return api.set_clock(instant, headers or make_council_admin_headers())


def create_cycle(api, headers=None, **overrides) -> dict:
    response = api.create_code_cycle(
        f.create_code_cycle_payload(**overrides),
        headers or make_council_admin_headers(),
    )
    return get_success_data(response)


def set_cycle_status(api, cycle_id: str, to_status: str, headers=None, **overrides):
    return api.set_code_cycle_status(
        cycle_id,
        f.code_cycle_status_payload(to_status, **overrides),
        headers or make_council_admin_headers(),
    )


def create_committee(api, cycle_id: str, headers=None, **overrides) -> dict:
    response = api.create_discipline_committee(
        cycle_id,
        f.create_discipline_committee_payload(**overrides),
        headers or make_council_admin_headers(),
    )
    return get_success_data(response)


def seat_member(
    api,
    committee_id: str,
    full_name: str,
    sector: str,
    voting_seat: bool = True,
    is_chair: bool = False,
    headers=None,
    **overrides,
) -> dict:
    response = api.create_committee_member(
        committee_id,
        f.create_committee_member_payload(
            full_name=full_name,
            sector=sector,
            voting_seat=voting_seat,
            is_chair=is_chair,
            **overrides,
        ),
        headers or make_council_admin_headers(),
    )
    return get_success_data(response)


def seat_roster(api, committee_id: str, roster, headers=None) -> dict:
    """Seat a roster of (key, full_name, sector, is_chair) tuples, returning the
    created member records keyed by their short key."""
    members = {}
    for key, full_name, sector, is_chair in roster:
        members[key] = seat_member(
            api,
            committee_id,
            full_name,
            sector,
            voting_seat=True,
            is_chair=is_chair,
            headers=headers,
        )
    return members


def read_proposal(api, proposal_id: str, headers=None) -> dict:
    """Re-read a proposal to obtain its current `version` for the next
    optimistic-concurrency guarded write."""
    return get_success_data(
        api.get_amendment_proposal(proposal_id, headers or make_council_admin_headers())
    )


def read_jurisdiction(api, jurisdiction_id: str, headers=None) -> dict:
    return get_success_data(
        api.get_jurisdiction(jurisdiction_id, headers or make_council_admin_headers())
    )


# ---------------------------------------------------------------------------
# Tier 2 — cycle and committee hierarchy
# ---------------------------------------------------------------------------
def setup_cycle(api, clock: str = CLOCK_INTAKE, **cycle_overrides) -> dict:
    """A DRAFT CodeCycle with the logical clock parked inside its intake
    window."""
    set_logical_clock(api, clock)
    cycle = create_cycle(api, **cycle_overrides)
    return {"clock": clock, "cycle": cycle, "cycle_id": cycle["id"]}


def setup_forming_energy_committee(
    api, seated=("chair", "fire", "local"), voting_seat_count: int = 6, **cycle_overrides
) -> dict:
    """An ENERGY committee that is still FORMING: fewer active voting members
    than the two-thirds seating threshold its seat count demands."""
    world = setup_cycle(api, **cycle_overrides)
    committee = create_committee(
        api,
        world["cycle_id"],
        discipline="ENERGY",
        voting_seat_count=voting_seat_count,
    )
    roster = tuple(row for row in ENERGY_ROSTER if row[0] in seated)
    world["committee"] = committee
    world["committee_id"] = committee["id"]
    world["members"] = seat_roster(api, committee["id"], roster)
    return world


def setup_seated_energy_committee(
    api, voting_seat_count: int = 6, **cycle_overrides
) -> dict:
    """A SEATED ENERGY committee of six voting seats with all four required
    sectors represented and exactly one chair."""
    return setup_forming_energy_committee(
        api,
        seated=tuple(row[0] for row in ENERGY_ROSTER),
        voting_seat_count=voting_seat_count,
        **cycle_overrides,
    )


def add_mechanical_committee(
    api, world: dict, seated=("chair", "fire", "local"), voting_seat_count: int = 3
) -> dict:
    """Add a second committee for a different discipline to the same cycle."""
    committee = create_committee(
        api,
        world["cycle_id"],
        discipline="MECHANICAL",
        voting_seat_count=voting_seat_count,
    )
    roster = tuple(row for row in MECHANICAL_ROSTER if row[0] in seated)
    world["mechanical_committee"] = committee
    world["mechanical_committee_id"] = committee["id"]
    world["mechanical_members"] = seat_roster(api, committee["id"], roster)
    return world


def setup_seated_fire_safety_committee(api, **cycle_overrides) -> dict:
    """A SEATED FIRE_AND_LIFE_SAFETY committee of three voting seats."""
    world = setup_cycle(api, **cycle_overrides)
    committee = create_committee(
        api, world["cycle_id"], discipline="FIRE_AND_LIFE_SAFETY", voting_seat_count=3
    )
    world["committee"] = committee
    world["committee_id"] = committee["id"]
    world["members"] = seat_roster(api, committee["id"], FIRE_SAFETY_ROSTER)
    return world


# ---------------------------------------------------------------------------
# Tier 3 — proposal, analysis, comment and hearing lifecycle
# ---------------------------------------------------------------------------
def submit_proposal(api, world: dict, headers=None, **overrides) -> dict:
    """Submit a proposal into the open intake window."""
    response = api.create_amendment_proposal(
        f.create_amendment_proposal_payload(world["cycle_id"], **overrides),
        headers or make_technical_staff_headers(STAFF_INTAKE_ID),
    )
    proposal = get_success_data(response)
    world["proposal"] = proposal
    world["proposal_id"] = proposal["id"]
    world["proposal_version_at_create"] = proposal["version"]
    return proposal


def screen_proposal(
    api, world: dict, decision: str = "ACCEPT_FOR_ANALYSIS", headers=None
) -> dict:
    response = api.screen_amendment_proposal(
        world["proposal_id"],
        f.screening_payload(decision),
        headers or make_technical_staff_headers(STAFF_INTAKE_ID),
    )
    proposal = get_success_data(response)
    world["proposal"] = proposal
    world["proposal_version_at_screening"] = proposal["version"]
    return proposal


def submit_cost_benefit_analysis(
    api, world: dict, expected_version=None, headers=None, **overrides
):
    """File a COST_BENEFIT analysis and return the raw response, for tests that
    expect the filing to be refused."""
    expected = (
        expected_version
        if expected_version is not None
        else world["proposal_version_at_screening"]
    )
    return api.create_impact_analysis(
        world["proposal_id"],
        f.create_cost_benefit_analysis_payload(expected, **overrides),
        headers or make_technical_staff_headers(STAFF_ANALYST_ID),
    )


def file_cost_benefit_analysis(
    api, world: dict, expected_version=None, headers=None, **overrides
) -> dict:
    response = submit_cost_benefit_analysis(
        api, world, expected_version=expected_version, headers=headers, **overrides
    )
    analysis = get_success_data(response)
    world["cost_benefit"] = analysis
    world["cost_benefit_id"] = analysis["id"]
    return analysis


def submit_energy_impact_analysis(
    api, world: dict, expected_version=None, headers=None, **overrides
):
    """File an ENERGY_IMPACT analysis and return the raw response. With no
    explicit version the proposal is re-read first, as a writer holding an older
    view is required to do."""
    if expected_version is None:
        expected_version = read_proposal(api, world["proposal_id"])["version"]
    return api.create_impact_analysis(
        world["proposal_id"],
        f.create_energy_impact_analysis_payload(expected_version, **overrides),
        headers or make_technical_staff_headers(STAFF_ANALYST_ID),
    )


def file_energy_impact_analysis(
    api, world: dict, expected_version=None, headers=None, **overrides
) -> dict:
    response = submit_energy_impact_analysis(
        api, world, expected_version=expected_version, headers=headers, **overrides
    )
    analysis = get_success_data(response)
    world["energy_impact"] = analysis
    world["energy_impact_id"] = analysis["id"]
    return analysis


def review_analysis(api, analysis_id: str, decision: str = "ACCEPT", headers=None):
    """Accept or reject a filed analysis. The reviewer must differ from the
    analyst who prepared it, so the default reviewer identifier is distinct from
    the default analyst identifier."""
    return api.review_impact_analysis(
        analysis_id,
        f.analysis_review_payload(decision),
        headers or make_council_admin_headers(ADMIN_REVIEWER_ID),
    )


def setup_screened_proposal(api, proposal_overrides=None, **committee_kwargs) -> dict:
    """A SCREENED proposal in an INTAKE_CLOSED cycle: intake is opened, the
    proposal is submitted, intake is closed, then screening accepts it for
    analysis."""
    world = committee_kwargs.pop("world", None) or setup_seated_energy_committee(
        api, **committee_kwargs
    )
    set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    submit_proposal(api, world, **(proposal_overrides or {}))
    set_cycle_status(api, world["cycle_id"], "INTAKE_CLOSED")
    screen_proposal(api, world)
    return world


def setup_proposal_with_accepted_cost_benefit(
    api, cost_benefit_overrides=None, proposal_overrides=None, **committee_kwargs
) -> dict:
    """A SCREENED proposal whose COST_BENEFIT analysis has been accepted, so the
    analysis dimension reads PARTIAL while the review dimension is unchanged."""
    world = setup_screened_proposal(
        api, proposal_overrides=proposal_overrides, **committee_kwargs
    )
    file_cost_benefit_analysis(api, world, **(cost_benefit_overrides or {}))
    review_analysis(api, world["cost_benefit_id"])
    return world


def setup_proposal_analysis_complete(
    api,
    cost_benefit_overrides=None,
    energy_impact_overrides=None,
    proposal_overrides=None,
    energy_impact: bool = True,
    **committee_kwargs,
) -> dict:
    """Both required analyses accepted, so the analysis dimension reads
    COMPLETE while the review dimension is still SCREENED. Pass
    `energy_impact=False` for a proposal that owes no energy analysis, where
    accepting the cost-benefit analysis alone completes the dimension."""
    world = setup_proposal_with_accepted_cost_benefit(
        api,
        cost_benefit_overrides=cost_benefit_overrides,
        proposal_overrides=proposal_overrides,
        **committee_kwargs,
    )
    if energy_impact:
        file_energy_impact_analysis(api, world, **(energy_impact_overrides or {}))
        review_analysis(api, world["energy_impact_id"])
    return world


def setup_proposal_ready_for_comment(api, **kwargs) -> dict:
    """Analysis COMPLETE and the cycle advanced to DELIBERATION, the state in
    which a comment window may be opened."""
    world = setup_proposal_analysis_complete(api, **kwargs)
    set_cycle_status(api, world["cycle_id"], "DELIBERATION")
    return world


def open_comment_window(api, world: dict, headers=None, **overrides):
    return api.act_on_comment_window(
        world["proposal_id"],
        f.open_comment_window_payload(**overrides),
        headers or make_council_admin_headers(),
    )


def act_on_comment_window(api, world: dict, action: str, headers=None, **overrides):
    return api.act_on_comment_window(
        world["proposal_id"],
        f.comment_window_action_payload(action, **overrides),
        headers or make_council_admin_headers(),
    )


def submit_comment(
    api,
    world: dict,
    commenter_sector: str,
    position: str,
    body: str,
    user_id: str = PETITIONER_ONE_ID,
    headers=None,
    **overrides,
):
    return api.create_public_comment(
        world["proposal_id"],
        f.create_public_comment_payload(
            commenter_sector=commenter_sector,
            position=position,
            body=body,
            **overrides,
        ),
        headers or make_petitioner_headers(user_id),
    )


def submit_golden_comments(api, world: dict) -> list:
    """Three SUPPORT comments and one OPPOSE comment, all inside the open
    window."""
    comments = []
    for sector, position, body, user_id in GOLDEN_COMMENTS:
        comments.append(
            get_success_data(
                submit_comment(api, world, sector, position, body, user_id=user_id)
            )
        )
    world["comments"] = comments
    return comments


def setup_proposal_comment_open(api, window_overrides=None, **kwargs) -> dict:
    """A proposal with an OPEN comment window and the clock inside it."""
    world = setup_proposal_ready_for_comment(api, **kwargs)
    open_comment_window(api, world, **(window_overrides or {}))
    set_logical_clock(api, CLOCK_MID_COMMENT)
    world["clock"] = CLOCK_MID_COMMENT
    return world


def setup_proposal_comment_closed(
    api, window_overrides=None, with_comments: bool = True, **kwargs
) -> dict:
    """A COMMENT_CLOSED proposal: the window ran its 30 days, four comments
    arrived, and the window was closed once its closing instant was reached."""
    world = setup_proposal_comment_open(api, window_overrides=window_overrides, **kwargs)
    if with_comments:
        submit_golden_comments(api, world)
    set_logical_clock(api, CLOCK_COMMENT_CLOSES)
    world["clock"] = CLOCK_COMMENT_CLOSES
    act_on_comment_window(api, world, "CLOSE")
    return world


def proposal_view(world: dict, proposal_id: str) -> dict:
    """A copy of the world scoped to a sibling proposal, so the proposal-scoped
    helpers can drive it without disturbing the golden proposal's keys."""
    view = dict(world)
    view["proposal_id"] = proposal_id
    for key in (
        "proposal",
        "proposal_version_at_create",
        "proposal_version_at_screening",
        "cost_benefit",
        "cost_benefit_id",
        "energy_impact",
        "energy_impact_id",
    ):
        view.pop(key, None)
    return view


def submit_sibling_proposal(api, world: dict, headers=None, **overrides) -> dict:
    """Submit the sibling ENERGY proposal into the same open intake window,
    returning a world view scoped to it."""
    payload = dict(SIBLING_PROPOSAL)
    payload.update(overrides)
    sibling = get_success_data(
        api.create_amendment_proposal(
            f.create_amendment_proposal_payload(world["cycle_id"], **payload),
            headers or make_technical_staff_headers(STAFF_INTAKE_ID),
        )
    )
    world["sibling"] = sibling
    world["sibling_id"] = sibling["id"]
    view = proposal_view(world, sibling["id"])
    view["proposal"] = sibling
    view["proposal_version_at_create"] = sibling["version"]
    world["sibling_view"] = view
    return view


def _setup_golden_and_sibling(api, sibling_complete: bool, **kwargs) -> dict:
    """Two ENERGY proposals on one committee: the golden one always reaches
    COMMENT_CLOSED with its four comments, and the sibling either follows it all
    the way or stops at SCREENED with its analysis dimension still PENDING."""
    world = setup_seated_energy_committee(api, **kwargs)
    set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    submit_proposal(api, world)
    sibling = submit_sibling_proposal(api, world)
    set_cycle_status(api, world["cycle_id"], "INTAKE_CLOSED")
    screen_proposal(api, world)
    screen_proposal(api, sibling)
    file_cost_benefit_analysis(api, world)
    review_analysis(api, world["cost_benefit_id"])
    file_energy_impact_analysis(api, world)
    review_analysis(api, world["energy_impact_id"])
    sibling_analyst = make_technical_staff_headers(STAFF_SECOND_ANALYST_ID)
    if sibling_complete:
        file_cost_benefit_analysis(
            api, sibling, headers=sibling_analyst, **SIBLING_COST_BENEFIT
        )
        review_analysis(api, sibling["cost_benefit_id"])
        file_energy_impact_analysis(
            api, sibling, headers=sibling_analyst, **SIBLING_ENERGY_IMPACT
        )
        review_analysis(api, sibling["energy_impact_id"])
    set_cycle_status(api, world["cycle_id"], "DELIBERATION")
    open_comment_window(api, world)
    if sibling_complete:
        open_comment_window(api, sibling)
    set_logical_clock(api, CLOCK_MID_COMMENT)
    submit_golden_comments(api, world)
    set_logical_clock(api, CLOCK_COMMENT_CLOSES)
    world["clock"] = CLOCK_COMMENT_CLOSES
    act_on_comment_window(api, world, "CLOSE")
    if sibling_complete:
        act_on_comment_window(api, sibling, "CLOSE")
    return world


def setup_comment_closed_on_two_committees(api, **kwargs) -> dict:
    """One cycle, two seated committees, and one COMMENT_CLOSED proposal on each.

    The golden ENERGY proposal carries the four comments; the MECHANICAL one is
    routed to the second committee — "the proposal's `committee_id` is resolved
    by finding the discipline committees of the named cycle whose own
    `discipline` equals the proposal's `discipline`" — and reaches
    `COMMENT_CLOSED` with its analysis dimension `COMPLETE` as well, since a
    `NEUTRAL` non-`ENERGY` proposal owes no energy analysis. It is therefore
    eligible in every respect the PRD names except that it can never appear on
    the ENERGY committee's agenda, whose pool holds only "the proposals routed
    to this hearing's committee".
    """
    world = setup_seated_energy_committee(api, **kwargs)
    add_mechanical_committee(api, world)
    set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    submit_proposal(api, world)
    other = submit_sibling_proposal(api, world, **MECHANICAL_PROPOSAL)
    set_cycle_status(api, world["cycle_id"], "INTAKE_CLOSED")
    screen_proposal(api, world)
    screen_proposal(api, other)
    file_cost_benefit_analysis(api, world)
    review_analysis(api, world["cost_benefit_id"])
    file_energy_impact_analysis(api, world)
    review_analysis(api, world["energy_impact_id"])
    other_analyst = make_technical_staff_headers(STAFF_SECOND_ANALYST_ID)
    file_cost_benefit_analysis(
        api, other, headers=other_analyst, **SIBLING_COST_BENEFIT
    )
    review_analysis(api, other["cost_benefit_id"])
    set_cycle_status(api, world["cycle_id"], "DELIBERATION")
    open_comment_window(api, world)
    open_comment_window(api, other)
    set_logical_clock(api, CLOCK_MID_COMMENT)
    submit_golden_comments(api, world)
    set_logical_clock(api, CLOCK_COMMENT_CLOSES)
    world["clock"] = CLOCK_COMMENT_CLOSES
    act_on_comment_window(api, world, "CLOSE")
    act_on_comment_window(api, other, "CLOSE")
    return world


def setup_comment_closed_with_screened_sibling(api, **kwargs) -> dict:
    """A COMMENT_CLOSED proposal beside a sibling that is only SCREENED, so the
    sibling is outside the eligible pool for an agenda or a ballot."""
    return _setup_golden_and_sibling(api, sibling_complete=False, **kwargs)


def setup_two_comment_closed_proposals(api, **kwargs) -> dict:
    """Two COMMENT_CLOSED proposals with both analyses accepted: the golden one
    carries the four comments, the sibling none at all."""
    return _setup_golden_and_sibling(api, sibling_complete=True, **kwargs)


def schedule_hearing(api, world: dict, committee_id=None, headers=None, **overrides):
    return api.create_hearing(
        f.create_hearing_payload(committee_id or world["committee_id"], **overrides),
        headers or make_council_admin_headers(),
    )


def add_scheduled_hearing(api, world: dict, committee_id=None, **overrides) -> dict:
    hearing = get_success_data(
        schedule_hearing(api, world, committee_id=committee_id, **overrides)
    )
    world["hearing"] = hearing
    world["hearing_id"] = hearing["id"]
    return hearing


def fill_agenda(api, world: dict, hearing_id=None, headers=None, **overrides):
    return api.fill_hearing_agenda(
        hearing_id or world["hearing_id"],
        f.agenda_payload(**overrides),
        headers or make_council_admin_headers(),
    )


def convene_hearing(api, world: dict, hearing_id=None, present=None, chair_id=None):
    """Convene a hearing. The presiding chair's own CommitteeMember id is the
    acting identity, and the roll call names every member present."""
    members = world["members"]
    present_ids = (
        present
        if present is not None
        else [member["id"] for member in members.values()]
    )
    chair = chair_id or members["chair"]["id"]
    return api.convene_hearing(
        hearing_id or world["hearing_id"],
        f.convene_payload(present_ids),
        make_council_chair_headers(chair),
    )


def setup_convened_hearing(api, hearing_overrides=None, **kwargs) -> dict:
    """The full chain to a CONVENED hearing whose agenda holds the
    COMMENT_CLOSED proposal, with the clock at the hearing's start."""
    world = setup_proposal_comment_closed(api, **kwargs)
    add_scheduled_hearing(api, world, **(hearing_overrides or {}))
    fill_agenda(api, world)
    set_logical_clock(api, CLOCK_HEARING_START)
    world["clock"] = CLOCK_HEARING_START
    convene_hearing(api, world)
    world["hearing"] = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    return world


def golden_ballots(world: dict) -> list:
    """Four YES and two NO ballots from the six seated ENERGY members."""
    members = world["members"]
    return [
        f.ballot(members["chair"]["id"], "YES"),
        f.ballot(members["industry_two"]["id"], "YES"),
        f.ballot(members["local"]["id"], "YES"),
        f.ballot(members["design"]["id"], "YES"),
        f.ballot(members["fire"]["id"], "NO"),
        f.ballot(members["public"]["id"], "NO"),
    ]


def record_vote(
    api, world: dict, ballots=None, hearing_id=None, proposal_id=None, chair_id=None
):
    return api.record_vote(
        hearing_id or world["hearing_id"],
        f.vote_payload(
            proposal_id or world["proposal_id"],
            ballots if ballots is not None else golden_ballots(world),
        ),
        make_council_chair_headers(chair_id or world["members"]["chair"]["id"]),
    )


def setup_approved_proposal(api, **kwargs) -> dict:
    """The golden chain through an APPROVED vote."""
    world = setup_convened_hearing(api, **kwargs)
    world["vote"] = get_success_data(record_vote(api, world))
    world["vote_id"] = world["vote"]["id"]
    return world


def reopen_proposal(api, world: dict, proposal_id=None, headers=None, **overrides):
    return api.reopen_amendment_proposal(
        proposal_id or world["proposal_id"],
        f.reopen_payload(**overrides),
        headers or make_council_admin_headers(),
    )


# ---------------------------------------------------------------------------
# Tier 4 — rulemaking, jurisdictions, local amendments, interpretations
# ---------------------------------------------------------------------------
def setup_rulemaking_cycle(api, **kwargs) -> dict:
    """An APPROVED proposal in a cycle advanced to RULEMAKING, which the PRD
    permits only once every proposal is resolved and at least one is
    approved."""
    world = setup_approved_proposal(api, **kwargs)
    set_cycle_status(api, world["cycle_id"], "RULEMAKING")
    return world


def create_adoption_rule(api, world: dict, headers=None, **overrides) -> dict:
    response = api.create_adoption_rule(
        f.create_adoption_rule_payload(world["cycle_id"], **overrides),
        headers or make_council_admin_headers(ADMIN_RULE_DRAFTER_ID),
    )
    rule = get_success_data(response)
    world["rule"] = rule
    world["rule_id"] = rule["id"]
    return rule


def advance_rule(api, world: dict, to_status: str, headers=None, **overrides):
    return api.set_adoption_rule_status(
        world["rule_id"],
        f.adoption_rule_status_payload(to_status, **overrides),
        headers or make_council_admin_headers(),
    )


def setup_draft_adoption_rule(api, rule_overrides=None, **kwargs) -> dict:
    world = setup_rulemaking_cycle(api, **kwargs)
    create_adoption_rule(api, world, **(rule_overrides or {}))
    return world


def setup_filed_adoption_rule(api, **kwargs) -> dict:
    """A FILED rule. Filing pins the approved amendment versions, and the filer
    must differ from the drafter."""
    world = setup_draft_adoption_rule(api, **kwargs)
    advance_rule(api, world, "FILED", make_council_admin_headers(ADMIN_FILER_ID))
    return world


def setup_published_adoption_rule(api, **kwargs) -> dict:
    """A PUBLISHED rule, published by an administrator distinct from the
    filer."""
    world = setup_filed_adoption_rule(api, **kwargs)
    advance_rule(
        api, world, "PUBLISHED", make_council_admin_headers(ADMIN_PUBLISHER_ID)
    )
    world["rule"] = get_success_data(
        api.get_adoption_rule(world["rule_id"], make_council_admin_headers())
    )
    return world


def add_jurisdiction(api, world: dict, key: str, headers=None, **overrides) -> dict:
    response = api.create_jurisdiction(
        f.create_jurisdiction_payload(**overrides),
        headers or make_council_admin_headers(),
    )
    jurisdiction = get_success_data(response)
    world.setdefault("jurisdictions", {})[key] = jurisdiction
    world[f"{key}_id"] = jurisdiction["id"]
    return jurisdiction


def add_riverbend(api, world: dict, **overrides) -> dict:
    """Riverbend: population 1200000, FULL local authority, five officials,
    hosting capacity 60."""
    return add_jurisdiction(api, world, "riverbend", **overrides)


def add_harborview(api, world: dict, **overrides) -> dict:
    """Harborview: population 300000, LIMITED local authority, four
    officials."""
    defaults = {
        "name": "Harborview",
        "population": 300000,
        "local_authority_level": "LIMITED",
        "host_seat_capacity": 40,
        "official_headcount": 4,
    }
    defaults.update(overrides)
    return add_jurisdiction(api, world, "harborview", **defaults)


def add_northgate(api, world: dict, **overrides) -> dict:
    """Northgate: population 100000 with NONE local authority, so it may not
    file a local amendment at all."""
    defaults = {
        "name": "Northgate",
        "population": 100000,
        "local_authority_level": "NONE",
        "host_seat_capacity": 0,
        "official_headcount": 3,
    }
    defaults.update(overrides)
    return add_jurisdiction(api, world, "northgate", **defaults)


def file_local_amendment(
    api, world: dict, jurisdiction_key: str = "riverbend", headers=None, **overrides
) -> dict:
    """File a local amendment against the published rule, supplying the
    jurisdiction version the filer last read."""
    jurisdiction = world["jurisdictions"][jurisdiction_key]
    expected_version = overrides.pop(
        "expected_jurisdiction_version",
        read_jurisdiction(api, jurisdiction["id"])["version"],
    )
    response = api.create_local_amendment(
        f.create_local_amendment_payload(
            expected_version,
            jurisdiction["id"],
            world["rule_id"],
            **overrides,
        ),
        headers or make_jurisdiction_official_headers(jurisdiction["id"]),
    )
    return response


def add_local_amendment(api, world: dict, **kwargs) -> dict:
    amendment = get_success_data(file_local_amendment(api, world, **kwargs))
    world["local_amendment"] = amendment
    world["local_amendment_id"] = amendment["id"]
    return amendment


def review_local_amendment(
    api, world: dict, decision: str, local_amendment_id=None, headers=None
):
    return api.review_local_amendment(
        local_amendment_id or world["local_amendment_id"],
        f.local_amendment_review_payload(decision),
        headers or make_council_admin_headers(ADMIN_LOCAL_REVIEWER_ID),
    )


def setup_accepted_local_amendment(api, **kwargs) -> dict:
    """A local amendment carried through START_REVIEW to ACCEPT."""
    world = kwargs.pop("world", None) or setup_published_adoption_rule(api, **kwargs)
    if "jurisdictions" not in world or "riverbend" not in world.get(
        "jurisdictions", {}
    ):
        add_riverbend(api, world)
    add_local_amendment(api, world)
    review_local_amendment(api, world, "START_REVIEW")
    review_local_amendment(api, world, "ACCEPT")
    world["local_amendment"] = get_success_data(
        api.get_local_amendment(
            world["local_amendment_id"], make_council_admin_headers()
        )
    )
    return world


def file_interpretation_request(
    api, world: dict, jurisdiction_key: str = "riverbend", headers=None, **overrides
):
    jurisdiction = world["jurisdictions"][jurisdiction_key]
    payload = f.create_interpretation_request_payload(
        world["rule_id"], jurisdiction_id=jurisdiction["id"], **overrides
    )
    return api.create_interpretation_request(
        payload,
        headers or make_jurisdiction_official_headers(jurisdiction["id"]),
    )


def add_interpretation_request(api, world: dict, **kwargs) -> dict:
    request = get_success_data(file_interpretation_request(api, world, **kwargs))
    world["interpretation_request"] = request
    world["interpretation_request_id"] = request["id"]
    return request


def act_on_interpretation(
    api, world: dict, action: str, request_id=None, headers=None, **overrides
):
    return api.act_on_interpretation_request(
        request_id or world["interpretation_request_id"],
        f.interpretation_action_payload(action, **overrides),
        headers or make_council_admin_headers(),
    )


def setup_published_interpretation(api, world: dict = None, **kwargs) -> dict:
    """An interpretation request walked ASSIGNED -> OPINION_DRAFTED ->
    PUBLISHED: the council assigns it, technical staff issue the opinion, and a
    different administrator publishes it."""
    if world is None:
        world = setup_published_adoption_rule(api, **kwargs)
    if "riverbend" not in world.get("jurisdictions", {}):
        add_riverbend(api, world)
    add_interpretation_request(api, world)
    act_on_interpretation(
        api, world, "ASSIGN", assigned_committee_id=world["committee_id"]
    )
    act_on_interpretation(
        api,
        world,
        "ISSUE_OPINION",
        opinion_text="Additions under 500 square feet follow the prior edition.",
        binding_scope="STATEWIDE",
        headers=make_technical_staff_headers(STAFF_DRAFTER_ID),
    )
    act_on_interpretation(
        api,
        world,
        "PUBLISH",
        headers=make_council_admin_headers(ADMIN_OPINION_PUBLISHER_ID),
    )
    world["interpretation_request"] = get_success_data(
        api.get_interpretation_request(
            world["interpretation_request_id"], make_council_admin_headers()
        )
    )
    return world


# ---------------------------------------------------------------------------
# Tier 5 — training sessions, enrollments, attendance and readiness
# ---------------------------------------------------------------------------
def create_session(
    api, world: dict, host_key: str = "riverbend", headers=None, **overrides
):
    return api.create_training_session(
        f.create_training_session_payload(
            world["rule_id"],
            world["jurisdictions"][host_key]["id"],
            **overrides,
        ),
        headers or make_council_admin_headers(),
    )


def add_session(api, world: dict, key: str = "session", **kwargs) -> dict:
    session = get_success_data(create_session(api, world, **kwargs))
    world.setdefault("sessions", {})[key] = session
    world["session"] = session
    world["session_id"] = session["id"]
    return session


def set_session_status(api, world: dict, to_status: str, session_id=None, headers=None):
    return api.set_training_session_status(
        session_id or world["session_id"],
        f.training_session_status_payload(to_status),
        headers or make_council_admin_headers(),
    )


def enroll(
    api,
    world: dict,
    key: str,
    jurisdiction_key: str,
    attendee_name: str,
    session_id=None,
    headers=None,
    **overrides,
):
    response = api.create_training_enrollment(
        session_id or world["session_id"],
        f.create_training_enrollment_payload(
            world["jurisdictions"][jurisdiction_key]["id"],
            attendee_name,
            **overrides,
        ),
        headers or make_council_admin_headers(),
    )
    return response


def add_enrollment(api, world: dict, key: str, jurisdiction_key: str, name: str, **kw):
    enrollment = get_success_data(
        enroll(api, world, key, jurisdiction_key, name, **kw)
    )
    world.setdefault("enrollments", {})[key] = enrollment
    return enrollment


def setup_enrollment_open_session(
    api, world: dict = None, session_overrides=None, **kwargs
) -> dict:
    """A PUBLISHED rule, the host jurisdiction Riverbend, and one training
    session moved to ENROLLMENT_OPEN."""
    if world is None:
        world = setup_published_adoption_rule(api, **kwargs)
    if "riverbend" not in world.get("jurisdictions", {}):
        add_riverbend(api, world)
    add_session(api, world, **(session_overrides or {}))
    set_session_status(api, world, "ENROLLMENT_OPEN")
    return world


def add_riverbend_enrollments(api, world: dict, count: int = 5) -> dict:
    for index in range(1, count + 1):
        add_enrollment(
            api,
            world,
            f"riverbend_{index}",
            "riverbend",
            f"Riverbend Official {index}",
        )
    return world


def add_harborview_enrollments(api, world: dict, count: int = 4) -> dict:
    for index in range(1, count + 1):
        add_enrollment(
            api,
            world,
            f"harborview_{index}",
            "harborview",
            f"Harborview Official {index}",
        )
    return world


def setup_session_with_riverbend_enrollments(
    api, world: dict = None, count: int = 5, **kwargs
) -> dict:
    """An ENROLLMENT_OPEN session holding five Riverbend building officials, one
    for every official on Riverbend's headcount."""
    world = setup_enrollment_open_session(api, world=world, **kwargs)
    add_riverbend_enrollments(api, world, count=count)
    world["session"] = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    return world


def record_attendance(api, world: dict, records, session_id=None, headers=None):
    return api.record_attendance(
        session_id or world["session_id"],
        f.attendance_payload(records),
        headers or make_council_admin_headers(),
    )


def attendance_for(world: dict, outcomes: dict) -> list:
    """Build the `records` array from a mapping of enrollment key to outcome."""
    return [
        f.attendance_record(world["enrollments"][key]["id"], outcome)
        for key, outcome in outcomes.items()
    ]


def setup_closed_enrollment_session(api, world: dict = None, **kwargs) -> dict:
    """A session whose enrollment is CLOSED with the clock at its end instant,
    the only state in which attendance may be recorded."""
    world = setup_session_with_riverbend_enrollments(api, world=world, **kwargs)
    set_session_status(api, world, "ENROLLMENT_CLOSED")
    set_logical_clock(api, CLOCK_SESSION_ENDS)
    world["clock"] = CLOCK_SESSION_ENDS
    return world


def setup_delivered_session_riverbend_only(api, world: dict = None, **kwargs) -> dict:
    """A DELIVERED session over Riverbend's five officials: four attended and
    one no-showed, so the two compliance bases diverge."""
    world = setup_closed_enrollment_session(api, world=world, **kwargs)
    record_attendance(
        api,
        world,
        attendance_for(
            world,
            {
                "riverbend_1": "ATTENDED",
                "riverbend_2": "ATTENDED",
                "riverbend_3": "ATTENDED",
                "riverbend_4": "ATTENDED",
                "riverbend_5": "NO_SHOW",
            },
        ),
    )
    world["session"] = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    return world


def setup_delivered_session_two_jurisdictions(api, world: dict = None, **kwargs) -> dict:
    """A DELIVERED session over nine enrollments: five Riverbend officials (four
    attended, one no-showed) and four Harborview officials, all attended."""
    if world is None:
        world = setup_published_adoption_rule(api, **kwargs)
    if "riverbend" not in world.get("jurisdictions", {}):
        add_riverbend(api, world)
    if "harborview" not in world.get("jurisdictions", {}):
        add_harborview(api, world)
    setup_enrollment_open_session(api, world=world)
    add_riverbend_enrollments(api, world)
    add_harborview_enrollments(api, world)
    set_session_status(api, world, "ENROLLMENT_CLOSED")
    set_logical_clock(api, CLOCK_SESSION_ENDS)
    world["clock"] = CLOCK_SESSION_ENDS
    record_attendance(
        api,
        world,
        attendance_for(
            world,
            {
                "riverbend_1": "ATTENDED",
                "riverbend_2": "ATTENDED",
                "riverbend_3": "ATTENDED",
                "riverbend_4": "ATTENDED",
                "riverbend_5": "NO_SHOW",
                "harborview_1": "ATTENDED",
                "harborview_2": "ATTENDED",
                "harborview_3": "ATTENDED",
                "harborview_4": "ATTENDED",
            },
        ),
    )
    world["session"] = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    return world


def cancel_enrollment(api, world: dict, key: str, headers=None, **overrides):
    enrollment = world["enrollments"][key]
    jurisdiction_id = enrollment["jurisdiction_id"]
    payload = {"reason": overrides.pop("reason", "Official reassigned to another district.")}
    payload.update(overrides)
    return api.cancel_training_enrollment(
        enrollment["id"],
        headers or make_jurisdiction_official_headers(jurisdiction_id),
        payload,
    )
