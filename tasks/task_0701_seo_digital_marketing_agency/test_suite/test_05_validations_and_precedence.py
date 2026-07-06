"""Validation precedence, cross-entity state gates, numeric boundaries, temporal overlap.

Covers queue A priority_pair_validation_conflict, cross_entity_state_dependency,
boundary_precision_check, and resource_temporal_overlap instances, plus the queue B
validations corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_assign_cancelled_deliverable_reports_invalid_state_over_credits(api):
    """PRD §2.7: "(6) that the target resource is in a state that permits the
    requested transition, failing with `ERR_INVALID_STATE`".
    PRD §2.7: "Only after all seven of these pass does the platform evaluate the
    endpoint's specific business rules (cross-entity preconditions, capacity, credits,
    dispute, budget, temporal, and uniqueness checks), which are described in §3 next
    to the workflows they guard."
    PRD §2.7: "The earlier a check sits in this list, the higher its precedence; a
    higher-priority failure masks every lower-priority one."

    Assigning an already-CANCELLED deliverable on a retainer with too few credits
    fails the state check (priority 6) which masks the credits business rule ->
    ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/assign_invalid_state_beats_insufficient_credits
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"tier": "STARTER", "monthly_credits": 2,
                            "wholesale_price_cents": 100000},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",  # cost 3 > 2 granted
    )
    validate_success(api.cancel_deliverable(deliverable["id"], AM))
    fresh = validate_success(api.get_retainer(retainer["id"], ADMIN))
    resp = api.assign_deliverable(
        deliverable["id"], {"expected_retainer_version": fresh["version"]}, AM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_deliverable(deliverable["id"], ADMIN))
    assert after["status"] == "CANCELLED", f"status unchanged, got {after['status']}"


def test_assign_cancelled_deliverable_leaves_credits_untouched(api):
    """PRD §3.6: "Assigning a `DRAFT` deliverable is the credit-reservation step".
    PRD §2.7: "a higher-priority failure masks every lower-priority one."

    Because the assign is masked by the state check, no credits are reserved: the
    retainer's credits_committed stays 0.

    Design: Difficulty/priority_pair_validation_conflict/assign_invalid_state_beats_insufficient_credits
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"tier": "STARTER", "monthly_credits": 2,
                            "wholesale_price_cents": 100000},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",
    )
    validate_success(api.cancel_deliverable(deliverable["id"], AM))
    fresh = validate_success(api.get_retainer(retainer["id"], ADMIN))
    api.assign_deliverable(
        deliverable["id"], {"expected_retainer_version": fresh["version"]}, AM
    )
    after = validate_success(api.get_retainer(retainer["id"], ADMIN))
    assert after["credits_committed"] == 0


def test_assign_on_suspended_retainer_with_low_credits_is_rejected(api):
    """PRD §3.6: "Assigning a `DRAFT` deliverable is the credit-reservation step and
    the second site of the optimistic-concurrency check (§2.8): it requires the
    retainer to be `ACTIVE` (else `ERR_RETAINER_NOT_ACTIVE`), the sprint to be
    `PLANNING` or `ACTIVE`, the retainer's `credits_available` to be at least the
    deliverable's `credit_cost` (else `ERR_INSUFFICIENT_CREDITS`), the sprint's
    `committed_credits` plus the new `credit_cost` to be at most the sprint's
    `capacity_credits` (else `ERR_SPRINT_CAPACITY_EXCEEDED`), and
    `expected_retainer_version` to match the retainer's current `version` (else
    `ERR_STALE_RETAINER_VERSION`)."

    Assigning a DRAFT deliverable (cost 3) whose retainer is SUSPENDED and has only 2
    credits is rejected as a business-rule failure. The PRD orders these requirements
    in prose but §2.7 does not pin a precedence between the two business rules, so the
    test accepts either business-rule error.

    Design: Difficulty/priority_pair_validation_conflict/assign_retainer_not_active_beats_insufficient_credits
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"tier": "STARTER", "monthly_credits": 2,
                            "wholesale_price_cents": 100000},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",
    )
    suspended = validate_success(api.suspend_retainer(retainer["id"], AM))
    resp = api.assign_deliverable(
        deliverable["id"], {"expected_retainer_version": suspended["version"]}, AM
    )
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_RETAINER_NOT_ACTIVE.value,
         ApiErrorId.ERR_INSUFFICIENT_CREDITS.value],
    )


