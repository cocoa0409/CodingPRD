"""The published public-need finding and the fork the capacity screen takes.

Covers assessment publication and supersession, the six side effects of a direct
screen, the composite gate that a screen must satisfy, and the renewal-priority
branch of the fork.
"""
from test_helpers import (
    ApiErrorId,
    activate_permit,
    create_application,
    create_needs_assessment,
    create_outfitter,
    create_screened_application,
    create_use_area,
    file_performance_evaluation,
    issue_permit,
    publish_needs_assessment,
    read_allocation_summary,
    read_application,
    read_needs_assessment_list,
    read_permit,
    read_use_area,
    satisfy_activation_gates,
    screen_application,
    set_clock,
    submit_application,
    validate_error,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]


def test_publishing_a_second_assessment_supersedes_only_the_same_year_incumbent():
    """PRD §3.1: "Only one published assessment may govern a given area and year at a time,
    so publishing a second one moves any earlier `PUBLISHED` sibling for the same area and
    `assessment_year` to `SUPERSEDED` inside the same request, incrementing the `version` of
    both rows."
    PRD §3.1: "`SUPERSEDED` is terminal: the row keeps its `published_at` and its last
    computed figures forever and is excluded from every later recomputation."
    PRD §3.1: "An area's assessments can be listed with optional `assessment_year` and
    `status` filters, ordered oldest first."

    Design: Corner/state_machines/publishing_a_second_assessment_supersedes_the_first_in_the_same_request
    """
    set_clock()
    area = create_use_area()

    first = create_needs_assessment(area["id"], assessment_year=2027,
                                    determined_capacity_service_days=900)
    first = publish_needs_assessment(first["id"])
    assert first["status"] == "PUBLISHED"
    assert first["published_at"] is not None
    assert first["published_at"].startswith("2027-01-05")
    assert first["version"] == 2
    assert first["allocated_service_days"] == 0
    assert first["unallocated_service_days"] == 900
    assert first["prospectus_required"] is False

    other_year = create_needs_assessment(area["id"], assessment_year=2028,
                                         determined_capacity_service_days=700)
    publish_needs_assessment(other_year["id"])

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    untouched = [row for row in rows if row["id"] == first["id"]][0]
    assert untouched["status"] == "PUBLISHED", (
        "supersession is scoped to the same assessment_year, not merely the same area"
    )
    assert untouched["version"] == 2

    second = create_needs_assessment(area["id"], assessment_year=2027,
                                     determined_capacity_service_days=800)
    second = publish_needs_assessment(second["id"])
    assert second["status"] == "PUBLISHED"
    assert second["unallocated_service_days"] == 800

    rows, meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]], (
        "the listing comes back oldest first"
    )
    superseded = rows[0]
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["version"] == 3
    assert superseded["published_at"] == first["published_at"], (
        "supersession freezes the row rather than clearing it"
    )
    assert superseded["allocated_service_days"] == 0
    assert superseded["unallocated_service_days"] == 900


