"""Formulas whose inputs interact rather than simply add.

Three shapes appear here: nested caps that saturate a product, a rounding order
that is load-bearing enough to move a percentage by seven points, and a quorum
target that the very vote being measured against it recomputes.
"""

from test_helpers import (
    api_client,
    assertions,
    factories,
    fixtures,
    validate_success,
)


# ---------------------------------------------------------------------------
# Nested caps: volume factor saturation inside an index that also saturates
# ---------------------------------------------------------------------------


HARD_STOP_OVERRIDES = {
    "name": "Concentrated KCl hard stop",
    "severity_tier": "TIER_1_HARD_STOP",
    "hard_stop_justification": "Fatal dysrhythmia risk documented by ISMP",
    "override_reason_codes": ["PHARMACY_VERIFIED", "CENTRAL_LINE_CONFIRMED"],
    "firing_criteria": {
        "trigger_event": "NEW_MEDICATION_ORDER",
        "expression": "order(potassium_chloride) AND concentration > 10 mEq per 100 mL",
    },
}

HARD_STOP_REQUEST_OVERRIDES = {
    "title": "Concentrated potassium hard stop",
    "request_type": "ALERT",
    "clinical_domain": "CRITICAL_CARE",
    "urgency": "SAFETY_URGENT",
    "evidence_grade": "A",
    "patient_safety_flag": True,
    "evidence_citations": [
        factories.build_citation("ISMP alert 2025-04", True),
        factories.build_citation("NEJM 2025;392:88", True),
    ],
}


