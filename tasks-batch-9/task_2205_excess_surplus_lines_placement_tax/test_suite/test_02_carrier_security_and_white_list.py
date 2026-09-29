"""Market security reviews -- scoring, the branching decision and the cascade
onto state white lists -- plus the white list's own capital and interval gates.
"""

from test_helpers import (
    ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM,
    ERR_CONDITIONS_NOTE_REQUIRED,
    ERR_DECISION_SCORE_MISMATCH,
    ERR_ELIGIBILITY_WINDOW_CONFLICT,
    ERR_REVIEW_ALREADY_OPEN,
    ERR_STALE_CARRIER_VERSION,
    COMPLIANCE_OFFICER_ANDERS,
    COMPLIANCE_OFFICER_ANDERS_ID,
    PLATFORM_ADMIN,
    STATE_REGULATOR_CA,
    STATE_REGULATOR_NV,
    STATE_REGULATOR_TX,
    assert_common_fields,
    carrier_eligibility_payload,
    review_decision_payload,
    validate_success,
    validate_error,
)


def _decide(world, review, carrier, decision, **extra):
    """Drive the decision endpoint with the carrier's current version."""
    payload = review_decision_payload(decision, carrier["version"], **extra)
    return world.api.decide_security_review(review["id"], payload, COMPLIANCE_OFFICER_ANDERS)


def test_an_unrated_carrier_scores_forty_five_and_only_decline_is_accepted(configured_world):
    """A carrier with no A.M. Best rating lands below the conditional floor.

    PRD 3.2: "**Rating points** come from a fixed table: 40 for `A_PLUS_PLUS`,
    35 for `A_PLUS`, 30 for `A`, 25 for `A_MINUS`, 15 for `B_PLUS_PLUS`, 10 for
    `B_PLUS`, and 0 for `NR`."

    Design: Corner/calculations/unrated_carrier_scores_forty_five_and_only_decline_is_accepted
    """
    world = configured_world
    carrier = world.create_carrier(
        naic_number="22222",
        legal_name="Meridian Indemnity Company",
        domicile_type="US_STATE",
        capital_surplus_cents=1_600_000_000,
        am_best_rating="NR",
        trust_fund_cents=0,
        naic_quarterly_listing=False,
    )
    review = world.open_review(carrier)
    started = world.start_review(review)

    # 0 rating + 30 capital + 15 domiciliary trust + 0 listing.
    assert started["score"] == 45
    assert started["variant_applied"] == "INITIAL_REVIEW"

    validate_error(
        _decide(world, review, carrier, "CONDITION", conditions_note="Watch list"),
        ERR_DECISION_SCORE_MISMATCH,
        422,
    )

    declined = validate_success(_decide(world, review, carrier, "DECLINE"), 200)
    assert declined["status"] == "DECLINED"
    assert declined["score"] == 45
    assert declined["rating_at_review"] == "NR"
    assert declined["capital_surplus_at_review_cents"] == 1_600_000_000
    assert world.get_carrier(carrier["id"])["security_status"] == "DECLINED"


def test_a_conditional_decision_without_a_conditions_note_is_refused(configured_world):
    """A mid-band score may be conditioned, but only with a written condition.

    PRD 3.2: "`UNDER_REVIEW → CONDITIONAL` additionally requires the supplied
    `conditions_note` to be a non-empty string, else
    `ERR_CONDITIONS_NOTE_REQUIRED`; it stores that note on the review and sets
    the carrier's `security_status` to `CONDITIONAL`."

    Design: Corner/errors/a_conditional_decision_without_a_conditions_note_is_refused
    """
    world = configured_world
    carrier = world.create_carrier(
        naic_number="44444",
        legal_name="Borderline Mutual Specialty",
        domicile_type="US_STATE",
        capital_surplus_cents=5_000_000_000,
        am_best_rating="NR",
        trust_fund_cents=0,
        naic_quarterly_listing=True,
    )
    review = world.open_review(carrier)
    started = world.start_review(review)

    # 0 rating + 40 capital + 15 domiciliary trust + 5 listing.
    assert started["score"] == 60

    validate_error(
        _decide(world, review, carrier, "CONDITION"),
        ERR_CONDITIONS_NOTE_REQUIRED,
        422,
    )
    assert world.get_carrier(carrier["id"])["security_status"] == "UNREVIEWED"

    decided = validate_success(
        _decide(
            world,
            review,
            carrier,
            "CONDITION",
            conditions_note="Quarterly financial statements required",
        ),
        200,
    )
    assert decided["status"] == "CONDITIONAL"
    assert decided["conditions_note"] == "Quarterly financial statements required"
    assert decided["reviewer_user_id"] == COMPLIANCE_OFFICER_ANDERS_ID
    assert world.get_carrier(carrier["id"])["security_status"] == "CONDITIONAL"


