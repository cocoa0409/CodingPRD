"""Distributions: fair-share clamp, allocation cancel conservation,
distribution-cancel cascade, insufficient credits."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_operational_site_to_program,
    create_allocation_payload,
    create_and_accept_drop,
    get_success_data,
    make_participant_headers,
    setup_closed_accepted_batch,
    setup_open_distribution,
    setup_program_with_operational_site,
    setup_verified_participant_with_grant,
    validate_error,
    validate_success,
)


def _setup_isolated_distribution(api, credit_drop_gross_kg=10.00,
                                 yield_ratio=1.0):
    """Participant holds credits from an accepted drop at site A (never
    collected); a feeder participant's drop at site B fills the batch that
    backs the distribution — so batch reconciliation never touches the test
    participant's credits.

    Returns (ids, part, dist_ctx) where part is the test participant dict.
    """
    ids = setup_program_with_operational_site()
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    part = setup_verified_participant_with_grant(prog_id, site_id)
    # Credit drop at site A: stays ACCEPTED, never collected by a route.
    create_and_accept_drop(prog_id, site_id, part["part_id"], part["grant_id"],
                           mat_id, gross_weight_kg=credit_drop_gross_kg)

    # Feeder site + participant: the batch serves only site B.
    site_b = add_operational_site_to_program(prog_id)
    feeder = setup_verified_participant_with_grant(prog_id, site_b["site_id"],
                                                   email="feeder@x.com")
    dist_ctx = setup_open_distribution(
        prog_id, site_b["site_id"], feeder["part_id"], feeder["grant_id"],
        mat_id, drop_gross_kg=credit_drop_gross_kg, yield_ratio=yield_ratio)
    return ids, part, dist_ctx

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / distribution_fair_share_three_input_min
# (2 tests)
# ---------------------------------------------------------------------------

def _setup_fair_share_scenario(api):
    """Pool 40.00 kg (yield 1.0 over 40.00 net input); participant A
    household_size=4 with 10 credits; participant B household_size=1 with 30
    credits; A requests 50 kg / 3 credits; B requests 10 kg / 10 credits."""
    ids = setup_program_with_operational_site()
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    pa = setup_verified_participant_with_grant(prog_id, site_id,
                                               email="a@x.com",
                                               household_size=4)
    pb = setup_verified_participant_with_grant(prog_id, site_id,
                                               email="b@x.com",
                                               household_size=1)

    # A: 10 credits; B: 30 credits (provisional grants at rate 1.0)
    create_and_accept_drop(prog_id, site_id, pa["part_id"], pa["grant_id"],
                           mat_id, gross_weight_kg=10.00,
                           occurred_at="2026-07-01T10:00:00Z")
    create_and_accept_drop(prog_id, site_id, pb["part_id"], pb["grant_id"],
                           mat_id, gross_weight_kg=30.00,
                           occurred_at="2026-07-01T11:00:00Z")

    # Collect all 40.00 kg -> batch measured_net 40.00, yield 1.0 -> pool 40.00
    chain = setup_closed_accepted_batch(
        prog_id, site_id, planned_pickup_kg=40, actual_pickup_kg=40.00,
        measured_contamination_kg=0.00, yield_ratio=1.0)

    dist = validate_success(api.create_distribution(
        prog_id, {"batch_id": chain["batch_id"]}, ADMIN), expected_status=201)
    dist_id = dist["id"]

    alloc_a = validate_success(api.create_allocation(
        prog_id, dist_id,
        create_allocation_payload(pa["part_id"], dist["version"],
                                  requested_kg=50.00, credits_redeemed=3),
        make_participant_headers(pa["part_id"])), expected_status=201)

    dist_after_a = validate_success(api.get_distribution(prog_id, dist_id, ADMIN))
    alloc_b = validate_success(api.create_allocation(
        prog_id, dist_id,
        create_allocation_payload(pb["part_id"], dist_after_a["version"],
                                  requested_kg=10.00, credits_redeemed=10),
        make_participant_headers(pb["part_id"])), expected_status=201)

    return ids, pa, pb, dist_id, alloc_a["id"], alloc_b["id"]


def test_fair_share_min_of_three_caps_grants_three_kg(api):
    """PRD §3.6: "The **credit cap** is `credits_redeemed` kilograms flat."
    PRD §3.6: "The granted `allocation_kg` is the minimum of `requested_kg`
    and those three caps, rounded half-up to two decimal places."
    (pool 40.00, households 4+1, A requests 50 kg with 3 credits ->
    min(50, min(32.00, 3.00), 20.00) = 3.00 kg)

    Design: Difficulty/combinatorial_formula/distribution_fair_share_three_input_min
    """
    ids, pa, _pb, dist_id, alloc_a, _alloc_b = _setup_fair_share_scenario(api)
    prog_id = ids["prog_id"]

    granted = validate_success(api.distribute_allocation(
        prog_id, dist_id, alloc_a, ADMIN))
    assert granted["status"] == "DISTRIBUTED"
    assert granted["allocation_kg"] == pytest.approx(3.00), (
        f"credit cap (3 credits) must bind over household share 32.00 and "
        f"equal split 20.00; got {granted['allocation_kg']}")


def test_fair_share_distribute_debits_redeemed_credits(api):
    """PRD §3.6: "A successful grant moves the allocation to `DISTRIBUTED`,
    debits `credits_redeemed` from the participant's `bucket_credit_balance`,
    adds the same amount to `bucket_credits_redeemed_total`, and adds
    `allocation_kg` to the distribution's `allocated_kg`."

    Design: Difficulty/combinatorial_formula/distribution_fair_share_three_input_min
    """
    ids, pa, _pb, dist_id, alloc_a, _alloc_b = _setup_fair_share_scenario(api)
    prog_id = ids["prog_id"]

    validate_success(api.distribute_allocation(prog_id, dist_id, alloc_a, ADMIN))

    participant = validate_success(api.get_participant(
        prog_id, pa["part_id"], ADMIN))
    assert participant["bucket_credit_balance"] == 7, (
        f"10 granted - 3 redeemed = 7; got "
        f"{participant['bucket_credit_balance']}")
    assert participant["bucket_credits_redeemed_total"] == 3


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / bucket_credit_conservation (2 tests)
# ---------------------------------------------------------------------------

def _setup_request_then_cancel(api):
    """Participant with 10 credits; distribution pool 10.00; REQUESTED
    allocation of 5 credits; then cancelled. Returns (prog_id, part_id)."""
    ids, part, dist_ctx = _setup_isolated_distribution(api)
    prog_id = ids["prog_id"]
    dist_id = dist_ctx["dist_id"]

    alloc = validate_success(api.create_allocation(
        prog_id, dist_id,
        create_allocation_payload(part["part_id"], dist_ctx["dist_version"],
                                  requested_kg=5.00, credits_redeemed=5),
        make_participant_headers(part["part_id"])), expected_status=201)

    get_success_data(api.cancel_allocation(prog_id, dist_id, alloc["id"], ADMIN))
    return prog_id, part["part_id"]


def test_request_then_cancel_leaves_balance_unchanged(api):
    """PRD §2.8: "Each participant's `bucket_credit_balance` equals
    `bucket_credits_granted_total` minus `bucket_credits_redeemed_total` minus
    `bucket_credits_expired_total` at all times."
    PRD §3.6: "Cancelling a requested allocation — directly, or cascaded from
    cancelling the whole distribution — moves it to `CANCELLED` and refunds
    `credits_redeemed` to the participant's `bucket_credit_balance` without
    counting a redemption."

    Design: Difficulty/compensating_invariant/bucket_credit_conservation
    """
    prog_id, part_id = _setup_request_then_cancel(api)

    participant = validate_success(api.get_participant(prog_id, part_id, ADMIN))
    assert participant["bucket_credit_balance"] == 10, (
        f"request+cancel must leave the balance at 10 (zero drift), got "
        f"{participant['bucket_credit_balance']}")


def test_request_then_cancel_does_not_count_redemption(api):
    """PRD §3.6: "Cancelling a requested allocation — directly, or cascaded
    from cancelling the whole distribution — moves it to `CANCELLED` and
    refunds `credits_redeemed` to the participant's `bucket_credit_balance`
    without counting a redemption."
    PRD §2.8: "Each participant's `bucket_credit_balance` equals
    `bucket_credits_granted_total` minus `bucket_credits_redeemed_total` minus
    `bucket_credits_expired_total` at all times."

    Design: Difficulty/compensating_invariant/bucket_credit_conservation
    """
    prog_id, part_id = _setup_request_then_cancel(api)

    participant = validate_success(api.get_participant(prog_id, part_id, ADMIN))
    assert participant["bucket_credits_redeemed_total"] == 0, (
        "a refunded request must not count as a redemption")
    # Ledger conservation: 10 == 10 - 0 - 0
    assert (participant["bucket_credit_balance"]
            == participant["bucket_credits_granted_total"]
            - participant["bucket_credits_redeemed_total"]
            - participant["bucket_credits_expired_total"])


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
#             allocation_distribute_requires_open_distribution (2 tests)
# ---------------------------------------------------------------------------

def _setup_cancelled_distribution_with_allocation(api):
    """Distribution cancelled while holding one REQUESTED allocation of
    5 credits. Participant holds 20 credits from an isolated accepted drop.
    Returns (prog_id, dist_id, alloc_id, part_id)."""
    ids, part, dist_ctx = _setup_isolated_distribution(
        api, credit_drop_gross_kg=20.00, yield_ratio=0.5)
    prog_id = ids["prog_id"]
    dist_id = dist_ctx["dist_id"]

    alloc = validate_success(api.create_allocation(
        prog_id, dist_id,
        create_allocation_payload(part["part_id"], dist_ctx["dist_version"],
                                  requested_kg=5.00, credits_redeemed=5),
        make_participant_headers(part["part_id"])), expected_status=201)

    get_success_data(api.cancel_distribution(prog_id, dist_id, ADMIN))
    return prog_id, dist_id, alloc["id"], part["part_id"]


def test_distribute_on_cancelled_allocation_is_invalid_state(api):
    """PRD §3.6: "Cancelling a distribution moves it to `CANCELLED` and cancels
    every `REQUESTED` allocation with the credit refund described above."
    PRD §2.9: "From-state: the target resource is in a valid from-state for
    the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/allocation_distribute_requires_open_distribution
    """
    prog_id, dist_id, alloc_id, _part_id = (
        _setup_cancelled_distribution_with_allocation(api))

    resp = api.distribute_allocation(prog_id, dist_id, alloc_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_distribution_cancel_refunds_credits_to_participant(api):
    """PRD §3.6: "Cancelling a distribution moves it to `CANCELLED` and cancels
    every `REQUESTED` allocation with the credit refund described above." —
    i.e. "refunds `credits_redeemed` to the participant's
    `bucket_credit_balance` without counting a redemption."

    Design: Difficulty/cross_entity_state_dependency/allocation_distribute_requires_open_distribution
    """
    prog_id, _dist_id, _alloc_id, part_id = (
        _setup_cancelled_distribution_with_allocation(api))

    participant = validate_success(api.get_participant(prog_id, part_id, ADMIN))
    assert participant["bucket_credit_balance"] == 20, (
        f"5 redeemed credits must be refunded after distribution cancel; got "
        f"{participant['bucket_credit_balance']}")
    assert participant["bucket_credits_redeemed_total"] == 0


# ---------------------------------------------------------------------------
# Corner: errors/error_insufficient_bucket_credits (1 test)
# ---------------------------------------------------------------------------

def test_allocation_request_exceeding_balance_rejected(api):
    """PRD §3.6: "The request must be affordable: `credits_redeemed` no
    greater than the participant's `bucket_credit_balance`, and `requested_kg`
    greater than 0 — otherwise `ERR_INSUFFICIENT_BUCKET_CREDITS` (HTTP 409)."

    Design: Corner/errors/error_insufficient_bucket_credits
    """
    ids, part, dist_ctx = _setup_isolated_distribution(api)
    prog_id = ids["prog_id"]

    # Participant holds 10 credits; requesting with 99 credits must fail.
    resp = api.create_allocation(
        prog_id, dist_ctx["dist_id"],
        create_allocation_payload(part["part_id"], dist_ctx["dist_version"],
                                  requested_kg=20.00, credits_redeemed=99),
        make_participant_headers(part["part_id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUCKET_CREDITS)
