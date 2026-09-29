"""Lifecycle mechanics: initial states, declared transitions, terminal lockdowns, the
cascades a transition fires, and the two loops that must terminate."""

from test_helpers import fixtures, get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import DEFAULT_CLOCK_UTC, clock_stamp
from test_helpers.factories import (
    create_qualification_review_payload,
    decide_payload,
    return_for_info_payload,
    signature_payload,
)
from test_helpers.fixtures import COMPLIANCE, OFFICER, REGULATOR
from test_helpers.test_users import (
    make_custodian_headers,
    make_public_unit_treasurer_headers,
)

SECOND_DAY = "2026-08-02T00:00:00Z"
THIRD_DAY = "2026-08-03T00:00:00Z"
FOURTH_DAY = "2026-08-04T00:00:00Z"
FIFTH_DAY = "2026-08-05T00:00:00Z"


def _read_review(client, depository_id, review_id):
    """Re-read one qualification package through the depository's review listing."""
    reviews, _meta = validate_paginated(
        client.list_qualification_reviews(depository_id, REGULATOR)
    )
    matches = [review for review in reviews if review["id"] == review_id]
    assert len(matches) == 1
    return matches[0]


def test_freshly_created_records_land_on_their_declared_initial_states(client):
    """A candidate bank is DRAFT, its filed package is SUBMITTED, a new account is
    PENDING_FUNDING, a drafted agreement is DRAFT with no stamps and no par, and a
    registered security is ELIGIBLE and UNPLEDGED at the default par price of 10000 basis
    points.

    PRD: "A new depository starts at `approval_status` `DRAFT`, `collateral_posture`
    `COMPLIANT`, `risk_grade` `A` with `risk_score_bps` zero, `consecutive_deficiency_runs`
    zero, `open_margin_call_count` zero, `approved_pledge_capacity_cents` zero, a null
    `approved_at`, `mtm_run_index` zero, a null `last_mtm_window_end`, and
    `total_required_collateral_cents`, `total_pledged_collateral_value_cents` and
    `total_pledged_par_cents` all zero."
    PRD: "The filed review is `SUBMITTED`, its `depository_id` is taken from the path rather
    than the body, its `submitted_by_user_id` records the filing officer's `X-User-ID`, and
    its `round_count` is 1."
    PRD: "The new account's `funding_status` is `PENDING_FUNDING` and its `collateral_status`
    is `UNSECURED`; `ledger_balance_cents`, `insured_amount_cents`, `uninsured_amount_cents`,
    `required_collateral_pct_bps`, `required_collateral_cents`,
    `assigned_collateral_value_cents` and `pooled_allocated_collateral_cents` are all zero;
    `coverage_ratio_bps` is 10000, because an account with no requirement is by definition
    fully covered; and `restricted_reason` is null."
    PRD: "A drafted agreement begins at `status` `DRAFT` with `signature_count` zero,
    `amendment_round` zero, all three party stamps (`depository_signed_at`,
    `public_unit_signed_at`, `custodian_signed_at`) null, both `executed_at` and
    `terminated_at` null, and `total_pledged_par_cents`, `total_collateral_value_cents` and
    `active_allocation_count` all zero."
    PRD: "A newly registered asset has `priced_at` stamped from the logical clock,
    `pledged_par_cents` at zero, `available_par_cents` equal to its full `par_value_cents`,
    `eligibility_status` `ELIGIBLE`, `pledge_status` `UNPLEDGED` and `ineligible_reason`
    null, with its two value mirrors computed as described below."
    PRD: "An optional `market_price_bps` may be supplied at registration — the clean price
    per 100 of par in basis points, where 10000 means the security trades exactly at par —
    and it defaults to 10000 when omitted."

    Design: Corner/state_machines/initial_states_of_agreement_asset_and_review_on_creation
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")

    candidate = fixtures.create_draft_depository(client, name="Ridge National Bank")
    assert candidate["approval_status"] == "DRAFT"

    review = fixtures.file_qualification_review(client, candidate["id"])
    assert review["status"] == "SUBMITTED"

    fixtures.attest_review(client, review["id"])
    fixtures.begin_review(client, review["id"])
    fixtures.decide_review(client, review["id"], "APPROVE")

    account = fixtures.create_deposit_account(
        client,
        candidate["id"],
        public_unit["id"],
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    assert account["funding_status"] == "PENDING_FUNDING"

    agreement = fixtures.draft_dedicated_agreement(
        client, candidate["id"], custodian["id"], account["id"]
    )
    assert agreement["status"] == "DRAFT"
    assert agreement["signature_count"] == 0
    assert agreement["depository_signed_at"] is None
    assert agreement["public_unit_signed_at"] is None
    assert agreement["custodian_signed_at"] is None
    assert agreement["amendment_round"] == 0
    assert agreement["executed_at"] is None
    assert agreement["terminated_at"] is None
    assert agreement["total_pledged_par_cents"] == 0
    assert agreement["active_allocation_count"] == 0

    asset = get_success_data(
        client.create_collateral_asset(
            {
                "depository_id": candidate["id"],
                "custodian_id": custodian["id"],
                "cusip": fixtures.next_cusip(),
                "asset_type": "US_TREASURY",
                "par_value_cents": 1_000_000,
            },
            OFFICER,
        ),
        201,
    )
    assert asset["eligibility_status"] == "ELIGIBLE"
    assert asset["pledge_status"] == "UNPLEDGED"
    assert asset["market_price_bps"] == 10000


def test_state_approval_moves_the_custodian_and_stamps_the_approval_clock(client):
    """A custodian registered on the first of the month and approved on the second is
    APPROVED with approved_at taken from the clock at approval time rather than at
    registration time, on version 2, with its type and concentration limit untouched.

    PRD: "A freshly registered custodian's `approval_status` is `PENDING_APPROVAL` and its
    `approved_at` is null."
    PRD: "State approval moves `approval_status` to `APPROVED` and stamps `approved_at` with
    the logical clock."
    PRD: "Most resources additionally carry `updated_at`, refreshed on every mutation using
    the same format, and `version`, an integer that starts at 1 when the resource is created
    and increments by exactly 1 on every mutation of that resource."

    Design: Corner/state_machines/valid_transition_custodian_pending_to_approved
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_custodian(
        client,
        name="First Custody Bank",
        custodian_type="FEDERAL_RESERVE",
        tri_party_capable=True,
        concentration_limit_bps=10000,
    )
    assert custodian["approval_status"] == "PENDING_APPROVAL"
    assert custodian["approved_at"] is None
    assert custodian["version"] == 1

    fixtures.set_clock(client, SECOND_DAY)
    approved = get_success_data(client.approve_custodian(custodian["id"], REGULATOR), 200)

    assert approved["approval_status"] == "APPROVED"
    assert approved["approved_at"] == clock_stamp(SECOND_DAY)
    assert approved["version"] == 2
    assert approved["created_at"].startswith("2026-08-01T00:00:00")
    assert approved["updated_at"].startswith("2026-08-02T00:00:00")
    assert approved["custodian_type"] == "FEDERAL_RESERVE"
    assert approved["concentration_limit_bps"] == 10000


