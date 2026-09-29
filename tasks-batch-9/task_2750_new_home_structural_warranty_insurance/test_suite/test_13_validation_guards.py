"""Validation guards: conditional gates, priority ordering between two rules
violated by the same request, cross-entity predecessor checks, temporal windows,
cascading documentation checks, aggregate money ceilings, and the accepting side
of five boundaries.

Every test builds its world from scratch against a freshly restarted server with
an empty database, so no test depends on another's residue.
"""

import pytest

from test_helpers import (
    ADJUSTER_USER_ID,
    ApiErrorId,
    INSURER_PERIOD_INSTANT,
    add_endorsement_term,
    adjudicate_claim,
    assert_claim_money_conserved,
    assert_coverage_capacity_conserved,
    assert_calendar_date,
    assert_escalation_case,
    assert_policy,
    assert_transfer,
    authorize_reserve,
    book_escalation,
    create_builder_under_review,
    create_claim_payload,
    create_coverage_term_payload,
    create_escalation_payload,
    create_homeowner,
    create_neutral,
    create_policy_payload,
    create_transfer_payload,
    documentation_request_payload,
    file_claim,
    investigate_claim,
    investigation_payload,
    invoice_policy,
    make_homeowner_headers,
    pay_claim,
    pay_policy_premium,
    payment_payload,
    read_builder,
    read_claim,
    read_coverage_term,
    read_escalation_case,
    read_loss_monitor,
    read_neutral,
    read_policy,
    read_transfer,
    record_session_outcome,
    resubmission_payload,
    review_intake_payload,
    route_claim,
    set_clock,
    setup_active_policy,
    setup_approved_builder_and_owner,
    setup_insurer_arm_claim,
    setup_routed_claim,
    transfer_decision_payload,
    underwriting_review_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# Table 4 Validations / the RESTRICTED posture gate on enrollment
# ==========================================================================
def test_a_restricted_posture_refuses_an_unacknowledged_enrollment(
    api, underwriting_officer_headers
):
    """A loss ratio of 1.0992 puts the builder in RESTRICTED, and an enrollment
    that does not carry the acknowledgement is refused outright.

    PRD Section 3.3: "And when the builder's `monitoring_posture` is
    `RESTRICTED`, the request must carry `posture_override_acknowledged` set to
    true; a restricted-posture enrollment without that explicit acknowledgement
    is refused with `ERR_POSTURE_OVERRIDE_REQUIRED`."

    PRD Section 3.2: "`monitoring_posture` is a band on the rounded ratio with
    lower bounds inclusive: `OPEN` below 0.6500, `WATCH` from 0.6500 up to but
    not including 0.9000, `RESTRICTED` from 0.9000 up to but not including
    1.2000, and `FROZEN` at 1.2000 or above."

    Design: Corner/Table 4 Validations/a_restricted_posture_gates_a_new_enrollment_unless_the_override_is_acknowledged
    """
    scenario = setup_insurer_arm_claim(claimed_amount_cents=500_000,
                                       substantiation_ratio=1.00)
    builder = scenario["builder"]
    assert scenario["claim"]["reserve_cents"] == 400_000

    monitor = read_loss_monitor(builder["id"])
    assert float(monitor["loss_ratio"]) == pytest.approx(1.0992, abs=1e-9)
    assert monitor["monitoring_posture"] == "RESTRICTED"

    response = api.create_policy(
        create_policy_payload(
            builder["id"], scenario["homeowner"]["id"],
            street_address="7 Restricted Row", purchase_price_cents=5_000_000,
            closing_date="2028-09-01",
        ),
        scenario["builder_headers"],
    )
    validate_error(response, ApiErrorId.ERR_POSTURE_OVERRIDE_REQUIRED.value)

    # The refused request enrolled nothing: only the original home remains.
    _, meta = validate_paginated(
        api.list_policies(underwriting_officer_headers,
                          {"builder_id": builder["id"]})
    )
    assert meta["total_count"] == 1


def test_the_watch_band_needs_no_acknowledgement_and_the_restricted_floor_does(
    api, underwriting_officer_headers
):
    """Re-reserving to 327,486 cents rounds the ratio to 0.8999 and the identical
    unacknowledged enrollment now succeeds; one cent more rounds onto the
    inclusive 0.9000 floor and the acknowledgement becomes mandatory again.

    PRD Section 3.3: "Under an `OPEN` or `WATCH` posture the acknowledgement flag
    is not required and is simply ignored if present."

    PRD Section 3.3: "And when the builder's `monitoring_posture` is
    `RESTRICTED`, the request must carry `posture_override_acknowledged` set to
    true; a restricted-posture enrollment without that explicit acknowledgement
    is refused with `ERR_POSTURE_OVERRIDE_REQUIRED`."

    PRD Section 2.5: "A builder's `loss_ratio` carries 4 decimal places, and the
    band comparison that assigns `monitoring_posture` is likewise made against
    the already-rounded ratio."

    Design: Corner/Table 4 Validations/a_restricted_posture_gates_a_new_enrollment_unless_the_override_is_acknowledged
    """
    scenario = setup_insurer_arm_claim(claimed_amount_cents=500_000,
                                       substantiation_ratio=1.00)
    builder = scenario["builder"]
    claim = scenario["claim"]
    owner_id = scenario["homeowner"]["id"]

    # One cent below the RESTRICTED floor: the posture is WATCH.
    watch_entry = authorize_reserve(claim["id"], 327_486, entry_type="ADJUSTMENT",
                                    expected_claim_version=claim["version"])
    assert watch_entry["balance_after_reserve_cents"] == 327_486
    watch_monitor = read_loss_monitor(builder["id"])
    assert float(watch_monitor["loss_ratio"]) == pytest.approx(0.8999, abs=1e-9)
    assert watch_monitor["monitoring_posture"] == "WATCH"

    unacknowledged = validate_success(
        api.create_policy(
            create_policy_payload(
                builder["id"], owner_id, street_address="7 Restricted Row",
                purchase_price_cents=5_000_000, closing_date="2028-09-01",
            ),
            scenario["builder_headers"],
        ),
        201,
    )
    assert_policy(unacknowledged)
    assert unacknowledged["premium_cents"] == 44_881
    assert unacknowledged["enrollment_hold"] is False

    # One cent more: 0.899951 rounds half up onto the inclusive floor.
    claim = read_claim(claim["id"])
    restricted_entry = authorize_reserve(claim["id"], 327_487,
                                         entry_type="ADJUSTMENT",
                                         expected_claim_version=claim["version"])
    assert restricted_entry["balance_after_reserve_cents"] == 327_487
    restricted_monitor = read_loss_monitor(builder["id"])
    assert float(restricted_monitor["loss_ratio"]) == pytest.approx(0.9000, abs=1e-9)
    assert restricted_monitor["monitoring_posture"] == "RESTRICTED"

    acknowledged = validate_success(
        api.create_policy(
            create_policy_payload(
                builder["id"], owner_id, street_address="9 Override Ave",
                purchase_price_cents=5_000_000, closing_date="2028-09-01",
                posture_override_acknowledged=True,
            ),
            scenario["builder_headers"],
        ),
        201,
    )
    # The acknowledgement satisfies the gate; it does not change the pricing.
    assert acknowledged["premium_cents"] == 44_881
    assert acknowledged["risk_class_at_enrollment"] == "C"

    _, meta = validate_paginated(
        api.list_policies(underwriting_officer_headers,
                          {"builder_id": builder["id"]})
    )
    assert meta["total_count"] == 3


# ==========================================================================
# Table 4 Validations / request shape outranks the from-state conflict
# ==========================================================================
def test_invalid_request_outranks_the_claim_state_conflict_on_investigation(
    api, claims_adjuster_headers
):
    """One request violates two rules at once — the claim is already
    UNDER_INVESTIGATION and the ratio is outside its declared range — and the
    earlier rung answers.

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    PRD Section 2.8: "**Request shape (422).** `ERR_INVALID_REQUEST` when a
    required body field is missing, is of the wrong type, falls outside its
    declared numeric range, is an enum value that is not a declared member, when
    an amount field is below its declared floor, or when `affected_elements`
    contains duplicate entries."

    PRD Section 3.6: "records a `substantiation_ratio` — the share of the claimed
    amount the carrier accepts as substantiated, between 0.00 and 1.00 inclusive
    with at most two decimal places"

    Design: Corner/Table 4 Validations/invalid_request_outranks_the_claim_state_conflict_on_investigation
    """
    scenario = setup_routed_claim(claimed_amount_cents=2_187_500,
                                  substantiation_ratio=0.80, route=False)
    claim = scenario["claim"]
    assert claim["status"] == "UNDER_INVESTIGATION"

    response = api.create_investigation(
        claim["id"], investigation_payload(1.50), claims_adjuster_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    unchanged = read_claim(claim["id"])
    assert float(unchanged["substantiation_ratio"]) == pytest.approx(0.80, abs=1e-9)
    assert unchanged["gross_adjusted_cents"] == 1_750_000
    assert unchanged["version"] == 2


def test_a_legal_ratio_on_an_investigated_claim_surfaces_the_claim_state_conflict(
    api, claims_adjuster_headers
):
    """The identical replay with a legal ratio reaches the from-state rung, which
    proves the earlier refusal was the shape check and not the state check in
    disguise.

    PRD Section 3.6: "Investigating a claim that is not in `SUBMITTED` is refused
    with `ERR_INVALID_CLAIM_STATE`."

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    Design: Corner/Table 4 Validations/invalid_request_outranks_the_claim_state_conflict_on_investigation
    """
    scenario = setup_routed_claim(claimed_amount_cents=2_187_500,
                                  substantiation_ratio=0.80, route=False)
    claim = scenario["claim"]

    response = api.create_investigation(
        claim["id"], investigation_payload(0.60), claims_adjuster_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE.value)

    unchanged = read_claim(claim["id"])
    assert unchanged["status"] == "UNDER_INVESTIGATION"
    assert float(unchanged["substantiation_ratio"]) == pytest.approx(0.80, abs=1e-9)
    assert unchanged["gross_adjusted_cents"] == 1_750_000
    assert unchanged["version"] == 2


# ==========================================================================
# Table 4 Validations / the two payment ceilings, in order
# ==========================================================================
def _endorsement_claim_scenario(limit_cents: int, claimed_amount_cents: int):
    """One ACTIVE home whose only in-force workmanship capacity is a small
    endorsement, with a WORKMANSHIP claim routed to the carrier and approved."""
    scenario = setup_active_policy()
    set_clock(INSURER_PERIOD_INSTANT)
    endorsement = add_endorsement_term(
        scenario["policy"]["id"], coverage_type="WORKMANSHIP",
        start_date="2028-09-01", end_date="2029-08-31",
        limit_cents=limit_cents, deductible_cents=100_000,
    )
    claim = file_claim(
        scenario["policy"]["id"], scenario["homeowner"]["id"],
        coverage_type="WORKMANSHIP", defect_category="WORKMANSHIP_DEFECT",
        claimed_amount_cents=claimed_amount_cents,
        damage_description="Cabinet and trim rework after a plumbing repair",
    )
    investigate_claim(claim["id"], 1.00)
    route_claim(claim["id"])
    adjudicate_claim(claim["id"], "APPROVE", adjuster_user_id=ADJUSTER_USER_ID)
    scenario["endorsement"] = endorsement
    scenario["claim"] = read_claim(claim["id"])
    return scenario


def test_payment_guards_prefer_exceeds_reserve_over_exceeds_coverage_limit(
    api, second_claims_adjuster_headers
):
    """With the reserve lifted to 900,000 cents over a term that has only 500,000
    of capacity, a payment of 900,001 breaks both ceilings and the reserve
    ceiling answers; 600,000 breaks only the coverage ceiling.

    PRD Section 3.8: "Two ceilings then apply, in order: the amount may not
    exceed the claim's `reserve_cents`, or `ERR_PAYMENT_EXCEEDS_RESERVE`; and it
    may not exceed the `remaining_limit_cents` of the claim's coverage term, or
    `ERR_COVERAGE_LIMIT_EXCEEDED`."

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    PRD Section 3.7: "`net_payable_cents` is the smaller of two figures: the
    provisional net less `betterment_cents`, and the `remaining_limit_cents` of
    the coverage term named by the claim's `coverage_term_id`."

    Design: Corner/Table 4 Validations/payment_guards_prefer_exceeds_reserve_over_exceeds_coverage_limit
    """
    scenario = _endorsement_claim_scenario(limit_cents=500_000,
                                           claimed_amount_cents=800_000)
    claim = scenario["claim"]
    endorsement = scenario["endorsement"]

    # The elapsed BASE workmanship term is out of the candidate set.
    assert endorsement["term_kind"] == "ENDORSEMENT"
    assert claim["coverage_term_id"] == endorsement["id"]
    assert claim["gross_adjusted_cents"] == 800_000
    assert claim["betterment_cents"] == 35_000
    assert claim["net_payable_cents"] == 500_000

    # A reserve may legitimately exceed the term limit; only payments are gated.
    entry = authorize_reserve(claim["id"], 900_000, entry_type="ADJUSTMENT",
                              expected_claim_version=claim["version"])
    assert entry["balance_after_reserve_cents"] == 900_000

    both_violated = api.create_payment(
        claim["id"], payment_payload(900_001), second_claims_adjuster_headers
    )
    validate_error(both_violated, ApiErrorId.ERR_PAYMENT_EXCEEDS_RESERVE.value)

    only_the_limit_violated = api.create_payment(
        claim["id"], payment_payload(600_000), second_claims_adjuster_headers
    )
    validate_error(only_the_limit_violated,
                   ApiErrorId.ERR_COVERAGE_LIMIT_EXCEEDED.value)

    # Neither refusal disbursed anything.
    untouched = read_claim(claim["id"])
    assert untouched["paid_cents"] == 0
    assert untouched["reserve_cents"] == 900_000
    assert read_coverage_term(endorsement["id"])["consumed_limit_cents"] == 0


def test_a_payment_sized_to_the_remaining_term_limit_is_accepted_and_exhausts_it(
    api, second_claims_adjuster_headers
):
    """A payment of exactly the remaining capacity clears both ceilings, closes
    the claim because paid reaches net payable, and drives the term to
    LIMIT_EXHAUSTED.

    PRD Section 3.8: "It closes the claim when the claim is `APPROVED` and its
    `paid_cents` after this payment equals its `net_payable_cents`, advancing
    `APPROVED → CLOSED_PAID`."

    PRD Section 3.8: "When that charge drives the term's `remaining_limit_cents`
    to exactly 0, the term transitions `OPEN → LIMIT_EXHAUSTED` and its
    `version` advances by 1"

    PRD Section 2.9: "A parallel but distinct invariant governs coverage
    capacity: a coverage term's `remaining_limit_cents` plus its
    `consumed_limit_cents` always equals its `limit_cents`."

    Design: Corner/Table 4 Validations/payment_guards_prefer_exceeds_reserve_over_exceeds_coverage_limit
    """
    scenario = _endorsement_claim_scenario(limit_cents=500_000,
                                           claimed_amount_cents=800_000)
    claim = scenario["claim"]
    endorsement = scenario["endorsement"]
    authorize_reserve(claim["id"], 900_000, entry_type="ADJUSTMENT",
                      expected_claim_version=claim["version"])

    paid = validate_success(
        api.create_payment(claim["id"], payment_payload(500_000),
                           second_claims_adjuster_headers),
        200,
    )
    assert paid["paid_cents"] == 500_000
    assert paid["reserve_cents"] == 400_000
    assert paid["status"] == "CLOSED_PAID"
    assert_claim_money_conserved(paid)

    term = read_coverage_term(endorsement["id"])
    assert term["status"] == "LIMIT_EXHAUSTED"
    assert term["consumed_limit_cents"] == 500_000
    assert term["remaining_limit_cents"] == 0
    assert_coverage_capacity_conserved(term)


# ==========================================================================
# Table 4 Validations / the arbitration predecessor must be this claim's impasse
# ==========================================================================
ARBITRATION_WINDOW = ("2028-09-20T14:00:00Z", "2028-09-20T18:00:00Z")


def _two_denied_claims_each_in_mediation():
    """Two DENIED claims on one home, each mediating with its own neutral, plus
    an arbitrator on the panel and the clock inside the mediation windows."""
    scenario = setup_routed_claim(claimed_amount_cents=2_187_500,
                                 substantiation_ratio=0.80)
    claim_a = scenario["claim"]
    adjudicate_claim(claim_a["id"], "DENY", adjuster_user_id=ADJUSTER_USER_ID,
                     adjudication_note="maintenance exclusion")

    scenario = setup_routed_claim(claimed_amount_cents=500_000,
                                 substantiation_ratio=1.00, scenario=scenario,
                                 claim_instant=None)
    claim_b = scenario["claim"]
    adjudicate_claim(claim_b["id"], "DENY", adjuster_user_id=ADJUSTER_USER_ID,
                     adjudication_note="maintenance exclusion")

    mediator_a = create_neutral(full_name="Marcia Vance", credential="MEDIATOR")
    mediator_b = create_neutral(full_name="Owen Reilly", credential="MEDIATOR")
    arbitrator = create_neutral(full_name="Priya Raman", credential="ARBITRATOR")

    owner_id = scenario["homeowner"]["id"]
    case_a = book_escalation(claim_a["id"], owner_id, mediator_a["id"],
                             stage="MEDIATION",
                             window_start="2028-09-10T14:00:00Z",
                             window_end="2028-09-10T18:00:00Z")
    case_b = book_escalation(claim_b["id"], owner_id, mediator_b["id"],
                             stage="MEDIATION",
                             window_start="2028-09-10T14:00:00Z",
                             window_end="2028-09-10T18:00:00Z")
    set_clock("2028-09-10T15:00:00Z")
    return {
        "owner_id": owner_id,
        "claim_a": read_claim(claim_a["id"]),
        "claim_b": read_claim(claim_b["id"]),
        "case_a": case_a,
        "case_b": case_b,
        "arbitrator": arbitrator,
    }


def test_arbitration_is_refused_while_its_own_predecessor_is_still_scheduled(api):
    """Claim B's mediation has not deadlocked, so naming it as the predecessor of
    an arbitration on claim B is refused as an unexhausted mediation.

    PRD Section 3.9: "An `ARBITRATION` request must supply a `prior_case_id`, and
    that case must have reached `status` `IMPASSE`; a missing predecessor or one
    that has not deadlocked is refused with `ERR_MEDIATION_NOT_EXHAUSTED`."

    PRD Section 3.9: "An outcome of `IMPASSE` moves the case `SCHEDULED →
    IMPASSE` and deliberately leaves the claim's `status` alone — a deadlocked
    mediation keeps the claim in `MEDIATION` so the arbitration rung remains
    reachable."

    Design: Corner/Table 4 Validations/arbitration_requires_an_impasse_predecessor_that_belongs_to_the_same_claim
    """
    world = _two_denied_claims_each_in_mediation()
    impasse = record_session_outcome(world["case_a"]["id"], "IMPASSE",
                                     adjuster_user_id=ADJUSTER_USER_ID)
    assert impasse["status"] == "IMPASSE"
    assert read_claim(world["claim_a"]["id"])["status"] == "MEDIATION"

    window_start, window_end = ARBITRATION_WINDOW
    response = api.create_escalation(
        world["claim_b"]["id"],
        create_escalation_payload(world["arbitrator"]["id"], "ARBITRATION",
                                  window_start, window_end,
                                  prior_case_id=world["case_b"]["id"]),
        make_homeowner_headers(world["owner_id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEDIATION_NOT_EXHAUSTED.value)

    assert read_escalation_case(world["case_b"]["id"])["status"] == "SCHEDULED"
    assert read_claim(world["claim_b"]["id"])["status"] == "MEDIATION"
    assert read_neutral(world["arbitrator"]["id"])["booked_session_count"] == 0


def test_arbitration_requires_an_impasse_predecessor_that_belongs_to_the_same_claim(
    api,
):
    """Once claim B's mediation is also deadlocked it is a legitimate impasse but
    still the wrong claim's, so the answer changes error; only claim A's own
    impasse case opens the binding rung.

    PRD Section 3.9: "That predecessor must also belong to the same claim: a
    `prior_case_id` naming a case whose `claim_id` is a different claim is refused
    with `ERR_PRIOR_CASE_CLAIM_MISMATCH`."

    PRD Section 3.9: "A successful booking creates an escalation case against the
    claim named in its `claim_id`, in `status` `SCHEDULED`, with `binding` false
    for a `MEDIATION` case and true for an `ARBITRATION` case — `binding` is
    derived from the stage and is never supplied by the client."

    PRD Section 3.9: "The booked neutral's `booked_session_count` is incremented
    by 1 and its `version` advances by 1; that counter is the number of escalation
    cases naming this neutral whose `status` is `SCHEDULED`, `SETTLED`, `IMPASSE`
    or `AWARD_ISSUED`."

    Design: Corner/Table 4 Validations/arbitration_requires_an_impasse_predecessor_that_belongs_to_the_same_claim
    """
    world = _two_denied_claims_each_in_mediation()
    record_session_outcome(world["case_a"]["id"], "IMPASSE",
                           adjuster_user_id=ADJUSTER_USER_ID)
    other_impasse = record_session_outcome(world["case_b"]["id"], "IMPASSE",
                                           adjuster_user_id=ADJUSTER_USER_ID)
    assert other_impasse["status"] == "IMPASSE"

    window_start, window_end = ARBITRATION_WINDOW
    owner_headers = make_homeowner_headers(world["owner_id"])

    mismatch = api.create_escalation(
        world["claim_a"]["id"],
        create_escalation_payload(world["arbitrator"]["id"], "ARBITRATION",
                                  window_start, window_end,
                                  prior_case_id=world["case_b"]["id"]),
        owner_headers,
    )
    validate_error(mismatch, ApiErrorId.ERR_PRIOR_CASE_CLAIM_MISMATCH.value)

    accepted = validate_success(
        api.create_escalation(
            world["claim_a"]["id"],
            create_escalation_payload(world["arbitrator"]["id"], "ARBITRATION",
                                      window_start, window_end,
                                      prior_case_id=world["case_a"]["id"]),
            owner_headers,
        ),
        201,
    )
    assert_escalation_case(accepted)
    assert accepted["status"] == "SCHEDULED"
    assert accepted["binding"] is True
    assert accepted["prior_case_id"] == world["case_a"]["id"]

    # The refused probe moved neither claim.
    assert read_claim(world["claim_a"]["id"])["status"] == "ARBITRATION"
    assert read_claim(world["claim_b"]["id"])["status"] == "MEDIATION"
    assert read_neutral(world["arbitrator"]["id"])["booked_session_count"] == 1


# ==========================================================================
# Table 4 Validations / class D is uninsurable, so only the verdict changes
# ==========================================================================
CLASS_D_INPUTS = {
    "company_name": "Hazard Homes",
    "years_in_business": 5,
    "homes_closed_last_year": 25,
    "claims_history_score": 0,
    "financial_strength_tier": "TIER_3",
}


def test_a_class_d_builder_cannot_be_approved(api, underwriting_officer_headers):
    """A claims history of 0 scores 50 + 50 + 2 - 10 - 0 = 92.00, which bands into
    class D, and the APPROVE verdict is refused without writing a review row.

    PRD Section 3.2: "One decision is not available at the underwriter's
    discretion: **approval of a class `D` builder is refused**."

    PRD Section 3.2: "The `UNDER_REVIEW → APPROVED` transition requires the
    builder's `risk_class` to be `A`, `B` or `C`, and an `APPROVE` verdict on a
    file whose `risk_class` is `D` is rejected with `ERR_RISK_CLASS_INELIGIBLE`."

    PRD Section 3.1: "class `D` for a score of 65.00 or higher"

    Design: Corner/Table 4 Validations/a_class_d_builder_cannot_be_approved_and_must_be_declined_instead
    """
    builder = create_builder_under_review(**CLASS_D_INPUTS)
    assert float(builder["risk_score"]) == pytest.approx(92.00, abs=1e-9)
    assert builder["risk_class"] == "D"
    assert builder["underwriting_status"] == "UNDER_REVIEW"

    response = api.create_underwriting_review(
        builder["id"],
        underwriting_review_payload(
            "APPROVE", reviewer_notes="attempted approval of a class D builder"),
        underwriting_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_RISK_CLASS_INELIGIBLE.value)

    rows, meta = validate_paginated(
        api.list_underwriting_reviews(builder["id"], underwriting_officer_headers,
                                      {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0
    assert rows == []

    after = read_builder(builder["id"])
    assert after["underwriting_status"] == "UNDER_REVIEW"
    assert after["version"] == builder["version"]


def test_a_class_d_builder_must_be_declined_instead(api, underwriting_officer_headers):
    """The same endpoint and the same file accept DECLINE, which proves the gate
    is on the decision value; DECLINED is then terminal against re-intake.

    PRD Section 3.2: "The other two verdicts have no such restriction: `DECLINE`
    and `REFER` are legal from `UNDER_REVIEW` for a builder in any class, and each
    records its review row and advances the builder's `version` by 1 exactly as
    `APPROVE` does."

    PRD Section 3.2: "`DECLINED` is terminal — a declined file never re-enters
    review."

    PRD Section 3.1: "The same operation also serves the referral loop: a file
    sitting in `REFERRED` — sent back for revision by an earlier decision — is
    taken into review again by the same operation, so `REFERRED → UNDER_REVIEW` is
    a legal transition alongside `SUBMITTED → UNDER_REVIEW`."

    Design: Corner/Table 4 Validations/a_class_d_builder_cannot_be_approved_and_must_be_declined_instead
    """
    builder = create_builder_under_review(**CLASS_D_INPUTS)

    review = validate_success(
        api.create_underwriting_review(
            builder["id"],
            underwriting_review_payload(
                "DECLINE", reviewer_notes="class D is outside appetite"),
            underwriting_officer_headers,
        ),
        201,
    )
    assert review["decision"] == "DECLINE"
    assert review["resulting_underwriting_status"] == "DECLINED"
    assert review["risk_class_snapshot"] == "D"
    assert float(review["risk_score_snapshot"]) == pytest.approx(92.00, abs=1e-9)

    declined = read_builder(builder["id"])
    assert declined["underwriting_status"] == "DECLINED"
    assert declined["version"] == builder["version"] + 1

    reentry = api.take_builder_into_review(
        builder["id"], review_intake_payload(), underwriting_officer_headers)
    validate_error(reentry, ApiErrorId.ERR_INVALID_BUILDER_STATE.value)
    assert read_builder(builder["id"])["underwriting_status"] == "DECLINED"


# ==========================================================================
# Table 4 Validations / the mediation deadline is inclusive to the day
# ==========================================================================
MEDIATION_WINDOW = ("2028-11-05T14:00:00Z", "2028-11-05T18:00:00Z")


def _denied_claim_with_its_own_mediator(scenario, claimed_amount_cents,
                                       substantiation_ratio, mediator_name,
                                       damage_description):
    """A DENIED claim on the supplied home plus a mediator nobody else has booked,
    so two bookings can never contend for the same panelist."""
    scenario = setup_routed_claim(
        claimed_amount_cents=claimed_amount_cents,
        substantiation_ratio=substantiation_ratio,
        scenario=scenario,
        claim_instant=INSURER_PERIOD_INSTANT,
        claim_overrides={"damage_description": damage_description},
    )
    claim = adjudicate_claim(scenario["claim"]["id"], "DENY",
                             adjuster_user_id=ADJUSTER_USER_ID)
    neutral = create_neutral(full_name=mediator_name, credential="MEDIATOR")
    return scenario, claim, neutral


def test_a_mediation_booked_on_the_deadline_date_itself_is_accepted(api):
    """Denial on 2028-09-01 sets a 2028-10-31 deadline, and a booking made with the
    clock standing on that very date opens the mediation rung.

    PRD Section 3.7: "`escalation_deadline_date` is set to that denial date plus
    60 days — the mediation window, and the deadline is **inclusive**, so opening
    the next rung exactly on `escalation_deadline_date` is allowed and one day
    later is not."

    PRD Section 3.9: "The first rung requires the claim to be in `DENIED` and
    advances it `DENIED → MEDIATION`."

    Design: Corner/Table 4 Validations/an_escalation_one_day_past_the_deadline_is_rejected_as_window_elapsed
    """
    scenario = setup_active_policy()
    scenario, claim, mediator = _denied_claim_with_its_own_mediator(
        scenario, 2_187_500, 0.80, "Marcia Vance",
        "Foundation slab cracking with visible displacement")
    assert claim["status"] == "DENIED"
    assert_calendar_date(claim["denial_date"])
    assert claim["denial_date"] == "2028-09-01"
    assert_calendar_date(claim["escalation_deadline_date"])
    assert claim["escalation_deadline_date"] == "2028-10-31"

    set_clock("2028-10-31T09:00:00Z")
    window_start, window_end = MEDIATION_WINDOW
    booked = validate_success(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(mediator["id"], "MEDIATION",
                                      window_start, window_end),
            make_homeowner_headers(scenario["homeowner"]["id"]),
        ),
        201,
    )
    assert_escalation_case(booked)
    assert booked["status"] == "SCHEDULED"
    assert booked["binding"] is False
    assert read_claim(claim["id"])["status"] == "MEDIATION"
    assert read_neutral(mediator["id"])["booked_session_count"] == 1


def test_an_escalation_one_day_past_the_deadline_is_rejected_as_window_elapsed(api):
    """Only the clock date at request time is compared: the identical booking,
    whose session window is still weeks in the future, is refused once the clock
    stands one day past the inclusive deadline, and the claim stays DENIED.

    PRD Section 3.9: "And the logical clock's current date must be on or before
    the claim's `escalation_deadline_date`; one day past it, the rung is refused
    with `ERR_ESCALATION_WINDOW_ELAPSED`."

    PRD Section 3.9: "The booked neutral's `booked_session_count` is incremented
    by 1 and its `version` advances by 1; that counter is the number of escalation
    cases naming this neutral whose `status` is `SCHEDULED`, `SETTLED`, `IMPASSE`
    or `AWARD_ISSUED`."

    Design: Corner/Table 4 Validations/an_escalation_one_day_past_the_deadline_is_rejected_as_window_elapsed
    """
    scenario = setup_active_policy()
    scenario, claim, mediator = _denied_claim_with_its_own_mediator(
        scenario, 500_000, 1.00, "Owen Reilly",
        "Second slab defect on the same home")
    assert_calendar_date(claim["escalation_deadline_date"])
    assert claim["escalation_deadline_date"] == "2028-10-31"

    set_clock("2028-11-01T09:00:00Z")
    window_start, window_end = MEDIATION_WINDOW
    response = api.create_escalation(
        claim["id"],
        create_escalation_payload(mediator["id"], "MEDIATION",
                                  window_start, window_end),
        make_homeowner_headers(scenario["homeowner"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ESCALATION_WINDOW_ELAPSED.value)

    after = read_claim(claim["id"])
    assert after["status"] == "DENIED"
    assert after["version"] == claim["version"]
    assert read_neutral(mediator["id"])["booked_session_count"] == 0


# ==========================================================================
# Table 4 Validations / approval waits for the documentation round trip
# ==========================================================================
def _undocumented_transfer_request(api):
    """The canonical home, ACTIVE and paid, with an open transfer request that
    simply omitted documents_reference, plus a third owner for the later sale."""
    scenario = setup_active_policy()
    second_owner = create_homeowner(full_name="Ben Calloway",
                                    email="ben.calloway@example.com")
    third_owner = create_homeowner(full_name="Cara Devlin",
                                   email="cara.devlin@example.com")
    policy = read_policy(scenario["policy"]["id"])
    payload = create_transfer_payload(second_owner["id"], policy["version"],
                                      transfer_date="2026-09-01")
    payload.pop("documents_reference")
    transfer = validate_success(
        api.create_transfer(policy["id"], payload, scenario["owner_headers"]),
        201,
    )
    scenario["second_owner"] = second_owner
    scenario["third_owner"] = third_owner
    scenario["transfer"] = transfer
    return scenario


def test_an_undocumented_transfer_cannot_be_approved(api, underwriting_officer_headers):
    """The first request omitted its deed reference and paid the base fee; the
    approval is refused and the request keeps sitting in REQUESTED.

    PRD Section 3.6: "`APPROVE` moves the request from `REQUESTED` to `APPROVED`,
    records the `decision_reason`, and advances the request's `version` by 1; it is
    available **only** when the request's `documents_reference` is not null, and an
    approval on an undocumented request is refused with
    `ERR_MISSING_TRANSFER_DOCUMENTATION`."

    PRD Section 3.6: "Its `transfer_fee_cents` is computed at that moment as a
    base fee of 7,500 cents plus 2,500 cents for each transfer already recorded on
    the policy — so the first hand-off costs seventy-five dollars, the second one
    hundred, the third one hundred and twenty-five."

    Design: Corner/Table 4 Validations/transfer_approval_is_blocked_until_documentation_is_resubmitted
    """
    scenario = _undocumented_transfer_request(api)
    transfer = scenario["transfer"]
    assert_transfer(transfer)
    assert transfer["status"] == "REQUESTED"
    assert transfer["transfer_fee_cents"] == 7_500

    response = api.decide_transfer(
        transfer["id"],
        transfer_decision_payload("APPROVE",
                                  decision_reason="premature approval attempt"),
        underwriting_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_MISSING_TRANSFER_DOCUMENTATION.value)

    unchanged = read_transfer(transfer["id"])
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["version"] == transfer["version"]
    assert read_policy(scenario["policy"]["id"])["current_owner_id"] == \
        scenario["homeowner"]["id"]


def test_transfer_approval_is_blocked_until_documentation_is_resubmitted(
    api, underwriting_officer_headers
):
    """The documentation round trip returns the request to the same state with the
    field filled, approval and recording then move ownership, and the next sale by
    the new owner is repriced from 7,500 to 10,000 cents.

    PRD Section 3.6: "The requesting owner — identified against
    `requested_by_owner_id` rather than against the policy's current holder —
    answers with a `documents_reference`, which overwrites whatever reference the
    row previously held and returns the request from `NEEDS_DOCUMENTATION` to
    `REQUESTED`, again advancing its `version` by 1."

    PRD Section 3.6: "The policy's `current_owner_id` is rewritten to the
    request's `new_owner_id`, its `transfer_count` is incremented by 1, its
    `pending_transfer_id` is cleared to null, and its `version` advances by 1; the
    request's own `version` advances by 1."

    PRD Section 3.6: "The multiplier is the policy's `transfer_count`, which
    counts only transfers that reached `RECORDED`; superseded and rejected requests
    never raise it and never raise the fee."

    Design: Corner/Table 4 Validations/transfer_approval_is_blocked_until_documentation_is_resubmitted
    """
    scenario = _undocumented_transfer_request(api)
    transfer = scenario["transfer"]
    policy_id = scenario["policy"]["id"]
    first_owner_headers = scenario["owner_headers"]

    validate_error(
        api.decide_transfer(
            transfer["id"],
            transfer_decision_payload("APPROVE",
                                      decision_reason="premature approval attempt"),
            underwriting_officer_headers,
        ),
        ApiErrorId.ERR_MISSING_TRANSFER_DOCUMENTATION.value,
    )

    needs_docs = validate_success(
        api.request_transfer_documentation(
            transfer["id"],
            documentation_request_payload(reason="recorded deed missing"),
            underwriting_officer_headers,
        )
    )
    assert needs_docs["status"] == "NEEDS_DOCUMENTATION"

    resubmitted = validate_success(
        api.resubmit_transfer(
            transfer["id"],
            resubmission_payload(documents_reference="DEED-2026-0901-REC"),
            first_owner_headers,
        )
    )
    assert resubmitted["status"] == "REQUESTED"
    assert resubmitted["documents_reference"] == "DEED-2026-0901-REC"

    approved = validate_success(
        api.decide_transfer(
            transfer["id"],
            transfer_decision_payload("APPROVE", decision_reason="deed on file"),
            underwriting_officer_headers,
        )
    )
    assert approved["status"] == "APPROVED"

    recorded = validate_success(
        api.record_transfer(transfer["id"], underwriting_officer_headers)
    )
    assert recorded["status"] == "RECORDED"

    policy = read_policy(policy_id)
    assert policy["current_owner_id"] == scenario["second_owner"]["id"]
    assert policy["initial_owner_id"] == scenario["homeowner"]["id"]
    assert policy["transfer_count"] == 1
    assert policy["pending_transfer_id"] is None

    resale = validate_success(
        api.create_transfer(
            policy_id,
            create_transfer_payload(scenario["third_owner"]["id"],
                                    policy["version"],
                                    transfer_date="2027-03-01",
                                    documents_reference="DEED-2027-0301"),
            make_homeowner_headers(scenario["second_owner"]["id"]),
        ),
        201,
    )
    assert resale["status"] == "REQUESTED"
    assert resale["transfer_fee_cents"] == 10_000
    assert resale["requested_by_owner_id"] == scenario["second_owner"]["id"]


# ==========================================================================
# Table 4 Validations / every gate seen from the accepting side of its boundary
# ==========================================================================
def test_a_closing_date_equal_to_the_clock_date_enrolls_and_then_activates(
    api, underwriting_officer_headers
):
    """A closing date exactly equal to the clock date satisfies the not-later-than
    rule, and the paid policy then clears all four activation conditions.

    PRD Section 3.3: "A `BuilderPrincipal` supplies the `builder_id` of its own
    file, the `initial_owner_id` of the buyer at closing, the home's
    `street_address` (1 to 200 characters, not blank), the home's `state_code`
    (again one of `TX`, `CO`, `AZ`, `FL`, `NC`), the `purchase_price_cents` at
    closing — a whole number of cents from 5,000,000 to 500,000,000 inclusive, that
    is, a home priced between fifty thousand and five million dollars — and the
    `closing_date` as an ISO 8601 calendar date, which may not be later than the
    logical clock's current date."

    PRD Section 3.4: "An `UnderwritingOfficer` drives `coverage_status` from
    `PENDING_ENROLLMENT` to `ACTIVE` with no request body at all, and four
    conditions must hold."

    Design: Corner/Table 4 Validations/each_gate_at_its_satisfying_boundary_lets_the_request_through
    """
    scenario = setup_approved_builder_and_owner()
    enrolled = validate_success(
        api.create_policy(
            create_policy_payload(scenario["builder"]["id"],
                                  scenario["homeowner"]["id"]),
            scenario["builder_headers"],
        ),
        201,
    )
    assert_policy(enrolled)
    assert enrolled["closing_date"] == "2026-08-15"
    assert enrolled["coverage_status"] == "PENDING_ENROLLMENT"
    assert enrolled["premium_status"] == "UNBILLED"
    assert enrolled["premium_cents"] == 363_894

    invoice_policy(enrolled["id"], invoice_reference="INV-2026-0001")
    pay_policy_premium(enrolled["id"], scenario["builder"]["id"],
                       payment_reference="ACH-0001")
    activated = validate_success(
        api.activate_policy(enrolled["id"], underwriting_officer_headers)
    )
    assert activated["coverage_status"] == "ACTIVE"
    assert activated["premium_status"] == "PAID"
    assert activated["enrollment_hold"] is False


def test_an_endorsement_starting_the_day_after_a_base_term_ends_is_accepted(
    api, underwriting_officer_headers
):
    """The BASE workmanship term ends 2027-08-14, so an endorsement opening on
    2027-08-15 merely abuts it and clears the closed-interval overlap rule.

    PRD Section 3.4: "And an endorsement may not overlap any existing term of the
    same `coverage_type` on that policy: both intervals are treated as closed on
    both ends with no buffer whatsoever, so an endorsement that merely touches an
    existing term of the same type — beginning on the very day the existing term
    ends — is a conflict, and the request is refused with
    `ERR_COVERAGE_TERM_OVERLAP`."

    PRD Section 3.4: "The new term is born with `term_kind` `ENDORSEMENT`, `status`
    `OPEN`, `consumed_limit_cents` of 0 and `remaining_limit_cents` equal to its
    `limit_cents`, and the policy's `version` advances by 1."

    Design: Corner/Table 4 Validations/each_gate_at_its_satisfying_boundary_lets_the_request_through
    """
    scenario = setup_active_policy()
    base_workmanship = scenario["workmanship_term"]
    assert base_workmanship["end_date"] == "2027-08-14"

    endorsement = validate_success(
        api.create_coverage_term(
            scenario["policy"]["id"],
            create_coverage_term_payload(coverage_type="WORKMANSHIP",
                                         start_date="2027-08-15",
                                         end_date="2028-08-14",
                                         limit_cents=1_000_000,
                                         deductible_cents=100_000),
            underwriting_officer_headers,
        ),
        201,
    )
    assert endorsement["term_kind"] == "ENDORSEMENT"
    assert endorsement["status"] == "OPEN"
    assert endorsement["consumed_limit_cents"] == 0
    assert endorsement["remaining_limit_cents"] == 1_000_000
    assert_coverage_capacity_conserved(endorsement)


def test_a_claim_on_the_first_covered_day_binds_a_term_and_lands_on_the_builder(
    api, claims_adjuster_headers
):
    """Coverage intervals are closed on both ends, so a claim reported on the very
    first covered day finds its term in force and, being well inside the
    two-year obligation period, is routed to the builder; listing it back with a
    page size of exactly 1 is the inclusive lower bound of pagination, not a
    violation.

    PRD Section 3.7: "From those, the terms whose `coverage_type` equals the
    claimed `coverage_type` and whose closed interval contains the `reported_date`
    — on or after `start_date` and on or before `end_date` — are ranked with `BASE`
    terms ahead of `ENDORSEMENT` terms, then by `start_date` ascending, then by
    `created_at` ascending, and the first is chosen."

    PRD Section 3.7: "When the `reported_date` is on or before the policy's
    `builder_obligation_end_date`, the `obligor` is `BUILDER`; when it falls after
    that date, the `obligor` is `INSURER`."

    PRD Section 2.3: "`limit` controls page size: it defaults to 10, its minimum
    accepted value is 1 and its maximum accepted value is 100."

    Design: Corner/Table 4 Validations/each_gate_at_its_satisfying_boundary_lets_the_request_through
    """
    scenario = setup_active_policy()
    structural_term = scenario["structural_term"]
    assert structural_term["start_date"] == "2026-08-15"

    filed = validate_success(
        api.create_claim(
            create_claim_payload(
                scenario["policy"]["id"], coverage_type="STRUCTURAL",
                defect_category="WATER_INTRUSION",
                claimed_amount_cents=2_187_500,
                damage_description="Slab movement reported on the enrollment date itself",
            ),
            scenario["owner_headers"],
        ),
        201,
    )
    assert filed["reported_date"] == "2026-08-15"
    assert filed["obligor"] == "BUILDER"
    assert filed["coverage_term_id"] == structural_term["id"]
    assert filed["status"] == "SUBMITTED"

    rows, meta = validate_paginated(
        api.list_claims(claims_adjuster_headers,
                        {"policy_id": scenario["policy"]["id"],
                         "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["limit"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [filed["id"]]


def test_a_transfer_dated_on_the_first_day_of_the_structural_interval_is_accepted(api):
    """The structural BASE interval opens on 2026-08-15, and a transfer dated on
    that inclusive first day is inside the window rather than elapsed.

    PRD Section 3.6: "The `transfer_date` must fall inside the closed interval of
    the policy's `BASE` term of type `STRUCTURAL` — on or after that term's
    `start_date` and on or before its `end_date` — and a date outside that window
    is refused with `ERR_COVERAGE_TERM_ELAPSED`."

    PRD Section 3.6: "A successful request creates a transfer row in `status`
    `REQUESTED` against the policy named in its `policy_id`, with
    `requested_by_owner_id` copied from the acting `X-User-ID`."

    Design: Corner/Table 4 Validations/each_gate_at_its_satisfying_boundary_lets_the_request_through
    """
    scenario = setup_active_policy()
    second_owner = create_homeowner(full_name="Ben Calloway",
                                    email="ben.calloway@example.com")
    policy = read_policy(scenario["policy"]["id"])
    assert scenario["structural_term"]["start_date"] == "2026-08-15"

    requested = validate_success(
        api.create_transfer(
            policy["id"],
            create_transfer_payload(second_owner["id"], policy["version"],
                                    transfer_date="2026-08-15",
                                    documents_reference="DEED-EDGE"),
            scenario["owner_headers"],
        ),
        201,
    )
    assert_transfer(requested)
    assert requested["status"] == "REQUESTED"
    assert requested["transfer_fee_cents"] == 7_500
    assert requested["requested_by_owner_id"] == scenario["homeowner"]["id"]
    assert read_policy(policy["id"])["pending_transfer_id"] == requested["id"]


# ==========================================================================
# Table 4 Validations / the coverage ceiling is an aggregate, not a per-draw test
# ==========================================================================
def test_two_payments_each_inside_the_limit_but_exceeding_it_together_are_refused(
    api, second_claims_adjuster_headers
):
    """Each draw is well under the 1,000,000 endorsement limit and well inside a
    reserve deliberately lifted to 900,000, yet the running sum may not pass the
    term's remaining capacity, so the second draw is refused on the coverage
    ceiling and not on the reserve ceiling.

    PRD Section 3.8: "Two ceilings then apply, in order: the amount may not exceed
    the claim's `reserve_cents`, or `ERR_PAYMENT_EXCEEDS_RESERVE`; and it may not
    exceed the `remaining_limit_cents` of the claim's coverage term, or
    `ERR_COVERAGE_LIMIT_EXCEEDED`."

    PRD Section 3.7: "`net_payable_cents` is the smaller of two figures: the
    provisional net less `betterment_cents`, and the `remaining_limit_cents` of the
    coverage term named by the claim's `coverage_term_id`."

    PRD Section 3.8: "On success the claim's `reserve_cents` becomes exactly the
    authorised `amount_cents`, and its `incurred_authorized_cents` becomes the sum
    of its existing `paid_cents`, its existing `released_cents` and that same
    authorised amount."

    Design: Corner/Table 4 Validations/two_payments_each_inside_the_limit_but_exceeding_it_together_are_refused
    """
    scenario = _endorsement_claim_scenario(limit_cents=1_000_000,
                                           claimed_amount_cents=1_200_000)
    claim = scenario["claim"]
    endorsement_id = scenario["endorsement"]["id"]
    assert claim["net_payable_cents"] == 1_000_000
    assert claim["reserve_cents"] == 1_000_000

    first_draw = pay_claim(claim["id"], 600_000)
    assert first_draw["paid_cents"] == 600_000
    assert first_draw["reserve_cents"] == 400_000
    term = read_coverage_term(endorsement_id)
    assert term["consumed_limit_cents"] == 600_000
    assert term["remaining_limit_cents"] == 400_000
    assert_coverage_capacity_conserved(term)

    # Lift the reserve above the remaining capacity so only the coverage ceiling
    # can refuse the next draw.
    adjustment = authorize_reserve(claim["id"], 900_000, entry_type="ADJUSTMENT",
                                   expected_claim_version=first_draw["version"],
                                   memo="reserve raised above the remaining capacity")
    assert adjustment["balance_after_reserve_cents"] == 900_000

    response = api.create_payment(
        claim["id"],
        payment_payload(500_000, memo="second draw beyond the remaining capacity"),
        second_claims_adjuster_headers,
    )
    validate_error(response, ApiErrorId.ERR_COVERAGE_LIMIT_EXCEEDED.value)

    unchanged = read_claim(claim["id"])
    assert unchanged["paid_cents"] == 600_000
    assert unchanged["reserve_cents"] == 900_000
    assert_claim_money_conserved(unchanged)
    still_open = read_coverage_term(endorsement_id)
    assert still_open["remaining_limit_cents"] == 400_000
    assert still_open["status"] == "OPEN"


def test_a_draw_sized_to_the_remaining_capacity_exhausts_the_term_and_closes_the_claim(
    api, second_claims_adjuster_headers
):
    """The identical-in-kind 400,000 draw consumes the last of the capacity: the
    term drives to LIMIT_EXHAUSTED and, because paid now equals net payable, the
    claim closes even though its reserve is still positive.

    PRD Section 3.8: "It closes the claim when the claim is `APPROVED` and its
    `paid_cents` after this payment equals its `net_payable_cents`, advancing
    `APPROVED → CLOSED_PAID`."

    PRD Section 3.8: "When that charge drives the term's `remaining_limit_cents`
    to exactly 0, the term transitions `OPEN → LIMIT_EXHAUSTED` and its `version`
    advances by 1"

    PRD Section 2.9: "A parallel but distinct invariant governs coverage capacity:
    a coverage term's `remaining_limit_cents` plus its `consumed_limit_cents`
    always equals its `limit_cents`."

    Design: Corner/Table 4 Validations/two_payments_each_inside_the_limit_but_exceeding_it_together_are_refused
    """
    scenario = _endorsement_claim_scenario(limit_cents=1_000_000,
                                           claimed_amount_cents=1_200_000)
    claim = scenario["claim"]
    endorsement_id = scenario["endorsement"]["id"]

    first_draw = pay_claim(claim["id"], 600_000)
    authorize_reserve(claim["id"], 900_000, entry_type="ADJUSTMENT",
                      expected_claim_version=first_draw["version"],
                      memo="reserve raised above the remaining capacity")

    final_draw = validate_success(
        api.create_payment(
            claim["id"],
            payment_payload(400_000,
                            memo="second draw sized to the remaining capacity"),
            second_claims_adjuster_headers,
        )
    )
    assert final_draw["paid_cents"] == 1_000_000
    assert final_draw["reserve_cents"] == 500_000
    assert final_draw["status"] == "CLOSED_PAID"
    assert_claim_money_conserved(final_draw)

    exhausted = read_coverage_term(endorsement_id)
    assert exhausted["consumed_limit_cents"] == 1_000_000
    assert exhausted["remaining_limit_cents"] == 0
    assert exhausted["status"] == "LIMIT_EXHAUSTED"
    assert_coverage_capacity_conserved(exhausted)