def test_one_direct_screen_lands_every_declared_side_effect_in_a_single_request():
    """PRD §3.2: "Given those, the screen stamps `screened_at` from the logical clock,
    evaluates the routing rule described next and stamps `routing_decision`, adds the
    application's `requested_service_days` to the area's `pending_service_days` and recomputes
    `available_service_days`, `demand_ratio` and `allocation_posture`, then recomputes the
    governing assessment's `allocated_service_days`, `unallocated_service_days` and
    `prospectus_required`."
    PRD §3.2: "The application lands on `CAPACITY_SCREENED` and then, inside the very same
    request, forks automatically to one of two statuses."
    PRD §3.2: "On the `DIRECT` fork the application moves `CAPACITY_SCREENED →
    DIRECT_AWARD_PENDING` and `hold_expires_at` is stamped at exactly 30 days past
    `screened_at` — a non-competitive hold, award-ready, with a deadline."

    Design: Corner/state_machines/direct_screen_writes_every_declared_side_effect_in_one_request
    """
    set_clock()
    area = create_use_area()
    assessment = create_needs_assessment(area["id"])
    assessment = publish_needs_assessment(assessment["id"])
    outfitter = create_outfitter()
    application = create_application(outfitter["id"], area["id"],
                                     narrative="Guided day floats.")
    submit_application(application["id"], outfitter["id"])

    screened = screen_application(application["id"])
    assert screened["status"] == "DIRECT_AWARD_PENDING", (
        "CAPACITY_SCREENED is never observable; the fork fires in the same request"
    )
    assert screened["routing_decision"] == "DIRECT"
    assert screened["screened_at"].startswith("2027-01-05")
    assert screened["hold_expires_at"][:10] == "2027-02-04", (
        "the hold expires exactly 30 days past the screening instant"
    )
    assert screened["prospectus_id"] is None
    assert screened["preliminary_evaluation_score"] is None
    assert screened["final_evaluation_score"] is None
    assert screened["version"] == 3, "create, submit and screen are three writes"

    stored = read_use_area(area["id"])
    assert stored["committed_service_days"] == 0
    assert stored["pending_service_days"] == 200
    assert stored["available_service_days"] == 700
    assert stored["demand_ratio"] == 0.2222
    assert stored["allocation_posture"] == "OPEN"
    assert stored["version"] == 2

    summary = read_allocation_summary(area["id"])
    assert summary["allocatable_service_days"] == 900
    assert (
        summary["committed_service_days"]
        + summary["pending_service_days"]
        + summary["available_service_days"]
        == 900
    )

    rows, _meta = read_needs_assessment_list(area["id"], params={"assessment_year": 2027})
    governing = [row for row in rows if row["id"] == assessment["id"]][0]
    assert governing["allocated_service_days"] == 200
    assert governing["unallocated_service_days"] == 700
    assert governing["prospectus_required"] is False, (
        "the flag is a side effect of the solicitation fork alone"
    )
    assert governing["version"] == 3, "create, publish and the screen recomputation"


SOUTH_FORK = {
    "area_code": "BRW-02",
    "name": "Bear River South Fork",
    "total_allocated_service_days": 500,
    "reserved_admin_service_days": 50,
    "season_open_date": "2027-06-01",
    "season_close_date": "2027-09-15",
    "party_size_max": 8,
    "max_clients_per_guide": 6,
}


def _two_areas_with_awkward_findings():
    """BRW-01 carries a published 2026 finding and a still-draft 2027 one; BRW-02
    carries a published 2027 finding of NO_NEED. One outfitter has a submitted
    2027 application waiting on each."""
    set_clock()
    north = create_use_area()
    south = create_use_area(**SOUTH_FORK)

    published_2026 = create_needs_assessment(north["id"], assessment_year=2026)
    published_2026 = publish_needs_assessment(published_2026["id"])
    draft_2027 = create_needs_assessment(north["id"], assessment_year=2027)

    no_need = create_needs_assessment(
        south["id"],
        assessment_year=2027,
        public_need_finding="NO_NEED",
        determined_capacity_service_days=450,
    )
    publish_needs_assessment(no_need["id"])

    outfitter = create_outfitter()
    north_app = create_application(outfitter["id"], north["id"])
    submit_application(north_app["id"], outfitter["id"])
    south_app = create_application(
        outfitter["id"], south["id"], requested_service_days=100,
        proposed_activity_type="HUNTING",
    )
    submit_application(south_app["id"], outfitter["id"])
    return {
        "north": north,
        "south": south,
        "published_2026": published_2026,
        "draft_2027": draft_2027,
        "north_app": north_app,
        "south_app": south_app,
    }


def test_a_published_finding_for_the_wrong_year_does_not_satisfy_the_screening_gate():
    """PRD §3.2: "A needs assessment whose `use_area_id` matches the application's area,
    whose `assessment_year` matches the application's `season_year` and whose `status` is
    `PUBLISHED` must exist, else `ERR_NEEDS_ASSESSMENT_NOT_PUBLISHED`; and that assessment's
    `public_need_finding` must be `NEED_EXISTS`, else `ERR_NO_PUBLIC_NEED`."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Difficulty/cross_entity_state_dependency/application_screening_gated_by_needs_assessment_publication
    """
    stage = _two_areas_with_awkward_findings()

    validate_error(
        api_client.screen_permit_application(stage["north_app"]["id"], SPECIALIST),
        ApiErrorId.ERR_NEEDS_ASSESSMENT_NOT_PUBLISHED,
    )
    refused = read_application(stage["north_app"]["id"])
    assert refused["status"] == "SUBMITTED"
    assert refused["routing_decision"] is None
    assert refused["screened_at"] is None
    assert read_allocation_summary(stage["north"]["id"])["pending_service_days"] == 0

    published = publish_needs_assessment(stage["draft_2027"]["id"])
    assert published["status"] == "PUBLISHED"
    assert published["published_at"].startswith("2027-01-05")

    rows, _meta = read_needs_assessment_list(
        stage["north"]["id"], params={"assessment_year": 2026}
    )
    assert [row["status"] for row in rows] == ["PUBLISHED"], (
        "supersession is scoped to the same area and year, so 2026 is left standing"
    )

    screened = screen_application(stage["north_app"]["id"])
    assert screened["routing_decision"] == "DIRECT"
    assert screened["status"] == "DIRECT_AWARD_PENDING"
    assert read_allocation_summary(stage["north"]["id"])["pending_service_days"] == 200


