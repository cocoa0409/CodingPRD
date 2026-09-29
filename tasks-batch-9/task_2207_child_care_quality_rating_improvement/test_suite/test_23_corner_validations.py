"""Rejection precedence along the validation ladder, plus the inclusive-interval boundaries.

Each precedence test constructs a request that violates two rules at once and pins the
single error the ordering in §2.7 — or a section's own pinned local ordering — requires.
"""
import pytest

from test_helpers import (
    COACH_USER_ID,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_grant,
    add_credential,
    build_rating_spine,
    create_allocation,
    create_applied_provider,
    create_enrolled_provider,
    create_observation_visit_payload,
    create_reliable_observer,
    create_self_assessment_payload,
    declare_domains,
    documentation_for,
    make_provider_headers,
    offer_grant,
    open_cycle,
    points_map,
    provider_version,
    set_clock,
    setup_tier_one_active_spine,
    submit_self_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    verify_self_assessment,
)

ADMIN = TEST_USERS["admin_headers"]
COACH = TEST_USERS["coach_headers"]

CREDENTIAL_BODY = {
    "staff_registry_id": "REG-X",
    "role_type": "DIRECTOR",
    "credential_level": 4,
    "fte": 1.00,
    "employment_status": "ACTIVE",
}


# --- the §2.7 ladder ---------------------------------------------------------


