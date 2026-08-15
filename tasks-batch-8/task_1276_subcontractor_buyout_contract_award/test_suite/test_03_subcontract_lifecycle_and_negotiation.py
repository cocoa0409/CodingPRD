"""Subcontract draft creation, the bounded negotiation loop, award/un-award
compensation, terminal-state lockdown, and the retainage band."""
import pytest

from test_helpers import (
    BL,
    OM,
    ApiErrorId,
    api_client,
    assert_negotiation_round,
    create_draft_subcontract,
    create_open_project,
    get_success_data,
    recommend,
    setup_awarded_subcontract,
    setup_executed_with_approved_sov,
    setup_leveling_package,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_sub(name, number, trade_code, **kwargs):
    """Leveling package (2 bids, last withdrawn) + one DRAFT subcontract."""
    proj, proj_v = create_open_project(name, number)
    ctx = setup_leveling_package(
        proj["id"], proj_v, name=name, trade_code=trade_code, **kwargs,
    )
    sub = create_draft_subcontract(
        ctx["package"]["id"], ctx["bids"][0]["id"], f"{name} Sub 1")
    return proj, ctx, sub


class TestNegotiationCycleCap:

    def test_two_full_loops_land_at_round_two(self):
        """PRD section 3.5: "Negotiation is a bounded cycle between `DRAFT`
        and `PENDING_AWARD`, and the bound is two: the system allows at most
        two `PENDING_AWARD → DRAFT` loops per subcontract."
        PRD section 3.5: "The loop increments `negotiation_round` by 1 and
        resets `contract_value_cents` to 0, ready for another attempt."

        Design: Difficulty/non_linear_state_machine/negotiation_cycle_pending_to_draft_loop_with_two_round_cap
        """
        _proj, _ctx, sub = _draft_sub("P-NL1", "NL1", "NL1-08")
        recommend(sub["id"], 9_000_000)
        validate_success(api_client.renegotiate(
            sub["id"], {"reason": "owner pushed back on exclusions"}, BL))
        recommend(sub["id"], 9_100_000)
        validate_success(api_client.renegotiate(
            sub["id"], {"reason": "second round"}, BL))
        after = get_success_data(api_client.get_subcontract(sub["id"], BL))
        assert after["negotiation_round"] == 2, \
            f"two loops must leave negotiation_round == 2, got {after['negotiation_round']}"
        assert after["status"] == "DRAFT"
        assert after["contract_value_cents"] == 0, \
            "renegotiate resets the pinned value"

    def test_third_recommend_rejected_at_round_cap(self):
        """PRD section 3.5: "the subcontract's `negotiation_round` must still
        be below the two-round cap; a third attempt is rejected with
        `ERR_NEGOTIATION_ROUND_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/negotiation_cycle_pending_to_draft_loop_with_two_round_cap
        """
        _proj, _ctx, sub = _draft_sub("P-NL1B", "NL1B", "NL1B-08")
        recommend(sub["id"], 9_000_000)
        validate_success(api_client.renegotiate(sub["id"], {}, BL))
        recommend(sub["id"], 9_100_000)
        validate_success(api_client.renegotiate(sub["id"], {}, BL))
        resp = api_client.recommend_award(
            sub["id"], {"contract_value_cents": 9_200_000}, BL)
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_EXCEEDED)
        after = get_success_data(api_client.get_subcontract(sub["id"], BL))
        assert after["status"] == "DRAFT", \
            "no state drift from the rejected recommend"


