"""Each refusal the PRD names, raised on the endpoint that owns it, with the
surrounding state shown to be untouched."""
from test_helpers import (
    ADMIN_FILER_ID,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    make_headers_without_identity,
    make_jurisdiction_official_headers,
    make_petitioner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_CYCLE = {
    "intake_opens_at": "2026-09-01T00:00:00Z",
    "intake_closes_at": "2026-11-01T00:00:00Z",
}

PLUMBING_PROPOSAL = {
    "code_section": "P2903.2",
    "discipline": "PLUMBING",
    "title": "Maximum static pressure",
    "proposed_text": "Cap static service pressure at 70 psi.",
    "stringency_direction": "MORE_STRINGENT",
    "proposer_sector": "INDUSTRY",
}

# Twenty-nine days from the golden opening instant, one day short of the minimum.
SHORT_WINDOW = {
    "opens_at": "2026-08-10T00:00:00Z",
    "closes_at": "2026-09-08T00:00:00Z",
}

# Ten days after the clock's 2026-09-09 position, four days short of the notice.
SHORT_NOTICE_HEARING = {
    "scheduled_start": "2026-09-19T14:00:00Z",
    "scheduled_end": "2026-09-19T17:00:00Z",
}

# The opinion is published at 2026-10-05T14:00:00Z, so the appeal window closes
# on 2026-11-04T14:00:00Z.
ONE_SECOND_AFTER_APPEAL_WINDOW = "2026-11-04T14:00:01Z"

TINY_SESSION = {
    "audience": "DESIGN_PROFESSIONAL",
    "seat_capacity": 1,
    "starts_at": "2027-01-12T09:00:00Z",
    "ends_at": "2027-01-12T12:00:00Z",
}


def _one_seat_open_session(api):
    """A single-seat session in ENROLLMENT_OPEN whose only seat is already
    taken."""
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_session(api, world, "tiny", **TINY_SESSION)
    fixtures.set_session_status(api, world, "ENROLLMENT_OPEN")
    fixtures.add_enrollment(
        api,
        world,
        "designer_one",
        "riverbend",
        "Riverbend Designer 1",
        attendee_role="DESIGN_PROFESSIONAL",
    )
    return world


def _convened_hearing_beside_a_screened_sibling(api):
    """A CONVENED hearing whose auto-filled agenda holds only the COMMENT_CLOSED
    proposal, with a still-SCREENED sibling on the same committee."""
    world = fixtures.setup_comment_closed_with_screened_sibling(api)
    fixtures.add_scheduled_hearing(api, world)
    fixtures.fill_agenda(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_HEARING_START)
    get_success_data(fixtures.convene_hearing(api, world))
    return world


def _convened_hearing_beside_an_off_agenda_proposal(api):
    """A CONVENED ENERGY hearing whose auto-filled agenda holds only its own
    committee's proposal, beside a MECHANICAL proposal that is `COMMENT_CLOSED`
    with its analysis dimension `COMPLETE` — eligible on every count the PRD
    names except that it is routed to the other committee and so can never sit
    on this hearing's agenda."""
    world = fixtures.setup_comment_closed_on_two_committees(api)
    fixtures.add_scheduled_hearing(api, world)
    fixtures.fill_agenda(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_HEARING_START)
    get_success_data(fixtures.convene_hearing(api, world))
    return world


def test_01_a_request_with_an_empty_user_id_is_unauthenticated(api):
    """The first rung of the ladder demands "both `X-User-ID` and `X-User-Role`
    present and non-empty, else `ERR_UNAUTHENTICATED` (401). This runs before the
    body is parsed." A well-formed jurisdiction body therefore writes nothing.

    Design: Corner/errors/create_jurisdiction_without_an_identity_header_returns_4xx
    """
    fixtures.set_logical_clock(api, fixtures.CLOCK_INTAKE)

    response = api.create_jurisdiction(
        factories.create_jurisdiction_payload(), make_headers_without_identity()
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    _, meta = validate_paginated(api.list_jurisdictions(make_council_admin_headers()))
    assert meta["total_count"] == 0


def test_02_a_second_cycle_for_the_same_year_and_edition_is_rejected(api):
    """"The pair of `cycle_year` and `model_code_edition` must be unique across
    all cycles; a repeat is rejected with `ERR_DUPLICATE_CODE_CYCLE`." Differing
    intake dates do not make the pair new, because "the declared intake dates are
    documentation only".

    Design: Corner/errors/second_code_cycle_with_the_same_year_and_edition_is_rejected
    """
    world = fixtures.setup_cycle(api)

    response = api.create_code_cycle(
        factories.create_code_cycle_payload(**SECOND_CYCLE),
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CODE_CYCLE, 409)

    page, meta = validate_paginated(api.list_code_cycles(make_council_admin_headers()))
    assert meta["total_count"] == 1
    assert page[0]["id"] == world["cycle_id"]


def test_03_a_second_energy_committee_on_one_cycle_is_rejected(api):
    """"A cycle may hold at most one live committee per discipline; a second
    attempt is rejected with `ERR_DUPLICATE_COMMITTEE_DISCIPLINE`." The rule is
    per discipline, not per cycle, so the same cycle still admits a `MECHANICAL`
    committee, and the surviving `ENERGY` committee keeps "a `voting_seat_count`
    between 3 and 12 inclusive that caps how many voting seats the committee may
    hold" at the six it was created with.

    Design: Corner/errors/second_energy_committee_on_the_same_cycle_is_rejected
    """
    world = fixtures.setup_cycle(api)
    committee = fixtures.create_committee(
        api, world["cycle_id"], discipline="ENERGY", voting_seat_count=6
    )

    response = api.create_discipline_committee(
        world["cycle_id"],
        factories.create_discipline_committee_payload(
            discipline="ENERGY", voting_seat_count=5
        ),
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_COMMITTEE_DISCIPLINE, 409)

    reread = get_success_data(
        api.get_discipline_committee(committee["id"], make_council_admin_headers())
    )
    assert reread["voting_seat_count"] == 6

    mechanical = validate_success(
        api.create_discipline_committee(
            world["cycle_id"],
            factories.create_discipline_committee_payload(
                discipline="MECHANICAL", voting_seat_count=3
            ),
            make_council_admin_headers(),
        ),
        201,
    )
    assert mechanical["discipline"] == "MECHANICAL"

    _, meta = validate_paginated(
        api.list_cycle_discipline_committees(
            world["cycle_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 2


def test_04_a_seventh_voting_member_on_six_seats_is_rejected(api):
    """"Adding a member that would push `active_voting_member_count` above the
    committee's `voting_seat_count` is rejected with `ERR_SEAT_LIMIT_EXCEEDED`."
    Only voting seats are capped, since "`active_voting_member_count` counts child
    members whose `voting_seat` is true and whose `status` is `ACTIVE`", so a
    non-voting member is still admissible and `quorum_required`, "two thirds of
    `active_voting_member_count`, rounded up to the next whole member", stays at 4.

    Design: Corner/errors/seventh_voting_member_on_a_six_seat_committee_is_rejected
    """
    world = fixtures.setup_seated_energy_committee(api)

    response = api.create_committee_member(
        world["committee_id"],
        factories.create_committee_member_payload(
            full_name="Priya Nandan",
            sector="INDUSTRY",
            voting_seat=True,
            is_chair=False,
        ),
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SEAT_LIMIT_EXCEEDED, 409)

    committee = get_success_data(
        api.get_discipline_committee(
            world["committee_id"], make_council_admin_headers()
        )
    )
    assert committee["active_voting_member_count"] == 6
    assert committee["quorum_required"] == 4
    assert committee["status"] == "SEATED"

    observer = validate_success(
        api.create_committee_member(
            world["committee_id"],
            factories.create_committee_member_payload(
                full_name="Priya Nandan",
                sector="INDUSTRY",
                voting_seat=False,
                is_chair=False,
            ),
            make_council_admin_headers(),
        ),
        201,
    )
    assert observer["voting_seat"] is False

    reread = get_success_data(
        api.get_discipline_committee(
            world["committee_id"], make_council_admin_headers()
        )
    )
    assert reread["active_voting_member_count"] == 6
    assert reread["quorum_required"] == 4


def test_05_a_second_chair_on_one_committee_is_rejected(api):
    """"Adding a second member with `is_chair` set to true while an `ACTIVE` chair
    already holds the seat is rejected with `ERR_CHAIR_ALREADY_SEATED`." The
    seated chair keeps the seat and the committee keeps its single member.

    Design: Corner/errors/second_chair_on_a_committee_is_rejected
    """
    world = fixtures.setup_cycle(api)
    committee = fixtures.create_committee(
        api, world["cycle_id"], discipline="ENERGY", voting_seat_count=6
    )
    chair = fixtures.seat_member(
        api, committee["id"], "Dana Reyes", "INDUSTRY", is_chair=True
    )

    response = api.create_committee_member(
        committee["id"],
        factories.create_committee_member_payload(
            full_name="Marcus Olabode",
            sector="FIRE_SERVICE",
            voting_seat=True,
            is_chair=True,
        ),
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_CHAIR_ALREADY_SEATED, 409)

    seated = get_success_data(
        api.get_committee_member(chair["id"], make_council_admin_headers())
    )
    assert seated["is_chair"] is True

    _, meta = validate_paginated(
        api.list_committee_members_of_committee(
            committee["id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 1


def test_06_a_proposal_whose_discipline_has_no_committee_is_rejected(api):
    """Routing looks for a live committee of the proposal's own discipline, and
    "if no such committee exists, the submission is rejected outright with
    `ERR_NO_COMMITTEE_FOR_DISCIPLINE`" — one of the refusals for which "all five
    are 409 conflicts, not 404s". Nothing unrouted is left behind, so the cycle's
    `proposal_count` stays at 0.

    Design: Corner/errors/plumbing_proposal_with_no_plumbing_committee_is_rejected
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")

    response = api.create_amendment_proposal(
        factories.create_amendment_proposal_payload(
            world["cycle_id"], **PLUMBING_PROPOSAL
        ),
        make_petitioner_headers(),
    )
    validate_error(response, ApiErrorId.ERR_NO_COMMITTEE_FOR_DISCIPLINE, 409)

    _, meta = validate_paginated(
        api.list_cycle_amendment_proposals(
            world["cycle_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 0

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["proposal_count"] == 0


def test_07_a_twenty_nine_day_comment_window_is_rejected(api):
    """"The requested window must span at least 30 days from `opens_at` to
    `closes_at`, inclusive at the boundary: exactly 30 days is accepted, 29 days
    and 23 hours 59 minutes 59 seconds is not, and a short window is refused with
    `ERR_COMMENT_PERIOD_TOO_SHORT`." Nothing about the proposal moves, so
    `review_status` is still `SCREENED` and `comment_window_status` keeps the
    value it "begins at", namely `NONE`.

    Design: Corner/errors/twenty_nine_day_comment_window_is_rejected
    """
    world = fixtures.setup_proposal_ready_for_comment(api)

    response = fixtures.open_comment_window(api, world, **SHORT_WINDOW)
    validate_error(response, ApiErrorId.ERR_COMMENT_PERIOD_TOO_SHORT, 409)

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["comment_window_status"] == "NONE"
    assert proposal["comment_round"] == 0
    assert proposal["review_status"] == "SCREENED"
    assert proposal["comment_opens_at"] is None
    assert proposal["comment_closes_at"] is None


def test_08_a_comment_arriving_at_the_closing_instant_is_rejected(api):
    """"A comment is accepted only when the clock stands at or after
    `comment_opens_at` and strictly before `comment_closes_at`", and "a comment
    arriving outside that half-open range — including one arriving at exactly
    `comment_closes_at` — or arriving when the window is not open, is refused with
    `ERR_COMMENT_WINDOW_CLOSED`". The four comments filed inside the window stand,
    and the window itself is still `OPEN` because nobody has closed it.

    Design: Corner/errors/comment_arriving_at_the_closing_instant_is_rejected
    """
    world = fixtures.setup_proposal_comment_open(api)
    fixtures.submit_golden_comments(api, world)
    fixtures.add_riverbend(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_COMMENT_CLOSES)

    response = fixtures.submit_comment(
        api,
        world,
        "LOCAL_JURISDICTION",
        "OPPOSE",
        "Filed one instant after the deadline.",
        headers=make_jurisdiction_official_headers(world["riverbend_id"]),
    )
    validate_error(response, ApiErrorId.ERR_COMMENT_WINDOW_CLOSED, 409)

    _, meta = validate_paginated(
        api.list_proposal_comments(world["proposal_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 4

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["comment_window_status"] == "OPEN"
    assert proposal["total_comment_count"] == 4


def test_09_a_hearing_noticed_ten_days_ahead_is_rejected(api):
    """"The hearing must be noticed at least 14 days ahead: `scheduled_start` must
    be at or after the clock's current instant plus 14 days, and exactly 14 days
    is acceptable; a shorter notice is refused with
    `ERR_HEARING_NOTICE_TOO_SHORT`." From 2026-09-09 a hearing on 2026-09-19 gives
    ten days, so no hearing row is created.

    Design: Corner/errors/hearing_scheduled_ten_days_out_is_rejected
    """
    world = fixtures.setup_proposal_comment_closed(api)

    response = fixtures.schedule_hearing(api, world, **SHORT_NOTICE_HEARING)
    validate_error(response, ApiErrorId.ERR_HEARING_NOTICE_TOO_SHORT, 409)

    _, meta = validate_paginated(
        api.list_committee_hearings(world["committee_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0


def test_10_convening_a_hearing_with_an_empty_agenda_is_rejected(api):
    """"`agenda_proposal_ids` must be non-empty, or the attempt is refused with
    `ERR_AGENDA_EMPTY`." The auto-fill step was skipped, so even with the clock
    past `scheduled_start` and all six members present the hearing stays
    `SCHEDULED` with "its `present_member_ids`, `present_voting_count`,
    `quorum_required_at_convene`, `convened_at` and `adjourned_at` all null".

    Design: Corner/errors/convening_a_hearing_with_an_empty_agenda_is_rejected
    """
    world = fixtures.setup_proposal_comment_closed(api)
    fixtures.add_scheduled_hearing(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_HEARING_START)

    response = fixtures.convene_hearing(api, world)
    validate_error(response, ApiErrorId.ERR_AGENDA_EMPTY, 409)

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "SCHEDULED"
    assert hearing["agenda_proposal_ids"] == []
    assert hearing["present_voting_count"] is None
    assert hearing["quorum_required_at_convene"] is None
    assert hearing["convened_at"] is None


def test_11_a_ballot_on_a_proposal_off_the_agenda_is_rejected(api):
    """Auto-fill takes only "the proposals routed to this hearing's committee",
    and at the ballot "the proposal must be listed in `agenda_proposal_ids`, or
    the call is refused with `ERR_PROPOSAL_NOT_ON_AGENDA`". The MECHANICAL
    proposal is `COMMENT_CLOSED` with its analysis `COMPLETE`, so the only rule
    it breaks is its absence from this agenda, and no vote record is written.

    Design: Corner/errors/voting_on_a_proposal_absent_from_the_agenda_is_rejected
    """
    world = _convened_hearing_beside_an_off_agenda_proposal(api)
    members = world["members"]
    ballots = [
        factories.ballot(members["chair"]["id"], "YES"),
        factories.ballot(members["fire"]["id"], "YES"),
        factories.ballot(members["local"]["id"], "YES"),
        factories.ballot(members["design"]["id"], "YES"),
    ]

    response = fixtures.record_vote(
        api, world, ballots=ballots, proposal_id=world["sibling_id"]
    )
    validate_error(response, ApiErrorId.ERR_PROPOSAL_NOT_ON_AGENDA, 409)

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["agenda_proposal_ids"] == [world["proposal_id"]]

    sibling = fixtures.read_proposal(api, world["sibling_id"])
    assert sibling["review_status"] == "COMMENT_CLOSED"
    assert sibling["analysis_status"] == "COMPLETE"

    _, meta = validate_paginated(
        api.list_hearing_votes(world["hearing_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0


def test_12_rulemaking_is_refused_while_one_proposal_is_still_open(api):
    """"Entering `RULEMAKING` is a compound gate: every proposal belonging to the
    cycle must have reached one of `APPROVED`, `REJECTED` or `WITHDRAWN`. If any
    proposal is still open, the move is refused with `ERR_PROPOSALS_UNRESOLVED`."
    One approved amendment is not enough while its `SCREENED` sibling is
    unresolved, so the cycle stays in `DELIBERATION`.

    Design: Corner/errors/rulemaking_with_an_unresolved_proposal_is_rejected
    """
    world = _convened_hearing_beside_a_screened_sibling(api)
    get_success_data(fixtures.record_vote(api, world))

    response = api.set_code_cycle_status(
        world["cycle_id"],
        factories.code_cycle_status_payload("RULEMAKING"),
        make_council_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_PROPOSALS_UNRESOLVED, 422)

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["status"] == "DELIBERATION"
    assert cycle["proposal_count"] == 2
    assert cycle["approved_proposal_count"] == 1

    assert fixtures.read_proposal(api, world["proposal_id"])["review_status"] == "APPROVED"
    assert fixtures.read_proposal(api, world["sibling_id"])["review_status"] == "SCREENED"


def test_13_filing_an_order_with_no_approved_amendment_is_rejected(api):
    """Filing requires that "the cycle's `approved_proposal_count` must be at
    least 1, or it is refused with `ERR_NO_APPROVED_AMENDMENTS`". A cycle that
    reached `RULEMAKING` carrying no proposals at all fails that gate, so the
    order stays `DRAFT`, nothing is pinned into the map that "becomes a map from
    each `APPROVED` proposal's `id` to that proposal's `version` at this instant",
    and `filed_by_user_id` is still null.

    Design: Corner/errors/filing_a_rule_with_zero_approved_amendments_is_rejected
    """
    world = fixtures.setup_seated_energy_committee(api)
    for status in ("INTAKE_OPEN", "INTAKE_CLOSED", "DELIBERATION", "RULEMAKING"):
        fixtures.set_cycle_status(api, world["cycle_id"], status)
    fixtures.create_adoption_rule(api, world)

    response = fixtures.advance_rule(
        api, world, "FILED", make_council_admin_headers(ADMIN_FILER_ID)
    )
    validate_error(response, ApiErrorId.ERR_NO_APPROVED_AMENDMENTS, 422)

    rule = get_success_data(
        api.get_adoption_rule(world["rule_id"], make_council_admin_headers())
    )
    assert rule["status"] == "DRAFT"
    assert len(rule["pinned_amendment_versions"]) == 0
    assert rule["filed_by_user_id"] is None

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_proposal_count"] == 0


def test_14_a_jurisdiction_with_no_delegated_authority_cannot_file(api):
    """"A jurisdiction whose `local_authority_level` is `NONE` cannot file at all:
    the attempt is refused with `ERR_LOCAL_AUTHORITY_ABSENT`, and that refusal
    outranks the duplicate-section check." A `MORE_STRINGENT` filing is no
    exception, so Northgate's queue stays empty.

    Design: Corner/errors/local_filing_from_a_jurisdiction_without_authority_is_rejected
    """
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_northgate(api, world)

    response = fixtures.file_local_amendment(
        api,
        world,
        jurisdiction_key="northgate",
        local_text=(
            "Northgate requires an additional half-inch of continuous insulation."
        ),
        stringency_direction="MORE_STRINGENT",
        justification="Colder microclimate.",
    )
    validate_error(response, ApiErrorId.ERR_LOCAL_AUTHORITY_ABSENT, 409)

    northgate = fixtures.read_jurisdiction(api, world["northgate_id"])
    assert northgate["local_authority_level"] == "NONE"
    assert northgate["effective_local_amendment_count"] == 0

    _, meta = validate_paginated(
        api.list_jurisdiction_local_amendments(
            world["northgate_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 0


def test_15_an_appeal_one_second_late_is_rejected(api):
    """"The clock must stand at or before `published_at` plus 30 days, inclusive
    at the boundary, or the appeal is refused with `ERR_APPEAL_WINDOW_EXPIRED`."
    The opinion was published at 2026-10-05T14:00:00Z, so an appeal at
    2026-11-04T14:00:01Z misses the window by a second, and the increment that
    would follow — "on success `appeal_round` increments by one" — never happens.

    Design: Corner/errors/appeal_after_the_thirty_day_window_is_rejected
    """
    world = fixtures.setup_published_interpretation(api)
    fixtures.set_logical_clock(api, ONE_SECOND_AFTER_APPEAL_WINDOW)

    response = fixtures.act_on_interpretation(
        api,
        world,
        "APPEAL",
        appeal_reason="The addition threshold is still ambiguous.",
        headers=make_jurisdiction_official_headers(world["riverbend_id"]),
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, 409)

    request = get_success_data(
        api.get_interpretation_request(
            world["interpretation_request_id"], make_council_admin_headers()
        )
    )
    assert request["status"] == "PUBLISHED"
    assert request["appeal_round"] == 0
    assert request["opinion_number"] == 1


def test_16_a_repeated_attendee_name_on_one_session_is_rejected(api):
    """"A given `attendee_name` may hold only one live seat on a given session — a
    duplicate on a non-`CANCELLED` row is refused with `ERR_DUPLICATE_ENROLLMENT`,
    while a cancelled row frees the name again." The name alone is the key, so
    reusing it under a different `attendee_role` is still a duplicate and the
    ledger keeps `seats_available` at 59.

    Design: Corner/errors/duplicate_attendee_name_on_one_session_is_rejected
    """
    world = fixtures.setup_enrollment_open_session(api)
    fixtures.add_enrollment(
        api, world, "riverbend_1", "riverbend", "Riverbend Official 1"
    )

    response = fixtures.enroll(
        api,
        world,
        "duplicate",
        "riverbend",
        "Riverbend Official 1",
        attendee_role="DESIGN_PROFESSIONAL",
        headers=make_jurisdiction_official_headers(world["riverbend_id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ENROLLMENT, 409)

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["enrolled_count"] == 1
    assert session["seats_available"] == 59

    _, meta = validate_paginated(
        api.list_session_enrollments(world["session_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 1


def test_17_enrolling_into_a_session_with_no_seat_left_is_rejected(api):
    """"A session with `seats_available` at 0 cannot take another enrollment: the
    attempt is refused with `ERR_SESSION_FULL`." The first enrollment consumed the
    only seat, since "`enrolled_count` rises by one and `seats_available` falls by
    one", and the refusal leaves both figures where they stood.

    Design: Corner/errors/enrolling_into_a_full_session_is_rejected
    """
    world = _one_seat_open_session(api)

    response = fixtures.enroll(
        api,
        world,
        "designer_two",
        "riverbend",
        "Riverbend Designer 2",
        attendee_role="DESIGN_PROFESSIONAL",
    )
    validate_error(response, ApiErrorId.ERR_SESSION_FULL, 409)

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["seats_available"] == 0
    assert session["enrolled_count"] == 1
