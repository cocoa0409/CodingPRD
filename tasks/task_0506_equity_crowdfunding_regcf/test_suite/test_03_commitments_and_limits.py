"""Placing commitments: deadline, OCC, annual-limit, per-investor cap, oversubscription,
priority conflicts, boundary precision, and derived-field reconciliation.

Queue-A: priority_pair_validation_conflict, boundary_precision_check, OCC (cross-cutting).
Queue-B: validations + calculations + cross_cutting corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_issuer_headers, make_investor_headers, make_compliance_officer_headers,
    create_offering_payload, create_investment_payload,
    create_verified_issuer, create_accredited_investor, create_investor,
    create_live_offering, set_clock, commit,
    setup_committed_offering, setup_funded_offering,
    api_client,
)

CO = make_compliance_officer_headers()


def _commit_raw(api, offering, investor_id, amount_cents, expected_version):
    """Direct create_investment with an explicit expected_offering_version."""
    return api.create_investment(
        create_investment_payload(offering["id"], investor_id, expected_version, amount_cents=amount_cents),
        headers=make_investor_headers(investor_id))


# ============================================================================
# Deadline gate (queue B validations)
# ============================================================================

def test_commit_after_deadline_returns_deadline_passed(api):
    """PRD §3.4: "first the offering deadline — the logical clock must be strictly before the
    offering's `deadline_at`, else `ERR_OFFERING_DEADLINE_PASSED`".

    Design: Corner/validations/commit_after_deadline_returns_deadline_passed
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Dl Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=100_000,
                                    max_target_cents=1_000_000, deadline_at="2026-07-01T00:00:00Z")
    fresh = validate_success(api.get_offering(offering["id"], headers=make_issuer_headers(issuer["id"])))
    set_clock("2026-08-01T00:00:00Z")  # past deadline
    resp = _commit_raw(api, offering, investor["id"], 200_000, fresh["version"])
    validate_error(resp, ApiErrorId.ERR_OFFERING_DEADLINE_PASSED, expected_status=409)


# ============================================================================
# OCC stale-version (queue B cross-cutting)
# ============================================================================

def test_stale_offering_version_on_commit_returns_412(api):
    """PRD §2.7: "If that value does not equal the target offering's current `version` at the
    moment the commitment is processed, the create is rejected with `ERR_STALE_OFFERING_VERSION`
    and HTTP status 412".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_offering_version_on_commit_returns_412
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Oc Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=2_000_000)
    v0 = validate_success(api.get_offering(offering["id"], headers=make_issuer_headers(issuer["id"])))["version"]
    # First commit succeeds at v0 and bumps the version.
    validate_success(_commit_raw(api, offering, investor["id"], 200_000, v0), expected_status=201)
    # Second commit re-using the pre-bump version is stale.
    resp = _commit_raw(api, offering, investor["id"], 200_000, v0)
    validate_error(resp, ApiErrorId.ERR_STALE_OFFERING_VERSION, expected_status=412)


def test_correct_offering_version_on_commit_succeeds_and_bumps(api):
    """PRD §2.7: "a commitment request must declare the offering version the investor last
    observed."
    PRD §3.4: "On a successful commit, the new investment is recorded, the offering's
    `committed_amount_cents` is recomputed as the sum of `amount_cents` over its investments in
    `COMMITTED` or `RECONFIRMED` status ... and the offering's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_offering_version_on_commit_succeeds
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Ok Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=2_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    investment = validate_success(_commit_raw(api, offering, investor["id"], 200_000, v0),
                                  expected_status=201)
    assert investment["status"] == "COMMITTED"
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["committed_amount_cents"] == 200_000
    assert after["version"] == v0 + 1


# ============================================================================
# Annual limit + accredited bypass (queue B calculations)
# ============================================================================

