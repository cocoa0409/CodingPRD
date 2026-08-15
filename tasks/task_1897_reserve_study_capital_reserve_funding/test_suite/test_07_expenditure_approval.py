"""Expenditure lifecycle: submission gates, approval gates and their
ordering, reversal windows, and the approve/reverse conservation invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    assert_expenditure,
    create_draft_study,
    create_expenditure,
    create_plan,
    get_association,
    get_expenditure,
    list_components,
    onboard_association,
    select_plan,
    setup_adopted_study,
    validate_error,
    validate_success,
)

TEST_HEADERS_SPECIALIST = TEST_USERS["reserve_specialist_headers"]

_ONE_COMPONENT = [{
    "name": "Roof", "category": "ROOFING", "useful_life_years": 5,
    "remaining_useful_life_years": 2, "current_replacement_cost_cents": 100000,
    "is_included_in_funding": True,
}]


class TestExpenditureCreation:
    def test_expenditure_created_with_initial_states(
            self, api, association_manager_headers):
        """PRD §3.6: "A new expenditure opens on two independent state axes at
        once: `approval_status` starts at `SUBMITTED` while
        `reconciliation_status` starts at `UNRECONCILED`, and the two move
        independently thereafter." and "Both chronological figures stay null
        until the expenditure reaches `APPROVED`" and PRD §2.5: "for a
        calendar-year association, the label is simply the calendar year of
        the date".

        Design: Corner/state_machines/expenditure_created_with_initial_states
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Init HOA",
                                  components=_ONE_COMPONENT)
        expenditure = validate_success(api.create_expenditure(
            {"association_id": ctx["association"]["id"],
             "component_id": ctx["components"][0]["id"],
             "amount_cents": 5000, "incurred_date": "2026-05-10",
             "kind": "UNPLANNED_REPAIR"}, association_manager_headers), 201)
        assert_expenditure(expenditure)
        assert expenditure["approval_status"] == "SUBMITTED"
        assert expenditure["reconciliation_status"] == "UNRECONCILED"
        assert expenditure["fiscal_year"] == 2026, (
            "2026-05-10 on a calendar-year association is FY2026; got "
            f"{expenditure['fiscal_year']}")
        assert expenditure["planned_chronological_cents"] is None
        assert expenditure["variance_chronological_cents"] is None

    def test_expenditure_create_without_adopted_study_rejected(
            self, api, association_manager_headers):
        """PRD §3.6: "Submission requires the association to have a current
        `ADOPTED` study, failing with `ERR_NO_ADOPTED_STUDY` otherwise".

        Design: Corner/validations/expenditure_create_without_adopted_study_rejected
        """
        association = onboard_association("CA", name="No Adopt HOA")
        study = create_draft_study(association["id"])
        component = add_component(study["id"], name="Roof")
        res = api.create_expenditure(
            {"association_id": association["id"],
             "component_id": component["id"], "amount_cents": 5000,
             "incurred_date": "2026-05-10", "kind": "UNPLANNED_REPAIR"},
            association_manager_headers)
        validate_error(res, ApiErrorId.ERR_NO_ADOPTED_STUDY)


