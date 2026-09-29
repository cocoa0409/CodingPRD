"""Cascades that run several levels past the row the client touched."""

from test_helpers import (
    ApiErrorId,
    assert_transfer_authority_conservation,
    fixtures,
    validate_error,
)

CASH_CASCADE_LINES = (
    {"fund_type": "GENERAL", "program_code": "P100", "introduced_amount_cents": 1_000_000_000},
    {"fund_type": "GENERAL", "program_code": "P200", "introduced_amount_cents": 500_000_000},
)


class TestReleaseCascadeReachesASiblingAppropriation:
    @staticmethod
    def _cascade_context():
        ctx = fixtures.setup_execution_cycle(
            appropriations=CASH_CASCADE_LINES, revenue_amount_cents=1_000_000_000
        )
        first = ctx["appropriations"]["P100"]
        sibling = ctx["appropriations"]["P200"]
        approved = fixtures.approved_allotment(
            first["id"], quarter=1, requested_cents=180_000_000
        )
        assert approved["computed_release_cents"] == 180_000_000
        assert approved["binding_constraint"] == "REQUEST"
        sibling_allotment = fixtures.open_allotment(
            sibling["id"], quarter=1, requested_cents=10_000_000
        )
        ctx["allotment"] = approved
        ctx["sibling_allotment"] = sibling_allotment
        return ctx

    def test_release_drives_the_cycle_to_constrained_and_holds_the_unreleased_sibling(self, api):
        """PRD §3.5: "On success `released_cents` on the allotment becomes `computed_release_cents`, and the cascade of §2.10 runs: the appropriation recomputes `released_cents` and `available_cash_cents` and moves its cash dimension; the cycle recomputes `total_released_cents`, `cash_utilization_pct`, and `cash_posture`; and a posture that has become `CONSTRAINED` sets `release_hold` to true on every appropriation of that cycle whose `fund_type` is `GENERAL` and whose `cash_status` is `UNRELEASED`."
        PRD §3.5: "Its `cash_utilization_pct` is `total_released_cents` divided by that projected figure — using 1 as the divisor whenever the projected figure is zero or less, so the ratio is always defined — rounded half up to 4 decimal places."
        PRD §3.5: "The `cash_posture` is `CONSTRAINED` when `cash_utilization_pct` is greater than or equal to 0.90, and `NORMAL` otherwise."
        PRD §3.5: "While the posture is `CONSTRAINED`, `release_hold` is true on exactly those appropriations of the cycle that are `GENERAL` fund and whose `cash_status` is `UNRELEASED`, and that flag blocks allotment preparation with `ERR_RELEASE_HOLD_ACTIVE`."

        Design: Difficulty/transitive_cascade/allotment_release_cascades_to_release_hold_on_a_sibling_appropriation
        """
        ctx = self._cascade_context()

        released = fixtures.release_allotment(ctx["allotment"]["id"])
        assert released["status"] == "RELEASED"
        assert released["released_cents"] == 180_000_000

        first = fixtures.read_appropriation(ctx["appropriations"]["P100"]["id"])
        assert first["released_cents"] == 180_000_000
        assert first["cash_status"] == "PARTIALLY_RELEASED"
        assert first["release_hold"] is False

        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert cycle["total_released_cents"] == 180_000_000
        assert cycle["projected_cumulative_cash_cents"] == 200_000_000
        assert cycle["cash_utilization_pct"] == 0.9
        assert cycle["cash_posture"] == "CONSTRAINED"

        sibling = fixtures.read_appropriation(ctx["appropriations"]["P200"]["id"])
        assert sibling["release_hold"] is True
        assert sibling["cash_status"] == "UNRELEASED"

    def test_held_sibling_cannot_prepare_its_own_allotment(self, api):
        """PRD §3.5: "It moves the allotment `DRAFT → PREPARED` and requires: the row to be in `DRAFT`; the owning appropriation's `authority_status` to be `ENACTED`, otherwise `ERR_APPROPRIATION_NOT_ENACTED`; that appropriation's `cash_status` not to be `FROZEN`, otherwise `ERR_CASH_FROZEN`; its `release_hold` to be false, otherwise `ERR_RELEASE_HOLD_ACTIVE`; and the owning cycle to be in `EXECUTION`."
        PRD §2.12: "The referenced appropriation's `release_hold` is false — otherwise `ERR_RELEASE_HOLD_ACTIVE` (409)."
        PRD §3.5: "A new allotment starts in `DRAFT` with `computed_release_cents` at 0, `binding_constraint` null, `released_cents` at 0, and `prepared_by_user_id`, `approved_by_user_id`, and `recall_reason` all null."

        Design: Difficulty/transitive_cascade/allotment_release_cascades_to_release_hold_on_a_sibling_appropriation
        """
        ctx = self._cascade_context()
        fixtures.release_allotment(ctx["allotment"]["id"])

        response = api.prepare_allotment(ctx["sibling_allotment"]["id"], fixtures.ANALYST)
        validate_error(response, ApiErrorId.ERR_RELEASE_HOLD_ACTIVE, 409)

        blocked = fixtures.read_allotment(ctx["sibling_allotment"]["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["computed_release_cents"] == 0
        assert blocked["binding_constraint"] is None
        assert blocked["prepared_by_user_id"] is None


class TestTransferCascadeReachesTheAgencyFlag:
    @staticmethod
    def _pledged_context():
        ctx = fixtures.setup_transfer_pair(source_cents=1_000_000_000, target_cents=1_000_000_000)
        grant = fixtures.record_federal_grant(
            ctx["agency"]["id"],
            ctx["cycle"]["id"],
            award_cents=400_000_000,
            required_match_ratio=0.25,
            period_start="2026-07-01T00:00:00Z",
            period_end="2027-07-01T00:00:00Z",
        )
        assert grant["required_state_match_cents"] == 100_000_000
        commitment = fixtures.pledge_match(
            grant["id"],
            ctx["source"]["id"],
            ctx["agency"]["id"],
            committed_match_cents=950_000_000,
        )
        ctx["grant"] = fixtures.read_federal_grant(grant["id"])
        ctx["commitment"] = commitment
        return ctx

    def test_execution_moves_authority_between_the_two_lines(self, api):
        """PRD §3.6: "On success the transfer records `executed_at` from the logical clock, the source's `transfers_out_cents` and the target's `transfers_in_cents` are recomputed from the set of executed transfers, and both rows' `available_authority_cents` are recomputed."
        PRD §2.11: "Summed across the appropriations of a cycle, `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents` equals the plain sum of `enacted_amount_cents`: a transfer moves authority between rows and never creates or destroys it."

        Design: Difficulty/transitive_cascade/transfer_execution_cascades_to_agency_federal_compliance_flag
        """
        ctx = self._pledged_context()

        executed = fixtures.executed_transfer(
            ctx["source"]["id"],
            ctx["target"]["id"],
            amount_cents=100_000_000,
            transfer_type="INTRA_AGENCY",
            justification="Shift authority to P200 for caseload growth",
        )
        assert executed["status"] == "EXECUTED"

        source = fixtures.read_appropriation(ctx["source"]["id"])
        target = fixtures.read_appropriation(ctx["target"]["id"])

        assert source["transfers_out_cents"] == 100_000_000
        assert source["available_authority_cents"] == 900_000_000
        assert target["transfers_in_cents"] == 100_000_000
        assert target["available_authority_cents"] == 1_100_000_000
        assert_transfer_authority_conservation([source, target])

    def test_impaired_pledge_walks_up_to_grant_shortfall_and_a_deficient_agency(self, api):
        """PRD §3.8: "A pledge moves `COMMITTED → AT_RISK` when a transfer executes on the pledged appropriation and the summed `committed_match_cents` of the `COMMITTED` pledges on that appropriation whose grant periods overlap this one now exceeds the appropriation's `available_authority_cents`; the pledged amount then stops counting toward its grant's `committed_match_cents`."
        PRD §3.8: "If the committed total is below `required_state_match_cents` and the committed total is exactly zero, the status is `SHORTFALL` when at least one commitment is `AT_RISK` and `UNMET` when none is."
        PRD §3.8: "Behind the grants, each agency's `federal_compliance_flag` resolves from the grants it owns: `DEFICIENT` when any grant of the agency is in `SHORTFALL`, otherwise `AT_RISK` when any grant is in `AT_RISK`, otherwise `CLEAR`."

        Design: Difficulty/transitive_cascade/transfer_execution_cascades_to_agency_federal_compliance_flag
        """
        ctx = self._pledged_context()
        assert ctx["grant"]["match_status"] == "MET"
        assert ctx["grant"]["committed_match_cents"] == 950_000_000
        assert fixtures.read_agency(ctx["agency"]["id"])["federal_compliance_flag"] == "CLEAR"

        fixtures.executed_transfer(
            ctx["source"]["id"],
            ctx["target"]["id"],
            amount_cents=100_000_000,
            transfer_type="INTRA_AGENCY",
            justification="Shift authority to P200 for caseload growth",
        )

        commitment = fixtures.read_match_commitment(ctx["commitment"]["id"])
        grant = fixtures.read_federal_grant(ctx["grant"]["id"])
        agency = fixtures.read_agency(ctx["agency"]["id"])

        assert commitment["status"] == "AT_RISK"
        assert grant["committed_match_cents"] == 0
        assert grant["match_status"] == "SHORTFALL"
        assert agency["federal_compliance_flag"] == "DEFICIENT"
