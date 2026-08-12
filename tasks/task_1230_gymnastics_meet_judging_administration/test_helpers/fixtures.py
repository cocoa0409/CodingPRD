"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear error, not a confusing assertion failure.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import APPARATUS_ORDER, CLOCK_START
from .factories import (
    create_athlete_entry_payload,
    create_coach_pass_payload,
    create_coach_payload,
    create_gymnast_payload,
    create_inquiry_payload,
    create_judge_panel_payload,
    create_judge_payload,
    create_meet_payload,
    create_score_payload,
    create_session_payload,
    create_squad_payload,
    create_ticket_payload,
)
from .test_users import TEST_USERS, make_coach_headers, make_judge_panel_chief_headers

DIRECTOR = TEST_USERS["meet_director_headers"]
REFEREE = TEST_USERS["meet_referee_headers"]
GATE = TEST_USERS["gate_attendant_headers"]
SPECTATOR = TEST_USERS["spectator_headers"]


# ---------------------------------------------------------------------------
# Timestamp helpers (tolerant of optional fractional seconds in responses)
# ---------------------------------------------------------------------------

def parse_ts(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional seconds)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with a Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 0: atomic creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START):
    """Drive the server's logical clock (MeetDirector-only capability)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, DIRECTOR)
    assert res.status_code == 200, f"clock setup failed: {res.status_code} {res.text}"


def create_meet(**overrides) -> dict:
    return get_success_data(api_client.create_meet(create_meet_payload(**overrides), DIRECTOR))


def create_session(meet_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_session(meet_id, create_session_payload(**overrides), DIRECTOR))


def create_squad(session_id: str, label: str = None, starting_apparatus: str = "VAULT") -> dict:
    payload = create_squad_payload(starting_apparatus=starting_apparatus)
    if label:
        payload["squad_label"] = label
    return get_success_data(api_client.create_squad(session_id, payload, DIRECTOR))


def create_gymnast(**overrides) -> dict:
    return get_success_data(api_client.create_gymnast(create_gymnast_payload(**overrides), DIRECTOR))


def create_entry(session_id: str, gymnast_id: str) -> dict:
    return get_success_data(api_client.create_athlete_entry(
        session_id, create_athlete_entry_payload(gymnast_id), DIRECTOR))


def create_credentialed_coach(gym: str = "Metro", **overrides) -> dict:
    """Register a coach and verify the record so credential_state is CREDENTIALED."""
    overrides.setdefault("affiliated_gym", gym)
    coach = get_success_data(api_client.create_coach(create_coach_payload(**overrides), DIRECTOR))
    return get_success_data(api_client.verify_coach(coach["id"], DIRECTOR))


def issue_pass_with_floor_access(meet_id: str, coach_id: str) -> dict:
    """Issue a CoachMeetPass and grant floor access. Returns the granted pass."""
    meet_pass = get_success_data(api_client.issue_coach_pass(
        meet_id, create_coach_pass_payload(coach_id), DIRECTOR))
    return get_success_data(api_client.grant_floor_access(meet_pass["id"], DIRECTOR))


def create_judge(**overrides) -> dict:
    return get_success_data(api_client.create_judge(create_judge_payload(**overrides), REFEREE))


def register_judges(count: int, **overrides) -> list:
    """Register `count` distinct judges sharing the given overrides."""
    return [create_judge(**overrides) for _ in range(count)]


def create_panel(session_id: str, meet_id: str, apparatus: str) -> dict:
    return get_success_data(api_client.create_judge_panel(
        session_id, create_judge_panel_payload(meet_id, apparatus), REFEREE))


def staff_panel(panel_id: str) -> list:
    """Run the panel selector and confirm every proposed assignment.

    Returns the list of CONFIRMED PanelAssignment rows.
    """
    assignments = get_success_data(api_client.auto_assign_panel(panel_id, REFEREE))
    confirmed = []
    for assignment in assignments:
        confirmed.append(get_success_data(
            api_client.confirm_assignment(assignment["id"], REFEREE)))
    return confirmed


def panel_chief_judge_id(panel_id: str) -> str:
    """The judge holding the CONFIRMED PANEL_CHIEF assignment on this panel.

    Publishing a score requires the acting judge to hold a confirmed
    PANEL_CHIEF assignment (PRD score-publication rule), so fixtures that
    publish scores resolve the chief through here.
    """
    assignments = get_success_data(api_client.list_panel_assignments(panel_id, REFEREE))
    confirmed = [a for a in assignments if a.get("assignment_state") == "CONFIRMED"]
    if not confirmed:
        confirmed = assignments
    chiefs = [a for a in confirmed if a.get("role") == "PANEL_CHIEF"]
    chosen = chiefs[0] if chiefs else confirmed[0]
    return chosen["judge_id"]


def publish_meet(meet_id: str) -> dict:
    return get_success_data(api_client.publish_meet(meet_id, DIRECTOR))


def generate_rotations(session_id: str) -> list:
    """Generate the four rotations, returned sorted by rotation_number."""
    rotations = get_success_data(api_client.generate_rotations(session_id, DIRECTOR))
    return sorted(rotations, key=lambda r: r["rotation_number"])


def assign_all_entries(session_id: str):
    return get_success_data(api_client.assign_squads(session_id, DIRECTOR))


def open_rotation(rotation_id: str) -> dict:
    return get_success_data(api_client.open_rotation_scoring(rotation_id, DIRECTOR))


def close_rotation(rotation_id: str) -> dict:
    return get_success_data(api_client.close_rotation_scoring(rotation_id, DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2/3: competition-ready composite
# ---------------------------------------------------------------------------

def setup_competition_ready(num_athletes: int = 1, level_band: str = "L9",
                            gymnast_level: str = None, meet_overrides: dict = None,
                            session_overrides: dict = None, check_in: bool = True,
                            advance_to_competition: bool = True) -> dict:
    """Full meet-day-ready context:

    meet + session + one squad + `num_athletes` entries assigned to the squad,
    a credentialed coach with floor access, all four apparatus panels staffed
    to FULL with distinct judges, the meet published, rotations generated, and
    (optionally) the clock advanced so the meet is IN_COMPETITION with every
    rotation past its scheduled start (panels ACTIVE, session IN_ROTATION).

    Returns a context dict with meet, session, squad, gymnasts, entries, coach,
    coach_pass, judges, panels (by apparatus), chiefs (judge id by apparatus),
    rotations, and competition_clock (datetime or None).
    """
    ctx = {}
    set_clock(CLOCK_START)
    meet = create_meet(**(meet_overrides or {}))
    session_kwargs = dict(session_overrides or {})
    session_kwargs.setdefault("level_band", level_band)
    session = create_session(meet["id"], **session_kwargs)
    squad = create_squad(session["id"], "A", "VAULT")

    coach = create_credentialed_coach(gym="Metro")
    coach_pass = issue_pass_with_floor_access(meet["id"], coach["id"])

    gymnasts, entries = [], []
    for _ in range(num_athletes):
        gymnast = create_gymnast(competitive_level=gymnast_level or level_band,
                                 home_gym="Metro")
        entry = create_entry(session["id"], gymnast["id"])
        gymnasts.append(gymnast)
        entries.append(entry)
    assign_all_entries(session["id"])

    if check_in:
        coach_headers = make_coach_headers(coach["id"])
        for i, entry in enumerate(entries):
            entries[i] = get_success_data(
                api_client.check_in_entry(entry["id"], coach_headers))

    judges = register_judges(12)
    panels, chiefs = {}, {}
    for apparatus in APPARATUS_ORDER:
        panel = create_panel(session["id"], meet["id"], apparatus)
        staff_panel(panel["id"])
        panels[apparatus] = panel
        chiefs[apparatus] = panel_chief_judge_id(panel["id"])

    meet = publish_meet(meet["id"])
    rotations = generate_rotations(session["id"])

    competition_clock = None
    if advance_to_competition:
        # Advance far enough that every rotation has reached its scheduled
        # start: the meet crosses to IN_COMPETITION, FULL panels go ACTIVE,
        # and each rotation settles at TIMED_WARMUP_HELD (no warmup blocks).
        competition_clock = max(parse_ts(r["scheduled_start"]) for r in rotations)
        set_clock(fmt_ts(competition_clock))

    ctx.update({
        "meet": get_success_data(api_client.get_meet(meet["id"], DIRECTOR)),
        "session": get_success_data(api_client.get_session(session["id"], DIRECTOR)),
        "squad": squad,
        "gymnasts": gymnasts,
        "entries": entries,
        "coach": coach,
        "coach_pass": coach_pass,
        "judges": judges,
        "panels": panels,
        "chiefs": chiefs,
        "rotations": rotations,
        "competition_clock": competition_clock,
    })
    return ctx


def add_published_score(ctx: dict, entry: dict, rotation: dict,
                        difficulty: float, execution: float,
                        neutral_deduction: float = None) -> dict:
    """Create a DRAFT score and publish it as the panel chief for the
    rotation's apparatus. Returns the PUBLISHED score."""
    chief_id = ctx["chiefs"][rotation["apparatus"]]
    chief_headers = make_judge_panel_chief_headers(chief_id)
    score = get_success_data(api_client.create_score(
        entry["id"],
        create_score_payload(rotation["id"], rotation["apparatus"],
                             difficulty, execution, neutral_deduction),
        chief_headers))
    return get_success_data(api_client.publish_score(
        score["id"], {"expected_score_version": score["version"]}, chief_headers))