def test_accredited_bypass_skips_annual_limit(api):
    """PRD §3.4: "The **annual-limit check** applies only to an `UNACCREDITED` investor; an
    `ACCREDITED` investor bypasses it entirely with no upper bound."

    Design: Corner/calculations/accredited_bypass_skips_annual_limit
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Ab Co")
    # Tiny income -> unaccredited limit would be the $2,500 floor; but accredited bypasses.
    investor = create_accredited_investor(annual_income_cents=1_000_000, net_worth_cents=1_000_000)
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=10_000_000)
    v0 = validate_success(api.get_offering(offering["id"], headers=make_issuer_headers(issuer["id"])))["version"]
    investment = validate_success(_commit_raw(api, offering, investor["id"], 5_000_000, v0),
                                  expected_status=201)
    assert investment["status"] == "COMMITTED"
    assert investment["amount_cents"] == 5_000_000


def test_trailing_window_excludes_cancelled_commitment(api):
    """PRD §3.4: "the system sums the investor's gross `amount_cents` across all of that investor's
    investments — spanning every offering — that are in `COMMITTED`, `RECONFIRMED`, or `ISSUED`
    status (commitments that were `CANCELLED` or `REFUNDED` are excluded)".

    Design: Corner/calculations/trailing_12mo_window_excludes_cancelled
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Wn Co")
    # Unaccredited, limit 500,000c (income 10,000,000 / net worth 10,000,000 -> 5% of greater).
    investor = create_investor(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=2_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    inv_headers = make_investor_headers(investor["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    first = validate_success(_commit_raw(api, offering, investor["id"], 400_000, v0), expected_status=201)
    validate_success(api.withdraw_investment(first["id"], headers=inv_headers))
    v2 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    # Cancelled 400,000 excluded -> fresh 450,000 admissible (<= 500,000 limit).
    second = validate_success(_commit_raw(api, offering, investor["id"], 450_000, v2), expected_status=201)
    assert second["status"] == "COMMITTED"
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["committed_amount_cents"] == 450_000


# ============================================================================
# Per-investor cap + oversubscription + issuer cap (queue B validations)
# ============================================================================

def test_per_investor_cap_exceeded_on_commit(api):
    """PRD §3.4: "The **per-investor cap** applies only when the offering's `per_investor_cap_cents`
    is set: the investor's cumulative commitment to *this* offering must not exceed that cap,
    otherwise the commitment is rejected with `ERR_PER_INVESTOR_CAP_EXCEEDED`."

    Design: Corner/validations/per_investor_cap_exceeded_on_commit
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Pc Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=100_000,
                                    max_target_cents=2_000_000, per_investor_cap_cents=300_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 200_000, v0), expected_status=201)
    v1 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    # cumulative 200,000 + 150,000 = 350,000 > 300,000 cap
    resp = _commit_raw(api, offering, investor["id"], 150_000, v1)
    validate_error(resp, ApiErrorId.ERR_PER_INVESTOR_CAP_EXCEEDED, expected_status=422)


def test_oversubscription_pushes_past_max_target(api):
    """PRD §3.4: "The **oversubscription check** protects the maximum target: the offering's
    `swept_amount_cents` plus its `committed_amount_cents` plus the new `amount_cents` must not
    exceed `max_target_cents`, otherwise the commitment is rejected with `ERR_OVERSUBSCRIBED`."

    Design: Corner/validations/oversubscription_pushes_past_max_target
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Os Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=200_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 150_000, v0), expected_status=201)
    v1 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    # 150,000 committed + 100,000 = 250,000 > 200,000 max
    resp = _commit_raw(api, offering, investor["id"], 100_000, v1)
    validate_error(resp, ApiErrorId.ERR_OVERSUBSCRIBED, expected_status=409)


def test_issuer_cap_exceeded_on_offering_create(api):
    """PRD §3.2: "the offering's `max_target_cents` added to the issuer's current
    trailing-twelve-month proceeds (see §3.7) must not exceed five million dollars, i.e.
    500,000,000 cents. If it would push the issuer past that ceiling, creation is rejected with
    `ERR_ISSUER_CAP_EXCEEDED`."

    Design: Corner/validations/issuer_cap_exceeded_on_offering_create
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Ic Co")
    investor = create_accredited_investor(annual_income_cents=100_000_000_000, net_worth_cents=100_000_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    # First REG_CF offering raises 480,000,000c and FUNDS (trailing 12mo proceeds basis).
    off1 = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=480_000_000,
                                deadline_at="2026-08-01T00:00:00Z")
    v0 = validate_success(api.get_offering(off1["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, off1, investor["id"], 480_000_000, v0), expected_status=201)
    validate_success(api.close_offering(off1["id"], headers=issuer_headers))
    # Second REG_CF offering: 480,000,000 + 30,000,001 = 510,000,001 > 500,000,000c cap.
    payload = create_offering_payload(issuer["id"], min_target_cents=100_000, max_target_cents=30_000_001,
                                      deadline_at="2026-12-01T00:00:00Z")
    resp = api.create_offering(payload, headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_ISSUER_CAP_EXCEEDED, expected_status=422)


def test_commit_amount_zero_returns_invalid_request(api):
    """PRD §3.4: "the gross `amount_cents` (which must be greater than zero)".

    Design: Corner/errors/amount_zero_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Z Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000)
    v0 = validate_success(api.get_offering(offering["id"], headers=make_issuer_headers(issuer["id"])))["version"]
    resp = _commit_raw(api, offering, investor["id"], 0, v0)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


# ============================================================================
# Priority-pair validation conflicts (queue A)
# ============================================================================