def test_publication_alone_is_not_enough_when_the_finding_records_no_public_need():
    """PRD §3.2: "A needs assessment whose `use_area_id` matches the application's area,
    whose `assessment_year` matches the application's `season_year` and whose `status` is
    `PUBLISHED` must exist, else `ERR_NEEDS_ASSESSMENT_NOT_PUBLISHED`; and that assessment's
    `public_need_finding` must be `NEED_EXISTS`, else `ERR_NO_PUBLIC_NEED`."
    PRD §3.1: "and sets `prospectus_required` to true when the finding is `NO_NEED` **or**
    when `unallocated_service_days` is at or below zero."

    Design: Difficulty/cross_entity_state_dependency/application_screening_gated_by_needs_assessment_publication
    """
    stage = _two_areas_with_awkward_findings()

    validate_error(
        api_client.screen_permit_application(stage["south_app"]["id"], SPECIALIST),
        ApiErrorId.ERR_NO_PUBLIC_NEED,
    )
    rows, _meta = read_needs_assessment_list(
        stage["south"]["id"], params={"assessment_year": 2027}
    )
    governing = rows[0]
    assert governing["status"] == "PUBLISHED"
    assert governing["public_need_finding"] == "NO_NEED"
    assert governing["prospectus_required"] is True

    publish_needs_assessment(stage["draft_2027"]["id"])
    screen_application(stage["north_app"]["id"])

    validate_error(
        api_client.screen_permit_application(stage["south_app"]["id"], SPECIALIST),
        ApiErrorId.ERR_NO_PUBLIC_NEED,
    )
    still_waiting = read_application(stage["south_app"]["id"])
    assert still_waiting["status"] == "SUBMITTED"
    assert read_allocation_summary(stage["south"]["id"])["pending_service_days"] == 0, (
        "the two areas' gates are independent"
    )


BETA = {"legal_name": "Beta Trails Co", "ein": "410000002",
        "contact_email": "ops@beta.example"}


def _active_2026_permit(area, outfitter, requested_service_days, activity_type):
    """Walk one outfitter to an ACTIVE 2026 permit in the given area."""
    application = create_screened_application(
        outfitter["id"], area["id"], season_year=2026,
        requested_service_days=requested_service_days,
        proposed_activity_type=activity_type,
    )
    permit = issue_permit(
        application["id"], term_start_date="2026-01-01", term_end_date="2026-12-31"
    )
    context = {"use_area": area, "outfitter": outfitter, "permit": permit}
    satisfy_activation_gates(context, plan_year=2026)
    context["permit"] = activate_permit(permit["id"])
    return context


def _two_renewals_awaiting_the_fork():
    """One area, two ACTIVE 2026 predecessors. Alpine's carries a SATISFACTORY
    evaluation; Beta's has never been evaluated. Both hold submitted 2027
    renewals and the area has room for either."""
    set_clock()
    area = create_use_area()
    publish_needs_assessment(
        create_needs_assessment(area["id"], assessment_year=2026)["id"]
    )

    alpine = create_outfitter()
    alpine_context = _active_2026_permit(area, alpine, 200, "RIVER_FLOAT")
    evaluation = file_performance_evaluation(
        alpine_context["permit"]["id"], evaluation_year=2026,
        resource_protection_score=88, client_safety_score=88,
        reporting_timeliness_score=88, fee_compliance_score=88,
    )

    beta = create_outfitter(**BETA)
    beta_context = _active_2026_permit(area, beta, 100, "HUNTING")

    publish_needs_assessment(
        create_needs_assessment(area["id"], assessment_year=2027)["id"]
    )

    alpine_renewal = create_application(
        alpine["id"], area["id"], application_type="RENEWAL",
        requested_service_days=200, proposed_activity_type="RIVER_FLOAT",
        predecessor_permit_id=alpine_context["permit"]["id"],
    )
    submit_application(alpine_renewal["id"], alpine["id"])
    beta_renewal = create_application(
        beta["id"], area["id"], application_type="RENEWAL",
        requested_service_days=100, proposed_activity_type="HUNTING",
        predecessor_permit_id=beta_context["permit"]["id"],
    )
    submit_application(beta_renewal["id"], beta["id"])
    return {
        "use_area": area,
        "evaluation": evaluation,
        "alpine": alpine_context,
        "beta": beta_context,
        "alpine_renewal": alpine_renewal,
        "beta_renewal": beta_renewal,
    }