def _saturating_window(committee):
    """A TIER_1 alert with 150 firings in four days, 90 of them overrides."""
    fixtures.reset_clock()
    scenario = fixtures.setup_active_alert(
        committee,
        request_overrides=HARD_STOP_REQUEST_OVERRIDES,
        alert_overrides=HARD_STOP_OVERRIDES,
    )
    alert_id = scenario["alert"]["id"]
    scenario["ingest"] = fixtures.ingest_firings(
        alert_id,
        "2026-09-01T00:00:00Z",
        fire_count=150,
        override_count=90,
        distinct_clinician_count=8,
        interval_seconds=600,
        override_reason_code="PHARMACY_VERIFIED",
    )
    window = fixtures.open_window(
        committee, alert_id, "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    scenario["window_id"] = window["id"]
    return scenario


def test_volume_factor_cap_and_index_cap_both_clip_the_fire_weighted_product(committee):
    """150 firings clip the volume factor to 2.0 and the product to 100.00.

    "Its `volume_factor` is `fire_count` divided by an expected 50 firings per
    window, rounded half-up to four decimal places, then capped at 2.0."
    "`burden_index` is then `override_rate` multiplied by the tier multiplier
    multiplied by `volume_factor` multiplied by 100, rounded half-up to two
    decimal places, and finally capped at 100.00."

    Design: Difficulty/combinatorial_formula/combinatorial_burden_index_volume_cap_and_tier_multiplier_interaction
    """
    scenario = _saturating_window(committee)
    alert_id = scenario["alert"]["id"]
    assert scenario["ingest"]["last_fired_at"] == "2026-09-02T00:50:00Z"

    closed = validate_success(
        api_client.close_burden_window(
            alert_id,
            scenario["window_id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            committee["chair_headers"],
        )
    )

    assert closed["fire_count"] == 150
    assert closed["override_count"] == 90
    assertions.assert_numeric_equals(closed["override_rate"], 0.6000, 4)
    # round(150 / 50, 4) is 3.0000 before the cap applies.
    assertions.assert_numeric_equals(closed["volume_factor"], 2.0, 4)
    # 0.6000 * 1.6 * 2.0 * 100 is 192.00 before the cap applies.
    assertions.assert_numeric_equals(closed["burden_index"], 100.00, 2)
    assertions.assert_two_decimal_places(closed["burden_index"])


def test_clinician_weighted_branch_of_the_same_window_is_uncapped(committee):
    """The people-counting branch lands at 64.00 with no cap engaged.

    "The tier multiplier comes from `severity_tier_snapshot`: 1.6 for
    `TIER_1_HARD_STOP`, 1.0 for `TIER_2_INTERRUPTIVE`, 0.4 for
    `TIER_3_PASSIVE`." "`burden_index_clinician_weighted` is that rate
    multiplied by the same tier multiplier multiplied by that volume factor
    multiplied by 100, rounded half-up to two decimal places and capped at
    100.00."

    Design: Difficulty/combinatorial_formula/combinatorial_burden_index_volume_cap_and_tier_multiplier_interaction
    """
    scenario = _saturating_window(committee)
    alert_id = scenario["alert"]["id"]

    closed = validate_success(
        api_client.close_burden_window(
            alert_id,
            scenario["window_id"],
            factories.build_close_window_payload(closure_reason="MANUAL_CLOSE"),
            committee["chair_headers"],
        )
    )

    assert closed["severity_tier_snapshot"] == "TIER_1_HARD_STOP"
    assert closed["distinct_fired_clinician_count"] == 8
    assert closed["distinct_overriding_clinician_count"] == 8
    # 1.0000 * 1.6 * 0.4000 * 100 needs no clipping at all.
    assertions.assert_numeric_equals(closed["burden_index_clinician_weighted"], 64.00, 2)
    assertions.assert_two_decimal_places(closed["burden_index_clinician_weighted"])
    assert closed["burden_classification"] == "LOW_VALUE"
    assertions.assert_classification_from_index(closed)


# ---------------------------------------------------------------------------
# Rounding order: mean of rounded rates versus one rounding of a pooled ratio
# ---------------------------------------------------------------------------


LOPSIDED_UNITS = [
    factories.build_unit_observation("ICU", 30, 20, 3),
    factories.build_unit_observation("WARD", 970, 490, 27),
    factories.build_unit_observation("CLIN", 0, 0, 0),
]


def test_per_protocol_averages_rates_each_rounded_to_four_places(committee):
    """Two lopsided units average to 58.60 as one-vote-per-unit rates.

    "For each included row it divides `adherent_orders` by `eligible_orders`
    and rounds that rate half-up to four decimal places; it sums those per-unit
    rates and divides the sum by `included_unit_count` to obtain an unweighted
    mean; it multiplies that mean by 100 and rounds half-up to two decimal
    places". "A unit whose `eligible_orders` is 0 contributed no denominator
    and is **excluded** from the adherence arithmetic".

    Design: Difficulty/combinatorial_formula/combinatorial_adherence_rounding_order_per_unit_mean_versus_pooled_ratio
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_published_order_set(committee)

    created = validate_success(
        api_client.create_adherence_measurement(
            scenario["order_set"]["id"],
            factories.build_adherence_measurement_payload(
                "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z", LOPSIDED_UNITS
            ),
            committee["chair_headers"],
        ),
        201,
    )

    # mean of the 4dp rates 0.6667 (20/30) and 0.5052 (490/970)
    assertions.assert_numeric_equals(created["adherence_pct_per_protocol"], 58.60, 2)
    assertions.assert_two_decimal_places(created["adherence_pct_per_protocol"])
    assert created["included_unit_count"] == 2
    assert created["excluded_unit_count"] == 1
    assert created["measurement_state"] == "PROVISIONAL"
    assert created["adherence_pct_intention_to_treat"] is None
    assert created["unintended_event_rate_per_100"] is None
    # every row feeds the raw event count, excluded rows included
    assert created["unintended_event_count"] == 30


def test_intention_to_treat_pools_raw_totals_and_rounds_once(committee):
    """The identical array pools to 51.00, 7.60 points below per-protocol.

    "it sums `adherent_orders` over the included rows, sums `eligible_orders`
    over the included rows, divides the first total by the second, multiplies
    by 100, rounds half-up to two decimal places". "the governed order set's
    `latest_adherence_pct` is set to this measurement's
    `adherence_pct_intention_to_treat`".

    Design: Difficulty/combinatorial_formula/combinatorial_adherence_rounding_order_per_unit_mean_versus_pooled_ratio
    """
    fixtures.reset_clock()
    scenario = fixtures.setup_published_order_set(committee)
    measurement = fixtures.create_measurement(
        committee,
        scenario["order_set"]["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        LOPSIDED_UNITS,
    )

    finalized = validate_success(
        api_client.finalize_adherence_measurement(
            measurement["id"],
            factories.build_finalize_measurement_payload(
                "REVISE", finalization_note="Below floor; revise content"
            ),
            committee["chair_headers"],
        )
    )

    # pooled 510 / 1000, rounded once
    assertions.assert_numeric_equals(finalized["adherence_pct_intention_to_treat"], 51.00, 2)
    assertions.assert_two_decimal_places(finalized["adherence_pct_intention_to_treat"])
    # 100 * 30 / 1000, pooled and never averaged
    assertions.assert_numeric_equals(finalized["unintended_event_rate_per_100"], 3.00, 2)
    # the creation-time figure is not rewritten by finalization
    assertions.assert_numeric_equals(finalized["adherence_pct_per_protocol"], 58.60, 2)
    assert finalized["measurement_state"] == "FINALIZED"
    assert finalized["verdict"] == "REVISE"

    order_set = fixtures.read_order_set(committee, scenario["order_set"]["id"])
    assertions.assert_numeric_equals(order_set["latest_adherence_pct"], 51.00, 2)


# ---------------------------------------------------------------------------
# Self-referential quorum: the cast being measured moves its own target
# ---------------------------------------------------------------------------


def _order_set_with_three_peer_assignments(committee):
    """A STANDARD build in PEER_REVIEW with three outstanding peer assignments."""
    fixtures.reset_clock()
    scenario = fixtures.setup_order_set_in_peer_review(committee)
    order_set_id = scenario["order_set"]["id"]
    scenario["assignments"] = [
        fixtures.assign_reviewer(
            committee, peer["id"], "PEER_REVIEW", order_set_id=order_set_id
        )
        for peer in committee["peers"]
    ]
    return scenario


def test_evidence_concern_on_the_measured_cast_raises_its_own_vote_target(committee):
    """Two of two approvals stop short because the second flags a concern.

    "Step three counts the assignments on this artifact and this stage that are
    in state `CAST` with `evidence_concern` true, *including the vote being
    cast in this very request*. Step four sets the required vote count to the
    base plus 1 when that concern count is at least 1, plus nothing when it is
    0, and then caps the result at 4."

    Design: Difficulty/combinatorial_formula/combinatorial_quorum_required_votes_pinned_evaluation_order_with_concern_bump
    """
    scenario = _order_set_with_three_peer_assignments(committee)
    order_set_id = scenario["order_set"]["id"]
    assert scenario["order_set"]["peer_required_votes"] == 2
    assert scenario["order_set"]["risk_class"] == "STANDARD"

    fixtures.cast_vote(
        committee,
        scenario["assignments"][0]["id"],
        committee["peer_headers"][0],
        "APPROVE",
        evidence_concern=False,
    )

    validate_success(
        api_client.cast_review_vote(
            scenario["assignments"][1]["id"],
            factories.build_cast_payload(
                "APPROVE", evidence_concern=True, comment="Citation 2 is a preprint"
            ),
            committee["peer_headers"][1],
        )
    )

    order_set = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_peer_stage_counters(order_set, 3, 2, 1.0000)
    assertions.assert_order_set_states(order_set, "PEER_REVIEW", "UNPUBLISHED")


def test_third_approval_meets_the_raised_target_and_seeds_a_clean_stage(committee):
    """The third approval clears the bumped quorum and reseeds the next stage.

    "When the peer stage reaches quorum the order set advances `PEER_REVIEW →
    SPECIALTY_APPROVAL` and `specialty_required_votes` is seeded by re-running
    the same evaluation for the specialty stage."

    Design: Difficulty/combinatorial_formula/combinatorial_quorum_required_votes_pinned_evaluation_order_with_concern_bump
    """
    scenario = _order_set_with_three_peer_assignments(committee)
    order_set_id = scenario["order_set"]["id"]

    fixtures.cast_vote(
        committee,
        scenario["assignments"][0]["id"],
        committee["peer_headers"][0],
        "APPROVE",
        evidence_concern=False,
    )
    fixtures.cast_vote(
        committee,
        scenario["assignments"][1]["id"],
        committee["peer_headers"][1],
        "APPROVE",
        evidence_concern=True,
    )

    third = validate_success(
        api_client.cast_review_vote(
            scenario["assignments"][2]["id"],
            factories.build_cast_payload("APPROVE", evidence_concern=False),
            committee["peer_headers"][2],
        )
    )
    assert third["state"] == "CAST"

    order_set = fixtures.read_order_set(committee, order_set_id)
    assertions.assert_peer_stage_counters(order_set, 3, 3, 1.0000)
    assertions.assert_order_set_states(order_set, "SPECIALTY_APPROVAL", "UNPUBLISHED")
    # a fresh stage carries no concern from the stage that just closed
    assertions.assert_specialty_stage_counters(order_set, 2, 0, None)
