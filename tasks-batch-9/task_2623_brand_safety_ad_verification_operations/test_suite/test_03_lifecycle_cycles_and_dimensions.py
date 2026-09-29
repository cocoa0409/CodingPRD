"""Cyclic and multi-dimensional lifecycles.

Two families of non-linear lifecycle live in this platform. The appeal
negotiation loop re-enters a state it has already occupied and is bounded by a
round counter rather than by the state itself, and the measurement batch carries
two independent status dimensions on one row, so a terminal position on the
measurement side does not freeze the money side.
"""
import pytest

from test_helpers import (
    ANALYST_REVIEWER_USER_ID,
    OFFICER_USER_ID,
    ApiErrorId,
    assert_credit_double_entry,
    assert_impression_conservation,
    assert_money_triple,
    factories,
    make_officer_headers,
    read_advertiser,
    read_appeal,
    read_batch,
    read_campaign,
    read_claim,
    read_page,
    read_publisher,
    setup_appeal_at_round,
    setup_approved_claim,
    setup_base_world,
    setup_certified_batch,
    setup_filed_appeal,
    setup_reviewed_classification,
    setup_submitted_claim,
    suspend_methodology_version,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"

#: An attested HIGH_RISK verdict: one ARMS category weighs 40 risk points, the
#: HUMAN classifier attracts no confidence inflation and the made-for-advertising
#: signals are mild, so adjusted_risk_points lands at 40.00 in HIGH_RISK.
ARMS_CLASSIFICATION = {
    "classifier_kind": "HUMAN",
    "category_codes": ["ARMS"],
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}

#: Sensor figures that clear every certification condition: coverage 0.9000 sits
#: above the 0.7 floor and the in-view claim is accepted wholesale.
CERTIFIABLE_FIGURES = {
    "measured_impressions": 100000,
    "measurable_impressions": 90000,
    "in_view_impressions": 80000,
}


def _appealable_world(api):
    """A page attested at HIGH_RISK by a reviewer distinct from its author, which
    is the only position an appeal may be filed from."""
    world = setup_base_world(api, clock=CLOCK)
    reviewed = setup_reviewed_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        decision="CONFIRM",
        reviewer_user_id=ANALYST_REVIEWER_USER_ID,
        classification_overrides=dict(ARMS_CLASSIFICATION),
    )
    assert reviewed["assigned_tier"] == "HIGH_RISK", (
        f"expected HIGH_RISK from 40 risk points, got {reviewed['assigned_tier']}"
    )
    return world, reviewed


def _decertified_batch_world(api):
    """A certified batch whose pinned VIEWABILITY version is then suspended, which
    repudiates the measurement and leaves the batch in DECERTIFIED."""
    world = setup_base_world(
        api,
        clock=CLOCK,
        campaign_overrides={"cpm_cents": 1000, "target_coverage_rate": 0.75},
        accredit=False,
    )
    batch = setup_certified_batch(api, world, index=0, **CERTIFIABLE_FIGURES)
    version = suspend_methodology_version(
        api, world["viewability_version"]["id"], audit_finding_rate=0.22
    )
    return world, batch, version


