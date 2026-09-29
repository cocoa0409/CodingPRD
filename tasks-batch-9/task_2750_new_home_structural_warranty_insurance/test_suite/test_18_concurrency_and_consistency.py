"""Optimistic-concurrency corners on both guarded write paths, the derived
denominator that moves only on activation, and the immediate-consistency
guarantee that a mutating response is already final.

Every test builds its own world from scratch against a freshly restarted server
with an empty database.
"""

from test_helpers import (
    ADJUSTER_USER_ID,
    CANONICAL_CLOSING_INSTANT,
    SECOND_ADJUSTER_USER_ID,
    ApiErrorId,
    create_approved_builder,
    create_homeowner,
    create_transfer_payload,
    enroll_policy,
    invoice_policy,
    make_claims_adjuster_headers,
    obligation_routing_payload,
    pay_policy_premium,
    payment_payload,
    read_claim,
    read_coverage_term,
    read_loss_monitor,
    read_policy,
    read_reserve_entries,
    read_transfer,
    reserve_entry_payload,
    set_clock,
    setup_active_policy,
    setup_approved_claim,
    setup_routed_claim,
    validate_error,
    validate_success,
)


# ==========================================================================
# Optimistic concurrency on a transfer request
# ==========================================================================
def test_replaying_the_pre_transfer_policy_version_is_refused_and_supersedes_nothing(
    api,
):
    """The accepted request bumps the policy itself, so the same
    `expected_policy_version` replayed is the lost update the rule guards.

    PRD Section 2.7: "A `POST /warranty/policies/{id}/transfers` request must
    carry `expected_policy_version`, a required (never optional) integer field
    holding the `version` of the target `WarrantyPolicy` as the client last read
    it. If that value does not equal the policy's current `version`, the request
    is rejected with `ERR_STALE_POLICY_VERSION` and HTTP 412."

    PRD Section 3.5: "Its `transfer_fee_cents` is computed at that moment as a
    base fee of 7,500 cents plus 2,500 cents for each transfer already recorded
    on the policy — so the first hand-off costs seventy-five dollars, the second
    one hundred, the third one hundred and twenty-five."

    PRD Section 3.5: "Either way the policy's `pending_transfer_id` is set to the
    new request's `id` and the policy's `version` advances by 1."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_expected_policy_version_on_a_transfer_request_returns_412
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]
    owner_headers = scenario["owner_headers"]
    second_buyer = create_homeowner(
        full_name="Ben Calloway", email="ben.calloway@example.com"
    )
    third_buyer = create_homeowner(
        full_name="Cora Devlin", email="cora.devlin@example.com"
    )

    version_before = scenario["policy"]["version"]
    assert version_before == 4, (
        "the policy row is born at 1 and the invoice, the payment and the "
        "activation each advance it by exactly 1"
    )

    first = validate_success(
        api.create_transfer(
            policy_id,
            create_transfer_payload(
                second_buyer["id"],
                version_before,
                transfer_date="2026-09-01",
                documents_reference="DEED-A",
            ),
            owner_headers,
        ),
        201,
    )
    assert first["transfer_fee_cents"] == 7_500
    assert first["status"] == "REQUESTED"
    assert first["prior_transfer_id"] is None

    after_first = read_policy(policy_id)
    assert after_first["version"] == version_before + 1
    assert after_first["pending_transfer_id"] == first["id"]

    stale = api.create_transfer(
        policy_id,
        create_transfer_payload(
            third_buyer["id"],
            version_before,
            transfer_date="2026-09-02",
            documents_reference="DEED-B",
        ),
        owner_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_POLICY_VERSION.value, 412)

    assert read_transfer(first["id"])["status"] == "REQUESTED"
    unchanged = read_policy(policy_id)
    assert unchanged["pending_transfer_id"] == first["id"]
    assert unchanged["version"] == version_before + 1


def test_the_refreshed_policy_version_supersedes_the_request_the_412_left_alone(api):
    """Retried on the version the refusal disclosed, the second request lands and
    the first goes terminal.

    PRD Section 2.7: "The rule exists because the product deliberately lets a new
    transfer request supersede whatever request is already open on the policy —
    the seller genuinely may have changed buyers — so nothing in the state
    machine stops a create that would quietly supersede a request the client
    never observed."

    PRD Section 3.5: "If the policy already has an open request — the row named
    by the policy's `pending_transfer_id`, in `status` `REQUESTED` or
    `NEEDS_DOCUMENTATION` — that row transitions to the terminal `SUPERSEDED` and
    its `version` advances by 1, and the new row's `prior_transfer_id` is set to
    the superseded row's `id`, forming an auditable chain of attempts."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_expected_policy_version_on_a_transfer_request_returns_412
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]
    owner_headers = scenario["owner_headers"]
    second_buyer = create_homeowner(
        full_name="Ben Calloway", email="ben.calloway@example.com"
    )
    third_buyer = create_homeowner(
        full_name="Cora Devlin", email="cora.devlin@example.com"
    )

    first = validate_success(
        api.create_transfer(
            policy_id,
            create_transfer_payload(
                second_buyer["id"],
                scenario["policy"]["version"],
                transfer_date="2026-09-01",
                documents_reference="DEED-A",
            ),
            owner_headers,
        ),
        201,
    )
    refreshed_version = read_policy(policy_id)["version"]

    second = validate_success(
        api.create_transfer(
            policy_id,
            create_transfer_payload(
                third_buyer["id"],
                refreshed_version,
                transfer_date="2026-09-02",
                documents_reference="DEED-B",
            ),
            owner_headers,
        ),
        201,
    )
    assert second["prior_transfer_id"] == first["id"]
    assert second["status"] == "REQUESTED"
    assert second["transfer_fee_cents"] == 7_500, (
        "the fee multiplier counts only transfers that reached RECORDED"
    )

    assert read_transfer(first["id"])["status"] == "SUPERSEDED"
    after = read_policy(policy_id)
    assert after["pending_transfer_id"] == second["id"]
    assert after["version"] == refreshed_version + 1
    assert after["transfer_count"] == 0


