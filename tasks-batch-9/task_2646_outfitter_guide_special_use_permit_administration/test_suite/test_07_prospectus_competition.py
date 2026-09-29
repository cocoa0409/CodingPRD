"""Competitive solicitation: the two scoring variants, the gates and the award.

Covers the preliminary/final rank flip, the five response preconditions, the
per-action lifecycle gates, the stale use-area token and the created_at tie-break.
"""
from test_helpers import (
    ApiErrorId,
    award_prospectus,
    close_prospectus_submissions,
    create_application,
    create_guide,
    create_outfitter,
    create_prospectus,
    create_published_assessment,
    create_qualified_guide,
    create_screened_application,
    create_submitted_application,
    create_use_area,
    current_use_area_version,
    issue_permit,
    read_application,
    read_outfitter,
    read_prospectus,
    read_use_area,
    respond_to_prospectus,
    screen_application,
    set_clock,
    setup_queued_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]

CEDAR_BASIN = {
    "area_code": "BRW-02",
    "name": "Cedar Basin",
    "total_allocated_service_days": 200,
    "reserved_admin_service_days": 0,
    "season_open_date": "2027-06-01",
    "season_close_date": "2027-09-15",
    "party_size_max": 10,
    "max_clients_per_guide": 6,
}
DELTA = {
    "legal_name": "Delta River Guides",
    "ein": "420000004",
    "contact_email": "ops@delta.example",
    "prequalification_insurance_verified": True,
}
CEDAR = {
    "legal_name": "Cedar Creek Outfitters",
    "ein": "420000003",
    "contact_email": "ops@cedar.example",
    "prequalification_insurance_verified": False,
}


def _rank_flip_stage():
    """A two-horse solicitation whose two variants disagree: Delta has a prior
    permit and two unqualified hires but is verified; Cedar has no prior permit
    and one qualified guide but is unverified."""
    set_clock()
    area = create_use_area(**CEDAR_BASIN)
    current = create_published_assessment(area["id"], determined_capacity_service_days=200)
    create_published_assessment(
        area["id"], assessment_year=2026, determined_capacity_service_days=200
    )
    delta = create_outfitter(**DELTA)
    cedar = create_outfitter(**CEDAR)

    prior = create_screened_application(
        delta["id"], area["id"], season_year=2026, requested_service_days=50,
        proposed_activity_type="FISHING", narrative="Delta prior season",
    )
    issue_permit(
        prior["id"], term_start_date="2026-01-01", term_end_date="2026-12-31"
    )
    assert read_outfitter(delta["id"])["prior_permit_count"] == 1

    create_guide(
        delta["id"], full_name="Dana Frost", qualification_level="LEAD",
        first_aid_cert_type="WFR", first_aid_expires_on="2030-06-30",
        seasons_experience=6,
    )
    create_guide(
        delta["id"], full_name="Dev Ortiz", qualification_level="ASSISTANT",
        first_aid_cert_type="WFR", first_aid_expires_on="2030-06-30",
        seasons_experience=3,
    )
    create_qualified_guide(
        cedar["id"], full_name="Cara Bell", qualification_level="LEAD",
        first_aid_cert_type="WEMT", first_aid_expires_on="2030-06-30",
        seasons_experience=9,
    )

    cedar_app = create_screened_application(
        cedar["id"], area["id"], requested_service_days=300,
        proposed_activity_type="FISHING", narrative="Cedar 2027 bid",
    )
    delta_app = create_screened_application(
        delta["id"], area["id"], requested_service_days=300,
        proposed_activity_type="FISHING", narrative="Delta 2027 bid",
    )
    assert cedar_app["routing_decision"] == "PROSPECTUS"
    assert delta_app["routing_decision"] == "PROSPECTUS"

    prospectus = create_prospectus(
        area["id"], current["id"], offered_service_days=300,
        submission_deadline_date="2027-03-31", min_qualifying_score=40.0,
    )
    respond_to_prospectus(prospectus["id"], cedar_app["id"], cedar["id"])
    respond_to_prospectus(prospectus["id"], delta_app["id"], delta["id"])
    return {
        "area": area,
        "delta": delta,
        "cedar": cedar,
        "cedar_app": cedar_app,
        "delta_app": delta_app,
        "prospectus": prospectus,
    }