# ===========================================================================
# The appeal negotiation cycle
# ===========================================================================
def test_appeal_negotiation_cycle_re_enters_filed_and_advances_round_no(api):
    """The publisher and the officer trade two evidence rounds, so the appeal
    re-enters FILED twice and its round counter climbs to the ceiling of three.

    PRD: "The publisher answers by supplying a further evidence round, which moves the appeal `MORE_EVIDENCE_REQUIRED → FILED`, increments `round_no` by 1, replaces `evidence_note` with the new narrative, and increments the appeal's `version` by 1."

    Design: Difficulty/non_linear_state_machine/appeal_negotiation_cycle_returns_to_filed_and_caps_at_three_rounds
    """
    world, reviewed = _appealable_world(api)

    filed = setup_filed_appeal(
        api,
        world,
        classification=reviewed,
        reason_code="CONTEXT_IGNORED",
        evidence_note="Historical documentary context, not arms promotion",
    )
    appeal = filed["appeal"]
    appeal_id = appeal["id"]
    assert appeal["appeal_state"] == "FILED", (
        f"a filed appeal starts in FILED, got {appeal['appeal_state']}"
    )
    assert appeal["round_no"] == 1, (
        f"a filed appeal starts at round_no 1, got {appeal['round_no']}"
    )
    first_filed_version = appeal["version"]

    # --- first loop: FILED -> MORE_EVIDENCE_REQUIRED -> FILED ---------------
    looped = validate_success(
        api.decide_appeal(
            appeal_id,
            factories.decide_appeal_payload(
                outcome="MORE_EVIDENCE",
                decision_note="Supply the editorial standards page",
            ),
            make_officer_headers(OFFICER_USER_ID),
        ),
        200,
    )
    assert looped["appeal_state"] == "MORE_EVIDENCE_REQUIRED", (
        f"MORE_EVIDENCE moves the appeal out of FILED, got {looped['appeal_state']}"
    )
    assert looped["round_no"] == 1, (
        f"the officer's request does not open a round, round_no should stay 1, "
        f"got {looped['round_no']}"
    )

    answered = validate_success(
        api.submit_appeal_evidence(
            appeal_id,
            factories.submit_evidence_payload(
                evidence_note="Editorial standards URL supplied"
            ),
            world["publisher_headers"],
        ),
        200,
    )
    assert answered["appeal_state"] == "FILED", (
        f"the evidence submission returns the appeal to FILED, "
        f"got {answered['appeal_state']}"
    )
    assert answered["round_no"] == 2, (
        f"round_no increments to 2 on the first evidence round, got {answered['round_no']}"
    )
    assert answered["evidence_note"] == "Editorial standards URL supplied", (
        f"evidence_note must be replaced by the new narrative, "
        f"got {answered['evidence_note']!r}"
    )
    assert answered["version"] > first_filed_version, (
        f"each cycle step increments the appeal's version, got "
        f"{answered['version']} against {first_filed_version}"
    )

    # --- second loop: FILED -> MORE_EVIDENCE_REQUIRED -> FILED again --------
    looped_again = validate_success(
        api.decide_appeal(
            appeal_id,
            factories.decide_appeal_payload(
                outcome="MORE_EVIDENCE",
                decision_note="Standards page insufficient, supply crawl sample",
            ),
            make_officer_headers(OFFICER_USER_ID),
        ),
        200,
    )
    assert looped_again["appeal_state"] == "MORE_EVIDENCE_REQUIRED", (
        f"the loop is re-entered a second time, got {looped_again['appeal_state']}"
    )
    assert looped_again["round_no"] == 2, (
        f"round_no stays 2 across the officer's second request, "
        f"got {looped_again['round_no']}"
    )

    answered_again = validate_success(
        api.submit_appeal_evidence(
            appeal_id,
            factories.submit_evidence_payload(
                evidence_note="Crawl sample of 50 comparable URLs supplied"
            ),
            world["publisher_headers"],
        ),
        200,
    )
    assert answered_again["appeal_state"] == "FILED", (
        f"FILED is occupied for the third time, got {answered_again['appeal_state']}"
    )
    assert answered_again["round_no"] == 3, (
        f"round_no reaches 3 after the second evidence round, "
        f"got {answered_again['round_no']}"
    )
    assert (
        answered_again["evidence_note"] == "Crawl sample of 50 comparable URLs supplied"
    ), (
        "evidence_note must carry the latest narrative, got "
        f"{answered_again['evidence_note']!r}"
    )

    stored = read_appeal(api, appeal_id)
    assert stored["appeal_state"] == "FILED", (
        f"the stored appeal sits in FILED at round 3, got {stored['appeal_state']}"
    )
    assert stored["round_no"] == 3, (
        f"the stored round_no is 3, got {stored['round_no']}"
    )
    assert stored["revised_tier"] is None, (
        f"no tier is awarded while the negotiation is live, got {stored['revised_tier']}"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "APPEALED", (
        f"the page stays frozen at APPEALED across the cycle, "
        f"got {page['classification_state']}"
    )
    assert page["current_tier"] == "HIGH_RISK", (
        f"the disputed tier is untouched during the loop, got {page['current_tier']}"
    )


def test_more_evidence_at_round_three_is_refused_and_leaves_the_appeal_intact(api):
    """A third request for more evidence would open a fourth round, so it is
    refused and the appeal stays exactly where it stood.

    PRD: "It is only available while `round_no` is strictly below the ceiling of 3 rounds; at round 3 it answers `ERR_APPEAL_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/appeal_negotiation_cycle_returns_to_filed_and_caps_at_three_rounds
    """
    world, reviewed = _appealable_world(api)
    walked = setup_appeal_at_round(api, world, 3, classification=reviewed)
    appeal = walked["appeal"]
    appeal_id = appeal["id"]
    assert appeal["appeal_state"] == "FILED", (
        f"the negotiation leaves the appeal in FILED, got {appeal['appeal_state']}"
    )
    assert appeal["round_no"] == 3, (
        f"the appeal must stand at round_no 3 before the trigger, got {appeal['round_no']}"
    )
    version_before = appeal["version"]

    response = api.decide_appeal(
        appeal_id,
        factories.decide_appeal_payload(
            outcome="MORE_EVIDENCE", decision_note="One more round please"
        ),
        make_officer_headers(OFFICER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_ROUNDS_EXHAUSTED.value, 409)

    unchanged = read_appeal(api, appeal_id)
    assert unchanged["appeal_state"] == "FILED", (
        f"the refused decision leaves appeal_state at FILED, "
        f"got {unchanged['appeal_state']}"
    )
    assert unchanged["round_no"] == 3, (
        f"the refused decision leaves round_no at 3, got {unchanged['round_no']}"
    )
    assert unchanged["version"] == version_before, (
        f"a refused request mutates nothing, so version stays {version_before}, "
        f"got {unchanged['version']}"
    )
    assert unchanged["decided_by_user_id"] is None, (
        f"no officer is stamped by a refused decision, "
        f"got {unchanged['decided_by_user_id']}"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "APPEALED", (
        f"the page remains frozen at APPEALED, got {page['classification_state']}"
    )
    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 0, (
        f"no appeal has been decided yet, got {publisher['decided_appeal_count']}"
    )


def test_terminal_uphold_still_succeeds_from_the_same_round_three_filed_state(api):
    """From the very FILED state that refused another evidence round, the officer's
    terminal decision to uphold the classification is still available.

    PRD: "The `FILED → MORE_EVIDENCE_REQUIRED → FILED` loop is the negotiation cycle, and it is bounded at three rounds; a terminal decision, however, remains available at any round, including round 3."

    Design: Difficulty/non_linear_state_machine/appeal_negotiation_cycle_returns_to_filed_and_caps_at_three_rounds
    """
    world, reviewed = _appealable_world(api)
    walked = setup_appeal_at_round(api, world, 3, classification=reviewed)
    appeal_id = walked["appeal"]["id"]

    exhausted = api.decide_appeal(
        appeal_id,
        factories.decide_appeal_payload(
            outcome="MORE_EVIDENCE", decision_note="One more round please"
        ),
        make_officer_headers(OFFICER_USER_ID),
    )
    validate_error(exhausted, ApiErrorId.ERR_APPEAL_ROUNDS_EXHAUSTED.value, 409)

    decided = validate_success(
        api.decide_appeal(
            appeal_id,
            factories.decide_appeal_payload(
                outcome="UPHELD",
                decision_note="Original HIGH_RISK classification stands",
            ),
            make_officer_headers(OFFICER_USER_ID),
        ),
        200,
    )
    assert decided["appeal_state"] == "UPHELD", (
        f"the terminal outcome is reachable from FILED at round 3, "
        f"got {decided['appeal_state']}"
    )
    assert decided["round_no"] == 3, (
        f"a terminal decision opens no round, round_no stays 3, "
        f"got {decided['round_no']}"
    )
    assert decided["decided_by_user_id"] == OFFICER_USER_ID, (
        f"decided_by_user_id is stamped from the officer, "
        f"got {decided['decided_by_user_id']}"
    )
    assert (
        decided["decision_note"] == "Original HIGH_RISK classification stands"
    ), f"the decision_note is stored verbatim, got {decided['decision_note']!r}"
    assert decided["revised_tier"] is None, (
        f"an upheld appeal awards no revised tier, got {decided['revised_tier']}"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "HUMAN_CONFIRMED", (
        f"an upheld appeal returns the page to HUMAN_CONFIRMED, "
        f"got {page['classification_state']}"
    )
    assert page["current_tier"] == "HIGH_RISK", (
        f"the disputed tier is left exactly as it was, got {page['current_tier']}"
    )
    assert page["current_classification_id"] == reviewed["id"], (
        "current_classification_id is left exactly as it was, got "
        f"{page['current_classification_id']}"
    )
    assert page["appeal_count"] == 1, (
        f"one appeal was filed against this page, got {page['appeal_count']}"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 1, (
        f"decided_appeal_count increments on the terminal decision, "
        f"got {publisher['decided_appeal_count']}"
    )
    assert publisher["overturned_appeal_count"] == 0, (
        f"an upheld appeal is not an overturn, "
        f"got {publisher['overturned_appeal_count']}"
    )


# ===========================================================================
# The batch's two independent status dimensions
# ===========================================================================
def test_decertification_moves_the_scoring_dimension_and_leaves_settlement_unbilled(api):
    """Suspending the pinned methodology repudiates a certified batch, driving the
    measurement dimension to DECERTIFIED while the money dimension stays UNBILLED.

    PRD: "`scoring_status` tracks the measurement, `settlement_status` tracks the money, and neither constrains the other's transitions."

    Design: Difficulty/non_linear_state_machine/batch_scoring_and_settlement_dimensions_advance_independently
    """
    world = setup_base_world(
        api,
        clock=CLOCK,
        campaign_overrides={"cpm_cents": 1000, "target_coverage_rate": 0.75},
        accredit=False,
    )
    batch = setup_certified_batch(api, world, index=0, **CERTIFIABLE_FIGURES)

    assert batch["scoring_status"] == "CERTIFIED", (
        f"the four certification conditions all hold, so the batch certifies, "
        f"got {batch['scoring_status']}"
    )
    assert batch["settlement_status"] == "UNBILLED", (
        f"certification touches no money, settlement_status stays UNBILLED, "
        f"got {batch['settlement_status']}"
    )
    assert batch["coverage_rate"] == pytest.approx(0.9, abs=0.0001), (
        f"coverage_rate is 90000/100000, got {batch['coverage_rate']}"
    )
    assert batch["qualified_in_view_impressions"] == 80000, (
        f"the in-view claim is accepted wholesale, expected 80000, "
        f"got {batch['qualified_in_view_impressions']}"
    )
    assert_impression_conservation(batch)

    campaign_before = read_campaign(api, world["campaign"]["id"])
    assert campaign_before["coverage_status"] == "ON_TARGET", (
        f"90000/100000 clears the 0.75 target, got {campaign_before['coverage_status']}"
    )
    assert campaign_before["certified_measured_impressions"] == 100000, (
        f"certification adds the measured impressions, got "
        f"{campaign_before['certified_measured_impressions']}"
    )

    version = suspend_methodology_version(
        api, world["viewability_version"]["id"], audit_finding_rate=0.22
    )
    assert version["accreditation_status"] == "SUSPENDED", (
        f"a DEFICIENT conclusion suspends the version, "
        f"got {version['accreditation_status']}"
    )
    assert version["decertified_batch_count"] == 1, (
        f"exactly one certified batch was repudiated, "
        f"got {version['decertified_batch_count']}"
    )

    repudiated = read_batch(api, batch["id"])
    assert repudiated["scoring_status"] == "DECERTIFIED", (
        f"the measurement dimension reaches its terminal position, "
        f"got {repudiated['scoring_status']}"
    )
    assert repudiated["settlement_status"] == "UNBILLED", (
        "the settlement dimension did not move with it and must still read "
        f"UNBILLED, got {repudiated['settlement_status']}"
    )
    assert repudiated["version"] > batch["version"], (
        f"the cascade increments the batch version, got {repudiated['version']} "
        f"against {batch['version']}"
    )
    assert_impression_conservation(repudiated)

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["certified_batch_count"] == 0, (
        f"the publisher's certified_batch_count is reversed, "
        f"got {publisher['certified_batch_count']}"
    )

    campaign_after = read_campaign(api, world["campaign"]["id"])
    assert campaign_after["certified_measured_impressions"] == 0, (
        f"the decertified batch is removed from the campaign counters, got "
        f"{campaign_after['certified_measured_impressions']}"
    )
    assert campaign_after["certified_measurable_impressions"] == 0, (
        f"both certified counters are reversed, got "
        f"{campaign_after['certified_measurable_impressions']}"
    )
    assert campaign_after["coverage_status"] == "UNKNOWN", (
        f"with no certified measured impressions the status is UNKNOWN, "
        f"got {campaign_after['coverage_status']}"
    )
    assert campaign_after["status"] == "ACTIVE", (
        "the remediation hop is conditional on BELOW_TARGET, so an UNKNOWN "
        f"campaign stays ACTIVE, got {campaign_after['status']}"
    )


def test_decertified_batch_is_still_claimable_and_moves_settlement_to_claimed(api):
    """A batch sitting in the terminal DECERTIFIED measurement position is exactly
    what makes it claimable, so its money dimension advances UNBILLED to CLAIMED.

    PRD: "A decertified batch has one further consequence worth stating here even though it belongs to the money story: because the measurement itself has been repudiated, the batch becomes claimable — its `settlement_status` may now move from `UNBILLED` to `CLAIMED`."

    Design: Difficulty/non_linear_state_machine/batch_scoring_and_settlement_dimensions_advance_independently
    """
    world, batch, _version = _decertified_batch_world(api)

    claim = setup_submitted_claim(api, world, batch_ids=[batch["id"]])
    assert claim["claim_state"] == "SUBMITTED", (
        f"an accepted claim stands at SUBMITTED, got {claim['claim_state']}"
    )
    assert claim["claimed_impressions"] == 100000, (
        "the gross basis credits the entire measured delivery of the defective "
        f"batch, expected 100000, got {claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 100000, (
        f"100000 impressions at a cpm_cents of 1000 price at 100000 cents, "
        f"got {claim['provisional_credit_cents']}"
    )
    assert claim["credited_impressions"] is None, (
        f"the net basis figures exist only from approval onward, "
        f"got {claim['credited_impressions']}"
    )
    assert claim["net_credit_cents"] is None, (
        f"net_credit_cents is null before approval, got {claim['net_credit_cents']}"
    )

    cited = read_batch(api, batch["id"])
    assert cited["settlement_status"] == "CLAIMED", (
        f"the money dimension advances on its own, got {cited['settlement_status']}"
    )
    assert cited["scoring_status"] == "DECERTIFIED", (
        "the terminal measurement position is unaffected by the money move, "
        f"got {cited['scoring_status']}"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 1, (
        f"open_claim_count increments once per claim, got {campaign['open_claim_count']}"
    )


def test_decertified_batch_can_still_be_credited_by_an_approved_claim(api):
    """The claim over the repudiated batch is reviewed and approved, so the money
    dimension reaches CREDITED with the measurement dimension still DECERTIFIED.

    PRD: "A batch that has already been claimed may still be decertified afterwards, and a decertified batch may still be credited."

    Design: Difficulty/non_linear_state_machine/batch_scoring_and_settlement_dimensions_advance_independently
    """
    world, batch, _version = _decertified_batch_world(api)

    approved = setup_approved_claim(api, world, batch_ids=[batch["id"]])
    assert approved["claim_state"] == "APPROVED", (
        f"approval is the only operation that moves money, "
        f"got {approved['claim_state']}"
    )
    assert approved["credited_impressions"] == 10000, (
        "the net basis credits the invalid traffic plus the non-viewable "
        "shortfall of 90000 less 80000, expected 10000, got "
        f"{approved['credited_impressions']}"
    )
    assert_money_triple(approved, gross=10000, rate=0.15, fee=1500, net=8500)

    credited = read_batch(api, batch["id"])
    assert credited["settlement_status"] == "CREDITED", (
        f"the money dimension reaches CREDITED, got {credited['settlement_status']}"
    )
    assert credited["scoring_status"] == "DECERTIFIED", (
        "the measurement dimension never left its terminal position, got "
        f"{credited['scoring_status']}"
    )

    advertiser = read_advertiser(api, world["advertiser"]["id"])
    publisher = read_publisher(api, world["publisher"]["id"])
    assert_credit_double_entry(advertiser, publisher, 8500)
    assert advertiser["settled_claim_count"] == 1, (
        f"settled_claim_count increments on approval, "
        f"got {advertiser['settled_claim_count']}"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 0, (
        f"open_claim_count is decremented at approval, "
        f"got {campaign['open_claim_count']}"
    )

    stored_claim = read_claim(api, approved["id"])
    assert stored_claim["claim_state"] == "APPROVED", (
        f"the settled claim reads back as APPROVED, got {stored_claim['claim_state']}"
    )