def test_assign_on_suspended_retainer_leaves_deliverable_draft(api):
    """PRD §3.6: "On success, assignment moves the deliverable to `ASSIGNED`".
    PRD §3.4: "while a retainer is `SUSPENDED`, creation of new deliverables against
    it is blocked".

    The rejected assign leaves the deliverable in DRAFT and reserves no credits.

    Design: Difficulty/priority_pair_validation_conflict/assign_retainer_not_active_beats_insufficient_credits
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"tier": "STARTER", "monthly_credits": 2,
                            "wholesale_price_cents": 100000},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",
    )
    suspended = validate_success(api.suspend_retainer(retainer["id"], AM))
    api.assign_deliverable(
        deliverable["id"], {"expected_retainer_version": suspended["version"]}, AM
    )
    after = validate_success(api.get_deliverable(deliverable["id"], ADMIN))
    assert after["status"] == "DRAFT", f"deliverable must stay DRAFT, got {after['status']}"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_deliverable_assign_requires_active_retainer(api):
    """PRD §3.6: "Assigning a `DRAFT` deliverable is the credit-reservation step and
    the second site of the optimistic-concurrency check (§2.8): it requires the
    retainer to be `ACTIVE` (else `ERR_RETAINER_NOT_ACTIVE`), the sprint to be
    `PLANNING` or `ACTIVE`, the retainer's `credits_available` to be at least the
    deliverable's `credit_cost` (else `ERR_INSUFFICIENT_CREDITS`)".

    A SUSPENDED retainer (with ample credits and capacity) still rejects assign with
    ERR_RETAINER_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/deliverable_assign_requires_retainer_active
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",
    )
    suspended = validate_success(api.suspend_retainer(retainer["id"], AM))
    resp = api.assign_deliverable(
        deliverable["id"], {"expected_retainer_version": suspended["version"]}, AM
    )
    validate_error(resp, ApiErrorId.ERR_RETAINER_NOT_ACTIVE.value)