def test_a_draft_agreement_cannot_be_signed_until_it_is_circulated(client):
    """Stamping a party on an agreement that has never been circulated is refused as
    inadmissible even though the acting role is the entitled one, nothing is written, and the
    very same call succeeds once the draft has been circulated.

    PRD: "**State admissibility** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."
    PRD: "Circulating the draft carries it to `PENDING_SIGNATURES`."
    PRD: "While fewer than three stamps are present the agreement self-loops in
    `PENDING_SIGNATURES`."
    PRD: "Each accepted signature stamps the matching `_signed_at` field with the logical
    clock, recomputes `signature_count` as the number of non-null party stamps, and
    increments the agreement's `version`."

    Design: Corner/state_machines/precondition_signature_on_draft_agreement_rejected
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_deposit_account(
        client, depository["id"], public_unit["id"], pledging_mode="DEDICATED"
    )
    agreement = fixtures.draft_dedicated_agreement(
        client, depository["id"], custodian["id"], account["id"]
    )

    response = client.create_signature(
        agreement["id"], signature_payload("DEPOSITORY"), COMPLIANCE
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    untouched = get_success_data(client.get_pledge_agreement(agreement["id"], OFFICER), 200)
    assert untouched["status"] == "DRAFT"
    assert untouched["signature_count"] == 0
    assert untouched["depository_signed_at"] is None
    assert untouched["version"] == 1

    circulated = fixtures.circulate(client, agreement["id"])
    assert circulated["status"] == "PENDING_SIGNATURES"

    stamped = fixtures.sign(client, agreement["id"], "DEPOSITORY", COMPLIANCE)
    assert stamped["signature_count"] == 1
    assert stamped["depository_signed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)


def test_a_denied_qualification_locks_the_bank_out_for_good(client):
    """Denial is terminal on both sides: the decided package can be neither re-decided nor
    returned for more information, no fresh package may be filed under the denied bank, and
    the bank keeps a zero capacity and a null approval stamp throughout.

    PRD: "A denial sets the review to `DENIED` with `decided_at` stamped, carries the
    depository to `DENIED`, resets `approved_pledge_capacity_cents` to zero, and increments
    the depository's `version`."
    PRD: "`DENIED` is terminal for the depository: no further review may be opened or
    progressed against it, and attempts are refused with `ERR_INVALID_STATE`."
    PRD: "**State admissibility** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminal_state_lockdown_after_denied_qualification_review
    """
    fixtures.set_clock(client)
    depository = fixtures.create_draft_depository(
        client, name="Rejected Bank", charter_type="NATIONAL", capital_ratio_bps=700
    )
    review = fixtures.file_qualification_review(client, depository["id"])
    fixtures.attest_review(client, review["id"])
    fixtures.begin_review(client, review["id"])
    denied = fixtures.decide_review(
        client, review["id"], "DENY", decision_note="Capital ratio below adequate floor"
    )
    assert denied["status"] == "DENIED"

    second_decision = client.decide_qualification_review(
        review["id"], decide_payload("APPROVE"), REGULATOR
    )
    validate_error(second_decision, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert _read_review(client, depository["id"], review["id"])["status"] == "DENIED"

    reopened = client.return_for_info_qualification_review(
        review["id"],
        return_for_info_payload(info_request_note="Please resubmit capital schedule"),
        REGULATOR,
    )
    validate_error(reopened, ApiErrorId.ERR_INVALID_STATE.value, 409)
    still_denied = _read_review(client, depository["id"], review["id"])
    assert still_denied["info_request_note"] is None
    assert still_denied["status"] == "DENIED"

    refiled = client.create_qualification_review(
        depository["id"],
        create_qualification_review_payload(requested_pledge_capacity_cents=100_000_000),
        OFFICER,
    )
    validate_error(refiled, ApiErrorId.ERR_INVALID_STATE.value, 409)

    reviews, meta = validate_paginated(
        client.list_qualification_reviews(depository["id"], REGULATOR)
    )
    assert meta["total_count"] == 1
    assert reviews[0]["id"] == review["id"]

    bank = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert bank["approval_status"] == "DENIED"
    assert bank["approved_pledge_capacity_cents"] == 0
    assert bank["approved_at"] is None


def test_approving_an_already_approved_custodian_is_refused_without_restamping(client):
    """Approval is not idempotent: the second approve four days later is refused outright
    rather than silently re-stamping, so approved_at still reads the original approval
    instant and the record is still on version 2.

    PRD: "State approval moves `approval_status` to `APPROVED` and stamps `approved_at` with
    the logical clock."
    PRD: "**State admissibility** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."
    PRD: "Most resources additionally carry `updated_at`, refreshed on every mutation using
    the same format, and `version`, an integer that starts at 1 when the resource is created
    and increments by exactly 1 on every mutation of that resource."

    Design: Corner/state_machines/idempotency_second_custodian_approve_rejected
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client, name="First Custody Bank")
    assert custodian["approved_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert custodian["version"] == 2

    fixtures.set_clock(client, FIFTH_DAY)
    response = client.approve_custodian(custodian["id"], REGULATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    unchanged = get_success_data(client.get_custodian(custodian["id"], REGULATOR), 200)
    assert unchanged["approved_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert unchanged["approved_at"] != FIFTH_DAY
    assert unchanged["version"] == 2


def test_terminate_is_refused_while_the_quorum_is_still_incomplete(client):
    """Termination is defined only against an executed agreement, so firing it with two of
    three stamps present is refused and — unlike an amendment request — leaves both stamps
    exactly where they were; once the custodian's stamp executes the document the same
    termination succeeds.

    PRD: "Termination is the regulator's move against an `EXECUTED` agreement, and it is
    blocked while any substitution under that agreement is still in flight — that is, while
    any of its substitution requests is in `SUBMITTED`, `COMPLIANCE_APPROVED`,
    `CUSTODIAN_ACKED` or `READY_TO_SETTLE` status; the attempt is refused with
    `ERR_INVALID_STATE`."
    PRD: "The signature that supplies the third distinct party — that is, the one arriving
    when `signature_count` stood at 2 — carries the agreement to `EXECUTED`, sets
    `signature_count` to 3 and stamps `executed_at` from the clock."
    PRD: "When termination proceeds, the agreement moves to `TERMINATED` with `terminated_at`
    stamped and its `version` incremented, and every one of its allocations still in `ACTIVE`
    is moved to `RELEASED` with `release_reason` set to `AGREEMENT_TERMINATED`."

    Design: Corner/state_machines/invalid_transition_terminate_on_pending_signatures_rejected
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000, pledging_mode="DEDICATED"
    )
    agreement = fixtures.draft_dedicated_agreement(
        client, depository["id"], custodian["id"], account["id"]
    )
    fixtures.circulate(client, agreement["id"])
    fixtures.sign(client, agreement["id"], "DEPOSITORY", COMPLIANCE)
    half_signed = fixtures.sign(
        client,
        agreement["id"],
        "PUBLIC_UNIT",
        make_public_unit_treasurer_headers(public_unit["id"]),
    )
    assert half_signed["status"] == "PENDING_SIGNATURES"
    assert half_signed["signature_count"] == 2

    response = client.terminate_pledge_agreement(agreement["id"], REGULATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    intact = get_success_data(client.get_pledge_agreement(agreement["id"], OFFICER), 200)
    assert intact["status"] == "PENDING_SIGNATURES"
    assert intact["signature_count"] == 2
    assert intact["depository_signed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert intact["public_unit_signed_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert intact["custodian_signed_at"] is None
    assert intact["terminated_at"] is None

    executed = fixtures.sign(
        client, agreement["id"], "CUSTODIAN", make_custodian_headers(custodian["id"])
    )
    assert executed["status"] == "EXECUTED"
    assert executed["signature_count"] == 3

    terminated = fixtures.terminate_agreement(client, agreement["id"])
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_at"] == clock_stamp(DEFAULT_CLOCK_UTC)


def test_termination_releases_the_pledge_and_unwinds_every_mirror(client):
    """Terminating an executed agreement runs its whole side-effect list in one response: the
    active allocation is released with the reason that marks the cascade, the asset's par is
    restored, the agreement and depository totals go to zero, the account falls back to
    UNSECURED while keeping its 78,750,000-cent requirement and its FUNDED status, and the
    owning unit returns to NORMAL.

    PRD: "When termination proceeds, the agreement moves to `TERMINATED` with `terminated_at`
    stamped and its `version` incremented, and every one of its allocations still in `ACTIVE`
    is moved to `RELEASED` with `release_reason` set to `AGREEMENT_TERMINATED`."
    PRD: "Each release restores the underlying asset's `pledged_par_cents` and
    `available_par_cents`, after which the agreement's totals, the depository's pledged totals
    and the beneficiary's coverage — the dedicated account's assigned value, or the pool
    waterfall for a pooled agreement — are all recomputed, followed by the affected public
    units' `exposure_status`."
    PRD: "`SECURED → UNSECURED` and `DEFICIENT → UNSECURED` when every allocation that was
    covering the account has left `ACTIVE`, so `assigned_collateral_value_cents` is zero while
    `required_collateral_cents` is still greater than zero."
    PRD: "The account's second status dimension, `collateral_status`, is a pure function of
    that ratio and of whether any collateral is assigned at all, and it moves entirely
    independently of `funding_status` — a `RESTRICTED` account still travels between
    `UNSECURED`, `SECURED` and `DEFICIENT`, and a `FUNDED` account's collateral status changes
    without any funding transition."

    Design: Corner/state_machines/side_effect_execution_agreement_terminate_releases_active_allocations
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=10_000_000,
        market_price_bps=10000,
    )
    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 10_000_000
    )
    assert allocation["allocated_collateral_value_cents"] == 9_800_000

    before = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert before["required_collateral_cents"] == 78_750_000
    assert before["coverage_ratio_bps"] == 1244
    assert before["collateral_status"] == "DEFICIENT"
    unit_before = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert unit_before["exposure_status"] == "WATCH"

    fixtures.set_clock(client, THIRD_DAY)
    terminated = fixtures.terminate_agreement(client, perimeter["agreement_id"])
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_at"] == clock_stamp(THIRD_DAY)

    released = get_success_data(client.get_pledge_allocation(allocation["id"], OFFICER), 200)
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "AGREEMENT_TERMINATED"
    assert released["released_at"] == clock_stamp(THIRD_DAY)

    freed = get_success_data(client.get_collateral_asset(asset["id"], OFFICER), 200)
    assert freed["pledged_par_cents"] == 0
    assert freed["available_par_cents"] == 10_000_000
    assert freed["pledge_status"] == "UNPLEDGED"
    assert freed["eligibility_status"] == "ELIGIBLE"

    assert terminated["total_pledged_par_cents"] == 0
    assert terminated["total_collateral_value_cents"] == 0
    assert terminated["active_allocation_count"] == 0

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 0
    assert account["coverage_ratio_bps"] == 0
    assert account["collateral_status"] == "UNSECURED"
    assert account["required_collateral_cents"] == 78_750_000
    assert account["funding_status"] == "FUNDED"

    unit = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert unit["exposure_status"] == "NORMAL"

    depository = get_success_data(
        client.get_depository(perimeter["depository_id"], REGULATOR), 200
    )
    assert depository["total_pledged_collateral_value_cents"] == 0


def test_marking_an_asset_ineligible_touches_only_its_active_allocations(client):
    """Declaring an asset ineligible releases the one allocation still ACTIVE, stamping it
    with the ineligibility reason at the current clock, while the allocation the officer had
    already released two days earlier keeps its own reason, its own release stamp and its own
    version — and the agreement itself stays EXECUTED.

    PRD: "Every `ACTIVE` allocation on that asset is then moved to `RELEASED` with
    `release_reason` `ASSET_INELIGIBLE`; each release restores `pledged_par_cents` and
    `available_par_cents`, then recomputes the owning agreement, then the beneficiary — a
    dedicated account's coverage, or the pool waterfall — and finally the affected public
    units' `exposure_status`."
    PRD: "A release sets `status` to `RELEASED`, stamps `released_at` from the clock, records
    `release_reason` as `OFFICER_RELEASE`, and increments the allocation's `version`; it then
    decreases the asset's `pledged_par_cents` by the allocated par, re-derives
    `available_par_cents` and `pledge_status`, recomputes the agreement's totals, recomputes
    the beneficiary (dedicated account coverage, or a fresh pool waterfall run), and finally
    recomputes the affected public units' `exposure_status`."
    PRD: "From `pledged_par_cents` the service also derives `pledge_status`: `UNPLEDGED` when
    nothing is pledged, `PARTIALLY_PLEDGED` when some but not all of the par is pledged, and
    `FULLY_PLEDGED` when the pledged par equals `par_value_cents` exactly."
    PRD: "`RELEASED` and `SUBSTITUTED` are both terminal for an allocation, and the four
    values `release_reason` can take are `OFFICER_RELEASE`, `AGREEMENT_TERMINATED`,
    `ASSET_INELIGIBLE` and `SUBSTITUTION_SETTLED`."

    Design: Corner/state_machines/conditional_cascade_mark_ineligible_touches_only_active_allocations
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=10_000_000,
        market_price_bps=10000,
    )
    first_leg = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 2_000_000
    )
    second_leg = fixtures.create_allocation(
        client, perimeter["agreement_id"], asset["id"], 3_000_000
    )

    fixtures.set_clock(client, SECOND_DAY)
    officer_released = fixtures.release_allocation(client, first_leg["id"])
    assert officer_released["release_reason"] == "OFFICER_RELEASE"
    assert officer_released["released_at"] == clock_stamp(SECOND_DAY)
    released_version = officer_released["version"]

    before_asset = get_success_data(client.get_collateral_asset(asset["id"], OFFICER), 200)
    assert before_asset["pledged_par_cents"] == 3_000_000
    assert before_asset["pledge_status"] == "PARTIALLY_PLEDGED"
    before_account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert before_account["assigned_collateral_value_cents"] == 2_940_000
    assert before_account["coverage_ratio_bps"] == 373
    assert before_account["collateral_status"] == "DEFICIENT"

    fixtures.set_clock(client, FOURTH_DAY)
    ineligible = fixtures.mark_ineligible(
        client,
        asset["id"],
        ineligible_reason="Issuer downgraded below state eligibility floor",
    )
    assert ineligible["eligibility_status"] == "INELIGIBLE"
    assert ineligible["ineligible_reason"] == "Issuer downgraded below state eligibility floor"

    cascaded = get_success_data(client.get_pledge_allocation(second_leg["id"], OFFICER), 200)
    assert cascaded["status"] == "RELEASED"
    assert cascaded["release_reason"] == "ASSET_INELIGIBLE"
    assert cascaded["released_at"] == clock_stamp(FOURTH_DAY)

    skipped = get_success_data(client.get_pledge_allocation(first_leg["id"], OFFICER), 200)
    assert skipped["status"] == "RELEASED"
    assert skipped["release_reason"] == "OFFICER_RELEASE"
    assert skipped["released_at"] == clock_stamp(SECOND_DAY)
    assert skipped["version"] == released_version

    stripped = get_success_data(client.get_collateral_asset(asset["id"], OFFICER), 200)
    assert stripped["pledged_par_cents"] == 0
    assert stripped["available_par_cents"] == 10_000_000
    assert stripped["pledge_status"] == "UNPLEDGED"

    account = get_success_data(
        client.get_deposit_account(perimeter["account_id"], OFFICER), 200
    )
    assert account["assigned_collateral_value_cents"] == 0
    assert account["coverage_ratio_bps"] == 0
    assert account["collateral_status"] == "UNSECURED"

    unit = get_success_data(
        client.get_public_unit(perimeter["public_unit_id"], REGULATOR), 200
    )
    assert unit["exposure_status"] == "NORMAL"

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["active_allocation_count"] == 0
    assert agreement["status"] == "EXECUTED"


def test_the_amendment_loop_stops_after_two_rounds(client):
    """The amendment cycle may run exactly twice: each request voids the stamps collected so
    far and re-circulation reopens the quorum, but the third request is refused, the round
    counter stays at 2, and the document can still be executed afterwards.

    PRD: "Amendment is the counter-move, available to the beneficiary's `PublicUnitTreasurer`
    or to a `StateRegulator` while the agreement sits in `PENDING_SIGNATURES`."
    PRD: "Requesting an amendment carries the agreement to `AMENDMENT_REQUESTED`, increments
    `amendment_round` by 1, and **voids every signature already collected**:
    `depository_signed_at`, `public_unit_signed_at` and `custodian_signed_at` are all reset to
    null and `signature_count` is reset to 0, so the whole quorum must be rebuilt after
    re-circulation."
    PRD: "The incremented `amendment_round` may be at most 2, so the third amendment request
    is refused with `ERR_ROUND_LIMIT_REACHED`."
    PRD: "Re-circulating an amended agreement is additionally admissible only while
    `amendment_round` remains within the ceiling of 2."

    Design: Corner/state_machines/cyclic_amendment_round_limit_blocks_third_amendment
    """
    fixtures.set_clock(client)
    custodian = fixtures.create_approved_custodian(client)
    public_unit = fixtures.create_public_unit(client, unit_type="COUNTY")
    depository = fixtures.create_approved_depository(client)
    account = fixtures.create_funded_account(
        client, depository["id"], public_unit["id"], 100_000_000, pledging_mode="DEDICATED"
    )
    treasurer = make_public_unit_treasurer_headers(public_unit["id"])
    agreement = fixtures.draft_dedicated_agreement(
        client, depository["id"], custodian["id"], account["id"]
    )
    fixtures.circulate(client, agreement["id"])
    fixtures.sign(client, agreement["id"], "DEPOSITORY", COMPLIANCE)

    first_round = fixtures.request_amendment(client, agreement["id"], treasurer)
    assert first_round["status"] == "AMENDMENT_REQUESTED"
    assert first_round["amendment_round"] == 1
    assert first_round["signature_count"] == 0
    assert first_round["depository_signed_at"] is None

    recirculated = fixtures.circulate(client, agreement["id"])
    assert recirculated["status"] == "PENDING_SIGNATURES"
    assert recirculated["amendment_round"] == 1

    fixtures.sign(client, agreement["id"], "DEPOSITORY", COMPLIANCE)

    second_round = fixtures.request_amendment(client, agreement["id"], REGULATOR)
    assert second_round["amendment_round"] == 2
    assert second_round["signature_count"] == 0

    recirculated_again = fixtures.circulate(client, agreement["id"])
    assert recirculated_again["status"] == "PENDING_SIGNATURES"
    assert recirculated_again["amendment_round"] == 2

    response = client.request_amendment(agreement["id"], treasurer)
    validate_error(response, ApiErrorId.ERR_ROUND_LIMIT_REACHED.value, 409)

    frozen = get_success_data(client.get_pledge_agreement(agreement["id"], OFFICER), 200)
    assert frozen["status"] == "PENDING_SIGNATURES"
    assert frozen["amendment_round"] == 2
    assert frozen["depository_signed_at"] is None
    assert frozen["public_unit_signed_at"] is None
    assert frozen["custodian_signed_at"] is None

    fixtures.sign(client, agreement["id"], "DEPOSITORY", COMPLIANCE)
    fixtures.sign(client, agreement["id"], "PUBLIC_UNIT", treasurer)
    executed = fixtures.sign(
        client, agreement["id"], "CUSTODIAN", make_custodian_headers(custodian["id"])
    )
    assert executed["status"] == "EXECUTED"
    assert executed["signature_count"] == 3
    assert executed["amendment_round"] == 2


def test_rejecting_and_withdrawing_a_substitution_moves_no_par(client):
    """Both abort paths leave the pledge ledger exactly as it was: a rejection from
    CUSTODIAN_ACKED keeps the custodian's stamp for the audit trail and still writes no value
    adequacy delta, a withdrawal by the originating officer closes a fresh request from
    SUBMITTED, and after both the outgoing allocation is still ACTIVE with no new allocation
    minted anywhere.

    PRD: "This branch, and only this branch, stamps `custodian_acked_at` from the clock, and it
    increments the request's `version`; it never writes `value_adequacy_delta_cents`, which
    stays null if the custodian acknowledges first."
    PRD: "Rejection sets `status` to `REJECTED`, stores the reason and increments `version`,
    and changes no allocation and no asset field, because the request never moved par; when
    rejecting from `CUSTODIAN_ACKED`, the existing `custodian_acked_at` stamp is retained for
    the audit trail rather than cleared."
    PRD: "The originating `BankCollateralOfficer`, and only the officer whose `X-User-ID`
    equals `submitted_by_user_id`, may **withdraw** a request from any of `SUBMITTED`,
    `COMPLIANCE_APPROVED`, `CUSTODIAN_ACKED` and `READY_TO_SETTLE`, including a late withdrawal
    on the very brink of settlement; withdrawal sets `status` to `WITHDRAWN` and increments
    `version`, and because no par movement occurs, every asset's `available_par_cents` plus
    `pledged_par_cents` remains exactly what it was."
    PRD: "`REJECTED` and `WITHDRAWN` are both terminal."

    Design: Corner/state_machines/branching_substitution_reject_and_withdraw_paths_move_no_par
    """
    perimeter = fixtures.build_dedicated_perimeter(client, deposit_cents=100_000_000)
    outgoing_asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=5_000_000,
        market_price_bps=10000,
    )
    incoming_asset = fixtures.create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        par_value_cents=5_000_000,
        market_price_bps=10000,
    )
    allocation = fixtures.create_allocation(
        client, perimeter["agreement_id"], outgoing_asset["id"], 5_000_000
    )
    assert allocation["allocated_collateral_value_cents"] == 4_900_000

    first_request = fixtures.create_substitution_request(
        client,
        perimeter["agreement_id"],
        allocation["id"],
        incoming_asset["id"],
        5_000_000,
    )
    acked = fixtures.custodian_ack(
        client, first_request["id"], perimeter["custodian_id"]
    )
    assert acked["status"] == "CUSTODIAN_ACKED"
    assert acked["custodian_acked_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert acked["value_adequacy_delta_cents"] is None

    rejected = fixtures.reject_substitution(
        client,
        first_request["id"],
        rejection_reason="Incoming issue not on the approved list",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "Incoming issue not on the approved list"
    assert rejected["custodian_acked_at"] == clock_stamp(DEFAULT_CLOCK_UTC)
    assert rejected["value_adequacy_delta_cents"] is None
    assert rejected["compliance_approved_at"] is None

    second_request = fixtures.create_substitution_request(
        client,
        perimeter["agreement_id"],
        allocation["id"],
        incoming_asset["id"],
        5_000_000,
    )
    assert second_request["status"] == "SUBMITTED"

    withdrawn = fixtures.withdraw_substitution(client, second_request["id"])
    assert withdrawn["status"] == "WITHDRAWN"

    untouched = get_success_data(
        client.get_pledge_allocation(allocation["id"], OFFICER), 200
    )
    assert untouched["status"] == "ACTIVE"

    outgoing = get_success_data(
        client.get_collateral_asset(outgoing_asset["id"], OFFICER), 200
    )
    assert outgoing["pledged_par_cents"] == 5_000_000
    assert outgoing["available_par_cents"] == 0

    incoming = get_success_data(
        client.get_collateral_asset(incoming_asset["id"], OFFICER), 200
    )
    assert incoming["pledged_par_cents"] == 0
    assert incoming["available_par_cents"] == 5_000_000
    assert incoming["pledge_status"] == "UNPLEDGED"

    agreement = get_success_data(
        client.get_pledge_agreement(perimeter["agreement_id"], OFFICER), 200
    )
    assert agreement["total_collateral_value_cents"] == 4_900_000
    assert agreement["active_allocation_count"] == 1

    allocations, allocation_meta = validate_paginated(
        client.list_pledge_allocations(
            OFFICER, {"pledge_agreement_id": perimeter["agreement_id"]}
        )
    )
    assert allocation_meta["total_count"] == 1
    assert allocations[0]["id"] == allocation["id"]

    requests, request_meta = validate_paginated(
        client.list_substitution_requests(
            OFFICER, {"pledge_agreement_id": perimeter["agreement_id"]}
        )
    )
    assert request_meta["total_count"] == 2
    assert sorted(request["status"] for request in requests) == ["REJECTED", "WITHDRAWN"]