def setup_published_score(difficulty: float = 5.0, execution: float = 8.0,
                          neutral_deduction: float = 0.0,
                          meet_overrides: dict = None) -> dict:
    """Competition-ready context plus one PUBLISHED score on the first rotation."""
    ctx = setup_competition_ready(num_athletes=1, meet_overrides=meet_overrides)
    rotation = ctx["rotations"][0]
    open_rotation(rotation["id"])
    score = add_published_score(ctx, ctx["entries"][0], rotation,
                                difficulty, execution, neutral_deduction)
    ctx["rotation"] = rotation
    ctx["score"] = score
    return ctx


def setup_filed_inquiry(**score_kwargs) -> dict:
    """Competition-ready context plus a PUBLISHED score with a FILED inquiry
    (so the score is UNDER_INQUIRY)."""
    ctx = setup_published_score(**score_kwargs)
    inquiry = get_success_data(api_client.file_inquiry(
        ctx["score"]["id"], create_inquiry_payload(ctx["coach"]["id"]),
        make_coach_headers(ctx["coach"]["id"])))
    ctx["inquiry"] = inquiry
    return ctx


def setup_inquiry_under_review(**score_kwargs) -> dict:
    """Filed inquiry advanced to UNDER_REVIEW by the referee."""
    ctx = setup_filed_inquiry(**score_kwargs)
    inquiry = get_success_data(api_client.begin_review(ctx["inquiry"]["id"], REFEREE))
    ctx["inquiry"] = inquiry
    return ctx