def test_forbidden_role_is_answered_before_the_missing_provider(api):
    """PRD §2.7: "Second, role authorization: the acting role must appear in the target
    endpoint's permitted-role list, or the request fails with `ERR_FORBIDDEN_ROLE` and HTTP
    403. Third, path existence: every path-templated resource must resolve, left to right,
    producing one of the 404 family codes described above."
    PRD §2.6: "An unresolvable `provider_id` yields `ERR_PROVIDER_NOT_FOUND`."

    Design: Corner/validations/p2_forbidden_role_beats_p3_missing_provider
    """
    set_clock("2026-08-01T00:00:00Z")
    validate_error(
        api.create_staff_credential(NON_EXISTENT_UUID, dict(CREDENTIAL_BODY), COACH),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    _, meta = validate_paginated(api.list_staff_credentials(ADMIN))
    assert meta["total_count"] == 0, (
        f"the rejected request must not have written a credential, got {meta['total_count']}"
    )


def test_the_missing_provider_is_answered_before_ownership(api):
    """PRD §2.7: "Third, path existence: every path-templated resource must resolve, left to
    right, producing one of the 404 family codes described above."
    PRD §2.7: "Fourth, ownership: for the two entity-backed roles the acting `X-User-ID` must
    equal the owning entity's `id`"
    PRD §2.6: "An unresolvable `provider_id` yields `ERR_PROVIDER_NOT_FOUND`."

    Design: Corner/validations/p3_missing_provider_beats_p4_ownership
    """
    set_clock("2026-08-01T00:00:00Z")
    caller = create_applied_provider(legal_name="Real Provider", licensed_capacity=20)
    validate_error(
        api.create_staff_credential(
            NON_EXISTENT_UUID, dict(CREDENTIAL_BODY), make_provider_headers(caller["id"])
        ),
        "ERR_PROVIDER_NOT_FOUND",
        404,
    )
    _, meta = validate_paginated(
        api.list_staff_credentials(ADMIN, params={"provider_id": caller["id"]})
    )
    assert meta["total_count"] == 0


def test_ownership_is_answered_before_the_body_schema(api):
    """PRD §2.7: "Fourth, ownership: for the two entity-backed roles the acting `X-User-ID`
    must equal the owning entity's `id` — a `Provider` acts only on resources whose provider
    linkage resolves to its own identifier, whether that linkage is direct, or reached
    through a rating cycle, or reached from a self-assessment through its cycle to the
    provider, or reached from a grant or allocation to its provider; an `Observer` may write
    scores only for a visit that names it as `lead_observer_id` or `secondary_observer_id`.
    A failure is `ERR_NOT_RESOURCE_OWNER` with HTTP 403."
    PRD §2.7: "Sixth, body schema and range checking on every creating or acting request
    produces `ERR_VALIDATION` with HTTP 422"
    PRD §3.2: "a `credential_level` from 1 to 6"

    Design: Corner/validations/p4_ownership_beats_p6_schema_violation
    """
    set_clock("2026-08-01T00:00:00Z")
    provider_a = create_applied_provider(legal_name="Provider A", licensed_capacity=20)
    provider_b = create_applied_provider(
        legal_name="Provider B", county_code="ROCK", region_code="RURAL", licensed_capacity=25
    )
    body = dict(CREDENTIAL_BODY)
    body["credential_level"] = 9
    validate_error(
        api.create_staff_credential(
            provider_a["id"], body, make_provider_headers(provider_b["id"])
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    _, meta = validate_paginated(
        api.list_staff_credentials(ADMIN, params={"provider_id": provider_a["id"]})
    )
    assert meta["total_count"] == 0, (
        "the out-of-range credential_level was never reached, and nothing was written"
    )


def test_the_body_schema_is_answered_before_a_body_foreign_key(api):
    """PRD §2.7: "Sixth, body schema and range checking on every creating or acting request
    produces `ERR_VALIDATION` with HTTP 422: required fields must be present, enum-typed
    fields must carry a declared member, integers must respect their declared minimums"
    PRD §2.7: "Seventh, body foreign keys are resolved."
    PRD §3.8: "A `StateAdministrator` offers a grant to a provider, naming in the payload the
    `rating_cycle_id` of the cycle whose award justified the grant, an `awarded_amount_cents`
    ceiling greater than zero, and a `spend_deadline` giving the inclusive last invoice date
    eligible for reimbursement."
    PRD §2.6: "An unresolvable `rating_cycle_id`, `self_assessment_id`,
    `observation_visit_id`, or `observation_score_id` — whether it arrived in the path or in
    a request body — yields `ERR_RATING_ARTIFACT_NOT_FOUND`."

    Design: Corner/validations/p6_schema_beats_p7_body_foreign_key
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_applied_provider(legal_name="Grant Target", licensed_capacity=20)
    validate_error(
        api.create_improvement_grant(
            provider["id"],
            {
                "rating_cycle_id": NON_EXISTENT_UUID,
                "awarded_amount_cents": -5,
                "spend_deadline": "2026-12-31",
            },
            ADMIN,
        ),
        "ERR_VALIDATION",
        422,
    )
    _, meta = validate_paginated(
        api.list_improvement_grants(ADMIN, params={"provider_id": provider["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no grant may be created by a rejected offer, got {meta['total_count']}"
    )


def test_the_stale_version_is_answered_before_the_cycle_gates(api):
    """PRD §3.3: "Four gates apply, evaluated in this order: first the stale-version
    comparison, which rejects with `ERR_STALE_VERSION`; then the provider's own standing,
    which must be `ACTIVE`, or `ENROLLED` when this is the provider's first cycle, and
    otherwise yields `ERR_PROVIDER_STATE_INVALID`; then the re-rating window, which requires
    for a `RERATING` cycle that the logical clock date be on or after the
    `rerating_window_opens_on` date of the provider's currently active cycle and otherwise
    yields `ERR_RERATING_WINDOW_NOT_OPEN` — a `REMAND` cycle is exempt from that window
    entirely; and finally the single-open-cycle rule, which rejects with
    `ERR_ACTIVE_CYCLE_EXISTS` when the provider already holds a cycle in any of `DRAFT`,
    `SELF_ASSESSMENT_SUBMITTED`, `DOCS_VERIFIED`, `OBSERVATION_SCHEDULED`,
    `OBSERVATION_FINALIZED`, `AWARDED`, or `UNDER_APPEAL`."
    PRD §2.5: "If that number does not equal the provider's current `version`, the request is
    rejected with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/validations/p8_stale_version_beats_p43_and_p50_cycle_rules
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_domains()
    provider = create_enrolled_provider(legal_name="Stale Test", licensed_capacity=20)
    version_before = provider_version(provider["id"])
    first = open_cycle(provider["id"], "INITIAL", expected_version=version_before)
    assert first["status"] == "DRAFT"

    validate_error(
        api.create_rating_cycle(
            provider["id"],
            {"cycle_type": "RERATING", "expected_provider_version": version_before - 1},
            make_provider_headers(provider["id"]),
        ),
        "ERR_STALE_VERSION",
        412,
    )

    still_draft = validate_success(api.get_rating_cycle(first["id"], ADMIN))
    assert still_draft["status"] == "DRAFT"
    rows, meta = validate_paginated(
        api.list_rating_cycles(ADMIN, params={"provider_id": provider["id"]})
    )
    assert meta["total_count"] == 1, (
        "the stale re-rating attempt must not create a second cycle, got "
        f"{meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]


def test_the_duplicate_self_assessment_is_answered_before_the_cycle_state(api):
    """PRD §2.7: "Ninth, uniqueness: a duplicate provider license number, a duplicate quality
    standard domain code, a duplicate staff registry identifier within one provider, or a
    second self-assessment on a cycle that already has one is rejected with
    `ERR_DUPLICATE_RESOURCE` and HTTP 409. Tenth, the target resource's own state must be one
    from which the requested transition is declared, producing the state-family code for that
    entity"
    PRD §3.3: "Submission also requires that the cycle still be in `DRAFT`, that all five
    standard domains exist with weights summing to exactly 1.00, and that the cycle not
    already have a self-assessment — a second submission on the same cycle is
    `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/p9_duplicate_self_assessment_beats_p10_cycle_state
    """
    ctx = build_rating_spine(
        stop_at="SELF_ASSESSMENT_SUBMITTED",
        provider_overrides={"legal_name": "Dup SA", "licensed_capacity": 20},
        claimed=points_map(learning=12, staff=8),
        cycle_clock="2026-08-03T00:00:00Z",
    )
    first = ctx["self_assessment"]
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "SELF_ASSESSMENT_SUBMITTED"

    validate_error(
        api.create_self_assessment(
            ctx["cycle"]["id"],
            create_self_assessment_payload(
                claimed=points_map(learning=20, staff=20, family=20, administration=20, child=20),
                documentation=documentation_for(["FAMILY_PARTNERSHIP"]),
            ),
            ctx["provider_headers"],
        ),
        "ERR_DUPLICATE_RESOURCE",
        409,
    )

    unchanged = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert unchanged["status"] == "SELF_ASSESSMENT_SUBMITTED"
    stored = validate_success(api.get_self_assessment(first["id"], ADMIN))
    assert stored["claimed_points"]["LEARNING_ENVIRONMENT"] == 12, (
        "the rejected resubmission must not overwrite the stored claim"
    )
    rows, meta = validate_paginated(
        api.list_self_assessments(ADMIN, params={"rating_cycle_id": ctx["cycle"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_the_unlinked_registry_record_is_answered_before_the_block_gate(api):
    """PRD §3.5: "Six checks guard the award, evaluated in this order. First, the
    secondary-observer requirement: a provisional run implying tier 4 or higher against a
    visit with no secondary observer is `ERR_SECONDARY_OBSERVER_REQUIRED`. Second, registry
    completeness: no staff credential of the provider whose `employment_status` is `ACTIVE`
    may sit in `UNLINKED` or `PENDING` — every active staff record must be resolved against
    the professional development registry, whether resolved to `VERIFIED` or to `EXPIRED` —
    and a violation is `ERR_CREDENTIAL_REGISTRY_UNLINKED` with HTTP 422."
    PRD §3.5: "Sixth, the block floor: `highest_block_cleared` must be at least 1, because
    when block 1 is not cleared no rating may be issued at all regardless of the weighted
    total, and the refusal is `ERR_BLOCK_GATE_NOT_MET` with HTTP 422."

    Design: Corner/validations/p26_registry_unlinked_beats_p52_block_gate
    """
    starved = points_map(learning=12, staff=5)
    ctx = build_rating_spine(
        stop_at="OBSERVATION_FINALIZED",
        provider_overrides={
            "legal_name": "Unlinked Registry",
            "licensed_capacity": 24,
            "active_staff_fte": 2.00,
        },
        credentials=[
            {"role_type": "DIRECTOR", "credential_level": 5, "fte": 1.00},
            {"role_type": "LEAD_TEACHER", "credential_level": 3, "fte": 1.00,
             "registry_status": "UNLINKED"},
        ],
        claimed=starved,
        verified=starved,
        raw_score=4.0,
    )
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["credential_compliance_pct"] == pytest.approx(50.00, abs=0.005), (
        "one VERIFIED fte of an active_staff_fte of 2.00 is 50.00, got "
        f"{provider['credential_compliance_pct']}"
    )

    preview = validate_success(
        api.get_score_preview(ctx["cycle"]["id"], ADMIN, params={"variant": "FINAL"})
    )
    assert preview["block_clearance"]["1"] == "NOT_CLEARED", (
        "STAFF_QUALIFICATIONS is awarded 5 points against a block_min_points of 8, so the "
        f"block floor is violated too, got {preview['block_clearance']}"
    )
    assert preview["highest_block_cleared"] == 0

    set_clock("2026-08-11T00:00:00Z")
    validate_error(
        api.award_cycle(ctx["cycle"]["id"], {"score_variant": "FINAL"}, ADMIN),
        "ERR_CREDENTIAL_REGISTRY_UNLINKED",
        422,
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_FINALIZED", (
        "a refused award leaves the cycle where it was"
    )
    assert cycle["awarded_tier"] is None
    assert cycle["awarded_on"] is None


# --- inclusive and exclusive interval boundaries -----------------------------


def test_a_category_ceiling_accepts_the_exact_amount_then_refuses_one_more_cent(api):
    """PRD §3.8: "Each cost category has a ceiling expressed as a share of the grant:
    equipment may consume up to 40 percent of `awarded_amount_cents`, professional
    development up to 30 percent, facility work up to 25 percent, and administrative costs up
    to 10 percent, each computed by multiplying the awarded amount by that share and
    discarding any fractional cent. A submission is admitted when the category's existing
    `category_spend_cents` entry plus the new `amount_cents` is no greater than that ceiling
    — the comparison is inclusive, so a submission landing exactly on the ceiling is accepted
    — and otherwise refused with `ERR_GRANT_CATEGORY_CEILING_EXCEEDED` and HTTP 422."
    PRD §3.8: "An accepted submission creates the line in `SUBMITTED` with
    `reimbursable_cents` and `disallowed_cents` at 0, adds its amount to `committed_cents`,
    subtracts it from `available_cents`, adds it to that category's entry in
    `category_spend_cents`, and increments the grant's `version` by 1."

    Design: Corner/validations/p60_category_ceiling_accepts_exactly_then_rejects_one_cent
    """
    ctx = setup_tier_one_active_spine()
    provider_id = ctx["provider"]["id"]
    grant = offer_grant(provider_id, ctx["cycle"]["id"], 1_000_000, "2026-12-31")
    grant = accept_grant(provider_id, grant["id"])
    assert grant["status"] == "OPEN"

    on_the_ceiling = validate_success(
        api.create_expenditure(
            grant["id"],
            {
                "category": "EQUIPMENT",
                "amount_cents": 400000,
                "invoice_date": "2026-09-01",
                "expected_grant_version": grant["version"],
            },
            make_provider_headers(provider_id),
        ),
        201,
    )
    assert on_the_ceiling["status"] == "SUBMITTED", (
        "40 percent of 1,000,000 cents is exactly 400,000 and the ceiling test is inclusive"
    )

    committed = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert committed["category_spend_cents"]["EQUIPMENT"] == 400000
    assert committed["committed_cents"] == 400000
    assert committed["available_cents"] == 600000

    validate_error(
        api.create_expenditure(
            grant["id"],
            {
                "category": "EQUIPMENT",
                "amount_cents": 1,
                "invoice_date": "2026-09-01",
                "expected_grant_version": committed["version"],
            },
            make_provider_headers(provider_id),
        ),
        "ERR_GRANT_CATEGORY_CEILING_EXCEEDED",
        422,
    )

    after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert after["category_spend_cents"]["EQUIPMENT"] == 400000, (
        "one cent past the ceiling commits nothing, even though 600,000 cents of the grant "
        f"remain available, got {after['category_spend_cents']}"
    )
    assert after["committed_cents"] == 400000
    assert after["available_cents"] == 600000
    rows, meta = validate_paginated(
        api.list_grant_expenditures(ADMIN, params={"improvement_grant_id": grant["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == on_the_ceiling["id"]


def _docs_verified_cycle(legal_name, capacity):
    """One provider whose first cycle has reached DOCS_VERIFIED. Domains must already exist."""
    provider = create_enrolled_provider(legal_name=legal_name, licensed_capacity=capacity)
    add_credential(provider["id"], expires_on="2030-01-01",
                   role_type="DIRECTOR", credential_level=4, fte=1.00)
    cycle = open_cycle(provider["id"])
    assessment = submit_self_assessment(
        provider["id"], cycle["id"], claimed=points_map(learning=12, staff=8)
    )
    verify_self_assessment(assessment["id"], verified=points_map(learning=12, staff=8))
    return provider, cycle


def test_an_observer_window_may_touch_but_not_overlap_by_one_second(api):
    """PRD §3.4: "Observation windows are treated as half-open intervals that include their
    start and exclude their end, so an existing visit that ends exactly at the new
    `window_start` does not conflict."
    PRD §3.4: "On top of the geometric overlap, a 48-hour cool-down buffer applies only when
    the conflicting existing visit belongs to the same provider: the request is refused when
    the new `window_start` falls earlier than the existing visit's `window_end` plus 48
    hours. A violation of either the overlap test or the same-provider buffer is
    `ERR_OBSERVER_SCHEDULE_CONFLICT` with HTTP 409."
    PRD §3.4: "A visit that survives all of this is created in `SCHEDULED` with
    `rescore_count` at 0, with `composite` and `reliability_pct` null, and with `finalized_on`
    null, and the cycle advances `DOCS_VERIFIED → OBSERVATION_SCHEDULED`."

    Design: Corner/validations/p41_observer_half_open_touch_allowed_then_one_second_overlap_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_domains()
    _, cycle_a = _docs_verified_cycle("Provider A", 20)
    _, cycle_b = _docs_verified_cycle("Provider B", 24)
    _, cycle_c = _docs_verified_cycle("Provider C", 28)
    lead = create_reliable_observer("Lead Observer One", certified_until="2026-12-31")

    set_clock("2026-08-03T00:00:00Z")
    visit_a = validate_success(
        api.create_observation_visit(
            cycle_a["id"],
            create_observation_visit_payload(
                lead["id"], "2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z"
            ),
            ADMIN,
        ),
        201,
    )

    touching = validate_success(
        api.create_observation_visit(
            cycle_b["id"],
            create_observation_visit_payload(
                lead["id"], "2026-08-10T17:00:00Z", "2026-08-10T21:00:00Z"
            ),
            ADMIN,
        ),
        201,
    )
    assert touching["status"] == "SCHEDULED", (
        "a start at the excluded end of the first window does not overlap, and the 48-hour "
        "buffer applies only to visits of the same provider"
    )
    assert touching["rescore_count"] == 0
    assert touching["composite"] is None
    assert touching["reliability_pct"] is None
    assert validate_success(api.get_rating_cycle(cycle_b["id"], ADMIN))["status"] == (
        "OBSERVATION_SCHEDULED"
    )

    validate_error(
        api.create_observation_visit(
            cycle_c["id"],
            create_observation_visit_payload(
                lead["id"], "2026-08-10T16:59:59Z", "2026-08-10T18:00:00Z"
            ),
            ADMIN,
        ),
        "ERR_OBSERVER_SCHEDULE_CONFLICT",
        409,
    )
    assert validate_success(api.get_rating_cycle(cycle_c["id"], ADMIN))["status"] == (
        "DOCS_VERIFIED"
    ), "a refused visit leaves its cycle unscheduled"

    rows, meta = validate_paginated(
        api.list_observation_visits(ADMIN, params={"lead_observer_id": lead["id"]})
    )
    assert meta["total_count"] == 2, (
        f"only the two accepted visits exist, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {visit_a["id"], touching["id"]}


def test_two_coaching_sessions_that_only_touch_still_conflict(api):
    """PRD §3.9: "Coaching intervals are treated as **closed** intervals that include both
    endpoints, so two sessions that merely touch at an endpoint do conflict — the opposite
    convention from observation windows, and deliberately so, because a coach cannot
    physically leave one classroom and enter another in the same instant."
    PRD §3.9: "Independently of geometry, an aggregate weekly capacity test applies: the sum
    of `scheduled_hours` over all the provider's sessions in `SCHEDULED` plus
    `delivered_hours` over all its sessions in `DELIVERED`, taken across all of that
    provider's allocations that share the new session's `iso_week_key`, plus the new session's
    own `scheduled_hours`, must not be strictly greater than the provider's
    `weekly_onsite_cap_hours`. A failure of either test is `ERR_ONSITE_CAPACITY_CONFLICT` with
    HTTP 409."
    PRD §3.9: "An accepted session is created in `SCHEDULED`, adds its hours to the
    allocation's `scheduled_hours`, and subtracts them from the allocation's
    `remaining_hours`."

    Design: Corner/validations/p42_closed_interval_touching_sessions_conflict_under_weekly_cap
    """
    ctx = setup_tier_one_active_spine(
        provider_overrides={
            "legal_name": "Closed Interval Care",
            "licensed_capacity": 30,
            "active_staff_fte": 1.00,
            "weekly_onsite_cap_hours": 12,
        }
    )
    provider_id = ctx["provider"]["id"]
    provider = validate_success(api.get_provider(provider_id, ADMIN))
    assert provider["status"] == "ACTIVE"
    assert float(provider["weekly_onsite_cap_hours"]) == pytest.approx(12.0, abs=0.05)

    allocation = create_allocation(
        provider_id,
        COACH_USER_ID,
        funding_source="STATE_BASE",
        funding_grant_id=None,
        period_start="2026-09-01",
        period_end="2026-09-30",
        allocated_hours=10.0,
        hourly_rate_cents=10_000,
    )
    allocation = validate_success(
        api.accept_coaching_allocation(allocation["id"], make_provider_headers(provider_id))
    )
    assert allocation["status"] == "ACTIVE"

    first = validate_success(
        api.create_coaching_session(
            allocation["id"],
            {"scheduled_start": "2026-09-14T09:00:00Z",
             "scheduled_end": "2026-09-14T12:00:00Z"},
            TEST_USERS["coach_headers"],
        ),
        201,
    )
    assert first["status"] == "SCHEDULED"
    assert float(first["scheduled_hours"]) == pytest.approx(3.0, abs=0.05)
    assert first["iso_week_key"] == "2026-W38"

    validate_error(
        api.create_coaching_session(
            allocation["id"],
            {"scheduled_start": "2026-09-14T12:00:00Z",
             "scheduled_end": "2026-09-14T14:00:00Z"},
            TEST_USERS["coach_headers"],
        ),
        "ERR_ONSITE_CAPACITY_CONFLICT",
        409,
    )

    after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(after["scheduled_hours"]) == pytest.approx(3.0, abs=0.05), (
        "the refused session commits no hours, even though 3.0 plus 2.0 is far under the "
        f"weekly cap of 12, got {after['scheduled_hours']}"
    )
    assert float(after["remaining_hours"]) == pytest.approx(7.0, abs=0.05)
    assert after["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_coaching_sessions(
            ADMIN, params={"coaching_allocation_id": allocation["id"],
                           "iso_week_key": "2026-W38"}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the first session survived, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]
