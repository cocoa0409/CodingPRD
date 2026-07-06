"""Validation ordering, business guards, optimistic concurrency, temporal
overlap, and RBAC (PRD §2.6, §2.7, §3).

Difficulty queue: priority_pair_validation_conflict (state-vs-segregation,
existence-vs-mandate), cross_entity_state_dependency (account activate, rebalance
approve), resource_temporal_overlap (fee-run overlap, review date collision).
Corner queue: validation violations, error catalogue, RBAC denials, OCC.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, api_client as api,
    TEST_USERS, make_advisor_headers, make_compliance_headers, make_billing_headers,
    build_user_headers, fixtures as fx, factories as f,
    ApiErrorId, FABRICATED_UUID,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / state_beats_segregation_on_ips_approve
# ===========================================================================
def test_state_check_beats_segregation_on_ips_approve(api):
    """PRD §2.7: "5. State legality — the target resource is in a state from which
    the requested transition is defined, else `ERR_INVALID_STATE` (409)."
    PRD §2.7: "6. Separation of duties — the policy-statement approver is not the
    proposing advisor, and the fee-run finalizer is not the run's creator, else
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    Approving a DRAFT (never-proposed) IPS: the lower-numbered state check (5)
    fires first, so ERR_INVALID_STATE, not ERR_SEGREGATION_OF_DUTIES.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_ips_approve
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips = fx.create_draft_ips(client["id"], pf["id"], max_equity_pct=80)
    resp = api.ips_state(ips["id"], "APPROVE", make_compliance_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_beats_segregation_even_for_distinct_officer(api):
    """PRD §2.7: "When several validations could apply to one request, they are
    evaluated in a fixed priority order so that the failure a client sees is
    deterministic."
    PRD §2.7: "5. State legality — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."

    A DRAFT IPS is approved by an officer distinct from the proposing advisor (so
    the segregation check WOULD pass); the state check at priority 5 still fires and
    returns ERR_INVALID_STATE because APPROVE is undefined from DRAFT.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_ips_approve
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips = fx.create_draft_ips(client["id"], pf["id"], max_equity_pct=80,
                              advisor_id="adv-1")
    resp = api.ips_state(ips["id"], "APPROVE", make_compliance_headers("co-distinct"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / existence_beats_mandate_on_ips_propose
# ===========================================================================
def test_body_fk_existence_beats_mandate_on_ips_create(api):
    """PRD §2.7: "4. Body-reference existence — every body foreign key
    (`household_id`, `client_id`, `fee_schedule_id`, `target_portfolio_id`,
    `plan_id`, `account_id`) resolves, else `ERR_REFERENCE_NOT_FOUND` (422)."
    PRD §2.7: "7. Policy-mandate safety — a policy statement's `max_equity_pct` is
    at least the target portfolio's `model_equity_pct`, and the target portfolio
    is published, else `ERR_IPS_MANDATE_VIOLATION` (422)."

    Creating an IPS naming a non-existent target_portfolio_id is rejected at body-FK
    existence (4) before any mandate check (7).

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_mandate_on_ips_propose
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    resp = api.create_ips(
        f.ips_payload(client["id"], FABRICATED_UUID, max_equity_pct=10), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_body_fk_existence_fires_even_when_mandate_would_pass(api):
    """PRD §2.7: "Body-reference existence — every body foreign key (`household_id`,
    `client_id`, `fee_schedule_id`, `target_portfolio_id`, `plan_id`, `account_id`)
    resolves, else `ERR_REFERENCE_NOT_FOUND` (422)."
    PRD §2.5: "and that referenced entity does not exist, the request is rejected
    with `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

    Here max_equity_pct=100 would satisfy any mandate, isolating that the missing
    target_portfolio_id is caught at body-FK existence (priority 4) regardless.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_mandate_on_ips_propose
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    resp = api.create_ips(
        f.ips_payload(client["id"], FABRICATED_UUID, max_equity_pct=100), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Difficulty: cross_entity_state_dependency / account_activate_requires_client_onboarded
# ===========================================================================
def test_account_activate_blocked_when_client_prospect(api):
    """PRD §3.3: "Activation moves an account from `PENDING` to `ACTIVE`; it
    requires the account be `PENDING`, the owning client's `onboarding_status` to be
    `IPS_SIGNED` or `ACTIVE`, and the owning household to be `ACTIVE`. A client not
    yet far enough along onboarding fails this cross-entity gate with
    `ERR_CROSS_ENTITY_PRECONDITION` (409)."

    Design: Difficulty/cross_entity_state_dependency/account_activate_requires_client_onboarded
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_client(hh["id"])  # PROSPECT, never KYC-verified
    acct = fx.create_account(hh["id"], client["id"], market_value_cents=100000)
    resp = api.account_state(acct["id"], "ACTIVATE", ADVISOR)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_PRECONDITION.value)


def test_account_activate_succeeds_when_client_ips_signed(api):
    """PRD §3.3: "the owning client's `onboarding_status` to be `IPS_SIGNED` or
    `ACTIVE`" permits activation. Once the client signs the IPS the same activation
    succeeds (the gate's positive branch).

    Design: Difficulty/cross_entity_state_dependency/account_activate_requires_client_onboarded
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])
    # An account in PENDING/ACTIVE must exist before SIGN_IPS lets the client go ACTIVE,
    # but SIGN_IPS itself only needs an APPROVED IPS; we activate the account afterwards.
    fx.create_approved_ips(client["id"], pf["id"], max_equity_pct=80)
    acct = fx.create_account(hh["id"], client["id"], market_value_cents=100000)
    # Sign the IPS to move the client to IPS_SIGNED.
    get_success_data(api.client_state(client["id"], "SIGN_IPS", ADVISOR))
    data = validate_success(api.account_state(acct["id"], "ACTIVATE", ADVISOR))
    assert data["status"] == "ACTIVE", \
        f"IPS_SIGNED client permits activation, got {data['status']}"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / rebalance_approve_requires_account_active
# ===========================================================================
def test_rebalance_approve_blocked_when_account_frozen(api):
    """PRD §3.7: "Approving advances it from `PROPOSED` to `APPROVED`; it requires
    the order be `PROPOSED`, the linked account be `ACTIVE` (a rebalance cannot be
    approved against a frozen or closed account), and the account's client to have a
    policy statement in `APPROVED` status — a frozen or closed account, or a client
    without an approved statement, fails with `ERR_CROSS_ENTITY_PRECONDITION` (409)."

    The order is proposed while ACTIVE, then the account is frozen before approve.

    Design: Difficulty/cross_entity_state_dependency/rebalance_approve_requires_account_active
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=1000000, equity_value_cents=1000000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    ro = fx.create_proposed_rebalance(acct["id"])
    # Freeze the account; freeze also auto-rejects PROPOSED orders, so re-propose
    # is not possible — instead create a fresh ACTIVE account flow. Per the design
    # instance, the order is proposed AFTER the account is frozen.
    # Reset: build an account, freeze it, then propose (propose has no state gate).
    setup2 = fx.setup_account_with_approved_ips(
        market_value_cents=1000000, equity_value_cents=1000000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct2 = setup2["account"]
    get_success_data(api.account_state(acct2["id"], "FREEZE", ADVISOR))
    ro2 = fx.create_proposed_rebalance(acct2["id"])
    assert ro2["status"] == "PROPOSED", "order proposed on a FROZEN account is PROPOSED"
    resp = api.rebalance_order_state(ro2["id"], "APPROVE", make_compliance_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_PRECONDITION.value)


def test_rebalance_approve_succeeds_when_account_active(api):
    """PRD §3.7: "Approving advances it from `PROPOSED` to `APPROVED`; it requires
    the order be `PROPOSED`, the linked account be `ACTIVE` (a rebalance cannot be
    approved against a frozen or closed account), and the account's client to have a
    policy statement in `APPROVED` status — a frozen or closed account, or a client
    without an approved statement, fails with `ERR_CROSS_ENTITY_PRECONDITION` (409)."

    The positive branch: an ACTIVE account whose client has an APPROVED IPS approves
    cleanly (distinguishing the FROZEN-rejection case from the legitimate path).

    Design: Difficulty/cross_entity_state_dependency/rebalance_approve_requires_account_active
    """
    setup = fx.setup_account_with_approved_ips(
        market_value_cents=1000000, equity_value_cents=800000,
        model_equity_pct=60, max_equity_pct=80, drift_tolerance_bps=500)
    acct = setup["account"]
    ro = fx.create_proposed_rebalance(acct["id"])
    data = validate_success(api.rebalance_order_state(ro["id"], "APPROVE",
                                                      make_compliance_headers("co-1")))
    assert data["status"] == "APPROVED", \
        f"ACTIVE account + APPROVED IPS permits approval, got {data['status']}"


# ===========================================================================
# Difficulty: resource_temporal_overlap / fee_run_finalize_period_range_overlap
# ===========================================================================
def test_finalize_rejects_overlapping_period_range(api):
    """PRD §3.5: "it enforces temporal non-overlap: there must be no other
    `FINALIZED` fee run for the same household whose inclusive
    `period_start`-through-`period_end` range overlaps this run's range; an overlap
    is rejected with `ERR_BILLING_PERIOD_OVERLAP` (409)."

    Q1 2026-01-01..2026-06-30 FINALIZED, then 2026-04-01..2026-09-30 (sharing
    April-June) cannot finalize.

    Design: Difficulty/resource_temporal_overlap/fee_run_finalize_period_range_overlap
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=100000000, billing_method="ARREARS")
    hh = setup["household"]
    v0 = fx.household_version(hh["id"])
    fx.create_finalized_fee_run(hh["id"], v0,
                                period_start="2026-01-01", period_end="2026-06-30")
    v1 = fx.household_version(hh["id"])
    r2 = fx.create_calculated_fee_run(hh["id"], v1,
                                      period_start="2026-04-01", period_end="2026-09-30")
    resp = api.fee_run_state(r2["id"], "FINALIZE", make_billing_headers("billing-2"))
    validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value)


def test_finalize_succeeds_for_non_overlapping_period(api):
    """PRD §3.5: "there must be no other `FINALIZED` fee run for the same household
    whose inclusive `period_start`-through-`period_end` range overlaps this run's
    range" A strictly later, non-overlapping period finalizes cleanly.

    Design: Difficulty/resource_temporal_overlap/fee_run_finalize_period_range_overlap
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=100000000, billing_method="ARREARS")
    hh = setup["household"]
    v0 = fx.household_version(hh["id"])
    fx.create_finalized_fee_run(hh["id"], v0,
                                period_start="2026-01-01", period_end="2026-06-30")
    v1 = fx.household_version(hh["id"])
    r2 = fx.create_calculated_fee_run(hh["id"], v1,
                                      period_start="2026-07-01", period_end="2026-12-31")
    data = validate_success(api.fee_run_state(r2["id"], "FINALIZE",
                                              make_billing_headers("billing-2")))
    assert data["status"] == "FINALIZED", \
        f"non-overlapping period finalizes, got {data['status']}"


# ===========================================================================
# Difficulty: resource_temporal_overlap / review_same_date_point_collision
# ===========================================================================
def test_review_same_date_collision_rejected(api):
    """PRD §3.8: "Two scheduled reviews for the same household may not share a
    `scheduled_for` date; a collision on the calendar is rejected with
    `ERR_REVIEW_DATE_COLLISION` (409)."

    Design: Difficulty/resource_temporal_overlap/review_same_date_point_collision
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    get_success_data(api.create_review(
        f.review_payload(hh["id"], scheduled_for="2026-09-01", cadence_days=365), ADVISOR))
    resp = api.create_review(
        f.review_payload(hh["id"], scheduled_for="2026-09-01", cadence_days=365), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_REVIEW_DATE_COLLISION.value)


def test_review_distinct_dates_no_collision(api):
    """PRD §3.8: "Two scheduled reviews for the same household may not share a
    `scheduled_for` date" Distinct dates are accepted (collision is on equality).

    Design: Difficulty/resource_temporal_overlap/review_same_date_point_collision
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    get_success_data(api.create_review(
        f.review_payload(hh["id"], scheduled_for="2026-09-01", cadence_days=365), ADVISOR))
    data = validate_success(api.create_review(
        f.review_payload(hh["id"], scheduled_for="2026-10-01", cadence_days=365), ADVISOR),
        expected_status=201)
    assert data["status"] == "SCHEDULED"


# ===========================================================================
# Corner: cross_cutting / occ_stale_household_version_on_fee_run_create
# ===========================================================================
def test_occ_stale_household_version_rejected(api):
    """PRD §2.6: "If they do not match — because some other writer (most commonly a
    prior fee run that finalized and bumped the household) has advanced the
    household's `version` since the client read it — the creation is rejected with
    `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_household_version_on_fee_run_create
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"], billing_method="ARREARS")
    v0 = hh["version"]
    # First create succeeds and bumps Household.version.
    get_success_data(api.create_fee_run(
        f.fee_run_payload(hh["id"], v0,
                          period_start="2026-01-01", period_end="2026-03-31"), BILLING))
    # Second create still carrying the now-stale v0 is rejected on OCC.
    resp = api.create_fee_run(
        f.fee_run_payload(hh["id"], v0,
                          period_start="2026-04-01", period_end="2026-06-30"), BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_HOUSEHOLD_VERSION.value)


# ===========================================================================
# Corner: cross_cutting / occ_correct_version_succeeds_and_bumps
# ===========================================================================
def test_occ_correct_version_creates_and_bumps_household(api):
    """PRD §3.4: "Creating the run is itself a household-level mutation and
    increments the household's `version` by one."

    Design: Corner/cross_cutting/occ_correct_version_succeeds_and_bumps
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"], billing_method="ARREARS")
    v0 = hh["version"]
    data = validate_success(api.create_fee_run(
        f.fee_run_payload(hh["id"], v0,
                          period_start="2026-01-01", period_end="2026-03-31"), BILLING),
        expected_status=201)
    assert data["status"] == "DRAFT"
    after = validate_success(api.get_household(hh["id"], BILLING))
    assert after["version"] == v0 + 1, \
        f"create bumps Household.version by 1, got {after['version']} from {v0}"


# ===========================================================================
# Corner: validations / portfolio_weights_not_sum_100_rejected
# ===========================================================================
def test_portfolio_weights_not_summing_100_rejected(api):
    """PRD §3.2: "The `target_pct` values across the sleeves must sum to exactly
    100; a portfolio whose weights do not sum to 100 is rejected with
    `ERR_ALLOCATION_INVALID` (422)."

    Design: Corner/validations/portfolio_weights_not_sum_100_rejected
    """
    resp = api.create_portfolio(
        f.portfolio_payload(target_weights=[
            {"sleeve": "EQ", "target_pct": 60},
            {"sleeve": "FI", "target_pct": 30}]), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_INVALID.value)


# ===========================================================================
# Corner: validations / account_equity_exceeds_market_rejected
# ===========================================================================
def test_account_equity_exceeds_market_rejected(api):
    """PRD §3.3: "An account whose `equity_value_cents` exceeds its
    `market_value_cents` is rejected with `ERR_ALLOCATION_INVALID` (422)."

    Design: Corner/validations/account_equity_exceeds_market_rejected
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_client(hh["id"])
    resp = api.create_account(
        f.account_payload(hh["id"], client["id"],
                          market_value_cents=1000, equity_value_cents=5000), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_INVALID.value)


# ===========================================================================
# Corner: validations / fee_run_period_end_not_after_start_rejected
# ===========================================================================
def test_fee_run_period_end_not_after_start_rejected(api):
    """PRD §3.4: "The period end must be strictly after the period start, or the
    creation is rejected with `ERR_INVALID_PERIOD` (422)."

    Design: Corner/validations/fee_run_period_end_not_after_start_rejected
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    v = hh["version"]
    resp = api.create_fee_run(
        f.fee_run_payload(hh["id"], v,
                          period_start="2026-03-31", period_end="2026-03-31"), BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value)


# ===========================================================================
# Corner: validations / ips_propose_mandate_violation_rejected
# ===========================================================================
def test_ips_propose_mandate_violation_rejected(api):
    """PRD §3.2: "it requires the statement's `max_equity_pct` to be at least the
    target portfolio's `model_equity_pct`, so that the mandate actually permits the
    model it points at — a `max_equity_pct` below the model's equity weight is
    rejected with `ERR_IPS_MANDATE_VIOLATION` (422)."

    Design: Corner/validations/ips_propose_mandate_violation_rejected
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips = fx.create_draft_ips(client["id"], pf["id"], max_equity_pct=50)
    resp = api.ips_state(ips["id"], "PROPOSE", make_advisor_headers("adv-1"))
    validate_error(resp, ApiErrorId.ERR_IPS_MANDATE_VIOLATION.value)


# ===========================================================================
# Corner: validations / ips_propose_unpublished_portfolio_rejected
# ===========================================================================
def test_ips_propose_unpublished_portfolio_rejected(api):
    """PRD §3.2: "it requires the portfolio named by `target_portfolio_id` to exist
    and have `is_published` true (a target that is unpublished is rejected with
    `ERR_PORTFOLIO_NOT_PUBLISHED`, 422)"

    Design: Corner/validations/ips_propose_unpublished_portfolio_rejected
    """
    pf = fx.create_portfolio(model_equity_pct=60)  # NOT published
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips = fx.create_draft_ips(client["id"], pf["id"], max_equity_pct=90)
    resp = api.ips_state(ips["id"], "PROPOSE", make_advisor_headers("adv-1"))
    validate_error(resp, ApiErrorId.ERR_PORTFOLIO_NOT_PUBLISHED.value)


# ===========================================================================
# Corner: validations / fee_run_segregation_finalizer_equals_creator_rejected
# ===========================================================================
def test_finalize_by_creator_rejected_segregation(api):
    """PRD §3.5: "the finalizing administrator's `X-User-ID` must differ from the
    `X-User-ID` of the administrator who created the run — the builder of a run
    cannot be its finalizer, and a self-finalization is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/validations/fee_run_segregation_finalizer_equals_creator_rejected
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=100000000, billing_method="ARREARS")
    hh = setup["household"]
    v = fx.household_version(hh["id"])
    run = fx.create_calculated_fee_run(hh["id"], v, creator_id="billing-1")
    resp = api.fee_run_state(run["id"], "FINALIZE", make_billing_headers("billing-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# Corner: errors / account_close_blocked_by_open_fee_run
# ===========================================================================
def test_account_close_blocked_by_open_fee_run(api):
    """PRD §3.3: "An account may be closed from either `ACTIVE` or `FROZEN`,
    reaching the terminal `CLOSED` state, but only when there is no fee run
    referencing the owning household in `DRAFT` or `CALCULATED` status — an account
    cannot be closed while an open fee run is in flight, and the attempt is rejected
    with `ERR_FEE_RUN_OPEN` (409)."

    Design: Corner/errors/account_close_blocked_by_open_fee_run
    """
    setup = fx.setup_household_with_active_account(
        market_value_cents=100000000, billing_method="ARREARS")
    hh = setup["household"]
    acct = setup["account"]
    v = fx.household_version(hh["id"])
    # A DRAFT (uncalculated) fee run is in flight.
    get_success_data(api.create_fee_run(f.fee_run_payload(hh["id"], v), BILLING))
    resp = api.account_state(acct["id"], "CLOSE", ADVISOR)
    validate_error(resp, ApiErrorId.ERR_FEE_RUN_OPEN.value)


# ===========================================================================
# Corner: errors / rebalance_propose_no_approved_ips
# ===========================================================================
def test_rebalance_propose_without_approved_ips_rejected(api):
    """PRD §3.7: "An account whose client has no `APPROVED` policy statement cannot
    have a rebalance proposed or approved against it; that attempt is rejected with
    `ERR_NO_APPROVED_IPS` (409)."

    Design: Corner/errors/rebalance_propose_no_approved_ips
    """
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    client = fx.create_kyc_verified_client(hh["id"])  # no APPROVED IPS
    # A client with no APPROVED IPS can never reach IPS_SIGNED (PRD §3.1), so its
    # account can never be activated (PRD §3.3). Rebalance proposal (PRD §3.7) has
    # no account-status precondition — only the approved-IPS guard — so a PENDING
    # account faithfully exercises the ERR_NO_APPROVED_IPS rejection.
    acct = fx.create_account(hh["id"], client["id"],
                             market_value_cents=1000000,
                             equity_value_cents=500000)
    resp = api.create_rebalance_order({"account_id": acct["id"]}, ADVISOR)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_IPS.value)


# ===========================================================================
# Corner: errors / duplicate_proposed_ips_rejected
# ===========================================================================
def test_duplicate_proposed_ips_rejected(api):
    """PRD §3.2: "A client may have only one statement in flight: proposing a new
    statement while the same client already has a `PROPOSED` statement is rejected
    with `ERR_DUPLICATE_APPROVED_IPS` (409)."

    Design: Corner/errors/duplicate_proposed_ips_rejected
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    fx.create_proposed_ips(client["id"], pf["id"], max_equity_pct=80)
    ips2 = fx.create_draft_ips(client["id"], pf["id"], max_equity_pct=70)
    resp = api.ips_state(ips2["id"], "PROPOSE", make_advisor_headers("adv-1"))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPROVED_IPS.value)


# ===========================================================================
# Corner: errors / compliance_satisfy_after_due_rejected
# ===========================================================================
def test_compliance_satisfy_after_due_rejected(api):
    """PRD §3.9: "Satisfying moves an item from `OPEN` to `SATISFIED`; it requires
    the item be `OPEN` and the logical clock's date to be on or before the item's
    `due_date` — an obligation may not be satisfied once it has lapsed."
    PRD §3.9: "a request that violates either one (satisfying an already-past-due
    item, or flagging an item that is not yet overdue) is rejected with
    `ERR_COMPLIANCE_NOT_DUE` (409)."

    Design: Corner/errors/compliance_satisfy_after_due_rejected
    """
    fx.set_clock("2026-03-01T00:00:00Z", headers=COMPLIANCE)
    sched = fx.create_flat_fee_schedule()
    hh = fx.create_household(sched["id"])
    item = fx.create_compliance_item("HOUSEHOLD", hh["id"],
                                     obligation_type="REG_BI_DISCLOSURE",
                                     due_date="2026-04-01")
    fx.set_clock("2026-05-01T00:00:00Z", headers=COMPLIANCE)
    resp = api.compliance_item_state(item["id"], "SATISFY", COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_DUE.value)


# ===========================================================================
# Corner: errors / pagination_limit_too_large_rejected
# ===========================================================================
def test_pagination_limit_too_large_rejected(api):
    """PRD §2.3: "A `limit` below 1, a `limit` above 100, or a negative `offset` is
    rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/errors/pagination_limit_too_large_rejected
    """
    resp = api.list_households(ADVISOR, params={"limit": 500, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


# ===========================================================================
# Corner: rbac / advisor_cannot_create_fee_schedule
# ===========================================================================
def test_advisor_cannot_create_fee_schedule(api):
    """PRD §2.1: "A `BillingAdmin` owns the fee mechanics: creating fee schedules,
    creating and progressing fee runs, and setting the logical clock."
    PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/advisor_cannot_create_fee_schedule
    """
    resp = api.create_fee_schedule(f.flat_fee_schedule_payload(), ADVISOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner: rbac / advisor_cannot_approve_ips_segregation_role
# ===========================================================================
def test_advisor_cannot_approve_ips(api):
    """PRD §2.1: "A `ComplianceOfficer` provides independent oversight: approving or
    requesting changes to policy statements, approving or rejecting rebalances, and
    managing and archiving compliance obligations."
    PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/advisor_cannot_approve_ips_segregation_role
    """
    pf = fx.create_published_portfolio(model_equity_pct=60)
    hh = fx.create_household()
    client = fx.create_kyc_verified_client(hh["id"])
    ips = fx.create_proposed_ips(client["id"], pf["id"], max_equity_pct=80)
    resp = api.ips_state(ips["id"], "APPROVE", make_advisor_headers("adv-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner: rbac / missing_auth_headers_unauthenticated
# ===========================================================================
def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    bad_headers = build_user_headers("nobody-1", "Nobody")
    resp = api.list_households(bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
