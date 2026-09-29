"""Boundary arithmetic on the three numeric gates the program committee runs on:
the reviewer-disagreement spread that opens a discrepancy case at, and only at,
the category threshold; the fifteen-minutes-per-quarter-credit floor that turns
accreditable content minutes into continuing-education credit; and the session
packing window that admits a slot landing exactly on the minute budget while
refusing the one that needs a single minute more.

Each gate is probed from both sides — on the boundary and one unit away — so an
inclusive comparison cannot pass as an exclusive one.
"""

import pytest

from test_helpers import (
    ADMIN,
    accreditation_validation_payload,
    add_slot,
    api_client,
    assert_cme_pool_conserved,
    assert_quarter_credit_step,
    close_review_phase,
    create_accreditation_payload,
    create_disclosure_statement_payload,
    create_session,
    create_session_slot_payload,
    decide_abstract,
    disclosure_adjudication_payload,
    get_success_data,
    register_author,
    release_decisions,
    reviews_of,
    setup_discrepancy_case,
    setup_scored_abstracts,
    setup_validated_accreditation,
    status_transition_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A hundredth of a point is the whole point of these tests, so the tolerance has
# to be tighter than a hundredth wherever two expected values sit that close.
HUNDREDTH = 0.005
CENT_OF_A_CREDIT = 0.01


# ─── The discrepancy spread threshold ────────────────────────────────────


def test_discrepancy_case_opens_when_spread_equals_the_category_threshold():
    """PRD: "The review's `weighted_score` is built by taking forty percent of `score_originality`, thirty percent of `score_methodology`, fifteen percent of `score_clarity` and fifteen percent of `score_relevance`, and adding those four contributions together."
    PRD: "With exactly two, the spread is the absolute difference between the two `weighted_score` values, rounded half up to two decimal places."
    PRD: "A discrepancy case is opened whenever the recomputed spread is greater than or equal to the category's `discrepancy_threshold` and no non-terminal case already exists for that abstract; the boundary is inclusive, so with a threshold of 1.50 a spread of exactly 1.50 opens a case while 1.49 does not."
    PRD: "The case is created with `status` `OPEN`, its `spread_at_open` frozen to the abstract's spread at that instant, and `arbiter_member_id`, `third_review_id`, `resolution_method` and `resolved_score` all null."
    PRD: "Score comparisons — ranking abstracts for waitlist promotion, comparing a spread to a threshold — are performed at two decimal places."

    Design: Difficulty/boundary_precision_check/score_spread_exactly_at_threshold_versus_one_hundredth_below
    """
    world = setup_discrepancy_case(
        discrepancy_threshold=1.50,
        # 5/4/3/3 rolls up to 2.00 + 1.20 + 0.45 + 0.45 = 4.10 with a zero bias.
        first_review={
            "score_originality": 5,
            "score_methodology": 4,
            "score_relevance": 3,
            "score_clarity": 3,
            "confidence": "HIGH",
            "recommended_format": "ORAL",
        },
        # 2/3/3/3 rolls up to 0.80 + 0.90 + 0.45 + 0.45 = 2.60.
        second_review={
            "score_originality": 2,
            "score_methodology": 3,
            "score_relevance": 3,
            "score_clarity": 3,
            "confidence": "MEDIUM",
            "recommended_format": "POSTER",
        },
    )
    abstract = world["abstracts"][0]

    rows = {row["id"]: row for row in reviews_of(world, abstract["id"])}
    first, second = world["reviews"][abstract["id"]]
    assert float(rows[first["id"]]["weighted_score"]) == pytest.approx(
        4.10, abs=HUNDREDTH
    )
    assert float(rows[second["id"]]["weighted_score"]) == pytest.approx(
        2.60, abs=HUNDREDTH
    )

    live = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert float(live["score_spread"]) == pytest.approx(1.50, abs=HUNDREDTH)
    assert float(live["provisional_score"]) == pytest.approx(3.35, abs=HUNDREDTH)
    assert live["status"] == "SCORED"
    assert live["submitted_review_count"] == 2
    assert live["final_score"] is None

    cases, meta = validate_paginated(
        api_client.list_discrepancy_cases(
            world["chair_headers"], params={"abstract_id": abstract["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert cases[0]["status"] == "OPEN"
    assert float(cases[0]["spread_at_open"]) == pytest.approx(1.50, abs=HUNDREDTH)
    assert cases[0]["arbiter_member_id"] is None
    assert cases[0]["third_review_id"] is None
    assert cases[0]["resolution_method"] is None
    assert cases[0]["resolved_score"] is None


def test_no_discrepancy_case_when_spread_falls_one_hundredth_below_the_threshold():
    """PRD: "Two optional inputs tune the member's behaviour: `max_review_load`, defaulting to 4 and constrained to between 1 and 20, is the ceiling on concurrently assigned reviews, and `calibration_bias`, defaulting to 0.00 and constrained to between minus 1.00 and plus 1.00 at two decimals, is the offset carried over from prior conferences that is added to every rubric total this member produces."
    PRD: "The reviewer's `calibration_bias` is then added to that total."
    PRD: "A discrepancy case is opened whenever the recomputed spread is greater than or equal to the category's `discrepancy_threshold` and no non-terminal case already exists for that abstract; the boundary is inclusive, so with a threshold of 1.50 a spread of exactly 1.50 opens a case while 1.49 does not."
    PRD: "The **provisional** variant is the plain arithmetic mean: the sum of the `weighted_score` values divided by the number of reviews in the set, rounded half up to two decimal places."
    PRD: Scores and money follow fixed precision rules and the "round half up" method throughout; no other rounding mode is used anywhere in the system.

    Design: Difficulty/boundary_precision_check/score_spread_exactly_at_threshold_versus_one_hundredth_below
    """
    world = setup_discrepancy_case(
        discrepancy_threshold=1.50,
        # The biased reviewer files the low card: 2.60 plus 0.01 of bias is 2.61.
        calibration_bias=0.01,
        first_review={
            "score_originality": 2,
            "score_methodology": 3,
            "score_relevance": 3,
            "score_clarity": 3,
            "confidence": "MEDIUM",
            "recommended_format": "POSTER",
        },
        second_review={
            "score_originality": 5,
            "score_methodology": 4,
            "score_relevance": 3,
            "score_clarity": 3,
            "confidence": "HIGH",
            "recommended_format": "ORAL",
        },
    )
    abstract = world["abstracts"][0]

    rows = {row["id"]: row for row in reviews_of(world, abstract["id"])}
    biased, unbiased = world["reviews"][abstract["id"]]
    assert float(rows[biased["id"]]["weighted_score"]) == pytest.approx(
        2.61, abs=HUNDREDTH
    )
    assert float(rows[unbiased["id"]]["weighted_score"]) == pytest.approx(
        4.10, abs=HUNDREDTH
    )

    live = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert float(live["score_spread"]) == pytest.approx(1.49, abs=HUNDREDTH)
    # The mean of 2.61 and 4.10 is exactly 3.355 and must round half up.
    assert float(live["provisional_score"]) == pytest.approx(3.36, abs=HUNDREDTH)
    assert live["status"] == "SCORED"
    assert live["submitted_review_count"] == 2
    assert live["final_score"] is None

    cases, meta = validate_paginated(
        api_client.list_discrepancy_cases(
            world["chair_headers"], params={"abstract_id": abstract["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert cases == []


# ─── The minutes-to-quarter-credit floor ─────────────────────────────────


def _two_accredited_abstracts(first_minutes: int, second_minutes: int) -> dict:
    """Two accepted abstracts of one CME-eligible category, each carrying a
    PENDING accreditation whose sole disclosure has already been validated."""
    world = setup_scored_abstracts(
        2,
        category_overrides={"cme_eligible": True, "min_reviews_required": 2},
    )
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")

    accreditations = []
    for abstract, minutes in zip(world["abstracts"], (first_minutes, second_minutes)):
        accreditation = get_success_data(
            api_client.create_accreditation(
                create_accreditation_payload(abstract["id"], minutes), ADMIN
            )
        )
        disclosure = get_success_data(
            api_client.create_disclosure_statement(
                create_disclosure_statement_payload(
                    abstract["id"],
                    accreditation["id"],
                    world["authors"]["ada"]["id"],
                ),
                world["author_headers"],
            )
        )
        get_success_data(
            api_client.adjudicate_disclosure_statement(
                disclosure["id"],
                disclosure_adjudication_payload("VALIDATED"),
                world["second_chair_headers"],
            )
        )
        accreditations.append(accreditation)
    world["accreditations"] = accreditations
    return world


def test_forty_four_content_minutes_award_two_quarter_credits():
    """PRD: "Both start from accreditable minutes and convert them into quarter credits at fifteen minutes per quarter credit."
    PRD: "The **per-abstract award** is what an accreditation actually earns and what feeds a session's ledger: for each validated accreditation, divide its `content_minutes` by fifteen, discard the remainder by rounding down to a whole number, and multiply by 0.25; the total over a set is the sum of those individually floored awards."
    PRD: "Leftover minutes below fifteen are lost per abstract."
    PRD: "Awarded credit values are additionally always exact multiples of 0.25."
    PRD: "A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`."

    Design: Difficulty/boundary_precision_check/cme_credit_floor_at_forty_four_versus_forty_five_minutes
    """
    world = setup_validated_accreditation(content_minutes=44)
    accreditation = validate_success(
        api_client.get_accreditation(
            world["accreditation"]["id"], world["chair_headers"]
        )
    )

    assert accreditation["validation_status"] == "VALIDATED"
    assert accreditation["content_minutes"] == 44
    # 44 / 15 floors to 2, so the award is 2 * 0.25 — not the 0.75 that rounding
    # to the nearest quarter credit would produce.
    assert float(accreditation["awarded_credits"]) == pytest.approx(
        0.50, abs=CENT_OF_A_CREDIT
    )
    assert_quarter_credit_step(accreditation["awarded_credits"])
    assert accreditation["validated_by_member_id"] == world["members"]["dana"]["id"]

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    # Credits are floored; the minute ledger is not.
    assert conference["cme_minutes_allocated"] == 44
    assert_cme_pool_conserved(conference)


def test_forty_five_content_minutes_award_three_quarter_credits():
    """PRD: "The **per-abstract award** is what an accreditation actually earns and what feeds a session's ledger: for each validated accreditation, divide its `content_minutes` by fifteen, discard the remainder by rounding down to a whole number, and multiply by 0.25; the total over a set is the sum of those individually floored awards."
    PRD: "Validation moves the row from `PENDING` to `VALIDATED` and has four preconditions: the acting chair must not be the member recorded in the abstract's `decided_by_member_id`, or the response is `ERR_ACCREDITATION_SELF_VALIDATION`; at least one disclosure must exist for the accreditation and every one of them must be `VALIDATED`, or the response is `ERR_DISCLOSURE_INCOMPLETE`; the accreditation's `commercial_bias_flag` must be false, which is the second trigger for that same error; and `content_minutes` must be less than or equal to the conference's `cme_minutes_available`, or the response is `ERR_CME_POOL_EXHAUSTED`."
    PRD: "On success the row's `awarded_credits` is computed, `validated_by_member_id` and `validated_at` are set, the conference's `cme_minutes_allocated` rises by `content_minutes` with `cme_minutes_available` recomputed and the conference's `version` advanced, and the session holding a counted slot for that abstract recomputes its `accredited_credit_total` and `accreditation_posture` with its own `version` advanced."

    Design: Difficulty/boundary_precision_check/cme_credit_floor_at_forty_four_versus_forty_five_minutes
    """
    world = setup_validated_accreditation(content_minutes=45)
    accreditation = validate_success(
        api_client.get_accreditation(
            world["accreditation"]["id"], world["chair_headers"]
        )
    )

    assert accreditation["validation_status"] == "VALIDATED"
    assert accreditation["content_minutes"] == 45
    # 45 minutes lands exactly on the third fifteen-minute step: 3 * 0.25.
    assert float(accreditation["awarded_credits"]) == pytest.approx(
        0.75, abs=CENT_OF_A_CREDIT
    )
    assert_quarter_credit_step(accreditation["awarded_credits"])
    assert accreditation["validated_by_member_id"] == world["members"]["dana"]["id"]

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert conference["cme_minutes_allocated"] == 45
    assert_cme_pool_conserved(conference)


def test_minute_pool_debits_whole_content_minutes_while_credits_stay_floored():
    """PRD: "The **per-abstract award** is what an accreditation actually earns and what feeds a session's ledger: for each validated accreditation, divide its `content_minutes` by fifteen, discard the remainder by rounding down to a whole number, and multiply by 0.25; the total over a set is the sum of those individually floored awards."
    PRD: "The **session bundle estimate** is a conference-level planning figure: sum the `content_minutes` of the validated set first, then divide that single total by fifteen, round down to a whole number once, and multiply by 0.25."
    PRD: "A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`."
    PRD: "Both figures are visible side by side on the conference capacity read, which reports the conference's identifier, remaining oral, poster and workshop capacity, the `waitlisted_count`, `cme_minutes_available`, the bundle figure as `cme_bundle_credits`, the plain sum of per-abstract `awarded_credits` as `awarded_credits_sum`, and the count of accredited sessions as `accredited_session_count`."

    Design: Difficulty/boundary_precision_check/cme_credit_floor_at_forty_four_versus_forty_five_minutes
    """
    world = _two_accredited_abstracts(44, 45)
    forty_four, forty_five = world["accreditations"]

    forty_four = validate_success(
        api_client.validate_accreditation(
            forty_four["id"],
            accreditation_validation_payload("VALIDATE"),
            world["second_chair_headers"],
        )
    )
    forty_five = validate_success(
        api_client.validate_accreditation(
            forty_five["id"],
            accreditation_validation_payload("VALIDATE"),
            world["second_chair_headers"],
        )
    )

    assert float(forty_four["awarded_credits"]) == pytest.approx(
        0.50, abs=CENT_OF_A_CREDIT
    )
    assert float(forty_five["awarded_credits"]) == pytest.approx(
        0.75, abs=CENT_OF_A_CREDIT
    )

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    # 44 + 45 minutes are debited in full even though the credits were floored.
    assert conference["cme_minutes_allocated"] == 89
    assert conference["cme_minutes_available"] == 511
    assert_cme_pool_conserved(conference)

    summary = validate_success(
        api_client.get_capacity_summary(
            world["conference"]["id"], world["chair_headers"]
        )
    )
    # The bundle route floors 89 / 15 once, to 5, and reports 5 * 0.25.
    assert float(summary["cme_bundle_credits"]) == pytest.approx(
        1.25, abs=CENT_OF_A_CREDIT
    )


# ─── The session packing window ──────────────────────────────────────────


def _session_of_ninety_minutes_holding_one_forty_minute_slot() -> dict:
    """A PLANNED oral session whose window is exactly ninety minutes, already
    holding one SCHEDULED forty-minute slot, plus a second CONFIRMED abstract
    waiting for the boundary probe."""
    world = setup_scored_abstracts(2)
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")
    release_decisions(world)
    register_author(world["authors"]["ada"]["id"], True)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = get_success_data(
            api_client.transition_abstract(
                abstract["id"],
                status_transition_payload("CONFIRMED"),
                world["author_headers"],
            )
        )
    session = create_session(
        world,
        start_utc="2026-09-01T09:00:00Z",
        end_utc="2026-09-01T10:30:00Z",
        capacity_slots=5,
        cme_designated=False,
    )
    add_slot(
        world,
        session,
        world["abstracts"][0]["id"],
        world["authors"]["ada"]["id"],
        position=1,
        duration_minutes=40,
    )
    return world


def test_slot_admitted_when_packing_lands_exactly_on_the_session_window():
    """PRD: "The session window is the whole number of minutes from `start_utc` to `end_utc`."
    PRD: "A new slot is admissible only when a ten-minute session buffer, plus the durations of all existing counted slots, plus the new slot's `duration_minutes`, plus five minutes for every gap in the resulting arrangement — five multiplied by one less than the post-addition slot count — is less than or equal to the window in minutes."
    PRD: "Worked at the boundary: a ninety-minute window already holding two twenty-five-minute slots has `committed_minutes` of fifty-five, being fifty minutes of content plus one five-minute changeover. Adding a twenty-minute slot needs ten plus seventy plus two changeovers of five, which is exactly ninety and therefore admissible at the boundary; adding a twenty-one-minute slot needs ninety-one, which exceeds the window and is rejected."
    PRD: "A session's `committed_minutes` is the sum of `duration_minutes` over its counted slots plus a five-minute changeover allowance for each gap between consecutive counted slots — that is, five minutes multiplied by one less than the number of counted slots, and zero when there are no slots at all."
    PRD: "A successful placement moves the abstract from `CONFIRMED` to `SCHEDULED`, raises the session's `slot_count` by one, recomputes `committed_minutes`, `accredited_credit_total` and `accreditation_posture`, and advances the session's `version`."

    Design: Difficulty/boundary_precision_check/session_packing_admits_exactly_ninety_minutes_and_rejects_ninety_one
    """
    world = _session_of_ninety_minutes_holding_one_forty_minute_slot()
    session = world["sessions"][0]

    live = validate_success(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert live["slot_count"] == 1
    assert live["committed_minutes"] == 40

    # 10 + (40 + 35) + 5 = 90, which is exactly the ninety-minute window.
    res = api_client.create_session_slot(
        session["id"],
        create_session_slot_payload(
            world["abstracts"][1]["id"],
            world["authors"]["ada"]["id"],
            2,
            35,
            live["version"],
        ),
        world["chair_headers"],
    )
    slot = validate_success(res, 201)
    assert slot["status"] == "SCHEDULED"
    assert slot["duration_minutes"] == 35
    assert slot["position"] == 2

    packed = validate_success(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert packed["slot_count"] == 2
    # Seventy content minutes plus a single five-minute changeover.
    assert packed["committed_minutes"] == 80

    for abstract in world["abstracts"]:
        live_abstract = validate_success(
            api_client.get_abstract(abstract["id"], world["chair_headers"])
        )
        assert live_abstract["status"] == "SCHEDULED"


def test_slot_rejected_when_packing_needs_one_minute_beyond_the_session_window():
    """PRD: "A new slot is admissible only when a ten-minute session buffer, plus the durations of all existing counted slots, plus the new slot's `duration_minutes`, plus five minutes for every gap in the resulting arrangement — five multiplied by one less than the post-addition slot count — is less than or equal to the window in minutes."
    PRD: "Worked at the boundary: a ninety-minute window already holding two twenty-five-minute slots has `committed_minutes` of fifty-five, being fifty minutes of content plus one five-minute changeover. Adding a twenty-minute slot needs ten plus seventy plus two changeovers of five, which is exactly ninety and therefore admissible at the boundary; adding a twenty-one-minute slot needs ninety-one, which exceeds the window and is rejected."
    PRD: "The three packing checks run in a fixed order: the count must be strictly less than `capacity_slots`, or the response is `ERR_SESSION_SLOT_CAPACITY_REACHED`; the requested `position` must not already be occupied by a counted slot of the session, or the response is `ERR_DUPLICATE_SLOT_POSITION`; and the minute budget must admit the new duration, or the response is `ERR_SESSION_DURATION_EXCEEDED`."
    PRD: "Later violations are never reported, and no partial write ever survives a rejection."

    Design: Difficulty/boundary_precision_check/session_packing_admits_exactly_ninety_minutes_and_rejects_ninety_one
    """
    world = _session_of_ninety_minutes_holding_one_forty_minute_slot()
    session = world["sessions"][0]

    live = validate_success(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert live["slot_count"] == 1
    assert live["committed_minutes"] == 40

    # 10 + (40 + 36) + 5 = 91, one minute past the ninety-minute window.
    res = api_client.create_session_slot(
        session["id"],
        create_session_slot_payload(
            world["abstracts"][1]["id"],
            world["authors"]["ada"]["id"],
            2,
            36,
            live["version"],
        ),
        world["chair_headers"],
    )
    validate_error(res, "ERR_SESSION_DURATION_EXCEEDED", 422)

    after = validate_success(
        api_client.get_session(session["id"], world["chair_headers"])
    )
    assert after["slot_count"] == 1
    assert after["committed_minutes"] == 40

    rejected_abstract = validate_success(
        api_client.get_abstract(world["abstracts"][1]["id"], world["chair_headers"])
    )
    assert rejected_abstract["status"] == "CONFIRMED"
