"""Abstraction, over-read review, inter-rater reliability, and sample finalize gates.

Covers the chase-state gate on abstraction creation, submit/retract compensation,
the selector top-up, the DISAGREE remediation cascade, IRR tier boundaries, and the
four finalize gates.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_abstraction_payload,
    create_submitted_abstraction,
    get_abstraction,
    get_chase,
    get_run,
    get_sample,
    list_abstraction_overreads,
    make_abstractor_headers,
    make_overreader_headers,
    receive_chases,
    record_overread,
    setup_hybrid_sample,
    setup_hybrid_with_submitted_abstractions,
    validate_error,
    validate_success,
    get_success_data,
)

ANALYST = TEST_USERS["quality_analyst_headers"]

FIFTY_TO_74_F = {"age_min": 50, "age_max": 74, "gender_requirement": "F"}
BORN_1960_F = {"birth_date": "1960-01-01T00:00:00Z", "gender": "F"}


def _refs_attrs(refs):
    return tuple(refs), {r: dict(BORN_1960_F) for r in refs}


def _hybrid_scenario(api, refs, floor):
    member_refs, attrs = _refs_attrs(refs)
    return setup_hybrid_sample(
        api,
        member_refs=member_refs,
        floor=floor,
        spec_overrides=dict(FIFTY_TO_74_F, hybrid_policy="SAMPLE_ONLY"),
        member_attrs=attrs,
        season_overrides={"approved_supplemental_sources": ["LAB_FEED"]},
    )


class TestAbstractionCreationGate:
    def test_abstraction_on_requested_chase_rejected(self, api):
        """Creating an abstraction on a chase still REQUESTED is a state violation.

        PRD §3.5: "The chase must be `RECEIVED` — abstracting a chart that has not
        arrived is `ERR_INVALID_STATE` — and at most one non-terminal abstraction may
        exist per chase"

        Design: Difficulty/cross_entity_state_dependency/abstraction_gated_on_chase_received
        """
        scenario = _hybrid_scenario(api, ("M001", "M002"), 2)
        c1 = scenario["chases"][0]
        assert c1["status"] == "REQUESTED"
        resp = api.create_abstraction(
            create_abstraction_payload(c1["id"], "HIT"), make_abstractor_headers("abs-1")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_abstraction_on_received_chase_accepted(self, api):
        """A RECEIVED chase accepts the abstraction: it starts DRAFT and stamps the
        author's X-User-ID.

        PRD §3.5: "Creation records the author's `X-User-ID` as `abstractor_user_id`
        and starts the abstraction in `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/abstraction_gated_on_chase_received
        """
        scenario = _hybrid_scenario(api, ("M001", "M002"), 2)
        c2 = scenario["chases"][1]
        receive_chases(api, [c2])
        resp = api.create_abstraction(
            create_abstraction_payload(c2["id"], "HIT"), make_abstractor_headers("abs-1")
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["abstractor_user_id"] == "abs-1"


class TestSubmitRetreatConservation:
    def _draft_scenario(self, api):
        scenario = _hybrid_scenario(api, ("M001", "M002"), 2)
        scenario["chases"] = receive_chases(api, scenario["chases"])
        c1 = scenario["chases"][0]
        a1 = get_success_data(
            api.create_abstraction(
                create_abstraction_payload(c1["id"], "HIT"), make_abstractor_headers("abs-1")
            )
        )
        scenario["a1"] = a1
        scenario["c1"] = c1
        return scenario

    def test_submit_counts_hit_and_abstracts_chase(self, api):
        """Submitting a HIT abstraction adds it to the counted set and moves the
        chase RECEIVED -> ABSTRACTED on first submit.

        PRD §3.5: "The submission stamps `submitted_at` with the current logical-clock
        time — this timestamp is the selector's sort key — and, on the first submit
        only, moves the chase from `RECEIVED` to `ABSTRACTED` as a side effect."
        PRD §3.7: "The counted abstraction states are `SUBMITTED`, `CONFIRMED`, and
        `OVERREAD_PASSED`."

        Design: Difficulty/compensating_invariant/submit_retract_numerator_conservation
        """
        scenario = self._draft_scenario(api)
        run_id = scenario["run"]["id"]
        assert get_run(api, run_id)["sample_numerator_count"] == 0
        validate_success(
            api.submit_abstraction(scenario["a1"]["id"], make_abstractor_headers("abs-1"))
        )
        run_after = get_run(api, run_id)
        assert run_after["sample_numerator_count"] == 1, (
            f"a SUBMITTED HIT must join the counted set; got "
            f"{run_after['sample_numerator_count']}"
        )
        chase = get_chase(api, scenario["c1"]["id"])
        assert chase["status"] == "ABSTRACTED"

    def test_retract_restores_numerator_and_chase(self, api):
        """The submit/retract pair leaves the sample numerator tally unchanged and
        returns the chase to RECEIVED.

        PRD §3.5: "the retraction moves the chase from `ABSTRACTED` back to `RECEIVED`
        and recomputes the run's `sample_numerator_count` with the retracted
        abstraction removed from the counted set."

        Design: Difficulty/compensating_invariant/submit_retract_numerator_conservation
        """
        scenario = self._draft_scenario(api)
        run_id = scenario["run"]["id"]
        headers = make_abstractor_headers("abs-1")
        validate_success(api.submit_abstraction(scenario["a1"]["id"], headers))
        assert get_run(api, run_id)["sample_numerator_count"] == 1
        validate_success(api.retract_abstraction(scenario["a1"]["id"], headers))
        run_after = get_run(api, run_id)
        assert run_after["sample_numerator_count"] == 0, (
            f"retract must remove the abstraction from the counted set; got "
            f"{run_after['sample_numerator_count']}"
        )
        chase = get_chase(api, scenario["c1"]["id"])
        assert chase["status"] == "RECEIVED"


class TestOverreadFractionTierEscalation:
    def test_disagree_drops_ratio_to_full_tier(self, api):
        """With two HIT abstractions submitted in order, the base fraction flags
        only the earliest; a DISAGREE on it moves it to REMEDIATION, bumps the
        remediation counter, re-flags the sibling, and the evaluation lands on
        ratio 0.0 -> FAILED -> fraction 1.0.

        PRD §3.5: "Among the sample's abstractions currently in `SUBMITTED`, ordered
        by `submitted_at` ascending with `created_at` ascending as tie-break, it flags
        `requires_overread` true in that order until the number flagged among the
        submitted set reaches at least the ceiling of `required_overread_fraction`
        times the number of submitted abstractions."
        PRD §3.5: "otherwise a ratio of at least 0.95 sets the fraction to 0.10, a
        ratio of at least 0.90 but below 0.95 sets it to 0.25, and anything below 0.90
        sets it to 1.0."
        PRD §3.5: "The `irr_state` becomes `PASSED` exactly when `irr_ratio` is
        non-null and at least 0.95 — the boundary is inclusive — and `FAILED` when it
        is non-null and below 0.95"

        Design: Difficulty/combinatorial_formula/overread_fraction_tier_escalation
        """
        scenario = setup_hybrid_with_submitted_abstractions(
            api, ("M001", "M002"), ("HIT", "HIT"), floor=2,
            spec_overrides=dict(FIFTY_TO_74_F, hybrid_policy="SAMPLE_ONLY"),
            member_attrs={"M001": dict(BORN_1960_F), "M002": dict(BORN_1960_F)},
        )
        a1, a2 = scenario["abstractions"]
        sample_id = scenario["sample"]["id"]
        assert a2["requires_overread"] is False, (
            "at fraction 0.10 with 2 submitted, only the earliest-submitted a1 is flagged"
        )
        record_overread(api, a1["id"], "DISAGREE", final_result="MISS")
        a1_after = get_abstraction(api, a1["id"])
        assert a1_after["status"] == "REMEDIATION"
        a2_after = get_abstraction(api, a2["id"])
        assert a2_after["requires_overread"] is True, (
            "a1 leaving SUBMITTED re-runs the selector top-up and flags a2"
        )
        sample_mid = get_sample(api, sample_id)
        assert sample_mid["remediation_count"] == 1
        evaluated = validate_success(api.evaluate_irr(sample_id, ANALYST))
        assert evaluated["irr_ratio"] == pytest.approx(0.0)
        assert evaluated["irr_state"] == "FAILED"
        assert evaluated["required_overread_fraction"] == pytest.approx(1.0), (
            "ratio 0.0 below 0.90 selects the full tier (remediation_count 1 < 2)"
        )

    def test_remediation_cycle_returns_to_base_tier(self, api):
        """The remediation loop: retract from REMEDIATION advances the submission
        round, resubmission is flagged under the 1.0 fraction, and after AGREEs all
        around the evaluation returns to ratio 1.0 -> PASSED -> fraction 0.10.

        PRD §3.5: "From `REMEDIATION`, retraction also returns to `DRAFT` but behaves
        differently: `resubmission_count` increments by 1 because leaving remediation
        advances the submission round and thereby unlocks a fresh over-read, and the
        chase stays `ABSTRACTED` — the chart remains in hand during remediation."
        PRD §3.5: "if the sample's `remediation_count` has reached 2, the fraction is
        1.0 regardless of ratio; otherwise, if `irr_ratio` is null, the fraction is
        left unchanged; otherwise a ratio of at least 0.95 sets the fraction to 0.10"

        Design: Difficulty/combinatorial_formula/overread_fraction_tier_escalation
        """
        scenario = setup_hybrid_with_submitted_abstractions(
            api, ("M001", "M002"), ("HIT", "HIT"), floor=2,
            spec_overrides=dict(FIFTY_TO_74_F, hybrid_policy="SAMPLE_ONLY"),
            member_attrs={"M001": dict(BORN_1960_F), "M002": dict(BORN_1960_F)},
        )
        a1, a2 = scenario["abstractions"]
        sample_id = scenario["sample"]["id"]
        record_overread(api, a1["id"], "DISAGREE", final_result="MISS")
        validate_success(api.evaluate_irr(sample_id, ANALYST))
        record_overread(api, a2["id"], "AGREE")
        retracted = validate_success(
            api.retract_abstraction(a1["id"], make_abstractor_headers("abs-1"))
        )
        assert retracted["status"] == "DRAFT"
        assert retracted["resubmission_count"] == 1, (
            "leaving REMEDIATION advances the submission round"
        )
        validate_success(
            api.update_abstraction(
                a1["id"], {"result": "MISS"}, make_abstractor_headers("abs-1")
            )
        )
        resubmitted = validate_success(
            api.submit_abstraction(a1["id"], make_abstractor_headers("abs-1"))
        )
        assert resubmitted["requires_overread"] is True, (
            "under fraction 1.0 the resubmitted abstraction is flagged again"
        )
        record_overread(api, a1["id"], "AGREE")
        evaluated = validate_success(api.evaluate_irr(sample_id, ANALYST))
        assert evaluated["irr_ratio"] == pytest.approx(1.0), (
            "latest reviews: a1 round-1 AGREE plus a2 AGREE = 2/2"
        )
        assert evaluated["irr_state"] == "PASSED"
        assert evaluated["required_overread_fraction"] == pytest.approx(0.10), (
            "ratio >= 0.95 selects the base tier"
        )


class TestDisagreeRemediationCascade:
    def _three_submitted(self, api):
        scenario = setup_hybrid_with_submitted_abstractions(
            api, ("M001", "M002", "M003"), ("HIT", "HIT", "HIT"), floor=3,
            spec_overrides=dict(FIFTY_TO_74_F, hybrid_policy="SAMPLE_ONLY"),
            member_attrs={r: dict(BORN_1960_F) for r in ("M001", "M002", "M003")},
        )
        a3 = get_abstraction(api, scenario["abstractions"][2]["id"])
        assert a3["requires_overread"] is False
        sample = get_sample(api, scenario["sample"]["id"])
        assert sample["required_overread_fraction"] == pytest.approx(0.10)
        return scenario

    def test_first_disagree_topup_flags_next_submitted(self, api):
        """The first DISAGREE moves the abstraction to REMEDIATION, increments the
        sample remediation counter, leaves the fraction at its base (one remediation
        is below the override), and re-runs the selector onto the next-earliest
        submitted abstraction.

        PRD §3.5: "A `DISAGREE` moves the abstraction from `SUBMITTED` to
        `REMEDIATION` and fires a three-link cascade: first the sample's
        `remediation_count` increments by 1; second, when that count reaches 2, the
        sample's `required_overread_fraction` is set to 1.0 immediately — a hard
        override applied at once, not deferred to the next IRR evaluation; third, the
        selector top-up re-runs immediately under the new fraction, flagging
        still-submitted abstractions in `submitted_at` then `created_at` order."

        Design: Difficulty/transitive_cascade/overread_disagree_remediation_cascade
        """
        scenario = self._three_submitted(api)
        a1, a2, _a3 = scenario["abstractions"]
        record_overread(api, a1["id"], "DISAGREE", final_result="MISS")
        assert get_abstraction(api, a1["id"])["status"] == "REMEDIATION"
        sample = get_sample(api, scenario["sample"]["id"])
        assert sample["remediation_count"] == 1
        assert sample["required_overread_fraction"] == pytest.approx(0.10), (
            "a single remediation does not trigger the override"
        )
        a2_after = get_abstraction(api, a2["id"])
        assert a2_after["requires_overread"] is True, (
            "a1 leaving SUBMITTED re-runs the selector top-up and flags a2"
        )

    def test_second_disagree_forces_full_fraction(self, api):
        """The second DISAGREE pushes remediation_count to 2, forcing
        required_overread_fraction to 1.0 immediately, and the top-up flags the
        still-submitted third abstraction.

        PRD §3.5: "second, when that count reaches 2, the sample's
        `required_overread_fraction` is set to 1.0 immediately — a hard override
        applied at once, not deferred to the next IRR evaluation; third, the selector
        top-up re-runs immediately under the new fraction, flagging still-submitted
        abstractions in `submitted_at` then `created_at` order."

        Design: Difficulty/transitive_cascade/overread_disagree_remediation_cascade
        """
        scenario = self._three_submitted(api)
        a1, a2, a3 = scenario["abstractions"]
        record_overread(api, a1["id"], "DISAGREE", final_result="MISS")
        record_overread(api, a2["id"], "DISAGREE", final_result="MISS")
        sample = get_sample(api, scenario["sample"]["id"])
        assert sample["remediation_count"] == 2
        assert sample["required_overread_fraction"] == pytest.approx(1.0), (
            "remediation_count reaching 2 forces the fraction override immediately"
        )
        a3_after = get_abstraction(api, a3["id"])
        assert a3_after["requires_overread"] is True, (
            "the new fraction re-runs the selector and flags a3"
        )


class TestIrrMidTierBoundary:
    def _boundary_scenario(self, api):
        refs = tuple(f"M{i:02d}" for i in range(1, 11))
        scenario = setup_hybrid_with_submitted_abstractions(
            api, refs, ("HIT",) * 10, floor=10,
            spec_overrides=dict(FIFTY_TO_74_F, hybrid_policy="SAMPLE_ONLY"),
            member_attrs={r: dict(BORN_1960_F) for r in refs},
        )
        return scenario

    def test_ratio_exactly_090_selects_mid_tier_and_fails_gate(self, api):
        """Nine agreements over ten latest reviews land exactly on the inclusive
        0.90 mid-tier boundary: fraction 0.25 (not the 1.0 full tier) while the
        0.95 pass gate still fails.

        PRD §2.7: "Tier thresholds in inter-rater reliability use inclusive
        boundaries: a ratio of exactly 0.95 passes, and a ratio of exactly 0.90 maps
        to the middle over-read fraction."
        PRD §3.5: "otherwise a ratio of at least 0.95 sets the fraction to 0.10, a
        ratio of at least 0.90 but below 0.95 sets it to 0.25, and anything below 0.90
        sets it to 1.0."

        Design: Difficulty/boundary_precision_check/irr_mid_tier_boundary_exactly_090
        """
        scenario = self._boundary_scenario(api)
        sample_id = scenario["sample"]["id"]
        abstractions = scenario["abstractions"]
        record_overread(api, abstractions[0]["id"], "DISAGREE", final_result="MISS")
        first = validate_success(api.evaluate_irr(sample_id, ANALYST))
        assert first["irr_ratio"] == pytest.approx(0.0)
        assert first["required_overread_fraction"] == pytest.approx(1.0), (
            "after the lone DISAGREE the ratio 0/1 is below 0.90 -> full tier, and the "
            "top-up flags the remaining submitted abstractions"
        )
        for abstraction in abstractions[1:]:
            record_overread(api, abstraction["id"], "AGREE")
        second = validate_success(api.evaluate_irr(sample_id, ANALYST))
        assert second["irr_ratio"] == pytest.approx(0.9), (
            "9 agreements over 10 latest reviews lands exactly on the 0.90 boundary"
        )
        assert second["irr_state"] == "FAILED", "0.90 is below the 0.95 pass gate"
        assert second["required_overread_fraction"] == pytest.approx(0.25), (
            "ratio >= 0.90 is inclusive for the mid tier (not demoted to 1.0)"
        )

    def test_finalize_rejected_when_irr_not_passed(self, api):
        """With flagged abstractions present and irr_state FAILED, finalization is
        blocked.

        PRD §3.5: "And whenever any abstraction carries `requires_overread` true, the
        sample's `irr_state` must be `PASSED`, else `ERR_IRR_NOT_PASSED`."

        Design: Difficulty/boundary_precision_check/irr_mid_tier_boundary_exactly_090
        """
        scenario = self._boundary_scenario(api)
        sample_id = scenario["sample"]["id"]
        abstractions = scenario["abstractions"]
        record_overread(api, abstractions[0]["id"], "DISAGREE", final_result="MISS")
        validate_success(api.evaluate_irr(sample_id, ANALYST))
        for abstraction in abstractions[1:]:
            record_overread(api, abstraction["id"], "AGREE")
        evaluated = validate_success(api.evaluate_irr(sample_id, ANALYST))
        assert evaluated["irr_state"] == "FAILED"
        resp = api.finalize_sample(sample_id, ANALYST)
        validate_error(resp, ApiErrorId.ERR_IRR_NOT_PASSED)


class TestOverReadReviewRecord:
    def test_overread_review_immutable_event(self, api):
        """The over-read row records outcome and reviewer, carries no
        version/updated_at, and a second review of the same round fails the state
        guard because the first moved the abstraction out of SUBMITTED.

        PRD §2.4: "A MemberEnrollmentSegment, an OverReadReview, and a
        SupplementalRecord each carry only `id` and `created_at`; both `updated_at`
        and `version` are absent on these three types, and no operation may expose or
        require them there."
        PRD §3.5: "At most one review exists per abstraction per submission round —
        the pair of `abstraction_id` and `resubmission_count` identifies a round — and
        this uniqueness needs no dedicated check: the first review always moves the
        abstraction out of `SUBMITTED`, so a second attempt against the same round
        fails the state guard with `ERR_INVALID_STATE`."

        Design: Corner/entities/overread_review_immutable_event
        """
        scenario = setup_hybrid_with_submitted_abstractions(api, ("M001",), ("HIT",), floor=1)
        a1 = scenario["abstractions"][0]
        assert a1["requires_overread"] is True
        record_overread(api, a1["id"], "AGREE", reviewer_id="orr-1")
        reviews, _ = list_abstraction_overreads(api, a1["id"])
        assert len(reviews) == 1
        review = reviews[0]
        assert review["outcome"] == "AGREE"
        assert review["reviewer_user_id"] == "orr-1"
        assert "version" not in review and "updated_at" not in review, (
            "the over-read row is a light event row: only id and created_at"
        )
        resp = api.create_overread(
            {"abstraction_id": a1["id"], "outcome": "AGREE"},
            make_overreader_headers("orr-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_overread_disagree_missing_final_result_invalid_request(self, api):
        """final_result is required exactly when the outcome is DISAGREE.

        PRD §3.5: "An `OverReader` records a review by supplying the `abstraction_id`,
        an `outcome` of `AGREE` or `DISAGREE`, and — required exactly when the outcome
        is `DISAGREE` — a `final_result` of `HIT` or `MISS` carrying the reviewer's
        corrected determination; a disagreeing review without `final_result` is
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/overread_disagree_missing_final_result_invalid_request
        """
        scenario = setup_hybrid_with_submitted_abstractions(api, ("M001",), ("HIT",), floor=1)
        a1 = scenario["abstractions"][0]
        resp = api.create_overread(
            {"abstraction_id": a1["id"], "outcome": "DISAGREE"},
            make_overreader_headers("orr-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_sod_self_overread_returns_403(self, api):
        """The abstraction's own author may not record its over-read, even with the
        OverReader role and a valid target state.

        PRD §2.8: "First, an over-read review may never be recorded by the abstractor
        who produced the abstraction: the reviewer's `X-User-ID` must differ from the
        abstraction's `abstractor_user_id`, and a violation is rejected with
        `ERR_SOD_SELF_OVERREAD`."

        Design: Corner/validations/sod_self_overread_returns_403
        """
        scenario = setup_hybrid_with_submitted_abstractions(api, ("M001",), ("HIT",), floor=1)
        a1 = scenario["abstractions"][0]
        assert a1["abstractor_user_id"] == "abs-1"
        resp = api.create_overread(
            {"abstraction_id": a1["id"], "outcome": "AGREE"},
            make_overreader_headers("abs-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_OVERREAD)


class TestAbstractionStateMachine:
    def test_abstraction_terminal_lockdown_overread_passed(self, api):
        """OVERREAD_PASSED is terminal: retract and re-submit are both rejected.

        PRD §4: "Retract an abstraction (`SUBMITTED` or `REMEDIATION` → `DRAFT`)"
        PRD §4: "Submit an abstraction (`DRAFT` or `REMEDIATION` → `SUBMITTED`)"
        PRD §2.9: "The target resource's own state machine must allow the transition —
        covering chase, abstraction, batch, sample, engagement, finding, and gap
        from-state checks — else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/abstraction_terminal_lockdown_overread_passed
        """
        scenario = setup_hybrid_with_submitted_abstractions(api, ("M001",), ("HIT",), floor=1)
        a1 = scenario["abstractions"][0]
        record_overread(api, a1["id"], "AGREE")
        assert get_abstraction(api, a1["id"])["status"] == "OVERREAD_PASSED"
        resp_retract = api.retract_abstraction(a1["id"], make_abstractor_headers("abs-1"))
        validate_error(resp_retract, ApiErrorId.ERR_INVALID_STATE)
        resp_submit = api.submit_abstraction(a1["id"], make_abstractor_headers("abs-1"))
        validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE)

    def test_duplicate_abstraction_returns_409(self, api):
        """A second non-terminal abstraction on the same chase is a constraint
        violation, not a state error — the chase is legitimately RECEIVED.

        PRD §3.5: "at most one non-terminal abstraction may exist per chase; because
        `CONFIRMED` and `OVERREAD_PASSED` are the abstraction's terminal states, a
        second concurrent draft on the same chase is rejected with
        `ERR_DUPLICATE_ABSTRACTION`."

        Design: Corner/validations/duplicate_abstraction_returns_409
        """
        scenario = _hybrid_scenario(api, ("M001",), 1)
        c1 = scenario["chases"][0]
        receive_chases(api, [c1])
        first = api.create_abstraction(
            create_abstraction_payload(c1["id"], "HIT"), make_abstractor_headers("abs-1")
        )
        validate_success(first, 201)
        resp = api.create_abstraction(
            create_abstraction_payload(c1["id"], "MISS"), make_abstractor_headers("abs-2")
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ABSTRACTION)


class TestFinalizeGates:
    def test_finalize_overreads_outstanding_returns_422(self, api):
        """A flagged SUBMITTED abstraction without an over-read blocks finalize;
        the chases are all resolved so the over-read gate is the one that fires.

        PRD §3.5: "No abstraction in `SUBMITTED` with `requires_overread` true may
        lack an over-read — outstanding reviews block with
        `ERR_OVERREADS_OUTSTANDING`."

        Design: Corner/validations/finalize_overreads_outstanding_returns_422
        """
        scenario = setup_hybrid_with_submitted_abstractions(api, ("M001",), ("HIT",), floor=1)
        a1 = scenario["abstractions"][0]
        assert a1["requires_overread"] is True and a1["status"] == "SUBMITTED"
        resp = api.finalize_sample(scenario["sample"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_OVERREADS_OUTSTANDING)

    def test_finalize_chases_in_flight_returns_422(self, api):
        """A chase still REQUESTED blocks finalize.

        PRD §3.5: "No chase of the sample may be in `REQUESTED` or
        `REJECTED_UNREADABLE` — charts still in flight block with
        `ERR_CHASES_IN_FLIGHT`."

        Design: Corner/validations/finalize_chases_in_flight_returns_422
        """
        scenario = setup_hybrid_sample(api, member_refs=("M001", "M002"), floor=2)
        c1, c2 = scenario["chases"]
        receive_chases(api, [c1])
        a1 = create_submitted_abstraction(api, c1["id"], "HIT")
        record_overread(api, a1["id"], "AGREE")
        get_success_data(api.evaluate_irr(scenario["sample"]["id"], ANALYST))
        assert get_chase(api, c2["id"])["status"] == "REQUESTED"
        resp = api.finalize_sample(scenario["sample"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_CHASES_IN_FLIGHT)

    def test_finalize_unabstracted_charts_returns_422(self, api):
        """A RECEIVED chase with no submitted abstraction blocks finalize; RECEIVED
        is not in flight, so the unabstracted-charts gate is the one that fires.

        PRD §3.5: "Every chase in `RECEIVED` must have an abstraction in `SUBMITTED`,
        `CONFIRMED`, or `OVERREAD_PASSED` — a received but unabstracted chart blocks
        with `ERR_UNABSTRACTED_CHARTS`."

        Design: Corner/validations/finalize_unabstracted_charts_returns_422
        """
        scenario = setup_hybrid_sample(api, member_refs=("M001", "M002"), floor=2)
        c1, c2 = scenario["chases"]
        receive_chases(api, [c1, c2])
        a1 = create_submitted_abstraction(api, c1["id"], "HIT")
        record_overread(api, a1["id"], "AGREE")
        get_success_data(api.evaluate_irr(scenario["sample"]["id"], ANALYST))
        assert get_chase(api, c2["id"])["status"] == "RECEIVED"
        resp = api.finalize_sample(scenario["sample"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_UNABSTRACTED_CHARTS)