def test_opening_a_second_security_review_while_one_is_under_review_is_refused(
    configured_world,
):
    """A carrier may collect many review records but only one may be open.

    PRD 3.2: "Two preconditions guard it: no other review of the same carrier
    may already be `UNDER_REVIEW`, else `ERR_REVIEW_ALREADY_OPEN`, and the
    carrier must have a `capital_surplus_cents` value on record."

    Design: Corner/errors/opening_a_second_security_review_while_one_is_under_review_is_refused
    """
    world = configured_world
    carrier = world.create_carrier(naic_number="12345")
    first = world.open_review(carrier)
    world.start_review(first)

    second = validate_success(
        world.api.create_security_review(carrier["id"], COMPLIANCE_OFFICER_ANDERS), 201
    )
    assert second["status"] == "DRAFT"

    validate_error(
        world.api.start_security_review(second["id"], COMPLIANCE_OFFICER_ANDERS),
        ERR_REVIEW_ALREADY_OPEN,
        409,
    )

    listed = validate_success(
        world.api.list_security_reviews(carrier["id"], COMPLIANCE_OFFICER_ANDERS), 200
    )
    assert len(listed) == 2

    # Closing the first review frees the slot.
    validate_success(_decide(world, first, carrier, "APPROVE"), 200)
    reopened = validate_success(
        world.api.start_security_review(second["id"], COMPLIANCE_OFFICER_ANDERS), 200
    )
    assert reopened["status"] == "UNDER_REVIEW"


def test_capital_tier_boundaries_step_the_score_exactly_at_the_declared_cents(
    configured_world,
):
    """One cent below a tier floor drops the carrier to the tier beneath it.

    PRD 3.2: "**Capital points** come from three tier floors, each comparison
    being "at or above": a carrier holding fifty million dollars or more of
    capital and surplus — that is, at least 5,000,000,000 cents — earns 40
    points; one holding at least fifteen million dollars, or 1,500,000,000
    cents, earns 30; one holding at least five million dollars, or 500,000,000
    cents, earns 20; and anything below the lowest floor earns the floor
    allowance of 5 points."

    Design: Corner/cross_cutting_complexity_layers/capital_tier_boundaries_step_the_score_exactly_at_the_declared_cents
    """
    world = configured_world
    # Rating A (30) + domiciliary trust (15) + quarterly listing (5) = 50 base,
    # so the whole spread below is attributable to the capital tier alone.
    probes = [
        ("50001", 5_000_000_000, 90),
        ("50002", 4_999_999_999, 80),
        ("50003", 1_500_000_000, 80),
        ("50004", 500_000_000, 70),
        ("50005", 499_999_999, 55),
    ]
    reviews = {}
    for naic, capital, expected_score in probes:
        carrier = world.create_carrier(
            naic_number=naic,
            legal_name=f"Tier Probe {naic} Insurance Company",
            domicile_type="US_STATE",
            capital_surplus_cents=capital,
            am_best_rating="A",
            trust_fund_cents=0,
            naic_quarterly_listing=True,
        )
        review = world.open_review(carrier)
        started = world.start_review(review)
        assert started["score"] == expected_score, f"NAIC {naic} at {capital} cents"
        reviews[naic] = (review, carrier)

    # Seventy is approvable; the floor-allowance carrier is not.
    review, carrier = reviews["50004"]
    approved = validate_success(_decide(world, review, carrier, "APPROVE"), 200)
    assert approved["status"] == "APPROVED"

    review, carrier = reviews["50005"]
    validate_error(
        _decide(world, review, carrier, "APPROVE"), ERR_DECISION_SCORE_MISMATCH, 422
    )


