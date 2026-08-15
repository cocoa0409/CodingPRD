"""Study submission: cadence and content gates, the in-progress rule, and
fiscal-window overlap/adjacency."""
from test_helpers import (
    ApiErrorId,
    assert_study,
    create_draft_study,
    create_plan,
    onboard_association,
    setup_adopted_study,
    setup_draft_study,
    setup_submitted_study,
    validate_error,
    validate_success,
)


class TestSubmitStateGate:
    def test_study_submit_from_submitted_rejected(
            self, api, reserve_specialist_headers):
        """PRD §3.5: "When the inventory and at least one plan are in place,
        the specialist submits the study for board review, moving it from
        `DRAFT` to `SUBMITTED` and advancing its `version`." and PRD §2.8:
        "The addressed entity sits in the state the action requires: the
        study `DRAFT` or `SUBMITTED` as the operation demands (surfacing
        `ERR_INVALID_STATE` or `ERR_STUDY_NOT_DRAFT`), the plan in a
        compatible status, the visit `SCHEDULED`, the expenditure `SUBMITTED`
        or `APPROVED`, the disclosure `PENDING`, exactly one `SELECTED` plan
        at adoption (`ERR_NO_PLAN_SELECTED`)."

        Design: Corner/state_machines/study_submit_from_submitted_rejected
        """
        ctx = setup_submitted_study(association_name="Twice HOA")
        assert ctx["study"]["status"] == "SUBMITTED"
        res = api.submit_study(ctx["study"]["id"], reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestSubmitContentMinimums:
    def test_study_submit_empty_components_rejected(
            self, api, reserve_specialist_headers):
        """PRD §3.5: "Second, the study must contain at least one component
        that is `ACTIVE` and included in funding — submitting an empty study
        is rejected with `ERR_STUDY_EMPTY`."

        Design: Corner/validations/study_submit_empty_components_rejected
        """
        ctx = setup_draft_study(state_code="CA", cash=500000, components=[],
                                with_visit=True, association_name="Empty HOA")
        create_plan(ctx["study"]["id"], "BASELINE")
        res = api.submit_study(ctx["study"]["id"], reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STUDY_EMPTY)

    def test_study_submit_without_plan_rejected(
            self, api, reserve_specialist_headers):
        """PRD §3.5: "Third, at least one funding plan in `DRAFT`,
        `RECOMMENDED`, or `SELECTED` status must exist, failing with
        `ERR_NO_FUNDING_PLAN` otherwise."

        Design: Corner/validations/study_submit_without_plan_rejected
        """
        ctx = setup_draft_study(state_code="CA", cash=500000,
                                with_visit=True,
                                association_name="Planless HOA",
                                components=[{
                                    "name": "Roof", "category": "ROOFING",
                                    "useful_life_years": 5,
                                    "remaining_useful_life_years": 2,
                                    "current_replacement_cost_cents": 100000,
                                    "is_included_in_funding": True,
                                }])
        res = api.submit_study(ctx["study"]["id"], reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_NO_FUNDING_PLAN)


class TestSubmitCadencePriority:
    def test_submit_cadence_beats_missing_plan(
            self, api, reserve_specialist_headers):
        """PRD §3.5: "Three gates guard submission, in this order of
        narrative priority. First, the statutory inspection cadence of §3.2
        must be satisfied for the study's `study_type`, failing with
        `ERR_SITE_VISIT_CADENCE`." and "Third, at least one funding plan in
        `DRAFT`, `RECOMMENDED`, or `SELECTED` status must exist, failing with
        `ERR_NO_FUNDING_PLAN` otherwise." and PRD §2.8: "an earlier failure
        masks all later checks — the client always sees the first applicable
        rejection, not a later one."

        Design: Difficulty/priority_pair_validation_conflict/submit_cadence_temporal_beats_constraint
        """
        ctx = setup_draft_study(state_code="CA", cash=500000,
                                with_visit=False,
                                association_name="No Visit HOA",
                                components=[{
                                    "name": "Roof", "category": "ROOFING",
                                    "useful_life_years": 5,
                                    "remaining_useful_life_years": 2,
                                    "current_replacement_cost_cents": 100000,
                                    "is_included_in_funding": True,
                                }])
        # No completed visit AND no funding plan: cadence (first gate) fires.
        res = api.submit_study(ctx["study"]["id"], reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_SITE_VISIT_CADENCE)

    def test_submit_cadence_beats_empty_study(
            self, api, reserve_specialist_headers):
        """PRD §3.5: "Three gates guard submission, in this order of
        narrative priority. First, the statutory inspection cadence of §3.2
        must be satisfied for the study's `study_type`, failing with
        `ERR_SITE_VISIT_CADENCE`. Second, the study must contain at least one
        component that is `ACTIVE` and included in funding — submitting an
        empty study is rejected with `ERR_STUDY_EMPTY`."

        Design: Difficulty/priority_pair_validation_conflict/submit_cadence_temporal_beats_constraint
        """
        ctx = setup_draft_study(state_code="CA", cash=500000, components=[],
                                with_visit=False,
                                association_name="Bare HOA")
        # No completed visit AND no components: cadence (first gate) fires.
        res = api.submit_study(ctx["study"]["id"], reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_SITE_VISIT_CADENCE)


class TestStudyCreationWindows:
    def test_study_create_while_draft_in_progress_rejected(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "An association may have at most one study in flight at
        a time: creating another while a `DRAFT` or `SUBMITTED` study exists
        fails with `ERR_STUDY_IN_PROGRESS`."

        Design: Corner/validations/study_create_while_draft_in_progress_rejected
        """
        association = onboard_association("CA", name="Busy HOA")
        create_draft_study(association["id"], fiscal_year=2026)
        res = api.create_study(
            {"association_id": association["id"], "fiscal_year": 2027,
             "study_type": "UPDATE_NO_VISIT", "inflation_rate": 0.03,
             "interest_rate": 0.02}, reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STUDY_IN_PROGRESS)

    def test_study_window_overlap_with_adopted_rejected(
            self, api, reserve_specialist_headers):
        """PRD §3.3: "The new study's fiscal window, derived per §2.5, must
        also not overlap the window of any `ADOPTED` study of the same
        association, on pain of `ERR_STUDY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/study_fiscal_window_overlap_adjacency
        """
        ctx = setup_adopted_study(state_code="CA", cash=1000000,
                                  association_name="Window HOA")
        # ADOPTED FY2026 study spans [2026-01-01, 2027-01-01).
        res = api.create_study(
            {"association_id": ctx["association"]["id"], "fiscal_year": 2026,
             "study_type": "UPDATE_NO_VISIT", "inflation_rate": 0.04,
             "interest_rate": 0.02}, reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STUDY_WINDOW_OVERLAP)

    def test_study_window_adjacent_to_adopted_accepted(
            self, api, reserve_specialist_headers):
        """PRD §2.5: "For a calendar-year association, the window runs from
        January 1 of the fiscal year (inclusive) to January 1 of the
        following year (exclusive)." and PRD §3.3: "The new study's fiscal
        window, derived per §2.5, must also not overlap the window of any
        `ADOPTED` study of the same association, on pain of
        `ERR_STUDY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/study_fiscal_window_overlap_adjacency
        """
        ctx = setup_adopted_study(state_code="CA", cash=1000000,
                                  association_name="Adjacent HOA")
        s2 = validate_success(api.create_study(
            {"association_id": ctx["association"]["id"], "fiscal_year": 2027,
             "study_type": "UPDATE_NO_VISIT", "inflation_rate": 0.04,
             "interest_rate": 0.02}, reserve_specialist_headers), 201)
        assert_study(s2)
        assert s2["status"] == "DRAFT"
        assert s2["window_start_date"] == "2027-01-01", (
            "the adjacent window starts exactly at the prior window's "
            f"exclusive end; got {s2['window_start_date']}")
        assert s2["window_end_date_exclusive"] == "2028-01-01"
