"""Writes gated on the state of a different entity: the agreement and the bank's approval."""

from test_helpers import fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import (
    create_deposit_account_payload,
    create_pledge_allocation_payload,
)
from test_helpers.fixtures import COMPLIANCE, OFFICER, REGULATOR
from test_helpers.test_users import (
    make_custodian_headers,
    make_public_unit_treasurer_headers,
)

FULL_PAR = 80_357_143


def _draft_agreement_and_a_matching_treasury(client):
    """An approved bank with a funded account, one treasury sized to cover the requirement to
    the cent, and a dedicated agreement still sitting in DRAFT."""
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000
    )
    asset = fixtures.create_collateral_asset(
        client,
        depository["id"],
        custodian["id"],
        asset_type="US_TREASURY",
        par_value_cents=FULL_PAR,
        market_price_bps=10000,
    )
    agreement = fixtures.draft_dedicated_agreement(
        client, depository["id"], custodian["id"], account["id"]
    )
    assert agreement["status"] == "DRAFT"
    return {
        "custodian_id": custodian["id"],
        "public_unit_id": public_unit["id"],
        "depository_id": depository["id"],
        "account_id": account["id"],
        "asset_id": asset["id"],
        "agreement_id": agreement["id"],
    }


def _attempt_full_par_allocation(client, world):
    payload = create_pledge_allocation_payload(
        world["agreement_id"],
        world["asset_id"],
        FULL_PAR,
        fixtures.agreement_version(client, world["agreement_id"]),
        effective_from=DEFAULT_CLOCK_UTC,
    )
    return client.create_pledge_allocation(payload, OFFICER)


def test_a_partly_signed_agreement_still_cannot_carry_a_pledge(client):
    """The gate is not merely "no longer DRAFT": the same pledge is refused against the draft
    and refused again once two of the three parties have stamped, and neither refusal creates an
    allocation or secures the account.

    PRD: "Execution is what turns the document into a legal pledge vehicle: until it has
    happened, any attempt to allocate collateral to the agreement, to request a substitution
    under it, or to issue a safekeeping receipt against it is refused with
    `ERR_AGREEMENT_NOT_EXECUTED`."
    PRD: "While fewer than three stamps are present the agreement self-loops in
    `PENDING_SIGNATURES`."
    PRD: "**Agreement execution** — the pledge agreement's `status` is `EXECUTED`, else
    `ERR_AGREEMENT_NOT_EXECUTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/allocation_requires_executed_pledge_agreement
    """
    world = _draft_agreement_and_a_matching_treasury(client)

    from_draft = _attempt_full_par_allocation(client, world)
    validate_error(from_draft, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED.value, 409)

    fixtures.circulate(client, world["agreement_id"])
    fixtures.sign(client, world["agreement_id"], "DEPOSITORY", COMPLIANCE)
    partly = fixtures.sign(
        client,
        world["agreement_id"],
        "PUBLIC_UNIT",
        make_public_unit_treasurer_headers(world["public_unit_id"]),
    )
    assert partly["status"] == "PENDING_SIGNATURES"
    assert partly["signature_count"] == 2

    from_pending = _attempt_full_par_allocation(client, world)
    validate_error(from_pending, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED.value, 409)

    _allocations, meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"pledge_agreement_id": world["agreement_id"]}
        )
    )
    assert meta["total_count"] == 0

    account = get_success_data(client.get_deposit_account(world["account_id"], OFFICER), 200)
    assert account["collateral_status"] == "UNSECURED"
    assert account["assigned_collateral_value_cents"] == 0


def test_the_third_stamp_unlocks_the_identical_pledge(client):
    """The stamp that arrives when two are already present executes the agreement, and the very
    same pledge payload then succeeds and carries the account to exactly 10000 basis points.

    PRD: "The signature that supplies the third distinct party — that is, the one arriving when
    `signature_count` stood at 2 — carries the agreement to `EXECUTED`, sets `signature_count` to
    3 and stamps `executed_at` from the clock."
    PRD: "A created allocation is `ACTIVE`, with `released_at`, `release_reason` and
    `created_by_substitution_id` all null — the last of these is populated only on an allocation
    minted by a settled substitution."
    PRD: "`UNSECURED → SECURED` when the recomputed `coverage_ratio_bps` is at least 10000."

    Design: Difficulty/cross_entity_state_dependency/allocation_requires_executed_pledge_agreement
    """
    world = _draft_agreement_and_a_matching_treasury(client)

    fixtures.circulate(client, world["agreement_id"])
    fixtures.sign(client, world["agreement_id"], "DEPOSITORY", COMPLIANCE)
    fixtures.sign(
        client,
        world["agreement_id"],
        "PUBLIC_UNIT",
        make_public_unit_treasurer_headers(world["public_unit_id"]),
    )
    executed = fixtures.sign(
        client,
        world["agreement_id"],
        "CUSTODIAN",
        make_custodian_headers(world["custodian_id"]),
    )
    assert executed["status"] == "EXECUTED"
    assert executed["signature_count"] == 3
    assert executed["executed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    allocation = get_success_data(_attempt_full_par_allocation(client, world), 201)
    assert allocation["status"] == "ACTIVE"
    assert allocation["allocated_collateral_value_cents"] == 78_750_000
    assert allocation["created_by_substitution_id"] is None

    _allocations, meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"pledge_agreement_id": world["agreement_id"]}
        )
    )
    assert meta["total_count"] == 1

    account = get_success_data(client.get_deposit_account(world["account_id"], OFFICER), 200)
    assert account["coverage_ratio_bps"] == 10000
    assert account["collateral_status"] == "SECURED"