def test_commit_to_funded_offering_state_beats_oversubscription(api):
    """PRD §2.8: "then existence of referenced resources (`ERR_NOT_FOUND`), then whether the
    target is in a legal state for the requested transition (`ERR_INVALID_STATE`). Only after these
    structural gates pass does the system evaluate domain-specific business rules".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_commit_to_funded_offering
    """
    # FUNDED offering (min 100,000 max 200,000), funded via 150,000; a 300,000 post-close commit
    # would also oversubscribe, but ERR_INVALID_STATE (structural gate) wins.
    issuer, investor, offering, _ = setup_funded_offering(
        amount_cents=150_000,
        offering_overrides={"min_target_cents": 100_000, "max_target_cents": 200_000})
    v_funded = validate_success(
        api.get_offering(offering["id"], headers=make_issuer_headers(issuer["id"])))["version"]
    resp = _commit_raw(api, offering, investor["id"], 300_000, v_funded)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_commit_to_failed_offering_state_gate_precedes_business_checks(api):
    """PRD §2.8: "then whether the target is in a legal state for the requested transition
    (`ERR_INVALID_STATE`). Only after these structural gates pass does the system evaluate
    domain-specific business rules".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_commit_to_funded_offering
    """
    # FAILED offering (min 500,000, max 600,000) collected only 100,000 then close -> FAILED.
    # A 700,000 post-failure commit would also oversubscribe; the state gate (offering not LIVE)
    # is evaluated before the oversubscription business rule, so ERR_INVALID_STATE wins.
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="StFail Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=500_000, max_target_cents=600_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 100_000, v0), expected_status=201)
    failed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert failed["status"] == "FAILED"
    v_failed = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    resp = _commit_raw(api, offering, investor["id"], 700_000, v_failed)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_annual_limit_beats_oversubscription_on_commit(api):
    """PRD §3.4: "the create-investment workflow runs the following business checks in this order:
    first the offering deadline ... then the optimistic-concurrency guard ... then the
    annual-limit check; then the per-investor cap; then oversubscription."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_annual_limit_over_oversubscription
    """
    set_clock("2026-06-01T00:00:00Z")
    # Unaccredited small investor: income/net worth 10,000,000c -> limit 500,000c.
    small = create_investor(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    # Issuer A: offering A where small already commits 480,000c.
    issuer_a = create_verified_issuer(legal_name="Sf Co")
    off_a = create_live_offering(issuer_a["id"], min_target_cents=100_000, max_target_cents=2_000_000,
                                 deadline_at="2026-12-01T00:00:00Z")
    a_v0 = validate_success(api.get_offering(off_a["id"], headers=make_issuer_headers(issuer_a["id"])))["version"]
    validate_success(_commit_raw(api, off_a, small["id"], 480_000, a_v0), expected_status=201)
    # Issuer B: offering B with only 50,000c remaining capacity after a whale's accredited commit.
    issuer_b = create_verified_issuer(legal_name="Sf2 Co")
    whale = create_accredited_investor()
    off_b = create_live_offering(issuer_b["id"], min_target_cents=100_000, max_target_cents=9_950_000,
                                 deadline_at="2026-12-15T00:00:00Z")
    b_v0 = validate_success(api.get_offering(off_b["id"], headers=make_issuer_headers(issuer_b["id"])))["version"]
    validate_success(_commit_raw(api, off_b, whale["id"], 9_900_000, b_v0), expected_status=201)
    b_v1 = validate_success(api.get_offering(off_b["id"], headers=make_issuer_headers(issuer_b["id"])))["version"]
    # small commits 100,000c to B: annual-limit (480,000+100,000 > 500,000) AND oversubscription
    # (50,000 left) both fail -> ERR_ANNUAL_LIMIT_EXCEEDED wins (checked before oversubscription).
    resp = _commit_raw(api, off_b, small["id"], 100_000, b_v1)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_LIMIT_EXCEEDED, expected_status=422)


def test_annual_limit_checked_before_oversubscription_single_offering(api):
    """PRD §3.4: "then the annual-limit check; then the per-investor cap; then oversubscription."
    PRD §3.4: "The commitment is admissible only if that running total plus the new `amount_cents`
    is at most the investor's `annual_limit_cents`; otherwise it is rejected with
    `ERR_ANNUAL_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_annual_limit_over_oversubscription
    """
    # Unaccredited investor, limit 500,000c, on an offering with max_target 600,000c (empty).
    # A single 700,000c commit fails BOTH the annual-limit (700,000 > 500,000) and oversubscription
    # (700,000 > 600,000); annual-limit is evaluated first, so ERR_ANNUAL_LIMIT_EXCEEDED wins.
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="SfSingle Co")
    investor = create_investor(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=600_000)
    v0 = validate_success(api.get_offering(offering["id"], headers=make_issuer_headers(issuer["id"])))["version"]
    resp = _commit_raw(api, offering, investor["id"], 700_000, v0)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_LIMIT_EXCEEDED, expected_status=422)


