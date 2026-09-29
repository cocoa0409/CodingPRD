"""Long synchronous cascades fired by a single write, and operations whose
legality is decided by the state of a *different* entity than the one being
addressed.

Every test builds its own world from scratch against a freshly restarted server
with an empty database.
"""

import pytest

from test_helpers import (
    SECOND_ADJUSTER_USER_ID,
    ApiErrorId,
    assert_builder,
    assert_claim,
    assert_coverage_term,
    assert_loss_monitor,
    assert_policy,
    assert_transfer,
    create_claim_payload,
    default_declaration_payload,
    find_term,
    invoice_policy,
    make_claims_adjuster_headers,
    make_homeowner_headers,
    pay_policy_premium,
    payment_payload,
    read_claim,
    read_coverage_term,
    read_escalation_case,
    read_policy,
    read_transfer,
    record_session_outcome,
    set_clock,
    setup_approved_transfer,
    setup_builder_arm_claim,
    setup_limit_exhaustion_scenario,
    setup_mediation_case,
    setup_paid_pending_policy,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# One disbursement -> exhausted term -> suspended sibling claim -> frozen
# builder -> a second home held out of force
# ==========================================================================
def test_disbursement_exhausts_the_term_and_closes_the_paid_claim(api):
    """The first three links of the chain: the money moves on the claim, the same
    amount is charged to the coverage term, and the term that reaches exactly zero
    capacity transitions OPEN -> LIMIT_EXHAUSTED.

    PRD 3.8: "A successful disbursement does five things. It appends a journal row of `entry_type` `PAYMENT` with `recorded_by_user_id` set to the acting `X-User-ID`. It moves money on the claim: `amount_cents` is added to `paid_cents` and subtracted from `reserve_cents`, leaving `incurred_authorized_cents` untouched. It charges the coverage term: `amount_cents` is added to the term's `consumed_limit_cents` and subtracted from its `remaining_limit_cents`. It closes the claim when the claim is `APPROVED` and its `paid_cents` after this payment equals its `net_payable_cents`, advancing `APPROVED → CLOSED_PAID`."
    PRD 3.8: "When that charge drives the term's `remaining_limit_cents` to exactly 0, the term transitions `OPEN → LIMIT_EXHAUSTED` and its `version` advances by 1 — and a three-link cascade fires, synchronously, in the same request."

    Design: Difficulty/transitive_cascade/single_payment_propagates_six_links_to_a_sibling_policy_enrollment_hold
    """
    scenario = setup_limit_exhaustion_scenario(with_pending_sibling_policy=False)
    claim = scenario["primary_claim"]
    term = scenario["structural_term"]
    assert claim["status"] == "APPROVED"
    assert claim["net_payable_cents"] == 5_000_000, (
        "the net payable is capped at the whole remaining structural limit"
    )
    assert claim["reserve_cents"] == 5_000_000
    assert term["limit_cents"] == 5_000_000
    assert term["remaining_limit_cents"] == 5_000_000
    assert term["status"] == "OPEN"

    validate_success(
        api.create_payment(
            claim["id"],
            payment_payload(5_000_000, memo="full indemnity on the structural limit"),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        200,
    )

    paid_claim = read_claim(claim["id"])
    assert paid_claim["paid_cents"] == 5_000_000
    assert paid_claim["reserve_cents"] == 0
    assert paid_claim["incurred_authorized_cents"] == 5_000_000
    assert paid_claim["status"] == "CLOSED_PAID"
    assert paid_claim["version"] == claim["version"] + 1
    assert_claim(paid_claim)

    charged_term = read_coverage_term(term["id"])
    assert charged_term["consumed_limit_cents"] == 5_000_000
    assert charged_term["remaining_limit_cents"] == 0
    assert charged_term["status"] == "LIMIT_EXHAUSTED"
    assert charged_term["version"] == term["version"] + 1
    assert_coverage_term(charged_term)


def test_exhaustion_suspends_the_sibling_claim_and_holds_a_second_home(
    api, underwriting_officer_headers
):
    """The remaining three links, reaching an entity the payment never named: the
    sibling claim on the same term is suspended and its reserve released, the
    builder's band is recomputed to FROZEN, and every home of that builder still
    in PENDING_ENROLLMENT is put on enrollment hold — which then blocks activation.

    PRD 3.8: "Every *other* claim bound to that same coverage term whose `status` is `UNDER_INVESTIGATION`, `BUILDER_OBLIGATION_NOTICE`, `INSURER_ADJUDICATION` or `APPROVED` transitions to the terminal `SUSPENDED_NO_LIMIT`; on each such claim the whole of its `reserve_cents` is added to its `released_cents` and its `reserve_cents` is set to 0, leaving its `incurred_authorized_cents` unchanged, and a journal row of `entry_type` `RELEASE` for the released amount is appended to that claim's journal when the released amount is at least 1 cent."
    PRD 3.8: "The **second link** follows because those reserves moved: the builder's `incurred_loss_cents`, `loss_ratio` and `monitoring_posture` are recomputed. The **third link** follows when that recompute pushes `monitoring_posture` to `FROZEN`: every policy of that builder whose `coverage_status` is `PENDING_ENROLLMENT` has its `enrollment_hold` set to true and its `version` advanced by 1 — which is exactly the flag that blocks activation in §3.4."
    PRD 3.8: "A single payment on one claim can therefore stop an unrelated home from going in force."
    PRD 3.4: "Its `enrollment_hold` must be false, or `ERR_ENROLLMENT_ON_HOLD`."

    Design: Difficulty/transitive_cascade/single_payment_propagates_six_links_to_a_sibling_policy_enrollment_hold
    """
    scenario = setup_limit_exhaustion_scenario()
    claim = scenario["primary_claim"]
    sibling = scenario["sibling_claim"]
    second_home = scenario["pending_policy"]
    invoice_policy(second_home["id"])
    pay_policy_premium(second_home["id"], scenario["builder"]["id"])

    assert sibling["status"] == "INSURER_ADJUDICATION"
    assert sibling["reserve_cents"] == 475_000
    assert sibling["released_cents"] == 0
    held_before = read_policy(second_home["id"])
    assert held_before["coverage_status"] == "PENDING_ENROLLMENT"
    assert held_before["premium_status"] == "PAID"
    assert held_before["enrollment_hold"] is False

    validate_success(
        api.create_payment(
            claim["id"],
            payment_payload(5_000_000, memo="full indemnity on the structural limit"),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        200,
    )

    suspended_sibling = read_claim(sibling["id"])
    assert suspended_sibling["status"] == "SUSPENDED_NO_LIMIT"
    assert suspended_sibling["released_cents"] == 475_000
    assert suspended_sibling["reserve_cents"] == 0
    assert suspended_sibling["incurred_authorized_cents"] == 475_000
    assert suspended_sibling["version"] == sibling["version"] + 1
    assert_claim(suspended_sibling)

    monitor = validate_success(
        api.get_loss_monitor(scenario["builder"]["id"], underwriting_officer_headers)
    )
    assert monitor["earned_premium_cents"] == 44_881
    assert monitor["incurred_loss_cents"] == 5_000_000, (
        "the released sibling reserve has left the numerator; the paid claim stays in"
    )
    assert float(monitor["loss_ratio"]) == pytest.approx(111.4057, abs=0.00005)
    assert monitor["monitoring_posture"] == "FROZEN"
    assert_loss_monitor(monitor)

    held_after = read_policy(second_home["id"])
    assert held_after["enrollment_hold"] is True
    assert held_after["coverage_status"] == "PENDING_ENROLLMENT"
    assert held_after["version"] == held_before["version"] + 1
    assert_policy(held_after)

    validate_error(
        api.activate_policy(second_home["id"], underwriting_officer_headers),
        ApiErrorId.ERR_ENROLLMENT_ON_HOLD.value,
    )
    assert read_policy(second_home["id"])["coverage_status"] == "PENDING_ENROLLMENT"


# ==========================================================================
# One default declaration -> re-partied claim -> re-run waterfall -> the band
# ==========================================================================
def test_default_declaration_reparties_the_stranded_claim_and_reruns_settlement(
    api, compliance_officer_headers
):
    """Links one and two. Declaring the builder in default moves a claim that was
    waiting on that builder into INSURER_ADJUDICATION and re-runs the settlement
    waterfall on it under the insurer-backed variant, so the deductible the
    builder arm had zeroed is charged and the reserve is established.

    PRD 3.2: "The **first link** re-parties every stranded claim: each claim on any policy of this builder whose `status` is `BUILDER_OBLIGATION_NOTICE` transitions to `INSURER_ADJUDICATION`, and its `obligor` is rewritten from `BUILDER` to `INSURER`."
    PRD 3.2: "The **second link** follows from the first: because those claims are now insurer-funded, the settlement waterfall of §3.7 is re-run on each of them under the insurer-backed variant, rewriting `deductible_applied_cents`, `betterment_cents` and `net_payable_cents`; then each claim's `incurred_authorized_cents` is set to the sum of its `paid_cents`, its `released_cents` and its freshly computed `net_payable_cents`, and its `reserve_cents` is set to that same `net_payable_cents`."
    PRD 3.7: "The deductible schedule is selected by the claim's `designated_structural` flag: 250,000 cents when the flag is true, and 100,000 cents when it is false."

    Design: Difficulty/transitive_cascade/builder_default_declaration_propagates_three_links_to_the_posture_band
    """
    scenario = setup_builder_arm_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="LOAD_BEARING_FAILURE",
        assessments=[
            {
                "affected_elements": ["BEAM", "LOAD_BEARING_WALL"],
                "deflection_ratio": 0.0062,
                "load_bearing_affected": True,
            }
        ],
        claim_overrides={"damage_description": "Beam deflection over the great room"},
    )
    claim = scenario["claim"]
    assert claim["status"] == "BUILDER_OBLIGATION_NOTICE"
    assert claim["obligor"] == "BUILDER"
    assert claim["deductible_applied_cents"] == 0
    assert claim["net_payable_cents"] == 1_610_000
    assert claim["reserve_cents"] == 0

    validate_success(
        api.declare_builder_default(
            scenario["builder"]["id"],
            default_declaration_payload(reason="builder ceased operations"),
            compliance_officer_headers,
        ),
        200,
    )

    repartied = read_claim(claim["id"])
    assert repartied["status"] == "INSURER_ADJUDICATION"
    assert repartied["obligor"] == "INSURER"
    assert repartied["gross_adjusted_cents"] == 1_750_000
    assert repartied["deductible_applied_cents"] == 250_000
    assert repartied["betterment_cents"] == 120_000
    assert repartied["net_payable_cents"] == 1_380_000, (
        "the insurer-backed variant charges the structural deductible, so the "
        "builder-arm figure of 1,610,000 is replaced rather than carried over"
    )
    assert repartied["reserve_cents"] == 1_380_000
    assert repartied["incurred_authorized_cents"] == 1_380_000
    assert repartied["version"] == claim["version"] + 1
    assert_claim(repartied)


def test_default_declaration_recompute_pushes_the_builder_into_frozen(
    api, compliance_officer_headers, underwriting_officer_headers
):
    """The third link, two hops from the write. The reserve figures the second link
    moved feed the loss-ratio recompute, and a builder whose band was OPEN before
    the declaration reads FROZEN after it.

    PRD 3.2: "The **third link** follows from the second: because those reserve figures moved, the builder's `incurred_loss_cents`, `loss_ratio` and `monitoring_posture` are recomputed."
    PRD 3.2: "`monitoring_posture` is a band on the rounded ratio with lower bounds inclusive: `OPEN` below 0.6500, `WATCH` from 0.6500 up to but not including 0.9000, `RESTRICTED` from 0.9000 up to but not including 1.2000, and `FROZEN` at 1.2000 or above."

    Design: Difficulty/transitive_cascade/builder_default_declaration_propagates_three_links_to_the_posture_band
    """
    scenario = setup_builder_arm_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="LOAD_BEARING_FAILURE",
        assessments=[
            {
                "affected_elements": ["BEAM", "LOAD_BEARING_WALL"],
                "deflection_ratio": 0.0062,
                "load_bearing_affected": True,
            }
        ],
        claim_overrides={"damage_description": "Beam deflection over the great room"},
    )
    builder_before = validate_success(
        api.get_builder(scenario["builder"]["id"], underwriting_officer_headers)
    )
    assert builder_before["underwriting_status"] == "APPROVED"
    assert builder_before["incurred_loss_cents"] == 0
    assert builder_before["monitoring_posture"] == "OPEN"

    defaulted = validate_success(
        api.declare_builder_default(
            scenario["builder"]["id"],
            default_declaration_payload(reason="builder ceased operations"),
            compliance_officer_headers,
        ),
        200,
    )
    assert defaulted["underwriting_status"] == "DEFAULTED"
    assert defaulted["earned_premium_cents"] == 363_894
    assert defaulted["incurred_loss_cents"] == 1_380_000
    assert float(defaulted["loss_ratio"]) == pytest.approx(3.7923, abs=0.00005)
    assert defaulted["monitoring_posture"] == "FROZEN"
    assert defaulted["version"] == builder_before["version"] + 1
    assert_builder(defaulted)

    monitor = validate_success(
        api.get_loss_monitor(scenario["builder"]["id"], underwriting_officer_headers)
    )
    assert monitor["incurred_loss_cents"] == 1_380_000
    assert float(monitor["loss_ratio"]) == pytest.approx(3.7923, abs=0.00005)
    assert monitor["monitoring_posture"] == "FROZEN"
    assert monitor["open_claim_count"] == 1
    assert_loss_monitor(monitor)


# ==========================================================================
# Claim intake reads the policy's coverage axis and ignores its premium axis
# ==========================================================================
def test_claim_intake_is_refused_on_a_paid_policy_whose_coverage_is_pending(
    api, underwriting_officer_headers
):
    """The depended-on axis. Intake tests `coverage_status`, so a policy that has
    already reached the terminal `PAID` state on the premium axis is still refused
    while its coverage axis sits in PENDING_ENROLLMENT — and nothing is written.

    PRD 3.6: "Claims can only be filed against a policy whose `coverage_status` is `ACTIVE`, and an attempt against any other coverage state is refused with `ERR_POLICY_NOT_ACTIVE`."
    PRD 3.4: "Neither axis waits for the other in general: `premium_status` may reach `PAID` while `coverage_status` is still `PENDING_ENROLLMENT`, and `coverage_status` may reach `EXPIRED` without `premium_status` ever leaving `UNBILLED`."

    Design: Difficulty/cross_entity_state_dependency/claim_intake_depends_on_the_policy_coverage_axis_not_the_premium_axis
    """
    scenario = setup_paid_pending_policy()
    policy = scenario["policy"]
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])
    assert policy["coverage_status"] == "PENDING_ENROLLMENT"
    assert policy["premium_status"] == "PAID", (
        "the premium axis is already at its terminal state"
    )

    payload = create_claim_payload(
        policy["id"],
        coverage_type="WORKMANSHIP",
        defect_category="WORKMANSHIP_DEFECT",
        claimed_amount_cents=300_000,
        damage_description="Cabinet doors out of true along the kitchen run",
    )
    validate_error(
        api.create_claim(payload, owner_headers),
        ApiErrorId.ERR_POLICY_NOT_ACTIVE.value,
    )

    rows, meta = validate_paginated(
        api.list_claims(underwriting_officer_headers, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 0, "a refused intake leaves no claim row behind"
    assert rows == []

    untouched = read_policy(policy["id"])
    assert untouched["coverage_status"] == "PENDING_ENROLLMENT"
    assert untouched["premium_status"] == "PAID"
    assert untouched["version"] == policy["version"]


def test_claim_intake_succeeds_once_the_coverage_axis_reaches_active(
    api, underwriting_officer_headers
):
    """The independent axis. Nothing about the premium axis changes across the
    crossing point, and the coverage term the claim binds to already existed while
    intake was being refused — so activation of the coverage axis is the whole of
    what made the identical request legal.

    PRD 3.4: "Activation is where coverage goes in force and where the premium finally enters the builder's denominator. An `UnderwritingOfficer` drives `coverage_status` from `PENDING_ENROLLMENT` to `ACTIVE` with no request body at all, and four conditions must hold."
    PRD 3.6: "From those, the terms whose `coverage_type` equals the claimed `coverage_type` and whose closed interval contains the `reported_date` — on or after `start_date` and on or before `end_date` — are ranked with `BASE` terms ahead of `ENDORSEMENT` terms, then by `start_date` ascending, then by `created_at` ascending, and the first is chosen."
    PRD 3.6: "A fresh claim lands in `status` `SUBMITTED` with `designated_structural` false and with all four money fields — `reserve_cents`, `paid_cents`, `released_cents` and `incurred_authorized_cents` — at 0."

    Design: Difficulty/cross_entity_state_dependency/claim_intake_depends_on_the_policy_coverage_axis_not_the_premium_axis
    """
    scenario = setup_paid_pending_policy()
    policy = scenario["policy"]
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])
    workmanship_term = find_term(scenario["terms"], "WORKMANSHIP")
    assert workmanship_term["term_kind"] == "BASE"
    assert workmanship_term["status"] == "OPEN"

    payload = create_claim_payload(
        policy["id"],
        coverage_type="WORKMANSHIP",
        defect_category="WORKMANSHIP_DEFECT",
        claimed_amount_cents=300_000,
        damage_description="Cabinet doors out of true along the kitchen run",
    )
    validate_error(
        api.create_claim(payload, owner_headers),
        ApiErrorId.ERR_POLICY_NOT_ACTIVE.value,
    )

    activated = validate_success(
        api.activate_policy(policy["id"], underwriting_officer_headers), 200
    )
    assert activated["coverage_status"] == "ACTIVE"
    assert activated["premium_status"] == "PAID", (
        "the premium axis is untouched by the crossing point"
    )
    assert_policy(activated)

    claim = validate_success(api.create_claim(payload, owner_headers), 201)
    assert claim["status"] == "SUBMITTED"
    assert claim["policy_id"] == policy["id"]
    assert claim["filed_by_owner_id"] == scenario["homeowner"]["id"]
    assert claim["coverage_term_id"] == workmanship_term["id"], (
        "the binding term pre-dated the activation; only the policy's coverage "
        "axis had been standing in the way"
    )
    assert claim["reported_date"] == "2026-08-15"
    assert claim["designated_structural"] is False
    assert claim["reserve_cents"] == 0
    assert claim["paid_cents"] == 0
    assert claim["released_cents"] == 0
    assert claim["incurred_authorized_cents"] == 0
    assert_claim(claim)

    rows, meta = validate_paginated(
        api.list_claims(underwriting_officer_headers, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == claim["id"]


# ==========================================================================
# Transfer recording reads the dispute state of the policy's claims
# ==========================================================================
def test_recording_is_blocked_while_a_claim_sits_in_mediation(
    api, underwriting_officer_headers
):
    """The depended-on entity is a claim, not the transfer being addressed. The
    transfer is fully APPROVED and every one of its own preconditions is met, yet
    recording is refused because a claim on the same policy is in MEDIATION — and
    neither the transfer nor the policy is touched by the refusal.

    PRD 3.5: "One guard protects the carrier here: recording is blocked while **any** claim on that policy has a `status` of `MEDIATION` or `ARBITRATION`, because the carrier will not change the claimant of record mid-dispute. The attempt is refused with `ERR_OPEN_DISPUTE_BLOCKS_TRANSFER`."

    Design: Difficulty/cross_entity_state_dependency/transfer_recording_depends_on_no_claim_sitting_in_the_dispute_ladder
    """
    scenario = setup_mediation_case()
    scenario = setup_approved_transfer(clock=None, scenario=scenario)
    policy = scenario["policy"]
    transfer = scenario["transfer"]
    claim = read_claim(scenario["claim"]["id"])
    assert claim["status"] == "MEDIATION"
    assert claim["policy_id"] == policy["id"]
    assert transfer["status"] == "APPROVED"
    assert transfer["transfer_fee_cents"] == 7_500
    assert policy["transfer_count"] == 0
    assert policy["current_owner_id"] == scenario["homeowner"]["id"]

    validate_error(
        api.record_transfer(transfer["id"], underwriting_officer_headers),
        ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_TRANSFER.value,
    )

    still_approved = read_transfer(transfer["id"])
    assert still_approved["status"] == "APPROVED"
    assert still_approved["version"] == transfer["version"]
    assert_transfer(still_approved)

    unchanged = read_policy(policy["id"])
    assert unchanged["current_owner_id"] == scenario["homeowner"]["id"], (
        "ownership of record does not move while the dispute is live"
    )
    assert unchanged["transfer_count"] == 0
    assert unchanged["pending_transfer_id"] == transfer["id"]
    assert unchanged["version"] == policy["version"]


def test_recording_succeeds_once_the_mediation_settles_and_closes_the_claim(
    api, underwriting_officer_headers
):
    """Closing the dispute on the other entity is what unblocks the transfer: the
    identical recording call, refused a moment earlier, now moves ownership. The
    guard reads the claim's live status rather than a flag latched onto the
    transfer.

    PRD 3.9: "An outcome of `SETTLED` moves the case `SCHEDULED → SETTLED`, records the `settlement_amount_cents`, and closes the claim: `MEDIATION → CLOSED_SETTLED`, or `ARBITRATION → CLOSED_SETTLED` when an arbitration session settles before an award is issued."
    PRD 3.5: "The policy's `current_owner_id` is rewritten to the request's `new_owner_id`, its `transfer_count` is incremented by 1, its `pending_transfer_id` is cleared to null, and its `version` advances by 1; the request's own `version` advances by 1. The policy's `initial_owner_id` is never rewritten — it permanently records the buyer at closing."

    Design: Difficulty/cross_entity_state_dependency/transfer_recording_depends_on_no_claim_sitting_in_the_dispute_ladder
    """
    scenario = setup_mediation_case()
    scenario = setup_approved_transfer(clock=None, scenario=scenario)
    policy = scenario["policy"]
    transfer = scenario["transfer"]
    case = scenario["mediation_case"]
    validate_error(
        api.record_transfer(transfer["id"], underwriting_officer_headers),
        ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_TRANSFER.value,
    )

    set_clock("2028-09-10T15:00:00Z")
    record_session_outcome(case["id"], "SETTLED", settlement_amount_cents=400_000)
    settled_case = read_escalation_case(case["id"])
    assert settled_case["status"] == "SETTLED"
    assert settled_case["settlement_amount_cents"] == 400_000
    settled_claim = read_claim(scenario["claim"]["id"])
    assert settled_claim["status"] == "CLOSED_SETTLED", (
        "the claim has left the dispute ladder"
    )

    validate_success(
        api.record_transfer(transfer["id"], underwriting_officer_headers), 200
    )

    recorded = read_transfer(transfer["id"])
    assert recorded["status"] == "RECORDED"
    assert recorded["transfer_fee_cents"] == 7_500
    assert recorded["new_owner_id"] == scenario["transferee"]["id"]
    assert_transfer(recorded)

    final_policy = read_policy(policy["id"])
    assert final_policy["current_owner_id"] == scenario["transferee"]["id"]
    assert final_policy["initial_owner_id"] == scenario["homeowner"]["id"]
    assert final_policy["transfer_count"] == 1
    assert final_policy["pending_transfer_id"] is None
    assert_policy(final_policy)
