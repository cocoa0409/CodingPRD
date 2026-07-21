"""Disbursement: request, review, the revision cycle, release and the void."""

from test_helpers import (
    ApiErrorId,
    REVIEWER_ONE_ID,
    REVIEWER_TWO_ID,
    assert_fund_conservation,
    current_campaign_version,
    make_finance_reviewer_headers,
    make_platform_admin_headers,
    request_payout,
    setup_approved_payout,
    setup_campaign_with_balance,
    setup_payout_under_review,
    setup_released_payout,
    validate_error,
    validate_paginated,
    validate_success,
    verify_payout_account,
)

ADMIN = make_platform_admin_headers()
REVIEWER_ONE = make_finance_reviewer_headers(REVIEWER_ONE_ID)
REVIEWER_TWO = make_finance_reviewer_headers(REVIEWER_TWO_ID)


def test_a_payout_below_the_disbursement_floor_is_rejected(api):
    """PRD §3.10: "The requested amount must be at least the platform's disbursement
    floor of 5000 cents, or the request is rejected with `ERR_PAYOUT_BELOW_MINIMUM`."

    Design: Corner/validations/payout_below_minimum_rejected
    """
    ctx = setup_campaign_with_balance(api=api)
    version = current_campaign_version(ctx["campaign_id"], ctx["cm_headers"], api=api)

    response = api.create_payout(
        ctx["campaign_id"],
        {"amount_cents": 4999, "expected_campaign_version": version, "note": "too small"},
        ctx["cm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM.value, expected_status=422
    )
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["reserved_payout_cents"] == 0


def test_a_payout_above_the_available_balance_is_rejected(api):
    """PRD §3.10: "The requested amount must not exceed the campaign's
    `available_balance_cents`, measured **after** any superseded reservation has been
    released, or it is rejected with `ERR_INSUFFICIENT_CAMPAIGN_BALANCE`."

    Design: Corner/validations/payout_exceeding_available_balance_rejected
    """
    ctx = setup_campaign_with_balance(api=api)
    version = current_campaign_version(ctx["campaign_id"], ctx["cm_headers"], api=api)

    response = api.create_payout(
        ctx["campaign_id"],
        {
            "amount_cents": 92071,
            "expected_campaign_version": version,
            "note": "one cent too much",
        },
        ctx["cm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_INSUFFICIENT_CAMPAIGN_BALANCE.value, expected_status=422
    )
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["available_balance_cents"] == 92070


def test_a_stale_campaign_version_blocks_the_payout_request(api):
    """PRD §2.9: "If that value does not equal the campaign's current `version`, the
    request is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412) and nothing is
    created."

    Design: Corner/cross_cutting_layers/stale_expected_campaign_version_on_payout_create_returns_conflict
    """
    ctx = setup_campaign_with_balance(api=api)
    version = current_campaign_version(ctx["campaign_id"], ctx["cm_headers"], api=api)

    response = api.create_payout(
        ctx["campaign_id"],
        {
            "amount_cents": 50000,
            "expected_campaign_version": version - 1,
            "note": "stale view",
        },
        ctx["cm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value, expected_status=412
    )
    _rows, meta = validate_paginated(
        api.list_payouts(ctx["cm_headers"], params={"campaign_id": ctx["campaign_id"]})
    )
    assert meta["total_count"] == 0, "Nothing is created on a stale request"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["version"] == version, "A rejected request must not bump the version"


def test_a_second_request_supersedes_the_open_one_and_releases_its_reservation(api):
    """PRD §3.10: "And on success, any existing payout of that campaign sitting in
    `REQUESTED` or `CHANGES_REQUESTED` transitions to `SUPERSEDED` and its reservation
    is released from `reserved_payout_cents` — this is why a second request is never
    blocked by a state precondition."
    PRD §2.9: "A successful payout request itself increments the campaign's `version`
    by 1."

    Design: Corner/cross_cutting_layers/second_payout_create_supersedes_open_request_and_bumps_version
    """
    ctx = setup_campaign_with_balance(api=api)
    first = request_payout(ctx["campaign_id"], ctx["cm_headers"], 50000, api=api, note="first")
    version = current_campaign_version(ctx["campaign_id"], ctx["cm_headers"], api=api)

    response = api.create_payout(
        ctx["campaign_id"],
        {
            "amount_cents": 20000,
            "expected_campaign_version": version,
            "note": "replacement",
        },
        ctx["cm_headers"],
    )

    second = validate_success(response, expected_status=201)
    assert second["status"] == "REQUESTED"
    assert second["amount_cents"] == 20000
    superseded = validate_success(api.get_payout(first["id"], ctx["cm_headers"]))
    assert superseded["status"] == "SUPERSEDED"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["reserved_payout_cents"] == 20000, "Only the live request reserves"
    assert campaign["available_balance_cents"] == 72070
    assert campaign["version"] == version + 1


def test_rejecting_a_payout_releases_its_reservation(api):
    """PRD §3.10: "Rejection moves it `UNDER_REVIEW → REJECTED` with an optional `note`
    and releases the reservation: `reserved_payout_cents` falls by the payout's
    `amount_cents` and `available_balance_cents` rises by the same figure."

    Design: Corner/state_machines/payout_reject_releases_reservation_back_to_available_balance
    """
    ctx = setup_payout_under_review(api=api, amount_cents=50000)

    rejected = validate_success(
        api.reject_payout(
            ctx["payout_id"], {"note": "insufficient documentation"}, REVIEWER_ONE
        )
    )

    assert rejected["status"] == "REJECTED"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["reserved_payout_cents"] == 0
    assert campaign["available_balance_cents"] == 92070
    assert campaign["paid_out_cents"] == 0


def test_the_reviewer_who_took_a_payout_into_review_cannot_approve_it(api):
    """PRD §3.10: "Approval moves it `UNDER_REVIEW → APPROVED` and records the acting
    `X-User-ID` as `approved_by_user_id` — but only if that identifier differs from the
    recorded `reviewed_by_user_id`. A reviewer who tries to approve the very request
    they took into review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/same_reviewer_cannot_approve_payout_they_reviewed
    """
    ctx = setup_payout_under_review(api=api, amount_cents=50000)

    blocked = api.approve_payout(ctx["payout_id"], REVIEWER_ONE)

    validate_error(
        blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )
    still_under_review = validate_success(
        api.get_payout(ctx["payout_id"], ctx["cm_headers"])
    )
    assert still_under_review["status"] == "UNDER_REVIEW"

    approved = validate_success(api.approve_payout(ctx["payout_id"], REVIEWER_TWO))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == REVIEWER_TWO_ID
    assert approved["reviewed_by_user_id"] == REVIEWER_ONE_ID


def test_a_payout_sent_back_returns_to_requested_with_the_revised_amount(api):
    """PRD §3.10: "A payout sent back for changes returns to the campaign manager, who
    revises and resubmits it with a replacement `amount_cents` and an optional `note`,
    moving it `CHANGES_REQUESTED → REQUESTED`."
    PRD §3.10: "On success the payout's `amount_cents` is replaced with the resubmitted
    figure, `requested_by_user_id` is set to the acting `X-User-ID`,
    `reviewed_by_user_id` is cleared so the next review starts clean, and the
    campaign's `reserved_payout_cents` and `available_balance_cents` are recomputed."

    Design: Difficulty/non_linear_state_machine/payout_changes_requested_revision_cycle_returns_to_requested
    """
    ctx = setup_payout_under_review(api=api, amount_cents=50000)
    validate_success(
        api.request_changes_payout(
            ctx["payout_id"], {"note": "split into two tranches"}, REVIEWER_ONE
        )
    )

    resubmitted = validate_success(
        api.resubmit_payout(
            ctx["payout_id"], {"amount_cents": 60000, "note": "revised"}, ctx["cm_headers"]
        )
    )

    assert resubmitted["status"] == "REQUESTED", "The payout re-enters a state it left"
    assert resubmitted["amount_cents"] == 60000
    assert resubmitted["reviewed_by_user_id"] is None


def test_the_revised_payout_can_be_reviewed_and_approved_again(api):
    """PRD §3.10: "The path `CHANGES_REQUESTED → REQUESTED → UNDER_REVIEW →
    CHANGES_REQUESTED` is a genuine revision cycle a payout may traverse repeatedly."
    PRD §2.10: "`reserved_payout_cents` is the sum of `amount_cents` across the
    campaign's payouts sitting in `REQUESTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED` or
    `APPROVED`."

    Design: Difficulty/non_linear_state_machine/payout_changes_requested_revision_cycle_returns_to_requested
    """
    ctx = setup_payout_under_review(api=api, amount_cents=50000)
    validate_success(
        api.request_changes_payout(
            ctx["payout_id"], {"note": "split into two tranches"}, REVIEWER_ONE
        )
    )
    validate_success(
        api.resubmit_payout(
            ctx["payout_id"], {"amount_cents": 60000, "note": "revised"}, ctx["cm_headers"]
        )
    )
    validate_success(api.review_payout(ctx["payout_id"], REVIEWER_ONE))

    approved = validate_success(api.approve_payout(ctx["payout_id"], REVIEWER_TWO))

    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == REVIEWER_TWO_ID
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["reserved_payout_cents"] == 60000
    assert campaign["available_balance_cents"] == 32070


def test_release_is_blocked_while_the_payout_account_is_unverified(api):
    """PRD §3.10: "It requires the beneficiary organization's `payout_account_status`
    to read `VERIFIED`; an `UNVERIFIED` or `SUSPENDED` account blocks the disbursement
    with `ERR_ORGANIZATION_PAYOUT_UNVERIFIED`."
    PRD §3.1: "A newly registered organization begins with `payout_account_status` of
    `UNVERIFIED`, and only a platform operator may change it, supplying a `status` of
    either `VERIFIED` or `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/payout_release_blocked_until_organization_payout_account_verified
    """
    ctx = setup_approved_payout(api=api, amount_cents=50000)

    response = api.release_payout(ctx["payout_id"], ADMIN)

    validate_error(
        response, ApiErrorId.ERR_ORGANIZATION_PAYOUT_UNVERIFIED.value, expected_status=409
    )
    payout = validate_success(api.get_payout(ctx["payout_id"], ctx["cm_headers"]))
    assert payout["status"] == "APPROVED", "The blocked release changes nothing"


def test_verifying_the_account_lets_the_same_release_through(api):
    """PRD §3.10: "Release stamps `released_at` and moves the amount from
    `reserved_payout_cents` into `paid_out_cents`; `available_balance_cents` is
    unchanged by a release, since the money was already committed."
    PRD §3.1: "`VERIFIED` unlocks disbursement; `SUSPENDED` blocks it again."

    Design: Difficulty/cross_entity_state_dependency/payout_release_blocked_until_organization_payout_account_verified
    """
    ctx = setup_approved_payout(api=api, amount_cents=50000)
    blocked = api.release_payout(ctx["payout_id"], ADMIN)
    validate_error(
        blocked, ApiErrorId.ERR_ORGANIZATION_PAYOUT_UNVERIFIED.value, expected_status=409
    )

    organization = verify_payout_account(ctx["org_id"], api=api)
    released = validate_success(api.release_payout(ctx["payout_id"], ADMIN))

    assert organization["payout_account_status"] == "VERIFIED"
    assert released["status"] == "RELEASED"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["paid_out_cents"] == 50000
    assert campaign["reserved_payout_cents"] == 0
    assert campaign["available_balance_cents"] == 42070


def test_voiding_a_released_payout_returns_the_money_to_the_spendable_pool(api):
    """PRD §3.10: "This is a compensating action: `paid_out_cents` falls by the
    payout's `amount_cents` and `available_balance_cents` rises by the same figure,
    restoring the conservation identity of §2.10 and returning the money to the
    campaign's spendable pool."

    Design: Difficulty/compensating_invariant/campaign_net_funds_conserved_across_payout_release_and_void
    """
    ctx = setup_released_payout(api=api, amount_cents=50000)

    voided = validate_success(
        api.void_payout(ctx["payout_id"], {"reason": "bank returned the transfer"}, ADMIN)
    )

    assert voided["status"] == "VOIDED"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["paid_out_cents"] == 0
    assert campaign["reserved_payout_cents"] == 0
    assert campaign["available_balance_cents"] == 92070


def test_the_conservation_identity_holds_across_release_and_void(api):
    """PRD §2.10: "After every mutation — including the compensating pair where a
    released payout is later voided — the following identity must hold:
    `available_balance_cents` added to `reserved_payout_cents` added to
    `paid_out_cents` equals `lifetime_net_cents`."

    Design: Difficulty/compensating_invariant/campaign_net_funds_conserved_across_payout_release_and_void
    """
    ctx = setup_released_payout(api=api, amount_cents=50000)
    after_release = validate_success(
        api.get_campaign(ctx["campaign_id"], ctx["cm_headers"])
    )
    assert_fund_conservation(after_release)
    assert after_release["lifetime_net_cents"] == 92070
    assert after_release["paid_out_cents"] == 50000

    validate_success(
        api.void_payout(ctx["payout_id"], {"reason": "bank returned the transfer"}, ADMIN)
    )

    after_void = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert_fund_conservation(after_void)
    assert after_void["lifetime_net_cents"] == 92070