class TestNegotiationRoundLedger:

    def test_round_recorded_with_index_value_and_logical_clock(self):
        """PRD section 3.5: "a `NegotiationRound` is recorded against the
        subcontract with `round_index` equal to `negotiation_round + 1`, the
        submitted `proposed_value_cents`, the `allowance_dispositions` and
        `alternate_selections` arrays, an optional `note`, a `recorded_at`
        taken from the project logical clock".

        Design: Corner/entities/negotiation_round_rows_immutable_no_version
        """
        proj, _ctx, sub = _draft_sub("P-E6", "E6", "E6-26")
        recommend(sub["id"], 9_000_000)
        data, _meta = validate_paginated(
            api_client.list_negotiation_rounds(sub["id"], BL))
        assert len(data) == 1
        row = data[0]
        assert_negotiation_round(row)
        assert row["round_index"] == 1
        assert row["proposed_value_cents"] == 9_000_000
        proj_after = get_success_data(api_client.get_project(proj["id"], BL))
        assert row["recorded_at"] == proj_after["current_time_utc"], \
            "recorded_at is taken from the project logical clock"

    def test_round_rows_carry_no_version_or_updated_at(self):
        """PRD section 2.5: "The one exception is the `NegotiationRound`,
        which is an append-only record: it carries `id` and `created_at` but
        no `updated_at` and no `version`, because a round is never modified
        once recorded."

        Design: Corner/entities/negotiation_round_rows_immutable_no_version
        """
        _proj, _ctx, sub = _draft_sub("P-E6B", "E6B", "E6B-26")
        recommend(sub["id"], 9_000_000)
        data, _meta = validate_paginated(
            api_client.list_negotiation_rounds(sub["id"], BL))
        assert len(data) == 1
        assert "version" not in data[0], "append-only record must omit version"
        assert "updated_at" not in data[0], \
            "append-only record must omit updated_at"


class TestSubcontractCreateDefaults:

    def test_subcontract_create_initializes_derived_fields(self):
        """PRD section 3.4: "A fresh subcontract draft lands in `DRAFT` with
        `contract_value_cents` at 0, `negotiation_round` at 0,
        `insurance_status` at `MISSING`, `cumulative_co_cents` at 0,
        `default_flag` false, and `bonding_requirement` at `PENDING_DECISION`
        — or directly at `NOT_REQUIRED` when the package's `bonding_policy`
        is `WAIVED`."

        Design: Corner/entities/subcontract_create_initializes_derived_fields
        """
        _proj, _ctx, sub = _draft_sub("P-E5", "E5", "E5-26")
        assert sub["status"] == "DRAFT"
        assert sub["contract_value_cents"] == 0
        assert sub["negotiation_round"] == 0
        assert sub["insurance_status"] == "MISSING"
        assert sub["sov_status"] == "DRAFT"
        assert sub["bonding_requirement"] == "NOT_REQUIRED", \
            "WAIVED policy initializes the requirement without a BondDecision"


