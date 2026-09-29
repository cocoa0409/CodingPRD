"""Role gates: exclusive operations, shared operations, and the three ownership
checks that sit beyond the flat endpoint-level test."""
from test_helpers import (
    ADMIN_FILER_ID,
    PETITIONER_ONE_ID,
    STAFF_SECOND_ANALYST_ID,
    UNKNOWN_IDENTITY_ID,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    make_committee_member_headers,
    make_council_admin_headers,
    make_jurisdiction_official_headers,
    make_petitioner_headers,
    make_technical_staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PETITIONER_PROPOSAL = {
    "code_section": "C405.2.1",
    "discipline": "ENERGY",
    "title": "Interior lighting power allowance",
    "proposed_text": "Reduce the interior lighting power allowance for warehouses.",
    "stringency_direction": "MORE_STRINGENT",
    "proposer_sector": "INDUSTRY",
}


def _energy_hearing_beside_a_mechanical_chair(api):
    """The golden chain to a SCHEDULED ENERGY hearing with its agenda filled and
    the clock at its start, on a cycle that also carries a SEATED MECHANICAL
    committee with its own chair."""
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_mechanical_committee(api, world)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    fixtures.submit_proposal(api, world)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_CLOSED")
    fixtures.screen_proposal(api, world)
    fixtures.file_cost_benefit_analysis(api, world)
    fixtures.review_analysis(api, world["cost_benefit_id"])
    fixtures.file_energy_impact_analysis(api, world)
    fixtures.review_analysis(api, world["energy_impact_id"])
    fixtures.set_cycle_status(api, world["cycle_id"], "DELIBERATION")
    fixtures.open_comment_window(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_MID_COMMENT)
    fixtures.submit_golden_comments(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_COMMENT_CLOSES)
    fixtures.act_on_comment_window(api, world, "CLOSE")
    fixtures.add_scheduled_hearing(api, world)
    fixtures.fill_agenda(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_HEARING_START)
    return world


def test_01_technical_staff_may_not_open_the_comment_period(api):
    """"A `CouncilAdmin` controls the public comment period for a screened
    proposal by submitting an `action` of `OPEN`, `EXTEND` or `CLOSE`", whereas
    `TechnicalStaff` "screens intake, prepares cost-benefit and energy analyses,
    drafts formal opinions". The analyst who prepared the studies is therefore
    refused on the role rung, and `comment_window_status` keeps the value it
    "begins at", namely `NONE`.

    Design: Corner/rbac/technical_staff_cannot_open_a_comment_window_unauthorized
    """
    world = fixtures.setup_proposal_ready_for_comment(api)

    response = fixtures.open_comment_window(
        api, world, headers=make_technical_staff_headers(STAFF_SECOND_ANALYST_ID)
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["comment_window_status"] == "NONE"
    assert proposal["comment_opens_at"] is None
    assert proposal["review_status"] == "SCREENED"


def test_02_an_ordinary_committee_member_may_not_record_the_ballot(api):
    """A `CouncilChair` "convenes hearings, records ballots, adjourns", while a
    `CommitteeMember` "reads the docket and the analyses; records nothing". A
    seated member of the very committee that is sitting is therefore refused on
    the role rung and no vote record appears.

    Design: Corner/rbac/committee_member_cannot_record_a_vote_unauthorized
    """
    world = fixtures.setup_convened_hearing(api)
    members = world["members"]
    ballots = [
        factories.ballot(members["fire"]["id"], "YES"),
        factories.ballot(members["local"]["id"], "YES"),
        factories.ballot(members["design"]["id"], "YES"),
        factories.ballot(members["industry_two"]["id"], "YES"),
    ]

    response = api.record_vote(
        world["hearing_id"],
        factories.vote_payload(world["proposal_id"], ballots),
        make_committee_member_headers(members["fire"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    _, meta = validate_paginated(
        api.list_hearing_votes(world["hearing_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["review_status"] == "COMMENT_CLOSED"

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "CONVENED"


def test_03_a_petitioner_may_submit_an_amendment_proposal(api):
    """Intake is shared: "a proposed state amendment may be submitted by a
    `CouncilAdmin`, `TechnicalStaff`, a `JurisdictionOfficial` or a `Petitioner`",
    whose "identifier lands in `submitted_by_user_id` on a proposal or a public
    comment". The proposal is routed exactly as any other, and "the server records
    the submitter's identifier in `submitted_by_user_id` and increments the cycle's
    `proposal_count` by one".

    Design: Corner/rbac/petitioner_may_submit_a_proposal_as_a_shared_operation
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")

    response = api.create_amendment_proposal(
        factories.create_amendment_proposal_payload(
            world["cycle_id"], **PETITIONER_PROPOSAL
        ),
        make_petitioner_headers(),
    )
    proposal = validate_success(response, 201)
    assert proposal["committee_id"] == world["committee_id"]
    assert proposal["review_status"] == "SUBMITTED"
    assert proposal["analysis_status"] == "NOT_STARTED"
    assert proposal["proposer_sector"] == "INDUSTRY"
    assert proposal["submitted_by_user_id"] == PETITIONER_ONE_ID

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["proposal_count"] == 1


def test_04_the_chair_of_another_committee_may_not_preside_here(api):
    """"A `CouncilChair` may only act at a hearing held by the committee it
    chairs: `X-User-ID` must resolve to a `CommitteeMember` whose `is_chair` is
    true, whose `status` is `ACTIVE`, and whose `committee_id` equals the hearing's
    committee; otherwise the convene, adjourn and vote-recording actions are
    rejected with `ERR_NOT_COMMITTEE_CHAIR` (403)." The mechanical chair is such a
    member of the wrong committee, so "the chair of a different committee holds the
    `CouncilChair` role but cannot preside here".

    Design: Corner/rbac/chair_of_another_committee_cannot_convene_this_hearing_unauthorized
    """
    world = _energy_hearing_beside_a_mechanical_chair(api)
    mechanical_chair = world["mechanical_members"]["chair"]
    assert mechanical_chair["is_chair"] is True

    response = fixtures.convene_hearing(api, world, chair_id=mechanical_chair["id"])
    validate_error(response, ApiErrorId.ERR_NOT_COMMITTEE_CHAIR, 403)

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "SCHEDULED"
    assert hearing["present_voting_count"] is None
    assert hearing["convened_at"] is None


def test_05_an_unresolvable_jurisdiction_identity_is_reported_before_the_body(api):
    """For the entity-backed roles, "an `X-User-ID` that does not resolve to a live
    row of the backing entity ... is an authorization failure reported as
    `ERR_IDENTITY_NOT_FOUND` (403), never a 404". Identity resolution sits above
    body-reference existence on the ladder, so the well-formed filing writes
    nothing.

    Design: Corner/rbac/jurisdiction_official_with_an_unknown_identity_returns_4xx
    """
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)

    response = fixtures.file_local_amendment(
        api,
        world,
        local_text="Filed by an identity the council does not know.",
        justification="Unknown filer.",
        headers=make_jurisdiction_official_headers(UNKNOWN_IDENTITY_ID),
    )
    validate_error(response, ApiErrorId.ERR_IDENTITY_NOT_FOUND, 403)

    _, meta = validate_paginated(
        api.list_jurisdiction_local_amendments(
            world["riverbend_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 0


def test_06_one_jurisdiction_may_not_file_on_another_s_behalf(api):
    """"A `JurisdictionOfficial` may only act on resources belonging to its own
    jurisdiction: filing or resubmitting a local amendment, enrolling an attendee,
    cancelling an enrollment, or appealing an opinion on behalf of another
    jurisdiction is rejected with `ERR_JURISDICTION_MISMATCH` (403)." Riverbend's
    official supplies Harborview's own `jurisdiction_id` and version, and is still
    refused because that identifier "must equal the acting `X-User-ID`".

    Design: Corner/rbac/jurisdiction_official_cannot_file_for_another_jurisdiction_unauthorized
    """
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_harborview(api, world)

    response = fixtures.file_local_amendment(
        api,
        world,
        jurisdiction_key="harborview",
        local_text="Riverbend files on Harborview's behalf.",
        justification="Shared building department.",
        headers=make_jurisdiction_official_headers(world["riverbend_id"]),
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_MISMATCH, 403)

    _, meta = validate_paginated(
        api.list_jurisdiction_local_amendments(
            world["harborview_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 0

    harborview = fixtures.read_jurisdiction(api, world["harborview_id"])
    assert harborview["effective_local_amendment_count"] == 0


def test_07_the_administrator_who_filed_the_order_may_not_publish_it(api):
    """"Publication moves the order `FILED` → `PUBLISHED`" only for a second pair
    of eyes: "an acting identifier equal to `filed_by_user_id` is refused with
    `ERR_SEGREGATION_OF_DUTIES`", the ladder rung that asks that "the acting
    `X-User-ID` differs from the user recorded for the paired earlier step".
    Nothing is stamped, so `published_at` stays null.

    Design: Corner/rbac/the_filer_cannot_publish_the_same_adoption_rule_unauthorized
    """
    world = fixtures.setup_filed_adoption_rule(api)

    response = fixtures.advance_rule(
        api, world, "PUBLISHED", make_council_admin_headers(ADMIN_FILER_ID)
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    rule = get_success_data(
        api.get_adoption_rule(world["rule_id"], make_council_admin_headers())
    )
    assert rule["status"] == "FILED"
    assert rule["filed_by_user_id"] == ADMIN_FILER_ID
    assert rule["published_at"] is None
    assert rule["published_by_user_id"] is None
