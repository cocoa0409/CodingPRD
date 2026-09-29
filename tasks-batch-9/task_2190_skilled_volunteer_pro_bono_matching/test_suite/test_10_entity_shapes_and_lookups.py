"""Entity shapes and lookups: what a freshly created row reports, what a list envelope carries,
and which vocabulary a path or body reference answers with when it resolves to nothing."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_cycle,
    create_partner,
    create_vetted_volunteer,
    deliverable_payload,
    deliverable_scores_payload,
    make_partner_contact_headers,
    make_program_manager_headers,
    make_quality_reviewer_headers,
    make_scoping_specialist_headers,
    make_volunteer_headers,
    partner_org_payload,
    project_request_payload,
    scope_definition_payload,
    setup_draft_request,
    setup_offer,
    validate_error,
    validate_paginated,
    validate_success,
    volunteer_payload,
)

NONEXISTENT_ID = "00000000-0000-4000-8000-000000000000"
STRANGER_ID = "00000000-0000-4000-8000-000000000001"

MID_BUDGET = 3000000.00
MICRO_BUDGET = 90000.00


# ---------------------------------------------------------------------------
# Creation shapes: derived figures and seeded defaults
# ---------------------------------------------------------------------------
def test_01_enrolling_a_mid_budget_partner_derives_its_capacity_ceiling(api):
    """PRD §3.1: "The partner's `capacity_class` is `MICRO` for a budget below 250000.00,
    `SMALL` from 250000.00 up to but not including 2000000.00, `MID` from 2000000.00 up to but
    not including 10000000.00, and `LARGE` at 10000000.00 and above — each band floor is
    inclusive and each ceiling exclusive."
    PRD §3.1: "A newly registered partner starts with `status` `ACTIVE`, a null
    `probation_reason`, a null `suspended_at`, a null `satisfaction_index`, a
    `satisfaction_sample_size` of 0 and an `open_engagement_count` of 0."

    Design: Corner/entities/create_partner_org_derives_capacity_class_and_seeds_defaults
    """
    pm = make_program_manager_headers()

    partner = validate_success(
        api_client.create_partner_org(
            partner_org_payload(sector="EDUCATION", annual_budget_usd=MID_BUDGET), pm
        ),
        201,
    )

    assert partner["capacity_class"] == "MID", (
        f"Expected capacity_class MID for a 3000000.00 budget, got "
        f"{partner['capacity_class']}"
    )
    assert partner["max_concurrent_engagements"] == 4, (
        f"Expected max_concurrent_engagements 4, got "
        f"{partner['max_concurrent_engagements']}"
    )
    assert partner["open_engagement_count"] == 0, (
        f"Expected open_engagement_count 0, got {partner['open_engagement_count']}"
    )
    assert partner["status"] == "ACTIVE", (
        f"Expected status ACTIVE, got {partner['status']}"
    )
    assert partner["probation_reason"] is None, (
        f"Expected a null probation_reason, got {partner['probation_reason']}"
    )
    assert partner["suspended_at"] is None, (
        f"Expected a null suspended_at, got {partner['suspended_at']}"
    )
    assert partner["satisfaction_index"] is None, (
        f"Expected a null satisfaction_index rather than 0.00, got "
        f"{partner['satisfaction_index']}"
    )
    assert partner["satisfaction_sample_size"] == 0, (
        f"Expected satisfaction_sample_size 0, got {partner['satisfaction_sample_size']}"
    )
    assert partner["version"] == 1, (
        f"Expected version 1 on creation, got {partner['version']}"
    )


def test_02_reading_a_micro_partner_back_reports_its_own_derived_ceiling(api):
    """PRD §3.1: "The class implies the partner's `max_concurrent_engagements` ceiling
    directly: one for `MICRO`, two for `SMALL`, four for `MID` and six for `LARGE`."
    PRD §3.1: "These two derivations are re-evaluated on registration and whenever a read
    surfaces the class, so they never drift from the budget on file."

    Design: Corner/entities/get_partner_org_returns_stored_and_derived_fields
    """
    pm = make_program_manager_headers()
    created = validate_success(
        api_client.create_partner_org(
            partner_org_payload(
                name="Harbor Arts Collective",
                sector="ARTS",
                annual_budget_usd=MICRO_BUDGET,
            ),
            pm,
        ),
        201,
    )

    partner = validate_success(
        api_client.get_partner_org(created["id"], make_scoping_specialist_headers())
    )

    assert partner["id"] == created["id"], (
        f"Expected the same row back, got {partner['id']} against {created['id']}"
    )
    assert partner["name"] == "Harbor Arts Collective", (
        f"Expected name Harbor Arts Collective, got {partner['name']}"
    )
    assert partner["sector"] == "ARTS", (
        f"Expected sector ARTS, got {partner['sector']}"
    )
    assert partner["capacity_class"] == "MICRO", (
        f"Expected capacity_class MICRO for a 90000.00 budget, got "
        f"{partner['capacity_class']}"
    )
    assert partner["max_concurrent_engagements"] == 1, (
        f"Expected max_concurrent_engagements 1, got "
        f"{partner['max_concurrent_engagements']}"
    )


def test_03_filing_a_request_without_an_urgency_lands_on_routine(api):
    """PRD §3.3: "An `urgency` may also be supplied — `ROUTINE`, `ELEVATED` or `CRITICAL` — and
    defaults to `ROUTINE` when omitted; urgency later drives both the offer's time-to-live and
    the weighting inside the matching score."
    PRD §3.3: "The request is created in `status` `DRAFT` with `rescope_count` 0,
    `failed_match_rounds` 0, `active_scope_revision_no` 0 and a null `closed_at`."

    Design: Corner/entities/create_project_request_omitting_urgency_applies_routine_default
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm)
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    payload = project_request_payload(partner["id"], cycle["id"])
    payload.pop("urgency")

    request = validate_success(
        api_client.create_project_request(
            payload, make_partner_contact_headers(partner["id"])
        ),
        201,
    )

    assert request["urgency"] == "ROUTINE", (
        f"Expected the omitted urgency to default to ROUTINE, got {request['urgency']}"
    )
    assert request["status"] == "DRAFT", (
        f"Expected status DRAFT, got {request['status']}"
    )
    assert request["rescope_count"] == 0, (
        f"Expected rescope_count 0, got {request['rescope_count']}"
    )
    assert request["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds 0, got {request['failed_match_rounds']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0, got "
        f"{request['active_scope_revision_no']}"
    )
    assert request["closed_at"] is None, (
        f"Expected a null closed_at, got {request['closed_at']}"
    )