class TestRetainageBand:

    def test_retainage_below_band_floor_rejected(self):
        """PRD section 3.4: "The retainage band is enforced at draft
        creation: a `payment_terms` whose `retainage_pct` falls outside the
        inclusive band from 0.05 to 0.10 is rejected with
        `ERR_RETAINAGE_OUT_OF_BAND` (HTTP 422)."

        Design: Corner/validations/retainage_band_boundary_enforcement
        """
        proj, proj_v = create_open_project("P-V5", "V5")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="V5", trade_code="V5-26",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_100_000, "2026-05-15T13:00:00Z"),
                  (9_200_000, "2026-05-15T14:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        # bids[1] is PLACED and unreferenced, so only the retainage band
        # check can fail on this request.
        resp = api_client.create_subcontract(
            pkg["id"],
            {"subcontractor_name": "AA",
             "source_bid_id": ctx["bids"][1]["id"],
             "flow_down_terms": "fd",
             "payment_terms": {"retainage_pct": 0.04, "pay_if_paid": True},
             "change_authority_limits": [
                 {"max_value_cents": -1, "max_cumulative_pct": -1,
                  "roles": ["OperationsManager"]}]},
            BL,
        )
        validate_error(resp, ApiErrorId.ERR_RETAINAGE_OUT_OF_BAND,
                       expected_status=422)

    def test_retainage_at_band_floor_accepted(self):
        """PRD section 3.4: "a `payment_terms` whose `retainage_pct` falls
        outside the inclusive band from 0.05 to 0.10 is rejected with
        `ERR_RETAINAGE_OUT_OF_BAND` (HTTP 422)."

        Design: Corner/validations/retainage_band_boundary_enforcement
        """
        proj2, proj_v2 = create_open_project("P-V5C", "V5C")
        ctx2 = setup_leveling_package(
            proj2["id"], proj_v2, name="V5C", trade_code="V5C-26",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_100_000, "2026-05-15T13:00:00Z"),
                  (9_200_000, "2026-05-15T14:00:00Z")),
            withdraw_last=True,
        )
        resp = api_client.create_subcontract(
            ctx2["package"]["id"],
            {"subcontractor_name": "AB",
             "source_bid_id": ctx2["bids"][1]["id"],
             "flow_down_terms": "fd",
             "payment_terms": {"retainage_pct": 0.05, "pay_if_paid": True},
             "change_authority_limits": [
                 {"max_value_cents": -1, "max_cumulative_pct": -1,
                  "roles": ["OperationsManager"]}]},
            BL,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT", "0.05 floor is inclusive"


class TestInvalidLifecycleTransitions:

    def test_issue_from_draft_rejected(self):
        """PRD section 3.6: "any request for a transition the current state
        does not support is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/issue_from_draft_rejected
        """
        _proj, _ctx, sub = _draft_sub("P-S3", "S3", "S3-26")
        resp = api_client.issue_subcontract(sub["id"], BL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_execute_from_awarded_rejected(self):
        """PRD section 3.6: "Execution — recording the signed subcontract,
        `ISSUED → EXECUTED`, again by a `BuyoutLead`".

        Design: Corner/state_machines/execute_from_awarded_rejected
        """
        proj, proj_v = create_open_project("P-S4", "S4")
        ctx = setup_awarded_subcontract(
            proj["id"], proj_v, name="S4", trade_code="S4-26")
        sub = ctx["subcontract"]
        assert get_success_data(
            api_client.get_subcontract(sub["id"], BL))["status"] == "AWARDED"
        resp = api_client.execute_subcontract(sub["id"], BL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_terminate_draft_then_recommend_rejected_terminal(self):
        """PRD section 3.6: "A draft subcontract that will never proceed can
        be terminated by an `OperationsManager` — `DRAFT → TERMINATED` with
        an optional `reason`. Operations against a subcontract that has
        reached `DEFAULTED`, `REPLACED`, or `TERMINATED` are rejected with
        `ERR_SUBCONTRACT_TERMINAL`".

        Design: Corner/state_machines/terminate_draft_then_recommend_rejected_terminal
        """
        _proj, _ctx, sub = _draft_sub("P-S6", "S6", "S6-26")
        resp = api_client.terminate_subcontract(sub["id"], {}, OM)
        data = validate_success(resp)
        assert data["status"] == "TERMINATED"
        resp = api_client.recommend_award(
            sub["id"], {"contract_value_cents": 9_000_000}, BL)
        validate_error(resp, ApiErrorId.ERR_SUBCONTRACT_TERMINAL)

    def test_declare_default_with_approved_sov_rejected(self):
        """PRD section 3.9: "it is blocked outright when an `APPROVED`
        schedule of values exists on the subcontract — that path must go
        through replacement instead, and the attempt is rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/declare_default_with_approved_sov_rejected
        """
        proj, proj_v = create_open_project("P-S5", "S5")
        ctx = setup_executed_with_approved_sov(
            proj["id"], proj_v, name="S5", trade_code="S5-26")
        sub = ctx["subcontract"]
        resp = api_client.declare_default(
            sub["id"],
            {"reason": "walked off",
             "estimated_replacement_cost_cents": 10_000_000},
            OM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api_client.get_subcontract(sub["id"], BL))
        assert after["status"] == "EXECUTED", "no drift from the rejected default"


class TestAwardThenUnawardCompensation:

    def _setup_pending_award_with_awarded_bid(self):
        proj, proj_v = create_open_project("P-CI1", "CI1")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="CI1", trade_code="CI1-05",
            bids=((9_000_000, "2026-05-15T12:00:00Z"),
                  (9_100_000, "2026-05-15T13:00:00Z")),
            withdraw_last=True,
        )
        pkg = ctx["package"]
        bid = ctx["bids"][0]
        sub = create_draft_subcontract(pkg["id"], bid["id"], "Phi Plumb")
        pre = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        recommend(sub["id"], 9_000_000)
        validate_success(api_client.award_bid(pkg["id"], bid["id"], BL))
        return pkg, bid, sub, pre["awarded_value_cents"]

    def test_unaward_restores_bid_and_subcontract_state(self):
        """PRD section 3.5: "if a bid was awarded but the linked subcontract
        is still in `PENDING_AWARD`, a `BuyoutLead` or `OperationsManager`
        may retract the bid award, moving the bid `AWARDED → PLACED` and
        dragging the linked subcontract back from `PENDING_AWARD` to `DRAFT`
        with its `contract_value_cents` reset to 0."

        Design: Difficulty/compensating_invariant/award_then_unaward_restores_bid_and_package_state_exactly
        """
        pkg, bid, sub, tp_pre = self._setup_pending_award_with_awarded_bid()
        mid_sub = get_success_data(api_client.get_subcontract(sub["id"], BL))
        mid_bid = get_success_data(api_client.get_bid(bid["id"], BL))
        assert mid_sub["status"] == "PENDING_AWARD"
        assert mid_sub["contract_value_cents"] == 9_000_000
        assert mid_bid["status"] == "AWARDED"

        validate_success(api_client.unaward_bid(bid["id"], BL))

        post_bid = get_success_data(api_client.get_bid(bid["id"], BL))
        post_sub = get_success_data(api_client.get_subcontract(sub["id"], BL))
        assert post_bid["status"] == "PLACED", "exact restoration of the bid"
        assert post_sub["status"] == "DRAFT"
        assert post_sub["contract_value_cents"] == 0, \
            "value reset to the DRAFT sentinel, not left at 9000000"

    def test_unaward_conserves_package_awarded_value(self):
        """PRD section 3.9: "Under the `PROVISIONAL` basis the
        `awarded_value_cents` is the sum of `contract_value_cents` over the
        package's `EXECUTED` subcontracts".

        Design: Difficulty/compensating_invariant/award_then_unaward_restores_bid_and_package_state_exactly
        """
        pkg, bid, _sub, tp_pre = self._setup_pending_award_with_awarded_bid()
        assert tp_pre == 0, "no awarded anchors before the award"
        validate_success(api_client.unaward_bid(bid["id"], BL))
        post = get_success_data(api_client.get_trade_package(pkg["id"], BL))
        assert post["awarded_value_cents"] == 0, \
            "conserved fiscal quantity — zero drift"


class TestAwardRoleSatisfaction:

    def test_award_by_operations_manager_succeeds(self):
        """PRD section 3.6: "Formal award belongs to the
        `OperationsManager`: it moves the subcontract `PENDING_AWARD →
        AWARDED`."
        PRD section 3.6: "On award, if the package's `bonding_policy` is
        anything other than `WAIVED`, the subcontract's
        `bonding_requirement` becomes `PENDING_DECISION`, queueing the
        bonding determination of §3.7."

        Design: Corner/rbac/award_by_operations_manager_succeeds
        """
        proj, proj_v = create_open_project("P-R1", "R1")
        ctx = setup_leveling_package(
            proj["id"], proj_v, name="R1", trade_code="R1-26",
            bonding_policy="PER_TRADE_RISK",
        )
        sub = create_draft_subcontract(
            ctx["package"]["id"], ctx["bids"][0]["id"], "BG")
        recommend(sub["id"], 9_000_000)
        resp = api_client.award_subcontract(sub["id"], OM)
        data = validate_success(resp)
        assert data["status"] == "AWARDED"
        assert data["bonding_requirement"] == "PENDING_DECISION", \
            "PER_TRADE_RISK requires a decision before issue"
