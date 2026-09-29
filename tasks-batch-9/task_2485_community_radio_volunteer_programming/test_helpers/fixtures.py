"""Composite setup builders.

Every test starts against an empty database, so every precondition below is
built from scratch through the endpoints the PRD declares. The builders are
plain functions rather than pytest fixtures so that a single test can raise two
or three variants of the same chain (two grids, three hosts, a near-miss and a
passing challenger) without fighting fixture scope.

Each builder returns a plain dict of the ids and server-computed values a test
needs, and every builder is parameterised over the values the callers actually
vary: the clock, the season code, the proposal title and format, the ballot
scores, the slot geometry and the money amounts.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, CORE_CERT_TYPES
from .factories import (
    adjudicate_incident_payload,
    air_result_payload,
    cast_vote_payload,
    create_certification_payload,
    create_episode_payload,
    create_incident_payload,
    create_membership_drive_payload,
    create_playlist_entry_payload,
    create_pledge_payload,
    create_premium_item_payload,
    create_proposal_payload,
    create_schedule_grid_payload,
    create_slot_assignment_payload,
    create_underwriting_spot_payload,
    create_volunteer_payload,
    decide_proposal_payload,
    log_decision_payload,
    publish_grid_payload,
    remediate_incident_payload,
)
from .test_users import (
    DEVELOPMENT_HEADERS,
    DIRECTOR_HEADERS,
    OFFICER_ADJUDICATOR,
    OFFICER_COPY_DESK,
    OFFICER_LOGS,
    OFFICER_SWEEPER,
    TRAINER_HEADERS,
    make_committee_member_headers,
    make_compliance_officer_headers,
    make_volunteer_headers,
)

# Exam scores used whenever a builder needs a volunteer to simply be certified.
# Every score clears the 80-point pass mark, so each record lands on PASSED.
CORE_EXAM_SCORES = {
    "BOARD_OPERATION": 88,
    "STATION_POLICY": 90,
    "BROADCAST_REGULATION": 91,
}

# The fall season used by most chains: the grid opens on a Monday.
FALL_SEASON = "2026-FALL"
FALL_FROM = "2026-09-07T00:00:00Z"
FALL_TO = "2026-12-27T23:59:00Z"
FIRST_MONDAY_2000 = "2026-09-07T20:00:00Z"

# Committee members carry a long tenure so that no seniority comparison in a
# test is ever decided by a member rather than by the hosts under test.
MEMBER_SENIORITY_START = "2023-01-01"

MEMBER_ROSTER = [
    ("Bo Lin", "bo@krcr.example"),
    ("Cy Nakamura", "cy@krcr.example"),
    ("Dee Okafor", "dee@krcr.example"),
    ("Eli Shaw", "eli@krcr.example"),
    ("Fern Duarte", "fern@krcr.example"),
    ("Gale Petrov", "gale@krcr.example"),
    ("Hollis Reed", "hollis@krcr.example"),
    ("Imani Bassey", "imani@krcr.example"),
]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(current_utc: str = CLOCK_EPOCH) -> dict:
    """Move the station's logical clock. Every chain calls this first so the
    starting instant is explicit rather than inherited."""
    return get_success_data(api_client.set_clock(current_utc, DIRECTOR_HEADERS))


# ---------------------------------------------------------------------------
# Volunteers and certifications
# ---------------------------------------------------------------------------
def create_volunteer(legal_name="Ada Reyes", email="ada@krcr.example",
                     role_track="PROGRAMMER", seniority_start_date="2024-08-01",
                     **overrides) -> dict:
    payload = create_volunteer_payload(
        legal_name=legal_name,
        email=email,
        role_track=role_track,
        seniority_start_date=seniority_start_date,
        **overrides,
    )
    return get_success_data(api_client.create_volunteer(payload, TRAINER_HEADERS))


def add_certification(volunteer_id, cert_type, exam_score=None) -> dict:
    """Register one certification attempt. Supplying `exam_score` grades the
    attempt in the same call."""
    extra = {} if exam_score is None else {"exam_score": exam_score}
    payload = create_certification_payload(cert_type=cert_type, **extra)
    return get_success_data(api_client.create_certification(volunteer_id, payload, TRAINER_HEADERS))


def add_core_certifications(volunteer_id, cert_types=None, scores=None) -> dict:
    """Pass the named core certifications for one volunteer, returning a map of
    cert_type to the created record."""
    cert_types = list(cert_types if cert_types is not None else CORE_CERT_TYPES)
    scores = scores or CORE_EXAM_SCORES
    return {
        cert_type: add_certification(volunteer_id, cert_type, scores[cert_type])
        for cert_type in cert_types
    }


def create_certified_host(legal_name="Ada Reyes", email="ada@krcr.example",
                          seniority_start_date="2024-08-01", role_track="PROGRAMMER",
                          scores=None, **overrides) -> dict:
    """A volunteer holding all three core certifications, which is what carries
    the roster row to CERTIFIED."""
    volunteer = create_volunteer(
        legal_name=legal_name,
        email=email,
        role_track=role_track,
        seniority_start_date=seniority_start_date,
        **overrides,
    )
    certifications = add_core_certifications(volunteer["id"], scores=scores)
    refreshed = get_success_data(api_client.get_volunteer(volunteer["id"], TRAINER_HEADERS))
    return {
        "id": volunteer["id"],
        "volunteer": refreshed,
        "certifications": certifications,
    }


def create_committee_members(count=3, seniority_start_date=MEMBER_SENIORITY_START,
                             certified=False) -> list:
    """Seat `count` volunteers on the programming committee."""
    members = []
    for legal_name, email in MEMBER_ROSTER[:count]:
        member = create_volunteer(
            legal_name=legal_name,
            email=email,
            seniority_start_date=seniority_start_date,
            committee_seat=True,
        )
        if certified:
            add_core_certifications(member["id"])
            member = get_success_data(api_client.get_volunteer(member["id"], TRAINER_HEADERS))
        members.append(member)
    return members


def member_ids(members) -> list:
    return [member["id"] for member in members]


# ---------------------------------------------------------------------------
# Proposals, ballots and programs
# ---------------------------------------------------------------------------
def create_proposal(host_id, title="Delta Sessions", format_code="MUSIC",
                    language_code="EN", requested_daypart="EVENING",
                    requested_duration_minutes=120, **overrides) -> dict:
    payload = create_proposal_payload(
        host_id,
        title=title,
        format_code=format_code,
        language_code=language_code,
        requested_daypart=requested_daypart,
        requested_duration_minutes=requested_duration_minutes,
        **overrides,
    )
    return get_success_data(api_client.create_proposal(payload, make_volunteer_headers(host_id)))


def submit_proposal(proposal_id, host_id) -> dict:
    return get_success_data(
        api_client.submit_proposal(proposal_id, make_volunteer_headers(host_id))
    )


def open_review(proposal_id) -> dict:
    return get_success_data(api_client.open_proposal_review(proposal_id, DIRECTOR_HEADERS))


def cast_ballot(proposal_id, member_id, format_fit_score=4, diversity_score=4,
                quality_score=4, recommendation="APPROVE",
                rationale="Approve.") -> dict:
    payload = cast_vote_payload(
        member_id,
        format_fit_score=format_fit_score,
        diversity_score=diversity_score,
        quality_score=quality_score,
        recommendation=recommendation,
        rationale=rationale,
    )
    return get_success_data(
        api_client.cast_vote(proposal_id, payload, make_committee_member_headers(member_id))
    )


def cast_uniform_ballots(proposal_id, members, format_fit_score=4, diversity_score=4,
                         quality_score=4, recommendation="APPROVE") -> list:
    """Every seated member files the same ballot, which keeps the composite
    score a hand-checkable number."""
    return [
        cast_ballot(
            proposal_id,
            member_id,
            format_fit_score=format_fit_score,
            diversity_score=diversity_score,
            quality_score=quality_score,
            recommendation=recommendation,
        )
        for member_id in member_ids(members)
    ]


def proposal_version(proposal_id) -> int:
    return get_success_data(api_client.get_proposal(proposal_id, DIRECTOR_HEADERS))["version"]


def decide_proposal(proposal_id, expected_version=None) -> dict:
    """Close the round. The guard version is re-read unless the caller wants to
    supply a stale one on purpose."""
    if expected_version is None:
        expected_version = proposal_version(proposal_id)
    return get_success_data(
        api_client.decide_proposal(
            proposal_id, decide_proposal_payload(expected_version), DIRECTOR_HEADERS
        )
    )


def program_for_proposal(proposal_id) -> dict:
    """The program a decision spawned, found through its originating proposal."""
    body = api_client.list_programs(DIRECTOR_HEADERS, params={"proposal_id": proposal_id})
    rows = get_success_data(body)
    return rows[0] if rows else None


def open_review_chain(host_id, members, title="Delta Sessions", format_code="MUSIC",
                      language_code="EN", requested_daypart="EVENING",
                      requested_duration_minutes=120) -> dict:
    """A proposal carried as far as IN_COMMITTEE with no ballots on file."""
    proposal = create_proposal(
        host_id,
        title=title,
        format_code=format_code,
        language_code=language_code,
        requested_daypart=requested_daypart,
        requested_duration_minutes=requested_duration_minutes,
    )
    submit_proposal(proposal["id"], host_id)
    in_committee = open_review(proposal["id"])
    return {"proposal_id": proposal["id"], "proposal": in_committee}


def create_approved_program(host_id, members, title="Delta Sessions", format_code="MUSIC",
                            language_code="EN", requested_daypart="EVENING",
                            requested_duration_minutes=120, format_fit_score=4,
                            diversity_score=4, quality_score=4) -> dict:
    """Carry one proposal from DRAFT to APPROVED and hand back the program the
    approval spawned."""
    chain = open_review_chain(
        host_id,
        members,
        title=title,
        format_code=format_code,
        language_code=language_code,
        requested_daypart=requested_daypart,
        requested_duration_minutes=requested_duration_minutes,
    )
    cast_uniform_ballots(
        chain["proposal_id"],
        members,
        format_fit_score=format_fit_score,
        diversity_score=diversity_score,
        quality_score=quality_score,
        recommendation="APPROVE",
    )
    decided = decide_proposal(chain["proposal_id"])
    program = program_for_proposal(chain["proposal_id"])
    return {
        "proposal_id": chain["proposal_id"],
        "proposal": decided,
        "program_id": program["id"] if program else None,
        "program": program,
    }


# ---------------------------------------------------------------------------
# Grids and occupations
# ---------------------------------------------------------------------------
def create_grid(season_code=FALL_SEASON, effective_from=FALL_FROM,
                effective_to=FALL_TO, **overrides) -> dict:
    payload = create_schedule_grid_payload(
        season_code=season_code,
        effective_from=effective_from,
        effective_to=effective_to,
        **overrides,
    )
    return get_success_data(api_client.create_schedule_grid(payload, DIRECTOR_HEADERS))


def grid_version(grid_id) -> int:
    return get_success_data(api_client.get_schedule_grid(grid_id, DIRECTOR_HEADERS))["version"]


def read_grid(grid_id) -> dict:
    return get_success_data(api_client.get_schedule_grid(grid_id, DIRECTOR_HEADERS))


def add_slot(grid_id, program_id, day_of_week=1, start_minute=1200,
             duration_minutes=120, expected_version=None, **overrides) -> dict:
    """Claim one weekday window. The guard version is re-read on every call so
    a chain of occupations never trips the optimistic-concurrency rule."""
    if expected_version is None:
        expected_version = grid_version(grid_id)
    payload = create_slot_assignment_payload(
        program_id,
        expected_version,
        day_of_week=day_of_week,
        start_minute=start_minute,
        duration_minutes=duration_minutes,
        **overrides,
    )
    return get_success_data(api_client.create_slot_assignment(grid_id, payload, DIRECTOR_HEADERS))


def confirm_slot(slot_id) -> dict:
    return get_success_data(api_client.confirm_slot_assignment(slot_id, DIRECTOR_HEADERS))


def read_slot(slot_id) -> dict:
    return get_success_data(api_client.get_slot_assignment(slot_id, DIRECTOR_HEADERS))


def publish_grid(grid_id, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = grid_version(grid_id)
    return get_success_data(
        api_client.publish_schedule_grid(
            grid_id, publish_grid_payload(expected_version), DIRECTOR_HEADERS
        )
    )


def grid_chain(host_id, members, season_code=FALL_SEASON, day_of_week=1,
               start_minute=1200, duration_minutes=120, format_code="MUSIC",
               title="Delta Sessions", requested_daypart="EVENING",
               confirm=True, publish=False) -> dict:
    """One approved program holding one occupation on a fresh grid."""
    approved = create_approved_program(
        host_id,
        members,
        title=title,
        format_code=format_code,
        requested_daypart=requested_daypart,
        requested_duration_minutes=duration_minutes,
    )
    grid = create_grid(season_code=season_code)
    slot = add_slot(
        grid["id"],
        approved["program_id"],
        day_of_week=day_of_week,
        start_minute=start_minute,
        duration_minutes=duration_minutes,
    )
    if confirm:
        slot = confirm_slot(slot["id"])
    if publish:
        publish_grid(grid["id"])
    return {
        "grid_id": grid["id"],
        "grid": read_grid(grid["id"]),
        "slot_id": slot["id"],
        "slot": read_slot(slot["id"]),
        "program_id": approved["program_id"],
        "proposal_id": approved["proposal_id"],
    }


def quota_ready_grid(host_id, members, season_code=FALL_SEASON, publish=True,
                     music_duration=120, news_duration=30) -> dict:
    """A grid carrying one music occupation and one news occupation. News is a
    public-affairs format, so the pair clears the diversity floor whenever the
    news share is at or above 8.00 percent, which lets the grid publish."""
    music = create_approved_program(
        host_id, members, title="Delta Sessions", format_code="MUSIC",
        requested_daypart="EVENING", requested_duration_minutes=music_duration,
    )
    news = create_approved_program(
        host_id, members, title="County Report", format_code="NEWS",
        requested_daypart="MORNING_DRIVE", requested_duration_minutes=news_duration,
    )
    grid = create_grid(season_code=season_code)
    music_slot = add_slot(
        grid["id"], music["program_id"], day_of_week=1, start_minute=1200,
        duration_minutes=music_duration,
    )
    news_slot = add_slot(
        grid["id"], news["program_id"], day_of_week=2, start_minute=420,
        duration_minutes=news_duration,
    )
    confirm_slot(music_slot["id"])
    confirm_slot(news_slot["id"])
    if publish:
        publish_grid(grid["id"])
    return {
        "grid_id": grid["id"],
        "grid": read_grid(grid["id"]),
        "music_program_id": music["program_id"],
        "news_program_id": news["program_id"],
        "music_proposal_id": music["proposal_id"],
        "news_proposal_id": news["proposal_id"],
        "music_slot_id": music_slot["id"],
        "news_slot_id": news_slot["id"],
    }


# ---------------------------------------------------------------------------
# Episodes, air results and playlist logs
# ---------------------------------------------------------------------------
def create_episode(program_id, slot_id, operator_id,
                   scheduled_start_utc=FIRST_MONDAY_2000, **overrides) -> dict:
    payload = create_episode_payload(
        program_id, slot_id, operator_id,
        scheduled_start_utc=scheduled_start_utc,
        **overrides,
    )
    return get_success_data(api_client.create_episode(payload, DIRECTOR_HEADERS))


def record_air_result(episode_id, air_status="AIRED", **overrides) -> dict:
    return get_success_data(
        api_client.record_air_result(
            episode_id, air_result_payload(air_status=air_status, **overrides), DIRECTOR_HEADERS
        )
    )


def read_episode(episode_id) -> dict:
    return get_success_data(api_client.get_episode(episode_id, DIRECTOR_HEADERS))


def add_playlist_entry(episode_id, host_id, sequence_number, **fields) -> dict:
    payload = create_playlist_entry_payload(sequence_number, **fields)
    return get_success_data(
        api_client.create_playlist_entry(episode_id, payload, make_volunteer_headers(host_id))
    )


def add_playlist_entries(episode_id, host_id, specs) -> list:
    """`specs` is a list of dicts of playlist-entry fields; sequence numbers are
    filled in from 1 upward when a spec does not carry one."""
    created = []
    for index, spec in enumerate(specs, start=1):
        fields = dict(spec)
        sequence_number = fields.pop("sequence_number", index)
        created.append(add_playlist_entry(episode_id, host_id, sequence_number, **fields))
    return created


def submit_log(episode_id, host_id) -> dict:
    return get_success_data(
        api_client.submit_playlist_log(episode_id, make_volunteer_headers(host_id))
    )


def decide_log(episode_id, decision="CERTIFY", officer=OFFICER_LOGS) -> dict:
    return get_success_data(
        api_client.decide_playlist_log(
            episode_id,
            log_decision_payload(decision=decision),
            make_compliance_officer_headers(officer),
        )
    )


def episode_chain(host_id, members, season_code=FALL_SEASON, format_code="MUSIC",
                  title="Delta Sessions", requested_daypart="EVENING",
                  duration_minutes=120, day_of_week=1, start_minute=1200,
                  scheduled_start_utc=FIRST_MONDAY_2000, air_status="AIRED",
                  confirm=True, publish=False, playlist=None) -> dict:
    """One episode of one occupation, optionally already aired and optionally
    carrying spins on its open log."""
    chain = grid_chain(
        host_id, members, season_code=season_code, day_of_week=day_of_week,
        start_minute=start_minute, duration_minutes=duration_minutes,
        format_code=format_code, title=title, requested_daypart=requested_daypart,
        confirm=confirm, publish=publish,
    )
    episode = create_episode(
        chain["program_id"], chain["slot_id"], host_id,
        scheduled_start_utc=scheduled_start_utc,
    )
    if air_status is not None:
        record_air_result(episode["id"], air_status=air_status)
    entries = []
    if playlist:
        entries = add_playlist_entries(episode["id"], host_id, playlist)
    chain.update({
        "episode_id": episode["id"],
        "episode": read_episode(episode["id"]),
        "playlist_entries": entries,
    })
    return chain


# ---------------------------------------------------------------------------
# Underwriting spots and the public file
# ---------------------------------------------------------------------------
def create_spot(underwriter_name="Fernwood Books", spot_class="UNDERWRITING",
                copy_text="Support for this hour comes from Fernwood Books on Third Street.",
                flight_start="2026-08-01T00:00:00Z", flight_end="2026-09-01T00:00:00Z",
                **overrides) -> dict:
    payload = create_underwriting_spot_payload(
        underwriter_name=underwriter_name,
        spot_class=spot_class,
        copy_text=copy_text,
        flight_start=flight_start,
        flight_end=flight_end,
        **overrides,
    )
    return get_success_data(api_client.create_underwriting_spot(payload, DEVELOPMENT_HEADERS))


def submit_spot(spot_id) -> dict:
    return get_success_data(api_client.submit_spot_for_review(spot_id, DEVELOPMENT_HEADERS))


def review_spot(spot_id, officer=OFFICER_COPY_DESK, payload=None) -> dict:
    return get_success_data(
        api_client.review_underwriting_spot(
            spot_id, payload or {}, make_compliance_officer_headers(officer)
        )
    )


def read_spot(spot_id) -> dict:
    return get_success_data(api_client.get_underwriting_spot(spot_id, DEVELOPMENT_HEADERS))


def create_reviewed_spot(officer=OFFICER_COPY_DESK, **spot_fields) -> dict:
    """Carry one spot from DRAFT through UNDER_REVIEW to the officer's decision.
    The decision the officer's call produces depends on the copy's own risk
    score, so the caller reads the returned record rather than assuming."""
    spot = create_spot(**spot_fields)
    submit_spot(spot["id"])
    decided = review_spot(spot["id"], officer=officer)
    return {"spot_id": spot["id"], "spot": decided, "reviewer": officer}


# ---------------------------------------------------------------------------
# Compliance incidents
# ---------------------------------------------------------------------------
def create_incident(category, severity, occurred_at,
                    complainant_note="Complaint on file.", **targets) -> dict:
    payload = create_incident_payload(
        category, severity, occurred_at, complainant_note=complainant_note, **targets
    )
    return get_success_data(
        api_client.create_compliance_incident(
            payload, make_compliance_officer_headers(OFFICER_ADJUDICATOR)
        )
    )


def adjudicate_incident(incident_id, finding="SUBSTANTIATED",
                        officer=OFFICER_ADJUDICATOR) -> dict:
    return get_success_data(
        api_client.adjudicate_compliance_incident(
            incident_id,
            adjudicate_incident_payload(finding=finding),
            make_compliance_officer_headers(officer),
        )
    )


def remediate_incident(incident_id, officer=OFFICER_ADJUDICATOR,
                       remediation_note="Corrective action completed.") -> dict:
    return get_success_data(
        api_client.remediate_compliance_incident(
            incident_id,
            remediate_incident_payload(remediation_note=remediation_note),
            make_compliance_officer_headers(officer),
        )
    )


def substantiated_incident(category, severity, occurred_at, **targets) -> dict:
    """File and substantiate one incident in a single step, which is how the
    penalty ledger is loaded before a test's own trigger runs."""
    incident = create_incident(category, severity, occurred_at, **targets)
    return adjudicate_incident(incident["id"])


