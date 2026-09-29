"""Non-linear lifecycle behaviour: states that are re-entered after leaving them,
and a claim lifecycle that forks into two arms with disjoint side effects before
rejoining at insurer adjudication.

Every test builds its own world from scratch against a freshly restarted server
with an empty database.
"""

import pytest

from test_helpers import (
    assert_builder,
    assert_claim,
    assert_loss_monitor,
    assert_underwriting_review,
    builder_response_payload,
    create_approved_builder,
    create_builder_under_review,
    make_builder_principal_headers,
    obligation_routing_payload,
    reinstatement_payload,
    review_intake_payload,
    setup_builder_arm_claim,
    suspension_payload,
    underwriting_review_payload,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# Builder underwriting file: two distinct cycles that re-enter a prior state
# ==========================================================================
def test_referred_file_is_taken_into_review_again_and_rescored(
    api, underwriting_officer_headers
):
    """A REFER verdict pushes the file back to REFERRED, and the intake operation
    then drives REFERRED -> UNDER_REVIEW a second time, re-entering a state the
    file had already left.

    PRD 3.1: "The same operation also serves the referral loop: a file sitting in `REFERRED` — sent back for revision by an earlier decision — is taken into review again by the same operation, so `REFERRED → UNDER_REVIEW` is a legal transition alongside `SUBMITTED → UNDER_REVIEW`."
    PRD 3.1: "Both intake transitions write `risk_score` and `risk_class` and set `risk_basis` to `INITIAL_UNDERWRITING`, and both advance the builder's `version` by 1."
    PRD 3.1: "`resulting_underwriting_status` records the state the builder landed in — `APPROVED`, `DECLINED` or `REFERRED` respectively."

    Design: Difficulty/non_linear_state_machine/builder_referral_and_suspension_cycles_re_enter_prior_states
    """
    builder = create_builder_under_review()
    assert builder["underwriting_status"] == "UNDER_REVIEW"
    assert float(builder["risk_score"]) == pytest.approx(45.00, abs=0.005)
    assert builder["risk_class"] == "C"

    referred = validate_success(
        api.create_underwriting_review(
            builder["id"],
            underwriting_review_payload(
                "REFER", reviewer_notes="surety letter missing from the file"
            ),
            underwriting_officer_headers,
        ),
        201,
    )
    assert referred["resulting_underwriting_status"] == "REFERRED"
    assert float(referred["risk_score_snapshot"]) == pytest.approx(45.00, abs=0.005)
    assert_underwriting_review(referred)

    before_reentry = validate_success(
        api.get_builder(builder["id"], underwriting_officer_headers)
    )
    assert before_reentry["underwriting_status"] == "REFERRED"

    re_entered = validate_success(
        api.take_builder_into_review(
            builder["id"],
            review_intake_payload(intake_note="surety letter received, re-reviewing"),
            underwriting_officer_headers,
        ),
        200,
    )
    assert re_entered["underwriting_status"] == "UNDER_REVIEW"
    assert float(re_entered["risk_score"]) == pytest.approx(45.00, abs=0.005)
    assert re_entered["risk_class"] == "C"
    assert re_entered["risk_basis"] == "INITIAL_UNDERWRITING"
    assert re_entered["version"] == before_reentry["version"] + 1
    assert_builder(re_entered)

    approved = validate_success(
        api.create_underwriting_review(
            builder["id"],
            underwriting_review_payload("APPROVE"),
            underwriting_officer_headers,
        ),
        201,
    )
    assert approved["resulting_underwriting_status"] == "APPROVED"
    assert (
        validate_success(api.get_builder(builder["id"], underwriting_officer_headers))[
            "underwriting_status"
        ]
        == "APPROVED"
    )

    rows, meta = validate_paginated(
        api.list_underwriting_reviews(builder["id"], underwriting_officer_headers)
    )
    assert meta["total_count"] == 2, (
        "the two verdicts are the only review rows: re-entering review mints none"
    )
    assert rows[0]["resulting_underwriting_status"] == "APPROVED"
    assert rows[1]["resulting_underwriting_status"] == "REFERRED"


def test_suspended_builder_is_reinstated_back_into_approved(
    api, underwriting_officer_headers, compliance_officer_headers
):
    """The second cycle re-enters APPROVED from SUSPENDED without re-running
    underwriting, so the scoring fields carry through the round trip untouched.

    PRD 3.2: "Suspension is also available to compliance directly. A `ComplianceOfficer` supplies a `reason` and drives `APPROVED → SUSPENDED`, which stops new enrollments and activations for that builder. The reverse move belongs to underwriting: an `UnderwritingOfficer` supplies a `reason` and drives `SUSPENDED → APPROVED`, closing the `APPROVED → SUSPENDED → APPROVED` cycle — but only while the builder's `monitoring_posture` is anything other than `FROZEN`."

    Design: Difficulty/non_linear_state_machine/builder_referral_and_suspension_cycles_re_enter_prior_states
    """
    builder = create_approved_builder()
    assert builder["underwriting_status"] == "APPROVED"
    assert builder["monitoring_posture"] == "OPEN"

    suspended = validate_success(
        api.suspend_builder(
            builder["id"],
            suspension_payload(reason="market-conduct examination opened"),
            compliance_officer_headers,
        ),
        200,
    )
    assert suspended["underwriting_status"] == "SUSPENDED"
    assert suspended["version"] == builder["version"] + 1
    assert_builder(suspended)

    reinstated = validate_success(
        api.reinstate_builder(
            builder["id"],
            reinstatement_payload(reason="examination closed with no findings"),
            underwriting_officer_headers,
        ),
        200,
    )
    assert reinstated["underwriting_status"] == "APPROVED", (
        "SUSPENDED -> APPROVED re-enters a state the file had already occupied"
    )
    assert reinstated["monitoring_posture"] == "OPEN"
    assert reinstated["version"] == suspended["version"] + 1
    assert float(reinstated["risk_score"]) == pytest.approx(45.00, abs=0.005)
    assert reinstated["risk_class"] == "C"
    assert reinstated["risk_basis"] == "INITIAL_UNDERWRITING"
    assert_builder(reinstated)

    rows, meta = validate_paginated(
        api.list_underwriting_reviews(builder["id"], underwriting_officer_headers)
    )
    assert meta["total_count"] == 1, (
        "neither the suspension nor the reinstatement records a verdict"
    )
    assert rows[0]["resulting_underwriting_status"] == "APPROVED"


# ==========================================================================
# Claim lifecycle fork: the builder arm and the insurer arm, then the rejoin
# ==========================================================================
def test_builder_arm_zeroes_the_deductible_and_puts_up_no_reserve(
    api, claims_adjuster_headers, underwriting_officer_headers
):
    """Arm A of the fork. Routing a claim reported inside the builder-obligation
    period lands in BUILDER_OBLIGATION_NOTICE, where the deductible is forced to
    0, no reserve is established, and the builder's loss figures stay untouched.

    PRD 3.7: "When the `obligor` is `BUILDER`, routing advances the claim `UNDER_INVESTIGATION → BUILDER_OBLIGATION_NOTICE`. The settlement waterfall runs under the **builder-obligation variant**, writing `betterment_cents` and `net_payable_cents` and forcing `deductible_applied_cents` to 0 — the builder repairs in kind, so no policy deductible is charged to the homeowner. Both `reserve_cents` and `incurred_authorized_cents` remain 0, because the builder and not the carrier funds this arm, and **no builder loss-ratio recompute occurs**."
    PRD 3.7: "The betterment percentage is selected from that **provisional net, before betterment is subtracted**: nothing at all when the provisional net is below 500,000 cents, 5 percent when it is from 500,000 cents up to but not including 1,500,000 cents, and 8 percent when it is 1,500,000 cents or more."

    Design: Difficulty/non_linear_state_machine/claim_fork_arms_carry_disjoint_side_effects_and_rejoin_at_insurer_adjudication
    """
    scenario = setup_builder_arm_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="LOAD_BEARING_FAILURE",
        assessments=[
            {
                "affected_elements": ["BEAM"],
                "deflection_ratio": 0.0062,
                "load_bearing_affected": True,
            }
        ],
        route=False,
        claim_overrides={"damage_description": "Beam deflection over the great room"},
    )
    claim = scenario["claim"]
    assert claim["status"] == "UNDER_INVESTIGATION"
    assert claim["designated_structural"] is True
    assert claim["gross_adjusted_cents"] == 1_750_000

    routed = validate_success(
        api.route_claim_obligation(
            claim["id"], obligation_routing_payload(), claims_adjuster_headers
        ),
        200,
    )
    assert routed["status"] == "BUILDER_OBLIGATION_NOTICE"
    assert routed["obligor"] == "BUILDER"
    assert routed["deductible_applied_cents"] == 0
    assert routed["betterment_cents"] == 140_000
    assert routed["net_payable_cents"] == 1_610_000
    assert routed["reserve_cents"] == 0
    assert routed["incurred_authorized_cents"] == 0
    assert_claim(routed)

    monitor = validate_success(
        api.get_loss_monitor(scenario["builder"]["id"], underwriting_officer_headers)
    )
    assert monitor["earned_premium_cents"] == 363_894
    assert monitor["incurred_loss_cents"] == 0, (
        "the builder arm contributes nothing to the carrier's incurred loss"
    )
    assert float(monitor["loss_ratio"]) == pytest.approx(0.0, abs=0.00005)
    assert monitor["monitoring_posture"] == "OPEN"
    assert_loss_monitor(monitor)


