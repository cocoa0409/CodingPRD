"""
Compensating actions and the identities they must restore.

Three reversals are exercised here — a reversed transfer, a charged-back refund
credit, and the two ways a submitted disposition election is undone — and in each
case the arithmetic identity the estate publishes is asserted both before and
after the compensation, to the cent.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f, fixtures
from test_helpers.api_errors import ERR_CREDIT_EXCEEDS_CLAIM, ERR_STALE_ASSET_VERSION
from test_helpers.assertions import (
    assert_estate_value_identity,
    assert_fields,
    assert_inventory_counter_identity,
    assert_not_null_fields,
    assert_null_fields,
    assert_refund_recovered_identity,
)
from test_helpers.constants import (
    CLAIM_ACTION_CHARGE_BACK,
    CLAIM_ACTION_CREDIT,
    CLAIM_CHARGED_BACK,
    CLAIM_CREDITED,
    CLAIM_PLATFORM_REVIEW,
    DISPOSITION_ELECTED,
    DISPOSITION_EXECUTED,
    DISPOSITION_PENDING,
    ELECTION_DELETE,
    ELECTION_EXECUTED,
    ELECTION_MEMORIALIZE,
    ELECTION_PENDING_COUNTERSIGN,
    ELECTION_REJECTED,
    ELECTION_REVERSED,
    ELECTION_SUPERSEDED,
    ELECTION_TRANSFER,
    EL_ACTION_EXECUTE,
    EL_ACTION_REJECT,
    EL_ACTION_REVERSE,
    PHASE_DISCLOSURE,
    PHASE_WIND_DOWN,
)
from test_helpers.test_users import make_platform_compliance_headers


def _transfer_election_ready_to_execute(api):
    """
    One transferable cloud-storage account quoted at 400033 cents, disclosed and
    appraised, with the whole estate willed to a single beneficiary and a TRANSFER
    election already SUBMITTED against it.
    """
    fixtures.set_clock(api)
    platform = fixtures.register_platform(api)
    ctx = fixtures.authorized_estate(api, "PR-2737-W")
    asset = fixtures.add_asset(
        api, ctx, platform["id"], account_handle="vault-transfer", quoted_value_cents=400033
    )
    beneficiary = fixtures.add_beneficiary(api, ctx)
    fixtures.approved_request(api, ctx, platform["id"], platform["form_code"])
    run = fixtures.computed_valuation_run(api, ctx)
    assert_fields(run, gross_value_cents=400033, included_asset_count=1)
    election = fixtures.submitted_election(
        api,
        ctx,
        asset["id"],
        election=ELECTION_TRANSFER,
        beneficiary_designation_id=beneficiary["id"],
    )
    return platform, ctx, asset, beneficiary, run, election


def test_transfer_execution_moves_value_and_keeps_the_estate_value_identity(api):
    """
    Before the transfer the whole appraised gross is undistributed and the
    beneficiary has received nothing. Executing the transfer moves the account's
    appraised value across in one step, and the estate's gross still splits
    exactly between what is undistributed and what has vested.

    PRD: "When all three hold, the election's `distributed_value_cents` is set to the account's `appraised_value_cents`, the designation's `received_value_cents` rises by that amount, the estate's `undistributed_value_cents` falls by the same amount, and the account's `disposition_status` becomes `EXECUTED` with `disposed_at` stamped."

    Design: Difficulty/compensating_invariant/transfer_reversal_restores_the_gross_equals_undistributed_plus_received_identity
    """
    platform, ctx, asset, beneficiary, run, election = _transfer_election_ready_to_execute(api)

    before_estate = fixtures.read_estate(api, ctx)
    before_beneficiary = fixtures.read_designation(api, ctx, beneficiary["id"])
    assert_fields(
        before_estate, gross_digital_estate_cents=400033, undistributed_value_cents=400033
    )
    assert_fields(
        before_beneficiary, planned_allocation_cents=400033, received_value_cents=0
    )
    assert_estate_value_identity(before_estate, [before_beneficiary])

    executed = validate_success(
        api.transition_disposition_election(
            election["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-XFER-1"
            ),
            make_platform_compliance_headers(platform["id"]),
        ),
        200,
    )
    assert_fields(
        executed, status=ELECTION_EXECUTED, distributed_value_cents=400033
    )

    after_estate = fixtures.read_estate(api, ctx)
    after_beneficiary = fixtures.read_designation(api, ctx, beneficiary["id"])
    assert_fields(
        after_estate, gross_digital_estate_cents=400033, undistributed_value_cents=0
    )
    assert_fields(after_beneficiary, received_value_cents=400033)
    assert_estate_value_identity(after_estate, [after_beneficiary])
    assert_fields(
        fixtures.read_asset(api, ctx, asset["id"]),
        disposition_status=DISPOSITION_EXECUTED,
        appraised_value_cents=400033,
    )


def test_transfer_reversal_restores_the_estate_value_identity(api):
    """
    Reversing an executed transfer must put every cent back exactly where it was:
    the beneficiary's received value returns to zero, the estate's undistributed
    pool returns to the full gross, and the election's distributed value is reset,
    so the identity holds on both sides of the compensation.

    PRD: "For a `TRANSFER` the compensation is exact and complete: the designation's `received_value_cents` is reduced by the election's `distributed_value_cents`, the estate's `undistributed_value_cents` is increased by the same amount, and `distributed_value_cents` is reset to 0, leaving the ledger byte-for-byte where it stood before the execution."

    Design: Difficulty/compensating_invariant/transfer_reversal_restores_the_gross_equals_undistributed_plus_received_identity
    """
    platform, ctx, asset, beneficiary, run, election = _transfer_election_ready_to_execute(api)
    compliance = make_platform_compliance_headers(platform["id"])

    validate_success(
        api.transition_disposition_election(
            election["id"],
            f.election_transition_payload(
                EL_ACTION_EXECUTE, platform_confirmation_reference="CV-XFER-1"
            ),
            compliance,
        ),
        200,
    )
    mid_estate = fixtures.read_estate(api, ctx)
    mid_beneficiary = fixtures.read_designation(api, ctx, beneficiary["id"])
    assert_fields(mid_estate, undistributed_value_cents=0, administration_phase=PHASE_WIND_DOWN)
    assert_fields(mid_beneficiary, received_value_cents=400033)
    assert_estate_value_identity(mid_estate, [mid_beneficiary])

    reversed_election = validate_success(
        api.transition_disposition_election(
            election["id"],
            f.election_transition_payload(
                EL_ACTION_REVERSE, reason="beneficiary declined the account"
            ),
            compliance,
        ),
        200,
    )
    assert_fields(
        reversed_election, status=ELECTION_REVERSED, distributed_value_cents=0
    )
    assert_null_fields(reversed_election, "executed_at")

    final_estate = fixtures.read_estate(api, ctx)
    final_beneficiary = fixtures.read_designation(api, ctx, beneficiary["id"])
    assert_fields(
        final_estate,
        gross_digital_estate_cents=400033,
        undistributed_value_cents=400033,
        administration_phase=PHASE_DISCLOSURE,
    )
    assert_fields(final_beneficiary, received_value_cents=0)
    assert_estate_value_identity(final_estate, [final_beneficiary])

    final_asset = fixtures.read_asset(api, ctx, asset["id"])
    assert_fields(
        final_asset,
        disposition_status=DISPOSITION_PENDING,
        appraised_value_cents=400033,
    )
    assert_null_fields(final_asset, "disposed_at")
    assert_fields(fixtures.read_run(api, ctx, run["id"]), gross_value_cents=400033)


def _two_claims_in_platform_review(api):
    """
    One annual subscription term of 11999 cents cancelled and confirmed, with two
    disjoint refund claims — 291 days worth 9566 cents and 59 days worth 1940
    cents — both open on the provider's desk.
    """
    fixtures.set_clock(api)
    platform = fixtures.register_subscription_platform(api)
    ctx = fixtures.authorized_estate(api, "PR-2737-X")
    bundle = fixtures.subscription_with_confirmed_order(api, ctx, platform)
    first = fixtures.claim_in_platform_review(
        api, ctx, platform["id"], bundle["order"]["id"], "2026-03-16", "2026-12-31"
    )
    second = fixtures.claim_in_platform_review(
        api, ctx, platform["id"], bundle["order"]["id"], "2026-01-01", "2026-02-28"
    )
    assert_fields(first, claimed_days=291, claimed_cents=9566, credited_cents=0)
    assert_fields(second, claimed_days=59, claimed_cents=1940, credited_cents=0)
    return platform, ctx, bundle, first, second


def test_credits_accumulate_into_the_refund_recovered_mirror(api):
    """
    The estate's recovered-refund figure is a mirror of its credited claims, so it
    starts at zero while both claims are still under review and rises by exactly
    the amount each credit actually paid — 9000 on a 9566-cent claim, then 1940 on
    a 1940-cent one.

    PRD: "And the recovered-refund mirror must always match its source: `refund_recovered_cents` equals the sum of `credited_cents` over exactly those claims whose `status` is `CREDITED`."

    Design: Difficulty/compensating_invariant/charge_back_restores_refund_recovered_to_the_sum_of_credited_claims
    """
    platform, ctx, bundle, first, second = _two_claims_in_platform_review(api)
    compliance = make_platform_compliance_headers(platform["id"])

    before = fixtures.read_estate(api, ctx)
    assert_fields(before, refund_recovered_cents=0)
    assert_refund_recovered_identity(before, [first, second])

    credited_first = validate_success(
        api.transition_refund_claim(
            first["id"],
            f.claim_transition_payload(CLAIM_ACTION_CREDIT, credited_cents=9000),
            compliance,
        ),
        200,
    )
    assert_fields(credited_first, status=CLAIM_CREDITED, credited_cents=9000)
    after_first = fixtures.read_estate(api, ctx)
    assert_fields(after_first, refund_recovered_cents=9000)
    assert_refund_recovered_identity(after_first, [credited_first, second])

    credited_second = validate_success(
        api.transition_refund_claim(
            second["id"],
            f.claim_transition_payload(CLAIM_ACTION_CREDIT, credited_cents=1940),
            compliance,
        ),
        200,
    )
    assert_fields(credited_second, status=CLAIM_CREDITED, credited_cents=1940)
    after_second = fixtures.read_estate(api, ctx)
    assert_fields(after_second, refund_recovered_cents=10940)
    assert_refund_recovered_identity(after_second, [credited_first, credited_second])


def test_charge_back_subtracts_the_stored_credit_and_restores_the_identity(api):
    """
    Charging back the larger claim must subtract the 9000 cents the provider
    actually paid, not the 9566 cents that were claimed, leaving 1940 behind and
    releasing the charged-back interval. The stored credit stays on the claim for
    audit, and the mirror still matches the sum over credited claims.

    PRD: "The provider's desk may charge back a `CREDITED` claim, advancing it to the terminal `CHARGED_BACK`, storing a `chargeback_reason` and compensating exactly: the estate's `refund_recovered_cents` is reduced by the claim's `credited_cents`, and the claimed interval is released just as a denial releases it."

    Design: Difficulty/compensating_invariant/charge_back_restores_refund_recovered_to_the_sum_of_credited_claims
    """
    platform, ctx, bundle, first, second = _two_claims_in_platform_review(api)
    compliance = make_platform_compliance_headers(platform["id"])

    credited_first = validate_success(
        api.transition_refund_claim(
            first["id"],
            f.claim_transition_payload(CLAIM_ACTION_CREDIT, credited_cents=9000),
            compliance,
        ),
        200,
    )
    credited_second = validate_success(
        api.transition_refund_claim(
            second["id"],
            f.claim_transition_payload(CLAIM_ACTION_CREDIT, credited_cents=1940),
            compliance,
        ),
        200,
    )
    mid = fixtures.read_estate(api, ctx)
    assert_fields(mid, refund_recovered_cents=10940)
    assert_refund_recovered_identity(mid, [credited_first, credited_second])
    assert_fields(
        fixtures.read_term(api, ctx, bundle["term"]["id"]), claimed_days_total=350
    )

    charged_back = validate_success(
        api.transition_refund_claim(
            first["id"],
            f.claim_transition_payload(
                CLAIM_ACTION_CHARGE_BACK, reason="provider clawed the credit back"
            ),
            compliance,
        ),
        200,
    )
    assert_fields(charged_back, status=CLAIM_CHARGED_BACK, credited_cents=9000)
    assert_not_null_fields(charged_back, "chargeback_reason")

    after = fixtures.read_estate(api, ctx)
    assert_fields(after, refund_recovered_cents=1940)
    assert_refund_recovered_identity(after, [charged_back, credited_second])
    assert_fields(
        fixtures.read_claim(api, ctx, second["id"]),
        status=CLAIM_CREDITED,
        credited_cents=1940,
    )
    assert_fields(
        fixtures.read_term(api, ctx, bundle["term"]["id"]), claimed_days_total=59
    )


def test_a_credit_larger_than_the_claim_leaves_the_mirror_untouched(api):
    """
    A credit of 9567 cents against a claim entitled to 9566 is refused, and
    nothing moves: the claim stays on the provider's desk with no credit stored
    and the estate's recovered-refund mirror stays at zero.

    PRD: "Crediting advances the claim to `CREDITED`, stores the `credited_cents` the provider actually paid — which must not exceed `claimed_cents`, with an exactly equal credit accepted and a larger one rejected as `ERR_CREDIT_EXCEEDS_CLAIM` — and adds that amount to the estate's `refund_recovered_cents`."

    Design: Difficulty/compensating_invariant/charge_back_restores_refund_recovered_to_the_sum_of_credited_claims
    """
    platform, ctx, bundle, first, second = _two_claims_in_platform_review(api)
    compliance = make_platform_compliance_headers(platform["id"])

    response = api.transition_refund_claim(
        first["id"],
        f.claim_transition_payload(CLAIM_ACTION_CREDIT, credited_cents=9567),
        compliance,
    )
    validate_error(response, ERR_CREDIT_EXCEEDS_CLAIM)

    unchanged = fixtures.read_claim(api, ctx, first["id"])
    assert_fields(
        unchanged,
        status=CLAIM_PLATFORM_REVIEW,
        claimed_cents=9566,
        credited_cents=0,
    )
    estate = fixtures.read_estate(api, ctx)
    assert_fields(estate, refund_recovered_cents=0)
    assert_refund_recovered_identity(estate, [unchanged, second])


def _one_disposed_and_one_elected_asset(api):
    """
    Two catalogue-disclosed cloud-storage accounts on one estate: the first already
    memorialized and disposed, the second carrying a SUBMITTED MEMORIALIZE
    election, so the counters read inventory 2, pending 1, disposed 1.
    """
    fixtures.set_clock(api)
    platform = fixtures.register_platform(api)
    ctx = fixtures.authorized_estate(api, "PR-2737-Y")
    first_asset = fixtures.add_asset(
        api, ctx, platform["id"], account_handle="vault-one", quoted_value_cents=50000
    )
    second_asset = fixtures.add_asset(
        api, ctx, platform["id"], account_handle="vault-two", quoted_value_cents=60000
    )
    fixtures.approved_request(api, ctx, platform["id"], platform["form_code"])
    fixtures.executed_election(
        api,
        ctx,
        platform["id"],
        first_asset["id"],
        platform_confirmation_reference="CV-MEM-Y1",
    )
    election = fixtures.submitted_election(api, ctx, second_asset["id"])
    return platform, ctx, first_asset, second_asset, election


def test_provider_rejection_restores_the_inventory_counter_identity(api):
    """
    A rejected election hands the account back to the fiduciary as PENDING, so the
    estate's inventory still splits exactly into pending and disposed — two
    accounts, one of each — and the already-executed account is left alone.

    PRD: "Rejection returns the account's `disposition_status` to `PENDING` so a different disposition may be elected, and recomputes the estate's counters."

    Design: Difficulty/compensating_invariant/rejection_and_supersession_both_restore_the_inventory_counter_identity
    """
    platform, ctx, first_asset, second_asset, election = _one_disposed_and_one_elected_asset(api)

    before = fixtures.read_estate(api, ctx)
    assert_fields(
        before,
        inventory_total_count=2,
        assets_pending_disposition_count=1,
        assets_disposed_count=1,
    )
    assert_inventory_counter_identity(before)
    assert_fields(
        fixtures.read_asset(api, ctx, second_asset["id"]),
        disposition_status=DISPOSITION_ELECTED,
    )

    rejected = validate_success(
        api.transition_disposition_election(
            election["id"],
            f.election_transition_payload(
                EL_ACTION_REJECT, reason="account already closed by next of kin"
            ),
            make_platform_compliance_headers(platform["id"]),
        ),
        200,
    )
    assert_fields(rejected, status=ELECTION_REJECTED)
    assert_not_null_fields(rejected, "rejection_reason")

    after = fixtures.read_estate(api, ctx)
    assert_fields(
        after,
        inventory_total_count=2,
        assets_pending_disposition_count=1,
        assets_disposed_count=1,
    )
    assert_inventory_counter_identity(after)
    assert_fields(
        fixtures.read_asset(api, ctx, second_asset["id"]),
        disposition_status=DISPOSITION_PENDING,
    )
    assert_fields(
        fixtures.read_asset(api, ctx, first_asset["id"]),
        disposition_status=DISPOSITION_EXECUTED,
    )


def test_supersession_of_a_submitted_election_restores_the_inventory_counter_identity(api):
    """
    Electing a deletion over a live memorialization supersedes the earlier
    election and hands the account back to PENDING, because a DELETE opens at
    PENDING_COUNTERSIGN and cannot drive the account yet. The counters must again
    read two accounts split one pending, one disposed.

    PRD: "Either way, creating an election supersedes whatever came before it: every earlier election on the same account whose `status` is `DRAFT`, `PENDING_COUNTERSIGN` or `SUBMITTED` moves to the terminal `SUPERSEDED`, and if the superseded election had reached `SUBMITTED` — meaning it had already moved the account's `disposition_status` to `ELECTED` — the account is returned to `PENDING` so the new election can drive it."

    Design: Difficulty/compensating_invariant/rejection_and_supersession_both_restore_the_inventory_counter_identity
    """
    platform, ctx, first_asset, second_asset, election = _one_disposed_and_one_elected_asset(api)

    live = fixtures.read_estate(api, ctx)
    assert_fields(
        live,
        inventory_total_count=2,
        assets_pending_disposition_count=1,
        assets_disposed_count=1,
    )
    assert_inventory_counter_identity(live)

    superseding = validate_success(
        api.create_disposition_election(
            second_asset["id"],
            f.election_payload(
                fixtures.asset_version(api, ctx, second_asset["id"]),
                election=ELECTION_DELETE,
            ),
            ctx.fiduciary_headers,
        ),
        201,
    )
    assert_fields(
        superseding, election=ELECTION_DELETE, status=ELECTION_PENDING_COUNTERSIGN
    )
    assert_fields(
        fixtures.read_election(api, ctx, election["id"]),
        election=ELECTION_MEMORIALIZE,
        status=ELECTION_SUPERSEDED,
    )

    after = fixtures.read_estate(api, ctx)
    assert_fields(
        after,
        inventory_total_count=2,
        assets_pending_disposition_count=1,
        assets_disposed_count=1,
    )
    assert_inventory_counter_identity(after)
    assert_fields(
        fixtures.read_asset(api, ctx, second_asset["id"]),
        disposition_status=DISPOSITION_PENDING,
    )
    assert_fields(
        fixtures.read_asset(api, ctx, first_asset["id"]),
        disposition_status=DISPOSITION_EXECUTED,
    )


def test_an_election_built_on_a_stale_reading_leaves_the_counters_alone(api):
    """
    Creation bumps the account's version, so replaying the same creation with the
    reading it was built on is refused on the concurrency check. Nothing about the
    estate moves: the superseding election stands and the counters still balance.

    PRD: "Creation also increases the account's `version` by one, which is why a second election attempt built on a stale reading fails the concurrency check with `ERR_STALE_ASSET_VERSION`."

    Design: Difficulty/compensating_invariant/rejection_and_supersession_both_restore_the_inventory_counter_identity
    """
    platform, ctx, first_asset, second_asset, election = _one_disposed_and_one_elected_asset(api)

    stale_version = fixtures.asset_version(api, ctx, second_asset["id"])
    superseding = validate_success(
        api.create_disposition_election(
            second_asset["id"],
            f.election_payload(stale_version, election=ELECTION_DELETE),
            ctx.fiduciary_headers,
        ),
        201,
    )

    replay = api.create_disposition_election(
        second_asset["id"],
        f.election_payload(stale_version, election=ELECTION_DELETE),
        ctx.fiduciary_headers,
    )
    validate_error(replay, ERR_STALE_ASSET_VERSION)

    assert_fields(
        fixtures.read_election(api, ctx, superseding["id"]),
        status=ELECTION_PENDING_COUNTERSIGN,
    )
    estate = fixtures.read_estate(api, ctx)
    assert_fields(
        estate,
        inventory_total_count=2,
        assets_pending_disposition_count=1,
        assets_disposed_count=1,
    )
    assert_inventory_counter_identity(estate)
