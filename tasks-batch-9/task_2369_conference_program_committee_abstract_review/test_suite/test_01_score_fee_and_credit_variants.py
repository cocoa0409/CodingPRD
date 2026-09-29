"""Dual-variant arithmetic across the program committee's three ledgers: the
provisional unweighted consensus against the confidence-weighted final consensus
on an abstract, the estimated change fee quoted at submission against the final
fee charged at approval, and the per-abstract continuing-education credit award
against the bundled conference-level credit estimate.
"""

import pytest

from test_helpers import (
    ADMIN,
    accreditation_validation_payload,
    api_client,
    assert_cme_pool_conserved,
    assert_quarter_credit_step,
    assert_two_decimal_places,
    change_request_adjudication_payload,
    close_review_phase,
    create_accreditation_payload,
    create_disclosure_statement_payload,
    decide_abstract,
    disclosure_adjudication_payload,
    get_success_data,
    make_program_chair_headers,
    reviews_of,
    setup_change_request,
    setup_scored_abstract,
    setup_scored_abstracts,
    validate_success,
)


# ─── Provisional versus final consensus on one abstract ──────────────────


def test_provisional_consensus_is_unweighted_mean_while_review_open():
    """PRD: "The review's `weighted_score` is built by taking forty percent of `score_originality`, thirty percent of `score_methodology`, fifteen percent of `score_clarity` and fifteen percent of `score_relevance`, and adding those four contributions together."
    PRD: "Both consensus scores read exactly the same rows: every review of the abstract whose `status` is `SUBMITTED` and whose `assigned_round` equals the abstract's current `revision_round`."
    PRD: "The **provisional** variant is the plain arithmetic mean: the sum of the `weighted_score` values divided by the number of reviews in the set, rounded half up to two decimal places."
    PRD: "It is written to `provisional_score` on every review submission and is the only consensus figure available while review is still open."
    PRD: "When `submitted_review_count` reaches the category's `min_reviews_required`, the abstract advances from `UNDER_REVIEW` to `SCORED`."

    Design: Difficulty/dual_variant_calc/consensus_provisional_unweighted_vs_final_confidence_weighted_on_abstract
    """
    world = setup_scored_abstract(
        category_overrides={
            "min_reviews_required": 2,
            "discrepancy_threshold": 4.00,
        }
    )
    abstract = world["abstracts"][0]

    rows = reviews_of(world, abstract["id"])
    by_id = {row["id"]: row for row in rows}
    first, second = world["reviews"][abstract["id"]]

    # 4/4/4/4 at HIGH confidence rolls up to 1.60 + 1.20 + 0.60 + 0.60 = 4.00.
    assert float(by_id[first["id"]]["weighted_score"]) == pytest.approx(
        4.00, abs=0.01
    )
    # 3/3/3/3 at MEDIUM confidence rolls up to 1.20 + 0.90 + 0.45 + 0.45 = 3.00.
    assert float(by_id[second["id"]]["weighted_score"]) == pytest.approx(
        3.00, abs=0.01
    )

    live = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live["status"] == "SCORED"
    assert live["submitted_review_count"] == 2
    assert_two_decimal_places(live["provisional_score"])
    # (4.00 + 3.00) / 2 = 3.50, the unweighted mean over the same two rows.
    assert float(live["provisional_score"]) == pytest.approx(3.50, abs=0.01)
    assert live["final_score"] is None