# ==========================================================================
# Optimistic concurrency on a reserve-journal entry
# ==========================================================================
def test_a_second_adjuster_reserving_on_a_stale_claim_read_is_refused(api):
    """The first authorisation moved the claim's version, so the colleague's
    cached reading is stale and its `ADJUSTMENT` writes nothing at all.

    PRD Section 2.7: "A `POST /warranty/claims/{id}/reserve-entries` request must
    carry `expected_claim_version`, a required (never optional) integer field
    holding the `version` of the target `Claim` as the client last read it. If
    that value does not equal the claim's current `version`, the request is
    rejected with `ERR_STALE_CLAIM_VERSION` and HTTP 412."

    PRD Section 3.8: "The request carries an `entry_type` of `INITIAL` or
    `ADJUSTMENT`, the `amount_cents` being authorised, an optional `memo`, and the
    `expected_claim_version` required by §2.7. The response is the newly created
    journal row."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_expected_claim_version_on_a_reserve_entry_returns_412
    """
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500, substantiation_ratio=0.80
    )
    claim_id = scenario["claim"]["id"]
    cached_version = scenario["claim"]["version"]
    assert scenario["claim"]["reserve_cents"] == 1_518_000

    first = validate_success(
        api.create_reserve_entry(
            claim_id,
            reserve_entry_payload(
                1_518_000,
                cached_version,
                entry_type="INITIAL",
                memo="opened by the first adjuster",
            ),
            make_claims_adjuster_headers(ADJUSTER_USER_ID),
        ),
        201,
    )
    assert first["entry_type"] == "INITIAL"
    assert first["recorded_by_user_id"] == ADJUSTER_USER_ID
    assert first["balance_after_reserve_cents"] == 1_518_000
    assert first["balance_after_paid_cents"] == 0

    stale = api.create_reserve_entry(
        claim_id,
        reserve_entry_payload(
            1_600_000,
            cached_version,
            entry_type="ADJUSTMENT",
            memo="raised on a stale read",
        ),
        make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CLAIM_VERSION.value, 412)

    after = read_claim(claim_id)
    assert after["reserve_cents"] == 1_518_000
    assert after["incurred_authorized_cents"] == 1_518_000
    assert after["version"] == cached_version + 1, (
        "only the accepted authorisation advanced the claim's version"
    )
    assert read_reserve_entries(claim_id, entry_type="ADJUSTMENT") == []