def test_a_security_decision_pinning_amended_financials_is_rejected_as_stale(
    configured_world,
):
    """An administrator's amendment invalidates the reviewer's loaded view.

    PRD 2.10: "Deciding a market security review requires
    `expected_carrier_version`, matching the reviewed carrier's current
    `version`. A mismatch is rejected with `ERR_STALE_CARRIER_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/a_security_decision_pinning_amended_financials_is_rejected_as_stale
    """
    world = configured_world
    carrier = world.create_carrier(naic_number="12345")
    stale_version = carrier["version"]
    review = world.open_review(carrier)
    started = world.start_review(review)

    amended = validate_success(
        world.api.patch_carrier(
            carrier["id"],
            {"am_best_rating": "A_MINUS", "capital_surplus_cents": 1_600_000_000},
            PLATFORM_ADMIN,
        ),
        200,
    )
    assert amended["version"] == stale_version + 1
    assert amended["security_status"] == "UNREVIEWED"

    validate_error(
        world.api.decide_security_review(
            review["id"],
            review_decision_payload("APPROVE", stale_version),
            COMPLIANCE_OFFICER_ANDERS,
        ),
        ERR_STALE_CARRIER_VERSION,
        412,
    )

    # Nothing was pinned by the refused decision.
    unchanged = validate_success(
        world.api.list_security_reviews(carrier["id"], COMPLIANCE_OFFICER_ANDERS), 200
    )[0]
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["rating_at_review"] is None
    assert unchanged["capital_surplus_at_review_cents"] is None
    assert unchanged["reviewer_user_id"] is None
    assert unchanged["version"] == started["version"]
    assert world.get_carrier(carrier["id"])["security_status"] == "UNREVIEWED"

    # Re-reading the carrier and retrying pins the amended figures.
    decided = validate_success(
        world.api.decide_security_review(
            review["id"],
            review_decision_payload("APPROVE", amended["version"]),
            COMPLIANCE_OFFICER_ANDERS,
        ),
        200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["rating_at_review"] == "A_MINUS"
    assert decided["capital_surplus_at_review_cents"] == 1_600_000_000


def test_white_listing_a_carrier_below_the_state_capital_minimum_is_refused(
    configured_world,
):
    """The same carrier is listable in one state and not in another.

    PRD 3.2: "Two gates apply: the carrier's `capital_surplus_cents` must be at
    or above the state's `min_carrier_capital_surplus_cents`, else
    `ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM`; and the new window must not
    collide with an existing window on the same carrier-and-state pair under the
    closed-interval-plus-thirty-day-cooling-off semantics of §2.11, else
    `ERR_ELIGIBILITY_WINDOW_CONFLICT`."

    Design: Corner/endpoints/white_listing_a_carrier_below_the_state_capital_minimum_is_refused
    """
    world = configured_world
    carrier = world.create_carrier(
        naic_number="33333",
        legal_name="Thin Capital Specialty Company",
        capital_surplus_cents=1_000_000_000,
    )
    world.review_carrier("APPROVE", carrier=carrier)

    validate_error(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(carrier["id"], world.program_id("TX")),
            STATE_REGULATOR_TX,
        ),
        ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM,
        409,
    )

    listed = validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(carrier["id"], world.program_id("NV")),
            STATE_REGULATOR_NV,
        ),
        201,
    )
    assert listed["listing_status"] == "WHITE_LISTED"
    assert listed["state_program_id"] == world.program_id("NV")