def test_final_consensus_is_confidence_weighted_and_diverges_from_provisional():
    """PRD: "The **final** variant is a confidence-weighted mean. Each review is given a weight from its `confidence` — 1 for `LOW`, 2 for `MEDIUM`, 3 for `HIGH` — and the score is the sum of each review's weight multiplied by its `weighted_score`, divided by the sum of those weights, rounded half up to two decimal places."
    PRD: "It is written to `final_score` when review closes and when a discrepancy resolves, and it is the only score that may drive a decision or a waitlist promotion."
    PRD: "When it succeeds, it fans out across the conference: every abstract that is `UNDER_REVIEW` with a `submitted_review_count` of at least its category's `min_reviews_required` advances to `SCORED`; every abstract that is `UNDER_REVIEW` or `SCORED` with at least one submitted review gets its `final_score` written from the final consensus variant; every review of the conference still in `ASSIGNED` status becomes `VOIDED`, with each affected reviewer's `current_review_load` lowered by one so the load ledger stays exact; and the conference's `version` advances."
    PRD: "Given three submitted reviews scoring 4.20 at `HIGH` confidence, 3.00 at `LOW` and 2.40 at `MEDIUM`, the provisional figure is 9.60 divided by 3, or 3.20, while the final figure is three times 4.20 plus one times 3.00 plus two times 2.40, all divided by six — 20.40 divided by 6, or 3.40."

    Design: Difficulty/dual_variant_calc/consensus_provisional_unweighted_vs_final_confidence_weighted_on_abstract
    """
    world = setup_scored_abstract(
        category_overrides={
            "min_reviews_required": 2,
            "discrepancy_threshold": 4.00,
        }
    )
    abstract = world["abstracts"][0]

    closed = close_review_phase(world)
    assert closed["status"] == "REVIEW_CLOSED"

    live = validate_success(
        api_client.get_abstract(abstract["id"], world["chair_headers"])
    )
    assert live["status"] == "SCORED"
    assert_two_decimal_places(live["final_score"])
    # (3 x 4.00 + 2 x 3.00) / (3 + 2) = 18.00 / 5 = 3.60.
    assert float(live["final_score"]) == pytest.approx(3.60, abs=0.01)
    # The unweighted figure stays on the row untouched.
    assert float(live["provisional_score"]) == pytest.approx(3.50, abs=0.01)
    assert float(live["provisional_score"]) != float(live["final_score"])


# ─── Estimated versus final program change fee ───────────────────────────


def test_change_fee_estimate_quoted_at_submission_uses_gentler_rush_table():
    """PRD: "Creation stamps `submitted_at` from the logical clock and freezes `days_to_event` onto the row: the number of whole 86,400-second days from `submitted_at` to the conference's `event_start_utc`, rounded down, which may be negative for a request filed after the event has begun."
    PRD: "The base fee depends only on `change_type`: 4,000 cents for a `MOVE`, 6,000 for a `SWAP`, 2,500 for a `SUBSTITUTE_PRESENTER` and nothing at all for a `WITHDRAW`."
    PRD: "A rush percentage is then selected from the frozen `days_to_event`, using three bands: fourteen days or more out is the relaxed band, seven to thirteen days out inclusive is the near band, and fewer than seven days out is the imminent band."
    PRD: "The **estimate quoted at submission** uses the gentler table — zero percent in the relaxed band, ten percent in the near band, twenty-five percent in the imminent band — applies it to the base fee, rounds half up to whole cents, and adds no surcharge of any kind."
    PRD: "The requester is then quoted an `estimated_fee_cents`, and the row starts `PENDING` with `final_fee_cents`, `rush_pct_applied` and `approver_member_id` all null."

    Design: Difficulty/dual_variant_calc/change_fee_pre_freeze_estimate_vs_post_freeze_final_on_change_request
    """
    world = setup_change_request(
        change_type="SUBSTITUTE_PRESENTER",
        clock_at_submission="2026-08-27T08:00:00Z",
        abstract_overrides={"coauthor_emails": ["ben@lab.example"]},
    )
    request = world["change_request"]

    live = validate_success(
        api_client.get_program_change_request(request["id"], world["chair_headers"])
    )
    assert live["status"] == "PENDING"
    # 2026-08-27T08:00:00Z to event_start 2026-09-01T08:00:00Z is exactly 5 days.
    assert live["days_to_event"] == 5
    # 2,500 base uplifted by the gentler imminent 25 percent, no surcharge.
    assert live["estimated_fee_cents"] == 3125
    assert live["final_fee_cents"] is None
    assert live["rush_pct_applied"] is None
    assert live["approver_member_id"] is None