def test_deliverable_assign_on_suspended_retainer_reserves_no_credits(api):
    """PRD §3.6: "On success, assignment moves the deliverable to `ASSIGNED`, adds the
    `credit_cost` to the retainer's `credits_committed` and recomputes
    `credits_available`, adds the same amount to the sprint's `committed_credits`, and
    increments the deliverable's `version` (and the retainer's `version`, per the
    reservation against it)."
    PRD §3.6: "it requires the retainer to be `ACTIVE` (else
    `ERR_RETAINER_NOT_ACTIVE`)".

    A rejected assign against a SUSPENDED retainer reserves nothing:
    credits_committed stays 0.

    Design: Difficulty/cross_entity_state_dependency/deliverable_assign_requires_retainer_active
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",
    )
    suspended = validate_success(api.suspend_retainer(retainer["id"], AM))
    api.assign_deliverable(
        deliverable["id"], {"expected_retainer_version": suspended["version"]}, AM
    )
    after = validate_success(api.get_retainer(retainer["id"], ADMIN))
    assert after["credits_committed"] == 0


def test_keyword_tracking_requires_client_audited(api):
    """PRD §3.2: "A keyword target moves `PLANNED → TRACKING` when an account manager
    activates tracking, which is permitted only while the parent client is `AUDITED`
    or `ACTIVE` — otherwise the request is rejected with `ERR_CLIENT_NOT_AUDITED`".

    A PROSPECT client rejects activate-tracking with ERR_CLIENT_NOT_AUDITED.

    Design: Difficulty/cross_entity_state_dependency/keyword_tracking_requires_client_audited
    """
    client = fixtures.create_prospect_client(
        company_name="XdepB Co", primary_domain="xdepb.example"
    )
    kw = get_success_data(
        api.create_keyword_target(
            factories.create_keyword_target_payload(
                client_id=client["id"], phrase="seo services",
                search_volume=800, difficulty=30,
            ),
            AM,
        )
    )
    resp = api.activate_tracking(kw["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_AUDITED.value)


def test_keyword_tracking_blocked_leaves_status_planned(api):
    """PRD §3.2: "Creation computes a `priority_score`, initializes `current_rank` to
    0 and `best_rank` to 0, and starts the target in `PLANNED` `status`."
    PRD §3.2: "permitted only while the parent client is `AUDITED` or `ACTIVE` —
    otherwise the request is rejected with `ERR_CLIENT_NOT_AUDITED`".

    The rejected activate-tracking leaves the keyword in PLANNED.

    Design: Difficulty/cross_entity_state_dependency/keyword_tracking_requires_client_audited
    """
    client = fixtures.create_prospect_client(
        company_name="XdepB2 Co", primary_domain="xdepb2.example"
    )
    kw = get_success_data(
        api.create_keyword_target(
            factories.create_keyword_target_payload(
                client_id=client["id"], phrase="seo services",
                search_volume=800, difficulty=30,
            ),
            AM,
        )
    )
    api.activate_tracking(kw["id"], AM)
    after = validate_success(api.get_keyword_target(kw["id"], AM))
    assert after["status"] == "PLANNED", f"keyword must stay PLANNED, got {after['status']}"


# ---------------------------------------------------------------------------
# boundary_precision_check
# ---------------------------------------------------------------------------
def test_record_spend_exactly_at_budget_succeeds(api):
    """PRD §3.7: "Spend is recorded against a campaign by supplying an `amount_cents`
    to add; the new spend may not push `spent_cents` above `budget_cents`, else
    `ERR_BUDGET_EXCEEDED`."

    Budget 500000c, already spent 499999c; recording 1c brings spent_cents to exactly
    500000 (== budget) and succeeds.

    Design: Difficulty/boundary_precision_check/record_spend_at_budget_boundary
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        499999,
        campaign_overrides={"channel": "BING", "budget_cents": 500000},
        retainer_overrides={"tier": "STARTER", "monthly_credits": 10,
                            "wholesale_price_cents": 100000},
    )
    ok = validate_success(api.record_spend(campaign["id"], {"amount_cents": 1}, AM))
    assert ok["spent_cents"] == 500000, (
        f"spend exactly to budget should succeed, got spent {ok['spent_cents']}"
    )


def test_record_spend_one_cent_over_budget_rejected(api):
    """PRD §3.7: "the new spend may not push `spent_cents` above `budget_cents`, else
    `ERR_BUDGET_EXCEEDED`."

    With spent_cents already at the budget of 500000c, recording one more cent
    (501000... here 500001 > 500000) is rejected with ERR_BUDGET_EXCEEDED.

    Design: Difficulty/boundary_precision_check/record_spend_at_budget_boundary
    """
    client, retainer, campaign = fixtures.setup_live_campaign_with_spend(
        499999,
        campaign_overrides={"channel": "BING", "budget_cents": 500000},
        retainer_overrides={"tier": "STARTER", "monthly_credits": 10,
                            "wholesale_price_cents": 100000},
    )
    validate_success(api.record_spend(campaign["id"], {"amount_cents": 1}, AM))
    resp = api.record_spend(campaign["id"], {"amount_cents": 1}, AM)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)


def test_gbp_optimization_score_below_active_client_is_75(api):
    """PRD §3.9: "The `optimization_score` is a completeness score out of 100,
    awarding twenty-five points for each of four signals: twenty-five if
    `location_name` is non-empty, twenty-five if `service_area` is non-empty,
    twenty-five if the listing's `status` is `VERIFIED` or `OPTIMIZED`, and
    twenty-five if the parent client's `status` is `ACTIVE`."

    A VERIFIED listing whose client is only AUDITED scores 25+25+25+0 = 75.

    Design: Difficulty/boundary_precision_check/gbp_optimize_score_threshold_and_empty_status_edge
    """
    client = fixtures.create_audited_client(
        company_name="Gbp Co", primary_domain="gbp.example"
    )
    listing = fixtures.create_verified_gbp_listing(
        client["id"], location_name="Main St", service_area="Downtown"
    )
    assert listing["optimization_score"] == 75, (
        f"AUDITED-client VERIFIED listing should score 75, "
        f"got {listing['optimization_score']}"
    )


