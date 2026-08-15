"""Component inventory: input validation, derived totals, retire/restore,
and the study-state gate on inventory mutations."""
from test_helpers import (
    ApiErrorId,
    add_component,
    assert_component,
    create_draft_study,
    get_study,
    list_components,
    onboard_association,
    setup_submitted_study,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestComponentInputValidation:
    def test_component_rul_above_ul_invalid_request(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "its `remaining_useful_life_years` of at least 0 and no
        greater than the useful life" and PRD §2.8: "numeric ranges hold —
        `useful_life_years` at least 1, `remaining_useful_life_years` at
        least 0 and no greater than the useful life, monetary amounts
        strictly positive, rates non-negative, `fiscal_year_end_month`
        between 1 and 12, `min_percent_funded_pct` between 0 and 100,
        `allowed_plan_types` a non-empty subset of the three plan types.
        Failures surface `ERR_INVALID_REQUEST`."

        Design: Corner/entities/component_rul_above_ul_invalid_request
        """
        association = onboard_association("CA", name="Range HOA")
        study = create_draft_study(association["id"])
        res = api.create_component(
            {"study_id": study["id"], "name": "Roof", "category": "ROOFING",
             "useful_life_years": 5, "remaining_useful_life_years": 6,
             "current_replacement_cost_cents": 100000},
            reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_component_create_extra_field_rejected(
            self, api, reserve_specialist_headers):
        """PRD §2.8: "Required fields are present, no unknown fields are
        supplied, enum values are members of their declared sets, and numeric
        ranges hold — `useful_life_years` at least 1,
        `remaining_useful_life_years` at least 0 and no greater than the
        useful life, monetary amounts strictly positive, rates non-negative,
        `fiscal_year_end_month` between 1 and 12, `min_percent_funded_pct`
        between 0 and 100, `allowed_plan_types` a non-empty subset of the
        three plan types. Failures surface `ERR_INVALID_REQUEST`."

        Design: Corner/entities/component_create_extra_field_rejected
        """
        association = onboard_association("CA", name="Strict HOA")
        study = create_draft_study(association["id"])
        res = api.create_component(
            {"study_id": study["id"], "name": "Roof", "category": "ROOFING",
             "useful_life_years": 5, "remaining_useful_life_years": 2,
             "current_replacement_cost_cents": 100000,
             "actual_expenditure_cents": 999},
            reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestDerivedTotals:
    def test_create_then_read_immediately_consistent(
            self, api, reserve_specialist_headers):
        """PRD §2.10: "Derived state is never lazy." and "Mutations propagate
        immediately and visibly". PRD §3.3: "A component opens in `ACTIVE`
        status with `actual_expenditure_cents` at 0 and
        `last_replaced_fiscal_year` null."

        Design: Corner/consistency_model/create_then_read_immediately_consistent
        """
        association = onboard_association("CA", name="Consistent HOA")
        study = create_draft_study(association["id"])
        component = validate_success(api.create_component(
            {"study_id": study["id"], "name": "Roof", "category": "ROOFING",
             "useful_life_years": 5, "remaining_useful_life_years": 2,
             "current_replacement_cost_cents": 100000,
             "is_included_in_funding": True},
            reserve_specialist_headers), 201)
        assert_component(component)

        rows, meta = validate_paginated(
            api.list_components(study["id"], reserve_specialist_headers))
        assert meta["total_count"] == 1
        read_back = rows[0]
        assert read_back["id"] == component["id"]
        assert read_back["name"] == "Roof"
        assert read_back["remaining_useful_life_years"] == 2
        assert read_back["status"] == "ACTIVE"
        assert read_back["actual_expenditure_cents"] == 0

    def test_percent_funded_zero_ffb_yields_full(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "When no obligation exists — a fully funded balance of
        zero — `percent_funded` is pinned at exactly 100.00 rather than being
        left undefined."

        Design: Corner/calculations/percent_funded_zero_ffb_yields_full
        """
        association = onboard_association("CA", name="Zero FFB HOA")
        study = create_draft_study(association["id"])
        add_component(study["id"], name="New Roof",
                      useful_life_years=5, remaining_useful_life_years=5)
        study_after = validate_success(
            api.get_study(study["id"], reserve_specialist_headers), 200)
        assert study_after["fully_funded_balance_cents"] == 0, (
            "RUL == UL leaves zero consumed life, so FFB is 0; got "
            f"{study_after['fully_funded_balance_cents']}")
        assert study_after["percent_funded"] == 100.00

    def test_derived_ffb_recomputed_on_component_retire(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "Each of them also recomputes the study's
        `fully_funded_balance_cents` and `percent_funded` immediately and
        advances the study's `version`, so a change deep in the inventory is
        always visible on the study itself."

        Design: Corner/calculations/derived_ffb_recomputed_on_component_retire
        """
        association = onboard_association("CA", name="Derived HOA",
                                          reserve_cash_balance_cents=500000)
        study = create_draft_study(association["id"])
        c1 = add_component(study["id"], name="Roof", useful_life_years=5,
                           remaining_useful_life_years=2,
                           current_replacement_cost_cents=100000)
        add_component(study["id"], name="Paving", category="PAVING",
                      useful_life_years=4, remaining_useful_life_years=1,
                      current_replacement_cost_cents=50000)

        validate_success(api.retire_component(c1["id"],
                                              reserve_specialist_headers))
        study_after = validate_success(
            api.get_study(study["id"], reserve_specialist_headers), 200)
        assert study_after["fully_funded_balance_cents"] == 37500, (
            "only Paving remains: round(50000*3/4) = 37500; got "
            f"{study_after['fully_funded_balance_cents']}")
        assert study_after["percent_funded"] == 1333.33, (
            "round_half_up(500000*100/37500, 2) = 1333.33; got "
            f"{study_after['percent_funded']}")


class TestInventoryStateGate:
    def test_component_edit_gated_by_study_state_patch(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "The inventory is editable only while its study is
        `DRAFT`." and "Any of these mutations against a study that is no
        longer `DRAFT` fails with `ERR_STUDY_NOT_DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/component_edit_gated_by_study_state
        """
        ctx = setup_submitted_study(association_name="Gate HOA")
        component = ctx["components"][0]
        res = api.patch_component(
            component["id"], {"current_replacement_cost_cents": 110000},
            reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STUDY_NOT_DRAFT)

    def test_component_retire_restore_gated_by_study_state(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "While it is, the specialist may update a component's
        `name`, `category`, life figures, replacement cost, or funding
        inclusion; may retire a component, moving it from `ACTIVE` to
        `RETIRED`, when it leaves scope; and may restore a retired component
        back to `ACTIVE`. Any of these mutations against a study that is no
        longer `DRAFT` fails with `ERR_STUDY_NOT_DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/component_edit_gated_by_study_state
        """
        ctx = setup_submitted_study(association_name="Gate2 HOA",
                                    components=[{
                                        "name": "Roof", "category": "ROOFING",
                                        "useful_life_years": 5,
                                        "remaining_useful_life_years": 2,
                                        "current_replacement_cost_cents": 100000,
                                        "is_included_in_funding": True,
                                    }, {
                                        "name": "Pool", "category": "RECREATION",
                                        "useful_life_years": 8,
                                        "remaining_useful_life_years": 3,
                                        "current_replacement_cost_cents": 40000,
                                        "is_included_in_funding": True,
                                    }])
        active_component = ctx["components"][0]
        res = api.retire_component(active_component["id"],
                                   reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STUDY_NOT_DRAFT)
        res = api.restore_component(active_component["id"],
                                    reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STUDY_NOT_DRAFT)
        res = api.create_component(
            {"study_id": ctx["study"]["id"], "name": "Gate",
             "category": "EXTERIOR", "useful_life_years": 10,
             "remaining_useful_life_years": 4,
             "current_replacement_cost_cents": 30000},
            reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STUDY_NOT_DRAFT)


class TestRetireRestoreInvariant:
    def test_retire_then_restore_conserves_ffb_and_count(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "For each `ACTIVE`, funding-included component, the
        consumed life is `useful_life_years` minus `remaining_useful_life_years`,
        and the component contributes its `current_replacement_cost_cents`
        multiplied by the ratio of consumed life to useful life; each
        per-component term is rounded half-up to integer cents before the
        terms are summed into `fully_funded_balance_cents`."

        Design: Difficulty/compensating_invariant/retire_then_restore_conserves_component_count
        """
        association = onboard_association("CA", name="Restore HOA",
                                          reserve_cash_balance_cents=500000)
        study = create_draft_study(association["id"])
        c1 = add_component(study["id"], name="Roof", useful_life_years=5,
                           remaining_useful_life_years=2,
                           current_replacement_cost_cents=100000)
        add_component(study["id"], name="Paving", category="PAVING",
                      useful_life_years=4, remaining_useful_life_years=1,
                      current_replacement_cost_cents=50000)

        ffb_before = get_study(study["id"])["fully_funded_balance_cents"]
        assert ffb_before == 97500, (
            "round(100000*3/5) + round(50000*3/4) = 97500; got "
            f"{ffb_before}")

        validate_success(api.retire_component(c1["id"],
                                              reserve_specialist_headers))
        ffb_mid = get_study(study["id"])["fully_funded_balance_cents"]
        assert ffb_mid == 37500, (
            f"C1 excluded while RETIRED: FFB 37500 expected, got {ffb_mid}")

        validate_success(api.restore_component(c1["id"],
                                               reserve_specialist_headers))
        ffb_end = get_study(study["id"])["fully_funded_balance_cents"]
        assert ffb_end == ffb_before, (
            "retire + restore conserves the aggregate: "
            f"expected {ffb_before}, got {ffb_end}")

        active_rows = list_components(study["id"], params={"status": "ACTIVE"})
        assert len(active_rows) == 2, (
            "ACTIVE included component count returns to 2 after restore; got "
            f"{len(active_rows)}")

    def test_retire_then_restore_conserves_percent_funded(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "The study's `percent_funded` then measures the
        association's position against that obligation: the association's
        `reserve_cash_balance_cents` multiplied by one hundred and divided by
        the fully funded balance, rounded half-up to two decimal places."

        Design: Difficulty/compensating_invariant/retire_then_restore_conserves_component_count
        """
        association = onboard_association("CA", name="Restore2 HOA",
                                          reserve_cash_balance_cents=500000)
        study = create_draft_study(association["id"])
        c1 = add_component(study["id"], name="Roof", useful_life_years=5,
                           remaining_useful_life_years=2,
                           current_replacement_cost_cents=100000)
        add_component(study["id"], name="Paving", category="PAVING",
                      useful_life_years=4, remaining_useful_life_years=1,
                      current_replacement_cost_cents=50000)

        pct_before = get_study(study["id"])["percent_funded"]
        assert pct_before == 512.82, (
            "round_half_up(500000*100/97500, 2) = 512.82; got "
            f"{pct_before}")

        validate_success(api.retire_component(c1["id"],
                                              reserve_specialist_headers))
        pct_mid = get_study(study["id"])["percent_funded"]
        assert pct_mid == 1333.33, (
            "round_half_up(500000*100/37500, 2) = 1333.33; got "
            f"{pct_mid}")

        validate_success(api.restore_component(c1["id"],
                                               reserve_specialist_headers))
        pct_end = get_study(study["id"])["percent_funded"]
        assert pct_end == pct_before, (
            "restore returns percent_funded to its pre-retire value: "
            f"expected {pct_before}, got {pct_end}")