def read_program(program_id) -> dict:
    return get_success_data(api_client.get_program(program_id, DIRECTOR_HEADERS))


def run_daily_sweep(officer=OFFICER_SWEEPER) -> dict:
    return get_success_data(
        api_client.run_daily_sweep(make_compliance_officer_headers(officer))
    )


# ---------------------------------------------------------------------------
# Membership drives, premiums and pledges
# ---------------------------------------------------------------------------
def create_drive(name="Fall Drive", goal_cents=5_000_000,
                 start_at="2026-08-01T00:00:00Z", end_at="2026-08-14T23:59:00Z",
                 phone_line_count=4, **overrides) -> dict:
    payload = create_membership_drive_payload(
        name=name,
        goal_cents=goal_cents,
        start_at=start_at,
        end_at=end_at,
        phone_line_count=phone_line_count,
        **overrides,
    )
    return get_success_data(api_client.create_membership_drive(payload, DEVELOPMENT_HEADERS))


def activate_drive(drive_id) -> dict:
    return get_success_data(api_client.activate_membership_drive(drive_id, DEVELOPMENT_HEADERS))


def create_active_drive(**drive_fields) -> dict:
    """A drive taking pledges."""
    drive = create_drive(**drive_fields)
    return activate_drive(drive["id"])


def read_drive(drive_id) -> dict:
    return get_success_data(api_client.get_membership_drive(drive_id, DEVELOPMENT_HEADERS))


