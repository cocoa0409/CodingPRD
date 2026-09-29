"""State machines that are not simple chains: a bounded review loop, two orthogonal
dimensions on one row, and a fork that rejoins under a compound guard.
"""

from typing import Any, Dict

from test_helpers import (
    AUDITOR_ALICE,
    AUDITOR_BOB,
    AUDITOR_CAROL,
    AUDITOR_DAVE,
    AlertStatus,
    ApiErrorId,
    BasicCategory,
    CapDecision,
    CapItemAction,
    CapReviewOutcome,
    CapStatus,
    ChallengeStatus,
    ChallengeType,
    CourtStatus,
    EvidenceType,
    RecordUpdateStatus,
    ReviewAction,
    SafetyFitnessStatus,
    SelectionBand,
    UnitType,
    ViolationStatus,
    assert_measure,
    assert_one_decimal,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_auditor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _challenge_after_three_rounds(api) -> Dict[str, Any]:
    """A challenge that has already used all three information-request rounds and is
    back in UNDER_REVIEW."""
    scenario = fx.build_single_violation_scored_report(api)
    carrier_id = scenario["carrier"]["id"]
    challenge = fx.build_challenge_under_review(
        api,
        carrier_id,
        scenario["report"]["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="The officer narrative does not describe a speeding event.",
        target_violation_id=scenario["violations"][0]["id"],
    )
    for evidence_type in (
        EvidenceType.ELD_RECORD,
        EvidenceType.GPS_LOG,
        EvidenceType.PHOTO,
    ):
        fx.cycle_information_request(
            api, carrier_id, challenge["id"], evidence_type=evidence_type
        )
    scenario["challenge"] = get_success_data(
        api.get_data_challenge(challenge["id"], fx.REVIEWER)
    )
    return scenario


class TestBoundedInformationRequestLoop:
    def test_fourth_information_request_is_rejected(self, api):
        """PRD 3.6: "The `REQUEST_INFO` action moves it from `UNDER_REVIEW` to
        `INFO_REQUESTED`, but only while `info_request_count` is still below 3; a fourth
        request on one challenge is rejected with
        `ERR_CHALLENGE_ROUND_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/challenge_fourth_info_request_rejected_after_three_rounds
        """
        scenario = _challenge_after_three_rounds(api)
        challenge_id = scenario["challenge"]["id"]
        assert scenario["challenge"]["status"] == ChallengeStatus.UNDER_REVIEW
        assert scenario["challenge"]["info_request_count"] == 3

        response = api.review_challenge(
            challenge_id,
            fac.review_payload(
                ReviewAction.REQUEST_INFO, review_note="Round 4: one more document."
            ),
            fx.REVIEWER,
        )
        validate_error(response, ApiErrorId.CHALLENGE_ROUND_LIMIT_EXCEEDED, 409)

        after = get_success_data(api.get_data_challenge(challenge_id, fx.REVIEWER))
        assert after["status"] == ChallengeStatus.UNDER_REVIEW
        assert after["info_request_count"] == 3
        assert after["info_response_deadline"].startswith("2026-08-31T00:00:00")

    def test_resubmissions_consume_no_extra_quota_and_stamp_their_round(self, api):
        """PRD 3.6: "The system stamps each row with `submitted_round`, copied from the
        challenge's `info_request_count` at the moment of upload — that stamp is what
        distinguishes the original filing package from follow-up material supplied in
        answer to a later information request."

        Design: Difficulty/non_linear_state_machine/challenge_fourth_info_request_rejected_after_three_rounds
        """
        scenario = _challenge_after_three_rounds(api)
        challenge_id = scenario["challenge"]["id"]

        assert scenario["challenge"]["evidence_count"] == 4
        rows, meta = validate_paginated(api.list_evidence(challenge_id, fx.REVIEWER))
        assert meta["total_count"] == 4
        assert sorted(row["submitted_round"] for row in rows) == [0, 1, 2, 3]

        carrier = fx.read_carrier(api, scenario["carrier"]["id"])
        assert carrier["challenge_quota_used"] == 1
        assert fx.read_violation(api, scenario["violations"][0]["id"])["under_challenge"] is True


def _reduced_citation(api) -> Dict[str, Any]:
    """A scored weight-5 violation whose citation has just come back REDUCED to a
    weight-3 code, with the record dimension still untouched."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    charged = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    reduced_to = fx.create_violation_code(
        api,
        code="392.2LS",
        description="Speeding less than 5 over the limit",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=3,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": charged["id"], "unit_type": UnitType.VEHICLE}],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    adjudication = fx.create_adjudication(
        api,
        rows[0]["id"],
        citation_number="OH-CIT-77002",
        court_date="2026-07-22T00:00:00Z",
    )
    fx.record_court_result(
        api,
        adjudication["id"],
        CourtStatus.REDUCED,
        reduced_to_violation_code_id=reduced_to["id"],
        court_note="Amended to a lesser speeding charge.",
    )
    return {
        "carrier": carrier,
        "charged_code": charged,
        "reduced_code": reduced_to,
        "report": report,
        "violation": rows[0],
        "adjudication": adjudication,
    }


class TestAdjudicationTwoDimensions:
    def test_court_dimension_moves_alone(self, api):
        """PRD 3.8: "The `court_status` dimension follows what the court did; the
        `record_update_status` dimension follows whether that outcome has been pushed
        into the safety record. Neither constrains the other, and the divergence between
        them is where a great deal of this domain's real complexity lives."

        Design: Difficulty/non_linear_state_machine/adjudication_court_and_record_dimensions_advance_independently
        """
        scenario = _reduced_citation(api)
        adjudication = get_success_data(
            api.get_citation_adjudication(scenario["adjudication"]["id"], fx.OFFICER)
        )
        assert adjudication["court_status"] == CourtStatus.REDUCED
        assert_one_decimal(adjudication["severity_factor"], 0.5)
        assert adjudication["record_update_status"] == RecordUpdateStatus.NOT_APPLIED

        violation = fx.read_violation(api, scenario["violation"]["id"])
        assert violation["status"] == ViolationStatus.ACTIVE
        assert violation["effective_violation_code_id"] == scenario["charged_code"]["id"]
        assert_one_decimal(violation["time_weighted_severity"], 15.0)

        row = fx.read_basic_score(
            api, scenario["carrier"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_measure(row["certified_measure"], 0.500)

    def test_record_dimension_moves_on_the_later_push(self, api):
        """PRD 3.8: "For `REDUCED`, `record_update_status` likewise moves to `APPLIED`,
        and the violation's `effective_violation_code_id` is set to the
        `reduced_to_violation_code_id`, its `status` becomes `RECODED`, its
        `code_weight_snapshot`, `oos_add_on_snapshot` and `pinned_violation_code_version`
        are re-pinned from the new code, and its `time_weighted_severity` is
        recomputed."

        Design: Difficulty/non_linear_state_machine/adjudication_court_and_record_dimensions_advance_independently
        """
        scenario = _reduced_citation(api)
        validate_success(
            api.apply_to_record(scenario["adjudication"]["id"], fx.REVIEWER), 200
        )

        adjudication = get_success_data(
            api.get_citation_adjudication(scenario["adjudication"]["id"], fx.OFFICER)
        )
        assert adjudication["record_update_status"] == RecordUpdateStatus.APPLIED
        assert adjudication["court_status"] == CourtStatus.REDUCED
        assert adjudication["superseded"] is False

        violation = fx.read_violation(api, scenario["violation"]["id"])
        assert violation["status"] == ViolationStatus.RECODED
        assert violation["effective_violation_code_id"] == scenario["reduced_code"]["id"]
        assert violation["code_weight_snapshot"] == 3
        assert violation["time_weight"] == 3
        assert_one_decimal(violation["time_weighted_severity"], 9.0)

        row = fx.read_basic_score(
            api, scenario["carrier"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_one_decimal(row["total_time_weighted_severity"], 9.0)
        assert_measure(row["certified_measure"], 0.300)
        assert_one_decimal(row["percentile"], 30.0)
        assert row["alert_status"] == AlertStatus.CLEAR

        carrier = fx.read_carrier(api, scenario["carrier"]["id"])
        assert_one_decimal(carrier["iss_pre_credit_value"], 10.5)
        assert_one_decimal(carrier["iss_value"], 10.5)
        assert carrier["selection_band"] == SelectionBand.PASS


def _plan_in_review_with_one_verified_item(api) -> Dict[str, Any]:
    """A three-item plan with both review branches CLEARED, all items IMPLEMENTED and
    the first one already VERIFIED."""
    scenario = fx.build_cap_in_review(
        api, item_count=3, safety_auditor=AUDITOR_BOB, data_auditor=AUDITOR_CAROL
    )
    fx.set_item_status(
        api,
        scenario["items"][0]["id"],
        CapItemAction.VERIFY,
        make_auditor_headers(AUDITOR_BOB),
    )
    scenario["cap"] = fx.read_cap(api, scenario["cap"]["id"])
    return scenario


class TestCorrectiveActionPlanForkJoin:
    def test_join_waits_for_the_last_verification(self, api):
        """PRD 3.10: "A plan in `IN_REVIEW` whose `safety_review_outcome` is `CLEARED`,
        whose `data_review_outcome` is `CLEARED`, and whose `completion_pct` has reached
        exactly 100.0 — meaning every non-rejected action item is `VERIFIED` — moves to
        `PENDING_DECISION`."

        Design: Difficulty/non_linear_state_machine/cap_fork_join_requires_both_branches_and_full_item_verification
        """
        scenario = _plan_in_review_with_one_verified_item(api)
        cap_id = scenario["cap"]["id"]
        auditor = make_auditor_headers(AUDITOR_BOB)

        assert scenario["cap"]["status"] == CapStatus.IN_REVIEW
        assert scenario["cap"]["triggering_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
        assert scenario["cap"]["item_count"] == 3
        assert scenario["cap"]["committed_item_count"] == 3
        assert_one_decimal(scenario["cap"]["completion_pct"], 33.3)
        assert scenario["cap"]["safety_review_outcome"] == CapReviewOutcome.CLEARED
        assert scenario["cap"]["data_review_outcome"] == CapReviewOutcome.CLEARED
        assert scenario["cap"]["safety_review_user_id"] == AUDITOR_BOB
        assert scenario["cap"]["data_review_user_id"] == AUDITOR_CAROL

        fx.set_item_status(api, scenario["items"][1]["id"], CapItemAction.VERIFY, auditor)
        midway = fx.read_cap(api, cap_id)
        assert midway["verified_item_count"] == 2
        assert_one_decimal(midway["completion_pct"], 66.7)
        assert midway["status"] == CapStatus.IN_REVIEW

        fx.set_item_status(api, scenario["items"][2]["id"], CapItemAction.VERIFY, auditor)
        joined = fx.read_cap(api, cap_id)
        assert joined["verified_item_count"] == 3
        assert_one_decimal(joined["completion_pct"], 100.0)
        assert joined["status"] == CapStatus.PENDING_DECISION

    def test_accepted_decision_upgrades_the_carrier_by_one_step(self, api):
        """PRD 3.10: "`ACCEPT` moves the plan to `ACCEPTED` and upgrades the carrier's
        `safety_fitness_status` by exactly one step — `UNSATISFACTORY` becomes
        `CONDITIONAL`, and `CONDITIONAL` becomes `SATISFACTORY` — incrementing both the
        carrier's `version` and the plan's `version` by 1."

        Design: Difficulty/non_linear_state_machine/cap_fork_join_requires_both_branches_and_full_item_verification
        """
        scenario = _plan_in_review_with_one_verified_item(api)
        cap_id = scenario["cap"]["id"]
        auditor = make_auditor_headers(AUDITOR_BOB)
        for item in scenario["items"][1:]:
            fx.set_item_status(api, item["id"], CapItemAction.VERIFY, auditor)

        validate_success(
            api.decide_cap(
                cap_id,
                {
                    "decision": CapDecision.ACCEPT,
                    "note": "Plan accepted; fitness upgraded.",
                },
                make_auditor_headers(AUDITOR_DAVE),
            ),
            200,
        )

        cap = fx.read_cap(api, cap_id)
        assert cap["status"] == CapStatus.ACCEPTED
        assert cap["decision"] == CapDecision.ACCEPT
        assert cap["decided_by_user_id"] == AUDITOR_DAVE

        carrier = fx.read_carrier(api, scenario["carrier"]["id"])
        assert carrier["safety_fitness_status"] == SafetyFitnessStatus.SATISFACTORY
        assert carrier["fitness_determined_by_user_id"] == AUDITOR_ALICE