def resolve_inquiry(inquiry_id: str, resolution: str, d_score_delta: float = None,
                    e_score_delta: float = None, deduction_delta: float = None,
                    resolution_reason: str = None):
    """Resolve an inquiry with a freshly read version (OCC). Returns the raw
    response so callers can assert on success or failure."""
    fresh = get_success_data(api_client.get_inquiry(inquiry_id, REFEREE))
    payload = {"expected_inquiry_version": fresh["version"], "resolution": resolution}
    if d_score_delta is not None:
        payload["d_score_delta"] = d_score_delta
    if e_score_delta is not None:
        payload["e_score_delta"] = e_score_delta
    if deduction_delta is not None:
        payload["deduction_delta"] = deduction_delta
    if resolution_reason is not None:
        payload["resolution_reason"] = resolution_reason
    return api_client.resolve_inquiry(inquiry_id, payload, REFEREE)


def run_rotations_with_scores(ctx: dict, scores_for) -> None:
    """Open each rotation in turn, publish one score per entry, close it, then
    advance the clock past the inquiry window so every PUBLISHED score
    finalizes itself. `scores_for(entry_index, apparatus)` returns
    (difficulty, execution, neutral_deduction)."""
    for rotation in ctx["rotations"]:
        open_rotation(rotation["id"])
        for index, entry in enumerate(ctx["entries"]):
            difficulty, execution, deduction = scores_for(index, rotation["apparatus"])
            add_published_score(ctx, entry, rotation, difficulty, execution, deduction)
        close_rotation(rotation["id"])
    finalize_clock = ctx["competition_clock"] + timedelta(
        minutes=ctx["meet"]["inquiry_window_minutes"] + 1)
    set_clock(fmt_ts(finalize_clock))
    ctx["finalized_clock"] = finalize_clock