def test_the_refreshed_claim_version_lets_the_adjustment_overwrite_the_reserve(api):
    """Retried on the version the accepted entry left behind, the adjustment
    overwrites the reserve target rather than adding to it.

    PRD Section 2.7: "Here the hazard is that re-reserving is a legitimate
    repeated operation: each entry *overwrites* the reserve target rather than
    adding to it, so a second entry submitted against an out-of-date reading
    would succeed on its own terms while discarding a reserve level the client
    never observed."

    PRD Section 3.8: "On success the claim's `reserve_cents` becomes exactly the
    authorised `amount_cents`, and its `incurred_authorized_cents` becomes the sum
    of its existing `paid_cents`, its existing `released_cents` and that same
    authorised amount."

    Design: Corner/Cross-Cutting Complexity Layers/a_stale_expected_claim_version_on_a_reserve_entry_returns_412
    """
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500, substantiation_ratio=0.80
    )
    claim_id = scenario["claim"]["id"]

    validate_success(
        api.create_reserve_entry(
            claim_id,
            reserve_entry_payload(
                1_518_000,
                scenario["claim"]["version"],
                entry_type="INITIAL",
                memo="opened by the first adjuster",
            ),
            make_claims_adjuster_headers(ADJUSTER_USER_ID),
        ),
        201,
    )
    refreshed_version = read_claim(claim_id)["version"]

    retried = validate_success(
        api.create_reserve_entry(
            claim_id,
            reserve_entry_payload(
                1_600_000,
                refreshed_version,
                entry_type="ADJUSTMENT",
                memo="retried on a fresh read",
            ),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        201,
    )
    assert retried["entry_type"] == "ADJUSTMENT"
    assert retried["recorded_by_user_id"] == SECOND_ADJUSTER_USER_ID
    assert retried["balance_after_reserve_cents"] == 1_600_000

    after = read_claim(claim_id)
    assert after["reserve_cents"] == 1_600_000
    assert after["paid_cents"] == 0
    assert after["released_cents"] == 0
    assert after["incurred_authorized_cents"] == 1_600_000
    assert after["version"] == refreshed_version + 1

    assert len(read_reserve_entries(claim_id, entry_type="INITIAL")) == 1
    assert len(read_reserve_entries(claim_id, entry_type="ADJUSTMENT")) == 1


# ==========================================================================
# The derived denominator moves only when the coverage axis moves
# ==========================================================================
def test_earned_premium_moves_on_activation_and_not_on_the_premium_payment(
    api, underwriting_officer_headers
):
    """A paid premium on a policy still in `PENDING_ENROLLMENT` contributes
    nothing; the same premium enters the denominator the moment coverage is in
    force, and the second home repeats the pattern.

    PRD Section 3.2: "The denominator, `earned_premium_cents`, is the sum of
    `premium_cents` over the builder's policies that are **both** in a coverage
    state of `ACTIVE` or `EXPIRED` **and** in a premium state of `PAID`; policies
    still in `PENDING_ENROLLMENT` and policies that were `VOIDED` are excluded,
    and so is an in-force policy whose premium was never paid."

    PRD Section 3.4: "Payment triggers a recompute of the builder's
    `earned_premium_cents`, `loss_ratio` and `monitoring_posture` — but because a
    policy in `PENDING_ENROLLMENT` is excluded from the denominator population,
    nothing actually moves yet."

    PRD Section 3.2: "The ratio itself is the numerator divided by the
    denominator, rounded half up to four decimal places — except when the
    denominator is 0, in which case `loss_ratio` is pinned at exactly 0.0000 and
    `monitoring_posture` at `OPEN` **even if `incurred_loss_cents` is positive**."

    PRD Section 3.2: "`policy_count` is the size of the denominator population:
    the number of this builder's policies that are in `ACTIVE` or `EXPIRED`
    coverage state and `PAID` premium state."

    Design: Corner/Cross-Cutting Complexity Layers/earned_premium_reconciles_on_each_activation_and_never_on_a_mere_payment
    """
    builder = create_approved_builder()
    buyer = create_homeowner()
    set_clock(CANONICAL_CLOSING_INSTANT)
    first_policy = enroll_policy(builder["id"], buyer["id"])
    invoice_policy(first_policy["id"])
    pay_policy_premium(first_policy["id"], builder["id"])
    assert read_policy(first_policy["id"])["premium_status"] == "PAID"

    while_pending = read_loss_monitor(builder["id"])
    assert while_pending["earned_premium_cents"] == 0
    assert while_pending["policy_count"] == 0
    assert while_pending["loss_ratio"] == 0.0
    assert while_pending["monitoring_posture"] == "OPEN"

    activated = validate_success(
        api.activate_policy(first_policy["id"], underwriting_officer_headers), 200
    )
    assert activated["coverage_status"] == "ACTIVE"

    after_first = read_loss_monitor(builder["id"])
    assert after_first["earned_premium_cents"] == 363_894
    assert after_first["policy_count"] == 1

    second_policy = enroll_policy(
        builder["id"],
        buyer["id"],
        street_address="22 Second Home Ct",
        purchase_price_cents=5_000_000,
    )
    assert second_policy["premium_cents"] == 44_881
    invoice_policy(second_policy["id"])
    pay_policy_premium(second_policy["id"], builder["id"])
    assert read_policy(second_policy["id"])["premium_status"] == "PAID"

    after_second_payment = read_loss_monitor(builder["id"])
    assert after_second_payment["earned_premium_cents"] == 363_894, (
        "paying the second premium reconciles nothing while its coverage axis "
        "still reads PENDING_ENROLLMENT"
    )
    assert after_second_payment["policy_count"] == 1

    validate_success(
        api.activate_policy(second_policy["id"], underwriting_officer_headers), 200
    )

    after_second_activation = read_loss_monitor(builder["id"])
    assert after_second_activation["earned_premium_cents"] == 408_775
    assert after_second_activation["policy_count"] == 2
    assert after_second_activation["loss_ratio"] == 0.0
    assert after_second_activation["monitoring_posture"] == "OPEN"


# ==========================================================================
# Immediate consistency: the mutating response is already final
# ==========================================================================
def test_the_routing_response_already_carries_the_whole_settlement_waterfall(api):
    """Deductible, betterment, net payable, reserve and incurred are all present
    in the routing response, and the very next read repeats them exactly.

    PRD Section 2.9: "Cascades in this system are **synchronous and complete
    within the request that triggers them**. There is no deferred settlement, no
    background job and no eventual consistency: by the time a response is
    returned, every dependent row the operation implicates has been rewritten,
    every derived aggregate recomputed, and every affected row's `version`
    advanced."

    PRD Section 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    PRD Section 3.7: "The deductible schedule is selected by the claim's
    `designated_structural` flag: 250,000 cents when the flag is true, and
    100,000 cents when it is false."

    PRD Section 3.7: "The claim's `incurred_authorized_cents` is set to the sum of
    its `paid_cents`, its `released_cents` and its `net_payable_cents`, and its
    `reserve_cents` is set to that `net_payable_cents` — the carrier has now put
    money aside."

    Design: Corner/Consistency Model/every_derived_field_is_already_correct_in_the_response_that_changed_it
    """
    scenario = setup_routed_claim(
        claimed_amount_cents=2_187_500, substantiation_ratio=0.80, route=False
    )
    claim_id = scenario["claim"]["id"]

    routed = validate_success(
        api.route_claim_obligation(
            claim_id,
            obligation_routing_payload(),
            make_claims_adjuster_headers(ADJUSTER_USER_ID),
        ),
        200,
    )
    assert routed["status"] == "INSURER_ADJUDICATION"
    assert routed["designated_structural"] is False
    assert routed["gross_adjusted_cents"] == 1_750_000
    assert routed["deductible_applied_cents"] == 100_000
    assert routed["betterment_cents"] == 132_000
    assert routed["net_payable_cents"] == 1_518_000
    assert routed["reserve_cents"] == 1_518_000
    assert routed["incurred_authorized_cents"] == 1_518_000

    immediate = read_claim(claim_id)
    assert immediate["gross_adjusted_cents"] == routed["gross_adjusted_cents"]
    assert immediate["deductible_applied_cents"] == routed["deductible_applied_cents"]
    assert immediate["betterment_cents"] == routed["betterment_cents"]
    assert immediate["net_payable_cents"] == routed["net_payable_cents"]
    assert immediate["reserve_cents"] == routed["reserve_cents"]
    assert immediate["incurred_authorized_cents"] == routed["incurred_authorized_cents"]
    assert immediate["version"] == routed["version"], (
        "a read may not repair or re-advance a row the write already finished"
    )


def test_the_payment_response_already_carries_the_closed_claim_and_the_ledger(api):
    """The disbursement response reports the final balances, and the builder
    monitor and coverage term read straight afterwards were already reconciled by
    that same request.

    PRD Section 2.9: "There is no deferred settlement, no background job and no
    eventual consistency: by the time a response is returned, every dependent row
    the operation implicates has been rewritten, every derived aggregate
    recomputed, and every affected row's `version` advanced."

    PRD Section 3.8: "It moves money on the claim: `amount_cents` is added to
    `paid_cents` and subtracted from `reserve_cents`, leaving
    `incurred_authorized_cents` untouched. It charges the coverage term:
    `amount_cents` is added to the term's `consumed_limit_cents` and subtracted
    from its `remaining_limit_cents`. It closes the claim when the claim is
    `APPROVED` and its `paid_cents` after this payment equals its
    `net_payable_cents`, advancing `APPROVED → CLOSED_PAID`. And it recomputes the
    builder's loss-ratio figures."

    PRD Section 3.3: "For the structural term it is the full
    `purchase_price_cents` with no cap at all."

    Design: Corner/Consistency Model/every_derived_field_is_already_correct_in_the_response_that_changed_it
    """
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500, substantiation_ratio=0.80
    )
    claim_id = scenario["claim"]["id"]

    paid = validate_success(
        api.create_payment(
            claim_id,
            payment_payload(1_518_000, memo="full indemnity"),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        200,
    )
    assert paid["paid_cents"] == 1_518_000
    assert paid["reserve_cents"] == 0
    assert paid["released_cents"] == 0
    assert paid["incurred_authorized_cents"] == 1_518_000
    assert paid["status"] == "CLOSED_PAID"

    monitor = read_loss_monitor(scenario["builder"]["id"])
    assert monitor["incurred_loss_cents"] == 1_518_000
    assert monitor["loss_ratio"] == 4.1715
    assert monitor["monitoring_posture"] == "FROZEN"
    assert monitor["open_claim_count"] == 0

    term = read_coverage_term(scenario["claim"]["coverage_term_id"])
    assert term["limit_cents"] == 44_500_000
    assert term["consumed_limit_cents"] == 1_518_000
    assert term["remaining_limit_cents"] == 42_982_000
    assert term["status"] == "OPEN"
