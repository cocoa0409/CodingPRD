"""Corner coverage for under-exercised endpoints and for the error catalogue's edges."""
import pytest

from test_helpers import (
    FULL_POINTS,
    NON_EXISTENT_UUID,
    SUBSCALE_CODES,
    TEST_USERS,
    build_rating_spine,
    create_observation_visit_payload,
    family_headers_without_user_id,
    make_observer_headers,
    make_provider_headers,
    points_map,
    score_payload,
    set_clock,
    setup_open_grant,
    setup_tier_one_active_spine,
    submit_claim,
    submit_expenditure,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

TIER_ONE_POINTS = points_map(learning=12, staff=8)


# --- endpoints ---------------------------------------------------------------


def test_score_preview_projects_a_full_house_without_touching_stored_state(api):
    """PRD §3.3: "The preview accepts an optional `variant` naming either the provisional or
    the final scoring run, defaults to the provisional run, persists nothing at all, and
    returns a cycle representation carrying that variant's `weighted_total`,
    `block_clearance`, `highest_block_cleared`, `points_tier`, and `awarded_tier` as a
    projection rather than as stored state."
    PRD §3.5: "For the observation-linked domain, if the cycle has no observation composite
    yet the credited number is used unchanged, which is why a provisional run before
    finalization simply keeps the claimed points; once a composite exists, the domain's
    points are instead derived from it by multiplying the domain's `max_points` by an
    observation fraction and rounding half up to a whole integer."

    Design: Corner/endpoints/score_preview_is_a_provisional_projection_that_persists_nothing
    """
    ctx = build_rating_spine(stop_at="SELF_ASSESSMENT_SUBMITTED", claimed=FULL_POINTS)
    cycle_id = ctx["cycle"]["id"]
    before = validate_success(api.get_rating_cycle(cycle_id, ADMIN))

    preview = validate_success(
        api.get_score_preview(cycle_id, ADMIN, params={"variant": "PROVISIONAL"})
    )
    assert preview["weighted_total"] == pytest.approx(100.00, abs=0.005), (
        f"all five domains claimed at their ceiling give 100.00, got {preview['weighted_total']}"
    )
    assert preview["points_tier"] == 5, f"points_tier must be 5, got {preview['points_tier']}"
    assert preview["awarded_tier"] == 5, f"awarded_tier must be 5, got {preview['awarded_tier']}"
    assert preview["highest_block_cleared"] == 3, (
        f"all three blocks clear, got {preview['highest_block_cleared']}"
    )
    clearance = preview["block_clearance"]
    for block in ("1", "2", "3"):
        value = clearance.get(block, clearance.get(int(block)))
        assert value == "CLEARED", f"block {block} must be CLEARED, got {value}"

    after = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert after["status"] == "SELF_ASSESSMENT_SUBMITTED", (
        f"the preview must not advance the cycle, got {after['status']}"
    )
    assert after["awarded_tier"] is None, (
        f"the preview must not stamp awarded_tier, got {after['awarded_tier']}"
    )
    assert after["awarded_on"] is None
    assert after["observation_composite"] is None
    assert after["version"] == before["version"], (
        f"the preview persists nothing, so version stays {before['version']}, "
        f"got {after['version']}"
    )


def test_visit_cancel_uncurrents_every_score_and_frees_the_observer_interval(api):
    """PRD §3.4: "Cancellation drives the visit to `CANCELLED`, sets `is_current` to false on
    every score row that visit had accumulated, releases the observer's occupied interval so
    the observer is free for other visits, and returns the cycle `OBSERVATION_SCHEDULED →
    DOCS_VERIFIED` so a replacement visit can be scheduled."
    PRD §3.4: "The candidate set is every observation visit naming that observer as lead or
    as secondary whose state is `SCHEDULED`, `IN_PROGRESS`, `SCORES_ENTERED`,
    `RELIABILITY_CHECK`, or `FINALIZED`; a `CANCELLED` visit never conflicts."

    Design: Corner/endpoints/visit_cancel_uncurrents_scores_and_frees_the_observer_interval
    """
    window_start = "2026-08-10T09:00:00Z"
    window_end = "2026-08-10T13:00:00Z"
    ctx = build_rating_spine(
        stop_at="OBSERVATION_SCHEDULED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        window_start=window_start,
        window_end=window_end,
    )
    visit_id = ctx["visit"]["id"]
    lead_headers = make_observer_headers(ctx["lead"]["id"])
    set_clock(window_start)
    for code in SUBSCALE_CODES[:3]:
        validate_success(api.submit_score(visit_id, score_payload(code, 4.0), lead_headers), 201)

    cancelled = validate_success(
        api.cancel_visit(visit_id, ADMIN, {"reason": "observer reassigned"})
    )
    assert cancelled["status"] == "CANCELLED", (
        f"cancel drives the visit to CANCELLED, got {cancelled['status']}"
    )

    current, current_meta = validate_paginated(
        api.list_observation_scores(ADMIN, params={"observation_visit_id": visit_id,
                                                  "is_current": "true"})
    )
    assert current_meta["total_count"] == 0, (
        f"every accumulated score row must lose is_current, got {current_meta['total_count']}"
    )
    stale, stale_meta = validate_paginated(
        api.list_observation_scores(ADMIN, params={"observation_visit_id": visit_id,
                                                  "is_current": "false"})
    )
    assert stale_meta["total_count"] == 3, (
        f"all three entered rows survive as non-current, got {stale_meta['total_count']}"
    )
    assert all(row["is_current"] is False for row in stale)

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "DOCS_VERIFIED", (
        f"the cycle returns to DOCS_VERIFIED, got {cycle['status']}"
    )
    assert cycle["observation_composite"] is None

    replacement = validate_success(
        api.create_observation_visit(
            ctx["cycle"]["id"],
            create_observation_visit_payload(ctx["lead"]["id"], window_start, window_end),
            ADMIN,
        ),
        201,
    )
    assert replacement["status"] == "SCHEDULED", (
        "the cancelled visit never conflicts, so the identical window is free again; "
        f"got {replacement['status']}"
    )
    assert replacement["id"] != visit_id
    reopened = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert reopened["status"] == "OBSERVATION_SCHEDULED", (
        f"the replacement visit re-advances the cycle, got {reopened['status']}"
    )


def test_publish_is_refused_on_day_nine_and_accepted_on_day_ten(api):
    """PRD §3.6: "An administrator may publish a cycle's award only once the logical clock
    date has reached the award date plus 10 calendar days — the family-notice quiet period,
    inclusive of day 10 — and an earlier attempt is refused with
    `ERR_PUBLICATION_QUIET_PERIOD` and HTTP 422."
    PRD §3.6: "Publishing drives the cycle's `publication_status` to `PUBLISHED`, stamps
    `published_at` from the logical clock, and freezes a `published_snapshot` containing the
    awarded tier, the `weighted_total`, the `domain_points` map, the provider's
    `licensed_capacity`, and its `county_code`."

    Design: Corner/endpoints/publish_quiet_period_day_ten_inclusive_then_public_directory_shows_snapshot
    """
    ctx = build_rating_spine(
        stop_at="AWARDED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        award_clock="2026-08-11T00:00:00Z",
    )
    cycle_id = ctx["cycle"]["id"]
    assert ctx["cycle"]["awarded_tier"] == 1, (
        f"the spine must award tier 1, got {ctx['cycle']['awarded_tier']}"
    )

    set_clock("2026-08-20T23:59:59Z")
    validate_error(api.publish_cycle(cycle_id, ADMIN), "ERR_PUBLICATION_QUIET_PERIOD", 422)
    held = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert held["publication_status"] == "UNPUBLISHED", (
        f"a refused publish leaves the cycle UNPUBLISHED, got {held['publication_status']}"
    )
    assert held["published_at"] is None
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["public_listing_visible"] is False

    set_clock("2026-08-21T00:00:00Z")
    published = validate_success(api.publish_cycle(cycle_id, ADMIN))
    assert published["publication_status"] == "PUBLISHED", (
        f"day 10 is inclusive, so publication succeeds, got {published['publication_status']}"
    )
    assert published["published_at"] == "2026-08-21T00:00:00.000Z", (
        f"published_at is stamped from the logical clock, got {published['published_at']}"
    )
    assert published["status"] == "AWARDED", (
        f"publication is not a cycle status transition, got {published['status']}"
    )
    snapshot = published["published_snapshot"]
    assert snapshot is not None, "publishing freezes a published_snapshot"
    assert snapshot["weighted_total"] == pytest.approx(26.00, abs=0.005), (
        f"the frozen weighted_total must be 26.00, got {snapshot['weighted_total']}"
    )
    assert snapshot["domain_points"]["LEARNING_ENVIRONMENT"] == 12
    assert snapshot["domain_points"]["STAFF_QUALIFICATIONS"] == 8
    assert snapshot["domain_points"]["FAMILY_PARTNERSHIP"] == 0
    assert snapshot["domain_points"]["ADMINISTRATION"] == 0
    assert snapshot["domain_points"]["CHILD_ASSESSMENT"] == 0
    assert snapshot["licensed_capacity"] == 60
    assert snapshot["county_code"] == "DANE"


def test_public_directory_serves_only_the_published_cycle(api):
    """PRD §3.6: "The family-facing directory returns only cycles whose publication state is
    `PUBLISHED`, each carrying its frozen snapshot, and may be narrowed by `county_code` or
    by `tier`."

    Design: Corner/endpoints/publish_quiet_period_day_ten_inclusive_then_public_directory_shows_snapshot
    """
    ctx = build_rating_spine(
        stop_at="AWARDED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        award_clock="2026-08-11T00:00:00Z",
    )
    cycle_id = ctx["cycle"]["id"]

    set_clock("2026-08-20T23:59:59Z")
    _, before_meta = validate_paginated(
        api.list_public_ratings(family_headers_without_user_id(), params={"county_code": "DANE"})
    )
    assert before_meta["total_count"] == 0, (
        f"an unpublished cycle is invisible to families, got {before_meta['total_count']}"
    )

    set_clock("2026-08-21T00:00:00Z")
    validate_success(api.publish_cycle(cycle_id, ADMIN))
    rows, meta = validate_paginated(
        api.list_public_ratings(family_headers_without_user_id(), params={"county_code": "DANE"})
    )
    assert meta["total_count"] == 1, (
        f"the published cycle appears exactly once, got {meta['total_count']}"
    )
    assert len(rows) == 1


# --- errors ------------------------------------------------------------------


def test_missing_user_id_header_is_rejected_for_every_role_but_family_viewer(api):
    """PRD §2.7: "First, authentication: the `X-User-Role` header must be present and must
    name one of the six declared roles, and `X-User-ID` must be present for every role except
    `FamilyViewer`. A failure here is `ERR_UNAUTHENTICATED` with HTTP 401."
    PRD §2.1: "When `X-User-Role` is `FamilyViewer`, `X-User-ID` is an opaque identifier not
    tied to any persisted entity, and it is the only role for which the `X-User-ID` header may
    be omitted entirely."

    Design: Corner/errors/err_unauthenticated_when_only_family_viewer_may_omit_user_id
    """
    validate_error(
        api.create_provider(
            {
                "legal_name": "Headerless Center",
                "license_number": "LIC-40001",
                "county_code": "DANE",
                "region_code": "URBAN",
                "licensed_capacity": 60,
                "active_staff_fte": 1.00,
            },
            {"X-User-Role": "StateAdministrator"},
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.list_providers({"X-User-Role": "Provider"}), "ERR_UNAUTHENTICATED", 401
    )
    validate_error(
        api.list_providers({"X-User-Role": "Coach"}), "ERR_UNAUTHENTICATED", 401
    )
    validate_error(
        api.list_providers({"X-User-Role": "AppealReviewer"}), "ERR_UNAUTHENTICATED", 401
    )
    validate_error(
        api.list_providers({"X-User-Role": "Observer"}), "ERR_UNAUTHENTICATED", 401
    )

    _, meta = validate_paginated(api.list_public_ratings(family_headers_without_user_id()))
    assert meta["total_count"] == 0, (
        "FamilyViewer alone may omit X-User-ID, and the empty directory is a success not a "
        f"401; got total_count {meta['total_count']}"
    )
    _, admin_meta = validate_paginated(api.list_providers(ADMIN))
    assert admin_meta["total_count"] == 0, (
        f"no rejected request may have created a provider, got {admin_meta['total_count']}"
    )


NOT_FOUND_CASES = [
    ("provider_id", lambda api, headers: api.get_provider(NON_EXISTENT_UUID, headers),
     "ERR_PROVIDER_NOT_FOUND"),
    ("rating_cycle_id", lambda api, headers: api.get_rating_cycle(NON_EXISTENT_UUID, headers),
     "ERR_RATING_ARTIFACT_NOT_FOUND"),
    ("self_assessment_id",
     lambda api, headers: api.get_self_assessment(NON_EXISTENT_UUID, headers),
     "ERR_RATING_ARTIFACT_NOT_FOUND"),
    ("observation_visit_id",
     lambda api, headers: api.get_observation_visit(NON_EXISTENT_UUID, headers),
     "ERR_RATING_ARTIFACT_NOT_FOUND"),
    ("observation_score_id",
     lambda api, headers: api.get_observation_score(NON_EXISTENT_UUID, headers),
     "ERR_RATING_ARTIFACT_NOT_FOUND"),
    ("credential_id",
     lambda api, headers: api.get_staff_credential(NON_EXISTENT_UUID, headers),
     "ERR_CREDENTIAL_NOT_FOUND"),
    ("appeal_id", lambda api, headers: api.get_appeal(NON_EXISTENT_UUID, headers),
     "ERR_REMEDY_NOT_FOUND"),
    ("data_dispute_id", lambda api, headers: api.get_data_dispute(NON_EXISTENT_UUID, headers),
     "ERR_REMEDY_NOT_FOUND"),
    ("improvement_grant_id",
     lambda api, headers: api.get_improvement_grant(NON_EXISTENT_UUID, headers),
     "ERR_FUNDING_NOT_FOUND"),
    ("grant_expenditure_id",
     lambda api, headers: api.get_grant_expenditure(NON_EXISTENT_UUID, headers),
     "ERR_FUNDING_NOT_FOUND"),
    ("coaching_allocation_id",
     lambda api, headers: api.get_coaching_allocation(NON_EXISTENT_UUID, headers),
     "ERR_FUNDING_NOT_FOUND"),
    ("coaching_session_id",
     lambda api, headers: api.get_coaching_session(NON_EXISTENT_UUID, headers),
     "ERR_FUNDING_NOT_FOUND"),
    ("subsidy_claim_id",
     lambda api, headers: api.get_subsidy_claim(NON_EXISTENT_UUID, headers),
     "ERR_FUNDING_NOT_FOUND"),
]


@pytest.mark.parametrize("path_param,call,expected_error", NOT_FOUND_CASES,
                         ids=[case[0] for case in NOT_FOUND_CASES])
def test_each_path_parameter_family_has_its_own_not_found_code(api, path_param, call,
                                                              expected_error):
    """PRD §2.6: "An unresolvable `provider_id` yields `ERR_PROVIDER_NOT_FOUND`. An
    unresolvable `rating_cycle_id`, `self_assessment_id`, `observation_visit_id`, or
    `observation_score_id` — whether it arrived in the path or in a request body — yields
    `ERR_RATING_ARTIFACT_NOT_FOUND`. An unresolvable `observer_id`, including one supplied as
    `lead_observer_id` or `secondary_observer_id`, yields `ERR_OBSERVER_NOT_FOUND`. An
    unresolvable `appeal_id` or `data_dispute_id` yields `ERR_REMEDY_NOT_FOUND`. An
    unresolvable `improvement_grant_id`, `grant_expenditure_id`, `coaching_allocation_id`,
    `coaching_session_id`, or `subsidy_claim_id` yields `ERR_FUNDING_NOT_FOUND`. An
    unresolvable `credential_id` yields `ERR_CREDENTIAL_NOT_FOUND`. All six carry HTTP status
    404."

    Design: Corner/errors/not_found_families_are_distinct_per_resource_prefix
    """
    validate_error(call(api, ADMIN), expected_error, 404)


def test_body_level_observer_reference_uses_the_observer_not_found_family(api):
    """PRD §2.6: "An unresolvable `observer_id`, including one supplied as `lead_observer_id`
    or `secondary_observer_id`, yields `ERR_OBSERVER_NOT_FOUND`."
    PRD §2.6: "Body-level foreign keys are resolved after the request body has passed schema
    checking, and they resolve into the same families: on visit scheduling,
    `lead_observer_id` and `secondary_observer_id` resolve against registered observers; on
    grant offering, the `rating_cycle_id` in the body resolves against rating cycles; on
    coaching allocation, `funding_grant_id` resolves against improvement grants and an
    unresolvable value is `ERR_FUNDING_NOT_FOUND`."

    Design: Corner/errors/not_found_families_are_distinct_per_resource_prefix
    """
    ctx = build_rating_spine(
        stop_at="DOCS_VERIFIED", claimed=TIER_ONE_POINTS, verified=TIER_ONE_POINTS
    )
    validate_error(
        api.create_observation_visit(
            ctx["cycle"]["id"],
            create_observation_visit_payload(NON_EXISTENT_UUID),
            ADMIN,
        ),
        "ERR_OBSERVER_NOT_FOUND",
        404,
    )
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "DOCS_VERIFIED", (
        f"a rejected scheduling attempt must not advance the cycle, got {cycle['status']}"
    )


def test_uncovered_claim_month_is_refused_before_the_zero_service_units_rule(api):
    """PRD §3.7: "Approval requires the claim to be in `SUBMITTED` and applies its checks in
    this order: first the coverage rule, which requires the claim to have resolved a
    `rating_cycle_id` whose validity window contains the first calendar day of the service
    month and whose cycle is `ACTIVE` with publication state `PUBLISHED` — a claim submitted
    for an uncovered month is still accepted at submission time with a null cycle and tier 1
    pricing, but its approval is refused with `ERR_CLAIM_MONTH_NOT_COVERED` and HTTP 422; then
    the open-appeal rule, which refuses approval with `ERR_OPEN_APPEAL_BLOCKS_ACTION` while
    any appeal of that cycle sits in `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED`; then the
    service-units rule, which requires the three age-band values to sum to more than zero and
    otherwise refuses with `ERR_ZERO_SERVICE_UNITS` and HTTP 422."
    PRD §3.7: "On acceptance the claim is created in `SUBMITTED`, its `base_amount_cents` is
    computed, and its `rating_cycle_id` is resolved to the cycle whose validity window
    contains the first calendar day of the service month, or left null when no cycle of that
    provider covers that day."

    Design: Corner/errors/p47_claim_month_not_covered_beats_p58_zero_service_units
    """
    ctx = setup_tier_one_active_spine()
    claim = submit_claim(ctx["provider"]["id"], "2026-08", infant=0, toddler=0, preschool=0)
    assert claim["status"] == "SUBMITTED", (
        f"an uncovered month is still accepted at submission, got {claim['status']}"
    )
    assert claim["rating_cycle_id"] is None, (
        f"no cycle covers 2026-08-01, so the linkage stays null, got {claim['rating_cycle_id']}"
    )
    assert claim["base_amount_cents"] == 0

    validate_error(
        api.adjudicate_claim(claim["id"], {"decision": "APPROVE"}, ADMIN),
        "ERR_CLAIM_MONTH_NOT_COVERED",
        422,
    )
    unchanged = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert unchanged["status"] == "SUBMITTED", (
        "the coverage rule is checked before the service-units rule, so the zero child-days "
        f"never surface; got {unchanged['status']}"
    )


def test_four_category_ceilings_consume_the_award_and_the_next_cent_is_exhausted(api):
    """PRD §3.8: "The grant balance check requires `amount_cents` to be no greater than
    `available_cents`; a submission consuming exactly the remaining availability is accepted
    and leaves `available_cents` at 0, while a larger one is refused with
    `ERR_GRANT_FUNDS_EXHAUSTED` and HTTP 422."
    PRD §3.8: "An accepted submission creates the line in `SUBMITTED` with
    `reimbursable_cents` and `disallowed_cents` at 0, adds its amount to `committed_cents`,
    subtracts it from `available_cents`, adds it to that category's entry in
    `category_spend_cents`, and increments the grant's `version` by 1."

    Design: Corner/errors/err_grant_funds_exhausted_after_four_ceilings_consume_the_award
    """
    ctx, grant = setup_open_grant(awarded_amount_cents=1_000_000)
    provider_id = ctx["provider"]["id"]
    assert grant["available_cents"] == 1_000_000, (
        f"acceptance initialises availability to the award, got {grant['available_cents']}"
    )

    for category, amount in (("EQUIPMENT", 400_000), ("PROF_DEV", 300_000),
                             ("FACILITY", 250_000), ("ADMIN", 50_000)):
        line = submit_expenditure(
            provider_id, grant["id"], category=category, amount_cents=amount,
            invoice_date="2026-09-15",
        )
        assert line["status"] == "SUBMITTED", (
            f"{category} at {amount} sits on or below its ceiling, got {line['status']}"
        )

    drained = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert drained["committed_cents"] == 1_000_000, (
        f"the four lines commit the whole award, got {drained['committed_cents']}"
    )
    assert drained["available_cents"] == 0, (
        f"a submission consuming exactly the remaining availability leaves 0, "
        f"got {drained['available_cents']}"
    )
    assert drained["reimbursed_cents"] == 0
    assert drained["status"] == "OPEN"
    assert drained["compliance_status"] == "COMPLIANT"
    assert drained["category_spend_cents"]["EQUIPMENT"] == 400_000
    assert drained["category_spend_cents"]["PROF_DEV"] == 300_000
    assert drained["category_spend_cents"]["FACILITY"] == 250_000
    assert drained["category_spend_cents"]["ADMIN"] == 50_000

    validate_error(
        api.create_expenditure(
            grant["id"],
            {
                "category": "ADMIN",
                "amount_cents": 1,
                "invoice_date": "2026-09-16",
                "expected_grant_version": drained["version"],
            },
            make_provider_headers(provider_id),
        ),
        "ERR_GRANT_FUNDS_EXHAUSTED",
        422,
    )
    lines, meta = validate_paginated(
        api.list_grant_expenditures(ADMIN, params={"improvement_grant_id": grant["id"]})
    )
    assert meta["total_count"] == 4, (
        f"the refused cent creates no line, got {meta['total_count']}"
    )
    assert all(row["status"] == "SUBMITTED" for row in lines)
    final = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert final["available_cents"] == 0
    assert final["committed_cents"] == 1_000_000