def test_recertification_scores_lower_than_an_initial_review_on_identical_financials(
    configured_world,
):
    """Two carriers with the same profile score differently by variant alone.

    PRD 3.2: "Under the `INITIAL_REVIEW` variant the `score` is that base figure
    exactly; no history is consulted."

    Design: Difficulty/dual_variant_calc/market_security_score_initial_versus_recertification_diverge
    """
    world = configured_world
    atlas = world.create_carrier(
        naic_number="12345",
        legal_name="Atlas Specialty Insurance Company",
        capital_surplus_cents=6_000_000_000,
        am_best_rating="A_PLUS",
    )
    first = world.open_review(atlas)
    first_started = world.start_review(first)
    assert first_started["variant_applied"] == "INITIAL_REVIEW"
    assert first_started["score"] == 95

    first_decided = validate_success(_decide(world, first, atlas, "APPROVE"), 200)
    assert first_decided["status"] == "APPROVED"
    assert first_decided["rating_at_review"] == "A_PLUS"
    assert first_decided["capital_surplus_at_review_cents"] == 6_000_000_000

    atlas = validate_success(
        world.api.patch_carrier(
            atlas["id"],
            {"am_best_rating": "A_MINUS", "capital_surplus_cents": 1_600_000_000},
            PLATFORM_ADMIN,
        ),
        200,
    )

    borealis = world.create_carrier(
        naic_number="67890",
        legal_name="Borealis Specialty Insurance Company",
        capital_surplus_cents=1_600_000_000,
        am_best_rating="A_MINUS",
        domicile_type="US_STATE",
        naic_quarterly_listing=True,
    )
    borealis_review = world.open_review(borealis)
    borealis_started = world.start_review(borealis_review)
    assert borealis_started["variant_applied"] == "INITIAL_REVIEW"
    assert borealis_started["score"] == 75

    second = world.open_review(atlas)
    second_started = world.start_review(second)
    assert second_started["variant_applied"] == "RECERTIFICATION"
    # Base 75, less twice the 20-point subscore drift from 75 down to 55.
    assert second_started["score"] == 35


def test_the_recertification_drift_penalty_changes_which_decision_is_legal(
    configured_world,
):
    """The identical financial profile is approvable on first review and not on
    recertification.

    PRD 3.2: "The drift penalty is the amount by which the prior subscore
    exceeds the current subscore — zero if the current subscore is equal or
    higher — multiplied by two."

    Design: Difficulty/dual_variant_calc/market_security_score_initial_versus_recertification_diverge
    """
    world = configured_world
    atlas = world.create_carrier(
        naic_number="12345",
        legal_name="Atlas Specialty Insurance Company",
        capital_surplus_cents=6_000_000_000,
        am_best_rating="A_PLUS",
    )
    world.review_carrier("APPROVE", carrier=atlas)
    atlas = validate_success(
        world.api.patch_carrier(
            atlas["id"],
            {"am_best_rating": "A_MINUS", "capital_surplus_cents": 1_600_000_000},
            PLATFORM_ADMIN,
        ),
        200,
    )

    second = world.open_review(atlas)
    world.start_review(second)
    validate_error(
        _decide(world, second, atlas, "APPROVE"), ERR_DECISION_SCORE_MISMATCH, 422
    )

    borealis = world.create_carrier(
        naic_number="67890",
        legal_name="Borealis Specialty Insurance Company",
        capital_surplus_cents=1_600_000_000,
        am_best_rating="A_MINUS",
    )
    borealis_review = world.open_review(borealis)
    world.start_review(borealis_review)
    approved = validate_success(_decide(world, borealis_review, borealis, "APPROVE"), 200)
    assert approved["status"] == "APPROVED"
    assert world.get_carrier(borealis["id"])["security_status"] == "APPROVED"