def create_premium(sku="MUG-01", name="Station Mug", tier_threshold_cents=10000,
                   fair_market_value_cents=1500, units_received_qty=2, **overrides) -> dict:
    payload = create_premium_item_payload(
        sku=sku,
        name=name,
        tier_threshold_cents=tier_threshold_cents,
        fair_market_value_cents=fair_market_value_cents,
        units_received_qty=units_received_qty,
        **overrides,
    )
    return get_success_data(api_client.create_premium_item(payload, DEVELOPMENT_HEADERS))


def read_premium(premium_item_id) -> dict:
    return get_success_data(api_client.get_premium_item(premium_item_id, DEVELOPMENT_HEADERS))


def create_pledge(drive_id, donor_name="Marisol Vega", amount_cents=12000,
                  wants_premium=False, **overrides) -> dict:
    payload = create_pledge_payload(
        drive_id,
        donor_name=donor_name,
        amount_cents=amount_cents,
        wants_premium=wants_premium,
        **overrides,
    )
    return get_success_data(api_client.create_pledge(payload, DEVELOPMENT_HEADERS))


def read_pledge(pledge_id) -> dict:
    return get_success_data(api_client.get_pledge(pledge_id, DEVELOPMENT_HEADERS))


def settle_pledge(pledge_id, outcome="PAID") -> dict:
    return get_success_data(
        api_client.settle_pledge(pledge_id, {"outcome": outcome}, DEVELOPMENT_HEADERS)
    )