def test_the_preliminary_variant_credits_pending_hires_and_assumes_the_paperwork():
    """PRD §3.3: "Closing submissions is the `PermitSpecialist`'s exclusive act and moves the
    solicitation `OPEN → EVALUATING`. It scores every responsive application under the
    **preliminary** variant and writes each result to `preliminary_evaluation_score`. No winner
    is chosen here."
    PRD §3.3: "Under the **preliminary** variant the guide-roster numerator counts guides in
    `QUALIFIED` *or* `PENDING_QUALIFICATION` — freshly hired guides get credit — and the
    assurance term is a flat 100.0 for every applicant, assuming the documents will prove
    acceptable."
    PRD §3.3: "The **experience** term gives the applicant 25 points for each permit its
    outfitter has ever held, capped at 100 — so four prior permits max it out."
    PRD §3.3: "so a request exactly equal to the offer scores 100.0"

    Design: Difficulty/dual_variant_calc/prospectus_scoring_preliminary_versus_final_rank_flip
    """
    stage = _rank_flip_stage()

    closed = close_prospectus_submissions(stage["prospectus"]["id"])
    assert closed["status"] == "EVALUATING"
    assert closed["responsive_application_count"] == 2

    cedar_app = read_application(stage["cedar_app"]["id"])
    delta_app = read_application(stage["delta_app"]["id"])
    assert cedar_app["preliminary_evaluation_score"] == 70.00, (
        "0.30*0 + 0.30*100.00 + 0.20*100.0 + 0.20*100.0"
    )
    assert delta_app["preliminary_evaluation_score"] == 77.50, (
        "0.30*25 + 0.30*100.00 + 0.20*100.0 + 0.20*100.0 — both hires count"
    )
    assert delta_app["preliminary_evaluation_score"] > cedar_app["preliminary_evaluation_score"]

    assert cedar_app["final_evaluation_score"] is None
    assert delta_app["final_evaluation_score"] is None
    assert closed["awarded_application_id"] is None
    assert cedar_app["status"] == "PROSPECTUS_RESPONDED"
    assert delta_app["status"] == "PROSPECTUS_RESPONDED"


def test_the_final_variant_reverses_the_ranking_and_the_award_follows_it():
    """PRD §3.3: "Under the **final** variant the numerator counts only `QUALIFIED` guides, and
    the assurance term is 100.0 only when the applicant outfitter's
    `prequalification_insurance_verified` is true, and 0.0 otherwise."
    PRD §3.3: "The award first re-scores every responsive application under the **final** variant,
    writing `final_evaluation_score` on each, and then runs the selector."
    PRD §3.3: "The award writes `awarded_application_id`, moves the solicitation `EVALUATING →
    AWARDED`, moves the winner `PROSPECTUS_RESPONDED → AWARDED`, and moves every other response
    `PROSPECTUS_RESPONDED → DENIED` with `denial_reason_code` set to the literal `NOT_SELECTED`."

    Design: Difficulty/dual_variant_calc/prospectus_scoring_preliminary_versus_final_rank_flip
    """
    stage = _rank_flip_stage()
    close_prospectus_submissions(stage["prospectus"]["id"])
    preliminary = {
        "cedar": read_application(stage["cedar_app"]["id"])["preliminary_evaluation_score"],
        "delta": read_application(stage["delta_app"]["id"])["preliminary_evaluation_score"],
    }
    assert preliminary["delta"] > preliminary["cedar"]

    awarded = award_prospectus(
        stage["prospectus"]["id"], current_use_area_version(stage["area"]["id"])
    )
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_application_id"] == stage["cedar_app"]["id"]

    cedar_app = read_application(stage["cedar_app"]["id"])
    delta_app = read_application(stage["delta_app"]["id"])
    assert cedar_app["final_evaluation_score"] == 50.00, (
        "0.30*0 + 0.30*100.00 + 0.20*0.0 + 0.20*100.0 — one of one guide qualified, unverified"
    )
    assert delta_app["final_evaluation_score"] == 47.50, (
        "0.30*25 + 0.30*0.00 + 0.20*100.0 + 0.20*100.0 — neither hire is qualified yet"
    )
    assert cedar_app["final_evaluation_score"] > delta_app["final_evaluation_score"], (
        "the two variants order the same pool in opposite directions"
    )
    assert cedar_app["status"] == "AWARDED"
    assert delta_app["status"] == "DENIED"
    assert delta_app["denial_reason_code"] == "NOT_SELECTED"

    assert min(
        cedar_app["final_evaluation_score"], delta_app["final_evaluation_score"]
    ) >= 40.0, "both clear the bar, so the flip is a ranking outcome not an eligibility filter"


