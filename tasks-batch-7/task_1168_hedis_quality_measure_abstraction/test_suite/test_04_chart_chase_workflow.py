"""Chart chase retrieval workflow: cyclic re-chase loops, coverage conservation,
and the sample-state guard on chase mutations.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_submitted_abstraction,
    get_chase,
    list_sample_chases,
    record_overread,
    receive_chases,
    setup_hybrid_sample,
    validate_error,
    validate_success,
    get_success_data,
)

ANALYST = TEST_USERS["quality_analyst_headers"]

HYBRID_SPEC = {"age_min": 50, "age_max": 74, "gender_requirement": "F"}
MEMBER_ATTRS = {
    "M001": {"birth_date": "1960-01-01T00:00:00Z", "gender": "F"},
    "M002": {"birth_date": "1960-01-01T00:00:00Z", "gender": "F"},
    "M003": {"birth_date": "1960-01-01T00:00:00Z", "gender": "F"},
    "M1": {"birth_date": "1960-01-01T00:00:00Z", "gender": "F"},
    "M2": {"birth_date": "1960-01-01T00:00:00Z", "gender": "F"},
    "M3": {"birth_date": "1960-01-01T00:00:00Z", "gender": "F"},
}


def _chase_scenario(api, member_refs=("M001", "M002"), floor=2):
    return setup_hybrid_sample(
        api,
        member_refs=member_refs,
        floor=floor,
        spec_overrides=dict(HYBRID_SPEC, hybrid_policy="SAMPLE_ONLY"),
        member_attrs={k: v for k, v in MEMBER_ATTRS.items() if k in member_refs},
        season_overrides={"approved_supplemental_sources": ["LAB_FEED"]},
    )


class TestRechaseCycles:
    def test_rechase_loops_increment_chase_round(self, api):
        """Both re-chase loops (REJECTED_UNREADABLE and WITHDRAWN) re-enter
        REQUESTED and increment chase_round by exactly 1 per traversal.

        PRD §3.4: "Rejecting an unreadable chart moves `RECEIVED` to
        `REJECTED_UNREADABLE`. Withdrawing a pending request moves `REQUESTED` to
        `WITHDRAWN`. Re-chasing returns a chase to `REQUESTED` from either
        `REJECTED_UNREADABLE` or `WITHDRAWN`, incrementing `chase_round` by exactly 1
        on every re-chase — the round counter is the audit trail of retrieval
        attempts."

        Design: Difficulty/non_linear_state_machine/chart_chase_rechase_cycles
        """
        scenario = _chase_scenario(api)
        c1 = scenario["chases"][0]
        assert c1["member_ref"] == "M001"
        assert c1["status"] == "REQUESTED" and c1["chase_round"] == 1

        step = validate_success(api.receive_chase(c1["id"], ANALYST))
        assert step["status"] == "RECEIVED"
        step = validate_success(api.reject_chase_unreadable(c1["id"], ANALYST))
        assert step["status"] == "REJECTED_UNREADABLE"
        step = validate_success(api.rechase_chase(c1["id"], ANALYST))
        assert step["status"] == "REQUESTED" and step["chase_round"] == 2, (
            f"first re-chase loop must bump chase_round to 2, got {step['chase_round']}"
        )
        step = validate_success(api.withdraw_chase(c1["id"], ANALYST))
        assert step["status"] == "WITHDRAWN"
        step = validate_success(api.rechase_chase(c1["id"], ANALYST))
        assert step["status"] == "REQUESTED" and step["chase_round"] == 3, (
            f"second re-chase loop must bump chase_round to 3, got {step['chase_round']}"
        )
        step = validate_success(api.receive_chase(c1["id"], ANALYST))
        assert step["status"] == "RECEIVED"

    def test_reject_unreadable_from_requested_has_no_side_effects(self, api):
        """Reject-unreadable is not a legal transition from REQUESTED; the failed
        call leaves the chase untouched.

        PRD §3.4: "Rejecting an unreadable chart moves `RECEIVED` to
        `REJECTED_UNREADABLE`."
        PRD §2.9: "The target resource's own state machine must allow the transition —
        covering chase, abstraction, batch, sample, engagement, finding, and gap
        from-state checks — else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/chart_chase_rechase_cycles
        """
        scenario = _chase_scenario(api)
        c2 = scenario["chases"][1]
        assert c2["member_ref"] == "M002"
        resp = api.reject_chase_unreadable(c2["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_chase(api, c2["id"])
        assert after["status"] == "REQUESTED"
        assert after["chase_round"] == 1


class TestWithdrawRechaseCoverageConservation:
    def test_withdraw_preserves_chase_coverage(self, api):
        """Withdrawing a chase mutates only its status: the sample still holds one
        chase row per sampled member.

        PRD §3.4: "Withdrawing a pending request moves `REQUESTED` to `WITHDRAWN`."
        PRD §3.4: "Each selected entry's `is_sampled` flips to true, and one chart
        chase is minted per selected entry: status `REQUESTED`, `chase_round` 1"

        Design: Difficulty/compensating_invariant/withdraw_rechase_chase_coverage_conservation
        """
        scenario = _chase_scenario(api, member_refs=("M1", "M2", "M3"), floor=3)
        sample = scenario["sample"]
        chases = scenario["chases"]
        assert sample["drawn_size"] == 3 and chases[0]["member_ref"] == "M1"
        withdrawn = validate_success(api.withdraw_chase(chases[0]["id"], ANALYST))
        assert withdrawn["status"] == "WITHDRAWN"
        mid, _ = list_sample_chases(api, sample["id"])
        assert [c["member_ref"] for c in mid] == ["M1", "M2", "M3"], (
            "withdraw must not destroy the chase coverage rows"
        )
        assert mid[0]["status"] == "WITHDRAWN"
        assert len(mid) == 3 == sample["drawn_size"]

    def test_rechase_restores_coverage_with_round_increment(self, api):
        """The withdraw/re-chase pair restores live coverage: same three rows, the
        re-chased chase back to REQUESTED with chase_round incremented by 1.

        PRD §3.4: "Re-chasing returns a chase to `REQUESTED` from either
        `REJECTED_UNREADABLE` or `WITHDRAWN`, incrementing `chase_round` by exactly 1
        on every re-chase"

        Design: Difficulty/compensating_invariant/withdraw_rechase_chase_coverage_conservation
        """
        scenario = _chase_scenario(api, member_refs=("M1", "M2", "M3"), floor=3)
        sample = scenario["sample"]
        chases = scenario["chases"]
        validate_success(api.withdraw_chase(chases[0]["id"], ANALYST))
        rechased = validate_success(api.rechase_chase(chases[0]["id"], ANALYST))
        assert rechased["status"] == "REQUESTED" and rechased["chase_round"] == 2
        final, _ = list_sample_chases(api, sample["id"])
        assert [c["member_ref"] for c in final] == ["M1", "M2", "M3"]
        assert len(final) == sample["drawn_size"] == 3


class TestChaseGuardAfterFinalize:
    def test_chase_rechase_blocked_once_sample_finalized(self, api):
        """Every analyst-driven chase mutation requires the owning sample to still
        be DRAWN; once the sample is FINALIZED even a legal-from-state re-chase of a
        WITHDRAWN chase is rejected.

        PRD §3.4: "Every one of these analyst-driven chase mutations requires the
        owning sample to still be `DRAWN` and otherwise fails with
        `ERR_INVALID_STATE`; each also increments the chase's `version` by 1."

        Design: Corner/state_machines/chase_rechase_blocked_once_sample_finalized
        """
        scenario = setup_hybrid_sample(
            api,
            member_refs=("M001", "M002"),
            floor=2,
            spec_overrides={"age_min": 0, "age_max": 100, "hybrid_policy": "SAMPLE_ONLY"},
            season_overrides={"approved_supplemental_sources": ["LAB_FEED"]},
        )
        c1, c2 = scenario["chases"]
        receive_chases(api, [c1])
        a1 = create_submitted_abstraction(api, c1["id"], "HIT")
        assert a1["requires_overread"] is True
        record_overread(api, a1["id"], "AGREE")
        validate_success(api.withdraw_chase(c2["id"], ANALYST))
        get_success_data(api.evaluate_irr(scenario["sample"]["id"], ANALYST))
        finalized = validate_success(api.finalize_sample(scenario["sample"]["id"], ANALYST))
        assert finalized["status"] == "FINALIZED"

        resp = api.rechase_chase(c2["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_chase(api, c2["id"])
        assert after["status"] == "WITHDRAWN" and after["chase_round"] == 1


class TestChaseExistenceOrdering:
    def test_receive_unknown_chase_returns_not_found(self, api):
        """Existence is checked before state: receiving a non-existent chase yields
        ERR_NOT_FOUND, never a state error.

        PRD §2.10: "Where a URL contains path parameters, each identifier is resolved
        in left-to-right order, and the first identifier that fails to resolve yields
        `ERR_NOT_FOUND` without evaluating the remainder of the request."

        Design: Corner/validations/receive_unknown_chase_returns_not_found
        """
        resp = api.receive_chase(NON_EXISTENT_UUID, ANALYST)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