def fulfill_premium(pledge_id, action="SHIP") -> dict:
    return get_success_data(
        api_client.fulfill_pledge_premium(pledge_id, {"action": action}, DEVELOPMENT_HEADERS)
    )


def refund_pledge(pledge_id) -> dict:
    return get_success_data(api_client.refund_pledge(pledge_id, DEVELOPMENT_HEADERS))


def create_shift(drive_id, volunteer_id, start_at, end_at) -> dict:
    return get_success_data(
        api_client.create_phone_bank_shift(
            {
                "drive_id": drive_id,
                "volunteer_id": volunteer_id,
                "start_at": start_at,
                "end_at": end_at,
            },
            DEVELOPMENT_HEADERS,
        )
    )


def close_shift(shift_id, outcome="COMPLETED") -> dict:
    return get_success_data(
        api_client.close_phone_bank_shift(shift_id, {"outcome": outcome}, DEVELOPMENT_HEADERS)
    )


def create_development_volunteers(count=3, seniority_start_date="2025-01-01") -> list:
    """Phone-bank staffers. The development track needs no certification, so
    these rows never touch the training lifecycle."""
    roster = [
        ("Gus Halvorsen", "gus@krcr.example"),
        ("Hana Ito", "hana@krcr.example"),
        ("Iris Mbeki", "iris@krcr.example"),
        ("Jae Park", "jae@krcr.example"),
    ]
    return [
        create_volunteer(
            legal_name=legal_name,
            email=email,
            role_track="DEVELOPMENT",
            seniority_start_date=seniority_start_date,
        )
        for legal_name, email in roster[:count]
    ]


# ---------------------------------------------------------------------------
# Whole-station preambles
# ---------------------------------------------------------------------------
def station(clock=CLOCK_EPOCH, host_seniority_start_date="2024-08-01",
            member_count=3) -> dict:
    """The preamble almost every programming chain shares: a known clock, one
    certified host and a staffed committee."""
    set_clock(clock)
    host = create_certified_host(seniority_start_date=host_seniority_start_date)
    members = create_committee_members(count=member_count)
    return {
        "host_id": host["id"],
        "host": host["volunteer"],
        "certifications": host["certifications"],
        "members": members,
        "member_ids": member_ids(members),
    }


def development_station(clock=CLOCK_EPOCH, volunteer_count=3) -> dict:
    """The preamble every drive chain shares: a known clock and enrolled
    development volunteers."""
    set_clock(clock)
    volunteers = create_development_volunteers(count=volunteer_count)
    return {
        "volunteers": volunteers,
        "volunteer_ids": [volunteer["id"] for volunteer in volunteers],
    }
