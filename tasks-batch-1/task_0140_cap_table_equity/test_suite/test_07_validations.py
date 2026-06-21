"""Business-rule validations: 409A compliance, wrong class type, seniority
cycle, authorized-share overflow, exercisable cap, locked-table guard, expired
valuation, stale-version OCC, grant-has-exercises.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_cap_table,
    create_security_class,
    create_shareholder,
    create_effective_valuation,
    create_option_pool,
    create_active_grant,
    lock_cap_table,
    issue_shares,
    set_clock,
    api_client,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["administrator_headers"]
APPROVER = TEST_USERS["board_approver_headers"]


# ============================================================================
# Corner/validations/grant_409a_noncompliant_strike_below_fmv
# ============================================================================

def test_grant_strike_below_fmv_409a_noncompliant(api):
    """PRD §3.6: "the `strike_price_cents` must be at least the
    `fmv_per_share_cents` of the grant's valuation, which itself must be
    `EFFECTIVE`; a strike below that fair-market value, or a valuation that is not
    effective, is rejected with `ERR_409A_NONCOMPLIANT` (HTTP 422)."

    EFFECTIVE valuation fmv=100, strike=90 → ERR_409A_NONCOMPLIANT.

    Design: Corner/validations/grant_409a_noncompliant_strike_below_fmv
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@nc.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=10_000)
    resp = api.create_option_grant({
        "cap_table_id": ct["id"], "option_pool_id": pool["id"], "shareholder_id": sh["id"],
        "security_class_id": common["id"], "valuation_id": val["id"], "share_count": 1000,
        "strike_price_cents": 90, "grant_date": "2025-02-01T00:00:00Z",
        "vesting_months": 48, "cliff_months": 12,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_409A_NONCOMPLIANT.value)


# ============================================================================
# Corner/validations/grant_target_must_be_common_wrong_class_type
# ============================================================================

def test_grant_target_preferred_class_wrong_class_type(api):
    """PRD §3.6: "The class named by `security_class_id` must be a `COMMON` class
    — naming a preferred class is rejected with `ERR_WRONG_CLASS_TYPE` (HTTP 422)."

    Grant targeting a PREFERRED class → ERR_WRONG_CLASS_TYPE.

    Design: Corner/validations/grant_target_must_be_common_wrong_class_type
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    pref = create_security_class(ct["id"], name="Series A", class_type="PREFERRED",
                                 original_issue_price_cents=1000,
                                 liquidation_pref_multiple=1.0, participating=False)
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@w.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2025-01-01T00:00:00Z",
                                     expires_at="2025-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=10_000)
    resp = api.create_option_grant({
        "cap_table_id": ct["id"], "option_pool_id": pool["id"], "shareholder_id": sh["id"],
        "security_class_id": pref["id"], "valuation_id": val["id"], "share_count": 1000,
        "strike_price_cents": 1000, "grant_date": "2025-02-01T00:00:00Z",
        "vesting_months": 48, "cliff_months": 12,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_WRONG_CLASS_TYPE.value)


# ============================================================================
# Corner/validations/issuance_exceeds_authorized_shares
# ============================================================================

def test_issuance_exceeds_authorized_shares(api):
    """PRD §3.3: "the issuance must not overflow the charter, meaning the
    requested `share_count` added to the cap table's current `issued_shares` must
    not exceed the table's `authorized_shares`, otherwise the request is rejected
    with `ERR_AUTHORIZED_EXCEEDED` (HTTP 422)."

    authorized 1,000,000; issue 1,000,001 → ERR_AUTHORIZED_EXCEEDED.

    Design: Corner/validations/issuance_exceeds_authorized_shares
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Fnd", holder_type="FOUNDER", email="f@auth.com")
    resp = api.create_share_issuance({
        "cap_table_id": ct["id"], "security_class_id": common["id"], "shareholder_id": sh["id"],
        "share_count": 1_000_001, "price_paid_cents": 0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_AUTHORIZED_EXCEEDED.value)


# ============================================================================
# Corner/validations/exercise_exceeds_vested_returns_error
# ============================================================================

def test_exercise_exceeds_vested_rejected(api):
    """PRD §3.8: "if the grant's `early_exercise_allowed` is false, the exercise's
    `share_count` may not exceed the grant's currently `vested_shares` (net of
    shares already exercised) ... A request that exceeds the exercisable amount is
    rejected with `ERR_EXCEEDS_EXERCISABLE` (HTTP 422)."

    Grant 12000, cliff 12mo, clock at grant_date (0 vested), no early exercise;
    exercising 5000 → ERR_EXCEEDS_EXERCISABLE.

    Design: Corner/validations/exercise_exceeds_vested_returns_error
    """
    set_clock("2025-01-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@ex.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2024-06-01T00:00:00Z",
                                     expires_at="2030-06-01T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=12000, strike_price_cents=100,
                                grant_date="2025-01-01T00:00:00Z",
                                early_exercise_allowed=False)
    resp = api.create_exercise({
        "cap_table_id": ct["id"], "option_grant_id": grant["id"], "share_count": 5000,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EXCEEDS_EXERCISABLE.value)


# ============================================================================
# Corner/validations/issuance_on_locked_table_rejected
# ============================================================================

def test_issuance_on_locked_table_rejected(api):
    """PRD §3.3: "the cap table must be `OPEN` — issuing onto a `LOCKED` or
    `DISSOLVED` table is rejected with `ERR_TABLE_NOT_OPEN` (HTTP 409)."

    LOCKED table, attempt issuance → ERR_TABLE_NOT_OPEN.

    Design: Corner/validations/issuance_on_locked_table_rejected
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Fnd", holder_type="FOUNDER", email="f@lk.com")
    lock_cap_table(ct["id"])
    resp = api.create_share_issuance({
        "cap_table_id": ct["id"], "security_class_id": common["id"], "shareholder_id": sh["id"],
        "share_count": 100, "price_paid_cents": 0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TABLE_NOT_OPEN.value)


# ============================================================================
# Corner/validations/grant_under_expired_valuation_rejected
# ============================================================================

def test_grant_under_expired_valuation_rejected(api):
    """PRD §3.6: "the chosen valuation must not be expired relative to the grant:
    the valuation's `expires_at` must be on or after the `grant_date`, otherwise
    the draft is rejected with `ERR_VALUATION_EXPIRED` (HTTP 422)."

    Valuation expires_at 2024-12-31, grant_date 2025-06-01 (after) →
    ERR_VALUATION_EXPIRED.

    Design: Corner/validations/grant_under_expired_valuation_rejected
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@exp.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2024-01-01T00:00:00Z",
                                     expires_at="2024-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=10_000)
    resp = api.create_option_grant({
        "cap_table_id": ct["id"], "option_pool_id": pool["id"], "shareholder_id": sh["id"],
        "security_class_id": common["id"], "valuation_id": val["id"], "share_count": 1000,
        "strike_price_cents": 100, "grant_date": "2025-06-01T00:00:00Z",
        "vesting_months": 48, "cliff_months": 12,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALUATION_EXPIRED.value)


# ============================================================================
# Corner/errors/stale_version_on_captable_lock
# ============================================================================

def test_captable_lock_with_stale_version_rejected(api):
    """PRD §2.6: "Locking a cap table requires `expected_cap_table_version` to
    match the target cap table's current `version`. Any issuance, grant approval,
    or valuation approval bumps the table's version, so a lock carrying a stale
    value is acting on an outdated snapshot and is rejected."

    Observe v0, issuance bumps version, lock with stale v0 → ERR_STALE_VERSION.

    Design: Corner/errors/stale_version_on_captable_lock
    """
    ct = create_cap_table(authorized_shares=1_000_000)
    v0 = ct["version"]
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Fnd", holder_type="FOUNDER", email="f@sl.com")
    issue_shares(ct["id"], common["id"], sh["id"], 100, price_paid_cents=0)
    resp = api.lock_cap_table(ct["id"], {"expected_cap_table_version": v0}, APPROVER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ============================================================================
# Corner/errors/grant_cancel_with_settled_exercises_rejected
# ============================================================================

def test_grant_cancel_with_settled_exercises_rejected(api):
    """PRD §3.6: "Cancelling a grant that is `ACTIVE` is permitted only when its
    `exercised_shares` is exactly zero; if any shares have already been exercised,
    the cancellation is rejected with `ERR_GRANT_HAS_EXERCISES` (HTTP 409)."

    ACTIVE grant with one settled exercise of 400 → cancel rejected.

    Design: Corner/errors/grant_cancel_with_settled_exercises_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON")
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE", email="e@he.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2020-01-01T00:00:00Z",
                                     expires_at="2030-12-31T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_active_grant(ct["id"], pool["id"], sh["id"], common["id"], val["id"],
                                share_count=1000, strike_price_cents=100,
                                grant_date="2020-01-01T00:00:00Z")
    ex = get_success_data(api.create_exercise({
        "cap_table_id": ct["id"], "option_grant_id": grant["id"], "share_count": 400,
    }, ADMIN))
    get_success_data(api.settle_exercise(ex["id"], ADMIN))
    resp = api.cancel_option_grant(grant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_GRANT_HAS_EXERCISES.value)
