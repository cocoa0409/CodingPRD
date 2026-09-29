"""
Competing-validation ordering on the Digital Estate Fiduciary Access API.

Each case below drives one request body that violates two different rules at
once and pins which of the two errors the contract's rejection ladder must
report, then relaxes the winning violation and shows the loser surfacing from
the very same body — so the ordering itself is under test, not either rule in
isolation.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLAIM_PERIOD_OUT_OF_TERM,
    ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED,
    ERR_INVALID_ORDER_STATE,
    ERR_PLATFORM_FORM_MISMATCH,
    ERR_REFUND_WINDOW_TOO_SHORT,
)
from test_helpers.constants import (
    ACCESS_UNVERIFIED,
    CLAIM_FILED,
    METHOD_PRORATA_DAILY,
    ORDER_CONFIRMED,
    ORDER_PENDING,
    REQ_ACTION_SUBMIT,
    REQUEST_DRAFT,
    REQUEST_TYPE_CONTENT_ACCESS,
    SCOPE_CATALOG_AND_CONTENT,
)


def test_pending_cancellation_order_outranks_an_out_of_term_claimed_period(api):
    """
    A refund claim filed against a cancellation order that is still PENDING and
    whose claimed period also runs outside the paid term is refused for the
    order's state, never for the period, and no claim row is written.

    "Filing a refund claim against a cancellation order that has not been confirmed returns `ERR_INVALID_ORDER_STATE`, never `ERR_CLAIM_PERIOD_OUT_OF_TERM`, because the order-state check sits in band 6 and the claimed-period check in band 9 — even when the claimed period is also out of term."

    Design: Difficulty/priority_pair_validation_conflict/pending_order_state_outranks_out_of_term_claim_period
    """
    fx.set_clock(api)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-L")
    asset = fx.add_subscription_asset(api, ctx, platform["id"])
    term = fx.add_subscription_term(api, ctx, asset["id"])
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])

    order = fx.cancellation_order_for_asset(api, ctx, asset["id"])
    assert order["status"] == ORDER_PENDING, (
        f"The auto-created order must open PENDING, got {order['status']!r}"
    )

    # The claimed period 2025-12-01..2027-01-31 straddles both ends of the term.
    refused = api.create_refund_claim(
        order["id"],
        f.refund_claim_payload("2025-12-01", "2027-01-31"),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_INVALID_ORDER_STATE)

    rows, meta = validate_paginated(
        api.list_refund_claims(ctx.fid_headers, cancellation_order_id=order["id"])
    )
    assert rows == [], "A refused filing must not persist a refund claim"
    assert meta["total_count"] == 0
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 0


def test_out_of_term_claimed_period_surfaces_once_the_order_is_confirmed(api):
    """
    The identical claim body, replayed after the cancellation order reaches
    CONFIRMED, now fails on the claimed period instead: its start precedes
    term_start_date and its end follows term_end_date.

    "Third, the claimed period must sit inside the term: `claimed_period_start` at or after `term_start_date`, `claimed_period_end` at or before `term_end_date`, and `claimed_period_start` no later than `claimed_period_end`, with any violation reported as `ERR_CLAIM_PERIOD_OUT_OF_TERM`."

    Design: Difficulty/priority_pair_validation_conflict/pending_order_state_outranks_out_of_term_claim_period
    """
    fx.set_clock(api)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-L")
    built = fx.subscription_with_confirmed_order(
        api, ctx, platform, platform_reference="SO-CANCEL-88"
    )
    order, term = built["order"], built["term"]
    assert order["status"] == ORDER_CONFIRMED

    refused = api.create_refund_claim(
        order["id"],
        f.refund_claim_payload("2025-12-01", "2027-01-31"),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_CLAIM_PERIOD_OUT_OF_TERM)

    rows, meta = validate_paginated(
        api.list_refund_claims(ctx.fid_headers, cancellation_order_id=order["id"])
    )
    assert rows == [], "A refused filing must not persist a refund claim"
    assert meta["total_count"] == 0
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 0


def test_an_in_term_claim_is_priced_pro_rata_after_the_two_refusals(api):
    """
    Once the order is CONFIRMED and the claimed period sits inside the term, the
    same endpoint accepts the filing: 2026-03-16..2026-12-31 is 291 of the
    term's 365 days, so 11999 * 291 / 365 rounds half up to 9566 cents.

    "The claimed period is also a **closed** interval, so `claimed_days` is the day count from `claimed_period_start` to `claimed_period_end` plus one."

    "Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share."

    Design: Difficulty/priority_pair_validation_conflict/pending_order_state_outranks_out_of_term_claim_period
    """
    fx.set_clock(api)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-L")
    built = fx.subscription_with_confirmed_order(
        api, ctx, platform, platform_reference="SO-CANCEL-88"
    )
    order, term = built["order"], built["term"]

    validate_error(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2025-12-01", "2027-01-31"),
            ctx.fid_headers,
        ),
        ERR_CLAIM_PERIOD_OUT_OF_TERM,
    )

    claim = validate_success(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-03-16", "2026-12-31"),
            ctx.fid_headers,
        ),
        201,
    )
    assert claim["claimed_days"] == 291
    assert claim["claimed_cents"] == 9566
    assert claim["method"] == METHOD_PRORATA_DAILY
    assert claim["status"] == CLAIM_FILED
    assert claim["credited_cents"] == 0


def test_stale_provider_form_code_outranks_missing_content_authority(api):
    """
    A CONTENT_ACCESS submission on an estate with no recorded directive at all
    lacks content authority, but once the provider has also changed its
    form_code the cited code is wrong too — and the form check is reported.

    "A submission that both cites the wrong provider form code and lacks content authority returns `ERR_PLATFORM_FORM_MISMATCH`, never `ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED`, because the form must match before the content-authority question is even asked."

    Design: Difficulty/priority_pair_validation_conflict/platform_form_mismatch_outranks_content_disclosure_not_authorized
    """
    fx.set_clock(api)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-M")
    asset = fx.add_asset(
        api, ctx, platform["id"], account_handle="vault-content", quoted_value_cents=150000
    )
    request = fx.draft_request(
        api,
        ctx,
        platform["id"],
        platform["form_code"],
        request_type=REQUEST_TYPE_CONTENT_ACCESS,
        requested_scope=SCOPE_CATALOG_AND_CONTENT,
    )
    fx.patch_platform(api, platform["id"], form_code="CV-FORM-9")

    refused = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
    )
    validate_error(refused, ERR_PLATFORM_FORM_MISMATCH)

    after = fx.read_request(api, ctx, request["id"])
    assert after["status"] == REQUEST_DRAFT
    assert after["review_window_start"] is None
    assert after["review_window_end"] is None
    assert fx.read_asset(api, ctx, asset["id"])["access_status"] == ACCESS_UNVERIFIED

    _, meta = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert meta["total_count"] == 0, "A refused submission may not create a grant"


def test_missing_content_authority_surfaces_once_the_form_code_matches_again(api):
    """
    Restoring the provider's form_code leaves the identical submission body with
    exactly one violation left: with no directive on file the resolution is the
    statutory default, which never reaches CATALOG_AND_CONTENT.

    "When the `request_type` is `CONTENT_ACCESS`, the resolution of §3.3 must come out at `CATALOG_AND_CONTENT` with a `clamp_reason` of `NONE`; if the recorded directives never granted content at all, the submission is rejected with `ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED`, and if they did grant content but the provider's `requires_court_order_for_content` is true and no `VERIFIED` `COURT_ORDER` document exists on the estate, it is rejected with the more specific `ERR_COURT_ORDER_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/platform_form_mismatch_outranks_content_disclosure_not_authorized
    """
    fx.set_clock(api)
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-M")
    asset = fx.add_asset(
        api, ctx, platform["id"], account_handle="vault-content", quoted_value_cents=150000
    )
    request = fx.draft_request(
        api,
        ctx,
        platform["id"],
        platform["form_code"],
        request_type=REQUEST_TYPE_CONTENT_ACCESS,
        requested_scope=SCOPE_CATALOG_AND_CONTENT,
    )

    fx.patch_platform(api, platform["id"], form_code="CV-FORM-9")
    validate_error(
        api.transition_platform_request(
            request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
        ),
        ERR_PLATFORM_FORM_MISMATCH,
    )

    fx.patch_platform(api, platform["id"], form_code="CV-FORM-1")
    refused = api.transition_platform_request(
        request["id"], f.request_transition_payload(REQ_ACTION_SUBMIT), ctx.fid_headers
    )
    validate_error(refused, ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED)

    after = fx.read_request(api, ctx, request["id"])
    assert after["status"] == REQUEST_DRAFT
    assert after["review_window_start"] is None
    assert fx.read_asset(api, ctx, asset["id"])["access_status"] == ACCESS_UNVERIFIED

    _, meta = validate_paginated(
        api.list_authority_grants(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert meta["total_count"] == 0


def test_out_of_term_claimed_period_outranks_a_too_short_claim_window(api):
    """
    The four-day interval 2026-12-29..2027-01-01 both ends after term_end_date
    and falls short of the seven-day minimum; the in-term check is reported.

    "And a claim whose period is out of term *and* shorter than the minimum claimable stretch returns `ERR_CLAIM_PERIOD_OUT_OF_TERM`, never `ERR_REFUND_WINDOW_TOO_SHORT`."

    Design: Difficulty/priority_pair_validation_conflict/out_of_term_claim_period_outranks_refund_window_too_short
    """
    fx.set_clock(api)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-N")
    built = fx.subscription_with_confirmed_order(
        api, ctx, platform, platform_reference="SO-CANCEL-99"
    )
    order, term = built["order"], built["term"]

    refused = api.create_refund_claim(
        order["id"],
        f.refund_claim_payload("2026-12-29", "2027-01-01"),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_CLAIM_PERIOD_OUT_OF_TERM)
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 0


def test_too_short_claim_window_surfaces_when_the_period_sits_inside_the_term(api):
    """
    Pulling the same four-day stretch back inside the term to
    2026-06-01..2026-06-04 leaves only the length rule to fail on.

    "Only after those four checks does the length rule apply: `claimed_days` must be at least 7, so a claim covering exactly 7 days is accepted and one covering 6 is rejected with `ERR_REFUND_WINDOW_TOO_SHORT`."

    Design: Difficulty/priority_pair_validation_conflict/out_of_term_claim_period_outranks_refund_window_too_short
    """
    fx.set_clock(api)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-N")
    built = fx.subscription_with_confirmed_order(
        api, ctx, platform, platform_reference="SO-CANCEL-99"
    )
    order, term = built["order"], built["term"]

    validate_error(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-12-29", "2027-01-01"),
            ctx.fid_headers,
        ),
        ERR_CLAIM_PERIOD_OUT_OF_TERM,
    )

    refused = api.create_refund_claim(
        order["id"],
        f.refund_claim_payload("2026-06-01", "2026-06-04"),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_REFUND_WINDOW_TOO_SHORT)

    _, meta = validate_paginated(
        api.list_refund_claims(ctx.fid_headers, cancellation_order_id=order["id"])
    )
    assert meta["total_count"] == 0
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 0


def test_a_seven_day_claim_after_both_refusals_is_accepted_and_counted(api):
    """
    A seven-day stretch inside the term clears both checks, is priced pro rata
    over the 365-day term (11999 * 7 / 365 = 230.11 -> 230) and is the only
    interval the term's claimed-day tally counts.

    "The term is a **closed** interval: both endpoints are inside it, so `term_days` is the number of days from `term_start_date` to `term_end_date` plus one, and a term whose two dates are equal is one day long."

    "Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share."

    "A new claim opens with `status` at `FILED` and `credited_cents` at 0, and the term's `claimed_days_total` — defined as the sum of `claimed_days` across the claims on that term in `FILED`, `PLATFORM_REVIEW`, `ESCALATED` or `CREDITED` — rises by this claim's `claimed_days`."

    Design: Difficulty/priority_pair_validation_conflict/out_of_term_claim_period_outranks_refund_window_too_short
    """
    fx.set_clock(api)
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, "PR-2737-N")
    built = fx.subscription_with_confirmed_order(
        api, ctx, platform, platform_reference="SO-CANCEL-99"
    )
    order, term = built["order"], built["term"]
    assert term["term_days"] == 365

    validate_error(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-12-29", "2027-01-01"),
            ctx.fid_headers,
        ),
        ERR_CLAIM_PERIOD_OUT_OF_TERM,
    )
    validate_error(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-06-01", "2026-06-04"),
            ctx.fid_headers,
        ),
        ERR_REFUND_WINDOW_TOO_SHORT,
    )

    claim = validate_success(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-06-01", "2026-06-07"),
            ctx.fid_headers,
        ),
        201,
    )
    assert claim["claimed_days"] == 7
    assert claim["claimed_cents"] == 230
    assert claim["status"] == CLAIM_FILED
    assert claim["method"] == METHOD_PRORATA_DAILY
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 7