class TestApprovalGates:
    def test_expenditure_approve_gated_by_component_currency(
            self, api, board_member_headers):
        """PRD §3.6: "It first re-verifies that the component still belongs
        to the association's current `ADOPTED` study and remains `ACTIVE` —
        a superseded study or a retired component since submission surfaces
        `ERR_COMPONENT_NOT_CURRENT`".

        Design: Difficulty/cross_entity_state_dependency/expenditure_approve_gated_by_component_currency
        """
        ctx = setup_adopted_study(state_code="CA", cash=1000000,
                                  association_name="Supersede HOA",
                                  components=_ONE_COMPONENT)
        component_x = ctx["components"][0]
        expenditure = create_expenditure(ctx["association"]["id"],
                                         component_x["id"], amount_cents=5000)

        # A new study for FY2027 is adopted, superseding the expenditure's
        # study and orphaning its component.
        s2 = create_draft_study(ctx["association"]["id"], fiscal_year=2027,
                                study_type="UPDATE_NO_VISIT")
        add_component(s2["id"], name="Roof", remaining_useful_life_years=1)
        plan = create_plan(s2["id"], "BASELINE")
        validate_success(api.submit_study(s2["id"],
                                          TEST_HEADERS_SPECIALIST))
        select_plan(plan["id"])
        validate_success(api.adopt_study(s2["id"], board_member_headers))

        res = api.approve_expenditure(expenditure["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_COMPONENT_NOT_CURRENT)

    def test_expenditure_create_with_component_of_other_study_rejected(
            self, api, association_manager_headers,
            reserve_specialist_headers):
        """PRD §3.6: "Submission requires the association to have a current
        `ADOPTED` study, failing with `ERR_NO_ADOPTED_STUDY` otherwise, and
        the component must belong to that study and still be `ACTIVE`,
        failing with `ERR_COMPONENT_NOT_CURRENT` otherwise."

        Design: Difficulty/cross_entity_state_dependency/expenditure_approve_gated_by_component_currency
        """
        ctx = setup_adopted_study(state_code="CA", cash=1000000,
                                  association_name="Foreign HOA",
                                  components=_ONE_COMPONENT)
        other_study = create_draft_study(ctx["association"]["id"],
                                         fiscal_year=2027,
                                         study_type="UPDATE_NO_VISIT")
        other_component = add_component(other_study["id"], name="Annex Roof")
        res = api.create_expenditure(
            {"association_id": ctx["association"]["id"],
             "component_id": other_component["id"], "amount_cents": 5000,
             "incurred_date": "2026-05-10", "kind": "UNPLANNED_REPAIR"},
            association_manager_headers)
        validate_error(res, ApiErrorId.ERR_COMPONENT_NOT_CURRENT)

    def test_expenditure_approve_cash_insufficient_rejected(
            self, api, board_member_headers):
        """PRD §3.6: "only then checks that the association's
        `reserve_cash_balance_cents` covers the `amount_cents`, failing with
        `ERR_CASH_INSUFFICIENT` when it does not."

        Design: Corner/validations/expenditure_approve_cash_insufficient_rejected
        """
        ctx = setup_adopted_study(state_code="NV", cash=1000,
                                  association_name="Broke HOA",
                                  components=_ONE_COMPONENT)
        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=999999)
        res = api.approve_expenditure(expenditure["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_CASH_INSUFFICIENT)


class TestApprovalPriorityPair:
    def test_approve_rejected_expenditure_state_beats_fiscal(
            self, api, board_member_headers):
        """PRD §2.8: "Every request is screened by an ordered validation
        cascade, and an earlier failure masks all later checks — the client
        always sees the first applicable rejection, not a later one." with
        target-state checks ("the expenditure `SUBMITTED` or `APPROVED`",
        `ERR_INVALID_STATE`) ordered before fiscal sufficiency ("the
        association's `reserve_cash_balance_cents` must cover the
        expenditure's `amount_cents`", `ERR_CASH_INSUFFICIENT`).

        Design: Difficulty/priority_pair_validation_conflict/approve_rejected_expenditure_state_beats_fiscal
        """
        ctx = setup_adopted_study(state_code="NV", cash=1000,
                                  association_name="Tiny Cash HOA",
                                  components=_ONE_COMPONENT)
        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=999999)
        validate_success(api.reject_expenditure(expenditure["id"],
                                                board_member_headers))
        res = api.approve_expenditure(expenditure["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_rejected_expenditure_state_fires_with_cash_available(
            self, api, board_member_headers):
        """PRD §2.8: "an earlier failure masks all later checks — the client
        always sees the first applicable rejection, not a later one." and PRD
        §3.6: "Board approval is the pivotal event." of a `SUBMITTED`
        expenditure; a `REJECTED` expenditure is outside the approval
        transition's source state.

        Design: Difficulty/priority_pair_validation_conflict/approve_rejected_expenditure_state_beats_fiscal
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Funded HOA",
                                  components=_ONE_COMPONENT)
        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=999999)
        validate_success(api.reject_expenditure(expenditure["id"],
                                                board_member_headers))
        res = api.approve_expenditure(expenditure["id"], board_member_headers)
        # Cash (2000000) covers the amount, so only the state check can fire.
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestReversal:
    def test_expenditure_reverse_from_submitted_rejected(
            self, api, board_member_headers, reserve_specialist_headers):
        """PRD §3.6: "An approved expenditure may also be reversed, but only
        inside its own fiscal year: the fiscal year of the logical clock's
        current date must equal the expenditure's `fiscal_year`, and once the
        calendar has moved past it the request fails with
        `ERR_REVERSAL_WINDOW_CLOSED`." and PRD §2.8: "The addressed entity
        sits in the state the action requires: the study `DRAFT` or
        `SUBMITTED` as the operation demands (surfacing `ERR_INVALID_STATE`
        or `ERR_STUDY_NOT_DRAFT`), the plan in a compatible status, the visit
        `SCHEDULED`, the expenditure `SUBMITTED` or `APPROVED`, the
        disclosure `PENDING`, exactly one `SELECTED` plan at adoption
        (`ERR_NO_PLAN_SELECTED`)."

        Design: Corner/state_machines/expenditure_reverse_from_submitted_rejected
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Reverse HOA",
                                  components=_ONE_COMPONENT)
        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=5000)
        res = api.reverse_expenditure(expenditure["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        association = get_association(ctx["association"]["id"])
        assert association["reserve_cash_balance_cents"] == 2000000, (
            "no side effects fired on a rejected reversal; cash drifted to "
            f"{association['reserve_cash_balance_cents']}")

    def test_expenditure_reverse_after_fiscal_year_rejected(
            self, api, board_member_headers, platform_admin_headers):
        """PRD §3.6: "An approved expenditure may also be reversed, but only
        inside its own fiscal year: the fiscal year of the logical clock's
        current date must equal the expenditure's `fiscal_year`, and once the
        calendar has moved past it the request fails with
        `ERR_REVERSAL_WINDOW_CLOSED`."

        Design: Corner/validations/expenditure_reverse_after_fiscal_year_rejected
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Window Close HOA",
                                  components=_ONE_COMPONENT)
        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=5000)
        validate_success(api.approve_expenditure(expenditure["id"],
                                                 board_member_headers))
        validate_success(api.set_clock("2027-02-01T00:00:00Z",
                                       platform_admin_headers))
        res = api.reverse_expenditure(expenditure["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_REVERSAL_WINDOW_CLOSED)


class TestApproveReverseConservation:
    def test_approve_then_reverse_conserves_reserve_cash(
            self, api, board_member_headers):
        """PRD §3.6: "Reversal sets `approval_status` to `REVERSED` and
        `reconciliation_status` to `NOT_APPLICABLE`, credits the
        `amount_cents` back onto the association's
        `reserve_cash_balance_cents`, and subtracts the amount from the
        component's `actual_expenditure_cents`."

        Design: Difficulty/compensating_invariant/approve_then_reverse_conserves_reserve_cash
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Conserve HOA",
                                  components=_ONE_COMPONENT)
        expenditure = create_expenditure(
            ctx["association"]["id"], ctx["components"][0]["id"],
            amount_cents=105000, kind="PLANNED_REPLACEMENT")

        validate_success(api.approve_expenditure(expenditure["id"],
                                                 board_member_headers))
        cash_mid = get_association(
            ctx["association"]["id"])["reserve_cash_balance_cents"]
        assert cash_mid == 1895000, (
            f"2000000 - 105000 = 1895000 after approval; got {cash_mid}")

        reversed_ex = validate_success(
            api.reverse_expenditure(expenditure["id"], board_member_headers),
            200)
        assert reversed_ex["approval_status"] == "REVERSED"
        assert reversed_ex["reconciliation_status"] == "NOT_APPLICABLE"

        cash_end = get_association(
            ctx["association"]["id"])["reserve_cash_balance_cents"]
        assert cash_end == 2000000, (
            "approve + reverse conserves reserve cash; expected 2000000, got "
            f"{cash_end}")

        component = list_components(ctx["study"]["id"])[0]
        assert component["actual_expenditure_cents"] == 0
        assert component["remaining_useful_life_years"] == 2, (
            "component life restored from the captured value; got "
            f"{component['remaining_useful_life_years']}")

    def test_planned_replacement_life_reset_and_restored(
            self, api, board_member_headers):
        """PRD §3.6: "for a `PLANNED_REPLACEMENT` the component's life is
        reset — its current `remaining_useful_life_years` is first captured
        into the expenditure's `component_rul_before_years`, then set to the
        full `useful_life_years`, with `last_replaced_fiscal_year` recorded as
        the expenditure's `fiscal_year`" and "For a `PLANNED_REPLACEMENT` it
        additionally restores the component's `remaining_useful_life_years`
        from the captured `component_rul_before_years` and recomputes
        `last_replaced_fiscal_year` as the greatest `fiscal_year` among the
        component's other `APPROVED` planned replacements, or null when none
        remain."

        Design: Difficulty/compensating_invariant/approve_then_reverse_conserves_reserve_cash
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="Life HOA",
                                  components=_ONE_COMPONENT)
        expenditure = create_expenditure(
            ctx["association"]["id"], ctx["components"][0]["id"],
            amount_cents=105000, kind="PLANNED_REPLACEMENT")

        approved = validate_success(
            api.approve_expenditure(expenditure["id"], board_member_headers),
            200)
        assert approved["component_rul_before_years"] == 2, (
            "captured at approval; got "
            f"{approved['component_rul_before_years']}")
        component = list_components(ctx["study"]["id"])[0]
        assert component["remaining_useful_life_years"] == 5, (
            "reset to the full useful life; got "
            f"{component['remaining_useful_life_years']}")
        assert component["last_replaced_fiscal_year"] == 2026
        assert component["actual_expenditure_cents"] == 105000

        validate_success(api.reverse_expenditure(expenditure["id"],
                                                 board_member_headers))
        restored = list_components(ctx["study"]["id"])[0]
        assert restored["remaining_useful_life_years"] == 2
        assert restored["last_replaced_fiscal_year"] is None, (
            "no other APPROVED planned replacements remain; got "
            f"{restored['last_replaced_fiscal_year']}")
        assert restored["actual_expenditure_cents"] == 0

        ex_after = get_expenditure(expenditure["id"])
        assert ex_after["approval_status"] == "REVERSED"
        assert ex_after["reconciliation_status"] == "NOT_APPLICABLE"