def _scoping_request():
    """A request moved to SCOPING with no revision drafted against it yet."""
    world = setup_draft_request()
    world["request"] = validate_success(
        api_client.submit_for_scoping(
            world["request"]["id"], world["partner_headers"]
        )
    )
    return world


def test_04_the_first_scope_revision_numbers_itself_one_and_records_its_author(api):
    """PRD §3.3: "The new row is created in `status` `DRAFT`; its `revision_no` is one greater
    than the highest `revision_no` among its siblings on the same request, so the first is 1;
    its `authored_by_user_id` records the drafting specialist's own `X-User-ID`, which is the
    value the segregation-of-duties barrier later reads; its `deliverable_count` and
    `deliverable_weight_total_pct` both start at 0."
    PRD §3.3: "An optional `supersedes_scope_id` names the prior revision this one replaces and
    is null on the first revision of a request."

    Design: Corner/entities/first_scope_revision_computes_revision_no_one_and_records_author
    """
    world = _scoping_request()

    scope = validate_success(
        api_client.create_scope_definition(
            world["request"]["id"],
            scope_definition_payload(world["request"]["version"]),
            world["spec_headers"],
        ),
        201,
    )

    assert scope["revision_no"] == 1, (
        f"Expected revision_no 1, got {scope['revision_no']}"
    )
    assert scope["supersedes_scope_id"] is None, (
        f"Expected a null supersedes_scope_id, got {scope['supersedes_scope_id']}"
    )
    assert scope["authored_by_user_id"] == world["spec_user_id"], (
        f"Expected authored_by_user_id {world['spec_user_id']}, got "
        f"{scope['authored_by_user_id']}"
    )
    assert scope["status"] == "DRAFT", (
        f"Expected status DRAFT, got {scope['status']}"
    )
    assert scope["deliverable_count"] == 0, (
        f"Expected deliverable_count 0, got {scope['deliverable_count']}"
    )
    assert scope["deliverable_weight_total_pct"] == pytest.approx(0.00, abs=0.01), (
        f"Expected deliverable_weight_total_pct 0, got "
        f"{scope['deliverable_weight_total_pct']}"
    )
    assert scope["approved_at"] is None, (
        f"Expected a null approved_at, got {scope['approved_at']}"
    )
    assert scope["approved_by_user_id"] is None, (
        f"Expected a null approved_by_user_id, got {scope['approved_by_user_id']}"
    )