def test_each_response_precondition_fires_its_own_error_at_its_own_tier():
    """PRD §3.3: "The application must be in `PROSPECTUS_QUEUED` and must belong to the caller,
    the solicitation must be `OPEN` (otherwise `ERR_PROSPECTUS_NOT_OPEN`), the solicitation's
    `use_area_id` must match the application's, the current logical date must be on or before
    `submission_deadline_date` (otherwise `ERR_SUBMISSION_DEADLINE_PASSED`, the boundary being
    inclusive), and the application's `requested_service_days` must not exceed
    `offered_service_days` (otherwise `ERR_INSUFFICIENT_SERVICE_DAYS`)."
    PRD §3.3: "The response moves the application `PROSPECTUS_QUEUED → PROSPECTUS_RESPONDED`,
    writes its `prospectus_id`, and recomputes `responsive_application_count` as the number of
    applications pointing at this solicitation in `PROSPECTUS_RESPONDED`."

    Design: Corner/state_machines/each_prospectus_response_precondition_fires_its_own_error
    """
    set_clock()
    area = create_use_area()
    assessment = create_published_assessment(area["id"], determined_capacity_service_days=900)
    alpine = create_outfitter()
    holder = make_outfitter_representative_headers(alpine["id"])

    direct = create_screened_application(alpine["id"], area["id"], requested_service_days=900)
    assert direct["routing_decision"] == "DIRECT"
    issue_permit(direct["id"])
    assert read_use_area(area["id"])["available_service_days"] == 0

    oversized = create_screened_application(
        alpine["id"], area["id"], requested_service_days=200
    )
    ready = create_screened_application(alpine["id"], area["id"], requested_service_days=100)
    unscreened = create_submitted_application(
        alpine["id"], area["id"], requested_service_days=100
    )
    on_deadline = create_screened_application(
        alpine["id"], area["id"], requested_service_days=100
    )
    late = create_screened_application(alpine["id"], area["id"], requested_service_days=100)
    for queued in (oversized, ready, on_deadline, late):
        assert queued["routing_decision"] == "PROSPECTUS"
        assert queued["status"] == "PROSPECTUS_QUEUED"
    assert unscreened["status"] == "SUBMITTED"

    prospectus = create_prospectus(
        area["id"], assessment["id"], offered_service_days=150,
        submission_deadline_date="2027-03-01",
    )

    validate_error(
        api_client.create_prospectus_response(
            prospectus["id"], {"application_id": unscreened["id"]}, holder
        ),
        ApiErrorId.ERR_INVALID_APPLICATION_STATE,
    )
    validate_error(
        api_client.create_prospectus_response(
            prospectus["id"], {"application_id": oversized["id"]}, holder
        ),
        ApiErrorId.ERR_INSUFFICIENT_SERVICE_DAYS,
    )

    responded = respond_to_prospectus(prospectus["id"], ready["id"], alpine["id"])
    assert responded["status"] == "PROSPECTUS_RESPONDED"
    assert responded["prospectus_id"] == prospectus["id"]
    assert read_prospectus(prospectus["id"])["responsive_application_count"] == 1

    set_clock("2027-03-01T00:00:00Z")
    boundary = respond_to_prospectus(prospectus["id"], on_deadline["id"], alpine["id"])
    assert boundary["status"] == "PROSPECTUS_RESPONDED", "the deadline is inclusive"
    assert read_prospectus(prospectus["id"])["responsive_application_count"] == 2

    set_clock("2027-03-02T00:00:00Z")
    validate_error(
        api_client.create_prospectus_response(
            prospectus["id"], {"application_id": late["id"]}, holder
        ),
        ApiErrorId.ERR_SUBMISSION_DEADLINE_PASSED,
    )

    final = read_prospectus(prospectus["id"])
    assert final["responsive_application_count"] == 2
    assert final["status"] == "OPEN"
    assert final["awarded_application_id"] is None
    for untouched in (oversized, unscreened, late):
        row = read_application(untouched["id"])
        assert row["prospectus_id"] is None
        assert row["status"] == untouched["status"]