def test_change_fee_final_charged_at_approval_adds_post_freeze_surcharge():
    """PRD: "The **final fee charged at approval** uses the steeper table — zero percent relaxed, twenty percent near, fifty percent imminent — on the same frozen `days_to_event`, rounds the uplifted base half up to whole cents, and then adds a flat 1,500-cent post-freeze surcharge when the request's `submitted_at` is at or after the conference's `program_freeze_utc`."
    PRD: "The result is stored in `final_fee_cents`, and the steeper percentage that was applied is recorded in `rush_pct_applied`."
    PRD: "That figure is stored in `estimated_fee_cents` and is never revised afterwards."
    PRD: "A `MOVE` filed five days before the event, after the freeze, therefore quotes 4,000 uplifted by twenty-five percent, or 5,000 cents, and later charges 4,000 uplifted by fifty percent plus the 1,500 surcharge, or 7,500 cents."
    PRD: "Approval computes `final_fee_cents` from the final variant, records `rush_pct_applied` and `approver_member_id`, and then applies the structural change:"
    PRD: "A `SUBSTITUTE_PRESENTER` replaces the slot's `presenter_author_id` with the `substitute_presenter_author_id`."

    Design: Difficulty/dual_variant_calc/change_fee_pre_freeze_estimate_vs_post_freeze_final_on_change_request
    """
    world = setup_change_request(
        change_type="SUBSTITUTE_PRESENTER",
        clock_at_submission="2026-08-27T08:00:00Z",
        abstract_overrides={"coauthor_emails": ["ben@lab.example"]},
    )
    request = world["change_request"]
    chair = world["members"]["cho"]

    applied = validate_success(
        api_client.adjudicate_program_change_request(
            request["id"],
            change_request_adjudication_payload(
                "APPROVED", note="substitution accepted"
            ),
            make_program_chair_headers(chair["id"]),
        )
    )
    assert applied["status"] == "APPLIED"
    # 2,500 base uplifted by the steeper imminent 50 percent is 3,750, plus the
    # flat 1,500-cent post-freeze surcharge.
    assert applied["final_fee_cents"] == 5250
    assert applied["rush_pct_applied"] == 50
    # The quote frozen at submission is never revised.
    assert applied["estimated_fee_cents"] == 3125
    assert applied["estimated_fee_cents"] != applied["final_fee_cents"]
    assert applied["days_to_event"] == 5

    slot = validate_success(
        api_client.get_session_slot(world["slots"][0]["id"], world["chair_headers"])
    )
    assert slot["presenter_author_id"] == world["authors"]["ben"]["id"]


# ─── Per-abstract credit award versus bundled conference estimate ─────────


def _validated_accreditations(minutes_by_index):
    """Two accepted abstracts, each carrying one VALIDATED accreditation whose
    disclosure was cleared by a chair who did not issue the decision."""
    world = setup_scored_abstracts(
        2,
        category_overrides={"cme_eligible": True, "min_reviews_required": 2},
    )
    close_review_phase(world)
    for index, abstract in enumerate(world["abstracts"]):
        world["abstracts"][index] = decide_abstract(world, abstract["id"], "ORAL")

    validator_headers = world["second_chair_headers"]
    accreditations = []
    for index, abstract in enumerate(world["abstracts"]):
        accreditation = get_success_data(
            api_client.create_accreditation(
                create_accreditation_payload(
                    abstract["id"], minutes_by_index[index]
                ),
                ADMIN,
            )
        )
        disclosure = get_success_data(
            api_client.create_disclosure_statement(
                create_disclosure_statement_payload(
                    abstract["id"],
                    accreditation["id"],
                    world["authors"]["ada"]["id"],
                    has_financial_relationship=False,
                ),
                world["author_headers"],
            )
        )
        get_success_data(
            api_client.adjudicate_disclosure_statement(
                disclosure["id"],
                disclosure_adjudication_payload("VALIDATED"),
                validator_headers,
            )
        )
        accreditations.append(
            get_success_data(
                api_client.validate_accreditation(
                    accreditation["id"],
                    accreditation_validation_payload("VALIDATE"),
                    validator_headers,
                )
            )
        )
    world["accreditations"] = accreditations
    return world