# ============================================================================
# Boundary precision (queue A)
# ============================================================================

def test_min_target_met_exactly_on_close_funds(api):
    """PRD §3.6: "A close is permitted only when the offering's `swept_amount_cents` plus the gross
    of the close batch is at least `min_target_cents`; if the cumulative swept total cannot reach
    the minimum, the close is rejected with `ERR_MINIMUM_NOT_MET`."

    Design: Difficulty/boundary_precision_check/min_target_met_exactly_on_close
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Bd Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=500_000, max_target_cents=1_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 500_000, v0), expected_status=201)
    closed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert closed["status"] == "FUNDED"
    assert closed["swept_amount_cents"] == 500_000


def test_min_target_one_cent_short_close_fails(api):
    """PRD §3.6: "A close is permitted only when the offering's `swept_amount_cents` plus the gross
    of the close batch is at least `min_target_cents`; if the cumulative swept total cannot reach
    the minimum, the close is rejected with `ERR_MINIMUM_NOT_MET`."
    PRD §3.6: "When a final close is attempted but the minimum is not met, the offering instead
    moves to `FAILED` per §3.5."

    Design: Difficulty/boundary_precision_check/min_target_met_exactly_on_close
    """
    # One cent below the minimum (499,999c < 500,000c min): the final close cannot fund -> FAILED.
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Bd2 Co")
    investor = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=500_000, max_target_cents=1_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 499_999, v0), expected_status=201)
    closed = validate_success(api.close_offering(offering["id"], headers=issuer_headers))
    assert closed["status"] == "FAILED"
    assert closed["swept_amount_cents"] == 0


def test_annual_limit_exact_equality_admitted_on_commit(api):
    """PRD §3.4: "The commitment is admissible only if that running total plus the new
    `amount_cents` is at most the investor's `annual_limit_cents`; otherwise it is rejected with
    `ERR_ANNUAL_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/annual_limit_exact_equality_admitted_on_commit
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Eq Co")
    # Unaccredited, limit 500,000c.
    investor = create_investor(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=2_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 400_000, v0), expected_status=201)
    v1 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    # cumulative 400,000 + 100,000 = 500,000 == limit -> admitted.
    second = validate_success(_commit_raw(api, offering, investor["id"], 100_000, v1), expected_status=201)
    assert second["status"] == "COMMITTED"
    assert second["amount_cents"] == 100_000
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["committed_amount_cents"] == 500_000


def test_annual_limit_one_cent_over_rejected_on_commit(api):
    """PRD §3.4: "The commitment is admissible only if that running total plus the new
    `amount_cents` is at most the investor's `annual_limit_cents`; otherwise it is rejected with
    `ERR_ANNUAL_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/annual_limit_exact_equality_admitted_on_commit
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Eq2 Co")
    # Unaccredited, limit 500,000c.
    investor = create_investor(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=2_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, investor["id"], 400_000, v0), expected_status=201)
    v1 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    # cumulative 400,000 + 100,001 = 500,001 > 500,000 limit -> first rejected amount.
    resp = _commit_raw(api, offering, investor["id"], 100_001, v1)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_LIMIT_EXCEEDED, expected_status=422)


# ============================================================================
# Derived-field reconciliation (queue B cross-cutting)
# ============================================================================

def test_committed_amount_reconciles_after_two_commits(api):
    """PRD §3.4: "the offering's `committed_amount_cents` is recomputed as the sum of
    `amount_cents` over its investments in `COMMITTED` or `RECONFIRMED` status, the escrow
    account's `held_amount_cents` is recomputed by the same rule (so that escrow held always equals
    the offering's committed amount)".

    Design: Corner/cross_cutting_complexity_layers/derived_committed_amount_reconciles_after_two_commits
    """
    set_clock("2026-06-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Dr Co")
    inv_a = create_accredited_investor()
    inv_b = create_accredited_investor()
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=2_000_000)
    issuer_headers = make_issuer_headers(issuer["id"])
    v0 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, inv_a["id"], 200_000, v0), expected_status=201)
    v1 = validate_success(api.get_offering(offering["id"], headers=issuer_headers))["version"]
    validate_success(_commit_raw(api, offering, inv_b["id"], 300_000, v1), expected_status=201)
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["committed_amount_cents"] == 500_000
    escrow = validate_success(api.get_escrow(offering["id"], headers=issuer_headers))[0]
    assert escrow["held_amount_cents"] == 500_000
    assert escrow["disbursed_amount_cents"] == 0