def test_the_decline_branch_strips_every_white_list_entry_the_carrier_holds(
    configured_world,
):
    """Declining reaches past the review and the carrier into the state lists.

    PRD 3.2: "`UNDER_REVIEW → DECLINED` sets the carrier's `security_status` to
    `DECLINED` and then, as a consequence of that carrier-level write, strikes
    the carrier from every state list it appears on: each white-list entry of
    the carrier whose `listing_status` is `WHITE_LISTED` moves to `REMOVED`, has
    its `removed_on` set to the current logical clock, and has its `version`
    incremented, processed in ascending order of the `state_code` of the state
    program each entry points at."

    Design: Difficulty/non_linear_state_machine/market_security_review_branches_decline_and_condition_carry_different_side_effect_sets
    """
    world = configured_world
    meridian = world.create_carrier(
        naic_number="22222",
        legal_name="Meridian Indemnity Company",
        domicile_type="US_STATE",
        capital_surplus_cents=1_600_000_000,
        am_best_rating="NR",
        trust_fund_cents=0,
        naic_quarterly_listing=False,
    )
    tx_entry = validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(meridian["id"], world.program_id("TX")),
            STATE_REGULATOR_TX,
        ),
        201,
    )
    ca_entry = validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(meridian["id"], world.program_id("CA")),
            STATE_REGULATOR_CA,
        ),
        201,
    )

    review = world.open_review(meridian)
    started = world.start_review(review)
    assert started["score"] == 45

    declined = validate_success(_decide(world, review, meridian, "DECLINE"), 200)
    assert declined["status"] == "DECLINED"
    assert declined["conditions_note"] is None
    assert world.get_carrier(meridian["id"])["security_status"] == "DECLINED"

    for entry in (tx_entry, ca_entry):
        swept = validate_success(
            world.api.get_carrier_eligibility(entry["id"], STATE_REGULATOR_TX), 200
        )
        assert swept["listing_status"] == "REMOVED"
        assert swept["removed_on"] == "2026-08-01T00:00:00Z"
        assert swept["version"] == entry["version"] + 1


def test_the_condition_branch_stores_a_note_and_touches_no_white_list_entry(
    configured_world,
):
    """Conditioning is a different branch with a different side-effect set.

    PRD 3.2: "The server refuses a decision the score does not support, with
    `ERR_DECISION_SCORE_MISMATCH`: `APPROVE` requires a score of at least 70,
    `CONDITION` requires a score of at least 50 and strictly below 70, and
    `DECLINE` requires a score strictly below 50."

    Design: Difficulty/non_linear_state_machine/market_security_review_branches_decline_and_condition_carry_different_side_effect_sets
    """
    world = configured_world
    trident = world.create_carrier(
        naic_number="33333",
        legal_name="Trident Global Assurance Ltd",
        domicile_type="ALIEN",
        capital_surplus_cents=1_500_000_000,
        am_best_rating="A",
        trust_fund_cents=539_999_999,
        naic_quarterly_listing=True,
    )
    review = world.open_review(trident)
    started = world.start_review(review)
    # 30 rating + 30 capital + 0 trust (one cent short) + 5 listing.
    assert started["score"] == 65

    # A 65 supports neither approval nor declination.
    validate_error(
        _decide(world, review, trident, "DECLINE"), ERR_DECISION_SCORE_MISMATCH, 422
    )
    validate_error(
        _decide(world, review, trident, "CONDITION"), ERR_CONDITIONS_NOTE_REQUIRED, 422
    )

    note = (
        "Trust fund is 1 cent short of the alien minimum; bind only with "
        "quarterly attestation."
    )
    decided = validate_success(
        _decide(world, review, trident, "CONDITION", conditions_note=note), 200
    )
    assert decided["status"] == "CONDITIONAL"
    assert decided["conditions_note"] == note
    assert world.get_carrier(trident["id"])["security_status"] == "CONDITIONAL"

    entries = validate_success(
        world.api.list_carrier_eligibilities(
            STATE_REGULATOR_TX, {"carrier_id": trident["id"]}
        ),
        200,
    )
    assert entries == []