def test_gbp_optimize_rejected_below_threshold(api):
    """PRD §3.9: "Optimizing a `VERIFIED` listing moves it to `OPTIMIZED`, but only
    when its `optimization_score` is at least 80 — a listing below that threshold is
    rejected with `ERR_OPTIMIZATION_THRESHOLD_NOT_MET`".

    A listing scoring 75 (< 80) is rejected and stays VERIFIED.

    Design: Difficulty/boundary_precision_check/gbp_optimize_score_threshold_and_empty_status_edge
    """
    client = fixtures.create_audited_client(
        company_name="Gbp2 Co", primary_domain="gbp2.example"
    )
    listing = fixtures.create_verified_gbp_listing(
        client["id"], location_name="Main St", service_area="Downtown"
    )
    resp = api.optimize_gbp_listing(listing["id"], AM)
    validate_error(resp, ApiErrorId.ERR_OPTIMIZATION_THRESHOLD_NOT_MET.value)

    after = validate_success(api.get_gbp_listing(listing["id"], ADMIN))
    assert after["status"] == "VERIFIED", f"listing must stay VERIFIED, got {after['status']}"


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_sprint_window_overlap_on_same_retainer_rejected(api):
    """PRD §3.6: "Sprint windows for the same retainer may not overlap: treat each
    window as the half-open interval from `starts_at` up to but not including
    `ends_at`, so two sprints that touch exactly — where one ends at the instant the
    other begins — are adjacent and allowed, but any genuine overlap against another
    `PLANNING` or `ACTIVE` sprint of the same retainer is rejected with
    `ERR_SPRINT_WINDOW_OVERLAP`."

    A second sprint starting 2026-04-15 (inside [04-01, 05-01)) overlaps the first ->
    ERR_SPRINT_WINDOW_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/sprint_window_half_open_overlap_on_same_retainer
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    get_success_data(
        api.create_sprint(
            factories.create_sprint_payload(
                client_id=client["id"], retainer_id=retainer["id"], name="Apr",
                starts_at="2026-04-01T00:00:00Z", ends_at="2026-05-01T00:00:00Z",
                capacity_credits=20,
            ),
            AM,
        )
    )
    resp = api.create_sprint(
        factories.create_sprint_payload(
            client_id=client["id"], retainer_id=retainer["id"], name="Mid",
            starts_at="2026-04-15T00:00:00Z", ends_at="2026-05-15T00:00:00Z",
            capacity_credits=20,
        ),
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_SPRINT_WINDOW_OVERLAP.value)


def test_sprint_window_adjacent_on_same_retainer_allowed(api):
    """PRD §3.6: "two sprints that touch exactly — where one ends at the instant the
    other begins — are adjacent and allowed".

    A second sprint starting exactly at the first's `ends_at` (2026-05-01) is adjacent
    under half-open semantics and is accepted.

    Design: Difficulty/resource_temporal_overlap/sprint_window_half_open_overlap_on_same_retainer
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    get_success_data(
        api.create_sprint(
            factories.create_sprint_payload(
                client_id=client["id"], retainer_id=retainer["id"], name="Apr",
                starts_at="2026-04-01T00:00:00Z", ends_at="2026-05-01T00:00:00Z",
                capacity_credits=20,
            ),
            AM,
        )
    )
    adjacent = validate_success(
        api.create_sprint(
            factories.create_sprint_payload(
                client_id=client["id"], retainer_id=retainer["id"], name="May",
                starts_at="2026-05-01T00:00:00Z", ends_at="2026-06-01T00:00:00Z",
                capacity_credits=20,
            ),
            AM,
        ),
        expected_status=201,
    )
    assert adjacent["id"]


