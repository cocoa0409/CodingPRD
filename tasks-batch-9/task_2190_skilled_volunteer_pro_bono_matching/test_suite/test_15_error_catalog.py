"""Error catalog: each rejection's trigger, its HTTP status, and — where the
rejection ladder of §2.12 fixes the order — the lower-priority rule it outranks.
"""
from test_helpers import (
    ApiErrorId,
    add_draft_revision,
    api_client,
    availability_window_payload,
    counter_payload,
    create_cycle,
    create_partner,
    create_skill_profile,
    create_vetted_volunteer,
    create_volunteer,
    deliverable_payload,
    deliverable_scores_payload,
    drive_review_to_outcome,
    get_success_data,
    make_partner_contact_headers,
    make_program_manager_headers,
    make_quality_reviewer_headers,
    make_scoping_specialist_headers,
    make_volunteer_headers,
    milestone_payload,
    post_valuation,
    project_request_payload,
    read_agreement,
    read_cycle,
    read_engagement,
    read_request,
    read_scope,
    read_valuation_records,
    set_clock,
    setup_draft_request,
    setup_drafted_agreement,
    setup_in_progress_engagement,
    setup_offer,
    setup_roster,
    setup_scoped_request,
    setup_scoping_request,
    setup_selector_world,
    setup_submitted_engagement,
    skill_profile_payload,
    time_log_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

NONEXISTENT_ID = "00000000-0000-4000-8000-000000000000"
SINGLE_DELIVERABLE = [{"weight_pct": 100.00}]


# ---------------------------------------------------------------------------
# Authentication and authorization outrank everything else
# ---------------------------------------------------------------------------
def test_01_blank_user_id_answers_missing_auth_headers_before_body_validation(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    caller, and `X-User-Role`, naming the caller's role. If either header is absent
    or blank, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) —
    this check runs before any other, on every endpoint including reads." PRD §2.12
    places that check at position 1 and body-schema conformance ("otherwise
    `ERR_VALIDATION` (422)") at position 17.

    Design: Corner/errors/error_missing_auth_headers_beats_validation_on_malformed_body
    """
    partner = create_partner()

    response = api_client.patch_partner_org_status(
        partner["id"],
        {"to_status": "DELETED"},
        {"X-User-ID": "", "X-User-Role": "ProgramManager"},
    )

    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS, expected_status=401)

    after = get_success_data(
        api_client.get_partner_org(partner["id"], make_program_manager_headers())
    )
    assert after["status"] == "ACTIVE", (
        f"Expected the partner to be untouched at ACTIVE, got {after['status']}"
    )


def test_02_unauthorized_role_outranks_the_unknown_volunteer_lookup(api):
    """PRD §2.12: "2. `X-User-Role` is one of the five named roles and is listed
    among the target endpoint's authorized roles, on every endpoint — otherwise
    `ERR_ROLE_NOT_PERMITTED` (403)." and "7. The `Volunteer` named by a path segment
    exists — on ... `PATCH /volunteers/{id}/status` ... — otherwise
    `ERR_VOLUNTEER_NOT_FOUND` (404)." §4 authorizes `PATCH /volunteers/{id}/status`
    for ProgramManager only.

    Design: Corner/errors/error_role_not_permitted_beats_volunteer_not_found
    """
    payload = {"to_status": "PAUSED"}

    forbidden = api_client.patch_volunteer_status(
        NONEXISTENT_ID, payload, make_scoping_specialist_headers()
    )
    validate_error(forbidden, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    permitted_role = api_client.patch_volunteer_status(
        NONEXISTENT_ID, payload, make_program_manager_headers()
    )
    validate_error(
        permitted_role, ApiErrorId.ERR_VOLUNTEER_NOT_FOUND, expected_status=404
    )


# ---------------------------------------------------------------------------
# Resolution failures (positions 3-14) outrank state, schema and quantity rules
# ---------------------------------------------------------------------------
def test_03_project_request_with_two_unresolvable_body_keys_answers_a_404(api):
    """PRD §2.12: "14. Every foreign key supplied in the request body resolves, as
    described in §2.11: on `POST /project-requests` an unresolvable
    `partner_org_id` yields `ERR_PARTNER_ORG_NOT_FOUND` (404) and an unresolvable
    `cycle_id` yields `ERR_PROGRAM_CYCLE_NOT_FOUND` (404)". Both faults sit at the
    same position, so the ladder fixes the status but not which of the two names is
    returned.

    Design: Corner/errors/error_partner_org_not_found_beats_program_cycle_not_found
    """
    create_partner()
    create_cycle()

    response = api_client.create_project_request(
        project_request_payload("org-nope", "cycle-nope"),
        make_partner_contact_headers("org-nope"),
    )

    validate_error_is_one_of(
        response,
        [
            ApiErrorId.ERR_PARTNER_ORG_NOT_FOUND,
            ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND,
        ],
    )
    assert response.status_code == 404, (
        f"Expected HTTP 404 for an unresolvable body key, got {response.status_code}"
    )

    rows, meta = validate_paginated(
        api_client.list_project_requests(make_program_manager_headers())
    )
    assert meta["total_count"] == 0, (
        f"Expected no project request to be created, got {meta['total_count']}"
    )


def test_04_unresolvable_cycle_outranks_enum_and_zero_quantity_faults(api):
    """PRD §2.12: "14. Every foreign key supplied in the request body resolves, as
    described in §2.11: on `POST /project-requests` an unresolvable
    `partner_org_id` yields `ERR_PARTNER_ORG_NOT_FOUND` (404) and an unresolvable
    `cycle_id` yields `ERR_PROGRAM_CYCLE_NOT_FOUND` (404)", ahead of "17. The
    request body conforms to the endpoint's input schema — all required fields
    present, enum values inside their declared sets, numbers inside their declared
    ranges, datetimes ISO 8601 UTC — on every write endpoint, otherwise
    `ERR_VALIDATION` (422)."

    Design: Corner/errors/error_program_cycle_not_found_beats_zero_hours_and_validation
    """
    partner = create_partner()

    response = api_client.create_project_request(
        project_request_payload(
            partner["id"],
            "cycle-nope",
            discipline="BASKET_WEAVING",
            requested_hours=0.0,
        ),
        make_partner_contact_headers(partner["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND, expected_status=404)


def test_05_unknown_request_on_submit_for_scoping_outranks_the_state_check(api):
    """PRD §2.12: "5. The `ProjectRequest` named by a path segment exists — on `GET
    /project-requests/{id}`, `POST /project-requests/{id}/submit-for-scoping`, ...
    — otherwise `ERR_PROJECT_REQUEST_NOT_FOUND` (404)", ahead of "20. The project
    request's `status` is in the from-set of the requested transition — on `POST
    /project-requests/{id}/submit-for-scoping` ... — otherwise
    `ERR_INVALID_REQUEST_STATE` (409)."

    Design: Corner/errors/error_project_request_not_found_beats_invalid_request_state
    """
    w = setup_draft_request()

    response = api_client.submit_for_scoping("req-nope", w["partner_headers"])

    validate_error(response, ApiErrorId.ERR_PROJECT_REQUEST_NOT_FOUND, expected_status=404)

    after = read_request(w)
    assert after["status"] == "DRAFT", (
        f"Expected the real request to stay in DRAFT, got {after['status']}"
    )


def test_06_unknown_revision_on_deliverable_add_outranks_the_weight_rule(api):
    """PRD §2.12: "6. The `ScopeDefinition` named by a path segment exists — on ...
    `POST /scope-definitions/{id}/deliverables` and `POST
    /scope-definitions/{id}/approve` — otherwise `ERR_SCOPE_DEFINITION_NOT_FOUND`
    (404)", ahead of "47. A deliverable's `sequence_no` is unique within its
    revision, and at approval time the revision's `deliverable_weight_total_pct`
    equals exactly 100.00 over non-`WAIVED` deliverables with `deliverable_count`
    of at least 1 — on `POST /scope-definitions/{id}/deliverables` and `POST
    /scope-definitions/{id}/approve` — otherwise
    `ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID` (422)."

    Design: Corner/errors/error_scope_definition_not_found_beats_weight_total_invalid
    """
    response = api_client.create_deliverable(
        "scope-nope",
        deliverable_payload(weight_pct=250.00),
        make_scoping_specialist_headers(),
    )

    validate_error(
        response, ApiErrorId.ERR_SCOPE_DEFINITION_NOT_FOUND, expected_status=404
    )


def test_07_unknown_volunteer_on_skill_claim_outranks_the_ownership_check(api):
    """PRD §2.12: "7. The `Volunteer` named by a path segment exists — on ... `POST
    /volunteers/{id}/skill-profiles` and `POST /volunteers/{id}/availability-windows`
    — otherwise `ERR_VOLUNTEER_NOT_FOUND` (404)", ahead of "15. For the entity-backed
    roles, the caller owns the target resource — `ERR_NOT_RESOURCE_OWNER` (403) — on
    ... `POST /volunteers/{id}/skill-profiles` and `POST
    /volunteers/{id}/availability-windows`."

    Design: Corner/errors/error_volunteer_not_found_beats_not_resource_owner
    """
    volunteer, _, _ = create_vetted_volunteer(window=False)

    response = api_client.create_skill_profile(
        "vol-nope",
        skill_profile_payload(skill_code="NONPROFIT_FINANCE"),
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_VOLUNTEER_NOT_FOUND, expected_status=404)


def test_08_unknown_offer_on_decline_outranks_the_missing_reason_fault(api):
    """PRD §2.12: "8. The `MatchOffer` named by a path segment exists — on `GET
    /match-offers/{id}`, `POST /match-offers/{id}/accept`, `POST
    /match-offers/{id}/decline` and `POST /match-offers/{id}/withdraw` — otherwise
    `ERR_MATCH_OFFER_NOT_FOUND` (404)", ahead of "17. The request body conforms to
    the endpoint's input schema — all required fields present ... on every write
    endpoint, otherwise `ERR_VALIDATION` (422)."

    Design: Corner/errors/error_match_offer_not_found_beats_validation_on_missing_reason
    """
    volunteer, _, _ = create_vetted_volunteer(window=False)

    response = api_client.decline_match_offer(
        "offer-nope", {}, make_volunteer_headers(volunteer["id"])
    )

    validate_error(response, ApiErrorId.ERR_MATCH_OFFER_NOT_FOUND, expected_status=404)


def test_09_unknown_engagement_on_time_log_outranks_the_zero_hours_rule(api):
    """PRD §2.12: "9. The `Engagement` named by a path segment exists — on
    `/engagements/{id}` and every sub-path beneath it — otherwise
    `ERR_ENGAGEMENT_NOT_FOUND` (404)", ahead of "19. Quantities that must be strictly
    positive are strictly positive — a time log's `hours`, a revision's
    `estimated_hours`, a window's `hours_offered` and a deliverable's `weight_pct` —
    on `POST /engagements/{id}/time-logs` ... A value of exactly 0 is refused here
    with `ERR_ZERO_HOURS_NOT_ALLOWED` (422), before any capacity arithmetic runs."

    Design: Corner/errors/error_engagement_not_found_beats_zero_hours_not_allowed
    """
    volunteer, _, _ = create_vetted_volunteer(window=False)

    response = api_client.create_time_log(
        "eng-nope",
        time_log_payload(hours=0.0),
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND, expected_status=404)


def test_10_sending_an_unknown_agreement_answers_agreement_not_found(api):
    """PRD §2.12: "10. The `EngagementAgreement` named by a path segment exists — on
    `POST /agreements/{id}/send`, `POST /agreements/{id}/counter`, `POST
    /agreements/{id}/execute` and `POST /agreements/{id}/void` — otherwise
    `ERR_AGREEMENT_NOT_FOUND` (404)."

    Design: Corner/errors/error_agreement_not_found_on_send_of_unknown_id
    """
    response = api_client.send_agreement("agr-nope", make_program_manager_headers())

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_FOUND, expected_status=404)


def test_11_unknown_milestone_outranks_the_negative_hours_fault(api):
    """PRD §2.12: "11. The `Milestone` named by a path segment exists — on `GET
    /milestones/{id}`, `GET /milestones/{id}/time-logs` and `POST
    /milestones/{id}/hold` — otherwise `ERR_MILESTONE_NOT_FOUND` (404)", ahead of
    "17. The request body conforms to the endpoint's input schema — all required
    fields present, enum values inside their declared sets, numbers inside their
    declared ranges, datetimes ISO 8601 UTC — on every write endpoint, otherwise
    `ERR_VALIDATION` (422)."

    Design: Corner/errors/error_milestone_not_found_beats_validation_on_negative_hours
    """
    pm = make_program_manager_headers()

    hold = api_client.hold_milestone("ms-nope", {"reported_cumulative_hours": -5.0}, pm)
    validate_error(hold, ApiErrorId.ERR_MILESTONE_NOT_FOUND, expected_status=404)

    read = api_client.get_milestone("ms-nope", pm)
    validate_error(read, ApiErrorId.ERR_MILESTONE_NOT_FOUND, expected_status=404)


def test_12_unknown_change_request_outranks_the_decision_enum_fault(api):
    """PRD §2.12: "12. The `ScopeChangeRequest` named by a path segment exists — on
    `POST /scope-change-requests/{id}/decide` — otherwise
    `ERR_SCOPE_CHANGE_NOT_FOUND` (404)", ahead of "17. The request body conforms to
    the endpoint's input schema — all required fields present, enum values inside
    their declared sets ... otherwise `ERR_VALIDATION` (422)."

    Design: Corner/errors/error_scope_change_not_found_beats_decision_enum_validation
    """
    response = api_client.decide_scope_change_request(
        "scr-nope", {"decision": "MAYBE"}, make_program_manager_headers()
    )

    validate_error(response, ApiErrorId.ERR_SCOPE_CHANGE_NOT_FOUND, expected_status=404)


def test_13_unknown_review_on_score_outranks_the_empty_score_set(api):
    """PRD §2.12: "13. The `QualityReview` named by a path segment exists — on `POST
    /quality-reviews/{id}/score` and `POST /quality-reviews/{id}/decide` — otherwise
    `ERR_QUALITY_REVIEW_NOT_FOUND` (404)", ahead of "48. The `deliverable_scores`
    set is exactly the set of non-`WAIVED` deliverables on the pinned revision,
    non-empty, with no extras and no omissions — on `POST
    /quality-reviews/{id}/score` — otherwise `ERR_DELIVERABLE_SET_MISMATCH` (422)."

    Design: Corner/errors/error_quality_review_not_found_beats_deliverable_set_mismatch
    """
    response = api_client.score_quality_review(
        "qr-nope", {"deliverable_scores": []}, make_quality_reviewer_headers()
    )

    validate_error(
        response, ApiErrorId.ERR_QUALITY_REVIEW_NOT_FOUND, expected_status=404
    )


def test_14_an_unknown_deliverable_in_a_score_payload_outranks_the_set_mismatch(api):
    """PRD §3.8: "A set that does not match is refused with
    `ERR_DELIVERABLE_SET_MISMATCH`, while an entry naming a deliverable that does
    not belong to the pinned revision at all is refused with
    `ERR_DELIVERABLE_NOT_FOUND`." PRD §2.12 places that body-key resolution at
    position 14 and the set-equality check at position 48.

    Design: Corner/errors/error_deliverable_not_found_beats_set_mismatch_on_score
    """
    w = setup_submitted_engagement(deliverables=SINGLE_DELIVERABLE)
    review = get_success_data(
        api_client.create_quality_review(w["engagement"]["id"], w["reviewer_headers"])
    )

    response = api_client.score_quality_review(
        review["id"],
        deliverable_scores_payload({w["deliverables"][0]["id"]: 5, NONEXISTENT_ID: 4}),
        w["reviewer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DELIVERABLE_NOT_FOUND, expected_status=404)

    rows, _ = validate_paginated(
        api_client.list_quality_reviews(w["engagement"]["id"], w["pm_headers"])
    )
    assert len(rows) == 1, f"Expected exactly one review round, got {len(rows)}"
    assert rows[0]["status"] == "OPEN", (
        f"Expected the review to stay OPEN, got {rows[0]['status']}"
    )
    assert rows[0]["weighted_score"] is None, (
        f"Expected a null weighted_score, got {rows[0]['weighted_score']}"
    )


# ---------------------------------------------------------------------------
# Schema, quantity and geometry rules on the roster and the read endpoints
# ---------------------------------------------------------------------------
def test_15_a_bad_window_kind_outranks_the_zero_hour_budget(api):
    """PRD §2.12: "17. The request body conforms to the endpoint's input schema — all
    required fields present, enum values inside their declared sets, numbers inside
    their declared ranges, datetimes ISO 8601 UTC — on every write endpoint,
    otherwise `ERR_VALIDATION` (422)", ahead of "19. Quantities that must be strictly
    positive are strictly positive — ... a window's `hours_offered` ... A value of
    exactly 0 is refused here with `ERR_ZERO_HOURS_NOT_ALLOWED` (422), before any
    capacity arithmetic runs."

    Design: Corner/errors/error_validation_beats_zero_hours_on_availability_window
    """
    create_cycle()
    volunteer, _, _ = create_vetted_volunteer(window=False)
    headers = make_volunteer_headers(volunteer["id"])

    response = api_client.create_availability_window(
        volunteer["id"],
        availability_window_payload(window_kind="MAYBE", hours_offered=0.0),
        headers,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION, expected_status=422)

    _, meta = validate_paginated(
        api_client.list_availability_windows(volunteer["id"], headers)
    )
    assert meta["total_count"] == 0, (
        f"Expected no window to be published, got {meta['total_count']}"
    )


def test_16_a_zero_hour_budget_outranks_the_cycle_containment_rule(api):
    """PRD §2.12: "19. Quantities that must be strictly positive are strictly
    positive — ... a window's `hours_offered` ... A value of exactly 0 is refused here
    with `ERR_ZERO_HOURS_NOT_ALLOWED` (422), before any capacity arithmetic runs",
    ahead of "39. A new availability window has `ends_at` strictly after `starts_at`
    and its whole half-open interval lies inside some program cycle's half-open
    interval — on `POST /volunteers/{id}/availability-windows` — otherwise
    `ERR_WINDOW_OUTSIDE_CYCLE` (422)."

    Design: Corner/errors/error_zero_hours_beats_window_outside_cycle
    """
    create_cycle(starts_at="2026-08-01T00:00:00Z", ends_at="2026-12-01T00:00:00Z")
    volunteer, _, _ = create_vetted_volunteer(window=False)
    headers = make_volunteer_headers(volunteer["id"])

    response = api_client.create_availability_window(
        volunteer["id"],
        availability_window_payload(
            starts_at="2026-07-01T00:00:00Z",
            ends_at="2026-08-15T00:00:00Z",
            hours_offered=0.0,
        ),
        headers,
    )

    validate_error(response, ApiErrorId.ERR_ZERO_HOURS_NOT_ALLOWED, expected_status=422)


def test_17_a_window_only_partly_inside_the_cycle_is_refused(api):
    """PRD §3.2: "Two geometric rules guard publication. The whole interval must sit
    inside some program cycle's interval, and a malformed interval or one that
    escapes every cycle is refused with `ERR_WINDOW_OUTSIDE_CYCLE`."

    Design: Corner/errors/error_window_outside_cycle_on_partially_contained_interval
    """
    create_cycle(starts_at="2026-08-01T00:00:00Z", ends_at="2026-12-01T00:00:00Z")
    volunteer, _, _ = create_vetted_volunteer(window=False)
    headers = make_volunteer_headers(volunteer["id"])

    straddling = api_client.create_availability_window(
        volunteer["id"],
        availability_window_payload(
            starts_at="2026-07-01T00:00:00Z",
            ends_at="2026-08-15T00:00:00Z",
            hours_offered=50.00,
        ),
        headers,
    )
    validate_error(straddling, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE, expected_status=422)

    contained = api_client.create_availability_window(
        volunteer["id"],
        availability_window_payload(
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-15T00:00:00Z",
            hours_offered=50.00,
        ),
        headers,
    )
    validate_success(contained, expected_status=201)


def test_18_out_of_range_limit_and_negative_offset_are_refused_together(api):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not exceed 100.
    `offset` defaults to 0 and may not be negative. Both must be integers; a `limit`
    below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/error_invalid_pagination_on_limit_and_offset_together
    """
    w = setup_draft_request()
    pm = w["pm_headers"]

    both_bad = api_client.list_project_requests(pm, {"limit": 101, "offset": -1})
    validate_error(both_bad, ApiErrorId.ERR_INVALID_PAGINATION, expected_status=400)

    at_the_ceiling = api_client.list_project_requests(pm, {"limit": 100, "offset": 0})
    _, meta = validate_paginated(at_the_ceiling)
    assert meta["total_count"] == 1, (
        f"Expected the one filed request to be listed, got {meta['total_count']}"
    )

    zero_limit = api_client.list_project_requests(pm, {"limit": 0})
    validate_error(zero_limit, ApiErrorId.ERR_INVALID_PAGINATION, expected_status=400)


def test_19_a_due_instant_inside_the_cycle_but_past_the_window_is_refused(api):
    """PRD §3.7: "The `due_at` must fall inside the engagement's pinned availability
    window and be strictly after the engagement's own `created_at`, or the request is
    refused with `ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT`."

    Design: Corner/errors/error_milestone_due_inside_cycle_but_outside_window_rejected
    """
    w = setup_in_progress_engagement()

    response = api_client.create_milestone(
        w["engagement"]["id"],
        milestone_payload(due_at="2026-11-15T00:00:00Z"),
        w["pm_headers"],
    )

    validate_error(
        response,
        ApiErrorId.ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT,
        expected_status=422,
    )

    _, meta = validate_paginated(
        api_client.list_milestones(w["engagement"]["id"], w["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected no check-in to be scheduled, got {meta['total_count']}"
    )

    engagement = read_engagement(w)
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement to stay IN_PROGRESS, got {engagement['work_status']}"
    )
    assert engagement["missed_checkin_count"] == 0, (
        f"Expected missed_checkin_count 0, got {engagement['missed_checkin_count']}"
    )


def test_20_a_second_window_overlapping_the_first_is_refused(api):
    """PRD §3.2: "And no two windows of the same volunteer whose `status` is not
    `EXPIRED` may overlap: overlap is judged on half-open geometry, so a new window
    is refused with `ERR_AVAILABILITY_WINDOW_OVERLAP` when its `starts_at` falls
    before an existing window's `ends_at` while that existing window's `starts_at`
    falls before the new one's `ends_at`."

    Design: Corner/errors/error_overlapping_window_inside_cycle_rejected
    """
    w = setup_roster(window_hours=200.00)
    volunteer_id = w["volunteer"]["id"]

    response = api_client.create_availability_window(
        volunteer_id,
        availability_window_payload(
            starts_at="2026-10-01T00:00:00Z",
            ends_at="2026-11-01T00:00:00Z",
            window_kind="SOFT",
            hours_offered=50.00,
        ),
        w["volunteer_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP, expected_status=409
    )

    rows, meta = validate_paginated(
        api_client.list_availability_windows(volunteer_id, w["pm_headers"])
    )
    assert meta["total_count"] == 1, (
        f"Expected the volunteer to still hold one window, got {meta['total_count']}"
    )
    assert float(rows[0]["hours_offered"]) == 200.00, (
        f"Expected the surviving window to offer 200.00 hours, got {rows[0]['hours_offered']}"
    )
    assert rows[0]["window_kind"] == "HARD", (
        f"Expected the surviving window to be HARD, got {rows[0]['window_kind']}"
    )


def test_21_a_second_claim_on_the_same_skill_code_is_refused(api):
    """PRD §3.2: "The pair of the owning `volunteer_id` and the `skill_code` must be
    unique — a second claim on the same code is refused with
    `ERR_DUPLICATE_SKILL_PROFILE` — and `verified` defaults to false until a vetting
    run names that code."

    Design: Corner/errors/error_duplicate_skill_profile_on_second_claim_of_same_code
    """
    volunteer, _, _ = create_vetted_volunteer(window=False)
    headers = make_volunteer_headers(volunteer["id"])

    duplicate = api_client.create_skill_profile(
        volunteer["id"],
        skill_profile_payload(skill_code="TAX_LAW", proficiency=2, years_experience=1.0),
        headers,
    )
    validate_error(
        duplicate, ApiErrorId.ERR_DUPLICATE_SKILL_PROFILE, expected_status=409
    )

    rows, meta = validate_paginated(
        api_client.list_skill_profiles(volunteer["id"], headers)
    )
    assert meta["total_count"] == 1, (
        f"Expected the duplicate to leave one claim, got {meta['total_count']}"
    )
    assert rows[0]["proficiency"] == 4, (
        f"Expected the original proficiency 4 to survive, got {rows[0]['proficiency']}"
    )

    other_code = api_client.create_skill_profile(
        volunteer["id"],
        skill_profile_payload(skill_code="NONPROFIT_FINANCE", proficiency=3),
        headers,
    )
    validate_success(other_code, expected_status=201)

    _, meta = validate_paginated(
        api_client.list_skill_profiles(volunteer["id"], headers)
    )
    assert meta["total_count"] == 2, (
        f"Expected two claims once a second code is declared, got {meta['total_count']}"
    )


def test_22_the_clock_accepts_its_own_instant_and_refuses_an_earlier_one(api):
    """PRD §2.5: "The clock only moves forward: an instant strictly earlier than the
    current clock reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422), while
    an instant exactly equal to the current reading is accepted and leaves the clock
    where it is."

    Design: Corner/errors/error_clock_regression_on_setting_the_current_instant
    """
    pm = make_program_manager_headers()
    set_clock("2026-08-01T12:00:00Z", pm)

    same_instant = api_client.set_clock({"to_iso8601": "2026-08-01T12:00:00Z"}, pm)
    validate_success(same_instant, expected_status=200)

    earlier = api_client.set_clock({"to_iso8601": "2026-07-31T23:59:59Z"}, pm)
    validate_error(earlier, ApiErrorId.ERR_CLOCK_REGRESSION, expected_status=422)


# ---------------------------------------------------------------------------
# Lifecycle-state rules and the guards they outrank
# ---------------------------------------------------------------------------
def test_23_matching_a_draft_request_answers_the_state_error_not_an_empty_pool(api):
    """PRD §2.12: "20. The project request's `status` is in the from-set of the
    requested transition — on ... `POST /project-requests/{id}/match` ... — otherwise
    `ERR_INVALID_REQUEST_STATE` (409)", ahead of "57. The matching selector produced a
    non-empty candidate set — on `POST /project-requests/{id}/match` — otherwise
    `ERR_NO_ELIGIBLE_VOLUNTEER` (422)."

    Design: Corner/errors/error_invalid_request_state_beats_no_eligible_volunteer
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm)
    cycle = create_cycle(pm)
    request = get_success_data(
        api_client.create_project_request(
            project_request_payload(partner["id"], cycle["id"]),
            make_partner_contact_headers(partner["id"]),
        )
    )
    w = {"pm_headers": pm, "request": request, "cycle": cycle}

    response = api_client.match_project_request(
        request["id"], make_scoping_specialist_headers()
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST_STATE, expected_status=409)

    after = read_request(w)
    assert after["status"] == "DRAFT", (
        f"Expected the request to stay in DRAFT, got {after['status']}"
    )
    assert after["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds to stay 0, got {after['failed_match_rounds']}"
    )
    cycle_after = read_cycle(w)
    assert cycle_after["slots_reserved"] == 0, (
        f"Expected no slot to be reserved, got {cycle_after['slots_reserved']}"
    )


def test_24_an_unvettable_pool_answers_no_eligible_volunteer_and_counts_the_round(api):
    """PRD §3.4: "If nothing survives this filter, no offer is created: the request
    stays in `SCOPED`, its `failed_match_rounds` rises by one, and the call answers
    `ERR_NO_ELIGIBLE_VOLUNTEER`."

    Design: Corner/errors/error_no_eligible_volunteer_is_the_last_resort_on_a_scoped_request
    """
    w = setup_selector_world([], skill_code="TAX_LAW")
    volunteer = create_volunteer(w["pm_headers"])
    create_skill_profile(volunteer["id"], skill_code="TAX_LAW", proficiency=4)

    response = api_client.match_project_request(w["request"]["id"], w["spec_headers"])

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_VOLUNTEER, expected_status=422)

    after = read_request(w)
    assert after["status"] == "SCOPED", (
        f"Expected the request to stay in SCOPED, got {after['status']}"
    )
    assert after["failed_match_rounds"] == 1, (
        f"Expected failed_match_rounds 1, got {after['failed_match_rounds']}"
    )

    _, meta = validate_paginated(api_client.list_match_offers(w["pm_headers"]))
    assert meta["total_count"] == 0, (
        f"Expected no offer to be raised, got {meta['total_count']}"
    )
    cycle_after = read_cycle(w)
    assert cycle_after["slots_reserved"] == 0, (
        f"Expected no slot to be reserved, got {cycle_after['slots_reserved']}"
    )


def test_25_approving_a_revision_weighing_sixty_percent_is_refused(api):
    """PRD §3.3: "A weight total that is not exactly 100.00 at this moment is refused
    with `ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID`; approving a revision that is not in
    `DRAFT` is refused with `ERR_INVALID_SCOPE_STATE`."

    Design: Corner/errors/error_deliverable_weight_total_invalid_on_approve_below_one_hundred
    """
    w = setup_scoping_request(
        deliverables=[{"weight_pct": 60.00, "hours_estimate": 24.00}]
    )

    response = api_client.approve_scope_definition(w["scope"]["id"], w["partner_headers"])

    validate_error(
        response, ApiErrorId.ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID, expected_status=422
    )

    scope = read_scope(w)
    assert scope["status"] == "DRAFT", (
        f"Expected the revision to stay in DRAFT, got {scope['status']}"
    )
    assert float(scope["deliverable_weight_total_pct"]) == 60.00, (
        f"Expected the weight total to stay 60.00, got {scope['deliverable_weight_total_pct']}"
    )
    assert scope["approved_at"] is None, (
        f"Expected approved_at to stay null, got {scope['approved_at']}"
    )

    request = read_request(w)
    assert request["status"] == "SCOPING", (
        f"Expected the request to stay in SCOPING, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0, got {request['active_scope_revision_no']}"
    )


def test_26_adding_a_deliverable_to_an_approved_revision_answers_the_state_error(api):
    """PRD §2.12: "21. The scope revision's `status` is `DRAFT` — on `POST
    /scope-definitions/{id}/approve` and `POST /scope-definitions/{id}/deliverables` —
    otherwise `ERR_INVALID_SCOPE_STATE` (409)", ahead of "47. A deliverable's
    `sequence_no` is unique within its revision, and at approval time the revision's
    `deliverable_weight_total_pct` equals exactly 100.00 over non-`WAIVED`
    deliverables with `deliverable_count` of at least 1 — on `POST
    /scope-definitions/{id}/deliverables` and `POST /scope-definitions/{id}/approve` —
    otherwise `ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID` (422)."

    Design: Corner/errors/error_invalid_scope_state_beats_weight_total_on_approved_revision
    """
    w = setup_scoped_request(deliverables=SINGLE_DELIVERABLE)

    response = api_client.create_deliverable(
        w["scope"]["id"],
        deliverable_payload(
            title="Late addition", sequence_no=2, weight_pct=50.00, hours_estimate=8.00
        ),
        w["spec_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_SCOPE_STATE, expected_status=409)

    scope = read_scope(w)
    assert scope["deliverable_count"] == 1, (
        f"Expected the deliverable count to stay 1, got {scope['deliverable_count']}"
    )
    assert float(scope["deliverable_weight_total_pct"]) == 100.00, (
        f"Expected the weight total to stay 100.00, got {scope['deliverable_weight_total_pct']}"
    )


def test_27_countering_a_drafted_agreement_answers_the_agreement_state_error(api):
    """PRD §3.6: "Attempting any of these moves from a status outside its declared
    from-set — sending from `EXECUTED`, countering something not `SENT`, signing
    something not `SENT`, voiding something already `EXECUTED` or `VOIDED` — is
    refused with `ERR_INVALID_AGREEMENT_STATE`." PRD §2.12 places that from-set check
    at position 25, ahead of the terms-alignment check at position 35, which it
    applies only "on `POST /agreements/{id}/execute` and `POST
    /engagements/{id}/handoff`".

    Design: Corner/errors/error_invalid_agreement_state_beats_ip_terms_mismatch_on_counter
    """
    w = setup_drafted_agreement()

    response = api_client.counter_agreement(
        w["agreement"]["id"],
        counter_payload(
            ip_disposition="RETAINED_BY_VOLUNTEER",
            confidentiality_tier="STANDARD",
            indemnity_cap_usd=5000.00,
        ),
        w["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_AGREEMENT_STATE, expected_status=409)

    agreement = read_agreement(w)
    assert agreement["status"] == "DRAFTED", (
        f"Expected the agreement to stay DRAFTED, got {agreement['status']}"
    )
    assert agreement["counter_round"] == 0, (
        f"Expected counter_round to stay 0, got {agreement['counter_round']}"
    )
    assert agreement["terms_revision_no"] == 1, (
        f"Expected terms_revision_no to stay 1, got {agreement['terms_revision_no']}"
    )
    assert agreement["ip_disposition"] == "ASSIGN_TO_PARTNER", (
        f"Expected the pinned IP terms to survive, got {agreement['ip_disposition']}"
    )


def test_28_accepting_a_released_offer_answers_offer_not_open(api):
    """PRD §3.5: "Any of the three volunteer- or staff-driven responses aimed at an
    offer that is no longer in `OFFERED` is refused with `ERR_OFFER_NOT_OPEN`." PRD
    §2.12 places the offer-status check at position 22, ahead of the pinned-revision
    check at position 49 ("otherwise `ERR_SCOPE_VERSION_SUPERSEDED` (409)").

    Design: Corner/errors/error_scope_version_superseded_is_pre_empted_by_offer_state
    """
    w = setup_offer()
    get_success_data(
        api_client.abandon_project_request(w["request"]["id"], w["pm_headers"])
    )

    response = api_client.accept_match_offer(w["offer"]["id"], w["volunteer_headers"])

    validate_error(response, ApiErrorId.ERR_OFFER_NOT_OPEN, expected_status=409)

    scope = read_scope(w)
    assert scope["status"] == "SUPERSEDED", (
        f"Expected the revision to be SUPERSEDED, got {scope['status']}"
    )
    request = read_request(w)
    assert request["status"] == "ABANDONED", (
        f"Expected the request to be ABANDONED, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0, got {request['active_scope_revision_no']}"
    )

    _, meta = validate_paginated(api_client.list_engagements(w["pm_headers"]))
    assert meta["total_count"] == 0, (
        f"Expected no engagement to be created, got {meta['total_count']}"
    )


def test_29_posting_a_valuation_after_a_restatement_is_refused(api):
    """PRD §3.9: "A post attempted against a `RESTATED` engagement, or a `FINAL`-stage
    post while the engagement is still `NOT_STARTED` or `IN_PROGRESS`, is refused with
    `ERR_INVALID_VALUATION_STATE`."

    Design: Corner/errors/error_invalid_valuation_state_on_post_after_restatement
    """
    w = setup_submitted_engagement(deliverables=SINGLE_DELIVERABLE)
    validate_success(post_valuation(w, "INDEPENDENT_SECTOR"), expected_status=201)

    drive_review_to_outcome(w, {w["deliverables"][0]["id"]: 2})
    validate_success(
        api_client.decide_quality_review(w["review"]["id"], w["reviewer_headers"], {})
    )

    engagement = read_engagement(w)
    assert engagement["valuation_status"] == "RESTATED", (
        f"Expected a RESTATED valuation status, got {engagement['valuation_status']}"
    )
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected a TERMINATED work status, got {engagement['work_status']}"
    )

    response = post_valuation(w, "MARKET_RATE")

    validate_error(
        response, ApiErrorId.ERR_INVALID_VALUATION_STATE, expected_status=409
    )

    methods = [record["method"] for record in read_valuation_records(w)]
    assert "MARKET_RATE" not in methods, (
        f"Expected no MARKET_RATE record to be written, got methods {methods}"
    )


def _fail_one_matching_round(w):
    """Run the selector and have the offered volunteer decline, spending one round."""
    offer = get_success_data(
        api_client.match_project_request(w["request"]["id"], w["spec_headers"])
    )
    get_success_data(
        api_client.decline_match_offer(
            offer["id"],
            {"decline_reason": "SCHEDULE_CONFLICT"},
            make_volunteer_headers(offer["volunteer_id"]),
        )
    )


def _restart_scoping_with_a_fresh_revision(w):
    """Take a RESCOPING request back through SCOPING to SCOPED on new terms."""
    get_success_data(
        api_client.rescope_project_request(w["request"]["id"], w["spec_headers"])
    )
    revision = add_draft_revision(w)
    get_success_data(
        api_client.create_deliverable(
            revision["id"], deliverable_payload(), w["spec_headers"]
        )
    )
    get_success_data(
        api_client.approve_scope_definition(revision["id"], w["partner_headers"])
    )


def test_30_a_fourth_rescope_is_refused_once_the_allowance_is_spent(api):
    """PRD §2.12: "50. The request's `rescope_count` is below 3 when a rescope is
    requested or forced — on `POST /project-requests/{id}/rescope` — otherwise
    `ERR_RESCOPE_LIMIT_REACHED` (409)."

    Design: Corner/errors/error_rescope_limit_reached_on_fourth_rescope_attempt
    """
    w = setup_selector_world([{} for _ in range(6)], skill_code="TAX_LAW")

    for spent in range(3):
        _fail_one_matching_round(w)
        _fail_one_matching_round(w)
        if spent < 2:
            _restart_scoping_with_a_fresh_revision(w)

    exhausted = read_request(w)
    assert exhausted["rescope_count"] == 3, (
        f"Expected the allowance to be spent at rescope_count 3, got {exhausted['rescope_count']}"
    )
    assert exhausted["status"] == "RESCOPING", (
        f"Expected the request to sit in RESCOPING, got {exhausted['status']}"
    )

    response = api_client.rescope_project_request(
        w["request"]["id"], w["spec_headers"]
    )

    validate_error(response, ApiErrorId.ERR_RESCOPE_LIMIT_REACHED, expected_status=409)

    after = read_request(w)
    assert after["status"] == "RESCOPING", (
        f"Expected the request to stay in RESCOPING, got {after['status']}"
    )
    assert after["rescope_count"] == 3, (
        f"Expected rescope_count to stay 3, got {after['rescope_count']}"
    )
    assert after["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds to stay 0, got {after['failed_match_rounds']}"
    )
    assert after["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0, got {after['active_scope_revision_no']}"
    )

    rows, meta = validate_paginated(api_client.list_match_offers(w["pm_headers"]))
    assert meta["total_count"] == 6, (
        f"Expected six offers across the six spent rounds, got {meta['total_count']}"
    )
    statuses = sorted({row["status"] for row in rows})
    assert statuses == ["DECLINED"], (
        f"Expected every offer to have been declined, got statuses {statuses}"
    )