def test_declining_a_review_writes_the_review_then_the_carrier(configured_world):
    """The first two hops of the decline cascade land on the review and carrier.

    PRD 2.8: "Declining a market security review is a three-hop cascade. The
    first hop writes the review's own `status`. The second hop, caused by the
    first, writes the carrier's `security_status` and increments the carrier's
    `version`."

    Design: Difficulty/transitive_cascade/security_decline_cascades_three_hops_to_white_list_removal
    """
    world = configured_world
    meridian = world.create_carrier(
        naic_number="22222",
        legal_name="Meridian Indemnity Company",
        domicile_type="US_STATE",
        capital_surplus_cents=1_600_000_000,
        am_best_rating="NR",
        trust_fund_cents=0,
        naic_quarterly_listing=False,
    )
    carrier_version_before = meridian["version"]

    review = world.open_review(meridian)
    world.start_review(review)
    declined = validate_success(_decide(world, review, meridian, "DECLINE"), 200)

    assert declined["status"] == "DECLINED"
    assert declined["score"] == 45
    assert declined["rating_at_review"] == "NR"
    assert declined["capital_surplus_at_review_cents"] == 1_600_000_000
    assert_common_fields(declined)

    carrier_after = world.get_carrier(meridian["id"])
    assert carrier_after["security_status"] == "DECLINED"
    assert carrier_after["version"] == carrier_version_before + 1


def test_the_decline_cascade_sweeps_only_currently_white_listed_entries(
    configured_world,
):
    """The third hop leaves an already-removed entry's `removed_on` alone.

    PRD 2.8: "The third hop, caused by the second, sweeps every white-list entry
    of that carrier whose `listing_status` is `WHITE_LISTED`, setting each to
    `REMOVED`, stamping each `removed_on` with the current logical clock and
    incrementing each row's `version`; the rows are processed in ascending order
    of the `state_code` of the state program each row points at."

    Design: Difficulty/transitive_cascade/security_decline_cascades_three_hops_to_white_list_removal
    """
    world = configured_world
    meridian = world.create_carrier(
        naic_number="22222",
        legal_name="Meridian Indemnity Company",
        domicile_type="US_STATE",
        capital_surplus_cents=1_600_000_000,
        am_best_rating="NR",
        trust_fund_cents=0,
        naic_quarterly_listing=False,
    )
    entries = {}
    for state_code, regulator in (
        ("TX", STATE_REGULATOR_TX),
        ("NV", STATE_REGULATOR_NV),
        ("CA", STATE_REGULATOR_CA),
    ):
        entries[state_code] = validate_success(
            world.api.create_carrier_eligibility(
                carrier_eligibility_payload(meridian["id"], world.program_id(state_code)),
                regulator,
            ),
            201,
        )

    # Nevada is struck by hand before the review is decided.
    hand_removed = validate_success(
        world.api.remove_carrier_eligibility(
            entries["NV"]["id"],
            STATE_REGULATOR_NV,
            {"removed_on": "2026-06-15T00:00:00Z"},
        ),
        200,
    )
    assert hand_removed["listing_status"] == "REMOVED"
    assert hand_removed["removed_on"] == "2026-06-15T00:00:00Z"

    review = world.open_review(meridian)
    world.start_review(review)
    validate_success(_decide(world, review, meridian, "DECLINE"), 200)

    for state_code in ("TX", "CA"):
        swept = validate_success(
            world.api.get_carrier_eligibility(entries[state_code]["id"], STATE_REGULATOR_TX),
            200,
        )
        assert swept["listing_status"] == "REMOVED"
        assert swept["removed_on"] == "2026-08-01T00:00:00Z"

    untouched = validate_success(
        world.api.get_carrier_eligibility(entries["NV"]["id"], STATE_REGULATOR_NV), 200
    )
    assert untouched["removed_on"] == "2026-06-15T00:00:00Z"
    assert untouched["version"] == hand_removed["version"]

    still_listed = validate_success(
        world.api.list_carrier_eligibilities(
            STATE_REGULATOR_TX,
            {"carrier_id": meridian["id"], "listing_status": "WHITE_LISTED"},
        ),
        200,
    )
    assert still_listed == []

    removed = validate_success(
        world.api.list_carrier_eligibilities(
            STATE_REGULATOR_TX,
            {"carrier_id": meridian["id"], "listing_status": "REMOVED"},
        ),
        200,
    )
    assert len(removed) == 3


