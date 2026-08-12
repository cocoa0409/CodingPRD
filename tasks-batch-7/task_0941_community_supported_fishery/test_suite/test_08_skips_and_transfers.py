"""Skips, their cutoff arithmetic, and share transfers onto the waitlist."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    assert_transfer_net_take,
    close_landings,
    delivery_of_week,
    file_skip,
    make_member_headers,
    new_hub,
    new_subscription,
    pause_subscription,
    pay_subscription,
    read_delivery,
    read_season,
    read_skip,
    read_subscription,
    read_transfer,
    set_clock,
    setup_member_subscription,
    setup_open_season,
    setup_transfer_pair,
    share_transfer_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _active_weekly_subscription():
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    ctx["hub"] = hub
    ctx.update(
        setup_member_subscription(
            ctx["season_id"],
            ctx["plan"]["id"],
            join_week_index=1,
            fulfillment_mode="HUB_PICKUP",
            pickup_hub_id=hub["id"],
        )
    )
    return ctx


def test_a_skip_filed_before_the_cutoff_takes_the_credit_branch(api):
    """PRD 3.8: "The skip's `cutoff_at` is the target delivery's `scheduled_at` less the
    season's `landing_commit_lead_hours`, and the skip's `requested_at` is the logical clock at
    filing."
    PRD 3.8: "Filing **at or before** `cutoff_at` takes the credit branch: `settlement_variant`
    is `CREDIT`, the skip's `credit_cents` is the subscription's full `price_per_delivery_cents`,
    that amount is banked on the subscription's `skip_credit_balance_cents`,
    `skip_credited_count` rises by 1, the skip is created directly in `CREDITED` and the
    delivery moves `SCHEDULED → SKIPPED` with its money axis moving `PENDING → CREDITED`."

    Design: Difficulty/non_linear_state_machine/share_delivery_skip_then_revoke_returns_to_scheduled
    """
    ctx = _active_weekly_subscription()
    week_three = delivery_of_week(ctx["subscription_id"], 3)

    skip = file_skip(week_three["id"], ctx["member_id"])
    assert skip["settlement_variant"] == "CREDIT"
    assert skip["credit_cents"] == 4500
    assert skip["status"] == "CREDITED"
    assert_same_instant(skip["cutoff_at"], "2026-05-15T00:00:00.000Z", "skip cutoff_at")

    delivery = read_delivery(week_three["id"])
    assert delivery["fulfillment_status"] == "SKIPPED"
    assert delivery["billing_status"] == "CREDITED"

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["skip_count"] == 1
    assert subscription["skip_credited_count"] == 1
    assert subscription["skip_credit_balance_cents"] == 4500


def test_revoking_a_credited_skip_returns_the_box_and_the_counters(api):
    """PRD 3.8: "It moves the skip `CREDITED → REVOKED`, removes `credit_cents` from the
    subscription's `skip_credit_balance_cents`, decrements both `skip_count` and
    `skip_credited_count` by 1, and returns the delivery `SKIPPED → SCHEDULED` with its money
    axis returning to `PENDING`."
    PRD 3.8: "`SCHEDULED → SKIPPED → SCHEDULED` on the fulfillment axis and `PENDING → CREDITED
    → PENDING` on the money axis are the two re-entrant loops this creates."

    Design: Difficulty/non_linear_state_machine/share_delivery_skip_then_revoke_returns_to_scheduled
    """
    ctx = _active_weekly_subscription()
    week_three = delivery_of_week(ctx["subscription_id"], 3)
    skip = file_skip(week_three["id"], ctx["member_id"])

    revoked = validate_success(
        api.revoke_skip_request(skip["id"], make_member_headers(ctx["member_id"]))
    )
    assert revoked["status"] == "REVOKED"
    assert read_skip(skip["id"])["status"] == "REVOKED"

    delivery = read_delivery(week_three["id"])
    assert delivery["fulfillment_status"] == "SCHEDULED"
    assert delivery["billing_status"] == "PENDING"

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["skip_credit_balance_cents"] == 0
    assert subscription["skip_count"] == 0
    assert subscription["skip_credited_count"] == 0


def test_the_fifth_skip_of_a_season_is_refused_by_the_cap(api):
    """PRD 3.8: "`SKIP_CAP_PER_SEASON` is 4, and the subscription's `skip_count` must be
    strictly below that before this skip is counted, or the request is refused with
    `ERR_SKIP_CAP_EXCEEDED`; the count includes every skip standing in `CREDITED` and every skip
    standing in `FORFEITED`, and excludes revoked ones."
    PRD 3.8: "On both branches the subscription's `skip_count` rises by 1."

    Design: Corner/validations/fifth_skip_in_a_season_is_rejected_by_the_cap
    """
    ctx = _active_weekly_subscription()
    for week in (5, 6, 7, 8):
        file_skip(delivery_of_week(ctx["subscription_id"], week)["id"], ctx["member_id"])

    week_nine = delivery_of_week(ctx["subscription_id"], 9)
    response = api.create_skip_request(
        {"share_delivery_id": week_nine["id"]}, make_member_headers(ctx["member_id"])
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_SKIP_CAP_EXCEEDED.value)

    subscription = read_subscription(ctx["subscription_id"])
    assert subscription["skip_count"] == 4
    assert subscription["skip_credited_count"] == 4
    assert subscription["skip_credit_balance_cents"] == 18000
    assert read_delivery(week_nine["id"])["fulfillment_status"] == "SCHEDULED"


def test_revoking_a_skip_after_its_cutoff_is_refused(api):
    """PRD 3.8: "Revocation requires the skip to be standing in `CREDITED` and the logical clock
    to be at or before `cutoff_at`, and a late attempt is refused with
    `ERR_SKIP_WINDOW_CLOSED`."
    PRD 3.8: "A week-11 box scheduled for `2026-07-13T00:00:00Z` under a 72-hour lead has a
    cutoff of `2026-07-10T00:00:00Z`; filing at exactly that instant earns the credit, and
    filing one second later does not."

    Design: Corner/validations/skip_revoke_after_the_cutoff_returns_window_closed
    """
    ctx = _active_weekly_subscription()
    week_three = delivery_of_week(ctx["subscription_id"], 3)
    skip = file_skip(week_three["id"], ctx["member_id"])
    set_clock("2026-05-15T00:00:01Z")

    response = api.revoke_skip_request(skip["id"], make_member_headers(ctx["member_id"]))
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SKIP_WINDOW_CLOSED.value)

    stored = read_skip(skip["id"])
    assert stored["status"] == "CREDITED"
    assert_same_instant(stored["cutoff_at"], "2026-05-15T00:00:00.000Z", "skip cutoff_at")
    assert read_subscription(ctx["subscription_id"])["skip_credit_balance_cents"] == 4500
    assert read_delivery(week_three["id"])["fulfillment_status"] == "SKIPPED"


def test_filing_a_skip_on_a_paused_subscription_is_refused(api):
    """PRD 2.5: "The subscription behind the operation has `lifecycle_status` equal to `ACTIVE`
    — otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE` (HTTP 409). This guards skip filing, transfer
    creation, box pickup and substitution proposal."
    PRD 3.8: "The box must be in `SCHEDULED` and the subscription must be `ACTIVE`."

    Design: Corner/validations/skip_on_a_paused_subscription_returns_subscription_not_active
    """
    ctx = _active_weekly_subscription()
    week_three = delivery_of_week(ctx["subscription_id"], 3)
    pause_subscription(ctx["subscription_id"], make_member_headers(ctx["member_id"]))

    response = api.create_skip_request(
        {"share_delivery_id": week_three["id"]}, make_member_headers(ctx["member_id"])
    )
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)

    assert read_subscription(ctx["subscription_id"])["skip_count"] == 0
    assert read_delivery(week_three["id"])["fulfillment_status"] == "SCHEDULED"


def test_a_transfer_offered_to_an_active_subscription_is_not_eligible(api):
    """PRD 3.8: "Eligibility is checked at creation and again at acceptance: the receiving
    subscription must be `WAITLISTED`, the transferring one must be `ACTIVE`, the two must
    belong to different members, and `remaining_delivery_count` must be strictly greater than 0,
    or the request is refused with `ERR_TRANSFER_NOT_ELIGIBLE`."

    Design: Corner/validations/transfer_to_an_active_subscription_is_not_eligible
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    hub = new_hub()
    first = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Mara One",
        email="m1@csf.test",
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )
    second = setup_member_subscription(
        ctx["season_id"],
        ctx["plan"]["id"],
        full_name="Nils Two",
        email="m2@csf.test",
        join_week_index=1,
        fulfillment_mode="HUB_PICKUP",
        pickup_hub_id=hub["id"],
    )

    response = api.create_share_transfer(
        share_transfer_payload(
            first["subscription_id"],
            second["subscription_id"],
            ctx["season_id"],
            11,
            first["subscription"]["version"],
        ),
        ADMIN,
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_TRANSFER_NOT_ELIGIBLE.value)

    assert read_subscription(first["subscription_id"])["lifecycle_status"] == "ACTIVE"
    assert read_subscription(second["subscription_id"])["lifecycle_status"] == "ACTIVE"

    _, meta = validate_paginated(api.list_share_transfers(ADMIN, {"season_id": ctx["season_id"]}))
    assert meta["total_count"] == 0