def test_05_a_deliverable_carries_no_version_and_no_modification_stamp(api):
    """PRD §2.4: "Five resource kinds are deliberately lighter and carry only `id` and
    `created_at` — they have no `updated_at` field and no `version` field at all, and callers
    must not expect either in their payloads: deliverables, skill profiles, availability
    windows, time logs and satisfaction surveys — `Deliverable`, `SkillProfile`,
    `AvailabilityWindow`, `TimeLog` and `SatisfactionSurvey`."
    PRD §3.3: "Each deliverable begins with `review_status` `PENDING`, a null `review_score` and
    a null `waived_reason`; the reasons a deliverable can later be excluded from scoring are
    `DESCOPED_BY_CHANGE` and `PARTNER_WITHDRAWN`, and `waived_reason` stays null unless
    `review_status` is `WAIVED`."

    Design: Corner/entities/deliverable_is_immutable_entity_without_version_field
    """
    world = _scoping_request()
    scope = validate_success(
        api_client.create_scope_definition(
            world["request"]["id"],
            scope_definition_payload(world["request"]["version"]),
            world["spec_headers"],
        ),
        201,
    )

    deliverable = validate_success(
        api_client.create_deliverable(
            scope["id"],
            deliverable_payload(weight_pct=60.00, hours_estimate=24.00),
            world["spec_headers"],
        ),
        201,
    )

    assert deliverable.get("id"), f"Expected an id on the row, got {deliverable}"
    assert deliverable.get("created_at"), (
        f"Expected a created_at on the row, got {deliverable}"
    )
    assert "version" not in deliverable, (
        f"A deliverable must carry no version field, got {deliverable.get('version')}"
    )
    assert "updated_at" not in deliverable, (
        f"A deliverable must carry no updated_at field, got "
        f"{deliverable.get('updated_at')}"
    )
    assert deliverable["review_status"] == "PENDING", (
        f"Expected review_status PENDING, got {deliverable['review_status']}"
    )
    assert deliverable["review_score"] is None, (
        f"Expected a null review_score, got {deliverable['review_score']}"
    )
    assert deliverable["waived_reason"] is None, (
        f"Expected a null waived_reason, got {deliverable['waived_reason']}"
    )


# ---------------------------------------------------------------------------
# Body schema: required fields and closed enumerations
# ---------------------------------------------------------------------------
def test_06_enrolling_a_volunteer_without_a_seniority_is_refused(api):
    """PRD §3.2: "Volunteers are enrolled by a `ProgramManager` with a `full_name` of 1 to 120
    characters, a unique `email`, a self-declared `professional_rate_usd_per_hour` that must be
    above zero and no greater than 2000.00, a `seniority` of `ASSOCIATE`, `SENIOR`, `PRINCIPAL`
    or `PARTNER`, and a `weekly_hours_cap` between 1 and 40 hours."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/create_volunteer_missing_required_seniority_is_rejected
    """
    payload = volunteer_payload(professional_rate_usd_per_hour=200.00, weekly_hours_cap=20)
    payload.pop("seniority")

    response = api_client.create_volunteer(payload, make_program_manager_headers())

    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)


