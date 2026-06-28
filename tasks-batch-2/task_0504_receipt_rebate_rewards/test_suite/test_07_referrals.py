"""Referral invite lifecycle: sign-up linking, expiry, duplicate guard, the
not-qualified reward guard, and the qualified-reward cascade to the referrer.

Translates corner `state_machines`, `errors`, and `cross_cutting` referral
instances.
"""
from test_helpers import (
    validate_success, validate_error, api_client, TEST_USERS, make_member_headers,
    ApiErrorId,
    create_member, set_clock, get_member,
    create_referral, setup_qualified_referral,
)

_PA = TEST_USERS["platform_admin_headers"]
_FA = TEST_USERS["finance_admin_headers"]


def test_referral_signup_links_referee(api):
    """PRD §3.7: "When a member registers naming this referrer and with an email
    matching `referee_email`, and no other referral for that email is already past
    invited, the referral moves `INVITED` to `SIGNED_UP` and its
    `referee_member_id` is set to the new member."

    Design: Corner/state_machines/referral_signup_links_referee
    """
    referrer = create_member("referrer@x.com")
    referral = create_referral(referrer["id"], "newbie@x.com")
    newbie = validate_success(api.create_member(
        {"email": "newbie@x.com", "referred_by_member_id": referrer["id"]}, _PA), 201)
    updated = validate_success(api.get_referral(referral["id"], _FA))
    assert updated["status"] == "SIGNED_UP"
    assert updated["referee_member_id"] == newbie["id"]


def test_invited_referral_expires_on_clock_advance(api):
    """PRD §3.7: "a referral that is never accepted expires: when the clock reaches
    the referral's creation instant plus the platform-wide referral expiry window
    ... while it is still `INVITED`, it transitions `INVITED` to `EXPIRED`."

    Design: Corner/state_machines/invited_referral_expires_on_clock_advance
    """
    referrer = create_member("rr@x.com")
    referral = create_referral(referrer["id"], "ghost@x.com")
    set_clock("2027-01-01T00:00:00Z")  # well past any referral expiry window
    expired = validate_success(api.get_referral(referral["id"], _FA))
    assert expired["status"] == "EXPIRED"


def test_duplicate_referral_for_email_rejected(api):
    """PRD §3.7: "A referral may not be created for a `referee_email` that already
    has a referral past the invited stage - if one already exists in `SIGNED_UP`,
    `QUALIFIED`, or `REWARDED`, creation is rejected with `ERR_DUPLICATE_REFERRAL`
    (HTTP 409)."

    Design: Corner/errors/duplicate_referral_for_email_rejected
    """
    referrer = create_member("rer@x.com")
    hdr = make_member_headers(referrer["id"])
    create_referral(referrer["id"], "dup@x.com")
    validate_success(api.create_member(
        {"email": "dup@x.com", "referred_by_member_id": referrer["id"]}, _PA), 201)  # -> SIGNED_UP
    resp = api.create_referral(
        {"referrer_member_id": referrer["id"], "referee_email": "dup@x.com"}, hdr)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REFERRAL)


def test_reward_unqualified_referral_rejected(api):
    """PRD §3.7: "rewarding requires the referral's `status` to be `QUALIFIED` (else
    `ERR_REFERRAL_NOT_QUALIFIED`, HTTP 409)".

    Design: Corner/errors/reward_unqualified_referral_rejected
    """
    referrer = create_member("un@x.com")
    referral = create_referral(referrer["id"], "pending@x.com")  # stays INVITED
    resp = api.reward_referral(referral["id"], _FA)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_QUALIFIED)


def test_reward_qualified_referral_credits_referrer(api):
    """PRD §3.7: "Rewarding cascades in three steps: step one creates a reward claim
    for the **referrer** with `ONLINE` attribution, `amount_cents` equal to the
    referral's `bonus_cents`, and status `AVAILABLE` (already matured, not pending);
    step two emits a `REFERRAL_BONUS` ledger entry for that positive `bonus_cents`;
    step three raises the referrer's available balance by `bonus_cents`."

    Design: Corner/cross_cutting_complexity_layers/cascade_referral_reward_credits_referrer
    """
    referrer_id, referee_id, referral_id = setup_qualified_referral(
        referee_qualifying_cents=1000, bonus_cents=500)
    rewarded = validate_success(api.reward_referral(referral_id, _FA))
    assert rewarded["status"] == "REWARDED"
    referrer_now = get_member(referrer_id)
    assert referrer_now["available_balance_cents"] == 500, \
        f"referrer available balance must rise by bonus 500, got {referrer_now['available_balance_cents']}"
