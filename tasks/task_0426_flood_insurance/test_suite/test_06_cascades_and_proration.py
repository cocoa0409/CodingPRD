"""Cross-entity cascades and premium ledger arithmetic: the claim-approve ledger
cascade to repetitive-loss, the cancel cascade to compliance LAPSED, premium
proration on cancel and transfer, and the conservation invariant.

Covers difficulty queue A (transitive_cascade, non_linear_state_machine policy
branching, compensating_invariant cancel) and corner queue B
(cross_cutting_complexity_layers).
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_community,
    create_property,
    create_elevation_certificate,
    quote_policy_as_underwriter,
    setup_active_policy,
    file_claim,
    open_review,
    file_proof_of_loss,
    accept_proof_of_loss,
    approve_claim,
    assert_premium_conservation_on_cancel,
    assert_premium_conservation_on_transfer,
    TEST_USERS,
)


def _activate_legacy_ae_policy_pair(api, owner_id):
    """Two independent ACTIVE legacy AE policies (premium 2000 each), both bound
    2026-03-01 and activated at effective_date 2026-03-31. Returns (pol_a, pol_b)
    each with the post-activate version captured."""
    community = create_community(crs_class=10, participating=True)
    set_clock("2026-03-01T00:00:00Z")
    prop_a = create_property(
        community["id"], owner_id, flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    prop_b = create_property(
        community["id"], owner_id, flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    pol_a = quote_policy_as_underwriter(
        prop_a["id"], "LEGACY_SUBSIDIZED",
        building_coverage=250000, contents_coverage=100000,
    )
    pol_b = quote_policy_as_underwriter(
        prop_b["id"], "LEGACY_SUBSIDIZED",
        building_coverage=250000, contents_coverage=100000,
    )
    hdr = TEST_USERS["underwriter_headers"]
    validate_success(api.bind_policy(pol_a["id"], hdr))
    validate_success(api.bind_policy(pol_b["id"], hdr))
    set_clock("2026-03-31T00:00:00Z")
    active_a = validate_success(api.activate_policy(pol_a["id"], hdr))
    active_b = validate_success(api.activate_policy(pol_b["id"], hdr))
    return active_a, active_b


def test_claim_approve_cascades_to_repetitive_loss(api):
    """PRD §3.10: "On approval the ledger cascade fires: the policy's
    `total_claims_paid` is increased by the settlement total; the property's
    `loss_history_count` is increased by one; and if that brings the loss count
    to 2 or more, the property's `is_repetitive_loss` flag is set to true."

    Design: Difficulty/transitive_cascade/claim_approve_cascade_to_repetitive_loss_depth3
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-8",
        flood_zone="X", base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
        crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000, quote_as_underwriter=True,
    )
    # First approved claim: loss_history_count -> 1, total_claims_paid -> 3000.
    claim1 = file_claim(active["id"], "holder-8", "2026-04-10T00:00:00Z", building_loss=5000)
    claim1 = open_review(claim1["id"])
    proof1 = file_proof_of_loss(claim1["id"], "holder-8", documented_building_loss=5000)
    accept_proof_of_loss(proof1["id"])
    approve_claim(claim1["id"], claim1["version"])

    # Second approved claim crosses the repetitive-loss threshold.
    claim2 = file_claim(active["id"], "holder-8", "2026-05-01T00:00:00Z", building_loss=5000)
    claim2 = open_review(claim2["id"])
    proof2 = file_proof_of_loss(claim2["id"], "holder-8", documented_building_loss=5000)
    accept_proof_of_loss(proof2["id"])
    approve_claim(claim2["id"], claim2["version"])

    fetched_policy = validate_success(
        api.get_policy(active["id"], TEST_USERS["underwriter_headers"])
    )
    fetched_prop = validate_success(
        api.get_property(prop["id"], TEST_USERS["underwriter_headers"])
    )
    assert fetched_policy["total_claims_paid"] == 6000, fetched_policy["total_claims_paid"]
    assert fetched_prop["loss_history_count"] == 2, fetched_prop["loss_history_count"]
    assert fetched_prop["is_repetitive_loss"] is True, fetched_prop["is_repetitive_loss"]


def test_cancel_cascades_compliance_to_lapsed(api):
    """PRD §3.6: "In both cases the property's `active_policy_id` is cleared to
    null, and where the structure is both SFHA and mortgaged its
    `compliance_status` cascades to `LAPSED`, because required coverage has been
    withdrawn."

    Design: Difficulty/transitive_cascade/policy_cancel_cascade_to_compliance_lapsed_depth2
    """
    community, prop, active = setup_active_policy(
        bind_clock="2026-03-01T00:00:00Z", owner_id="holder-9",
        flood_zone="AE", base_flood_elevation_ft=8.0, lowest_floor_elevation_ft=10.0,
        has_active_mortgage=True, crs_class=10, is_lender_required=True,
        building_coverage=250000, contents_coverage=100000, quote_as_underwriter=True,
    )
    cancelled = validate_success(api.cancel_policy(
        active["id"], {"expected_policy_version": active["version"]},
        TEST_USERS["underwriter_headers"],
    ))
    assert cancelled["status"] == "CANCELLED", cancelled["status"]

    fetched_prop = validate_success(
        api.get_property(prop["id"], TEST_USERS["underwriter_headers"])
    )
    assert fetched_prop["active_policy_id"] is None, fetched_prop["active_policy_id"]
    assert fetched_prop["compliance_status"] == "LAPSED", fetched_prop["compliance_status"]