def test_07_enrolling_a_partner_in_an_undeclared_sector_is_refused(api):
    """PRD §3.1: "A `ProgramManager` enrols a nonprofit partner by supplying its legal `name`
    (1 to 160 characters, required), a `contact_email` that must be unique across all partners,
    a mission `sector` drawn from `HEALTH`, `EDUCATION`, `HOUSING`, `ENVIRONMENT`, `ARTS` and
    `CIVIC`, and a self-reported `annual_budget_usd` of at least zero carried to two decimals."
    PRD §2.12: "The request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared ranges,
    datetimes ISO 8601 UTC — on every write endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/entities/create_partner_org_with_invalid_enum_sector_is_rejected
    """
    response = api_client.create_partner_org(
        partner_org_payload(sector="SPORTS", annual_budget_usd=MID_BUDGET),
        make_program_manager_headers(),
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)


# ---------------------------------------------------------------------------
# List envelopes
# ---------------------------------------------------------------------------
def test_08_a_narrow_page_still_reports_the_whole_filtered_count(api):
    """PRD §2.3: "Unless a specific endpoint's description in §4 states another ordering, list
    results are sorted by `created_at` ascending, and the `meta` block of a list response
    carries `limit`, `offset`, `total_count` (the number of rows matching the filter before
    pagination) and `has_more` (true when rows remain beyond the current page)."
    PRD §2.3: "Project requests may be narrowed by `partner_org_id`, `cycle_id` and `status`;
    scope revisions by `project_request_id`, `supersedes_scope_id` and `status` — supplying
    `supersedes_scope_id` walks the revision chain forward from any revision; match offers by
    `project_request_id`, `volunteer_id`, `scope_definition_id`, `availability_window_id` and
    `status`; engagements by `match_offer_id`, `project_request_id`, `volunteer_id`,
    `scope_definition_id`, `cycle_id`, `availability_window_id` and `work_status`."

    Design: Corner/entities/list_project_requests_returns_pagination_envelope
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm)
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    contact = make_partner_contact_headers(partner["id"])
    for title, discipline, skill in (
        ("Annual audit readiness", "ACCOUNTING", "TAX_LAW"),
        ("Donor CRM migration", "TECHNOLOGY", "CRM_ADMIN"),
    ):
        validate_success(
            api_client.create_project_request(
                project_request_payload(
                    partner["id"],
                    cycle["id"],
                    title=title,
                    discipline=discipline,
                    required_skill_code=skill,
                ),
                contact,
            ),
            201,
        )

    rows, meta = validate_paginated(
        api_client.list_project_requests(
            pm, params={"partner_org_id": partner["id"], "limit": 1, "offset": 0}
        )
    )

    assert meta["total_count"] == 2, (
        f"Expected total_count 2 for the whole filtered set, got {meta['total_count']}"
    )
    assert meta["limit"] == 1, f"Expected limit 1, got {meta['limit']}"
    assert meta["offset"] == 0, f"Expected offset 0, got {meta['offset']}"
    assert meta["has_more"] is True, (
        f"Expected has_more true with a row beyond the page, got {meta['has_more']}"
    )
    assert len(rows) == 1, f"Expected exactly one row on the page, got {len(rows)}"


def test_09_a_limit_of_zero_is_refused_rather_than_coerced(api):
    """PRD §2.3: "Both must be integers; a `limit` below 1 or above 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."
    PRD §2.12: "Pagination parameters are integers with `limit` between 1 and 100 inclusive and
    `offset` at least 0 — on `GET /project-requests`, `GET /scope-definitions`,
    `GET /match-offers` and `GET /engagements` — otherwise `ERR_INVALID_PAGINATION` (400)."

    Design: Corner/entities/list_engagements_with_limit_zero_returns_invalid_pagination
    """
    response = api_client.list_engagements(
        make_program_manager_headers(), params={"limit": 0, "offset": 0}
    )

    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION, expected_status=400)


# ---------------------------------------------------------------------------
# Path existence: one vocabulary per addressed entity
# ---------------------------------------------------------------------------
def test_10_reading_an_unknown_partner_answers_partner_org_not_found(api):
    """PRD §2.12: "The `PartnerOrg` named by a path segment exists — checked on
    `GET /partner-orgs/{id}`, `GET /partner-orgs/{id}/summary`,
    `GET /partner-orgs/{id}/satisfaction-surveys` and `PATCH /partner-orgs/{id}/status` —
    otherwise `ERR_PARTNER_ORG_NOT_FOUND` (404)."

    Design: Corner/entities/get_partner_org_unknown_id_returns_not_found
    """
    response = api_client.get_partner_org(
        NONEXISTENT_ID, make_program_manager_headers()
    )

    validate_error(
        response, ApiErrorId.ERR_PARTNER_ORG_NOT_FOUND, expected_status=404
    )


def test_11_recalculating_an_unknown_cycle_answers_program_cycle_not_found(api):
    """PRD §2.12: "The `ProgramCycle` named by a path segment exists — on
    `GET /program-cycles/{id}` and `POST /program-cycles/{id}/recalculate` — otherwise
    `ERR_PROGRAM_CYCLE_NOT_FOUND` (404)."

    Design: Corner/entities/recalculate_unknown_cycle_returns_not_found
    """
    response = api_client.recalculate_program_cycle(
        NONEXISTENT_ID, make_program_manager_headers()
    )

    validate_error(
        response, ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND, expected_status=404
    )


def test_12_matching_an_unknown_request_answers_project_request_not_found(api):
    """PRD §2.12: "The `ProjectRequest` named by a path segment exists — on
    `GET /project-requests/{id}`, `POST /project-requests/{id}/submit-for-scoping`,
    `POST /project-requests/{id}/scope-definitions`, `POST /project-requests/{id}/match`,
    `POST /project-requests/{id}/rescope` and `POST /project-requests/{id}/abandon` — otherwise
    `ERR_PROJECT_REQUEST_NOT_FOUND` (404)."

    Design: Corner/entities/match_unknown_project_request_returns_not_found
    """
    response = api_client.match_project_request(
        NONEXISTENT_ID, make_scoping_specialist_headers()
    )

    validate_error(
        response, ApiErrorId.ERR_PROJECT_REQUEST_NOT_FOUND, expected_status=404
    )


def test_13_adding_a_deliverable_to_an_unknown_revision_answers_scope_not_found(api):
    """PRD §2.12: "The `ScopeDefinition` named by a path segment exists — on
    `GET /scope-definitions/{id}`, `GET /scope-definitions/{id}/deliverables`,
    `POST /scope-definitions/{id}/deliverables` and `POST /scope-definitions/{id}/approve` —
    otherwise `ERR_SCOPE_DEFINITION_NOT_FOUND` (404)."

    Design: Corner/entities/add_deliverable_to_unknown_scope_returns_not_found
    """
    response = api_client.create_deliverable(
        NONEXISTENT_ID, deliverable_payload(), make_scoping_specialist_headers()
    )

    validate_error(
        response, ApiErrorId.ERR_SCOPE_DEFINITION_NOT_FOUND, expected_status=404
    )


def test_14_vetting_an_unknown_volunteer_answers_volunteer_not_found(api):
    """PRD §2.12: "The `Volunteer` named by a path segment exists — on `GET /volunteers/{id}`,
    `GET /volunteers/{id}/skill-profiles`, `GET /volunteers/{id}/availability-windows`,
    `POST /volunteers/{id}/vet`, `PATCH /volunteers/{id}/status`,
    `POST /volunteers/{id}/skill-profiles` and `POST /volunteers/{id}/availability-windows` —
    otherwise `ERR_VOLUNTEER_NOT_FOUND` (404)."

    Design: Corner/entities/vet_unknown_volunteer_returns_not_found
    """
    response = api_client.vet_volunteer(
        NONEXISTENT_ID,
        {"verify_skill_codes": ["TAX_LAW"]},
        make_program_manager_headers(),
    )

    validate_error(response, ApiErrorId.ERR_VOLUNTEER_NOT_FOUND, expected_status=404)


def test_15_accepting_an_unknown_offer_answers_match_offer_not_found(api):
    """PRD §2.12: "The `MatchOffer` named by a path segment exists — on
    `GET /match-offers/{id}`, `POST /match-offers/{id}/accept`,
    `POST /match-offers/{id}/decline` and `POST /match-offers/{id}/withdraw` — otherwise
    `ERR_MATCH_OFFER_NOT_FOUND` (404)."

    Design: Corner/entities/accept_unknown_match_offer_returns_not_found
    """
    response = api_client.accept_match_offer(
        NONEXISTENT_ID, make_volunteer_headers(STRANGER_ID)
    )

    validate_error(response, ApiErrorId.ERR_MATCH_OFFER_NOT_FOUND, expected_status=404)


def test_16_reading_an_unknown_engagement_answers_engagement_not_found(api):
    """PRD §2.12: "The `Engagement` named by a path segment exists — on `/engagements/{id}` and
    every sub-path beneath it — otherwise `ERR_ENGAGEMENT_NOT_FOUND` (404)."

    Design: Corner/entities/get_engagement_unknown_id_returns_not_found
    """
    response = api_client.get_engagement(
        NONEXISTENT_ID, make_quality_reviewer_headers()
    )

    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND, expected_status=404)


def test_17_sending_an_unknown_agreement_answers_agreement_not_found(api):
    """PRD §2.12: "The `EngagementAgreement` named by a path segment exists — on
    `POST /agreements/{id}/send`, `POST /agreements/{id}/counter`,
    `POST /agreements/{id}/execute` and `POST /agreements/{id}/void` — otherwise
    `ERR_AGREEMENT_NOT_FOUND` (404)."

    Design: Corner/entities/send_unknown_agreement_returns_not_found
    """
    response = api_client.send_agreement(
        NONEXISTENT_ID, make_program_manager_headers()
    )

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_FOUND, expected_status=404)


def test_18_holding_an_unknown_milestone_answers_milestone_not_found(api):
    """PRD §2.12: "The `Milestone` named by a path segment exists — on
    `GET /milestones/{id}`, `GET /milestones/{id}/time-logs` and `POST /milestones/{id}/hold` —
    otherwise `ERR_MILESTONE_NOT_FOUND` (404)."

    Design: Corner/entities/hold_unknown_milestone_returns_not_found
    """
    response = api_client.hold_milestone(
        NONEXISTENT_ID,
        {"reported_cumulative_hours": 8.00},
        make_program_manager_headers(),
    )

    validate_error(response, ApiErrorId.ERR_MILESTONE_NOT_FOUND, expected_status=404)


def test_19_deciding_an_unknown_change_request_answers_scope_change_not_found(api):
    """PRD §2.12: "The `ScopeChangeRequest` named by a path segment exists — on
    `POST /scope-change-requests/{id}/decide` — otherwise `ERR_SCOPE_CHANGE_NOT_FOUND` (404)."

    Design: Corner/entities/decide_unknown_scope_change_returns_not_found
    """
    response = api_client.decide_scope_change_request(
        NONEXISTENT_ID, {"decision": "APPROVE"}, make_program_manager_headers()
    )

    validate_error(
        response, ApiErrorId.ERR_SCOPE_CHANGE_NOT_FOUND, expected_status=404
    )


def test_20_scoring_an_unknown_review_answers_quality_review_not_found(api):
    """PRD §2.12: "The `QualityReview` named by a path segment exists — on
    `POST /quality-reviews/{id}/score` and `POST /quality-reviews/{id}/decide` — otherwise
    `ERR_QUALITY_REVIEW_NOT_FOUND` (404)."

    Design: Corner/entities/score_unknown_quality_review_returns_not_found
    """
    response = api_client.score_quality_review(
        NONEXISTENT_ID,
        deliverable_scores_payload({STRANGER_ID: 4}),
        make_quality_reviewer_headers(),
    )

    validate_error(
        response, ApiErrorId.ERR_QUALITY_REVIEW_NOT_FOUND, expected_status=404
    )


# ---------------------------------------------------------------------------
# Body foreign keys: two references, two vocabularies
# ---------------------------------------------------------------------------
def test_21_an_unresolvable_partner_reference_answers_partner_org_not_found(api):
    """PRD §2.12: "Every foreign key supplied in the request body resolves, as described in
    §2.11: on `POST /project-requests` an unresolvable `partner_org_id` yields
    `ERR_PARTNER_ORG_NOT_FOUND` (404) and an unresolvable `cycle_id` yields
    `ERR_PROGRAM_CYCLE_NOT_FOUND` (404), and on `POST /quality-reviews/{id}/score` a
    `deliverable_id` inside `deliverable_scores` that names no deliverable of the pinned scope
    revision yields `ERR_DELIVERABLE_NOT_FOUND` (404)."

    Design: Corner/entities/create_project_request_with_unknown_partner_org_returns_not_found
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm)

    response = api_client.create_project_request(
        project_request_payload(NONEXISTENT_ID, cycle["id"]),
        make_partner_contact_headers(NONEXISTENT_ID),
    )

    validate_error(
        response, ApiErrorId.ERR_PARTNER_ORG_NOT_FOUND, expected_status=404
    )