def test_closing_landings_expires_the_unanswered_transfer_without_moving_money(api):
    """PRD 3.8: "On the `PREPAID` variant, `transferee_charge_cents` is
    `remaining_delivery_count` multiplied by the transferor's `price_per_delivery_cents`, and
    `transferor_refund_cents` is that same figure less the transfer fee — the transferor gets
    back the unused prepaid value minus the fee, and the transferee pays exactly the unused
    value."
    PRD 3.8: "An offer that is never answered dies with the season: when the season moves `OPEN
    → LANDINGS_CLOSED`, every transfer of that season still standing in `REQUESTED` moves to
    `EXPIRED` and no money moves."

    Design: Corner/state_machines/share_transfer_expires_when_the_season_closes_landings
    """
    ctx = setup_transfer_pair(payment_basis="PREPAID_FULL_SEASON", paid_cents=82800)
    transfer = validate_success(
        api.create_share_transfer(
            share_transfer_payload(
                ctx["transferor_id"],
                ctx["transferee_id"],
                ctx["season_id"],
                11,
                ctx["transferor_version"],
            ),
            ADMIN,
        ),
        201,
    )
    assert transfer["remaining_delivery_count"] == 10
    assert transfer["settlement_variant"] == "PREPAID"
    assert transfer["transfer_fee_cents"] == 2500
    assert transfer["transferee_charge_cents"] == 41400
    assert transfer["transferor_refund_cents"] == 38900
    assert_transfer_net_take(transfer, 4140)

    close_landings(ctx["season_id"])

    expired = read_transfer(transfer["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["transferor_refund_cents"] == 38900
    assert read_subscription(ctx["transferor_id"])["lifecycle_status"] == "ACTIVE"
    assert read_subscription(ctx["transferee_id"])["lifecycle_status"] == "WAITLISTED"
    assert read_season(ctx["season_id"])["status"] == "LANDINGS_CLOSED"


def test_a_transfer_carrying_a_pre_payment_subscription_version_is_refused(api):
    """PRD 2.7: "The second is the share transfer. A request that creates a transfer must carry
    `expected_subscription_version` equal to the current `version` of the transferring
    subscription."
    PRD 2.7: "If the value supplied does not equal the parent's current `version`, the request
    is rejected with `ERR_STALE_VERSION` at HTTP 412 and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/stale_subscription_version_on_transfer_create_returns_412
    """
    ctx = setup_transfer_pair(payment_basis="PREPAID_FULL_SEASON", paid_cents=82800)
    stale_version = ctx["transferor_version"]
    pay_subscription(ctx["transferor_id"], 100)

    response = api.create_share_transfer(
        share_transfer_payload(
            ctx["transferor_id"], ctx["transferee_id"], ctx["season_id"], 11, stale_version
        ),
        ADMIN,
    )
    assert response.status_code == 412
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    assert read_subscription(ctx["transferor_id"])["lifecycle_status"] == "ACTIVE"
    assert read_subscription(ctx["transferee_id"])["lifecycle_status"] == "WAITLISTED"

    _, meta = validate_paginated(api.list_share_transfers(ADMIN, {"season_id": ctx["season_id"]}))
    assert meta["total_count"] == 0