def test_the_four_solicitation_actions_admit_three_different_state_sets():
    """PRD §3.3: "Closing submissions is the `PermitSpecialist`'s exclusive act and moves the
    solicitation `OPEN → EVALUATING`."
    PRD §3.3: "Award is the officer's act, shared with the `ProgramAdministrator`, and it needs
    the solicitation to be `EVALUATING` (otherwise `ERR_PROSPECTUS_NOT_OPEN`) and the
    `expected_use_area_version` to match the governing area's current `version` (otherwise
    `ERR_STALE_USE_AREA_VERSION`)."
    PRD §3.3: "If the pool is empty, the whole award is rejected with
    `ERR_NO_RESPONSIVE_APPLICATIONS` (HTTP 409) and nothing is written."
    PRD §3.3: "An `AuthorizedOfficer` or `ProgramAdministrator` may cancel a solicitation that is
    `OPEN` or `EVALUATING`, supplying a `cancellation_reason_code`; a solicitation already
    `AWARDED` or `CANCELLED` yields `ERR_PROSPECTUS_NOT_OPEN`."
    PRD §3.3: "Each denial releases its `requested_service_days` from the area's
    `pending_service_days`, after which `available_service_days`, `demand_ratio` and
    `allocation_posture` are recomputed and the area's `version` is incremented by exactly 1."

    Design: Corner/endpoints/prospectus_actions_are_each_gated_on_a_different_slice_of_the_lifecycle
    """
    context = setup_queued_application(requested_service_days=250)
    area_id = context["use_area"]["id"]
    alpine_id = context["outfitter"]["id"]
    holder = context["holder_headers"]
    application = context["application"]
    create_qualified_guide(alpine_id, full_name="Rita Long", seasons_experience=0)
    assert context["outfitter"]["prequalification_insurance_verified"] is True

    first = create_prospectus(
        area_id, context["needs_assessment"]["id"], offered_service_days=300,
        submission_deadline_date="2027-03-31",
    )
    second = create_prospectus(
        area_id, context["needs_assessment"]["id"], offered_service_days=300,
        submission_deadline_date="2027-03-31",
    )
    opening_version = current_use_area_version(area_id)

    validate_error(
        api_client.award_prospectus(
            first["id"], {"expected_use_area_version": opening_version}, OFFICER
        ),
        ApiErrorId.ERR_PROSPECTUS_NOT_OPEN,
    )

    evaluating = close_prospectus_submissions(first["id"])
    assert evaluating["status"] == "EVALUATING"
    assert evaluating["responsive_application_count"] == 0

    validate_error(
        api_client.create_prospectus_response(
            first["id"], {"application_id": application["id"]}, holder
        ),
        ApiErrorId.ERR_PROSPECTUS_NOT_OPEN,
    )
    validate_error(
        api_client.award_prospectus(
            first["id"], {"expected_use_area_version": opening_version}, OFFICER
        ),
        ApiErrorId.ERR_NO_RESPONSIVE_APPLICATIONS,
    )
    still_evaluating = read_prospectus(first["id"])
    assert still_evaluating["status"] == "EVALUATING"
    assert still_evaluating["awarded_application_id"] is None
    assert current_use_area_version(area_id) == opening_version, (
        "neither rejected award consumed the concurrency token"
    )

    cancelled = validate_success(
        api_client.cancel_prospectus(
            first["id"], {"cancellation_reason_code": "PROGRAM_WITHDRAWN"}, OFFICER
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason_code"] == "PROGRAM_WITHDRAWN"

    validate_error(
        api_client.cancel_prospectus(
            first["id"], {"cancellation_reason_code": "PROGRAM_WITHDRAWN"}, OFFICER
        ),
        ApiErrorId.ERR_PROSPECTUS_NOT_OPEN,
    )
    validate_error(
        api_client.close_prospectus_submissions(first["id"], SPECIALIST),
        ApiErrorId.ERR_PROSPECTUS_NOT_OPEN,
    )

    responded = respond_to_prospectus(second["id"], application["id"], alpine_id)
    assert responded["status"] == "PROSPECTUS_RESPONDED"
    assert responded["prospectus_id"] == second["id"]
    assert read_prospectus(second["id"])["responsive_application_count"] == 1

    close_prospectus_submissions(second["id"])
    assert read_application(application["id"])["preliminary_evaluation_score"] == 66.67, (
        "0.30*0 + 0.30*100.00 + 0.20*100.0 + 0.20*83.33"
    )

    awarded = award_prospectus(second["id"], current_use_area_version(area_id))
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_application_id"] == application["id"]

    winner = read_application(application["id"])
    assert winner["status"] == "AWARDED"
    assert winner["final_evaluation_score"] == 66.67
    assert winner["final_evaluation_score"] >= 60.0, "the defaulted qualifying bar"

    validate_error(
        api_client.close_prospectus_submissions(second["id"], SPECIALIST),
        ApiErrorId.ERR_PROSPECTUS_NOT_OPEN,
    )


def test_a_sibling_screen_staleness_the_award_token_and_the_refreshed_one_works():
    """PRD §2.6: "Awarding a solicitation must carry `expected_use_area_version`, a non-optional
    field holding the client's last observed `version` of the governing `UseArea`. If it does not
    equal that area's current `version` — because a different solicitation in the same area was
    awarded, or because a sibling permit was issued and moved the area's day counts — the award is
    rejected with `ERR_STALE_USE_AREA_VERSION` (HTTP 412)."
    PRD §3.2: "The `version` of the screened application, the use area, the governing assessment
    and every re-routed sibling all advance."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Corner/complexity_layers/award_rejects_a_stale_use_area_token_and_accepts_the_refreshed_one
    """
    context = setup_queued_application(requested_service_days=250)
    area_id = context["use_area"]["id"]
    alpine_id = context["outfitter"]["id"]
    application = context["application"]
    create_qualified_guide(alpine_id, full_name="Rita Long", seasons_experience=0)

    prospectus = create_prospectus(
        area_id, context["needs_assessment"]["id"], offered_service_days=300,
        submission_deadline_date="2027-03-31",
    )
    respond_to_prospectus(prospectus["id"], application["id"], alpine_id)
    close_prospectus_submissions(prospectus["id"])
    stale_token = current_use_area_version(area_id)

    sibling = create_application(alpine_id, area_id, requested_service_days=50)
    submit_application(sibling["id"], alpine_id)
    screen_application(sibling["id"])
    assert current_use_area_version(area_id) > stale_token, (
        "a screen on an unrelated sibling advances the parent area's token"
    )

    error = validate_error(
        api_client.award_prospectus(
            prospectus["id"], {"expected_use_area_version": stale_token}, OFFICER
        ),
        ApiErrorId.ERR_STALE_USE_AREA_VERSION,
        412,
    )
    assert error["error_id"] == ApiErrorId.ERR_STALE_USE_AREA_VERSION.value

    unmoved = read_prospectus(prospectus["id"])
    assert unmoved["status"] == "EVALUATING"
    assert unmoved["awarded_application_id"] is None
    assert read_application(application["id"])["status"] == "PROSPECTUS_RESPONDED"

    refreshed = current_use_area_version(area_id)
    awarded = award_prospectus(prospectus["id"], refreshed)
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_application_id"] == application["id"]
    winner = read_application(application["id"])
    assert winner["status"] == "AWARDED"
    assert winner["final_evaluation_score"] == 66.67


def test_an_exact_tie_is_broken_by_created_at_and_never_by_response_order():
    """PRD §3.3: "Otherwise the pool is ranked by `final_evaluation_score` from highest to lowest,
    and an exact tie at two decimal places is broken in favour of the application with the earlier
    `created_at`. The record `id` is never consulted; `created_at` ascending is the only fallback
    ordering. The first row after ranking wins."
    PRD §3.3: "moves every other response `PROSPECTUS_RESPONDED → DENIED` with
    `denial_reason_code` set to the literal `NOT_SELECTED`."
    PRD §3.2: "listable oldest-first with filters that reach every reference an application
    carries: `outfitter_id`, `use_area_id`, `prospectus_id`, `predecessor_permit_id`, `status` and
    `season_year`"

    Design: Corner/complexity_layers/award_tie_is_broken_by_created_at_ascending
    """
    context = setup_queued_application(requested_service_days=250)
    area_id = context["use_area"]["id"]
    alpine_id = context["outfitter"]["id"]
    earlier = context["application"]
    create_qualified_guide(alpine_id, full_name="Rita Long", seasons_experience=0)

    later = create_screened_application(alpine_id, area_id, requested_service_days=250)
    assert later["routing_decision"] == "PROSPECTUS"

    prospectus = create_prospectus(
        area_id, context["needs_assessment"]["id"], offered_service_days=300,
        submission_deadline_date="2027-03-31",
    )
    respond_to_prospectus(prospectus["id"], later["id"], alpine_id)
    respond_to_prospectus(prospectus["id"], earlier["id"], alpine_id)
    close_prospectus_submissions(prospectus["id"])

    awarded = award_prospectus(prospectus["id"], current_use_area_version(area_id))
    winner = read_application(earlier["id"])
    loser = read_application(later["id"])

    assert winner["final_evaluation_score"] == loser["final_evaluation_score"] == 66.67, (
        "identical experience, roster, assurance and need-match terms leave the pool tied"
    )
    assert awarded["awarded_application_id"] == earlier["id"], (
        "the earlier-created application wins although it responded second"
    )
    assert winner["status"] == "AWARDED"
    assert loser["status"] == "DENIED"
    assert loser["denial_reason_code"] == "NOT_SELECTED"

    rows, meta = validate_paginated(
        api_client.list_permit_applications(
            SPECIALIST, params={"prospectus_id": prospectus["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [earlier["id"], later["id"]], (
        "the listing walks created_at ascending, the same order the selector ranked in"
    )