def test_refused_obligation_rejoins_the_insurer_arm_and_charges_the_deductible(
    api, underwriting_officer_headers
):
    """The rejoin. A REFUSE_OBLIGATION response carries the very same claim from
    the builder arm into INSURER_ADJUDICATION, where the waterfall is re-run with
    the deductible charged, the reserve established and the loss ratio recomputed
    — so arm A's side effects are replaced rather than added to.

    PRD 3.7: "`REFUSE_OBLIGATION` is the **join point** where the builder arm rejoins the insurer arm, and its side effects are the mirror image of acceptance. The claim advances `BUILDER_OBLIGATION_NOTICE → INSURER_ADJUDICATION`; its `obligor` is rewritten from `BUILDER` to `INSURER`; the settlement waterfall is re-run under the insurer-backed variant, rewriting `deductible_applied_cents`, `betterment_cents` and `net_payable_cents` — so the deductible the builder arm had zeroed is now charged, and the betterment tier may fall as a result; `incurred_authorized_cents` is set to the sum of `paid_cents`, `released_cents` and the new `net_payable_cents`, and `reserve_cents` is set to that new `net_payable_cents`; the builder's `incurred_loss_cents`, `loss_ratio` and `monitoring_posture` are recomputed; and the claim's `version` advances by 1."
    PRD 3.7: "The deductible schedule is selected by the claim's `designated_structural` flag: 250,000 cents when the flag is true, and 100,000 cents when it is false."

    Design: Difficulty/non_linear_state_machine/claim_fork_arms_carry_disjoint_side_effects_and_rejoin_at_insurer_adjudication
    """
    scenario = setup_builder_arm_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="LOAD_BEARING_FAILURE",
        assessments=[
            {
                "affected_elements": ["BEAM"],
                "deflection_ratio": 0.0062,
                "load_bearing_affected": True,
            }
        ],
        claim_overrides={"damage_description": "Beam deflection over the great room"},
    )
    claim = scenario["claim"]
    assert claim["status"] == "BUILDER_OBLIGATION_NOTICE"
    assert claim["deductible_applied_cents"] == 0
    assert claim["net_payable_cents"] == 1_610_000
    assert claim["reserve_cents"] == 0

    joined = validate_success(
        api.create_builder_response(
            claim["id"],
            builder_response_payload(
                "REFUSE_OBLIGATION",
                response_note="the defect predates our scope of work",
            ),
            make_builder_principal_headers(scenario["builder"]["id"]),
        ),
        200,
    )
    assert joined["status"] == "INSURER_ADJUDICATION"
    assert joined["obligor"] == "INSURER"
    assert joined["gross_adjusted_cents"] == 1_750_000
    assert joined["deductible_applied_cents"] == 250_000
    assert joined["betterment_cents"] == 120_000
    assert joined["net_payable_cents"] == 1_380_000
    assert joined["reserve_cents"] == 1_380_000
    assert joined["incurred_authorized_cents"] == 1_380_000
    assert joined["version"] == claim["version"] + 1
    assert_claim(joined)

    monitor = validate_success(
        api.get_loss_monitor(scenario["builder"]["id"], underwriting_officer_headers)
    )
    assert monitor["earned_premium_cents"] == 363_894
    assert monitor["incurred_loss_cents"] == 1_380_000
    assert float(monitor["loss_ratio"]) == pytest.approx(3.7923, abs=0.00005)
    assert monitor["monitoring_posture"] == "FROZEN"
    assert_loss_monitor(monitor)