def _candidate_bank_with_a_registered_unit(client):
    """A bank still in DRAFT plus the county that wants to bank with it."""
    fixtures.set_clock(client)
    public_unit = fixtures.create_public_unit(client)
    depository = fixtures.create_draft_depository(client)
    assert depository["approval_status"] == "DRAFT"
    assert depository["approved_pledge_capacity_cents"] == 0
    assert depository["approved_at"] is None
    return depository, public_unit


def _attempt_to_open_an_account(client, depository_id, public_unit_id):
    return client.create_deposit_account(
        create_deposit_account_payload(depository_id, public_unit_id),
        make_public_unit_treasurer_headers(public_unit_id),
    )


def test_an_in_flight_review_does_not_yet_unlock_deposit_taking(client):
    """Opening an account at a DRAFT bank is refused, and the refusal repeats once the
    package has been attested and taken under review: an in-flight review leaves the bank at
    UNDER_REVIEW, which is still not APPROVED.

    PRD: "**Depository approval** — the depository's `approval_status` is `APPROVED`, else
    `ERR_DEPOSITORY_NOT_APPROVED` (HTTP 409). This rung guards six operations: opening a deposit
    account, crediting a deposit, debiting a withdrawal, circulating a pledge agreement,
    registering a collateral asset, and creating a pledge allocation."
    PRD: "Taking an `ATTESTED` package under review drives the review to `UNDER_REVIEW` and
    simultaneously carries the depository from `DRAFT` to `UNDER_REVIEW`, incrementing the
    depository's `version`; the depository must be in `DRAFT` or `UNDER_REVIEW` for this to be
    admissible."

    Design: Difficulty/cross_entity_state_dependency/deposit_account_requires_approved_depository
    """
    depository, public_unit = _candidate_bank_with_a_registered_unit(client)

    from_draft = _attempt_to_open_an_account(client, depository["id"], public_unit["id"])
    validate_error(from_draft, ApiErrorId.ERR_DEPOSITORY_NOT_APPROVED.value, 409)

    review = fixtures.file_qualification_review(client, depository["id"])
    fixtures.attest_review(client, review["id"])
    fixtures.begin_review(client, review["id"])

    under_review = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert under_review["approval_status"] == "UNDER_REVIEW"
    assert under_review["approved_pledge_capacity_cents"] == 0

    from_under_review = _attempt_to_open_an_account(
        client, depository["id"], public_unit["id"]
    )
    validate_error(from_under_review, ApiErrorId.ERR_DEPOSITORY_NOT_APPROVED.value, 409)

    _accounts, meta = validate_paginated(
        client.list_deposit_accounts(OFFICER, {"depository_id": depository["id"]})
    )
    assert meta["total_count"] == 0


def test_the_regulators_approval_is_what_opens_the_bank_for_business(client):
    """The decision that carries the bank to APPROVED also copies the requested capacity and
    stamps approved_at, and only then does the identical account-opening request succeed —
    landing PENDING_FUNDING, UNSECURED and with an empty ledger.

    PRD: "An approval requires the review to be `UNDER_REVIEW` with a non-null
    `attested_by_user_id`; it sets the review to `APPROVED` with `decided_at` stamped from the
    clock, carries the depository from `UNDER_REVIEW` to `APPROVED` with `approved_at` stamped,
    copies `requested_pledge_capacity_cents` into the depository's
    `approved_pledge_capacity_cents`, and increments the depository's `version`."
    PRD: "The new account's `funding_status` is `PENDING_FUNDING` and its `collateral_status` is
    `UNSECURED`; `ledger_balance_cents`, `insured_amount_cents`, `uninsured_amount_cents`,
    `required_collateral_pct_bps`, `required_collateral_cents`, `assigned_collateral_value_cents`
    and `pooled_allocated_collateral_cents` are all zero; `coverage_ratio_bps` is 10000, because
    an account with no requirement is by definition fully covered; and `restricted_reason` is
    null."
    PRD: "At creation the service assigns `group_sequence`, a monotone integer beginning at 1
    within the account's **insurance group**, which is the triple of `public_unit_id`,
    `depository_id` and `deposit_class`."

    Design: Difficulty/cross_entity_state_dependency/deposit_account_requires_approved_depository
    """
    depository, public_unit = _candidate_bank_with_a_registered_unit(client)

    review = fixtures.file_qualification_review(client, depository["id"])
    fixtures.attest_review(client, review["id"])
    fixtures.begin_review(client, review["id"])
    decided = fixtures.decide_review(client, review["id"], "APPROVE")
    assert decided["status"] == "APPROVED"

    approved = get_success_data(client.get_depository(depository["id"], REGULATOR), 200)
    assert approved["approval_status"] == "APPROVED"
    assert approved["approved_pledge_capacity_cents"] == 400_000_000_000
    assert approved["approved_at"] == clock_stamp(DEFAULT_CLOCK_UTC)

    account = get_success_data(
        _attempt_to_open_an_account(client, depository["id"], public_unit["id"]), 201
    )
    assert account["funding_status"] == "PENDING_FUNDING"
    assert account["collateral_status"] == "UNSECURED"
    assert account["ledger_balance_cents"] == 0
    assert account["coverage_ratio_bps"] == 10000
    assert account["group_sequence"] == 1
    assert account["restricted_reason"] is None

    _accounts, meta = validate_paginated(
        client.list_deposit_accounts(OFFICER, {"depository_id": depository["id"]})
    )
    assert meta["total_count"] == 1
