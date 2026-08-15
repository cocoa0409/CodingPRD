"""Board review: adoption gates, the rejection revision loop, withdrawal,
and the adoption supersession cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    api_client,
    create_draft_study,
    create_plan,
    get_study,
    list_disclosures,
    list_plans,
    onboard_association,
    recommend_plan,
    schedule_and_complete_visit,
    seed_state_rule,
    select_plan,
    setup_adopted_study,
    setup_submitted_study,
    validate_error,
    validate_success,
)

SPECIALIST = TEST_USERS["reserve_specialist_headers"]
BOARD = TEST_USERS["board_member_headers"]
MANAGER = TEST_USERS["association_manager_headers"]


def _adopt_ready_study(association_id, fiscal_year, study_type,
                       inflation_rate, component_rul, plan_type="BASELINE"):
    """Create study + one component + plan, submit, select. Returns dict."""
    study = create_draft_study(association_id, fiscal_year=fiscal_year,
                               study_type=study_type,
                               inflation_rate=inflation_rate)
    component = add_component(
        study["id"], name="Roof", useful_life_years=5,
        remaining_useful_life_years=component_rul,
        current_replacement_cost_cents=100000)
    plan = create_plan(study["id"], plan_type)
    validate_success(api_client.submit_study(study["id"], SPECIALIST))
    select_plan(plan["id"])
    return {"study": study, "component": component, "plan": plan}


class TestAdoptAndWithdrawStateGates:
    def test_study_adopt_from_draft_rejected(self, api, board_member_headers):
        """PRD §3.5: "Adoption is the board's final word, moving the study
        from `SUBMITTED` to `ADOPTED`." and PRD §2.8: "The addressed entity
        sits in the state the action requires: the study `DRAFT` or
        `SUBMITTED` as the operation demands (surfacing `ERR_INVALID_STATE`
        or `ERR_STUDY_NOT_DRAFT`), the plan in a compatible status, the visit
        `SCHEDULED`, the expenditure `SUBMITTED` or `APPROVED`, the
        disclosure `PENDING`, exactly one `SELECTED` plan at adoption
        (`ERR_NO_PLAN_SELECTED`)."

        Design: Corner/state_machines/study_adopt_from_draft_rejected
        """
        association = onboard_association("CA", name="Draft HOA")
        study = create_draft_study(association["id"])
        res = api.adopt_study(study["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_study_withdraw_terminal_lockdown(
            self, api, reserve_specialist_headers):
        """PRD §3.5: "A specialist may also abandon a study outright while it
        is still `DRAFT`, moving it to `WITHDRAWN`, a terminal state"."

        Design: Corner/state_machines/study_withdraw_terminal_lockdown
        """
        association = onboard_association("CA", name="Gone HOA")
        study = create_draft_study(association["id"])
        withdrawn = validate_success(
            api.withdraw_study(study["id"], reserve_specialist_headers), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        res = api.submit_study(study["id"], reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestRevisionLoop:
    def test_study_submit_reject_revision_loop(
            self, api, reserve_specialist_headers, board_member_headers):
        """PRD §3.5: "The board may instead send the study back for revision,
        returning it from `SUBMITTED` to `DRAFT`; the rejection may carry an
        optional `reason`. The study's `version` advances, its `SELECTED`
        plan — if one exists — reverts to `DRAFT` as compensation so that a
        re-submitted study must go through selection again, and any plan
        sitting in `RECOMMENDED` likewise falls back to `DRAFT`, clearing the
        endorsement along with the board's pick. This revision loop may
        repeat as often as needed."

        Design: Difficulty/non_linear_state_machine/study_submit_reject_revision_loop
        """
        ctx = setup_submitted_study(association_name="Loop HOA")
        study_id = ctx["study"]["id"]
        plan_id = ctx["plan"]["id"]
        select_plan(plan_id)

        rejected = validate_success(
            api.reject_study(study_id, board_member_headers,
                             reason="needs more components"), 200)
        assert rejected["status"] == "DRAFT", (
            f"cycle SUBMITTED -> DRAFT; got {rejected['status']}")

        plan_rows = list_plans(study_id)
        assert plan_rows[0]["status"] == "DRAFT", (
            "SELECTED -> DRAFT compensation; got "
            f"{plan_rows[0]['status']}")

        resubmitted = validate_success(
            api.submit_study(study_id, reserve_specialist_headers), 200)
        assert resubmitted["status"] == "SUBMITTED", (
            f"loop closed, re-entry allowed; got {resubmitted['status']}")

        select_plan(plan_id)
        adopted = validate_success(api.adopt_study(study_id,
                                                   board_member_headers), 200)
        assert adopted["status"] == "ADOPTED"

    def test_reject_reverts_recommended_plan_and_loop_repeats(
            self, api, reserve_specialist_headers, board_member_headers):
        """PRD §3.5: "The study's `version` advances, its `SELECTED` plan —
        if one exists — reverts to `DRAFT` as compensation so that a
        re-submitted study must go through selection again, and any plan
        sitting in `RECOMMENDED` likewise falls back to `DRAFT`, clearing the
        endorsement along with the board's pick. This revision loop may repeat
        as often as needed."

        Design: Difficulty/non_linear_state_machine/study_submit_reject_revision_loop
        """
        association = onboard_association("CA", name="Loop2 HOA")
        schedule_and_complete_visit(association["id"])
        study = create_draft_study(association["id"])
        add_component(study["id"], name="Roof")
        p1 = create_plan(study["id"], "BASELINE")
        p2 = create_plan(study["id"], "THRESHOLD")
        recommend_plan(p2["id"])

        validate_success(api_client.submit_study(study["id"], SPECIALIST))
        select_plan(p1["id"])

        rejected = validate_success(
            api_client.reject_study(study["id"], BOARD), 200)
        assert rejected["status"] == "DRAFT"

        plan_rows = {r["id"]: r for r in list_plans(study["id"])}
        assert plan_rows[p1["id"]]["status"] == "DRAFT", (
            "the SELECTED plan reverts to DRAFT; got "
            f"{plan_rows[p1['id']]['status']}")
        assert plan_rows[p2["id"]]["status"] == "DRAFT", (
            "the RECOMMENDED plan falls back to DRAFT; got "
            f"{plan_rows[p2['id']]['status']}")

        # The loop may repeat: re-submit, select the other plan, adopt.
        validate_success(api_client.submit_study(study["id"], SPECIALIST))
        select_plan(p2["id"])
        adopted = validate_success(api_client.adopt_study(study["id"], BOARD),
                                   200)
        assert adopted["status"] == "ADOPTED"
        assert adopted["adopted_plan_id"] == p2["id"]


class TestAdoptionStatutoryGates:
    def test_study_adopt_without_selected_plan_rejected(
            self, api, board_member_headers):
        """PRD §3.5: "Three statutory checks stand in front of it: exactly
        one plan of the study must be `SELECTED` (otherwise
        `ERR_NO_PLAN_SELECTED`); the selected plan's `plan_type` must appear
        in the state rule's `allowed_plan_types` (otherwise
        `ERR_PLAN_TYPE_NOT_ALLOWED`); and the study's `percent_funded` must
        meet or exceed the state rule's `min_percent_funded_pct` (otherwise
        `ERR_PERCENT_FUNDED_BELOW_MINIMUM`)."

        Design: Corner/validations/study_adopt_without_selected_plan_rejected
        """
        ctx = setup_submitted_study(association_name="No Select HOA")
        res = api.adopt_study(ctx["study"]["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_NO_PLAN_SELECTED)

    def test_adopt_plan_type_not_allowed_rejected(
            self, api, board_member_headers):
        """PRD §3.5: "the selected plan's `plan_type` must appear in the
        state rule's `allowed_plan_types` (otherwise
        `ERR_PLAN_TYPE_NOT_ALLOWED`)".

        Design: Corner/validations/adopt_plan_type_not_allowed_rejected
        """
        ctx = setup_submitted_study(state_code="TX", cash=500000,
                                    plan_type="THRESHOLD",
                                    association_name="Texas HOA",
                                    components=[{
                                        "name": "Roof", "category": "ROOFING",
                                        "useful_life_years": 5,
                                        "remaining_useful_life_years": 2,
                                        "current_replacement_cost_cents": 100000,
                                        "is_included_in_funding": True,
                                    }])
        select_plan(ctx["plan"]["id"])
        res = api.adopt_study(ctx["study"]["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_PLAN_TYPE_NOT_ALLOWED)


class TestPercentFundedBoundary:
    @staticmethod
    def _prepared_association(api, name, cash):
        association = onboard_association("CA", seed_rule=False, name=name,
                                          reserve_cash_balance_cents=cash)
        schedule_and_complete_visit(association["id"])
        study = create_draft_study(association["id"])
        add_component(study["id"], name="Roof", useful_life_years=10,
                      remaining_useful_life_years=5,
                      current_replacement_cost_cents=20000)
        plan = create_plan(study["id"], "BASELINE")
        validate_success(api_client.submit_study(study["id"], SPECIALIST))
        select_plan(plan["id"])
        return study

    def test_percent_funded_exact_statutory_minimum_adopts(
            self, api, platform_admin_headers, board_member_headers):
        """PRD §3.5: "the study's `percent_funded` must meet or exceed the
        state rule's `min_percent_funded_pct` (otherwise
        `ERR_PERCENT_FUNDED_BELOW_MINIMUM`)."

        Design: Difficulty/boundary_precision_check/percent_funded_exact_statutory_minimum
        """
        seed_state_rule("CA")
        # FFB = round(20000*5/10) = 10000; cash 5000 -> exactly 50.00.
        study = self._prepared_association(api, "Exact HOA", 5000)
        adopted = validate_success(api.adopt_study(study["id"],
                                                   board_member_headers), 200)
        assert adopted["percent_funded"] == 50.00, (
            f"cash 5000 / FFB 10000 = 50.00 exactly; got "
            f"{adopted['percent_funded']}")
        assert adopted["status"] == "ADOPTED", (
            ">= admits the exact minimum; got "
            f"{adopted['status']}")

    def test_percent_funded_one_cent_below_minimum_rejected(
            self, api, platform_admin_headers, board_member_headers):
        """PRD §3.5: "the study's `percent_funded` must meet or exceed the
        state rule's `min_percent_funded_pct` (otherwise
        `ERR_PERCENT_FUNDED_BELOW_MINIMUM`)."

        Design: Difficulty/boundary_precision_check/percent_funded_exact_statutory_minimum
        """
        seed_state_rule("CA")
        # FFB = 10000; cash 4999 -> 49.99 < 50.
        study = self._prepared_association(api, "Below HOA", 4999)
        res = api.adopt_study(study["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_PERCENT_FUNDED_BELOW_MINIMUM)


class TestAdoptionSupersessionCascade:
    @staticmethod
    def _adopt_second_study(association_id):
        return _adopt_ready_study(association_id, fiscal_year=2027,
                                  study_type="UPDATE_NO_VISIT",
                                  inflation_rate=0.03, component_rul=1)

    def test_adoption_supersedes_prior_study_cascade(
            self, api, board_member_headers):
        """PRD §3.5: "Adoption is also a regime change for the association:
        any previously `ADOPTED` study of the same association moves to
        `SUPERSEDED` with its `version` advanced, its `DRAFT`, `RECOMMENDED`,
        and `SELECTED` plans move to `RETIRED`, and its still-`PENDING`
        disclosures move to `VOIDED`. The newly adopted study spawns a member
        disclosure of `disclosure_type` `ADOPTION_SUMMARY` in `PENDING`
        status, whose `due_date` falls `disclosure_deadline_days` after the
        adoption date."

        Design: Difficulty/transitive_cascade/adoption_supersedes_prior_study_cascade
        """
        ctx = setup_adopted_study(state_code="CA", cash=1000000,
                                  association_name="Cascade HOA")
        s1 = ctx["study"]
        p1 = ctx["plan"]
        d1 = list_disclosures(s1["id"])[0]
        assert d1["status"] == "PENDING"

        s2_ctx = self._adopt_second_study(ctx["association"]["id"])
        adopted_s2 = validate_success(
            api.adopt_study(s2_ctx["study"]["id"], board_member_headers), 200)
        assert adopted_s2["status"] == "ADOPTED"

        s1_after = get_study(s1["id"])
        assert s1_after["status"] == "SUPERSEDED", (
            "link 1: adoption mutated the prior study; got "
            f"{s1_after['status']}")

        p1_after = next(r for r in list_plans(s1["id"])
                        if r["id"] == p1["id"])
        assert p1_after["status"] == "RETIRED", (
            "link 2: supersession retired S1's SELECTED plan; got "
            f"{p1_after['status']}")

        d1_after = next(r for r in list_disclosures(s1["id"])
                        if r["id"] == d1["id"])
        assert d1_after["status"] == "VOIDED", (
            "link 2: supersession voided S1's PENDING disclosure; got "
            f"{d1_after['status']}")

        d2 = list_disclosures(adopted_s2["id"])[0]
        assert d2["disclosure_type"] == "ADOPTION_SUMMARY"
        assert d2["status"] == "PENDING"
        assert d2["due_date"] == "2026-08-31", (
            "adoption at the default clock 2026-08-01 + 30 deadline days; "
            f"got {d2['due_date']}")

    def test_distributed_disclosure_survives_supersession(
            self, api, board_member_headers, association_manager_headers):
        """PRD §3.5: "its still-`PENDING` disclosures move to `VOIDED`" and
        PRD §3.7: "When a study is superseded, its still-`PENDING`
        disclosures move to `VOIDED`, a terminal state, so a stale summary
        never reaches members as if it were current."

        Design: Difficulty/transitive_cascade/adoption_supersedes_prior_study_cascade
        """
        ctx = setup_adopted_study(state_code="CA", cash=1000000,
                                  association_name="Survivor HOA")
        s1 = ctx["study"]
        d1 = list_disclosures(s1["id"])[0]
        distributed = validate_success(
            api.distribute_disclosure(d1["id"], association_manager_headers),
            200)
        assert distributed["status"] == "DISTRIBUTED"

        s2_ctx = self._adopt_second_study(ctx["association"]["id"])
        validate_success(api.adopt_study(s2_ctx["study"]["id"],
                                         board_member_headers), 200)

        s1_after = get_study(s1["id"])
        assert s1_after["status"] == "SUPERSEDED"
        d1_after = next(r for r in list_disclosures(s1["id"])
                        if r["id"] == d1["id"])
        assert d1_after["status"] == "DISTRIBUTED", (
            "only still-PENDING disclosures are voided; an already "
            f"DISTRIBUTED disclosure survives; got {d1_after['status']}")