def test_active_to_transferred_vs_cancelled_branch(api):
    """PRD §3.7: "The unearned remainder, recorded as the transfer's
    `credited_amount`, is the quoted premium minus the earned premium, and it is
    added to the policy's `premium_credit_balance`; earned premium plus credit
    balance therefore equals the quoted premium."
    PRD §3.6: "Cancelling a `BOUND` policy — one whose coverage never started —
    sets `earned_premium` to 0 and leaves the credit balance untouched."

    Design: Difficulty/non_linear_state_machine/policy_branching_active_to_transferred_vs_cancelled
    """
    active_a, active_b = _activate_legacy_ae_policy_pair(api, "holder-6")
    set_clock("2026-09-30T00:00:00Z")
    hdr = TEST_USERS["underwriter_headers"]

    # The transfer record itself is created (201); the assertion is on the
    # source policy's terminal state and credited unearned premium below.
    validate_success(api.create_policy_transfer(
        {
            "from_policy_id": active_a["id"],
            "new_owner_id": "holder-7",
            "expected_policy_version": active_a["version"],
        },
        hdr,
    ), expected_status=201)

    cancelled = validate_success(api.cancel_policy(
        active_b["id"], {"expected_policy_version": active_b["version"]}, hdr
    ))

    src_a = validate_success(api.get_policy(active_a["id"], hdr))
    assert src_a["status"] == "TRANSFERRED", src_a["status"]
    assert src_a["premium_credit_balance"] == 997, src_a["premium_credit_balance"]
    assert_premium_conservation_on_transfer(src_a)

    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    assert cancelled["premium_credit_balance"] == 0, cancelled["premium_credit_balance"]


def test_cancel_premium_conservation_earned_plus_refund(api):
    """PRD §3.6: "the `earned_premium` is the quoted premium multiplied by days
    elapsed divided by the term, rounded to whole dollars. The refund returned to
    the holder is the quoted premium minus the earned premium, computed as the
    exact complement so that earned premium plus refund equals the quoted
    premium."

    Design: Difficulty/compensating_invariant/cancel_premium_conservation_earned_plus_refund
    """
    community = create_community(crs_class=10, participating=True)
    set_clock("2026-03-01T00:00:00Z")
    prop = create_property(
        community["id"], "holder-19", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    quoted = quote_policy_as_underwriter(
        prop["id"], "LEGACY_SUBSIDIZED",
        building_coverage=250000, contents_coverage=100000,
    )
    assert quoted["quoted_premium"] == 2000, quoted["quoted_premium"]
    hdr = TEST_USERS["underwriter_headers"]
    validate_success(api.bind_policy(quoted["id"], hdr))
    set_clock("2026-03-31T00:00:00Z")
    active = validate_success(api.activate_policy(quoted["id"], hdr))
    set_clock("2026-09-30T00:00:00Z")
    cancelled = validate_success(api.cancel_policy(
        active["id"], {"expected_policy_version": active["version"]}, hdr
    ))
    assert cancelled["quoted_premium"] == 2000, cancelled["quoted_premium"]
    assert cancelled["earned_premium"] == 1003, cancelled["earned_premium"]
    assert cancelled["premium_credit_balance"] == 0, cancelled["premium_credit_balance"]
    assert_premium_conservation_on_cancel(cancelled)


def test_policy_version_increments_on_each_mutation(api):
    """PRD §2.4: "an integer `version` that begins at its initial value and
    increments by one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_policy_mutation
    """
    community = create_community(crs_class=10, participating=True)
    set_clock("2026-03-01T00:00:00Z")
    prop = create_property(
        community["id"], "h-vr", flood_zone="X",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=10.0,
    )
    create_elevation_certificate(prop["id"], "h-vr", lowest_floor_elevation_ft=11.0)
    quoted = quote_policy_as_underwriter(
        prop["id"], "RISK_RATING_2_0",
        building_coverage=100000, contents_coverage=40000, is_lender_required=True,
    )
    assert quoted["version"] == 1, quoted["version"]
    hdr = TEST_USERS["underwriter_headers"]
    bound = validate_success(api.bind_policy(quoted["id"], hdr))
    assert bound["version"] == 2, bound["version"]
    active = validate_success(api.activate_policy(quoted["id"], hdr))
    assert active["version"] == 3, active["version"]