def test_cme_per_abstract_award_floors_each_accreditation_separately():
    """PRD: "The **per-abstract award** is what an accreditation actually earns and what feeds a session's ledger: for each validated accreditation, divide its `content_minutes` by fifteen, discard the remainder by rounding down to a whole number, and multiply by 0.25; the total over a set is the sum of those individually floored awards."
    PRD: "On success the row's `awarded_credits` is computed, `validated_by_member_id` and `validated_at` are set, the conference's `cme_minutes_allocated` rises by `content_minutes` with `cme_minutes_available` recomputed and the conference's `version` advanced, and the session holding a counted slot for that abstract recomputes its `accredited_credit_total` and `accreditation_posture` with its own `version` advanced."
    PRD: "A conference's `cme_minutes_allocated` equals the sum of `content_minutes` over its accreditations whose `validation_status` is `VALIDATED`, and `cme_minutes_available` is always `cme_minutes_pool_total` minus `cme_minutes_allocated`."

    Design: Difficulty/dual_variant_calc/cme_credits_per_abstract_award_vs_conference_bundle_estimate
    """
    world = _validated_accreditations([20, 25])
    first, second = world["accreditations"]

    assert first["validation_status"] == "VALIDATED"
    assert second["validation_status"] == "VALIDATED"
    # 20 minutes floors to one quarter credit; the leftover 5 minutes are lost.
    assert float(first["awarded_credits"]) == pytest.approx(0.25, abs=0.01)
    # 25 minutes likewise floors to one quarter credit, losing 10 minutes.
    assert float(second["awarded_credits"]) == pytest.approx(0.25, abs=0.01)
    assert_quarter_credit_step(first["awarded_credits"])
    assert_quarter_credit_step(second["awarded_credits"])

    conference = validate_success(
        api_client.get_conference(world["conference"]["id"], world["chair_headers"])
    )
    assert conference["cme_minutes_allocated"] == 45
    assert conference["cme_minutes_available"] == 555
    assert_cme_pool_conserved(conference)


def test_cme_bundle_estimate_pools_minutes_and_outruns_awarded_sum():
    """PRD: "The **session bundle estimate** is a conference-level planning figure: sum the `content_minutes` of the validated set first, then divide that single total by fifteen, round down to a whole number once, and multiply by 0.25."
    PRD: "Given three validated accreditations of 20, 25 and 40 minutes, the per-abstract route awards 0.25, 0.25 and 0.50 for a total of 1.00, while the bundle route sums to 85 minutes, floors 85 divided by 15 to 5, and reports 1.25."
    PRD: "Both figures are visible side by side on the conference capacity read, which reports the conference's identifier, remaining oral, poster and workshop capacity, the `waitlisted_count`, `cme_minutes_available`, the bundle figure as `cme_bundle_credits`, the plain sum of per-abstract `awarded_credits` as `awarded_credits_sum`, and the count of accredited sessions as `accredited_session_count`."
    PRD: "The gap between `cme_bundle_credits` and `awarded_credits_sum` is expected, not a defect."

    Design: Difficulty/dual_variant_calc/cme_credits_per_abstract_award_vs_conference_bundle_estimate
    """
    world = _validated_accreditations([20, 25])

    summary = validate_success(
        api_client.get_capacity_summary(
            world["conference"]["id"], world["chair_headers"]
        )
    )
    # 0.25 + 0.25 from the individually floored per-abstract awards.
    assert float(summary["awarded_credits_sum"]) == pytest.approx(0.50, abs=0.01)
    # 20 + 25 = 45 minutes pooled, floored once to three quarter credits.
    assert float(summary["cme_bundle_credits"]) == pytest.approx(0.75, abs=0.01)
    assert float(summary["awarded_credits_sum"]) != float(
        summary["cme_bundle_credits"]
    )
    assert_quarter_credit_step(summary["awarded_credits_sum"])
    assert_quarter_credit_step(summary["cme_bundle_credits"])
    assert summary["cme_minutes_available"] == 555
    # No session was ever built in this program, so nothing is accredited.
    assert summary["accredited_session_count"] == 0