def close_session(ctx: dict) -> dict:
    """Close the session with a freshly read version (OCC)."""
    fresh = get_success_data(api_client.get_session(ctx["session"]["id"], DIRECTOR))
    closed = get_success_data(api_client.close_session(
        ctx["session"]["id"], {"expected_session_version": fresh["version"]}, DIRECTOR))
    ctx["session"] = closed
    return closed


def setup_closed_session(num_athletes: int = 1, level_band: str = "L9",
                         gymnast_level: str = None, meet_overrides: dict = None,
                         scores_for=None) -> dict:
    """Full competition flow through session close (session CLOSED, all scores
    FINAL, awards/qualification computations run)."""
    if scores_for is None:
        scores_for = lambda index, apparatus: (5.0, 8.0, 0.0)
    ctx = setup_competition_ready(num_athletes=num_athletes, level_band=level_band,
                                  gymnast_level=gymnast_level,
                                  meet_overrides=meet_overrides)
    run_rotations_with_scores(ctx, scores_for)
    close_session(ctx)
    # Refresh entries so callers see post-close computed fields.
    ctx["entries"] = [
        get_success_data(api_client.get_athlete_entry(e["id"], DIRECTOR))
        for e in ctx["entries"]
    ]
    return ctx


def setup_archived_meet() -> dict:
    """Full lifecycle through Meet ARCHIVED: session closed, meet scoring
    closed, finalized, archived. Low scores keep qualification vacuous."""
    low_scores = lambda index, apparatus: (2.0, 3.0, 0.0)  # AA 20.000, no event >= 9.000
    ctx = setup_closed_session(num_athletes=1, scores_for=low_scores)
    get_success_data(api_client.close_meet_scoring(ctx["meet"]["id"], DIRECTOR))
    get_success_data(api_client.finalize_meet(ctx["meet"]["id"], DIRECTOR))
    ctx["meet"] = get_success_data(api_client.archive_meet(ctx["meet"]["id"], DIRECTOR))
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 (tickets): meet + session + ticket shortcuts
# ---------------------------------------------------------------------------

def setup_meet_with_session(**meet_overrides) -> dict:
    """Minimal meet + one session (both left in their initial states)."""
    set_clock(CLOCK_START)
    meet = create_meet(**meet_overrides)
    session = create_session(meet["id"])
    return {"meet": meet, "session": session}


def issue_ticket(meet_id: str, session_id: str, **overrides) -> dict:
    return get_success_data(api_client.issue_ticket(
        meet_id, session_id, create_ticket_payload(**overrides), DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2 (warm-up layout): session with squads pre-filled to given sizes
# ---------------------------------------------------------------------------

def setup_squads_for_layout(squad_sizes=(4,), max_athletes_per_squad: int = 4) -> dict:
    """Session with one squad per element of `squad_sizes`; each squad filled
    with that many REGISTERED entries (one distinct home_gym per squad so the
    team-cohesion selector keeps each group together). Rotations generated.
    Meet left in DRAFT; no panels, no clock advance."""
    set_clock(CLOCK_START)
    meet = create_meet(max_athletes_per_squad=max_athletes_per_squad)
    session = create_session(meet["id"])
    squads = []
    for position, _ in enumerate(squad_sizes):
        squads.append(create_squad(session["id"], f"Squad {chr(ord('A') + position)}",
                                   APPARATUS_ORDER[position % 4]))
    for position, size in enumerate(squad_sizes):
        for _ in range(size):
            gymnast = create_gymnast(home_gym=f"Club {position}")
            create_entry(session["id"], gymnast["id"])
    assign_all_entries(session["id"])
    rotations = generate_rotations(session["id"])
    squads = [get_success_data(api_client.get_squad(s["id"], DIRECTOR)) for s in squads]
    return {"meet": meet, "session": session, "squads": squads, "rotations": rotations}
