"""Plan-versus-actual reconciliation: the chronological and forward-looking
variants, the independent approval/reconciliation axes, and the compliance
cascade from expenditure approval."""
from test_helpers import (
    ApiErrorId,
    add_component,
    api_client,
    create_draft_study,
    create_expenditure,
    create_plan,
    get_association,
    get_study,
    list_components,
    select_plan,
    setup_adopted_study,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["reserve_specialist_headers"]
BOARD = TEST_USERS["board_member_headers"]

_ONE_COMPONENT_RUL0 = [{
    "name": "Roof", "category": "ROOFING", "useful_life_years": 5,
    "remaining_useful_life_years": 0, "current_replacement_cost_cents": 100000,
    "is_included_in_funding": True,
}]


class TestIndependentAxes:
    def test_three_expenditures_land_in_three_reconciliation_outcomes(
            self, api, board_member_headers):
        """PRD §3.6: "When the absolute value of the variance is no greater
        than the tolerance — the larger of 500 cents and ten percent of
        `planned_chronological_cents` rounded half-up — the expenditure's
        `reconciliation_status` is set to `MATCHED` automatically; otherwise
        it remains `UNRECONCILED`."

        Design: Difficulty/non_linear_state_machine/expenditure_independent_approval_reconciliation_axes
        """
        # Component RUL 0 anchors FY2026 planned at exactly 100000, so the
        # tolerance is max(500, round_half_up(0.10*100000)) = 10000.
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Axes HOA",
                                  components=_ONE_COMPONENT_RUL0)
        component_id = ctx["components"][0]["id"]
        e1 = create_expenditure(ctx["association"]["id"], component_id,
                                amount_cents=105000,
                                incurred_date="2026-05-10")
        e2 = create_expenditure(ctx["association"]["id"], component_id,
                                amount_cents=112000,
                                incurred_date="2026-05-11")
        e3 = create_expenditure(ctx["association"]["id"], component_id,
                                amount_cents=110000,
                                incurred_date="2026-05-12")

        a1 = validate_success(api.approve_expenditure(e1["id"],
                                                      board_member_headers))
        assert a1["approval_status"] == "APPROVED"
        assert a1["reconciliation_status"] == "MATCHED", (
            "variance 5000 <= 10000; got "
            f"{a1['reconciliation_status']}")

        a2 = validate_success(api.approve_expenditure(e2["id"],
                                                      board_member_headers))
        assert a2["approval_status"] == "APPROVED"
        assert a2["reconciliation_status"] == "UNRECONCILED", (
            "variance 12000 > 10000; got "
            f"{a2['reconciliation_status']}")

        a3 = validate_success(api.approve_expenditure(e3["id"],
                                                      board_member_headers))
        assert a3["approval_status"] == "APPROVED"
        assert a3["reconciliation_status"] == "MATCHED", (
            "variance 10000 == tolerance and <= holds; got "
            f"{a3['reconciliation_status']}")

    def test_accept_variance_moves_only_the_reconciliation_axis(
            self, api, board_member_headers, reserve_specialist_headers):
        """PRD §3.6: "Independently of approval, the specialist may accept an
        out-of-tolerance variance, moving `reconciliation_status` from
        `UNRECONCILED` to `VARIANCE_ACCEPTED`; the request may carry an
        optional `reason`. This transition touches only the reconciliation
        axis — `approval_status` is left untouched — and attempting it from
        any other reconciliation state fails with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/expenditure_independent_approval_reconciliation_axes
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Axes2 HOA",
                                  components=_ONE_COMPONENT_RUL0)
        component_id = ctx["components"][0]["id"]
        matched_ex = create_expenditure(ctx["association"]["id"], component_id,
                                        amount_cents=105000,
                                        incurred_date="2026-05-10")
        outlier_ex = create_expenditure(ctx["association"]["id"], component_id,
                                        amount_cents=112000,
                                        incurred_date="2026-05-11")
        validate_success(api.approve_expenditure(matched_ex["id"],
                                                 board_member_headers))
        validate_success(api.approve_expenditure(outlier_ex["id"],
                                                 board_member_headers))

        # Accept-variance from MATCHED is rejected.
        res = api.accept_variance(matched_ex["id"], reserve_specialist_headers,
                                  reason="not needed")
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        accepted = validate_success(
            api.accept_variance(outlier_ex["id"], reserve_specialist_headers,
                                reason="board-noted overage"), 200)
        assert accepted["reconciliation_status"] == "VARIANCE_ACCEPTED"
        assert accepted["approval_status"] == "APPROVED", (
            "the approval axis is untouched; got "
            f"{accepted['approval_status']}")


class TestChronologicalVsForwardVariance:
    def _setup_two_study_regime(self, api):
        """S1 FY2026 (inflation 0.03) ADOPTED then SUPERSEDED by S2 FY2027
        (inflation 0.10) ADOPTED; returns the association and S2's component.
        """
        ctx = setup_adopted_study(state_code="CA", cash=1000000,
                                  association_name="Twin Peaks HOA",
                                  components=_ONE_COMPONENT_RUL0,
                                  inflation_rate=0.03)
        s2 = create_draft_study(ctx["association"]["id"], fiscal_year=2027,
                                study_type="UPDATE_NO_VISIT",
                                inflation_rate=0.10)
        component_y = add_component(s2["id"], name="Roof",
                                    remaining_useful_life_years=2)
        plan2 = create_plan(s2["id"], "BASELINE")
        validate_success(api_client.submit_study(s2["id"], SPECIALIST))
        select_plan(plan2["id"])
        validate_success(api_client.adopt_study(s2["id"], BOARD))
        assert get_study(ctx["study"]["id"])["status"] == "SUPERSEDED"
        return ctx["association"], component_y

    def test_variance_chronological_vs_forward_on_approve(
            self, api, board_member_headers):
        """PRD §3.6: "The anchor is the study of the same association whose
        `fiscal_year` equals the expenditure's `fiscal_year` and whose status
        is `ADOPTED` or `SUPERSEDED`; when several studies qualify, the most
        recently created one — the greatest `created_at` — wins, and when none
        qualifies, the association's current `ADOPTED` study anchors instead."
        and "`planned_forward_cents` applies the same growth formula but
        anchors on the association's current `ADOPTED` study, whatever it
        happens to be at read time, and `variance_forward_cents` is the actual
        amount minus it."

        Design: Difficulty/dual_variant_calc/expenditure_variance_chronological_vs_forward
        """
        association, component_y = self._setup_two_study_regime(api)
        expenditure = create_expenditure(
            association["id"], component_y["id"], amount_cents=105000,
            incurred_date="2026-03-10", kind="PLANNED_REPLACEMENT")

        approved = validate_success(
            api.approve_expenditure(expenditure["id"], board_member_headers),
            200)
        assert approved["planned_chronological_cents"] == 100000, (
            "anchored to the SUPERSEDED FY2026 study (inflation 0.03, "
            f"exponent 0); got {approved['planned_chronological_cents']}")
        assert approved["variance_chronological_cents"] == 5000
        assert approved["planned_forward_cents"] == 90909, (
            "anchored to the current ADOPTED FY2027 study: "
            "round_half_up(100000 * 1.10^-1); got "
            f"{approved['planned_forward_cents']}")
        assert approved["variance_forward_cents"] == 14091
        assert approved["reconciliation_status"] == "MATCHED", (
            "|5000| <= max(500, 10000); got "
            f"{approved['reconciliation_status']}")
        assert approved["planned_chronological_cents"] != \
            approved["planned_forward_cents"], (
                "same expenditure, two anchor studies, two planned amounts")

    def test_forward_pair_recomputed_live_on_read(
            self, api, board_member_headers,
            reserve_specialist_headers):
        """PRD §3.6: "Because the anchor moves as studies are adopted and
        superseded, the forward pair is recomputed live on every read and
        diverges from the stored chronological pair whenever assumptions have
        changed since the expenditure's fiscal year" and "a
        single-expenditure read returns both reconciliation variants."

        Design: Difficulty/dual_variant_calc/expenditure_variance_chronological_vs_forward
        """
        association, component_y = self._setup_two_study_regime(api)
        expenditure = create_expenditure(
            association["id"], component_y["id"], amount_cents=105000,
            incurred_date="2026-03-10", kind="PLANNED_REPLACEMENT")
        validate_success(api.approve_expenditure(expenditure["id"],
                                                 board_member_headers))

        read_back = validate_success(
            api.get_expenditure(expenditure["id"],
                                reserve_specialist_headers), 200)
        # The stored chronological pair is pinned at approval time...
        assert read_back["planned_chronological_cents"] == 100000
        assert read_back["variance_chronological_cents"] == 5000
        # ...while the forward pair is recomputed live from the current
        # ADOPTED study (FY2027, inflation 0.10).
        assert read_back["planned_forward_cents"] == 90909
        assert read_back["variance_forward_cents"] == 14091
        assert read_back["approval_status"] == "APPROVED"
        assert read_back["reconciliation_status"] == "MATCHED"


class TestApprovalComplianceCascade:
    _CASCADE_COMPONENTS = [
        {"name": "Fence", "category": "EXTERIOR", "useful_life_years": 2,
         "remaining_useful_life_years": 0,
         "current_replacement_cost_cents": 100000,
         "is_included_in_funding": True},
        {"name": "Gate", "category": "EXTERIOR", "useful_life_years": 10,
         "remaining_useful_life_years": 9,
         "current_replacement_cost_cents": 10000,
         "is_included_in_funding": True},
    ]

    def test_expenditure_approve_compliance_cascade(
            self, api, board_member_headers, reserve_specialist_headers):
        """PRD §3.6: "the amount is debited from the association's
        `reserve_cash_balance_cents`, advancing the association's `version`;
        the amount is added to the component's running
        `actual_expenditure_cents`" and "the adopted study's
        `fully_funded_balance_cents` and `percent_funded` are recomputed and
        the study's `version` advances, and the association's
        `statutory_compliance_status` is re-evaluated, dropping to
        `NON_COMPLIANT` when the recomputed percent falls below the state
        minimum."

        Design: Difficulty/transitive_cascade/expenditure_approve_compliance_cascade
        """
        # FFB = 100000 + round(10000*1/10) = 101000; 60000/101000 = 59.41.
        ctx = setup_adopted_study(state_code="CA", cash=60000,
                                  association_name="Thin Cash HOA",
                                  components=self._CASCADE_COMPONENTS)
        comp_before = get_association(
            ctx["association"]["id"])["statutory_compliance_status"]
        assert comp_before == "COMPLIANT", (
            "adoption enforces the minimum (59.41 >= 50); got "
            f"{comp_before}")

        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=15001,
                                         incurred_date="2026-05-10")
        approved = validate_success(
            api.approve_expenditure(expenditure["id"], board_member_headers),
            200)
        assert approved["approval_status"] == "APPROVED"

        association = get_association(ctx["association"]["id"])
        assert association["reserve_cash_balance_cents"] == 44999, (
            f"link 1: 60000 - 15001; got "
            f"{association['reserve_cash_balance_cents']}")
        study = get_study(ctx["study"]["id"])
        assert study["percent_funded"] == 44.55, (
            "link 2: round_half_up(44999*100/101000, 2); got "
            f"{study['percent_funded']}")
        assert association["statutory_compliance_status"] == "NON_COMPLIANT", (
            "link 3: 44.55 < 50; got "
            f"{association['statutory_compliance_status']}")

        fence = list_components(ctx["study"]["id"])[0]
        assert fence["actual_expenditure_cents"] == 15001

    def test_reverse_restores_compliance(
            self, api, board_member_headers, reserve_specialist_headers):
        """PRD §2.10: "On expenditure approval, on expenditure reversal, and
        at every annual update the comparison is re-run against the freshly
        recomputed percent funded: meeting or exceeding the minimum yields
        `COMPLIANT`, and falling below it yields `NON_COMPLIANT`."

        Design: Difficulty/transitive_cascade/expenditure_approve_compliance_cascade
        """
        ctx = setup_adopted_study(state_code="CA", cash=60000,
                                  association_name="Thin Cash 2 HOA",
                                  components=self._CASCADE_COMPONENTS)
        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=15001,
                                         incurred_date="2026-05-10")
        validate_success(api.approve_expenditure(expenditure["id"],
                                                 board_member_headers))
        assert get_association(
            ctx["association"]["id"])["statutory_compliance_status"] == \
            "NON_COMPLIANT"

        validate_success(api.reverse_expenditure(expenditure["id"],
                                                 board_member_headers))
        association = get_association(ctx["association"]["id"])
        assert association["reserve_cash_balance_cents"] == 60000
        study = get_study(ctx["study"]["id"])
        assert study["percent_funded"] == 59.41, (
            "round_half_up(60000*100/101000, 2); got "
            f"{study['percent_funded']}")
        assert association["statutory_compliance_status"] == "COMPLIANT", (
            "the reversal re-runs the comparison against the restored "
            f"percent; got {association['statutory_compliance_status']}")