def test_a_rated_predecessor_wins_a_direct_renewal_while_an_unrated_one_is_queued():
    """PRD §3.2: "For a `RENEWAL` the area's remainder is not consulted at all. Instead,
    three conditions on the predecessor must all hold for a `DIRECT` routing: the
    predecessor's `compliance_status` must be `COMPLIANT`, its `latest_performance_rating`
    must be `SUPERIOR` or `SATISFACTORY`, and the `requested_service_days` must not exceed
    the predecessor's `authorized_service_days`."
    PRD §3.2: "A renewal whose predecessor has never been evaluated has a null
    `latest_performance_rating`, which is not one of the two priority ratings, so it routes
    `PROSPECTUS` too."

    Design: Difficulty/non_linear_state_machine/application_screen_fork_renewal_priority_versus_prospectus
    """
    stage = _two_renewals_awaiting_the_fork()

    assert stage["evaluation"]["rating"] == "SATISFACTORY"
    alpine_permit = read_permit(stage["alpine"]["permit"]["id"])
    assert alpine_permit["compliance_status"] == "COMPLIANT"
    assert alpine_permit["latest_performance_rating"] == "SATISFACTORY"
    beta_permit = read_permit(stage["beta"]["permit"]["id"])
    assert beta_permit["compliance_status"] == "COMPLIANT"
    assert beta_permit["latest_performance_rating"] is None

    before = read_allocation_summary(stage["use_area"]["id"])
    assert before["committed_service_days"] == 300
    assert before["available_service_days"] == 600, (
        "both renewals could have been satisfied on capacity alone"
    )

    alpine_screened = screen_application(stage["alpine_renewal"]["id"])
    assert alpine_screened["routing_decision"] == "DIRECT"
    assert alpine_screened["status"] == "DIRECT_AWARD_PENDING"
    assert alpine_screened["hold_expires_at"][:10] == "2027-02-04"

    beta_screened = screen_application(stage["beta_renewal"]["id"])
    assert beta_screened["routing_decision"] == "PROSPECTUS", (
        "a null rating is not a member of the priority set, so the remainder never mattered"
    )
    assert beta_screened["status"] == "PROSPECTUS_QUEUED"
    assert beta_screened["hold_expires_at"] is None


def test_the_two_renewal_forks_have_disjoint_continuations():
    """PRD §3.4: "An `AuthorizedOfficer` or `ProgramAdministrator` issues the permit for an
    application sitting in `DIRECT_AWARD_PENDING` or in `AWARDED`; from any other status the
    answer is `ERR_INVALID_APPLICATION_STATE`."
    PRD §3.2: "A queued application cannot advance on its own; it must be attached to a
    solicitation."

    Design: Difficulty/non_linear_state_machine/application_screen_fork_renewal_priority_versus_prospectus
    """
    stage = _two_renewals_awaiting_the_fork()
    screen_application(stage["alpine_renewal"]["id"])
    screen_application(stage["beta_renewal"]["id"])

    successor = issue_permit(
        stage["alpine_renewal"]["id"],
        term_start_date="2027-01-15",
        term_end_date="2027-12-31",
    )
    assert successor["administrative_status"] == "ISSUED"
    assert successor["authorized_service_days"] == 200
    assert successor["predecessor_permit_id"] == stage["alpine"]["permit"]["id"]

    validate_error(
        api_client.issue_permit(
            stage["beta_renewal"]["id"],
            {
                "term_start_date": "2027-01-15",
                "term_end_date": "2027-12-31",
                "indemnification_acknowledged": True,
            },
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
    )
    assert read_application(stage["beta_renewal"]["id"])["status"] == "PROSPECTUS_QUEUED"
