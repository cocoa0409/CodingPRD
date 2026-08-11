"""Referral creation, vesting, lapse, and the operator-driven daily batch."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_referral,
    assert_same_instant,
    list_credits_of,
    list_referrals,
    make_account_holder_headers,
    make_child,
    make_plan,
    make_sku,
    make_subscription,
    read_account,
    read_subscription,
    register_account,
    register_and_verify_account,
    set_clock,
    setup_allocated_cycle,
    unique_code,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    activate,
    allocate_cycle,
    charge_cycle,
    dispatch_cycle,
    generate_cycle,
    lock_cycle,
)

OPS = TEST_USERS["ops_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _referrer_and_referee_with_a_dispatched_cycle(api, *, signup_clock, dispatch_clock,
                                                  email_prefix):
    """Referrer A, referee B signed up on A's code, and B's first cycle dispatched."""
    set_clock(api, signup_clock)
    plan = make_plan(api)
    make_sku(api, code=unique_code("S2-STD"))

    referrer = register_and_verify_account(
        api, email=unique_email(f"{email_prefix}-a"), payment_method_on_file=True
    )
    referee = register_and_verify_account(
        api,
        email=unique_email(f"{email_prefix}-b"),
        payment_method_on_file=True,
        referred_by_code=referrer["referral_code"],
    )
    child = make_child(api, referee, name="Kai", birth_date="2026-02-01")
    subscription = make_subscription(api, referee, plan, child)
    subscription = activate(api, referee["id"], subscription["id"])

    cycle = generate_cycle(api, subscription["id"])
    allocate_cycle(api, cycle["id"])
    set_clock(api, dispatch_clock)
    lock_cycle(api, cycle["id"])
    charge_cycle(api, cycle["id"])
    dispatch_cycle(api, cycle["id"])
    return referrer, referee, cycle


# ==========================================================================
# Vesting is tied to delivery
# ==========================================================================
def test_a_referral_stays_pending_until_the_referees_box_is_delivered(api):
    """PRD §3.11: "Vesting is tied to actual delivery, never to signup and never to dispatch.
    A `PENDING` referral vests when a cycle belonging to a subscription of the referee's
    account reaches `DELIVERED`, provided no earlier cycle of that account has ever reached
    `DELIVERED` — it is the referee's *first* real delivery that counts"
    PRD §3.11: "Vesting sets `status` to `VESTED`, stamps `vested_at` with the logical clock,
    records `vesting_cycle_id` as the delivering cycle, and sets `credit_cents`. That amount is
    normally 1500 cents."

    Design: Difficulty/cross_entity_state_dependency/referral_vests_on_delivery_not_on_dispatch
    """
    referrer, referee, cycle = _referrer_and_referee_with_a_dispatched_cycle(
        api, signup_clock="2026-06-01T00:00:00Z",
        dispatch_clock="2026-06-08T00:00:00Z", email_prefix="ref",
    )
    pending = list_referrals(api, referee_account_id=referee["id"])
    assert len(pending) == 1
    assert pending[0]["status"] == "PENDING", "a dispatched box has not been delivered"

    validate_success(api.deliver_cycle(cycle["id"], OPS))

    vested = validate_success(api.get_referral(pending[0]["id"], OPS))
    assert_referral(vested)
    assert vested["status"] == "VESTED"
    assert vested["credit_cents"] == 1500
    assert vested["vesting_cycle_id"] == cycle["id"]


def test_vesting_issues_the_referral_credit_on_the_referrers_account(api):
    """PRD §3.11: "Vesting then issues a `Credit` of `credit_type` `REFERRAL` on the
    *referrer's* account, with `refundable` true, `expires_at` 365 days after the logical
    clock, and `source_referral_id` naming the referral, and recomputes the referrer's
    `available_credit_cents`."

    Design: Difficulty/cross_entity_state_dependency/referral_vests_on_delivery_not_on_dispatch
    """
    referrer, referee, cycle = _referrer_and_referee_with_a_dispatched_cycle(
        api, signup_clock="2026-06-01T00:00:00Z",
        dispatch_clock="2026-06-08T00:00:00Z", email_prefix="ref2",
    )
    validate_success(api.deliver_cycle(cycle["id"], OPS))

    assert read_account(api, referrer["id"])["available_credit_cents"] == 1500
    credits = list_credits_of(api, referrer["id"], credit_type="REFERRAL")
    assert len(credits) == 1
    assert credits[0]["issued_cents"] == 1500
    assert credits[0]["refundable"] is True


# ==========================================================================
# The promotional window is measured at the vesting instant
# ==========================================================================
def test_a_delivery_inside_the_promotional_window_doubles_the_referral_credit(api):
    """PRD §3.11: "During a promotional window it doubles to 3000 cents: the window is
    half-open, running from `2026-11-01T00:00:00Z` inclusive up to `2026-12-01T00:00:00Z`
    exclusive, and it is measured against the *vesting* instant, not the signup instant — a
    referral created before the window that delivers inside it earns the doubled amount."

    Design: Difficulty/dual_variant_calc/referral_credit_promo_window_doubles_at_vesting_instant
    """
    referrer, referee, cycle = _referrer_and_referee_with_a_dispatched_cycle(
        api, signup_clock="2026-10-20T00:00:00Z",
        dispatch_clock="2026-11-02T00:00:00Z", email_prefix="promo",
    )
    validate_success(api.deliver_cycle(cycle["id"], OPS))

    referrals = list_referrals(api, referee_account_id=referee["id"])
    assert len(referrals) == 1
    assert referrals[0]["status"] == "VESTED"
    assert referrals[0]["credit_cents"] == 3000, (
        "the vesting instant 2026-11-02 sits inside the half-open promotional window"
    )
    assert referrals[0]["vesting_cycle_id"] == cycle["id"]


def test_the_doubled_amount_is_what_the_referrer_actually_receives(api):
    """PRD §3.11: "Vesting then issues a `Credit` of `credit_type` `REFERRAL` on the
    *referrer's* account, with `refundable` true, `expires_at` 365 days after the logical
    clock, and `source_referral_id` naming the referral, and recomputes the referrer's
    `available_credit_cents`."
    PRD §3.11: "That amount is normally 1500 cents. During a promotional window it doubles to
    3000 cents"

    Design: Difficulty/dual_variant_calc/referral_credit_promo_window_doubles_at_vesting_instant
    """
    referrer, _referee, cycle = _referrer_and_referee_with_a_dispatched_cycle(
        api, signup_clock="2026-10-20T00:00:00Z",
        dispatch_clock="2026-11-02T00:00:00Z", email_prefix="promo2",
    )
    validate_success(api.deliver_cycle(cycle["id"], OPS))

    credits = list_credits_of(api, referrer["id"], credit_type="REFERRAL")
    assert len(credits) == 1
    assert credits[0]["issued_cents"] == 3000
    assert credits[0]["refundable"] is True
    assert read_account(api, referrer["id"])["available_credit_cents"] == 3000


# ==========================================================================
# The three policy rungs guarding referral creation
# ==========================================================================
def test_a_self_referral_is_refused(api):
    """PRD §3.1: "a referral whose `referrer_account_id` equals its `referee_account_id` is
    refused with `ERR_SELF_REFERRAL` (HTTP 422)"

    Design: Corner/errors/corner_self_referral_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("selfref"))
    resp = api.create_referral(
        {
            "referrer_account_id": account["id"],
            "referee_account_id": account["id"],
            "code": account["referral_code"],
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_SELF_REFERRAL.value, 422)
    assert not list_referrals(api, referrer_account_id=account["id"])


def test_a_mirrored_referral_is_refused(api):
    """PRD §3.1: "a referral that would mirror an existing one — where a `Referral` already
    exists whose referrer is this referee and whose referee is this referrer — is refused with
    `ERR_RECIPROCAL_REFERRAL` (HTTP 422)"

    Design: Corner/errors/corner_reciprocal_referral_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    first = register_and_verify_account(api, email=unique_email("recipA"))
    second = register_and_verify_account(api, email=unique_email("recipB"))
    validate_success(
        api.create_referral(
            {
                "referrer_account_id": first["id"],
                "referee_account_id": second["id"],
                "code": first["referral_code"],
            },
            OPS,
        ),
        201,
    )

    resp = api.create_referral(
        {
            "referrer_account_id": second["id"],
            "referee_account_id": first["id"],
            "code": second["referral_code"],
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_RECIPROCAL_REFERRAL.value, 422)

    _referrals, meta = validate_paginated(api.list_referrals(OPS, {"limit": 100}))
    assert meta["total_count"] == 1


def test_the_sixth_referral_inside_the_period_is_refused(api):
    """PRD §3.1: "and a referrer who already holds five or more `Referral` rows in *any*
    status created within the trailing 365 days is refused with `ERR_REFERRAL_CAP_EXCEEDED`
    (HTTP 409). The cap is enforced at creation, never at vesting."
    PRD §3.11: "the specification nevertheless pins that the five-per-365-days cap is enforced
    at referral *creation* rather than at vesting, so that it is observable as a rejection on
    the sixth referral created"

    Design: Corner/errors/corner_referral_cap_exceeded_on_sixth_referral
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    referrer = register_and_verify_account(api, email=unique_email("capA"))
    referees = [register_account(api, email=unique_email(f"capB{i}")) for i in range(6)]

    for referee in referees[:5]:
        validate_success(
            api.create_referral(
                {
                    "referrer_account_id": referrer["id"],
                    "referee_account_id": referee["id"],
                    "code": referrer["referral_code"],
                },
                OPS,
            ),
            201,
        )

    resp = api.create_referral(
        {
            "referrer_account_id": referrer["id"],
            "referee_account_id": referees[5]["id"],
            "code": referrer["referral_code"],
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_REFERRAL_CAP_EXCEEDED.value, 409)

    assert len(list_referrals(api, referrer_account_id=referrer["id"])) == 5


def test_lapsing_a_referral_before_after_and_then_again(api):
    """PRD §3.11: "an `expires_at` sitting 120 days after the referral's creation"
    PRD §3.11: "A referral that never delivers lapses instead: an operator may expire a
    `PENDING` referral once the logical clock is strictly past its `expires_at`, moving it
    `PENDING → EXPIRED` with no credit ever issued. Requesting that lapse on a referral that is
    not `PENDING` is refused with `ERR_REFERRAL_STATE_INVALID` (HTTP 409), and requesting it
    before `expires_at` has passed is refused with `ERR_REFERRAL_WINDOW_EXPIRED`."

    Design: Corner/state_machines/corner_expire_referral_before_window_then_after_then_again
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    referrer = register_and_verify_account(api, email=unique_email("lapseA"))
    referee = register_and_verify_account(api, email=unique_email("lapseB"))
    referral = validate_success(
        api.create_referral(
            {
                "referrer_account_id": referrer["id"],
                "referee_account_id": referee["id"],
                "code": referrer["referral_code"],
            },
            OPS,
        ),
        201,
    )
    assert_same_instant(referral["expires_at"], "2026-09-29T00:00:00Z", "Referral.expires_at")

    validate_error(
        api.expire_referral(referral["id"], OPS),
        ApiErrorId.ERR_REFERRAL_WINDOW_EXPIRED.value,
        409,
    )

    set_clock(api, "2026-10-01T00:00:00Z")
    expired = validate_success(api.expire_referral(referral["id"], OPS))
    assert expired["status"] == "EXPIRED"

    validate_error(
        api.expire_referral(referral["id"], OPS),
        ApiErrorId.ERR_REFERRAL_STATE_INVALID.value,
        409,
    )

    after = validate_success(api.get_referral(referral["id"], OPS))
    assert after["credit_cents"] == 0
    _credits, meta = validate_paginated(
        api.list_credits(
            make_account_holder_headers(referrer["id"]),
            {"source_referral_id": referral["id"]},
        )
    )
    assert meta["total_count"] == 0


# ==========================================================================
# The daily batch and the descent into delinquency
# ==========================================================================
def test_a_delinquent_subscription_may_not_generate_another_cycle(api):
    """PRD §3.7: "The descent into delinquency is a batch matter: when a `PAST_DUE`
    subscription still has an `UNCHARGED` cycle whose `ship_date` is more than 14 days before
    the logical clock, the daily batch moves it `PAST_DUE → DELINQUENT`, which blocks any
    further cycle generation."
    PRD §3.5: "A subscription whose `billing_state` is `DELINQUENT` may not generate a cycle at
    all and is refused with `ERR_SUBSCRIPTION_DELINQUENT` (HTTP 409)."

    Design: Corner/validations/corner_delinquent_subscription_cannot_generate_a_cycle
    """
    ctx, cycle = setup_allocated_cycle(
        api, email_prefix="delinq", account_overrides={"payment_method_on_file": False}
    )
    validate_error(
        api.charge_cycle(cycle["id"], OPS), ApiErrorId.ERR_NO_PAYMENT_METHOD.value, 402
    )

    set_clock(api, "2026-06-23T00:00:00Z")
    report = validate_success(api.run_daily_jobs(OPS))
    assert report["delinquent_subscriptions"] == 1

    assert read_subscription(api, ctx["subscription"]["id"])["billing_state"] == "DELINQUENT"

    resp = api.generate_cycle(ctx["subscription"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_DELINQUENT.value, 409)

    _cycles, meta = validate_paginated(
        api.list_cycles(OPS, {"subscription_id": ctx["subscription"]["id"], "limit": 100})
    )
    assert meta["total_count"] == 1