def test_22_an_unresolvable_cycle_reference_answers_program_cycle_not_found(api):
    """PRD §2.12: "Every foreign key supplied in the request body resolves, as described in
    §2.11: on `POST /project-requests` an unresolvable `partner_org_id` yields
    `ERR_PARTNER_ORG_NOT_FOUND` (404) and an unresolvable `cycle_id` yields
    `ERR_PROGRAM_CYCLE_NOT_FOUND` (404), and on `POST /quality-reviews/{id}/score` a
    `deliverable_id` inside `deliverable_scores` that names no deliverable of the pinned scope
    revision yields `ERR_DELIVERABLE_NOT_FOUND` (404)."

    Design: Corner/entities/create_project_request_with_unknown_cycle_returns_program_cycle_not_found
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)

    response = api_client.create_project_request(
        project_request_payload(partner["id"], NONEXISTENT_ID),
        make_partner_contact_headers(partner["id"]),
    )

    validate_error(
        response, ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND, expected_status=404
    )


# ---------------------------------------------------------------------------
# Reaching the children
# ---------------------------------------------------------------------------
def test_23_a_volunteers_claims_and_windows_are_reachable_beneath_her_row(api):
    """PRD §2.11: "A child created under a parent takes its parent reference from the resolved
    path segment and never from the body: a milestone, time log, scope change request, review
    round, agreement, valuation record or satisfaction survey created beneath
    `/engagements/{id}` stores that engagement as its `engagement_id`, a deliverable created
    beneath `/scope-definitions/{id}` stores that revision as its `scope_definition_id`, and a
    skill profile or availability window created beneath `/volunteers/{id}` stores that
    volunteer as its `volunteer_id`."
    PRD §3.2: "The window's own ledger fields start at `hours_committed` of 0.00 and
    `hours_remaining` equal to `hours_offered`, and its `status` is derived rather than set:
    `OPEN` while `hours_remaining` is above zero and the clock is still before `ends_at`,
    `EXHAUSTED` once `hours_remaining` reaches exactly zero, and `EXPIRED` once the clock
    reaches or passes `ends_at`."

    Design: Corner/entities/skill_profile_and_window_children_are_reverse_reachable_from_volunteer
    """
    pm = make_program_manager_headers()
    create_cycle(pm)
    volunteer, _skill, _win = create_vetted_volunteer(
        skill_code="TAX_LAW",
        proficiency=4,
        window_overrides={"hours_offered": 200.00},
    )
    spec = make_scoping_specialist_headers()

    windows, _meta = validate_paginated(
        api_client.list_availability_windows(volunteer["id"], spec)
    )

    assert len(windows) == 1, f"Expected exactly one window, got {len(windows)}"
    assert windows[0]["volunteer_id"] == volunteer["id"], (
        f"Expected the window to carry volunteer_id {volunteer['id']}, got "
        f"{windows[0]['volunteer_id']}"
    )
    assert windows[0]["hours_offered"] == pytest.approx(200.00, abs=0.01), (
        f"Expected hours_offered 200.00, got {windows[0]['hours_offered']}"
    )
    assert windows[0]["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected hours_committed 0.00, got {windows[0]['hours_committed']}"
    )
    assert windows[0]["hours_remaining"] == pytest.approx(200.00, abs=0.01), (
        f"Expected hours_remaining 200.00, got {windows[0]['hours_remaining']}"
    )
    assert windows[0]["status"] == "OPEN", (
        f"Expected window status OPEN, got {windows[0]['status']}"
    )

    claims, _claim_meta = validate_paginated(
        api_client.list_skill_profiles(volunteer["id"], spec)
    )
    assert len(claims) == 1, f"Expected exactly one skill claim, got {len(claims)}"
    assert claims[0]["skill_code"] == "TAX_LAW", (
        f"Expected skill_code TAX_LAW, got {claims[0]['skill_code']}"
    )
    assert claims[0]["proficiency"] == 4, (
        f"Expected proficiency 4, got {claims[0]['proficiency']}"
    )
    assert claims[0]["verified"] is True, (
        f"Expected the vetted claim verified, got {claims[0]['verified']}"
    )


def test_24_the_offer_row_joins_request_volunteer_revision_and_window(api):
    """PRD §3.4: "A winning selection writes a match offer in `status` `OFFERED` against the
    request, recording the winning `volunteer_id`, the `scope_definition_id` of the `APPROVED`
    revision pinned at this instant, the `availability_window_id` of the chosen window, and a
    `round_no` equal to the request's `failed_match_rounds` plus one at offer time — so the
    first offer on a request is round 1."
    PRD §2.3: "Filtered list endpoints combine their filter parameters conjunctively."

    Design: Corner/entities/match_offer_junction_links_volunteer_request_scope_and_window
    """
    world = setup_offer()

    rows, _meta = validate_paginated(
        api_client.list_match_offers(
            world["pm_headers"],
            params={
                "availability_window_id": world["window"]["id"],
                "status": "OFFERED",
            },
        )
    )

    assert len(rows) == 1, f"Expected exactly one offer on that window, got {len(rows)}"
    offer = rows[0]
    assert offer["id"] == world["offer"]["id"], (
        f"Expected offer {world['offer']['id']}, got {offer['id']}"
    )
    assert offer["project_request_id"] == world["request"]["id"], (
        f"Expected project_request_id {world['request']['id']}, got "
        f"{offer['project_request_id']}"
    )
    assert offer["volunteer_id"] == world["volunteer"]["id"], (
        f"Expected volunteer_id {world['volunteer']['id']}, got {offer['volunteer_id']}"
    )
    assert offer["scope_definition_id"] == world["scope"]["id"], (
        f"Expected scope_definition_id {world['scope']['id']}, got "
        f"{offer['scope_definition_id']}"
    )
    assert offer["availability_window_id"] == world["window"]["id"], (
        f"Expected availability_window_id {world['window']['id']}, got "
        f"{offer['availability_window_id']}"
    )
    assert offer["round_no"] == 1, (
        f"Expected round_no 1 on the first offer, got {offer['round_no']}"
    )