def test_an_alien_carrier_exactly_on_the_trust_minimum_earns_the_trust_points(
    configured_world,
):
    """One cent decides fifteen points of the security score.

    PRD 3.2: "**Trust points** are 15 for a carrier whose `domicile_type` is
    `US_STATE`, on the strength of its domiciliary regulator; an `ALIEN` carrier
    earns those same 15 points only when its `trust_fund_cents` is at least the
    US trust minimum of five million four hundred thousand dollars —
    540,000,000 cents — and 0 otherwise, treating a null trust balance as zero."

    Design: Difficulty/boundary_precision_check/alien_carrier_trust_fund_minimum_is_inclusive_at_the_threshold
    """
    world = configured_world
    kestrel = world.create_carrier(
        naic_number="44444",
        legal_name="Kestrel Reinsurance Ltd",
        domicile_type="ALIEN",
        capital_surplus_cents=1_500_000_000,
        am_best_rating="A",
        trust_fund_cents=540_000_000,
        naic_quarterly_listing=True,
    )
    kittiwake = world.create_carrier(
        naic_number="55555",
        legal_name="Kittiwake Reinsurance Ltd",
        domicile_type="ALIEN",
        capital_surplus_cents=1_500_000_000,
        am_best_rating="A",
        trust_fund_cents=539_999_999,
        naic_quarterly_listing=True,
    )

    on_threshold = world.start_review(world.open_review(kestrel))
    assert on_threshold["score"] == 80

    below_threshold = world.start_review(world.open_review(kittiwake))
    assert below_threshold["score"] == 65
    assert on_threshold["score"] - below_threshold["score"] == 15


def test_the_alien_trust_threshold_decides_approval_versus_condition(configured_world):
    """The inclusive threshold moves the carrier between decision bands.

    PRD 3.2: "The server refuses a decision the score does not support, with
    `ERR_DECISION_SCORE_MISMATCH`: `APPROVE` requires a score of at least 70,
    `CONDITION` requires a score of at least 50 and strictly below 70, and
    `DECLINE` requires a score strictly below 50."

    Design: Difficulty/boundary_precision_check/alien_carrier_trust_fund_minimum_is_inclusive_at_the_threshold
    """
    world = configured_world
    kestrel = world.create_carrier(
        naic_number="44444",
        legal_name="Kestrel Reinsurance Ltd",
        domicile_type="ALIEN",
        capital_surplus_cents=1_500_000_000,
        am_best_rating="A",
        trust_fund_cents=540_000_000,
        naic_quarterly_listing=True,
    )
    kestrel_review = world.open_review(kestrel)
    world.start_review(kestrel_review)
    approved = validate_success(_decide(world, kestrel_review, kestrel, "APPROVE"), 200)
    assert approved["status"] == "APPROVED"
    assert world.get_carrier(kestrel["id"])["security_status"] == "APPROVED"

    kittiwake = world.create_carrier(
        naic_number="55555",
        legal_name="Kittiwake Reinsurance Ltd",
        domicile_type="ALIEN",
        capital_surplus_cents=1_500_000_000,
        am_best_rating="A",
        trust_fund_cents=539_999_999,
        naic_quarterly_listing=True,
    )
    kittiwake_review = world.open_review(kittiwake)
    world.start_review(kittiwake_review)
    validate_error(
        _decide(world, kittiwake_review, kittiwake, "APPROVE"),
        ERR_DECISION_SCORE_MISMATCH,
        422,
    )
    conditioned = validate_success(
        _decide(
            world,
            kittiwake_review,
            kittiwake,
            "CONDITION",
            conditions_note="Trust fund one cent below the alien minimum.",
        ),
        200,
    )
    assert conditioned["status"] == "CONDITIONAL"
    assert world.get_carrier(kittiwake["id"])["security_status"] == "CONDITIONAL"