def test_report_period_within_buffer_rejected(api):
    """PRD §3.3: "a new `period_start` must be strictly greater than the prior
    period's `period_end` plus one day, and a new `period_end` must be strictly less
    than the next period's `period_start` minus one day. Periods that touch or fall
    within the one-day buffer are rejected with `ERR_REPORT_PERIOD_OVERLAP`".

    Prior period [2026-04-01, 2026-04-30]; a new period starting 2026-05-01 is exactly
    prior_end + 1 day (not strictly greater) -> ERR_REPORT_PERIOD_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/report_period_closed_buffer_overlap_on_same_client
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    get_success_data(
        api.create_report(
            client["id"],
            {"period_start": "2026-04-01T00:00:00Z",
             "period_end": "2026-04-30T00:00:00Z"},
            AM,
        )
    )
    resp = api.create_report(
        client["id"],
        {"period_start": "2026-05-01T00:00:00Z",
         "period_end": "2026-05-31T00:00:00Z"},
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value)


def test_report_period_outside_buffer_allowed(api):
    """PRD §3.3: "a new `period_start` must be strictly greater than the prior
    period's `period_end` plus one day".

    Prior period [2026-04-01, 2026-04-30]; a new period starting 2026-05-02 is
    strictly greater than prior_end + 1 day (2026-05-01) and is accepted.

    Design: Difficulty/resource_temporal_overlap/report_period_closed_buffer_overlap_on_same_client
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    get_success_data(
        api.create_report(
            client["id"],
            {"period_start": "2026-04-01T00:00:00Z",
             "period_end": "2026-04-30T00:00:00Z"},
            AM,
        )
    )
    ok = validate_success(
        api.create_report(
            client["id"],
            {"period_start": "2026-05-02T00:00:00Z",
             "period_end": "2026-05-31T00:00:00Z"},
            AM,
        ),
        expected_status=201,
    )
    assert ok["id"]


# ---------------------------------------------------------------------------
# queue B validations corner instances
# ---------------------------------------------------------------------------
def test_duplicate_keyword_phrase_per_client_rejected(api):
    """PRD §3.2: "The `phrase` must be unique among the client's keyword targets that
    are not `DROPPED`; a colliding phrase is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_keyword_phrase_per_client
    """
    client = fixtures.create_prospect_client(
        company_name="Dup Co", primary_domain="dup.example"
    )
    get_success_data(
        api.create_keyword_target(
            factories.create_keyword_target_payload(
                client_id=client["id"], phrase="duplicate me",
                search_volume=100, difficulty=30,
            ),
            AM,
        )
    )
    resp = api.create_keyword_target(
        factories.create_keyword_target_payload(
            client_id=client["id"], phrase="duplicate me",
            search_volume=200, difficulty=40,
        ),
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_sprint_window_end_before_start_rejected(api):
    """PRD §3.6: "The window must satisfy `ends_at` strictly after `starts_at`, else
    `ERR_INVALID_SPRINT_WINDOW`."

    Design: Corner/validations/invalid_sprint_window_end_before_start
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    resp = api.create_sprint(
        factories.create_sprint_payload(
            client_id=client["id"], retainer_id=retainer["id"], name="Bad",
            starts_at="2026-05-01T00:00:00Z", ends_at="2026-04-01T00:00:00Z",
            capacity_credits=20,
        ),
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SPRINT_WINDOW.value)


def test_churn_blocked_by_binding_contract(api):
    """PRD §3.1: "Churning a client is terminal and is permitted from either `ACTIVE`
    or `PAUSED`. It is blocked while the client still has any `Contract` in `ACTIVE`
    or `RENEWED` status — such a contract must be terminated first, and a premature
    churn is rejected with `ERR_CONTRACT_STILL_BINDING`."

    Design: Corner/validations/churn_blocked_by_binding_contract
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    fixtures.create_active_contract(client["id"], retainer["id"], term_cycles=6)
    resp = api.churn_client(client["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_STILL_BINDING.value)

    after = validate_success(api.get_client(client["id"], ADMIN))
    assert after["status"] == "ACTIVE", f"client must stay ACTIVE, got {after['status']}"
