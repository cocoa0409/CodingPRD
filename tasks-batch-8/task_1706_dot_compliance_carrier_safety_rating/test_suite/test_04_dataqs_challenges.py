"""The DataQs challenge loop: review states, bounded remand cycle, terminal
lockdown, and the uphold/overturn cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_timestamp_at,
    get_challenge,
    get_driver,
    get_inspection,
    get_premium_model,
    get_violation,
    list_snapshots,
    make_challenge,
    make_inspection_with_violation,
    run_cycle,
    set_clock,
    setup_overturn_cascade_case,
    setup_remand_loop_case,
    setup_uphold_conservation_case,
    validate_error,
    validate_success,
)


class TestChallengeStateMachine:
    def test_challenge_decide_from_submitted_rejected(self, api, admin_headers):
        """PRD §3.4: "The decision call takes an `outcome` and requires the
        challenge to be `UNDER_REVIEW`; from any other state — including a
        second decision on a challenge that has already reached a terminal state
        — it is rejected with `ERR_CHALLENGE_NOT_UNDER_REVIEW`."

        Design: Corner/state_machines/challenge_decide_from_submitted_rejected
        """
        _, _, _, _, violation = make_inspection_with_violation(
            severity_weight=3,
            carrier_overrides={"dot_number": "DOT-2101"},
            inspection_overrides={"report_number": "R-2101", "inspection_level": 2, "state_code": "MT"},
        )
        challenge = make_challenge(violation["id"], reason_code="OTHER", evidence_note="docs")
        assert challenge["status"] == "SUBMITTED"

        resp = api.decide_challenge(challenge["id"], {"outcome": "UPHELD"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_CHALLENGE_NOT_UNDER_REVIEW)
        assert get_challenge(challenge["id"])["status"] == "SUBMITTED"

    def test_challenge_terminal_lockdown_after_upheld(
        self, api, admin_headers, analyst_headers
    ):
        """PRD §3.4: "The decision call takes an `outcome` and requires the
        challenge to be `UNDER_REVIEW`; from any other state — including a
        second decision on a challenge that has already reached a terminal state
        — it is rejected with `ERR_CHALLENGE_NOT_UNDER_REVIEW`."
        PRD §3.4: "A remanded challenge can be re-filed by a `ComplianceAnalyst`
        with a fresh `evidence_note`, moving `REMANDED` → `SUBMITTED`; from any
        other state resubmission is rejected with `ERR_CHALLENGE_NOT_REMANDED`."

        Design: Corner/state_machines/challenge_terminal_lockdown_after_upheld
        """
        _, _, _, _, violation = make_inspection_with_violation(
            severity_weight=3,
            carrier_overrides={"dot_number": "DOT-2102"},
            inspection_overrides={"report_number": "R-2102", "inspection_level": 2, "state_code": "MT"},
        )
        challenge = make_challenge(violation["id"], reason_code="OTHER", evidence_note="docs")
        validate_success(api.start_review_challenge(challenge["id"], admin_headers), 200)
        upheld = validate_success(
            api.decide_challenge(challenge["id"], {"outcome": "UPHELD"}, admin_headers), 200
        )
        assert upheld["status"] == "UPHELD"

        second = api.decide_challenge(challenge["id"], {"outcome": "OVERTURNED"}, admin_headers)
        validate_error(second, ApiErrorId.ERR_CHALLENGE_NOT_UNDER_REVIEW)

        resubmit = api.resubmit_challenge(
            challenge["id"], {"evidence_note": "retry"}, analyst_headers
        )
        validate_error(resubmit, ApiErrorId.ERR_CHALLENGE_NOT_REMANDED)

    def test_challenge_start_review_twice_and_resubmit_when_not_remanded_rejected(
        self, api, admin_headers, analyst_headers
    ):
        """PRD §3.4: "Starting review moves `SUBMITTED` → `UNDER_REVIEW`, and
        from any other state is rejected with `ERR_CHALLENGE_NOT_SUBMITTED`."
        PRD §3.4: "from any other state resubmission is rejected with
        `ERR_CHALLENGE_NOT_REMANDED`."

        Design: Corner/validations/challenge_start_review_twice_and_resubmit_when_not_remanded_rejected
        """
        _, _, _, _, violation = make_inspection_with_violation(
            severity_weight=3,
            carrier_overrides={"dot_number": "DOT-2323"},
            inspection_overrides={"report_number": "R-2323", "state_code": "AL"},
        )
        challenge = make_challenge(violation["id"], reason_code="OTHER", evidence_note="docs")

        validate_success(api.start_review_challenge(challenge["id"], admin_headers), 200)
        second = api.start_review_challenge(challenge["id"], admin_headers)
        validate_error(second, ApiErrorId.ERR_CHALLENGE_NOT_SUBMITTED)

        resubmit = api.resubmit_challenge(
            challenge["id"], {"evidence_note": "early resubmit"}, analyst_headers
        )
        validate_error(resubmit, ApiErrorId.ERR_CHALLENGE_NOT_REMANDED)


class TestRemandCycleBound:
    def test_third_remand_rejected_at_limit(self, api, admin_headers):
        """PRD §3.4: "`REMANDED` sends the challenge back for more evidence:
        `remand_count` increments by one, `decided_at` is stamped with the
        clock, and the violation remains `CHALLENGED`. A challenge may be
        remanded at most twice — deciding `REMANDED` when `remand_count` has
        already reached 2 is rejected with `ERR_REMAND_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/dataqs_remand_cycle_bounded
        """
        env = setup_remand_loop_case()
        challenge = env["challenge"]
        assert challenge["remand_count"] == 2, "the loop iterated twice (1, then 2)"
        assert challenge["status"] == "UNDER_REVIEW"
        assert get_violation(env["violation"]["id"])["status"] == "CHALLENGED"

        resp = api.decide_challenge(challenge["id"], {"outcome": "REMANDED"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_REMAND_LIMIT_REACHED)

        after = get_challenge(challenge["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["remand_count"] == 2

    def test_upheld_still_succeeds_after_remand_limit(self, api, admin_headers):
        """PRD §3.4: "A challenge may be remanded at most twice — deciding
        `REMANDED` when `remand_count` has already reached 2 is rejected with
        `ERR_REMAND_LIMIT_REACHED`." and "`UPHELD` closes the challenge and
        returns the violation `CHALLENGED` → `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/dataqs_remand_cycle_bounded
        """
        env = setup_remand_loop_case()
        challenge = env["challenge"]
        # The bounded loop is full: a third REMAND is refused...
        validate_error(
            api.decide_challenge(challenge["id"], {"outcome": "REMANDED"}, admin_headers),
            ApiErrorId.ERR_REMAND_LIMIT_REACHED,
        )
        # ...but the challenge remains decidable: UPHELD closes it.
        upheld = validate_success(
            api.decide_challenge(challenge["id"], {"outcome": "UPHELD"}, admin_headers), 200
        )
        assert upheld["status"] == "UPHELD"
        assert get_violation(env["violation"]["id"])["status"] == "ACTIVE"


class TestUpholdCompensatingInvariant:
    def test_uphold_conserves_weighted_points(self, api, admin_headers):
        """PRD §3.4: "`UPHELD` closes the challenge and returns the violation
        `CHALLENGED` → `ACTIVE`. The inspection's `total_weighted_points` and
        the driver's `risk_score` are both recomputed but remain numerically
        unchanged, since a `CHALLENGED` violation was already counted in each —
        the compensating invariant that keeps official figures stable through
        adjudication."

        Design: Difficulty/compensating_invariant/challenge_uphold_conserves_weighted_points
        """
        env = setup_uphold_conservation_case()
        assert env["snap1"]["official_measure"] == pytest.approx(3.00, abs=0.001)
        assert env["snap1"]["provisional_measure"] == pytest.approx(3.00, abs=0.001)
        assert get_inspection(env["inspection"]["id"])["total_weighted_points"] == 15
        assert get_driver(env["driver"]["id"])["risk_score"] == 15

        challenge = make_challenge(
            env["violation"]["id"],
            reason_code="INCORRECT_DATA",
            evidence_note="Contesting brake citation",
        )
        validate_success(api.start_review_challenge(challenge["id"], admin_headers), 200)
        validate_success(
            api.decide_challenge(challenge["id"], {"outcome": "UPHELD"}, admin_headers), 200
        )

        assert get_violation(env["violation"]["id"])["status"] == "ACTIVE"
        assert get_inspection(env["inspection"]["id"])["total_weighted_points"] == 15
        assert get_driver(env["driver"]["id"])["risk_score"] == 15

    def test_uphold_conserves_next_cycle_measures(self, api, admin_headers):
        """PRD §3.4: "The inspection's `total_weighted_points` and the driver's
        `risk_score` are both recomputed but remain numerically unchanged, since
        a `CHALLENGED` violation was already counted in each — the compensating
        invariant that keeps official figures stable through adjudication."
        PRD §3.10: "the official variant includes violations in `ACTIVE` or
        `CHALLENGED` status, while the provisional variant counts only `ACTIVE`
        ones, and `REMOVED` violations are excluded from both."

        Design: Difficulty/compensating_invariant/challenge_uphold_conserves_weighted_points
        """
        env = setup_uphold_conservation_case()
        challenge = make_challenge(
            env["violation"]["id"],
            reason_code="INCORRECT_DATA",
            evidence_note="Contesting brake citation",
        )
        validate_success(api.start_review_challenge(challenge["id"], admin_headers), 200)
        validate_success(
            api.decide_challenge(challenge["id"], {"outcome": "UPHELD"}, admin_headers), 200
        )

        set_clock("2026-08-02T00:00:00Z")
        run_cycle(env["carrier"]["id"])
        snaps = list_snapshots(
            carrier_id=env["carrier"]["id"], category_id=env["category"]["id"]
        )
        assert len(snaps) == 2
        snap2 = [s for s in snaps if s["id"] != env["snap1"]["id"]][0]
        assert snap2["official_measure"] == pytest.approx(3.00, abs=0.001)
        assert snap2["provisional_measure"] == pytest.approx(3.00, abs=0.001)
        assert snap2["official_measure"] == pytest.approx(
            env["snap1"]["official_measure"], abs=0.0001
        )
        assert snap2["provisional_measure"] == pytest.approx(
            env["snap1"]["provisional_measure"], abs=0.0001
        )


class TestOverturnCascade:
    def test_overturn_removes_violation_and_recomputes_points(
        self, api, admin_headers
    ):
        """PRD §3.4: "`OVERTURNED` closes the challenge and moves the violation
        `CHALLENGED` → `REMOVED`, which is terminal. The inspection's
        `total_weighted_points` drops by the removed violation's
        `weighted_points`, the driver's `risk_score` is recomputed, and if the
        driver's `risk_tier` changes, every `QUOTED` premium model of the
        carrier goes `STALE`. The challenge's `decided_at` is stamped with the
        clock."
        PRD §3.2: "The `risk_tier` derives from it: `LOW` below 10, `MEDIUM`
        from 10 through 19, and `HIGH` at 20 or above."

        Design: Difficulty/transitive_cascade/cascade_overturn_to_premium_stale
        """
        env = setup_overturn_cascade_case()
        assert env["model"]["computed_premium_cents"] == 107100, (
            "100000 base x 1.05 NONE factor x 1.02 driver loading at quote time"
        )
        assert get_driver(env["driver"]["id"])["risk_tier"] == "HIGH"

        decided = validate_success(
            api.decide_challenge(
                env["challenge"]["id"], {"outcome": "OVERTURNED"}, admin_headers
            ),
            200,
        )
        assert decided["status"] == "OVERTURNED"

        assert get_violation(env["v1"]["id"])["status"] == "REMOVED"
        assert get_inspection(env["inspection"]["id"])["total_weighted_points"] == 18
        driver = get_driver(env["driver"]["id"])
        assert driver["risk_score"] == 18
        assert driver["risk_tier"] == "MEDIUM"

    def test_overturn_tier_change_marks_quoted_premium_stale(
        self, api, admin_headers
    ):
        """PRD §3.4: "if the driver's `risk_tier` changes, every `QUOTED`
        premium model of the carrier goes `STALE`. The challenge's `decided_at`
        is stamped with the clock."

        Design: Difficulty/transitive_cascade/cascade_overturn_to_premium_stale
        """
        env = setup_overturn_cascade_case()
        decided = validate_success(
            api.decide_challenge(
                env["challenge"]["id"], {"outcome": "OVERTURNED"}, admin_headers
            ),
            200,
        )
        assert decided["status"] == "OVERTURNED"
        assert_timestamp_at(decided["decided_at"], "2026-08-01T00:00:00")

        model = get_premium_model(env["model"]["id"])
        assert model["status"] == "STALE", (
            "driver tier crossed HIGH -> MEDIUM, so the QUOTED model is swept"
        )