def test_a_closed_white_list_window_rejects_windows_that_touch_or_overlap_it(
    approved_carrier_world,
):
    """A removed window still occupies its final day, and the day after too.

    PRD 2.11: "White-list windows on one carrier-and-state pair are treated as
    **closed** intervals from `listed_on` through `removed_on` inclusive and
    additionally require a thirty-day cooling-off gap following an existing
    window's `removed_on`, so touching windows are rejected; a collision is
    `ERR_ELIGIBILITY_WINDOW_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/eligibility_windows_are_closed_intervals_with_a_thirty_day_cooling_off_buffer
    """
    world = approved_carrier_world
    program_id = world.program_id("TX")
    first = validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(
                world.carrier["id"], program_id, listed_on="2026-01-01T00:00:00Z"
            ),
            STATE_REGULATOR_TX,
        ),
        201,
    )
    closed = validate_success(
        world.api.remove_carrier_eligibility(
            first["id"], STATE_REGULATOR_TX, {"removed_on": "2026-06-01T00:00:00Z"}
        ),
        200,
    )
    assert closed["listing_status"] == "REMOVED"

    # Strictly inside the closed interval.
    validate_error(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(
                world.carrier["id"], program_id, listed_on="2026-05-01T00:00:00Z"
            ),
            STATE_REGULATOR_TX,
        ),
        ERR_ELIGIBILITY_WINDOW_CONFLICT,
        409,
    )
    # Touching the closed interval's own final instant.
    validate_error(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(
                world.carrier["id"], program_id, listed_on="2026-06-01T00:00:00Z"
            ),
            STATE_REGULATOR_TX,
        ),
        ERR_ELIGIBILITY_WINDOW_CONFLICT,
        409,
    )
    # Clear of both the interval and its cooling-off buffer.
    reopened = validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(
                world.carrier["id"], program_id, listed_on="2026-07-02T00:00:00Z"
            ),
            STATE_REGULATOR_TX,
        ),
        201,
    )
    assert reopened["listing_status"] == "WHITE_LISTED"
    assert reopened["removed_on"] is None


def test_an_open_ended_white_list_window_blocks_every_later_listing(
    approved_carrier_world,
):
    """A live entry with a null `removed_on` has no upper bound to clear.

    PRD 3.2: "The new entry's `listing_status` is `WHITE_LISTED` and its
    `removed_on` is null."

    Design: Difficulty/resource_temporal_overlap/eligibility_windows_are_closed_intervals_with_a_thirty_day_cooling_off_buffer
    """
    world = approved_carrier_world
    program_id = world.program_id("TX")
    first = validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(
                world.carrier["id"], program_id, listed_on="2026-01-01T00:00:00Z"
            ),
            STATE_REGULATOR_TX,
        ),
        201,
    )
    validate_success(
        world.api.remove_carrier_eligibility(
            first["id"], STATE_REGULATOR_TX, {"removed_on": "2026-06-01T00:00:00Z"}
        ),
        200,
    )
    validate_success(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(
                world.carrier["id"], program_id, listed_on="2026-07-02T00:00:00Z"
            ),
            STATE_REGULATOR_TX,
        ),
        201,
    )

    validate_error(
        world.api.create_carrier_eligibility(
            carrier_eligibility_payload(
                world.carrier["id"], program_id, listed_on="2026-09-01T00:00:00Z"
            ),
            STATE_REGULATOR_TX,
        ),
        ERR_ELIGIBILITY_WINDOW_CONFLICT,
        409,
    )

    rows = validate_success(
        world.api.list_carrier_eligibilities(
            STATE_REGULATOR_TX,
            {"carrier_id": world.carrier["id"], "state_program_id": program_id},
        ),
        200,
    )
    assert len(rows) == 2
