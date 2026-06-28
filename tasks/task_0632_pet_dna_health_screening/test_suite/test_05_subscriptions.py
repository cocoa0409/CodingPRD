"""Subscription creation, the single-active-subscription rule, BASIC->PREMIUM
upgrade proration, OCC on upgrade, expiry, and the active_subscription_id pointer.

Covers queue A (compensating_invariant proration, resource_temporal_overlap
single subscription) and queue B (cross_cutting OCC upgrade, errors upgrade-not-
allowed, state_machines expire-not-elapsed, consistency_model pointer,
derived_field_reconciliation indirectly via account fields).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    TEST_USERS,
    setup_active_basic_subscription,
    setup_active_premium_subscription,
)
from test_helpers.fixtures import set_clock
from test_helpers.factories import (
    create_subscription_payload,
    upgrade_subscription_payload,
)
from test_helpers.test_users import make_account_headers

ADMIN = TEST_USERS["platform_admin_headers"]


# =========================================================================
# compensating_invariant: upgrade proration conserves premium fee (queue A)
# =========================================================================

def test_upgrade_proration_charge_is_12469(api):
    """PRD §3.7: "The unused credit in cents is the basic subscription's
    `annual_fee_cents` multiplied by the remaining days, divided by the basic
    `term_days`, floored to a whole cent. The successor's `last_charge_cents` is
    the premium annual fee of 19900 cents minus that unused credit."

    Design: Difficulty/compensating_invariant/upgrade_proration_conserves_premium_fee_cents
    """
    base = setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z")
    sub = base["subscription"]
    acct_h = make_account_headers(base["account"]["id"])
    set_clock("2026-04-02T00:00:00Z")  # 91 days elapsed

    resp = api.upgrade_subscription(sub["id"], upgrade_subscription_payload(sub["version"]), acct_h)
    successor = validate_success(resp)
    assert successor["last_charge_cents"] == 12469, \
        f"prorated charge must be 12469, got {successor['last_charge_cents']}"


def test_upgrade_supersedes_original_subscription(api):
    """PRD §3.7: "On success the original subscription moves from `ACTIVE` to
    `SUPERSEDED`, a successor subscription is created at tier `PREMIUM` in
    `ACTIVE` status with a prorated `last_charge_cents`"

    Design: Difficulty/compensating_invariant/upgrade_proration_conserves_premium_fee_cents
    """
    base = setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z")
    sub = base["subscription"]
    acct_h = make_account_headers(base["account"]["id"])
    set_clock("2026-04-02T00:00:00Z")

    api.upgrade_subscription(sub["id"], upgrade_subscription_payload(sub["version"]), acct_h)
    original = validate_success(api.get_subscription(sub["id"], acct_h))
    assert original["status"] == "SUPERSEDED", \
        f"original must be SUPERSEDED, got {original['status']}"


# =========================================================================
# resource_temporal_overlap: single ACTIVE/GRACE subscription per account (queue A)
# =========================================================================

def test_second_subscription_create_rejected(api):
    """PRD §3.7: "An account may hold only one subscription that is `ACTIVE` or
    `GRACE` at a time; a second create while such a subscription exists is
    rejected with `ERR_SUBSCRIPTION_EXISTS`."

    Design: Difficulty/resource_temporal_overlap/account_single_active_subscription_term_overlap
    """
    base = setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z")
    acct_h = make_account_headers(base["account"]["id"])

    resp = api.create_subscription(
        create_subscription_payload(base["account"]["id"], tier="PREMIUM",
                                    annual_fee_cents=19900),
        acct_h,
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_EXISTS.value)


def test_second_subscription_does_not_replace_active_pointer(api):
    """PRD §3.7: "Creating the subscription sets the account's
    `active_subscription_id` to the new subscription. An account may hold only one
    subscription that is `ACTIVE` or `GRACE` at a time"

    Design: Difficulty/resource_temporal_overlap/account_single_active_subscription_term_overlap
    """
    base = setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z")
    acct_h = make_account_headers(base["account"]["id"])

    api.create_subscription(
        create_subscription_payload(base["account"]["id"], tier="PREMIUM",
                                    annual_fee_cents=19900),
        acct_h,
    )
    account = validate_success(api.get_account(base["account"]["id"], acct_h))
    assert account["active_subscription_id"] == base["subscription"]["id"], \
        "active_subscription_id must still point at the first subscription"


# =========================================================================
# Corner: OCC upgrade stale subscription (cross_cutting_complexity_layers)
# =========================================================================

def test_upgrade_with_stale_version_after_cancel_rejected(api):
    """PRD §2.9: "If another writer has advanced that subscription's `version`
    since the client last read it — for instance because the subscription was
    already cancelled, moving it from `ACTIVE` to `GRACE`, or already upgraded,
    moving it from `ACTIVE` to `SUPERSEDED` — then the upgrade is acting on a
    stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_upgrade_stale_subscription_returns_412
    """
    base = setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z")
    sub = base["subscription"]
    acct_h = make_account_headers(base["account"]["id"])
    stale_version = sub["version"]

    # A cancel bumps the version past the value read above.
    api.cancel_subscription(sub["id"], acct_h)

    # PRD §2.9 names this exact scenario (cancel moving ACTIVE->GRACE, then a
    # stale-version upgrade) as ERR_STALE_VERSION. But §2.8 fixes a priority
    # order in which the state precondition (ERR_INVALID_STATE, priority 5)
    # is evaluated strictly before the optimistic-concurrency version check
    # (ERR_STALE_VERSION, last). The two sentences are in genuine tension: a
    # faithful PRD-only implementer could land on either, since after the cancel
    # the subscription is in GRACE (from which upgrade is undefined) AND the
    # supplied version is stale. Accept either member of the set.
    resp = api.upgrade_subscription(sub["id"], upgrade_subscription_payload(stale_version), acct_h)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


# =========================================================================
# Corner: upgrade premium subscription rejected (errors)
# =========================================================================

def test_upgrade_premium_subscription_rejected(api):
    """PRD §3.7: "an upgrade on a non-`BASIC` subscription, or one requesting any
    tier other than `PREMIUM`, is rejected with `ERR_UPGRADE_NOT_ALLOWED`."

    Design: Corner/errors/upgrade_premium_subscription_returns_upgrade_not_allowed
    """
    base = setup_active_premium_subscription(annual_fee_cents=19900, clock="2026-01-01T00:00:00Z")
    sub = base["subscription"]
    acct_h = make_account_headers(base["account"]["id"])

    resp = api.upgrade_subscription(sub["id"], upgrade_subscription_payload(sub["version"]), acct_h)
    validate_error(resp, ApiErrorId.ERR_UPGRADE_NOT_ALLOWED.value)


# =========================================================================
# Corner: expire grace subscription before term (state_machines)
# =========================================================================

def test_expire_grace_subscription_before_term_rejected(api):
    """PRD §3.7: "An expire requested before the clock has reached `started_on`
    plus `term_days` is rejected with `ERR_GRACE_NOT_ELAPSED`."

    Design: Corner/state_machines/expire_grace_subscription_before_term_returns_grace_not_elapsed
    """
    base = setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z")
    sub = base["subscription"]
    acct_h = make_account_headers(base["account"]["id"])
    api.cancel_subscription(sub["id"], acct_h)  # ACTIVE -> GRACE

    set_clock("2026-06-01T00:00:00Z")  # < 2026-01-01 + 365 days
    resp = api.expire_subscription(sub["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_GRACE_NOT_ELAPSED.value)

    fetched = validate_success(api.get_subscription(sub["id"], acct_h))
    assert fetched["status"] == "GRACE", f"subscription must stay GRACE, got {fetched['status']}"


# =========================================================================
# Corner: immediate active_subscription_id pointer (consistency_model)
# =========================================================================

def test_active_subscription_pointer_immediately_visible(api):
    """PRD §3.7: "Creating the subscription sets the account's
    `active_subscription_id` to the new subscription."

    Design: Corner/consistency_model/immediate_visibility_of_active_subscription_pointer
    """
    base = setup_active_basic_subscription(annual_fee_cents=9900, clock="2026-01-01T00:00:00Z")
    acct_h = make_account_headers(base["account"]["id"])

    account = validate_success(api.get_account(base["account"]["id"], acct_h))
    assert account["active_subscription_id"] == base["subscription"]["id"], \
        "active_subscription_id must immediately reflect the new subscription"
